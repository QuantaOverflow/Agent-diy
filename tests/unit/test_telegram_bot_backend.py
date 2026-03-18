from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

from telegram.error import RetryAfter

from agent_diy.agent_backend import InProcessAgentBackend, RemoteHttpAgentBackend
from agent_diy.telegram_bot import TELEGRAM_MAX_MESSAGE_CHARS, TelegramBot


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


def test_split_text_handles_boundary_lengths():
    exact = "a" * TELEGRAM_MAX_MESSAGE_CHARS
    over = "b" * (TELEGRAM_MAX_MESSAGE_CHARS + 1)

    assert TelegramBot._split_text(exact) == [exact]
    chunks = TelegramBot._split_text(over)
    assert len(chunks) == 2
    assert len(chunks[0]) == TELEGRAM_MAX_MESSAGE_CHARS
    assert len(chunks[1]) == 1


def test_preview_text_for_stream_handles_boundary_lengths():
    exact = "x" * TELEGRAM_MAX_MESSAGE_CHARS
    over = "y" * (TELEGRAM_MAX_MESSAGE_CHARS + 1)

    assert TelegramBot._preview_text_for_stream(exact) == exact
    preview = TelegramBot._preview_text_for_stream(over)
    assert len(preview) <= TELEGRAM_MAX_MESSAGE_CHARS
    assert preview.startswith("[内容较长，显示末尾部分]\n")


def test_retry_after_seconds_supports_timedelta():
    exc = RetryAfter(timedelta(seconds=2))
    assert TelegramBot._retry_after_seconds(exc) == 2.0
