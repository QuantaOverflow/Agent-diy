"""Agent backend abstractions for Telegram integration."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from langchain_core.messages import HumanMessage

from agent_diy.core.agent import create_agent
from agent_diy.utils import StreamEvent, content_to_text, parse_stream_chunk

DEFAULT_ERROR_REPLY = "出错：处理消息时发生异常，请稍后重试。"
EMPTY_MESSAGES_REPLY = "出错：未获取到回复。"
logger = logging.getLogger(__name__)


class AgentBackend(Protocol):
    async def reply(self, user_id: int, text: str) -> str:
        """Generate a reply string for a user's message."""

    def stream_reply(self, user_id: int, text: str) -> AsyncIterator[StreamEvent]:
        """Stream reply events for a user's message."""

    def reset_session(self, user_id: int) -> None:
        """Reset conversation session for a user, clearing history."""


class InProcessAgentBackend:
    def __init__(self, agent: Any | None = None):
        self._agent = agent
        self._sessions: dict[int, int] = {}

    def _thread_id(self, user_id: int) -> str:
        return f"{user_id}-{self._sessions.get(user_id, 0)}"

    def _get_agent(self) -> Any:
        if self._agent is None:
            self._agent = create_agent()
        return self._agent

    async def reply(self, user_id: int, text: str) -> str:
        try:
            result = await asyncio.to_thread(
                self._get_agent().invoke,
                {"messages": [HumanMessage(content=text)]},
                config={
                    "configurable": {
                        "thread_id": self._thread_id(user_id),
                        "user_id": user_id,
                    }
                },
            )
            messages = result.get("messages", [])
            if not messages:
                return EMPTY_MESSAGES_REPLY
            return content_to_text(getattr(messages[-1], "content", messages[-1]))
        except Exception:  # noqa: BLE001
            return DEFAULT_ERROR_REPLY

    async def stream_reply(self, user_id: int, text: str) -> AsyncIterator[StreamEvent]:
        queue: asyncio.Queue[StreamEvent | Exception | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _worker() -> None:
            try:
                for chunk in self._get_agent().stream(
                    {"messages": [HumanMessage(content=text)]},
                    config={
                        "configurable": {
                            "thread_id": self._thread_id(user_id),
                            "user_id": user_id,
                        }
                    },
                    stream_mode="messages",
                    version="v2",
                ):
                    event = parse_stream_chunk(chunk)
                    if event is not None:
                        loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker_task = asyncio.create_task(asyncio.to_thread(_worker))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            await worker_task

    def reset_session(self, user_id: int) -> None:
        self._sessions[user_id] = self._sessions.get(user_id, 0) + 1


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

    @property
    def _stream_url(self) -> str:
        if self._remote_url.endswith("/v1/telegram/reply"):
            return self._remote_url[: -len("/v1/telegram/reply")] + "/v1/telegram/stream"
        return self._remote_url.rstrip("/") + "/stream"

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

    async def stream_reply(self, user_id: int, text: str) -> AsyncIterator[StreamEvent]:
        if not self._remote_url:
            yield StreamEvent("token", DEFAULT_ERROR_REPLY)
            return

        payload = {"user_id": user_id, "text": text}
        headers = {"X-Agent-Bridge-Token": self._bridge_token}

        try:
            logger.info("Remote stream request start: %s", self._stream_url)
            if self._client is not None:
                async with self._client.stream(
                    "POST",
                    self._stream_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        event_type = data.get("type")
                        content = data.get("content")
                        if event_type in {"token", "tool_call"} and isinstance(content, str):
                            yield StreamEvent(type=event_type, content=content)
            else:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        self._stream_url,
                        json=payload,
                        headers=headers,
                        timeout=self._timeout,
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line:
                                continue
                            data = json.loads(line)
                            event_type = data.get("type")
                            content = data.get("content")
                            if event_type in {"token", "tool_call"} and isinstance(content, str):
                                yield StreamEvent(type=event_type, content=content)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remote stream request failed, fallback to reply: %s", exc)

        full_text = await self.reply(user_id, text)
        yield StreamEvent("token", full_text)

    def reset_session(self, user_id: int) -> None:
        _ = user_id
