/**
 * Risk Analysis view
 * Renders top bottleneck predictions with risk scores and baseline comparisons.
 */

import { MetricCard, escape, number, percent } from "../components.js";

/** @param {HTMLElement} container */
/** @param {Array} risks - top_risk array */
/** @param {Array} tasks - by_task array for threshold lookup */
export function renderRisk(container, risks, tasks = []) {
  const riskList = Array.isArray(risks) ? risks : [];
  const taskAverages = new Map(tasks.map((t) => [String(t.task), Number(t.avg_duration || 0)]));

  container.innerHTML = `
      <div class="section-heading">
        <div>
          <h2>Risks</h2>
        <p>Calibrated model and runtime signals.</p>
        </div>
        <span class="risk-tag">TOP 10</span>
      </div>

      <div class="metric-grid risk-summary-grid">
        ${renderRiskSummary(riskList)}
      </div>
  <p class="risk-guidance">Priority scores combine model evidence with runtime above a learned task threshold. They rank runs for review; they are not failure probabilities or guarantees.</p>

      <article class="panel risk-panel">
        <div class="risk-list" id="risk-list">${renderRiskItems(riskList, taskAverages)}</div>
      </article>
  `;
}

/** @param {Array} risks */
function renderRiskSummary(risks) {
  if (!risks.length) return "";
  const scores = risks.map((r) => Math.max(0, Math.min(1, Number(r.risk || 0))));
  const high = scores.filter((s) => s >= 0.75).length;
  const aboveBaseline = risks.filter((r) => {
    const threshold = Number(r.duration_threshold) || 0;
    return threshold > 0 && Number(r.duration) > threshold;
  }).length;
  return [
    ["Candidates ranked", number(risks.length), "Top priority-scored runs"],
    ["High priority", number(high), "Score at or above 75%"],
    ["Above task baseline", number(aboveBaseline), "Runtime exceeds its available task reference"],
    ["Highest score", percent(Math.max(...scores)), "Calibrated review signal"],
  ].map(([label, value, caption]) => `
    <article class="metric-card risk-stat-card">
      <div class="metric-top">${escape(label)}</div>
      <div class="metric-value">${escape(value)}</div>
      <div class="subtle-caption">${escape(caption)}</div>
    </article>
  `).join("");
}

/** @param {Array} risks @param {Map} taskAverages */
function renderRiskItems(risks, taskAverages) {
  if (!risks.length) {
    return '<div class="empty-row">No bottleneck predictions are available.</div>';
  }

  return risks.map((risk, index) => {
    const score = Math.max(0, Math.min(1, Number(risk.risk || 0)));
    const severity = score >= 0.75 ? "high" : score >= 0.45 ? "medium" : "low";
    const learnedThreshold = Number(risk.duration_threshold || 0);
    const threshold = learnedThreshold || taskAverages.get(String(risk.task)) || 0;
    const duration = Number(risk.duration || 0);
    const baseline = threshold > 0
      ? duration > threshold
        ? `${((duration / threshold - 1) * 100).toFixed(0)}% above ${learnedThreshold ? "learned threshold" : "task average"} (${threshold.toFixed(1)}s)`
        : `${(duration / threshold * 100).toFixed(0)}% of ${learnedThreshold ? "learned threshold" : "task average"} (${threshold.toFixed(1)}s)`
      : "No task threshold available";
    const timestamp = String(risk.timestamp || "").replace("T", " ").slice(0, 16);

    return `
      <div class="risk-item ${severity}">
        <span class="risk-rank">${String(index + 1).padStart(2, "0")}</span>
        <div class="risk-main">
          <div class="risk-item-top">
            <div>
              <div class="risk-task">${escape(risk.task)}</div>
              <div class="risk-meta">${escape(timestamp)}</div>
            </div>
            <span class="risk-priority ${severity}">
              ${severity === "high" ? "High priority" : severity === "medium" ? "Review" : "Lower"}
            </span>
          </div>
          <div class="risk-baseline">
            Runtime <strong>${duration.toFixed(1)}s</strong><span>·</span>${escape(baseline)}
          </div>
          <div class="risk-track" role="img" aria-label="Risk priority score ${percent(score)}">
            <span style="width:${Math.round(score * 100)}%"></span>
          </div>
        </div>
        <div class="risk-score"><strong>${percent(score)}</strong><span>priority score</span></div>
      </div>
    `;
  }).join("");
}
