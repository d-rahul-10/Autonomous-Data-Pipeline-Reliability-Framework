"""End-to-end demo of the Autonomous Data Pipeline Reliability Framework.

Usage:
    python main.py                       # synthetic data
    python main.py --data logs.csv       # your ETL Logs Anomaly Dataset (edit config.py column names)
"""
import argparse
import random

import pandas as pd

from bottleneck_predictor import BottleneckPredictor
from config import Config
from csv_input import read_csv_table
from data_quality import DataQualityValidator
from failure_detector import FailureDetector
from logging_utils import get_logger
from monitor import PipelineMonitor
from recovery import RecoveryManager
from reporter import Reporter
from scheduler import Scheduler
from synthetic_data import generate_logs


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _read_pipeline_csv(path, cfg: Config) -> pd.DataFrame:
    df = read_csv_table(path, low_memory=False)
    needed = [
        cfg.col_timestamp, cfg.col_task, cfg.col_status, cfg.col_duration,
        cfg.col_cpu, cfg.col_memory, cfg.col_io, cfg.col_latency,
    ]
    missing = [column for column in needed if column not in df.columns]
    if missing:
        raise ValueError(
            "CSV was read, but it is not in the ETL pipeline-log format this project "
            f"analyzes; missing required columns: {missing}."
        )
    if cfg.col_error not in df.columns:
        df[cfg.col_error] = None
    if cfg.col_deps not in df.columns:
        df[cfg.col_deps] = ""
    df[cfg.col_timestamp] = pd.to_datetime(df[cfg.col_timestamp], errors="coerce")
    return df


def build_config() -> Config:
    cfg = Config()
    cfg.schema = {cfg.col_duration: "float", cfg.col_cpu: "float", cfg.col_memory: "float",
                  cfg.col_io: "float", cfg.col_latency: "float", cfg.col_timestamp: "datetime"}
    cfg.required_columns = [cfg.col_timestamp, cfg.col_task, cfg.col_status, cfg.col_duration]
    cfg.not_null_columns = [cfg.col_timestamp, cfg.col_task, cfg.col_duration]
    return cfg


def demo_live_pipeline(cfg: Config) -> dict:
    """Simulated ETL with flaky tasks to demonstrate monitoring + automatic recovery."""
    monitor = PipelineMonitor(cfg.task_timeout_s, cfg.log_file)
    rm = RecoveryManager(monitor, cfg)
    state = {"conn_ok": False, "file_ready": False}

    def reconnect(_exc): state["conn_ok"] = True
    def recreate_file(_exc): state["file_ready"] = True
    rm.register_action(ConnectionError, reconnect)
    rm.register_action(FileNotFoundError, recreate_file)

    def extract():
        if not state["file_ready"]:
            raise FileNotFoundError("source file missing")
        return list(range(100))

    def transform(rows):
        return [r * 2 for r in rows]

    def load(rows):
        if not state["conn_ok"]:
            raise ConnectionError("warehouse unreachable")
        return len(rows)

    rows = rm.execute("extract", extract)
    rows = rm.execute("transform", transform, rows)
    loaded = rm.execute("load", load, rows)
    records = monitor.to_frame().astype(object)
    records = records.where(pd.notna(records), None)
    return {"rows_loaded": loaded, "monitor": monitor.summary(), "recovery": rm.stats,
            "records": records.to_dict("records")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="CSV of ETL logs")
    ap.add_argument("--rows", type=_positive_int, default=50_000)
    args = ap.parse_args()

    cfg = build_config()
    cfg.backoff_base_s = 0.1                      # fast demo

    if args.data:
        try:
            df = _read_pipeline_csv(args.data, cfg)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            ap.error(f"Could not load pipeline CSV: {exc}")
    else:
        df = generate_logs(args.rows)
    clean = DataQualityValidator(cfg).clean(df)
    if len(clean) < 200:
        ap.error("Too few valid rows after cleaning (need at least 200).")

    log = get_logger("main", cfg.log_file)
    reporter = Reporter(cfg)
    report = {}
    log.info("loaded %d log records", len(df))

    # 1. Data quality
    dq = DataQualityValidator(cfg)
    dq_report = dq.validate(df)
    report["data_quality"] = {"rows": dq_report["rows"], "passed": dq_report["passed"],
                              "critical_failure": dq_report["critical_failure"],
                              "issues": dq_report["issues"]}
    log.info("cleaned: %d -> %d rows", len(df), len(clean))

    # 2. Failure detection
    fd = FailureDetector(cfg).fit_anomaly(clean)
    detected = fd.detect(clean)
    report["failure_detection"] = fd.summarize(detected)

    # 3. Bottleneck prediction
    bp = BottleneckPredictor(cfg)
    metrics = bp.train(clean)
    bp.save()
    report["bottleneck_prediction"] = {k: v for k, v in metrics.items() if k != "report"}
    top = bp.predict_risk(clean.tail(2000)).nlargest(5, "bottleneck_risk")[
        [cfg.col_timestamp, cfg.col_task, "bottleneck_risk"]]
    report["top_risk_runs"] = top.to_dict("records")

    # 4. Live pipeline w/ recovery, run through the scheduler
    results = {}
    sched = Scheduler(cfg.log_file)
    sched.add_job("etl_run", lambda: results.update(demo_live_pipeline(cfg)), interval_s=60)
    sched.run(max_cycles=1, tick_s=0.1)
    report["live_pipeline"] = results

    jpath, mpath = reporter.write(report)
    log.info("reports written: %s, %s", jpath, mpath)
    print("\n=== SUMMARY ===")
    for k in ("failure_detection", "bottleneck_prediction", "live_pipeline"):
        print(k, "->", {a: b for a, b in report[k].items() if a != "feature_importance"})


if __name__ == "__main__":
    random.seed(0)
    main()
