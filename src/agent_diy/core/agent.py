"""Multi-turn conversational agent built with LangGraph."""

from __future__ import annotations

import os
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
    get_current_weather,
    get_sunrise_sunset,
    get_weather_forecast,
    web_search,
)

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
SYSTEM_PROMPT = (
    "你是一个有用的助手。"
    "当用户询问天气且未明确城市时，默认使用北京作为城市参数调用天气工具。"
    "当用户询问今晚、明天、后天或未来天气时，优先调用天气预报工具。"
    "当用户询问当前天气时，调用实时天气工具。"
    "当用户询问日出、日落时间时，调用日出日落工具。"
    "当用户询问湿度、风力、体感温度等常用指标时，调用实时天气工具并返回具体数值。"
    "当用户询问今天/今晚的日出日落时，日出日落工具的 date 参数留空或使用当天日期。"
    "若任一工具返回服务失败或不可用，直接说明失败并建议稍后重试，不要给出估算值。"
    "当用户询问实时/最新信息（新闻、价格、近期事件等）或明确要求‘搜/查’时，调用网络搜索工具。"
    "当用户提问包含年份、日期、节假日安排等可能随时间变化的信息时，优先调用网络搜索工具。"
    "用户明确使用‘搜/查/检索’时，必须调用网络搜索工具，即使问题属于天气等已有专用工具。"
    "闲聊和稳定通识问题不触发网络搜索。"
    "天气、日出日落等已有专用工具的问题优先使用专用工具，除非用户明确要求搜索。"
    "调用网络搜索后必须以搜索结果为准，不得用训练知识质疑或否定搜索结果；"
    "搜索结果代表互联网实时信息，与训练知识冲突时搜索结果优先。"
    "当搜索结果中提到某事件'将于'某日期发生，请对比当前日期判断该日期是否已过去；"
    "若已过去，则该事件已经发生，应据此作答，不得以'尚未发布'等措辞回复。"
)


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
    tools = [
        get_current_weather,
        get_weather_forecast,
        get_sunrise_sunset,
        web_search,
    ]
    model_with_tools = model.bind_tools(tools)

    def llm_call(state: MessagesState):
        now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日 %H:%M")
        system = SystemMessage(content=SYSTEM_PROMPT + f"\n当前北京时间：{now}")
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
