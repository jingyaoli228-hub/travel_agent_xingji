"""Structured P0/P1/P2 travel constraints and deterministic reports."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


RoomType = Literal["entire_place", "private_room", "shared_room", "non_shared_accommodation"]


class CommonsenseConstraints(BaseModel):
    complete_information: bool = True
    sufficient_meal_gaps: bool = True
    valid_poi_list: bool = True
    diverse_events: bool = True
    within_current_city: bool = True
    reasonable_city_route: bool = True
    diverse_restaurants: bool = True
    diverse_attractions: bool = True
    non_conflicting_transportation: bool = True
    meals_per_day: Literal[2, 3] = 3
    minimum_meal_gap_hours: float = 4.0
    arrival_buffer_minutes: int = 90
    hotel_buffer_minutes: int = 60


class HardConstraints(BaseModel):
    total_budget: Optional[float] = None
    room_rules: List[str] = Field(default_factory=list)
    room_type: Optional[RoomType] = None
    allowed_cuisines: List[str] = Field(default_factory=list)
    preferred_cuisines: List[str] = Field(default_factory=list)
    excluded_cuisines: List[str] = Field(default_factory=list)
    forbid_flights: bool = False
    forbid_self_driving: bool = False
    required_event_types: List[str] = Field(default_factory=list)
    required_attraction_types: List[str] = Field(default_factory=list)


class PersonaPreferences(BaseModel):
    traveler_type: Optional[str] = None
    travel_purposes: List[str] = Field(default_factory=list)
    spending_preference: Optional[str] = None
    location_preferences: List[str] = Field(default_factory=list)


class TravelConstraintSet(BaseModel):
    commonsense: CommonsenseConstraints = Field(default_factory=CommonsenseConstraints)
    hard: HardConstraints = Field(default_factory=HardConstraints)
    persona: PersonaPreferences = Field(default_factory=PersonaPreferences)


class ConstraintViolation(BaseModel):
    priority: Literal["P0", "P1"]
    code: str
    message: str
    day: Optional[int] = None
    item: Optional[str] = None
    repairable: bool = True


class ConstraintValidationReport(BaseModel):
    hard_violations: List[ConstraintViolation] = Field(default_factory=list)
    commonsense_violations: List[ConstraintViolation] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    relaxation_options: List[str] = Field(default_factory=list)

    @property
    def p0_passed(self) -> bool:
        return not self.hard_violations

    @property
    def p1_passed(self) -> bool:
        return not self.commonsense_violations

    @property
    def passed(self) -> bool:
        return self.p0_passed and self.p1_passed

    @property
    def needs_constraint_relaxation(self) -> bool:
        return any(not violation.repairable for violation in self.hard_violations)

    def relaxation_response(self) -> Dict[str, Any]:
        return {
            "status": "NEEDS_CONSTRAINT_RELAXATION",
            "conflicts": self.conflicts or [v.message for v in self.hard_violations],
            "relaxation_options": self.relaxation_options,
        }
