"""Tests for `travel_agent/agents/query_generation.py::QueryGenerator` --
the four-tier dynamic query precedence (skill-declared / static map /
region-profile signature experiences / generic fallback), fully offline
(no LLM, no tool calls -- pure function over fixture inputs).
"""

from __future__ import annotations

from travel_agent.agents.query_generation import QueryGenerator
from travel_agent.schemas.destination import RegionCandidate
from travel_agent.skills.registry import SkillRegistry, get_skill_registry


def _write_skill(root, name, activity_type, synonyms, query_templates, place_type="tourist_attraction", display_label_cn=None):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    synonyms_yaml = "\n".join(f"  - {s}" for s in synonyms)
    if query_templates:
        templates_block = "query_templates:\n" + "\n".join(f'  - "{t}"' for t in query_templates)
    else:
        templates_block = "query_templates: []"
    label_line = f"display_label_cn: {display_label_cn}\n" if display_label_cn else ""
    content = f"""---
name: {name}
activity_type: {activity_type}
synonyms:
{synonyms_yaml}
{templates_block}
tool: google_places.search_places
place_type: {place_type}
{label_line}enabled: true
---
body
"""
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _use_isolated_registry(tmp_path, monkeypatch):
    from travel_agent.skills import registry as registry_module

    registry = SkillRegistry(skills_dir_getter=lambda: str(tmp_path))
    monkeypatch.setattr(registry_module, "_registry", registry)
    return registry


_STATIC_MAP = {
    "landmark": [("{dest} 地标景点", "tourist_attraction")],
    "food": [("{dest} 餐厅美食", "restaurant"), ("{dest} 特色咖啡馆", "cafe")],
}


# -- Tier 1: skill-declared -----------------------------------------------


def test_tier1_skill_declared_query_wins_over_static_map(tmp_path, monkeypatch):
    _write_skill(tmp_path, "snorkeling_activities", "snorkeling", ["浮潜"], ["{dest} snorkeling spot 浮潜"])
    _use_isolated_registry(tmp_path, monkeypatch)

    plan = QueryGenerator().generate(focus=["snorkeling"], dest_label="Nusa Penida", tag_query_map=_STATIC_MAP)
    assert plan == [("Nusa Penida snorkeling spot 浮潜", "tourist_attraction", "snorkeling")]


# -- Tier 2: static _TAG_QUERY_MAP ------------------------------------------


def test_tier2_static_map_used_when_no_skill_declares_the_tag(tmp_path, monkeypatch):
    _use_isolated_registry(tmp_path, monkeypatch)  # empty registry
    plan = QueryGenerator().generate(focus=["food"], dest_label="东京", tag_query_map=_STATIC_MAP)
    assert plan == [
        ("东京 餐厅美食", "restaurant", "food"),
        ("东京 特色咖啡馆", "cafe", "food"),
    ]


# -- Tier 3: region-profile signature experiences ---------------------------


def test_tier3_signature_experiences_generate_queries_independent_of_focus(tmp_path, monkeypatch):
    _use_isolated_registry(tmp_path, monkeypatch)
    region_candidate = RegionCandidate(name="Nusa Penida", signature_experiences=["浮潜", "滑翔伞"])
    plan = QueryGenerator().generate(focus=[], dest_label="巴厘岛 Nusa Penida", region_candidate=region_candidate)
    queries = [(q, tag) for q, _pt, tag in plan]
    assert ("巴厘岛 Nusa Penida 浮潜", "浮潜") in queries
    assert ("巴厘岛 Nusa Penida 滑翔伞", "滑翔伞") in queries


def test_tier3_uses_skill_synonym_to_canonicalize_signature_experience_tag(tmp_path, monkeypatch):
    """A signature experience string ("浮潜") that happens to match a
    skill's synonym should get the skill's canonical activity_type as its
    tag, not the raw Chinese text -- keeps tags consistent with Tier 1."""
    _write_skill(tmp_path, "snorkeling_activities", "snorkeling", ["浮潜"], ["{dest} 浮潜"])
    _use_isolated_registry(tmp_path, monkeypatch)
    region_candidate = RegionCandidate(name="Nusa Penida", signature_experiences=["浮潜"])
    plan = QueryGenerator().generate(focus=[], dest_label="Nusa Penida", region_candidate=region_candidate)
    assert plan[0][2] == "snorkeling"


def test_tier3_and_focus_combine_without_duplicate_tags(tmp_path, monkeypatch):
    _use_isolated_registry(tmp_path, monkeypatch)
    region_candidate = RegionCandidate(name="Nusa Penida", signature_experiences=["浮潜", "悬崖景观"])
    plan = QueryGenerator().generate(
        focus=["浮潜"], dest_label="Nusa Penida", region_candidate=region_candidate, tag_query_map=_STATIC_MAP,
    )
    tags = [tag for _q, _pt, tag in plan]
    assert tags.count("浮潜") == 1  # focus tier claimed it first; tier 3 doesn't duplicate


# -- Tier 4: generic fallback (replaces the old silent "local_life" drop) ----


def test_tier4_generic_fallback_for_completely_unknown_tag(tmp_path, monkeypatch):
    _use_isolated_registry(tmp_path, monkeypatch)  # empty registry, empty static map
    plan = QueryGenerator().generate(focus=["paragliding"], dest_label="Nusa Penida", tag_query_map=_STATIC_MAP)
    assert plan == [("Nusa Penida paragliding 体验", None, "paragliding")]


def test_tier4_uses_skill_display_label_even_without_query_templates(tmp_path, monkeypatch):
    # No query_templates -> falls through to tier 4, but a skill entry still
    # exists for this activity_type, so its Chinese display label is used
    # instead of the raw tag string (see skills/travel_weather/SKILL.md for
    # the real-world analog: a skill that maps onto an existing tool without
    # participating in query generation).
    _write_skill(tmp_path, "weather_ref", "weather_advisory", ["天气"], [], display_label_cn="天气")
    _use_isolated_registry(tmp_path, monkeypatch)
    plan = QueryGenerator().generate(focus=["weather_advisory"], dest_label="东京", tag_query_map=_STATIC_MAP)
    assert plan == [("东京 天气 体验", None, "weather_advisory")]
