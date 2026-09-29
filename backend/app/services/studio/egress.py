"""
Outbound HTTP for connections and webhooks — and only to where it is allowed.

Three locks, all of which must open:

1. **The organisation's allowlist** (``studio_allowed_hosts``). An owner or
   manager names each host a connection or webhook may reach (``api.example-
   hrms.com``, or ``*.example-hrms.com``). Nothing else is reachable, whatever
   URL a connection is configured with.
2. **HTTPS**, except where local development explicitly allows otherwise.
3. **Public addresses only.** The host is resolved at connect time and every
   address must be globally routable: no loopback, private ranges, link-local
   (which includes the cloud metadata address 169.254.169.254), carrier-grade
   NAT, multicast or reserved space. The check happens inside the connection —
   the socket connects to the address that was checked, while TLS still
   verifies the certificate against the hostname — so a DNS answer that
   changes between check and connect (rebinding) cannot slip through.

Redirects are never followed: a 3xx is reported, not obeyed, because a
redirect is a way to send a request somewhere the allowlist never saw.
Responses are capped in size and time. ``STUDIO_ALLOW_PRIVATE_DESTINATIONS``
relaxes lock 3 and the HTTPS rule for local development and tests; it is
forced off in production.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpcore
from sqlalchemy.orm import Session

from app.config import settings

_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class EgressRefused(Exception):
    """A request that must not be made. ``code`` is shown to the person."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EgressFailed(Exception):
    """A request that was allowed but did not succeed (network, timeout, size)."""

    def __init__(self, code: str, message: str, transient: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int
    url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def json(self) -> Any:
        import json

        return json.loads(self.body.decode("utf-8"))


def address_allowed(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    # Link-local holds the cloud metadata service (169.254.169.254). It is
    # refused even where local development relaxes everything else.
    if addr.is_link_local:
        return False
    if settings.studio_allow_private_destinations:
        return not addr.is_multicast and not addr.is_unspecified
    if isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT:
        return False
    return addr.is_global and not addr.is_multicast


def resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressFailed("dns_failed", f"{host} could not be resolved.", transient=True) from exc
    addresses = sorted({info[4][0] for info in infos})
    blocked = [a for a in addresses if not address_allowed(a)]
    if blocked or not addresses:
        raise EgressRefused(
            "destination_not_public",
            f"{host} resolves to an address that is not on the public internet "
            f"({', '.join(blocked[:3])}). Requests to internal, private or metadata addresses are refused.",
        )
    return addresses


class GuardedBackend(httpcore.SyncBackend):
    """Connects only to addresses that passed the check, resolved here and now."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = resolve(host, port)
        last: Exception | None = None
        for address in addresses:
            try:
                return super().connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                           socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        raise last or httpcore.ConnectError(f"could not connect to {host}")


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
def normalise_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    if not host or " " in host or "/" in host or ":" in host.replace("*.", ""):
        raise ValueError("Give a host name only, like api.example.com or *.example.com — no scheme, path or port.")
    if host.startswith("*.") and host.count(".") < 2:
        raise ValueError("A wildcard must name a domain, like *.example.com.")
    return host


def host_matches(host: str, pattern: str) -> bool:
    host = host.lower().rstrip(".")
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and host != pattern[2:]
    return host == pattern


def allowed_hosts(db: Session, org_id: Any) -> list[str]:
    from app.models import StudioAllowedHost

    return [h.host for h in db.query(StudioAllowedHost).filter(StudioAllowedHost.org_id == org_id).all()]


def check_url(db: Session, org_id: Any, url: str) -> tuple[str, str, int, str]:
    """Validate a destination against the allowlist and scheme rules. Returns parts."""
    parts = urlsplit(url or "")
    if parts.scheme not in ("https", "http"):
        raise EgressRefused("invalid_url", "The address must start with https://.")
    if parts.scheme == "http" and not settings.studio_allow_private_destinations:
        raise EgressRefused("https_required", "Only https:// destinations are allowed.")
    if parts.username or parts.password:
        raise EgressRefused("credentials_in_url", "Put credentials in the connection's authentication, not in the URL.")
    host = (parts.hostname or "").lower()
    if not host:
        raise EgressRefused("invalid_url", "The address has no host.")
    patterns = allowed_hosts(db, org_id)
    if not any(host_matches(host, p) for p in patterns):
        raise EgressRefused(
            "destination_not_allowed",
            f"{host} is not on this organisation's list of allowed destinations. An owner or manager can "
            "add it under Studio → Connections → Allowed destinations.",
        )
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, host, port, parts.path or "/"


def request(
    db: Session,
    org_id: Any,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: bytes | None = None,
    timeout: float | None = None,
    max_bytes: int | None = None,
) -> Response:
    check_url(db, org_id, url)
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode({k: v for k, v in params.items() if v is not None})
    timeout = float(timeout or settings.studio_http_timeout_seconds)
    max_bytes = int(max_bytes or settings.studio_http_max_response_mb * 1024 * 1024)
    hdrs = [(b"User-Agent", b"PeopleOpsLab-Studio/1.0"), (b"Accept", b"application/json")]
    hdrs += [(k.encode(), str(v).encode()) for k, v in (headers or {}).items()]
    started = time.perf_counter()
    try:
        limits = {"connect": min(timeout, 10.0), "read": timeout, "write": timeout, "pool": timeout}
        with httpcore.ConnectionPool(network_backend=GuardedBackend(), max_connections=4, retries=0) as pool, \
                pool.stream(method.upper(), url, headers=hdrs, content=body,
                            extensions={"timeout": limits}) as resp:
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_stream():
                size += len(chunk)
                if size > max_bytes:
                    raise EgressFailed("response_too_large",
                                       f"The response was larger than {max_bytes // (1024 * 1024)} MB.",
                                       transient=False)
                chunks.append(chunk)
            status = resp.status
            out_headers = {k.decode().lower(): v.decode(errors="replace") for k, v in resp.headers}
    except (EgressRefused, EgressFailed):
        raise
    except httpcore.TimeoutException as exc:
        raise EgressFailed("timeout", f"No answer within {int(timeout)} s.") from exc
    except httpcore.ConnectError as exc:
        raise EgressFailed("connect_failed", "Could not connect to the destination.") from exc
    except httpcore.ProtocolError as exc:
        raise EgressFailed("protocol_error", "The destination's answer could not be read.") from exc
    except httpcore.UnsupportedProtocol as exc:
        raise EgressRefused("invalid_url", "That address cannot be requested.") from exc
    elapsed = int((time.perf_counter() - started) * 1000)
    if 300 <= status < 400:
        raise EgressFailed("redirect_not_followed",
                           f"The destination answered {status} (a redirect). Redirects are not followed; "
                           "configure the final address instead.", transient=False)
    return Response(status=status, headers=out_headers, body=b"".join(chunks), elapsed_ms=elapsed, url=url)
