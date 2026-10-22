"""USER-RUN read-only diagnostic; no publication or database write path."""
import argparse
from datetime import date, datetime, timezone
from getpass import GetPassWarning, getpass
import json
import os
from pathlib import Path
import sys
import warnings

from components.member4_crisis_forecasting.services.aggregate_calibration import CalibrationPlan, compare_calibration
from components.member4_crisis_forecasting.services.research_outputs_local import read_research_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Existing reviewed research configuration; never overwritten')
    parser.add_argument('--reference-start', type=date.fromisoformat, required=True)
    parser.add_argument('--reference-end', type=date.fromisoformat, required=True)
    parser.add_argument('--comparison-start', type=date.fromisoformat, required=True)
    parser.add_argument('--comparison-end', type=date.fromisoformat, required=True)
    parser.add_argument('--upper-percentile', type=float, required=True, help='Predeclared experimental percentile, not a validated clinical threshold')
    parser.add_argument('--minimum-days', type=int, required=True)
    parser.add_argument('--new-version', required=True)
    parser.add_argument('--recording-regime-note', required=True)
    parser.add_argument('--candidate-config', help='Optional NEW private JSON path outside repository; config only, no records')
    args = parser.parse_args(argv)
    try:
        plan = CalibrationPlan.model_validate({key: getattr(args, key) for key in CalibrationPlan.model_fields})
        config = read_research_config(args.config)
        destination = None
        if args.candidate_config:
            destination = Path(args.candidate_config).resolve()
            repository = Path(__file__).resolve().parents[3]
            if (destination.suffix.lower() != '.json' or destination == repository or repository in destination.parents
                    or destination.exists() or not destination.parent.is_dir()):
                raise ValueError('new_private_config_path_required')
        if not sys.stdin.isatty(): raise ValueError('interactive_terminal_required')
        now = datetime.now(timezone.utc)
        if plan.comparison_end > now.date(): raise ValueError('future_comparison_not_allowed')
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            password = getpass('Local farmx_c4 password (hidden, no .env reader): ')
        from components.member4_crisis_forecasting.data_access.local_training_loader import load_approved_days
        rows = load_approved_days(host=os.environ.get('C4_DB_HOST', 'localhost'),
            port=int(os.environ.get('C4_DB_PORT', '5432')), password=password, test_end=plan.comparison_end)
        del password
        report, candidate = compare_calibration(rows, config, plan, generated_at=now, data_kind='published')
        report['candidate_configuration_file'] = 'not_requested'
        if destination:
            if candidate is None:
                report['candidate_configuration_file'] = 'not_written_proposal_unavailable'
            else:
                with destination.open('x', encoding='utf-8') as handle:
                    json.dump(candidate.model_dump(mode='json'), handle, indent=2, allow_nan=False)
                report['candidate_configuration_file'] = 'new_configuration_only_written_no_records'
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled'})); return 130
    except Exception:
        print(json.dumps({'status': 'diagnostic_failed', 'reason': 'Check reviewed config, prior reference/later comparison, explicit percentile/support, new private config path and local read permissions. No records or credentials printed.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
