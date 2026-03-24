from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.agent_backend import InProcessAgentBackend
from agent_diy.reminder_scheduler import ReminderScheduler
from agent_diy.reminder_store import ReminderStore
from agent_diy.telegram_bot import TelegramBot
from agent_diy.tools.reminder import make_reminder_tools

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "reminder_once.feature"))


class FakeBackend:
    def __init__(self, reply_text="task result"):
        self.reply_text = reply_text
        self.reply_calls: list = []
        self.raise_error = False

    async def reply(self, user_id: int, text: str, *, thread_id: str | None = None) -> str:
        self.reply_calls.append((user_id, text, thread_id))
        if self.raise_error:
            raise RuntimeError("test error")
        return self.reply_text


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
    }


@pytest.fixture
def bot_factory(ctx):
    store = ctx["reminder_store"]
    reminder_tools = make_reminder_tools(store)

    from agent_diy.core.agent import create_agent

    agent = create_agent(extra_tools=reminder_tools)
    backend = InProcessAgentBackend(agent=agent)
    bot = TelegramBot(token="fake-token", backend=backend, reminder_store=store)
    ctx["bot"] = bot
    ctx["backend"] = backend
    return bot


@given(parsers.parse('用户 "{user_id}" 已设置一次性提醒 "{task}"'))
def given_user_has_once_reminder(ctx, user_id, task):
    run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    entry = ctx["reminder_store"].add_once(int(user_id), task, run_at, mode="remind")
    ctx["pending_reminder"] = entry


@given(parsers.parse('用户 "{user_id}" 已设置一次性提醒型任务 "{task}"'))
def given_user_has_once_remind_task(ctx, user_id, task):
    run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    entry = ctx["reminder_store"].add_once(int(user_id), task, run_at, mode="remind")
    ctx["pending_reminder"] = entry


@given(parsers.parse('用户 "{user_id}" 已设置一次性执行型任务 "{task}"'))
def given_user_has_once_execute_task(ctx, user_id, task):
    run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    entry = ctx["reminder_store"].add_once(int(user_id), task, run_at, mode="execute")
    ctx["pending_reminder"] = entry
    ctx["backend"] = FakeBackend(reply_text="北京天气：晴，20°C")


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


@then(parsers.parse('用户 "{user_id}" 应有 {count:d} 个已设置的提醒'))
def then_user_has_n_reminders(ctx, user_id, count):
    assert len(ctx["reminder_store"].list(int(user_id))) == count


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
