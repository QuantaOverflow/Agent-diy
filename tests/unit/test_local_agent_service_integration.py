from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_diy.local_agent_service import create_app


@pytest.mark.integration
def test_local_service_http_chain_sets_relative_reminder():
    app = create_app(bridge_token="secret")

    with TestClient(app) as client:
        response = client.post(
            "/v1/telegram/reply",
            json={"user_id": 100, "text": "一分钟后提醒我喝水"},
            headers={"X-Agent-Bridge-Token": "secret"},
        )

    assert response.status_code == 200
    text = response.json()["reply"]
    assert "提醒" in text

    store = app.state.reminder_store
    assert store is not None
    reminders = store.list(100)
    assert len(reminders) >= 1
    assert reminders[-1].schedule_type == "once"
