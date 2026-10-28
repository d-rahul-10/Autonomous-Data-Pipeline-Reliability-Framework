/**
 * Scheduler view
 * Renders recurring schedule configuration, dataset uploads, and schedule state.
 */

import { SelectField, CheckboxField, escape, number, formatTime } from "../components.js";

/** @param {HTMLElement} container */
/** @param {Object} schedule - schedule state */
/** @param {Array} datasets - dataset items */
export function renderScheduler(container, schedule, datasets = []) {
  const s = schedule || {};
  const selectedDataset = s.dataset_name || "";

  container.innerHTML = `
      <div class="section-heading"><div>
        <h2>Scheduler</h2>
        <p>Schedule recurring analyses.</p>
      </div></div>

      <article class="panel scheduler-panel">
        <div class="scheduler-status">
          <span class="schedule-indicator ${s.enabled ? "enabled" : ""}" id="schedule-indicator"></span>
          <div>
            <strong id="schedule-state">${s.running ? "Pipeline analysis running" : s.enabled ? "Scheduler active" : "Scheduler paused"}</strong>
            <span id="schedule-detail">${s.running ? "A scheduled data analysis is in progress." : s.enabled ? "The next run is scheduled below." : "Configure and enable an interval to start automatic runs."}</span>
          </div>
        </div>

        <form id="schedule-form" class="schedule-form" novalidate>
          <div class="form-group">
            <label class="form-label">Run interval</label>
            <select id="schedule-interval" class="form-input">
              <option value="15">Every 15 seconds (demo)</option>
              <option value="300">Every 5 minutes</option>
              <option value="900">Every 15 minutes</option>
              <option value="3600" ${s.interval_seconds === 3600 ? "selected" : ""}>Every hour</option>
              <option value="86400">Every day</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Data source</label>
            <select id="schedule-source" class="form-input">
              <option value="sample" ${s.source_type === "sample" ? "selected" : ""}>Generated sample</option>
              <option value="csv" ${s.source_type === "csv" ? "selected" : ""}>Saved ETL CSV</option>
            </select>
          </div>
          <div class="form-group" id="schedule-rows-field" ${s.source_type === "csv" ? "hidden" : ""}>
            <label class="form-label">Sample size</label>
            <select id="schedule-rows" class="form-input">
              <option value="1000">1,000 rows</option>
              <option value="10000" ${s.rows === 10000 ? "selected" : ""}>10,000 rows</option>
              <option value="50000">50,000 rows</option>
              <option value="100000">100,000 rows</option>
              <option value="500000">500,000 rows</option>
            </select>
          </div>
          <div class="form-group" id="schedule-dataset-field" ${s.source_type !== "csv" ? "hidden" : ""}>
            <label class="form-label">Saved CSV</label>
            <select id="schedule-dataset" class="form-input">
              <option value="">Upload or select a CSV</option>
              ${datasets.map((d) => `<option value="${escape(d.name)}" ${d.name === selectedDataset ? "selected" : ""}>${escape(d.name)} · ${number(d.size)} bytes</option>`).join("")}
            </select>
          </div>
          <label class="schedule-switch">
            <input type="checkbox" id="schedule-enabled" ${s.enabled ? "checked" : ""}>
            <span>Enable automatic runs</span>
          </label>
          <button class="button button-primary" id="save-schedule" type="submit">Save schedule</button>
        </form>

        <div class="schedule-upload">
          <label for="schedule-csv-file">Add or replace an ETL CSV <input id="schedule-csv-file" type="file" accept=".csv,text/csv" style="display:none"></label>
          <button class="button button-secondary" id="upload-schedule-csv" type="button">Save CSV for scheduling</button>
          <span id="schedule-upload-status" role="status"></span>
        </div>

        <div class="schedule-meta" id="schedule-meta">
          Next run: ${s.next_run ? formatTime(s.next_run) : "Not scheduled"} ·
          Last run: ${s.last_run ? formatTime(s.last_run) : "No runs yet"} ·
          Completed runs: ${number(s.runs || 0)}
        </div>
        <div class="schedule-error" id="schedule-error" ${!s.last_error ? "hidden" : ""}>${escape(s.last_error || "")}</div>
      </article>

      <p class="scheduler-note">CSV uploads are saved in <code>data/incoming/</code>. Each scheduled run reads the latest file contents, so an ETL job can replace that file with its newest export. The dashboard checks for completed analyses every 2 seconds and updates automatically. Keep the app running for scheduled runs.</p>
  `;

  // Wire source toggle
  const sourceSelect = container.querySelector("#schedule-source");
  const rowsField = container.querySelector("#schedule-rows-field");
  const datasetField = container.querySelector("#schedule-dataset-field");
  const datasetSelect = container.querySelector("#schedule-dataset");

  sourceSelect.addEventListener("change", () => {
    const usesCsv = sourceSelect.value === "csv";
    rowsField.hidden = usesCsv;
    datasetField.hidden = !usesCsv;
  });

  // Expose elements for controller
  container._schedulerElements = {
    form: container.querySelector("#schedule-form"),
    saveButton: container.querySelector("#save-schedule"),
    uploadButton: container.querySelector("#upload-schedule-csv"),
    csvFile: container.querySelector("#schedule-csv-file"),
    uploadStatus: container.querySelector("#schedule-upload-status"),
    scheduleError: container.querySelector("#schedule-error"),
    scheduleMeta: container.querySelector("#schedule-meta"),
    scheduleState: container.querySelector("#schedule-state"),
    scheduleDetail: container.querySelector("#schedule-detail"),
    scheduleIndicator: container.querySelector("#schedule-indicator"),
    enabledCheckbox: container.querySelector("#schedule-enabled"),
    intervalSelect: container.querySelector("#schedule-interval"),
    rowsSelect: container.querySelector("#schedule-rows"),
    sourceSelect,
    datasetSelect,
  };
}

/**
 * Update schedule UI with fresh state.
 * @param {HTMLElement} container
 * @param {Object} schedule
 * @param {Array} datasets
 */
export function updateScheduler(container, schedule, datasets = []) {
  const s = schedule || {};
  const els = container._schedulerElements;
  if (!els) return;

  els.enabledCheckbox.checked = Boolean(s.enabled);
  els.intervalSelect.value = String(s.interval_seconds || 3600);
  els.rowsSelect.value = String(s.rows || 10000);
  els.sourceSelect.value = s.source_type || "sample";
  els.datasetSelect.value = s.dataset_name || "";

  const usesCsv = els.sourceSelect.value === "csv";
  els.scheduleMeta.textContent = `Next run: ${s.next_run ? formatTime(s.next_run) : "Not scheduled"} · Last run: ${s.last_run ? formatTime(s.last_run) : "No runs yet"} · Completed runs: ${number(s.runs || 0)}`;
  els.scheduleState.textContent = s.running ? "Pipeline analysis running" : s.enabled ? "Scheduler active" : "Scheduler paused";
  els.scheduleDetail.textContent = s.running ? "A scheduled data analysis is in progress." : s.enabled ? "The next run is scheduled below." : "Configure and enable an interval to start automatic runs.";
  els.scheduleIndicator.classList.toggle("enabled", Boolean(s.enabled));
  els.scheduleError.hidden = !s.last_error;
  els.scheduleError.textContent = escape(s.last_error || "");

  // Refresh dataset options
  els.datasetSelect.innerHTML = `<option value="">Upload or select a CSV</option>` + datasets.map((d) => `
    <option value="${escape(d.name)}" ${d.name === s.dataset_name ? "selected" : ""}>${escape(d.name)} · ${number(d.size)} bytes</option>
  `).join("");
}
