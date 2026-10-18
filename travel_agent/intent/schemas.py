"""Stage-3 intent pipeline schemas.

Every stage of `MultiSignalIntentInterpreter` (see `interpreter.py`) speaks
Pydantic in, Pydantic out -- no free-format string parsing between stages.
This module intentionally has zero business logic; it only defines the data
contracts shared by `complexity_classifier.py`, `context_builder.py`,
`pattern_parser.py`, `embedding_router.py`, `llm_resolver.py`,
`workflow_validator.py` and `fusion_resolver.py`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------
# Complexity classification (Fast Path vs Deep Path)
# ---------------------------------------------------------------------
class ComplexityResult(BaseModel):
    level: Literal["SIMPLE", "COMPLEX"] = "SIMPLE"
    reasons: List[str] = Field(default_factory=list)
    requires_llm: bool = False
    requires_context: bool = False
    requires_multi_intent: bool = False
    confidence: float = 0.5


# ---------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------
class ContextMessage(BaseModel):
    role: str
    content: str


class IntentContext(BaseModel):
    """Built once per turn by `IntentContextBuilder.build()`."""

    current_message: str
    recent_relevant_messages: List[ContextMessage] = Field(default_factory=list)

    current_phase: str = ""
    pending_confirmation: Optional[Dict[str, Any]] = None

    travel_requirement_summary: Dict[str, Any] = Field(default_factory=dict)
    current_plan_summary: Dict[str, Any] = Field(default_factory=dict)

    current_day_index: Optional[int] = None
    selected_activity_ids: List[str] = Field(default_factory=list)
    visible_candidate_ids: List[str] = Field(default_factory=list)

    last_agent_output_summary: Optional[str] = None
    current_destination: Optional[str] = None
    current_regions: List[str] = Field(default_factory=list)

    immutable_constraints: Dict[str, Any] = Field(default_factory=dict)

    # Bookkeeping -- not part of the spec's field list, but needed to thread
    # a trace_id through pattern/embedding/llm/fusion evidence logs.
    session_id: str = ""
    trace_id: str = ""


# ---------------------------------------------------------------------
# Pattern / rule parser output (see pattern_parser.py)
# ---------------------------------------------------------------------
class PatternResult(BaseModel):
    operation: Optional[str] = None  # ADD|REMOVE|REPLACE|MOVE|REPLAN|SELECT|CONFIRM|REJECT|COMPARE|QUERY|PRESERVE
    target: Optional[str] = None
    day_index: Optional[int] = None
    time_period: Optional[str] = None  # MORNING|AFTERNOON|EVENING

    activity_categories: List[str] = Field(default_factory=list)
    remove_categories: List[str] = Field(default_factory=list)
    add_categories: List[str] = Field(default_factory=list)
    region: Optional[str] = None
    quantity: Optional[int] = None

    # Round-5: region-replacement ("把第3天的Ubud换成努沙佩尼达"). Additive --
    # `region` above stays untouched for existing single-region usages
    # (COMPARE_REGIONS etc). `target_region` is deliberately allowed to be a
    # region never seen before (see pattern_parser._extract_region_replacement).
    source_region: Optional[str] = None
    target_region: Optional[str] = None
    region_focus: List[str] = Field(default_factory=list, description="活动需求关键词，例如 ['snorkeling','paragliding']")

    is_confirm: bool = False
    is_reject: bool = False
    is_negation: bool = False
    is_side_query: bool = False

    preserve_other_days: Optional[bool] = None
    preserve_other_time_periods: Optional[bool] = None

    mentioned_names: List[str] = Field(default_factory=list)
    referenced_ordinal: Optional[int] = Field(default=None, description="'第三个'/'这个'式的序号指代，1-based")

    has_ambiguity: bool = False
    multi_intent: bool = False
    confidence: float = 0.0
    raw_message: str = ""


# ---------------------------------------------------------------------
# Embedding retrieval output (see embedding_router.py)
# ---------------------------------------------------------------------
class MatchedExample(BaseModel):
    text: str
    intent: str
    score: float


class IntentCandidate(BaseModel):
    intent: str
    score: float


class FeedbackCandidate(BaseModel):
    feedback_type: str
    score: float


class EmbeddingIntentResult(BaseModel):
    intent_candidates: List[IntentCandidate] = Field(default_factory=list)
    feedback_candidates: List[FeedbackCandidate] = Field(default_factory=list)
    nearest_examples: List[MatchedExample] = Field(default_factory=list)
    confidence: float = 0.0


# ---------------------------------------------------------------------
# Workflow-state validation (see workflow_validator.py)
# ---------------------------------------------------------------------
class WorkflowValidationResult(BaseModel):
    is_valid: bool = True
    violations: List[str] = Field(default_factory=list)
    is_side_query: bool = False
    resume_phase: Optional[str] = None
    referenced_day_exists: Optional[bool] = None
    referenced_activity_exists: Optional[bool] = None
    touches_locked_constraint: bool = False
    penalty: float = 0.0


# ---------------------------------------------------------------------
# Final unified intent result (see fusion_resolver.py)
# ---------------------------------------------------------------------
class TravelIntentEntities(BaseModel):
    destination: Optional[str] = None
    region: Optional[str] = None
    day_index: Optional[int] = None
    time_period: Optional[str] = None

    # Round-5: region-replacement (see PatternResult above for rationale).
    source_region: Optional[str] = None
    target_region: Optional[str] = None
    region_focus: List[str] = Field(default_factory=list)
    search_strategy: Optional[str] = None

    activity_ids: List[str] = Field(default_factory=list)
    activity_names: List[str] = Field(default_factory=list)
    activity_categories: List[str] = Field(default_factory=list)

    remove_categories: List[str] = Field(default_factory=list)
    add_categories: List[str] = Field(default_factory=list)

    quantity: Optional[int] = None

    preserve_other_days: Optional[bool] = None
    preserve_existing_plan: Optional[bool] = None
    preserve_other_time_periods: Optional[bool] = None


class IntentResult(BaseModel):
    task_type: str = "GENERAL_CONVERSATION"
    operation: str = "QUERY"
    target: str = "FULL_ITINERARY"

    primary_intent: str = "OUT_OF_SCOPE"
    secondary_intents: List[str] = Field(default_factory=list)

    feedback_types: List[str] = Field(default_factory=list)

    rewritten_request: str = ""
    entities: TravelIntentEntities = Field(default_factory=TravelIntentEntities)

    state_patch: Dict[str, Any] = Field(default_factory=dict)

    requires_research: bool = False
    requires_replanning: bool = False

    interaction_mode: Literal[
        "NORMAL_FLOW", "SIDE_QUERY", "CLARIFICATION", "CONSERVATIVE_EXECUTION"
    ] = "NORMAL_FLOW"

    confidence: float = 0.0
    clarification_required: bool = False
    clarification_question: Optional[str] = None

    execution_plan: List[str] = Field(default_factory=list)
    next_agents: List[str] = Field(default_factory=list)

    preserve_current_state: bool = False
    resume_phase: Optional[str] = None

    # Log/eval-only; never surfaced to the end user.
    evidence: Dict[str, Any] = Field(default_factory=dict)
