"""Synthetic ETL log generator (stand-in for the 500K-row ETL Logs Anomaly Dataset)."""
import numpy as np
import pandas as pd


def generate_logs(n: int = 50_000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tasks = [f"task_{i}" for i in range(8)]
    base = dict(zip(tasks, rng.uniform(5, 60, len(tasks))))
    t = rng.choice(tasks, n)
    cpu = np.clip(rng.normal(55, 18, n), 1, 100)
    mem = np.clip(rng.normal(60, 15, n), 1, 100)
    io = np.clip(rng.normal(200, 60, n), 5, None)
    lat = np.clip(rng.normal(80, 30, n), 1, None)
    dur = np.array([base[x] for x in t]) * (1 + 0.012 * (cpu - 55) + 0.008 * (lat - 80) / 10 - 0.002 * (io - 200) / 10)
    dur = np.clip(dur + rng.normal(0, 3, n), 0.5, None)
    spike = rng.random(n) < 0.04
    dur[spike] *= rng.uniform(3, 8, spike.sum())
    status = np.where(rng.random(n) < 0.03, "FAILED", "SUCCESS")
    err = np.where(status == "FAILED", rng.choice(["E101", "E204", "E500", "E503"], n), None)
    deps = rng.choice(["", "task_0", "task_0,task_1", "task_2,task_3,task_4"], n)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="30s"),
        "task_id": t, "status": status, "duration": dur.round(3), "cpu_usage": cpu.round(2),
        "memory_usage": mem.round(2), "io_throughput": io.round(2), "latency": lat.round(2),
        "error_code": err, "dependencies": deps,
    })
    # inject quality problems
    df.loc[rng.choice(n, n // 200, replace=False), "cpu_usage"] = np.nan
    df = pd.concat([df, df.sample(n // 300, random_state=seed)], ignore_index=True)
    return df
