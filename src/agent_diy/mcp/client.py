"""MCP client loader for financial-news tools."""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from agent_diy.utils import run_async_sync

_CLIENT: MultiServerMCPClient | None = None
_TOOLS = None
_CACHE_LOCK = threading.RLock()


def _invalidate_cached_client() -> None:
    """Invalidate cached MCP client/tools so next call can reconnect."""
    global _CLIENT, _TOOLS
    with _CACHE_LOCK:
        _TOOLS = None
        _CLIENT = None


async def _invoke_tool_with_recovery(tool_name: str, kwargs: dict[str, Any]) -> Any:
    """Invoke MCP tool and recover once by reloading client/tools on failure."""
    tools = await get_financial_news_tools()
    tool = next((t for t in tools if getattr(t, "name", None) == tool_name), None)
    if tool is None:
        raise RuntimeError(f"MCP tool not found: {tool_name}")

    try:
        return await tool.ainvoke(kwargs)
    except Exception:  # noqa: BLE001 - retry once with fresh MCP client/session
        _invalidate_cached_client()
        tools = await get_financial_news_tools()
        tool = next((t for t in tools if getattr(t, "name", None) == tool_name), None)
        if tool is None:
            raise RuntimeError(f"MCP tool not found after reload: {tool_name}")
        return await tool.ainvoke(kwargs)


def _attach_sync_func(tool: Any) -> Any:
    """LangGraph ToolNode sync path requires tool.func for StructuredTool."""
    if getattr(tool, "func", None) is not None:
        return tool
    if getattr(tool, "coroutine", None) is None:
        return tool

    tool_name = getattr(tool, "name", "")

    def _sync_func(**kwargs: Any):
        output = run_async_sync(_invoke_tool_with_recovery(tool_name, kwargs))
        # MCP adapters use response_format=content_and_artifact.
        return output, output

    tool.func = _sync_func
    return tool


async def get_financial_news_tools():
    """Load MCP tools using the supported MultiServerMCPClient API."""
    global _CLIENT, _TOOLS

    with _CACHE_LOCK:
        if _TOOLS is not None:
            return _TOOLS

        if _CLIENT is None:
            _CLIENT = MultiServerMCPClient(
                {
                    "financial_news": {
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["-m", "agent_diy.mcp.financial_news_server"],
                        "env": dict(os.environ),
                    }
                }
            )

    loaded_tools = await _CLIENT.get_tools()
    wrapped = [_attach_sync_func(tool) for tool in loaded_tools]
    with _CACHE_LOCK:
        _TOOLS = wrapped
        return _TOOLS
