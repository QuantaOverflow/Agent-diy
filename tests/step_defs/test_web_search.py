"""BDD steps for web search behavior."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.core.agent import create_agent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "web_search.feature"))


@pytest.fixture
def web_search_context():
    return {
        "agent": None,
        "thread_id": "web-search-thread",
        "result": None,
    }


def _require_base_env():
    if not os.getenv("DASHSCOPE_API_KEY"):
        pytest.skip("DASHSCOPE_API_KEY not set")
    if not os.getenv("ALIYUN_ACCESS_KEY_ID"):
        pytest.skip("ALIYUN_ACCESS_KEY_ID not set")
    if not os.getenv("ALIYUN_ACCESS_KEY_SECRET"):
        pytest.skip("ALIYUN_ACCESS_KEY_SECRET not set")


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )
    return str(content)


@given("a running agent")
def given_running_agent(web_search_context):
    _require_base_env()
    model = ChatOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )
    web_search_context["agent"] = create_agent(model=model)


@given("a running agent with unavailable search service")
def given_running_agent_with_unavailable_search_service(web_search_context, monkeypatch):
    _require_base_env()
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "invalid")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "invalid")

    model = ChatOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )
    web_search_context["agent"] = create_agent(model=model)


@when(parsers.parse('I ask "{text}"'))
def when_i_ask(web_search_context, text):
    result = web_search_context["agent"].invoke(
        {"messages": [("human", text)]},
        config={"configurable": {"thread_id": web_search_context["thread_id"]}},
    )
    web_search_context["result"] = result


@then("the agent should have searched the web")
def then_agent_should_have_searched_the_web(web_search_context):
    result = web_search_context["result"]
    tool_messages = [
        m for m in result["messages"]
        if getattr(m, "name", None) == "web_search"
    ]
    assert len(tool_messages) > 0
    assert re.search(r"https?://", _extract_text(tool_messages[-1].content))


@then("the agent should not have searched the web")
def then_agent_should_not_have_searched_the_web(web_search_context):
    result = web_search_context["result"]
    tool_messages = [
        m for m in result["messages"]
        if getattr(m, "name", None) == "web_search"
    ]
    assert len(tool_messages) == 0


@then("the response should be relevant to the topic")
def then_response_should_be_relevant_to_topic(web_search_context):
    final_message = web_search_context["result"]["messages"][-1]
    text = _extract_text(final_message.content).strip()
    assert text
    assert len(text) > 10
    assert not re.match(r"^(抱歉|无法|不能|不知道)", text)


@then("the response should not be an error message")
def then_response_should_not_be_an_error_message(web_search_context):
    final_message = web_search_context["result"]["messages"][-1]
    text = _extract_text(final_message.content).strip()
    assert text
    assert not text.startswith("网络搜索暂不可用")
