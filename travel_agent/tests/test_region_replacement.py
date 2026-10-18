"""Tests for the Round-5 region-replacement feedback flow: resolving which
days a region swap applies to when the user gives no explicit day number
(`execution/region_resolution.py`), and pinning a specific rebuilt day to a
specific region without touching the global region split
(`PlannerAgent.run_partial(..., region_overrides=...)`).
"""

from __future__ import annotations

from travel_agent.agents.planner_agent import PlannerAgent
from travel_agent.execution.region_resolution import resolve_target_days_for_region
from travel_agent.schemas.itinerary import DayPlan, Itinerary, ItineraryItem
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.travel_requirement import TravelRequirement


def _item(location, region=None):
    return ItineraryItem(time="09:00", activity="attraction", location=location, duration_minutes=60, estimated_cost=0, reason="", region=region)


# -- resolve_target_days_for_region -------------------------------------------


def test_resolve_target_days_for_region_finds_matching_days():
    itinerary = Itinerary(days=[
        DayPlan(day_number=1, items=[_item("寺庙", region="Ubud")]),
        DayPlan(day_number=2, items=[_item("海滩", region="Canggu")]),
        DayPlan(day_number=3, items=[_item("瑜伽馆", region="Ubud"), _item("手作工坊", region="Ubud")]),
    ])
    assert resolve_target_days_for_region(itinerary, "Ubud") == [1, 3]


def test_resolve_target_days_for_region_no_match_returns_empty():
    itinerary = Itinerary(days=[DayPlan(day_number=1, items=[_item("海滩", region="Canggu")])])
    assert resolve_target_days_for_region(itinerary, "Ubud") == []


def test_resolve_target_days_for_region_handles_none_itinerary():
    assert resolve_target_days_for_region(None, "Ubud") == []
    assert resolve_target_days_for_region(Itinerary(days=[]), None) == []


# -- PlannerAgent.run_partial(region_overrides=...) ----------------------------


def _requirement() -> TravelRequirement:
    req = TravelRequirement(
        destination="巴厘岛", duration_days=5, num_travelers=2, budget=15000, pace="平衡", daily_attraction_count=2,
        region_preferences=["Ubud", "Canggu"], region_split_confirmed=True,
    )
    req.apply_defaults()
    return req


def _experience(name, type_="landmark", cost=0, region=None):
    return {
        "name": name, "type": type_, "category": "", "location": name, "region": region,
        "rating": 4.5, "popularity": 50.0, "duration_minutes": 90, "cost": cost, "currency": "CNY",
        "advantages": ["不错"], "disadvantages": [],
        "source": {"title": name, "url": "https://example.com", "source_type": "mock"},
    }


def test_run_partial_region_override_pins_day_without_touching_global_split(stub_external_calls, no_llm):
    req = _requirement()
    research = ResearchResult()
    selected = {
        "experiences": [
            _experience("乌布寺庙1", region="Ubud"),
            _experience("乌布寺庙2", region="Ubud"),
            _experience("乌布寺庙3", region="Ubud"),
            _experience("Canggu海滩1", region="Canggu"),
            _experience("Canggu海滩2", region="Canggu"),
            _experience("乌布餐厅1", type_="food", cost=50, region="Ubud"),
            _experience("Canggu餐厅1", type_="food", cost=50, region="Canggu"),
            _experience("Canggu餐厅2", type_="food", cost=50, region="Canggu"),
        ],
    }
    planner = PlannerAgent()
    initial, _ = planner.run(req, selected, research)
    assert len(initial.days) == 5

    # Simulate: Research just found Nusa-Penida-tagged snorkeling/paragliding
    # experiences (Phase 5 will make this dynamic; for this Phase-3 test the
    # region-tagged pool is what matters, not how it was discovered).
    extra_selected = {
        "experiences": selected["experiences"] + [
            _experience("浮潜体验", type_="snorkeling", region="Nusa Penida"),
            _experience("滑翔伞体验", type_="paragliding", region="Nusa Penida"),
        ],
    }

    target_day = next(d.day_number for d in initial.days if any(i.region == "Ubud" for i in d.items))
    updated = planner.run_partial(
        req, initial, research, extra_selected,
        target_days=[target_day],
        region_overrides={target_day: "Nusa Penida"},
    )

    changed_day = next(d for d in updated.days if d.day_number == target_day)
    changed_locations = {i.location.split(" (")[0] for i in changed_day.items}
    assert "浮潜体验" in changed_locations or "滑翔伞体验" in changed_locations
    # No Ubud-tagged item should have been pulled into the overridden day.
    assert not any(loc.startswith("乌布") for loc in changed_locations)

    # Every other day must be byte-identical to the pre-swap itinerary.
    for day in initial.days:
        if day.day_number == target_day:
            continue
        before = day.model_dump()
        after = next(d for d in updated.days if d.day_number == day.day_number).model_dump()
        assert before == after

    # The global, persisted split must be untouched -- a later full replan
    # must not be polluted by this one-off swap.
    assert req.region_preferences == ["Ubud", "Canggu"]


def test_run_partial_without_region_override_keeps_global_split(stub_external_calls, no_llm):
    req = _requirement()
    research = ResearchResult()
    selected = {
        "experiences": [
            _experience("乌布寺庙1", region="Ubud"),
            _experience("Canggu海滩1", region="Canggu"),
            _experience("乌布餐厅1", type_="food", cost=50, region="Ubud"),
            _experience("Canggu餐厅1", type_="food", cost=50, region="Canggu"),
        ],
    }
    planner = PlannerAgent()
    initial, _ = planner.run(req, selected, research)
    # No region_overrides passed -- must behave exactly like the pre-Round-5
    # `run_partial` (region_overrides defaults to None).
    updated = planner.run_partial(req, initial, research, selected, target_days=[1])
    assert len(updated.days) == len(initial.days)
