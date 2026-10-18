"""Tests for the real tool implementations.

Every tool that calls an external API is tested by mocking the HTTP layer
(`requests.get`/`requests.post`) or, for `search.py`, `subprocess`/`shutil`,
so these tests stay fast, free and fully offline while still exercising the
real request-building and response-parsing logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from travel_agent.tools import amap_places, amap_routes, search, weather
from travel_agent.tools.visa import search_visa_information


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.side_effect = None
    return resp


def test_search_visa_information_shape():
    result = search_visa_information.invoke({"passport_country": "中国", "destination": "东京"})
    assert "visa_required" in result
    assert result["source"]["source_type"] == "mock"


def test_search_places_parses_response(monkeypatch):
    monkeypatch.setattr(amap_places.get_settings(), "amap_web_service_key", "fake-key")
    payload = {
        "status": "1", "pois": [
            {
                "id": "abc123",
                "name": "故宫博物院", "address": "景山前街4号", "pname": "北京市", "cityname": "北京市",
                "adname": "东城区", "location": "116.397029,39.917839", "type": "风景名胜;博物馆",
                "business": {"rating": "4.9"},
            }
        ]
    }
    with patch.object(amap_places.requests, "get", return_value=_mock_response(payload)) as mock_get:
        result = amap_places.search_places.invoke({"query": "故宫", "location": "北京", "place_type": "tourist_attraction"})
    assert mock_get.called
    assert result[0]["name"] == "故宫博物院"
    assert result[0]["place_id"] == "abc123"
    assert result[0]["location"] == {"lat": 39.917839, "lng": 116.397029}


def test_search_places_missing_api_key(monkeypatch):
    monkeypatch.setattr(amap_places.get_settings(), "amap_web_service_key", None)
    result = amap_places.search_places.invoke({"query": "北京"})
    assert result[0]["success"] is False


def test_get_place_details_parses_response(monkeypatch):
    monkeypatch.setattr(amap_places.get_settings(), "amap_web_service_key", "fake-key")
    payload = {
        "status": "1", "pois": [{"id": "abc123", "name": "故宫博物院", "address": "景山前街4号",
        "location": "116.397029,39.917839", "type": "风景名胜;博物馆",
        "business": {"rating": "4.9", "opentime_week": "周二至周日 08:30-17:00", "cost": "60"}}],
    }
    with patch.object(amap_places.requests, "get", return_value=_mock_response(payload)):
        result = amap_places.get_place_details.invoke({"place_id": "abc123"})
    assert result["opening_hours"] == ["周二至周日 08:30-17:00"]
    assert result["reviews"] == []
    assert result["price_level"] == "60"


def test_calculate_route_parses_response(monkeypatch):
    monkeypatch.setattr(amap_routes.get_settings(), "amap_web_service_key", "fake-key")
    payload = {
        "status": "1", "route": {"paths": [{"distance": "1200", "cost": {"duration": "930"},
        "steps": [{"instruction": "向东步行", "cost": {"duration": "300"}, "polyline": "116.1,39.1;116.2,39.2"}]}]}
    }
    with patch.object(amap_routes.requests, "get", return_value=_mock_response(payload)):
        result = amap_routes.calculate_route.invoke({"origin": "116.1,39.1", "destination": "116.2,39.2", "mode": "walk"})
    assert result["mode"] == "WALK"
    assert result["duration_minutes"] == 15.5
    assert result["distance_km"] == 1.2
    assert result["steps"][0]["instruction"] == "向东步行"


def test_calculate_route_no_routes_found(monkeypatch):
    monkeypatch.setattr(amap_routes.get_settings(), "amap_web_service_key", "fake-key")
    with patch.object(amap_routes.requests, "get", return_value=_mock_response({"status": "1", "route": {"paths": []}})):
        result = amap_routes.calculate_route.invoke({"origin": "116.1,39.1", "destination": "116.2,39.2", "mode": "walk"})
    assert result["success"] is False


def test_get_weather_out_of_forecast_window(monkeypatch):
    monkeypatch.setattr(weather.get_settings(), "amap_web_service_key", "fake-key")
    result = weather.get_weather.invoke({"destination": "东京", "travel_date": "2099-01-01"})
    assert result["success"] is False


def test_get_weather_parses_response(monkeypatch):
    from datetime import date, timedelta

    monkeypatch.setattr(weather.get_settings(), "amap_web_service_key", "fake-key")
    monkeypatch.setattr(weather, "_adcode", lambda destination, key: "110000")
    monkeypatch.setattr(weather, "_global_geocode", lambda destination: (39.9, 116.4, "cn"))
    target = date.today() + timedelta(days=1)
    payload = {
        "status": "1", "forecasts": [{"casts": [{"date": target.isoformat(), "dayweather": "晴",
        "daytemp": "27", "nighttemp": "20"}]}]
    }
    with patch.object(weather.requests, "get", return_value=_mock_response(payload)):
        result = weather.get_weather.invoke({"destination": "东京", "travel_date": target.isoformat()})
    assert result["success"] is True
    assert result["weather"] == "晴"
    assert result["temperature"] == "20-27°C"


def test_search_travel_guides_missing_command(monkeypatch):
    monkeypatch.setattr(search.shutil, "which", lambda exe: None)
    result = search.search_travel_guides.invoke({"destination": "东京", "platform": "xiaohongshu"})
    assert result[0]["success"] is False


def test_search_travel_guides_parses_json_output(monkeypatch):
    monkeypatch.setattr(search.shutil, "which", lambda exe: "/usr/bin/xhs")
    fake_proc = MagicMock(returncode=0, stdout='[{"title": "东京购物攻略", "url": "https://x.com/1", "snippet": "避坑指南"}]', stderr="")
    with patch.object(search.subprocess, "run", return_value=fake_proc):
        result = search.search_travel_guides.invoke({"destination": "东京", "platform": "xiaohongshu", "limit": 3})
    assert result[0]["title"] == "东京购物攻略"
    assert result[0]["platform"] == "xiaohongshu"
