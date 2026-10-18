"""Sanity tests for pydantic schemas."""

from travel_agent.schemas.itinerary import DayPlan, Itinerary, ItineraryItem
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.review import DimensionScores, ReviewReport
from travel_agent.schemas.travel_requirement import TravelRequirement


def test_travel_requirement_required_fields_detection():
    req = TravelRequirement(destination="东京", duration_days=5, num_travelers=2, budget=20000, pace="平衡")
    assert req.missing_required_fields() == []


def test_travel_requirement_missing_fields():
    req = TravelRequirement(destination="东京")
    missing = req.missing_required_fields()
    assert "num_travelers" in missing
    assert "budget" in missing


def test_travel_requirement_defaults():
    req = TravelRequirement(destination="东京", duration_days=5, num_travelers=2, budget=20000, pace="松弛")
    req.apply_defaults()
    assert req.daily_attraction_count == 2
    assert req.interests  # non-empty


def test_itinerary_total_cost():
    item = ItineraryItem(time="09:00", activity="attraction", location="X", duration_minutes=60, estimated_cost=100, reason="test")
    day = DayPlan(day_number=1, items=[item, item])
    itinerary = Itinerary(days=[day])
    assert itinerary.total_cost() == 200


def test_review_report_valid_scores():
    scores = DimensionScores(time_feasibility=90, route_efficiency=80, preference_match=85, richness=88, budget=95)
    report = ReviewReport(score=87, passed=True, dimension_scores=scores)
    assert report.passed is True


def test_research_result_defaults_empty():
    r = ResearchResult()
    assert r.experiences == []
    assert r.all_sources() == []
