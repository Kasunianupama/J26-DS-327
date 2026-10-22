"""Build final V3 from frozen, validated V2 historical inputs; no data access."""
import hashlib
import json
from uuid import UUID, uuid5
from collections import Counter
from components.member4_crisis_forecasting.schemas.risk_output import validate_research_output, DomainScore
from components.member4_crisis_forecasting.schemas.v3_output import V3Output, V3Configuration, VERSION, ALARMS
from components.member4_crisis_forecasting.services.aggregate_calibration import distribution

NAMESPACE = UUID('101bbacc-1146-4990-aada-78fea00dc5aa')


def generate_v3(payloads, *, generated_at):
    sources = [validate_research_output(p) for p in payloads]
    if len({s.assessment_date for s in sources}) != len(sources): raise ValueError('duplicate_source_dates')
    if len({s.scoring_config.version for s in sources}) > 1: raise ValueError('mixed_source_versions')
    outputs = []
    for source in sorted(sources, key=lambda s: s.assessment_date):
        if source.contract_version != '1.1.0' or source.provenance.source != 'published': raise ValueError('published_descriptive_v2_required')
        original = next(d for d in source.domains if d.domain == 'operational')
        if len(original.indicators) != 2 or {i.feature for i in original.indicators} != ALARMS:
            raise ValueError('exactly_two_alarm_indicators_required')
        scores = [i.score for i in original.indicators if i.score is not None]
        operational = DomainScore(**{**original.model_dump(), 'score': sum(scores)/2 if len(scores)==2 else None,
            'explanation': 'Arithmetic mean of blood and conductivity alarm indicator scores using unchanged calibrated source rules.'})
        climate = next(d for d in source.domains if d.domain == 'climate')
        cfg = V3Configuration(source_scoring_version=source.scoring_config.version,
            climate_rules=source.scoring_config.climate_rules, operational_rules=source.scoring_config.operational_rules,
            medium_starts_at=source.scoring_config.medium_starts_at, high_starts_at=source.scoring_config.high_starts_at)
        domains = (climate, operational)
        contributions = {d.domain: None if d.score is None else d.score/2 for d in domains}
        count = sum(d.score is not None for d in domains)
        combined = sum(contributions.values()) if count == 2 else None
        category = 'unavailable' if combined is None else 'high_provisional' if combined >= cfg.high_starts_at else 'medium_provisional' if combined >= cfg.medium_starts_at else 'low_provisional'
        canonical = json.dumps(source.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        outputs.append(V3Output(output_id=uuid5(NAMESPACE, f'FARM_X:{VERSION}:{source.assessment_date}'),
            source_output_id=source.output_id, source_payload_sha256=digest,
            assessment_date=source.assessment_date, generated_at=generated_at, scoring_config=cfg,
            provenance=source.provenance, domains=domains, contributions=contributions, combined_score=combined,
            risk_category=category, available_domains=count,
            data_completeness='complete' if count==2 else 'partial' if any(d.available_indicators for d in domains) else 'unavailable',
            explanations=('Provisional historical two-domain research model, not clinically validated or a live warning.',
                          'Climate and calibrated alarm indicator values/rules are retained from the referenced stored V2 assessment.',
                          'Operational Risk averages two alarm indicator scores; Combined Risk equally averages Climate and Operational Risk.',
                          'Missing required inputs are unavailable, never zero-filled; original recording completeness and availability remain unverified.')))
    return tuple(outputs), dict(scoring_version=VERSION, contract_version='3.0.0', research_only=True,
        live_warning_allowed=False, assessment_days=len(outputs), missing_calendar_days=232-len(outputs),
        eligible_complete_assessments=sum(o.combined_score is not None for o in outputs),
        distributions={name: distribution([o.combined_score if name=='combined' else next(d.score for d in o.domains if d.domain==name) for o in outputs]) for name in ('climate','operational','combined')},
        operational_at_100=sum(o.domains[1].score==100 for o in outputs),
        categories=dict(Counter(o.risk_category for o in outputs)), publication='not_requested_no_writes')
