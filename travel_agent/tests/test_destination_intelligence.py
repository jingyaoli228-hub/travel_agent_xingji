"""Tests for `travel_agent/destination_intelligence/service.py`: the
whole-destination region-split assessment (moved verbatim from
`RequirementAgent`, must stay behavior-preserving) and the new ad-hoc
single-region `profile_region()` entry point used by the post-plan
region-replacement flow.
"""

from __future__ import annotations

from travel_agent.agents.requirement_agent import RequirementAgent
from travel_agent.destination_intelligence.service import DestinationIntelligenceService
from travel_agent.schemas.destination import RegionCandidate
from travel_agent.schemas.travel_requirement import TravelRequirement


# -- assess_region_split (refactor-equivalence with pre-Round-5 behavior) ----


def test_assess_region_split_known_destination_offline():
    service = DestinationIntelligenceService()
    result = service.assess_region_split("巴厘岛")
    assert result.is_complex is True
    names = [r.name for r in result.regions]
    assert "Ubud" in names and "Nusa Penida" in names
    assert result.confirmation_message and "巴厘岛" in result.confirmation_message


def test_assess_region_split_simple_destination_offline():
    service = DestinationIntelligenceService()
    result = service.assess_region_split("东京")
    assert result.is_complex is False
    assert result.regions == []


def test_assess_region_split_empty_destination():
    service = DestinationIntelligenceService()
    result = service.assess_region_split("")
    assert result.is_complex is False


def test_requirement_agent_delegates_and_matches_prior_behavior(no_llm):
    """RequirementAgent.assess_destination_complexity() must produce
    identical output to calling the service directly -- proves the
    refactor (logic moved out of requirement_agent.py) is behavior-
    preserving, not just "doesn't crash"."""
    agent = RequirementAgent()
    req = TravelRequirement(destination="巴厘岛")
    via_agent = agent.assess_destination_complexity(req)

    service = DestinationIntelligenceService()
    via_service_directly = service.assess_region_split("巴厘岛", llm=None, system_prompt="")

    assert via_agent.model_dump() == via_service_directly.model_dump()


# -- profile_region (new: ad-hoc single-region lookup) ------------------------


def test_profile_region_known_region_returns_static_candidate():
    service = DestinationIntelligenceService()
    candidate = service.profile_region("巴厘岛", "Nusa Penida")
    assert candidate.name == "Nusa Penida"
    assert "潜水" in candidate.highlights


def test_profile_region_unknown_region_falls_back_to_heuristic_stub():
    """No LLM configured, region never seen before (e.g. "努沙佩尼达" as a
    CJK spelling the static table doesn't have an entry for under that
    exact alias) -- must not crash, must still carry the user's activity
    focus through as signature_experiences."""
    service = DestinationIntelligenceService()
    candidate = service.profile_region(
        "巴厘岛", "努沙佩尼达", focus_hint=["浮潜", "滑翔伞"], llm=None,
    )
    assert candidate.name == "努沙佩尼达"
    assert candidate.signature_experiences == ["浮潜", "滑翔伞"]
    assert isinstance(candidate, RegionCandidate)


def test_profile_region_deterministic_without_llm_patching_fixture():
    """The service takes `llm` as a call-time argument rather than holding
    a module-level client -- so `tests/conftest.py::no_llm` needs no entry
    for this module at all; calling with llm=None (the fixture's whole
    point) is sufficient and this test doesn't even need the fixture."""
    service = DestinationIntelligenceService()
    candidate = service.profile_region("未知目的地", "未知区域", focus_hint=["徒步"])
    assert candidate.name == "未知区域"
    assert candidate.signature_experiences == ["徒步"]
