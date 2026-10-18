"""REST API for the visual planning workspace and versioned local patches."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from travel_agent.graph.workflow import get_compiled_graph
from travel_agent.schemas.workspace import (
    ApplyPatchRequest, HotelSelectionRequest, InsertPoiRequest, UseRecommendedHotelsRequest,
)
from travel_agent.workspace.service import PlanVersionConflict, PlaceRejected, WorkspaceNotFound, workspace_service

router = APIRouter(prefix="/api")


class RollbackRequest(BaseModel):
    plan_version: int
    request_id: str


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
    return {
        "trip_id": trip_id,
        "title": f"{destination} {len(state.days)} 日游",
        "subtitle": f"{dates[0][5:]} - {dates[-1][5:]}" if dates else "",
        "status": values.get("stage") or "done",
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
        graph = get_compiled_graph()
        config = {"configurable": {"thread_id": trip_id}}
        snapshot = graph.get_state(config)
        if snapshot and snapshot.values:
            graph.update_state(config, {"itinerary": {"days": [day.model_dump() for day in workspace_service.get(trip_id).days]}})
        return result
    except Exception as exc:
        raise _translate_error(exc)


@router.post("/trips/{trip_id}/rollback-patch")
def rollback_patch(trip_id: str, request: RollbackRequest) -> dict[str, Any]:
    _ensure_workspace(trip_id)
    try:
        state = workspace_service.rollback(trip_id, request.plan_version)
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
