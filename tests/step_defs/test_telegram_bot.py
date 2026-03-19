"""BDD steps for Telegram bot behavior."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from telegram.error import NetworkError

from agent_diy.agent_backend import InProcessAgentBackend
from agent_diy.telegram_bot import TelegramBot
from agent_diy.utils import StreamEvent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "telegram_bot.feature"))


class MockStreamBackend:
    def __init__(self):
        self.reply_text = "mock reply"
        self.raise_error = False
        self.calls: list[int] = []
        self.session_versions: dict[int, int] = {}

    async def reply(self, user_id: int, text: str) -> str:
        self.calls.append(user_id)
        if self.raise_error:
            raise RuntimeError("test error")
        return self.reply_text

    async def stream_reply(self, user_id: int, text: str):
        self.calls.append(user_id)
        if self.raise_error:
            raise RuntimeError("test error")
        yield StreamEvent(type="token", content=self.reply_text)

    def reset_session(self, user_id: int) -> None:
        self.session_versions[user_id] = self.session_versions.get(user_id, 0) + 1


class MockReplyOnlyBackend:
    def __init__(self):
        self.reply_text = "mock reply"
        self.calls: list[int] = []

    async def reply(self, user_id: int, text: str) -> str:
        self.calls.append(user_id)
        return self.reply_text


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


@pytest.fixture
def bot_factory(ctx, request):
    """Create TelegramBot with backend abstraction for unit and integration."""
    if request.node.get_closest_marker("integration"):
        from agent_diy.core.agent import create_agent

        backend = InProcessAgentBackend(agent=create_agent())
    else:
        backend = MockStreamBackend()

    bot = TelegramBot(token="fake-token", backend=backend)
    ctx["bot"] = bot
    ctx["backend"] = backend
    return bot


@given("Telegram bot 已初始化")
def given_bot_initialized(bot_factory):
    pass


@given(parsers.parse('backend 对任意消息返回 "{text}"'))
def given_backend_returns_text(ctx, text):
    ctx["backend"].reply_text = text


@given("backend 处理消息时抛出异常")
def given_backend_raises_error(ctx):
    ctx["backend"].raise_error = True


@given("TELEGRAM_BOT_TOKEN 环境变量未配置")
def given_token_not_configured(ctx):
    ctx["token_missing"] = True


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
    # This scenario verifies fallback send retry behavior only.
    fallback_backend = MockReplyOnlyBackend()
    ctx["bot"]._backend = fallback_backend
    ctx["backend"] = fallback_backend
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
        sent_message = AsyncMock()
        sent_message.edit_text = AsyncMock()
        message.reply_text = AsyncMock(return_value=sent_message)

    update = MagicMock()
    update.effective_user = MagicMock(id=123)
    update.message = message

    asyncio.run(ctx["bot"]._on_text_message(update, None))
    ctx["last_message"] = message
    ctx["handled_messages"].append(message)


@then("两个请求应使用不同的会话标识")
def then_two_requests_use_different_session_id(ctx):
    calls = ctx["backend"].calls
    assert len(calls) >= 2
    assert calls[0] != calls[1]


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
    assert len(ctx["backend"].calls) == 0


@then("bot 不应发送任何回复")
def then_bot_should_not_send_reply(ctx):
    assert ctx["last_message"] is not None
    ctx["last_message"].reply_text.assert_not_called()


@then("backend 应被调用一次")
def then_backend_should_be_called_once(ctx):
    assert len(ctx["backend"].calls) == 1


@then("backend 应被调用两次")
def then_backend_should_be_called_twice(ctx):
    assert len(ctx["backend"].calls) == 2


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


@when(parsers.parse('用户 "{user_id}" 发送命令 "/clear"'))
def when_user_sends_clear_command(ctx, user_id):
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = MagicMock(id=int(user_id))
    update.message = msg

    asyncio.run(ctx["bot"]._on_clear_command(update, None))
    ctx["clear_reply"] = msg.reply_text.await_args.args[0]


@then(parsers.parse('/clear 前后用户 "{user_id}" 的会话标识应不同'))
def then_clear_should_change_session_id(ctx, user_id):
    versions = ctx["backend"].session_versions
    assert versions[int(user_id)] > 0


@then("bot 应回复对话重置确认")
def then_bot_should_reply_clear_confirmation(ctx):
    assert "重置" in ctx["clear_reply"]
