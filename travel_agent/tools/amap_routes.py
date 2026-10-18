"""AMap Web Service route planning normalized to the app contract."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from langchain_core.tools import tool

from travel_agent.config.settings import get_settings
from travel_agent.schemas.tool_results import GeoPoint, RouteResult, RouteStep
from travel_agent.tools.amap_places import search_places
from travel_agent.utils.logging import get_logger, log_call

_TIMEOUT = 12
_MODE_MAP = {"walk": "WALK", "walking": "WALK", "transit": "TRANSIT", "taxi": "DRIVE",
             "drive": "DRIVE", "driving": "DRIVE", "bicycle": "BICYCLE", "bike": "BICYCLE"}
_ENDPOINTS = {"WALK": "walking", "DRIVE": "driving", "BICYCLE": "bicycling", "TRANSIT": "transit/integrated"}
_logger = get_logger("travel_agent.tools.amap_routes")


def _coordinate(value: str) -> Optional[Tuple[str, Optional[str]]]:
    if re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*", value):
        return value.replace(" ", ""), None
    rows = search_places.invoke({"query": value, "limit": 1})
    if not rows or rows[0].get("success") is False or not rows[0].get("location"):
        return None
    loc = rows[0]["location"]
    return f"{loc['lng']},{loc['lat']}", rows[0].get("city")


def _polyline(paths: List[Dict[str, Any]]) -> List[GeoPoint]:
    points: List[GeoPoint] = []
    for path in paths:
        for step in path.get("steps") or []:
            for pair in str(step.get("polyline") or "").split(";"):
                try:
                    lng, lat = pair.split(",", 1)
                    point = GeoPoint(lat=float(lat), lng=float(lng))
                    if not points or point != points[-1]:
                        points.append(point)
                except ValueError:
                    continue
    return points


@tool
@log_call("tool", "amap_routes.calculate_route")
def calculate_route(origin: str, destination: str, mode: str = "TRANSIT") -> Dict[str, Any]:
    """使用高德路线规划 2.0 计算国内步行、驾车、公交或骑行路线。"""
    key = get_settings().amap_web_service_key
    if not key:
        return {"success": False, "error": "AMAP_WEB_SERVICE_KEY 未配置，无法调用高德路线规划。"}
    travel_mode = _MODE_MAP.get(mode.lower(), mode.upper())
    if travel_mode not in _ENDPOINTS:
        return {"success": False, "error": f"高德路线规划不支持交通方式 {travel_mode}。"}
    start, end = _coordinate(origin), _coordinate(destination)
    if not start or not end:
        return {"success": False, "error": f"无法在高德中定位「{origin}」或「{destination}」。"}
    params: Dict[str, Any] = {"key": key, "origin": start[0], "destination": end[0], "show_fields": "cost,polyline"}
    if travel_mode == "TRANSIT":
        if not start[1] or not end[1]:
            return {"success": False, "error": "公交规划需要高德可识别的国内起终点城市。"}
        params.update({"city1": start[1], "city2": end[1]})
    url = f"https://restapi.amap.com/v5/direction/{_ENDPOINTS[travel_mode]}"
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        _logger.error("amap routes request failed: %s", exc)
        return {"success": False, "error": f"高德路线规划请求失败: {exc}"}
    except ValueError as exc:
        return {"success": False, "error": f"高德路线规划返回内容解析失败: {exc}"}
    if str(data.get("status")) != "1":
        return {"success": False, "error": f"高德路线规划 {data.get('infocode', 'UNKNOWN')}: {data.get('info', '请求失败')}"}
    route = data.get("route") or {}
    paths = route.get("paths") or route.get("transits") or []
    if not paths:
        return {"success": False, "error": f"未找到从「{origin}」到「{destination}」的 {travel_mode} 路线。"}
    path = paths[0]
    cost = path.get("cost") or {}
    duration = float(cost.get("duration") or path.get("duration") or 0)
    distance = float(path.get("distance") or 0)
    steps = [RouteStep(instruction=str(step.get("instruction") or ""), duration_minutes=float((step.get("cost") or {}).get("duration") or 0) / 60)
             for step in path.get("steps") or [] if step.get("instruction")]
    return RouteResult(origin=origin, destination=destination, mode=travel_mode,
                       distance_km=round(distance / 1000, 3) if distance else None,
                       duration_minutes=round(duration / 60, 1), steps=steps,
                       cost=None, currency="CNY", polyline=_polyline([path])).model_dump()
