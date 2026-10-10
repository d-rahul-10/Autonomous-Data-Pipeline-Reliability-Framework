"""JSON + Markdown reporting."""
import json
import os
from datetime import datetime

from config import Config


class Reporter:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        os.makedirs(self.cfg.report_dir, exist_ok=True)

    def write(self, sections: dict) -> tuple[str, str]:
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
                            if key != "report":
                                f.write(f"- **{key.replace('_', ' ').title()}**: {value}\n")
                    else:
                        f.write(f"{body}\n")
                    f.write("\n")
        return jpath, mpath

    @staticmethod
    def _write_analysis_markdown(file, source: str, analysis: dict):
        file.write(f"## Run overview\n\n- **Source:** {source}\n")
        file.write(f"- **Input records:** {analysis.get('rows_raw', 0):,}\n")
        file.write(f"- **Clean records:** {analysis.get('rows_clean', 0):,}\n")
        file.write(f"- **Generated:** {analysis.get('generated_at', 'Unknown')}\n\n")

        quality = analysis.get("data_quality", {})
        file.write("## Data quality\n\n")
        file.write(f"- **Passed:** {'Yes' if quality.get('passed') else 'No'}\n")
        file.write(f"- **Critical failure:** {'Yes' if quality.get('critical_failure') else 'No'}\n\n")
        findings = quality.get("issues", [])
        if findings:
            file.write("| Finding | Column | Count | Severity |\n|---|---|---:|---|\n")
            for issue in findings:
                columns = ", ".join(issue.get("columns", [])) or issue.get("column", "—")
                count = issue.get("count", "Review")
                severity = "Critical" if issue.get("critical") else "Review"
                file.write(f"| {issue.get('type', 'Finding').replace('_', ' ').title()} | {columns} | {count} | {severity} |\n")
            file.write("\n")

        failures = analysis.get("failures", {})
        file.write("## Failure detection\n\n")
        for key in ("records", "rule_flagged", "anomaly_flagged", "total_flagged"):
            file.write(f"- **{key.replace('_', ' ').title()}:** {failures.get(key, 0):,}\n")
        file.write("\n")

        file.write("## Performance\n\n")
        file.write("| Metric | Value |\n|---|---:|\n")
        for key, value in analysis.get("performance", {}).items():
            file.write(f"| {key.replace('_', ' ').title()} | {value} |\n")
        file.write("\n")

        model = analysis.get("model", {})
        file.write("## Bottleneck model\n\n")
        for key in ("train_rows", "test_rows", "bottleneck_rate_test", "f1", "roc_auc"):
            if key in model:
                file.write(f"- **{key.replace('_', ' ').title()}:** {model[key]}\n")
        file.write("\n")

        risks = analysis.get("top_risk", [])
        file.write("## Highest-risk runs\n\n")
        if risks:
            file.write("| Timestamp | Task | Duration (s) | Risk |\n|---|---|---:|---:|\n")
            for risk in risks:
                file.write(
                    f"| {risk.get('timestamp', '')} | {risk.get('task', '')} | "
                    f"{risk.get('duration', 0)} | {risk.get('risk', 0)} |\n"
                )
        else:
            file.write("No risk predictions were returned.\n")
