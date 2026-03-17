"""Telegram bot adapter for agent_diy."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.request import HTTPXRequest
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agent_diy.agent_backend import AgentBackend, InProcessAgentBackend, RemoteHttpAgentBackend

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, backend: AgentBackend | None = None):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN 未配置")
        self._token = token
        self._backend = backend or self._default_backend()
        self._start_time = datetime.now(timezone.utc)

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
        reply = await self.handle_message(update.effective_user.id, text)
        for attempt in range(3):
            try:
                await update.message.reply_text(reply)
                return
            except (NetworkError, TimedOut):
                if attempt == 2:
                    logger.warning("Failed to send Telegram reply after retries", exc_info=True)
                    return
                await asyncio.sleep(0.5 * (2**attempt))

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
