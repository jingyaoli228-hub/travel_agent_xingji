"""Translate only explicit requirement/profile evidence into constraints."""

from __future__ import annotations

from typing import Any

from travel_agent.schemas.constraints import TravelConstraintSet


def build_constraints(requirement: dict[str, Any], profile: dict[str, Any] | None = None) -> TravelConstraintSet:
    profile = profile or {}
    explicit = requirement.get("structured_constraints") or {}
    hard = dict(explicit.get("hard") or {})
    if requirement.get("budget") is not None:
        hard.setdefault("total_budget", requirement["budget"])
    hard.setdefault("forbid_flights", bool(requirement.get("forbid_flights", False)))
    hard.setdefault("forbid_self_driving", bool(requirement.get("forbid_self_driving", False)))
    persona = {
        "traveler_type": profile.get("traveler_type") or requirement.get("traveler_type"),
        "travel_purposes": profile.get("travel_purposes") or requirement.get("travel_purposes") or [],
        "spending_preference": profile.get("spending_preference") or requirement.get("spending_preference"),
        "location_preferences": profile.get("location_preferences") or requirement.get("location_preferences") or requirement.get("region_preferences") or [],
    }
    return TravelConstraintSet(commonsense=explicit.get("commonsense") or {}, hard=hard, persona=persona)
