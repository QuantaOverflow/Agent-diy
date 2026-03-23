from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.agent_backend import InProcessAgentBackend
from agent_diy.reminder_store import ReminderStore
from agent_diy.telegram_bot import TelegramBot
from agent_diy.tools.reminder import make_reminder_tools

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "scheduled_reminder.feature"))


class FakeReminderModel:
    """确定性 fake 模型，用于 @unit 测试。"""

    @staticmethod
    def _parse_minutes(text: str) -> int | None:
        match = re.search(r"([一二两三四五六七八九十\d]+)分钟后", text)
        if not match:
            return None
        raw = match.group(1)
        if raw.isdigit():
            return int(raw)
        mapping = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        return mapping.get(raw)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, config=None):
        user_id = 100
        for m in messages:
            if isinstance(m, SystemMessage):
                # 依赖 llm_call 注入 "当前用户ID：{id}" 的格式。
                # 若生产代码调整该格式，需同步更新这里以避免回落到默认 user_id=100。
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

        minute_value = self._parse_minutes(last_human)
        if minute_value is not None and "提醒" in last_human:
            task = re.sub(r".*分钟后", "", last_human).strip() or "执行任务"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "set_reminder",
                        "args": {"user_id": user_id, "task": task, "after_minutes": minute_value},
                        "id": "tc_set_once",
                        "type": "tool_call",
                    }
                ],
            )

        time_match = re.search(r"(\d+)点", last_human)
        has_task = any(kw in last_human for kw in ["帮我", "提醒", "查", "推送", "天气", "股市"])
        if time_match and has_task:
            hour = int(time_match.group(1))
            task = re.sub(r"每天.+点", "", last_human).strip() or "执行任务"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "set_reminder",
                        "args": {"user_id": user_id, "task": task, "time_str": f"{hour:02d}:00"},
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
    """scheduled_reminder 专用 bot_factory：@unit 用 FakeReminderModel，@integration 用真实 LLM。"""
    store = ctx["reminder_store"]
    reminder_tools = make_reminder_tools(store)

    from agent_diy.core.agent import create_agent

    if request.node.get_closest_marker("integration"):
        agent = create_agent(extra_tools=reminder_tools)
    else:
        agent = create_agent(model=FakeReminderModel(), extra_tools=reminder_tools)

    class TestableInProcessBackend(InProcessAgentBackend):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.raise_error = False

        async def reply(self, user_id: int, text: str) -> str:
            if self.raise_error:
                raise RuntimeError("test error")
            return await super().reply(user_id, text)

    backend = TestableInProcessBackend(agent=agent)
    bot = TelegramBot(token="fake-token", backend=backend, reminder_store=store)
    ctx["bot"] = bot
    ctx["backend"] = backend
    return bot


@then(parsers.parse('用户 "{user_id}" 应有 {count:d} 个已设置的提醒'))
def then_user_has_n_reminders(ctx, user_id, count):
    assert len(ctx["reminder_store"].list(int(user_id))) == count


@given(parsers.parse('用户 "{user_id}" 有一个提醒 "{task}"'))
def given_user_has_reminder_in_store(ctx, user_id, task):
    entry = ctx["reminder_store"].add(int(user_id), task, "09:00")
    ctx["pending_reminder"] = entry


@given(parsers.parse('用户 "{user_id}" 已设置提醒 "{task}"'))
def given_user_has_reminder(ctx, user_id, task):
    entry = ctx["reminder_store"].add(int(user_id), task, "09:00")
    ctx["pending_reminder"] = entry


@given("提醒调度注册会失败")
def given_reminder_schedule_registration_fails(ctx):
    def _fail_on_add(_entry):
        raise ValueError("调度失败：mock error")

    ctx["reminder_store"].on_add = _fail_on_add


@when(parsers.parse('用户 "{user_id}" 的提醒在预定时间触发'))
def when_reminder_fires(ctx, user_id):
    from agent_diy.reminder_scheduler import ReminderScheduler

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


@when(parsers.parse('调用 list_reminders 工具查询用户 "{user_id}" 的提醒'))
def when_call_list_reminders(ctx, user_id):
    tools = {t.name: t for t in make_reminder_tools(ctx["reminder_store"])}
    ctx["tool_result"] = tools["list_reminders"].invoke({"user_id": int(user_id)})


@when(parsers.parse('调用 cancel_reminder 工具取消用户 "{user_id}" 的提醒 "{reminder_id}"'))
def when_call_cancel_reminder(ctx, user_id, reminder_id):
    tools = {t.name: t for t in make_reminder_tools(ctx["reminder_store"])}
    ctx["tool_result"] = tools["cancel_reminder"].invoke(
        {"user_id": int(user_id), "reminder_id": int(reminder_id)}
    )


@then(parsers.parse('结果应包含 "{keyword}"'))
def then_result_contains(ctx, keyword):
    assert keyword in ctx["tool_result"]


@then("结果应为空列表")
def then_result_is_empty(ctx):
    assert "没有" in ctx["tool_result"]


@then("结果应提示提醒不存在")
def then_result_not_found(ctx):
    assert "未找到" in ctx["tool_result"]


@when(parsers.parse('用户 "{user_id}" 在 "{time_str}" 添加提醒 "{task}"'))
def when_user_adds_reminder(ctx, user_id, time_str, task):
    try:
        ctx["reminder_store"].add(int(user_id), task, time_str)
    except Exception as exc:
        ctx["error"] = exc
    else:
        ctx["error"] = None


@then("提醒添加应失败")
def then_reminder_add_should_fail(ctx):
    assert ctx["error"] is not None


@then("bot 的回复应包含反问时间的内容")
def then_response_asks_for_time(ctx):
    response = list(ctx["responses"].values())[-1]
    assert any(kw in response for kw in ["几点", "什么时间", "时间", "点钟"])
