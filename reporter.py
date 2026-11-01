"""JSON + Markdown reporting."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from config import Config


class Reporter:
    """Generate JSON and Markdown reports."""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        os.makedirs(self.cfg.report_dir, exist_ok=True)

    def write(self, sections: Dict[str, Any]) -> Tuple[str, str]:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        jpath = os.path.join(self.cfg.report_dir, f"report_{stamp}.json")
        mpath = os.path.join(self.cfg.report_dir, f"report_{stamp}.md")

        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(sections, f, indent=2, default=str)

        with open(mpath, "w", encoding="utf-8") as f:
            f.write(f"# Pipeline Reliability Report\n\n_Generated {datetime.now():%Y-%m-%d %H:%M:%S}_\n\n")
            analysis = sections.get("analysis")
            if isinstance(analysis, dict):
                self._write_analysis_markdown(f, sections.get("source", "Unknown"), analysis)
            else:
                for title, body in sections.items():
                    f.write(f"## {title.replace('_', ' ').title()}\n\n")
                    if isinstance(body, dict):
                        for key, value in body.items():
                            if key == "report":
                                continue
                            key_title = str(key).replace("_", " ").title()
                            f.write(f"- **{key_title}**: {value}\n")
                    elif isinstance(body, (list, tuple)):
                        for item in body:
                            f.write(f"- {item}\n")
                    else:
                        f.write(f"{body}\n")
                    f.write("\n")
        return jpath, mpath

    @staticmethod
    def _write_analysis_markdown(file, source: str, analysis: Dict[str, Any]) -> None:
        file.write(f"## Run overview\n\n- **Source:** {source}\n")
        file.write(f"- **Input records:** {analysis.get('rows_raw', 0):,}\n")
        file.write(f"- **Clean records:** {analysis.get('rows_clean', 0):,}\n")
        file.write(f"- **Generated:** {analysis.get('generated_at', 'Unknown')}\n\n")

        quality = analysis.get("data_quality", {}) or {}
        file.write("## Data quality\n\n")
        file.write(f"- **Passed:** {'Yes' if quality.get('passed') else 'No'}\n")
        file.write(f"- **Critical failure:** {'Yes' if quality.get('critical_failure') else 'No'}\n\n")
        findings = quality.get("issues", []) or []
        if findings:
            file.write("| Finding | Column | Count | Severity |\n|---|---|---:|---|\n")
            for issue in findings:
                if not isinstance(issue, dict):
                    continue
                columns_list = issue.get("columns") or []
                if isinstance(columns_list, (list, tuple)) and columns_list:
                    columns = ", ".join(str(c) for c in columns_list)
                else:
                    columns = issue.get("column") or "—"
                count = issue.get("count", "Review")
                severity = "Critical" if issue.get("critical") else "Review"
                ftype = str(issue.get("type", "Finding")).replace("_", " ").title()
                file.write(f"| {ftype} | {columns} | {count} | {severity} |\n")
            file.write("\n")

        failures = analysis.get("failures", {}) or {}
        file.write("## Failure detection\n\n")
        for key in ("records", "rule_flagged", "anomaly_flagged", "total_flagged"):
            file.write(f"- **{key.replace('_', ' ').title()}:** {failures.get(key, 0):,}\n")
        file.write("\n")

        performance = analysis.get("performance", {}) or {}
        if performance:
            file.write("## Performance\n\n")
            file.write("| Metric | Value |\n|---|---:|\n")
            for key, value in performance.items():
                file.write(f"| {str(key).replace('_', ' ').title()} | {value} |\n")
            file.write("\n")

        model = analysis.get("model", {}) or {}
        if model:
            file.write("## Bottleneck model\n\n")
            for key in ("train_rows", "test_rows", "bottleneck_rate_test", "f1", "roc_auc"):
                if key in model:
                    file.write(f"- **{key.replace('_', ' ').title()}:** {model[key]}\n")
            file.write("\n")

        risks = analysis.get("top_risk", []) or []
        file.write("## Highest-risk runs\n\n")
        if risks:
            file.write("| Timestamp | Task | Duration (s) | Risk |\n|---|---|---:|---:|\n")
            for risk in risks:
                if not isinstance(risk, dict):
                    continue
                file.write(
                    f"| {risk.get('timestamp', '')} | {risk.get('task', '')} | "
                    f"{risk.get('duration', 0)} | {risk.get('risk', 0)} |\n"
                )
        else:
            file.write("No risk predictions were returned.\n")
