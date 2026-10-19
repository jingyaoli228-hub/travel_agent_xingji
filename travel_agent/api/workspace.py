"""REST API for the visual planning workspace and versioned local patches."""

from __future__ import annotations

from datetime import date
import copy
import re
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from travel_agent.graph.workflow import get_compiled_graph
from travel_agent.schemas.workspace import (
    ApplyPatchRequest, DeleteItemRequest, HotelSelectionRequest, InsertPoiRequest,
    ItemLockRequest, ReorderDayRequest, UseRecommendedHotelsRequest,
)
from travel_agent.workspace.service import PlanVersionConflict, PlaceRejected, WorkspaceNotFound, workspace_service

router = APIRouter(prefix="/api")


class RollbackRequest(BaseModel):
    plan_version: int
    request_id: str


class CopyTripRequest(BaseModel):
    user_id: str
    start_date: Optional[str] = None


class XhsParseRequest(BaseModel):
    user_id: str
    content: str


class XhsStoreRequest(BaseModel):
    user_id: str
    import_id: str
    content: str
    places: list[dict[str, Any]]


def _ensure_workspace(trip_id: str):
    try:
        return workspace_service.get(trip_id)
    except WorkspaceNotFound:
        graph = get_compiled_graph()
        snapshot = graph.get_state({"configurable": {"thread_id": trip_id}})
        values = snapshot.values if snapshot else {}
        itinerary = values.get("itinerary") or (values.get("final_plan") or {}).get("itinerary")
        if not itinerary:
            raise HTTPException(404, detail="TRIP_NOT_FOUND")
        return workspace_service.seed(trip_id, itinerary.get("days") or [])


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PlanVersionConflict):
        return HTTPException(409, detail={"code": "PLAN_VERSION_CONFLICT", "message": str(exc)})
    if isinstance(exc, WorkspaceNotFound):
        return HTTPException(404, detail="TRIP_NOT_FOUND")
    return HTTPException(422, detail=str(exc))


def _status_for(days: list[Any], score: float) -> tuple[str, bool]:
    dates = [date.fromisoformat(day.date) for day in days if day.date]
    today = date.today()
    if dates and max(dates) < today:
        return "traveled", False
    ongoing = bool(dates and min(dates) <= today <= max(dates))
    return ("confirmed" if score >= 85 else "draft"), ongoing


def _snapshot_values(trip_id: str) -> dict[str, Any]:
    snapshot = get_compiled_graph().get_state({"configurable": {"thread_id": trip_id}})
    return snapshot.values if snapshot else {}


def _sync_workspace_itinerary(trip_id: str) -> None:
    """Keep the conversation graph's L0 itinerary aligned with workspace edits."""
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": trip_id}}
    snapshot = graph.get_state(config)
    if snapshot and snapshot.values:
        graph.update_state(config, {
            "itinerary": {"days": [day.model_dump() for day in workspace_service.get(trip_id).days]}
        })


@router.get("/trips")
def list_trips(user_id: str) -> dict[str, Any]:
    from travel_agent.persistence import database

    if database.enabled():
        rows = database.list_sessions(user_id)
        ids = [row["session_id"] for row in rows]
        updated = {row["session_id"]: row["updated_at"].isoformat() for row in rows}
    else:
        ids = workspace_service.list_trip_ids()
        updated = {}
    trips = []
    for trip_id in ids:
        try:
            state = _ensure_workspace(trip_id)
        except HTTPException:
            continue
        values = _snapshot_values(trip_id)
        review = values.get("review_report") or {}
        score = float(review.get("score") or 0)
        status, ongoing = _status_for(state.days, score)
        destination = (values.get("travel_requirement") or {}).get("destination") or next((day.city for day in state.days if day.city), "行程")
        dates = [day.date for day in state.days if day.date]
        trips.append({
            "trip_id": trip_id, "city": destination, "days": len(state.days), "status": status,
            "ongoing": ongoing, "dates": f"{dates[0][5:]} - {dates[-1][5:]}" if dates else "日期待定",
            "score": round(score), "issues": len(review.get("issues") or []),
            "summary": "只读" if status == "traveled" else (f"质量 {round(score)}" if score else "规划中"),
            "updated_at": updated.get(trip_id, ""),
        })
    trips.sort(key=lambda row: row["updated_at"], reverse=True)
    trips.sort(key=lambda row: (0 if row["ongoing"] else 1, {"confirmed": 0, "draft": 1, "traveled": 2}[row["status"]]))
    return {"trips": trips}


@router.delete("/trips/{trip_id}")
def delete_trip(trip_id: str) -> dict[str, str]:
    workspace_service.delete(trip_id)
    graph = get_compiled_graph()
    try:
        delete_thread = getattr(graph.checkpointer, "delete_thread", None)
        if delete_thread:
            delete_thread(trip_id)
    except Exception:
        pass
    return {"status": "DELETED"}


@router.post("/trips/{trip_id}/copy")
def copy_trip(trip_id: str, request: CopyTripRequest) -> dict[str, Any]:
    source_values = _snapshot_values(trip_id)
    new_id = f"trip-{uuid4().hex[:16]}"
    start = request.start_date or date.today().isoformat()
    state = workspace_service.clone(trip_id, new_id, start)
    from travel_agent.persistence import database
    if database.enabled():
        database.touch_session(new_id, request.user_id, "post_plan_feedback")
    if source_values:
        copied_values = copy.deepcopy(source_values)
        copied_values.update({
            "session_id": new_id, "user_id": request.user_id,
            "conversation_history": [], "stage": "post_plan_feedback",
            "current_node": "post_plan_feedback", "need_user_input": True,
            "itinerary": {"days": [day.model_dump(mode="json") for day in state.days]},
        })
        final_plan = dict(copied_values.get("final_plan") or {})
        final_plan["itinerary"] = copied_values["itinerary"]
        copied_values["final_plan"] = final_plan
        get_compiled_graph().update_state(
            {"configurable": {"thread_id": new_id}}, copied_values, as_node="final_output",
        )
    return {"trip_id": new_id, "plan_version": state.plan_version, "days": len(state.days)}


@router.get("/trips/{trip_id}/insight")
def trip_insight(trip_id: str) -> dict[str, Any]:
    state = _ensure_workspace(trip_id)
    values = _snapshot_values(trip_id)
    memory = values.get("memory_context") or {}
    review = values.get("review_report") or {}
    strict = values.get("strict_evaluation") or {}
    intent = values.get("intent_result") or {}
    changes = state.history[-5:]
    real_routes = sum(1 for rows in state.route_segments_by_day.values() for row in rows if row.status == "REAL_ROUTE")
    return {
        "intent": {"path": intent.get("route") or intent.get("intent") or values.get("current_node"), "confidence": intent.get("confidence"), "source": "本次记录"},
        "memory": {
            "l0": bool(values.get("travel_requirement")), "l1": len(values.get("conversation_history") or []),
            "l2": len(memory.get("episodic") or []), "l3": [row.get("statement") for row in memory.get("profile_statements") or []],
            "source": "本次记录",
        },
        "tools": {"real_routes": real_routes, "candidate_count": len((values.get("selected_places") or {}).get("experiences") or []), "source": "本次记录"},
        "quality": {"reviewer": review.get("score"), "strict": strict.get("overall_score"), "issues": review.get("issues") or strict.get("improvement_actions") or [], "source": "本次记录"},
        "changes": [{"version": row.get("plan_version"), "summary": row.get("summary"), "items": row.get("changed_items") or []} for row in changes],
        "developer": {"plan_version": state.plan_version, "stage": values.get("stage"), "node": values.get("current_node"), "source": "本次记录"},
    }


_PLACE_PATTERN = re.compile(r"([\u4e00-\u9fff]{2,12}(?:博物馆|公园|美术馆|艺术区|广场|长城|胡同|大街|寺|宫|山|海|街|巷|园|馆|城|塔|湖))")
_KNOWN_POIS = (
    "故宫博物院", "天坛公园", "颐和园", "八达岭长城", "慕田峪长城", "景山公园",
    "北海公园", "中国国家博物馆", "恭王府", "什刹海", "南锣鼓巷", "雍和宫",
    "孔庙和国子监博物馆", "圆明园", "北京环球度假区", "798艺术区", "前门大街", "鼓楼",
)


@router.post("/imports/xhs/parse")
def parse_xhs(request: XhsParseRequest) -> dict[str, Any]:
    content = request.content.strip()
    if not content:
        raise HTTPException(422, detail="请粘贴链接或笔记正文")
    plain = re.sub(r"https?://\S+", " ", content)
    if not plain.strip():
        raise HTTPException(422, detail={"code": "LINK_CONTENT_UNAVAILABLE", "message": "链接打不开或需要登录，请把正文也粘贴进来"})
    known = [name for name in _KNOWN_POIS if name in plain]
    names = list(dict.fromkeys(known + _PLACE_PATTERN.findall(plain)))[:20]
    if not names:
        raise HTTPException(422, detail={"code": "NO_PLACE_FOUND", "message": "没认出具体地点，请补充城市或地点名称"})
    city_match = re.search(r"(北京|上海|广州|深圳|成都|杭州|西安|重庆|南京|苏州|厦门|长沙|武汉|青岛)", plain)
    city = city_match.group(1) if city_match else ""
    places = []
    for name in names:
        matches = workspace_service.autocomplete(name, city)[:1]
        match = matches[0] if matches else {}
        places.append({
            "name": name, "note": next((line.strip() for line in plain.splitlines() if name in line), "")[:120],
            "matched": bool(match.get("place_id")), "checked": bool(match.get("place_id")),
            "place_id": match.get("place_id"), "city": city, "source": "用户粘贴",
        })
    return {"import_id": f"xhs-{uuid4().hex[:16]}", "title": (plain.splitlines()[0] or "小红书笔记")[:40], "places": places}


@router.post("/imports/xhs/store")
def store_xhs(request: XhsStoreRequest) -> dict[str, Any]:
    from travel_agent.persistence import database
    payload = {"places": request.places, "source": "user_paste", "platform": "xiaohongshu"}
    if database.enabled():
        database.save_xhs_import(request.import_id, request.user_id, request.content, payload)
    try:
        from datetime import datetime, timezone
        from travel_agent.rag.ingestion.embedding_writer import write_chunks
        from travel_agent.rag.schemas import TravelGuideChunk

        now = datetime.now(timezone.utc).isoformat()
        chunks = [TravelGuideChunk(
            id=f"{request.import_id}::{index}",
            content=row.get("note") or request.content,
            summary=row.get("note") or f"用户导入的 {row.get('name', '')} 笔记",
            destination_city=row.get("city") or None,
            canonical_destination=row.get("city") or None,
            canonical_place_name=row.get("name") or None,
            guide_type="玩法笔记",
            activity_topics=[row.get("name")] if row.get("name") else [],
            source_type="小红书·用户粘贴",
            source_title=f"用户导入：{row.get('name') or request.import_id}",
            collected_time=now,
            freshness_level="用户导入",
            quality_score=0.6,
            parent_document_id=request.import_id,
            chunk_index=index,
        ) for index, row in enumerate(request.places)]
        write_chunks(chunks)
    except Exception:
        pass
    return {"status": "STORED", "import_id": request.import_id, "places": len(request.places)}


@router.get("/trips/{trip_id}/days")
def get_days(trip_id: str) -> dict[str, Any]:
    state = _ensure_workspace(trip_id)
    return {"days": [day.model_dump() for day in state.days], "plan_version": state.plan_version,
            "hotel_selection_status": state.hotel_selection_status, "selected_hotels_by_city": state.selected_hotels_by_city}


@router.get("/trips/{trip_id}/overview")
def get_trip_overview(trip_id: str) -> dict[str, Any]:
    """One request for the P0 itinerary home, including map and history data."""
    _ensure_workspace(trip_id)
    state = workspace_service.ensure_geodata(trip_id)
    route_segments_by_day: dict[str, list[dict[str, Any]]] = {}
    for day in state.days:
        day_id = day.day_id or f"day_{day.day_number}"
        route_segments_by_day[day_id] = [segment.model_dump() for segment in workspace_service.routes(trip_id, day_id)]

    graph = get_compiled_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": trip_id}})
    values = snapshot.values if snapshot else {}
    requirement = values.get("travel_requirement") or {}
    final_plan = values.get("final_plan") or {}
    review = values.get("review_report") or {}
    strict_review = values.get("strict_evaluation") or {}
    score = review.get("score")
    if score is None:
        score = strict_review.get("overall_score") or 0

    alerts: list[dict[str, Any]] = []
    degraded = sum(
        1 for segments in route_segments_by_day.values()
        for segment in segments if segment.get("status") != "REAL_ROUTE"
    )
    if degraded:
        alerts.append({
            "id": "route-degraded", "type": "degraded",
            "text": f"{degraded} 段路线暂为估算", "actionText": "重试",
        })
    if score < 85:
        issues = review.get("issues") or strict_review.get("improvement_actions") or []
        detail = f"：{issues[0]}" if issues else ""
        alerts.append({
            "id": "quality", "type": "quality", "text": f"评审 {round(float(score))} 分{detail}",
            "actionText": "看透视",
        })
    notes = final_plan.get("notes") or []
    risk = next((note for note in notes if any(word in note for word in ("天气", "雨", "风险", "注意"))), None)
    if risk:
        alerts.append({"id": "risk", "type": "risk", "text": risk, "actionText": "查看"})

    dates = [day.date for day in state.days if day.date]
    destination = requirement.get("destination") or next((day.city for day in state.days if day.city), "行程")
    trip_status, ongoing = _status_for(state.days, float(score))
    return {
        "trip_id": trip_id,
        "title": f"{destination} {len(state.days)} 日游",
        "subtitle": f"{dates[0][5:]} - {dates[-1][5:]}" if dates else "",
        "status": trip_status,
        "ongoing": ongoing,
        "plan_version": state.plan_version,
        "quality": {
            "score": round(float(score)), "passed": bool(review.get("passed") or float(score) >= 85),
            "issues": review.get("issues") or strict_review.get("improvement_actions") or [],
        },
        "days": [day.model_dump(mode="json") for day in state.days],
        "route_segments_by_day": route_segments_by_day,
        "alerts": alerts,
        "conversation_history": values.get("conversation_history") or [],
        "changes": [
            {
                "plan_version": entry.get("plan_version"),
                "summary": entry.get("summary") or "行程已修改",
                "changed_items": entry.get("changed_items") or [],
                "can_undo": index == len(state.history) - 1,
            }
            for index, entry in enumerate(state.history)
        ],
    }


@router.get("/trips/{trip_id}/days/{day_id}")
def get_day(trip_id: str, day_id: str) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        return {"day": workspace_service.day(trip_id, day_id).model_dump(), "plan_version": workspace_service.get(trip_id).plan_version}
    except Exception as exc:
        raise _translate_error(exc)


@router.get("/places/autocomplete")
def autocomplete(q: str, city: str, latitude: Optional[float] = None, longitude: Optional[float] = None,
                 radius_meters: int = Query(20000, ge=100, le=50000)) -> dict[str, Any]:
    return {"results": workspace_service.autocomplete(q, city, latitude, longitude, radius_meters), "location_bias": city}


@router.get("/places/{place_id}")
def place_details(place_id: str) -> dict[str, Any]:
    try:
        return workspace_service.place_details(place_id)
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/days/{day_id}/preview-insert")
@router.post("/trips/{trip_id}/days/{day_id}/insert-poi")
def preview_insert(trip_id: str, day_id: str, request: InsertPoiRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        return workspace_service.preview_insert(trip_id, day_id, request.model_dump())
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/apply-patch")
def apply_patch(trip_id: str, request: ApplyPatchRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        result = workspace_service.apply_patch(trip_id, request.patch_id, request.current_plan_version, request.request_id)
        # Keep LangGraph L0 state synchronized; workspace remains the version authority.
        _sync_workspace_itinerary(trip_id)
        return result
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/days/{day_id}/reorder")
def reorder_day(trip_id: str, day_id: str, request: ReorderDayRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        result = workspace_service.reorder_day(
            trip_id, day_id, request.ordered_item_ids,
            request.current_plan_version, request.request_id,
        )
        _sync_workspace_itinerary(trip_id)
        return result
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/days/{day_id}/items/{item_id}/lock")
def set_item_lock(trip_id: str, day_id: str, item_id: str, request: ItemLockRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        result = workspace_service.set_item_lock(
            trip_id, day_id, item_id, request.locked,
            request.current_plan_version, request.request_id,
        )
        _sync_workspace_itinerary(trip_id)
        return result
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/days/{day_id}/items/{item_id}/delete")
def delete_item(trip_id: str, day_id: str, item_id: str, request: DeleteItemRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        result = workspace_service.delete_item(
            trip_id, day_id, item_id,
            request.current_plan_version, request.request_id,
        )
        _sync_workspace_itinerary(trip_id)
        return result
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/rollback-patch")
def rollback_patch(trip_id: str, request: RollbackRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        state = workspace_service.rollback(trip_id, request.plan_version)
        _sync_workspace_itinerary(trip_id)
        return {
            "status": "ROLLED_BACK", "plan_version": state.plan_version,
            "days": [day.model_dump(mode="json") for day in state.days],
        }
    except Exception as exc:
        raise _translate_error(exc)


@router.get("/trips/{trip_id}/hotel-candidates")
def hotel_candidates(trip_id: str) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    rows = workspace_service.hotel_candidates(trip_id)
    state = workspace_service.get(trip_id)
    return {"hotel_candidates_by_city": rows, "hotel_selection_status": state.hotel_selection_status,
            "plan_version": state.plan_version}


@router.post("/trips/{trip_id}/hotels/select")
def select_hotel(trip_id: str, request: HotelSelectionRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        state = workspace_service.select_hotel(trip_id, request.city, request.place_id,
                                               request.current_plan_version, request.request_id)
        return state.model_dump()
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/hotels/use-recommended")
def use_recommended(trip_id: str, request: UseRecommendedHotelsRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        return workspace_service.use_recommended(trip_id, request.cities, request.current_plan_version,
                                                 request.request_id).model_dump()
    except Exception as exc:
        raise _translate_error(exc)


@router.get("/trips/{trip_id}/days/{day_id}/routes")
def routes(trip_id: str, day_id: str) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    return {"route_segments": workspace_service.routes(trip_id, day_id), "plan_version": workspace_service.get(trip_id).plan_version}
