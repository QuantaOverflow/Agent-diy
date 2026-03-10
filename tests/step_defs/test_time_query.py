"""BDD steps for current time query behavior."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
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
def given_running_agent(context):
    model = ChatOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )
    context["agent"] = create_agent(model=model)


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
