"""Versioned itinerary-workspace, map, hotel, and patch API models."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from travel_agent.schemas.itinerary import DayPlan


class MoneyRange(BaseModel):
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    currency: str = "CNY"


class HotelCandidate(BaseModel):
    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    city: str
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    photos: List[str] = Field(default_factory=list)
    map_uri: Optional[str] = None
    website_uri: Optional[str] = None
    phone_number: Optional[str] = None
    primary_type: Optional[str] = None
    business_status: Optional[str] = None
    distance_to_city_center_meters: Optional[int] = None
    distance_to_transit_meters: Optional[int] = None
    average_route_minutes_to_pois: Optional[float] = None
    estimated_price: Optional[MoneyRange] = None
    price_source: Optional[str] = None
    room_rules_verified: bool = False
    room_rules: Dict[str, Literal["allowed", "forbidden", "unknown"]] = Field(default_factory=dict)
    ranking_score: float = 0.0


class RouteSegment(BaseModel):
    segment_id: str
    from_item_id: str
    to_item_id: str
    travel_mode: Literal["WALK", "TRANSIT", "DRIVE", "BICYCLE", "FERRY", "FLIGHT"]
    duration_minutes: float
    distance_meters: Optional[int] = None
    encoded_polyline: Optional[str] = None
    polyline: List[Dict[str, float]] = Field(default_factory=list)
    status: Literal["REAL_ROUTE", "FALLBACK", "UNAVAILABLE"]
    warning: Optional[str] = None


class VersionedMutation(BaseModel):
    current_plan_version: int = Field(alias="plan_version")
    request_id: str

    model_config = {"populate_by_name": True}


class InsertPoiRequest(VersionedMutation):
    place_id: str
    insert_after_item_id: Optional[str] = None
    preferred_duration_minutes: int = 90
    user_locked: bool = True
    force_insert: bool = False


class ApplyPatchRequest(VersionedMutation):
    patch_id: str


class HotelSelectionRequest(VersionedMutation):
    city: str
    place_id: str


class UseRecommendedHotelsRequest(VersionedMutation):
    cities: List[str] = Field(default_factory=list)


class WorkspaceState(BaseModel):
    trip_id: str
    plan_version: int = 1
    days: List[DayPlan] = Field(default_factory=list)
    route_segments_by_day: Dict[str, List[RouteSegment]] = Field(default_factory=dict)
    hotel_selection_status: Literal["NOT_STARTED", "WAITING_USER_SELECTION", "CONFIRMED"] = "NOT_STARTED"
    hotel_candidates_by_city: Dict[str, List[HotelCandidate]] = Field(default_factory=dict)
    selected_hotels_by_city: Dict[str, HotelCandidate] = Field(default_factory=dict)
    pending_patches: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    applied_request_ids: List[str] = Field(default_factory=list)
    mutation_results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    history: List[Dict[str, Any]] = Field(default_factory=list)
