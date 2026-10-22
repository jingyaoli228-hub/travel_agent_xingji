"""Tests for the Research Orchestrator's Stage-2 behaviors: tag-driven search
plans and the Research Feedback Loop's offline intent parsing.

These force the LLM off (`no_llm` fixture, see `conftest.py`) so they exercise
the deterministic/heuristic paths.
"""

from travel_agent.agents.research_agent import ResearchOrchestratorAgent
from travel_agent.schemas.common import Source
from travel_agent.schemas.destination import RegionCandidate
from travel_agent.schemas.experience import TravelExperience
from travel_agent.schemas.travel_requirement import TravelRequirement


def test_search_plan_adds_music_tag_on_top_of_baseline(no_llm):
    """Test1: a music/vinyl preference should ADD music-tagged queries to the
    baseline discovery set, not replace it -- so the user still gets landmarks
    *and* Tower-Records/livehouse-style results, not just one or the other."""
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京", experience_preferences=["music"])
    plan = agent._build_search_plan(req)
    tags = {tag for tag, _query, _place_type in plan}
    assert "music" in tags
    assert "landmark" in tags  # baseline breadth preserved
    music_queries = [q for tag, q, _ in plan if tag == "music"]
    assert any("黑胶" in q or "livehouse" in q for q in music_queries)


def test_search_plan_without_preferences_stays_broad(no_llm):
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")
    plan = agent._build_search_plan(req)
    tags = {tag for tag, _q, _pt in plan}
    assert {"landmark", "culture", "nature", "shopping", "food"}.issubset(tags)


def test_search_plan_region_scoped_uses_region_typical_types(no_llm):
    """Bali/Canggu should search surf/beach/nightlife, not generic landmarks."""
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(
        destination="巴厘岛",
        region_split_confirmed=True,
        region_preferences=["Canggu"],
        region_candidates=[
            {"name": "Canggu", "highlights": ["冲浪"], "typical_experience_types": ["surf", "beach", "nightlife"]},
        ],
    )
    plan = agent._build_search_plan(req, region="Canggu")
    tags = {tag for tag, _q, _pt in plan}
    assert tags == {"surf", "beach", "nightlife", "food"}


def test_search_plan_uses_compact_region_hint_for_amap(no_llm):
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(
        destination="北京",
        region_candidates=[
            {"name": "东城·故宫/天安门/王府井", "typical_experience_types": ["culture"]},
        ],
    )
    plan = agent._build_search_plan(req, region="东城·故宫/天安门/王府井")
    assert all("北京 东城" in query for _tag, query, _place_type in plan)
    assert all("故宫/天安门/王府井" not in query for _tag, query, _place_type in plan)


def test_auto_select_prefers_user_types_covers_regions_and_avoids_cafes(no_llm):
    agent = ResearchOrchestratorAgent()
    candidates = {"experiences": {
        "culture": [
            {"name": "故宫博物院", "region": "东城", "popularity": 0, "rating": 4.9},
            {"name": "国家博物馆", "region": "东城", "popularity": 0, "rating": 4.8},
        ],
        "landmark": [
            {"name": "慕田峪长城", "region": "怀柔", "popularity": 0, "rating": 4.8},
            {"name": "天安门", "region": "东城", "popularity": 0, "rating": 4.7},
        ],
        "architecture": [
            {"name": "明城墙遗址公园", "region": "东城", "popularity": 0, "rating": 4.6},
        ],
        "shopping": [
            {"name": "星海钢琴商城", "region": "东城", "popularity": 100, "rating": 5.0},
        ],
        "food": [
            {"name": "出走咖啡", "region": "东城", "popularity": 100, "rating": 5.0},
            {"name": "老北京涮肉", "region": "东城", "popularity": 0, "rating": 4.5},
        ],
    }}

    selected = agent.auto_select(candidates, daily_count=2, days=2, preferred_types=["culture", "food"])["experiences"]
    names = [item["name"] for item in selected]
    assert "故宫博物院" in names
    assert "慕田峪长城" in names
    assert "星海钢琴商城" not in names
    assert names.index("老北京涮肉") < names.index("出走咖啡")


def test_auto_select_keeps_every_explicit_requested_place(no_llm):
    agent = ResearchOrchestratorAgent()
    candidates = {"experiences": {
        "landmark": [
            {"name": "成都大熊猫繁育研究基地", "popularity": 1, "rating": 4.1},
            {"name": "春熙路", "popularity": 1, "rating": 4.0},
            {"name": "成都远望塔", "popularity": 99, "rating": 5.0},
        ],
        "local_life": [{"name": "成都太古里", "popularity": 1, "rating": 4.0}],
        "food": [{"name": "成都小吃", "popularity": 1, "rating": 4.0}],
    }}
    selected = agent.auto_select(
        candidates, daily_count=2, days=2,
        required_names=["大熊猫", "春熙路", "太古里"],
    )["experiences"]
    names = [item["name"] for item in selected]
    assert "成都大熊猫繁育研究基地" in names
    assert "春熙路" in names
    assert "成都太古里" in names


def test_auto_select_prioritizes_relevance_and_honors_explicit_exclusions(no_llm):
    agent = ResearchOrchestratorAgent()
    candidates = {"experiences": {
        "culture": [
            {"name": "地方历史博物馆", "popularity": 60, "rating": 4.6, "confidence": .95},
            {"name": "非遗展示馆", "popularity": 55, "rating": 4.5, "confidence": .93},
            {"name": "古城考古遗址", "popularity": 50, "rating": 4.5, "confidence": .92},
        ],
        "nature": [
            {"name": "明确不想去公园", "popularity": 100, "rating": 5.0, "confidence": .99},
            {"name": "普通城市公园", "popularity": 98, "rating": 4.9, "confidence": .99},
        ],
        "architecture": [{"name": "历史建筑群", "popularity": 70, "rating": 4.7, "confidence": .94}],
        "food": [{"name": "本地菜馆", "popularity": 70, "rating": 4.5, "confidence": .9}],
    }}
    selected = agent.auto_select(
        candidates, daily_count=2, days=2, preferred_types=["culture"],
        required_names=["历史建筑群"], excluded_names=["不想去公园"],
    )["experiences"]
    names = [item["name"] for item in selected]
    non_food = [item for item in selected if item.get("type") != "food"]
    assert "明确不想去公园" not in names
    assert "历史建筑群" in names
    assert sum(item.get("name") in {"地方历史博物馆", "非遗展示馆", "古城考古遗址"} for item in non_food) >= 3


def test_requested_place_family_keeps_one_real_panda_destination(no_llm):
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="成都", requested_places=["大熊猫"])
    source = Source(title="amap", url="https://www.amap.com", source_type="amap")
    rows = [
        TravelExperience(name="成都大熊猫繁育研究基地", type="landmark", location="成都", source=source),
        TravelExperience(name="熊猫基地旅游服务中心", type="local_life", location="成都", source=source),
        TravelExperience(name="大熊猫4号别墅", type="landmark", location="成都", source=source),
    ]
    deduped = agent._dedupe_candidate_pool(rows, req)
    assert [item.name for item in deduped] == ["成都大熊猫繁育研究基地"]


def test_parse_feedback_intent_niche_architecture(no_llm):
    """Test3: "这些太游客了，多找一些小众建筑" -> architecture + niche."""
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")
    intent = agent.parse_feedback_intent("这些地方太游客了，多找一些小众建筑", req)
    assert intent["category"] == "architecture"
    assert intent["popularity"] == "niche"


def test_parse_feedback_intent_defaults_to_mainstream(no_llm):
    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")
    intent = agent.parse_feedback_intent("挺好的，没什么意见", req)
    assert intent["popularity"] == "mainstream"


def test_run_feedback_does_not_touch_visa_weather_flight(no_llm, stub_external_calls):
    """The feedback loop must be scoped/incremental -- never a blind full
    re-run of visa/weather/flight workers."""
    from travel_agent.schemas.research_result import ResearchResult

    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="东京")
    existing = ResearchResult(visa_info=None, weather=None, flights=[])

    updated = agent.run_feedback(req, existing, "这些太游客了，多找一些小众建筑")

    assert updated.visa_info is None
    assert updated.weather is None
    assert updated.flights == []
    assert len(updated.experiences) >= len(existing.experiences)
    assert all(e.type == "architecture" for e in updated.experiences[len(existing.experiences):])


# -- Round-5: dynamic query generation (Phase 5) regression test for the
# diagnosed bug -- an unrecognized activity request ("浮潜"/"滑翔伞") used to
# silently canonicalize down to a generic "local_life" search
# ("{dest} 市集 社区活动"), finding nothing related to what the user asked
# for. Exercises the REAL skills/ directory (snorkeling_activities/
# paragliding_activities, added in Phase 2) rather than an isolated one, so
# this proves the actual shipped configuration, not just the mechanism. -----


def test_run_expansion_region_profile_finds_snorkeling_and_paragliding_not_local_life(no_llm, stub_external_calls):
    from travel_agent.schemas.research_result import ResearchResult

    agent = ResearchOrchestratorAgent()
    req = TravelRequirement(destination="巴厘岛")
    existing = ResearchResult()
    region_candidate = RegionCandidate(
        name="Nusa Penida",
        identity=["island", "marine", "adventure"],
        signature_experiences=["浮潜", "滑翔伞"],
    )

    updated = agent.run_expansion(req, existing, missing_categories=[], region="Nusa Penida", region_candidate=region_candidate)

    new_types = {e.type for e in updated.experiences}
    assert "local_life" not in new_types
    assert new_types == {"snorkeling", "paragliding"}
