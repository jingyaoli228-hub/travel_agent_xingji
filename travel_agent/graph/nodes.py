"""LangGraph node functions.

Each node takes the current `AgentState` and returns a partial state update
(a dict merged into the state by LangGraph). Nodes are intentionally thin
wrappers around the agent classes in `travel_agent.agents.*` -- business
logic lives in the agents, orchestration/control-flow lives here and in
`workflow.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from travel_agent.agents.planner_agent import PlannerAgent
from travel_agent.agents.requirement_agent import RequirementAgent
from travel_agent.agents.research_agent import ResearchOrchestratorAgent
from travel_agent.agents.reviewer_agent import ReviewerAgent
from travel_agent.config.llm import get_llm
from travel_agent.config.settings import get_settings
from travel_agent.evaluation.llm_judge import StrictTravelEvaluator
from travel_agent.evaluation.report_generator import generate_notes
from travel_agent.evaluation.revision_router import decide_route, presentation_route
from travel_agent.evaluation.schemas import StrictEvaluationInput, TravelEvaluationResult
from travel_agent.evaluation.constraint_builder import build_constraints
from travel_agent.evaluation.constraint_validator import ConstraintValidator as DeterministicConstraintValidator
from travel_agent.evaluation.planning_loop import build_repair_targets, choose_best, route_metric_attempt
from travel_agent.evaluation.tripcraft_metric_evaluator import TripCraftMetricEvaluator
from travel_agent.schemas.constraints import TravelConstraintSet
from travel_agent.execution import research_jobs
from travel_agent.execution.agent_router import AgentRouter
from travel_agent.execution.execution_planner import ExecutionPlanner
from travel_agent.execution.result_aggregator import AgentResultAggregator
from travel_agent.graph.state import AgentState
from travel_agent.intent.context_builder import IntentContextBuilder
from travel_agent.intent.interpreter import MultiSignalIntentInterpreter
from travel_agent.intent.pattern_parser import PatternParser, STOP_WORDS
from travel_agent.intent.schemas import IntentResult
from travel_agent.memory.context_builder import flatten_profile_statements, rejected_experience_names
from travel_agent.memory.memory_manager import MemoryManager
from travel_agent.memory.schemas import MemoryContext
from travel_agent.schemas.destination import DestinationComplexityAssessment
from travel_agent.schemas.experience import TravelExperience
from travel_agent.schemas.itinerary import BudgetBreakdown, Itinerary, TravelPlan
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.review import ReviewReport
from travel_agent.schemas.travel_requirement import TravelRequirement
from travel_agent.tool_runtime import get_tool_manager
from travel_agent.tools.visa import search_visa_information
from travel_agent.tools.weather import get_weather

_requirement_agent = RequirementAgent()
_research_agent = ResearchOrchestratorAgent()
_planner_agent = PlannerAgent()
_reviewer_agent = ReviewerAgent()
_memory_manager = MemoryManager()
_strict_evaluator = StrictTravelEvaluator()
_constraint_validator = DeterministicConstraintValidator()
_metric_evaluator = TripCraftMetricEvaluator()

_CONFIRM_WORDS = ["确认", "是的", "对的", "可以", "没问题", "ok", "yes", "好的", "对"]
_DENY_WORDS = ["不对", "不是", "错了", "修改", "改一下", "不", "no"]
_AUTO_WORDS = [
    "帮我推荐", "帮我选", "自动", "都可以", "你决定", "随便",
    "自行推荐", "自己推荐", "你来推荐", "你推荐", "你安排", "帮我搞定", "你规划",
]
_REMOVAL_WORDS = ["去掉", "删除", "不要", "移除"]
_INTEREST_PREFERRED_TYPES = {"购物": "shopping", "美食": "food", "人文": "culture", "自然": "nature", "摄影": "photography"}

# -- Stage-3: multi-signal intent pipeline + post-plan feedback loop --------
# Ordinary services/singletons, not a fifth Agent -- AgentRouter dispatches
# to the exact same four agent instances constructed above.
_context_builder = IntentContextBuilder()
_intent_interpreter = MultiSignalIntentInterpreter()
_execution_planner = ExecutionPlanner()
_agent_router = AgentRouter(_requirement_agent, _research_agent, _planner_agent)
_result_aggregator = AgentResultAggregator()
_routing_pattern_parser = PatternParser()


def _req_from_state(state: AgentState) -> TravelRequirement:
    data = state.get("travel_requirement")
    return TravelRequirement(**data) if data else TravelRequirement()


def _research_from_state(state: AgentState) -> ResearchResult:
    data = state.get("research_result")
    return ResearchResult(**data) if data else ResearchResult()


def _itinerary_from_state(state: AgentState) -> Itinerary:
    data = state.get("itinerary")
    return Itinerary(**data) if data else Itinerary()


def _user_id(state: AgentState) -> str:
    return state.get("user_id") or state.get("session_id", "")


def _say(text: str) -> Dict[str, Any]:
    return {"role": "assistant", "content": text}


# ---------------------------------------------------------------------
# Requirement stage
# ---------------------------------------------------------------------
def requirement_agent_node(state: AgentState) -> Dict[str, Any]:
    """Extracts/updates the TravelRequirement from the latest user message."""
    previous = _req_from_state(state)
    user_message = state.get("user_message", "")
    is_brand_new_session = state.get("travel_requirement") is None

    extra: Dict[str, Any] = {}
    profile_hint = state.get("user_profile_hint")
    if is_brand_new_session:
        # Round-6 Phase 5: one unified MemoryContext read (not a separate ad
        # hoc profile lookup) -- stored in state so research_orchestrator_node
        # reads the *same* context rather than querying memory again.
        memory_context = _memory_manager.build_context(
            state.get("session_id", ""), _user_id(state), intent_key="NEW_TRIP", query_text=user_message,
        )
        profile_hint = flatten_profile_statements(memory_context.profile_statements) or None
        extra["user_profile_hint"] = profile_hint
        extra["memory_context"] = memory_context.model_dump()

    result = _requirement_agent.run(user_message, previous, profile_hint=profile_hint)

    if result.is_complete:
        assessment = _requirement_agent.assess_destination_complexity(result.requirement)
        if assessment.is_complex and not result.requirement.region_split_confirmed:
            result.requirement.region_candidates = [r.model_dump() for r in assessment.regions]
            response = assessment.confirmation_message or f"「{result.requirement.destination}」体验差异较大，是否希望按区域安排？"
            stage = "region_confirmation"
            extra["destination_assessment"] = assessment.model_dump()
        else:
            response = (
                f"当前旅行需求总结：{result.summary}\n\n"
                f"已确认信息：{', '.join(result.confirmed_fields) or '无'}\n\n"
                "以上旅行需求是否正确？确认后开始搜索。"
            )
            stage = "confirmation"
    else:
        response = (
            f"当前旅行需求总结：{result.summary}\n\n"
            f"已确认信息：{', '.join(result.confirmed_fields) or '无'}\n\n"
            f"缺失信息：{', '.join(result.missing_fields)}\n\n"
            f"{result.clarification_question}"
        )
        stage = "clarification"

    return {
        **extra,
        "travel_requirement": result.requirement.model_dump(),
        "requirement_summary": result.summary,
        "confirmed_fields": result.confirmed_fields,
        "missing_fields": result.missing_fields,
        "stage": stage,
        "current_node": "requirement_agent",
        "need_user_input": True,
        "pending_response": response,
        "conversation_history": [_say(response)],
    }


def clarification_node(state: AgentState) -> Dict[str, Any]:
    """Incorporates a user's clarifying reply and re-runs extraction."""
    update = requirement_agent_node(state)
    update["current_node"] = "clarification"
    return update


def route_after_requirement(state: AgentState) -> str:
    stage = state.get("stage")
    if stage == "confirmation":
        return "user_confirmation"
    if stage == "region_confirmation":
        return "region_confirmation"
    return "clarification"


# ---------------------------------------------------------------------
# Region confirmation (Stage-2: complex destinations, e.g. Bali)
# ---------------------------------------------------------------------
def region_confirmation_node(state: AgentState) -> Dict[str, Any]:
    """Parses the user's reply to the region-split question, then reuses
    `requirement_agent_node` to produce the normal requirement-confirmation
    summary/question (region_split_confirmed is now True, so it won't loop
    back into this same node)."""
    req = _req_from_state(state)
    message = state.get("user_message", "").strip()
    assessment_data = state.get("destination_assessment")
    assessment = (
        DestinationComplexityAssessment(**assessment_data)
        if assessment_data
        else _requirement_agent.assess_destination_complexity(req)
    )

    regions = _requirement_agent.parse_region_selection(message, assessment)
    req.region_preferences = regions
    req.region_split_confirmed = True
    region_note = f"已为您安排区域：{'、'.join(regions)}。" if regions else "将不按区域拆分，整体安排行程。"

    pseudo_state: AgentState = {**state, "travel_requirement": req.model_dump(), "user_message": ""}
    update = requirement_agent_node(pseudo_state)
    update["current_node"] = "region_confirmation"
    update["pending_response"] = region_note + "\n\n" + update["pending_response"]
    update["conversation_history"] = [_say(update["pending_response"])]
    return update


def route_after_region_confirmation(state: AgentState) -> str:
    return "user_confirmation" if state.get("stage") == "confirmation" else "clarification"


# ---------------------------------------------------------------------
# Requirement confirmation
# ---------------------------------------------------------------------
def user_confirmation_node(state: AgentState) -> Dict[str, Any]:
    """Handles the user's reply to 'is this requirement correct?'."""
    message = state.get("user_message", "").strip()
    lower = message.lower()

    if any(w in message or w in lower for w in _CONFIRM_WORDS) and not any(w in message for w in _DENY_WORDS):
        req = _req_from_state(state)
        req.confirmed = True
        history = state.get("conversation_history") or []
        original_request = history[0].get("content", "") if history else state.get("user_message", "")
        _memory_manager.update_memory(
            state.get("session_id", ""), _user_id(state),
            original_request=original_request, confirmed_requirement=req.model_dump(),
        )
        response = "需求已确认，正在为您搜索目的地信息、体验与餐厅，请稍候..."
        return {
            "travel_requirement": req.model_dump(),
            "stage": "research",
            "research_mode": "initial",
            "current_node": "user_confirmation",
            "need_user_input": False,
            "pending_response": response,
            "conversation_history": [_say(response)],
        }

    # Treat as a correction: feed the message back through the requirement
    # extractor, while handling removals/replacements of an already-confirmed
    # region split explicitly. Incremental LLM list patches are additive by
    # design and therefore cannot represent "不要台场" on their own.
    corrected_regions = None
    req = _req_from_state(state)
    assessment_data = state.get("destination_assessment")
    if req.region_split_confirmed and assessment_data:
        assessment = DestinationComplexityAssessment(**assessment_data)
        parsed_regions = _requirement_agent.parse_region_correction(
            message, req.region_preferences, assessment
        )
        if parsed_regions != req.region_preferences:
            corrected_regions = parsed_regions
            req.region_preferences = parsed_regions

    correction_state = (
        {**state, "travel_requirement": req.model_dump()}
        if corrected_regions is not None
        else state
    )
    update = requirement_agent_node(correction_state)
    if corrected_regions is not None:
        updated_req = TravelRequirement(**update["travel_requirement"])
        updated_req.region_preferences = corrected_regions
        updated_req.region_split_confirmed = True
        update["travel_requirement"] = updated_req.model_dump()
        corrected_summary = _requirement_agent._build_summary(updated_req)
        update["requirement_summary"] = corrected_summary
        update["confirmed_fields"] = updated_req.confirmed_field_names()
        update["missing_fields"] = updated_req.missing_required_fields()
        if update.get("stage") == "confirmation":
            response = (
                f"当前旅行需求总结：{corrected_summary}\n\n"
                f"已确认信息：{', '.join(update['confirmed_fields']) or '无'}\n\n"
                "以上旅行需求是否正确？确认后开始搜索。"
            )
            update["pending_response"] = response
            update["conversation_history"] = [_say(response)]
    update["current_node"] = "user_confirmation"
    return update


def route_after_confirmation(state: AgentState) -> str:
    if state.get("stage") == "research":
        return "research_orchestrator"
    return "user_confirmation" if state.get("stage") == "confirmation" else "clarification"


# ---------------------------------------------------------------------
# Research stage
# ---------------------------------------------------------------------
def _memory_context_from_state(state: AgentState) -> MemoryContext:
    """Round-6 Phase 5: read the MemoryContext `requirement_agent_node`
    already built for this turn when present, instead of querying memory
    again -- only builds fresh if this node runs without one already in
    state (e.g. a background expansion pass, or a direct test call)."""
    data = state.get("memory_context")
    if data:
        return MemoryContext(**data)
    return _memory_manager.build_context(
        state.get("session_id", ""), _user_id(state), intent_key="REPLAN", query_text=state.get("user_message", ""),
    )


def research_orchestrator_node(state: AgentState) -> Dict[str, Any]:
    req = _req_from_state(state)
    mode = state.get("research_mode", "initial")
    # Stage-4: looked up by session_id (not LangGraph config injection, so
    # this doesn't depend on the installed LangGraph version's node-signature
    # introspection) -- `None` when this node runs outside the background-job
    # dispatcher (e.g. directly in a test), which every agent method treats as
    # "no progress reporting", not an error.
    progress_cb = research_jobs.get_progress_callback(state.get("session_id", ""))
    memory_context = _memory_context_from_state(state)
    rejected_names = rejected_experience_names(memory_context.episodic)

    if mode == "expansion":
        existing = _research_from_state(state)
        missing_categories = (state.get("plan_feasibility") or {}).get("missing_categories") or []
        result = _research_agent.run_expansion(
            req, existing, missing_categories, progress_cb=progress_cb, extra_exclude=rejected_names,
        )

        selected = state.get("selected_places") or {"experiences": []}
        days = req.duration_days or 5
        daily_count = req.daily_attraction_count or 3
        target_total = max(daily_count * days, 3) + max(days + 1, 2)
        # Bug fix (found while testing an unrelated change, confirmed live):
        # `result.experiences` is `existing.experiences + newly_found`, i.e.
        # the *whole* pool, not just what this expansion pass added. Passing
        # the whole pool to `auto_select_additional` (which treats its second
        # argument as "candidates to consider adding") let it re-add
        # something the user had explicitly removed a turn earlier -- the
        # removal only ever touched `selected_places`, never `research_
        # result`, so a since-removed item was always still sitting in
        # `existing.experiences`, waiting to be picked "fresh" the next time
        # expansion ran low on selected items. Diffing against `existing`
        # here restricts `auto_select_additional` to genuinely new finds.
        already_known_names = {e.name for e in existing.experiences}
        newly_found = [e for e in result.experiences if e.name not in already_known_names]
        new_selected = _research_agent.auto_select_additional(
            selected.get("experiences", []), newly_found, target_total
        )
        return {
            "research_result": result.model_dump(),
            "selected_places": {"experiences": new_selected},
            "expansion_loop_count": state.get("expansion_loop_count", 0) + 1,
            "current_node": "research_orchestrator",
            "need_user_input": False,
            "research_feedback_topics": None,
            "auto_select_after_feedback": False,
        }

    if mode == "feedback" and state.get("research_feedback_message"):
        result = _research_agent.run_feedback(
            req, _research_from_state(state), state["research_feedback_message"], progress_cb=progress_cb,
            extra_exclude=rejected_names, preferred_topics=state.get("research_feedback_topics"),
        )
        update: Dict[str, Any] = {
            "research_result": result.model_dump(),
            "research_feedback_message": None,
            "research_feedback_topics": None,
            "current_node": "research_orchestrator",
            "need_user_input": False,
            "auto_select_after_feedback": False,
        }
        if state.get("auto_select_after_feedback"):
            # Round-6: "你帮我自行推荐吧，我要瑜伽/浮潜/..." -- the user already
            # said "you decide" alongside naming topics, so once the
            # topic-scoped research above comes back, auto-select from it and
            # go straight to planning instead of pausing to show candidates
            # again (`route_after_research` below routes on this same mode
            # marker to skip `recommendation`/`user_selection` entirely,
            # exactly like the "expansion" branch above already does).
            candidates = _research_agent.build_candidates(result)
            daily_count, days = req.daily_attraction_count or 3, req.duration_days or 5
            preferred = list(req.experience_preferences or []) + [
                _INTEREST_PREFERRED_TYPES[i] for i in (req.interests or []) if i in _INTEREST_PREFERRED_TYPES
            ]
            selected = _research_agent.auto_select(candidates, daily_count, days, preferred_types=preferred)
            update["candidates"] = candidates
            update["selected_places"] = selected
            update["research_mode"] = "feedback_auto_select"
        return update

    result = _research_agent.run_full(
        req, progress_cb=progress_cb, extra_exclude=rejected_names, memory_context=memory_context,
    )
    if not result.experiences:
        # A pass with zero place candidates is not a successful research
        # result.  Treating it as "done" previously surfaced an empty
        # selection screen and let Planner loop for minutes against an empty
        # pool. Raising here gives RQ its bounded retries and ultimately a
        # durable, user-visible error instead of a false success.
        raise RuntimeError(
            "实时地点调研未返回任何候选；请检查高德 Web 服务网络连通性、API 权限与配额。海外目的地不在普通高德 Key 覆盖范围。"
        )
    return {
        "research_result": result.model_dump(),
        "research_feedback_message": None,
        "research_feedback_topics": None,
        "current_node": "research_orchestrator",
        "need_user_input": False,
        "auto_select_after_feedback": False,
    }


def route_after_research(state: AgentState) -> str:
    return "planner" if state.get("research_mode") in ("expansion", "feedback_auto_select") else "recommendation"


# ---------------------------------------------------------------------
# Candidate presentation stage
# ---------------------------------------------------------------------
def recommendation_node(state: AgentState) -> Dict[str, Any]:
    research = _research_from_state(state)
    candidates = _research_agent.build_candidates(research)
    message = _research_agent.build_summary_message(candidates)
    if research.warnings:
        message += "\n\n⚠ 数据可用性：\n" + "\n".join(f"- {warning}" for warning in research.warnings)

    return {
        "candidates": candidates,
        "stage": "selection",
        "current_node": "user_selection",
        "need_user_input": True,
        "pending_response": message,
        "conversation_history": [_say(message)],
    }


def _extract_mentioned_names(message: str, all_items: List[dict]) -> List[dict]:
    return [item for item in all_items if item["name"] in message]


def user_selection_node(state: AgentState) -> Dict[str, Any]:
    """Handles selection AND the Research Feedback Loop: any reply that isn't
    a recognizable selection/removal/auto-pick is forwarded to the Research
    Orchestrator as free-text feedback for it to interpret.

    Round-6: a message like "你帮我自行推荐吧，我要瑜伽，跳舞，浮潜，冲浪，spa，
    看日落" carries TWO signals at once -- "proceed with an auto-pick"
    (`is_auto`) AND "bias what you pick toward these specific activity
    types" (`preferred_topics`). The old version only ever recognized one
    branch per message, so a combined message like this fell through to the
    free-text-feedback branch, where `parse_feedback_intent`'s single-
    category heuristic kept only the *first* matching category and searched
    for just that one -- from the user's side, indistinguishable from
    "nothing changed, same attractions again".

    `preferred_topics` reuses `rag/query_rewriter.py`'s heuristic positive-
    preference extraction (same `topic_vocab.py` table RAG retrieval already
    uses). Finding topics does NOT search Google Places right here -- that
    would block this node on real network calls outside the background-job
    path Stage-4 built specifically so research never blocks the request
    thread (see `execution/research_jobs.py`). Instead this routes through
    `research_orchestrator` exactly like the pre-existing free-text-feedback
    path already did, carrying the parsed topics (`research_feedback_topics`)
    and the auto-pick signal (`auto_select_after_feedback`) as state so
    `research_orchestrator_node` can act on them once the (still
    async/background) research actually runs.
    """
    message = state.get("user_message", "").strip()
    req = _req_from_state(state)
    candidates = state.get("candidates") or {"experiences": {}}
    all_experiences = [i for items in candidates.get("experiences", {}).values() for i in items]

    is_auto = any(w in message for w in _AUTO_WORDS) or not message
    is_removal = any(w in message for w in _REMOVAL_WORDS)
    mentioned = _extract_mentioned_names(message, all_experiences)

    preferred_topics: List[str] = []
    if message and not (is_removal or mentioned):
        from travel_agent.rag.query_rewriter import rewrite_query

        preferred_topics = rewrite_query(message, travel_requirement=req).positive_preferences

    if preferred_topics:
        return {
            "research_feedback_message": message,
            "research_feedback_topics": preferred_topics,
            "research_mode": "feedback",
            "auto_select_after_feedback": is_auto,
            "stage": "selection",
            "current_node": "research_orchestrator",
            "need_user_input": False,
        }

    if not (is_auto or is_removal or mentioned):
        return {
            "research_feedback_message": message,
            "research_mode": "feedback",
            "stage": "selection",
            "current_node": "research_orchestrator",
            "need_user_input": False,
        }

    daily_count, days = req.daily_attraction_count or 3, req.duration_days or 5
    preferred = list(req.experience_preferences or []) + [
        _INTEREST_PREFERRED_TYPES[i] for i in (req.interests or []) if i in _INTEREST_PREFERRED_TYPES
    ]
    if is_auto:
        selected = _research_agent.auto_select(candidates, daily_count, days, preferred_types=preferred)
    elif is_removal:
        base = _research_agent.auto_select(candidates, daily_count, days, preferred_types=preferred)
        removed_names = {i["name"] for i in mentioned}
        selected = {"experiences": [e for e in base["experiences"] if e["name"] not in removed_names]}
    else:
        selected = {"experiences": mentioned}

    response = f"已为您选定 {len(selected['experiences'])} 项体验，正在生成每日行程..."
    return {
        "selected_places": selected,
        "stage": "planning",
        "current_node": "user_selection",
        "need_user_input": False,
        "pending_response": response,
        "conversation_history": [_say(response)],
    }


def route_after_selection(state: AgentState) -> str:
    return "research_orchestrator" if state.get("current_node") == "research_orchestrator" else "planner"


def constraint_builder_node(state: AgentState) -> Dict[str, Any]:
    constraints = build_constraints(state.get("travel_requirement") or {}, state.get("user_profile_hint") or {})
    return {"travel_constraints": constraints.model_dump(), "current_node": "constraint_builder"}


# ---------------------------------------------------------------------
# Planning stage (Hierarchical Planner + feasibility/expansion loop)
# ---------------------------------------------------------------------
def planner_node(state: AgentState) -> Dict[str, Any]:
    req = _req_from_state(state)
    research = _research_from_state(state)
    selected = state.get("selected_places") or {"experiences": []}

    review_report_data = state.get("review_report")
    revision_instruction = review_report_data.get("revision_instruction") if review_report_data else None
    rule_issues = review_report_data.get("issues") if review_report_data else None
    loop_count = state.get("review_loop_count", 0)
    profile_hint = state.get("user_profile_hint")
    # Stage-3 fix (design doc point 21): on a review-loop revision, optimize
    # the PREVIOUS itinerary rather than regenerating the whole trip from the
    # original pool every loop -- see PlannerAgent.run's docstring.
    previous_itinerary = _itinerary_from_state(state) if state.get("itinerary") else None

    repair_targets = state.get("repair_targets") or []
    target_days = sorted({int(target["day"]) for target in repair_targets if target.get("day")})
    if previous_itinerary is not None and target_days:
        itinerary = _planner_agent.run_partial(
            req, previous_itinerary, research, selected, target_days, profile_hint=profile_hint,
        )
        feasibility = _planner_agent.check_feasibility(req, list(selected.get("experiences", [])))
    else:
        revision_instruction = revision_instruction or [target.get("problem", "") for target in repair_targets]
        rule_issues = rule_issues or [target.get("problem", "") for target in repair_targets]
        itinerary, feasibility = _planner_agent.run(
            req, selected, research, revision_instruction=revision_instruction, rule_issues=rule_issues,
            loop_count=loop_count, profile_hint=profile_hint, previous_itinerary=previous_itinerary,
        )

    settings = get_settings()
    needs_expansion = (
        feasibility.status == "insufficient"
        and state.get("expansion_loop_count", 0) < settings.max_research_expansion_loops
    )

    update: Dict[str, Any] = {
        "plan_feasibility": feasibility.model_dump(),
        "stage": "planning",
        "current_node": "planner",
        "need_user_input": False,
        "planner_attempt": int(state.get("planner_attempt", 0)) + 1,
    }
    if needs_expansion:
        update["research_mode"] = "expansion"
    else:
        update["itinerary"] = itinerary.model_dump()
    return update


def route_after_planner(state: AgentState) -> str:
    feasibility = state.get("plan_feasibility") or {}
    settings = get_settings()
    if feasibility.get("status") == "insufficient" and state.get("expansion_loop_count", 0) < settings.max_research_expansion_loops:
        return "research_orchestrator"
    return "validator"


# ---------------------------------------------------------------------
# Review stage
# ---------------------------------------------------------------------
def validator_node(state: AgentState) -> Dict[str, Any]:
    itinerary = _itinerary_from_state(state)
    constraints = TravelConstraintSet(**(state.get("travel_constraints") or build_constraints(state.get("travel_requirement") or {}).model_dump()))
    report = _constraint_validator.validate(itinerary, constraints)
    violations = [v.model_dump() for v in [*report.hard_violations, *report.commonsense_violations]]
    return {"constraint_validation": report.model_dump(), "constraint_violations": violations,
            "rule_issues": [v["message"] for v in violations], "needs_constraint_relaxation": report.needs_constraint_relaxation,
            "current_node": "constraint_validator"}


def tripcraft_metric_evaluator_node(state: AgentState) -> Dict[str, Any]:
    itinerary = _itinerary_from_state(state)
    constraints = TravelConstraintSet(**(state.get("travel_constraints") or {}))
    validation = _constraint_validator.validate(itinerary, constraints)
    report_data = _metric_evaluator.evaluate(itinerary, constraints.persona.model_dump(), validation).model_dump()
    best_plan, best_report = choose_best(state.get("itinerary") or {}, report_data, state.get("best_plan"), state.get("best_metric_report"))
    return {"metric_report": report_data, "metric_history": [*(state.get("metric_history") or []), report_data],
            "best_plan": best_plan, "best_metric_report": best_report, "repair_targets": build_repair_targets(report_data),
            "current_node": "tripcraft_metric_evaluator"}


def route_after_metric_evaluator(state: AgentState) -> str:
    return route_metric_attempt(state)


def constraint_relaxation_node(state: AgentState) -> Dict[str, Any]:
    report = state.get("metric_report") or {}
    conflicts = [v.get("message", "") for v in report.get("hard_violations") or []]
    response = {"status": "NEEDS_CONSTRAINT_RELAXATION", "conflicts": conflicts,
                "relaxation_options": [f"请明确是否放宽：{v.get('code')}" for v in report.get("hard_violations") or []]}
    return {"stage": "clarification", "need_user_input": True, "pending_response": str(response),
            "needs_constraint_relaxation": True, "current_node": "constraint_relaxation"}


def reviewer_node(state: AgentState) -> Dict[str, Any]:
    settings = get_settings()
    itinerary = _itinerary_from_state(state)
    req = _req_from_state(state)
    research = _research_from_state(state)
    rule_issues = state.get("rule_issues", [])
    loop_count = state.get("review_loop_count", 0)

    report = _reviewer_agent.review(itinerary, req, research, loop_count, rule_issues=rule_issues)

    if not report.passed and loop_count + 1 >= settings.max_review_loops:
        report.issues.append(f"已达到最大评审循环次数({settings.max_review_loops})，采用当前最优版本。")

    return {
        "review_report": report.model_dump(),
        "review_loop_count": loop_count + 1,
        "current_node": "reviewer",
        "need_user_input": False,
    }


def route_after_reviewer(state: AgentState) -> str:
    report = state.get("review_report") or {}
    settings = get_settings()
    if report.get("passed") or state.get("review_loop_count", 0) >= settings.max_review_loops:
        return "strict_evaluation"
    return "planner"


# ---------------------------------------------------------------------
# Round-6 Phase 6: Strict Evaluation
# ---------------------------------------------------------------------
def strict_evaluation_node(state: AgentState) -> Dict[str, Any]:
    """Deeper, 8-dimension gate than `reviewer_node`'s 5-dim quick pass --
    runs once the reviewer has already passed the itinerary, with full
    context (`MemoryContext`, research candidates, tool evidence) the
    reviewer never sees. `revision_round` is this node's *own* loop counter
    (see `graph/state.py`) -- deliberately separate from `review_loop_count`,
    since the two gates check different things and shouldn't share a budget:
    a plan can pass the reviewer's time/route/budget/richness/preference
    rubric on the first try yet still fail here on profile alignment or a
    hard penalty (repeated-rejected content, a schedule conflict), and vice
    versa after a revision.
    """
    req = _req_from_state(state)
    research = _research_from_state(state)
    itinerary = _itinerary_from_state(state)
    selected = state.get("selected_places") or {"experiences": []}

    memory_data = state.get("memory_context")
    memory_context = MemoryContext(**memory_data) if memory_data else None
    history = state.get("conversation_history") or []
    user_request = history[0].get("content", "") if history else state.get("user_message", "")

    evaluation_input = StrictEvaluationInput(
        user_request=user_request,
        travel_requirement=req.model_dump(),
        user_profile=flatten_profile_statements(memory_context.profile_statements) if memory_context else {},
        episodic_memories=[e.model_dump() for e in (memory_context.episodic if memory_context else [])],
        candidate_activities=selected.get("experiences", []),
        final_itinerary=itinerary.model_dump(),
        tool_evidence=[s.model_dump() for s in research.all_sources()],
        user_feedback=state.get("research_feedback_message") or "",
    )

    llm = get_llm(role="reviewer", tier="fast")
    result = _strict_evaluator.evaluate(evaluation_input, llm=llm)

    update: Dict[str, Any] = {
        "strict_evaluation": result.model_dump(),
        "revision_round": state.get("revision_round", 0) + 1,
        "current_node": "strict_evaluation",
    }
    if result.improvement_actions:
        review_data = dict(state.get("review_report") or {})
        review_data["revision_instruction"] = list(result.improvement_actions)
        update["review_report"] = review_data
    return update


def route_after_strict_evaluation(state: AgentState) -> str:
    result_data = state.get("strict_evaluation") or {}
    result = TravelEvaluationResult(**result_data)
    return decide_route(result, state.get("revision_round", 0))


# ---------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------
def final_output_node(state: AgentState) -> Dict[str, Any]:
    req = _req_from_state(state)
    research = _research_from_state(state)
    itinerary = _itinerary_from_state(state)
    review_data = state.get("review_report") or {}
    report = ReviewReport(**review_data) if review_data else None
    selected = state.get("selected_places") or {"experiences": []}

    total_attraction_cost = sum(
        i.estimated_cost for d in itinerary.days for i in d.items if i.activity == "attraction"
    )
    total_food_cost = sum(
        i.estimated_cost for d in itinerary.days for i in d.items if i.activity in ("breakfast", "lunch", "dinner")
    )
    total_transport_cost = sum(t.cost for t in research.transportation)
    flight_cost = sum(f.price for f in research.flights)
    hotel_cost = ((research.hotels[0].price_per_night or 0) if research.hotels else 0) * (req.duration_days or 1)
    total = flight_cost + hotel_cost + total_attraction_cost + total_food_cost + total_transport_cost

    budget = BudgetBreakdown(
        flights=flight_cost, hotels=hotel_cost, attractions=total_attraction_cost,
        food=total_food_cost, transport=total_transport_cost,
        shopping_buffer=max((req.budget or 0) - total, 0),
        total=total, currency=req.budget_currency,
    )

    overview = (
        f"{req.destination} {req.duration_days}天{req.num_travelers}人行程 · "
        f"节奏：{req.pace} · 预算：{req.budget:.0f}{req.budget_currency}"
        + (f"（评审得分 {report.score}/100）" if report else "")
    )

    route_summary = " → ".join(
        dict.fromkeys(
            [it.location.split(" (")[0] for d in itinerary.days for it in d.items if it.activity == "attraction"]
        )
    )

    notes = [
        f"目的地天气：{research.weather.summary}" if research.weather else "",
        f"签证提示：{research.visa_info.notes}" if research.visa_info else "",
        "境内体验/餐厅/交通时长来自高德地点与路线真实数据；机票/酒店价格与签证信息暂无对接的"
        "真实 API，为规则估算，实际请以预订平台/官方信息为准。",
    ]
    notes = [n for n in notes if n] + list(research.warnings)

    _TRANSPORT_MODE_LABELS = {"WALK": "步行", "TRANSIT": "公共交通", "DRIVE": "驾车"}
    transport_suggestions = [
        f"机场-市区推荐交通方式：{_TRANSPORT_MODE_LABELS.get(research.transportation[0].mode.upper(), research.transportation[0].mode)}，"
        f"约{research.transportation[0].duration_minutes}分钟"
    ] if research.transportation else []

    plan = TravelPlan(
        overview=overview,
        itinerary=itinerary,
        map_route_summary=route_summary or "行程地点集中，建议按行程顺序步行/地铁前往。",
        budget=budget,
        hotel_suggestions=research.hotels,
        transport_suggestions=transport_suggestions,
        notes=notes,
        sources=research.all_sources(),
    )

    # L2 (episode) + L3 (profile) memory writes -- makes the next trip smarter.
    profile_fields = _memory_manager.extract_user_preference(
        req, selected_experiences=selected.get("experiences", []),
        hotel=research.hotels[0].model_dump() if research.hotels else None,
        review_feedback=report.issues if report else None,
    )
    episode = {
        "user_id": _user_id(state),
        "session_id": state.get("session_id", ""),
        "destination": req.destination or "",
        "selected_experiences": selected.get("experiences", []),
        "final_plan_summary": {"overview": overview, "score": report.score if report else None},
        "feedback": report.issues if report else [],
        "budget_difference": (req.budget or 0) - total,
        "tags": list(dict.fromkeys((req.interests or []) + (req.experience_preferences or []))),
    }
    _memory_manager.update_memory(
        state.get("session_id", ""), _user_id(state), episode=episode, profile_fields=profile_fields,
    )

    # P0 copy rule: a draft that did not pass review must never claim that
    # planning is complete. The UI and conversation history use the same text.
    opening = f"行程规划完成！{overview}" if not report or report.passed else f"行程草稿已生成（质量未达标）：{overview}"
    response_lines = [opening, "", "== 每日安排 =="]
    for day in itinerary.days:
        region_label = f"（{day.items[0].region}）" if day.items and day.items[0].region else ""
        response_lines.append(f"Day {day.day_number}{region_label}:")
        for item in day.items:
            response_lines.append(f"  {item.time} {item.activity} - {item.location}")
    response_lines.append("")
    response_lines.append(f"预估总花费：{budget.total:.0f} {budget.currency}（预算 {req.budget:.0f}）")

    if research.warnings:
        response_lines.extend(["", "⚠ 数据可用性：", *[f"- {warning}" for warning in research.warnings]])

    # Round-6 Phase 6: score >= pass_threshold (80) shows nothing extra --
    # anything the revision loop couldn't push past notes_threshold (65)
    # within its round budget still gets presented (never blocks the user),
    # but with the strict evaluator's own explanation of what's weak,
    # instead of silently showing a plan that scored in the "notes" band.
    strict_data = state.get("strict_evaluation")
    if strict_data and presentation_route(TravelEvaluationResult(**strict_data)) == "final_output_with_notes":
        response_lines.append("")
        response_lines.append(generate_notes(TravelEvaluationResult(**strict_data)))

    response = "\n".join(response_lines)

    return {
        "final_plan": plan.model_dump(),
        "stage": "done",
        "current_node": "final_output",
        "need_user_input": False,
        "pending_response": response,
        "conversation_history": [_say(response)],
    }


# ---------------------------------------------------------------------
# Stage-3: post-plan feedback loop.
#
#   final_output -> post_plan_feedback (interrupt_before -- pauses here,
#       reporting final_output's own need_user_input=False/stage=done for
#       *this* turn, exactly as before this upgrade) -> [next user message] ->
#   post_plan_feedback -[stop phrase?]-> close_out -> post_plan_feedback (loop)
#                       -[else]-> intent_interpreter
#   intent_interpreter -[SIDE_QUERY]-> side_query -> post_plan_feedback (loop)
#                      -[CLARIFICATION]-> clarify_post_plan -> post_plan_feedback (loop)
#                      -[else]-> execution_router -> result_aggregation -> post_plan_feedback (loop)
#
# Every path loops back to the single `post_plan_feedback` interrupt point,
# so the graph never truly reaches END after the first plan -- it just keeps
# listening for more feedback, indefinitely, exactly like a real agent that
# hasn't forgotten the conversation is still open.
# ---------------------------------------------------------------------
def post_plan_feedback_node(state: AgentState) -> Dict[str, Any]:
    """Waits at the interrupt boundary for the user's reaction to the plan.
    `interrupt_before` pauses execution right before this node runs, so the
    very first arrival here (immediately after final_output) never executes
    this body at all -- the API layer sees final_output's own state. Only a
    *resumed* call (a new message arrived) actually runs it."""
    return {"current_node": "post_plan_feedback", "stage": "post_plan_feedback"}


def route_after_post_plan_feedback(state: AgentState) -> str:
    message = (state.get("user_message") or "").strip()
    if any(w in message for w in STOP_WORDS):
        return "close_out"
    if _routing_pattern_parser.parse(message).is_confirm:
        return "close_out"
    return "intent_interpreter"


def close_out_node(state: AgentState) -> Dict[str, Any]:
    response = "好的，行程已确认，祝您旅途愉快！之后如果还想调整，随时可以告诉我。"
    return {
        "stage": "done",
        "current_node": "close_out",
        "need_user_input": False,
        "pending_response": response,
        "conversation_history": [_say(response)],
    }


def intent_interpreter_node(state: AgentState) -> Dict[str, Any]:
    """MultiSignalIntentInterpreter entry point (design doc section II/V/VI).
    Ordinary workflow node, not an Agent -- it only produces an `IntentResult`
    for `execution_router_node` to act on."""
    context = _context_builder.build(state)
    result = _intent_interpreter.interpret(state.get("user_message", ""), context)
    return {
        "intent_result": result.model_dump(),
        "current_node": "intent_interpreter",
        "need_user_input": False,
    }


def route_after_intent_interpreter(state: AgentState) -> str:
    mode = (state.get("intent_result") or {}).get("interaction_mode")
    if mode == "CLARIFICATION":
        return "clarify_post_plan"
    if mode == "SIDE_QUERY":
        return "side_query"
    return "execution_router"


def clarify_post_plan_node(state: AgentState) -> Dict[str, Any]:
    intent_data = state.get("intent_result") or {}
    question = intent_data.get("clarification_question") or "能否再具体说明一下您想如何调整这部分安排？"
    return {
        "stage": "post_plan_feedback",
        "current_node": "clarify_post_plan",
        "need_user_input": True,
        "pending_response": question,
        "conversation_history": [_say(question)],
    }


def _answer_side_query(intent_data: Dict[str, Any], req: TravelRequirement) -> str:
    primary = intent_data.get("primary_intent")
    if primary == "QUERY_WEATHER":
        result = get_tool_manager().call(
            get_weather,
            {"destination": req.destination, "travel_date": datetime.now().date().isoformat()},
            tool_name="weather.get_weather",
        )
        if result.get("success", True):
            return (
                f"{req.destination} 天气：{result['weather']}，{result['temperature']}，" +
                (f"降雨概率 {result['rain_probability']}%。" if result.get('rain_probability') is not None else "高德未提供降雨概率。")
                + result.get('recommendation', '')
            )
        return f"暂时无法获取「{req.destination}」的实时天气，建议出发前再查询。"
    if primary == "QUERY_VISA":
        result = get_tool_manager().call(
            search_visa_information,
            {"passport_country": req.passport_country or "中国", "destination": req.destination},
            tool_name="visa.search_visa_information",
        )
        return result.get("notes") or "暂无签证信息，请以官方渠道信息为准。"
    if primary == "QUERY_TRANSPORT":
        return "交通方式请参考行程中已安排的具体路线；如需更详细的建议，请告诉我具体的出发地和目的地。"
    return "这个问题我暂时无法直接回答，建议出发前再确认。"


def side_query_node(state: AgentState) -> Dict[str, Any]:
    """Answers a weather/visa/transport question inline WITHOUT disturbing
    the current plan/state -- `preserve_current_state`/`resume_phase` on the
    IntentResult are exactly why this stays a dead-end back to
    `post_plan_feedback` instead of touching the itinerary."""
    intent_data = state.get("intent_result") or {}
    req = _req_from_state(state)
    answer = _answer_side_query(intent_data, req)
    return {
        "stage": "post_plan_feedback",
        "current_node": "side_query",
        "need_user_input": True,
        "pending_response": answer,
        "conversation_history": [_say(answer)],
    }


def execution_router_node(state: AgentState) -> Dict[str, Any]:
    """Design doc section XIII: `ExecutionPlanner` + `AgentRouter` -- routes
    the fused intent through whichever of the four existing agents it needs
    (Requirement/Research/Planner), in order."""
    intent_data = state.get("intent_result") or {}
    intent = IntentResult(**intent_data)
    context = _context_builder.build(state)
    plan = _execution_planner.plan(intent, context)

    requirement_before = _req_from_state(state)
    research = _research_from_state(state)
    selected = state.get("selected_places") or {"experiences": []}
    previous_itinerary = _itinerary_from_state(state) if state.get("itinerary") else None
    profile_hint = state.get("user_profile_hint")

    requirement_after, research, selected, itinerary, new_candidates, step_results = _agent_router.run(
        plan, intent, requirement_before, research, selected, previous_itinerary, profile_hint=profile_hint,
    )

    aggregated = _result_aggregator.aggregate(
        intent, step_results, requirement_before, requirement_after,
        previous_itinerary, itinerary, new_candidates, context.trace_id,
    )

    return {
        "travel_requirement": requirement_after.model_dump(),
        "research_result": research.model_dump(),
        "selected_places": selected,
        "itinerary": itinerary.model_dump() if itinerary else state.get("itinerary"),
        "aggregated_result": aggregated.model_dump(),
        "current_node": "execution_router",
        "need_user_input": False,
    }


def route_after_execution_router(state: AgentState) -> str:
    return "result_aggregation"


def result_aggregation_node(state: AgentState) -> Dict[str, Any]:
    """AgentResultAggregator's output rendered into the single unified reply
    (design doc section XIV): what changed, what's new (full Activity
    Cards), what stayed untouched -- then back to listening for more
    feedback, never forgetting the main line."""
    aggregated = state.get("aggregated_result") or {}
    summary = aggregated.get("user_visible_summary", {})

    lines = [f"已理解您的调整：{summary.get('understood_request') or state.get('user_message', '')}"]
    if summary.get("added_categories"):
        lines.append(f"新增体验类别：{', '.join(summary['added_categories'])}")
    if summary.get("removed_categories"):
        lines.append(f"减少体验类别：{', '.join(summary['removed_categories'])}")

    new_candidates = aggregated.get("new_activity_candidates") or []
    if new_candidates:
        lines.append("")
        lines.append("新增活动介绍：")
        for c in new_candidates:
            try:
                lines.append("")
                lines.append(TravelExperience(**c).to_activity_card_text())
            except Exception:  # noqa: BLE001 - never let a malformed candidate break the whole reply
                lines.append(f"- {c.get('name', '')}")

    changed_days = summary.get("changed_days") or []
    preserved_days = summary.get("preserved_days") or []
    if changed_days:
        lines.append("")
        lines.append("已调整：第" + "、".join(str(d) for d in changed_days) + "天")
    if preserved_days:
        lines.append("其余天保持不变：第" + "、".join(str(d) for d in preserved_days) + "天")

    for w in aggregated.get("warnings") or []:
        lines.append(f"⚠️ {w}")

    lines.append("")
    lines.append("以上调整是否满意？满意的话回复“确认”即可；如果还需要修改，请继续告诉我。")
    response = "\n".join(lines)

    update: Dict[str, Any] = {}
    itinerary_data = aggregated.get("updated_itinerary")
    if itinerary_data:
        final_plan = dict(state.get("final_plan") or {})
        final_plan["itinerary"] = itinerary_data
        update["final_plan"] = final_plan

    return {
        **update,
        "stage": "post_plan_feedback",
        "current_node": "result_aggregation",
        "need_user_input": True,
        "pending_response": response,
        "conversation_history": [_say(response)],
    }
