"""Shared utility helpers."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class StreamEvent:
    type: Literal["token", "tool_call"]
    content: str


def parse_stream_chunk(chunk) -> StreamEvent | None:
    """Parse LangGraph ``stream(stream_mode="messages", version="v2")`` chunks.

    ``chunk`` can be:
    - tuple(message_chunk, metadata_dict)
    - dict with ``type == "messages"`` and ``data == (message_chunk, metadata_dict)``

    Only events from ``langgraph_node == "llm_call"`` are handled.
    """
    if isinstance(chunk, tuple) and len(chunk) == 2:
        msg, metadata = chunk
    elif isinstance(chunk, dict) and chunk.get("type") == "messages":
        msg, metadata = chunk["data"]
    else:
        return None

    if metadata.get("langgraph_node", "") != "llm_call":
        return None

    if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
        for tc in msg.tool_call_chunks:
            name = tc.get("name")
            if name:
                return StreamEvent(type="tool_call", content=name)
        return None

    if msg.content:
        return StreamEvent(type="token", content=msg.content)

    return None


def run_async_sync(coro: Awaitable[Any]) -> Any:
    """Run async code from sync contexts (with nested-loop safety)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Any = None
    error: Exception | None = None

    def _runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            error = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


def content_to_text(content: Any) -> str:
    """Normalize model/message content to plain text."""
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
