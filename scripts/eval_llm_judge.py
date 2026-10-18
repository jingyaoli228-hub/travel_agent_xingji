"""Offline LLM-as-Judge evaluation against `evaluation_cases/*.json`.

Scoping note (deliberate, not an oversight): like `eval_intent_accuracy.py`,
this drives `MultiSignalIntentInterpreter` directly rather than the full
LangGraph -- running the whole graph per case would need either real
Research/Planner API calls (contradicting this project's "prefer offline"
convention for scripts, see `travel_agent/tests/conftest.py`'s docstring) or
a lot of session/checkpoint scaffolding to fabricate `prior_state` as if it
came from a real prior conversation. Instead, each case's `prior_state` is
used to build an `IntentContext` directly, and the "agent_response" scored
by the judge is a synthesized summary of what the system understood
(primary_intent, entities, next_agents) -- enough signal for
intent_understanding/destination_relevance/activity_matching, the three
dimensions this phase's bug fixes target most directly. Wiring in a live,
full-graph mode is a documented follow-up (`--live`, not implemented here),
not required for this harness to be useful today.

Default: Pattern + Embedding only (fast, free, offline), heuristic judge
(no LLM key needed). Pass `--with-llm` to also exercise the Deep Path's LLM
branch AND the LLM-based judge (needs a configured `KIMI_API`/`DEEPSEEK_API_KEY`
etc.); expect this to take much longer.

Usage:
    python scripts/eval_llm_judge.py
    python scripts/eval_llm_judge.py --with-llm --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("asyncio").setLevel(logging.WARNING)  # settings.debug=True otherwise leaks noisy proactor logs

from travel_agent.config.llm import get_llm
from travel_agent.config.settings import get_settings
from travel_agent.evaluation.case_schema import EvalCase
from travel_agent.evaluation.judge import LLMJudge
from travel_agent.evaluation.schemas import JudgeVerdict
from travel_agent.intent.interpreter import MultiSignalIntentInterpreter
from travel_agent.intent.schemas import IntentContext


class _NullLLMResolver:
    def resolve(self, *args, **kwargs):
        return None


def _load_cases(cases_dir: str) -> List[EvalCase]:
    cases: List[EvalCase] = []
    for filename in ("feedback_cases.json", "destination_cases.json", "modification_cases.json"):
        path = Path(cases_dir) / filename
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases.extend(EvalCase(**item) for item in raw)
    return cases


def _context_from_case(case: EvalCase) -> IntentContext:
    prior = case.prior_state or {}
    return IntentContext(
        current_message=case.user_request,
        current_phase=prior.get("current_phase", ""),
        current_plan_summary=prior.get("current_plan_summary", {}),
        current_regions=prior.get("current_regions", []),
        current_destination=prior.get("current_destination"),
    )


def _synthesize_agent_response(case: EvalCase, interpreter: MultiSignalIntentInterpreter) -> str:
    ctx = _context_from_case(case)
    result = interpreter.interpret(case.user_request, ctx)
    entities = result.entities
    parts = [
        f"理解意图: {result.primary_intent} (operation={result.operation}, target={result.target})",
        f"下一步Agent: {', '.join(result.next_agents) or '无'}",
    ]
    if entities.source_region or entities.target_region:
        parts.append(f"区域替换: {entities.source_region} -> {entities.target_region}")
    if entities.region_focus:
        parts.append(f"活动需求: {', '.join(entities.region_focus)}")
    if entities.add_categories:
        parts.append(f"新增类别: {', '.join(entities.add_categories)}")
    if entities.remove_categories:
        parts.append(f"移除类别: {', '.join(entities.remove_categories)}")
    if entities.day_index:
        parts.append(f"目标天数: 第{entities.day_index}天")
    parts.append(f"其他天保持不变: {'是' if entities.preserve_other_days else '未声明/否'}")
    return "；".join(parts)


def _print_verdict(verdict: JudgeVerdict) -> None:
    print(f"  overall={verdict.overall_score:6.2f}  "
          f"intent={verdict.dimension_scores.intent_understanding} "
          f"dest={verdict.dimension_scores.destination_relevance} "
          f"activity={verdict.dimension_scores.activity_matching} "
          f"personal={verdict.dimension_scores.personalization} "
          f"feasible={verdict.dimension_scores.planning_feasibility} "
          f"quality={verdict.dimension_scores.response_quality}")
    for issue in verdict.issues:
        print(f"    issue: {issue}")
    for suggestion in verdict.suggestions:
        print(f"    suggestion: {suggestion}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-llm", action="store_true", help="Also exercise the LLM branches (slow, needs a real key)")
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N cases")
    args = parser.parse_args()

    settings = get_settings()
    cases = _load_cases(settings.evaluation_cases_dir)
    if args.limit:
        cases = cases[: args.limit]

    interpreter = MultiSignalIntentInterpreter()
    judge_llm = None
    judge_system_prompt = ""
    if not args.with_llm:
        interpreter._llm_resolver = _NullLLMResolver()
    else:
        judge_llm = get_llm(role="reviewer", tier="fast")

    judge = LLMJudge()
    verdicts: List[JudgeVerdict] = []
    print(f"Cases: {len(cases)}  (LLM branch: {'on' if args.with_llm else 'off'})\n")
    for case in cases:
        agent_response = _synthesize_agent_response(case, interpreter)
        verdict = judge.evaluate(case, agent_response, llm=judge_llm, system_prompt=judge_system_prompt)
        verdicts.append(verdict)
        print(f"[{case.category}] {case.case_id}")
        print(f"  request: {case.user_request}")
        print(f"  response: {agent_response}")
        _print_verdict(verdict)
        print()

    if verdicts:
        avg_overall = sum(v.overall_score for v in verdicts) / len(verdicts)
        dims = ["intent_understanding", "destination_relevance", "activity_matching", "personalization", "planning_feasibility", "response_quality"]
        print("=" * 60)
        print(f"Average overall_score: {avg_overall:.2f}")
        for dim in dims:
            avg = sum(getattr(v.dimension_scores, dim) for v in verdicts) / len(verdicts)
            print(f"  {dim}: {avg:.1f}")
        worst = sorted(verdicts, key=lambda v: v.overall_score)[:5]
        print("\nWorst 5 cases:")
        for v in worst:
            print(f"  {v.case_id}: {v.overall_score:.2f}")


if __name__ == "__main__":
    main()
