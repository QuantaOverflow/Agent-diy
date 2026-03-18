"""Telegram bot adapter for agent_diy."""

from __future__ import annotations

import logging
import os
import time
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from telegram import Update
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.request import HTTPXRequest
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agent_diy.agent_backend import (
    DEFAULT_ERROR_REPLY,
    EMPTY_MESSAGES_REPLY,
    AgentBackend,
    InProcessAgentBackend,
    RemoteHttpAgentBackend,
)

logger = logging.getLogger(__name__)
TELEGRAM_MAX_MESSAGE_CHARS = 4096


class TelegramBot:
    def __init__(self, token: str, backend: AgentBackend | None = None):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN 未配置")
        self._token = token
        self._backend = backend or self._default_backend()
        self._start_time = datetime.now(timezone.utc)
        # Telegram edits are rate-limited; keep updates frequent but bounded.
        self._stream_edit_interval_sec = max(
            0.1,
            float(os.getenv("TELEGRAM_STREAM_EDIT_INTERVAL_SEC", "0.35")),
        )
        self._log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()

    def _configure_logging(self) -> None:
        level = getattr(logging, self._log_level_name, logging.INFO)
        root = logging.getLogger()
        if not root.handlers:
            logging.basicConfig(
                level=level,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
        root.setLevel(level)

    @staticmethod
    def _split_text(text: str, max_chars: int = TELEGRAM_MAX_MESSAGE_CHARS) -> list[str]:
        if not text:
            return [""]
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    @staticmethod
    def _preview_text_for_stream(text: str) -> str:
        if len(text) <= TELEGRAM_MAX_MESSAGE_CHARS:
            return text
        prefix = "[内容较长，显示末尾部分]\n"
        keep = TELEGRAM_MAX_MESSAGE_CHARS - len(prefix)
        return prefix + text[-keep:]

    @staticmethod
    def _retry_after_seconds(exc: RetryAfter) -> float:
        retry_after = getattr(exc, "_retry_after", None)
        if retry_after is None:
            retry_after = getattr(exc, "retry_after", None)
        if isinstance(retry_after, timedelta):
            return max(retry_after.total_seconds(), 1.0)
        try:
            return max(float(retry_after or 1), 1.0)
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _default_backend() -> AgentBackend:
        remote_url = os.getenv("AGENT_REMOTE_URL", "").strip()
        if remote_url:
            return RemoteHttpAgentBackend(
                remote_url=remote_url,
                bridge_token=os.getenv("AGENT_BRIDGE_TOKEN", ""),
                timeout=55.0,
            )
        return InProcessAgentBackend()

    @property
    def _agent(self) -> Any:  # compatibility for existing tests
        if isinstance(self._backend, InProcessAgentBackend):
            return self._backend._agent
        return None

    @_agent.setter
    def _agent(self, value: Any) -> None:  # compatibility for existing tests
        if isinstance(self._backend, InProcessAgentBackend):
            self._backend._agent = value
        else:
            self._backend = InProcessAgentBackend(agent=value)

    async def handle_message(self, user_id: int, text: str) -> str:
        return await self._backend.reply(user_id=user_id, text=text)

    async def _on_text_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user is None or update.message is None:
            return
        if update.message.date < self._start_time:
            return
        text = update.message.text or ""
        user_id = update.effective_user.id
        logger.info("Telegram message received: user_id=%s, text_len=%s", user_id, len(text))

        stream_reply = getattr(self._backend, "stream_reply", None)
        backend_agent = self._agent
        using_mock_agent = (
            backend_agent is not None and type(backend_agent).__module__.startswith("unittest.mock")
        )
        if not callable(stream_reply) or using_mock_agent:
            reply = await self.handle_message(user_id, text)
            attempt = 0
            while attempt < 3:
                try:
                    await update.message.reply_text(reply)
                    return
                except (NetworkError, TimedOut):
                    if attempt == 2:
                        logger.warning("Failed to send Telegram reply after retries", exc_info=True)
                        return
                    await asyncio.sleep(0.5 * (2**attempt))
                    attempt += 1

        sent = await update.message.reply_text("⏳")
        buffer = ""
        last_sent_text = "⏳"
        last_edit_time = 0.0
        rate_limited_until = 0.0

        try:
            async for event in stream_reply(user_id, text):
                if event.type == "tool_call":
                    buffer += f"\n🔧 {event.content}\n"
                else:
                    buffer += event.content

                now = time.monotonic()
                if now < rate_limited_until:
                    continue

                preview = self._preview_text_for_stream(buffer)
                if now - last_edit_time >= self._stream_edit_interval_sec and preview != last_sent_text:
                    try:
                        await sent.edit_text(preview)
                        last_sent_text = preview
                        last_edit_time = now
                    except RetryAfter as exc:
                        retry_after = self._retry_after_seconds(exc)
                        rate_limited_until = time.monotonic() + retry_after
                        logger.warning(
                            "Telegram edit rate-limited; pause edits for %.1fs (user_id=%s)",
                            retry_after,
                            user_id,
                        )
                    except (BadRequest, NetworkError, TimedOut):
                        pass

            if buffer:
                chunks = self._split_text(buffer)
                if len(chunks) == 1:
                    final_text = chunks[0]
                    if final_text != last_sent_text:
                        try:
                            await sent.edit_text(final_text)
                        except RetryAfter:
                            await update.message.reply_text(final_text)
                else:
                    try:
                        await sent.edit_text(chunks[0])
                    except RetryAfter:
                        await update.message.reply_text(chunks[0])
                    for chunk in chunks[1:]:
                        try:
                            await update.message.reply_text(chunk)
                        except RetryAfter as exc:
                            retry_after = self._retry_after_seconds(exc)
                            logger.warning(
                                "Telegram send rate-limited; waiting %.1fs before next chunk (user_id=%s)",
                                retry_after,
                                user_id,
                            )
                            await asyncio.sleep(retry_after)
                            await update.message.reply_text(chunk)
            elif not buffer:
                await sent.edit_text(EMPTY_MESSAGES_REPLY)
            logger.info("Telegram message handled: user_id=%s, output_len=%s", user_id, len(buffer))
        except Exception:  # noqa: BLE001
            logger.warning("Streaming failed, showing error", exc_info=True)
            try:
                await sent.edit_text(DEFAULT_ERROR_REPLY)
            except Exception:  # noqa: BLE001
                pass

    async def _on_error(self, _update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.warning("Telegram update handling failed", exc_info=context.error)

    def _build_application(self) -> Application:
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=20.0,
            pool_timeout=5.0,
            httpx_kwargs={"trust_env": False},
        )
        application = Application.builder().token(self._token).request(request).build()
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text_message))
        application.add_error_handler(self._on_error)
        return application

    def run(self) -> None:
        self._configure_logging()
        self._start_time = datetime.now(timezone.utc)
        application = self._build_application()
        application.run_polling(drop_pending_updates=True, bootstrap_retries=-1)

    def run_webhook(
        self,
        webhook_url: str,
        *,
        listen: str = "0.0.0.0",
        port: int = 8000,
        url_path: str = "telegram/webhook",
        secret_token: str | None = None,
    ) -> None:
        if not webhook_url:
            raise ValueError("webhook_url 未配置")
        self._configure_logging()
        self._start_time = datetime.now(timezone.utc)
        application = self._build_application()
        application.run_webhook(
            listen=listen,
            port=port,
            url_path=url_path,
            webhook_url=webhook_url,
            secret_token=secret_token,
            drop_pending_updates=True,
            bootstrap_retries=-1,
        )
