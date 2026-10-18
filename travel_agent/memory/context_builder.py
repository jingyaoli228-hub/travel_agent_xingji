"""Memory Context Builder (requirement doc section 20): decides which of
the 3 persisted memory layers a given turn actually needs, rather than
always loading everything -- a weather lookup doesn't need episodic/profile
retrieval; a full replan needs all three.

Not wired into `graph/nodes.py` yet -- Phase 5 ("Agent 接入") is where the
four agents switch to reading one shared `MemoryContext` from here instead
of each querying memory ad hoc. This module is the piece Phase 5 calls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from travel_agent.memory import working_memory
from travel_agent.memory.config import load_memory_config
from travel_agent.memory.episodic_memory import EpisodicMemory
from travel_agent.memory.profile_memory import ProfileMemory
from travel_agent.memory.schemas import MemoryContext, UserProfileStatement

_DEFAULT_PLAN: Dict[str, bool] = {"working": True, "episodic": False, "profile": True}

# Keyed by `IntentResult.primary_intent`/`task_type` (see
# `travel_agent/intent/schemas.py`) -- both vocabularies are checked since
# either one might carry the signal depending on which pipeline stage built
# it. Unlisted intents fall back to `_DEFAULT_PLAN` (requirement doc
# section 20's own "default" example: working + profile, no episodic).
_INTENT_PLANS: Dict[str, Dict[str, bool]] = {
    "WEATHER_QUERY": {"working": True, "episodic": False, "profile": False},
    "SIDE_QUERY": {"working": True, "episodic": False, "profile": False},
    "REPLAN": {"working": True, "episodic": True, "profile": True},
    "MODIFY_ITINERARY": {"working": True, "episodic": True, "profile": True},
    "FEEDBACK": {"working": True, "episodic": True, "profile": True},
    "NEW_TRIP": {"working": False, "episodic": True, "profile": True},
    "REQUIREMENT_GATHERING": {"working": False, "episodic": True, "profile": True},
}


def _resolve_plan(intent_key: Optional[str]) -> Dict[str, bool]:
    if intent_key and intent_key in _INTENT_PLANS:
        return _INTENT_PLANS[intent_key]
    return dict(_DEFAULT_PLAN)


def build_context(
    session_id: str,
    user_id: str,
    intent_key: Optional[str] = None,
    query_text: str = "",
    tags: Optional[List[str]] = None,
) -> MemoryContext:
    plan = _resolve_plan(intent_key)
    config = load_memory_config()
    context = MemoryContext(plan_used=plan)

    if plan.get("working") and session_id:
        context.working = working_memory.load(session_id)

    if plan.get("episodic") and user_id:
        context.episodic = EpisodicMemory().retrieve_similar_trips(
            user_id, tags or [], top_k=config.episodic_top_k, query_text=query_text
        )

    if plan.get("profile") and user_id:
        context.profile_statements = ProfileMemory().get_statements(user_id)[: config.profile_top_k]

    return context


def flatten_profile_statements(statements: List[UserProfileStatement]) -> Dict[str, Any]:
    """Reshape per-dimension `UserProfileStatement`s back into the flat
    `{dimension: value}` dict the existing agents already know how to read
    (`RequirementAgent._apply_profile_hint`, `PlannerAgent._preferred_mode`
    both just do `profile_hint.get("some_dimension")`) -- so those agents
    need zero code changes to start reading from the unified `MemoryContext`
    instead of the old ad hoc `ProfileMemory.get()` lookup. `STABLE_PROFILE`
    statements win over `TENTATIVE_PROFILE` ones for the same dimension."""
    by_dimension: Dict[str, UserProfileStatement] = {}
    for statement in statements:
        if not statement.preference_dimension:
            continue
        existing = by_dimension.get(statement.preference_dimension)
        if existing is None or (statement.status == "STABLE_PROFILE" and existing.status != "STABLE_PROFILE"):
            by_dimension[statement.preference_dimension] = statement
    return {dimension: statement.value for dimension, statement in by_dimension.items()}


def rejected_experience_names(episodes: List[Any]) -> List[str]:
    """Flatten `TripEpisode.rejected_experiences` across a `MemoryContext`'s
    episodic entries -- used by `ResearchOrchestratorAgent` so a re-planned
    or brand-new trip doesn't re-suggest something the user already turned
    down (requirement doc section 21 / validation scenario 3)."""
    names: List[str] = []
    for episode in episodes:
        for name in getattr(episode, "rejected_experiences", None) or []:
            if name not in names:
                names.append(name)
    return names
