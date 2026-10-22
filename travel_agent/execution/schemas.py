"""Execution-layer schemas: how an `IntentResult` turns into a concrete,
traceable chain across the four existing agents (Requirement / Research
Orchestrator / Planner / Presentation-Review), and how their partial results
get merged back into one coherent, diff-aware update.

No fifth agent is introduced here -- `AgentName` only ever names one of the
four existing agents; `ExecutionPlanner`/`AgentRouter`/`AgentResultAggregator`
are ordinary services, not agents.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

AgentName = Literal["RequirementAgent", "ResearchOrchestrator", "PlannerAgent", "PresentationAgent"]


class ExecutionStep(BaseModel):
    step: int
    agent: AgentName
    action: str
    input_ref: Dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    trace_id: str
    steps: List[ExecutionStep] = Field(default_factory=list)
    preserve_scope: Dict[str, Any] = Field(default_factory=dict)


class StepResult(BaseModel):
    step: int
    agent: AgentName
    action: str
    success: bool = True
    error: Optional[str] = None
    output: Dict[str, Any] = Field(default_factory=dict)


class AggregatedExecutionResult(BaseModel):
    requirement_changes: Dict[str, Any] = Field(default_factory=dict)
    new_activity_candidates: List[dict] = Field(default_factory=list)
    changed_items: List[Dict[str, Any]] = Field(default_factory=list)
    updated_itinerary: Optional[dict] = None

    preserved_scope: Dict[str, Any] = Field(default_factory=dict)
    changed_scope: Dict[str, Any] = Field(default_factory=dict)

    warnings: List[str] = Field(default_factory=list)
    unresolved_issues: List[str] = Field(default_factory=list)

    user_visible_summary: Dict[str, Any] = Field(default_factory=dict)
    step_results: List[StepResult] = Field(default_factory=list)
    trace_id: str = ""
