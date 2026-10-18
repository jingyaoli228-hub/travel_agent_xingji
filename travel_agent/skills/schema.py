"""Pydantic schema for a `SKILL.md` file's YAML frontmatter."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    name: str
    version: str = "1.0"
    activity_type: str = Field(description="Becomes TravelExperience.type, e.g. 'paragliding'.")
    synonyms: List[str] = Field(default_factory=list, description="Keywords that map onto activity_type, e.g. ['滑翔伞','跳伞'].")
    query_templates: List[str] = Field(
        default_factory=list, description="e.g. ['{dest} paragliding 滑翔伞体验'] -- {dest} is substituted at query time."
    )
    tool: str = Field(default="amap_places.search_places", description="Registry name from travel_agent/tool_runtime/registry.py.")
    place_type: Optional[str] = None
    display_label_cn: Optional[str] = None
    enabled: bool = True


class SkillDocument(BaseModel):
    manifest: SkillManifest
    body: str = ""
