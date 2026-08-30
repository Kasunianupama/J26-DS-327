from fastapi import APIRouter
from shared.schemas.farm import Farm
router = APIRouter(prefix="/farms", tags=["farms"])
@router.get("/{farm_id}/summary")
def summary(farm_id: str) -> dict:
    return {"farm": Farm(id=farm_id, name="NLDB Ridiyagama Farm", herd_size=48), "milk_yield_litres": 612.4, "data_notice": "All values are synthetic demonstration data."}
