"""Failure detection: rule-based checks + Isolation Forest anomaly detection on ETL logs."""
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from config import Config


class FailureDetector:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.scaler = StandardScaler()
        self.model = IsolationForest(contamination=self.cfg.anomaly_contamination,
                                     n_estimators=200, random_state=self.cfg.random_state, n_jobs=-1)

    def rule_based(self, df: pd.DataFrame) -> pd.DataFrame:
        c = self.cfg
        out = df.copy()
        out["rule_failed_status"] = out[c.col_status].astype(str).str.upper().isin(c.failed_statuses)
        out["rule_timeout"] = out[c.col_duration] > c.duration_timeout_s
        out["rule_cpu"] = out[c.col_cpu] > c.cpu_limit_pct
        out["rule_memory"] = out[c.col_memory] > c.memory_limit_pct
        out["rule_error_code"] = out[c.col_error].notna() & (out[c.col_error].astype(str) != "0")
        rule_cols = [x for x in out.columns if x.startswith("rule_")]
        out["rule_flag"] = out[rule_cols].any(axis=1)
        return out

    def _features(self, df: pd.DataFrame) -> pd.DataFrame:
        c = self.cfg
        return df[[c.col_duration, c.col_cpu, c.col_memory, c.col_io, c.col_latency]].fillna(0)

    def fit_anomaly(self, df: pd.DataFrame):
        features = self._features(df)
        if len(features) > 100_000:
            features = features.sample(n=100_000, random_state=self.cfg.random_state)
            self.model.set_params(n_estimators=100)
        X = self.scaler.fit_transform(features)
        self.model.fit(X)
        return self

    def detect(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self.rule_based(df)
        X = self.scaler.transform(self._features(out))
        out["anomaly_score"] = -self.model.score_samples(X)          # higher = more anomalous
        out["anomaly_flag"] = self.model.predict(X) == -1
        out["failure_detected"] = out["rule_flag"] | out["anomaly_flag"]
        return out

    def summarize(self, detected: pd.DataFrame) -> dict:
        rule_cols = [x for x in detected.columns if x.startswith("rule_") and x != "rule_flag"]
        return {
            "records": len(detected),
            "rule_flagged": int(detected["rule_flag"].sum()),
            "anomaly_flagged": int(detected["anomaly_flag"].sum()),
            "total_flagged": int(detected["failure_detected"].sum()),
            "by_rule": {x: int(detected[x].sum()) for x in rule_cols},
        }
