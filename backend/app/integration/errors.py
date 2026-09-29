"""
The integration API's error catalogue.

Every error a client can receive has a stable ``code``. Messages may be
reworded; codes never change within a major version, so clients branch on the
code and show the message.
"""
from __future__ import annotations

from typing import Any

#: code → (HTTP status, meaning). Published in the OpenAPI description.
CODES: dict[str, tuple[int, str]] = {
    "unauthorized": (401, "No API key, or not a valid one."),
    "credential_expired": (401, "The key has passed its expiry date. Rotate or issue a new one."),
    "credential_revoked": (401, "The key, or its service account, has been revoked or disabled."),
    "forbidden_scope": (403, "The key lacks the scope this endpoint needs."),
    "approval_required": (403, "This action needs a person's decision; a key cannot take it."),
    "company_required": (400, "The key covers several companies; name one with X-Company-Id."),
    "not_found": (404, "No such object — or not one this key's companies can see."),
    "invalid_request": (400, "The request is well-formed JSON but asks for something invalid."),
    "validation_error": (422, "The request does not match the schema."),
    "idempotency_key_required": (400, "This write must carry an Idempotency-Key header."),
    "idempotency_key_invalid": (400, "The Idempotency-Key header is empty or too long."),
    "idempotency_key_reused": (409, "The key was used for a different request."),
    "idempotency_in_progress": (409, "The first request with this key has not finished."),
    "conflict": (409, "The object is not in a state that allows this."),
    "payload_too_large": (413, "The request body is over the size limit."),
    "rate_limited": (429, "Too many requests for this key; wait for Retry-After seconds."),
    "internal_error": (500, "Something failed on our side; retry with the same Idempotency-Key."),
}


class ApiError(Exception):
    def __init__(self, code: str, message: str | None = None, *, status: int | None = None,
                 headers: dict[str, str] | None = None, detail: Any = None):
        super().__init__(message or CODES.get(code, (500, code))[1])
        self.code = code
        self.status = status or CODES.get(code, (500, ""))[0]
        self.message = message or CODES.get(code, (500, code))[1]
        self.headers = headers or {}
        self.detail = detail


def body(code: str, message: str, request_id: str | None, detail: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "detail": message, "request_id": request_id}
    if detail is not None:
        error["errors"] = detail
    return {"success": False, "data": None, "error": error}
