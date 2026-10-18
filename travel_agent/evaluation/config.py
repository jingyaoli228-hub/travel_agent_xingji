"""Loads `config/evaluation_criteria.yaml` -- the 6-dimension weight set.
Mirrors `travel_agent/intent/config.py::load_fusion_config` and
`travel_agent/tool_runtime/config.py::load_tool_runtime_config` exactly:
pydantic model tree, `@lru_cache` keyed on `(path, mtime)`, all-defaults if
the file is missing.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field

from travel_agent.config.settings import get_settings


class EvaluationWeights(BaseModel):
    intent_understanding: float = 0.25
    destination_relevance: float = 0.20
    activity_matching: float = 0.20
    personalization: float = 0.15
    planning_feasibility: float = 0.10
    response_quality: float = 0.10


class StrictWeights(BaseModel):
    """Point budget for `StrictDimensionScores` (requirement doc section
    24) -- these are absolute point maxima per dimension, not fractional
    weights that need to sum to 1.0 like `EvaluationWeights` above."""

    requirement_adherence: float = 20
    user_profile_alignment: float = 15
    destination_specificity: float = 15
    activity_richness: float = 15
    activity_diversity: float = 10
    itinerary_feasibility: float = 15
    evidence_and_accuracy: float = 5
    presentation_quality: float = 5


class HardPenalties(BaseModel):
    """Requirement doc section 26. All values are negative points."""

    wrong_destination: float = -30
    missed_explicit_activity: float = -20
    violated_preserve_scope: float = -20
    unsupported_claim: float = -10
    empty_day: float = -10
    geographically_impossible: float = -15
    repeated_rejected_activity: float = -12
    missing_activity_description: float = -8
    generic_destination_plan: float = -10


class EvaluationConfig(BaseModel):
    weights: EvaluationWeights = Field(default_factory=EvaluationWeights)
    strict_weights: StrictWeights = Field(default_factory=StrictWeights)
    hard_penalties: HardPenalties = Field(default_factory=HardPenalties)
    max_revision_rounds: int = 2
    pass_threshold: float = 80
    notes_threshold: float = 65


def _default_config_path() -> str:
    return get_settings().evaluation_criteria_path


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime: float) -> EvaluationConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}
    return EvaluationConfig(**raw)


def load_evaluation_config(path: str | None = None) -> EvaluationConfig:
    resolved_path = path or _default_config_path()
    try:
        mtime = os.path.getmtime(resolved_path)
    except OSError:
        return EvaluationConfig()
    return _load_cached(resolved_path, mtime)
