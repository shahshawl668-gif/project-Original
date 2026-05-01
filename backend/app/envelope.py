"""Standard API response envelope for all JSON endpoints."""
from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder


def ok(data: Any | None = None) -> dict[str, Any]:
    """Success payload (HTTP 2xx)."""
    return {
        "success": True,
        "data": jsonable_encoder(data) if data is not None else None,
        "error": None,
    }


def err_payload(detail: Any, code: str | None = None) -> dict[str, Any]:
    """Error object for JSON responses (usually combined with HTTPException by handlers)."""
    payload: dict[str, Any] = {"detail": detail}
    if code:
        payload["code"] = code
    return payload
