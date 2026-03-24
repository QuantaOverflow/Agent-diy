from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass
class Reminder:
    id: int
    user_id: int
    task: str
    time_str: str  # daily: "HH:MM"；once: 本地展示时间 "YYYY-MM-DD HH:MM"
    schedule_type: str = "daily"  # "daily" | "once"
    run_at: datetime | None = None
    mode: str = "execute"  # "remind" | "execute"


class ReminderStore:
    def __init__(self):
        self._data: dict[int, list[Reminder]] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self.on_add: Callable[[Reminder], None] | None = None
        self.on_cancel: Callable[[int], None] | None = None

    def add(self, user_id: int, task: str, time_str: str, mode: str = "execute") -> Reminder:
        with self._lock:
            entry = Reminder(
                self._next_id,
                user_id,
                task,
                time_str,
                schedule_type="daily",
                mode=mode,
            )
            self._data.setdefault(user_id, []).append(entry)
            self._next_id += 1
        if self.on_add:
            try:
                self.on_add(entry)
            except Exception:
                with self._lock:
                    self._data[user_id] = [r for r in self._data[user_id] if r.id != entry.id]
                raise
        return entry

    def add_once(self, user_id: int, task: str, run_at: datetime, mode: str = "execute") -> Reminder:
        with self._lock:
            entry = Reminder(
                self._next_id,
                user_id,
                task,
                run_at.strftime("%Y-%m-%d %H:%M"),
                schedule_type="once",
                run_at=run_at,
                mode=mode,
            )
            self._data.setdefault(user_id, []).append(entry)
            self._next_id += 1
        if self.on_add:
            try:
                self.on_add(entry)
            except Exception:
                with self._lock:
                    self._data[user_id] = [r for r in self._data[user_id] if r.id != entry.id]
                raise
        return entry

    def get(self, reminder_id: int) -> Reminder | None:
        with self._lock:
            for reminders in self._data.values():
                for reminder in reminders:
                    if reminder.id == reminder_id:
                        return reminder
        return None

    def list(self, user_id: int) -> list[Reminder]:
        with self._lock:
            return list(self._data.get(user_id, []))

    def cancel(self, user_id: int, reminder_id: int) -> bool:
        with self._lock:
            reminders = self._data.get(user_id, [])
            filtered = [r for r in reminders if r.id != reminder_id]
            removed = len(filtered) < len(reminders)
            if removed:
                self._data[user_id] = filtered
        if removed and self.on_cancel:
            self.on_cancel(reminder_id)
        return removed

    def exists(self, reminder_id: int) -> bool:
        with self._lock:
            return any(r.id == reminder_id for reminders in self._data.values() for r in reminders)

    def complete_once(self, reminder_id: int) -> None:
        with self._lock:
            for user_id, reminders in list(self._data.items()):
                filtered = [r for r in reminders if r.id != reminder_id]
                if len(filtered) < len(reminders):
                    self._data[user_id] = filtered
                    break

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._next_id = 1
