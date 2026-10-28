/**
 * PipelineIQ Form Validation
 * Schema-based validation aligned with backend rules:
 * - Auth: email format, password strength (8+ char, upper, lower, digit)
 * - Schedule: interval 15s-7d, rows 1000-500k, whole numbers
 */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Validation result.
 * @typedef {Object} ValidationResult
 * @property {boolean} valid
 * @property {Object<string, string>} errors - field -> message
 */

/**
 * @typedef {Object} ValidationRule
 * @property {(value: unknown) => boolean} test
 * @property {string} message
 */

/**
 * Run a field through a list of rules, returning the first failure.
 * @param {unknown} value
 * @param {ValidationRule[]} rules
 * @returns {string|null}
 */
function checkField(value, rules) {
  for (const rule of rules) {
    if (!rule.test(value)) return rule.message;
  }
  return null;
}

/**
 * Required field rule.
 * @param {string} [message]
 * @returns {ValidationRule}
 */
function required(message = "This field is required.") {
  return {
    test: (value) => value !== null && value !== undefined && String(value).trim() !== "",
    message,
  };
}

/**
 * Email format rule.
 * @param {string} [message]
 * @returns {ValidationRule}
 */
function email(message = "Please enter a valid email address.") {
  return {
    test: (value) => EMAIL_RE.test(String(value)),
    message,
  };
}

/**
 * Min length rule.
 * @param {number} min
 * @param {string} [message]
 * @returns {ValidationRule}
 */
function minLength(min, message) {
  return {
    test: (value) => String(value).length >= min,
    message: message || `Must be at least ${min} characters.`,
  };
}

/**
 * Password strength rule aligned with backend validation.
 * @param {string} [message]
 * @returns {ValidationRule}
 */
function strongPassword(message) {
  return {
    test: (value) => {
      const s = String(value);
      return (
        s.length >= 8 &&
        /[a-z]/.test(s) &&
        /[A-Z]/.test(s) &&
        /[0-9]/.test(s)
      );
    },
    message: message || "Must be at least 8 characters with uppercase, lowercase, and a number.",
  };
}

/**
 * Whole number rule within a range.
 * @param {number} min
 * @param {number} max
 * @param {string} [message]
 * @returns {ValidationRule}
 */
function wholeNumberInRange(min, max, message) {
  return {
    test: (value) => {
      const n = Number(value);
      return Number.isInteger(n) && n >= min && n <= max;
    },
    message: message || `Must be a whole number between ${min} and ${max}.`,
  };
}

/**
 * Boolean rule.
 * @param {string} [message]
 * @returns {ValidationRule}
 */
function booleanRule(message = "Must be true or false.") {
  return {
    test: (value) => value === true || value === false || value === "true" || value === "false",
    message,
  };
}

/**
 * Auth login schema.
 * @param {object} data
 * @returns {ValidationResult}
 */
function validateLogin(data) {
  const errors = {};
  const emailErr = checkField(data.email, [required(), email()]);
  const passErr = checkField(data.password, [required()]);
  if (emailErr) errors.email = emailErr;
  if (passErr) errors.password = passErr;
  return { valid: Object.keys(errors).length === 0, errors };
}

/**
 * Auth signup schema aligned with backend rules.
 * @param {object} data
 * @returns {ValidationResult}
 */
function validateSignup(data) {
  const errors = {};
  const nameErr = checkField(data.name, [required(), minLength(2, "Name must be at least 2 characters.")]);
  const emailErr = checkField(data.email, [required(), email()]);
  const passErr = checkField(data.password, [required(), strongPassword()]);
  const confirmErr = data.password !== data.confirm
    ? "Passwords do not match."
    : null;
  const termsErr = data.terms === true
    ? null
    : "You must agree to the Terms of Service.";

  if (nameErr) errors.name = nameErr;
  if (emailErr) errors.email = emailErr;
  if (passErr) errors.password = passErr;
  if (confirmErr) errors.confirm = confirmErr;
  if (termsErr) errors.terms = termsErr;
  return { valid: Object.keys(errors).length === 0, errors };
}

/**
 * Schedule config schema aligned with backend rules.
 * @param {object} data
 * @returns {ValidationResult}
 */
function validateSchedule(data) {
  const errors = {};
  const intervalErr = checkField(data.interval_seconds, [
    required(),
    wholeNumberInRange(15, 604800, "Interval must be between 15 seconds and 7 days."),
  ]);
  const rowsErr = checkField(data.rows, [
    required(),
    wholeNumberInRange(1000, 500000, "Sample size must be between 1,000 and 500,000 rows."),
  ]);
  const sourceErr = checkField(data.source_type, [
    (v) => v === "sample" || v === "csv",
    "Choose either generated sample data or a saved CSV source.",
  ]);
  const enabledErr = checkField(data.enabled, [booleanRule()]);

  if (sourceErr) errors.source_type = sourceErr;
  if (intervalErr) errors.interval_seconds = intervalErr;
  if (rowsErr) errors.rows = rowsErr;
  if (enabledErr) errors.enabled = enabledErr;

  // CSV source requires a dataset name
  if (data.source_type === "csv" && (!data.dataset_name || String(data.dataset_name).trim() === "")) {
    errors.dataset_name = "Please select a saved CSV file.";
  }

  return { valid: Object.keys(errors).length === 0, errors };
}

export { validateLogin, validateSignup, validateSchedule, required, email, minLength, strongPassword, wholeNumberInRange, booleanRule, checkField };
