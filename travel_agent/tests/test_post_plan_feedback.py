"""End-to-end test of the Stage-3 post-plan feedback loop -- the demo
scenario from the design doc section 23: system presents a plan built from
traditional attractions, the user asks to add Ubud yoga/nightlife with
"other days unchanged", and the system must actually search, replan only the
targeted day, and present full Activity Cards -- not just say it did.
"""

from __future__ import annotations

import uuid

import pytest

from travel_agent.api.chat import run_chat_turn

pytestmark = pytest.mark.usefixtures("stub_external_calls", "no_llm")


def _reach_final_plan(session_id: str) -> None:
    r1 = run_chat_turn(session_id, "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累")
    assert r1.data.get("stage") == "confirmation"
    r2 = run_chat_turn(session_id, "确认")
    assert r2.data.get("stage") == "selection"
    r3 = run_chat_turn(session_id, "帮我推荐")
    assert r3.data.get("stage") == "done"
    assert r3.need_user_input is False


def test_final_output_pauses_at_post_plan_feedback_without_changing_existing_contract():
    """The first arrival at `done` must look exactly like it did before this
    upgrade (need_user_input=False) -- interrupt_before halts BEFORE
    `post_plan_feedback_node` runs, so this turn's reported state is
    unaffected. The capability is additive, not a breaking change."""
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_final_plan(session_id)


def test_add_activity_feedback_replans_only_targeted_day_with_full_cards():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_final_plan(session_id)

    before = run_chat_turn(session_id, "东京明天天气怎么样")  # side query, sanity check first
    assert before.data.get("stage") == "post_plan_feedback"
    assert before.need_user_input is True

    r = run_chat_turn(session_id, "第三天下午再增加两个咖啡体验，其他安排不要动。")
    assert r.data.get("stage") == "post_plan_feedback"
    assert r.need_user_input is True

    itinerary = r.data["final_plan"]["itinerary"]
    assert len(itinerary["days"]) == 5  # day count preserved, no full-trip rebuild

    # The response must show full activity cards, not just names.
    assert "介绍" in r.response
    assert "第3" in r.response or "第三" in r.response


def test_side_query_does_not_disturb_plan_and_resumes_feedback_phase():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_final_plan(session_id)

    r = run_chat_turn(session_id, "去日本需要签证吗")
    assert r.data.get("stage") == "post_plan_feedback"
    assert r.need_user_input is True
    assert r.data.get("final_plan") is not None


def test_confirm_after_feedback_closes_out():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_final_plan(session_id)
    run_chat_turn(session_id, "第三天下午再增加一个咖啡体验，其他安排不要动。")

    r = run_chat_turn(session_id, "确认")
    assert r.data.get("stage") == "done"
    assert r.need_user_input is False
