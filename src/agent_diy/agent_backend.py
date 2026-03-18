"""Agent backend abstractions for Telegram integration."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx
from langchain_core.messages import HumanMessage

from agent_diy.core.agent import create_agent
from agent_diy.utils import content_to_text

DEFAULT_ERROR_REPLY = "出错：处理消息时发生异常，请稍后重试。"
EMPTY_MESSAGES_REPLY = "出错：未获取到回复。"


class AgentBackend(Protocol):
    async def reply(self, user_id: int, text: str) -> str:
        """Generate a reply string for a user's message."""


class InProcessAgentBackend:
    def __init__(self, agent: Any | None = None):
        self._agent = agent

    def _get_agent(self) -> Any:
        if self._agent is None:
            self._agent = create_agent()
        return self._agent

    async def reply(self, user_id: int, text: str) -> str:
        try:
            result = await asyncio.to_thread(
                self._get_agent().invoke,
                {"messages": [HumanMessage(content=text)]},
                config={"configurable": {"thread_id": str(user_id)}},
            )
            messages = result.get("messages", [])
            if not messages:
                return EMPTY_MESSAGES_REPLY
            return content_to_text(getattr(messages[-1], "content", messages[-1]))
        except Exception:  # noqa: BLE001
            return DEFAULT_ERROR_REPLY


class RemoteHttpAgentBackend:
    def __init__(
        self,
        remote_url: str,
        bridge_token: str,
        *,
        timeout: float = 55.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._remote_url = remote_url
        self._bridge_token = bridge_token
        self._timeout = timeout
        self._client = client

    async def reply(self, user_id: int, text: str) -> str:
        if not self._remote_url:
            return DEFAULT_ERROR_REPLY

        payload = {"user_id": user_id, "text": text}
        headers = {"X-Agent-Bridge-Token": self._bridge_token}

        try:
            if self._client is not None:
                response = await self._client.post(
                    self._remote_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self._remote_url,
                        json=payload,
                        headers=headers,
                        timeout=self._timeout,
                    )

            response.raise_for_status()
            data = response.json()
            reply = data.get("reply")
            if isinstance(reply, str) and reply:
                return reply
            return DEFAULT_ERROR_REPLY
        except Exception:  # noqa: BLE001
            return DEFAULT_ERROR_REPLY
