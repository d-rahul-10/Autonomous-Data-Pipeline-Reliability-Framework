from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from bottleneck_predictor import BottleneckPredictor
from config import Config
from data_quality import DataQualityValidator
from failure_detector import FailureDetector
from reporter import Reporter
from synthetic_data import generate_logs


class BottleneckPredictorTests(unittest.TestCase):
    def _frame(self, durations, cpu_values):
        return pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=len(durations), freq="h"),
            "task_id": ["task-a"] * len(durations),
            "duration": durations,
            "cpu_usage": cpu_values,
            "memory_usage": [20.0] * len(durations),
            "io_throughput": [10.0] * len(durations),
            "latency": [5.0] * len(durations),
            "dependencies": [""] * len(durations),
        })

    def test_first_lag_features_do_not_use_future_rows(self):
        predictor = BottleneckPredictor()
        early = predictor._prepare(self._frame([10.0, 20.0], [30.0, 60.0])).iloc[0]
        changed_future = predictor._prepare(self._frame([10.0, 200.0], [30.0, 99.0])).iloc[0]

        self.assertEqual(early["prev_dur_mean5"], 0)
        self.assertEqual(early["prev_cpu_mean5"], 0)
        self.assertEqual(changed_future["prev_dur_mean5"], early["prev_dur_mean5"])
        self.assertEqual(changed_future["prev_cpu_mean5"], early["prev_cpu_mean5"])

    def test_training_keeps_nonempty_chronological_partitions(self):
        metrics = BottleneckPredictor().train(self._frame([10.0, 20.0], [30.0, 60.0]))

        self.assertEqual(metrics["train_rows_available"], 1)
        self.assertEqual(metrics["test_rows_available"], 1)

    def test_training_rejects_invalid_test_fraction(self):
        predictor = BottleneckPredictor()
        predictor.cfg.test_fraction = 1

        with self.assertRaisesRegex(ValueError, "test_fraction"):
            predictor.train(self._frame([10.0, 20.0], [30.0, 60.0]))

    def test_model_save_and_load_round_trip(self):
        predictor = BottleneckPredictor()
        predictor.train(self._frame([10.0, 20.0], [30.0, 60.0]))

        with TemporaryDirectory() as directory:
            model_path = Path(directory) / "models" / "bottleneck.joblib"
            predictor.save(model_path)
            loaded = BottleneckPredictor().load(model_path)

        self.assertEqual(loaded.task_codes, predictor.task_codes)
        self.assertEqual(loaded.task_thresholds, predictor.task_thresholds)


class DataQualityValidatorTests(unittest.TestCase):
    def test_default_validators_do_not_share_mutable_config(self):
        first = DataQualityValidator()
        second = DataQualityValidator()
        first.cfg.schema["custom"] = "float"

        self.assertNotIn("custom", second.cfg.schema)

    def test_unknown_schema_kind_has_actionable_error(self):
        validator = DataQualityValidator()
        validator.cfg.schema = {"value": "decimal"}

        with self.assertRaisesRegex(ValueError, "Unsupported schema kind"):
            validator.validate(pd.DataFrame({"value": [1]}))

    def test_validate_reports_missing_columns_types_nulls_and_ranges(self):
        config = Config(
            schema={"duration": "float", "timestamp": "datetime", "batch_number": "int"},
            required_columns=["timestamp", "task_id", "duration"],
            not_null_columns=["timestamp"],
        )
        validator = DataQualityValidator(config)
        frame = pd.DataFrame({
            "timestamp": [pd.NaT, pd.NaT],
            "duration": [-1, 2],
            "cpu_usage": [101, 50],
            "batch_number": ["1", "2"],
        })

        report = validator.validate(frame)
        issue_types = {issue["type"] for issue in report["issues"]}

        self.assertFalse(report["passed"])
        self.assertTrue(report["critical_failure"])
        self.assertIn("schema_missing_columns", issue_types)
        self.assertIn("invalid_dtype", issue_types)
        self.assertIn("missing_values", issue_types)
        self.assertIn("range_violation", issue_types)

    def test_clean_coerces_numeric_values_fills_optional_nulls_and_does_not_mutate_input(self):
        validator = DataQualityValidator(Config(
            schema={"duration": "float"},
            not_null_columns=["timestamp", "task_id"],
        ))
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "task_id": ["a", "b", "c"],
            "duration": ["2", "invalid", "4"],
            "optional_metric": [4.0, None, 10.0],
        })
        original = frame.copy(deep=True)

        cleaned = validator.clean(frame)

        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned.loc[1, "duration"], 3.0)
        self.assertEqual(cleaned.loc[1, "optional_metric"], 7.0)
        pd.testing.assert_frame_equal(frame, original)

    def test_clean_removes_duplicates_and_out_of_range_metrics(self):
        validator = DataQualityValidator()
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02"]),
            "task_id": ["task-a", "task-a", "task-b"],
            "duration": [10.0, 10.0, -1.0],
            "cpu_usage": [25.0, 25.0, 35.0],
        })

        cleaned = validator.clean(frame)

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned.loc[0, "duration"], 10.0)


class FailureDetectorTests(unittest.TestCase):
    def test_rules_anomaly_detection_and_summary_are_consistent(self):
        config = Config(
            failed_statuses=("FAILED", "ERROR"),
            duration_timeout_s=20,
            cpu_limit_pct=90,
            memory_limit_pct=90,
            anomaly_contamination=0.1,
        )
        frame = generate_logs(50, seed=7)
        frame.loc[0, ["status", "duration", "cpu_usage", "memory_usage", "error_code"]] = [
            "FAILED", 25.0, 99.0, 98.0, "E500",
        ]
        detector = FailureDetector(config).fit_anomaly(frame)

        detected = detector.detect(frame)
        summary = detector.summarize(detected)

        self.assertTrue(detected.loc[0, "rule_failed_status"])
        self.assertTrue(detected.loc[0, "rule_timeout"])
        self.assertTrue(detected.loc[0, "rule_cpu"])
        self.assertTrue(detected.loc[0, "rule_memory"])
        self.assertTrue(detected.loc[0, "rule_error_code"])
        self.assertEqual(summary["records"], len(frame))
        self.assertGreaterEqual(summary["rule_flagged"], 1)
        self.assertGreaterEqual(summary["total_flagged"], summary["rule_flagged"])

    def test_empty_feature_frame_fails_explicitly(self):
        frame = generate_logs(1).iloc[0:0]
        with self.assertRaises(ValueError):
            FailureDetector().fit_anomaly(frame)


class ReporterTests(unittest.TestCase):
    def test_default_reporters_do_not_share_mutable_config(self):
        first = Reporter()
        second = Reporter()
        first.cfg.report_dir = "changed"

        self.assertNotEqual(first.cfg.report_dir, second.cfg.report_dir)

    def test_reporter_writes_json_and_markdown(self):
        with TemporaryDirectory() as directory:
            config = Config(report_dir=directory)
            json_path, markdown_path = Reporter(config).write({"summary": {"runs": 1}})

            self.assertTrue(Path(json_path).is_file())
            self.assertTrue(Path(markdown_path).is_file())
            markdown = Path(markdown_path).read_text(encoding="utf-8")
            self.assertIn("# Pipeline Reliability Report", markdown)


if __name__ == "__main__":
    unittest.main()
