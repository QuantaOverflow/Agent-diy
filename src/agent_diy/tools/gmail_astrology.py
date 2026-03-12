"""Gmail tool for fetching and formatting the latest astrology newsletter."""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

ASTROLOGY_SENDER = "authority-astrology@mail.beehiiv.com"
SECTION_TODAY_HOROSCOPE = "Today's Horoscope"
SECTION_COSMIC_MUSINGS = "Cosmic Musings"
SECTION_TODAY_AFFIRMATION = "Today's Affirmation"


def _normalize_text(text: str) -> str:
    normalized = text.replace("’", "'").replace("\r\n", "\n")
    for title in (
        SECTION_TODAY_HOROSCOPE,
        SECTION_COSMIC_MUSINGS,
        SECTION_TODAY_AFFIRMATION,
    ):
        normalized = normalized.replace(f"**{title}**", title)
        normalized = normalized.replace(f"__{title}__", title)
    return normalized


def _extract_section(text: str, title: str, next_titles: list[str]) -> str:
    if next_titles:
        next_pattern = "|".join(re.escape(item) for item in next_titles)
        end_pattern = rf"(?=(?:\n\s*(?:#+\s*)?\**(?:{next_pattern})\**\s*:?)|\Z)"
    else:
        end_pattern = r"(?=\Z)"
    pattern = (
        rf"(?:^|\n)\s*(?:#+\s*)?\**{re.escape(title)}\**\s*:?\s*\n+"
        rf"(?:[-—_]+\s*)*(.*?){end_pattern}"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_sections(body: str) -> tuple[str, str, str]:
    normalized = _normalize_text(body)
    horoscope = _extract_section(
        normalized,
        SECTION_TODAY_HOROSCOPE,
        [SECTION_COSMIC_MUSINGS, SECTION_TODAY_AFFIRMATION],
    )
    musings = _extract_section(
        normalized,
        SECTION_COSMIC_MUSINGS,
        [SECTION_TODAY_AFFIRMATION],
    )
    affirmation = _extract_section(normalized, SECTION_TODAY_AFFIRMATION, [])
    return horoscope, musings, affirmation


def _tool_by_name(tools: list[Any], name: str) -> Any | None:
    for item in tools:
        if getattr(item, "name", "") == name:
            return item
    return None


def _decode_payload(payload: dict[str, Any]) -> str:
    """Recursively extract text/plain body from Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = (payload.get("body") or {}).get("data", "")
        if data:
            padding = "=" * (-len(data) % 4)
            return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
    for part in payload.get("parts") or []:
        if not isinstance(part, dict):
            continue
        result = _decode_payload(part)
        if result:
            return result
    return ""


def _get_body_from_api(api_resource: Any, message_id: str) -> str:
    message = (
        api_resource.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = message.get("payload", {}) if isinstance(message, dict) else {}
    if not isinstance(payload, dict):
        return ""
    return _decode_payload(payload)


def _search_query_for_date(date: str) -> str:
    dt = datetime.strptime(date, "%Y-%m-%d")
    next_day = (dt + timedelta(days=1)).strftime("%Y/%m/%d")
    date_fmt = dt.strftime("%Y/%m/%d")
    return f"from:{ASTROLOGY_SENDER} after:{date_fmt} before:{next_day}"


def _today_and_expected_newsletter_date() -> tuple[str, str]:
    now_bj = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    today = now_bj.strftime("%Y-%m-%d")
    expected_newsletter_date = (now_bj - timedelta(days=1)).strftime("%Y-%m-%d")
    return today, expected_newsletter_date


def _extract_date_from_metadata(api_resource: Any, message_id: str) -> str:
    payload = (
        api_resource.users()
        .messages()
        .get(userId="me", id=message_id, format="metadata", metadataHeaders=["Date"])
        .execute()
    )
    headers = (
        ((payload.get("payload") or {}).get("headers")) or []
        if isinstance(payload, dict)
        else []
    )
    for header in headers:
        if not isinstance(header, dict):
            continue
        if (header.get("name") or "").lower() != "date":
            continue
        raw_value = header.get("value")
        if not raw_value:
            continue
        try:
            dt = parsedate_to_datetime(raw_value)
            return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            continue
    return ""


def _format_result(date_text: str, horoscope: str, musings: str, affirmation: str) -> str:
    final_date = date_text or datetime.now().strftime("%Y-%m-%d")
    return (
        f"邮件日期：{final_date}\n"
        f"{SECTION_TODAY_HOROSCOPE}:\n{horoscope or '未提取到该章节。'}\n\n"
        f"{SECTION_COSMIC_MUSINGS}:\n{musings or '未提取到该章节。'}\n\n"
        f"{SECTION_TODAY_AFFIRMATION}:\n{affirmation or '未提取到该章节。'}"
    )


@tool
def get_astrology_email(date: str = "") -> str:
    """Fetch astrology newsletter from Gmail. date: optional YYYY-MM-DD to query a specific date's email."""

    credentials = Path("credentials.json")
    token = Path("token.json")
    if not credentials.exists() or not token.exists():
        return "Gmail 服务暂不可用：未找到认证文件。"

    try:
        from langchain_google_community import GmailToolkit
        from langchain_google_community.gmail.utils import build_resource_service
    except ImportError:
        return "Gmail 服务暂不可用：缺少依赖 langchain-google-community[gmail]。"

    try:
        api_resource = build_resource_service()
        toolkit = GmailToolkit(api_resource=api_resource)
        toolkit_tools = toolkit.get_tools()
        search_tool = _tool_by_name(toolkit_tools, "search_gmail")
        if search_tool is None:
            return "Gmail 服务暂不可用：工具初始化失败。"

        if date:
            try:
                query = _search_query_for_date(date)
            except ValueError:
                return "date 参数格式错误，应为 YYYY-MM-DD。"
            results = search_tool.invoke({"query": query, "max_results": 5})
            if not isinstance(results, list) or not results:
                return f"未找到 {date} 的星座订阅邮件。"
        else:
            today, expected_newsletter_date = _today_and_expected_newsletter_date()
            expected_query = _search_query_for_date(expected_newsletter_date)
            results = search_tool.invoke({"query": expected_query, "max_results": 5})
            expected_date_missing = not isinstance(results, list) or not results
            if expected_date_missing:
                results = search_tool.invoke(
                    {"query": f"from:{ASTROLOGY_SENDER} newer_than:2d", "max_results": 5}
                )
                if not results:
                    results = search_tool.invoke(
                        {"query": f"from:{ASTROLOGY_SENDER}", "max_results": 5}
                    )
        if not isinstance(results, list) or not results:
            return f"未找到来自 {ASTROLOGY_SENDER} 的星座订阅邮件。"

        latest = results[0]
        message_id = latest.get("id") if isinstance(latest, dict) else None
        if not message_id:
            return f"未找到来自 {ASTROLOGY_SENDER} 的星座订阅邮件。"

        body = _get_body_from_api(api_resource, message_id)
        if not body:
            return "Gmail 服务返回的邮件正文为空，请稍后重试。"

        email_date = _extract_date_from_metadata(api_resource, message_id)
        horoscope, musings, affirmation = _extract_sections(body)
        formatted = _format_result(email_date, horoscope, musings, affirmation)

        if not date and email_date and email_date != expected_newsletter_date:
            return (
                f"提示：未找到 {today} 对应的星座邮件（按时差应对应 {expected_newsletter_date}），"
                f"当前最新邮件日期为 {email_date}（PT）。\n"
                f"{formatted}"
            )

        return formatted
    except Exception as exc:  # noqa: BLE001 - degrade gracefully in tool runtime
        return f"Gmail 服务暂不可用：{exc}。"
