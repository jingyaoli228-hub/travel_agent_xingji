from travel_agent.graph import nodes
from travel_agent.schemas.common import Source
from travel_agent.schemas.experience import TravelExperience
from travel_agent.schemas.research_result import DestinationInfo, ResearchResult


def _experience(name: str) -> TravelExperience:
    return TravelExperience(
        name=name,
        type="culture",
        location="北京",
        duration_minutes=90,
        cost=0,
        source=Source(title=name, url="https://example.com", source_type="amap"),
    )


def test_initial_research_reuses_prefetch_and_applies_confirmed_exclusion(monkeypatch, no_llm):
    prefetched = ResearchResult(
        destination_info=DestinationInfo(name="北京", country="中国"),
        experiences=[_experience("故宫博物院"), _experience("颐和园")],
    )
    monkeypatch.setattr(nodes.research_prefetch, "get_result", lambda session_id: prefetched.model_copy(deep=True))
    monkeypatch.setattr(nodes._research_agent, "run_full", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prefetch should be reused")))
    monkeypatch.setattr(nodes, "rejected_experience_names", lambda episodic: [])

    update = nodes.research_orchestrator_node({
        "session_id": "trip-prefetch",
        "user_id": "owner",
        "research_mode": "initial",
        "travel_requirement": {
            "destination": "北京",
            "duration_days": 3,
            "excluded_places": ["颐和园"],
        },
    })

    names = [row["name"] for row in update["research_result"]["experiences"]]
    assert names == ["故宫博物院"]
