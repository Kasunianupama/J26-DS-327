"""Explicit training-only median imputation with fixed missing indicators."""

import numpy as np
from sklearn.impute import SimpleImputer


class TrainingFeaturePreprocessor:
    """Drop all-missing training value columns; never learn from later splits.

    A missing indicator is appended for EVERY raw feature, including those that
    first become missing after training. Dropped values have no learned signal.
    """

    def fit(self, x, feature_names):
        values = np.asarray(x, dtype=float)
        self.feature_names = tuple(feature_names)
        if values.ndim != 2 or values.shape[1] != len(self.feature_names) or not len(values):
            raise ValueError("invalid_training_features")
        self.active = ~np.isnan(values).all(axis=0)
        self.imputer = SimpleImputer(strategy="median")
        self.imputer.fit(values[:, self.active])
        self.output_names = tuple(name for name, active in zip(self.feature_names, self.active) if active) + tuple(
            f"{name}__missing" for name in self.feature_names
        )
        return self

    def transform(self, x):
        values = np.asarray(x, dtype=float)
        if values.ndim != 2 or values.shape[1] != len(self.feature_names):
            raise ValueError("invalid_feature_dimensions")
        return np.column_stack((self.imputer.transform(values[:, self.active]), np.isnan(values).astype(float)))

    def report(self):
        return dict(
            strategy="training_only_median_with_missing_indicators",
            dropped_all_missing_training_features=[name for name, active in zip(self.feature_names, self.active) if not active],
            output_feature_names=list(self.output_names),
        )


def feature_coverage(x, feature_names):
    values = np.asarray(x, dtype=float).reshape((-1, len(feature_names)))
    n = len(values)
    return {
        name: dict(observed_samples=int(np.isfinite(values[:, index]).sum()),
                   missing_samples=int(np.isnan(values[:, index]).sum()),
                   observed_fraction=float(np.isfinite(values[:, index]).mean()) if n else None,
                   observed_days_sum=float(values[:, index].sum()) if name.endswith("_observed_days_7d") else None,
                   possible_days=7 * n if name.endswith("_observed_days_7d") else None)
        for index, name in enumerate(feature_names)
    }
