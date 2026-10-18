"""AMap (Gaode) Web Service POI tools.

The public API is mainland-China oriented. Results are validated against the
requested administrative region so a domestic name match is not mistaken for
an overseas result.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import quote
import threading
import time

import requests
from langchain_core.tools import tool

from travel_agent.config.settings import get_settings
from travel_agent.schemas.tool_results import GeoPoint, PlaceDetails, PlaceResult
from travel_agent.utils.logging import get_logger, log_call

_SEARCH_URL = "https://restapi.amap.com/v5/place/text"
_DETAILS_URL = "https://restapi.amap.com/v5/place/detail"
_TIMEOUT = 10
_TYPE_MAP = {
    "tourist_attraction": "110000", "museum": "140100", "art_gallery": "140400",
    "park": "110101", "restaurant": "050000", "cafe": "050500", "bar": "050600",
    "night_club": "080300", "shopping_mall": "060100", "clothing_store": "061200",
    "lodging": "100000",
}
_logger = get_logger("travel_agent.tools.amap_places")
_AMAP_MAX_REQUESTS_PER_SECOND = 2
_amap_rate_lock = threading.Lock()
_amap_request_times: Deque[float] = deque()
_NOMINATIM_URL = "https://nominatim.openstreetmap.org"
_PHOTON_URL = "https://photon.komoot.io"
_NOMINATIM_HEADERS = {"User-Agent": "enterprise-travel-agent/1.0"}
_nominatim_lock = threading.Lock()
_last_nominatim_call = 0.0


def _key() -> Optional[str]:
    return get_settings().amap_web_service_key or None


def _api_error(data: Dict[str, Any]) -> Optional[str]:
    if str(data.get("status")) == "1":
        return None
    return f"高德 API {data.get('infocode', 'UNKNOWN')}: {data.get('info', '请求失败')}"


def _amap_get(url: str, params: Dict[str, Any]) -> requests.Response:
    """Stay below the ordinary Web Service key's per-user QPS ceiling.

    Research fans queries out across several threads, so limiting each worker
    independently still creates a burst large enough for AMap to reject the
    later regions.  Reserve request slots process-wide before doing network IO.
    """
    while True:
        with _amap_rate_lock:
            now = time.monotonic()
            while _amap_request_times and now - _amap_request_times[0] >= 1.0:
                _amap_request_times.popleft()
            if len(_amap_request_times) < _AMAP_MAX_REQUESTS_PER_SECOND:
                _amap_request_times.append(now)
                break
            wait_for = max(0.01, 1.0 - (now - _amap_request_times[0]))
        time.sleep(wait_for)
    return requests.get(url, params=params, timeout=_TIMEOUT)


def _region_matches(poi: Dict[str, Any], region: Optional[str]) -> bool:
    if not region:
        return True
    needle = region.lower().replace("市", "").replace("省", "").strip()
    administrative = " ".join(str(poi.get(k) or "") for k in ("pname", "cityname", "adname")).lower()
    return not needle or needle in administrative.replace("市", "").replace("省", "")


def _location(value: Any) -> Optional[GeoPoint]:
    try:
        lng, lat = str(value).split(",", 1)
        return GeoPoint(lat=float(lat), lng=float(lng))
    except (TypeError, ValueError):
        return None


def _address(poi: Dict[str, Any]) -> Optional[str]:
    parts = [poi.get("pname"), poi.get("cityname"), poi.get("adname"), poi.get("address")]
    return "".join(str(part) for part in parts if part) or None


def _normalized_types(poi: Dict[str, Any], requested: Optional[str] = None) -> List[str]:
    labels = str(poi.get("type") or "")
    result = [requested] if requested else []
    rules = (("餐饮", "restaurant"), ("咖啡", "cafe"), ("酒吧", "bar"),
             ("住宿", "lodging"), ("酒店", "lodging"), ("公园", "park"),
             ("博物馆", "museum"), ("购物", "shopping_mall"), ("风景名胜", "tourist_attraction"))
    result.extend(value for needle, value in rules if needle in labels and value not in result)
    return result


def _nominatim_get(path: str, params: Dict[str, Any]) -> Any:
    """Respect the public service's one-request-per-second usage policy."""
    global _last_nominatim_call
    with _nominatim_lock:
        delay = 1.05 - (time.monotonic() - _last_nominatim_call)
        if delay > 0:
            time.sleep(delay)
        response = requests.get(f"{_NOMINATIM_URL}/{path}", params=params, headers=_NOMINATIM_HEADERS, timeout=_TIMEOUT)
        _last_nominatim_call = time.monotonic()
    response.raise_for_status()
    return response.json()


def _osm_id(row: Dict[str, Any]) -> str:
    prefix = {"node": "N", "way": "W", "relation": "R"}.get(str(row.get("osm_type")), "N")
    return f"osm:{prefix}{row.get('osm_id')}"


def _photon_search(query: str, region: Optional[str], place_type: Optional[str], limit: int) -> List[Dict[str, Any]]:
    try:
        response = requests.get(f"{_PHOTON_URL}/api/",
            params={"q": f"{query} {region or ''}".strip(), "limit": max(1, min(limit, 10)), "lang": "en"},
            headers=_NOMINATIM_HEADERS, timeout=15)
        response.raise_for_status()
        features = response.json().get("features") or []
    except (requests.RequestException, ValueError):
        return []
    results: List[Dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        lng, lat = float(coordinates[0]), float(coordinates[1])
        osm_type = str(props.get("osm_type") or "N")[:1].upper()
        place_id = f"photon:{osm_type}:{props.get('osm_id')}:{lng}:{lat}"
        address = ", ".join(str(props.get(key)) for key in ("street", "district", "city", "state", "country") if props.get(key))
        results.append(PlaceResult(name=str(props.get("name") or query), place_id=place_id,
            address=address or None, rating=0, user_rating_count=0,
            location=GeoPoint(lat=lat, lng=lng),
            types=[place_type or str(props.get("type") or "point_of_interest")],
            city=str(props.get("city") or props.get("state") or "") or None,
            source="openstreetmap").model_dump())
    return results


def _nominatim_search(query: str, region: Optional[str], place_type: Optional[str], limit: int) -> List[Dict[str, Any]]:
    photon = _photon_search(query, region, place_type, limit)
    if photon:
        return photon
    try:
        rows = _nominatim_get("search", {"format": "jsonv2", "q": f"{query} {region or ''}".strip(),
                                          "limit": max(1, min(limit, 10)), "addressdetails": 1,
                                          "extratags": 1, "namedetails": 1, "accept-language": "zh,en"})
    except (requests.RequestException, ValueError) as exc:
        return [{"success": False, "error": f"海外地点降级搜索失败: {exc}"}]
    results: List[Dict[str, Any]] = []
    for row in rows:
        address = row.get("address") or {}
        name = (row.get("namedetails") or {}).get("name") or str(row.get("display_name") or "").split(",")[0]
        try:
            point = GeoPoint(lat=float(row["lat"]), lng=float(row["lon"]))
        except (KeyError, ValueError):
            continue
        results.append(PlaceResult(name=name, place_id=_osm_id(row), address=row.get("display_name"),
                                   rating=0, user_rating_count=0, location=point,
                                   types=[place_type or str(row.get("type") or "point_of_interest")],
                                   city=address.get("city") or address.get("town") or address.get("state"),
                                   source="openstreetmap").model_dump())
    return results or [{"success": False, "error": f"高德不覆盖「{region or query}」，OpenStreetMap 也未返回候选。"}]


@tool
@log_call("tool", "amap_places.search_places")
def search_places(query: str, location: Optional[str] = None, place_type: Optional[str] = None,
                  limit: int = 10) -> List[Dict[str, Any]]:
    """使用高德地点搜索 2.0 搜索景点、餐厅、酒店和其他 POI。"""
    api_key = _key()
    if not api_key:
        return [{"success": False, "error": "AMAP_WEB_SERVICE_KEY 未配置，无法调用高德地点搜索。"}]
    params: Dict[str, Any] = {
        "key": api_key, "keywords": query, "page_size": max(1, min(limit, 25)),
        "show_fields": "business,photos", "city_limit": "true" if location else "false",
    }
    if location:
        params["region"] = location
    if place_type and _TYPE_MAP.get(place_type):
        params["types"] = _TYPE_MAP[place_type]
    try:
        response = _amap_get(_SEARCH_URL, params)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        _logger.error("amap places request failed: %s", exc)
        return [{"success": False, "error": f"高德地点搜索请求失败: {exc}"}]
    except ValueError as exc:
        return [{"success": False, "error": f"高德地点搜索返回内容解析失败: {exc}"}]
    if error := _api_error(data):
        return [{"success": False, "error": error}]
    pois = [poi for poi in data.get("pois", []) if _region_matches(poi, location)]
    if not pois and location:
        return _nominatim_search(query, location, place_type, limit)
    results: List[Dict[str, Any]] = []
    for poi in pois[:limit]:
        business = poi.get("business") or {}
        loc = _location(poi.get("location"))
        results.append(PlaceResult(
            name=str(poi.get("name") or ""), place_id=str(poi.get("id") or ""), address=_address(poi),
            rating=float(business.get("rating") or 0), user_rating_count=0, location=loc,
            types=_normalized_types(poi, place_type),
            price_level=str(business.get("cost") or "") or None,
            city=str(poi.get("cityname") or "") or None,
        ).model_dump())
    return results


@tool
@log_call("tool", "amap_places.get_place_details")
def get_place_details(place_id: str) -> Dict[str, Any]:
    """获取高德 POI 详情；高德不提供 Google 风格的用户评论正文。"""
    if place_id.startswith("photon:"):
        try:
            _, _, osm_id, lng, lat = place_id.split(":", 4)
            response = requests.get(f"{_PHOTON_URL}/reverse", params={"lat": lat, "lon": lng},
                                    headers=_NOMINATIM_HEADERS, timeout=15)
            response.raise_for_status()
            features = response.json().get("features") or []
        except (requests.RequestException, ValueError):
            features = []
        props = (features[0].get("properties") or {}) if features else {}
        name = str(props.get("name") or "OpenStreetMap POI")
        address = ", ".join(str(props.get(key)) for key in ("street", "district", "city", "state", "country") if props.get(key))
        return PlaceDetails(name=name, rating=0, reviews=[], address=address or None,
                            latitude=float(lat), longitude=float(lng),
                            types=[str(props.get("type") or "point_of_interest")],
                            primary_category=str(props.get("type") or "point_of_interest"),
                            map_uri=f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}",
                            source="openstreetmap").model_dump()
    if place_id.startswith("osm:"):
        try:
            rows = _nominatim_get("lookup", {"format": "jsonv2", "osm_ids": place_id[4:],
                                              "addressdetails": 1, "extratags": 1,
                                              "namedetails": 1, "accept-language": "zh,en"})
        except (requests.RequestException, ValueError) as exc:
            return {"success": False, "error": f"OpenStreetMap 地点详情失败: {exc}"}
        if not rows:
            return {"success": False, "error": f"OpenStreetMap 未找到 POI: {place_id}"}
        row = rows[0]
        extra = row.get("extratags") or {}
        name = (row.get("namedetails") or {}).get("name") or str(row.get("display_name") or "").split(",")[0]
        return PlaceDetails(name=name,
                            opening_hours=[extra["opening_hours"]] if extra.get("opening_hours") else [],
                            rating=0, reviews=[], address=row.get("display_name"),
                            latitude=float(row["lat"]), longitude=float(row["lon"]),
                            types=[str(row.get("type") or "point_of_interest")],
                            primary_category=str(row.get("type") or "point_of_interest"),
                            map_uri=f"https://www.openstreetmap.org/{str(row.get('osm_type'))}/{row.get('osm_id')}",
                            website_uri=extra.get("website"), phone_number=extra.get("phone"),
                            source="openstreetmap").model_dump()
    api_key = _key()
    if not api_key:
        return {"success": False, "error": "AMAP_WEB_SERVICE_KEY 未配置，无法调用高德地点详情。"}
    if not place_id:
        return {"success": False, "error": "place_id 不能为空。"}
    try:
        response = _amap_get(_DETAILS_URL, {"key": api_key, "id": place_id, "show_fields": "business,photos"})
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {"success": False, "error": f"高德地点详情请求失败: {exc}"}
    except ValueError as exc:
        return {"success": False, "error": f"高德地点详情返回内容解析失败: {exc}"}
    if error := _api_error(data):
        return {"success": False, "error": error}
    pois = data.get("pois") or []
    if not pois:
        return {"success": False, "error": f"高德未找到 POI: {place_id}"}
    poi = pois[0]
    business = poi.get("business") or {}
    loc = _location(poi.get("location"))
    map_uri = None
    if loc:
        map_uri = f"https://uri.amap.com/marker?position={loc.lng},{loc.lat}&name={quote(str(poi.get('name') or ''))}&callnative=0"
    return PlaceDetails(
        name=str(poi.get("name") or ""),
        opening_hours=[business["opentime_week"]] if business.get("opentime_week") else [],
        rating=float(business.get("rating") or 0), reviews=[], price_level=str(business.get("cost") or "") or None,
        address=_address(poi), latitude=loc.lat if loc else None, longitude=loc.lng if loc else None,
        types=_normalized_types(poi),
        primary_category=str(poi.get("type") or "").split("|")[0] or None,
        business_status=None, map_uri=map_uri, website_uri=None,
        phone_number=str(business.get("tel") or "") or None,
        photos=[photo.get("url", "") for photo in poi.get("photos", []) if photo.get("url")],
    ).model_dump()
