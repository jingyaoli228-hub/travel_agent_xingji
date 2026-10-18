"""Offline tests for the multi-intent fix in `graph/nodes.py::user_selection_
node`: a reply like "你帮我自行推荐吧，我要瑜伽，跳舞，浮潜，冲浪，spa，看日落"
carries an auto-pick signal AND specific activity-topic preferences at once --
the old code only ever recognized one signal per message and silently
dropped the other, which from the user's side looked exactly like "nothing
changed, same recommendations every time" (confirmed live).
"""

from __future__ import annotations

import uuid

import pytest

from travel_agent.api.chat import run_chat_turn

pytestmark = pytest.mark.usefixtures("stub_external_calls", "no_llm")


def _reach_selection(session_id: str) -> None:
    run_chat_turn(session_id, "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累")
    run_chat_turn(session_id, "确认")


def test_auto_pick_with_topics_enriches_candidates_before_selecting_and_proceeds():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_selection(session_id)

    r = run_chat_turn(session_id, "你帮我自行推荐吧，我要瑜伽，跳舞，浮潜，冲浪，spa，看日落")

    assert r.data.get("stage") == "done"
    final_plan = r.data.get("final_plan")
    assert final_plan is not None

    # `ItineraryItem.activity` is a generic slot label ("attraction"/"dinner"/
    # "shopping"/...), not the place name -- the actual pick is in `location`
    # (see `final_output_node`'s own `i.activity == "attraction"` cost-summing
    # logic for the same convention). The fake Google Places stub names an
    # unrecognized-tag query's single result after the query text itself, so
    # a topic actually reaching Google Places shows up verbatim there.
    all_locations = " ".join(item["location"] for day in final_plan["itinerary"]["days"] for item in day["items"])
    assert any(topic in all_locations for topic in ("瑜伽", "浮潜", "冲浪", "spa", "看日落", "舞蹈体验"))


def test_topics_only_without_auto_word_enriches_but_waits_for_confirmation():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_selection(session_id)

    r = run_chat_turn(session_id, "我要瑜伽，浮潜，spa")

    assert r.data.get("stage") == "selection"
    assert r.need_user_input is True
    categories = set(r.data.get("candidates", {}).get("experiences", {}).keys())
    assert categories & {"瑜伽", "浮潜", "spa"}


def test_removal_message_is_not_treated_as_topic_preference():
    """A plain removal ("去掉浅草寺") must still work exactly as before --
    topic-preference extraction should not fire alongside it. Checked via
    `selected_places` (what the removal logic actually controls) rather than
    the rendered itinerary's `location` strings -- a meal slot's location can
    legitimately reference a nearby landmark for context regardless of
    whether that landmark itself was ever selected as an attraction, which
    is a pre-existing planner formatting behavior unrelated to removal."""
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_selection(session_id)

    r = run_chat_turn(session_id, "去掉浅草寺")
    assert r.data.get("stage") == "done"
    selected_names = {e["name"] for e in r.data.get("selected_places", {}).get("experiences", [])}
    assert "浅草寺" not in selected_names


def test_free_text_feedback_without_topic_vocab_match_still_routes_as_feedback():
    """Existing behavior (test_workflow.py::test_feedback_triggers_incremental_
    research) must be unaffected: feedback text with no topic_vocab keyword
    match still goes through the free-text Research Feedback Loop."""
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    _reach_selection(session_id)

    r = run_chat_turn(session_id, "这些太游客了，多找一些建筑摄影")
    assert r.data.get("stage") == "selection"
    assert len(r.data.get("candidates", {}).get("experiences", {})) > 0
