from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.security import decode_token


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Attach user_id / tenant_id to request.state for observability (JWT best-effort, no DB hit)."""

    async def dispatch(self, request: Request, call_next):
        request.state.user_id = None
        request.state.tenant_id = None
        auth = request.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            try:
                token = auth.split(" ", 1)[1].strip()
                payload = decode_token(token)
                if payload.get("type") == "access":
                    sub = payload.get("sub")
                    if sub:
                        request.state.user_id = sub
                        request.state.tenant_id = sub
            except Exception:
                pass
        return await call_next(request)
