from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import tool as lc_tool

from agent_diy.reminder_store import ReminderStore


def make_reminder_tools(store: ReminderStore) -> list:
    """为指定 store 实例创建三个 reminder 工具（闭包绑定，无全局状态）。"""

    @lc_tool
    def set_reminder(
        user_id: int,
        task: str,
        time_str: str | None = None,
        after_minutes: int | None = None,
        mode: str = "execute",
    ) -> str:
        """设置定时提醒（北京时间），支持每日固定时间或一次性相对时间。

        Args:
            user_id: 当前用户 ID（从系统消息中获取）
            task: 要执行的任务描述，如"查北京天气"
            time_str: 每天触发的时间，格式 HH:MM（24小时制），如 "09:00" 或 "20:30"
            after_minutes: 一次性提醒，N 分钟后触发（正整数）
            mode: 到时执行模式。"remind"=发固定提醒文案；"execute"=由 AI 执行任务并返回结果。
                LLM 应根据用户意图填写：如“提醒我喝水”用 "remind"，如“帮我查天气”用 "execute"。
        """
        if time_str and after_minutes is not None:
            return "请只提供一种时间：time_str（每日）或 after_minutes（一次性）。"

        try:
            if after_minutes is not None:
                if after_minutes <= 0:
                    return "after_minutes 必须是正整数。"
                tz = ZoneInfo("Asia/Shanghai")
                run_at = datetime.now(tz) + timedelta(minutes=after_minutes)
                entry = store.add_once(user_id, task, run_at, mode=mode)
                return (
                    f"已为您设置一次性提醒（ID: {entry.id}）："
                    f"{entry.time_str}（北京时间）执行：{task}"
                )

            if not time_str:
                return "请提供提醒时间（HH:MM）或 after_minutes。"
            h, m = map(int, time_str.split(":"))
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
            entry = store.add(user_id, task, time_str, mode=mode)
        except Exception as exc:
            return f"提醒设置失败：{exc}"
        return f"已为您设置提醒（ID: {entry.id}）：每天 {time_str}（北京时间）执行：{task}"

    @lc_tool
    def list_reminders(user_id: int) -> str:
        """列出用户的所有定时提醒。

        Args:
            user_id: 当前用户 ID
        """
        reminders = store.list(user_id)
        if not reminders:
            return "您当前没有设置任何提醒。"
        lines = []
        for r in reminders:
            if r.schedule_type == "once":
                lines.append(f"{r.id}. 一次性 {r.time_str} → {r.task}")
            else:
                lines.append(f"{r.id}. 每天 {r.time_str} → {r.task}")
        return "您的提醒列表：\n" + "\n".join(lines)

    @lc_tool
    def cancel_reminder(user_id: int, reminder_id: int) -> str:
        """取消指定的定时提醒。

        Args:
            user_id: 当前用户 ID
            reminder_id: 提醒 ID（可通过 list_reminders 查询）
        """
        if store.cancel(user_id, reminder_id):
            return f"已取消提醒 ID {reminder_id}。"
        return f"未找到提醒 ID {reminder_id}，请用查看提醒确认 ID 是否正确。"

    @lc_tool
    def cancel_reminder_by_task(user_id: int, task_keyword: str) -> str:
        """按任务关键词取消提醒（用于用户未提供 reminder_id 的自然语言取消场景）。

        Args:
            user_id: 当前用户 ID
            task_keyword: 任务关键词，例如“天气”“喝水”
        """
        keyword = (task_keyword or "").strip()
        if not keyword:
            return "请提供要取消的提醒关键词。"
        reminders = store.list(user_id)
        for reminder in reminders:
            if keyword in reminder.task:
                store.cancel(user_id, reminder.id)
                return f"已取消提醒 ID {reminder.id}。"
        return f"未找到包含“{keyword}”的提醒。"

    return [set_reminder, list_reminders, cancel_reminder, cancel_reminder_by_task]
