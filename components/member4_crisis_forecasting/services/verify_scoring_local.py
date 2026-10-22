"""USER-RUN ONLY: read-only local score verification, aggregate stdout only."""

import argparse
from datetime import date, datetime, timezone
from getpass import GetPassWarning, getpass
import json
import os
from pathlib import Path
import sys
import warnings

from components.member4_crisis_forecasting.schemas.scoring_verification import VerificationConfig, VerificationMetadata
from components.member4_crisis_forecasting.services.scoring_verification import verify_scoring


def read_documents(config_path, metadata_path):
    """Explicit JSON documents only. Never discover files or load .env."""
    def unique_keys(pairs):
        document = {}
        for key, value in pairs:
            if key in document:
                raise ValueError("duplicate_json_keys")
            document[key] = value
        return document
    def read_json(path):
        resolved = Path(path).resolve()
        if resolved.suffix.lower() != ".json":
            raise ValueError("explicit_json_document_required")
        return json.loads(resolved.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    return (VerificationConfig.model_validate(read_json(config_path)),
            VerificationMetadata.model_validate(read_json(metadata_path)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Research-only scoring verification; no training or publishing.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)
    try:
        if args.start_date > args.end_date:
            raise ValueError("invalid_date_range")
        config, metadata = read_documents(args.config, args.metadata)
        if not sys.stdin.isatty():
            print(json.dumps({"status": "interactive_terminal_required"}))
            return 2
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Local farmx_c4 password (hidden): ")
        from components.member4_crisis_forecasting.data_access.local_training_loader import load_approved_days
        rows = load_approved_days(host=os.environ.get("C4_DB_HOST", "localhost"),
                                  port=int(os.environ.get("C4_DB_PORT", "5432")),
                                  password=password, test_end=args.end_date)
        del password
        summary = verify_scoring(rows, config, metadata, start_date=args.start_date, end_date=args.end_date,
                                 data_kind="published", generated_at=datetime.now(timezone.utc))
        print(json.dumps(summary, allow_nan=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled"}))
        return 130
    except Exception:
        # No input values, dates, credentials, driver details, or tracebacks.
        print(json.dumps({"status": "scoring_verification_failed",
                          "reason": "Review JSON contracts, date range, approved input types, and local read-only connection settings privately."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
