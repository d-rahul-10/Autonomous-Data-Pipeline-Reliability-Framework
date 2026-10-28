/**
 * PipelineIQ Chart Renderers
 * Shared SVG chart components used across views.
 */

import { escape, number } from "../components.js";

/**
 * Render an execution timeline SVG.
 * @param {Array} points - array of { t, avg_duration, failures }
 * @returns {string} HTML string
 */
export function renderTimelineChart(points) {
  const width = 900;
  const height = 250;
  const padding = { top: 27, right: 52, bottom: 39, left: 58 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  if (!points.length) {
    return `<div class="empty-chart">Your execution trend will appear here after analysis.</div>`;
  }

  const chartPoints = points.length > 32
    ? Array.from({ length: 32 }, (_, i) => points[Math.round(i * (points.length - 1) / 31)])
    : points;

  const maxDuration = Math.max(...chartPoints.map((p) => Number(p.avg_duration) || 0), 1);
  const maxFailures = Math.max(...chartPoints.map((p) => Number(p.failures) || 0), 1);

  const grid = [0, 1, 2, 3].map((step) => {
    const y = padding.top + (chartHeight * step / 3);
    const durationTick = (maxDuration * (1 - step / 3)).toFixed(maxDuration < 10 ? 1 : 0);
    const failureTick = Math.round(maxFailures * (1 - step / 3));
    return `
      <line class="chart-grid-line" x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}"></line>
      <text class="chart-axis-label" x="${padding.left - 10}" y="${y + 4}" text-anchor="end">${escape(durationTick)}</text>
      <text class="chart-axis-label" x="${width - padding.right + 10}" y="${y + 4}" text-anchor="start">${escape(failureTick)}</text>
    `;
  }).join("");

  const bars = chartPoints.map((point, index) => {
    const slot = chartWidth / chartPoints.length;
    const failures = Number(point.failures) || 0;
    const barHeight = (failures / maxFailures) * chartHeight;
    const x = chartPoints.length === 1
      ? padding.left + (chartWidth - Math.max(3, chartWidth * 0.35)) / 2
      : padding.left + index * slot + slot * 0.25;
    const barWidth = chartPoints.length === 1 ? Math.max(3, chartWidth * 0.35) : Math.max(2, slot * 0.58);
    return `<rect class="chart-bar" x="${x.toFixed(1)}" y="${(padding.top + chartHeight - barHeight).toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="3"><title>${escape(point.t || "Run group")} · ${failures} failures</title></rect>`;
  }).join("");

  const coordinates = chartPoints.map((point, index) => ({
    x: padding.left + (chartPoints.length === 1 ? chartWidth / 2 : index * chartWidth / (chartPoints.length - 1)),
    y: padding.top + chartHeight - ((Number(point.avg_duration) || 0) / maxDuration) * chartHeight,
  }));

  const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const areaPath = `${path} L${coordinates[coordinates.length - 1].x.toFixed(1)},${(padding.top + chartHeight).toFixed(1)} L${coordinates[0].x.toFixed(1)},${(padding.top + chartHeight).toFixed(1)} Z`;

  const labelIndexes = [...new Set([0, Math.round((chartPoints.length - 1) * 0.25), Math.round((chartPoints.length - 1) * 0.5), Math.round((chartPoints.length - 1) * 0.75), chartPoints.length - 1])];
  const dateLabel = (value) => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value || "").slice(0, 10)
      : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(parsed);
  };
  const labels = labelIndexes.map((index) => chartPoints[index])
    .filter((point, index, items) => items.indexOf(point) === index)
    .map((point, index, items) => {
      const sourceIndex = chartPoints.indexOf(point);
      const x = padding.left + (chartPoints.length === 1 ? chartWidth / 2 : sourceIndex * chartWidth / (chartPoints.length - 1));
      return `<text class="chart-label" x="${x}" y="${height - 9}" text-anchor="${index === 0 ? "start" : index === items.length - 1 ? "end" : "middle"}"><title>${escape(point.t || "")}</title>${escape(dateLabel(point.t))}</text>`;
    }).join("");

  const markerIndexes = new Set(Array.from({ length: Math.min(8, chartPoints.length) }, (_, index) => Math.round(index * (chartPoints.length - 1) / Math.max(1, Math.min(8, chartPoints.length) - 1))));
  const markers = coordinates.filter((_, index) => markerIndexes.has(index))
    .map((point) => {
      const item = chartPoints[coordinates.indexOf(point)];
      return `<circle class="chart-point" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="4"><title>${escape(item.t || "Run group")} · ${Number(item.avg_duration || 0).toFixed(2)}s average · ${Number(item.failures || 0)} failures</title></circle>`;
    }).join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Timeline of average duration and detected failures">
      <defs>
        <linearGradient id="timelineChartFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#60e8df" stop-opacity=".24"/>
          <stop offset="100%" stop-color="#60e8df" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <text class="chart-axis-title" x="${padding.left}" y="13">AVG RUNTIME · SECONDS</text>
      <text class="chart-axis-title" x="${width - padding.right}" y="13" text-anchor="end">FLAGGED RUNS</text>
      ${grid}${bars}
      <path class="chart-area" d="${areaPath}" style="fill:url(#timelineChartFill)"></path>
      <path class="chart-line" d="${path}"></path>
      ${markers}
      ${labels}
    </svg>
  `;
}

/**
 * Render a task failure rate mini chart (horizontal bars).
 * @param {Array} tasks - array of { task, runs, flagged, avg_duration }
 * @returns {string} HTML string
 */
export function renderTaskRateChart(tasks) {
  const topTasks = tasks.map((task) => ({
    ...task,
    rate: Number(task.runs || 0) ? Number(task.flagged || 0) / Number(task.runs) : 0,
  })).sort((a, b) => b.rate - a.rate).slice(0, 7);

  if (!topTasks.length) {
    return '<div class="empty-row">Task-level results will appear after analysis.</div>';
  }

  const maxRate = Math.max(...topTasks.map((t) => t.rate), 0.01);

  return topTasks.map((task) => {
    const health = task.rate > 0.15 ? "critical" : task.rate > 0.05 ? "watch" : "good";
    return `
      <div class="task-rate-row">
        <span class="task-rate-name" title="${escape(task.task)}">${escape(task.task)}</span>
        <span class="task-rate-track"><i class="${health}" style="width:${Math.max(task.rate ? 2 : 0, task.rate / maxRate * 100)}%"></i></span>
        <strong>${Number(task.rate * 100).toFixed(1)}%</strong>
        <small>${number(task.flagged)} / ${number(task.runs)} flagged</small>
      </div>
    `;
  }).join("");
}
