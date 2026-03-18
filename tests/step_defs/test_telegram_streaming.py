"""BDD steps for Telegram streaming reply behavior."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from telegram.error import RetryAfter

from agent_diy.agent_backend import DEFAULT_ERROR_REPLY, EMPTY_MESSAGES_REPLY, InProcessAgentBackend
from agent_diy.telegram_bot import TelegramBot
from agent_diy.utils import StreamEvent, parse_stream_chunk

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
        "tool_name": None,
        "expected_text": "",
        "edit_side_effect": None,
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
    ctx["expected_text"] = "你好！"


@given(parsers.parse('agent 流式过程中调用工具 "{tool_name}"'))
def given_agent_streams_with_tool_call(ctx, tool_name):
    ctx["backend"].events = [
        StreamEvent("tool_call", tool_name),
        StreamEvent("token", "工具结果文本"),
    ]
    ctx["expected_text"] = "工具结果文本"
    ctx["tool_name"] = tool_name


@given("agent 流式快速返回大量 token")
def given_agent_streams_many_tokens_fast(ctx):
    ctx["backend"].events = [StreamEvent("token", "x") for _ in range(50)]
    ctx["expected_text"] = "x" * 50


@given("agent 流式返回超长内容")
def given_agent_streams_very_long_content(ctx):
    long_text = "长文" * 2500
    ctx["backend"].events = [StreamEvent("token", long_text)]
    ctx["expected_text"] = long_text


@given("agent 仅返回一次性完整文本")
def given_agent_streams_single_full_text(ctx):
    full_text = "这是一次性完整回复文本。"
    ctx["backend"].events = [StreamEvent("token", full_text)]
    ctx["expected_text"] = full_text


@given("agent 流式过程中抛出异常")
def given_agent_stream_raises_error(ctx):
    ctx["backend"].error = RuntimeError("stream error")


@given("agent 流式返回空内容")
def given_agent_streams_empty_content(ctx):
    ctx["backend"].events = []


@given("Telegram 编辑消息会触发一次限流")
def given_telegram_edit_hits_rate_limit_once(ctx):
    ctx["edit_side_effect"] = [RetryAfter(timedelta(seconds=1)), None]


@when(parsers.parse('用户 "{user_id}" 发送消息 "{message}"'))
def when_user_sends(ctx, user_id, message):
    sent_message = AsyncMock()
    side_effect = ctx.get("edit_side_effect")
    if side_effect is None:
        sent_message.edit_text = AsyncMock()
    else:
        sent_message.edit_text = AsyncMock(side_effect=side_effect)

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
    expected = ctx["expected_text"] or "".join(
        event.content for event in ctx["backend"].events if event.type == "token"
    )
    assert final_text
    assert "出错" not in final_text
    assert expected in final_text


@then("编辑过程中应出现工具调用提示")
def then_editing_should_show_tool_call_status(ctx):
    calls = ctx["sent_message"].edit_text.call_args_list
    assert any("🔧" in str(call[0][0]) for call in calls)
    if ctx["tool_name"] is not None:
        assert any(ctx["tool_name"] in str(call[0][0]) for call in calls)


@then("最终消息不应是错误提示")
def then_final_message_should_not_be_error(ctx):
    assert ctx["sent_message"].edit_text.call_args_list
    final_text = ctx["sent_message"].edit_text.call_args_list[-1][0][0]
    assert final_text not in {DEFAULT_ERROR_REPLY, EMPTY_MESSAGES_REPLY}
    assert "Message_too_long" not in final_text


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


@then("长回复应被完整送达")
def then_long_reply_should_be_fully_delivered(ctx):
    expected = ctx["expected_text"]
    assert expected
    assert ctx["sent_message"].edit_text.call_args_list

    first_chunk = ctx["sent_message"].edit_text.call_args_list[-1][0][0]
    extra_chunks = [call.args[0] for call in ctx["reply_text_mock"].await_args_list[1:]]
    delivered = first_chunk + "".join(extra_chunks)

    assert delivered == expected


# ─── parse_stream_chunk 组件测试 ──────────────────────────────────────────

def _make_chunk(node: str, chunk_type: str):
    """构造模拟的 LangGraph stream chunk。"""
    msg = MagicMock()
    if chunk_type == "token":
        msg.content = "你好"
        msg.tool_call_chunks = []
    elif chunk_type == "tool_call":
        msg.content = ""
        msg.tool_call_chunks = [{"name": "get_current_weather"}]
    elif chunk_type == "empty_content":
        msg.content = ""
        msg.tool_call_chunks = []
    else:
        msg.content = "something"
        msg.tool_call_chunks = []
    return (msg, {"langgraph_node": node})


@given(parsers.parse('一个 langgraph_node 为 "{node}" 的 stream chunk，类型为 "{chunk_type}"'))
def given_a_stream_chunk(ctx, node, chunk_type):
    ctx["chunk"] = _make_chunk(node, chunk_type)


@when("解析该 chunk")
def when_parse_chunk(ctx):
    ctx["parse_result"] = parse_stream_chunk(ctx["chunk"])


@then(parsers.parse('解析结果应为 "{event_type}" 事件，内容为 "{content}"'))
def then_parse_result_should_be_event(ctx, event_type, content):
    result = ctx["parse_result"]
    assert result is not None
    assert result.type == event_type
    assert result.content == content


@then("解析结果应为 None")
def then_parse_result_should_be_none(ctx):
    assert ctx["parse_result"] is None


# ─── InProcessAgentBackend.stream_reply 组件测试 ─────────────────────────

class FakeStreamableAgent:
    """非 MagicMock 的 fake agent，避免触发 telegram_bot 的 mock 检测。"""

    def __init__(self, chunks, error=None):
        self._chunks = chunks
        self._error = error

    def stream(self, *_args, **_kwargs):
        for c in self._chunks:
            yield c
        if self._error:
            raise self._error

    def invoke(self, *_args, **_kwargs):
        return {"messages": []}


def _make_mock_agent_with_stream(chunks, error=None):
    """构造 fake agent，其 .stream() 返回预设 chunks。"""
    return FakeStreamableAgent(chunks, error)


@given("一个 mock agent 的 stream 返回 token 和工具调用 chunks")
def given_mock_agent_stream_with_events(ctx):
    tool_msg = MagicMock()
    tool_msg.content = ""
    tool_msg.tool_call_chunks = [{"name": "web_search"}]

    token_msg = MagicMock()
    token_msg.content = "搜索结果"
    token_msg.tool_call_chunks = []

    chunks = [
        (tool_msg, {"langgraph_node": "llm_call"}),
        (token_msg, {"langgraph_node": "llm_call"}),
    ]
    ctx["mock_agent"] = _make_mock_agent_with_stream(chunks)


@given("一个 mock agent 的 stream 过程中抛出异常")
def given_mock_agent_stream_raises(ctx):
    token_msg = MagicMock()
    token_msg.content = "部分"
    token_msg.tool_call_chunks = []
    chunks = [(token_msg, {"langgraph_node": "llm_call"})]
    ctx["mock_agent"] = _make_mock_agent_with_stream(chunks, error=RuntimeError("boom"))


@given("一个 mock agent 的 stream 返回空序列")
def given_mock_agent_stream_empty(ctx):
    ctx["mock_agent"] = _make_mock_agent_with_stream([])


@when("通过 InProcessAgentBackend 调用 stream_reply")
def when_call_stream_reply(ctx):
    backend = InProcessAgentBackend(agent=ctx["mock_agent"])
    events = []
    error = None

    async def _collect():
        nonlocal error
        try:
            async for event in backend.stream_reply(user_id=1, text="test"):
                events.append(event)
        except Exception as exc:
            error = exc

    asyncio.run(_collect())
    ctx["stream_events"] = events
    ctx["stream_error"] = error


@then("应依次产出 tool_call 和 token 类型的 StreamEvent")
def then_should_yield_tool_call_and_token(ctx):
    events = ctx["stream_events"]
    assert len(events) == 2
    assert events[0].type == "tool_call"
    assert events[0].content == "web_search"
    assert events[1].type == "token"
    assert events[1].content == "搜索结果"


@then("stream_reply 应抛出该异常")
def then_stream_reply_should_raise(ctx):
    assert ctx["stream_error"] is not None
    assert isinstance(ctx["stream_error"], RuntimeError)


@then("stream_reply 应产出零个事件")
def then_stream_reply_should_yield_nothing(ctx):
    assert ctx["stream_events"] == []
    assert ctx["stream_error"] is None


# ─── 全链路集成测试 ──────────────────────────────────────────────────────

@given("Telegram bot 使用 InProcessAgentBackend 和可流式的 mock agent")
def given_bot_with_in_process_backend(ctx):
    token_msg1 = MagicMock()
    token_msg1.content = "集成"
    token_msg1.tool_call_chunks = []

    token_msg2 = MagicMock()
    token_msg2.content = "测试通过"
    token_msg2.tool_call_chunks = []

    chunks = [
        (token_msg1, {"langgraph_node": "llm_call"}),
        (token_msg2, {"langgraph_node": "llm_call"}),
    ]
    agent = _make_mock_agent_with_stream(chunks)
    backend = InProcessAgentBackend(agent=agent)
    bot = TelegramBot(token="fake", backend=backend)
    ctx["bot"] = bot
    ctx["expected_text"] = "集成测试通过"


@when(parsers.parse('用户 "{user_id}" 通过 Telegram 发送消息 "{message}"'))
def when_user_sends_via_telegram(ctx, user_id, message):
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


@then("最终消息应包含 mock agent 的完整输出")
def then_final_message_should_contain_full_agent_output(ctx):
    assert ctx["sent_message"].edit_text.call_args_list
    final_text = ctx["sent_message"].edit_text.call_args_list[-1][0][0]
    assert ctx["expected_text"] in final_text
    assert "出错" not in final_text
