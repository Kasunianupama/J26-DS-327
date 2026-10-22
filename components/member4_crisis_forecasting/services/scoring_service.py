"""Component-only orchestration; callers supply validated inputs and metadata."""

from components.member4_crisis_forecasting.climate.environmental_risk import assess_climate
from components.member4_crisis_forecasting.biological_risk.biological_assessment import assess_biological_inputs
from components.member4_crisis_forecasting.operational_risk.operational_consistency import assess_operational_inputs
from components.member4_crisis_forecasting.farm_risk.dairy_risk_score import build_farm_risk_output


def assess_and_score(*, climate_input=None, climate_config=None, climate_baseline=None,
                     biological_input=None, operational_input=None, **output_arguments):
    cutoff = output_arguments["assessment_cutoff"]
    if climate_input is not None and climate_config is None:
        raise ValueError("explicit_climate_configuration_required")
    return build_farm_risk_output(
        climate=assess_climate(climate_input, cutoff, climate_config, climate_baseline) if climate_input is not None else None,
        biological=assess_biological_inputs(biological_input, cutoff) if biological_input is not None else None,
        operational=assess_operational_inputs(operational_input, cutoff) if operational_input is not None else None,
        **output_arguments,
    )
