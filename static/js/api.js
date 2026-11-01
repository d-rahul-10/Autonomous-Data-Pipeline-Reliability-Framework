/**
 * PipelineIQ API Client
 * Centralized fetch wrapper with CSRF, typed responses, timeouts, retries,
 * and consistent error handling aligned with the backend API contract.
 */

/** @typedef {Object} ApiError
 * @property {string} error - Human-readable error message
 */

/** @typedef {Object} AuthUser
 * @property {number} id
 * @property {string} name
 * @property {string} email
 */

/** @typedef {Object} AnalysisPayload
 * @property {string} source
 * @property {string} generated_at
 * @property {number} rows_raw
 * @property {number} rows_clean
 * @property {Object} data_quality
 * @property {Object} failures
 * @property {Object} model
 * @property {Object} performance
 * @property {Array} timeline
 * @property {Array} by_task
 * @property {Array} top_risk
 * @property {string} report_file
 */

/** @typedef {Object} ScheduleState
 * @property {boolean} enabled
 * @property {number} interval_seconds
 * @property {number} rows
 * @property {string} source_type
 * @property {string} dataset_name
 * @property {string|null} next_run
 * @property {string|null} last_run
 * @property {string|null} last_error
 * @property {number} runs
 * @property {boolean} running
 */

/** @typedef {Object} AirflowStatus
 * @property {Object} status
 * @property {Array} failed_tasks
 * @property {Array} events
 * @property {string|null} error
 */

/** @typedef {Object} RecoveryResult
 * @property {number} rows_loaded
 * @property {Object} recovery
 * @property {Object} monitor
 * @property {Array} records
 */

/** @typedef {Object} HistoryItem
 * @property {string} generated_at
 * @property {string} source
 * @property {number} rows_raw
 * @property {number} rows_clean
 * @property {number} flagged
 * @property {number} reliability
 * @property {string|null} report_file
 */

/** @typedef {Object} ReportItem
 * @property {string} filename
 * @property {string} format
 * @property {number} size
 * @property {string} modified
 */

/** @typedef {Object} DatasetItem
 * @property {string} name
 * @property {number} size
 */

/** @typedef {Object} AnalysisJob
 * @property {string} job_id
 * @property {string} status
 * @property {number} progress
 * @property {string} stage
 * @property {Object|null} result
 * @property {string|null} error
 * @property {string} started_at
 * @property {string} deadline_at
 * @property {string|null} completed_at
 */

/**
 * PipelineIQ API error - thrown when a request fails.
 * Carries the HTTP status and the server-provided error message.
 */
class ApiError extends Error {
  /** @param {number} status */
  /** @param {string} message */
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Read the CSRF token from the page meta tag.
 * @returns {string}
 */
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : "";
}

/**
 * Parse a JSON response body safely.
 * @param {Response} response
 * @returns {Promise<unknown>}
 */
async function parseJson(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * Standardized fetch wrapper.
 * - Injects CSRF token for state-changing requests
 * - Parses JSON body
 * - Throws ApiError on non-ok responses with server message
 * - Enforces a request timeout
 * @param {string} path
 * @param {RequestInit} [init]
 * @param {number} [timeoutMs=30000]
 * @returns {Promise<unknown>}
 */
async function request(path, init = {}, timeoutMs = 30000) {
  const headers = {
    "Accept": "application/json",
    ...(init.headers || {}),
  };

  const method = (init.method || "GET").toUpperCase();
  const isBodyMethod = method === "POST" || method === "PUT" || method === "PATCH" || method === "DELETE";

  if (isBodyMethod && !headers["Content-Type"] && !(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  // Inject CSRF for state-changing requests
  if (isBodyMethod) {
    headers["X-CSRF-Token"] = getCsrfToken();
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(path, {
      ...init,
      headers,
      signal: controller.signal,
    });

    const body = await parseJson(response);

    if (!response.ok) {
      const message =
        (body && typeof body === "object" && body.error)
          ? String(body.error)
          : `Request failed with status ${response.status}`;
      throw new ApiError(response.status, message);
    }

    return body;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error.name === "AbortError") {
      throw new ApiError(408, "The request timed out. Please try again.");
    }
    throw new ApiError(0, error instanceof Error ? error.message : "An unexpected error occurred.");
  } finally {
    clearTimeout(timeoutId);
  }
}

/** GET helper */
const get = (path, timeoutMs) => request(path, { method: "GET" }, timeoutMs);

/** POST JSON helper */
const postJson = (path, body, timeoutMs) =>
  request(path, { method: "POST", body: JSON.stringify(body) }, timeoutMs);

/** POST form helper */
const postForm = (path, formData, timeoutMs) =>
  request(path, { method: "POST", body: formData }, timeoutMs);

// ---------------------------------------------------------------------------
// Endpoint clients aligned with the backend API contract
// ---------------------------------------------------------------------------

const Api = {
  // Auth
  /** @returns {Promise<{user: AuthUser, redirect: string}>} */
  signup: (name, email, password) =>
    postJson("/api/auth/signup", { name, email, password }),

  /** @returns {Promise<{user: AuthUser, redirect: string}>} */
  login: (email, password, remember = false) =>
    postJson("/api/auth/login", { email, password, remember }),

  /** @returns {Promise<{message: string}>} */
  logout: () => postJson("/api/auth/logout", {}),

  /** @returns {Promise<{user: AuthUser}|{authenticated: boolean}>} */
  me: () => get("/api/auth/me"),

  /** @returns {Promise<{authenticated: boolean}>} */
  check: () => get("/api/auth/check"),

  // Analysis
  /** Start analysis of an uploaded CSV. Async jobs return {job_id, status}. */
  analyzeFile: (file, { async = false } = {}) => {
    const form = new FormData();
    form.append("file", file);
    if (async) form.append("async", "true");
    return postForm("/api/analyze", form, async ? 120000 : 30000);
  },

  /** Start analysis of generated data. Async jobs return {job_id, status}. */
  analyzeSample: (rows, { async = false } = {}) => {
    const form = new FormData();
    form.append("rows", String(rows));
    if (async) form.append("async", "true");
    return postForm("/api/analyze", form, async ? 120000 : 30000);
  },

  /** @param {string} jobId @returns {Promise<AnalysisJob>} */
  getJob: (jobId) => get(`/api/analyze/jobs/${encodeURIComponent(jobId)}`),

  /** @returns {Promise<{jobs: AnalysisJob[]}>} */
  listJobs: () => get("/api/analyze/jobs"),

  // Schedule
  /** @returns {Promise<{schedule: ScheduleState}>} */
  getSchedule: () => get("/api/schedule"),

  /**
   * @param {object} params
   * @param {boolean} params.enabled
   * @param {number} params.interval_seconds
   * @param {number} params.rows
   * @param {'sample'|'csv'} params.source_type
   * @param {string} [params.dataset_name]
   * @returns {Promise<{schedule: ScheduleState}>}
   */
  setSchedule: (params) => postJson("/api/schedule", params),

  /** @returns {Promise<{datasets: DatasetItem[]}>} */
  listDatasets: () => get("/api/schedule/datasets"),

  /** @param {File} file @returns {Promise<{dataset: DatasetItem}>} */
  uploadDataset: (file) => {
    const form = new FormData();
    form.append("file", file);
    return postForm("/api/schedule/datasets", form);
  },

  // Status / health
  /** @returns {Promise<{ready: boolean, latest_analysis: AnalysisPayload|null, schedule: ScheduleState}>} */
  getStatus: () => get("/api/status"),

  /** @returns {Promise<{history: HistoryItem[]}>} */
  getHistory: () => get("/api/history"),

  /** @param {number} [limit] @returns {Promise<{logs: string[]}>} */
  getLogs: (limit = 150) => get(`/api/logs?limit=${limit}`),

  /** @returns {Promise<{recovery: Object, history: Array}>} */
  getMonitor: () => get("/api/monitor"),

  // Reports
  /** @returns {Promise<{reports: ReportItem[]}>} */
  getReports: () => get("/api/reports"),

  /** @param {string} filename @returns {Promise<Response>} (raw file stream) */
  downloadReport: async (filename) => {
    const response = await fetch(`/api/reports/${encodeURIComponent(filename)}`);
    if (!response.ok) {
      const body = await parseJson(response);
      throw new ApiError(response.status, (body && body.error) || "Report not found.");
    }
    return response;
  },

  // Airflow
  /** @returns {Promise<AirflowStatus>} */
  getAirflow: () => get("/api/airflow"),

  /** @returns {Promise<{requested: Array, events: Array}>} */
  retryAirflow: () => postJson("/api/airflow/retry", {}),

  // Recovery demo
  /** @returns {Promise<RecoveryResult>} */
  recoveryDemo: () => postJson("/api/recovery-demo", {}),

  // Health
  /** @returns {Promise<{status: string}>} */
  health: () => get("/healthz"),
};

export { Api, ApiError, getCsrfToken };
