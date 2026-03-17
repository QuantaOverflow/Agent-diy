"""BDD steps for Telegram bot behavior."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import NetworkError
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.telegram_bot import TelegramBot

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "telegram_bot.feature"))


@pytest.fixture
def ctx():
    return {
        "bot": None,
        "invoke_thread_ids": [],
        "responses": {},
        "error": None,
        "last_message": None,
        "handled_messages": [],
        "reply_side_effect_sequences": [],
    }


@pytest.fixture
def bot_factory(ctx, request):
    """创建 TelegramBot，根据测试类型注入不同 agent。"""
    if request.node.get_closest_marker("e2e"):
        from agent_diy.core.agent import create_agent

        agent = create_agent()
    else:
        agent = MagicMock()
        agent.invoke.return_value = {"messages": [MagicMock(content="mock reply")]}

    bot = TelegramBot(token="fake-token")
    bot._agent = agent
    ctx["bot"] = bot
    return bot


@given("Telegram bot 已初始化")
def given_bot_initialized(bot_factory):
    pass


@given(parsers.parse('agent 对任意消息返回 "{text}"'))
def given_agent_returns_text(ctx, text):
    ctx["bot"]._agent.invoke.return_value = {"messages": [MagicMock(content=text)]}


@given("agent 处理消息时抛出异常")
def given_agent_raises_error(ctx):
    ctx["bot"]._agent.invoke.side_effect = RuntimeError("test error")


@given("TELEGRAM_BOT_TOKEN 环境变量未配置")
def given_token_not_configured(ctx):
    ctx["token_missing"] = True


@when(parsers.parse('用户 "{user_id}" 发送消息 "{message}"'))
def when_user_sends_message(ctx, user_id, message):
    response = asyncio.run(ctx["bot"].handle_message(int(user_id), message))
    ctx["responses"][user_id] = response

    agent = ctx["bot"]._agent
    if hasattr(agent, "invoke") and hasattr(agent.invoke, "call_args") and agent.invoke.call_args:
        ctx["invoke_thread_ids"].append(
            agent.invoke.call_args.kwargs["config"]["configurable"]["thread_id"]
        )


@when("尝试启动 Telegram bot")
def when_try_start_bot(ctx):
    try:
        TelegramBot(token="")
    except ValueError as exc:
        ctx["error"] = exc


@given(parsers.parse('bot 的启动时间为 "{dt} UTC"'))
def given_bot_start_time(ctx, dt):
    ctx["bot"]._start_time = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


@given("第一条消息发送回复将连续失败三次，第二条消息发送成功")
def given_first_fail_then_second_success(ctx):
    ctx["reply_side_effect_sequences"] = [
        [
            NetworkError("transient network error"),
            NetworkError("transient network error"),
            NetworkError("transient network error"),
        ],
        [None],
    ]


@when(parsers.parse('收到一条发送时间为 "{dt} UTC" 的 Telegram 文本消息'))
def when_receive_telegram_text_message(ctx, dt):
    message_date = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    message = MagicMock()
    message.date = message_date
    message.text = "test message"
    if ctx["reply_side_effect_sequences"]:
        message.reply_text = AsyncMock(side_effect=ctx["reply_side_effect_sequences"].pop(0))
    else:
        message.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_user = MagicMock(id=123)
    update.message = message

    asyncio.run(ctx["bot"]._on_text_message(update, None))
    ctx["last_message"] = message
    ctx["handled_messages"].append(message)


@then("两个请求应使用不同的 thread_id")
def then_two_requests_use_different_thread_id(ctx):
    thread_ids = ctx["invoke_thread_ids"]
    assert len(thread_ids) >= 2
    assert thread_ids[0] != thread_ids[1]


@then(parsers.parse('bot 应向用户 "{user_id}" 发送文本 "{text}"'))
def then_bot_sends_text(ctx, user_id, text):
    assert ctx["responses"][user_id] == text


@then(parsers.parse('bot 应向用户 "{user_id}" 发送包含 "{keyword}" 的消息'))
def then_bot_sends_message_with_keyword(ctx, user_id, keyword):
    assert keyword in ctx["responses"][user_id]


@then("应抛出配置缺失错误")
def then_should_raise_missing_config_error(ctx):
    assert isinstance(ctx["error"], ValueError)


@then("agent 不应被调用")
def then_agent_should_not_be_called(ctx):
    assert ctx["bot"]._agent.invoke.call_count == 0


@then("bot 不应发送任何回复")
def then_bot_should_not_send_reply(ctx):
    assert ctx["last_message"] is not None
    ctx["last_message"].reply_text.assert_not_called()


@then("agent 应被调用一次")
def then_agent_should_be_called_once(ctx):
    assert ctx["bot"]._agent.invoke.call_count == 1


@then("agent 应被调用两次")
def then_agent_should_be_called_twice(ctx):
    assert ctx["bot"]._agent.invoke.call_count == 2


@then("第二条消息应成功发送回复")
def then_second_message_reply_should_succeed(ctx):
    assert len(ctx["handled_messages"]) >= 2
    first_message = ctx["handled_messages"][0]
    second_message = ctx["handled_messages"][1]
    assert first_message.reply_text.await_count == 3
    second_message.reply_text.assert_awaited_once()


@then("bot 的回复应与消息内容相关")
def then_response_related(ctx):
    response = list(ctx["responses"].values())[-1]
    assert len(response) > 10 and "出错" not in response


@then("bot 的回复应包含星座运势内容")
def then_response_contains_astrology(ctx):
    response = list(ctx["responses"].values())[-1]
    assert re.search(r"(运势|星座|行星|能量|格言|宇宙|占星)", response)


@then("bot 的回复应为中文")
def then_response_is_chinese(ctx):
    response = list(ctx["responses"].values())[-1]
    assert re.search(r"[\u4e00-\u9fff]", response)


@then("bot 的回复应包含天气信息")
def then_response_contains_weather(ctx):
    response = list(ctx["responses"].values())[-1]
    assert any(kw in response for kw in ["天气", "温度", "℃", "晴", "雨", "云", "风"])


@then("bot 的回复应与搜索话题相关")
def then_response_related_to_search(ctx):
    response = list(ctx["responses"].values())[-1]
    assert len(response) > 10 and "出错" not in response


@then(parsers.parse('bot 的回复应提及 "{text}"'))
def then_response_mentions_text(ctx, text):
    response = list(ctx["responses"].values())[-1]
    assert text in response


@then(parsers.parse('用户 "{user_id}" 的回复不应提及 "{text}"'))
def then_user_response_should_not_mention_text(ctx, user_id, text):
    assert text not in ctx["responses"][str(user_id)]
