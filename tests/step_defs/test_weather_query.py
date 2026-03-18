"""BDD steps for weather query behavior."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import requests
from langchain_core.messages import HumanMessage
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.core.agent import create_agent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "weather_query.feature"))


@pytest.fixture
def weather_context():
    return {
        "agent": None,
        "thread_id": "weather-query-thread",
        "response": "",
    }


@given("a running agent")
def given_running_agent(weather_context, qwen_model):
    qweather_api_key = os.getenv("QWEATHER_API_KEY")
    qweather_api_host = os.getenv("QWEATHER_API_HOST")
    if not qweather_api_key:
        pytest.skip("QWEATHER_API_KEY not set")
    if not qweather_api_host:
        pytest.skip("QWEATHER_API_HOST not set")

    # Preflight QWeather availability to avoid false negatives caused by
    # invalid key/host/network issues in the local environment.
    try:
        preflight = requests.get(
            f"https://{qweather_api_host}/v7/weather/now",
            params={"location": "101010100"},
            headers={"X-QW-Api-Key": qweather_api_key},
            timeout=10,
        )
        if preflight.status_code != 200:
            pytest.skip(f"QWeather unavailable: HTTP {preflight.status_code}")
    except requests.RequestException as exc:
        pytest.skip(f"QWeather unavailable: {exc}")

    weather_context["agent"] = create_agent(model=qwen_model)


@when(parsers.parse('I ask "{text}"'))
def when_i_ask(weather_context, text):
    result = weather_context["agent"].invoke(
        {"messages": [HumanMessage(content=text)]},
        config={"configurable": {"thread_id": weather_context["thread_id"]}},
    )
    content = result["messages"][-1].content
    weather_context["response"] = content if isinstance(content, str) else str(content)


@then("the response should contain weather information")
def then_response_contains_weather_info(weather_context):
    assert re.search(r"(℃|度|摄氏)", weather_context["response"])


@then("the response should not contain weather information")
def then_response_should_not_contain_weather_info(weather_context):
    assert not re.search(r"(℃|度|摄氏)", weather_context["response"])


@then(parsers.parse('the response should mention "{expected}"'))
def then_response_should_mention(weather_context, expected):
    assert expected in weather_context["response"]


@then("the response should contain weather forecast information")
def then_response_contains_weather_forecast_info(weather_context):
    response = weather_context["response"]
    has_temperature = re.search(r"(℃|度|摄氏)", response)
    has_weather_text = re.search(r"(晴|阴|雨|雪|风|多云|雾|霾|雷)", response)
    assert has_temperature and has_weather_text


@then("the response should not be a guess from current weather")
def then_response_should_not_be_guess_from_current_weather(weather_context):
    response = weather_context["response"]
    # Forecast responses should include explicit future date/time cues.
    has_future_cue = re.search(
        r"(今晚|今夜|明天|后天|未来|预报|\d{4}-\d{2}-\d{2})",
        response,
    )
    assert has_future_cue


@then("the response should contain sunrise sunset information")
def then_response_contains_sunrise_sunset_info(weather_context):
    response = weather_context["response"]
    has_sunrise_or_sunset = re.search(r"(日出|日落|sunrise|sunset)", response, re.IGNORECASE)
    has_time_text = re.search(r"(\d{1,2}:\d{2})", response)
    assert has_sunrise_or_sunset and has_time_text


@then("the response should contain weather metric information")
def then_response_contains_weather_metric_info(weather_context):
    response = weather_context["response"]
    has_metric = re.search(r"(湿度|体感|风力|风速|%|级|hPa|能见度)", response)
    has_numeric = re.search(r"\d+", response)
    assert has_metric and has_numeric
