"""tests 专用 httpx 轻量 stub（仅在缺少真实 httpx 依赖时由 conftest 注入）。

目标：让单测在“无外部依赖的精简环境”中仍可 import 并可被 patch/mock。

注意：这是测试 stub，不应被生产路径导入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class TimeoutException(Exception):
    pass


class ConnectError(Exception):
    pass


class NetworkError(Exception):
    pass


class HTTPStatusError(Exception):
    def __init__(self, message: str, *, request: Any = None, response: Any = None):
        super().__init__(message)
        self.request = request
        self.response = response


@dataclass
class Timeout:
    timeout: Optional[float] = None
    connect: Optional[float] = None

    def __init__(self, timeout: Optional[float] = None, *, connect: Optional[float] = None, **_kwargs: Any):
        self.timeout = timeout
        self.connect = connect


@dataclass
class Limits:
    max_connections: Optional[int] = None
    max_keepalive_connections: Optional[int] = None

    def __init__(
        self,
        max_connections: Optional[int] = None,
        max_keepalive_connections: Optional[int] = None,
        **_kwargs: Any,
    ):
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections


class Response:
    def __init__(
        self,
        status_code: int = 200,
        *,
        json_data: Any = None,
        text: str = "",
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPStatusError("HTTP error", request=None, response=self)


class AsyncClient:
    """极简 AsyncClient：默认不发真实网络请求。

    单测通常会 patch `httpx.AsyncClient` 或 `client.post`，因此这里仅保证接口存在。
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self._closed = False
        self.args = args
        self.kwargs = kwargs

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def aclose(self) -> None:
        self._closed = True

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def post(self, *args: Any, **kwargs: Any) -> Response:
        # 默认返回空响应，避免未 patch 时直接崩溃。
        return Response(status_code=200, json_data={})

    async def get(self, *args: Any, **kwargs: Any) -> Response:
        """GET 请求 stub"""
        return Response(status_code=200, json_data={})

    async def put(self, *args: Any, **kwargs: Any) -> Response:
        """PUT 请求 stub"""
        return Response(status_code=200, json_data={})

    async def delete(self, *args: Any, **kwargs: Any) -> Response:
        """DELETE 请求 stub"""
        return Response(status_code=200, json_data={})

    async def patch(self, *args: Any, **kwargs: Any) -> Response:
        """PATCH 请求 stub"""
        return Response(status_code=200, json_data={})

    async def head(self, *args: Any, **kwargs: Any) -> Response:
        """HEAD 请求 stub"""
        return Response(status_code=200, json_data={})

    async def options(self, *args: Any, **kwargs: Any) -> Response:
        """OPTIONS 请求 stub"""
        return Response(status_code=200, json_data={})

