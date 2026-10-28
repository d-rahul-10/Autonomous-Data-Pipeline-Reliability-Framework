/**
 * Task Health view
 * Renders task-level failure rates, summary stats, and a sortable/filterable task table.
 */

import { MetricCard, DataTable, healthPill, escape, number, percent } from "../components.js";
import { renderTaskRateChart } from "./charts.js";

/** @param {HTMLElement} container */
/** @param {Array} tasks - by_task array from analysis */
export function renderHealth(container, tasks) {
  const taskList = Array.isArray(tasks) ? tasks : [];
  const totalRuns = taskList.reduce((sum, t) => sum + Number(t.runs || 0), 0);
  const totalFlagged = taskList.reduce((sum, t) => sum + Number(t.flagged || 0), 0);
  const worstTask = taskList.reduce((worst, t) => {
    const rate = Number(t.runs || 0) ? Number(t.flagged || 0) / Number(t.runs) : 0;
    return !worst || rate > worst.rate ? { name: t.task, rate } : worst;
  }, null);

  container.innerHTML = `
      <div class="section-heading">
        <div>
          <h2>Task health</h2>
          <p>Runs, failures, and runtime.</p>
        </div>
        <span class="table-count">${number(taskList.length)} tasks</span>
      </div>

      <div class="metric-grid task-summary-grid">
        ${[
          ["Tasks observed", number(taskList.length), "Distinct pipeline task IDs"],
          ["Runs reviewed", number(totalRuns), "Across all observed tasks"],
          ["Flagged runs", `${number(totalFlagged)} · ${percent(totalRuns ? totalFlagged / totalRuns : 0)}`, "Runs requiring review"],
          ["Highest task rate", worstTask ? `${percent(worstTask.rate)} · ${escape(worstTask.name)}` : "N/A", "Flagged share in this dataset"],
        ].map(([label, value, caption]) => `
          <article class="metric-card task-stat-card">
            <div class="metric-top">${escape(label)}</div>
            <div class="metric-value">${escape(value)}</div>
            <div class="subtle-caption">${escape(caption)}</div>
          </article>
        `).join("")}
      </div>

      <article class="panel task-profile-panel">
        <div class="panel-heading"><div><h2>Failure rate</h2><p>By task</p></div></div>
        <div class="task-rate-chart" id="task-rate-chart">${renderTaskRateChart(taskList)}</div>
      </article>

      <article class="panel task-panel">
        <div class="task-table-toolbar">
          <label for="task-search">Find a task</label>
          <input id="task-search" type="search" placeholder="Search task names">
          <label for="task-sort">Sort by</label>
          <select id="task-sort">
            <option value="rate">Failure rate</option>
            <option value="flagged">Flagged runs</option>
            <option value="duration">Avg. runtime</option>
            <option value="runs">Run volume</option>
            <option value="name">Task name</option>
          </select>
          <span id="task-visible-count" role="status"></span>
        </div>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Task</th><th>Runs</th><th>Flagged</th><th>Failure rate</th><th>Avg. runtime</th><th>Health</th></tr></thead>
            <tbody id="task-rows"><tr><td colspan="6" class="empty-row">Task results will appear after analysis.</td></tr></tbody>
          </table>
        </div>
      </article>
  `;

  // Store task data on container for the controller to wire search/sort
  container.dataset.tasks = JSON.stringify(taskList);
  container._renderTaskTable = () => renderTaskTable(container, taskList);
  container._renderTaskTable();
}

/**
 * Render the task table with filtering and sorting.
 * @param {HTMLElement} container
 * @param {Array} tasks
 */
function renderTaskTable(container, tasks) {
  const searchEl = container.querySelector("#task-search");
  const sortEl = container.querySelector("#task-sort");
  const tbody = container.querySelector("#task-rows");
  const visibleCount = container.querySelector("#task-visible-count");
  if (!tbody) return;

  const query = (searchEl?.value || "").trim().toLowerCase();
  const sort = sortEl?.value || "rate";

  let rows = tasks.filter((t) => String(t.task).toLowerCase().includes(query));
  rows.sort((a, b) => {
    const rateA = Number(a.runs || 0) ? Number(a.flagged || 0) / Number(a.runs) : 0;
    const rateB = Number(b.runs || 0) ? Number(b.flagged || 0) / Number(b.runs) : 0;
    if (sort === "name") return String(a.task).localeCompare(String(b.task));
    const field = { rate: null, flagged: "flagged", duration: "avg_duration", runs: "runs" }[sort] || "flagged";
    const va = sort === "rate" ? rateA : Number(a[field] || 0);
    const vb = sort === "rate" ? rateB : Number(b[field] || 0);
    return vb - va;
  });

  if (visibleCount) visibleCount.textContent = `${number(rows.length)} shown`;

  tbody.innerHTML = rows.length
    ? rows.map((task) => {
      const flagged = Number(task.flagged || 0);
      const runs = Number(task.runs || 0);
      const rate = runs ? flagged / runs : 0;
      const health = rate > 0.15 ? "critical" : rate > 0.05 ? "watch" : "good";
      const label = health === "critical" ? "At risk" : health === "watch" ? "Monitor" : "Healthy";
      return `
        <tr>
          <td>${escape(task.task)}</td>
          <td>${number(runs)}</td>
          <td>${number(flagged)}</td>
          <td><div class="failure-rate-cell"><span>${percent(rate)}</span><i><b class="${health}" style="width:${Math.min(100, rate * 100)}%"></b></i></div></td>
          <td>${Number(task.avg_duration || 0).toFixed(1)}s</td>
          <td>${healthPill(health)}</td>
        </tr>
      `;
    }).join("")
    : `<tr><td colspan="6" class="empty-row">No tasks match that search.</td></tr>`;
}
