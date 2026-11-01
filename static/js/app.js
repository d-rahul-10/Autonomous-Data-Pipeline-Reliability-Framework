/**
 * PipelineIQ Main Application
 * Orchestrates the dashboard: tab routing, API data fetching, state synchronization,
 * view rendering, and user interaction handling. All modules are ES modules imported
 * statically for a clean dependency graph.
 */

import { Api, ApiError } from "./api.js";
import { state, set, get, subscribe, patchAnalysis, upsertJob, removeJob } from "./store.js";
import { validateLogin, validateSignup, validateSchedule } from "./validation.js";
import {
  Button, SecondaryButton, TextButton, Notice, Loader, Skeleton, EmptyState,
  MetricCard, FilePicker, SelectField, CheckboxField, InputField,
  escape, number, percent, toggleVisibility,
} from "./components.js";
import { views } from "./views/index.js";
import { updateAirflow } from "./views/monitor.js";
import { updateScheduler } from "./views/scheduler.js";

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------
const els = {
  appShell: document.querySelector(".app-shell"),
  sideNav: document.querySelector(".side-nav"),
  results: document.getElementById("results"),
  welcomeCard: document.getElementById("welcome-card"),
  notice: document.getElementById("notice"),
  noticeTitle: document.getElementById("notice-title"),
  noticeMessage: document.getElementById("notice-message"),
  noticeClose: document.getElementById("notice-close"),
  loadingPanel: document.getElementById("loading-panel"),
  analysisProgressTitle: document.getElementById("analysis-progress-title"),
  analysisProgressDetail: document.getElementById("analysis-progress-detail"),
  systemStatus: document.getElementById("system-status"),
  runAnalysis: document.getElementById("run-analysis"),
  refreshButton: document.getElementById("refresh-button"),
  logoutButton: document.getElementById("logout-button"),
  lastRun: document.getElementById("last-run"),
  breadcrumbs: document.querySelector(".breadcrumbs strong"),
  pageSubtitle: document.querySelector(".page-subtitle"),
  fileInput: document.getElementById("csv-file"),
  fileLabel: document.getElementById("file-label"),
  sourceNote: document.getElementById("source-note"),
  sampleRows: document.getElementById("sample-rows"),
  mainContent: document.getElementById("main-content"),
  profileName: document.getElementById("profile-name"),
  profileAvatar: document.querySelector(".profile .avatar"),
  profileState: document.getElementById("profile-state"),
};

// Tab config
const tabTitles = {
  overview: { title: "Overview", subtitle: "Health, performance, and risks." },
  health: { title: "Task health", subtitle: "Runs, failures, and runtime." },
  risk: { title: "Risks", subtitle: "Runs needing review." },
  quality: { title: "Data quality", subtitle: "Schema and data checks." },
  performance: { title: "Performance", subtitle: "Runtime and resource use." },
  monitor: { title: "Monitor & recovery", subtitle: "Activity and retries." },
  reports: { title: "Reports", subtitle: "Saved analyses and history." },
  scheduler: { title: "Scheduler", subtitle: "Schedule recurring analyses." },
};
const tabHashes = {
  overview: "#overview", health: "#task-health", risk: "#risk-analysis",
  quality: "#data-quality", performance: "#performance", monitor: "#monitoring",
  reports: "#reports", scheduler: "#scheduler",
};

let activeTab = "overview";
let pollInterval = null;
let isPolling = false;
let currentAnalysisJob = null;

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function showNotice(message, title = "We couldn’t complete the analysis") {
  els.noticeTitle.textContent = title;
  els.noticeMessage.textContent = message;
  els.notice.classList.remove("entering");
  void els.notice.offsetHeight;
  els.notice.classList.add("entering");
  toggleVisibility(els.notice, false);
  els.notice.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearNotice() {
  els.notice.classList.remove("entering");
  toggleVisibility(els.notice, true);
  els.noticeMessage.textContent = "";
}

function setBusy(busy, stage = "") {
  [els.runAnalysis, els.refreshButton, ...document.querySelectorAll("[data-run-analysis]"), document.getElementById("welcome-run")].forEach((b) => {
    if (!b) return;
    b.disabled = busy;
    b.setAttribute("aria-busy", String(busy));
  });
  toggleVisibility(els.loadingPanel, busy);
  if (busy) {
    els.loadingPanel.classList.remove("fade-in");
    void els.loadingPanel.offsetHeight;
    els.loadingPanel.classList.add("fade-in");
  } else {
    els.loadingPanel.classList.remove("fade-in");
  }
  if (els.runAnalysis) {
    els.runAnalysis.innerHTML = busy
      ? '<span class="loader" aria-hidden="true"></span> Analyzing…'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"/></svg> Run analysis';
  }
  if (!busy) updateAnalysisProgress();
  else updateAnalysisProgress(stage || "starting", 0);
}

const analysisStageLabels = {
  queued: "Waiting for the analysis worker",
  starting: "Preparing analysis",
  reading_csv: "Reading CSV data",
  validating: "Validating input",
  cleaning: "Cleaning pipeline records",
  detecting_failures: "Detecting failures",
  training_model: "Training risk model",
  computing_metrics: "Computing dashboard metrics",
  finalizing: "Saving results",
  done: "Analysis complete",
  error: "Analysis failed",
  timeout: "Analysis timed out",
};

function updateAnalysisProgress(stage = "", progress = null) {
  if (els.analysisProgressTitle) {
    els.analysisProgressTitle.textContent = analysisStageLabels[stage] || "Analyzing";
  }
  if (els.analysisProgressDetail) {
    els.analysisProgressDetail.textContent = progress == null
      ? "Large datasets may take a moment."
      : `${Math.max(0, Math.min(100, Number(progress) || 0))}% complete — your dashboard will update automatically.`;
  }
}

function updateLastRun(generatedAt) {
  if (!els.lastRun || !generatedAt) return;
  const ts = new Date(generatedAt);
  if (!Number.isNaN(ts.getTime())) {
    els.lastRun.textContent = `Updated ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(ts)}`;
  }
}

function setSystemStatus(ready, schedule) {
  if (!els.systemStatus) return;
  const live = ready && Boolean(schedule?.enabled);
  els.systemStatus.classList.toggle("offline", !ready);
  els.systemStatus.classList.toggle("live", live);
  const label = !ready
    ? "Connection unavailable"
    : live
      ? schedule.running ? "Live · analyzing" : `Live · every ${number(schedule.interval_seconds)}s`
      : "System ready";
  els.systemStatus.innerHTML = `<span class="status-dot"></span> ${escape(label)}`;
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

function activateTab(tab, updateHistory = true) {
  if (!Object.hasOwn(tabTitles, tab)) tab = "overview";
  activeTab = tab;

  // Sidebar nav
  els.sideNav.querySelectorAll("[data-tab]").forEach((link) => {
    const selected = link.dataset.tab === tab;
    link.classList.toggle("active", selected);
    link.setAttribute("aria-selected", String(selected));
    link.tabIndex = selected ? 0 : -1;
  });

  // Breadcrumbs
  if (els.breadcrumbs) els.breadcrumbs.textContent = tabTitles[tab].title;
  if (els.pageSubtitle) els.pageSubtitle.textContent = tabTitles[tab].subtitle;

  // Show results shell for data tabs
  const needsAnalysis = ["overview", "health", "risk", "quality", "performance"].includes(tab);
  const hasAnalysis = Boolean(state.analysis);

  if (["reports", "scheduler", "monitor"].includes(tab) && els.results) {
    toggleVisibility(els.results, false);
  }

  // Tab views
  document.querySelectorAll("[data-tab-view]").forEach((view) => {
    const selected = view.dataset.tabView === tab;
    const show = selected && (!needsAnalysis || hasAnalysis);
    toggleVisibility(view, !show);
  });

  // Empty states
  const emptyStates = {
    health: document.getElementById("health-empty"),
    risk: document.getElementById("risk-empty"),
    quality: document.getElementById("quality-empty"),
    performance: document.getElementById("performance-empty"),
    monitor: document.getElementById("monitor-empty"),
  };
  Object.values(emptyStates).forEach((el) => { if (el) toggleVisibility(el, true); });
  if (emptyStates[tab] && !hasAnalysis) toggleVisibility(emptyStates[tab], false);

  // Welcome card
  if (els.welcomeCard) toggleVisibility(els.welcomeCard, tab !== "overview" || hasAnalysis);

  // Bring the newly selected view into focus with a small stagger.
  const activeView = [...document.querySelectorAll("[data-tab-view], .tab-empty-state, .welcome-card")]
    .find((view) => !view.hidden);
  if (activeView) {
    activeView.classList.remove("is-entering");
    requestAnimationFrame(() => {
      activeView.classList.remove("is-entering");
      void activeView.offsetWidth;
      activeView.classList.add("is-entering");
    });
  }

  // Update URL
  if (updateHistory && window.location.hash !== tabHashes[tab]) {
    window.history.pushState({ tab }, "", tabHashes[tab]);
  }

  // Load data for this tab
  void loadTabData(tab);
}

function switchTabFromHash() {
  const hash = window.location.hash;
  const tab = Object.keys(tabHashes).find((name) => tabHashes[name] === hash) || "overview";
  activateTab(tab, false);
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadTabData(tab) {
  try {
    switch (tab) {
      case "health":
      case "risk":
      case "quality":
      case "performance":
        if (state.analysis) renderView(tab, state.analysis);
        break;
      case "reports": {
        const [reportData, historyData] = await Promise.all([
          Api.getReports(),
          Api.getHistory(),
        ]);
        set("reports", reportData.reports || []);
        set("history", historyData.history || []);
        renderView(tab, { reports: state.reports, history: state.history });
        break;
      }
      case "monitor": {
        const [monitorData, logData] = await Promise.all([
          Api.getMonitor(),
          Api.getLogs(150),
        ]);
        set("monitor", monitorData);
        renderView(tab, { ...monitorData, logs: logData.logs || [] });
        await loadAirflowStatus();
        break;
      }
      case "scheduler": {
        const [scheduleData, datasetData] = await Promise.all([
          Api.getSchedule(),
          Api.listDatasets(),
        ]);
        set("schedule", scheduleData.schedule);
        set("datasets", datasetData.datasets || []);
        renderView(tab, { schedule: state.schedule, datasets: state.datasets });
        break;
      }
    }
  } catch (error) {
    handleApiError(error, "Could not load this workspace.");
  }
}

/** Render a view through the views registry. */
function renderView(tab, data) {
  const view = views[tab];
  const container = document.querySelector(`[data-tab-view="${tab}"]`);
  if (!view || !container) return;
  if (tab === "health") view(container, data.by_task || []);
  else if (tab === "risk") view(container, data.top_risk || [], data.by_task || []);
  else if (tab === "quality") view(container, data.data_quality || {});
  else if (tab === "performance") view(container, data.performance || {}, data.timeline || []);
  else view(container, data);

  // Wire view-specific interactive elements after render
  if (tab === "scheduler") wireScheduler(container);
  if (tab === "quality") wireQualityToggle(container, data);
  animateReportView(container);
}

/**
 * Give each report visual a short, ordered entrance.  This is deliberately
 * presentation-only: it never changes the data, filtering, or chart values.
 */
function animateReportView(container) {
  const cards = container.querySelectorAll(
    ".metric-card, .panel, .recovery-panel, .risk-item, .quality-finding, .task-rate-row"
  );
  cards.forEach((element, index) => {
    element.classList.remove("report-reveal", "is-visible");
    element.style.setProperty("--reveal-delay", `${Math.min(index, 10) * 45}ms`);
    element.classList.add("report-reveal");
  });
  requestAnimationFrame(() => {
    cards.forEach((element) => element.classList.add("is-visible"));
  });
}

/** Wire quality toggle on dashboard. */
function wireQualityToggle(container, data) {
  const toggle = container.querySelector("#quality-toggle");
  const listEl = container.querySelector("#quality-list");
  const issues = Array.isArray(data.data_quality?.issues) ? data.data_quality.issues : [];
  if (!toggle || !listEl) return;
  let expanded = false;
  const renderList = () => {
    const visible = expanded ? issues : issues.slice(0, 4);
    const items = visible.map((issue) => {
      const count = issue.count == null ? ((issue.columns || []).length || "Review") : number(issue.count);
      return `<div class="quality-item"><span>${escape(issue.type.replaceAll("_", " "))}</span><span>${escape(count)}</span></div>`;
    });
    if (!issues.length) {
      items.push('<div class="quality-item"><span>Schema and required fields</span><span class="quality-clear">Passed</span></div>');
      items.push('<div class="quality-item"><span>Missing and duplicate data</span><span class="quality-clear">Passed</span></div>');
    }
    listEl.innerHTML = items.join("");
  };
  renderList();
  toggle.addEventListener("click", () => {
    expanded = !expanded;
    toggle.textContent = expanded ? "Show fewer checks ↑" : `View all ${issues.length} quality checks →`;
    renderList();
  });
}

/** Wire scheduler form and upload. */
function wireScheduler(container) {
  const els = container._schedulerElements;
  if (!els) return;

  // Source toggle
  els.sourceSelect.addEventListener("change", () => {
    const usesCsv = els.sourceSelect.value === "csv";
    document.getElementById("schedule-rows-field").hidden = usesCsv;
    document.getElementById("schedule-dataset-field").hidden = !usesCsv;
  });

  // Save schedule
  els.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearNotice();
    els.saveButton.disabled = true;
    els.saveButton.textContent = "Saving…";
    try {
      const data = await Api.setSchedule({
        enabled: els.enabledCheckbox.checked,
        interval_seconds: parseInt(els.intervalSelect.value, 10),
        rows: parseInt(els.rowsSelect.value, 10),
        source_type: els.sourceSelect.value,
        dataset_name: els.datasetSelect.value,
      });
      set("schedule", data.schedule);
      updateScheduler(container, state.schedule, state.datasets);
      setSystemStatus(true, state.schedule);
    } catch (error) {
      handleApiError(error, "Could not save the schedule.");
    } finally {
      els.saveButton.disabled = false;
      els.saveButton.textContent = "Save schedule";
    }
  });

  // Upload dataset CSV
  els.uploadButton.addEventListener("click", async () => {
    clearNotice();
    const file = els.csvFile.files?.[0];
    if (!file) {
      showNotice("Choose an ETL CSV file first.", "No CSV selected");
      return;
    }
    els.uploadButton.disabled = true;
    els.uploadButton.textContent = "Saving CSV…";
    els.uploadStatus.textContent = "";
    try {
      const result = await Api.uploadDataset(file);
      const datasets = await Api.listDatasets();
      set("datasets", datasets.datasets || []);
      updateScheduler(container, state.schedule, state.datasets);
      els.uploadStatus.textContent = `${result.dataset.name} saved and ready for scheduled analysis.`;
      els.csvFile.value = "";
    } catch (error) {
      handleApiError(error, "Could not save the scheduled CSV.");
    } finally {
      els.uploadButton.disabled = false;
      els.uploadButton.textContent = "Save CSV for scheduling";
    }
  });
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function runAnalysis() {
  clearNotice();
  const file = els.fileInput?.files?.[0];
  if (!file && !els.sampleRows?.value) {
    showNotice("Upload your ETL CSV or choose a generated sample before running the analysis.", "Choose a data source");
    return;
  }

  setBusy(true, "starting");
  try {
    // The service already exposes a job API.  Use it for every dashboard
    // submission so a slow model fit never exceeds the browser request
    // deadline or leaves the loading panel without a completion path.
    let started;
    if (file) {
      started = await Api.analyzeFile(file, { async: true });
    } else {
      started = await Api.analyzeSample(parseInt(els.sampleRows.value, 10) || 30000, { async: true });
    }
    if (!started?.job_id) throw new ApiError(500, "The analysis service did not return a job identifier.");
    const result = await waitForAnalysisJob(started.job_id);
    set("analysis", result);
    updateLastRun(result.generated_at);
    setSystemStatus(true);
    renderView("overview", result);
    if (els.results) toggleVisibility(els.results, false);
    if (els.welcomeCard) toggleVisibility(els.welcomeCard, true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    handleApiError(error, "Analysis failed. Please check your data and try again.");
  } finally {
    setBusy(false);
  }
}

async function waitForAnalysisJob(jobId) {
  currentAnalysisJob = jobId;
  const pollDelayMs = 750;
  // A server deadline is authoritative.  This client-side guard also covers
  // an older/stale server that never returns a terminal state.
  let deadline = Date.now() + 6 * 60 * 1000;
  try {
    while (currentAnalysisJob === jobId) {
      const job = await Api.getJob(jobId);
      upsertJob(jobId, job);
      updateAnalysisProgress(job.stage, job.progress);
      const serverDeadline = Date.parse(job.deadline_at || "");
      if (!Number.isNaN(serverDeadline)) deadline = Math.min(deadline, serverDeadline + 5000);
      if (job.status === "completed") {
        if (!job.result) throw new ApiError(500, "Analysis completed without dashboard results.");
        return job.result;
      }
      if (job.status === "failed") {
        throw new ApiError(500, job.error || "Analysis could not be completed.");
      }
      if (Date.now() >= deadline) {
        throw new ApiError(408, "Analysis timed out before the server returned a result. Please try again with a smaller CSV.");
      }
      await new Promise((resolve) => window.setTimeout(resolve, pollDelayMs));
    }
    throw new ApiError(409, "The analysis job was superseded.");
  } finally {
    if (currentAnalysisJob === jobId) currentAnalysisJob = null;
    removeJob(jobId);
  }
}

async function runRecoveryDemo() {
  clearNotice();
  const button = document.getElementById("recovery-button") || document.getElementById("monitor-recovery-button");
  const resultEl = document.getElementById("recovery-result");
  if (button) { button.disabled = true; button.textContent = "Running recovery…"; }
  if (resultEl) { toggleVisibility(resultEl, true); resultEl.textContent = ""; }

  try {
    const data = await Api.recoveryDemo();
    const recovery = data.recovery || {};
    if (resultEl) {
      resultEl.textContent = `Recovery demo complete · ${number(data.rows_loaded)} rows loaded · ${number(recovery.recovered || 0)} tasks recovered · ${number(recovery.non_recoverable || 0)} issue${Number(recovery.non_recoverable || 0) === 1 ? "" : "s"} escalated.`;
      toggleVisibility(resultEl, false);
    }
    if (activeTab === "monitor") await loadTabData("monitor");
  } catch (error) {
    handleApiError(error, "Recovery failed.");
  } finally {
    if (button) { button.disabled = false; button.innerHTML = 'Run recovery <span aria-hidden="true">→</span>'; }
  }
}

async function requestAirflowRetry(button) {
  button.disabled = true;
  button.textContent = "Checking failures…";
  try {
    await Api.retryAirflow();
    await loadAirflowStatus();
    showNotice("Approved retry request(s) sent to Airflow.", "Airflow recovery complete");
  } catch (error) {
    handleApiError(error, "Could not request Airflow retries.");
  } finally {
    button.disabled = false;
    button.textContent = "Retry approved failures";
    await loadAirflowStatus();
  }
}

async function logout() {
  if (!els.logoutButton) return;
  els.logoutButton.disabled = true;
  try {
    await Api.logout();
    window.location.assign("/auth");
  } catch (error) {
    handleApiError(error, "Could not log out.");
  } finally {
    els.logoutButton.disabled = false;
  }
}

async function loadAccountProfile() {
  try {
    const payload = await Api.me();
    const user = payload.user || {};
    const fullName = String(user.name || "").trim();
    const emailName = String(user.email || "").split("@")[0].trim();
    const displayName = !fullName || fullName.toLowerCase() === "pipeline demo"
      ? emailName || "Account"
      : fullName;
    if (els.profileName) { els.profileName.textContent = displayName; els.profileName.title = displayName; }
    if (els.profileAvatar) els.profileAvatar.textContent = displayName.slice(0, 2).toUpperCase();
    if (els.profileState) els.profileState.textContent = "Signed in";
    set("user", user);
    set("authenticated", true);
  } catch {
    // Keep server-rendered name if profile endpoint is unavailable
  }
}

async function loadAirflowStatus() {
  try {
    const data = await Api.getAirflow();
    const container = document.querySelector('[data-tab-view="monitor"]');
    if (container) updateAirflow(container, data);
    set("airflow", data);
  } catch (error) {
    const container = document.querySelector('[data-tab-view="monitor"]');
    if (container) updateAirflow(container, { status: {}, error: error.message });
  }
}

// ---------------------------------------------------------------------------
// Live polling
// ---------------------------------------------------------------------------

async function refreshLiveState(showError = false) {
  if (isPolling || document.visibilityState === "hidden") return;
  isPolling = true;
  try {
    const stateData = await Api.getStatus();
    setSystemStatus(Boolean(stateData.ready), stateData.schedule);
    set("schedule", stateData.schedule);

    if (stateData.latest_analysis && stateData.latest_analysis.generated_at !== state.analysis?.generated_at) {
      set("analysis", stateData.latest_analysis);
      updateLastRun(stateData.latest_analysis.generated_at);
      renderView("overview", stateData.latest_analysis);
      if (els.results) toggleVisibility(els.results, false);
      if (els.welcomeCard) toggleVisibility(els.welcomeCard, true);
    }
  } catch (error) {
    setSystemStatus(false);
    if (showError) showNotice(error instanceof Error ? error.message : "Could not connect to the analysis service.", "Service unavailable");
  } finally {
    isPolling = false;
  }
}

function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(() => void refreshLiveState(), 10000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void refreshLiveState();
  });
}

function stopPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = null;
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

function handleApiError(error, fallbackMessage) {
  const message = error instanceof ApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : fallbackMessage;
  showNotice(message);
  console.error("PipelineIQ API error:", error);
}

// ---------------------------------------------------------------------------
// File input
// ---------------------------------------------------------------------------

function setupFileInput() {
  if (!els.fileInput || !els.fileLabel || !els.sourceNote) return;
  els.fileInput.addEventListener("change", () => {
    const file = els.fileInput.files?.[0];
    if (file) {
      els.fileLabel.textContent = file.name;
      els.sourceNote.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
    } else {
      els.fileLabel.textContent = "Choose CSV";
      els.sourceNote.textContent = "Required: timestamp, task_id, status, duration, CPU, memory, I/O, and latency.";
    }
  });
}

// ---------------------------------------------------------------------------
// Auth page (mounted only on /auth)
// ---------------------------------------------------------------------------

function initAuthPage() {
  const loginForm = document.getElementById("login-form");
  const signupForm = document.getElementById("signup-form");
  if (!loginForm && !signupForm) return;

  const errorMsg = document.getElementById("error-message");
  const successMsg = document.getElementById("success-message");
  const errorTitle = document.getElementById("error-title");
  const errorText = document.getElementById("error-text");
  const successTitle = document.getElementById("success-title");
  const successText = document.getElementById("success-text");

  function showAuthError(title, message) {
    if (successMsg) toggleVisibility(successMsg, true);
    if (errorMsg) {
      if (errorTitle) errorTitle.textContent = title;
      if (errorText) errorText.textContent = message;
      toggleVisibility(errorMsg, false);
      errorMsg.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
  function showAuthSuccess(title, message) {
    if (errorMsg) toggleVisibility(errorMsg, true);
    if (successMsg) {
      if (successTitle) successTitle.textContent = title;
      if (successText) successText.textContent = message;
      toggleVisibility(successMsg, false);
      successMsg.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
  function hideAuthMessages() {
    if (errorMsg) toggleVisibility(errorMsg, true);
    if (successMsg) toggleVisibility(successMsg, true);
  }

  function switchTab(tabName) {
    document.querySelectorAll(".auth-tab").forEach((t) => {
      const active = t.dataset.tab === tabName;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".auth-panel").forEach((p) => {
      const active = p.id === `panel-${tabName}`;
      p.classList.toggle("active", active);
      toggleVisibility(p, !active);
    });
  }

  // Tab switching
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.addEventListener("click", () => { switchTab(tab.dataset.tab); hideAuthMessages(); });
  });

  // Close buttons
  document.querySelectorAll("[data-close-message]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const type = btn.dataset.closeMessage;
      const el = document.getElementById(`${type}-message`);
      if (el) toggleVisibility(el, true);
    });
  });

  // Password toggles
  document.querySelectorAll(".password-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.input);
      const eyeOpen = btn.querySelector(".eye-open");
      const eyeClosed = btn.querySelector(".eye-closed");
      if (!input) return;
      if (input.type === "password") {
        input.type = "text";
        if (eyeOpen) toggleVisibility(eyeOpen, true);
        if (eyeClosed) toggleVisibility(eyeClosed, false);
        btn.setAttribute("aria-label", "Hide password");
      } else {
        input.type = "password";
        if (eyeOpen) toggleVisibility(eyeOpen, false);
        if (eyeClosed) toggleVisibility(eyeClosed, true);
        btn.setAttribute("aria-label", "Show password");
      }
    });
  });

  // Real-time validation
  ["login-email", "signup-email"].forEach((id) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener("blur", () => {
      const value = input.value.trim();
      if (value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
        input.classList.add("error");
        input.setAttribute("aria-invalid", "true");
        const err = document.getElementById(`${id}-error`);
        if (err) err.textContent = "Please enter a valid email address.";
      } else {
        input.classList.remove("error");
        input.removeAttribute("aria-invalid");
        const err = document.getElementById(`${id}-error`);
        if (err) err.textContent = "";
      }
    });
    input.addEventListener("input", () => {
      if (input.classList.contains("error")) {
        input.classList.remove("error");
        input.removeAttribute("aria-invalid");
        const err = document.getElementById(`${id}-error`);
        if (err) err.textContent = "";
      }
    });
  });

  // Login submit
  if (loginForm) {
    loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      hideAuthMessages();
      const email = document.getElementById("login-email").value;
      const password = document.getElementById("login-password").value;
      const remember = document.getElementById("remember-me").checked;

      const { valid, errors } = validateLogin({ email, password });
      if (!valid) {
        Object.entries(errors).forEach(([field, msg]) => {
          const input = document.getElementById(`login-${field}`);
          const errSpan = document.getElementById(`login-${field}-error`);
          if (input) { input.classList.add("error"); input.setAttribute("aria-invalid", "true"); }
          if (errSpan) errSpan.textContent = msg;
        });
        return;
      }

      const submitBtn = document.getElementById("login-submit");
      const btnText = submitBtn?.querySelector(".btn-text");
      const btnLoader = submitBtn?.querySelector(".btn-loader");
      submitBtn.disabled = true;
      if (btnText) btnText.style.visibility = "hidden";
      if (btnLoader) toggleVisibility(btnLoader, false);

      try {
        const response = await Api.login(email, password, remember);
        showAuthSuccess("Welcome back!", "Redirecting to your workspace…");
        setTimeout(() => { window.location.href = response.redirect || "/"; }, 1000);
      } catch (error) {
        showAuthError("Login failed", error instanceof Error ? error.message : "Login failed.");
      } finally {
        submitBtn.disabled = false;
        if (btnText) btnText.style.visibility = "visible";
        if (btnLoader) toggleVisibility(btnLoader, true);
      }
    });
  }

  // Signup submit
  if (signupForm) {
    signupForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      hideAuthMessages();
      const formData = {
        name: document.getElementById("signup-name").value,
        email: document.getElementById("signup-email").value,
        password: document.getElementById("signup-password").value,
        confirm: document.getElementById("signup-confirm").value,
        terms: document.getElementById("terms-agree").checked,
      };

      const { valid, errors } = validateSignup(formData);
      if (!valid) {
        Object.entries(errors).forEach(([field, msg]) => {
          const input = document.getElementById(`signup-${field}`);
          const errSpan = document.getElementById(`signup-${field}-error`);
          if (input) { input.classList.add("error"); input.setAttribute("aria-invalid", "true"); }
          if (errSpan) errSpan.textContent = msg;
        });
        if (errors.terms) {
          const errSpan = document.getElementById("terms-error");
          if (errSpan) errSpan.textContent = errors.terms;
        }
        return;
      }

      const submitBtn = document.getElementById("signup-submit");
      const btnText = submitBtn?.querySelector(".btn-text");
      const btnLoader = submitBtn?.querySelector(".btn-loader");
      submitBtn.disabled = true;
      if (btnText) btnText.style.visibility = "hidden";
      if (btnLoader) toggleVisibility(btnLoader, false);

      try {
        const response = await Api.signup(formData.name, formData.email, formData.password);
        showAuthSuccess("Account created!", "Redirecting to your workspace…");
        setTimeout(() => { window.location.href = response.redirect || "/"; }, 1000);
      } catch (error) {
        showAuthError("Registration failed", error instanceof Error ? error.message : "Registration failed.");
      } finally {
        submitBtn.disabled = false;
        if (btnText) btnText.style.visibility = "visible";
        if (btnLoader) toggleVisibility(btnLoader, true);
      }
    });
  }

  // Social buttons
  document.querySelectorAll(".btn-social").forEach((btn) => {
    btn.addEventListener("click", () => {
      const provider = btn.dataset.provider;
      showAuthError("Sign-in unavailable", `${provider} sign-in is not configured yet. Use your email and password instead.`);
    });
  });

  // Hash-based tab switching
  const hash = window.location.hash.slice(1);
  if (hash === "signup") switchTab("signup");
  window.addEventListener("hashchange", () => {
    const newHash = window.location.hash.slice(1);
    if (newHash === "signup" || newHash === "login") switchTab(newHash);
  });

  // Info dialog
  const dialog = document.getElementById("auth-info-dialog");
  if (dialog) {
    const closeBtn = document.getElementById("auth-info-close");
    const sections = [...dialog.querySelectorAll(".auth-info-card")];
    const openSection = (sectionId) => {
      sections.forEach((s) => toggleVisibility(s, s.id !== sectionId));
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      const selected = document.getElementById(sectionId);
      if (selected) selected.focus({ preventScroll: true });
    };
    document.addEventListener("click", (event) => {
      const link = event.target.closest("a[href]");
      if (!link) return;
      const sectionId = new URL(link.href, window.location.href).hash.slice(1);
      if (!["privacy", "terms", "support"].includes(sectionId)) return;
      event.preventDefault();
      openSection(sectionId);
    });
    if (closeBtn) closeBtn.addEventListener("click", () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        if (typeof dialog.close === "function") dialog.close();
        else dialog.removeAttribute("open");
      }
    });
    const initialHash = window.location.hash.slice(1);
    if (["privacy", "terms", "support"].includes(initialHash)) openSection(initialHash);
  }
}

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

async function init() {
  // Auth page
  if (document.body.classList.contains("auth-page") || document.getElementById("login-form")) {
    initAuthPage();
    return;
  }

  // Dashboard app
  setupFileInput();

  // Sidebar navigation
  els.sideNav?.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[data-tab]");
    if (!link || !els.sideNav.contains(link)) return;
    event.preventDefault();
    activateTab(link.dataset.tab);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  els.sideNav?.addEventListener("keydown", (event) => {
    const links = [...els.sideNav.querySelectorAll("[data-tab]")];
    const currentIndex = links.indexOf(document.activeElement);
    if (currentIndex < 0) return;
    let nextIndex = currentIndex;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") nextIndex += 1;
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft") nextIndex -= 1;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = links.length - 1;
    else return;
    event.preventDefault();
    const nextLink = links[(nextIndex + links.length) % links.length];
    nextLink.focus();
    activateTab(nextLink.dataset.tab);
  });

  // Action buttons
  [els.runAnalysis, els.refreshButton, document.querySelectorAll("[data-run-analysis]")].flat().forEach((btn) => {
    if (btn) btn.addEventListener("click", runAnalysis);
  });
  els.results?.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || !els.results.contains(button)) return;
    if (button.id === "recovery-button" || button.id === "monitor-recovery-button") {
      void runRecoveryDemo();
    } else if (button.id === "airflow-refresh") {
      void loadAirflowStatus();
    } else if (button.id === "airflow-retry") {
      void requestAirflowRetry(button);
    } else if (button.id === "refresh-reports") {
      void loadTabData("reports");
    }
  });
  els.logoutButton?.addEventListener("click", logout);

  // Footer link
  document.querySelector(".footer a")?.addEventListener("click", (event) => {
    event.preventDefault();
    document.getElementById("data-source")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // Notice close
  els.noticeClose?.addEventListener("click", clearNotice);

  // Popstate
  window.addEventListener("popstate", switchTabFromHash);

  // Initial load
  switchTabFromHash();
  await loadAccountProfile();
  await refreshLiveState(true);
  startPolling();
}

// Start when DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
