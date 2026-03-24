from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from agent_diy.reminder_store import Reminder, ReminderStore

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """APScheduler AsyncIOScheduler 封装。"""

    def __init__(
        self,
        store: ReminderStore,
        backend,
        send_callback: Callable[[int, str], Awaitable[None]],
    ):
        self._store = store
        self._backend = backend
        self._send_callback = send_callback
        self._scheduler = AsyncIOScheduler()

        store.on_add = self._on_add
        store.on_cancel = self._on_cancel

    def _on_add(self, entry: Reminder) -> None:
        """调度失败时 raise，让 store.add() 回滚。"""
        try:
            if entry.schedule_type == "once":
                if entry.run_at is None:
                    raise ValueError("一次性提醒缺少 run_at")
                trigger = DateTrigger(run_date=entry.run_at, timezone="Asia/Shanghai")
            else:
                h, m = map(int, entry.time_str.split(":"))
                trigger = CronTrigger(hour=h, minute=m, timezone="Asia/Shanghai")
            self._scheduler.add_job(
                self._fire,
                trigger,
                args=[entry.user_id, entry.task, entry.id],
                id=f"reminder_{entry.id}",
            )
        except Exception as exc:
            raise ValueError(f"调度失败：{exc}") from exc

    def _on_cancel(self, reminder_id: int) -> None:
        try:
            self._scheduler.remove_job(f"reminder_{reminder_id}")
        except Exception:
            pass

    async def _fire(self, user_id: int, task: str, reminder_id: int) -> None:
        entry = self._store.get(reminder_id)
        if entry is None:
            return

        try:
            result = await self._backend.reply(
                user_id,
                task,
                thread_id=f"scheduler_{reminder_id}",
            )
        except Exception:
            result = f"出错：任务执行失败（{task}），请稍后重试"
        await self._send_callback(user_id, result)
        if entry.schedule_type == "once":
            self._store.complete_once(reminder_id)

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
