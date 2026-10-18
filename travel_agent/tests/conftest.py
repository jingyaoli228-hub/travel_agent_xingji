"""Shared pytest fixtures.

The tools/agents now call real external services (Google Places / Routes /
Weather, Agent Reach, Kimi). Unit tests that exercise the *tool parsing
logic* mock at the HTTP/subprocess boundary (see `test_tools.py`). Tests that
exercise the *graph/agent orchestration* (see `test_workflow.py`,
`test_requirement_agent.py`) don't care about real API responses, so this
conftest provides fixtures that stub the tool `.invoke` calls with
deterministic fake data and force every agent's LLM off (back to the
rule-based/heuristic path), keeping those tests fast, free and offline --
exactly like the original mock-based test suite.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional

import pytest

# Redirect L2/L3 memory storage (`episodic_memory_path`/`user_profile_store_path`,
# see `travel_agent/config/settings.py`) at a throwaway temp directory *before*
# any test module import can trigger `travel_agent.graph.nodes`' module-level
# `MemoryManager()` singleton construction (which reads these paths eagerly).
# Without this, running the test suite would write real files into the
# project's `./data/` directory.
_TEST_MEMORY_DIR = tempfile.mkdtemp(prefix="travel_agent_test_memory_")
os.environ.setdefault("EPISODIC_MEMORY_PATH", os.path.join(_TEST_MEMORY_DIR, "episodic_memory.jsonl"))
os.environ.setdefault("USER_PROFILE_STORE_PATH", os.path.join(_TEST_MEMORY_DIR, "user_profiles.json"))

# Round-6: `episodic_memory.py`/`profile_memory.py` additionally dual-write
# into ChromaDB (`config/rag.yaml: chroma_path`, default `./data/chroma` --
# not a `Settings`/env-var field, so the JSONL/JSON redirection above doesn't
# cover it). Same rationale as above -- `travel_agent.rag.config.
# load_rag_config()` respects this override (see that module).
os.environ.setdefault("RAG_CHROMA_PATH", os.path.join(_TEST_MEMORY_DIR, "chroma"))

_ATTRACTIONS = [
    {"name": "浅草寺", "types": ["buddhist_temple", "tourist_attraction"], "rating": 4.6, "user_rating_count": 90000},
    {"name": "东京晴空塔", "types": ["tourist_attraction", "landmark"], "rating": 4.5, "user_rating_count": 80000},
    {"name": "明治神宫", "types": ["shinto_shrine", "tourist_attraction"], "rating": 4.7, "user_rating_count": 70000},
    {"name": "涩谷十字路口", "types": ["tourist_attraction", "point_of_interest"], "rating": 4.4, "user_rating_count": 60000},
    {"name": "银座", "types": ["shopping_mall", "tourist_attraction"], "rating": 4.5, "user_rating_count": 50000},
    {"name": "原宿竹下通", "types": ["shopping_mall"], "rating": 4.3, "user_rating_count": 40000},
    {"name": "上野公园", "types": ["park", "tourist_attraction"], "rating": 4.4, "user_rating_count": 30000},
    {"name": "新宿御苑", "types": ["park", "garden"], "rating": 4.6, "user_rating_count": 20000},
    {"name": "下北泽古着街", "types": ["point_of_interest"], "rating": 4.3, "user_rating_count": 10000},
    {"name": "台场海滨公园", "types": ["park", "natural_feature"], "rating": 4.2, "user_rating_count": 9000},
    {"name": "秋叶原电器街", "types": ["shopping_mall", "tourist_attraction"], "rating": 4.4, "user_rating_count": 8000},
    {"name": "谷根千老街散步", "types": ["point_of_interest"], "rating": 4.5, "user_rating_count": 7000},
]

_RESTAURANTS = [
    {"name": "一兰拉面 涩谷店", "rating": 4.4, "user_rating_count": 9000, "price_level": "PRICE_LEVEL_INEXPENSIVE"},
    {"name": "筑地场外市场海鲜丼", "rating": 4.5, "user_rating_count": 8000, "price_level": "PRICE_LEVEL_MODERATE"},
    {"name": "银座数寄屋桥次郎", "rating": 4.8, "user_rating_count": 2000, "price_level": "PRICE_LEVEL_VERY_EXPENSIVE"},
    {"name": "烧肉牛角 新宿店", "rating": 4.2, "user_rating_count": 6000, "price_level": "PRICE_LEVEL_MODERATE"},
    {"name": "原宿可丽饼店", "rating": 4.1, "user_rating_count": 5000, "price_level": "PRICE_LEVEL_INEXPENSIVE"},
    {"name": "叙叙苑烤肉 银座本店", "rating": 4.6, "user_rating_count": 3000, "price_level": "PRICE_LEVEL_EXPENSIVE"},
    {"name": "浅草今半寿喜烧", "rating": 4.5, "user_rating_count": 4000, "price_level": "PRICE_LEVEL_MODERATE"},
    {"name": "秋叶原女仆咖啡厅", "rating": 3.9, "user_rating_count": 3500, "price_level": "PRICE_LEVEL_MODERATE"},
]


def _fake_place(name: str, idx: int, rating: float, count: int, price_level: Optional[str] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "place_id": f"fake-place-{idx}",
        "address": "东京",
        "rating": rating,
        "user_rating_count": count,
        "location": {"lat": 35.68 + idx * 0.001, "lng": 139.76 + idx * 0.001},
        "types": [],
        "price_level": price_level,
        "source": "google_places",
        "success": True,
    }


def _fake_search_places(**kwargs) -> List[Dict[str, Any]]:
    place_type = kwargs.get("place_type")
    exclude = set(kwargs.get("exclude_names") or [])
    limit = kwargs.get("limit", 10)

    if place_type == "restaurant":
        pool = _RESTAURANTS
    elif place_type == "lodging":
        return [_fake_place("东京湾酒店", 0, 4.2, 500, "PRICE_LEVEL_MODERATE")]
    elif place_type == "tourist_attraction":
        pool = _ATTRACTIONS
    else:
        # generic / geocoding-only call (e.g. weather worker) -- single hit is enough.
        return [_fake_place(kwargs.get("query", "东京"), 0, 4.5, 1000)]

    results = []
    for i, item in enumerate(pool):
        if item["name"] in exclude or len(results) >= limit:
            continue
        place = _fake_place(item["name"], i, item["rating"], item["user_rating_count"], item.get("price_level"))
        place["types"] = item.get("types", [])
        results.append(place)
    return results


def _fake_get_place_details(**kwargs) -> Dict[str, Any]:
    return {
        "name": "详情",
        "opening_hours": ["Monday: 9:00 AM – 6:00 PM"],
        "rating": 4.5,
        "reviews": ["非常值得一去，风景很好。", "人比较多，建议早点去。"],
        "price_level": None,
        "source": "google_places",
        "success": True,
    }


def _fake_calculate_route(**kwargs) -> Dict[str, Any]:
    mode = str(kwargs.get("mode", "transit")).upper()
    return {
        "origin": kwargs.get("origin", ""),
        "destination": kwargs.get("destination", ""),
        "mode": mode,
        "distance_km": 3.0,
        "duration_minutes": 20.0,
        "steps": [],
        "cost": 0.0,
        "currency": "CNY",
        "source": "google_routes",
        "success": True,
    }


def _fake_get_weather(**kwargs) -> Dict[str, Any]:
    return {
        "date": kwargs.get("travel_date", ""),
        "temperature": "20-27°C",
        "weather": "晴",
        "rain_probability": 10.0,
        "recommendation": "天气较为舒适，正常安排行程即可",
        "source": "weather_api",
        "success": True,
    }


def _fake_search_travel_guides(**kwargs) -> List[Dict[str, Any]]:
    platform = kwargs.get("platform", "web")
    return [
        {
            "title": f"{kwargs.get('destination', '')} 攻略 #{i}",
            "url": f"https://example.com/guide/{i}",
            "snippet": "热门玩法与避坑提示。",
            "platform": platform,
            "source": "agent_reach",
            "success": True,
        }
        for i in range(kwargs.get("limit", 3))
    ]


def _fake_xhs_search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
    return [
        {
            "title": f"{keyword} 小红书笔记 #{i}",
            "author": f"博主{i}",
            "likes": str(1000 - i * 100),
            "url": f"https://www.xiaohongshu.com/search_result/fake{i}",
            "content": None,
            "tags": [],
        }
        for i in range(min(limit, 5))
    ]


@pytest.fixture
def stub_external_calls(monkeypatch):
    """Stub every real-API tool call with deterministic fake data."""
    from travel_agent.tools import google_places, google_routes, search, weather
    from travel_agent.tools.xhs_search import XiaohongshuSearcher

    monkeypatch.setattr(google_places.search_places, "func", _fake_search_places)
    monkeypatch.setattr(google_places.get_place_details, "func", _fake_get_place_details)
    monkeypatch.setattr(google_routes.calculate_route, "func", _fake_calculate_route)
    monkeypatch.setattr(weather.get_weather, "func", _fake_get_weather)
    monkeypatch.setattr(search.search_travel_guides, "func", _fake_search_travel_guides)
    monkeypatch.setattr(XiaohongshuSearcher, "search", _fake_xhs_search)


@pytest.fixture
def no_llm(monkeypatch):
    """Force every agent (new + already-constructed singletons) onto its offline heuristic path.

    Each agent module did `from travel_agent.config.llm import get_llm`, which
    binds its own local name at import time -- patching the origin module's
    attribute alone would not affect an already-imported reference, so we
    patch every agent module's local `get_llm` name too (for agents
    constructed fresh inside a test) in addition to zeroing out the
    already-constructed singletons' `._llm` (for the graph/workflow tests).
    """
    no_llm_fn = lambda role=None, tier=None, temperature=None: None
    monkeypatch.setattr("travel_agent.config.llm.get_llm", no_llm_fn)
    monkeypatch.setattr("travel_agent.agents.requirement_agent.get_llm", no_llm_fn)
    monkeypatch.setattr("travel_agent.agents.research_agent.get_llm", no_llm_fn)
    monkeypatch.setattr("travel_agent.agents.planner_agent.get_llm", no_llm_fn)
    monkeypatch.setattr("travel_agent.agents.reviewer_agent.get_llm", no_llm_fn)
    monkeypatch.setattr("travel_agent.intent.llm_resolver.get_llm", no_llm_fn)
    # Round-6 Phase 6: `graph/nodes.py::strict_evaluation_node` also does
    # `from travel_agent.config.llm import get_llm` at module import time --
    # same stale-binding trap as every other agent module above. Without
    # this, a real (60-100s) DeepSeek/Kimi call fires from *every* test that
    # reaches `strict_evaluation_node` whenever a real API key is configured
    # in `.env` -- confirmed live, this alone was enough to make the full
    # suite hang well past two minutes.
    monkeypatch.setattr("travel_agent.graph.nodes.get_llm", no_llm_fn)

    from travel_agent.graph import nodes

    monkeypatch.setattr(nodes._requirement_agent, "_llm", None)
    monkeypatch.setattr(nodes._research_agent, "_llm", None)
    monkeypatch.setattr(nodes._planner_agent, "_llm", None)
    monkeypatch.setattr(nodes._reviewer_agent.llm_reviewer, "_llm", None)
    # `nodes._intent_interpreter` is also a module-level singleton built at
    # import time -- its `LLMIntentResolver._llm` was already bound to
    # whatever `get_llm()` returned back then (a real DeepSeek/Kimi client
    # whenever an API key is configured), so patching `get_llm` above never
    # touches it. Left unset, "offline" tests silently make real, temperature-
    # sampled LLM calls in the Deep Path fusion (see fusion_resolver.fuse()'s
    # `entities = llm.entities if (llm and llm.entities) else ...`), which is
    # what made e.g. test_post_plan_feedback.py's category-extraction
    # assertions flaky across process runs.
    monkeypatch.setattr(nodes._intent_interpreter._llm_resolver, "_llm", None)
