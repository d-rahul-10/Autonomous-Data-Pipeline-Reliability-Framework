"""Pandas-based data quality validation and cleaning."""
import pandas as pd
from pandas.api import types as pdt

from config import Config

_KIND_CHECK = {
    "int": pdt.is_integer_dtype,
    "float": pdt.is_numeric_dtype,
    "str": lambda s: pdt.is_string_dtype(s) or pdt.is_object_dtype(s),
    "datetime": pdt.is_datetime64_any_dtype,
}


class DataQualityValidator:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()

    def validate(self, df: pd.DataFrame) -> dict:
        issues = []
        # 1. Schema: required columns
        missing_cols = [c for c in self.cfg.required_columns if c not in df.columns]
        if missing_cols:
            issues.append({"type": "schema_missing_columns", "columns": missing_cols})

        # 2. Invalid data types
        for col, kind in self.cfg.schema.items():
            if kind not in _KIND_CHECK:
                raise ValueError(f"Unsupported schema kind {kind!r} for column {col!r}.")
            if col in df.columns and not _KIND_CHECK[kind](df[col]):
                issues.append({"type": "invalid_dtype", "column": col,
                               "expected": kind, "found": str(df[col].dtype)})

        # 3. Missing values
        null_counts = df.isna().sum()
        for col, n in null_counts[null_counts > 0].items():
            issues.append({"type": "missing_values", "column": col, "count": int(n),
                           "pct": round(100 * n / len(df), 3) if len(df) else 0,
                           "critical": col in self.cfg.not_null_columns})

        # 4. Duplicates
        dups = int(df.duplicated().sum())
        if dups:
            issues.append({"type": "duplicate_rows", "count": dups})

        # 5. Negative values in numeric columns that should be non-negative
        for col in df.select_dtypes("number").columns:
            neg = int((df[col] < 0).sum())
            if neg:
                issues.append({"type": "negative_values", "column": col, "count": neg})

        bounds = {
            self.cfg.col_duration: (0, None),
            self.cfg.col_cpu: (0, 100),
            self.cfg.col_memory: (0, 100),
            self.cfg.col_io: (0, None),
            self.cfg.col_latency: (0, None),
        }
        for col, (minimum, maximum) in bounds.items():
            if col not in df.columns or not pdt.is_numeric_dtype(df[col]):
                continue
            invalid = df[col].lt(minimum)
            if maximum is not None:
                invalid |= df[col].gt(maximum)
            count = int(invalid.sum())
            if count:
                issues.append({
                    "type": "range_violation",
                    "column": col,
                    "count": count,
                    "minimum": minimum,
                    "maximum": maximum,
                    "critical": col in self.cfg.not_null_columns,
                })

        critical = any(i["type"] in ("schema_missing_columns", "invalid_dtype")
                       or i.get("critical") for i in issues)
        return {"rows": len(df), "passed": not issues, "critical_failure": critical, "issues": issues}

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Drop duplicates, drop rows null in critical columns, coerce numeric types, fill numeric nulls with median."""
        out = df.drop_duplicates().copy()
        for col, kind in self.cfg.schema.items():
            if col not in out.columns:
                continue
            if kind in ("int", "float"):
                out[col] = pd.to_numeric(out[col], errors="coerce")
            elif kind == "datetime":
                out[col] = pd.to_datetime(out[col], errors="coerce")

        crit = [c for c in self.cfg.not_null_columns if c in out.columns]
        if crit:
            out = out.dropna(subset=crit)

        bounds = {
            self.cfg.col_duration: (0, None),
            self.cfg.col_cpu: (0, 100),
            self.cfg.col_memory: (0, 100),
            self.cfg.col_io: (0, None),
            self.cfg.col_latency: (0, None),
        }
        for col, (minimum, maximum) in bounds.items():
            if col not in out.columns:
                continue
            out[col] = pd.to_numeric(out[col], errors="coerce")
            valid = out[col].ge(minimum)
            if maximum is not None:
                valid &= out[col].le(maximum)
            out = out.loc[valid | out[col].isna()]

        for col in out.select_dtypes("number").columns:
            median = out[col].median()
            out[col] = out[col].fillna(median if pd.notna(median) else 0)
        return out.reset_index(drop=True)
