"""Offline tests for Round-6 Phase 5: wiring the unified `MemoryContext`
into the live graph -- `requirement_agent_node` building it,
`research_orchestrator_node` reading it and excluding historically-rejected
experiences, and `ResearchOrchestratorAgent`'s new `extra_exclude` parameter.
"""

from __future__ import annotations

import pytest

from travel_agent.agents.research_agent import ResearchOrchestratorAgent
from travel_agent.config.settings import get_settings
from travel_agent.schemas.travel_requirement import TravelRequirement


@pytest.fixture
def isolated_memory_paths(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("EPISODIC_MEMORY_PATH", str(tmp_path / "episodes.jsonl"))
    monkeypatch.setenv("USER_PROFILE_STORE_PATH", str(tmp_path / "profiles.json"))

    pytest.importorskip("chromadb")
    import chromadb

    from travel_agent.rag.chroma_client import HashEmbeddingFunction

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collections: dict = {}

    def _fake_get_collection(name, embedding_function=None):
        if name not in collections:
            collections[name] = client.get_or_create_collection(name=name, embedding_function=HashEmbeddingFunction())
        return collections[name]

    monkeypatch.setattr("travel_agent.rag.chroma_client.get_collection", _fake_get_collection)

    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# ResearchOrchestratorAgent: extra_exclude (historically-rejected experiences)
# ---------------------------------------------------------------------------

def test_run_full_excludes_historically_rejected_experiences(no_llm, stub_external_calls) -> None:
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")

    result = agent.run_full(req, extra_exclude=["浅草寺"])
    names = {e.name for e in result.experiences}
    assert "浅草寺" not in names
    assert len(result.experiences) > 0  # exclusion doesn't just empty everything out


def test_run_full_without_extra_exclude_can_include_it(no_llm, stub_external_calls) -> None:
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")

    result = agent.run_full(req)
    names = {e.name for e in result.experiences}
    assert "浅草寺" in names  # sanity check: it's normally reachable, so the exclude test means something


def test_run_feedback_merges_extra_exclude_with_existing_and_intent_exclude(no_llm, stub_external_calls) -> None:
    """`extra_exclude` must keep a rejected name out of *newly found*
    experiences too (not just names already absent from `existing`) --
    "多来点地标景点" triggers the `landmark`/`tourist_attraction` query that
    would otherwise surface 明治神宫 from the fake attraction pool."""
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")
    existing = agent.run_full(req, extra_exclude=["明治神宫"])
    assert "明治神宫" not in {e.name for e in existing.experiences}

    result = agent.run_feedback(req, existing, "多来点地标景点", extra_exclude=["明治神宫"])
    names = {e.name for e in result.experiences}
    assert "明治神宫" not in names


def test_run_expansion_merges_extra_exclude(no_llm, stub_external_calls) -> None:
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")
    existing = agent.run_full(req, extra_exclude=["明治神宫"])
    assert "明治神宫" not in {e.name for e in existing.experiences}

    result = agent.run_expansion(req, existing, missing_categories=["landmark"], extra_exclude=["明治神宫"])
    names = {e.name for e in result.experiences}
    assert "明治神宫" not in names


# ---------------------------------------------------------------------------
# graph/nodes.py wiring
# ---------------------------------------------------------------------------

def test_requirement_agent_node_builds_memory_context_and_profile_hint(no_llm, isolated_memory_paths) -> None:
    from travel_agent.graph.nodes import requirement_agent_node
    from travel_agent.memory.profile_memory import ProfileMemory

    user_id = "wiring-user-1"
    ProfileMemory().upsert(user_id, session_id="prior-session", travel_style="悠闲慢节奏")

    state = {
        "session_id": "new-session-1",
        "user_id": user_id,
        "user_message": "帮我规划一次东京5天的旅行，预算1万，2人",
        "travel_requirement": None,
        "conversation_history": [],
    }
    update = requirement_agent_node(state)

    assert update.get("memory_context") is not None
    assert update["memory_context"]["plan_used"]["profile"] is True
    profile_hint = update.get("user_profile_hint")
    assert profile_hint is not None
    assert profile_hint.get("travel_style") == "悠闲慢节奏"


def test_research_orchestrator_node_excludes_rejected_experiences(no_llm, stub_external_calls, isolated_memory_paths) -> None:
    from travel_agent.graph.nodes import research_orchestrator_node
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.schemas.memory import TripEpisode
    from travel_agent.schemas.travel_requirement import TravelRequirement

    user_id = "wiring-user-2"
    EpisodicMemory().add_episode(
        TripEpisode(
            user_id=user_id, session_id="prior-trip", destination="东京",
            rejected_experiences=["浅草寺"], feedback=["寺庙太多了"],
        )
    )

    req = TravelRequirement(destination="东京", num_travelers=2, budget=10000, pace="平衡")
    state = {
        "session_id": "new-session-2",
        "user_id": user_id,
        "user_message": "开始搜索",
        "travel_requirement": req.model_dump(),
        "research_mode": "initial",
    }
    update = research_orchestrator_node(state)

    names = {e["name"] for e in update["research_result"]["experiences"]}
    assert "浅草寺" not in names


# ---------------------------------------------------------------------------
# RAG-informed specialty discovery (the actual fix for "推荐的景点每次都一样"):
# `_places_worker` now checks `travel_guides` for the destination/region's
# specialties *before* building the Google Places query plan, instead of
# only ever using the generic baseline tags. Uses a synthetic destination
# name ("测试镇") so this can't collide with real ingested guide data or with
# other tests sharing the same session-wide isolated Chroma path
# (`RAG_CHROMA_PATH`, set once in conftest.py -- no per-test monkeypatching
# needed here since that env var isolation is real, not import-order-fragile).
# ---------------------------------------------------------------------------

@pytest.fixture
def travel_guide_for_test_town():
    from travel_agent.rag.ingestion.embedding_writer import write_chunks
    from travel_agent.rag.schemas import TravelGuideChunk

    chunk = TravelGuideChunk(
        id="test-town-guide#0::0",
        content="测试镇最有名的是瑜伽课程和黑胶唱片店，本地人晚上喜欢去livehouse看演出",
        parent_document_id="test-town-guide#0",
        chunk_index=0,
        collected_time="2026-7-22",
        canonical_destination="测试镇",
        canonical_region="测试镇",
        activity_topics=["瑜伽", "音乐"],
        source_title="测试镇特色体验攻略",
    )
    write_chunks([chunk])
    yield
    from travel_agent.rag.chroma_client import get_collection
    get_collection("travel_guides").delete(ids=["test-town-guide#0::0"])


def test_discover_specialties_finds_ingested_guide_content(no_llm, travel_guide_for_test_town) -> None:
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="测试镇")

    topics, titles = agent._discover_specialties(req, region=None, memory_context=None)

    assert "瑜伽" in topics
    assert "测试镇特色体验攻略" in titles


def test_discover_specialties_returns_empty_for_uncovered_destination(no_llm, travel_guide_for_test_town) -> None:
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="一个从未被攻略覆盖的地方")

    topics, titles = agent._discover_specialties(req, region=None, memory_context=None)
    assert topics == []
    assert titles == []


def test_places_worker_search_plan_includes_rag_discovered_topics(no_llm, stub_external_calls, travel_guide_for_test_town) -> None:
    """The concrete fix: Google Places is now *also* searched for whatever
    the RAG knowledge base says this destination specializes in, not only
    the generic baseline categories."""
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="测试镇")

    topics, _ = agent._discover_specialties(req, region=None, memory_context=None)
    region_candidate = agent._region_candidate_for(req, None, topics)

    from travel_agent.agents.research_agent import _TAG_QUERY_MAP, _query_generator

    baseline_plan = agent._build_search_plan(req, region=None)
    existing_tags = {tag for tag, _q, _pt in baseline_plan}
    rag_plan = _query_generator.generate(
        focus=[t for t in topics if t not in existing_tags],
        dest_label="测试镇", region_candidate=region_candidate, tag_query_map=_TAG_QUERY_MAP,
    )
    assert any("瑜伽" in query for query, _pt, _tag in rag_plan)


def test_region_candidate_for_merges_into_existing_known_region(no_llm, travel_guide_for_test_town) -> None:
    req = TravelRequirement(
        destination="测试镇", region_split_confirmed=True, region_preferences=["测试镇"],
        region_candidates=[{"name": "测试镇", "highlights": ["已知特色A"], "signature_experiences": ["已知体验A"]}],
    )
    agent = ResearchOrchestratorAgent()
    candidate = agent._region_candidate_for(req, "测试镇", ["瑜伽", "音乐"])

    assert "已知体验A" in candidate.signature_experiences  # existing data preserved
    assert "瑜伽" in candidate.signature_experiences  # RAG-discovered topics merged in


def test_region_candidate_for_returns_none_when_nothing_known_and_no_topics() -> None:
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="一个从未被覆盖的地方")
    assert agent._region_candidate_for(req, None, []) is None


def test_discover_specialties_never_calls_llm_even_when_configured(travel_guide_for_test_town) -> None:
    """Confirmed live: passing a real LLM into `rewrite_query()`/`rerank()`
    here made this method flip between finding and not finding the *same*
    single matching chunk across identical back-to-back calls (temperature
    sampling variance). `_discover_specialties` must stay heuristic-only
    regardless of whether `self._llm` is configured -- this test doesn't use
    `no_llm` on purpose, to prove the method itself never reaches for it."""

    class _PoisonLLM:
        def with_structured_output(self, schema, method="function_calling"):
            raise AssertionError("_discover_specialties must not invoke the LLM")

    agent = ResearchOrchestratorAgent()
    agent._llm = _PoisonLLM()
    req = TravelRequirement(destination="测试镇")

    topics, titles = agent._discover_specialties(req, region=None, memory_context=None)
    assert "瑜伽" in topics
    assert titles == ["测试镇特色体验攻略"]
