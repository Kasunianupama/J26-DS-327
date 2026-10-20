"""Leakage-aware training/evaluation tools for actual one-day Farm X forecasts."""
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from components.member1_didt.prediction.predictor import (
    CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES,
)
from components.member1_didt.services.farmx_repository import TRAINING_SQL, component_engine


@dataclass(frozen=True)
class Evaluation:
    model_version: str
    train_rows: int
    test_rows: int
    train_end_date: str
    test_start_date: str
    test_end_date: str
    model_mae_l_day: float
    model_rmse_l_day: float
    model_r2: float
    persistence_mae_l_day: float
    persistence_rmse_l_day: float


def create_estimator() -> Pipeline:
    transforms = ColumnTransformer([
        ("numeric", "passthrough", NUMERIC_FEATURES),
        ("breed", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
    ], remainder="drop", verbose_feature_names_out=False)
    return Pipeline([
        ("features", transforms),
        ("regressor", HistGradientBoostingRegressor(
            max_iter=180, max_leaf_nodes=31, l2_regularization=1.0,
            random_state=327, early_stopping=True,
        )),
    ])


def train_and_evaluate(frame: pd.DataFrame, artifact_path: str | Path,
                       max_train_rows: int = 350_000,
                       max_test_rows: int = 150_000) -> Evaluation:
    """Use a date holdout; never split rows randomly across time."""
    required = {"milk_date", "target_yield_l_day", *FEATURES}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("Training data lack required columns: " + ", ".join(missing))
    data = frame.dropna(subset=["milk_date", "target_yield_l_day", "yield_today_l_day", "days_in_milk"]).copy()
    data.replace([np.inf, -np.inf], np.nan, inplace=True)
    data.dropna(subset=["target_yield_l_day", "yield_today_l_day", "days_in_milk"], inplace=True)
    data["milk_date"] = pd.to_datetime(data["milk_date"])
    data["breed"] = data["breed"].astype("string").fillna("__MISSING__").astype(str)
    last_date = data["milk_date"].max()
    test_start = last_date - pd.Timedelta(days=179)
    train = data.loc[data["milk_date"] < test_start]
    test = data.loc[data["milk_date"] >= test_start]
    if train.empty or test.empty:
        raise ValueError("A chronological 180-day holdout cannot be formed from the available records.")
    if len(train) > max_train_rows:
        train = train.sample(n=max_train_rows, random_state=327)
    if len(test) > max_test_rows:
        test = test.sample(n=max_test_rows, random_state=327)

    estimator = create_estimator()
    estimator.fit(train[FEATURES], train["target_yield_l_day"])
    y_true = test["target_yield_l_day"].to_numpy(dtype=float)
    predicted = estimator.predict(test[FEATURES])
    persistence = test["yield_today_l_day"].to_numpy(dtype=float)
    model_version = f"farmx-one-day-hgb-v1-{last_date:%Y%m%d}"
    evaluation = Evaluation(
        model_version=model_version,
        train_rows=len(train), test_rows=len(test),
        train_end_date=train["milk_date"].max().date().isoformat(),
        test_start_date=test["milk_date"].min().date().isoformat(),
        test_end_date=test["milk_date"].max().date().isoformat(),
        model_mae_l_day=float(mean_absolute_error(y_true, predicted)),
        model_rmse_l_day=float(np.sqrt(mean_squared_error(y_true, predicted))),
        model_r2=float(r2_score(y_true, predicted)),
        persistence_mae_l_day=float(mean_absolute_error(y_true, persistence)),
        persistence_rmse_l_day=float(np.sqrt(mean_squared_error(y_true, persistence))),
    )
    output = Path(artifact_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    numeric_support = {
        feature: {
            "minimum": float(train[feature].min()) if train[feature].notna().any() else None,
            "maximum": float(train[feature].max()) if train[feature].notna().any() else None,
        }
        for feature in NUMERIC_FEATURES
    }
    known_breeds = sorted(set(train["breed"].astype(str)))
    joblib.dump({
        "estimator": estimator,
        "metadata": {
            **asdict(evaluation),
            "feature_names": FEATURES,
            "observed_numeric_support": numeric_support,
            "observed_breeds": known_breeds,
            "target": "next_calendar_day_yield_l_day",
            "source": "Farm X approved core.daily_milk, core.animal, core.weather_day",
            "scikit_learn_version": sklearn.__version__,
            "validation": "chronological 180-day holdout; persistence baseline",
            "causal_interpretation": False,
        },
    }, output, compress=3)
    return evaluation


def train_from_farmx(artifact_path: str | Path) -> Evaluation:
    """Load training rows from approved core data through the read-only c13 role."""
    try:
        frame = pd.read_sql_query(TRAINING_SQL, component_engine())
    except Exception:
        raise RuntimeError("Farm X training data could not be read via the component role.") from None
    if frame.empty:
        raise RuntimeError("No eligible consecutive-day Farm X prediction rows are available.")
    return train_and_evaluate(frame, artifact_path)
