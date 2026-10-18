"""Unit tests for the Stage-3 Planner additions: `run_partial` (local
replan of specific days) and `run()`'s incremental-revision path (rebuild
only the days the reviewer flagged, instead of the whole trip from scratch
every review loop -- see planner_agent.py::PlannerAgent.run's docstring).
"""

from __future__ import annotations

from travel_agent.agents.planner_agent import PlannerAgent
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.travel_requirement import TravelRequirement


def _requirement() -> TravelRequirement:
    req = TravelRequirement(
        destination="东京", duration_days=3, num_travelers=2, budget=15000, pace="平衡", daily_attraction_count=2,
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


def _selected(names_by_type):
    experiences = []
    for type_, names in names_by_type.items():
        for n in names:
            experiences.append(_experience(n, type_=type_, cost=50 if type_ == "food" else 0))
    return {"experiences": experiences}


def test_run_partial_only_rebuilds_target_day(stub_external_calls, no_llm):
    req = _requirement()
    research = ResearchResult()
    # Exactly 2/day * 3 days, no leftover landmarks -- so the only "new"
    # candidate available when rebuilding day 2 is the wellness item, making
    # the assertion below unambiguous (see planner_agent.py's `_new_first`
    # pool-prioritization: brand-new candidates go first, but among two
    # equally-"new" leftovers FIFO order still applies).
    selected = _selected({
        "landmark": [f"景点{i}" for i in range(1, 7)],
        "food": [f"餐厅{i}" for i in range(1, 9)],
    })
    planner = PlannerAgent()
    initial, _ = planner.run(req, selected, research)
    assert len(initial.days) == 3

    extra_selected = {
        "experiences": selected["experiences"] + [_experience("新瑜伽课", type_="wellness")],
    }
    updated = planner.run_partial(req, initial, research, extra_selected, target_days=[2])

    day1_before = next(d for d in initial.days if d.day_number == 1).model_dump()
    day3_before = next(d for d in initial.days if d.day_number == 3).model_dump()
    day1_after = next(d for d in updated.days if d.day_number == 1).model_dump()
    day3_after = next(d for d in updated.days if d.day_number == 3).model_dump()

    assert day1_before == day1_after
    assert day3_before == day3_after
    day2_locations = {i.location.split(" (")[0] for i in next(d for d in updated.days if d.day_number == 2).items}
    assert "新瑜伽课" in day2_locations


def test_run_partial_does_not_duplicate_items_already_used_elsewhere(stub_external_calls, no_llm):
    req = _requirement()
    research = ResearchResult()
    selected = _selected({
        "landmark": [f"景点{i}" for i in range(1, 9)],
        "food": [f"餐厅{i}" for i in range(1, 9)],
    })
    planner = PlannerAgent()
    initial, _ = planner.run(req, selected, research)

    day1_names = {i.location.split(" (")[0] for i in next(d for d in initial.days if d.day_number == 1).items}

    updated = planner.run_partial(req, initial, research, selected, target_days=[2])
    day2_names = {i.location.split(" (")[0] for i in next(d for d in updated.days if d.day_number == 2).items}

    assert not (day1_names & day2_names & {n for n in day2_names if n.startswith("景点") or n.startswith("餐厅")})


def test_run_incremental_revision_only_touches_flagged_day(stub_external_calls, no_llm):
    req = _requirement()
    research = ResearchResult()
    selected = _selected({
        "landmark": [f"景点{i}" for i in range(1, 9)],
        "food": [f"餐厅{i}" for i in range(1, 9)],
    })
    planner = PlannerAgent()
    initial, _ = planner.run(req, selected, research)

    revised, _ = planner.run(
        req, selected, research,
        rule_issues=["第2天 lunch(12:00) 与前一活动时间冲突"],
        previous_itinerary=initial,
    )

    day1_before = next(d for d in initial.days if d.day_number == 1).model_dump()
    day3_before = next(d for d in initial.days if d.day_number == 3).model_dump()
    day1_after = next(d for d in revised.days if d.day_number == 1).model_dump()
    day3_after = next(d for d in revised.days if d.day_number == 3).model_dump()
    assert day1_before == day1_after
    assert day3_before == day3_after


def test_run_budget_issue_falls_back_to_full_rebuild_even_with_previous_itinerary(stub_external_calls, no_llm, monkeypatch):
    req = _requirement()
    research = ResearchResult()
    selected = _selected({
        "landmark": [f"景点{i}" for i in range(1, 9)],
        "food": [f"餐厅{i}" for i in range(1, 9)],
    })
    planner = PlannerAgent()
    initial, _ = planner.run(req, selected, research)

    calls = []
    original = planner._rebuild_days
    monkeypatch.setattr(planner, "_rebuild_days", lambda *a, **kw: (calls.append(1) or original(*a, **kw)))

    planner.run(
        req, selected, research,
        revision_instruction=["超预算，请优先选择更经济的餐厅/景点，降低总花费。"],
        rule_issues=["第2天 预估总花费超出预算"],
        previous_itinerary=initial,
    )
    assert calls == []  # budget issues are cross-day -- must NOT take the day-scoped path
