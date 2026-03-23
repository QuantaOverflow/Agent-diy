from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from agent_diy.core.agent import create_agent
from agent_diy.reminder_store import ReminderStore
from agent_diy.tools.reminder import make_reminder_tools


class FakeModel:
    def bind_tools(self, _tools):
        return self

    def invoke(self, _messages):
        return AIMessage(content="llm rewrite should not happen")


def test_reminder_tool_result_is_returned_verbatim():
    store = ReminderStore()
    agent = create_agent(model=FakeModel(), extra_tools=make_reminder_tools(store))

    result = agent.invoke(
        {
            "messages": [
                ToolMessage(content="已为您设置一次性提醒（ID: 1）：2026-03-24 08:00（北京时间）执行：喝水", tool_call_id="tc1", name="set_reminder")
            ]
        },
        config={"configurable": {"thread_id": "t1", "user_id": 123}},
    )

    assert result["messages"][-1].content.startswith("已为您设置一次性提醒")
