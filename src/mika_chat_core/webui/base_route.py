"""Shared API response helpers for WebUI routes."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel
from fastapi.responses import JSONResponse


class ApiResponse(BaseModel):
    """Unified API envelope."""

    status: str = "ok"
    message: str = "ok"
    data: Any = None


class BaseRouteHelper:
    """Route response helper."""

    @staticmethod
    def ok(data: Any = None, message: str = "ok") -> Dict[str, Any]:
        return ApiResponse(status="ok", message=message, data=data).model_dump()

    @staticmethod
    def error(message: str, data: Any = None) -> Dict[str, Any]:
        return ApiResponse(status="error", message=message, data=data).model_dump()

    @staticmethod
    def error_response(
        message: str,
        *,
        status_code: int = 400,
        data: Any = None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=BaseRouteHelper.error(message=message, data=data),
        )


__all__ = ["ApiResponse", "BaseRouteHelper"]
