"""USER-RUN ONLY. Read-only verification by default; no fitting or model saving."""

import argparse
from datetime import date, datetime, timedelta, timezone
from getpass import GetPassWarning, getpass
import json
import os
import sys
import warnings

from components.member4_crisis_forecasting.prediction.research_prediction import load_trusted_artifact, predict_research_history

PREDICTION_OBJECT = "c4_output.milk_decline_prediction_v1"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Experimental retrospective prediction verification, not live forecasting.")
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--trust-local-artifact", action="store_true", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--publish-approved", action="store_true")
    parser.add_argument("--approved-object")
    args = parser.parse_args(argv)
    try:
        if args.start_date > args.end_date:
            raise ValueError("invalid_date_range")
        if args.publish_approved != (args.approved_object == PREDICTION_OBJECT):
            raise ValueError("publication_requires_separate_explicit_flags")
        if args.approved_object is not None and not args.publish_approved:
            raise ValueError("unexpected_approval_object")
        bundle, digest = load_trusted_artifact(args.artifact_path, trust_local_artifact=args.trust_local_artifact)
        if bundle["research_metadata"]["data_kind"] != "published":
            raise ValueError("real_predictions_require_real_data_trained_artifact")
        if not sys.stdin.isatty():
            raise ValueError("interactive_terminal_required")
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Local farmx_c4 password (hidden): ")
        host, port = os.environ.get("C4_DB_HOST", "localhost"), int(os.environ.get("C4_DB_PORT", "5432"))
        from components.member4_crisis_forecasting.data_access.local_training_loader import load_approved_days
        now = datetime.now(timezone.utc)
        # Read prior history and at most seven outcome days through today's date.
        # These future actuals are annotations only and cannot enter X.
        rows = load_approved_days(host=host, port=port, password=password,
                                  test_end=min(args.end_date + timedelta(days=7), now.date()))
        outputs, summary = predict_research_history(rows, bundle, digest, start_date=args.start_date,
                end_date=args.end_date, generated_at=now, data_kind="published")
        summary["publication"] = "not_requested_no_writes"
        if args.publish_approved:
            from components.member4_crisis_forecasting.output.prediction_publication import publish_approved_predictions
            count = publish_approved_predictions(outputs, approved_object=args.approved_object, host=host, port=port, password=password)
            summary["publication"] = dict(status="approved_predictions_committed", inserted_count=count)
        del password
        print(json.dumps(summary, allow_nan=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled"}))
        return 130
    except Exception:
        print(json.dumps({"status": "research_prediction_failed", "reason": "Review trusted artifact compatibility, date range, source, local read-only connection, or separately approved prediction-table readiness privately. No rows or credentials printed."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
