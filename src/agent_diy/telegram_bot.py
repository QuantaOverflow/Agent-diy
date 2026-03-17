"""Telegram bot adapter for agent_diy."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage
from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.request import HTTPXRequest
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agent_diy.core.agent import create_agent

logger = logging.getLogger(__name__)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        if parts:
            return "\n".join(parts)
    return str(content)


class TelegramBot:
    def __init__(self, token: str, agent: Any | None = None):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN 未配置")
        self._token = token
        self._agent = agent
        self._start_time = datetime.now(timezone.utc)

    def _get_agent(self) -> Any:
        if self._agent is None:
            self._agent = create_agent()
        return self._agent

    async def handle_message(self, user_id: int, text: str) -> str:
        try:
            result = self._get_agent().invoke(
                {"messages": [HumanMessage(content=text)]},
                config={"configurable": {"thread_id": str(user_id)}},
            )
            messages = result.get("messages", [])
            if not messages:
                return "出错：未获取到回复。"
            return _content_to_text(getattr(messages[-1], "content", messages[-1]))
        except Exception:  # noqa: BLE001
            return "出错：处理消息时发生异常，请稍后重试。"

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
