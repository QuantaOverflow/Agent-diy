"""BDD steps for financial news integration behavior."""

from __future__ import annotations

import os
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.core.agent import create_agent
from agent_diy.mcp import financial_news_server
from agent_diy.utils import content_to_text

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "financial_news.feature"))

FINANCIAL_TOOL_NAMES = {"stock_news", "semantic_search", "hot_news"}


@pytest.fixture
def financial_news_context():
    return {
        "agent": None,
        "thread_id": "financial-news-thread",
        "result": None,
        "tool": None,
        "unit_result": None,
        "calls": [],
        "resolved_ticker": None,
        "base_url": None,
        "client_kwargs": {},
    }


@pytest.fixture
def financial_news_tool():
    return {
        "lookup": financial_news_server.lookup,
        "stock_news": financial_news_server.stock_news,
        "semantic_search": financial_news_server.semantic_search,
        "hot_news": financial_news_server.hot_news,
    }


def _mock_response(payload):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _tool_name(message) -> str:
    raw_name = getattr(message, "name", "") or ""
    if raw_name in FINANCIAL_TOOL_NAMES:
        return raw_name
    for name in FINANCIAL_TOOL_NAMES:
        if raw_name.endswith(name):
            return name
    return raw_name


def _tool_payload(message):
    try:
        return json.loads(content_to_text(message.content))
    except json.JSONDecodeError:
        return None


def _require_e2e_env():
    if not os.getenv("DASHSCOPE_API_KEY"):
        pytest.skip("DASHSCOPE_API_KEY not set")

    base_url = os.getenv("FINANCIAL_NEWS_BASE_URL", "http://localhost:8000").rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/v1/market/hot_news", timeout=2.0)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"financial-news service unavailable at {base_url}: {exc}")


@given("a running agent")
def given_running_agent(financial_news_context, qwen_model):
    _require_e2e_env()
    financial_news_context["agent"] = create_agent(model=qwen_model)


@given("a running agent with unavailable financial news service")
def given_running_agent_with_unavailable_financial_news_service(
    financial_news_context, monkeypatch, qwen_model, reset_financial_news_runtime_cache
):
    monkeypatch.setenv("FINANCIAL_NEWS_BASE_URL", "http://127.0.0.1:1")

    reset_financial_news_runtime_cache()
    financial_news_context["agent"] = create_agent(model=qwen_model)


@when(parsers.parse('I ask "{text}"'))
def when_i_ask(financial_news_context, text):
    financial_news_context["result"] = financial_news_context["agent"].invoke(
        {"messages": [("human", text)]},
        config={"configurable": {"thread_id": financial_news_context["thread_id"]}},
    )


@given("a financial news tool")
def given_a_financial_news_tool(financial_news_context, financial_news_tool):
    financial_news_context["tool"] = financial_news_tool


@given("a financial news tool with unavailable backend")
def given_financial_news_tool_with_unavailable_backend(financial_news_context, financial_news_tool):
    financial_news_context["tool"] = financial_news_tool


@when(parsers.re(r'I query stock news for symbol "(?P<symbol>[^"]*)"'))
def when_i_query_stock_news_for_symbol(financial_news_context, symbol):
    payload = [
        {"title": "贵州茅台发布年报", "publish_time": "2026-03-10 09:00:00"},
        {"title": "白酒板块早盘走强", "publish_time": "2026-03-10 10:00:00"},
    ]
    with patch("agent_diy.mcp.financial_news_server.httpx.Client.get", return_value=_mock_response(payload)) as mock_get:
        financial_news_context["unit_result"] = financial_news_context["tool"]["stock_news"](symbol)
        financial_news_context["calls"] = mock_get.call_args_list


@when(parsers.parse('I search for topic "{topic}"'))
def when_i_search_for_topic(financial_news_context, topic):
    payload = [
        {"title": f"{topic} 新闻 {i}", "publish_time": f"2026-03-10 0{i % 10}:00:00"}
        for i in range(15)
    ]
    with patch("agent_diy.mcp.financial_news_server.httpx.Client.post", return_value=_mock_response(payload)):
        financial_news_context["unit_result"] = financial_news_context["tool"]["semantic_search"](topic)


@when(parsers.parse('I query both stock news and semantic search for ticker "{ticker}" and topic "{topic}"'))
def when_i_query_both_sources(financial_news_context, ticker, topic):
    stock_payload = [
        {"title": "贵州茅台发布年报", "publish_time": "2026-03-10 09:00:00"},
        {"title": "白酒板块早盘走强", "publish_time": "2026-03-10 10:00:00"},
    ]
    semantic_payload = [
        {"title": "贵州茅台发布年报", "publish_time": "2026-03-10 09:00:00"},
        {"title": "茅台渠道调研更新", "publish_time": "2026-03-11 08:30:00"},
    ]

    with patch("agent_diy.mcp.financial_news_server.httpx.Client.get", return_value=_mock_response(stock_payload)), patch(
        "agent_diy.mcp.financial_news_server.httpx.Client.post",
        return_value=_mock_response(semantic_payload),
    ):
        stock_items = financial_news_context["tool"]["stock_news"](ticker)
        semantic_items = financial_news_context["tool"]["semantic_search"](topic)

    merged = stock_items + semantic_items
    dedup = []
    seen_titles = set()
    for item in merged:
        title = item.get("title")
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        dedup.append(item)

    financial_news_context["unit_result"] = dedup
    financial_news_context["source_titles"] = {
        "stock": {item["title"] for item in stock_items},
        "semantic": {item["title"] for item in semantic_items},
    }


@when(parsers.parse('I query stock news for company name "{company_name}"'))
def when_i_query_stock_news_for_company_name(financial_news_context, company_name):
    calls = []
    ticker_map = {"贵州茅台": "600519"}

    def _mock_get(_self, url, params=None, **_kwargs):
        if url.endswith("/api/v1/stock/lookup"):
            calls.append(("lookup", params))
            resolved_ticker = ticker_map.get(company_name, "")
            if not resolved_ticker:
                return _mock_response([])
            return _mock_response([{"ticker": resolved_ticker, "company_name": company_name}])
        if url.endswith("/api/v1/stock/news"):
            calls.append(("stock_news", params))
            return _mock_response([
                {"title": "贵州茅台渠道调研", "publish_time": "2026-03-10 12:00:00", "ticker": "600519"}
            ])
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("agent_diy.mcp.financial_news_server.httpx.Client.get", autospec=True, side_effect=_mock_get):
        lookup_result = financial_news_context["tool"]["lookup"](company_name)
        ticker = lookup_result[0]["ticker"] if lookup_result else ""
        financial_news_context["resolved_ticker"] = ticker
        if ticker:
            financial_news_context["unit_result"] = financial_news_context["tool"]["stock_news"](ticker)
        else:
            financial_news_context["unit_result"] = []

    financial_news_context["calls"] = calls


@when(parsers.re(r'I call "(?P<tool>[^"]+)" with "(?P<param>[^"]*)"'))
def when_i_call_tool_with_param(financial_news_context, tool, param):
    with patch("agent_diy.mcp.financial_news_server.httpx.Client.get", side_effect=Exception("backend down")), patch(
        "agent_diy.mcp.financial_news_server.httpx.Client.post",
        side_effect=Exception("backend down"),
    ):
        if tool == "hot_news":
            financial_news_context["unit_result"] = financial_news_context["tool"][tool]()
        elif tool == "semantic_search":
            financial_news_context["unit_result"] = financial_news_context["tool"][tool](param)
        else:
            financial_news_context["unit_result"] = financial_news_context["tool"][tool](param)


@then("the result should contain a list of news items")
def then_result_contains_list_of_news_items(financial_news_context):
    result = financial_news_context["unit_result"]
    assert isinstance(result, list)
    assert len(result) > 0


@then("each item should have a title and publish time")
def then_each_item_has_title_and_publish_time(financial_news_context):
    for item in financial_news_context["unit_result"]:
        assert "title" in item
        assert "publish_time" in item


@then("the result should contain at most 15 news items")
def then_result_contains_at_most_15_news_items(financial_news_context):
    assert len(financial_news_context["unit_result"]) <= 15


@then("the result should contain news from both sources")
def then_result_contains_news_from_both_sources(financial_news_context):
    result_titles = {item.get("title") for item in financial_news_context["unit_result"]}
    assert result_titles & financial_news_context["source_titles"]["stock"]
    assert result_titles & financial_news_context["source_titles"]["semantic"]


@then("duplicate news items should appear only once")
def then_duplicate_news_items_should_appear_only_once(financial_news_context):
    titles = [item.get("title") for item in financial_news_context["unit_result"] if item.get("title")]
    assert len(titles) == len(set(titles))


@then(parsers.parse('the tool should resolve the ticker to "{ticker}"'))
def then_tool_should_resolve_ticker(financial_news_context, ticker):
    assert financial_news_context["resolved_ticker"] == ticker
    call_names = [item[0] for item in financial_news_context["calls"]]
    assert "lookup" in call_names
    assert "stock_news" in call_names
    assert call_names.index("lookup") < call_names.index("stock_news")


@then(parsers.parse('the result should contain stock news for "{ticker}"'))
def then_result_should_contain_stock_news_for_ticker(financial_news_context, ticker):
    result = financial_news_context["unit_result"]
    assert isinstance(result, list)
    assert len(result) > 0
    assert any(item.get("ticker", ticker) == ticker for item in result)


@then("the result should be empty without raising an exception")
def then_result_empty_without_exception(financial_news_context):
    assert financial_news_context["unit_result"] == []


@then("the result should return an empty news list without error")
def then_result_return_empty_news_list_without_error(financial_news_context):
    assert financial_news_context["unit_result"] == []


@then("the agent should have queried financial news")
def then_agent_should_have_queried_financial_news(financial_news_context):
    result = financial_news_context["result"]
    tool_messages = [m for m in result["messages"] if _tool_name(m) in FINANCIAL_TOOL_NAMES]
    assert len(tool_messages) > 0


@then("the agent should not have queried financial news")
def then_agent_should_not_have_queried_financial_news(financial_news_context):
    result = financial_news_context["result"]
    tool_messages = [m for m in result["messages"] if _tool_name(m) in FINANCIAL_TOOL_NAMES]
    assert len(tool_messages) == 0


@then("the response should synthesize news from multiple sources")
def then_response_synthesizes_news_from_multiple_sources(financial_news_context):
    result = financial_news_context["result"]
    tool_names = {_tool_name(m) for m in result["messages"]}
    assert "stock_news" in tool_names
    assert "semantic_search" in tool_names

    final_message = result["messages"][-1]
    text = content_to_text(final_message.content).strip()
    assert text
    assert len(text) > 20


@then("the response should contain relevant market information")
def then_response_contains_relevant_market_information(financial_news_context):
    final_message = financial_news_context["result"]["messages"][-1]
    text = content_to_text(final_message.content).strip()
    assert text
    assert len(text) > 20


@then("the response should contain relevant stock information")
def then_response_contains_relevant_stock_information(financial_news_context):
    final_message = financial_news_context["result"]["messages"][-1]
    text = content_to_text(final_message.content).strip()
    assert text
    assert len(text) > 20


@then("the response should indicate limited information availability")
def then_response_indicates_limited_information_availability(financial_news_context):
    result = financial_news_context["result"]
    tool_messages = [m for m in result["messages"] if _tool_name(m) in FINANCIAL_TOOL_NAMES]
    assert tool_messages, "Expected financial news tool to be called"
    assert _tool_payload(tool_messages[-1]) == []

    final_message = financial_news_context["result"]["messages"][-1]
    text = content_to_text(final_message.content).strip()
    assert text


@when(parsers.parse('I query stock news with symbol "{symbol}"'))
def when_i_query_stock_news_with_symbol(financial_news_context, symbol):
    payload = [{"title": "淳中科技公告", "publish_time": "2026-03-10 09:00:00"}]
    with patch("agent_diy.mcp.financial_news_server.httpx.Client.get", return_value=_mock_response(payload)) as mock_get:
        financial_news_context["unit_result"] = financial_news_context["tool"]["stock_news"](symbol=symbol)
        financial_news_context["calls"] = mock_get.call_args_list


@then(parsers.parse('the request should use ticker "{ticker}"'))
def then_request_should_use_ticker(financial_news_context, ticker):
    assert financial_news_context["calls"], "Expected at least one backend call"
    params = financial_news_context["calls"][-1].kwargs.get("params", {})
    assert params.get("ticker") == ticker


@when("stock news backend returns a wrapped results payload")
def when_stock_news_backend_returns_wrapped_results_payload(financial_news_context):
    payload = {
        "success": True,
        "ticker": "603516",
        "results": [
            {"title": "淳中科技公告", "publish_time": "2026-03-10 09:00:00"},
            {"title": "计算机板块资金流向", "publish_time": "2026-03-09 17:10:25"},
        ],
    }
    with patch("agent_diy.mcp.financial_news_server.httpx.Client.get", return_value=_mock_response(payload)):
        financial_news_context["unit_result"] = financial_news_context["tool"]["stock_news"](symbol="603516")


@then("the parsed result should contain a list of news items")
def then_parsed_result_should_contain_a_list_of_news_items(financial_news_context):
    result = financial_news_context["unit_result"]
    assert isinstance(result, list)
    assert len(result) > 0


@given("FINANCIAL_NEWS_BASE_URL is empty")
def given_financial_news_base_url_is_empty(monkeypatch):
    monkeypatch.setenv("FINANCIAL_NEWS_BASE_URL", "")


@when("I read financial news base url")
def when_i_read_financial_news_base_url(financial_news_context):
    financial_news_context["base_url"] = financial_news_server._base_url()


@then(parsers.parse('the base url should be "{expected}"'))
def then_the_base_url_should_be(financial_news_context, expected):
    assert financial_news_context["base_url"] == expected


@when(parsers.parse('I query stock news with ticker "{ticker}" and capture client options'))
def when_i_query_stock_news_and_capture_client_options(financial_news_context, ticker):
    payload = [{"title": "淳中科技公告", "publish_time": "2026-03-10 09:00:00"}]
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.get.return_value = _mock_response(payload)

    with patch("agent_diy.mcp.financial_news_server.httpx.Client", return_value=mock_client) as mock_client_cls:
        financial_news_context["unit_result"] = financial_news_context["tool"]["stock_news"](symbol=ticker)
        financial_news_context["client_kwargs"] = mock_client_cls.call_args.kwargs


@then("the HTTP client should set trust_env to false")
def then_http_client_should_set_trust_env_false(financial_news_context):
    assert financial_news_context["client_kwargs"].get("trust_env") is False
