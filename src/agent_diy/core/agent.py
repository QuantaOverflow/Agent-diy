"""Multi-turn conversational agent built with LangGraph."""

from __future__ import annotations

import os
import time
import zlib
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from agent_diy.core.model import create_dashscope_model
from agent_diy.prompts.system import build_system_prompt
from agent_diy.tools import (
    get_astrology_email,
    get_current_weather,
    get_sunrise_sunset,
    get_weather_forecast,
    web_search,
)
from agent_diy.utils import run_async_sync

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
_FINANCIAL_NEWS_TOOLS: list[Any] | None = None
_FINANCIAL_NEWS_LOAD_ERROR: str | None = None
_GRAPH = None


def _load_financial_news_tools() -> list[Any]:
    """Load MCP financial-news tools with graceful fallback."""
    global _FINANCIAL_NEWS_TOOLS, _FINANCIAL_NEWS_LOAD_ERROR

    if _FINANCIAL_NEWS_TOOLS is not None:
        return _FINANCIAL_NEWS_TOOLS

    try:
        from agent_diy.mcp.client import get_financial_news_tools
    except Exception:  # noqa: BLE001 - keep agent available when MCP deps are absent
        _FINANCIAL_NEWS_TOOLS = []
        return _FINANCIAL_NEWS_TOOLS

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            _FINANCIAL_NEWS_TOOLS = run_async_sync(get_financial_news_tools())
            _FINANCIAL_NEWS_LOAD_ERROR = None
            return _FINANCIAL_NEWS_TOOLS
        except Exception as exc:  # noqa: BLE001 - keep agent available
            _FINANCIAL_NEWS_LOAD_ERROR = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(0.2)

    if os.getenv("FINANCIAL_NEWS_REQUIRED") == "1":
        raise RuntimeError(
            f"Failed to load financial news MCP tools: {_FINANCIAL_NEWS_LOAD_ERROR}"
        )

    return []


def _default_model() -> Any:
    """Build the default model from env vars (DashScope/Qwen)."""
    try:
        return create_dashscope_model()
    except ValueError:
        return init_chat_model(DEFAULT_MODEL)


def _build_graph(
    model: Any = None,
    extra_tools: list[Any] | None = None,
):
    """Build the StateGraph (uncompiled)."""
    if model is None:
        model = _default_model()
    financial_tools = _load_financial_news_tools()
    tools = [
        get_current_weather,
        get_weather_forecast,
        get_sunrise_sunset,
        web_search,
        get_astrology_email,
        *financial_tools,
        *(extra_tools or []),
    ]
    model_with_tools = model.bind_tools(tools)
    system_prompt = build_system_prompt(
        financial_tools_available=bool(financial_tools),
        reminder_tools_available=bool(extra_tools),
    )
    reminder_tool_names = {"set_reminder", "list_reminders", "cancel_reminder"}

    def llm_call(state: MessagesState, config: RunnableConfig):
        messages = state["messages"]
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, ToolMessage) and last_message.name in reminder_tool_names:
                # Reminder tools should be rendered verbatim to avoid LLM paraphrase distortion.
                return {"messages": [AIMessage(content=last_message.content)]}

        configurable = config.get("configurable", {})
        raw_user_id = configurable.get("user_id")
        thread_id = configurable.get("thread_id", "")
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            user_id = zlib.crc32(str(thread_id).encode("utf-8")) if thread_id else 0
        now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日 %H:%M")
        system = SystemMessage(
            content=system_prompt + f"\n当前北京时间：{now}\n当前用户ID：{user_id}"
        )
        response = model_with_tools.invoke([system] + messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    builder = StateGraph(MessagesState)
    builder.add_node("llm_call", llm_call)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "llm_call")
    builder.add_conditional_edges("llm_call", tools_condition)
    builder.add_edge("tools", "llm_call")
    return builder


def create_agent(
    model: Any = None,
    model_name: str = DEFAULT_MODEL,
    extra_tools: list[Any] | None = None,
):
    """Create a conversational agent graph with checkpointed memory."""
    if model is None and not os.getenv("DASHSCOPE_API_KEY"):
        model = init_chat_model(model_name)
    builder = _build_graph(model, extra_tools=extra_tools)
    checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)


def _get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph().compile()
    return _GRAPH


def __getattr__(name):
    if name == "graph":
        return _get_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Export an explicit symbol for LangGraph loader (`module.__dict__["graph"]`).
# Use factory form to keep lazy initialization behavior.
graph = _get_graph
