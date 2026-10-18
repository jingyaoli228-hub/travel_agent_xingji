"""Static registry of known tool names -> metadata the middleware needs but
can't infer from the tool call site alone: whether the result shape is a
list (google_places.search_places, search.search_travel_guides,
xhs_search.search) or a single dict, and a manual pydantic parameter schema
for the one tool that isn't a LangChain `@tool` object (`xhs_search.search`,
a plain instance method -- the other five already carry an auto-generated
`args_schema` LangChain attaches to every `@tool`-decorated function, which
`ToolManager` reads directly off the tool object; no need to duplicate it
here).

Phase 2 (Dynamic Skill Runtime) references tools by these exact name strings
-- a `SKILL.md`'s `tool:` field must match one of these keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Type

from pydantic import BaseModel


class XhsSearchArgs(BaseModel):
    keyword: str
    limit: int = 10


@dataclass(frozen=True)
class ToolSpec:
    name: str
    result_is_list: bool = False
    args_schema: Optional[Type[BaseModel]] = None


TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "amap_places.search_places": ToolSpec(name="amap_places.search_places", result_is_list=True),
    "amap_places.get_place_details": ToolSpec(name="amap_places.get_place_details"),
    "amap_routes.calculate_route": ToolSpec(name="amap_routes.calculate_route"),
    "weather.get_weather": ToolSpec(name="weather.get_weather"),
    "search.search_travel_guides": ToolSpec(name="search.search_travel_guides", result_is_list=True),
    "visa.search_visa_information": ToolSpec(name="visa.search_visa_information"),
    "xhs_search.search": ToolSpec(name="xhs_search.search", result_is_list=True, args_schema=XhsSearchArgs),
}


def get_tool_spec(tool_name: str) -> ToolSpec:
    return TOOL_REGISTRY.get(tool_name) or ToolSpec(name=tool_name)


def register_tool(spec: ToolSpec) -> None:
    """Add/override a tool's registry entry. Exposed for Phase 2 (Skill
    Runtime) and tests -- production tool set above never needs this."""
    TOOL_REGISTRY[spec.name] = spec
