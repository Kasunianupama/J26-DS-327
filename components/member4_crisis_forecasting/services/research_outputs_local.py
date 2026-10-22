"""User-run descriptive calculation; publication is a separate explicit opt-in."""

import argparse
from datetime import date, datetime, timezone
from getpass import GetPassWarning, getpass
import json
import os
from pathlib import Path
import sys
import warnings

from components.member4_crisis_forecasting.output.publisher import APPROVAL_OBJECT
from components.member4_crisis_forecasting.services.retrospective_scoring import RetrospectiveResearchConfig, calculate_research_outputs


def read_research_config(path):
    path = Path(path).resolve()
    if path.suffix.lower() != ".json":
        raise ValueError("explicit_json_configuration_required")
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_configuration_keys")
            result[key] = value
        return result
    return RetrospectiveResearchConfig.model_validate(json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Provisional descriptive research outputs, not quality-verified live warnings.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 12, 31))
    parser.add_argument("--publish-approved", action="store_true")
    parser.add_argument("--approved-object")
    args = parser.parse_args(argv)
    try:
        if args.publish_approved != (args.approved_object == APPROVAL_OBJECT):
            raise ValueError("publication_requires_both_explicit_flags")
        if args.approved_object is not None and not args.publish_approved:
            raise ValueError("unexpected_publication_approval")
        if not date(2025, 1, 1) <= args.start_date <= args.end_date <= date(2026, 12, 31):
            raise ValueError("research_dates_must_be_within_2025_2026")
        config = read_research_config(args.config)
        if not sys.stdin.isatty():
            raise ValueError("interactive_terminal_required")
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Local farmx_c4 password (hidden): ")
        host, port = os.environ.get("C4_DB_HOST", "localhost"), int(os.environ.get("C4_DB_PORT", "5432"))
        from components.member4_crisis_forecasting.data_access.local_training_loader import load_approved_days
        rows = load_approved_days(host=host, port=port, password=password, test_end=args.end_date)
        outputs, summary = calculate_research_outputs(rows, config, start_date=args.start_date, end_date=args.end_date,
            generated_at=datetime.now(timezone.utc), data_kind="published")
        summary["publication"] = "not_requested_no_writes"
        if args.publish_approved:
            from components.member4_crisis_forecasting.output.local_publication import publish_approved_batch
            inserted = publish_approved_batch(outputs, approved_object=args.approved_object, host=host, port=port, password=password)
            summary["publication"] = dict(status="approved_batch_committed", inserted_count=inserted)
        del password
        print(json.dumps(summary, allow_nan=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled"}))
        return 130
    except Exception:
        print(json.dumps({"status": "research_workflow_failed", "reason": "Review local configuration, approval flags, read-only input permissions, or separately approved output table privately. No records or credentials printed."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
