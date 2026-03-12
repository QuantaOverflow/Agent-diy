"""BDD steps for Gmail astrology digest behavior."""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.core.agent import create_agent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "gmail_astrology.feature"))

SAMPLE_EMAIL_BODY = """
Today's Horoscope
The planets align in your favor today. Jupiter brings expansion.

Cosmic Musings
The universe whispers of transformation and growth.

Today's Affirmation
I am open to receiving abundance in all forms.
"""


@pytest.fixture
def astrology_context():
    return {
        "agent": None,
        "thread_id": "gmail-astrology-thread",
        "response": "",
    }


@pytest.fixture
def tool_context():
    return {"body": "", "result": "", "sections": ()}


@given("Gmail credentials are configured")
def given_gmail_credentials_configured():
    creds = Path("credentials.json")
    token = Path("token.json")
    if not creds.exists() and not token.exists():
        pytest.skip("Gmail credentials not configured")


@given("a running agent")
def given_running_agent(astrology_context):
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    if not dashscope_api_key:
        pytest.skip("DASHSCOPE_API_KEY not set")

    model = ChatOpenAI(
        api_key=dashscope_api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )
    astrology_context["agent"] = create_agent(model=model)


@when(parsers.parse('I ask "{text}"'))
def when_i_ask(astrology_context, text):
    result = astrology_context["agent"].invoke(
        {"messages": [HumanMessage(content=text)]},
        config={"configurable": {"thread_id": astrology_context["thread_id"]}},
    )
    content = result["messages"][-1].content
    astrology_context["response"] = content if isinstance(content, str) else str(content)


@then("the response should contain astrology content")
def then_response_should_contain_astrology_content(astrology_context):
    response = astrology_context["response"]
    assert re.search(r"(星座|运势|行星|宇宙|占星|格言|木星|土星|水星|金星|火星|能量)", response)


@then("the response should be in Chinese")
def then_response_should_be_in_chinese(astrology_context):
    response = astrology_context["response"]
    assert re.search(r"[\u4e00-\u9fff]", response)


@then("the response should indicate which date the email is from")
def then_response_should_indicate_email_date(astrology_context):
    response = astrology_context["response"]
    assert re.search(r"\d{1,4}[年/-]\d{1,2}[月/-]\d{1,2}", response) or re.search(
        r"\d{1,2}月\d{1,2}日", response
    )


@then("the response should not contain astrology content")
def then_response_should_not_contain_astrology_content(astrology_context):
    response = astrology_context["response"]
    assert not re.search(r"(星座|运势|行星|宇宙|占星|格言|木星|土星|水星|金星|火星|能量)", response)


@then("the response should inform that no email was found for that date")
def then_response_should_inform_no_email_found(astrology_context):
    response = astrology_context["response"]
    assert re.search(r"(未找到|没有找到|找不到|不存在|无邮件)", response)


@given("an email body containing all three astrology sections")
def given_email_body_with_sections(tool_context):
    tool_context["body"] = SAMPLE_EMAIL_BODY


@when("the tool parses the email body")
def when_tool_parses_body(tool_context):
    from agent_diy.tools.gmail_astrology import _extract_sections

    tool_context["sections"] = _extract_sections(tool_context["body"])


@then("the horoscope section should not be empty")
def then_horoscope_not_empty(tool_context):
    assert tool_context["sections"][0] != ""


@then("the cosmic musings section should not be empty")
def then_musings_not_empty(tool_context):
    assert tool_context["sections"][1] != ""


@then("the affirmation section should not be empty")
def then_affirmation_not_empty(tool_context):
    assert tool_context["sections"][2] != ""


@given("Gmail credentials are not configured")
def given_no_credentials(tool_context):
    _ = tool_context


@when("I call the astrology email tool")
def when_call_tool(tool_context):
    with patch("agent_diy.tools.gmail_astrology.Path.exists", return_value=False):
        from agent_diy.tools.gmail_astrology import get_astrology_email

        tool_context["result"] = get_astrology_email.func()


@then("the tool result should indicate service unavailable")
def then_result_unavailable(tool_context):
    assert "暂不可用" in tool_context["result"]


@given("Gmail returns no emails for the requested date")
def given_no_emails_for_date(tool_context):
    _ = tool_context


@given(parsers.parse('today is "{today_date}" in Beijing and expected newsletter date is "{expected_date}"'))
def given_today_and_expected_date(tool_context, today_date, expected_date):
    tool_context["today"] = today_date
    tool_context["expected_newsletter_date"] = expected_date


@when(parsers.parse('I call the astrology email tool with date "{date}"'))
def when_call_tool_with_date(tool_context, date):
    mock_api = MagicMock()
    mock_search = MagicMock()
    mock_search.invoke.return_value = []
    mock_toolkit = MagicMock()
    mock_toolkit.get_tools.return_value = [mock_search]

    with patch("agent_diy.tools.gmail_astrology.Path.exists", return_value=True), patch(
        "langchain_google_community.gmail.utils.build_resource_service", return_value=mock_api
    ), patch("langchain_google_community.GmailToolkit", return_value=mock_toolkit), patch(
        "agent_diy.tools.gmail_astrology._tool_by_name",
        side_effect=lambda _tools, name: mock_search if name == "search_gmail" else MagicMock(),
    ):
        from agent_diy.tools.gmail_astrology import get_astrology_email

        tool_context["result"] = get_astrology_email.func(date=date)


@when("I call the astrology email tool without date")
def when_call_tool_without_date(tool_context):
    mock_api = MagicMock()
    mock_search = MagicMock()
    mock_search.name = "search_gmail"
    captured_queries = []

    today = tool_context.get("today", "2026-03-12")
    expected = tool_context.get("expected_newsletter_date", "2026-03-11")
    stale_date = tool_context.get("stale_email_date")

    def _capture_search(payload):
        query = payload.get("query", "")
        captured_queries.append(query)
        if stale_date:
            from datetime import datetime as _dt
            exp_fmt = _dt.strptime(expected, "%Y-%m-%d").strftime("%Y/%m/%d")
            if f"after:{exp_fmt}" in query:
                return []
        return [{"id": "msg-1"}]

    mock_search.invoke.side_effect = _capture_search
    mock_toolkit = MagicMock()
    mock_toolkit.get_tools.return_value = [mock_search]

    with (
        patch("agent_diy.tools.gmail_astrology.Path.exists", return_value=True),
        patch("langchain_google_community.gmail.utils.build_resource_service", return_value=mock_api),
        patch("langchain_google_community.GmailToolkit", return_value=mock_toolkit),
        patch(
            "agent_diy.tools.gmail_astrology._tool_by_name",
            side_effect=lambda _tools, name: mock_search if name == "search_gmail" else MagicMock(),
        ),
        patch(
            "agent_diy.tools.gmail_astrology._today_and_expected_newsletter_date",
            return_value=(today, expected),
        ),
        patch("agent_diy.tools.gmail_astrology._get_body_from_api", return_value=SAMPLE_EMAIL_BODY),
        patch(
            "agent_diy.tools.gmail_astrology._extract_date_from_metadata",
            return_value=stale_date if stale_date else expected,
        ),
    ):
        from agent_diy.tools.gmail_astrology import get_astrology_email

        tool_context["result"] = get_astrology_email.func()
        tool_context["search_queries"] = captured_queries


@then("the tool result should indicate no email was found for that date")
def then_result_not_found(tool_context):
    assert re.search(r"未找到", tool_context["result"])


@then(parsers.parse('the search query should target date "{expected_date}"'))
def then_search_query_targets_date(tool_context, expected_date):
    from datetime import datetime, timedelta

    dt = datetime.strptime(expected_date, "%Y-%m-%d")
    date_fmt = dt.strftime("%Y/%m/%d")
    next_day = (dt + timedelta(days=1)).strftime("%Y/%m/%d")
    expected_pattern = f"after:{date_fmt} before:{next_day}"
    queries = tool_context.get("search_queries", [])
    assert any(expected_pattern in q for q in queries), (
        f"Expected query containing '{expected_pattern}', got: {queries}"
    )


@then("the response date should be within two days of today")
def then_response_date_within_two_days(astrology_context):
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    response = astrology_context["response"]
    today_bj = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    match = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", response)
    assert match, f"No date found in response: {response[:200]}"
    found_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    diff = abs((today_bj - found_date).days)
    assert diff <= 2, f"Date {found_date} is {diff} days from today {today_bj}, expected ≤ 2"


@given(parsers.parse('an email metadata Date header "{header_value}"'))
def given_email_metadata_header(tool_context, header_value):
    tool_context["date_header"] = header_value


@when("the tool extracts the date from metadata")
def when_tool_extracts_date_from_metadata(tool_context):
    mock_api = MagicMock()
    mock_api.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "payload": {
            "headers": [{"name": "Date", "value": tool_context["date_header"]}]
        }
    }
    from agent_diy.tools.gmail_astrology import _extract_date_from_metadata
    tool_context["extracted_date"] = _extract_date_from_metadata(mock_api, "msg-1")


@then(parsers.parse('the extracted date should be "{expected_date}"'))
def then_extracted_date_should_be(tool_context, expected_date):
    assert tool_context["extracted_date"] == expected_date, (
        f"Expected {expected_date}, got {tool_context['extracted_date']}"
    )


@given(parsers.parse('the primary search returns no results but a stale email dated "{stale_date}" exists'))
def given_stale_email_exists(tool_context, stale_date):
    tool_context["stale_email_date"] = stale_date


@then(parsers.parse('the tool result should warn about stale email dated "{stale_date}"'))
def then_result_warns_stale_email(tool_context, stale_date):
    result = tool_context["result"]
    assert "提示" in result, f"Expected warning in result: {result[:200]}"
    assert tool_context["expected_newsletter_date"] in result
    assert stale_date in result
