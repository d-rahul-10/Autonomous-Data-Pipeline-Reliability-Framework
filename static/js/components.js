/**
 * PipelineIQ UI Components
 * Reusable, accessible UI primitives: buttons, inputs, notifications, loaders,
 * skeletons, tables, and modals. All components accept a container element and
 * render HTML into it, keeping rendering logic separate from business logic.
 */

const html = (strings, ...values) => strings.reduce((acc, part, i) => acc + part + (values[i] ?? ""), "");

/** Escape HTML to prevent XSS. */
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[ch]);

/** Format a number with thousands separators. */
const number = (value) => Number(value || 0).toLocaleString();

/** Format a percentage. */
const percent = (value, digits = 1) => `${(Number(value || 0) * 100).toFixed(digits)}%`;

/** Format a timestamp to locale string. */
const formatTime = (value) => {
  try { return new Date(value).toLocaleString(); } catch { return String(value); }
};

/** Set or remove a hidden attribute and toggle aria-hidden. */
const toggleVisibility = (el, hidden) => {
  if (hidden) { el.hidden = true; el.setAttribute("aria-hidden", "true"); }
  else { el.hidden = false; el.removeAttribute("aria-hidden"); }
};

/**
 * Render a primary action button with optional loading state.
 * @param {object} opts
 * @param {string} opts.label
 * @param {() => void | Promise<void>} [opts.onClick]
 * @param {boolean} [opts.disabled]
 * @param {boolean} [opts.loading]
 * @param {string} [opts.id]
 * @returns {HTMLButtonElement}
 */
function Button({ label, onClick, disabled = false, loading = false, id }) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "button button-primary";
  btn.id = id;
  btn.disabled = disabled || loading;
  btn.setAttribute("aria-busy", String(loading));
  btn.innerHTML = loading
    ? `<span class="loader" aria-hidden="true"></span> ${escape(label)}…`
    : `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"/></svg> ${escape(label)}`;
  if (onClick) btn.addEventListener("click", onClick);
  return btn;
}

/**
 * Render a secondary button.
 * @param {object} opts
 * @param {string} opts.label
 * @param {() => void | Promise<void>} [opts.onClick]
 * @param {boolean} [opts.disabled]
 * @param {string} [opts.id]
 * @returns {HTMLButtonElement}
 */
function SecondaryButton({ label, onClick, disabled = false, id }) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "button button-secondary";
  btn.id = id;
  btn.disabled = disabled;
  btn.textContent = escape(label);
  if (onClick) btn.addEventListener("click", onClick);
  return btn;
}

/**
 * Render a text link button.
 * @param {object} opts
 * @param {string} opts.label
 * @param {() => void} [opts.onClick]
 * @param {boolean} [opts.hidden]
 * @returns {HTMLButtonElement}
 */
function TextButton({ label, onClick, hidden = false, id }) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "text-button";
  btn.id = id;
  btn.hidden = hidden;
  btn.textContent = escape(label);
  if (onClick) btn.addEventListener("click", onClick);
  return btn;
}

/**
 * Render a notification/alert banner.
 * @param {object} opts
 * @param {string} opts.title
 * @param {string} opts.message
 * @param {string} [opts.type="error"] - 'error' | 'success' | 'info'
 * @param {() => void} [opts.onDismiss]
 * @returns {HTMLElement}
 */
function Notice({ title, message, type = "error", onDismiss }) {
  const el = document.createElement("div");
  el.className = `notice notice-${type} entering`;
  el.setAttribute("role", "alert");
  el.setAttribute("aria-live", "polite");
  el.innerHTML = `
    <span class="notice-icon" aria-hidden="true">${type === "success" ? "✓" : type === "info" ? "i" : "!"}</span>
    <div>
      <strong>${escape(title)}</strong>
      <p>${escape(message)}</p>
    </div>
    ${onDismiss ? `<button class="notice-close" type="button" aria-label="Dismiss message">×</button>` : ""}
  `;
  const closeBtn = el.querySelector(".notice-close");
  if (closeBtn && onDismiss) closeBtn.addEventListener("click", onDismiss);
  return el;
}

/**
 * Render a loading spinner overlay.
 * @param {object} opts
 * @param {string} [opts.label="Loading…"]
 * @returns {HTMLElement}
 */
function Loader({ label = "Loading…" } = {}) {
  const el = document.createElement("div");
  el.className = "loading-panel fade-in";
  el.setAttribute("aria-live", "polite");
  el.innerHTML = `
    <span class="loader" aria-hidden="true"></span>
    <div><strong>${escape(label)}</strong><span>Please wait.</span></div>
  `;
  return el;
}

/**
 * Render a skeleton placeholder while content loads.
 * @param {number} [count=3]
 * @returns {HTMLElement}
 */
function Skeleton({ count = 3 } = {}) {
  const el = document.createElement("div");
  el.className = "skeleton-list";
  el.innerHTML = Array.from({ length: count }, () => `
    <article class="skeleton-card">
      <div class="skeleton-line skeleton-title"></div>
      <div class="skeleton-line skeleton-text"></div>
      <div class="skeleton-line skeleton-text short"></div>
    </article>
  `).join("");
  return el;
}

/**
 * Render an empty state.
 * @param {object} opts
 * @param {string} opts.title
 * @param {string} opts.message
 * @param {string} [opts.icon]
 * @param {HTMLButtonElement} [opts.action]
 * @returns {HTMLElement}
 */
function EmptyState({ title, message, icon = "doc", action }) {
  const el = document.createElement("div");
  el.className = "empty-state";
  el.innerHTML = `
    <div class="empty-visual" aria-hidden="true"><svg viewBox="0 0 24 24">${iconSvg(icon)}</svg></div>
    <h2>${escape(title)}</h2>
    <p>${escape(message)}</p>
  `;
  if (action) el.appendChild(action);
  return el;
}

/** Return an SVG snippet by name. */
function iconSvg(name) {
  const icons = {
    doc: `<path d="M5 4.5h14v15H5zM8 9l2.2 2.2L15.5 6m-7.5 9h8"/>`,
    chart: `<path d="M4 19.5h16M6.5 16V9.5m5 6.5V5m5 11V11m-12 8.5h13"/>`,
    risk: `<path d="M12 3.5 21 20H3L12 3.5Z"/><path d="M12 9v4.5m0 3h.01"/>`,
    schedule: `<rect x="4" y="5.5" width="16" height="15" rx="1"/><path d="M8 3.5v4m8-4v4M4 10h16m-8 3v3l2 1"/>`,
    report: `<path d="M6 3.5h8l4.5 4.5v12H6zM14 4v5h5m-9 4h5m-5 3h5"/>`,
  };
  return icons[name] || icons.doc;
}

/**
 * Render a metric card.
 * @param {object} opts
 * @param {string} opts.label
 * @param {string} opts.value
 * @param {string} [opts.caption]
 * @returns {HTMLElement}
 */
function MetricCard({ label, value, caption }) {
  const el = document.createElement("article");
  el.className = "metric-card";
  el.innerHTML = `
    <div class="metric-top">${escape(label)}</div>
    <div class="metric-value">${escape(value)}</div>
    ${caption ? `<div class="subtle-caption">${escape(caption)}</div>` : ""}
  `;
  return el;
}

/**
 * Render a table with header rows and body rows.
 * @param {object} opts
 * @param {string[]} opts.headers
 * @param {string[][]} opts.rows - each inner array is cell HTML
 * @param {string} [opts.emptyMessage]
 * @returns {HTMLElement}
 */
function DataTable({ headers, rows, emptyMessage = "No data available." }) {
  const el = document.createElement("div");
  el.className = "table-scroll";
  el.innerHTML = `
    <table>
      <thead><tr>${headers.map((h) => `<th>${escape(h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.length
        ? rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")
        : `<tr><td colspan="${headers.length}" class="empty-row">${escape(emptyMessage)}</td></tr>`}
      </tbody>
    </table>
  `;
  return el;
}

/**
 * Render a health pill badge.
 * @param {'good'|'watch'|'critical'} level
 * @returns {string}
 */
function healthPill(level) {
  const labels = { good: "Healthy", watch: "Monitor", critical: "At risk" };
  return `<span class="health-pill ${level}">${escape(labels[level])}</span>`;
}

/**
 * Create a file picker label + input.
 * @param {object} opts
 * @param {string} opts.accept
 * @param {string} opts.label
 * @param {Function} [opts.onChange]
 * @returns {HTMLElement}
 */
function FilePicker({ accept = ".csv,text/csv", label = "Choose CSV", onChange }) {
  const wrapper = document.createElement("label");
  wrapper.className = "file-picker";
  wrapper.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 3.5H6A1.5 1.5 0 0 0 4.5 5v14A1.5 1.5 0 0 0 6 20.5h12a1.5 1.5 0 0 0 1.5-1.5V9l-6-5.5Z"/><path d="M13 4v5h5m-8 5h5m-5 3h5"/></svg>
    <span class="file-label">${escape(label)}</span>
  `;
  const input = document.createElement("input");
  input.type = "file";
  input.accept = accept;
  input.className = "file-input";
  input.style.display = "none";
  if (onChange) input.addEventListener("change", onChange);
  wrapper.appendChild(input);
  wrapper.querySelector(".file-label").textContent = label;
  return { element: wrapper, input, setLabel: (text) => { wrapper.querySelector(".file-label").textContent = text; } };
}

/**
 * Render a select dropdown.
 * @param {object} opts
 * @param {string} opts.id
 * @param {Array<{value: string, label: string}>} opts.options
 * @param {string} [opts.value]
 * @param {string} [opts.labelText]
 * @param {Function} [opts.onChange]
 * @returns {HTMLElement}
 */
function SelectField({ id, options, value, labelText, onChange }) {
  const container = document.createElement("div");
  container.className = "form-group";
  if (labelText) {
    const label = document.createElement("label");
    label.htmlFor = id;
    label.className = "form-label";
    label.textContent = escape(labelText);
    container.appendChild(label);
  }
  const select = document.createElement("select");
  select.id = id;
  select.className = "form-input";
  select.innerHTML = options.map((opt) =>
    `<option value="${escape(opt.value)}" ${opt.value === value ? "selected" : ""}>${escape(opt.label)}</option>`
  ).join("");
  if (onChange) select.addEventListener("change", onChange);
  container.appendChild(select);
  return container;
}

/**
 * Render a checkbox toggle.
 * @param {object} opts
 * @param {string} opts.id
 * @param {string} opts.label
 * @param {boolean} [opts.checked]
 * @param {Function} [opts.onChange]
 * @returns {HTMLElement}
 */
function CheckboxField({ id, label, checked = false, onChange }) {
  const container = document.createElement("label");
  container.className = "schedule-switch";
  container.innerHTML = `
    <input type="checkbox" id="${escape(id)}" ${checked ? "checked" : ""}>
    <span>${escape(label)}</span>
  `;
  const input = container.querySelector("input");
  if (onChange) input.addEventListener("change", onChange);
  return container;
}

/**
 * Render a form group with label, input, and error message.
 * @param {object} opts
 * @param {string} opts.id
 * @param {string} opts.label
 * @param {string} [opts.type="text"]
 * @param {string} [opts.value]
 * @param {string} [opts.placeholder]
 * @param {boolean} [opts.required]
 * @param {Function} [opts.onInput]
 * @returns {{element: HTMLElement, input: HTMLInputElement, errorEl: HTMLElement, setError: (msg: string) => void, clearError: () => void}}
 */
function InputField({ id, label, type = "text", value = "", placeholder = "", required = false, onInput }) {
  const container = document.createElement("div");
  container.className = "form-group";
  const labelEl = document.createElement("label");
  labelEl.htmlFor = id;
  labelEl.className = "form-label";
  labelEl.textContent = escape(label);
  container.appendChild(labelEl);

  const wrapper = document.createElement("div");
  wrapper.className = "input-wrapper";
  const input = document.createElement("input");
  input.type = type;
  input.id = id;
  input.className = "form-input";
  input.value = value;
  input.placeholder = escape(placeholder);
  if (required) input.required = true;
  if (onInput) input.addEventListener("input", onInput);
  wrapper.appendChild(input);
  container.appendChild(wrapper);

  const errorEl = document.createElement("span");
  errorEl.className = "form-error";
  errorEl.setAttribute("role", "alert");
  container.appendChild(errorEl);

  return {
    element: container,
    input,
    errorEl,
    setError: (msg) => { input.classList.add("error"); input.setAttribute("aria-invalid", "true"); errorEl.textContent = escape(msg); },
    clearError: () => { input.classList.remove("error"); input.removeAttribute("aria-invalid"); errorEl.textContent = ""; },
  };
}

export { Button, SecondaryButton, TextButton, Notice, Loader, Skeleton, EmptyState, MetricCard, DataTable, healthPill, FilePicker, SelectField, CheckboxField, InputField, escape, number, percent, formatTime, toggleVisibility };
