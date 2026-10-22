"""User-run aggregate-only verification. No publication path."""
import argparse
from datetime import date, datetime
from getpass import GetPassWarning, getpass
import json
import os
import sys
import warnings

from .c1_integration import assess_c1_context, aggregate_summary
from ..data_access.c1_forecast_loader import load_c1_forecasts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-authorized-c1-read", action="store_true", required=True)
    parser.add_argument("--assessment-date", type=date.fromisoformat, required=True)
    parser.add_argument("--origin-date", type=date.fromisoformat, required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--core-version")
    parser.add_argument("--assessed-at", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    try:
        if args.assessed_at.tzinfo is None or not sys.stdin.isatty():
            raise ValueError("aware_cutoff_and_interactive_terminal_required")
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Local farmx_c4 password (hidden): ")
        rows = load_c1_forecasts(host=os.environ.get("C4_DB_HOST", "localhost"),
                                port=int(os.environ.get("C4_DB_PORT", "5432")),
                                password=password, origin_date=args.origin_date,
                                model_version=args.model_version)
        del password
        context = assess_c1_context(rows, assessment_date=args.assessment_date,
                assessed_at=args.assessed_at, origin_date=args.origin_date,
                model_version=args.model_version, core_version=args.core_version)
        print(json.dumps(aggregate_summary([context]), allow_nan=False, indent=2))
        return 0
    except Exception:
        print(json.dumps(dict(status="verification_failed", reason="Review authorized C1 SELECT access, contract, explicit run and cutoff locally. No fallback or writes.")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
