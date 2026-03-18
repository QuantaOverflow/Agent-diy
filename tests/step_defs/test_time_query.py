"""BDD steps for current time query behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.core.agent import create_agent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "time_query.feature"))


@pytest.fixture
def context():
    return {
        "agent": None,
        "thread_id": "time-query-thread",
        "response": "",
    }


@given("a running agent")
def given_running_agent(context, qwen_model):
    context["agent"] = create_agent(model=qwen_model)


@when(parsers.parse('I ask "{text}"'))
def when_i_ask(context, text):
    result = context["agent"].invoke(
        {"messages": [HumanMessage(content=text)]},
        config={"configurable": {"thread_id": context["thread_id"]}},
    )
    content = result["messages"][-1].content
    context["response"] = content if isinstance(content, str) else str(content)


@then("the response should contain the current hour in China timezone")
def then_contains_current_china_hour(context):
    expected_hour = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H")
    assert expected_hour in context["response"]


@then("the response should not contain a time string")
def then_response_should_not_contain_time(context):
    import re

    # 不应包含 HH:MM 格式的时间
    assert not re.search(r"\d{2}:\d{2}", context["response"])


class _CapturingModel:
    def __init__(self, capture: dict):
        self._capture = capture

    def bind_tools(self, _tools):
        return self

    def invoke(self, messages):
        self._capture["captured_system"] = messages[0].content
        return AIMessage(content="ok")


@given("an agent with a capturing model")
def given_agent_with_capturing_model(context):
    context["captured_system"] = ""
    context["agent"] = create_agent(model=_CapturingModel(context))


@when("the agent processes a message")
def when_agent_processes_message(context):
    context["agent"].invoke(
        {"messages": [HumanMessage(content="你好")]},
        config={"configurable": {"thread_id": "unit-datetime-inject"}},
    )


@then("the system prompt should contain the current Beijing datetime")
def then_system_prompt_contains_beijing_datetime(context):
    system = context["captured_system"]
    assert "年" in system
    assert "月" in system
    assert "北京时间" in system
    expected_hour = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H")
    assert expected_hour in system
