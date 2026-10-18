"""Optimistically locked day patches, route fallback, and hotel selection."""

from __future__ import annotations

import copy
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from uuid import uuid4

from travel_agent.evaluation.constraint_validator import ConstraintValidator
from travel_agent.evaluation.tripcraft_metric_evaluator import TripCraftMetricEvaluator
from travel_agent.persistence import database
from travel_agent.schemas.constraints import TravelConstraintSet
from travel_agent.schemas.itinerary import DayPlan, Itinerary, ItineraryItem
from travel_agent.schemas.workspace import HotelCandidate, RouteSegment, WorkspaceState
from travel_agent.tools.amap_places import get_place_details, search_places
from travel_agent.tools.amap_routes import calculate_route


class PlanVersionConflict(Exception):
    pass


class WorkspaceNotFound(Exception):
    pass


class PlaceRejected(Exception):
    pass


class TTLCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, Any]] = {}

    def get_or_set(self, key: str, ttl: int, loader: Callable[[], Any]) -> Any:
        now = time.time()
        cached = self._values.get(key)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])
        value = loader()
        self._values[key] = (now + ttl, copy.deepcopy(value))
        return value


class WorkspaceService:
    PLACE_DETAILS_TTL = 7 * 86400
    HOTEL_SEARCH_TTL = 12 * 3600
    POI_SEARCH_TTL = 3 * 3600
    ROUTE_TTL = 15 * 60

    def __init__(self) -> None:
        self._states: dict[str, WorkspaceState] = {}
        self._lock = threading.RLock()
        self._cache = TTLCache()
        self.place_details_provider: Callable[[str], dict[str, Any]] = lambda place_id: get_place_details.invoke({"place_id": place_id})
        self.place_search_provider: Callable[..., list[dict[str, Any]]] = lambda **kwargs: search_places.invoke(kwargs)
        self.route_provider: Callable[..., dict[str, Any]] = lambda **kwargs: calculate_route.invoke(kwargs)

    def seed(self, trip_id: str, days: list[dict[str, Any]] | list[DayPlan], version: int = 1) -> WorkspaceState:
        parsed = [day if isinstance(day, DayPlan) else DayPlan(**day) for day in days]
        for day in parsed:
            day.day_id = day.day_id or f"day_{day.day_number}"
        with self._lock:
            state = WorkspaceState(trip_id=trip_id, plan_version=version, days=parsed)
            if database.enabled():
                state = WorkspaceState(**database.create_workspace(trip_id, version, state.model_dump(mode="json")))
            else:
                self._states[trip_id] = state
            return copy.deepcopy(state)

    def get(self, trip_id: str) -> WorkspaceState:
        with self._lock:
            if database.enabled():
                raw = database.load_workspace(trip_id)
                if raw is None:
                    raise WorkspaceNotFound(trip_id)
                return WorkspaceState(**raw)
            if trip_id not in self._states:
                raise WorkspaceNotFound(trip_id)
            return copy.deepcopy(self._states[trip_id])

    def _save(self, state: WorkspaceState, expected_version: int) -> None:
        if database.enabled():
            if not database.save_workspace(
                state.trip_id, expected_version, state.model_dump(mode="json")
            ):
                raise PlanVersionConflict("workspace was updated concurrently")
        else:
            self._states[state.trip_id] = state

    def day(self, trip_id: str, day_id: str) -> DayPlan:
        state = self.get(trip_id)
        return copy.deepcopy(self._find_day(state, day_id))

    def ensure_geodata(self, trip_id: str) -> WorkspaceState:
        """Backfill legacy itinerary nodes with map identity and GCJ-02 points.

        New plans carry these fields from Research. This read-time migration
        keeps older persisted plans usable without changing their plan version.
        """
        with self._lock:
            state = self.get(trip_id)
            changed = False
            for day in state.days:
                for item in day.items:
                    if item.latitude is not None and item.longitude is not None:
                        continue
                    details: dict[str, Any] = {}
                    if item.place_id:
                        try:
                            details = self.place_details(item.place_id)
                        except PlaceRejected:
                            details = {}
                    if not details:
                        query = item.name or item.location.split(" (")[0]
                        rows = self.place_search_provider(query=query, location=day.city or item.city, limit=1)
                        row = next((candidate for candidate in rows if candidate.get("success", True)), None)
                        if row:
                            point = row.get("location") or {}
                            details = {
                                "place_id": row.get("place_id"), "name": row.get("name"),
                                "latitude": point.get("lat"), "longitude": point.get("lng"),
                                "rating": row.get("rating"),
                            }
                    latitude, longitude = details.get("latitude"), details.get("longitude")
                    if latitude is None or longitude is None:
                        continue
                    item.latitude, item.longitude = float(latitude), float(longitude)
                    item.place_id = item.place_id or details.get("place_id")
                    item.name = item.name or details.get("name") or item.location.split(" (")[0]
                    item.rating = item.rating if item.rating is not None else details.get("rating")
                    item.place_details_status = "VERIFIED"
                    changed = True
                if changed:
                    state.route_segments_by_day.pop(day.day_id or f"day_{day.day_number}", None)
            if changed:
                self._save(state, state.plan_version)
            return copy.deepcopy(state)

    def autocomplete(self, query: str, city: str, latitude: Optional[float] = None, longitude: Optional[float] = None, radius_meters: int = 20000) -> list[dict[str, Any]]:
        if not query.strip() or not city.strip():
            return []
        key = f"poi:{city}:{query}:{latitude}:{longitude}:{radius_meters}"
        rows = self._cache.get_or_set(key, self.POI_SEARCH_TTL, lambda: self.place_search_provider(query=query, location=city, limit=10))
        # Server-side city/region guard: global name-only results are excluded.
        return [row for row in rows if row.get("success", True) and row.get("place_id") and city.casefold() in (row.get("address") or city).casefold()]

    def place_details(self, place_id: str) -> dict[str, Any]:
        if not place_id:
            raise PlaceRejected("place_id is required")
        details = self._cache.get_or_set(f"place:{place_id}", self.PLACE_DETAILS_TTL, lambda: self.place_details_provider(place_id))
        if not details or details.get("success") is False or not details.get("name"):
            raise PlaceRejected("PLACE_ID_NOT_FOUND")
        return details

    def preview_insert(self, trip_id: str, day_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._require_version(trip_id, payload["current_plan_version"])
            if payload["request_id"] in state.applied_request_ids:
                return {"status": "SUCCESS", "plan_version": state.plan_version, "idempotent": True}
            original = self._find_day(state, day_id)
            day = original.model_copy(deep=True)
            details = self.place_details(payload["place_id"])
            place_city = details.get("city") or self._city_from_address(details.get("address", ""))
            if place_city and day.city and place_city.casefold() != day.city.casefold():
                return self._conflict("该地点不在当天城市", day_id)
            index = self._insert_index(day, payload.get("insert_after_item_id"))
            previous = day.items[index - 1] if index > 0 else None
            following = day.items[index] if index < len(day.items) else None
            duration = max(15, int(payload.get("preferred_duration_minutes", 90)))
            start_minutes = self._end_minutes(previous) if previous else 9 * 60
            before_route = self._route(previous, details, payload["place_id"]) if previous else None
            if before_route:
                start_minutes += round(before_route.duration_minutes)
            closing = self._hhmm(details.get("closing_time"))
            if closing is not None and start_minutes + duration > closing:
                return self._conflict("加入该景点后无法在闭馆前完成游览", day_id, duration)
            added = ItineraryItem(
                item_id=f"item_{uuid4().hex[:12]}", place_id=payload["place_id"], time=self._format_minutes(start_minutes),
                activity=self._activity_type(details), item_type=self._activity_type(details), name=details["name"],
                location=details["name"], duration_minutes=duration, planned_duration_hours=duration / 60,
                estimated_cost=float(details.get("estimated_cost") or 0), reason="用户手动添加",
                city=day.city, latitude=details.get("latitude"), longitude=details.get("longitude"),
                primary_category=details.get("primary_category"), user_locked=bool(payload.get("user_locked", True)),
                source="user_added", place_details_status="VERIFIED",
            )
            day.items.insert(index, added)
            changed = [{"action": "ADD", "item_id": added.item_id, "name": added.name}]
            cursor = start_minutes + duration
            after_route = self._route_to_item(details, payload["place_id"], following) if following else None
            if after_route:
                cursor += round(after_route.duration_minutes)
            for item in day.items[index + 1:]:
                old = item.time
                old_minutes = self._hhmm(old) or cursor
                if old_minutes < cursor:
                    item.time = self._format_minutes(cursor)
                    changed.append({"action": "SHIFT", "item_id": item.item_id, "from": old, "to": item.time})
                cursor = (self._hhmm(item.time) or cursor) + item.duration_minutes
            if cursor > 24 * 60 or self._meal_or_return_conflict(day):
                return self._conflict("顺延后与晚餐或返程时间冲突", day_id, duration)
            routes = self._routes_for_day(day)
            validation = ConstraintValidator().validate(Itinerary(days=[day]), TravelConstraintSet()).model_dump()
            metrics = TripCraftMetricEvaluator().evaluate(Itinerary(days=[day]), {}, ConstraintValidator().validate(Itinerary(days=[day]), TravelConstraintSet())).model_dump()
            patch_id = f"patch_{uuid4().hex}"
            preview = {"status": "PREVIEW", "patch_id": patch_id, "updated_day_plan": day.model_dump(),
                       "updated_route_segments": [r.model_dump() for r in routes], "validation": validation,
                       "tripcraft_metrics": metrics, "changed_items": changed, "plan_version": state.plan_version}
            state.pending_patches[patch_id] = {
                "day_id": day_id, "day": day.model_dump(),
                "routes": [r.model_dump() for r in routes],
                "request_id": payload["request_id"], "changed_items": changed,
            }
            self._save(state, state.plan_version)
            return preview

    def apply_patch(self, trip_id: str, patch_id: str, version: int, request_id: str) -> dict[str, Any]:
        with self._lock:
            current = self.get(trip_id)
            if request_id in current.mutation_results:
                return copy.deepcopy(current.mutation_results[request_id])
            state = self._require_version(trip_id, version)
            patch = state.pending_patches.get(patch_id)
            if not patch:
                raise PlaceRejected("PATCH_NOT_FOUND")
            index = next(i for i, day in enumerate(state.days) if (day.day_id or f"day_{day.day_number}") == patch["day_id"])
            state.history.append({
                "plan_version": state.plan_version,
                "days": [d.model_dump() for d in state.days],
                "summary": "已加入地点并重算当天行程",
                "changed_items": copy.deepcopy(patch.get("changed_items") or []),
            })
            state.days[index] = DayPlan(**patch["day"])
            state.route_segments_by_day[patch["day_id"]] = [RouteSegment(**row) for row in patch["routes"]]
            state.plan_version += 1
            state.applied_request_ids.append(request_id)
            state.pending_patches.clear()
            result = {"status": "SUCCESS", "updated_day_plan": state.days[index].model_dump(),
                      "updated_route_segments": patch["routes"], "changed_items": [],
                      "plan_version": state.plan_version}
            state.mutation_results[request_id] = result
            self._save(state, version)
            return result

    def rollback(self, trip_id: str, version: int) -> WorkspaceState:
        with self._lock:
            state = self._require_version(trip_id, version)
            if not state.history:
                raise PlaceRejected("NO_REVERSIBLE_CHANGE")
            previous = state.history.pop()
            state.days = [DayPlan(**day) for day in previous.get("days") or []]
            state.route_segments_by_day.clear()
            state.pending_patches.clear()
            state.plan_version += 1
            self._save(state, version)
            return copy.deepcopy(state)

    def hotel_candidates(self, trip_id: str) -> dict[str, list[HotelCandidate]]:
        with self._lock:
            state = self.get(trip_id)
            cities = list(dict.fromkeys(day.city for day in state.days if day.city))
            for city in cities:
                if city in state.hotel_candidates_by_city:
                    continue
                rows = self._cache.get_or_set(f"hotel:{city}", self.HOTEL_SEARCH_TTL,
                    lambda city=city: self.place_search_provider(query=f"hotels in {city}", location=city, place_type="lodging", limit=10))
                candidates = []
                for row in rows:
                    loc = row.get("location") or {}
                    if not row.get("place_id") or loc.get("lat") is None:
                        continue
                    rating, count = row.get("rating"), row.get("user_rating_count")
                    stable_rating = (float(rating or 0) * min(1.0, (int(count or 0) / 200) ** .5))
                    candidates.append(HotelCandidate(
                        place_id=row["place_id"], name=row.get("name", ""), address=row.get("address") or "",
                        latitude=loc["lat"], longitude=loc["lng"], city=city, rating=rating,
                        user_rating_count=count, map_uri=row.get("map_uri"),
                        primary_type="lodging", business_status=row.get("business_status"), estimated_price=None,
                        price_source=None, room_rules_verified=False,
                        room_rules={rule: "unknown" for rule in ("smoking", "children_under_10", "pets", "parties", "overnight_visitors")},
                        ranking_score=stable_rating,
                    ))
                state.hotel_candidates_by_city[city] = sorted(candidates, key=lambda h: h.ranking_score, reverse=True)[:10]
            state.hotel_selection_status = "WAITING_USER_SELECTION" if cities else "NOT_STARTED"
            self._save(state, state.plan_version)
            return copy.deepcopy(state.hotel_candidates_by_city)

    def select_hotel(self, trip_id: str, city: str, place_id: str, version: int, request_id: str) -> WorkspaceState:
        with self._lock:
            current = self.get(trip_id)
            if request_id in current.applied_request_ids:
                return current
            state = self._require_version(trip_id, version)
            candidate = next((h for h in state.hotel_candidates_by_city.get(city, []) if h.place_id == place_id), None)
            if not candidate:
                raise PlaceRejected("HOTEL_CANDIDATE_NOT_FOUND")
            state.selected_hotels_by_city[city] = candidate
            self._lock_hotel_nodes(state, city, candidate)
            cities = {day.city for day in state.days if day.city}
            state.hotel_selection_status = "CONFIRMED" if cities <= set(state.selected_hotels_by_city) else "WAITING_USER_SELECTION"
            state.plan_version += 1; state.applied_request_ids.append(request_id)
            self._save(state, version)
            return copy.deepcopy(state)

    def use_recommended(self, trip_id: str, cities: list[str], version: int, request_id: str) -> WorkspaceState:
        state = self.get(trip_id)
        targets = cities or list(state.hotel_candidates_by_city)
        current_version = version
        for city in targets:
            candidates = state.hotel_candidates_by_city.get(city) or []
            if not candidates:
                raise PlaceRejected(f"NO_HOTEL_CANDIDATE:{city}")
            state = self.select_hotel(trip_id, city, candidates[0].place_id, current_version, f"{request_id}:{city}")
            current_version = state.plan_version
        return state

    def routes(self, trip_id: str, day_id: str) -> list[RouteSegment]:
        with self._lock:
            state = self.get(trip_id)
            if day_id not in state.route_segments_by_day:
                state.route_segments_by_day[day_id] = self._routes_for_day(self._find_day(state, day_id))
                self._save(state, state.plan_version)
            return copy.deepcopy(state.route_segments_by_day[day_id])

    def _routes_for_day(self, day: DayPlan) -> list[RouteSegment]:
        return [self._route_items(left, right) for left, right in zip(day.items, day.items[1:])]

    def _route_items(self, left: ItineraryItem, right: ItineraryItem) -> RouteSegment:
        mode = self._mode(right.transport)
        # AMap transit needs city metadata, which the route tool derives from
        # named places. Other modes can use exact GCJ-02 coordinates directly.
        use_coordinates = mode != "TRANSIT"
        origin = f"{left.longitude},{left.latitude}" if use_coordinates and left.latitude is not None and left.longitude is not None else left.location
        destination = f"{right.longitude},{right.latitude}" if use_coordinates and right.latitude is not None and right.longitude is not None else right.location
        key = f"route:{left.place_id or origin}:{right.place_id or destination}:{mode}"
        data = self._cache.get_or_set(key, self.ROUTE_TTL, lambda: self.route_provider(origin=origin, destination=destination, mode=mode))
        if not data or data.get("success") is False:
            return RouteSegment(segment_id=f"seg_{uuid4().hex[:10]}", from_item_id=left.item_id, to_item_id=right.item_id,
                travel_mode=mode, duration_minutes=float(right.transport_duration_minutes or 0), status="FALLBACK",
                warning="路线数据暂不可用；虚线仅作视觉提示，不代表真实路线")
        return RouteSegment(segment_id=f"seg_{uuid4().hex[:10]}", from_item_id=left.item_id, to_item_id=right.item_id,
            travel_mode=mode, duration_minutes=float(data.get("duration_minutes") or 0),
            distance_meters=round(float(data["distance_km"])*1000) if data.get("distance_km") is not None else None,
            encoded_polyline=data.get("encoded_polyline"), polyline=data.get("polyline") or [], status="REAL_ROUTE")

    def _route(self, previous: Optional[ItineraryItem], details: dict, place_id: str) -> Optional[RouteSegment]:
        if previous is None: return None
        target = ItineraryItem(time="00:00", activity="attraction", location=details["name"], duration_minutes=1,
            reason="route target", place_id=place_id)
        return self._route_items(previous, target)

    def _route_to_item(self, details: dict, place_id: str, following: Optional[ItineraryItem]) -> Optional[RouteSegment]:
        if following is None: return None
        source = ItineraryItem(time="00:00", activity="attraction", location=details["name"], duration_minutes=1,
            reason="route source", place_id=place_id)
        return self._route_items(source, following)

    @staticmethod
    def _lock_hotel_nodes(state: WorkspaceState, city: str, hotel: HotelCandidate) -> None:
        for day in state.days:
            if day.city != city: continue
            hotel_item = lambda time_value: ItineraryItem(time=time_value, activity="hotel", item_type="hotel", name=hotel.name,
                location=hotel.name, duration_minutes=1, estimated_cost=0, reason="用户确认酒店", city=city,
                place_id=hotel.place_id, latitude=hotel.latitude, longitude=hotel.longitude, user_locked=True,
                source="hotel_selection", place_details_status="VERIFIED")
            day.items = [item for item in day.items if item.source != "hotel_selection"]
            day.items.insert(0, hotel_item("08:00")); day.items.append(hotel_item("22:00"))
            day.accommodation = hotel.name

    def _require_version(self, trip_id: str, version: int) -> WorkspaceState:
        state = self.get(trip_id)
        if state.plan_version != version: raise PlanVersionConflict(f"expected {state.plan_version}, got {version}")
        return state

    @staticmethod
    def _find_day(state: WorkspaceState, day_id: str) -> DayPlan:
        for day in state.days:
            if (day.day_id or f"day_{day.day_number}") == day_id: return day
        raise WorkspaceNotFound(day_id)

    @staticmethod
    def _insert_index(day: DayPlan, after: Optional[str]) -> int:
        if not after: return 0
        for index, item in enumerate(day.items):
            if item.item_id == after: return index + 1
        raise PlaceRejected("INSERT_ANCHOR_NOT_FOUND")

    @staticmethod
    def _hhmm(value: Optional[str]) -> Optional[int]:
        if not value: return None
        match = re.match(r"^(\d{1,2}):(\d{2})$", value)
        return int(match.group(1))*60+int(match.group(2)) if match else None

    def _end_minutes(self, item: Optional[ItineraryItem]) -> int:
        return (self._hhmm(item.time) or 0) + (item.duration_minutes if item else 0)

    @staticmethod
    def _format_minutes(value: int) -> str:
        return f"{value//60:02d}:{value%60:02d}"

    @staticmethod
    def _city_from_address(address: str) -> Optional[str]:
        return None  # Text Search is city-biased; explicit provider city wins when available.

    @staticmethod
    def _activity_type(details: dict) -> str:
        types = details.get("types") or []
        return "restaurant" if "restaurant" in types else "attraction"

    @staticmethod
    def _mode(transport: Optional[str]) -> str:
        text = (transport or "").lower()
        if any(k in text for k in ("walk", "步行")): return "WALK"
        if any(k in text for k in ("drive", "taxi", "自驾", "出租")): return "DRIVE"
        if any(k in text for k in ("bicycle", "bike", "自行车")): return "BICYCLE"
        if any(k in text for k in ("ferry", "船")): return "FERRY"
        if any(k in text for k in ("flight", "航班")): return "FLIGHT"
        return "TRANSIT"

    def _meal_or_return_conflict(self, day: DayPlan) -> bool:
        dinner = [self._hhmm(item.time) for item in day.items if item.activity == "dinner"]
        returns = [self._hhmm(item.time) for item in day.items if item.activity in ("return_to_hotel", "hotel")]
        return any(value is not None and value > 22*60 for value in dinner) or any(value is not None and value > 23*60 for value in returns)

    @staticmethod
    def _conflict(reason: str, day_id: str, duration: int = 45) -> dict[str, Any]:
        return {"status": "INSERTION_CONFLICT", "reason": reason, "alternatives": [
            {"action": "INSERT_ON_ANOTHER_DAY", "day_id": day_id}, {"action": "SHORTEN_DURATION", "duration_minutes": min(45, duration)}]}


workspace_service = WorkspaceService()
