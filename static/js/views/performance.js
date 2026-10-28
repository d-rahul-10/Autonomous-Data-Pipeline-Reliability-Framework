/**
 * Performance view
 * Renders performance metrics and execution trend chart.
 */

import { MetricCard, escape, number } from "../components.js";
import { renderTimelineChart } from "./charts.js";

/** @param {HTMLElement} container */
/** @param {Object} perf - performance object from analysis */
/** @param {Array} timeline - timeline array */
export function renderPerformance(container, perf, timeline = []) {
  const p = perf || {};

  container.innerHTML = `
      <div class="section-heading"><div>
        <h2>Performance</h2>
        <p>Runtime and resource use.</p>
      </div></div>

      <div class="metric-grid performance-metrics">
        ${[
          ["Average duration", `${Number(p.avg_duration || 0).toFixed(2)} s`],
          ["95th percentile", `${Number(p.p95_duration || 0).toFixed(2)} s`],
          ["Longest run", `${Number(p.max_duration || 0).toFixed(2)} s`],
          ["Average CPU", `${Number(p.avg_cpu || 0).toFixed(1)}%`],
          ["Average memory", `${Number(p.avg_memory || 0).toFixed(1)}%`],
          ["Average I/O", `${Number(p.avg_io || 0).toFixed(1)} units`],
          ["Average latency", `${Number(p.avg_latency || 0).toFixed(1)} ms`],
          ["Tasks observed", number(p.task_count)],
        ].map(([label, value]) => `
          <article class="metric-card">
            <div class="metric-top">${escape(label)}</div>
            <div class="metric-value">${escape(value)}</div>
          </article>
        `).join("")}
      </div>

      <article class="panel performance-trend-panel">
        <div class="panel-heading"><div>
          <h2>Execution trend</h2>
          <p>Runtime and failures</p>
        </div></div>
        <div class="chart-wrap" id="performance-chart">
          ${renderTimelineChart(timeline)}
        </div>
      </article>
  `;
}
