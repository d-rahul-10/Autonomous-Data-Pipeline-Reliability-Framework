/**
 * PipelineIQ State Store
 * Lightweight observable state management. Views subscribe to state slices
 * and re-render when data changes. Keeps UI state (loading, errors, auth)
 * separate from server-derived data.
 */

const subscribers = new Map();

/**
 * Subscribe to state changes.
 * @param {string} key
 * @param {(value: unknown) => void} callback
 * @returns {() => void} unsubscribe function
 */
function subscribe(key, callback) {
  if (!subscribers.has(key)) subscribers.set(key, new Set());
  subscribers.get(key).add(callback);
  return () => {
    const set = subscribers.get(key);
    if (set) set.delete(callback);
  };
}

/**
 * Notify all subscribers of a state key.
 * @param {string} key
 * @param {unknown} value
 */
function notify(key, value) {
  const set = subscribers.get(key);
  if (set) {
    set.forEach((cb) => {
      try { cb(value); } catch (err) {
        console.error(`PipelineIQ store subscriber error for "${key}":`, err);
      }
    });
  }
}

/**
 * Application state. All server-derived and UI state lives here.
 * @typedef {Object} AppState
 * @property {Object|null} analysis - latest analysis payload
 * @property {Object|null} schedule - schedule state
 * @property {Object|null} user - authenticated user
 * @property {boolean} authenticated
 * @property {boolean} loading
 * @property {string|null} error
 * @property {Array} history
 * @property {Array} reports
 * @property {Array} datasets
 * @property {Object|null} monitor
 * @property {Object|null} airflow
 * @property {Map<string, Object>} jobs - async job registry by jobId
 * @property {string} activeTab
 */

/** @type {AppState} */
const state = {
  analysis: null,
  schedule: null,
  user: null,
  authenticated: false,
  loading: false,
  error: null,
  history: [],
  reports: [],
  datasets: [],
  monitor: null,
  airflow: null,
  jobs: new Map(),
  activeTab: "overview",
};

/**
 * Set a state key and notify subscribers.
 * @param {keyof AppState} key
 * @param {AppState[keyof AppState]} value
 */
function set(key, value) {
  state[key] = value;
  notify(key, value);
  notify("*", state);
}

/**
 * Get a state key or the whole state.
 * @param {keyof AppState | "*"} [key]
 * @returns {AppState[keyof AppState] | AppState}
 */
function get(key) {
  return key === undefined ? state : state[key];
}

/**
 * Merge partial state into analysis.
 * @param {Partial<AppState['analysis']>} patch
 */
function patchAnalysis(patch) {
  state.analysis = { ...state.analysis, ...patch };
  notify("analysis", state.analysis);
  notify("*", state);
}

/**
 * Add or update a job in the registry.
 * @param {string} jobId
 * @param {Object} job
 */
function upsertJob(jobId, job) {
  state.jobs.set(jobId, job);
  notify("jobs", new Map(state.jobs));
  notify("*", state);
}

/**
 * Remove a job from the registry.
 * @param {string} jobId
 */
function removeJob(jobId) {
  state.jobs.delete(jobId);
  notify("jobs", new Map(state.jobs));
  notify("*", state);
}

export { state, get, set, subscribe, notify, patchAnalysis, upsertJob, removeJob };
