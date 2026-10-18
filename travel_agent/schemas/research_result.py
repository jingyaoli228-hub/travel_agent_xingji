"""Schemas for the Research stage (workers, orchestrator output) and the
Candidate Selection stage (Recommendation Agent output).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from travel_agent.schemas.common import Source
from travel_agent.schemas.experience import TravelExperience


class DestinationInfo(BaseModel):
    name: str
    country: str
    timezone: Optional[str] = None
    currency: Optional[str] = None
    language: Optional[str] = None
    best_season: Optional[str] = None
    summary: Optional[str] = None


class VisaInfo(BaseModel):
    passport_country: str
    destination_country: str
    visa_required: bool
    visa_type: Optional[str] = None
    processing_days: Optional[int] = None
    notes: Optional[str] = None


class WeatherDay(BaseModel):
    """One day of the `get_weather` tool's real forecast (see tools/weather.py)."""

    date: str
    weather: str
    temperature: str = Field(..., description="例如 '20-27°C'")
    rain_probability: Optional[float] = None
    recommendation: str


class WeatherInfo(BaseModel):
    destination: str
    forecast: List[WeatherDay] = Field(default_factory=list)
    summary: Optional[str] = None


class FlightOption(BaseModel):
    airline: str
    flight_number: str
    departure_city: str
    arrival_city: str
    departure_time: str
    arrival_time: str
    price: float
    currency: str = "CNY"


class HotelOption(BaseModel):
    name: str
    area: str
    star_rating: Optional[float] = None
    price_per_night: Optional[float] = None
    price_source: Optional[str] = None
    currency: str = "CNY"
    rating: float
    highlights: List[str] = Field(default_factory=list)


class TransportOption(BaseModel):
    origin: str
    destination: str
    mode: str
    duration_minutes: int
    cost: float
    currency: str = "CNY"


class ResearchResult(BaseModel):
    """Aggregate output of the Research Orchestrator Agent."""

    destination_info: Optional[DestinationInfo] = None
    visa_info: Optional[VisaInfo] = None
    weather: Optional[WeatherInfo] = None
    flights: List[FlightOption] = Field(default_factory=list)
    hotels: List[HotelOption] = Field(default_factory=list)
    experiences: List[TravelExperience] = Field(default_factory=list)
    transportation: List[TransportOption] = Field(default_factory=list)
    web_notes: List[Source] = Field(default_factory=list, description="旅游攻略/网络资料来源")
    social_notes: List[Source] = Field(default_factory=list, description="小红书/Reddit 等社媒来源")
    sources: List[Source] = Field(default_factory=list, description="所有来源汇总")

    warnings: List[str] = Field(default_factory=list)

    def all_sources(self) -> List[Source]:
        seen = set()
        merged: List[Source] = []
        for s in self.sources + self.web_notes + self.social_notes:
            key = (s.title, s.url)
            if key not in seen:
                seen.add(key)
                merged.append(s)
        return merged

    @property
    def food_experiences(self) -> List[TravelExperience]:
        return [e for e in self.experiences if e.type == "food"]

    @property
    def non_food_experiences(self) -> List[TravelExperience]:
        return [e for e in self.experiences if e.type != "food"]
