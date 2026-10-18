"""`IntentContextBuilder` (design doc section 4): turns the raw LangGraph
`AgentState` into the compact `IntentContext` every downstream intent stage
reads. Deliberately NOT a full transcript dump -- keeps the last few turns
plus a one-line anchor of the original request when history runs long, and
carries stable identifiers (day count, activity ids) instead of re-deriving
them from prose each time.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from travel_agent.intent.schemas import ContextMessage, IntentContext

_RECENT_MESSAGE_LIMIT = 8
_LAST_OUTPUT_PREVIEW_CHARS = 200


def _recent_relevant_messages(history: List[Dict[str, str]]) -> List[ContextMessage]:
    """Last N turns, plus a one-line anchor back to the very first user
    message when the conversation has grown past that window -- avoids both
    "concat everything" and "always exactly the last 3" per the design doc."""
    if not history:
        return []
    tail = history[-_RECENT_MESSAGE_LIMIT:]
    messages = [ContextMessage(role=m.get("role", "user"), content=m.get("content", "")) for m in tail]
    if len(history) > _RECENT_MESSAGE_LIMIT:
        first = history[0]
        anchor_text = (first.get("content", "") or "")[:80]
        messages.insert(0, ContextMessage(role="system", content=f"[更早对话摘要] 最初请求: {anchor_text}"))
    return messages


def _activity_id(experience: Dict[str, Any]) -> str:
    return experience.get("id") or experience.get("name") or ""


class IntentContextBuilder:
    def build(self, state: Dict[str, Any], message: Optional[str] = None) -> IntentContext:
        requirement = state.get("travel_requirement") or {}
        itinerary = state.get("itinerary") or {}
        days = itinerary.get("days") or []
        selected = state.get("selected_places") or {}
        candidates = state.get("candidates") or {}

        selected_ids = [_activity_id(e) for e in selected.get("experiences", []) if _activity_id(e)]
        visible_ids = [
            _activity_id(e)
            for items in candidates.get("experiences", {}).values()
            for e in items
            if _activity_id(e)
        ]

        immutable_constraints: Dict[str, Any] = {}
        if requirement.get("confirmed"):
            for key in ("destination", "budget", "start_date", "end_date"):
                if requirement.get(key) is not None:
                    immutable_constraints[key] = requirement[key]

        pending_confirmation = None
        if state.get("need_user_input") and state.get("stage") in (
            "confirmation",
            "region_confirmation",
            "selection",
        ):
            pending_confirmation = {"phase": state.get("stage"), "question": state.get("pending_response")}

        regions = list(requirement.get("region_preferences") or [])
        if not regions:
            regions = [r.get("name") for r in requirement.get("region_candidates") or [] if r.get("name")]

        return IntentContext(
            current_message=message if message is not None else state.get("user_message", ""),
            recent_relevant_messages=_recent_relevant_messages(state.get("conversation_history") or []),
            current_phase=state.get("stage", ""),
            pending_confirmation=pending_confirmation,
            travel_requirement_summary={
                k: requirement.get(k)
                for k in (
                    "destination", "duration_days", "num_travelers", "budget", "pace",
                    "interests", "experience_preferences", "region_preferences", "confirmed",
                )
                if requirement.get(k) not in (None, [], "")
            },
            current_plan_summary={"day_count": len(days)} if days else {},
            current_day_index=None,
            selected_activity_ids=selected_ids,
            visible_candidate_ids=visible_ids,
            last_agent_output_summary=(state.get("pending_response") or "")[:_LAST_OUTPUT_PREVIEW_CHARS] or None,
            current_destination=requirement.get("destination"),
            current_regions=regions,
            immutable_constraints=immutable_constraints,
            session_id=state.get("session_id", ""),
            trace_id=uuid.uuid4().hex[:12],
        )
