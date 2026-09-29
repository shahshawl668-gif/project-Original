"""
Connections to other systems: authentication, testing, and fetching records.

The generic REST connector covers the common shape of an HRMS or attendance
API: an authenticated GET that returns a JSON list (or an object holding one),
paged by page number, offset or cursor, optionally filtered by a "modified
since" parameter. Provider-specific connectors are not built: none of the
providers' documented APIs or test tenants are available to this project, and
a connector written against guesses would fail in ways nobody could test.

Authentication methods, and what they may hold:

* ``none``, ``api_key_header`` (a header name + key), ``bearer`` (a token);
* ``basic`` — a username and password **issued for integration** (an API or
  technical user). Never a person's own account password; the form says so;
* ``oauth2_client_credentials`` — client id and secret, token fetched and
  cached;
* ``oauth2_authorization_code`` — a proper authorisation flow: the person is
  sent to the provider's consent page with ``state`` and a PKCE challenge,
  the code comes back to Studio, is exchanged once, and tokens are stored
  encrypted and refreshed when they expire. Nobody pastes a password.

Every secret is sealed with ``secrets.seal``; the API returns only masks.
Every request goes through ``egress.request`` — allowlist, HTTPS, public
addresses only, no redirects, bounded size and time.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets as pysecrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from sqlalchemy.orm import Session

from app.models import Entity, StudioConnection, StudioOAuthState, StudioStream, User
from app.services import audit
from app.services.studio import egress
from app.services.studio import secrets as vault
from app.services.studio.credentials import redact

AUTH_METHODS = {
    "none": {"config": [], "secrets": []},
    "api_key_header": {"config": ["header"], "secrets": ["api_key"]},
    "bearer": {"config": [], "secrets": ["token"]},
    "basic": {"config": ["username"], "secrets": ["password"]},
    "oauth2_client_credentials": {"config": ["token_url", "client_id", "scope"], "secrets": ["client_secret"]},
    "oauth2_authorization_code": {"config": ["authorize_url", "token_url", "client_id", "scope"],
                                  "secrets": ["client_secret"]},
}
SYSTEM_KINDS = ("hrms", "attendance", "finance", "payroll", "file_transfer", "other")
PROVIDERS = ("rest", "file")
OAUTH_STATE_MINUTES = 10


class ConnectionError_(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------
def add_allowed_host(db: Session, org_id: Any, actor: User, host: str, note: str | None):
    from app.models import StudioAllowedHost

    host = egress.normalise_host(host)
    existing = db.query(StudioAllowedHost).filter(StudioAllowedHost.org_id == org_id,
                                                  StudioAllowedHost.host == host).first()
    if existing:
        return existing
    row = StudioAllowedHost(org_id=org_id, host=host, note=note, added_by=actor.id)
    db.add(row)
    db.flush()
    audit.record(db, entity_id=None, org_id=org_id, user=actor, action="studio.destination.allowed",
                 object_type="studio_allowed_host", object_id=host,
                 summary=f"Allowed outbound requests to {host}" + (f" ({note})" if note else ""))
    return row


def remove_allowed_host(db: Session, org_id: Any, actor: User, host_id: str) -> None:
    from app.models import StudioAllowedHost

    try:
        row = db.get(StudioAllowedHost, uuid.UUID(host_id))
    except ValueError:
        row = None
    if row is None or row.org_id != org_id:
        raise ConnectionError_("Destination not found.", 404)
    db.delete(row)
    audit.record(db, entity_id=None, org_id=org_id, user=actor, action="studio.destination.removed",
                 object_type="studio_allowed_host", object_id=row.host,
                 summary=f"Removed {row.host} from allowed destinations")


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def _clean_config(method: str, config: dict[str, Any]) -> dict[str, Any]:
    allowed = set(AUTH_METHODS[method]["config"]) | {"extra_headers"}
    out = {k: v for k, v in (config or {}).items() if k in allowed and v not in (None, "")}
    headers = out.get("extra_headers") or {}
    if not isinstance(headers, dict) or any(k.lower() in ("authorization", "cookie") for k in headers):
        raise ConnectionError_("Extra headers are name → value, and may not carry Authorization or Cookie — "
                               "use the authentication method for credentials.")
    if headers:
        out["extra_headers"] = {str(k): str(v) for k, v in headers.items()}
    for key in ("token_url", "authorize_url"):
        if key in out and not str(out[key]).startswith("https://") and not egress.settings.studio_allow_private_destinations:
            raise ConnectionError_(f"{key} must be an https:// address.")
    missing = [k for k in AUTH_METHODS[method]["config"] if k != "scope" and k not in out]
    if missing:
        raise ConnectionError_(f"{method.replace('_', ' ')} needs: {', '.join(missing)}.")
    return out


def _seal(conn: StudioConnection, method: str, given: dict[str, Any], keep_existing: bool) -> None:
    wanted = AUTH_METHODS[method]["secrets"]
    current = vault.unseal(conn.secret_ciphertext) if (keep_existing and conn.secret_ciphertext) else {}
    for k in wanted:
        v = (given or {}).get(k)
        if v:
            current[k] = str(v)
    current = {k: v for k, v in current.items() if k in wanted or k in ("access_token", "refresh_token", "expires_at")}
    missing = [k for k in wanted if not current.get(k)]
    if missing:
        raise ConnectionError_(f"Enter the {', '.join(m.replace('_', ' ') for m in missing)}.")
    conn.secret_ciphertext = vault.seal(current) if current else None
    conn.secret_hint = vault.masks({k: current.get(k) for k in wanted})
    conn.secret_updated_at = _now() if given else conn.secret_updated_at


def create(db: Session, entity: Entity, actor: User, body: dict[str, Any]) -> StudioConnection:
    method = body.get("auth_method") or "none"
    if method not in AUTH_METHODS:
        raise ConnectionError_(f"Authentication must be one of: {', '.join(AUTH_METHODS)}.")
    provider = body.get("provider") or "rest"
    if provider not in PROVIDERS:
        raise ConnectionError_("Provider is rest (a REST API) or file (files uploaded through Studio).")
    kind = body.get("system_kind") or "hrms"
    if kind not in SYSTEM_KINDS:
        raise ConnectionError_(f"System kind must be one of: {', '.join(SYSTEM_KINDS)}.")
    env = body.get("environment") or "production"
    if env not in ("development", "test", "production"):
        raise ConnectionError_("Environment must be development, test or production.")
    name = (body.get("name") or "").strip()
    if len(name) < 2:
        raise ConnectionError_("Name the connection.")
    base_url = (body.get("base_url") or "").strip() or None
    if provider == "rest":
        if not base_url:
            raise ConnectionError_("A REST connection needs its base URL, e.g. https://api.example-hrms.com/v1.")
        egress.check_url(db, entity.org_id, base_url)
    conn = StudioConnection(
        org_id=entity.org_id, entity_id=entity.id, name=name, system_kind=kind, provider=provider,
        environment=env, base_url=base_url, auth_method=method,
        auth_config=_clean_config(method, body.get("auth_config") or {}), created_by=actor.id,
    )
    _seal(conn, method, body.get("secrets") or {}, keep_existing=False)
    db.add(conn)
    db.flush()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.connection.created",
                 object_type="studio_connection", object_id=str(conn.id),
                 summary=f"Created connection “{name}” ({provider}, {method}, {env})")
    return conn


def update(db: Session, entity: Entity, conn: StudioConnection, actor: User, body: dict[str, Any]) -> StudioConnection:
    changed = []
    if "name" in body and body["name"]:
        conn.name = str(body["name"]).strip()
        changed.append("name")
    if "base_url" in body and conn.provider == "rest":
        egress.check_url(db, entity.org_id, body["base_url"])
        conn.base_url = body["base_url"].strip()
        changed.append("base URL")
    method = body.get("auth_method") or conn.auth_method
    if method not in AUTH_METHODS:
        raise ConnectionError_("Unknown authentication method.")
    if "auth_config" in body or method != conn.auth_method:
        conn.auth_config = _clean_config(method, body.get("auth_config") or conn.auth_config)
        changed.append("authentication settings")
    if body.get("secrets") or method != conn.auth_method:
        _seal(conn, method, body.get("secrets") or {}, keep_existing=method == conn.auth_method)
        changed.append("credentials")
    conn.auth_method = method
    if body.get("status") in ("active", "disabled"):
        conn.status = body["status"]
        changed.append(f"status → {conn.status}")
    audit.record(db, entity_id=entity.id, user=actor, action="studio.connection.updated",
                 object_type="studio_connection", object_id=str(conn.id),
                 summary=f"Changed connection “{conn.name}”: {', '.join(changed) or 'nothing'}")
    return conn


def get(db: Session, entity: Entity, connection_id: str) -> StudioConnection:
    try:
        conn = db.get(StudioConnection, uuid.UUID(connection_id))
    except ValueError:
        conn = None
    if conn is None or conn.entity_id != entity.id:
        raise ConnectionError_("Connection not found.", 404)
    return conn


def describe(db: Session, conn: StudioConnection) -> dict[str, Any]:
    streams = db.query(StudioStream).filter(StudioStream.connection_id == conn.id).order_by(StudioStream.name).all()
    secret = vault.unseal(conn.secret_ciphertext) if conn.secret_ciphertext else {}
    return {
        "id": str(conn.id), "name": conn.name, "system_kind": conn.system_kind, "provider": conn.provider,
        "environment": conn.environment, "base_url": conn.base_url, "auth_method": conn.auth_method,
        "auth_config": conn.auth_config or {}, "secret_hint": conn.secret_hint or {},
        "oauth": ({"connected": bool(secret.get("access_token")),
                   "expires_at": secret.get("expires_at"), "has_refresh_token": bool(secret.get("refresh_token"))}
                  if conn.auth_method.startswith("oauth2") else None),
        "secret_updated_at": conn.secret_updated_at.isoformat() if conn.secret_updated_at else None,
        "direction": conn.direction, "status": conn.status, "health": conn.health,
        "last_tested_at": conn.last_tested_at.isoformat() if conn.last_tested_at else None,
        "last_test_result": conn.last_test_result,
        "last_success_at": conn.last_success_at.isoformat() if conn.last_success_at else None,
        "last_failure_at": conn.last_failure_at.isoformat() if conn.last_failure_at else None,
        "last_error": conn.last_error,
        "streams": [describe_stream(s) for s in streams],
    }


def describe_stream(s: StudioStream) -> dict[str, Any]:
    return {
        "id": str(s.id), "name": s.name, "object_type": s.object_type, "path": s.path,
        "records_path": s.records_path, "pagination": s.pagination or {}, "sync_mode": s.sync_mode,
        "watermark_field": s.watermark_field, "watermark_param": s.watermark_param,
        "checkpoint": s.checkpoint or {}, "import_options": s.import_options or {},
        "mapping_key": s.mapping_key, "mapping_version": s.mapping_version, "schedule": s.schedule or {},
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None, "max_attempts": s.max_attempts,
        "max_pages": s.max_pages, "enabled": s.enabled,
        "last_run_id": str(s.last_run_id) if s.last_run_id else None,
    }


def health(conn: StudioConnection, ok: bool, error: str | None = None) -> None:
    if ok:
        conn.health = "healthy"
        conn.last_success_at = _now()
        conn.last_error = None
    else:
        conn.health = "failing"
        conn.last_failure_at = _now()
        conn.last_error = redact(error or "")[:1000]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _token_request(db: Session, conn: StudioConnection, form: dict[str, str], secret: dict[str, Any]) -> dict[str, Any]:
    cfg = conn.auth_config or {}
    basic = base64.b64encode(f"{cfg['client_id']}:{secret.get('client_secret', '')}".encode()).decode()
    resp = egress.request(db, conn.org_id, "POST", cfg["token_url"], body=urlencode(form).encode(),
                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                   "Authorization": f"Basic {basic}"})
    if resp.status >= 400:
        raise egress.EgressFailed("token_refused", f"The token endpoint answered {resp.status}.", transient=resp.status >= 500)
    try:
        token = resp.json()
    except ValueError as exc:
        raise egress.EgressFailed("token_unreadable", "The token endpoint's answer was not JSON.", transient=False) from exc
    if not token.get("access_token"):
        raise egress.EgressFailed("token_missing", "The token endpoint returned no access_token.", transient=False)
    return token


def _store_token(conn: StudioConnection, secret: dict[str, Any], token: dict[str, Any]) -> None:
    secret["access_token"] = token["access_token"]
    if token.get("refresh_token"):
        secret["refresh_token"] = token["refresh_token"]
    expires = int(token.get("expires_in") or 3600)
    secret["expires_at"] = (_now() + timedelta(seconds=max(expires - 60, 30))).isoformat()
    conn.secret_ciphertext = vault.seal(secret)


def auth_headers(db: Session, conn: StudioConnection) -> dict[str, str]:
    """Headers that authenticate a request. May fetch or refresh a token."""
    cfg = conn.auth_config or {}
    secret = vault.unseal(conn.secret_ciphertext) if conn.secret_ciphertext else {}
    headers = dict(cfg.get("extra_headers") or {})
    method = conn.auth_method
    if method == "api_key_header":
        headers[cfg["header"]] = secret["api_key"]
    elif method == "bearer":
        headers["Authorization"] = f"Bearer {secret['token']}"
    elif method == "basic":
        headers["Authorization"] = "Basic " + base64.b64encode(f"{cfg['username']}:{secret['password']}".encode()).decode()
    elif method.startswith("oauth2"):
        expires = secret.get("expires_at")
        fresh = secret.get("access_token") and expires and datetime.fromisoformat(expires) > _now()
        if not fresh:
            if method == "oauth2_client_credentials":
                form = {"grant_type": "client_credentials"}
                if cfg.get("scope"):
                    form["scope"] = cfg["scope"]
                _store_token(conn, secret, _token_request(db, conn, form, secret))
            elif secret.get("refresh_token"):
                _store_token(conn, secret, _token_request(
                    db, conn, {"grant_type": "refresh_token", "refresh_token": secret["refresh_token"]}, secret))
            else:
                raise egress.EgressRefused("not_authorised",
                                           "This connection has not been authorised yet. Press “Connect” to sign in "
                                           "at the provider.")
        headers["Authorization"] = f"Bearer {secret['access_token']}"
    return headers


def oauth_start(db: Session, conn: StudioConnection, actor: User, redirect_uri: str) -> str:
    if conn.auth_method != "oauth2_authorization_code":
        raise ConnectionError_("This connection does not use the authorisation-code flow.")
    cfg = conn.auth_config or {}
    state = pysecrets.token_urlsafe(32)
    verifier = pysecrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    db.add(StudioOAuthState(
        state_hash=hashlib.sha256(state.encode()).hexdigest(), connection_id=conn.id, user_id=actor.id,
        verifier_ciphertext=vault.seal({"verifier": verifier}), redirect_uri=redirect_uri,
        expires_at=_now() + timedelta(minutes=OAUTH_STATE_MINUTES),
    ))
    params = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect_uri,
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    if cfg.get("scope"):
        params["scope"] = cfg["scope"]
    url = cfg["authorize_url"]
    return url + ("&" if urlsplit(url).query else "?") + urlencode(params)


def oauth_finish(db: Session, entity: Entity, actor: User, state: str, code: str) -> StudioConnection:
    row = (db.query(StudioOAuthState)
           .filter(StudioOAuthState.state_hash == hashlib.sha256((state or "").encode()).hexdigest()).first())
    if row is None or row.used_at is not None or _aware(row.expires_at) < _now():
        raise ConnectionError_("This authorisation link has expired or was already used. Start again.", 400)
    if row.user_id != actor.id:
        raise ConnectionError_("This authorisation was started by someone else.", 403)
    conn = db.get(StudioConnection, row.connection_id)
    if conn is None or conn.entity_id != entity.id:
        raise ConnectionError_("Connection not found.", 404)
    row.used_at = _now()
    verifier = vault.unseal(row.verifier_ciphertext)["verifier"]
    secret = vault.unseal(conn.secret_ciphertext) if conn.secret_ciphertext else {}
    token = _token_request(db, conn, {"grant_type": "authorization_code", "code": code,
                                      "redirect_uri": row.redirect_uri, "code_verifier": verifier}, secret)
    _store_token(conn, secret, token)
    conn.secret_updated_at = _now()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.connection.authorised",
                 object_type="studio_connection", object_id=str(conn.id),
                 summary=f"Authorised connection “{conn.name}” at the provider")
    return conn


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def _url(conn: StudioConnection, path: str) -> str:
    if path.startswith("https://") or path.startswith("http://"):
        return path
    return conn.base_url.rstrip("/") + "/" + path.lstrip("/")


def _records_in(body: Any, records_path: str) -> list[Any]:
    from app.services.studio.mapping import dig

    value = dig(body, records_path) if records_path else body
    if not isinstance(value, list):
        raise egress.EgressFailed("unexpected_shape",
                                  f"Expected a list of records at '{records_path or '(the whole response)'}'.",
                                  transient=False)
    return value


def get_json(db: Session, conn: StudioConnection, path: str, params: dict[str, Any] | None = None) -> Any:
    resp = egress.request(db, conn.org_id, "GET", _url(conn, path), headers=auth_headers(db, conn), params=params)
    if resp.status == 401 or resp.status == 403:
        raise egress.EgressFailed("auth_refused", f"The system refused the credentials ({resp.status}).", transient=False)
    if resp.status == 429 or resp.status >= 500:
        raise egress.EgressFailed("provider_unavailable", f"The system answered {resp.status} (temporarily unavailable).", transient=True)
    if resp.status >= 400:
        raise egress.EgressFailed("request_refused", f"The system answered {resp.status}.", transient=False)
    try:
        return resp.json()
    except ValueError as exc:
        raise egress.EgressFailed("not_json", "The answer was not JSON.", transient=False) from exc


def fetch(db: Session, conn: StudioConnection, stream: StudioStream, *, watermark: str | None = None,
          sample: int | None = None) -> tuple[list[Any], dict[str, Any]]:
    """Every record the stream yields now, page by page. Returns (records, meta)."""
    pg = stream.pagination or {"type": "none"}
    kind = pg.get("type", "none")
    size = int(pg.get("size") or 500)
    params: dict[str, Any] = dict(pg.get("params") or {})
    if stream.sync_mode == "incremental" and watermark and stream.watermark_param:
        params[stream.watermark_param] = watermark
    records: list[Any] = []
    pages = 0
    page = int(pg.get("start", 1))
    offset = 0
    cursor = None
    while True:
        p = dict(params)
        if kind == "page":
            p[pg.get("param", "page")] = page
            p[pg.get("size_param", "page_size")] = size
        elif kind == "offset":
            p[pg.get("param", "offset")] = offset
            p[pg.get("size_param", "limit")] = size
        elif kind == "cursor" and cursor:
            p[pg.get("param", "cursor")] = cursor
        body = get_json(db, conn, stream.path, p)
        batch = _records_in(body, stream.records_path)
        records.extend(batch)
        pages += 1
        if sample is not None:
            # A sample is the first page: enough to see the fields, without
            # walking a whole system to test a connection.
            return records[:sample], {"pages": pages, "truncated": True}
        if kind == "none" or not batch:
            break
        if kind == "page":
            if len(batch) < size:
                break
            page += 1
        elif kind == "offset":
            if len(batch) < size:
                break
            offset += len(batch)
        elif kind == "cursor":
            from app.services.studio.mapping import dig

            cursor = dig(body, pg.get("cursor_path", "next_cursor"))
            if not cursor:
                break
        if pages >= stream.max_pages:
            raise egress.EgressFailed("too_many_pages", f"Stopped after {pages} pages (the stream's limit).",
                                      transient=False)
    return records, {"pages": pages, "truncated": False}


def test(db: Session, conn: StudioConnection, stream: StudioStream | None = None) -> dict[str, Any]:
    """Authenticate and read one page (of a stream, or the base URL). Records health."""
    started = _now()
    try:
        if conn.provider != "rest":
            result = {"ok": True, "message": "File connections have nothing to reach; upload a file to test the mapping."}
        elif stream is not None:
            records, _ = fetch(db, conn, stream, sample=5)
            keys = sorted({k for r in records if isinstance(r, dict) for k in r})[:50]
            result = {"ok": True, "message": f"Read {len(records)} sample record(s) from {stream.path}.",
                      "sample_fields": keys, "sample_count": len(records)}
        else:
            get_json(db, conn, "")
            result = {"ok": True, "message": f"Reached {conn.base_url} and authenticated."}
        health(conn, True)
    except (egress.EgressRefused, egress.EgressFailed) as exc:
        result = {"ok": False, "code": exc.code, "message": exc.message}
        health(conn, False, exc.message)
    except vault.SecretStoreUnavailable as exc:
        result = {"ok": False, "code": "secret_store_unavailable", "message": str(exc)}
        health(conn, False, str(exc))
    result["tested_at"] = started.isoformat()
    conn.last_tested_at = started
    conn.last_test_result = json.loads(json.dumps(result, default=str))
    return result
