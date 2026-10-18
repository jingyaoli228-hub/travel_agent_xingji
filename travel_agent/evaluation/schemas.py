"""Schemas for the LLM-as-Judge evaluation harness. Named distinctly from
`schemas/review.py`'s `DimensionScores`/`ReviewReport` to avoid confusion
with the live in-generation ReviewerAgent -- these are a different rubric
for a different purpose (see `evaluation/__init__.py`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JudgeDimensionScores(BaseModel):
    intent_understanding: int = Field(..., ge=0, le=100, description="是否正确理解了用户意图（含隐含的修改/替换/区域切换类请求）")
    destination_relevance: int = Field(..., ge=0, le=100, description="是否理解了目的地/区域的真实特色，而非套用通用模板")
    activity_matching: int = Field(..., ge=0, le=100, description="推荐/搜索到的活动是否匹配用户具体提出的活动需求")
    personalization: int = Field(..., ge=0, le=100, description="个性化程度，是否针对用户偏好而非泛化推荐")
    planning_feasibility: int = Field(..., ge=0, le=100, description="行程/修改是否可行（时间、范围、约束）")
    response_quality: int = Field(..., ge=0, le=100, description="回应本身的清晰度、完整度")


class JudgeVerdict(BaseModel):
    case_id: str = ""
    overall_score: float = Field(default=0.0, ge=0, le=100, description="6 维加权分，权重见 config/evaluation_criteria.yaml")
    dimension_scores: JudgeDimensionScores
    issues: List[str] = Field(default_factory=list, description="具体问题，例如'没有识别区域替换'")
    suggestions: List[str] = Field(default_factory=list, description="具体建议，例如'增加 Destination Intelligence'")


# ===========================================================================
# Round-6 Phase 6: Strict Travel Evaluation (`evaluation/llm_judge.py`'s
# `StrictTravelEvaluator`) -- a SEPARATE, heavier-input system from the
# `JudgeVerdict`/`LLMJudge` pair above. `LLMJudge` keeps serving
# `scripts/eval_llm_judge.py`'s "hand-authored case vs agent response"
# harness unchanged; this is the graph-wired, 8-dimension, hard-penalty,
# closed-loop evaluator (requirement doc sections 22-28).
# ===========================================================================


class StrictEvaluationInput(BaseModel):
    """Everything `StrictTravelEvaluator` needs -- requirement doc section
    23 is explicit that the Judge must not just get "question + final
    answer": it needs the structured requirement, profile, episodic
    memories, candidates, and tool evidence too, or it can't tell whether a
    plan matches the profile, omits an explicitly-requested activity, or
    wrongly touched a day the user said to leave alone."""

    user_request: str = ""
    travel_requirement: Dict[str, Any] = Field(default_factory=dict)
    user_profile: Dict[str, Any] = Field(default_factory=dict)
    episodic_memories: List[Dict[str, Any]] = Field(default_factory=list)
    destination_profile: Dict[str, Any] = Field(default_factory=dict)
    candidate_activities: List[Dict[str, Any]] = Field(default_factory=list)
    final_itinerary: Dict[str, Any] = Field(default_factory=dict)
    tool_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    user_feedback: str = ""
    preserve_other_days: Optional[bool] = None
    target_day_index: Optional[int] = None


class StrictDimensionScores(BaseModel):
    """Requirement doc section 24 -- each field's `le` is that dimension's
    max points (they intentionally don't share one 0-100 scale; see
    `config/evaluation_criteria.yaml: strict_weights` for the point budget)."""

    requirement_adherence: float = Field(..., ge=0, le=20)
    user_profile_alignment: float = Field(..., ge=0, le=15)
    destination_specificity: float = Field(..., ge=0, le=15)
    activity_richness: float = Field(..., ge=0, le=15)
    activity_diversity: float = Field(..., ge=0, le=10)
    itinerary_feasibility: float = Field(..., ge=0, le=15)
    evidence_and_accuracy: float = Field(..., ge=0, le=5)
    presentation_quality: float = Field(..., ge=0, le=5)


class HardPenaltyHit(BaseModel):
    rule: str
    points: float = Field(..., description="Negative -- see config/evaluation_criteria.yaml: hard_penalties")
    reason: str = ""


class TravelEvaluationResult(BaseModel):
    """Requirement doc section 27, field-for-field."""

    overall_score: float = Field(default=0.0, ge=0, le=100)
    dimension_scores: StrictDimensionScores

    hard_penalties: List[HardPenaltyHit] = Field(default_factory=list)

    passed_requirements: List[str] = Field(default_factory=list)
    failed_requirements: List[str] = Field(default_factory=list)

    missing_user_preferences: List[str] = Field(default_factory=list)
    repeated_rejected_preferences: List[str] = Field(default_factory=list)

    richness_issues: List[str] = Field(default_factory=list)
    diversity_issues: List[str] = Field(default_factory=list)
    feasibility_issues: List[str] = Field(default_factory=list)
    evidence_issues: List[str] = Field(default_factory=list)

    critical_failures: List[str] = Field(default_factory=list)
    improvement_actions: List[str] = Field(default_factory=list)

    should_research_more: bool = False
    should_replan: bool = False
    suggested_research_directions: List[str] = Field(default_factory=list)
