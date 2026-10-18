"""Pydantic output schemas for the real (non-mock) tools in `travel_agent/tools/`.

Every tool returns one of these shapes (via `.model_dump()`, since LangChain
`@tool` functions must return JSON-serializable data). On failure (network
error, non-2xx response, missing API key, ...) a tool returns
`{"success": False, "error": "..."}` instead, so agents can detect the
failure and fall back / re-plan rather than silently receiving fabricated
data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from travel_agent.schemas.common import Source


class ToolError(BaseModel):
    success: bool = False
    error: str


class GeoPoint(BaseModel):
    lat: float
    lng: float


class PlaceResult(BaseModel):
    """One result from the configured POI provider."""

    name: str
    place_id: str
    address: Optional[str] = None
    rating: float = 0.0
    user_rating_count: int = 0
    location: Optional[GeoPoint] = None
    types: List[str] = Field(default_factory=list)
    price_level: Optional[str] = None
    city: Optional[str] = None
    source: str = "amap_places"
    success: bool = True


class PlaceDetails(BaseModel):
    """AMap POI details, normalized to the application contract."""

    name: str
    opening_hours: List[str] = Field(default_factory=list)
    rating: float = 0.0
    reviews: List[str] = Field(default_factory=list)
    price_level: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    types: List[str] = Field(default_factory=list)
    primary_category: Optional[str] = None
    business_status: Optional[str] = None
    map_uri: Optional[str] = None
    website_uri: Optional[str] = None
    phone_number: Optional[str] = None
    photos: List[str] = Field(default_factory=list)
    source: str = "amap_places"
    success: bool = True


class RouteStep(BaseModel):
    instruction: str
    duration_minutes: Optional[float] = None


class RouteResult(BaseModel):
    """Normalized route result."""

    origin: str
    destination: str
    mode: str
    distance_km: Optional[float] = None
    duration_minutes: float
    steps: List[RouteStep] = Field(default_factory=list)
    cost: Optional[float] = None
    currency: str = "CNY"
    encoded_polyline: Optional[str] = None
    polyline: List[GeoPoint] = Field(default_factory=list)
    source: str = "amap_routes"
    success: bool = True


class WeatherDayResult(BaseModel):
    """AMap weather forecast for one day."""

    date: str
    temperature: str
    weather: str
    rain_probability: Optional[float] = None
    recommendation: str
    source: str = "weather_api"
    success: bool = True


class GuideResult(BaseModel):
    """One travel-guide / social-content search result (Agent Reach)."""

    title: str
    url: str
    snippet: Optional[str] = None
    platform: str
    source: str = "agent_reach"
    success: bool = True


def as_source(item: Dict[str, Any], title_key: str = "name") -> Source:
    """Build a `Source` citation from a tool result dict."""
    return Source(
        title=item.get(title_key, "unknown"),
        url=item.get("url") or item.get("map_uri") or "https://www.amap.com/",
        source_type="amap",
        snippet=item.get("snippet"),
    )
