"""Build a local historical C3 briefing from aggregates, without LLM calls."""
import json
from datetime import date
from pathlib import Path

from .aggregate_repository import read_context
from .data_readiness import connection_settings


def build_brief(context, *, today=None):
    """Keep milk sources separate; suppress changes over incomplete/gap periods."""
    today = today or date.today()
    herd = context['herd']
    observed = herd['observed_date']
    current, previous = context['current_period'], context['previous_period']
    warnings = []
    if observed < today:
        warnings.append(f'Historical records end on {observed}; these are not current farm conditions.')
    if context['balance_failing_months']:
        warnings.append(f"{context['balance_failing_months']} months fail ETL herd-balance acceptance; herd counts are reconstructed and require review.")
    milk = {}
    for source, count_field, total_field in (
        ('delpro', 'delpro_days', 'delpro_litres'),
        ('shipments', 'shipment_days', 'shipment_litres'),
    ):
        usable = all(p['observed_days'] == 7 and p['gap_days'] == 0
                     and p[count_field] == 7 and p[total_field] is not None
                     for p in (current, previous))
        baseline = previous[total_field]
        change = (float(current[total_field] - baseline) / float(baseline) * 100
                  if usable and baseline > 0 else None)
        milk[source] = dict(current_litres=current[total_field],
                            previous_litres=baseline,
                            current_observed_days=current[count_field],
                            previous_observed_days=previous[count_field],
                            change_pct=change)
        if change is None:
            warnings.append(f'{source}: weekly change unavailable because coverage, gap flags or a positive baseline do not support comparison.')
    if context['weather']['complete_days'] != 7:
        warnings.append('Weather coverage is incomplete for the latest seven-day period.')
    return dict(source='published_core_aggregates', demo=False,
                core_version=context['core_version'], observed_date=observed,
                latest_period=dict(start=current['start'], end=current['end']),
                previous_period=dict(start=previous['start'], end=previous['end']),
                herd=herd, milk=milk, historical_weather=context['weather'], milk_daily=context.get('milk_daily'),
                warnings=warnings,
                interpretation='DelPro and shipment measurements remain separate. Historical weather is reanalysis. No forecast, diagnosis or causal explanation is inferred.',
                teammate_models='Not connected; no model predictions are included.')


def main():
    # Only this explicit operator-run entry point loads private local settings.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / '.env', override=False)
    try:
        settings = connection_settings()
        brief = build_brief(read_context(settings))
        output = json.dumps(brief, default=str, indent=2, allow_nan=False)
    except Exception:
        print('C3 briefing unavailable: check local configuration, published coverage and permissions. No demo fallback was used.')
        return 1
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
