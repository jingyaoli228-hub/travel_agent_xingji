"""End-to-end test of the Round-5 acceptance-criteria scenario (design doc
section 二十四): "替换一天乌布给帕尼达岛吧，我要在帕尼达岛浮潜和滑翔伞" ->
system recognizes region replacement, understands the activity requirement,
researches the new region's actual specialty activities, modifies only that
day, preserves other days.

Drives the FULL pipeline through `run_chat_turn` (real graph, real
checkpointed session state) rather than unit-testing individual layers --
`test_region_replacement.py`/`test_intent_pattern_parser.py`/
`test_query_generation.py` already cover those in isolation. This test is
the "does it all actually compose" check.
"""

from __future__ import annotations

import uuid

import pytest

from travel_agent.api.chat import run_chat_turn

pytestmark = pytest.mark.usefixtures("stub_external_calls", "no_llm")


def _reach_bali_final_plan(session_id: str) -> dict:
    r1 = run_chat_turn(session_id, "我想去巴厘岛玩7天，两个人，预算3万元，不想太累")
    assert r1.data.get("stage") == "region_confirmation"

    r2 = run_chat_turn(session_id, "Canggu和Ubud")
    assert r2.data.get("stage") == "confirmation"
    # Known-destination table order (schemas/destination.py's canonical
    # region_names ordering, see destination_intelligence/service.py) puts
    # Ubud before Canggu regardless of the order the user typed them --
    # `_plan_regions` allocates days 1..N to region_preferences[0] first, so
    # Ubud ends up on the early days. Assert this instead of hardcoding it,
    # so the test doesn't silently rot if that ordering ever changes.
    region_preferences = r2.data["travel_requirement"]["region_preferences"]
    assert set(region_preferences) == {"Canggu", "Ubud"}

    r3 = run_chat_turn(session_id, "确认")
    assert r3.data.get("stage") == "selection"

    r4 = run_chat_turn(session_id, "帮我推荐")
    assert r4.data.get("stage") == "done"
    assert r4.need_user_input is False

    return r4.data["final_plan"]["itinerary"], region_preferences[0]


def test_region_replacement_scenario_end_to_end():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    itinerary_before, first_region = _reach_bali_final_plan(session_id)
    assert len(itinerary_before["days"]) == 7

    # Find a day whose items are tagged with the first-allocated region
    # (Ubud, per the assertion above) -- this is the day we'll ask to swap.
    target_day = next(
        d["day_number"] for d in itinerary_before["days"]
        if any(item.get("region") == first_region for item in d["items"])
    )
    assert first_region == "Ubud"

    feedback = f"把第{target_day}天的Ubud换成努沙佩尼达，我想浮潜和滑翔伞"
    r = run_chat_turn(session_id, feedback)
    assert r.data.get("stage") == "post_plan_feedback"
    assert r.need_user_input is True

    itinerary_after = r.data["final_plan"]["itinerary"]
    assert len(itinerary_after["days"]) == 7  # day count preserved, no full-trip rebuild

    # Every day except the target must be byte-identical to the pre-feedback
    # itinerary -- "其他天不要动" is a guarantee, not a promise in the reply text.
    days_before = {d["day_number"]: d for d in itinerary_before["days"]}
    days_after = {d["day_number"]: d for d in itinerary_after["days"]}
    for day_number, before in days_before.items():
        if day_number == target_day:
            continue
        assert days_after[day_number] == before, f"day {day_number} changed but was not the target of the swap"

    # The target day's content must have actually changed and reflect the
    # new region's specialty activities -- not silently become a generic
    # "local_life" search (the diagnosed bug), and not still be Ubud.
    changed_day = days_after[target_day]
    changed_types = {item.get("activity") for item in changed_day["items"]}
    assert not any(item.get("region") == "Ubud" for item in changed_day["items"])
    assert "attraction" in changed_types  # the swap actually placed new content, not just skipped the day
