/**
 * Dashboard / Overview view
 * Renders the top-level metrics, timeline, quality summary, and recovery demo
 * from a single analysis payload.
 */

import { MetricCard, DataTable, healthPill, escape, number, percent, formatTime } from "../components.js";
import { renderTimelineChart } from "./charts.js";

/** @param {HTMLElement} container */
/** @param {Object} data - AnalysisPayload */
export function renderDashboard(container, data) {
  const failures = data.failures || {};
  const quality = data.data_quality || {};
  const model = data.model || {};
  const perf = data.performance || {};
  const rows = Number(failures.records || data.rows_clean || 0);
  const flagged = Number(failures.total_flagged || 0);
  const reliability = rows ? Math.max(0, 1 - flagged / rows) : 0;

  const issues = Array.isArray(quality.issues) ? quality.issues : [];
  const qualityScore = Math.max(0, Math.round(100 - issues.reduce((sum, issue) => {
    const count = Number(issue.count || 1);
    return sum + (issue.critical ? Math.min(count, 20) * 2 : Math.min(count, 10));
  }, 0)));

  container.innerHTML = `
      <div class="section-heading">
        <div>
          <h2>Pipeline health</h2>
          <p id="result-summary">${number(data.rows_raw)} records reviewed · ${number(data.rows_clean)} passed cleaning</p>
        </div>
        <span class="source-badge">${escape(data.source || "Analysis complete")}</span>
      </div>

      <div class="metric-grid">
        ${[
          { label: "Reliability score", value: percent(reliability), caption: `${number(flagged)} run${flagged === 1 ? "" : "s"} flagged for review`, meter: Math.round(reliability * 100) },
          { label: "Runs analyzed", value: number(data.rows_clean), caption: "Clean records analyzed", sub: `${number(data.rows_raw)} records received` },
          { label: "Flagged runs", value: number(flagged), caption: `${number(failures.rule_flagged || 0)} rule-based · ${number(failures.anomaly_flagged || 0)} anomaly`, rate: percent(rows ? flagged / rows : 0, 2) },
          { label: "Model F1 score", value: model.f1 == null ? "N/A" : percent(model.f1), caption: `${number(model.train_rows || 0)} training · ${number(model.test_rows || 0)} test` },
        ].map((c) => `
          <article class="metric-card">
            <div class="metric-top">${escape(c.label)}</div>
            <div class="metric-value">${escape(c.value)}</div>
            <div class="metric-foot">${escape(c.caption || "")}</div>
            ${c.meter !== undefined ? `<div class="meter"><span style="width:${c.meter}%"></span></div>` : ""}
            ${c.sub ? `<div class="subtle-caption">${escape(c.sub)}</div>` : ""}
            ${c.rate ? `<div class="subtle-caption">${escape(c.rate)} of analyzed runs</div>` : ""}
          </article>
        `).join("")}
      </div>

      <div class="dashboard-grid">
        <article class="panel timeline-panel">
          <div class="panel-heading">
            <div>
              <h2>Execution timeline</h2>
              <p>Duration and failures</p>
            </div>
            <span class="chart-legend"><i class="legend-line"></i> Avg. duration <i class="legend-bar"></i> Failures</span>
          </div>
          <div class="chart-wrap" id="timeline-chart">
            ${renderTimelineChart(data.timeline || [])}
          </div>
        </article>
        <article class="panel quality-panel">
          <div class="panel-heading"><div><h2>Data quality</h2><p>Validation summary</p></div></div>
          <div class="quality-score">
            <div class="quality-ring" style="--ring-target:${qualityScore}%; --ring-color:${quality.critical_failure ? "#e2696e" : "#34b88c"}">
              <span>${qualityScore}%</span>
            </div>
            <div>
              <strong>${quality.critical_failure ? "Needs attention" : issues.length ? "Review suggested" : "Looking good"}</strong>
              <span>${issues.length} check${issues.length === 1 ? "" : "s"} with findings · ${number(quality.rows || 0)} input rows</span>
            </div>
          </div>
          <div class="quality-list" id="quality-list"></div>
          <button class="text-button" id="quality-toggle" type="button" ${issues.length <= 4 ? "hidden" : ""}>
            View all ${issues.length} quality checks →
          </button>
        </article>
      </div>

      <article class="recovery-panel">
        <div class="recovery-art" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none">
            <path d="M24 5 40 11v12c0 10-7 16-16 20C15 39 8 33 8 23V11l16-6Z" stroke="currentColor" stroke-width="2.2"/>
            <path d="m17 24 4.5 4.5L31.5 18" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <div class="recovery-copy"><h2>Recovery demo</h2><p>Simulate task retries.</p></div>
        <button class="button button-secondary" id="recovery-button" type="button">Run recovery <span aria-hidden="true">→</span></button>
        <div class="recovery-result" id="recovery-result" hidden></div>
      </article>
  `;

  // Wire quality toggle
  const toggle = container.querySelector("#quality-toggle");
  if (toggle) {
    let expanded = false;
    toggle.addEventListener("click", () => {
      expanded = !expanded;
      renderQualityList(container.querySelector("#quality-list"), issues, expanded);
      toggle.textContent = expanded ? "Show fewer checks ↑" : `View all ${issues.length} quality checks →`;
    });
    renderQualityList(container.querySelector("#quality-list"), issues, false);
  }
}

/**
 * Render the quality list inside the dashboard.
 * @param {HTMLElement} el
 * @param {Array} issues
 * @param {boolean} expanded
 */
function renderQualityList(el, issues, expanded) {
  const visible = expanded ? issues : issues.slice(0, 4);
  const items = visible.map((issue) => {
    const count = issue.count == null ? ((issue.columns || []).length || "Review") : number(issue.count);
    const label = escape(issue.type.replaceAll("_", " "));
    return `<div class="quality-item"><span>${label}</span><span>${escape(count)}</span></div>`;
  });
  if (!issues.length) {
    items.push('<div class="quality-item"><span>Schema and required fields</span><span class="quality-clear">Passed</span></div>');
    items.push('<div class="quality-item"><span>Missing and duplicate data</span><span class="quality-clear">Passed</span></div>');
  }
  el.innerHTML = items.join("");
}
