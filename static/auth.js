/**
 * Authentication JavaScript — PipelineIQ
 * Handles login, signup, password validation, and auth state management
 */

(() => {
  "use strict";

  const $ = (selector, context = document) => context.querySelector(selector);
  const $$ = (selector, context = document) => [...context.querySelectorAll(selector)];
  const motionReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Auth state
  let authState = {
    token: null,
    user: null,
    isAuthenticated: false
  };

  // API base URL
  const API_BASE = "/api/auth";

  // Initialize auth state from cookie or localStorage
  function initAuthState() {
    // Try to get token from cookie first
    const cookieToken = getCookie("auth_token");
    // Fallback to localStorage
    const storageToken = localStorage.getItem("auth_token");
    const token = cookieToken || storageToken;

    if (token) {
      authState.token = token;
      validateToken(token).then(user => {
        if (user) {
          authState.user = user;
          authState.isAuthenticated = true;
          updateUIForAuth();
        } else {
          clearAuth();
        }
      }).catch(() => clearAuth());
    }

    // Check if we're on login/signup page
    const isAuthPage = document.body.classList.contains("auth-page") ||
                       window.location.pathname.includes("/login") ||
                       window.location.pathname.includes("/signup");

    if (isAuthPage) {
      setupAuthForms();
    }

    // Protect routes if needed
    if (!isAuthPage && !authState.isAuthenticated) {
      // Redirect to login if on protected route
      const protectedRoutes = ["/", "/dashboard", "/overview", "/health", "/risk", "/quality", "/performance", "/monitor", "/reports", "/scheduler"];
      if (protectedRoutes.some(r => window.location.pathname.startsWith(r))) {
        window.location.href = "/login";
      }
    }
  }

  // Get cookie by name
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  // Set auth cookie
  function setAuthCookie(token, remember = false) {
    const maxAge = remember ? 30 * 24 * 60 * 60 : 24 * 60 * 60; // 30 days or 1 day
    document.cookie = `auth_token=${token}; path=/; max-age=${maxAge}; SameSite=Lax${window.location.protocol === "https:" ? "; Secure" : ""}`;
    localStorage.setItem("auth_token", token);
  }

  // Clear auth cookie
  function clearAuthCookie() {
    document.cookie = "auth_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
    localStorage.removeItem("auth_token");
  }

  // Validate token with backend
  async function validateToken(token) {
    try {
      const response = await fetch(`${API_BASE}/me`, {
        headers: { "Authorization": `Bearer ${token}` }
      });

      if (response.ok) {
        const data = await response.json();
        return data.user;
      }
    } catch (e) {
      console.warn("Token validation failed:", e);
    }
    return null;
  }

  // Clear auth state
  function clearAuth() {
    authState = { token: null, user: null, isAuthenticated: false };
    clearAuthCookie();
    updateUIForAuth();
  }

  // Update UI based on auth state
  function updateUIForAuth() {
    const authElements = $$("[data-auth-required], [data-auth-hidden]");
    authElements.forEach(el => {
      if (el.dataset.authRequired) {
        el.style.display = authState.isAuthenticated ? "" : "none";
      }
      if (el.dataset.authHidden) {
        el.style.display = authState.isAuthenticated ? "none" : "";
      }
    });

    // Update user info displays
    $$("[data-user-email]").forEach(el => el.textContent = authState.user?.email || "");
    $$("[data-user-name]").forEach(el => el.textContent = authState.user?.email?.split("@")[0] || "");
  }

  // Show alert message
  function showAlert(message, isError = true) {
    const alert = $("#auth-alert");
    const msg = $("#alert-message");
    if (alert && msg) {
      msg.textContent = message;
      alert.hidden = false;
      alert.style.borderColor = isError ? "rgba(255, 135, 152, 0.48)" : "rgba(124, 231, 178, 0.48)";
      alert.style.background = isError ? "rgba(73, 30, 43, 0.78)" : "rgba(30, 73, 43, 0.78)";
      const icon = alert.querySelector(".alert-icon");
      if (icon) {
        icon.style.color = isError ? "#ff8798" : "#7ce7b2";
        icon.style.background = isError ? "rgba(255, 135, 152, 0.14)" : "rgba(124, 231, 178, 0.14)";
      }

      // Auto-hide after 5 seconds for non-error messages
      if (!isError) {
        setTimeout(() => { alert.hidden = true; }, 5000);
      }
    }
  }

  // Hide alert
  function hideAlert() {
    const alert = $("#auth-alert");
    if (alert) alert.hidden = true;
  }

  // Set field error
  function setFieldError(fieldId, message) {
    const field = $(`#${fieldId}`);
    const error = $(`#${fieldId}-error`);
    if (field) {
      field.setAttribute("aria-invalid", message ? "true" : "false");
      field.classList.toggle("error", !!message);
    }
    if (error) {
      error.textContent = message || "";
    }
  }

  // Clear all field errors
  function clearFieldErrors(form) {
    $$(".form-error", form).forEach(el => el.textContent = "");
    $$("[aria-invalid]", form).forEach(el => el.removeAttribute("aria-invalid"));
  }

  // Password strength calculation
  function calculatePasswordStrength(password) {
    let score = 0;
    const checks = [
      password.length >= 8,
      password.length >= 12,
      /[a-z]/.test(password) && /[A-Z]/.test(password),
      /\d/.test(password),
      /[^a-zA-Z0-9]/.test(password)
    ];

    checks.forEach((check, i) => {
      if (check) score += (i < 2) ? 1 : (i === 2 ? 1 : (i === 3 ? 1 : 1));
    });

    // Normalize to 1-4
    if (score <= 1) return 1;
    if (score <= 2) return 2;
    if (score <= 3) return 3;
    return 4;
  }

  // Update password strength meter
  function updatePasswordStrength(password) {
    const strengthEl = $("#password-strength");
    const label = strengthEl?.querySelector(".strength-label");
    const labels = ["Very Weak", "Weak", "Good", "Strong"];

    if (strengthEl) {
      const strength = password ? calculatePasswordStrength(password) : 0;
      strengthEl.dataset.strength = strength;
      if (label) label.textContent = strength ? labels[strength - 1] : "";
    }
  }

  // Toggle password visibility
  function setupPasswordToggles() {
    $$(".password-toggle").forEach(btn => {
      btn.addEventListener("click", () => {
        const wrapper = btn.closest(".input-wrapper");
        const input = wrapper?.querySelector("input");
        const eyeIcon = btn.querySelector(".icon-eye");
        const eyeOffIcon = btn.querySelector(".icon-eye-off");

        if (input) {
          const isPassword = input.type === "password";
          input.type = isPassword ? "text" : "password";
          if (eyeIcon) eyeIcon.hidden = isPassword;
          if (eyeOffIcon) eyeOffIcon.hidden = !isPassword;
          btn.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
        }
      });
    });
  }

  // Handle form submission
  async function handleSubmit(form, endpoint, isSignup = false) {
    const submitBtn = form.querySelector('button[type="submit"]');
    const btnText = submitBtn?.querySelector(".btn-text");
    const btnLoader = submitBtn?.querySelector(".btn-loader");

    // Clear previous errors
    clearFieldErrors(form);
    hideAlert();

    // Collect form data
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());

    // Client-side validation
    let hasErrors = false;

    if (!data.email || !data.email.includes("@")) {
      setFieldError("email", "Please enter a valid email address");
      hasErrors = true;
    }

    if (!data.password) {
      setFieldError("password", "Password is required");
      hasErrors = true;
    } else if (data.password.length < 8) {
      setFieldError("password", "Password must be at least 8 characters");
      hasErrors = true;
    }

    if (isSignup) {
      if (data.password !== data.confirm_password) {
        setFieldError("confirm_password", "Passwords do not match");
        hasErrors = true;
      }

      const terms = form.querySelector("#terms");
      if (terms && !terms.checked) {
        setFieldError("terms", "You must accept the terms and conditions");
        hasErrors = true;
      }
    }

    if (hasErrors) {
      // Focus first error field
      const firstError = form.querySelector("[aria-invalid='true']");
      if (firstError) firstError.focus();
      return;
    }

    // Show loading state
    if (submitBtn) {
      submitBtn.disabled = true;
      if (btnText) btnText.hidden = true;
      if (btnLoader) btnLoader.hidden = false;
    }

    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });

      const result = await response.json();

      if (!response.ok) {
        // Handle specific field errors
        if (result.field_errors) {
          Object.entries(result.field_errors).forEach(([field, msg]) => {
            setFieldError(field, msg);
          });
        } else if (result.error) {
          showAlert(result.error);
        }
        throw new Error(result.error || "Request failed");
      }

      // Success!
      const { token, user } = result;
      const remember = form.querySelector("#remember")?.checked || false;

      authState.token = token;
      authState.user = user;
      authState.isAuthenticated = true;

      setAuthCookie(token, remember);

      showAlert(isSignup ? "Account created successfully!" : "Welcome back!", false);

      // Redirect after short delay
      setTimeout(() => {
        window.location.href = "/";
      }, 1000);

    } catch (error) {
      console.error("Auth error:", error);
      if (!error.message.includes("Request failed")) {
        showAlert("An unexpected error occurred. Please try again.");
      }
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        if (btnText) btnText.hidden = false;
        if (btnLoader) btnLoader.hidden = true;
      }
    }
  }

  // Setup auth forms
  function setupAuthForms() {
    document.body.classList.add("auth-page");

    // Password toggles
    setupPasswordToggles();

    // Password strength meter
    const passwordInput = $("#password");
    if (passwordInput) {
      passwordInput.addEventListener("input", (e) => {
        updatePasswordStrength(e.target.value);
      });
    }

    // Login form
    const loginForm = $("#login-form");
    if (loginForm) {
      loginForm.addEventListener("submit", (e) => {
        e.preventDefault();
        handleSubmit(loginForm, "/login");
      });
    }

    // Signup form
    const signupForm = $("#signup-form");
    if (signupForm) {
      signupForm.addEventListener("submit", (e) => {
        e.preventDefault();
        handleSubmit(signupForm, "/signup", true);
      });
    }

    // Add entrance animation
    if (!motionReduced) {
      const card = $(".auth-card");
      if (card) {
        card.style.opacity = "0";
        card.style.transform = "translateY(20px)";
        requestAnimationFrame(() => {
          card.style.transition = "opacity 0.5s var(--ease-out), transform 0.5s var(--ease-out)";
          card.style.opacity = "1";
          card.style.transform = "translateY(0)";
        });
      }
    }
  }

  // Public API for other scripts
  window.PipelineAuth = {
    getState: () => ({ ...authState }),
    getToken: () => authState.token,
    getUser: () => authState.user,
    isAuthenticated: () => authState.isAuthenticated,
    login: (email, password) => handleApiLogin(email, password),
    signup: (email, password, confirmPassword) => handleApiSignup(email, password, confirmPassword),
    logout: async () => {
      try {
        await fetch(`${API_BASE}/logout`, { method: "POST" });
      } catch (e) {
        console.warn("Logout request failed:", e);
      }
      clearAuth();
      window.location.href = "/login";
    },
    refreshToken: async () => {
      if (!authState.token) return null;
      try {
        const response = await fetch(`${API_BASE}/refresh`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${authState.token}` }
        });
        if (response.ok) {
          const { token } = await response.json();
          authState.token = token;
          setAuthCookie(token);
          return token;
        }
      } catch (e) {
        console.warn("Token refresh failed:", e);
      }
      return null;
    }
  };

  // Helper for programmatic login
  async function handleApiLogin(email, password) {
    const response = await fetch(`${API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    const result = await response.json();
    if (response.ok) {
      authState.token = result.token;
      authState.user = result.user;
      authState.isAuthenticated = true;
      setAuthCookie(result.token);
      updateUIForAuth();
      return result;
    }
    throw new Error(result.error || "Login failed");
  }

  // Helper for programmatic signup
  async function handleApiSignup(email, password, confirmPassword) {
    const response = await fetch(`${API_BASE}/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, confirm_password: confirmPassword })
    });
    const result = await response.json();
    if (response.ok) {
      authState.token = result.token;
      authState.user = result.user;
      authState.isAuthenticated = true;
      setAuthCookie(result.token);
      updateUIForAuth();
      return result;
    }
    throw new Error(result.error || "Signup failed");
  }

  // Initialize on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAuthState);
  } else {
    initAuthState();
  }

  // Also initialize when GSAP is ready (for auth pages)
  if (window.gsap) {
    window.gsap.ticker.add(() => {
      // GSAP ready
    });
  }
})();