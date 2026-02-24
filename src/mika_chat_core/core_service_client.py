"""Async HTTP client for remote core-service mode."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .contracts import EventEnvelope, NoopAction, SendMessageAction

CoreAction = SendMessageAction | NoopAction


class CoreServiceError(RuntimeError):
    """Base exception for core service client failures."""


class CoreServiceTimeoutError(CoreServiceError):
    """Raised when core service request times out."""


class CoreServiceRequestError(CoreServiceError):
    """Raised for non-timeout transport errors when calling core service."""


def _parse_action(payload: dict[str, Any]) -> CoreAction:
    action_type = str(payload.get("type", "")).strip().lower()
    if action_type == "send_message":
        return SendMessageAction.from_dict(payload)
    if action_type == "noop":
        return NoopAction.from_dict(payload)
    raise ValueError(f"unsupported action type: {action_type}")


class CoreServiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 15.0,
        token: str = "",
        extra_headers: Optional[dict[str, str]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.token = str(token or "").strip()
        self.extra_headers = dict(extra_headers or {})
        self.transport = transport

        if not self.base_url:
            raise ValueError("core service base_url is required")
        if self.timeout_seconds <= 0:
            raise ValueError("core service timeout_seconds must be > 0")

    def _headers(self) -> dict[str, str]:
        headers = dict(self.extra_headers)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def handle_event(
        self,
        envelope: EventEnvelope,
        *,
        dispatch: bool = False,
    ) -> list[CoreAction]:
        url = f"{self.base_url}/v1/events"
        payload = {"envelope": envelope.to_dict(), "dispatch": bool(dispatch)}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.post(url, headers=self._headers(), json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError:
            raise
        except httpx.ReadTimeout as exc:
            raise CoreServiceTimeoutError(
                f"core service request failed: {type(exc).__name__}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise CoreServiceRequestError(
                f"core service request failed: {type(exc).__name__}: {exc}"
            ) from exc
        except ValueError as exc:
            raise CoreServiceRequestError(
                f"core service response is not valid JSON: {exc}"
            ) from exc

        raw_actions = list((data or {}).get("actions") or [])
        actions: list[CoreAction] = []
        for item in raw_actions:
            if not isinstance(item, dict):
                raise ValueError("remote core action payload must be object")
            actions.append(_parse_action(item))
        return actions

    async def get_health(self) -> dict[str, Any]:
        url = f"{self.base_url}/v1/health"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError:
            raise
        except httpx.ReadTimeout as exc:
            raise CoreServiceTimeoutError(
                f"core service request failed: {type(exc).__name__}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise CoreServiceRequestError(
                f"core service request failed: {type(exc).__name__}: {exc}"
            ) from exc
        except ValueError as exc:
            raise CoreServiceRequestError(
                f"core service response is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise CoreServiceRequestError("core service health payload must be object")
        return data
