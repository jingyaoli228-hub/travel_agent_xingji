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
        return {"status": "ROLLED_BACK", "plan_version": state.plan_version}
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
