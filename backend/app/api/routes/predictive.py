from datetime import date

from fastapi import APIRouter, HTTPException, Query

from components.predictive_farm_intelligence.services.demo_service import predictive_demo_service
from components.predictive_farm_intelligence.services.outlook_service import outlook_service
from shared.schemas.pfoi_outlook import AttributionResponse, OutlookResponse
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


# --- Component 1 (PFOI) outputs from c1_output (demo fallback, labelled) ---------------

@router.get("/pfoi/runs")
def pfoi_runs():
    """Forecast dates with a published page document, oldest first (404 when none)."""
    runs = outlook_service.run_origins()
    if not runs:
        raise HTTPException(status_code=404, detail="No PFOI run published in c1_output")
    return {"source": "model", "runs": runs}


@router.get("/pfoi/run")
def pfoi_run(origin: date | None = Query(default=None, description="Forecast date (YYYY-MM-DD); latest if omitted"),
             model_version: str | None = Query(default=None, description="Exact version (comparison chart); "
                                                                         "default: the page's version")):
    """One published page document, or 404 so the page shows its labelled demo."""
    run = outlook_service.run(origin, model_version)
    if run is None:
        raise HTTPException(status_code=404, detail="No PFOI run published in c1_output for this date")
    return run


@router.get("/pfoi/run/versions")
def pfoi_run_versions(origin: date = Query(description="Forecast date (YYYY-MM-DD)")):
    """Model versions published for one forecast date (for the comparison chart)."""
    return {"source": "model", "origin_date": origin.isoformat(),
            "versions": outlook_service.run_versions(origin)}


@router.get("/pfoi/outlook", response_model=OutlookResponse)
def pfoi_outlook(grain: str | None = Query(default=None), series: str | None = Query(default=None)):
    return outlook_service.outlook(grain, series)


@router.get("/pfoi/attribution", response_model=AttributionResponse)
def pfoi_attribution(series: str | None = Query(default=None), kind: str | None = Query(default=None)):
    return outlook_service.attribution(series, kind)
