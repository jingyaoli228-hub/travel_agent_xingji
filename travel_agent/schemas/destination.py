"""Destination-complexity schemas.

Owned by the Requirement Agent: deciding whether a destination should be
split into regions (e.g. Bali -> Ubud/Canggu/Seminyak/Nusa Penida) and, if so,
presenting candidates for the user to confirm before Research runs per-region.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RegionCandidate(BaseModel):
    name: str
    highlights: List[str] = Field(default_factory=list)
    typical_experience_types: List[str] = Field(
        default_factory=list, description="该区域典型体验类型，例如 ['surf','beach','nightlife']"
    )
    notes: Optional[str] = None

    # Round-5: Destination Intelligence -- dynamically-discovered profile
    # fields, additive (safe defaults so an old `RegionCandidate` built from
    # `_KNOWN_COMPLEX_DESTINATIONS`'s static dict still validates unchanged).
    # Deliberately free-text / not constrained to EXPERIENCE_TYPES, unlike
    # `typical_experience_types` above -- the whole point is to name things
    # like "浮潜"/"滑翔伞" that aren't in that fixed vocabulary.
    identity: List[str] = Field(default_factory=list, description="身份标签，例如 ['冲浪圣地','嬉皮文化']")
    signature_experiences: List[str] = Field(default_factory=list, description="标志性体验，自由文本")
    local_features: List[str] = Field(default_factory=list, description="本地特色，例如 ['当地渔市','传统火祭']")


class DestinationComplexityAssessment(BaseModel):
    destination: str = ""
    is_complex: bool = False
    regions: List[RegionCandidate] = Field(default_factory=list)
    confirmation_message: Optional[str] = Field(
        default=None, description="向用户确认是否按区域拆分的提问文案"
    )
