"""Local HTTP service exposing agent replies for VPS Telegram gateway."""

from __future__ import annotations

import os
import json
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from telegram import Bot

from agent_diy.agent_backend import AgentBackend, InProcessAgentBackend
from agent_diy.core.agent import create_agent
from agent_diy.reminder_scheduler import ReminderScheduler
from agent_diy.reminder_store import ReminderStore
from agent_diy.tools.reminder import make_reminder_tools


class ReplyRequest(BaseModel):
    user_id: int
    text: str


class ReplyResponse(BaseModel):
    reply: str


def create_app(
    *,
    bridge_token: str | None = None,
    backend: AgentBackend | None = None,
) -> FastAPI:
    token = bridge_token if bridge_token is not None else os.getenv("AGENT_BRIDGE_TOKEN", "")
    reminder_store: ReminderStore | None = None
    reminder_scheduler: ReminderScheduler | None = None

    if backend is None:
        reminder_store = ReminderStore()
        reminder_tools = make_reminder_tools(reminder_store)
        service_backend = InProcessAgentBackend(agent=create_agent(extra_tools=reminder_tools))
    else:
        service_backend = backend
    app = FastAPI(title="Local Agent Service")
    app.state.reminder_store = reminder_store
    app.state.reminder_scheduler = None

    if reminder_store is not None:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        bot = Bot(token=bot_token) if bot_token else None

        async def _send_proactive_message(user_id: int, text: str) -> None:
            if bot is None:
                return
            await bot.send_message(chat_id=user_id, text=text)

        reminder_scheduler = ReminderScheduler(
            store=reminder_store,
            backend=service_backend,
            send_callback=_send_proactive_message,
        )
        app.state.reminder_scheduler = reminder_scheduler

        @app.on_event("startup")
        async def _startup() -> None:
            reminder_scheduler.start()

        @app.on_event("shutdown")
        async def _shutdown() -> None:
            reminder_scheduler.shutdown()

    @app.post("/v1/telegram/reply", response_model=ReplyResponse)
    async def telegram_reply(
        payload: ReplyRequest,
        x_agent_bridge_token: str | None = Header(default=None, alias="X-Agent-Bridge-Token"),
    ) -> ReplyResponse:
        if not token or x_agent_bridge_token != token:
            raise HTTPException(status_code=401, detail="unauthorized")
        reply = await service_backend.reply(user_id=payload.user_id, text=payload.text)
        return ReplyResponse(reply=reply)

    @app.post("/v1/telegram/stream")
    async def telegram_stream(
        payload: ReplyRequest,
        x_agent_bridge_token: str | None = Header(default=None, alias="X-Agent-Bridge-Token"),
    ) -> StreamingResponse:
        if not token or x_agent_bridge_token != token:
            raise HTTPException(status_code=401, detail="unauthorized")

        async def _event_lines() -> AsyncIterator[str]:
            async for event in service_backend.stream_reply(user_id=payload.user_id, text=payload.text):
                yield json.dumps({"type": event.type, "content": event.content}, ensure_ascii=False) + "\n"

        return StreamingResponse(_event_lines(), media_type="application/x-ndjson")

    return app


def main() -> None:
    host = os.getenv("LOCAL_AGENT_HOST", "127.0.0.1")
    port = int(os.getenv("LOCAL_AGENT_PORT", "8787"))
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
