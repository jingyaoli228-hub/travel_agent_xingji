"""Three-attempt controller and lexicographic best-plan selection."""

from __future__ import annotations

from typing import Any

MAX_PLAN_ATTEMPTS = 3


def plan_rank(report: dict[str, Any]) -> tuple:
    metrics = tuple(report.get(key) if report.get(key) is not None else float("-inf") for key in (
        "temporal_meal_score", "temporal_attraction_score", "spatial_score", "persona_score"
    ))
    return (-len(report.get("hard_violations") or []), -len(report.get("commonsense_violations") or []), *metrics)


def choose_best(current_plan, current_report, best_plan=None, best_report=None):
    if best_report is None or plan_rank(current_report) > plan_rank(best_report):
        return current_plan, current_report
    return best_plan, best_report


def build_repair_targets(report: dict[str, Any]) -> list[dict[str, Any]]:
    targets = []
    for violation in [*(report.get("hard_violations") or []), *(report.get("commonsense_violations") or [])]:
        targets.append({"dimension": violation["code"], "day": violation.get("day"), "poi": violation.get("item"), "problem": violation["message"]})
    for dimension in report.get("low_score_dimensions") or []:
        targets.append({"dimension": dimension, "day": None, "poi": None, "problem": f"{dimension} 指标低于独立阈值"})
    return targets


def route_metric_attempt(state: dict[str, Any]) -> str:
    report = state.get("metric_report") or {}
    attempt = int(state.get("planner_attempt", 0))
    if report.get("constraint_passed") and not report.get("low_score_dimensions"):
        return "reviewer"
    if state.get("needs_constraint_relaxation"):
        return "constraint_relaxation"
    if attempt < MAX_PLAN_ATTEMPTS:
        return "planner"
    return "constraint_relaxation" if report.get("hard_violations") else "reviewer"
