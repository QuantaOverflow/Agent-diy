"""Unit tests for datetime injection into system prompt."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage

from agent_diy.core.agent import create_agent


def test_current_datetime_injected_in_system_prompt():
    captured = {}

    class CapturingFakeModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            captured["system"] = messages[0].content
            return AIMessage(content="ok")

    agent = create_agent(model=CapturingFakeModel())
    agent.invoke(
        {"messages": [HumanMessage(content="你好")]},
        config={"configurable": {"thread_id": "unit-datetime-inject"}},
    )

    assert "年" in captured["system"]
    assert "月" in captured["system"]
    assert "北京时间" in captured["system"]

    expected_hour = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H")
    assert expected_hour in captured["system"]
