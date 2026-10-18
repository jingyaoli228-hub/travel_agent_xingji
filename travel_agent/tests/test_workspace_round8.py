from __future__ import annotations

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
