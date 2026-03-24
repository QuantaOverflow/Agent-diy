from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.agent_backend import InProcessAgentBackend
from agent_diy.reminder_store import ReminderStore
from agent_diy.reminder_scheduler import ReminderScheduler
from agent_diy.telegram_bot import TelegramBot
from agent_diy.tools.reminder import make_reminder_tools

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "reminder_execution_mode.feature"))


class FakeBackend:
    """追踪 reply() 调用，支持 raise_error，返回固定文本。"""

    def __init__(self, reply_text="task result"):
        self.reply_text = reply_text
        self.reply_calls: list = []
        self.raise_error = False

    async def reply(self, user_id: int, text: str, *, thread_id: str | None = None) -> str:
        self.reply_calls.append((user_id, text, thread_id))
        if self.raise_error:
            raise RuntimeError("test error")
        return self.reply_text


class FakeReminderModel:
    """确定性 fake 模型，用于 @unit 测试。"""

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, config=None):
        user_id = 100
        for m in messages:
            if isinstance(m, SystemMessage):
                match = re.search(r"当前用户ID：(\d+)", m.content)
                if match:
                    user_id = int(match.group(1))

        last = messages[-1]
        if isinstance(last, ToolMessage):
            content = last.content
            if "没有" in content:
                return AIMessage(content="您当前没有设置任何提醒。")
            if "已取消" in content or "未找到" in content:
                return AIMessage(content=content)
            return AIMessage(content="已为您设置提醒！")

        human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        if not human_msgs:
            return AIMessage(content="没有可用的提醒")
        last_human = human_msgs[-1].content

        time_match = re.search(r"(\d+)点", last_human)
        has_task = any(kw in last_human for kw in ["帮我", "提醒", "查", "推送", "天气", "股市"])
        if time_match and has_task:
            hour = int(time_match.group(1))
            task = re.sub(r"每天.+点", "", last_human).strip() or "执行任务"
            remind_keywords = ["喝水", "起身", "休息", "睡觉", "提醒我"]
            execute_keywords = ["查", "天气", "股市", "新闻", "汇率", "星座", "帮我"]
            if any(k in task for k in execute_keywords):
                mode = "execute"
            elif any(k in task for k in remind_keywords):
                mode = "remind"
            else:
                mode = "execute"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "set_reminder",
                        "args": {
                            "user_id": user_id,
                            "task": task,
                            "time_str": f"{hour:02d}:00",
                            "mode": mode,
                        },
                        "id": "tc_set",
                        "type": "tool_call",
                    }
                ],
            )

        if any(kw in last_human for kw in ["查看", "哪些", "我的提醒"]):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_reminders",
                        "args": {"user_id": user_id},
                        "id": "tc_list",
                        "type": "tool_call",
                    }
                ],
            )

        return AIMessage(content="没有可用的提醒")


@pytest.fixture
def reminder_store():
    return ReminderStore()


@pytest.fixture(autouse=True)
def isolate_store(reminder_store):
    yield
    reminder_store.clear()
    reminder_store.on_add = None
    reminder_store.on_cancel = None


@pytest.fixture
def ctx(reminder_store):
    return {
        "bot": None,
        "backend": None,
        "responses": {},
        "error": None,
        "last_message": None,
        "handled_messages": [],
        "reply_side_effect_sequences": [],
        "reminder_store": reminder_store,
        "pending_reminder": None,
        "proactive_messages": [],
        "tool_result": None,
    }


@pytest.fixture
def bot_factory(ctx, request):
    store = ctx["reminder_store"]
    reminder_tools = make_reminder_tools(store)

    from agent_diy.core.agent import create_agent

    if request.node.get_closest_marker("integration"):
        agent = create_agent(extra_tools=reminder_tools)
    else:
        agent = create_agent(model=FakeReminderModel(), extra_tools=reminder_tools)

    backend = InProcessAgentBackend(agent=agent)
    bot = TelegramBot(token="fake-token", backend=backend, reminder_store=store)
    ctx["bot"] = bot
    ctx["backend"] = backend
    return bot


@given(parsers.parse('用户 "{user_id}" 已设置提醒型任务 "{task}"'))
def given_user_has_remind_type_task(ctx, user_id, task):
    store = ctx["reminder_store"]
    entry = store.add(int(user_id), task, "09:00", mode="remind")
    ctx["pending_reminder"] = entry
    if ctx["backend"] is None:
        ctx["backend"] = FakeBackend()


@given(parsers.parse('用户 "{user_id}" 已设置执行型任务 "{task}"'))
def given_user_has_execute_type_task(ctx, user_id, task):
    store = ctx["reminder_store"]
    entry = store.add(int(user_id), task, "09:00", mode="execute")
    ctx["pending_reminder"] = entry
    if ctx["backend"] is None:
        ctx["backend"] = FakeBackend(reply_text="北京天气：晴，20°C")


@given(parsers.parse('用户 "{user_id}" 已通过消息 "{message}" 设置了提醒'))
def given_user_set_reminder_via_message(ctx, user_id, message):
    uid = int(user_id)
    sent_message = AsyncMock()
    sent_message.edit_text = AsyncMock()
    msg = MagicMock()
    msg.date = datetime.now(timezone.utc)
    msg.text = message
    msg.reply_text = AsyncMock(return_value=sent_message)
    update = MagicMock()
    update.effective_user = MagicMock(id=uid)
    update.message = msg
    asyncio.run(ctx["bot"]._on_text_message(update, None))
    reminders = ctx["reminder_store"].list(uid)
    assert reminders, f"LLM 未设置任何提醒（消息：{message}）"
    ctx["pending_reminder"] = reminders[-1]


@when(parsers.parse('用户 "{user_id}" 的提醒在预定时间触发'))
def when_reminder_fires(ctx, user_id):
    sent = []

    async def mock_send(uid, text):
        sent.append((uid, text))

    store = ctx["reminder_store"]
    prev_on_add = store.on_add
    prev_on_cancel = store.on_cancel
    scheduler = ReminderScheduler(
        store=store,
        backend=ctx["backend"],
        send_callback=mock_send,
    )
    entry = ctx["pending_reminder"]
    try:
        asyncio.run(scheduler._fire(int(user_id), entry.task, entry.id))
    finally:
        store.on_add = prev_on_add
        store.on_cancel = prev_on_cancel
    ctx["proactive_messages"] = sent
    for uid, text in sent:
        ctx["responses"][str(uid)] = text


@then(parsers.parse('bot 应主动向用户 "{user_id}" 发送包含任务结果的消息'))
def then_bot_proactively_sends(ctx, user_id):
    msgs = ctx["proactive_messages"]
    assert any(uid == int(user_id) and text for uid, text in msgs)


@then(parsers.parse('bot 应主动向用户 "{user_id}" 发送固定提醒文案'))
def then_bot_sends_fixed_reminder_text(ctx, user_id):
    uid = int(user_id)
    msgs = ctx["proactive_messages"]
    assert any(u == uid and "提醒" in t for u, t in msgs), f"未找到固定提醒文案: {msgs}"
    for u, t in msgs:
        if u == uid:
            assert "已完成" not in t and "已记录" not in t, f"出现错误话术: {t}"


@then("bot 不应调用 backend 处理该提醒")
def then_backend_not_called(ctx):
    backend = ctx["backend"]
    if hasattr(backend, "reply_calls"):
        assert len(backend.reply_calls) == 0, f"backend.reply 被调用了: {backend.reply_calls}"
