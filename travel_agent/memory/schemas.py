"""Round-6 layered-memory schemas -- distinct from (and a superset built on
top of) `travel_agent/schemas/memory.py`'s existing `ConversationMemoryRecord`
/`TripEpisode`/`UserProfile` (kept for backward compatibility, see
`memory/episodic_memory.py`/`memory/profile_memory.py` module docstrings for
how the two coexist). Names deliberately don't collide with the existing
`schemas/memory.py` classes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from travel_agent.schemas.memory import TripEpisode

ProfileStatus = Literal["SESSION_PREFERENCE", "TENTATIVE_PROFILE", "STABLE_PROFILE"]


class WorkingMemory(BaseModel):
    """L0, now actually persisted (Redis, 24h TTL) -- requirement doc section
    16. Key: `travel:session:{session_id}:working_memory`."""

    session_id: str
    user_id: str = ""

    recent_messages: List[Dict[str, Any]] = Field(default_factory=list)

    current_intent: Optional[Dict[str, Any]] = None
    travel_requirement: Optional[Dict[str, Any]] = None
    planning_state: Optional[Dict[str, Any]] = None

    visible_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    pending_confirmation: Optional[Dict[str, Any]] = None

    last_retrieval_summary: Optional[Dict[str, Any]] = None
    last_execution_trace: Optional[Dict[str, Any]] = None

    updated_at: str = ""


class EpisodicMemoryRecord(BaseModel):
    """L2 upgrade target -- requirement doc section 17. Built from an
    existing `schemas.memory.TripEpisode` by `episodic_memory.py`, not a
    replacement for it (the JSONL store keeps writing `TripEpisode`s
    unchanged; this is the additional shape written to the
    `episodic_memory` Chroma collection)."""

    memory_id: str
    user_id: str
    session_id: str

    event_type: str
    event_summary: str

    destinations: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)

    user_feedback: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    rejected_options: List[str] = Field(default_factory=list)

    importance_score: float = 0.0
    created_at: str = ""
    last_accessed_at: Optional[str] = None


class UserProfileStatement(BaseModel):
    """L3 upgrade target -- requirement doc section 18. One record per
    preference statement (not one record per user) -- `profile_memory.py`
    writes one of these per non-empty field passed to `upsert()`, alongside
    (not instead of) the existing flat JSON `UserProfile` merge."""

    profile_id: str
    user_id: str

    profile_type: str = "preference"
    statement: str

    preference_dimension: Optional[str] = None
    value: Any = None

    confidence: float = 0.5
    scope: Literal["long_term", "trip_specific"] = "long_term"
    explicitness: Literal["explicit", "strong_inference", "weak_inference"] = "weak_inference"
    evidence: List[str] = Field(default_factory=list)
    source_turn_ids: List[str] = Field(default_factory=list)
    evidence_count: int = 1

    source_session_ids: List[str] = Field(default_factory=list)

    first_observed_at: str = ""
    last_updated_at: str = ""

    status: ProfileStatus = "TENTATIVE_PROFILE"


class MemoryContext(BaseModel):
    """Output of `memory/context_builder.py::build_context()` -- what a
    given turn actually needs to read, per requirement doc section 20 (not
    every turn loads every layer). `episodic` uses the existing `TripEpisode`
    shape (not `EpisodicMemoryRecord`, which is `episodic_memory.py`'s
    internal Chroma-write-side representation) since that's what
    `EpisodicMemory.retrieve_similar_trips()` already returns and what
    Requirement/Research/Planner agents already know how to read."""

    working: Optional[WorkingMemory] = None
    episodic: List[TripEpisode] = Field(default_factory=list)
    profile_statements: List[UserProfileStatement] = Field(default_factory=list)
    plan_used: Dict[str, bool] = Field(default_factory=dict)
