"""BDD steps for multi-turn conversation behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.core.agent import create_agent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "conversation.feature"))


@pytest.fixture
def context():
    return {
        "agent": None,
        "default_thread": "default-thread",
        "last_response": "",
        "thread_responses": {},
    }


def _extract_text(message):
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
        )
    return str(content)


def _send_message(agent, thread_id: str, text: str) -> str:
    result = agent.invoke(
        {"messages": [HumanMessage(content=text)]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return _extract_text(result["messages"][-1])


@given("an agent with memory")
def given_agent_with_memory(context, patch_init_chat_model):
    context["agent"] = create_agent()


@when(parsers.parse('I say "{text}"'))
def when_i_say(context, text):
    response = _send_message(context["agent"], context["default_thread"], text)
    context["last_response"] = response


@when("I receive a response")
def when_i_receive_response(context):
    assert context["last_response"]


@when(parsers.parse('I start a conversation with thread "{thread_id}" saying "{text}"'))
def when_i_start_thread_conversation(context, thread_id, text):
    response = _send_message(context["agent"], thread_id, text)
    context["thread_responses"][thread_id] = response
    context["last_response"] = response


@then(parsers.parse('the response should mention "{expected}"'))
def then_response_should_mention(context, expected):
    assert expected in context["last_response"]


@then(parsers.parse('the response for thread "{thread_id}" should not mention "{text}"'))
def then_thread_response_should_not_mention(context, thread_id, text):
    assert text not in context["thread_responses"][thread_id]
