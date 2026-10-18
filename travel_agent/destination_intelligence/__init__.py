"""Destination Intelligence: dynamically understands a destination/region's
own character (identity tags, signature experiences, local features)
instead of always searching fixed categories like "attractions". A shared
service, not a 5th agent -- called by `RequirementAgent` (whole-destination
region-split assessment, moved here verbatim from `requirement_agent.py`)
and, from Phase 5 onward, by the post-plan region-replacement flow
(ad-hoc, single-region lookup for a region the trip never planned around
originally, e.g. a mid-trip "swap Ubud for Nusa Penida" request).
"""

from __future__ import annotations

from travel_agent.destination_intelligence.service import DestinationIntelligenceService

__all__ = ["DestinationIntelligenceService"]
