"""End-to-end test of the full LangGraph workflow, mirroring `demo.py`.

Exercises: requirement collection -> clarification (implicitly skipped
since the demo sentence is already complete) -> user confirmation ->
research -> recommendation -> user selection -> planner -> validator ->
reviewer (loop) -> final output. All human-in-the-loop pauses are resumed by
calling `run_chat_turn` again with the same `session_id`.

`stub_external_calls` and `no_llm` (see `conftest.py`) stand in for the real
Google/Kimi/Agent Reach calls with deterministic fake data, so this test
stays fast, free and offline while still exercising the real orchestration
logic end-to-end.
"""

import uuid

import pytest

from travel_agent.api.chat import run_chat_turn

pytestmark = pytest.mark.usefixtures("stub_external_calls", "no_llm")


def test_full_pipeline_runs_to_completion():
    session_id = f"test-{uuid.uuid4().hex[:8]}"

    r1 = run_chat_turn(session_id, "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累")
    assert r1.need_user_input is True
    assert r1.data.get("stage") == "confirmation"

    r2 = run_chat_turn(session_id, "确认")
    assert r2.need_user_input is True
    assert r2.data.get("stage") == "selection"

    r3 = run_chat_turn(session_id, "帮我推荐")
    assert r3.need_user_input is False
    assert r3.data.get("stage") == "done"

    final_plan = r3.data.get("final_plan")
    assert final_plan is not None
    assert len(final_plan["itinerary"]["days"]) == 5

    review_report = r3.data.get("review_report")
    assert review_report is not None
    assert 0 <= review_report["score"] <= 100


def test_clarification_loop_when_info_incomplete():
    session_id = f"test-{uuid.uuid4().hex[:8]}"

    r1 = run_chat_turn(session_id, "我想去东京玩")
    assert r1.need_user_input is True
    assert r1.data.get("stage") == "clarification"

    r2 = run_chat_turn(session_id, "5天，两个人，预算2万，节奏平衡")
    assert r2.data.get("stage") in ("confirmation", "clarification")


def test_feedback_triggers_incremental_research():
    """A free-text refinement ("多找一些建筑摄影") should route back through the
    Research Orchestrator as feedback, not be treated as a selection."""
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    run_chat_turn(session_id, "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累")
    run_chat_turn(session_id, "确认")

    r_more = run_chat_turn(session_id, "这些太游客了，多找一些建筑摄影")
    assert r_more.data.get("stage") == "selection"
    assert len(r_more.data.get("candidates", {}).get("experiences", {})) > 0


def test_bali_triggers_region_confirmation():
    """Stage-2: complex destinations (Bali) get a region-split question before
    the normal requirement confirmation."""
    session_id = f"test-{uuid.uuid4().hex[:8]}"

    r1 = run_chat_turn(session_id, "我想去巴厘岛玩7天，两个人，预算3万元，不想太累")
    assert r1.need_user_input is True
    assert r1.data.get("stage") == "region_confirmation"
    assert "Ubud" in r1.response or "Canggu" in r1.response

    r2 = run_chat_turn(session_id, "Canggu和Ubud")
    assert r2.data.get("stage") == "confirmation"
    assert set(r2.data["travel_requirement"]["region_preferences"]) == {"Canggu", "Ubud"}

    r3 = run_chat_turn(session_id, "确认")
    assert r3.data.get("stage") == "selection"


def test_plan_feasibility_expansion_loop_completes():
    """A thin selection (fewer experiences than the trip needs) should trigger
    the Planner -> Research Orchestrator auto-expansion loop and still reach
    `done` within the configured loop budget."""
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    run_chat_turn(session_id, "我想10月去东京10天，两个人，预算5万元，喜欢购物和美食，节奏特种兵")
    run_chat_turn(session_id, "确认")
    r_candidates = run_chat_turn(session_id, "帮我推荐")

    assert r_candidates.data.get("stage") == "done"
    final_plan = r_candidates.data.get("final_plan")
    assert final_plan is not None
    assert len(final_plan["itinerary"]["days"]) == 10
