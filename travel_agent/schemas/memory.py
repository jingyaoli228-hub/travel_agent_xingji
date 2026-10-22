"""Schemas for the 4-layer Memory system.

L0 Working Memory has no schema here -- it's a typed view over LangGraph's own
`AgentState` (see `travel_agent/memory/working_memory.py`). L1-L3 are the
persistent layers, all keyed by `session_id` (L1) or `user_id` (L2/L3).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConversationMemoryRecord(BaseModel):
    """L1: lifecycle = current trip. Backed by Redis (falls back to in-memory)."""

    session_id: str
    original_request: str = ""
    confirmed_requirement: Dict[str, Any] = Field(default_factory=dict)
    user_choices: List[str] = Field(default_factory=list)
    rejected_options: List[str] = Field(default_factory=list)
    last_user_edits: List[Dict[str, Any]] = Field(default_factory=list)
    current_version: int = 0


class TripEpisode(BaseModel):
    """L2: lifecycle = cross-trip. One record per completed trip."""

    user_id: str
    session_id: str
    destination: str = ""
    selected_experiences: List[Dict[str, Any]] = Field(default_factory=list)
    rejected_experiences: List[str] = Field(default_factory=list)
    final_plan_summary: Dict[str, Any] = Field(default_factory=dict)
    feedback: List[str] = Field(default_factory=list)
    budget_difference: float = 0.0
    tags: List[str] = Field(default_factory=list, description="用于相似度检索的标签，例如兴趣/体验类型")
    created_at: str = ""


class UserProfile(BaseModel):
    """L3: long-term. One record per user."""

    user_id: str
    travel_style: Optional[str] = None
    hotel_preference: Optional[str] = None
    interest_preference: List[str] = Field(default_factory=list)
    food_constraints: List[str] = Field(default_factory=list)
    transport_preference: Optional[str] = None
    updated_at: str = ""


class MemoryBundle(BaseModel):
    """Aggregate result of `MemoryManager.retrieve_memory()`."""

    profile: Optional[UserProfile] = None
    similar_trips: List[TripEpisode] = Field(default_factory=list)
    conversation: Optional[ConversationMemoryRecord] = None
