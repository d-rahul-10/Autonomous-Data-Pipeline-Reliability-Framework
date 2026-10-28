/**
 * PipelineIQ Authentication Page
 * Refactored to use the shared API client (api.js) and validation schemas
 * (validation.js). Handles login/signup forms, tab switching, password
 * visibility toggles, real-time validation, and info dialogs.
 */

import { Api } from "./js/api.js";
import { validateLogin, validateSignup } from "./js/validation.js";

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------
const loginForm = document.getElementById("login-form");
const signupForm = document.getElementById("signup-form");
const errorMsg = document.getElementById("error-message");
const successMsg = document.getElementById("success-message");
const errorTitle = document.getElementById("error-title");
const errorText = document.getElementById("error-text");
const successTitle = document.getElementById("success-title");
const successText = document.getElementById("success-text");

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function toggleVisibility(el, hidden) {
  if (!el) return;
  if (hidden) { el.hidden = true; el.setAttribute("aria-hidden", "true"); }
  else { el.hidden = false; el.removeAttribute("aria-hidden"); }
}

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

function clearFieldError(inputId) {
  const input = document.getElementById(inputId);
  const errSpan = document.getElementById(`${inputId}-error`);
  if (input) { input.classList.remove("error"); input.removeAttribute("aria-invalid"); }
  if (errSpan) errSpan.textContent = "";
}

function showFieldError(inputId, message) {
  const input = document.getElementById(inputId);
  const errSpan = document.getElementById(`${inputId}-error`);
  if (input) { input.classList.add("error"); input.setAttribute("aria-invalid", "true"); }
  if (errSpan) errSpan.textContent = message;
}

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Real-time validation
// ---------------------------------------------------------------------------

function setupRealTimeValidation() {
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  ["login-email", "signup-email"].forEach((id) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener("blur", () => {
      const value = input.value.trim();
      if (value && !emailRe.test(value)) {
        input.classList.add("error");
        input.setAttribute("aria-invalid", "true");
        const err = document.getElementById(`${id}-error`);
        if (err) err.textContent = "Please enter a valid email address.";
      } else {
        clearFieldError(id);
      }
    });
    input.addEventListener("input", () => clearFieldError(id));
  });
}

// ---------------------------------------------------------------------------
// Password visibility toggles
// ---------------------------------------------------------------------------

function setupPasswordToggles() {
  document.querySelectorAll(".password-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.input);
      if (!input) return;
      const eyeOpen = btn.querySelector(".eye-open");
      const eyeClosed = btn.querySelector(".eye-closed");
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
}

// ---------------------------------------------------------------------------
// Form submission helpers
// ---------------------------------------------------------------------------

function setSubmitButton(btn, loading) {
  const text = btn.querySelector(".btn-text");
  const loader = btn.querySelector(".btn-loader");
  btn.disabled = loading;
  if (text) text.style.visibility = loading ? "hidden" : "visible";
  if (loader) toggleVisibility(loader, !loading);
}

function displayErrors(errors, prefix) {
  Object.entries(errors).forEach(([field, msg]) => {
    if (field === "terms") {
      const err = document.getElementById("terms-error");
      if (err) err.textContent = msg;
      return;
    }
    const input = document.getElementById(`${prefix}-${field}`);
    const err = document.getElementById(`${prefix}-${field}-error`);
    if (input) { input.classList.add("error"); input.setAttribute("aria-invalid", "true"); }
    if (err) err.textContent = msg;
  });
}

// ---------------------------------------------------------------------------
// Login handler
// ---------------------------------------------------------------------------

async function handleLogin(event) {
  event.preventDefault();
  hideAuthMessages();

  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  const remember = document.getElementById("remember-me").checked;

  const { valid, errors } = validateLogin({ email, password });
  if (!valid) {
    displayErrors(errors, "login");
    return;
  }

  const btn = document.getElementById("login-submit");
  setSubmitButton(btn, true);
  try {
    const response = await Api.login(email, password, remember);
    showAuthSuccess("Welcome back!", "Redirecting to your workspace…");
    setTimeout(() => { window.location.href = response.redirect || "/"; }, 1000);
  } catch (error) {
    showAuthError("Login failed", error instanceof Error ? error.message : "Login failed.");
  } finally {
    setSubmitButton(btn, false);
  }
}

// ---------------------------------------------------------------------------
// Signup handler
// ---------------------------------------------------------------------------

async function handleSignup(event) {
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
    displayErrors(errors, "signup");
    return;
  }

  const btn = document.getElementById("signup-submit");
  setSubmitButton(btn, true);
  try {
    const response = await Api.signup(formData.name, formData.email, formData.password);
    showAuthSuccess("Account created!", "Redirecting to your workspace…");
    setTimeout(() => { window.location.href = response.redirect || "/"; }, 1000);
  } catch (error) {
    showAuthError("Registration failed", error instanceof Error ? error.message : "Registration failed.");
  } finally {
    setSubmitButton(btn, false);
  }
}

// ---------------------------------------------------------------------------
// Provider sign-in
// ---------------------------------------------------------------------------

function setupSocialButtons() {
  document.querySelectorAll(".btn-social").forEach((btn) => {
    btn.addEventListener("click", () => {
      const provider = btn.dataset.provider;
      if (provider === "google" || provider === "github") {
        window.location.assign(`/api/auth/oauth/${provider}/start`);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Info dialog (privacy/terms/support)
// ---------------------------------------------------------------------------

function setupInfoDialog() {
  const dialog = document.getElementById("auth-info-dialog");
  if (!dialog) return;
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

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

function init() {
  // Tab switching
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      switchTab(tab.dataset.tab);
      hideAuthMessages();
    });
  });

  // Close buttons
  document.querySelectorAll("[data-close-message]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const type = btn.dataset.closeMessage;
      const el = document.getElementById(`${type}-message`);
      if (el) toggleVisibility(el, true);
    });
  });

  // Form submissions
  if (loginForm) loginForm.addEventListener("submit", handleLogin);
  if (signupForm) signupForm.addEventListener("submit", handleSignup);

  // UI enhancements
  setupPasswordToggles();
  setupSocialButtons();
  setupRealTimeValidation();
  setupInfoDialog();

  const oauthError = new URLSearchParams(window.location.search).get("oauth_error");
  const oauthMessages = {
    provider_not_configured: "Google and GitHub sign-in need provider credentials before they can be used.",
    verification_failed: "Sign-in verification failed. Please try again.",
    sign_in_failed: "The provider could not complete sign-in. Please try again.",
    account_unavailable: "This account is not available."
  };
  if (oauthError && oauthMessages[oauthError]) {
    showAuthError("Sign-in unavailable", oauthMessages[oauthError]);
  }

  // Hash-based tab switching
  const hash = window.location.hash.slice(1);
  if (hash === "signup") switchTab("signup");
  window.addEventListener("hashchange", () => {
    const newHash = window.location.hash.slice(1);
    if (newHash === "signup" || newHash === "login") switchTab(newHash);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
