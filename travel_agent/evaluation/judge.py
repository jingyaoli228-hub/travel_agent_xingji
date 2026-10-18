"""`LLMJudge`: scores a finished agent turn against a hand-authored test
case's expected goal, across the 6 weighted dimensions in
`config/evaluation_criteria.yaml`, with concrete issues/suggestions.

Deliberately a SEPARATE system from `agents/reviewer_agent.py`'s
`ReviewReport`: `ReviewerAgent` is a live in-generation quality gate (5-dim
rubric, drives revision loops during initial plan generation; inputs =
Itinerary + TravelRequirement). This judge scores *finished* agent
responses against hand-authored expectations (inputs = user_request +
agent_response + expected_goal), run manually/in CI via
`scripts/eval_llm_judge.py` -- not wired into the live graph. Conflating the
two would mix "is this itinerary internally consistent" with "did the agent
do what a test case expects" -- different questions, different failure
modes.

Dual-path like `ReviewerAgent`/`DestinationIntelligenceService`: LLM
structured-output scoring when a client is given (passed in per-call, never
constructed here -- same reasoning as `destination_intelligence/service.py`,
keeps this module out of every LLM-patching test fixture), heuristic
keyword-overlap fallback otherwise, so the eval harness still produces
*something* with zero LLM key configured.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from travel_agent.evaluation.case_schema import EvalCase
from travel_agent.evaluation.config import load_evaluation_config
from travel_agent.evaluation.schemas import JudgeDimensionScores, JudgeVerdict


def _weighted_overall(scores: JudgeDimensionScores) -> float:
    w = load_evaluation_config().weights
    return round(
        scores.intent_understanding * w.intent_understanding
        + scores.destination_relevance * w.destination_relevance
        + scores.activity_matching * w.activity_matching
        + scores.personalization * w.personalization
        + scores.planning_feasibility * w.planning_feasibility
        + scores.response_quality * w.response_quality,
        2,
    )


def _tokenize(text: str) -> List[str]:
    """Crude whitespace/punctuation split -- good enough for a keyword-
    overlap heuristic; this codebase already leans on similarly simple
    regex/keyword heuristics elsewhere (`intent/pattern_parser.py`) rather
    than a real NLP dependency."""
    return [w for w in re.split(r"[\s,，。！？、/]+", text or "") if w]


class LLMJudge:
    def evaluate(
        self, case: EvalCase, agent_response: str, llm: Optional[Any] = None, system_prompt: str = ""
    ) -> JudgeVerdict:
        if llm is not None:
            verdict = self._evaluate_with_llm(case, agent_response, llm, system_prompt)
            if verdict is not None:
                return verdict
        return self._evaluate_heuristic(case, agent_response)

    def _evaluate_with_llm(self, case: EvalCase, agent_response: str, llm: Any, system_prompt: str) -> Optional[JudgeVerdict]:
        try:
            # method="function_calling": see requirement_agent.py's identical
            # comment -- DeepSeek rejects the response_format=json_schema
            # default for pydantic targets.
            structured_llm = llm.with_structured_output(JudgeVerdict, method="function_calling")
            prompt = (
                "你是旅行规划系统的评测员。请根据以下信息，对 Agent 的回应从六个维度打分(0-100)：\n"
                "intent_understanding(意图理解，包含是否识别出区域替换/活动需求等隐含意图)、"
                "destination_relevance(是否理解目的地/区域的真实特色而非套用通用模板)、"
                "activity_matching(推荐/搜索结果是否匹配用户具体提出的活动需求)、"
                "personalization(个性化程度)、planning_feasibility(行程/修改是否可行)、"
                "response_quality(回应清晰度与完整度)。\n"
                "必须列出具体问题(issues)和改进建议(suggestions)，不要只给分数、不要输出笼统评语。\n\n"
                f"用户请求: {case.user_request}\n\n"
                f"期望目标: {case.expected_goal}\n\n"
                f"Agent 回应: {agent_response}\n"
            )
            messages = []
            if system_prompt:
                messages.append(("system", system_prompt))
            messages.append(("human", prompt))
            result = structured_llm.invoke(messages)
            if isinstance(result, JudgeVerdict):
                result.case_id = case.case_id
                result.overall_score = _weighted_overall(result.dimension_scores)
                return result
        except Exception:
            return None
        return None

    def _evaluate_heuristic(self, case: EvalCase, agent_response: str) -> JudgeVerdict:
        """Rule-based approximate scoring: keyword-overlap between the
        expected goal and the actual response. Never crashes, never returns
        nothing -- the harness must still produce output with zero LLM key
        configured."""
        expected_keywords = [w for w in _tokenize(case.expected_goal) if len(w) >= 2]
        response_text = agent_response or ""
        matched = [w for w in expected_keywords if w in response_text]
        coverage = (len(matched) / len(expected_keywords)) if expected_keywords else 0.5

        base = int(30 + coverage * 60)
        scores = JudgeDimensionScores(
            intent_understanding=base,
            destination_relevance=base,
            activity_matching=base,
            personalization=max(20, base - 10),
            planning_feasibility=base,
            response_quality=base,
        )

        issues: List[str] = []
        suggestions: List[str] = []
        if not response_text:
            issues.append("Agent 未返回任何内容")
            suggestions.append("检查该场景下的执行链路是否正常触发。")
        else:
            missing = [w for w in expected_keywords if w not in response_text]
            if missing:
                issues.append(f"回应未覆盖期望目标中的关键点：{'、'.join(missing[:5])}")
                suggestions.append("检查是否正确理解了用户真实需求，并在回应中体现相关内容。")

        return JudgeVerdict(
            case_id=case.case_id,
            overall_score=_weighted_overall(scores),
            dimension_scores=scores,
            issues=issues,
            suggestions=suggestions,
        )
