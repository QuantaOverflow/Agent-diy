"""Multi-turn conversational agent built with LangGraph."""

from __future__ import annotations

import asyncio
import os
import time
import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from agent_diy.tools import (
    get_astrology_email,
    get_current_weather,
    get_sunrise_sunset,
    get_weather_forecast,
    web_search,
)

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
_FINANCIAL_NEWS_TOOLS: list[Any] | None = None
_FINANCIAL_NEWS_LOAD_ERROR: str | None = None

BASE_SYSTEM_PROMPT = (
    "你是一个有用的助手。"
    "当用户询问天气且未明确城市时，默认使用北京作为城市参数调用天气工具。"
    "当用户询问今晚、明天、后天或未来天气时，优先调用天气预报工具。"
    "当用户询问当前天气时，调用实时天气工具。"
    "当用户询问日出、日落时间时，调用日出日落工具。"
    "当用户询问湿度、风力、体感温度等常用指标时，调用实时天气工具并返回具体数值。"
    "当用户询问星座运势、占星解读、星座格言、行星动态、宇宙能量等话题时，调用星座邮件工具获取最新邮件内容，用中文进行分析总结，不要逐段翻译原文，要提炼核心洞见、行星能量要点和今日格言。"
    "回复星座运势时，以今日北京日期为准称呼日期，邮件日期与北京日期的差异是系统内部处理细节，不要向用户披露。"
    "当用户询问指定日期（如昨日、前天、具体日期）的星座运势时，将该日期转换为 YYYY-MM-DD 格式后作为 date 参数传入星座邮件工具。"
    "与占星无关的问题不要调用星座邮件工具。"
    "对于与占星无关的问题，回复中也不要主动提及星座邮件工具或占星能力。"
    "用户问题与占星无关时，回复中避免出现这些词：星座、运势、行星、宇宙、占星、格言、木星、土星、水星、金星、火星、能量。"
    "对于暂不支持的请求，简短说明限制并请用户提供可处理任务，不要罗列全部工具能力。"
    "当用户询问今天/今晚的日出日落时，日出日落工具的 date 参数留空或使用当天日期。"
    "若任一工具返回服务失败或不可用，直接说明失败并建议稍后重试，不要给出估算值。"
    '当星座邮件工具返回某日期无邮件时，回复中必须明确包含"未找到"这三个字。'
    "当用户询问实时/最新信息（新闻、价格、近期事件等）或明确要求’搜/查’时，调用网络搜索工具。"
    "价格类问题（黄金、外汇、大宗商品、加密货币、股指等）必须调用网络搜索工具，禁止用训练知识直接回答价格。"
    "当用户提问包含年份、日期、节假日安排等可能随时间变化的信息时，优先调用网络搜索工具。"
    "闲聊和稳定通识问题不触发网络搜索。"
    "天气、日出日落等已有专用工具的问题默认使用专用工具；"
    "但当用户问题中包含’搜/查/检索’等关键词时，必须调用网络搜索工具，不得调用天气等专用工具。"
    "示例：’帮我搜一下北京的天气’ → 必须调用 web_search，不得调用 get_current_weather。"
    "调用网络搜索后必须以搜索结果为准，不得用训练知识质疑或否定搜索结果；"
    "搜索结果代表互联网实时信息，与训练知识冲突时搜索结果优先。"
    "当搜索结果中提到某事件'将于'某日期发生，请对比当前日期判断该日期是否已过去；"
    "若已过去，则该事件已经发生，应据此作答，不得以'尚未发布'等措辞回复。"
)

FINANCIAL_NEWS_PROMPT = (
    "当用户询问A股个股新闻、股票行情、市场热点时，调用金融新闻工具。"
    "当用户询问具体股票时，同时调用 stock_news 和 semantic_search 以获取更全面的信息。"
    "金融新闻工具不可用时，说明暂时无法获取最新市场数据，不要给出估算。"
    "通识性金融问题（如‘股票是什么’）不触发金融新闻工具。"
    "对于A股个股新闻、股票行情、市场热点，优先金融新闻工具，不调用网络搜索工具，除非用户明确要求‘搜/查/检索’。"
)

FINANCIAL_NEWS_UNAVAILABLE_PROMPT = (
    "当前金融新闻工具不可用。用户询问A股个股新闻、股票行情、市场热点时，"
    "直接说明暂时无法获取最新市场数据，不要调用不存在的金融新闻工具。"
)


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

    async def _load_async() -> list[Any]:
        return await get_financial_news_tools()

    def _load_once() -> list[Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_load_async())

        loaded_tools: list[Any] = []
        load_error: Exception | None = None

        def _runner() -> None:
            nonlocal loaded_tools, load_error
            try:
                loaded_tools = asyncio.run(_load_async())
            except Exception as exc:  # noqa: BLE001 - MCP service may be unavailable
                load_error = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if load_error is not None:
            raise load_error
        return loaded_tools

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            _FINANCIAL_NEWS_TOOLS = _load_once()
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


def _default_model() -> ChatOpenAI:
    """Build the default model from env vars (DashScope/Qwen)."""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if api_key:
        return ChatOpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
        )
    return init_chat_model(DEFAULT_MODEL)


def _build_graph(model: Any = None):
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
    ]
    model_with_tools = model.bind_tools(tools)
    system_prompt = BASE_SYSTEM_PROMPT + (
        FINANCIAL_NEWS_PROMPT if financial_tools else FINANCIAL_NEWS_UNAVAILABLE_PROMPT
    )

    def llm_call(state: MessagesState):
        now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日 %H:%M")
        system = SystemMessage(content=system_prompt + f"\n当前北京时间：{now}")
        response = model_with_tools.invoke(
            [system] + state["messages"]
        )
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    builder = StateGraph(MessagesState)
    builder.add_node("llm_call", llm_call)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "llm_call")
    builder.add_conditional_edges("llm_call", tools_condition)
    builder.add_edge("tools", "llm_call")
    return builder


def create_agent(model: Any = None, model_name: str = DEFAULT_MODEL):
    """Create a conversational agent graph with checkpointed memory."""
    if model is None and not os.getenv("DASHSCOPE_API_KEY"):
        model = init_chat_model(model_name)
    builder = _build_graph(model)
    checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)


# Module-level graph for `langgraph dev` (no checkpointer — server manages it)
graph = _build_graph().compile()
