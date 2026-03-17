from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from agent_diy.agent_backend import InProcessAgentBackend
from agent_diy.local_agent_service import create_app


def test_local_service_returns_reply_with_valid_token():
    backend = AsyncMock()
    backend.reply.return_value = "ok"
    app = create_app(bridge_token="secret", backend=backend)
    client = TestClient(app)

    response = client.post(
        "/v1/telegram/reply",
        json={"user_id": 1, "text": "hi"},
        headers={"X-Agent-Bridge-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "ok"}


def test_local_service_rejects_invalid_token():
    backend = AsyncMock()
    app = create_app(bridge_token="secret", backend=backend)
    client = TestClient(app)

    response = client.post(
        "/v1/telegram/reply",
        json={"user_id": 1, "text": "hi"},
        headers={"X-Agent-Bridge-Token": "wrong"},
    )

    assert response.status_code == 401


def test_local_service_validates_payload():
    backend = AsyncMock()
    app = create_app(bridge_token="secret", backend=backend)
    client = TestClient(app)

    response = client.post(
        "/v1/telegram/reply",
        json={"user_id": 1},
        headers={"X-Agent-Bridge-Token": "secret"},
    )

    assert response.status_code == 422


def test_local_service_uses_inprocess_backend():
    agent = MagicMock()
    agent.invoke.return_value = {"messages": [MagicMock(content="from-agent")]}
    backend = InProcessAgentBackend(agent=agent)
    app = create_app(bridge_token="secret", backend=backend)
    client = TestClient(app)

    response = client.post(
        "/v1/telegram/reply",
        json={"user_id": 9, "text": "hello"},
        headers={"X-Agent-Bridge-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "from-agent"}
    assert agent.invoke.call_count == 1
