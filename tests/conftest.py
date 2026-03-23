"""Shared fixtures for conversation tests."""

from __future__ import annotations

import os
import re
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pytest_bdd import given, parsers, then, when

from agent_diy.core import agent as agent_module
from agent_diy.utils import content_to_text


def _reset_financial_news_runtime_cache() -> None:
    from agent_diy.mcp import client as mcp_client

    agent_module._FINANCIAL_NEWS_TOOLS = None
    agent_module._FINANCIAL_NEWS_LOAD_ERROR = None
    mcp_client._invalidate_cached_client()


@pytest.fixture
def reset_financial_news_runtime_cache():
    return _reset_financial_news_runtime_cache


def pytest_collection_modifyitems(config, items):
    """Map feature file tags to pytest markers and auto-skip integration without API key."""
    for item in items:
        # pytest-bdd stores tags from feature files in item.get_closest_marker
        # but we need to check keywords for scenario-level tags
        if "integration" in item.keywords:
            item.add_marker(pytest.mark.integration)
            if not os.getenv("DASHSCOPE_API_KEY"):
                item.add_marker(pytest.mark.skip(reason="DASHSCOPE_API_KEY not set"))
        if "e2e" in item.keywords:
            item.add_marker(pytest.mark.e2e)
            if not os.getenv("DASHSCOPE_API_KEY"):
                item.add_marker(pytest.mark.skip(reason="DASHSCOPE_API_KEY not set"))
        if "unit" in item.keywords:
            item.add_marker(pytest.mark.unit)


class FakeModel:
    """Simple deterministic fake model for conversation tests."""

    def bind_tools(self, _tools):
        return self

    def invoke(self, messages):
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        last_human = human_messages[-1].content if human_messages else ""

        if "what is my name" in last_human.lower():
            name = self._find_latest_name(human_messages)
            if name:
                return AIMessage(content=f"Your name is {name}.")
            return AIMessage(content="I don't know your name yet.")

        intro_match = re.search(r"my name is\s+([A-Za-z]+)", last_human, flags=re.IGNORECASE)
        if intro_match:
            name = intro_match.group(1)
            return AIMessage(content=f"Nice to meet you, {name}.")

        return AIMessage(content="How can I help?")

    @staticmethod
    def _find_latest_name(human_messages):
        # This intentionally scans all human messages in the current state.
        # In these tests, LangGraph's InMemorySaver restores prior turns into
        # `messages` for the same thread_id before invoke(), so name recall
        # depends on that persisted-history behavior.
        for msg in reversed(human_messages):
            match = re.search(r"my name is\s+([A-Za-z]+)", msg.content, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None


@pytest.fixture
def patch_init_chat_model(monkeypatch):
    """Patch chat model initialization to avoid external API calls."""

    def _init_chat_model(_model_name):
        return FakeModel()

    monkeypatch.setattr(agent_module, "init_chat_model", _init_chat_model)


@pytest.fixture
def qwen_model():
    from agent_diy.core.model import create_dashscope_model

    if not os.getenv("DASHSCOPE_API_KEY"):
        pytest.skip("DASHSCOPE_API_KEY not set")
    return create_dashscope_model()


@pytest.fixture
def ctx():
    return {
        "bot": None,
        "backend": None,
        "responses": {},
        "error": None,
        "last_message": None,
        "handled_messages": [],
        "reply_side_effect_sequences": [],
    }


@given("Telegram bot 已初始化")
def given_bot_initialized(bot_factory):
    pass


@given("backend 处理消息时抛出异常")
def given_backend_raises_error(ctx):
    ctx["backend"].raise_error = True


@when(parsers.parse('Telegram 收到用户 "{user_id}" 的消息 "{message}"'))
def when_telegram_receives_message(ctx, user_id, message):
    sent_message = AsyncMock()
    sent_message.edit_text = AsyncMock()

    msg = MagicMock()
    msg.date = datetime.now(timezone.utc)
    msg.text = message
    if ctx["reply_side_effect_sequences"]:
        msg.reply_text = AsyncMock(side_effect=ctx["reply_side_effect_sequences"].pop(0))
    else:
        msg.reply_text = AsyncMock(return_value=sent_message)

    update = MagicMock()
    update.effective_user = MagicMock(id=int(user_id))
    update.message = msg

    asyncio.run(ctx["bot"]._on_text_message(update, None))

    ctx["last_message"] = msg
    ctx["handled_messages"].append(msg)

    reply_calls = [call.args[0] for call in msg.reply_text.await_args_list]
    edit_calls = [call.args[0] for call in sent_message.edit_text.call_args_list]

    if edit_calls:
        extra_chunks = "".join(reply_calls[1:]) if len(reply_calls) > 1 else ""
        ctx["responses"][str(user_id)] = edit_calls[-1] + extra_chunks
    elif reply_calls:
        ctx["responses"][str(user_id)] = reply_calls[-1]
    else:
        ctx["responses"][str(user_id)] = ""


@then(parsers.parse('bot 应向用户 "{user_id}" 发送包含 "{keyword}" 的消息'))
def then_bot_sends_message_with_keyword(ctx, user_id, keyword):
    assert keyword in ctx["responses"][user_id]


@then(parsers.parse('bot 的回复应提及 "{text}"'))
def then_response_mentions_text(ctx, text):
    response = list(ctx["responses"].values())[-1]
    assert text in response


@then(parsers.parse('用户 "{user_id}" 的回复不应提及 "{text}"'))
def then_user_response_should_not_mention_text(ctx, user_id, text):
    assert text not in ctx["responses"][str(user_id)]


@then("the response should not be an error message")
def then_response_should_not_be_an_error_message(request):
    context = None
    matched_fixture_name = None
    for fixture_name in ("financial_news_context", "web_search_context"):
        if fixture_name in request.fixturenames:
            context = request.getfixturevalue(fixture_name)
            matched_fixture_name = fixture_name
            break

    assert context is not None, "Missing known context fixture for response assertion"
    final_message = context["result"]["messages"][-1]
    text = content_to_text(final_message.content).strip()
    assert text
    if matched_fixture_name == "web_search_context":
        assert not text.startswith("网络搜索暂不可用")


@given("Gmail credentials are configured")
def given_gmail_credentials_configured():
    creds = Path("credentials.json")
    token = Path("token.json")
    if not creds.exists() and not token.exists():
        pytest.skip("Gmail credentials not configured")
