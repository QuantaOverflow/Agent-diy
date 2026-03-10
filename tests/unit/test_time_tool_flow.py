"""Unit tests for time-tool execution path in the graph."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_diy.core.agent import create_agent


class ToolCallingFakeModel:
    """Fake model that requests the time tool and then formats the final reply."""

    def bind_tools(self, _tools):
        return self

    def invoke(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage) and "几点" in last.content:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_current_time",
                        "args": {},
                        "id": "call_time_1",
                        "type": "tool_call",
                    }
                ],
            )

        if isinstance(last, ToolMessage):
            return AIMessage(content=f"好的，{last.content}")

        return AIMessage(content="我不确定")


def test_time_query_uses_tool_path():
    agent = create_agent(model=ToolCallingFakeModel())
    result = agent.invoke(
        {"messages": [HumanMessage(content="现在几点了")]},
        config={"configurable": {"thread_id": "unit-time-tool"}},
    )

    content = result["messages"][-1].content
    assert isinstance(content, str)

    expected_hour = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H")
    assert expected_hour in content
    assert "北京时间" in content
