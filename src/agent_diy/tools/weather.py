"""Weather querying tools backed by QWeather API."""

from __future__ import annotations

import os

import requests
from langchain_core.tools import tool

QWEATHER_GEO_PATH = "/geo/v2/city/lookup"
QWEATHER_NOW_PATH = "/v7/weather/now"
QWEATHER_FORECAST_3D_PATH = "/v7/weather/3d"


def _api_url(host: str, path: str) -> str:
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
    else:
        base = f"https://{host.rstrip('/')}"
    return f"{base}{path}"


def _city_to_location_id(city: str, api_key: str, api_host: str) -> str | None:
    response = requests.get(
        _api_url(api_host, QWEATHER_GEO_PATH),
        params={"location": city},
        headers={"X-QW-Api-Key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "200":
        return None
    locations = payload.get("location") or []
    if not locations:
        return None
    return locations[0].get("id")


@tool
def get_current_weather(city: str = "北京") -> str:
    """Get current weather for a city. Defaults to Beijing when city is not specified."""

    api_key = os.getenv("QWEATHER_API_KEY")
    api_host = os.getenv("QWEATHER_API_HOST")
    if not api_key:
        return "天气服务暂不可用：缺少 QWEATHER_API_KEY。"
    if not api_host:
        return "天气服务暂不可用：缺少 QWEATHER_API_HOST。"

    try:
        location_id = _city_to_location_id(city, api_key, api_host)
        if not location_id:
            return f"未找到城市 {city} 的天气信息。"

        response = requests.get(
            _api_url(api_host, QWEATHER_NOW_PATH),
            params={"location": location_id},
            headers={"X-QW-Api-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return "天气服务请求失败，请稍后重试。"

    if payload.get("code") != "200":
        return "天气服务暂时不可用，请稍后重试。"

    now = payload.get("now") or {}
    temperature = now.get("temp")
    weather_text = now.get("text")

    if temperature is None or not weather_text:
        return "天气服务返回数据不完整，请稍后再试。"

    return f"{city}当前天气：{weather_text}，气温 {temperature}℃。"


@tool
def get_weather_forecast(city: str = "北京") -> str:
    """Get 3-day weather forecast for a city. Defaults to Beijing."""

    api_key = os.getenv("QWEATHER_API_KEY")
    api_host = os.getenv("QWEATHER_API_HOST")
    if not api_key:
        return "天气预报服务暂不可用：缺少 QWEATHER_API_KEY。"
    if not api_host:
        return "天气预报服务暂不可用：缺少 QWEATHER_API_HOST。"

    try:
        location_id = _city_to_location_id(city, api_key, api_host)
        if not location_id:
            return f"未找到城市 {city} 的天气预报信息。"

        response = requests.get(
            _api_url(api_host, QWEATHER_FORECAST_3D_PATH),
            params={"location": location_id},
            headers={"X-QW-Api-Key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return "天气预报服务请求失败，请稍后重试。"

    if payload.get("code") != "200":
        return "天气预报服务暂时不可用，请稍后重试。"

    daily = payload.get("daily") or []
    if not daily:
        return "天气预报服务返回数据不完整，请稍后再试。"

    lines = []
    for item in daily[:3]:
        date = item.get("fxDate")
        text_day = item.get("textDay")
        temp_max = item.get("tempMax")
        temp_min = item.get("tempMin")
        if not date or not text_day or temp_max is None or temp_min is None:
            continue
        lines.append(f"{date}：{text_day}，{temp_min}~{temp_max}℃")

    if not lines:
        return "天气预报服务返回数据不完整，请稍后再试。"

    return f"{city}未来三天天气预报：{'；'.join(lines)}。"
