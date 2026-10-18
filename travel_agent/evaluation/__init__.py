"""LLM-as-Judge offline evaluation harness (Round-5 Phase 6).

Scores a *finished* agent turn (user request + agent response + expected
goal, from a hand-authored `evaluation_cases/*.json` test case) across 6
weighted dimensions with concrete issues/suggestions -- replacing a single
blunt overall score. Run manually/in CI via `scripts/eval_llm_judge.py`, not
wired into the live graph. Deliberately separate from
`agents/reviewer_agent.py`'s `ReviewReport` (a live in-generation quality
gate with a different rubric, different inputs, different consumer) -- see
`travel_agent/evaluation/judge.py`'s module docstring for the full
rationale.
"""

from __future__ import annotations

from travel_agent.evaluation.judge import LLMJudge
from travel_agent.evaluation.llm_judge import StrictTravelEvaluator

__all__ = ["LLMJudge", "StrictTravelEvaluator"]
