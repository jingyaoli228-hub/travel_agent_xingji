"""Tests for the Stage-4 HTTP layer: `POST /api/chat/stream` (SSE),
`GET /api/research/status`, `GET /api/session/{id}`.

Uses FastAPI's `TestClient` (in-process, no real network) with the same
`stub_external_calls`/`no_llm` fixtures as the rest of the suite, so the
background research job (see `execution/research_jobs.py`) completes near-
instantly and these tests stay fast, free and fully offline.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from travel_agent.main import app

pytestmark = pytest.mark.usefixtures("stub_external_calls", "no_llm")

client = TestClient(app)


def _parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def _poll_research_status(session_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    status = client.get("/api/research/status", params={"session_id": session_id}).json()
    while status["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        status = client.get("/api/research/status", params={"session_id": session_id}).json()
    return status


def test_chat_stream_returns_final_event_for_simple_turn():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我想去东京玩"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events, "expected at least the final event"
    assert events[-1]["type"] == "final"
    assert events[-1]["data"]["stage"] == "clarification"


def test_chat_stream_dispatches_research_without_blocking():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累"},
    )
    resp = client.post("/api/chat/stream", json={"session_id": session_id, "message": "确认"})
    events = _parse_sse(resp.text)
    final = events[-1]
    assert final["type"] == "final"
    # Dispatched to the background job -- the turn itself doesn't block for
    # the whole research pass (offline heuristic run_full is fast even so,
    # but the *response contract* is what's under test here).
    assert final["data"]["stage"] == "research"
    assert final["need_user_input"] is False


def test_research_status_and_session_endpoints_after_background_dispatch():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累"},
    )
    client.post("/api/chat/stream", json={"session_id": session_id, "message": "确认"})

    status = _poll_research_status(session_id)
    assert status["status"] == "done"

    session_resp = client.get(f"/api/session/{session_id}")
    assert session_resp.status_code == 200
    data = session_resp.json()
    assert data["data"]["stage"] == "selection"
    assert data["data"].get("candidates")


def test_planner_expansion_pause_is_reported_as_researching_then_delivers_itinerary():
    """Regression: the UI used to remain forever on the selection node's
    'generating itinerary' text because a Planner-triggered research pause
    was incorrectly returned as stage=planning, which the browser did not
    poll."""
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我想10月去东京10天，两个人，预算5万元，喜欢购物和美食，节奏特种兵"})
    assert _parse_sse(first.text)[-1]["data"]["stage"] == "confirmation"
    client.post("/api/chat/stream", json={"session_id": session_id, "message": "确认"})
    assert _poll_research_status(session_id)["status"] == "done"

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "帮我推荐"})
    final = _parse_sse(response.text)[-1]
    assert final["data"]["stage"] == "researching"
    assert final["need_user_input"] is False

    assert _poll_research_status(session_id)["status"] == "done"
    session = client.get(f"/api/session/{session_id}").json()
    assert session["data"].get("itinerary") or session["data"].get("final_plan")


def test_get_session_404_for_unknown_session():
    resp = client.get(f"/api/session/does-not-exist-{uuid.uuid4().hex}")
    assert resp.status_code == 404


def test_research_status_idle_for_unknown_session():
    resp = client.get("/api/research/status", params={"session_id": f"never-seen-{uuid.uuid4().hex}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_research_status_poll_self_heals_paused_session(monkeypatch):
    from travel_agent.api import chat as chat_module
    calls = []
    monkeypatch.setattr(chat_module.research_jobs, "get_status", lambda session_id: {"status": "idle", "progress": {}} if not calls else {"status": "running", "progress": {}})
    monkeypatch.setattr(chat_module.research_jobs, "dispatch_if_needed", lambda session_id, graph, config: calls.append(session_id) or True)
    response = client.get("/api/research/status", params={"session_id": "paused-session"})
    assert response.json()["status"] == "running"
    assert calls == ["paused-session"]


def test_planning_context_exposes_only_prefill_dimensions(monkeypatch):
    from travel_agent.memory.profile_memory import ProfileMemory
    from travel_agent.schemas.memory import UserProfile

    monkeypatch.setattr(
        ProfileMemory,
        "get",
        lambda self, user_id: UserProfile(
            user_id=user_id,
            travel_style="适中",
            interest_preference=["人文古迹"],
            food_constraints=["不吃辣"],
            transport_preference="公共交通",
        ),
    )
    response = client.get("/api/users/owner/planning-context")
    assert response.status_code == 200
    assert response.json()["prefilled"] is True
    assert response.json()["profile"]["interests"] == ["人文古迹"]
    assert "user_id" not in response.json()["profile"]
