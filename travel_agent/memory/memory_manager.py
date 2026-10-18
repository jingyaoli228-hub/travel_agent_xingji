"""Memory Manager: the single façade over the 3 persistent memory layers.

Deliberately not a 5th Agent -- it's called *by* the Requirement Agent and
Planner Agent (per spec), exposing exactly the three operations asked for:
`retrieve_memory`, `update_memory`, `extract_user_preference`. L0 Working
Memory is intentionally excluded (it lives in `AgentState`, see
`working_memory.py`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from travel_agent.memory.conversation_memory import ConversationMemory
from travel_agent.memory.episodic_memory import EpisodicMemory
from travel_agent.memory.profile_memory import ProfileMemory
from travel_agent.memory.schemas import MemoryContext
from travel_agent.schemas.memory import MemoryBundle, TripEpisode

_PACE_TRAVEL_STYLE = {
    "特种兵": "快节奏打卡型，偏好尽量多的体验密度",
    "平衡": "均衡型，体验数量与休息时间兼顾",
    "松弛": "慢节奏休闲型，偏好较少安排、充分休息",
}
_PACE_TRANSPORT_PREFERENCE = {
    "特种兵": "高效优先（驾车/直达交通），减少等待",
    "平衡": "公共交通为主",
    "松弛": "步行/公共交通为主，减少换乘次数",
}
_FOOD_CONSTRAINT_KEYWORDS = ["素食", "清真", "过敏", "忌", "无麸质", "不吃"]


class MemoryManager:
    def __init__(self) -> None:
        self.conversation = ConversationMemory()
        self.episodic = EpisodicMemory()
        self.profile = ProfileMemory()

    def retrieve_memory(self, session_id: str, user_id: str, tags: Optional[List[str]] = None) -> MemoryBundle:
        profile = self.profile.get(user_id)
        query_tags = tags or (profile.interest_preference if profile else [])
        similar_trips = self.episodic.retrieve_similar_trips(user_id, query_tags, top_k=3)
        conversation = self.conversation.get(session_id)
        return MemoryBundle(profile=profile, similar_trips=similar_trips, conversation=conversation)

    def build_context(
        self,
        session_id: str,
        user_id: str,
        intent_key: Optional[str] = None,
        query_text: str = "",
        tags: Optional[List[str]] = None,
    ) -> MemoryContext:
        """Round-6: the unified read path Phase 5 wires the four agents up
        to (see `memory/context_builder.py`). Not yet called from
        `graph/nodes.py` -- `retrieve_memory()` above remains the live
        read path until that wiring lands."""
        from travel_agent.memory.context_builder import build_context

        return build_context(session_id, user_id, intent_key=intent_key, query_text=query_text, tags=tags)

    def update_memory(
        self,
        session_id: str,
        user_id: str,
        *,
        original_request: Optional[str] = None,
        confirmed_requirement: Optional[Dict[str, Any]] = None,
        user_choice: Optional[str] = None,
        rejected_option: Optional[str] = None,
        episode: Optional[Union[TripEpisode, Dict[str, Any]]] = None,
        profile_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        if any([original_request, confirmed_requirement, user_choice, rejected_option]):
            self.conversation.update(
                session_id,
                original_request=original_request,
                confirmed_requirement=confirmed_requirement,
                user_choice=user_choice,
                rejected_option=rejected_option,
            )
        if episode is not None:
            self.episodic.add_episode(episode if isinstance(episode, TripEpisode) else TripEpisode(**episode))
        if profile_fields:
            self.profile.upsert(user_id, session_id=session_id, **profile_fields)

    def extract_user_preference(
        self,
        requirement: Any,
        selected_experiences: Optional[List[Dict[str, Any]]] = None,
        hotel: Optional[Dict[str, Any]] = None,
        review_feedback: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Derive L3 profile fields from a completed trip. Never overwrites with
        empty values -- `ProfileMemory.upsert` already skips falsy values."""
        pace = getattr(requirement, "pace", None) or ""
        interests = list(getattr(requirement, "interests", None) or [])
        experience_preferences = list(getattr(requirement, "experience_preferences", None) or [])
        constraints = list(getattr(requirement, "constraints", None) or [])
        special_needs = getattr(requirement, "special_needs", None) or ""

        food_constraints = [c for c in constraints if any(k in c for k in _FOOD_CONSTRAINT_KEYWORDS)]
        if any(k in special_needs for k in _FOOD_CONSTRAINT_KEYWORDS):
            food_constraints.append(special_needs.strip())

        hotel_preference = None
        if hotel:
            area = hotel.get("area")
            star = hotel.get("star_rating")
            hotel_preference = f"{star}星附近 {area}".strip() if star else area

        return {
            "travel_style": _PACE_TRAVEL_STYLE.get(pace),
            "hotel_preference": hotel_preference,
            "interest_preference": list(dict.fromkeys(interests + experience_preferences)),
            "food_constraints": food_constraints,
            "transport_preference": _PACE_TRANSPORT_PREFERENCE.get(pace),
        }
