"""Scripted end-to-end demo of the travel planning agent.

Runs the exact scenario from the project brief:

    "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累"

and walks through: requirement confirmation -> real Research (Google Places /
Routes / Weather / Agent Reach) -> candidate selection -> itinerary
generation -> reviewer feedback loop -> final output. Falls back to
rule-based heuristics for Requirement/Reviewer when no Kimi key is
configured, and to `{"success": false, ...}` per-tool when a Google API key
is missing or a call fails, so the pipeline still completes either way.

Run with:
    python demo.py
"""

from __future__ import annotations

import json
import sys
import uuid

from travel_agent.api.chat import run_chat_turn

# Windows consoles default to the GBK codepage, which can't encode arbitrary
# Unicode (e.g. the checkmark below) -- force UTF-8 so this script never
# crashes on the final print regardless of the host console's locale.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def _print_turn(label: str, user_message: str, resp) -> None:
    print("=" * 70)
    print(f"[{label}] 用户: {user_message}")
    print("-" * 70)
    print(f"Agent ({resp.current_node} | need_user_input={resp.need_user_input}):")
    print(resp.response)
    print()


def main() -> None:
    session_id = f"demo-{uuid.uuid4().hex[:8]}"
    print(f"Session ID: {session_id}\n")

    resp = run_chat_turn(session_id, "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累")
    _print_turn("需求输入", "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累", resp)

    # Stage-2: complex destinations (an LLM-configured run may flag Tokyo's
    # distinct areas too, not just offline-known ones like Bali) get an extra
    # region-split question here. Handle it if it shows up, skip it otherwise
    # -- this keeps the demo correct regardless of whether an LLM is
    # configured/what it decides, rather than assuming a fixed turn count.
    if resp.data.get("stage") == "region_confirmation":
        resp = run_chat_turn(session_id, "不用分区")
        _print_turn("区域确认", "不用分区", resp)

    if resp.data.get("stage") == "confirmation":
        resp = run_chat_turn(session_id, "确认")
        _print_turn("需求确认", "确认", resp)

    resp = run_chat_turn(session_id, "帮我推荐")
    _print_turn("候选选择", "帮我推荐", resp)

    assert resp.data.get("stage") == "done", f"Expected stage=done, got {resp.data.get('stage')}"

    final_plan = resp.data.get("final_plan")
    review_report = resp.data.get("review_report")

    print("=" * 70)
    print("最终评审报告 (ReviewReport):")
    print(json.dumps(review_report, ensure_ascii=False, indent=2))

    out_path = "demo_final_plan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_plan, f, ensure_ascii=False, indent=2)
    print(f"\n完整 TravelPlan 已保存到 {out_path}")
    print("\n[Demo] 全流程跑通：需求确认 → Research(真实API) → 用户选择 → itinerary生成 → reviewer优化 → final output")

    # Stage-3: post-plan feedback loop (design doc section 23's demo scenario,
    # adapted to whatever destination the requirement above resolved to --
    # "系统先推荐传统景点 → 用户要求增加瑜伽和夜生活 → 意图解析 → Research 搜索
    # → 局部重规划 → 返回完整活动介绍"). The graph no longer ends at `done`;
    # it pauses at `post_plan_feedback` and accepts further feedback here.
    feedback_message = "这些景点有点太传统了，想多安排一些瑜伽和夜生活体验，第三天下午重新安排一下，其他天不要动。"
    resp = run_chat_turn(session_id, feedback_message)
    _print_turn("计划后反馈", feedback_message, resp)
    assert resp.data.get("stage") == "post_plan_feedback", f"Expected stage=post_plan_feedback, got {resp.data.get('stage')}"

    print("=" * 70)
    print("意图解析结果 (IntentResult, 不含 evidence 日志字段):")
    intent_result = dict(resp.data.get("intent_result") or {})
    intent_result.pop("evidence", None)
    print(json.dumps(intent_result, ensure_ascii=False, indent=2))

    resp = run_chat_turn(session_id, "确认")
    _print_turn("确认调整", "确认", resp)
    print("[Demo] 计划后反馈闭环跑通：多信号意图解析 → 局部重规划(仅第三天) → 完整活动介绍 → 用户确认收尾")


if __name__ == "__main__":
    main()
