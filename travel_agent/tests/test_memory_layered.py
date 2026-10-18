"""Offline tests for the Round-6 Phase 4 layered-memory upgrade: Redis
working memory, episodic/profile ChromaDB dual-write + confidence/status
state machine, and the Memory Context Builder.

Chroma-touching tests use `HashEmbeddingFunction` (no model download) via a
temp `PersistentClient`, patched at `travel_agent.rag.chroma_client.
get_collection` -- sufficient here because `episodic_memory.py`/
`profile_memory.py` both do their `from travel_agent.rag.chroma_client
import get_collection` *inside* the methods that use it (not at module
import time), so there's no stale-binding trap the way there was for the
top-level-import retrievers in `test_rag_retrieval.py`.
"""

from __future__ import annotations

import pytest

from travel_agent.config.settings import get_settings
from travel_agent.memory import working_memory
from travel_agent.memory.schemas import WorkingMemory


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
# working_memory (L0, now Redis-backed with in-memory fallback)
# ---------------------------------------------------------------------------

def test_working_memory_save_and_load_roundtrip() -> None:
    wm = WorkingMemory(session_id="wm-session-1", user_id="user-1", current_intent={"primary_intent": "NEW_TRIP"})
    working_memory.save(wm)

    loaded = working_memory.load("wm-session-1")
    assert loaded is not None
    assert loaded.user_id == "user-1"
    assert loaded.current_intent == {"primary_intent": "NEW_TRIP"}
    assert loaded.updated_at  # stamped by save()


def test_working_memory_load_missing_session_returns_none() -> None:
    assert working_memory.load("no-such-session-ever") is None


def test_working_memory_truncates_recent_messages_to_max_config() -> None:
    wm = WorkingMemory(session_id="wm-session-truncate", user_id="user-1")
    for i in range(20):
        wm.recent_messages.append({"role": "user", "content": f"msg-{i}"})
    working_memory.save(wm)

    loaded = working_memory.load("wm-session-truncate")
    assert loaded is not None
    assert len(loaded.recent_messages) == 12  # config/memory.yaml: max_working_messages
    assert loaded.recent_messages[-1]["content"] == "msg-19"  # kept the most recent ones


def test_working_memory_append_message_creates_if_missing() -> None:
    wm = working_memory.append_message("wm-session-append", "user-1", "user", "你好")
    assert wm.recent_messages == [{"role": "user", "content": "你好"}]

    wm2 = working_memory.append_message("wm-session-append", "user-1", "assistant", "在的")
    assert len(wm2.recent_messages) == 2


def test_update_from_state_builds_working_memory_from_agent_state() -> None:
    state = {
        "session_id": "wm-session-state",
        "user_id": "user-1",
        "intent_result": {"primary_intent": "REPLAN"},
        "travel_requirement": {"destination": "东京"},
        "itinerary": {"days": []},
        "need_user_input": True,
        "pending_response": "请确认行程",
    }
    wm = working_memory.update_from_state(state)
    assert wm.current_intent == {"primary_intent": "REPLAN"}
    assert wm.travel_requirement == {"destination": "东京"}
    assert wm.pending_confirmation == {"question": "请确认行程"}

    loaded = working_memory.load("wm-session-state")
    assert loaded is not None and loaded.travel_requirement == {"destination": "东京"}


# ---------------------------------------------------------------------------
# episodic_memory (L2): Chroma dual-write + semantic retrieval
# ---------------------------------------------------------------------------

def test_add_episode_dual_writes_to_chroma_when_important(isolated_memory_paths) -> None:
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.rag.chroma_client import get_collection
    from travel_agent.rag.config import load_rag_config
    from travel_agent.schemas.memory import TripEpisode

    EpisodicMemory().add_episode(
        TripEpisode(
            user_id="user-1", session_id="s1", destination="东京", tags=["music"],
            feedback=["寺庙和博物馆太多了"], rejected_experiences=["浅草寺"],
        )
    )
    collection = get_collection(load_rag_config().collections.episodic_memory)
    rows = collection.get(where={"user_id": "user-1"})
    assert len(rows["ids"]) == 1


def test_add_episode_skips_chroma_when_importance_below_threshold(isolated_memory_paths, monkeypatch) -> None:
    """A bare "trip completed" episode (no feedback/rejections/tags) is, by
    design, itself already a valid write trigger (requirement doc section
    21) -- its baseline importance_score (0.3) matches the *default*
    threshold, so it normally still qualifies. To exercise the actual
    skip path deterministically (rather than relying on the default
    threshold being exactly at the baseline), this raises the configured
    threshold above what a bare episode can reach."""
    from travel_agent.memory import episodic_memory as episodic_memory_module
    from travel_agent.memory.config import MemoryConfig
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.rag.chroma_client import get_collection
    from travel_agent.rag.config import load_rag_config
    from travel_agent.schemas.memory import TripEpisode

    monkeypatch.setattr(
        episodic_memory_module, "load_memory_config", lambda: MemoryConfig(episodic_importance_threshold=0.9)
    )

    EpisodicMemory().add_episode(TripEpisode(user_id="user-2", session_id="s2", destination=""))

    collection = get_collection(load_rag_config().collections.episodic_memory)
    rows = collection.get(where={"user_id": "user-2"})
    assert len(rows["ids"]) == 0

    # JSONL always gets it regardless (ground-truth ledger).
    all_episodes = EpisodicMemory().all_for_user("user-2")
    assert len(all_episodes) == 1


def test_retrieve_similar_trips_semantic_path_finds_match(isolated_memory_paths) -> None:
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.schemas.memory import TripEpisode

    store = EpisodicMemory()
    store.add_episode(
        TripEpisode(user_id="user-3", session_id="s1", destination="东京", tags=["music"], feedback=["寺庙太多了"])
    )
    store.add_episode(
        TripEpisode(user_id="user-3", session_id="s2", destination="首尔", tags=["shopping"], feedback=["购物街不错"])
    )

    results = store.retrieve_similar_trips("user-3", tags=[], top_k=2, query_text="东京 寺庙")
    assert len(results) >= 1
    assert any(e.destination == "东京" for e in results)


def test_retrieve_similar_trips_without_query_text_uses_jaccard_unchanged(isolated_memory_paths) -> None:
    """Backward-compat: no query_text -> original Jaccard-over-JSONL path,
    same contract as before Phase 4."""
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.schemas.memory import TripEpisode

    store = EpisodicMemory()
    store.add_episode(TripEpisode(user_id="user-4", session_id="s1", destination="东京", tags=["music", "food"]))
    store.add_episode(TripEpisode(user_id="user-4", session_id="s2", destination="首尔", tags=["shopping"]))

    similar = store.retrieve_similar_trips("user-4", tags=["music", "vinyl"], top_k=2)
    assert similar[0].destination == "东京"


def test_retrieve_similar_trips_semantic_failure_falls_back_to_jaccard(isolated_memory_paths, monkeypatch) -> None:
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.schemas.memory import TripEpisode

    store = EpisodicMemory()
    store.add_episode(TripEpisode(user_id="user-5", session_id="s1", destination="东京", tags=["music"]))

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated chroma outage")

    monkeypatch.setattr("travel_agent.rag.chroma_client.get_collection", _raise)

    results = store.retrieve_similar_trips("user-5", tags=["music"], top_k=2, query_text="东京旅行")
    assert len(results) == 1
    assert results[0].destination == "东京"


# ---------------------------------------------------------------------------
# profile_memory (L3): per-statement Chroma + confidence/status state machine
# ---------------------------------------------------------------------------

def test_upsert_creates_tentative_statement_with_confidence(isolated_memory_paths) -> None:
    from travel_agent.memory.profile_memory import ProfileMemory

    ProfileMemory().upsert("user-1", session_id="s1", travel_style="悠闲慢节奏")
    statements = ProfileMemory().get_statements("user-1")

    assert len(statements) == 1
    stmt = statements[0]
    assert stmt.preference_dimension == "travel_style"
    assert stmt.status == "TENTATIVE_PROFILE"
    assert stmt.evidence_count == 1
    assert stmt.confidence == pytest.approx(0.5)
    assert "悠闲慢节奏" in stmt.statement


def test_upsert_reinforcement_increases_confidence_and_evidence_count(isolated_memory_paths) -> None:
    from travel_agent.memory.profile_memory import ProfileMemory

    store = ProfileMemory()
    store.upsert("user-2", session_id="s1", travel_style="悠闲慢节奏")
    store.upsert("user-2", session_id="s2", travel_style="悠闲慢节奏")

    [stmt] = store.get_statements("user-2")
    assert stmt.evidence_count == 2
    assert stmt.confidence == pytest.approx(0.65)
    assert set(stmt.source_session_ids) == {"s1", "s2"}


def test_upsert_promotes_to_stable_after_threshold_reinforcements(isolated_memory_paths) -> None:
    from travel_agent.memory.profile_memory import ProfileMemory

    store = ProfileMemory()
    for i in range(3):  # config/memory.yaml: profile_stable_evidence_count == 3
        store.upsert("user-3", session_id=f"s{i}", travel_style="悠闲慢节奏")

    [stmt] = store.get_statements("user-3")
    assert stmt.evidence_count == 3
    assert stmt.status == "STABLE_PROFILE"


def test_upsert_merges_list_dimension_values_across_calls(isolated_memory_paths) -> None:
    from travel_agent.memory.profile_memory import ProfileMemory

    store = ProfileMemory()
    store.upsert("user-4", session_id="s1", interest_preference=["music"])
    store.upsert("user-4", session_id="s2", interest_preference=["coffee"])

    [stmt] = store.get_statements("user-4")
    assert set(stmt.value) == {"music", "coffee"}


def test_get_statements_falls_back_to_json_when_chroma_unavailable(isolated_memory_paths, monkeypatch) -> None:
    from travel_agent.memory.profile_memory import ProfileMemory

    store = ProfileMemory()
    store.upsert("user-5", session_id="s1", travel_style="悠闲")  # succeeds (chroma isolated+working)

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated chroma outage")

    monkeypatch.setattr("travel_agent.rag.chroma_client.get_collection", _raise)

    statements = store.get_statements("user-5")
    assert len(statements) == 1
    assert statements[0].preference_dimension == "travel_style"


def test_get_statements_unknown_user_returns_empty(isolated_memory_paths) -> None:
    from travel_agent.memory.profile_memory import ProfileMemory

    assert ProfileMemory().get_statements("no-such-user") == []


# ---------------------------------------------------------------------------
# context_builder (Memory Context Builder)
# ---------------------------------------------------------------------------

def test_build_context_default_plan_skips_episodic(isolated_memory_paths) -> None:
    from travel_agent.memory.context_builder import build_context
    from travel_agent.memory.profile_memory import ProfileMemory

    ProfileMemory().upsert("user-1", session_id="s1", travel_style="悠闲")
    context = build_context("session-1", "user-1")

    assert context.plan_used == {"working": True, "episodic": False, "profile": True}
    assert context.episodic == []
    assert len(context.profile_statements) == 1


def test_build_context_replan_intent_reads_all_three(isolated_memory_paths) -> None:
    from travel_agent.memory.context_builder import build_context
    from travel_agent.memory.profile_memory import ProfileMemory
    from travel_agent.memory.episodic_memory import EpisodicMemory
    from travel_agent.memory import working_memory
    from travel_agent.memory.schemas import WorkingMemory
    from travel_agent.schemas.memory import TripEpisode

    working_memory.save(WorkingMemory(session_id="session-2", user_id="user-2"))
    ProfileMemory().upsert("user-2", session_id="s1", travel_style="悠闲")
    EpisodicMemory().add_episode(
        TripEpisode(user_id="user-2", session_id="s1", destination="东京", feedback=["寺庙太多"])
    )

    context = build_context("session-2", "user-2", intent_key="REPLAN", query_text="东京")

    assert context.plan_used == {"working": True, "episodic": True, "profile": True}
    assert context.working is not None
    assert len(context.episodic) == 1
    assert len(context.profile_statements) == 1


def test_build_context_weather_query_skips_episodic_and_profile(isolated_memory_paths) -> None:
    from travel_agent.memory.context_builder import build_context

    context = build_context("session-3", "user-3", intent_key="WEATHER_QUERY")
    assert context.plan_used == {"working": True, "episodic": False, "profile": False}
    assert context.episodic == []
    assert context.profile_statements == []


def test_build_context_without_session_or_user_stays_empty() -> None:
    from travel_agent.memory.context_builder import build_context

    context = build_context("", "", intent_key="REPLAN")
    assert context.working is None
    assert context.episodic == []
    assert context.profile_statements == []


def test_memory_manager_build_context_delegates(isolated_memory_paths) -> None:
    from travel_agent.memory.memory_manager import MemoryManager
    from travel_agent.memory.profile_memory import ProfileMemory

    ProfileMemory().upsert("user-6", session_id="s1", travel_style="悠闲")
    manager = MemoryManager()
    context = manager.build_context("session-6", "user-6")
    assert len(context.profile_statements) == 1
