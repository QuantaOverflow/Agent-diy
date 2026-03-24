from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from agent_diy.reminder_scheduler import ReminderScheduler
from agent_diy.reminder_store import ReminderStore


def test_fire_task_calls_backend_and_sends_result():
    async def _case():
        store = ReminderStore()
        entry = store.add_once(1, "喝水", datetime.now())
        backend = AsyncMock()
        backend.reply = AsyncMock(return_value="该喝水了！")
        sent: list[tuple[int, str]] = []

        async def _send(uid: int, text: str):
            sent.append((uid, text))

        scheduler = ReminderScheduler(store=store, backend=backend, send_callback=_send)
        await scheduler._fire(1, entry.task, entry.id)

        backend.reply.assert_awaited_once_with(1, "喝水", thread_id=f"scheduler_{entry.id}")
        assert sent == [(1, "该喝水了！")]

    asyncio.run(_case())


def test_fire_query_task_uses_same_reminder_prompt():
    async def _case():
        store = ReminderStore()
        entry = store.add_once(1, "查北京天气", datetime.now())
        backend = AsyncMock()
        backend.reply = AsyncMock(return_value="北京晴，20°C")
        sent: list[tuple[int, str]] = []

        async def _send(uid: int, text: str):
            sent.append((uid, text))

        scheduler = ReminderScheduler(store=store, backend=backend, send_callback=_send)
        await scheduler._fire(1, entry.task, entry.id)

        backend.reply.assert_awaited_once_with(1, "查北京天气", thread_id=f"scheduler_{entry.id}")
        assert sent == [(1, "北京晴，20°C")]

    asyncio.run(_case())
