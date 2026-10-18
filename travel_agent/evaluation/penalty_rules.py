"""Hard-penalty detection for `StrictTravelEvaluator` (requirement doc
section 26): objective, rule-checkable failure modes that must dock points
regardless of what an LLM's subjective dimension scores land on -- "不能因为
格式完整就给高分".

Scope note: not all 9 penalty rules in `config/evaluation_criteria.yaml:
hard_penalties` are heuristically checkable without either semantic
judgment or data this pipeline doesn't currently snapshot:

- `wrong_destination` needs to know what "belongs" to a destination well
  enough to say an itinerary drifted from it -- a real judgment call, not a
  string-containment check reliable enough to avoid false positives on
  legitimate region-only itineraries (e.g. a Bali trip whose items only ever
  say "乌布"/"苍古", never literally "巴厘岛").
- `violated_preserve_scope` needs a *before* itinerary snapshot to diff
  against, which `graph/nodes.py` doesn't currently preserve past the
  revision that already happened.
- `unsupported_claim` needs fact-checking a claim against real-world truth.

These three are LLM-only in `evaluate_with_llm()` (see `llm_judge.py`) and
simply don't fire in the heuristic-only path -- documented, not silently
dropped. The 6 rules below (`empty_day`, `repeated_rejected_activity`,
`missing_activity_description`, `generic_destination_plan`,
`missed_explicit_activity`, `geographically_impossible`) are all
objectively checkable from `StrictEvaluationInput` alone.
"""

from __future__ import annotations

from typing import Any, Dict, List

from travel_agent.evaluation.config import HardPenalties, load_evaluation_config
from travel_agent.evaluation.schemas import HardPenaltyHit, StrictEvaluationInput
from travel_agent.rag.topic_vocab import TOPIC_KEYWORDS

_MIN_DESCRIPTION_CHARS = 4


def _itinerary_days(evaluation_input: StrictEvaluationInput) -> List[Dict[str, Any]]:
    return evaluation_input.final_itinerary.get("days") or []


def _all_items(evaluation_input: StrictEvaluationInput) -> List[Dict[str, Any]]:
    return [item for day in _itinerary_days(evaluation_input) for item in (day.get("items") or [])]


def _itinerary_text(evaluation_input: StrictEvaluationInput) -> str:
    parts = []
    for item in _all_items(evaluation_input):
        parts.append(str(item.get("activity") or ""))
        parts.append(str(item.get("location") or ""))
        parts.append(str(item.get("reason") or ""))
    return " ".join(parts)


def _check_empty_days(evaluation_input: StrictEvaluationInput, points: float) -> List[HardPenaltyHit]:
    hits = []
    for day in _itinerary_days(evaluation_input):
        if not day.get("items"):
            hits.append(
                HardPenaltyHit(
                    rule="empty_day", points=points,
                    reason=f"第{day.get('day_number', '?')}天没有安排任何活动",
                )
            )
    return hits


def _check_repeated_rejected(evaluation_input: StrictEvaluationInput, points: float) -> List[HardPenaltyHit]:
    rejected_names = set()
    for episode in evaluation_input.episodic_memories:
        rejected_names.update(episode.get("rejected_experiences") or [])
    if not rejected_names:
        return []

    hit_names = set()
    for item in _all_items(evaluation_input):
        activity = str(item.get("activity") or "")
        location = str(item.get("location") or "")
        for name in rejected_names:
            if name and (name in activity or name in location):
                hit_names.add(name)
    if not hit_names:
        return []
    return [
        HardPenaltyHit(
            rule="repeated_rejected_activity", points=points,
            reason=f"再次推荐了用户明确拒绝过的内容：{'、'.join(sorted(hit_names))}",
        )
    ]


def _check_missing_description(evaluation_input: StrictEvaluationInput, points: float) -> List[HardPenaltyHit]:
    missing = [
        item.get("activity", "?")
        for item in _all_items(evaluation_input)
        if len(str(item.get("reason") or "").strip()) < _MIN_DESCRIPTION_CHARS
    ]
    if not missing:
        return []
    return [
        HardPenaltyHit(
            rule="missing_activity_description", points=points,
            reason=f"以下活动缺少推荐理由说明：{'、'.join(missing[:5])}",
        )
    ]


def _check_generic_plan(evaluation_input: StrictEvaluationInput, points: float) -> List[HardPenaltyHit]:
    highlights = list(evaluation_input.destination_profile.get("signature_experiences") or []) + list(
        evaluation_input.destination_profile.get("highlights") or []
    )
    if not highlights:
        return []  # no known destination profile to compare against -- can't judge genericness
    text = _itinerary_text(evaluation_input)
    if any(str(h) and str(h) in text for h in highlights):
        return []
    return [
        HardPenaltyHit(
            rule="generic_destination_plan", points=points,
            reason=f"行程未体现该目的地的任何特色体验（{'、'.join(str(h) for h in highlights[:5])}）",
        )
    ]


def _check_missed_explicit_activity(evaluation_input: StrictEvaluationInput, points: float) -> List[HardPenaltyHit]:
    request_text = f"{evaluation_input.user_request} {evaluation_input.user_feedback}"
    requested_topics = {topic for keyword, topic in TOPIC_KEYWORDS.items() if keyword in request_text}
    if not requested_topics:
        return []
    itinerary_text = _itinerary_text(evaluation_input)
    missed = sorted(topic for topic in requested_topics if topic not in itinerary_text)
    if not missed:
        return []
    return [
        HardPenaltyHit(
            rule="missed_explicit_activity", points=points,
            reason=f"用户明确要求的活动未出现在最终行程中：{'、'.join(missed)}",
        )
    ]


def _parse_hhmm(value: str) -> int:
    """Minutes since midnight, or -1 if unparseable."""
    try:
        hour, minute = value.strip().split(":")
        return int(hour) * 60 + int(minute)
    except (ValueError, AttributeError):
        return -1


def _check_schedule_overlap(evaluation_input: StrictEvaluationInput, points: float) -> List[HardPenaltyHit]:
    """Proxy for `geographically_impossible`: back-to-back items whose
    start times overlap once the first's duration is accounted for can't
    both be real (whether or not we know the actual travel distance)."""
    hits = []
    for day in _itinerary_days(evaluation_input):
        items = sorted(
            (item for item in (day.get("items") or []) if _parse_hhmm(str(item.get("time", ""))) >= 0),
            key=lambda item: _parse_hhmm(str(item["time"])),
        )
        for current, following in zip(items, items[1:]):
            start = _parse_hhmm(str(current["time"]))
            end = start + int(current.get("duration_minutes") or 0)
            next_start = _parse_hhmm(str(following["time"]))
            if next_start < end:
                hits.append(
                    HardPenaltyHit(
                        rule="geographically_impossible", points=points,
                        reason=(
                            f"第{day.get('day_number', '?')}天「{current.get('activity')}」"
                            f"（{current['time']}起{current.get('duration_minutes')}分钟）"
                            f"与「{following.get('activity')}」（{following['time']}）时间冲突，行程不可行"
                        ),
                    )
                )
    return hits


def detect_penalties(evaluation_input: StrictEvaluationInput, penalties: HardPenalties | None = None) -> List[HardPenaltyHit]:
    cfg = penalties or load_evaluation_config().hard_penalties
    hits: List[HardPenaltyHit] = []
    hits.extend(_check_empty_days(evaluation_input, cfg.empty_day))
    hits.extend(_check_repeated_rejected(evaluation_input, cfg.repeated_rejected_activity))
    hits.extend(_check_missing_description(evaluation_input, cfg.missing_activity_description))
    hits.extend(_check_generic_plan(evaluation_input, cfg.generic_destination_plan))
    hits.extend(_check_missed_explicit_activity(evaluation_input, cfg.missed_explicit_activity))
    hits.extend(_check_schedule_overlap(evaluation_input, cfg.geographically_impossible))
    return hits
