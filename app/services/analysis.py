"""Analysis service: the core data-pipeline reliability analysis.

Encapsulates the end-to-end analysis pipeline (data quality, failure
detection, bottleneck prediction, reporting, and persistence) so it can be
invoked from both synchronous and asynchronous callers without duplicating
business logic. Flask- and thread-free, so it is straightforward to unit test.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from bottleneck_predictor import BottleneckPredictor
from config import Config
from data_quality import DataQualityValidator
from failure_detector import FailureDetector
from pipeline_core import build_config
from reporter import Reporter

from app.exceptions import ValidationError

logger = logging.getLogger("app.services.analysis")


def json_default(o):
    """JSON serializer for numpy/pandas values shared across the app."""
    import numpy as np

    if isinstance(o, np.generic):
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


class AnalysisService:
    MAX_TIMELINE_CHUNKS = 80
    TOP_RISK_COUNT = 10
    RISK_WINDOW = 5000

    def __init__(
        self,
        cfg: Config | None = None,
        history_repository=None,
        report_writer=None,
        min_clean_rows: int = 200,
        history_sink=None,
    ):
        self.cfg = cfg or build_config()
        self.history_repository = history_repository
        self.report_writer = report_writer or self._default_report_writer
        self.min_clean_rows = min_clean_rows
        self.history_sink = history_sink

    @staticmethod
    def _default_report_writer(sections: dict):
        return Reporter().write(sections)

    # ------------------------------------------------------------------ core
    def analyze(self, df: pd.DataFrame, source: str, progress=None, cfg: Config | None = None) -> dict:
        """Run the complete analysis once.

        Args:
            df: Raw input DataFrame.
            source: Human-readable source label.
            progress: Optional callable(stage: str, progress: int) -> None.
            cfg: Optional config override for this call (defaults to self.cfg).

        Returns:
            Serialisable analysis payload.

        Raises:
            ValidationError: If too few valid rows remain after cleaning.
        """
        active_cfg = cfg or self.cfg
        if progress:
            progress("validating", 10)

        dq_report = DataQualityValidator(active_cfg).validate(df)

        if progress:
            progress("cleaning", 20)
        clean = DataQualityValidator(active_cfg).clean(df)
        if len(clean) < self.min_clean_rows:
            raise ValidationError(
                f"Too few valid rows after cleaning (need at least {self.min_clean_rows})."
            )

        if progress:
            progress("detecting_failures", 40)
        detector = FailureDetector(active_cfg).fit_anomaly(clean)
        detected = detector.detect(clean)
        failures = detector.summarize(detected)

        if progress:
            progress("training_model", 60)
        predictor = BottleneckPredictor(active_cfg)
        metrics = predictor.train(clean)
        predictor.save()
        metrics.pop("report", None)

        if progress:
            progress("computing_metrics", 80)

        payload = self._build_payload(
            df, clean, detected, failures, metrics, predictor, source, active_cfg, dq_report
        )

        if progress:
            progress("finalizing", 95)

        json_report, _ = self.report_writer({"source": source, "analysis": payload})
        payload["report_file"] = Path(json_report).name

        self._persist(payload)
        return payload

    # ------------------------------------------------------------------ assembly
    def _build_payload(self, df, clean, detected, failures, metrics, predictor, source, cfg, dq_report):
        timestamp, duration, task = (
            cfg.col_timestamp,
            cfg.col_duration,
            cfg.col_task,
        )

        ordered = detected[[timestamp, duration, "failure_detected"]].sort_values(
            timestamp, kind="stable"
        ).reset_index(drop=True)
        chunks = [
            indices
            for indices in np.array_split(
                np.arange(len(ordered)), min(self.MAX_TIMELINE_CHUNKS, len(ordered))
            )
            if len(indices)
        ]
        timeline = [
            {
                "t": str(ordered[timestamp].iloc[indices[0]])[:16],
                "avg_duration": round(float(ordered[duration].iloc[indices].mean()), 2),
                "failures": int(ordered["failure_detected"].iloc[indices].sum()),
            }
            for indices in chunks
        ]

        by_task = (
            detected.groupby(task)
            .agg(runs=("failure_detected", "size"),
                 flagged=("failure_detected", "sum"),
                 avg_duration=(duration, "mean"))
            .round(2)
            .reset_index()
            .rename(columns={task: "task"})
            .to_dict("records")
        )

        risk = predictor.predict_risk(clean.tail(self.RISK_WINDOW)).nlargest(
            self.TOP_RISK_COUNT, "bottleneck_risk"
        )
        top_risk = [
            {
                "timestamp": str(getattr(row, timestamp)),
                "task": str(getattr(row, task)),
                "duration": round(float(getattr(row, duration)), 2),
                "duration_threshold": round(
                    float(predictor.task_thresholds.get(str(getattr(row, task)), 0)), 2
                ),
                "risk": round(float(row.bottleneck_risk), 3),
            }
            for row in risk.itertuples(index=False)
        ]

        performance = {
            "avg_duration": round(float(clean[duration].mean()), 2),
            "p95_duration": round(float(clean[duration].quantile(0.95)), 2),
            "max_duration": round(float(clean[duration].max()), 2),
            "avg_cpu": round(float(clean[cfg.col_cpu].mean()), 2),
            "avg_memory": round(float(clean[cfg.col_memory].mean()), 2),
            "avg_io": round(float(clean[cfg.col_io].mean()), 2),
            "avg_latency": round(float(clean[cfg.col_latency].mean()), 2),
            "task_count": int(clean[task].nunique()),
        }

        return {
            "source": source,
            "generated_at": self._iso_now(),
            "rows_raw": int(len(df)),
            "rows_clean": int(len(clean)),
            "data_quality": dq_report,
            "failures": failures,
            "model": metrics,
            "performance": performance,
            "timeline": timeline,
            "by_task": by_task,
            "top_risk": top_risk,
        }

    # ------------------------------------------------------------------ persistence
    def _persist(self, payload: dict) -> None:
        generated_at = payload["generated_at"]
        if self.history_repository is not None:
            self.history_repository.save(
                generated_at, json.dumps(payload, default=json_default)
            )
        if self.history_sink is not None:
            try:
                self.history_sink(payload)
            except Exception:  # noqa: BLE001 - sink must not break analysis
                logger.exception("history sink failed")

    @staticmethod
    def _iso_now():
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
