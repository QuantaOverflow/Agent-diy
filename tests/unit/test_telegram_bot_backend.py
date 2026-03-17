from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from agent_diy.agent_backend import InProcessAgentBackend, RemoteHttpAgentBackend
from agent_diy.telegram_bot import TelegramBot


def test_telegram_bot_handle_message_awaits_backend_reply():
    backend = AsyncMock()
    backend.reply.return_value = "backend reply"
    bot = TelegramBot(token="fake-token", backend=backend)

    reply = asyncio.run(bot.handle_message(user_id=123, text="hello"))

    assert reply == "backend reply"
    backend.reply.assert_awaited_once_with(user_id=123, text="hello")


def test_telegram_bot_defaults_to_inprocess_backend(monkeypatch):
    monkeypatch.delenv("AGENT_REMOTE_URL", raising=False)
    bot = TelegramBot(token="fake-token")
    assert isinstance(bot._backend, InProcessAgentBackend)


def test_telegram_bot_uses_remote_backend_when_configured(monkeypatch):
    monkeypatch.setenv("AGENT_REMOTE_URL", "https://local.test/v1/telegram/reply")
    monkeypatch.setenv("AGENT_BRIDGE_TOKEN", "secret")
    bot = TelegramBot(token="fake-token")
    assert isinstance(bot._backend, RemoteHttpAgentBackend)
