"""Revision routing (requirement doc section 28): what happens after
`StrictTravelEvaluator` scores a plan.

    score >= pass_threshold (80)              -> pass, no notes
    notes_threshold <= score < pass_threshold  -> pass, but show improvement notes
    score < notes_threshold OR critical_failure, and revision budget left
                                                -> loop back for another pass
    revision budget exhausted                  -> pass anyway, with notes (never hang)

`decide_route()` picks the *graph node* to go to next (`"planner"` or
`"final_output"` -- both `graph/workflow.py`'s new `strict_evaluation` node
targets). `presentation_route()` is a separate, finer-grained call
`final_output_node` itself uses to decide whether to append improvement
notes to the response -- both "score >= 80" and "revision budget exhausted
at a lower score" end up at the same `final_output` node, but only the
latter should show notes.
"""

from __future__ import annotations

from typing import Literal

from travel_agent.evaluation.config import load_evaluation_config
from travel_agent.evaluation.schemas import TravelEvaluationResult

RouteTarget = Literal["planner", "final_output"]
PresentationMode = Literal["final_output", "final_output_with_notes"]


def decide_route(result: TravelEvaluationResult, revision_round: int) -> RouteTarget:
    config = load_evaluation_config()
    if revision_round >= config.max_revision_rounds:
        return "final_output"
    if result.critical_failures:
        return "planner"
    if result.overall_score >= config.notes_threshold:
        return "final_output"
    return "planner"


def presentation_route(result: TravelEvaluationResult) -> PresentationMode:
    config = load_evaluation_config()
    if result.overall_score >= config.pass_threshold and not result.critical_failures:
        return "final_output"
    return "final_output_with_notes"
