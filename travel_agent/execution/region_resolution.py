"""Resolves which itinerary days a region-replacement request targets when
the user doesn't state an explicit day number (e.g. "把乌布换成努沙佩尼达"
with no "第3天"). Scans the existing itinerary for days that currently have
anything tagged with `source_region` -- those are the days the swap applies
to.
"""

from __future__ import annotations

from typing import List, Optional

from travel_agent.schemas.itinerary import Itinerary


def resolve_target_days_for_region(itinerary: Optional[Itinerary], source_region: Optional[str]) -> List[int]:
    if itinerary is None or not source_region:
        return []
    days: List[int] = []
    for day in itinerary.days:
        if day.day_number in days:
            continue
        if any(item.region == source_region for item in day.items):
            days.append(day.day_number)
    return days
