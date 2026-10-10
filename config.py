"""Central configuration for the Autonomous Data Pipeline Reliability Framework."""
from dataclasses import dataclass, field


@dataclass
class Config:
    # --- Dataset column mapping (edit to match your ETL Logs Anomaly Dataset) ---
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
    failed_statuses: tuple = ("FAILED", "ERROR", "TIMEOUT")

    # --- Failure detection ---
    duration_timeout_s: float = 300.0
    cpu_limit_pct: float = 95.0
    memory_limit_pct: float = 95.0
    anomaly_contamination: float = 0.02

    # --- Recovery ---
    max_retries: int = 3
    backoff_base_s: float = 0.5
    backoff_factor: float = 2.0
    task_timeout_s: float = 10.0

    # --- Bottleneck prediction ---
    bottleneck_quantile: float = 0.90   # duration above this per-task quantile = bottleneck
    test_fraction: float = 0.2
    rf_estimators: int = 200
    random_state: int = 42

    # --- Output ---
    log_file: str = "pipeline.log"
    report_dir: str = "reports"
    model_path: str = "bottleneck_model.joblib"

    # --- Data quality schema (column -> expected kind: int, float, str, datetime) ---
    schema: dict = field(default_factory=dict)
    required_columns: list = field(default_factory=list)
    not_null_columns: list = field(default_factory=list)
