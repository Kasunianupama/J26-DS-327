"""C3 boundary to C2's documented 1.1 HTTP API; never import or modify C2 internals."""
from datetime import date, timedelta
from math import isclose
import os
from threading import Lock
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

Reference = Annotated[str, Field(min_length=2, max_length=160, pattern=r'^A[A-Za-z0-9_-]+$')]
Numeric = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Measurement = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
Message = Annotated[str, Field(max_length=2000)]
_request_lock = Lock()


class ScenarioInput(BaseModel):
    """User supplies absolute feature values; a model never chooses the cow or numbers."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)
    animal_ref: Reference
    thi_mean: Numeric | None = Field(default=None, strict=True)
    milkings_per_day: Numeric | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode='after')
    def supported_input(self):
        if self.animal_ref == 'A_PLACEHOLDER':
            raise ValueError('An approved individual reference is required.')
        if self.thi_mean is None and self.milkings_per_day is None:
            raise ValueError('Supply at least one supported feature value.')
        return self

    def producer_request(self):
        body = dict(animal_ref=self.animal_ref, prediction_horizon_days=1, scenarios=[])
        if self.thi_mean is not None and self.milkings_per_day is not None:
            body['combined_scenario'] = dict(scenario_id='c3-combined',
                thi_mean=self.thi_mean, milkings_per_day=self.milkings_per_day)
        else:
            heat = self.thi_mean is not None
            body['scenarios'] = [dict(scenario_id='c3-single',
                category='heat' if heat else 'management',
                name='THI exposure what-if' if heat else 'Milking-frequency what-if',
                feature='thi_mean' if heat else 'milkings_per_day',
                proposed_value=self.thi_mean if heat else self.milkings_per_day,
                unit='THI' if heat else 'milkings/day')]
        return body


class Estimate(BaseModel):
    """Validate the response subset C3 consumes; preserve all producer limitations."""
    model_config = ConfigDict(extra='ignore', allow_inf_nan=False)
    scenario_id: str
    scenario_status: Literal['ESTIMATED_MODEL_INPUT_PERTURBATION', 'UNSUPPORTED_INTERVENTION_SEMANTICS',
        'BASELINE_FEATURE_UNAVAILABLE', 'OUTSIDE_TRAINING_SUPPORT', 'PREDICTION_UNAVAILABLE']
    model_support_status: Literal['PASSED', 'OUTSIDE_TRAINING_SUPPORT', 'RANGE_UNAVAILABLE', 'NOT_ASSESSED']
    baseline_predicted_milk_yield_l_day: Measurement | None = None
    counterfactual_predicted_milk_yield_l_day: Measurement | None = None
    absolute_yield_change_l_day: Numeric | None = None
    percentage_yield_change: Numeric | None = None
    model_version: str | None = None
    assumptions: list[Message] = Field(default_factory=list, max_length=80)
    data_limitations: list[Message] = Field(default_factory=list, max_length=80)
    warnings: list[Message] = Field(default_factory=list, max_length=80)
    feature: str | None = None
    category: str | None = None
    unit: str | None = None
    baseline_value: Numeric | None = None
    proposed_value: Numeric | None = None
    baseline_thi_mean: Numeric | None = None
    proposed_thi_mean: Numeric | None = None
    baseline_milkings_per_day: Measurement | None = None
    proposed_milkings_per_day: Numeric | None = None


class ProducerResponse(BaseModel):
    model_config = ConfigDict(extra='ignore', allow_inf_nan=False)
    contract_version: Literal['1.1']
    animal_ref: Reference
    observed_date: date
    observed_milk_yield_l_day: Measurement | None = None
    prediction_horizon_days: int = Field(strict=True, ge=1, le=1)
    baseline_status: Literal['AVAILABLE', 'UNAVAILABLE']
    baseline_predicted_milk_yield_l_day: Measurement | None = None
    model_version: str | None = None
    scenarios: list[Estimate] = Field(max_length=1)
    combined_scenario: Estimate | None = None
    warnings: list[Message] = Field(default_factory=list, max_length=80)


class C2Unavailable(RuntimeError):
    """Do not expose producer errors, private diagnostics or payloads in chat."""


def call_c2(request: ScenarioInput):
    """Only loopback, one fixed API path, bounded response; no retries or redirects."""
    try:
        port = int(os.environ.get('C3_C2_API_PORT', '8000'))
        if not 1 <= port <= 65535:
            raise ValueError('Invalid local port')
        if not _request_lock.acquire(blocking=False):
            raise C2Unavailable('The local simulator is busy. Please try again later.')
        try:
            with httpx.Client(trust_env=False, follow_redirects=False,
                              timeout=httpx.Timeout(45, connect=2)) as client:
                url = f'http://127.0.0.1:{port}/api/v1/interventions/simulate-counterfactual'
                with client.stream('POST', url, json=request.producer_request()) as result:
                    result.raise_for_status()
                    body = bytearray()
                    for chunk in result.iter_bytes():
                        if len(body) + len(chunk) > 1024 * 1024:
                            raise ValueError('Response exceeds local contract limit')
                        body.extend(chunk)
            # This is only local runtime memory; never log the body or cow state.
            return httpx.Response(200, content=bytes(body)).json()
        finally:
            _request_lock.release()
    except C2Unavailable:
        raise
    except Exception:
        raise C2Unavailable('The local C2 API could not return a valid response. No simulation estimate was substituted.') from None


def validate_evidence(raw, request: ScenarioInput):
    """Match cow, absolute values, units, horizon, versions and arithmetic before explaining."""
    if not isinstance(raw, dict) or raw.get('demo') is True or raw.get('synthetic') is True:
        raise ValueError('Unexpected producer mode')
    result = ProducerResponse.model_validate(raw)
    if result.animal_ref != request.animal_ref:
        raise ValueError('Wrong animal reference')
    sent = request.producer_request()
    combined = 'combined_scenario' in sent
    if combined:
        estimate = result.combined_scenario
        if result.scenarios or estimate is None or estimate.scenario_id != 'c3-combined':
            raise ValueError('Wrong combined alternative')
        if estimate.proposed_thi_mean != request.thi_mean or estimate.proposed_milkings_per_day != request.milkings_per_day:
            raise ValueError('Changed proposed values')
        proposed = dict(thi_mean=request.thi_mean, milkings_per_day=request.milkings_per_day)
        original = dict(thi_mean=estimate.baseline_thi_mean, milkings_per_day=estimate.baseline_milkings_per_day)
    else:
        if result.combined_scenario is not None or len(result.scenarios) != 1:
            raise ValueError('Wrong number of alternatives')
        estimate = result.scenarios[0]
        expected = sent['scenarios'][0]
        if any(getattr(estimate, key) != expected[key] for key in ('scenario_id', 'feature', 'category', 'unit', 'proposed_value')):
            raise ValueError('Scenario mismatch')
        proposed = {expected['feature']: expected['proposed_value']}
        original = {expected['feature']: estimate.baseline_value}
    available = (result.baseline_status == 'AVAILABLE'
        and estimate.scenario_status == 'ESTIMATED_MODEL_INPUT_PERTURBATION'
        and estimate.model_support_status == 'PASSED')
    baseline = result.baseline_predicted_milk_yield_l_day
    if result.baseline_status == 'UNAVAILABLE' and baseline is not None:
        raise ValueError('Unavailable baseline contains a prediction')
    if available:
        predicted = estimate.counterfactual_predicted_milk_yield_l_day
        change = estimate.absolute_yield_change_l_day
        if baseline is None or predicted is None or change is None or not result.model_version:
            raise ValueError('Incomplete available estimate')
        if estimate.model_version != result.model_version or estimate.baseline_predicted_milk_yield_l_day != baseline:
            raise ValueError('Different baseline or model')
        if any(value is None for value in original.values()) or not isclose(predicted - baseline, change, abs_tol=1e-6):
            raise ValueError('Missing feature or inconsistent difference')
        percent = estimate.percentage_yield_change
        if (baseline == 0 and percent is not None) or (baseline > 0 and
                (percent is None or not isclose(change / baseline * 100, percent, abs_tol=1e-6))):
            raise ValueError('Inconsistent percentage')
    warnings = list(dict.fromkeys(result.warnings + estimate.data_limitations + estimate.warnings + [
        'Observational model-input what-if only; not a causal effect, guaranteed benefit or management recommendation.',
        'Costs, welfare and operational feasibility have not been validated.',
        'Source core version and an uncertainty interval are not supplied by C2; compatibility with other component outputs is unverified.',
        'The baseline uses the latest usable recorded cow-day, not necessarily current conditions.',
    ]))
    if not available and estimate.model_support_status == 'RANGE_UNAVAILABLE':
        warnings.append('C3 withheld the what-if estimate because its training support could not be checked.')
    evidence = dict(kind='c2_live_simulation', demo=False, source='c2_api',
        contract_version=result.contract_version, model_version=result.model_version,
        source_core_version=None, animal_ref=result.animal_ref,
        observed_date=result.observed_date.isoformat(),
        target_period=(result.observed_date + timedelta(days=1)).isoformat(),
        prediction_horizon_days=1, observed_milk_yield_l_day=result.observed_milk_yield_l_day,
        baseline_predicted_milk_yield_l_day=baseline,
        counterfactual_predicted_milk_yield_l_day=estimate.counterfactual_predicted_milk_yield_l_day if available else None,
        absolute_yield_change_l_day=estimate.absolute_yield_change_l_day if available else None,
        percentage_yield_change=estimate.percentage_yield_change if available else None,
        scenario_status=estimate.scenario_status, model_support_status=estimate.model_support_status,
        original_inputs=original, proposed_inputs=proposed,
        operational_feasibility_validated=False, assumptions=estimate.assumptions)
    return dict(available=available, evidence=evidence, warnings=warnings)


def simulate(request: ScenarioInput, *, invoke=None):
    return validate_evidence((invoke or call_c2)(request), request)
