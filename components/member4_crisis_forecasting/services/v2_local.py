"""USER-RUN V2 verification by default; publication requires separate approval flags."""
import argparse
from datetime import datetime, timezone
from getpass import GetPassWarning, getpass
import json
import os
import sys
import warnings
from components.member4_crisis_forecasting.services.research_outputs_local import read_research_config
from components.member4_crisis_forecasting.services.v2_outputs import END, generate_v2
from components.member4_crisis_forecasting.output.v2_publication import OBJECT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--baseline-config', required=True)
    parser.add_argument('--publish-approved', action='store_true')
    parser.add_argument('--approved-object')
    args = parser.parse_args(argv)
    try:
        if args.publish_approved != (args.approved_object == OBJECT) or (args.approved_object and not args.publish_approved):
            raise ValueError('explicit_v2_approval_flags_required')
        candidate, baseline = read_research_config(args.config), read_research_config(args.baseline_config)
        from components.member4_crisis_forecasting.services.v2_outputs import validate_v2_config
        validate_v2_config(candidate, baseline)
        if not sys.stdin.isatty(): raise ValueError('interactive_terminal_required')
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            password = getpass('Local farmx_c4 password (hidden): ')
        host, port = os.environ.get('C4_DB_HOST', 'localhost'), int(os.environ.get('C4_DB_PORT', '5432'))
        from components.member4_crisis_forecasting.data_access.local_training_loader import load_approved_days
        rows = load_approved_days(host=host, port=port, password=password, test_end=END)
        outputs, summary = generate_v2(rows, candidate, baseline, generated_at=datetime.now(timezone.utc), data_kind='published')
        if args.publish_approved:
            from components.member4_crisis_forecasting.output.v2_publication import publish_v2
            summary['publication'] = publish_v2(outputs, approved_object=args.approved_object, host=host, port=port, password=password)
        del password
        print(json.dumps(summary, allow_nan=False, indent=2)); return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled'})); return 130
    except Exception:
        print(json.dumps({'status': 'v2_workflow_failed', 'reason': 'Check candidate/baseline compatibility, local read permissions, or separately approved V2 table readiness/conflicting existing version. No records or credentials printed.'})); return 2


if __name__ == '__main__': main()
