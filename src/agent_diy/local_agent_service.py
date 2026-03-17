"""Local HTTP service exposing agent replies for VPS Telegram gateway."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from agent_diy.agent_backend import AgentBackend, InProcessAgentBackend


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
    service_backend = backend or InProcessAgentBackend()
    app = FastAPI(title="Local Agent Service")

    @app.post("/v1/telegram/reply", response_model=ReplyResponse)
    async def telegram_reply(
        payload: ReplyRequest,
        x_agent_bridge_token: str | None = Header(default=None, alias="X-Agent-Bridge-Token"),
    ) -> ReplyResponse:
        if not token or x_agent_bridge_token != token:
            raise HTTPException(status_code=401, detail="unauthorized")
        reply = await service_backend.reply(user_id=payload.user_id, text=payload.text)
        return ReplyResponse(reply=reply)

    return app


def main() -> None:
    host = os.getenv("LOCAL_AGENT_HOST", "127.0.0.1")
    port = int(os.getenv("LOCAL_AGENT_PORT", "8787"))
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
