"""Offline regression harness for the ten P0 domestic golden itineraries.

The harness deliberately exercises the production candidate auto-selector
and production ReviewerAgent.  It does not call maps or an LLM, so CI gets a
deterministic signal for preference relevance, explicit include/exclude
constraints and the same >=85 quality gate shown to users.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from travel_agent.agents.research_agent import ResearchOrchestratorAgent
from travel_agent.agents.reviewer_agent import ReviewerAgent
from travel_agent.schemas.common import Source
from travel_agent.schemas.experience import TravelExperience
from travel_agent.schemas.itinerary import DayPlan, Itinerary, ItineraryItem
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.travel_requirement import TravelRequirement


class DomesticGoldenCase(BaseModel):
    case_id: str
    destination: str
    days: int = Field(ge=1, le=7)
    daily_count: int = Field(ge=1, le=6)
    preferred_types: List[str]
    required_names: List[str] = Field(default_factory=list)
    excluded_names: List[str] = Field(default_factory=list)
    candidates: List[Dict[str, Any]]
    min_preferred_ratio: float = Field(default=0.75, ge=0, le=1)
    min_reviewer_score: int = Field(default=85, ge=0, le=100)


class DomesticGoldenResult(BaseModel):
    case_id: str
    destination: str
    reviewer_score: int
    preferred_ratio: float
    selected_names: List[str]
    failures: List[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def load_domestic_golden_cases(path: str | Path) -> List[DomesticGoldenCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [DomesticGoldenCase.model_validate(item) for item in raw]


def _contains_name(names: List[str], requested: str) -> bool:
    return any(requested in name or name in requested for name in names)


def _research_result(case: DomesticGoldenCase) -> ResearchResult:
    source = Source(title="P0 国内黄金案例", url=f"golden://{case.case_id}", source_type="mock")
    experiences = [
        TravelExperience(
            **candidate,
            location=case.destination,
            duration_minutes=90,
            cost=0 if candidate.get("type") != "food" else 80,
            source=source,
            short_description=f"{case.destination}真实候选：{candidate['name']}",
        )
        for candidate in case.candidates
    ]
    return ResearchResult(experiences=experiences, sources=[source])


def _itinerary_from_selection(case: DomesticGoldenCase, selected: List[dict]) -> Itinerary:
    attractions = [item for item in selected if item.get("type") != "food"]
    foods = [item for item in selected if item.get("type") == "food"]
    days: List[DayPlan] = []
    for day_index in range(case.days):
        day_attractions = attractions[day_index * case.daily_count:(day_index + 1) * case.daily_count]
        items: List[ItineraryItem] = []
        for slot, candidate in enumerate(day_attractions):
            items.append(ItineraryItem(
                time=["09:00", "11:00", "14:00", "16:00", "17:30", "19:00"][slot],
                activity="attraction",
                location=f"{candidate['name']} ({case.destination})",
                duration_minutes=90,
                estimated_cost=float(candidate.get("cost") or 0),
                reason=f"符合本次 {candidate.get('type')} 偏好，候选可信度与口碑较高。",
            ))
        lunch = foods[(day_index * 2) % len(foods)] if foods else {"name": "当地特色餐厅"}
        dinner = foods[(day_index * 2 + 1) % len(foods)] if foods else {"name": "当地特色餐厅"}
        items.extend([
            ItineraryItem(time="13:00", activity="lunch", location=f"{lunch['name']} ({case.destination})", duration_minutes=60, estimated_cost=80, reason="选择真实检索到的本地餐饮候选。"),
            ItineraryItem(time="18:30", activity="dinner", location=f"{dinner['name']} ({case.destination})", duration_minutes=75, estimated_cost=100, reason="结合当天路线安排本地晚餐。"),
        ])
        items.sort(key=lambda item: item.time)
        days.append(DayPlan(day_number=day_index + 1, items=items))
    return Itinerary(days=days)


def evaluate_domestic_golden_case(case: DomesticGoldenCase) -> DomesticGoldenResult:
    research = _research_result(case)
    candidates: Dict[str, Dict[str, List[dict]]] = {"experiences": {}}
    for experience in research.experiences:
        candidates["experiences"].setdefault(experience.type, []).append(experience.model_dump())

    selector = ResearchOrchestratorAgent()
    selector._llm = None
    selected = selector.auto_select(
        candidates,
        daily_count=case.daily_count,
        days=case.days,
        preferred_types=case.preferred_types,
        required_names=case.required_names,
        excluded_names=case.excluded_names,
    )["experiences"]
    selected_names = [item["name"] for item in selected]
    selected_non_food = [item for item in selected if item.get("type") != "food"]
    preferred_hits = sum(item.get("type") in case.preferred_types for item in selected_non_food)
    preferred_ratio = round(preferred_hits / max(len(selected_non_food), 1), 3)

    requirement = TravelRequirement(
        destination=case.destination, duration_days=case.days, num_travelers=2, budget=10_000,
        pace="平衡", daily_attraction_count=case.daily_count, latest_return_time="21:30",
        experience_preferences=case.preferred_types, requested_places=case.required_names,
        excluded_places=case.excluded_names, confirmed=True,
    )
    reviewer = ReviewerAgent()
    reviewer.llm_reviewer._llm = None
    review = reviewer.review(_itinerary_from_selection(case, selected), requirement, research, loop_count=0)

    failures: List[str] = []
    for required in case.required_names:
        if not _contains_name(selected_names, required):
            failures.append(f"缺少必去地点：{required}")
    for excluded in case.excluded_names:
        if _contains_name(selected_names, excluded):
            failures.append(f"选入明确排除地点：{excluded}")
    if preferred_ratio < case.min_preferred_ratio:
        failures.append(f"偏好相关候选占比 {preferred_ratio:.0%} < {case.min_preferred_ratio:.0%}")
    if review.score < case.min_reviewer_score:
        failures.append(f"Reviewer {review.score} < {case.min_reviewer_score}")
    if review.issues:
        failures.extend(f"Reviewer 硬问题：{issue}" for issue in review.issues)

    return DomesticGoldenResult(
        case_id=case.case_id, destination=case.destination, reviewer_score=review.score,
        preferred_ratio=preferred_ratio, selected_names=selected_names, failures=failures,
    )


def evaluate_domestic_golden_suite(cases: List[DomesticGoldenCase]) -> List[DomesticGoldenResult]:
    return [evaluate_domestic_golden_case(case) for case in cases]
