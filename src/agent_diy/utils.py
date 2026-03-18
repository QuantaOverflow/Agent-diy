"""Shared utility helpers."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import Any


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
