from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.agent_backend import InProcessAgentBackend
from agent_diy.reminder_scheduler import ReminderScheduler
from agent_diy.reminder_store import ReminderStore
from agent_diy.telegram_bot import TelegramBot
from agent_diy.tools.reminder import make_reminder_tools

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "reminder_execution_mode.feature"))


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
        "backend": FakeBackend(reply_text="任务执行结果"),
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


@given(parsers.parse('用户 "{user_id}" 已设置提醒 "{task}"'))
def given_user_has_reminder(ctx, user_id, task):
    entry = ctx["reminder_store"].add(int(user_id), task, "09:00")
    ctx["pending_reminder"] = entry


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
