/**
 * Data Quality view
 * Renders validation findings, quality score cards, and detailed issue list.
 */

import { MetricCard, escape, number } from "../components.js";

/** @param {HTMLElement} container */
/** @param {Object} quality - data_quality object from analysis */
export function renderQuality(container, quality) {
  const q = quality || {};
  const issues = Array.isArray(q.issues) ? q.issues : [];
  const critical = issues.filter((i) => i.critical).length;

  container.innerHTML = `
      <div class="section-heading"><div>
        <h2>Data quality</h2>
        <p>Schema and data checks.</p>
      </div></div>

      <div class="metric-grid quality-summary-grid">
        ${[
          ["Rows inspected", number(q.rows)],
          ["Checks with findings", number(issues.length)],
          ["Critical findings", number(critical)],
          ["Validation state", q.passed ? "Passed" : "Review"],
        ].map(([label, value]) => `
          <article class="metric-card">
            <div class="metric-top">${escape(label)}</div>
            <div class="metric-value">${escape(value)}</div>
          </article>
        `).join("")}
      </div>

      <article class="panel quality-details-panel">
        <div class="panel-heading"><div>
          <h2>Validation findings</h2>
          <p id="quality-findings-caption">${issues.length ? `${number(issues.length)} validation finding${issues.length === 1 ? "" : "s"} from ${number(q.rows)} input rows.` : "All configured schema, completeness, and range checks passed."}</p>
        </div></div>
        <div class="quality-findings" id="quality-findings">${renderFindings(issues)}</div>
      </article>
  `;
}

/** @param {Array} issues */
function renderFindings(issues) {
  if (!issues.length) {
    return '<div class="empty-row">No quality issues found. This dataset passed the configured validation checks.</div>';
  }
  return issues.map((issue) => {
    const details = [
      issue.expected && `expected ${issue.expected}`,
      issue.found && `found ${issue.found}`,
      issue.minimum != null && `minimum ${issue.minimum}`,
      issue.maximum != null && `maximum ${issue.maximum}`,
    ].filter(Boolean).join(" · ");
    return `
      <div class="quality-finding">
        <span class="finding-marker ${issue.critical ? "critical" : ""}">${issue.critical ? "!" : "i"}</span>
        <div class="finding-copy">
          <strong>${escape(issue.type.replaceAll("_", " "))}</strong>
          <span>${escape(details || (issue.columns || []).join(", ") || "Validation check")}</span>
        </div>
        <span class="finding-count">${issue.count == null ? "Review" : `${number(issue.count)} rows`}</span>
      </div>
    `;
  }).join("");
}
