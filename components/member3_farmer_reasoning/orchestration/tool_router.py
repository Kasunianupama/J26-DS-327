"""Execute one validated, allowlisted C3 tool through an injected adapter."""
from dataclasses import dataclass
from typing import Callable

from pydantic import ValidationError

from components.member3_farmer_reasoning.schemas.tool_contracts import (
    ToolCall, ToolOutcome, CoreArguments, ForecastArguments, SimulationArguments,
    CoreEvidence, ForecastEvidence, SimulationEvidence, RiskArguments, RiskEvidence,
)

INPUTS = dict(core_summary=CoreArguments, c1_forecast=ForecastArguments,
              c2_simulation=SimulationArguments, c4_risk=RiskArguments)
OUTPUTS = dict(core_summary=CoreEvidence, c1_forecast=ForecastEvidence,
               c2_simulation=SimulationEvidence, c4_risk=RiskEvidence)


@dataclass(frozen=True)
class Adapter:
    invoke: Callable
    synthetic: bool


class ToolRouter:
    """No adapters are enabled by default; never load paths supplied by a model."""
    def __init__(self, adapters=None):
        self.adapters = dict(adapters or {})
        if set(self.adapters) - set(INPUTS):
            raise ValueError('Unknown tool registration.')

    def execute(self, request):
        try:
            call = ToolCall.model_validate(request)
        except ValidationError:
            return ToolOutcome(status='invalid_request', message='Choose an approved C3 tool.')
        if call.tool == 'c4_risk' and call.arguments.get('purpose') == 'live_warning':
            return ToolOutcome(status='unavailable', tool=call.tool,
                message='C4 is connected for historical research explanation only, not live warnings.')
        try:
            arguments = INPUTS[call.tool].model_validate(call.arguments)
        except ValidationError as exc:
            missing = sorted({str(e['loc'][0]) for e in exc.errors() if e['type'] == 'missing'})
            # Never echo input values or exception messages into the response.
            return ToolOutcome(tool=call.tool,
                status='needs_input' if missing else 'invalid_request',
                missing_fields=missing,
                message='Provide the missing tool inputs.' if missing else 'Tool inputs are invalid.')
        adapter = self.adapters.get(call.tool)
        if adapter is None:
            return ToolOutcome(status='unavailable', tool=call.tool,
                message='This tool has no connected adapter. No prediction or simulation was generated.')
        try:
            raw = adapter.invoke(arguments)
        except Exception:
            return ToolOutcome(status='error', tool=call.tool,
                message='The tool failed. No substitute result was generated.')
        try:
            evidence = OUTPUTS[call.tool].model_validate(raw)
            if evidence.demo != adapter.synthetic:
                raise ValueError('Source mode mismatch.')
            if call.tool == 'core_summary':
                if evidence.topic != arguments.topic:
                    raise ValueError('Topic mismatch.')
                allowed = ({'total_animals', 'milking', 'dry'} if arguments.topic == 'herd'
                           else {'mean_daily_thi', 'max_hourly_thi'})
                if not evidence.metrics or set(evidence.metrics) - allowed:
                    raise ValueError('Metric mismatch.')
            if call.tool == 'c1_forecast':
                if (evidence.model_version != arguments.model_version
                    or evidence.origin_date > arguments.reference_date
                    or evidence.target_period < evidence.origin_date
                    or (arguments.origin_date is not None and evidence.origin_date != arguments.origin_date)
                    or any(getattr(evidence, key) != getattr(arguments, key)
                           for key in ('target_period', 'grain', 'series'))):
                    raise ValueError('Forecast provenance mismatch.')
                # Missing ranges and a point outside a range remain explicit evidence.
                if evidence.lower is None or evidence.upper is None:
                    evidence.warnings.append('Forecast bounds are incomplete; no range was invented.')
                if ((evidence.lower is not None and evidence.forecast < evidence.lower)
                    or (evidence.upper is not None and evidence.forecast > evidence.upper)):
                    evidence.warnings.append('Point forecast is outside its supplied bounds; producer review is needed.')
                evidence.warnings.append('Development model; source-data compatibility must be established before combining local records.')
            if call.tool == 'c4_risk':
                if (evidence.reference_date != arguments.reference_date
                    or evidence.assessment_date > arguments.reference_date
                    or evidence.assessment_count != 1):
                    raise ValueError('Ambiguous or future assessment.')
                evidence.warnings.append('Historical experimental research assessment; not a current alert, validated forecast or confirmed cause.')
                if evidence.research_only:
                    evidence.warnings.append('Producer marks this output as research only.')
                if not evidence.live_warning_allowed:
                    evidence.warnings.append('Producer explicitly disallows live warnings.')
                evidence.warnings.append('Source core version is not supplied; compatibility with local core is unverified.')
                evidence.warnings.append('Assessment date is not proof the result was available then; retain generation and cutoff timestamps.')
                evidence.warnings.append('Score units and category thresholds are not confirmed; do not assign an independent risk category.')
                if evidence.combined_score is None:
                    evidence.warnings.append('Combined score is missing; no replacement was calculated.')
            if call.tool == 'c2_simulation':
                if any(getattr(evidence, key) != getattr(arguments, key)
                       for key in ('intervention', 'change_percent', 'horizon_days')):
                    raise ValueError('Scenario mismatch.')
                evidence.warnings.append('Simulation result, not a measured outcome or a guaranteed effect.')
        except (ValidationError, ValueError, TypeError):
            return ToolOutcome(status='invalid_result', tool=call.tool,
                message='Tool evidence failed validation. No answer was fabricated.')
        return ToolOutcome(status='success', tool=call.tool, evidence=evidence,
            message='Synthetic test evidence only.' if adapter.synthetic else 'Validated tool evidence; retain provenance and warnings.')
