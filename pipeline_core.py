"""Shared core pipeline logic used by both CLI and web API."""
import pandas as pd

from config import Config
from csv_input import read_csv_table
from data_quality import DataQualityValidator


def build_config() -> Config:
    """Create a standard Config with schema, required columns, and not-null constraints."""
    cfg = Config()
    cfg.schema = {
        cfg.col_duration: "float",
        cfg.col_cpu: "float",
        cfg.col_memory: "float",
        cfg.col_io: "float",
        cfg.col_latency: "float",
        cfg.col_timestamp: "datetime",
    }
    cfg.required_columns = [
        cfg.col_timestamp,
        cfg.col_task,
        cfg.col_status,
        cfg.col_duration,
    ]
    cfg.not_null_columns = [
        cfg.col_timestamp,
        cfg.col_task,
        cfg.col_duration,
    ]
    return cfg


def _read_pipeline_csv(
    source,
    cfg: Config,
    check_clean_rows: bool = True,
) -> pd.DataFrame:
    """Read and validate a pipeline CSV from file path or file-like object.

    Args:
        source: Path to CSV file or file-like object with .read() and .seek().
        cfg: Configuration with column mappings.
        check_clean_rows: If True, validate minimum clean row count (200).

    Returns:
        Cleaned DataFrame with required columns and parsed timestamps.

    Raises:
        ValueError: If CSV is missing required columns or has too few clean rows.
    """
    try:
        df = read_csv_table(source, low_memory=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise ValueError(f"Could not read CSV: {exc}") from exc

    needed = [
        cfg.col_timestamp,
        cfg.col_task,
        cfg.col_status,
        cfg.col_duration,
        cfg.col_cpu,
        cfg.col_memory,
        cfg.col_io,
        cfg.col_latency,
    ]
    missing = [column for column in needed if column not in df.columns]
    if missing:
        raise ValueError(
            f"CSV was read, but it is not in the ETL pipeline-log format; "
            f"missing required columns: {missing}. Found columns: {list(df.columns)}. "
            "Upload ETL run logs with timestamp, task_id, status, duration, "
            "cpu_usage, memory_usage, io_throughput, and latency columns, "
            "or map your ETL column names in config.py."
        )

    if cfg.col_error not in df.columns:
        df[cfg.col_error] = None
    if cfg.col_deps not in df.columns:
        df[cfg.col_deps] = ""

    df[cfg.col_timestamp] = pd.to_datetime(df[cfg.col_timestamp], errors="coerce")

    if check_clean_rows and len(DataQualityValidator(cfg).clean(df)) < 200:
        raise ValueError("Too few valid rows after cleaning (need at least 200).")

    return df