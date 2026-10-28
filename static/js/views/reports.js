/**
 * Reports view
 * Renders saved reports list and recent analysis history.
 */

import { escape, number, formatTime } from "../components.js";

/** @param {HTMLElement} container */
/** @param {Array} reports - report items */
/** @param {Array} history - history items */
export function renderReports(container, reports, history = []) {
  container.innerHTML = `
      <div class="section-heading"><div>
        <h2>Reports</h2>
        <p>Saved analyses and history.</p>
      </div><button class="button button-secondary" id="refresh-reports" type="button">Refresh</button></div>

      <article class="panel reports-panel">
        <div class="panel-heading"><div>
          <h2>Generated reports</h2>
          <p id="reports-count">${number(reports.length)} saved report files</p>
        </div></div>
        <div id="report-list" class="report-list">${renderReportItems(reports)}</div>
      </article>

      <article class="panel history-panel">
        <div class="panel-heading"><div>
          <h2>Recent analysis runs</h2>
          <p>Last 25 runs, saved across restarts</p>
        </div></div>
        <div class="table-scroll"><table>
          <thead><tr><th>Run time</th><th>Source</th><th>Rows</th><th>Flagged</th><th>Reliability</th></tr></thead>
          <tbody id="history-rows">${renderHistoryRows(history)}</tbody>
        </table></div>
      </article>
  `;
}

/** @param {Array} reports */
function renderReportItems(reports) {
  if (!reports.length) {
    return '<div class="empty-row">No reports yet. Run an analysis to generate JSON and Markdown reports.</div>';
  }
  return reports.map((r) => {
    const modified = r.modified ? formatTime(r.modified) : "Saved report";
    return `
      <a class="report-item" href="/api/reports/${encodeURIComponent(r.filename)}" download>
        <span class="report-icon">${r.format === "JSON" ? "{}" : "MD"}</span>
        <span class="report-copy">
          <strong>${escape(r.filename)}</strong>
          <span>${escape(modified)} · ${number(r.size)} bytes</span>
        </span>
        <span class="report-download" aria-hidden="true">↓</span>
      </a>
    `;
  }).join("");
}

/** @param {Array} history */
function renderHistoryRows(history) {
  if (!history.length) {
    return `<tr><td colspan="5" class="empty-row">No analysis runs in this server session yet.</td></tr>`;
  }
  return history.map((item) => `
    <tr>
      <td>${escape(formatTime(item.generated_at))}</td>
      <td>${escape(item.source)}</td>
      <td>${number(item.rows_clean)}</td>
      <td>${number(item.flagged)}</td>
      <td>${Number(item.reliability || 0).toFixed(1)}%</td>
    </tr>
  `).join("");
}
