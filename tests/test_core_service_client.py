from __future__ import annotations

import httpx
import pytest

fastapi = pytest.importorskip("fastapi")
FastAPI = fastapi.FastAPI
Header = fastapi.Header
HTTPException = fastapi.HTTPException

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope, SendMessageAction
from mika_chat_core.core_service_client import (
    CoreServiceClient,
    CoreServiceRequestError,
    CoreServiceTimeoutError,
)


def _envelope() -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id="group:10001",
        platform="onebot_v11",
        protocol="onebot",
        message_id="msg-1",
        timestamp=1730000000.0,
        author=Author(id="42", nickname="alice", role="member"),
        content_parts=[ContentPart(kind="text", text="hello")],
        meta={"intent": "group", "group_id": "10001", "user_id": "42"},
    )


@pytest.mark.asyncio
async def test_core_service_client_parses_actions_from_http():
    app = FastAPI()

    @app.post("/v1/events")
    async def post_event():
        return {
            "schema_version": 1,
            "actions": [
                {
                    "type": "send_message",
                    "session_id": "group:10001",
                    "parts": [{"kind": "text", "text": "ok"}],
                    "reply_to": "msg-1",
                    "mentions": [],
                    "meta": {},
                }
            ],
        }

    transport = httpx.ASGITransport(app=app)
    client = CoreServiceClient(base_url="http://test", transport=transport)
    actions = await client.handle_event(_envelope())

    assert len(actions) == 1
    assert isinstance(actions[0], SendMessageAction)
    assert actions[0].parts[0].text == "ok"


@pytest.mark.asyncio
async def test_core_service_client_sends_bearer_token():
    app = FastAPI()

    @app.post("/v1/events")
    async def post_event(authorization: str | None = Header(default=None)):
        if authorization != "Bearer token-123":
            raise HTTPException(status_code=401, detail="invalid token")
        return {"schema_version": 1, "actions": [{"type": "noop", "reason": "accepted"}]}

    transport = httpx.ASGITransport(app=app)
    client = CoreServiceClient(
        base_url="http://test",
        token="token-123",
        transport=transport,
    )

    actions = await client.handle_event(_envelope())
    assert len(actions) == 1
    assert actions[0].type == "noop"


@pytest.mark.asyncio
async def test_core_service_client_wraps_request_errors():
    def _raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = httpx.MockTransport(_raise_connect_error)
    client = CoreServiceClient(base_url="http://test", transport=transport)

    with pytest.raises(CoreServiceRequestError, match="core service request failed"):
        await client.handle_event(_envelope())


@pytest.mark.asyncio
async def test_core_service_client_raises_timeout_error():
    def _raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(_raise_timeout)
    client = CoreServiceClient(base_url="http://test", transport=transport)

    with pytest.raises(CoreServiceTimeoutError, match="core service request failed"):
        await client.handle_event(_envelope())


@pytest.mark.asyncio
async def test_core_service_client_get_health():
    app = FastAPI()

    @app.get("/v1/health")
    async def get_health():
        return {"status": "healthy", "api_probe": {"status": "disabled"}, "runtime": {}, "version": "1"}

    transport = httpx.ASGITransport(app=app)
    client = CoreServiceClient(base_url="http://test", transport=transport)
    payload = await client.get_health()

    assert payload["status"] == "healthy"
    assert payload["version"] == "1"


def test_core_service_client_proactive_api_removed():
    assert hasattr(CoreServiceClient, "evaluate_proactive") is False
