"""Tests for the 4-layer Memory system (L1-L3; L0 is just AgentState).

Uses `tmp_path` + `monkeypatch` on `get_settings()` so these never touch the
real `./data/` directory, and never require Redis/a vector DB (both layers
degrade gracefully to file-backed stores when unconfigured, same pattern as
`redis_memory.py`).
"""

from __future__ import annotations

import pytest

from travel_agent.config.settings import get_settings
from travel_agent.memory.episodic_memory import EpisodicMemory
from travel_agent.memory.memory_manager import MemoryManager
from travel_agent.memory.profile_memory import ProfileMemory
from travel_agent.schemas.memory import TripEpisode
from travel_agent.schemas.travel_requirement import TravelRequirement


@pytest.fixture
def isolated_memory_paths(tmp_path, monkeypatch):
    """Point L2/L3 storage at a throwaway temp directory for this test only."""
    get_settings.cache_clear()
    monkeypatch.setenv("EPISODIC_MEMORY_PATH", str(tmp_path / "episodes.jsonl"))
    monkeypatch.setenv("USER_PROFILE_STORE_PATH", str(tmp_path / "profiles.json"))
    yield
    get_settings.cache_clear()


def test_profile_memory_upsert_and_get_roundtrip(isolated_memory_paths):
    store = ProfileMemory()
    store.upsert("user-1", travel_style="慢节奏休闲型", interest_preference=["music", "local_life"])

    profile = store.get("user-1")
    assert profile is not None
    assert profile.travel_style == "慢节奏休闲型"
    assert "music" in profile.interest_preference

    # a later upsert should merge list fields, not clobber them
    store.upsert("user-1", interest_preference=["coffee"])
    merged = store.get("user-1")
    assert set(merged.interest_preference) == {"music", "local_life", "coffee"}


def test_episodic_memory_retrieve_similar_trips_by_tag_overlap(isolated_memory_paths):
    store = EpisodicMemory()
    store.add_episode(TripEpisode(user_id="user-1", session_id="s1", destination="东京", tags=["music", "food"]))
    store.add_episode(TripEpisode(user_id="user-1", session_id="s2", destination="首尔", tags=["shopping"]))
    store.add_episode(TripEpisode(user_id="user-2", session_id="s3", destination="东京", tags=["music"]))

    similar = store.retrieve_similar_trips("user-1", tags=["music", "vinyl"], top_k=2)
    assert all(e.user_id == "user-1" for e in similar)
    assert similar[0].destination == "东京"  # higher tag overlap than the Seoul trip


def test_memory_manager_extract_user_preference_from_requirement():
    manager = MemoryManager.__new__(MemoryManager)  # skip __init__ (no storage needed here)
    req = TravelRequirement(
        destination="东京", pace="松弛", interests=["美食"], experience_preferences=["music", "local_life"],
    )
    prefs = manager.extract_user_preference(req, hotel={"area": "涩谷", "star_rating": 4})

    assert prefs["travel_style"] and "休闲" in prefs["travel_style"]
    assert "music" in prefs["interest_preference"] and "美食" in prefs["interest_preference"]
    assert prefs["hotel_preference"] == "4星附近 涩谷"


def test_memory_manager_retrieve_and_update_roundtrip(isolated_memory_paths):
    """Test5: a second trip should read back what a completed first trip wrote
    to L3, without needing a 5th agent -- MemoryManager is plain infrastructure."""
    manager = MemoryManager()
    user_id = "returning-user"

    manager.update_memory(
        "session-1", user_id,
        profile_fields={"interest_preference": ["music", "local_life", "coffee"], "travel_style": "慢节奏休闲型"},
        episode={
            "user_id": user_id, "session_id": "session-1", "destination": "东京",
            "tags": ["music", "local_life"],
        },
    )

    bundle = manager.retrieve_memory("session-2", user_id, tags=["music"])
    assert bundle.profile is not None
    assert "music" in bundle.profile.interest_preference
    assert len(bundle.similar_trips) >= 1
