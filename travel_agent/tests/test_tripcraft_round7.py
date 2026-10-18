from __future__ import annotations

import math

import numpy as np
import pytest

from travel_agent.evaluation.attraction_duration_config import ATTRACTION_DURATION_HOURS
from travel_agent.evaluation.planning_loop import MAX_PLAN_ATTEMPTS, build_repair_targets, choose_best, route_metric_attempt
from travel_agent.evaluation.tripcraft_metric_evaluator import (
    TripCraftMetricEvaluator, attraction_score, meal_score, persona_cosine_score, spatial_point_score,
)
from travel_agent.evaluation.tripcraft_parameters import ATTRACTION_PARAMETERS, MEAL_PARAMETERS
from travel_agent.evaluation.constraint_validator import ConstraintValidator
from travel_agent.memory.profile_merger import ProfileFieldUpdate, merge_profile_fields
from travel_agent.schemas.constraints import TravelConstraintSet
from travel_agent.schemas.itinerary import DayPlan, Itinerary, ItineraryItem


def item(activity="attraction", **updates):
    data = dict(time="10:00", activity=activity, location="Museum", transport="metro", duration_minutes=120,
                estimated_cost=10, reason="test", city="Paris", primary_category="Museums",
                nearest_transit_distance_meters=500)
    data.update(updates)
    return ItineraryItem(**data)


def itinerary(*items):
    return Itinerary(days=[DayPlan(day_number=1, city="Paris", accommodation="Hotel", items=list(items))])


def test_meal_score_matches_manual_formula():
    p = MEAL_PARAMETERS[3]["lunch"]
    x = np.array([14.0, 1.0]); mu = np.array(p[:2])
    covariance = np.array([[p[2] ** 2, p[4] * p[2] * p[3]], [p[4] * p[2] * p[3], p[3] ** 2]])
    expected = math.exp(-.5 * (x-mu) @ np.linalg.inv(covariance) @ (x-mu))
    assert meal_score(14.0, 1.0, p) == pytest.approx(expected)


def test_attraction_score_matches_paper_formula():
    p = ATTRACTION_PARAMETERS[3]; n = 2; duration = 2.5
    expected_duration = 3.0 - p["k"] * (n-p["n_min"])
    expected = math.exp(-((duration-expected_duration)**2)/(2*p["sigma"]**2)) * p["adventurous_lambda"]**n * math.exp(-p["adventurous_lambda"]) / math.factorial(n)
    assert attraction_score(duration, "Museums", n, "adventurous", p) == pytest.approx(expected)


def test_all_15_attraction_durations_are_present():
    assert len(ATTRACTION_DURATION_HOURS) == 15
    assert ATTRACTION_DURATION_HOURS["Water & Amusement Parks"] == 5.0


def test_spatial_piecewise_boundary():
    assert spatial_point_score(0) == 1
    assert spatial_point_score(5000) == pytest.approx(.5)
    assert spatial_point_score(5000.0001) < .5


def test_persona_uses_exactly_four_components():
    calls = []
    def embed(texts):
        calls.append(list(texts)); return np.tile(np.array([[1., 0.]]), (len(texts), 1))
    assert persona_cosine_score(["a", "b", "c", "d"], ["poi"], embed) == pytest.approx(1)
    assert len(calls[0][:4]) == 4
    assert persona_cosine_score(["age", "gender"], ["poi"], embed) is None


def test_missing_transit_distance_reduces_coverage():
    plan = itinerary(item(), item(location="Park", nearest_transit_distance_meters=None))
    report = TripCraftMetricEvaluator().evaluate(plan, {}, ConstraintValidator().validate(plan, TravelConstraintSet()))
    assert report.metric_coverage["spatial_metric_coverage"] == pytest.approx(.5)
    assert report.metric_coverage["missing_transit_distance_count"] == 1


def test_hard_constraint_beats_high_metrics():
    plan = itinerary(item(estimated_cost=200))
    report = ConstraintValidator().validate(plan, TravelConstraintSet(hard={"total_budget": 10}))
    assert not report.p0_passed
    best, best_report = choose_best({"name": "bad"}, {"hard_violations": [{"code":"budget"}], "commonsense_violations": [], "persona_score": 1.0},
                                    {"name":"good"}, {"hard_violations": [], "commonsense_violations": [], "persona_score": 0.0})
    assert best["name"] == "good"


def test_three_attempt_route_early_stop_and_cap():
    assert route_metric_attempt({"planner_attempt": 1, "metric_report": {"constraint_passed": True, "low_score_dimensions": []}}) == "reviewer"
    assert route_metric_attempt({"planner_attempt": MAX_PLAN_ATTEMPTS, "metric_report": {"constraint_passed": False, "hard_violations": [{"code":"budget"}]}}) == "constraint_relaxation"


def test_trip_specific_diving_does_not_pollute_long_term_profile():
    merged = merge_profile_fields({}, [ProfileFieldUpdate(field="interests", value=["diving"], scope="trip_specific", evidence=["这次想潜水"])])
    assert "interests" not in {key for key in merged if key != "trip_specific"}
    assert merged["trip_specific"]["interests"]["value"] == ["diving"]


def test_low_score_creates_dimension_target_without_whole_trip_replan():
    targets = build_repair_targets({"low_score_dimensions": ["spatial"], "hard_violations": [], "commonsense_violations": []})
    assert targets == [{"dimension": "spatial", "day": None, "poi": None, "problem": "spatial 指标低于独立阈值"}]
