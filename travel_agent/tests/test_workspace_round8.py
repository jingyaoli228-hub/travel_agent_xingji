from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from travel_agent.schemas.itinerary import DayPlan, ItineraryItem
from travel_agent.workspace.service import PlanVersionConflict, PlaceRejected, WorkspaceService


def activity(item_id: str, time: str, name: str, locked: bool = False) -> ItineraryItem:
    return ItineraryItem(item_id=item_id, time=time, activity="attraction", location=name, name=name,
                         transport="transit", duration_minutes=60, estimated_cost=10, reason="test",
                         city="Tokyo", place_id=f"place_{item_id}", user_locked=locked,
                         latitude=35.0, longitude=139.0)


@pytest.fixture
def service():
    value = WorkspaceService()
    value.seed("trip", [DayPlan(day_number=1, day_id="day_1", city="Tokyo", accommodation="Hotel",
                                          items=[activity("a", "09:00", "A", True), activity("b", "13:00", "B")]),
                              DayPlan(day_number=2, day_id="day_2", city="Tokyo", accommodation="Hotel",
                                          items=[activity("c", "10:00", "C")])])
    value.place_details_provider = lambda place_id: {"success": True, "name": "Record Store", "place_id": place_id,
        "city": "Tokyo", "address": "Tokyo", "latitude": 35.1, "longitude": 139.1,
        "types": ["store"], "primary_category": "Shopping"}
    value.route_provider = lambda **kwargs: {"success": True, "duration_minutes": 20, "distance_km": 2,
                                             "encoded_polyline": "abc"}
    return value


def request(**updates):
    result = {"place_id": "new_place", "insert_after_item_id": "a", "preferred_duration_minutes": 90,
              "user_locked": True, "current_plan_version": 1, "request_id": "request-1"}
    result.update(updates); return result


def test_insert_only_changes_current_day_and_preserves_locked_items(service):
    before = service.get("trip").days[1].model_dump()
    preview = service.preview_insert("trip", "day_1", request())
    assert preview["status"] == "PREVIEW"
    result = service.apply_patch("trip", preview["patch_id"], 1, "apply-1")
    assert result["plan_version"] == 2
    state = service.get("trip")
    assert state.days[1].model_dump() == before
    assert any(item.item_id == "a" and item.user_locked for item in state.days[0].items)
    assert any(item.place_id == "new_place" and item.user_locked for item in state.days[0].items)


def test_invalid_place_id_is_rejected(service):
    service.place_details_provider = lambda place_id: {"success": False, "error": "not found"}
    with pytest.raises(PlaceRejected): service.preview_insert("trip", "day_1", request())


def test_cross_city_and_closing_time_conflicts(service):
    service.place_details_provider = lambda place_id: {"success": True, "name": "Kyoto POI", "city": "Kyoto"}
    assert service.preview_insert("trip", "day_1", request())["status"] == "INSERTION_CONFLICT"
    service._cache._values.clear()
    service.place_details_provider = lambda place_id: {"success": True, "name": "Early Museum", "city": "Tokyo", "closing_time": "10:00"}
    assert "闭馆" in service.preview_insert("trip", "day_1", request())["reason"]


def test_force_insert_keeps_visible_conflict_reason(service):
    service.place_details_provider = lambda place_id: {
        "success": True, "name": "Early Museum", "city": "Tokyo",
        "closing_time": "10:00", "place_id": place_id,
    }
    preview = service.preview_insert("trip", "day_1", request(force_insert=True))
    added = next(item for item in preview["updated_day_plan"]["items"] if item["place_id"] == "new_place")
    assert preview["status"] == "PREVIEW"
    assert "闭馆" in added["conflict_reason"]


def test_route_time_shifts_following_item_and_metrics_are_returned(service):
    service.route_provider = lambda **kwargs: {"success": True, "duration_minutes": 90, "distance_km": 8}
    preview = service.preview_insert("trip", "day_1", request())
    assert any(change["action"] == "SHIFT" for change in preview["changed_items"])
    assert "tripcraft_metrics" in preview and "validation" in preview


def test_plan_version_conflict(service):
    with pytest.raises(PlanVersionConflict): service.preview_insert("trip", "day_1", request(current_plan_version=7))


def test_route_failure_is_explicit_fallback(service):
    service.route_provider = lambda **kwargs: {"success": False, "error": "routes down"}
    routes = service.routes("trip", "day_1")
    assert routes[0].status == "FALLBACK"
    assert "不代表真实路线" in routes[0].warning


def test_route_failure_still_has_public_transport_duration(service):
    state = service.get("trip")
    state.days[0].items[1].transport = "公共交通 约42分钟"
    service._states["trip"] = state
    service.route_provider = lambda **kwargs: {"success": False, "error": "routes down"}
    route = service.routes("trip", "day_1")[0]
    assert route.travel_mode == "TRANSIT"
    assert route.duration_minutes == 42


def test_manual_unlock_reorder_and_delete_recalculate_day(service):
    unlocked = service.set_item_lock("trip", "day_1", "a", False, 1, "unlock-a")
    assert unlocked["plan_version"] == 2
    reordered = service.reorder_day("trip", "day_1", ["b", "a"], 2, "reorder-day")
    assert reordered["plan_version"] == 3
    state = service.get("trip")
    assert [item.item_id for item in state.days[0].items] == ["b", "a"]
    assert state.days[0].items[1].transport_duration_minutes == 20
    deleted = service.delete_item("trip", "day_1", "a", 3, "delete-a")
    assert deleted["plan_version"] == 4
    assert [item.item_id for item in service.get("trip").days[0].items] == ["b"]


def test_insert_request_defaults_to_unlocked():
    from travel_agent.schemas.workspace import InsertPoiRequest
    payload = InsertPoiRequest(place_id="p", plan_version=1, request_id="r")
    assert payload.user_locked is False


def test_legacy_items_get_geodata_without_bumping_plan_version():
    service = WorkspaceService()
    item = activity("legacy", "09:00", "Legacy Place")
    item.place_id = None; item.latitude = None; item.longitude = None
    service.seed("legacy-trip", [DayPlan(day_number=1, day_id="day_1", city="Beijing", items=[item])])
    service.place_search_provider = lambda **kwargs: [{
        "place_id": "amap-legacy", "name": "Legacy Place",
        "location": {"lat": 39.9, "lng": 116.4}, "rating": 4.7,
    }]
    state = service.ensure_geodata("legacy-trip")
    assert state.plan_version == 1
    assert state.days[0].items[0].place_id == "amap-legacy"
    assert state.days[0].items[0].latitude == 39.9


def test_rollback_restores_previous_days_and_advances_version(service):
    before = service.get("trip").days[0].model_dump()
    preview = service.preview_insert("trip", "day_1", request())
    applied = service.apply_patch("trip", preview["patch_id"], 1, "apply-for-undo")
    restored = service.rollback("trip", applied["plan_version"])
    assert restored.plan_version == 3
    assert restored.days[0].model_dump() == before
    assert restored.history == []


def test_hotel_candidates_never_fabricate_price_or_rules(service):
    service.place_search_provider = lambda **kwargs: [{"place_id": "hotel-1", "name": "Real Hotel", "address": "Tokyo",
        "location": {"lat": 35.2, "lng": 139.2}, "rating": 4.8, "user_rating_count": 12}]
    hotels = service.hotel_candidates("trip")["Tokyo"]
    assert hotels and hotels[0].estimated_price is None and hotels[0].price_source is None
    assert not hotels[0].room_rules_verified and set(hotels[0].room_rules.values()) == {"unknown"}


def test_hotel_selection_locks_each_day_start_and_end(service):
    service.place_search_provider = lambda **kwargs: [{"place_id": "hotel-1", "name": "Real Hotel", "address": "Tokyo",
        "location": {"lat": 35.2, "lng": 139.2}, "rating": 4.4, "user_rating_count": 900}]
    service.hotel_candidates("trip")
    state = service.select_hotel("trip", "Tokyo", "hotel-1", 1, "hotel-request")
    assert state.hotel_selection_status == "CONFIRMED"
    for day in state.days:
        assert day.items[0].source == day.items[-1].source == "hotel_selection"
        assert day.items[0].user_locked and day.items[-1].user_locked


def test_autocomplete_is_city_scoped(service):
    service.place_search_provider = lambda **kwargs: [
        {"place_id": "tokyo", "name": "Tokyo Store", "address": "Shibuya, Tokyo"},
        {"place_id": "paris", "name": "Paris Store", "address": "Paris, France"},
    ]
    assert [row["place_id"] for row in service.autocomplete("store", "Tokyo")] == ["tokyo"]


def test_mutation_endpoint_returns_409_for_stale_plan_version(monkeypatch):
    from travel_agent.main import app
    from travel_agent.api import workspace as api_module
    local = WorkspaceService()
    local.seed("api-trip", [DayPlan(day_number=1, day_id="day_1", city="Tokyo", accommodation="Hotel", items=[activity("a", "09:00", "A")])], version=3)
    monkeypatch.setattr(api_module, "workspace_service", local)
    response = TestClient(app).post("/api/trips/api-trip/days/day_1/preview-insert", json={
        "place_id": "x", "insert_after_item_id": "a", "preferred_duration_minutes": 60,
        "user_locked": True, "current_plan_version": 2, "request_id": "stale",
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PLAN_VERSION_CONFLICT"


def test_itinerary_overview_aggregates_routes_quality_and_history(monkeypatch):
    from travel_agent.main import app
    from travel_agent.api import workspace as api_module
    local = WorkspaceService()
    local.seed("overview-trip", [DayPlan(day_number=1, day_id="day_1", date="2026-10-18", city="Beijing",
        items=[activity("a", "09:00", "A"), activity("b", "11:00", "B")])])
    local.route_provider = lambda **kwargs: {
        "success": True, "duration_minutes": 18, "distance_km": 2.1,
        "polyline": [{"lat": 39.9, "lng": 116.4}, {"lat": 39.91, "lng": 116.41}],
    }
    fake_values = {
        "stage": "done", "travel_requirement": {"destination": "北京"},
        "review_report": {"score": 78, "passed": False, "issues": ["步行偏多"]},
        "conversation_history": [{"role": "user", "content": "轻松一点"}],
        "final_plan": {"notes": ["周日下午可能有雨"]},
    }
    monkeypatch.setattr(api_module, "workspace_service", local)
    monkeypatch.setattr(api_module, "get_compiled_graph", lambda: SimpleNamespace(
        get_state=lambda config: SimpleNamespace(values=fake_values)
    ))
    response = TestClient(app).get("/api/trips/overview-trip/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "北京 1 日游"
    assert payload["quality"]["score"] == 78
    assert payload["route_segments_by_day"]["day_1"][0]["status"] == "REAL_ROUTE"
    assert [alert["type"] for alert in payload["alerts"]] == ["quality", "risk"]


def test_trip_copy_is_independent_and_shifts_dates(service):
    source = service.get("trip")
    source.days[0].date = "2025-01-01"
    source.days[1].date = "2025-01-03"
    service._states["trip"] = source
    copied = service.clone("trip", "trip-copy", "2026-11-01")
    assert [day.date for day in copied.days] == ["2026-11-01", "2026-11-03"]
    assert copied.plan_version == 1
    assert service.get("trip").days[0].date == "2025-01-01"


def test_xhs_parse_extracts_known_places_and_matches_amap(monkeypatch):
    from travel_agent.main import app
    from travel_agent.api import workspace as api_module
    local = WorkspaceService()
    local.place_search_provider = lambda **kwargs: [{
        "place_id": f"amap-{kwargs['query']}", "name": kwargs["query"], "address": "北京市",
    }]
    monkeypatch.setattr(api_module, "workspace_service", local)
    response = TestClient(app).post("/api/imports/xhs/parse", json={
        "user_id": "owner", "content": "北京三天：故宫博物院一定早去，下午去景山公园看中轴线。",
    })
    assert response.status_code == 200
    places = response.json()["places"]
    assert {row["name"] for row in places} >= {"故宫博物院", "景山公园"}
    assert all(row["matched"] for row in places[:2])


def test_xhs_link_only_failure_is_truthful():
    from travel_agent.main import app
    response = TestClient(app).post("/api/imports/xhs/parse", json={
        "user_id": "owner", "content": "https://xhslink.com/a/abc",
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "LINK_CONTENT_UNAVAILABLE"
