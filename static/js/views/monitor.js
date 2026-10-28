/**
 * Monitor view
 * Renders Airflow status, recovery events, and execution logs.
 */

import { MetricCard, DataTable, escape, number, formatTime } from "../components.js";

/** @param {HTMLElement} container */
/** @param {Object} monitor - /api/monitor response */
/** @param {Array} logs - log lines */
export function renderMonitor(container, monitor, logs = []) {
  const recovery = monitor.recovery || {};
  const summary = recovery.monitor || {};
  const recoveryStats = recovery.recovery || {};
  const records = Array.isArray(recovery.records) ? recovery.records : [];

  container.innerHTML = `
      <div class="section-heading"><div>
        <h2>Monitoring & recovery</h2>
        <p>Airflow failures and approved retries.</p>
      </div></div>

      <article class="panel monitor-panel airflow-panel">
        <div class="panel-heading"><div>
          <h2>Apache Airflow connection</h2>
          <p id="airflow-status">Checking integration setup…</p>
        </div><div class="airflow-actions">
          <button class="button button-secondary" id="airflow-refresh" type="button">Check Airflow</button>
          <button class="button button-primary" id="airflow-retry" type="button" disabled>Retry approved failures</button>
        </div></div>
        <p class="scheduler-note" id="airflow-config-note">Configure the Airflow API URL, version, credentials, DAG allowlist, and task allowlist in the server environment.</p>
        <div class="table-scroll"><table>
          <thead><tr><th>DAG</th><th>Run</th><th>Task</th><th>State</th><th>Attempt</th></tr></thead>
          <tbody id="airflow-failures"><tr><td colspan="5" class="empty-row">No Airflow tasks loaded.</td></tr></tbody>
        </table></div>
        <div id="airflow-events" class="airflow-events" aria-live="polite"></div>
      </article>

      <div class="metric-grid monitor-summary">
        ${[
          ["Recent analyses", number((monitor.history || []).length)],
          ["Task attempts", number(summary.total_runs || 0)],
          ["Successful attempts", number(summary.success || 0)],
          ["Tasks recovered", number(recoveryStats.recovered || 0)],
        ].map(([label, value]) => `
          <article class="metric-card">
            <div class="metric-top">${escape(label)}</div>
            <div class="metric-value">${escape(value)}</div>
          </article>
        `).join("")}
      </div>

      <article class="panel monitor-panel">
        <div class="panel-heading"><div>
          <h2>Recovery events</h2>
          <p>Recent retries</p>
        </div><button class="button button-secondary" id="monitor-recovery-button" type="button">Run recovery</button></div>
        <div class="table-scroll"><table>
          <thead><tr><th>Task</th><th>Status</th><th>Attempt</th><th>Duration</th><th>Details</th></tr></thead>
          <tbody id="monitor-events">${renderRecoveryRows(records)}</tbody>
        </table></div>
      </article>

      <article class="panel monitor-logs-panel">
        <div class="panel-heading"><div>
          <h2>Execution log</h2>
          <p>Latest framework activity</p>
        </div></div>
        <pre id="monitor-logs" class="log-console">${escape(renderLogs(logs))}</pre>
      </article>
  `;

  // Expose elements for the controller to wire Airflow buttons
  container._airflowElements = {
    status: container.querySelector("#airflow-status"),
    configNote: container.querySelector("#airflow-config-note"),
    retryButton: container.querySelector("#airflow-retry"),
    failureTable: container.querySelector("#airflow-failures"),
    eventsEl: container.querySelector("#airflow-events"),
  };
}

/** @param {Array} records */
function renderRecoveryRows(records) {
  if (!records.length) {
    return `<tr><td colspan="5" class="empty-row">No recovery events recorded. Run the recovery demo to exercise automated retries.</td></tr>`;
  }
  return records.map((record) => {
    const successfulRetry = records.find((later) =>
      later.task === record.task
      && later.status === "SUCCESS"
      && Number(later.attempt) > Number(record.attempt)
    );
    const status = successfulRetry ? "RETRIED" : record.status === "FAILED" ? "FAILED" : record.status;
    const statusClass = successfulRetry || status === "SUCCESS" ? "good" : status === "TIMEOUT" ? "critical" : "watch";
    const details = successfulRetry
      ? `Recovered on attempt ${number(successfulRetry.attempt)} · temporary issue`
      : record.error_msg || "—";
    return `
      <tr>
        <td>${escape(record.task)}</td>
        <td><span class="health-pill ${statusClass}">${escape(status)}</span></td>
        <td>${number(record.attempt)}</td>
        <td>${Number(record.duration_s || 0).toFixed(3)}s</td>
        <td>${escape(details)}</td>
      </tr>
    `;
  }).join("");
}

/** @param {Array} logs */
function renderLogs(logs) {
  if (!logs.length) return "No execution log entries yet.";
  // Group log lines into entries
  const entries = [];
  let entry = [];
  logs.forEach((line) => {
    if (/^(?:\d{4}-\d{2}-\d{2}[ T]|Traceback \(most recent call last\):)/.test(line)) {
      if (entry.length) entries.push(entry.join("\n"));
      entry = [];
    }
    entry.push(line);
  });
  if (entry.length) entries.push(entry.join("\n"));
  // Filter out recovery demo noise
  const filtered = entries.filter((e) =>
    !/\|\s(?:monitor|recovery)\s\|\stask=(?:extract|transform|load|validate_schema)\b/.test(e)
    && !/applying corrective action '(?:recreate_file|reconnect)'/.test(e)
    && !/(?:source file missing|warehouse unreachable|schema mismatch: column 'amount' missing)/.test(e)
  );
  return filtered.length ? filtered.join("\n") : "No non-demo execution log entries yet. Recovery-demo attempts are summarized above.";
}

/**
 * Update the Airflow status sub-component.
 * @param {HTMLElement} container
 * @param {Object} data - /api/airflow response
 */
export function updateAirflow(container, data) {
  const els = container._airflowElements;
  if (!els) return;

  const state = data.status || {};
  const configured = state.configured === true;
  const ready = state.ready_for_automation === true;

  if (els.status) {
    els.status.textContent = data.error
      ? data.error
      : configured
        ? `Connected to Airflow ${String(state.api_version || "").toUpperCase()}${ready ? " · automatic retries enabled" : " · read-only until retry policy is enabled"}`
        : "Not connected · setup required";
  }
  if (els.configNote) {
    els.configNote.textContent = configured
      ? `Approved DAGs: ${(state.dag_allowlist || []).join(", ") || "none"}. Approved tasks: ${(state.task_allowlist || []).join(", ") || "none"}. Allowlist only idempotent tasks safe to rerun; inputs and connections are never modified.`
      : "Set AIRFLOW_API_URL and API version. Airflow 2 commonly uses basic auth; Airflow 3 uses jwt auth (username/password token exchange) or a pre-issued bearer token. Add DAG and task allowlists before enabling retries.";
  }
  if (els.retryButton) els.retryButton.disabled = !ready || Boolean(data.error);

  const failures = Array.isArray(data.failed_tasks) ? data.failed_tasks : [];
  if (els.failureTable) {
    els.failureTable.innerHTML = failures.length
      ? failures.map((t) => `
        <tr>
          <td>${escape(t.dag_id || "")}</td>
          <td>${escape(t.dag_run_id || "")}</td>
          <td>${escape(t.task_id || "")}</td>
          <td>${escape(t.state || "failed")}</td>
          <td>${escape(t.try_number ?? "—")}</td>
        </tr>
      `).join("")
      : `<tr><td colspan="5" class="empty-row">${configured && !data.error ? "No failed tasks in the approved DAGs." : "Airflow task data is unavailable until the connection is configured."}</td></tr>`;
  }
  const events = Array.isArray(data.events) ? data.events : [];
  if (els.eventsEl) {
    els.eventsEl.innerHTML = events.length
      ? `<strong>Recent Airflow recovery actions</strong>${events.slice(0, 5).map((e) => `
        <div>${escape(e.time || "")} · ${escape(e.dag_id || "")} / ${escape(e.task_id || "")} · ${escape(e.status || "")} · ${escape(e.detail || "")}</div>
      `).join("")}`
      : "";
  }
}
