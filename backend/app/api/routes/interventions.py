import math

from fastapi import APIRouter, HTTPException, Query

from components.member1_didt.schemas.counterfactual import (
    CowReference, CowState, SimulationRequest, SimulationResponse,
)
from components.member1_didt.services.farmx_repository import (
    AnimalNotFound, FarmXDataUnavailable, FarmXRepository,
)
from components.member1_didt.services.intervention_pipeline import run_simulation
from components.member1_didt.prediction.predictor import FarmXMilkYieldPredictor
from shared.schemas.intervention import InterventionScenario as LegacyScenario
from components.member1_didt.services.demo_service import simulate as legacy_demo

router = APIRouter(prefix="/interventions", tags=["interventions"])


@router.get("/model-support")
def model_support() -> dict:
    """Expose only training bounds used by the simulator's existing validator."""
    unavailable = {
        "status": "UNAVAILABLE",
        "model_version": None,
        "features": {"thi_mean": None, "milkings_per_day": None},
    }
    try:
        predictor = FarmXMilkYieldPredictor()
    except Exception:
        return unavailable

    try:
        metadata = getattr(predictor, "metadata", {})
        observed_support = {}
        if isinstance(metadata, dict):
            observed_support = metadata.get("observed_numeric_support") or {}
        model_version = predictor.model_version
    except Exception:
        return unavailable
    features = {}
    for feature in ("thi_mean", "milkings_per_day"):
        raw_range = observed_support.get(feature) or {}
        if not isinstance(raw_range, dict):
            features[feature] = None
            continue
        minimum, maximum = raw_range.get("minimum"), raw_range.get("maximum")
        if (
            isinstance(minimum, (int, float)) and not isinstance(minimum, bool)
            and isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
            and math.isfinite(minimum) and math.isfinite(maximum) and minimum <= maximum
        ):
            features[feature] = {"minimum": float(minimum), "maximum": float(maximum)}
        else:
            features[feature] = None

    available_count = sum(value is not None for value in features.values())
    status = "AVAILABLE" if available_count == 2 else "PARTIAL" if available_count else "UNAVAILABLE"
    return {"status": status, "model_version": model_version, "features": features}


@router.post("/simulate")
def intervention_simulation(scenario: LegacyScenario) -> dict:
    """Legacy compatibility contract; does not return its former fabricated uplift."""
    return legacy_demo(scenario)


@router.get("/cows/{animal_ref}/state", response_model=CowState)
def current_cow_state(animal_ref: str) -> CowState:
    try:
        return FarmXRepository().get_current_state(animal_ref)
    except AnimalNotFound as exc:
        raise HTTPException(status_code=404, detail="No usable approved cow-day is available for this reference.") from exc
    except FarmXDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Approved Farm X data are temporarily unavailable.") from exc


@router.get("/cows", response_model=list[CowReference])
def available_cows(limit: int = Query(default=10000, ge=1, le=10000)) -> list[CowReference]:
    try:
        return FarmXRepository().list_available_animals(limit)
    except FarmXDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Approved Farm X animal references are temporarily unavailable.") from exc


@router.post("/simulate-counterfactual", response_model=SimulationResponse)
def counterfactual_simulation(request: SimulationRequest) -> SimulationResponse:
    try:
        return run_simulation(request)
    except AnimalNotFound as exc:
        raise HTTPException(status_code=404, detail="No usable approved cow-day is available for this reference.") from exc
    except FarmXDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Counterfactual simulation is unavailable; no estimate was returned.") from exc
