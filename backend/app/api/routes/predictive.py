from fastapi import APIRouter, HTTPException, Query

from components.predictive_farm_intelligence.services.demo_service import predictive_demo_service
from shared.schemas.predictive_api import HorizonId, PredictiveSnapshot

router = APIRouter(prefix="/predictive", tags=["predictive-intelligence"])


def _call(operation, *args):
    try:
        return operation(*args)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Unknown farm: {error.args[0]}") from error


@router.get("/farms")
def farms():
    return predictive_demo_service.farms()


@router.get("/farms/{farm_id}/snapshot", response_model=PredictiveSnapshot)
def snapshot(farm_id: str, horizon: HorizonId = Query(default="90d")):
    return _call(predictive_demo_service.snapshot, farm_id, horizon)


@router.get("/farms/{farm_id}/timeline")
def timeline(farm_id: str, horizon: HorizonId = Query(default="90d")):
    return _call(predictive_demo_service.timeline, farm_id, horizon)


@router.get("/farms/{farm_id}/milk")
def milk(farm_id: str, horizon: HorizonId = Query(default="90d")):
    return _call(predictive_demo_service.milk, farm_id, horizon)


@router.get("/farms/{farm_id}/reproduction")
def reproduction(farm_id: str):
    return _call(predictive_demo_service.reproduction, farm_id)


@router.get("/farms/{farm_id}/finance")
def finance(farm_id: str, horizon: HorizonId = Query(default="90d")):
    return _call(predictive_demo_service.finance, farm_id, horizon)


@router.get("/farms/{farm_id}/findings")
def findings(farm_id: str):
    return _call(predictive_demo_service.findings, farm_id)


@router.get("/farms/{farm_id}/evidence")
def evidence(farm_id: str):
    return _call(predictive_demo_service.evidence, farm_id)


@router.get("/farms/{farm_id}/animals/{animal_id}")
def animal(farm_id: str, animal_id: str):
    result = _call(predictive_demo_service.animal, farm_id, animal_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown animal: {animal_id}")
    return result
