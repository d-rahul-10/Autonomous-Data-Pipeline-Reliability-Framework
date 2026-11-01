"""Failure detection: rule-based checks + Isolation Forest anomaly detection on ETL logs."""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from config import Config


class FailureDetector:
    """Detect pipeline failures via declarative rules and unsupervised anomaly detection."""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.scaler = StandardScaler()
        self.model = IsolationForest(
            contamination=self.cfg.anomaly_contamination,
            n_estimators=200,
            random_state=self.cfg.random_state,
            n_jobs=-1,
        )

    def rule_based(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply rule-based failure checks to the input DataFrame."""
        c = self.cfg
        out = df.copy()

        status = out[c.col_status].astype(str).str.upper()
        out["rule_failed_status"] = status.isin(c.failed_statuses)
        out["rule_timeout"] = out[c.col_duration] > c.duration_timeout_s
        out["rule_cpu"] = out[c.col_cpu] > c.cpu_limit_pct
        out["rule_memory"] = out[c.col_memory] > c.memory_limit_pct

        error = out[c.col_error]
        out["rule_error_code"] = error.notna() & (error.astype(str).str.strip() != "") & (
            error.astype(str).str.strip() != "0"
        )

        rule_cols = [col for col in out.columns if col.startswith("rule_") and col != "rule_flag"]
        out["rule_flag"] = out[rule_cols].any(axis=1)
        return out

    def _features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract numeric features for anomaly detection."""
        c = self.cfg
        feature_cols = [c.col_duration, c.col_cpu, c.col_memory, c.col_io, c.col_latency]
        features = df[feature_cols].copy()
        return features.fillna(0.0)

    def fit_anomaly(self, df: pd.DataFrame) -> "FailureDetector":
        """Fit the Isolation Forest on historical (clean) data."""
        features = self._features(df)
        if len(features) > 100_000:
            features = features.sample(n=100_000, random_state=self.cfg.random_state)
            self.model.set_params(n_estimators=100)
        X = self.scaler.fit_transform(features)
        self.model.fit(X)
        return self

    def detect(self, df: pd.DataFrame, progress=None) -> pd.DataFrame:
        """Run rule-based and anomaly detection, flagging failures."""
        out = self.rule_based(df)
        features = self._features(out)
        scores = np.empty(len(out), dtype=float)
        flags = np.empty(len(out), dtype=bool)
        # Scoring in bounded batches prevents a large upload from allocating a
        # second full transformed feature matrix while it is already held in
        # memory by the request worker.
        for start in range(0, len(out), self.PREDICT_BATCH_SIZE):
            stop = min(start + self.PREDICT_BATCH_SIZE, len(out))
            transformed = self.scaler.transform(features.iloc[start:stop])
            scores[start:stop] = -self.model.score_samples(transformed)
            flags[start:stop] = self.model.predict(transformed) == -1
            if progress:
                progress(stop, len(out))
        out["anomaly_score"] = scores  # higher = more anomalous
        out["anomaly_flag"] = flags
        out["failure_detected"] = out["rule_flag"] | out["anomaly_flag"]
        return out

    def summarize(self, detected: pd.DataFrame) -> Dict[str, object]:
        """Summarize detection results."""
        rule_cols: List[str] = [
            col for col in detected.columns if col.startswith("rule_") and col != "rule_flag"
        ]
        return {
            "records": int(len(detected)),
            "rule_flagged": int(detected["rule_flag"].sum()),
            "anomaly_flagged": int(detected["anomaly_flag"].sum()),
            "total_flagged": int(detected["failure_detected"].sum()),
            "by_rule": {col: int(detected[col].sum()) for col in rule_cols},
        }
    PREDICT_BATCH_SIZE = 50_000
