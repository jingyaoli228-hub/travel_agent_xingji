"""Human-readable rendering of a `TravelEvaluationResult` -- requirement doc
section 27/39: "明确解释为什么计划得分低", never just a bare number. Used by
`GET /evaluation/report/{trace_id}` and `final_output_node`'s improvement
notes.
"""

from __future__ import annotations

from travel_agent.evaluation.schemas import TravelEvaluationResult

_DIMENSION_LABELS = {
    "requirement_adherence": "需求符合度",
    "user_profile_alignment": "画像匹配度",
    "destination_specificity": "目的地特色",
    "activity_richness": "活动丰富度",
    "activity_diversity": "活动多样性",
    "itinerary_feasibility": "行程可行性",
    "evidence_and_accuracy": "证据与准确性",
    "presentation_quality": "呈现质量",
}

_ISSUE_SECTIONS = [
    ("failed_requirements", "未满足的需求"),
    ("missing_user_preferences", "缺失的用户偏好"),
    ("repeated_rejected_preferences", "重复推荐了已拒绝内容"),
    ("richness_issues", "丰富度问题"),
    ("diversity_issues", "多样性问题"),
    ("feasibility_issues", "可行性问题"),
    ("evidence_issues", "证据问题"),
    ("critical_failures", "严重问题"),
]


def generate_report(result: TravelEvaluationResult, trace_id: str = "") -> str:
    lines = []
    if trace_id:
        lines.append(f"trace_id: {trace_id}")
    lines.append(f"总分: {result.overall_score}/100")
    lines.append("")
    lines.append("维度得分:")
    for field, label in _DIMENSION_LABELS.items():
        lines.append(f"  {label}: {getattr(result.dimension_scores, field)}")

    if result.hard_penalties:
        lines.append("")
        lines.append("硬性扣分:")
        for penalty in result.hard_penalties:
            lines.append(f"  [{penalty.rule}] {penalty.points} 分 -- {penalty.reason}")

    for field, label in _ISSUE_SECTIONS:
        items = getattr(result, field)
        if items:
            lines.append("")
            lines.append(f"{label}:")
            for item in items:
                lines.append(f"  - {item}")

    if result.improvement_actions:
        lines.append("")
        lines.append("改进建议:")
        for action in result.improvement_actions:
            lines.append(f"  - {action}")

    if result.should_research_more or result.should_replan:
        lines.append("")
        lines.append(
            "后续动作: "
            + ("补充研究 " if result.should_research_more else "")
            + ("重新规划 " if result.should_replan else "")
        )
        if result.suggested_research_directions:
            lines.append(f"建议研究方向: {'、'.join(result.suggested_research_directions)}")

    return "\n".join(lines)


def generate_notes(result: TravelEvaluationResult) -> str:
    """Short version for `final_output_node`'s "final_output_with_notes"
    presentation mode -- a few lines appended to the itinerary response, not
    the full report."""
    lines = [f"（本次行程质量评分 {result.overall_score}/100，以下是可改进之处：）"]
    for action in result.improvement_actions:
        lines.append(f"- {action}")
    if not result.improvement_actions:
        for field, label in _ISSUE_SECTIONS:
            items = getattr(result, field)
            if items:
                lines.append(f"- {label}: {items[0]}")
                break
    return "\n".join(lines)
