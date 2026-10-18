"""Deterministic field-level merger for long-term and trip-specific profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


PROFILE_FIELDS = {
    "traveler_type", "travel_purposes", "spending_preference", "location_preferences",
    "age", "gender", "interests", "home_city", "home_country", "preferred_pace",
    "wake_time", "sleep_time", "daily_activity_count",
}
TRIPCRAFT_PERSONA_FIELDS = ("traveler_type", "travel_purposes", "spending_preference", "location_preferences")


class ProfileFieldUpdate(BaseModel):
    field: str
    value: Any
    confidence: float = 0.5
    scope: str = "trip_specific"
    explicitness: str = "explicit"
    evidence: list[str] = Field(default_factory=list)
    source_turn_ids: list[str] = Field(default_factory=list)
    last_updated_at: str = ""


def merge_profile_fields(existing: dict[str, Any], updates: list[ProfileFieldUpdate]) -> dict[str, Any]:
    """Merge whitelisted fields, retaining conflicting evidence; no whole-profile overwrite."""
    result = {key: value for key, value in existing.items()}
    result.setdefault("trip_specific", {})
    result.setdefault("conflicts", [])
    now = datetime.now(timezone.utc).isoformat()
    for update in updates:
        if update.field not in PROFILE_FIELDS:
            continue
        payload = update.model_dump()
        payload["last_updated_at"] = update.last_updated_at or now
        target = result if update.scope == "long_term" else result["trip_specific"]
        old = target.get(update.field)
        if old and old.get("value") != update.value:
            result["conflicts"].append({"field": update.field, "old": old, "new": payload})
            # Stronger evidence wins; evidence from both sides remains in conflicts.
            if float(old.get("confidence", 0)) > update.confidence:
                continue
        target[update.field] = payload
    return result


def tripcraft_persona_values(profile: dict[str, Any]) -> dict[str, Any]:
    return {field: (profile.get(field) or {}).get("value") for field in TRIPCRAFT_PERSONA_FIELDS}
