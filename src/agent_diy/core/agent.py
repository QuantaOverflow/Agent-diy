"""Multi-turn conversational agent built with LangGraph."""

from __future__ import annotations

import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


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

    def llm_call(state: MessagesState):
        response = model.invoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("llm_call", llm_call)
    builder.add_edge(START, "llm_call")
    builder.add_edge("llm_call", END)
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
