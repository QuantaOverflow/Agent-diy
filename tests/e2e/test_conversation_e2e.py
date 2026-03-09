"""E2E tests against a real DashScope/Qwen model."""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from agent_diy.core.agent import create_agent

pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY not set",
)


@pytest.mark.e2e
def test_real_model_remembers_name():
    model = ChatOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )
    agent = create_agent(model=model)
    config = {"configurable": {"thread_id": "e2e-1"}}

    agent.invoke({"messages": [HumanMessage(content="Hi, my name is Alice")]}, config=config)
    result = agent.invoke({"messages": [HumanMessage(content="What is my name?")]}, config=config)

    content = result["messages"][-1].content
    if not isinstance(content, str):
        content = str(content)

    assert "Alice" in content
