"""ML-based bottleneck / delay prediction from historical execution logs."""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, f1_score, roc_auc_score

from config import Config


class BottleneckPredictor:
    """Predict per-run bottleneck risk using task thresholds and a Random Forest model."""

    MAX_TRAIN_ROWS = 20_000
    MAX_TEST_ROWS = 20_000
    FEATURES = [
        "cpu",
        "mem",
        "io",
        "latency",
        "dep_count",
        "hour",
        "dow",
        "task_code",
        "prev_dur_mean5",
        "prev_cpu_mean5",
    ]

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.model = RandomForestClassifier(
            n_estimators=self.cfg.rf_estimators,
            class_weight="balanced",
            min_samples_leaf=max(1, int(self.cfg.rf_min_samples_leaf)),
            n_jobs=-1,
            random_state=self.cfg.random_state,
        )
        self.task_thresholds: Dict[str, float] = {}
        self.task_codes: Dict[str, int] = {}
        self.global_threshold: float = 0.0

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Feature engineering with lag features computed using only past rows."""
        c = self.cfg
        columns = [
            c.col_timestamp,
            c.col_task,
            c.col_duration,
            c.col_cpu,
            c.col_memory,
            c.col_io,
            c.col_latency,
            c.col_deps,
        ]
        d = df.loc[:, columns].sort_values(c.col_timestamp).copy()
        ts = pd.to_datetime(d[c.col_timestamp])

        d["cpu"] = d[c.col_cpu]
        d["mem"] = d[c.col_memory]
        d["io"] = d[c.col_io]
        d["latency"] = d[c.col_latency]

        deps = d[c.col_deps].fillna("").astype(str)
        split_deps = deps.str.split(",")
        dep_count = split_deps.str.len()
        d["dep_count"] = dep_count.where(~deps.isin(("", "0", "[]")), 0)

        d["hour"] = ts.dt.hour
        d["dow"] = ts.dt.dayofweek

        if not self.task_codes:
            task_series = d[c.col_task].astype(str)
            self.task_codes = {t: i for i, t in enumerate(sorted(task_series.unique()))}

        d["task_code"] = d[c.col_task].astype(str).map(self.task_codes).fillna(-1).astype(int)

        g = d.groupby(c.col_task)
        d["prev_dur_mean5"] = g[c.col_duration].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        d["prev_cpu_mean5"] = g[c.col_cpu].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        d[["prev_dur_mean5", "prev_cpu_mean5"]] = d[["prev_dur_mean5", "prev_cpu_mean5"]].fillna(0.0)
        return d

    def _label(self, d: pd.DataFrame) -> pd.Series:
        thr = d[self.cfg.col_task].map(self.task_thresholds).fillna(self.global_threshold)
        return (d[self.cfg.col_duration] > thr).astype(int)

    def _positive_probability(self, features: pd.DataFrame) -> np.ndarray:
        probabilities = self.model.predict_proba(features)
        classes = self.model.classes_
        positive_class = np.flatnonzero(classes == 1)
        if positive_class.size == 0:
            return np.zeros(len(features), dtype=float)
        return probabilities[:, positive_class[0]].astype(float)

    def train(self, df: pd.DataFrame) -> Dict[str, Any]:
        c = self.cfg
        if not 0 < c.test_fraction < 1:
            raise ValueError("test_fraction must be greater than 0 and less than 1.")
        d = self._prepare(df)
        if len(d) < 2:
            raise ValueError("At least two valid rows are required to train the bottleneck model.")

        split = min(max(1, int(len(d) * (1 - c.test_fraction))), len(d) - 1)
        train, test = d.iloc[:split], d.iloc[split:]
        self.task_thresholds = train.groupby(c.col_task)[c.col_duration].quantile(c.bottleneck_quantile).to_dict()
        self.global_threshold = float(train[c.col_duration].quantile(c.bottleneck_quantile))

        train_indices = np.linspace(0, len(train) - 1, min(len(train), self.MAX_TRAIN_ROWS), dtype=int)
        test_indices = np.linspace(0, len(test) - 1, min(len(test), self.MAX_TEST_ROWS), dtype=int)
        train_sample = train.iloc[train_indices]
        test_sample = test.iloc[test_indices]

        y_train = self._label(train_sample)
        y_test = self._label(test_sample)
        self.model.fit(train_sample[self.FEATURES], y_train)

        proba = self._positive_probability(test_sample[self.FEATURES])
        pred = (proba >= 0.5).astype(int)

        metrics: Dict[str, Any] = {
            "train_rows": int(len(train_sample)),
            "test_rows": int(len(test_sample)),
            "train_rows_available": int(len(train)),
            "test_rows_available": int(len(test)),
            "bottleneck_rate_test": round(float(y_test.mean()), 4),
            "f1": round(float(f1_score(y_test, pred, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(y_test, proba)), 4) if y_test.nunique() > 1 else None,
            "report": classification_report(y_test, pred, output_dict=True, zero_division=0),
            "feature_importance": dict(
                sorted(
                    zip(self.FEATURES, (round(float(x), 4) for x in self.model.feature_importances_)),
                    key=lambda kv: -kv[1],
                )
            ),
        }
        return metrics

    def predict_risk(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a calibrated, actionable bottleneck priority for each run.

        Model probability alone is a weak operational signal: a classifier can
        be confident based on resource patterns even when the current runtime
        is normal.  The resulting score therefore combines the learned model
        probability with the observed excess over that task's learned runtime
        threshold.  It remains a ranking signal, not a guaranteed outcome.
        """
        d = self._prepare(df)
        model_probability = self._positive_probability(d[self.FEATURES])
        thresholds = d[self.cfg.col_task].map(self.task_thresholds).fillna(self.global_threshold)
        safe_thresholds = thresholds.clip(lower=np.finfo(float).eps)
        runtime_excess = ((d[self.cfg.col_duration] / safe_thresholds - 1.0) / 0.5).clip(0.0, 1.0)
        d["model_probability"] = model_probability
        d["runtime_excess"] = runtime_excess
        d["bottleneck_risk"] = 0.65 * model_probability + 0.35 * runtime_excess
        d["bottleneck_predicted"] = d["bottleneck_risk"] >= 0.5
        return d

    def save(self, path: Optional[str] = None) -> None:
        """Persist model, thresholds, and task codes atomically."""
        destination = os.path.abspath(path or self.cfg.model_path)
        parent_dir = os.path.dirname(destination)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".bottleneck-model-", suffix=".tmp", dir=parent_dir or None
        )
        os.close(descriptor)
        try:
            payload = {
                "model": self.model,
                "thr": self.task_thresholds,
                "codes": self.task_codes,
                "global_threshold": self.global_threshold,
            }
            joblib.dump(payload, temporary_path)
            os.replace(temporary_path, destination)
        finally:
            if os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def load(self, path: Optional[str] = None) -> "BottleneckPredictor":
        """Load persisted model artifacts."""
        o = joblib.load(path or self.cfg.model_path)
        self.model = o["model"]
        self.task_thresholds = o.get("thr", {})
        self.task_codes = o.get("codes", {})
        self.global_threshold = float(o.get("global_threshold", 0.0))
        return self
