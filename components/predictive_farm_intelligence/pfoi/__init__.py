"""PFOI research package: herd-dynamics and milk-yield forecasting for Farm X.

Everything here works on herd-level aggregates. Loaders in ``data`` are read-only
and configured from environment variables; the engine and estimators are pure
functions that are unit-tested on synthetic data.
"""

MODEL_VERSION = "herd-engine-0.1.0"
