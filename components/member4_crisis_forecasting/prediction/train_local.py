"""USER-RUN ONLY: python -m ...prediction.train_local (see Member 4 README)."""

import argparse
from datetime import date
from getpass import GetPassWarning, getpass
import json
import os
import sys
import warnings

from components.member4_crisis_forecasting.prediction.chronological_training import ExperimentConfig, run_experiment


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local retrospective research; not point-in-time validation.")
    parser.add_argument("--acknowledge-retrospective-limitations", action="store_true", required=True)
    parser.add_argument("--milk-source", choices=("shipment", "delpro"), required=True)
    parser.add_argument("--decline-threshold-pct", type=float, required=True)
    parser.add_argument("--decision-threshold", type=float, required=True)
    parser.add_argument("--class-weight", choices=("none", "balanced_subsample"), default="none")
    parser.add_argument("--threshold-selection", choices=("fixed", "validation_f1", "validation_f1_legacy"), default="fixed")
    parser.add_argument("--forest-comparison", choices=("fixed", "validation_small"), default="fixed")
    parser.add_argument("--feature-set", choices=("integrated", "production_only"), default="integrated")
    for name in ("train-end", "validation-end", "test-end"):
        parser.add_argument(f"--{name}", type=date.fromisoformat, required=True)
    parser.add_argument("--min-train-samples", type=int, default=30)
    parser.add_argument("--artifact-path", help="Optional NEW private .pkl file outside the repository; no overwrite.")
    args = parser.parse_args(argv)
    try:
        config_values = {
            key: value for key, value in vars(args).items()
            if key not in {"acknowledge_retrospective_limitations", "artifact_path"}
        }
        if config_values["class_weight"] == "none":
            config_values["class_weight"] = None
        config = ExperimentConfig(**config_values)
        artifact_callback = None
        saved = []
        if args.artifact_path:
            from components.member4_crisis_forecasting.prediction.model_artifact import validate_artifact_destination, save_model_artifact
            destination = validate_artifact_destination(args.artifact_path)
            def artifact_callback(bundle):
                save_model_artifact(bundle, destination)
                saved.append(True)
        host = os.environ.get("C4_DB_HOST", "localhost")
        port = int(os.environ.get("C4_DB_PORT", "5432"))
        # Interactive prompt: password is absent from command history and outputs.
        # getpass must have a terminal; never fall back to echoing a password.
        if not sys.stdin.isatty():
            print(json.dumps({"status": "interactive_terminal_required"}))
            return 2
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Local farmx_c4 password (hidden): ")
        from components.member4_crisis_forecasting.data_access.local_training_loader import load_approved_days
        rows = load_approved_days(host=host, port=port, password=password, test_end=config.test_end)
        del password
        if artifact_callback is None:
            summary = run_experiment(rows, config, data_kind="published")
        else:
            summary = run_experiment(rows, config, data_kind="published", artifact_callback=artifact_callback)
            summary["artifact_save_status"] = "saved_private_research_artifact" if saved else "not_saved_no_fitted_model"
        print(json.dumps(summary, allow_nan=False, indent=2))
        return 0 if summary["status"] == "evaluated_retrospectively" else 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled"}))
        return 130
    except Exception:
        # Never print driver errors, DSNs, validation inputs, or tracebacks.
        print(json.dumps({"status": "local_workflow_failed",
                          "reason": "Check connection, approved column types, configuration, and installed dependencies locally. No records were printed."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
