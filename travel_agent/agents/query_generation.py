"""Dynamic activity-query generation (Round-5 Phase 5).

Lives alongside `research_agent.py` since it's Research-internal (a
strategy helper `ResearchOrchestratorAgent` composes), not a new agent.
Replaces `run_expansion()`'s old behavior of canonicalizing any
unrecognized category down to a generic `"local_life"` search -- which
actively mis-searched (a "浮潜"/snorkeling request silently became a
"市集/社区活动" query, the exact bug this phase fixes).

Four-tier precedence, in order, per requested `focus` tag:
    1. Skill-declared query templates (`travel_agent/skills/*/SKILL.md`,
       Phase 2) -- exact `activity_type` match, e.g. "snorkeling"/"paragliding".
    2. The static `_TAG_QUERY_MAP` (`research_agent.py`) -- the well-known,
       curated 14-type vocabulary. Kept as-is; this phase doesn't remove it,
       it becomes the "well-known" tier beneath the dynamic ones.
    3. Generic fallback -- `"{dest} {label} 体验"`. Replaces the old silent
       `local_life` degradation: at least searches for what the user
       actually asked for, even with no template/skill for it.

A destination profile's own `signature_experiences` (Destination
Intelligence, Phase 4) are synthesized into ADDITIONAL queries independent
of `focus` -- this is the actual "dynamically discovers the activity space"
behavior: no template lookup at all, just the region's own researched
specialty experiences turned directly into search queries.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from travel_agent.schemas.destination import RegionCandidate
from travel_agent.skills.registry import get_skill_registry

QueryPlanEntry = Tuple[str, Optional[str], str]  # (query_text, google_place_type, activity_type_tag)


class QueryGenerator:
    def generate(
        self,
        focus: List[str],
        dest_label: str,
        region_candidate: Optional[RegionCandidate] = None,
        tag_query_map: Optional[Dict[str, List[Tuple[str, Optional[str]]]]] = None,
    ) -> List[QueryPlanEntry]:
        tag_query_map = tag_query_map or {}
        vocabulary = get_skill_registry().get_activity_vocabulary()
        synonym_map = get_skill_registry().get_synonym_map()

        plan: List[QueryPlanEntry] = []
        seen_tags: set = set()

        for tag in focus or []:
            if tag in seen_tags:
                continue
            for entry in self._for_tag(tag, dest_label, tag_query_map, vocabulary):
                plan.append(entry)
            seen_tags.add(tag)

        if region_candidate and region_candidate.signature_experiences:
            for experience in region_candidate.signature_experiences:
                tag = self._canonicalize_signature_experience(experience, synonym_map)
                if tag in seen_tags:
                    continue
                plan.append((f"{dest_label} {experience}".strip(), None, tag))
                seen_tags.add(tag)

        return plan

    def _for_tag(
        self,
        tag: str,
        dest_label: str,
        tag_query_map: Dict[str, List[Tuple[str, Optional[str]]]],
        vocabulary: Dict[str, object],
    ) -> List[QueryPlanEntry]:
        skill = vocabulary.get(tag)
        if skill is not None and getattr(skill, "query_templates", None):
            return [
                (template.format(dest=dest_label), getattr(skill, "place_type", None), tag)
                for template in skill.query_templates
            ]
        if tag in tag_query_map:
            return [(template.format(dest=dest_label), place_type, tag) for template, place_type in tag_query_map[tag]]
        label = getattr(skill, "display_label_cn", None) or tag
        return [(f"{dest_label} {label} 体验".strip(), None, tag)]

    @staticmethod
    def _canonicalize_signature_experience(experience: str, synonym_map: Dict[str, str]) -> str:
        for keyword, activity_type in synonym_map.items():
            if keyword in experience:
                return activity_type
        return experience.strip()
