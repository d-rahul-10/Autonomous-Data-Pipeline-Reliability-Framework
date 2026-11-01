"""Central configuration for the Autonomous Data Pipeline Reliability Framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(slots=True)
class Config:
    """Runtime configuration for pipeline reliability components.

    Column names can be customized to match different ETL log schemas.
    """

    # Dataset column mapping (edit to match your ETL Logs Anomaly Dataset)
    col_timestamp: str = "timestamp"
    col_task: str = "task_id"
    col_status: str = "status"
    col_duration: str = "duration"
    col_cpu: str = "cpu_usage"
    col_memory: str = "memory_usage"
    col_io: str = "io_throughput"
    col_latency: str = "latency"
    col_error: str = "error_code"
    col_deps: str = "dependencies"
    failed_statuses: Tuple[str, ...] = ("FAILED", "ERROR", "TIMEOUT")

    # Failure detection
    duration_timeout_s: float = 300.0
    cpu_limit_pct: float = 95.0
    memory_limit_pct: float = 95.0
    anomaly_contamination: float = 0.02

    # Recovery
    max_retries: int = 3
    backoff_base_s: float = 0.5
    backoff_factor: float = 2.0
    task_timeout_s: float = 10.0

    # Bottleneck prediction
    bottleneck_quantile: float = 0.90  # duration above this per-task quantile = bottleneck
    test_fraction: float = 0.2
    rf_estimators: int = 50
    # Keep individual trees from assigning all-or-nothing probabilities to a
    # handful of similar runs.  This makes risk scores more stable on both
    # small and very large datasets.
    rf_min_samples_leaf: int = 8
    random_state: int = 42

    # Task-health labels are derived from the observed flagged-run rate.
    task_watch_failure_rate: float = 0.05
    task_critical_failure_rate: float = 0.15

    # Output
    log_file: str = "pipeline.log"
    report_dir: str = "reports"
    model_path: str = "bottleneck_model.joblib"

    # Data quality schema (column -> expected kind: int, float, str, datetime)
    schema: Dict[str, str] = field(default_factory=dict)
    required_columns: List[str] = field(default_factory=list)
    not_null_columns: List[str] = field(default_factory=list)
