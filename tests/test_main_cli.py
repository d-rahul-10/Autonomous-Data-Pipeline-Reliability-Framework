from contextlib import redirect_stderr, redirect_stdout
import io
import logging
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

from main import main


class MainCliTests(unittest.TestCase):
    def _run_main(self, *arguments):
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["main.py", *arguments]), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as result:
                main()
        return result.exception.code, stderr.getvalue()

    def test_generated_rows_must_be_positive_integers(self):
        for rows in ("0", "-1", "many"):
            with self.subTest(rows=rows):
                exit_code, stderr = self._run_main("--rows", rows)
                self.assertEqual(exit_code, 2)
                expected_message = "whole number" if rows == "many" else "positive integer"
                self.assertIn(expected_message, stderr)

    def test_csv_missing_pipeline_columns_returns_usage_error(self):
        with TemporaryDirectory() as directory:
            csv_path = Path(directory) / "incomplete.csv"
            csv_path.write_text("timestamp,task_id\n2026-01-01,task-a\n", encoding="utf-8")
            exit_code, stderr = self._run_main("--data", str(csv_path))

        self.assertEqual(exit_code, 2)
        self.assertIn("missing required columns", stderr)

    def test_csv_with_too_few_clean_rows_returns_usage_error(self):
        frame = pd.DataFrame({
            "timestamp": ["2026-01-01"],
            "task_id": ["task-a"],
            "status": ["SUCCESS"],
            "duration": [10.0],
            "cpu_usage": [35.0],
            "memory_usage": [45.0],
            "io_throughput": [100.0],
            "latency": [5.0],
        })
        with TemporaryDirectory() as directory:
            csv_path = Path(directory) / "small.csv"
            frame.to_csv(csv_path, index=False)
            exit_code, stderr = self._run_main("--data", str(csv_path))

        self.assertEqual(exit_code, 2)
        self.assertIn("at least 200", stderr)

    def test_valid_synthetic_cli_run_writes_outputs_in_isolated_workspace(self):
        with TemporaryDirectory() as directory:
            original_cwd = Path.cwd()
            logger_names = ("main", "monitor", "recovery", "scheduler")
            original_handlers = {
                name: set(logging.getLogger(name).handlers) for name in logger_names
            }
            try:
                os.chdir(directory)
                output = io.StringIO()
                with patch.object(sys, "argv", ["main.py", "--rows", "1000"]):
                    with redirect_stdout(output):
                        main()

                reports = Path(directory) / "reports"
                self.assertEqual(len(list(reports.glob("report_*.json"))), 1)
                self.assertEqual(len(list(reports.glob("report_*.md"))), 1)
                self.assertTrue((Path(directory) / "bottleneck_model.joblib").is_file())
                self.assertIn("failure_detection ->", output.getvalue())
            finally:
                for name in logger_names:
                    logger = logging.getLogger(name)
                    for handler in logger.handlers[:]:
                        if handler not in original_handlers[name]:
                            logger.removeHandler(handler)
                            handler.close()
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
