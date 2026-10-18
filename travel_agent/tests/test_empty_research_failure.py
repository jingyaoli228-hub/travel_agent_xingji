import pytest

from travel_agent.graph import nodes
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.travel_requirement import TravelRequirement


def test_initial_research_with_no_experiences_is_explicit_failure(monkeypatch, no_llm):
    requirement = TravelRequirement(
        destination="东京",
        duration_days=3,
        num_travelers=2,
        budget=10000,
        pace="平衡",
        confirmed=True,
    )
    requirement.apply_defaults()
    monkeypatch.setattr(nodes._research_agent, "run_full", lambda *args, **kwargs: ResearchResult())
    monkeypatch.setattr(nodes, "_memory_context_from_state", lambda _state: nodes.MemoryContext())

    with pytest.raises(RuntimeError, match="未返回任何候选"):
        nodes.research_orchestrator_node({
            "session_id": "empty-research",
            "user_id": "user-1",
            "travel_requirement": requirement.model_dump(),
            "research_mode": "initial",
        })
