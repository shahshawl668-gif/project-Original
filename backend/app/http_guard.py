"""
Response headers and a request-size ceiling for every route.

Both are pure ASGI so they cover the mounted integration API too, and the size
check happens before a byte of an oversized body is read into memory.

The API answers JSON and file downloads, never pages, so its content policy
allows nothing at all. The two exceptions are the interactive references
(``/docs``, ``/redoc``), which are pages; in production the main one is off and
only the integration API's published reference remains.
"""
from __future__ import annotations

import json

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings

_BASE = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
_DOC_PAGES = ("/docs", "/redoc", "/docs/oauth2-redirect")


class _TooLarge(HTTPException):
    """
    Raised from inside ``receive``. An HTTPException, because FastAPI re-raises
    those from body parsing (anything else becomes a generic 400), so the
    app's own handler answers 413 in the usual envelope.
    """

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=f"The request body is over {settings.max_request_mb} MB.")


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        page = path.endswith(_DOC_PAGES)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra = list(_BASE)
                if not page:
                    extra.append(_CSP)
                if settings.is_production:
                    extra.append(_HSTS)
                # Payroll data is never to sit in a shared or browser cache.
                if path.startswith("/api") and not page:
                    extra.append((b"cache-control", b"no-store"))
                headers.extend((k, v) for k, v in extra if k not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = settings.max_request_mb * 1024 * 1024
        for key, value in scope.get("headers", []):
            if key == b"content-length" and value.isdigit() and int(value) > limit:
                await _refuse(send)
                return
        seen = 0
        started = False

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, tracking_send)
        except _TooLarge:
            if not started:
                await _refuse(send)


async def _refuse(send: Send) -> None:
    body = json.dumps({"success": False, "data": None, "error": {
        "detail": f"The request body is over {settings.max_request_mb} MB.", "code": "payload_too_large"}}).encode()
    await send({"type": "http.response.start", "status": 413, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
