"""Member 4 published research reads; no demo fallback or mutation routes."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from typing import Literal
from backend.app.api.routes.member4_session import valid_session
from backend.app.api.routes.member4_local_read import local_read_allowed
from components.member4_crisis_forecasting.services.published_api import (
    published_output_service, PublishedUnavailable, StoredContractMismatch,
)

router = APIRouter(prefix="/research/farms", tags=["member4-research"])


def require_member4_read(request: Request):
    """Trusted scoped session OR verified opt-in loopback research session.

    Never accept browser role selection or an unverified header as authentication.
    """
    if local_read_allowed(request):
        return
    principal = request.scope.get("user")
    credentials = request.scope.get("auth")
    trusted = (principal is not None and getattr(principal, "is_authenticated", False)
               and "member4:read" in getattr(credentials, "scopes", ()))
    if not trusted and not valid_session(request):
        raise HTTPException(403, detail={"code": "member4_read_not_authorized"})


def read_output(kind, farm_id, response):
    response.headers["Cache-Control"] = "no-store"
    if farm_id != "FARM_X":
        raise HTTPException(404, detail={"code": "unsupported_farm"})
    try:
        return published_output_service.read(kind, farm_id)
    except PublishedUnavailable:
        raise HTTPException(503, detail={"code": "member4_published_data_unavailable"}) from None
    except StoredContractMismatch:
        raise HTTPException(503, detail={"code": "member4_stored_contract_mismatch"}) from None


@router.get("/{farm_id}/assessments", dependencies=[Depends(require_member4_read)])
def assessments(farm_id: str, response: Response, scoring_version: Literal['v1', 'v2', 'v3'] = Query(default='v1')):
    return read_output({'v1':'assessments','v2':'assessments_v2','v3':'assessments_v3'}[scoring_version], farm_id, response)


@router.get("/{farm_id}/milk-decline-predictions", dependencies=[Depends(require_member4_read)])
def predictions(farm_id: str, response: Response):
    return read_output("predictions", farm_id, response)
