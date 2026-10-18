"""Interactive CLI entry point for the Travel Planning Agent.

Run with:
    python main.py

Drives the same LangGraph workflow used by the FastAPI `/chat` endpoint and
`demo.py` (`travel_agent.api.chat.run_chat_turn`), but reads each message
from stdin so you can freely converse with the four agents (Requirement /
Research / Planner / Reviewer) instead of following a scripted transcript.
"""

from __future__ import annotations

import uuid

from travel_agent.api.chat import run_chat_turn


def main() -> None:
    session_id = f"cli-{uuid.uuid4().hex[:8]}"
    print("=== 旅游规划 Agent ===")
    print("输入你的旅行需求开始对话（Ctrl+C 退出）。\n")

    message = input("你: ").strip()
    while True:
        resp = run_chat_turn(session_id, message)
        print(f"\nAgent [{resp.current_node}]:\n{resp.response}\n")

        if resp.data.get("stage") == "done":
            print("=== 行程规划完成 ===")
            break

        message = input("你: ").strip()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出。")
