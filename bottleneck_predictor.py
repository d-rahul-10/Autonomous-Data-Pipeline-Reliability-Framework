"""ML-based bottleneck / delay prediction from historical execution logs."""
import os
import tempfile

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score, f1_score

from config import Config


class BottleneckPredictor:
    MAX_TRAIN_ROWS = 100_000
    MAX_TEST_ROWS = 100_000
    FEATURES = ["cpu", "mem", "io", "latency", "dep_count", "hour", "dow", "task_code",
                "prev_dur_mean5", "prev_cpu_mean5"]

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.model = RandomForestClassifier(n_estimators=self.cfg.rf_estimators, class_weight="balanced",
                                            n_jobs=-1, random_state=self.cfg.random_state)
        self.task_thresholds: dict = {}
        self.task_codes: dict = {}

    # ---- feature engineering (lag features use only PAST rows -> no leakage) ----
    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        c = self.cfg
        columns = [
            c.col_timestamp, c.col_task, c.col_duration, c.col_cpu, c.col_memory,
            c.col_io, c.col_latency, c.col_deps,
        ]
        d = df.loc[:, columns].sort_values(c.col_timestamp).copy()
        ts = pd.to_datetime(d[c.col_timestamp])
        d["cpu"], d["mem"], d["io"], d["latency"] = d[c.col_cpu], d[c.col_memory], d[c.col_io], d[c.col_latency]
        d["dep_count"] = d[c.col_deps].fillna("").astype(str).apply(lambda s: 0 if s in ("", "0", "[]") else len(s.split(",")))
        d["hour"], d["dow"] = ts.dt.hour, ts.dt.dayofweek
        if not self.task_codes:
            self.task_codes = {t: i for i, t in enumerate(sorted(d[c.col_task].astype(str).unique()))}
        d["task_code"] = d[c.col_task].astype(str).map(self.task_codes).fillna(-1)
        g = d.groupby(c.col_task)
        d["prev_dur_mean5"] = g[c.col_duration].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        d["prev_cpu_mean5"] = g[c.col_cpu].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        d[["prev_dur_mean5", "prev_cpu_mean5"]] = d[["prev_dur_mean5", "prev_cpu_mean5"]].fillna(0)
        return d

    def _label(self, d: pd.DataFrame) -> pd.Series:
        thr = d[self.cfg.col_task].map(self.task_thresholds)
        return (d[self.cfg.col_duration] > thr).astype(int)

    def _positive_probability(self, features: pd.DataFrame) -> np.ndarray:
        probabilities = self.model.predict_proba(features)
        positive_class = np.flatnonzero(self.model.classes_ == 1)
        if not len(positive_class):
            return np.zeros(len(features))
        return probabilities[:, positive_class[0]]

    def train(self, df: pd.DataFrame) -> dict:
        c = self.cfg
        if not 0 < c.test_fraction < 1:
            raise ValueError("test_fraction must be greater than 0 and less than 1.")
        d = self._prepare(df)
        if len(d) < 2:
            raise ValueError("At least two valid rows are required to train the bottleneck model.")
        split = min(max(1, int(len(d) * (1 - c.test_fraction))), len(d) - 1)
        train, test = d.iloc[:split], d.iloc[split:]
        self.task_thresholds = train.groupby(c.col_task)[c.col_duration].quantile(c.bottleneck_quantile).to_dict()
        train_indices = np.linspace(
            0, len(train) - 1, min(len(train), self.MAX_TRAIN_ROWS), dtype=int
        )
        test_indices = np.linspace(
            0, len(test) - 1, min(len(test), self.MAX_TEST_ROWS), dtype=int
        )
        train_sample = train.iloc[train_indices]
        test_sample = test.iloc[test_indices]
        y_train, y_test = self._label(train_sample), self._label(test_sample)
        self.model.fit(train_sample[self.FEATURES], y_train)
        proba = self._positive_probability(test_sample[self.FEATURES])
        pred = (proba >= 0.5).astype(int)
        metrics = {
            "train_rows": len(train_sample), "test_rows": len(test_sample),
            "train_rows_available": len(train), "test_rows_available": len(test),
            "bottleneck_rate_test": round(float(y_test.mean()), 4),
            "f1": round(f1_score(y_test, pred, zero_division=0), 4),
            "roc_auc": round(roc_auc_score(y_test, proba), 4) if y_test.nunique() > 1 else None,
            "report": classification_report(y_test, pred, output_dict=True, zero_division=0),
            "feature_importance": dict(sorted(zip(self.FEATURES, map(lambda x: round(float(x), 4),
                                       self.model.feature_importances_)), key=lambda kv: -kv[1])),
        }
        return metrics

    def predict_risk(self, df: pd.DataFrame) -> pd.DataFrame:
        d = self._prepare(df)
        d["bottleneck_risk"] = self._positive_probability(d[self.FEATURES])
        d["bottleneck_predicted"] = d["bottleneck_risk"] >= 0.5
        return d

    def save(self, path=None):
        destination = os.path.abspath(path or self.cfg.model_path)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".bottleneck-model-", suffix=".tmp", dir=os.path.dirname(destination)
        )
        os.close(descriptor)
        try:
            joblib.dump(
                {"model": self.model, "thr": self.task_thresholds, "codes": self.task_codes},
                temporary_path,
            )
            os.replace(temporary_path, destination)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def load(self, path=None):
        o = joblib.load(path or self.cfg.model_path)
        self.model, self.task_thresholds, self.task_codes = o["model"], o["thr"], o["codes"]
        return self
