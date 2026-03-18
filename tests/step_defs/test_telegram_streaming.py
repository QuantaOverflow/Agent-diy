"""BDD steps for Telegram streaming reply behavior."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.agent_backend import DEFAULT_ERROR_REPLY, EMPTY_MESSAGES_REPLY
from agent_diy.telegram_bot import TelegramBot
from agent_diy.utils import StreamEvent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "telegram_streaming.feature"))


class MockStreamingBackend:
    def __init__(self):
        self.events: list[StreamEvent] = []
        self.error: Exception | None = None

    async def reply(self, user_id: int, text: str) -> str:
        return "fallback reply"

    async def stream_reply(self, user_id: int, text: str):
        for event in self.events:
            yield event
        if self.error:
            raise self.error


@pytest.fixture
def ctx():
    return {
        "bot": None,
        "backend": None,
        "sent_message": None,
        "reply_text_mock": None,
        "token_count": 0,
        "tool_name": None,
    }


@given("Telegram bot 已初始化")
def given_telegram_bot_initialized(ctx):
    backend = MockStreamingBackend()
    bot = TelegramBot(token="fake", backend=backend)
    ctx["bot"] = bot
    ctx["backend"] = backend


@given("agent 流式返回多个 token")
def given_agent_streams_multiple_tokens(ctx):
    ctx["backend"].events = [
        StreamEvent("token", "你"),
        StreamEvent("token", "好"),
        StreamEvent("token", "！"),
    ]
    ctx["token_count"] = 3


@given(parsers.parse('agent 流式过程中调用工具 "{tool_name}"'))
def given_agent_streams_with_tool_call(ctx, tool_name):
    ctx["backend"].events = [
        StreamEvent("tool_call", tool_name),
        StreamEvent("token", "工具结果文本"),
    ]
    ctx["token_count"] = 2
    ctx["tool_name"] = tool_name


@given("agent 流式快速返回大量 token")
def given_agent_streams_many_tokens_fast(ctx):
    ctx["backend"].events = [StreamEvent("token", "x") for _ in range(50)]
    ctx["token_count"] = 50


@given("agent 流式过程中抛出异常")
def given_agent_stream_raises_error(ctx):
    ctx["backend"].error = RuntimeError("stream error")


@given("agent 流式返回空内容")
def given_agent_streams_empty_content(ctx):
    ctx["backend"].events = []


@when(parsers.parse('用户 "{user_id}" 发送消息 "{message}"'))
def when_user_sends(ctx, user_id, message):
    sent_message = AsyncMock()
    sent_message.edit_text = AsyncMock()

    msg = MagicMock()
    msg.date = datetime.now(timezone.utc)
    msg.text = message
    msg.reply_text = AsyncMock(return_value=sent_message)

    update = MagicMock()
    update.effective_user = MagicMock(id=int(user_id))
    update.message = msg

    asyncio.run(ctx["bot"]._on_text_message(update, None))

    ctx["sent_message"] = sent_message
    ctx["reply_text_mock"] = msg.reply_text


@then("bot 应先发送占位消息")
def then_bot_should_send_placeholder_first(ctx):
    ctx["reply_text_mock"].assert_called_once_with("⏳")


@then("bot 应编辑该消息至少一次")
def then_bot_should_edit_message_at_least_once(ctx):
    assert ctx["sent_message"].edit_text.call_count >= 1


@then("最终消息应包含完整回复内容")
def then_final_message_should_contain_complete_reply(ctx):
    assert ctx["sent_message"].edit_text.call_args_list
    final_text = ctx["sent_message"].edit_text.call_args_list[-1][0][0]
    expected = "".join(event.content for event in ctx["backend"].events if event.type == "token")
    assert final_text
    assert "出错" not in final_text
    assert expected in final_text


@then("编辑过程中应出现工具调用提示")
def then_editing_should_show_tool_call_status(ctx):
    calls = ctx["sent_message"].edit_text.call_args_list
    assert any("🔧" in str(call[0][0]) for call in calls)
    if ctx["tool_name"] is not None:
        assert any(ctx["tool_name"] in str(call[0][0]) for call in calls)


@then("消息编辑次数应少于 token 总数")
def then_edit_count_should_be_less_than_token_count(ctx):
    assert ctx["sent_message"].edit_text.call_count < ctx["token_count"]


@then("最终消息应包含错误提示")
def then_final_message_should_contain_error_hint(ctx):
    assert ctx["sent_message"].edit_text.call_args_list
    final_text = ctx["sent_message"].edit_text.call_args_list[-1][0][0]
    assert "出错" in final_text
    assert final_text == DEFAULT_ERROR_REPLY


@then("最终消息应包含空回复错误提示")
def then_final_message_should_contain_empty_reply_error(ctx):
    assert ctx["sent_message"].edit_text.call_args_list
    final_text = ctx["sent_message"].edit_text.call_args_list[-1][0][0]
    assert final_text == EMPTY_MESSAGES_REPLY
