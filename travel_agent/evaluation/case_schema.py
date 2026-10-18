"""Schema for a hand-authored evaluation case
(`evaluation_cases/{feedback,destination,modification}_cases.json`)."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel


class EvalCase(BaseModel):
    case_id: str
    # Round-6 Phase 6 (requirement doc section 29) adds rag/memory/
    # personalization/richness alongside the original three categories.
    category: Literal[
        "feedback", "destination", "modification", "rag", "memory", "personalization", "richness"
    ]
    user_request: str
    prior_state: Optional[Dict[str, Any]] = None
    expected_goal: str
    notes: Optional[str] = None
