"""Dynamic Skill Runtime: declarative `SKILL.md` capability files under
`skills/<name>/SKILL.md`, loaded (and hot-reloaded, no restart needed) by
`SkillRegistry`. A Skill teaches the system a new activity-type tag +
keyword synonyms + query templates + which registered tool
(`travel_agent/tool_runtime/registry.py`) handles it -- this is how new
activity vocabulary (e.g. snorkeling, paragliding) gets added without
touching `pattern_parser.py`'s `CATEGORY_KEYWORDS` or `research_agent.py`'s
`_TAG_QUERY_MAP` again for every new activity type.
"""

from __future__ import annotations

from travel_agent.skills.registry import SkillRegistry, get_skill_registry

__all__ = ["SkillRegistry", "get_skill_registry"]
