"""Load-only predictor for a model trained and evaluated from actual Farm X rows."""
import os
from pathlib import Path
from typing import Protocol

import pandas as pd
import sklearn

from components.member1_didt.schemas.counterfactual import CowState


FEATURES = [
    "yield_today_l_day", "days_in_milk", "lactation_no", "milkings_per_day",
    "dry_matter_intake", "concentrate_intake", "bcs", "body_weight",
    "rectal_temperature", "thi_mean", "breed",
]
NUMERIC_FEATURES = [feature for feature in FEATURES if feature != "breed"]
CATEGORICAL_FEATURES = ["breed"]


class PredictorUnavailable(RuntimeError):
    """Raised when a compatible Farm X model artifact is not installed."""


class MilkYieldPredictor(Protocol):
    model_version: str
    def predict(self, state: CowState, horizon_days: int = 1) -> float: ...


class FarmXMilkYieldPredictor:
    """One-day-ahead observational predictor; it does not estimate causal effects."""
    def __init__(self, artifact_path: str | Path | None = None):
        self.artifact_path = Path(artifact_path or os.getenv(
            "DIDT_MODEL_PATH",
            Path(__file__).parent / "artifacts" / "farmx_milk_yield.joblib",
        ))
        if not self.artifact_path.is_file():
            raise PredictorUnavailable("No evaluated Farm X milk-yield model artifact is installed.")
        try:
            import joblib
            artifact = joblib.load(self.artifact_path)
            self.estimator = artifact["estimator"]
            self.metadata = artifact["metadata"]
            artifact_sklearn = self.metadata.get("scikit_learn_version")
            if artifact_sklearn != sklearn.__version__:
                raise PredictorUnavailable("The model artifact requires a different scikit-learn version.")
            self.model_version = self.metadata["model_version"]
        except Exception as exc:
            raise PredictorUnavailable("The configured Farm X model artifact could not be loaded.") from exc

    def predict(self, state: CowState, horizon_days: int = 1) -> float:
        if horizon_days != 1:
            raise PredictorUnavailable("The installed model supports a one-day prediction horizon only.")
        if state.milk_yield_l_day is None or state.days_in_milk is None:
            raise PredictorUnavailable("Current yield and days in milk are required by this model.")
        row = {
            "yield_today_l_day": state.milk_yield_l_day,
            "days_in_milk": state.days_in_milk,
            "lactation_no": state.lactation_no,
            "milkings_per_day": state.milkings_per_day,
            "dry_matter_intake": state.dry_matter_intake,
            "concentrate_intake": state.concentrate_intake,
            "bcs": state.bcs,
            "body_weight": state.body_weight,
            "rectal_temperature": state.rectal_temperature,
            "thi_mean": state.thi_mean,
            # Training encodes missing breed with this explicit sentinel; it is
            # a preprocessing category, not an imputed biological observation.
            "breed": state.breed if state.breed is not None else "__MISSING__",
        }
        frame = pd.DataFrame([row], columns=FEATURES)
        prediction = float(self.estimator.predict(frame)[0])
        if not pd.notna(prediction) or prediction < 0:
            raise PredictorUnavailable("The model returned an invalid milk-yield estimate.")
        return prediction
