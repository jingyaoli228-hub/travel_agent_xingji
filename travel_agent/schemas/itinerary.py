"""Schemas for the Planning stage and the Final Output."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from travel_agent.schemas.common import Source
from travel_agent.schemas.research_result import HotelOption


class ItineraryItem(BaseModel):
    """A single scheduled activity within a day."""

    time: str = Field(..., description="HH:MM 开始时间")
    activity: str = Field(..., description="活动名称，例如 breakfast/attraction/dinner/shopping")
    location: str
    transport: Optional[str] = Field(default=None, description="到达该地点的交通方式")
    duration_minutes: int = Field(..., description="预计时长（分钟）")
    estimated_cost: float = Field(default=0.0, description="预计花费")
    reason: str = Field(..., description="为什么安排该活动/地点")
    region: Optional[str] = Field(default=None, description="所属区域（复杂目的地拆分时使用）")


    city: Optional[str] = None
    primary_category: Optional[str] = None
    secondary_categories: List[str] = Field(default_factory=list)
    planned_duration_hours: Optional[float] = None
    nearest_transit_distance_meters: Optional[float] = None
    transport_duration_minutes: Optional[int] = None
    item_id: str = Field(default_factory=lambda: f"item_{uuid4().hex[:12]}")
    place_id: Optional[str] = None
    item_type: Optional[str] = None
    name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    user_locked: bool = False
    source: Literal["planner", "user_added", "hotel_selection", "transport"] = "planner"
    place_details_status: str = "UNKNOWN"


class DayPlan(BaseModel):
    day_number: int
    date: Optional[str] = None
    items: List[ItineraryItem] = Field(default_factory=list)
    city: Optional[str] = None
    accommodation: Optional[str] = None
    is_day_trip: bool = False
    is_cross_city: bool = False
    day_id: Optional[str] = None
    status: Optional[str] = None

    def total_cost(self) -> float:
        return sum(i.estimated_cost for i in self.items)


class Itinerary(BaseModel):
    """The full day-by-day plan produced by the Planner Agent."""

    days: List[DayPlan] = Field(default_factory=list)

    def total_cost(self) -> float:
        return sum(d.total_cost() for d in self.days)


class PlanFeasibility(BaseModel):
    """Output of the Planner's pre-generation check (`check_feasibility`).

    When `status == "insufficient"`, the Planner refuses to hard-generate a
    thin itinerary and instead signals the graph to loop back to the Research
    Orchestrator for a targeted expansion (see `graph/nodes.py`).
    """

    status: Literal["sufficient", "insufficient"] = "sufficient"
    reason: str = ""
    missing_categories: List[str] = Field(default_factory=list)


class BudgetBreakdown(BaseModel):
    flights: float = 0.0
    hotels: float = 0.0
    attractions: float = 0.0
    food: float = 0.0
    transport: float = 0.0
    shopping_buffer: float = 0.0
    total: float = 0.0
    currency: str = "CNY"


class TravelPlan(BaseModel):
    """Final assembled output presented to the user."""

    overview: str
    itinerary: Itinerary
    map_route_summary: str
    budget: BudgetBreakdown
    hotel_suggestions: List[HotelOption] = Field(default_factory=list)
    transport_suggestions: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    sources: List[Source] = Field(default_factory=list)
