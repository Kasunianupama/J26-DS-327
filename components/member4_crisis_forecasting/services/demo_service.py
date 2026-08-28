from shared.schemas.risk import DairyRiskScore, NationalDairyRiskIndex

def farm_risk(farm_id: str) -> DairyRiskScore:
    return DairyRiskScore(farm_id=farm_id, score=36, level="medium", drivers=["warm weather outlook", "routine variance"])

def national_risk() -> NationalDairyRiskIndex:
    return NationalDairyRiskIndex(score=31, level="medium", farms_considered=3)

