"""Weather querying tools backed by QWeather API."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from langchain_core.tools import tool

QWEATHER_GEO_PATH = "/geo/v2/city/lookup"
QWEATHER_NOW_PATH = "/v7/weather/now"
QWEATHER_FORECAST_3D_PATH = "/v7/weather/3d"
QWEATHER_SUN_PATH = "/v7/astronomy/sun"


class _QWeatherConfigError(Exception):
    pass


def _api_url(host: str, path: str) -> str:
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
    else:
        base = f"https://{host.rstrip('/')}"
    return f"{base}{path}"


def _get_qweather_config() -> tuple[str, str]:
    """Return (api_key, api_host), raise _QWeatherConfigError if missing."""
    api_key = os.getenv("QWEATHER_API_KEY")
    api_host = os.getenv("QWEATHER_API_HOST")
    if not api_key:
        raise _QWeatherConfigError("缺少 QWEATHER_API_KEY")
    if not api_host:
        raise _QWeatherConfigError("缺少 QWEATHER_API_HOST")
    return api_key, api_host


def _qweather_get(api_key: str, api_host: str, path: str, params: dict) -> dict:
    """Make a QWeather API GET request and return the parsed JSON."""
    response = requests.get(
        _api_url(api_host, path),
        params=params,
        headers={"X-QW-Api-Key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _city_to_location_id(city: str, api_key: str, api_host: str) -> str | None:
    payload = _qweather_get(api_key, api_host, QWEATHER_GEO_PATH, {"location": city})
    if payload.get("code") != "200":
        return None
    locations = payload.get("location") or []
    if not locations:
        return None
    return locations[0].get("id")


def _normalize_sun_query_date(date_text: str) -> str:
    """Normalize sunrise/sunset query date: empty -> today (YYYYMMDD)."""
    if not date_text:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().strftime("%Y%m%d")
    return date_text


@tool
def get_current_weather(city: str = "北京") -> str:
    """Get current weather metrics for a city. Prefer web_search when user explicitly asks to 搜/查."""

    try:
        api_key, api_host = _get_qweather_config()
        location_id = _city_to_location_id(city, api_key, api_host)
        if not location_id:
            return f"未找到城市 {city} 的天气信息。"
        payload = _qweather_get(api_key, api_host, QWEATHER_NOW_PATH, {"location": location_id})
    except _QWeatherConfigError as exc:
        return f"天气服务暂不可用：{exc}。"
    except requests.RequestException:
        return "天气服务请求失败，请稍后重试。"

    if payload.get("code") != "200":
        return "天气服务暂时不可用，请稍后重试。"

    now = payload.get("now") or {}
    temperature = now.get("temp")
    weather_text = now.get("text")
    feels_like = now.get("feelsLike")
    humidity = now.get("humidity")
    wind_dir = now.get("windDir")
    wind_scale = now.get("windScale")

    if temperature is None or not weather_text:
        return "天气服务返回数据不完整，请稍后再试。"

    details = []
    if feels_like is not None:
        details.append(f"体感 {feels_like}℃")
    if humidity is not None:
        details.append(f"湿度 {humidity}%")
    if wind_dir and wind_scale is not None:
        details.append(f"{wind_dir}{wind_scale}级")

    detail_text = f"，{', '.join(details)}" if details else ""
    return f"{city}当前天气：{weather_text}，气温 {temperature}℃{detail_text}。"


@tool
def get_weather_forecast(city: str = "北京") -> str:
    """Get 3-day weather forecast. Prefer web_search when user explicitly asks to 搜/查."""

    try:
        api_key, api_host = _get_qweather_config()
        location_id = _city_to_location_id(city, api_key, api_host)
        if not location_id:
            return f"未找到城市 {city} 的天气预报信息。"
        payload = _qweather_get(api_key, api_host, QWEATHER_FORECAST_3D_PATH, {"location": location_id})
    except _QWeatherConfigError as exc:
        return f"天气预报服务暂不可用：{exc}。"
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


@tool
def get_sunrise_sunset(city: str = "北京", date: str = "") -> str:
    """Get sunrise/sunset times. Prefer web_search when user explicitly asks to 搜/查."""

    query_date = _normalize_sun_query_date(date)

    try:
        api_key, api_host = _get_qweather_config()
        location_id = _city_to_location_id(city, api_key, api_host)
        if not location_id:
            return f"未找到城市 {city} 的日出日落信息。"
        payload = _qweather_get(
            api_key,
            api_host,
            QWEATHER_SUN_PATH,
            {"location": location_id, "date": query_date},
        )
    except _QWeatherConfigError as exc:
        return f"日出日落服务暂不可用：{exc}。"
    except requests.RequestException:
        return "日出日落服务请求失败，请稍后重试。"

    if payload.get("code") != "200":
        return "日出日落服务暂时不可用，请稍后重试。"

    sunrise = payload.get("sunrise")
    sunset = payload.get("sunset")
    if not sunrise or not sunset:
        return "日出日落服务返回数据不完整，请稍后再试。"

    display_date = f"{query_date[:4]}-{query_date[4:6]}-{query_date[6:8]}"
    return f"{city}{display_date}日出时间 {sunrise}，日落时间 {sunset}。"
