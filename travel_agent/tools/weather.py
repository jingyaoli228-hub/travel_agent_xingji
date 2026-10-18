"""Weather tool backed by AMap Web Service.

AMap returns a short domestic city forecast and does not expose precipitation
probability, so that field is explicitly ``None`` instead of being invented.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

import requests
from langchain_core.tools import tool

from travel_agent.config.settings import get_settings
from travel_agent.schemas.tool_results import WeatherDayResult
from travel_agent.utils.logging import get_logger, log_call

_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
_TIMEOUT = 10
_logger = get_logger("travel_agent.tools.weather")
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_WEATHER_CODES = {0: "晴", 1: "大部晴朗", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
                  51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨", 61: "小雨", 63: "中雨",
                  65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨",
                  81: "中等阵雨", 82: "强阵雨", 95: "雷暴"}
_GLOBAL_CITY_ALIASES = {"东京": "Tokyo", "大阪": "Osaka", "京都": "Kyoto", "首尔": "Seoul",
                        "曼谷": "Bangkok", "巴厘岛": "Bali", "新加坡": "Singapore", "巴黎": "Paris",
                        "伦敦": "London", "纽约": "New York", "悉尼": "Sydney"}


def _recommendation(condition: str, max_temp: float, min_temp: float) -> str:
    tips = []
    if any(word in condition for word in ("雨", "雪", "雷")):
        tips.append("预报有降水，建议携带雨具")
    if max_temp >= 30:
        tips.append("气温较高，注意防晒补水")
    if min_temp <= 10:
        tips.append("早晚较凉，建议带件外套")
    return "；".join(tips) if tips else "天气较为舒适，正常安排行程即可"


def _adcode(destination: str, key: str) -> Optional[str]:
    response = requests.get(_GEOCODE_URL, params={"key": key, "address": destination}, timeout=_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if str(data.get("status")) != "1" or not data.get("geocodes"):
        return None
    return str(data["geocodes"][0].get("adcode") or "") or None


def _global_geocode(destination: str) -> Optional[tuple[float, float, str]]:
    query = _GLOBAL_CITY_ALIASES.get(destination.strip(), destination)
    response = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                            params={"name": query, "count": 1, "language": "zh", "format": "json"},
                            timeout=_TIMEOUT)
    response.raise_for_status()
    rows = response.json().get("results") or []
    if not rows:
        return None
    row = rows[0]
    return float(row["latitude"]), float(row["longitude"]), str(row.get("country_code") or "").lower()


def _open_meteo(destination: str, target, geo: tuple[float, float, str]) -> Dict[str, Any]:
    lat, lng, _ = geo
    response = requests.get(_OPEN_METEO_URL, params={"latitude": lat, "longitude": lng, "timezone": "auto",
        "start_date": target.isoformat(), "end_date": target.isoformat(),
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}, timeout=_TIMEOUT)
    response.raise_for_status()
    daily = response.json().get("daily") or {}
    if not daily.get("time"):
        return {"success": False, "error": f"Open-Meteo 未返回 {target.isoformat()} 的预报。"}
    code = int((daily.get("weather_code") or [0])[0])
    max_temp = float((daily.get("temperature_2m_max") or [0])[0])
    min_temp = float((daily.get("temperature_2m_min") or [0])[0])
    rain = (daily.get("precipitation_probability_max") or [None])[0]
    condition = _WEATHER_CODES.get(code, f"天气代码 {code}")
    result = WeatherDayResult(date=target.isoformat(), temperature=f"{min_temp:.0f}-{max_temp:.0f}°C",
                              weather=condition, rain_probability=float(rain) if rain is not None else None,
                              recommendation=_recommendation(condition, max_temp, min_temp)).model_dump()
    result["source"] = "open_meteo"
    return result


@tool
@log_call("tool", "weather.get_weather")
def get_weather(destination: str, travel_date: str) -> Dict[str, Any]:
    """获取高德支持的国内城市短期天气预报。"""
    key = get_settings().amap_web_service_key
    if not key:
        return {"success": False, "error": "AMAP_WEB_SERVICE_KEY 未配置，无法调用高德天气。"}
    try:
        target = datetime.fromisoformat(travel_date[:10]).date()
    except ValueError:
        return {"success": False, "error": f"travel_date 格式不合法: {travel_date}"}
    days_ahead = (target - date.today()).days
    if days_ahead < 0 or days_ahead > 15:
        return {"success": False, "error": f"{travel_date} 超出实时天气约16天的预报窗口。"}
    try:
        global_geo = _global_geocode(destination)
        if not global_geo:
            return {"success": False, "error": f"无法定位城市「{destination}」。"}
        if global_geo[2] != "cn":
            return _open_meteo(destination, target, global_geo)
        if days_ahead > 3:
            return _open_meteo(destination, target, global_geo)
        adcode = _adcode(destination, key)
        if not adcode:
            return {"success": False, "error": f"高德无法定位国内城市「{destination}」，海外天气不在普通 Key 覆盖范围。"}
        response = requests.get(_WEATHER_URL, params={"key": key, "city": adcode, "extensions": "all"}, timeout=_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        _logger.error("amap weather request failed: %s", exc)
        return {"success": False, "error": f"高德天气请求失败: {exc}"}
    except ValueError as exc:
        return {"success": False, "error": f"高德天气返回内容解析失败: {exc}"}
    if str(data.get("status")) != "1":
        return {"success": False, "error": f"高德天气 {data.get('infocode', 'UNKNOWN')}: {data.get('info', '请求失败')}"}
    casts = ((data.get("forecasts") or [{}])[0].get("casts") or [])
    entry = next((item for item in casts if item.get("date") == target.isoformat()), None)
    if not entry:
        return {"success": False, "error": f"{travel_date} 超出高德天气的短期预报窗口。"}
    day_temp, night_temp = float(entry.get("daytemp") or 0), float(entry.get("nighttemp") or 0)
    condition = str(entry.get("dayweather") or entry.get("nightweather") or "未知")
    return WeatherDayResult(date=travel_date, temperature=f"{night_temp:.0f}-{day_temp:.0f}°C",
                            weather=condition, rain_probability=None,
                            recommendation=_recommendation(condition, day_temp, night_temp)).model_dump()
