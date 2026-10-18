"""Fusion resolver (design doc section 10) + the shared Fast/Deep Path
assembly helpers.

`build_fast_result()` is used by the Fast Path: Pattern + Workflow State
only, no LLM/embedding weighting -- if it can't clear the fast-path
confidence gate (or the Workflow Validator rejects it), it returns `None`
and the interpreter falls back to `FusionResolver.fuse()` on the Deep Path,
which combines Pattern + Embedding + LLM under the configured weights.

Both paths funnel through the same entity/state-patch/next-agent inference
helpers so the two paths can never silently diverge in shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from travel_agent.intent.config import load_fusion_config
from travel_agent.intent.data_store import load_taxonomy
from travel_agent.intent.schemas import (
    EmbeddingIntentResult,
    IntentContext,
    IntentResult,
    PatternResult,
    TravelIntentEntities,
)
from travel_agent.intent.workflow_validator import WorkflowStateValidator

_WEATHER_WORDS = ["天气", "下雨", "热不热", "季节"]
_VISA_WORDS = ["签证", "免签", "落地签", "护照"]
_TRANSPORT_WORDS = ["怎么去", "打车", "地铁", "机场", "多久一班", "出租车", "公交", "怎么走", "租车"]

_AGENTS_WITH_STEP_LABELS = {
    "RequirementAgent": "UPDATE_REQUIREMENT",
    "ResearchOrchestrator": "SEARCH_MORE_ACTIVITIES",
    "PresentationAgent": "PRESENT_PLAN_DIFF",
}


def _query_subtype(pattern: PatternResult) -> str:
    text = pattern.raw_message
    if any(w in text for w in _WEATHER_WORDS):
        return "QUERY_WEATHER"
    if any(w in text for w in _VISA_WORDS):
        return "QUERY_VISA"
    if any(w in text for w in _TRANSPORT_WORDS):
        return "QUERY_TRANSPORT"
    if "附近" in text or "一带" in text:
        return "QUERY_NEARBY"
    return "QUERY_ACTIVITY_DETAIL"


def pattern_to_intent(pattern: PatternResult, context: IntentContext) -> Tuple[str, float]:
    """Best-guess `primary_intent` derivable from Pattern alone, plus a score
    in [0, 1] (== `pattern.confidence`, already operation-aware)."""
    op = pattern.operation
    score = pattern.confidence

    if op is None:
        return ("AMBIGUOUS_MODIFICATION" if pattern.has_ambiguity else "OUT_OF_SCOPE"), max(score, 0.2)
    if op == "CONFIRM":
        phase = context.current_phase
        if phase == "selection":
            return "CONFIRM_SELECTION", score
        if phase in ("post_plan_feedback", "done"):
            return "CONFIRM_ITINERARY", score
        return "CONFIRM_REQUIREMENT", score
    if op == "REJECT":
        return "REJECT_CURRENT_OPTIONS", score
    if op == "ADD":
        return "ADD_ACTIVITY", score
    if op == "REMOVE":
        return "REMOVE_ACTIVITY", score
    if op == "REPLACE":
        if pattern.target == "REGION" or (pattern.source_region and pattern.target_region):
            return "REGION_REPLACEMENT", score
        return "REPLACE_ACTIVITY", score
    if op == "MOVE":
        return "MOVE_ACTIVITY", score
    if op == "SELECT":
        return "SELECT_ACTIVITY", score
    if op == "COMPARE":
        return "COMPARE_REGIONS", score
    if op == "REPLAN":
        if pattern.day_index and pattern.preserve_other_days:
            return "REPLAN_PARTIAL_DAY", score
        if pattern.day_index:
            return "REPLAN_DAY", score
        return "REPLAN_FULL_TRIP", score
    if op == "QUERY":
        return _query_subtype(pattern), score
    return "AMBIGUOUS_MODIFICATION", max(score, 0.2)


def entities_from_pattern(pattern: PatternResult) -> TravelIntentEntities:
    # A region-replacement's activity ask ("我想浮潜和滑翔伞") is carried in
    # `region_focus`, separate from `add_categories` -- but merged into
    # `add_categories` too here so the *existing* research/selection call
    # sites (agent_router.py, pre-Phase-5) that only read `add_categories`
    # still pick it up without waiting on the Phase-5 query generator.
    add_categories = list(pattern.add_categories)
    for cat in pattern.region_focus:
        if cat not in add_categories:
            add_categories.append(cat)
    return TravelIntentEntities(
        region=pattern.region,
        source_region=pattern.source_region,
        target_region=pattern.target_region,
        region_focus=pattern.region_focus,
        search_strategy=("REGION_PROFILE_THEN_FOCUSED_SEARCH" if pattern.target_region else None),
        day_index=pattern.day_index,
        time_period=pattern.time_period,
        activity_categories=pattern.activity_categories,
        remove_categories=pattern.remove_categories,
        add_categories=add_categories,
        quantity=pattern.quantity,
        preserve_other_days=pattern.preserve_other_days,
        preserve_other_time_periods=pattern.preserve_other_time_periods,
    )


def state_patch_from_feedback(feedback_types: List[str]) -> Dict[str, Any]:
    table = load_taxonomy().get("feedback_types", {})
    reduce_types: List[str] = []
    add_types: List[str] = []
    patch: Dict[str, Any] = {}
    for ft in feedback_types:
        spec = table.get(ft, {})
        reduce_types.extend(spec.get("reduce_types", []))
        add_types.extend(spec.get("add_types", []))
        if "daily_attraction_count_delta" in spec:
            patch["daily_attraction_count_delta"] = patch.get("daily_attraction_count_delta", 0) + spec["daily_attraction_count_delta"]
        if spec.get("prefer_cheap"):
            patch["prefer_cheap"] = True
        if spec.get("prefer_niche"):
            patch["prefer_niche"] = True
        if spec.get("transport_preference"):
            patch["transport_preference"] = spec["transport_preference"]
        if spec.get("trigger_more_research"):
            patch["trigger_more_research"] = True
        if spec.get("tighten_region"):
            patch["tighten_region"] = True
    if reduce_types:
        patch["preferences_to_reduce"] = list(dict.fromkeys(reduce_types))
    if add_types:
        patch["preferences_to_add"] = list(dict.fromkeys(add_types))
    return patch


def merge_category_state_patch(state_patch: Dict[str, Any], entities: TravelIntentEntities) -> Dict[str, Any]:
    merged = dict(state_patch)
    if entities.add_categories:
        merged["preferences_to_add"] = list(dict.fromkeys(merged.get("preferences_to_add", []) + entities.add_categories))
    if entities.remove_categories:
        merged["preferences_to_reduce"] = list(dict.fromkeys(merged.get("preferences_to_reduce", []) + entities.remove_categories))
    return merged


def requires_research(entities: TravelIntentEntities, state_patch: Dict[str, Any], primary_intent: str) -> bool:
    return bool(
        entities.add_categories
        or state_patch.get("preferences_to_add")
        or state_patch.get("trigger_more_research")
        or primary_intent == "REQUEST_MORE_OPTIONS"
    )


def requires_replanning(operation: str, target: str) -> bool:
    # "REGION" was missing here entirely -- a REGION_REPLACEMENT intent
    # (target=REGION) never reached PlannerAgent without this, regardless of
    # how correctly everything upstream parsed it. This is the actual root
    # cause of the region-swap "misrouting" bug, not just the extraction gaps.
    return operation in {"ADD", "REMOVE", "REPLACE", "MOVE", "REPLAN"} and target in {
        "ACTIVITY", "DAY_PLAN", "FULL_ITINERARY", "REGION",
    }


def infer_next_agents(task_type: str, needs_research: bool, needs_replanning: bool, state_patch: Dict[str, Any]) -> List[str]:
    if task_type == "INFORMATION_QUERY":
        return []
    agents: List[str] = []
    if any(
        state_patch.get(k)
        for k in ("preferences_to_add", "preferences_to_reduce", "daily_attraction_count_delta", "prefer_cheap", "prefer_niche", "transport_preference")
    ):
        agents.append("RequirementAgent")
    if needs_research:
        agents.append("ResearchOrchestrator")
    if needs_replanning:
        agents.append("PlannerAgent")
    if task_type in ("PLAN_MODIFICATION", "PLAN_CONFIRMATION", "OPTION_DISCOVERY", "TRIP_CREATION"):
        agents.append("PresentationAgent")
    return list(dict.fromkeys(agents))


def default_execution_plan(next_agents: List[str], target: str) -> List[str]:
    steps: List[str] = []
    for agent in next_agents:
        if agent == "PlannerAgent":
            steps.append("REPLAN_PARTIAL_DAY" if target in ("DAY_PLAN", "REGION") else "APPLY_PLAN_CHANGE")
        else:
            steps.append(_AGENTS_WITH_STEP_LABELS.get(agent, agent))
    return steps


def build_clarification_question(primary_intent: str, entities: TravelIntentEntities) -> str:
    cats = entities.add_categories or entities.remove_categories
    if entities.day_index and cats:
        cats_label = "、".join(cats)
        return f"你是想在第{entities.day_index}天额外增加{cats_label}，还是用它替换当前已有的相关安排？"
    if cats:
        cats_label = "、".join(cats)
        return f"你是想额外增加{cats_label}，还是替换掉某个已有的安排？"
    return "能否再具体说明一下您想如何调整这部分安排？比如是增加、替换，还是重新安排某一天？"


def build_fast_result(pattern: PatternResult, context: IntentContext) -> Optional[IntentResult]:
    """Fast Path assembly: Pattern + Workflow State only. Returns `None` if
    confidence is insufficient or the Workflow Validator rejects it -- the
    caller (interpreter) must escalate to the Deep Path in that case."""
    if not pattern.operation:
        return None

    primary_intent, base_score = pattern_to_intent(pattern, context)
    entities = entities_from_pattern(pattern)
    taxonomy_meta = load_taxonomy().get("intents", {}).get(primary_intent, {})
    task_type = taxonomy_meta.get("task_type", "GENERAL_CONVERSATION")
    operation = pattern.operation
    target = pattern.target or taxonomy_meta.get("target", "FULL_ITINERARY")

    validation = WorkflowStateValidator().validate(entities, task_type, primary_intent, context)
    confidence = max(0.0, base_score - validation.penalty)

    cfg = load_fusion_config()
    if not validation.is_valid or confidence < cfg.fast_path.confidence_threshold:
        return None

    state_patch = merge_category_state_patch({}, entities)
    needs_research = requires_research(entities, state_patch, primary_intent)
    needs_replanning = requires_replanning(operation, target)
    next_agents = infer_next_agents(task_type, needs_research, needs_replanning, state_patch)

    return IntentResult(
        task_type=task_type,
        operation=operation,
        target=target,
        primary_intent=primary_intent,
        secondary_intents=[],
        feedback_types=[],
        rewritten_request=pattern.raw_message,
        entities=entities,
        state_patch=state_patch,
        requires_research=needs_research,
        requires_replanning=needs_replanning,
        interaction_mode="SIDE_QUERY" if validation.is_side_query else "NORMAL_FLOW",
        confidence=round(confidence, 4),
        clarification_required=False,
        clarification_question=None,
        execution_plan=default_execution_plan(next_agents, target),
        next_agents=next_agents,
        preserve_current_state=validation.is_side_query,
        resume_phase=validation.resume_phase,
        evidence={"pattern": pattern.model_dump(), "workflow": validation.model_dump(), "fusion": {"path": "fast"}},
    )


class FusionResolver:
    """Deep Path: weighted fusion of Pattern + Embedding + LLM, gated by
    Workflow State. Never trusts the LLM's self-reported confidence alone --
    see the design doc section 10's list of adjustments folded into
    `weighted` below."""

    def fuse(
        self,
        message: str,
        context: IntentContext,
        pattern: PatternResult,
        embedding: EmbeddingIntentResult,
        llm: Optional[IntentResult],
    ) -> IntentResult:
        cfg = load_fusion_config().intent_fusion
        taxonomy_intents = load_taxonomy().get("intents", {})

        pattern_intent, pattern_score = pattern_to_intent(pattern, context)
        embedding_intent = embedding.intent_candidates[0].intent if embedding.intent_candidates else None
        embedding_score = embedding.intent_candidates[0].score if embedding.intent_candidates else 0.0
        llm_intent = llm.primary_intent if llm else None
        llm_score = llm.confidence if llm else 0.0

        primary_intent = llm_intent or embedding_intent or pattern_intent or "OUT_OF_SCOPE"

        present = [c for c in (pattern_intent, embedding_intent, llm_intent) if c]
        agreement = len(present) >= 2 and len(set(present)) == 1

        # Renormalize by the weight of signals actually PRESENT this turn --
        # otherwise a missing/failed/timed-out LLM branch (llm_weight=0.60,
        # the largest share) silently caps the ceiling every other signal
        # can reach, so a request both Pattern and Embedding agree on
        # confidently would still never clear the confidence gate just
        # because no LLM key is configured. A present signal's own score
        # still has to earn its weight; only the denominator adapts.
        available_weight = cfg.pattern_weight
        raw = pattern_score * cfg.pattern_weight
        if embedding.intent_candidates:
            available_weight += cfg.embedding_weight
            raw += embedding_score * cfg.embedding_weight
        if llm is not None:
            available_weight += cfg.llm_weight
            raw += llm_score * cfg.llm_weight
        weighted = raw / available_weight if available_weight > 0 else 0.0

        if agreement:
            weighted += cfg.agreement_bonus
        if pattern.has_ambiguity and not (llm and llm.confidence >= cfg.high_confidence_threshold):
            weighted -= cfg.ambiguity_penalty

        entities = llm.entities if (llm and llm.entities) else entities_from_pattern(pattern)
        taxonomy_meta = taxonomy_intents.get(primary_intent, {})
        task_type = (llm.task_type if llm else None) or taxonomy_meta.get("task_type", "GENERAL_CONVERSATION")
        operation = (llm.operation if llm else None) or pattern.operation or taxonomy_meta.get("operation", "QUERY")
        target = (llm.target if llm else None) or pattern.target or taxonomy_meta.get("target", "FULL_ITINERARY")

        validation = WorkflowStateValidator().validate(entities, task_type, primary_intent, context)
        weighted = max(0.0, min(weighted - validation.penalty, 0.99))

        feedback_types = list(
            dict.fromkeys(
                (llm.feedback_types if llm else [])
                + [c.feedback_type for c in embedding.feedback_candidates if c.score >= 0.3]
            )
        )
        state_patch = state_patch_from_feedback(feedback_types)
        state_patch = merge_category_state_patch(state_patch, entities)
        if llm and llm.state_patch:
            state_patch.update(llm.state_patch)

        needs_research = requires_research(entities, state_patch, primary_intent) or (llm.requires_research if llm else False)
        needs_replanning = requires_replanning(operation, target) or (llm.requires_replanning if llm else False)

        explicit_review_apply = bool(
            llm
            and llm.confidence >= cfg.high_confidence_threshold
            and not validation.touches_locked_constraint
            and (
                llm.primary_intent in {"AUTO_FIX_BY_REVIEW", "APPLY_REVIEW_FIXES"}
                or llm.state_patch.get("auto_fix_from_review")
                or llm.state_patch.get("auto_apply_review_fixes")
                or llm.state_patch.get("skip_confirmation")
            )
        )

        if validation.is_side_query:
            interaction_mode = "SIDE_QUERY"
        elif explicit_review_apply:
            interaction_mode = "NORMAL_FLOW"
        elif weighted >= cfg.high_confidence_threshold and validation.is_valid:
            interaction_mode = "NORMAL_FLOW"
        elif weighted >= cfg.medium_confidence_threshold:
            interaction_mode = "CONSERVATIVE_EXECUTION"
        else:
            interaction_mode = "CLARIFICATION"

        clarification_required = interaction_mode == "CLARIFICATION"
        clarification_question = (
            (llm.clarification_question if llm and llm.clarification_question else build_clarification_question(primary_intent, entities))
            if clarification_required
            else None
        )

        next_agents = (llm.next_agents if (llm and llm.next_agents) else infer_next_agents(task_type, needs_research, needs_replanning, state_patch))
        # Conservative execution never touches the live plan directly -- it
        # only searches/presents new candidates for the user to react to.
        if interaction_mode == "CONSERVATIVE_EXECUTION":
            next_agents = [a for a in next_agents if a != "PlannerAgent"]
            needs_replanning = False
        execution_plan = (llm.execution_plan if (llm and llm.execution_plan) else default_execution_plan(next_agents, target))

        evidence = {
            "pattern": pattern.model_dump(),
            "embedding": embedding.model_dump(),
            "llm": llm.model_dump() if llm else None,
            "workflow": validation.model_dump(),
            "fusion": {"weighted_score": round(weighted, 4), "agreement": agreement, "path": "deep"},
        }

        return IntentResult(
            task_type=task_type,
            operation=operation,
            target=target,
            primary_intent=primary_intent,
            secondary_intents=(llm.secondary_intents if llm else []),
            feedback_types=feedback_types,
            rewritten_request=(llm.rewritten_request if (llm and llm.rewritten_request) else message),
            entities=entities,
            state_patch=state_patch,
            requires_research=needs_research,
            requires_replanning=needs_replanning,
            interaction_mode=interaction_mode,
            confidence=round(weighted, 4),
            clarification_required=clarification_required,
            clarification_question=clarification_question,
            execution_plan=execution_plan,
            next_agents=next_agents,
            preserve_current_state=validation.is_side_query,
            resume_phase=validation.resume_phase,
            evidence=evidence,
        )
