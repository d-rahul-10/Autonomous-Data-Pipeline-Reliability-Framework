"""Report routes: listing and downloading generated reports."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_file

reports_bp = Blueprint("reports", __name__, url_prefix="")


def _config():
    return current_app.config["APP_CONFIG"]


_REPORT_FILENAME = re.compile(r"report_[A-Za-z0-9_-]+\.(?:json|md)")


@reports_bp.get("/api/reports")
def reports():
    config = _config()
    report_dir = Path(config.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(
        report_dir.glob("report_*.*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:50]:
        if path.suffix.lower() not in {".json", ".md"}:
            continue
        items.append({
            "filename": path.name,
            "format": path.suffix.lstrip(".").upper(),
            "size": path.stat().st_size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
                timespec="seconds"
            ),
        })
    return jsonify(reports=items)


@reports_bp.get("/api/reports/<path:filename>")
def download_report(filename):
    if not _REPORT_FILENAME.fullmatch(filename):
        return jsonify(error="Invalid report filename."), 400
    config = _config()
    path = Path(config.report_dir) / filename
    if not path.is_file():
        return jsonify(error="Report not found."), 404
    return send_file(path.resolve(), as_attachment=True, download_name=path.name)
