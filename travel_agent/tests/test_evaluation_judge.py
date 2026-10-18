"""Tests for the Round-5 LLM-as-Judge evaluation harness
(`travel_agent/evaluation/`): heuristic-path scoring arithmetic (offline,
no LLM key needed) and schema-validation of the hand-authored
`evaluation_cases/*.json` datasets (catches malformed data early, cheap CI
signal, same convention as other schema-load tests in this suite).
"""

from __future__ import annotations

import json
from pathlib import Path

from travel_agent.evaluation.case_schema import EvalCase
from travel_agent.evaluation.config import load_evaluation_config
from travel_agent.evaluation.judge import LLMJudge
from travel_agent.evaluation.schemas import JudgeDimensionScores, JudgeVerdict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CASES_DIR = _REPO_ROOT / "evaluation_cases"


def test_weights_sum_to_one():
    w = load_evaluation_config().weights
    total = (
        w.intent_understanding + w.destination_relevance + w.activity_matching
        + w.personalization + w.planning_feasibility + w.response_quality
    )
    assert abs(total - 1.0) < 1e-6


def test_heuristic_overall_score_matches_weighted_formula():
    scores = JudgeDimensionScores(
        intent_understanding=80, destination_relevance=70, activity_matching=60,
        personalization=50, planning_feasibility=90, response_quality=100,
    )
    w = load_evaluation_config().weights
    expected = round(
        80 * w.intent_understanding + 70 * w.destination_relevance + 60 * w.activity_matching
        + 50 * w.personalization + 90 * w.planning_feasibility + 100 * w.response_quality,
        2,
    )

    case = EvalCase(case_id="unit_test", category="feedback", user_request="x", expected_goal="y")
    judge = LLMJudge()

    class _FakeLLM:
        def with_structured_output(self, *_args, **_kwargs):
            fake = self

            class _Structured:
                def invoke(self, _messages):
                    return JudgeVerdict(case_id="", overall_score=0, dimension_scores=scores)

            return _Structured()

    verdict = judge.evaluate(case, "some response", llm=_FakeLLM())
    assert verdict.case_id == "unit_test"
    assert verdict.overall_score == expected


def test_heuristic_path_used_without_llm_produces_valid_verdict():
    case = EvalCase(
        case_id="heuristic_test", category="modification", user_request="把Ubud换成努沙佩尼达，我想浮潜",
        expected_goal="识别为区域替换，target_region为努沙佩尼达，活动需求包含浮潜",
    )
    judge = LLMJudge()
    verdict = judge.evaluate(case, "理解意图: REGION_REPLACEMENT；活动需求: 浮潜", llm=None)
    assert 0 <= verdict.overall_score <= 100
    assert verdict.case_id == "heuristic_test"
    for field in (
        "intent_understanding", "destination_relevance", "activity_matching",
        "personalization", "planning_feasibility", "response_quality",
    ):
        value = getattr(verdict.dimension_scores, field)
        assert 0 <= value <= 100


def test_heuristic_path_flags_missing_expected_keywords():
    case = EvalCase(case_id="missing_test", category="feedback", user_request="x", expected_goal="识别为区域替换并研究浮潜")
    judge = LLMJudge()
    verdict = judge.evaluate(case, "完全不相关的回应", llm=None)
    assert verdict.issues  # some expected keyword should be reported missing


def test_heuristic_path_empty_response_flagged():
    case = EvalCase(case_id="empty_test", category="feedback", user_request="x", expected_goal="任意目标")
    judge = LLMJudge()
    verdict = judge.evaluate(case, "", llm=None)
    assert any("未返回任何内容" in issue for issue in verdict.issues)


# -- Hand-authored evaluation_cases/*.json schema validation ------------------


def test_evaluation_case_files_exist_and_validate():
    filenames = ["feedback_cases.json", "destination_cases.json", "modification_cases.json"]
    total = 0
    for filename in filenames:
        path = _CASES_DIR / filename
        assert path.exists(), f"missing {path}"
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(raw, list) and len(raw) >= 2
        for item in raw:
            case = EvalCase(**item)
            assert case.case_id
            assert case.user_request
            assert case.expected_goal
            total += 1
    assert total >= 8


def test_evaluation_cases_have_unique_ids():
    filenames = ["feedback_cases.json", "destination_cases.json", "modification_cases.json"]
    all_ids = []
    for filename in filenames:
        raw = json.loads((_CASES_DIR / filename).read_text(encoding="utf-8"))
        all_ids.extend(item["case_id"] for item in raw)
    assert len(all_ids) == len(set(all_ids))


def test_modification_cases_cover_region_replacement_scenario():
    """The literal spec-example scenario must be represented in the eval
    dataset -- otherwise this whole Phase's fix has no regression coverage
    at the evaluation-harness level, only at the unit-test level."""
    raw = json.loads((_CASES_DIR / "modification_cases.json").read_text(encoding="utf-8"))
    assert any("换成" in item["user_request"] and "浮潜" in item["user_request"] for item in raw)
