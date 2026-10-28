# PipelineIQ Authentication System - Complete Design & Development Specification

## Executive Summary

This is a design proposal, not a description of every implemented feature. The current implementation supports email/password signup, login, logout, server-side session validation, and CSRF checks. Password reset email and social OAuth are not configured; the Google/GitHub controls are informational placeholders. For verified behavior and deployment limits, see [AUTH_README.md](AUTH_README.md) and [DEPLOYMENT.md](DEPLOYMENT.md).

---

## Table of Contents

1. [User Goals & Experience](#user-goals--experience)
2. [Page Structure & Content](#page-structure--content)
3. [Visual & UI Design System](#visual--ui-design-system)
4. [Technical Implementation](#technical-implementation)
5. [API Specification](#api-specification)
6. [Security Considerations](#security-considerations)
7. [Responsive Design](#responsive-design)
8. [Accessibility](#accessibility)
9. [Testing Strategy](#testing-strategy)
10. [Deployment Guide](#deployment-guide)

---

## 1. User Goals & Experience

### Primary User Goals

1. **Seamless Authentication Flow**: Users should experience minimal friction when signing up or logging in
2. **Clear Visual Feedback**: All actions should provide immediate, understandable feedback
3. **Error Prevention**: Client-side validation prevents common mistakes before submission
4. **Quick Login**: Returning users can sign in with minimal steps
5. **Account Creation Guidance**: New users are guided through password requirements and validation

### User Journey Maps

#### New User Signup Journey
```
1. Land on auth page (default: login tab)
2. Click "Create Account" tab
3. Fill in full name → Real-time validation on blur
4. Enter email → Format validation on blur
5. Create password → See strength indicator update in real-time
6. Confirm password → Match validation on blur
7. Check terms agreement
8. Submit → Loading state → Success message → Redirect to dashboard
```

#### Returning User Login Journey
```
1. Land on auth page (login tab active)
2. Enter email/username
3. Enter password
4. Optionally check "Remember me"
5. Submit → Loading state → Success message → Redirect to dashboard
```

---

## 2. Page Structure & Content

### 2.1 Overall Layout

```
┌─────────────────────────────────────┐
│         Background Pattern          │
│                                     │
│         [PipelineIQ Logo]          │
│                                     │
│  ┌─────────────────────────────┐  │
│  │    [Login] [Sign Up]        │  │
│  ├─────────────────────────────┤  │
│  │                             │  │
│  │      Form Content           │  │
│  │                             │  │
│  │  [Social Login Buttons]     │  │
│  └─────────────────────────────┘  │
│                                     │
│      [Footer Links]                │
└─────────────────────────────────────┘
```

### 2.2 Component Breakdown

#### Branding Section
- **Logo**: SVG pipeline visualization icon (40px)
- **Brand Name**: "PipelineIQ" with accent color on "IQ"
- **Positioning**: Centered, above auth card

#### Tab Navigation
- **Two Tabs**: "Sign In" and "Create Account"
- **Active Indicator**: Animated sliding background
- **Keyboard Navigation**: Full tab/arrow key support
- **ARIA Roles**: Proper tablist/tab/tabpanel structure

#### Login Panel Content

```html
Header:
  - Title: "Welcome back"
  - Subtitle: "Sign in to your PipelineIQ workspace"

Form Fields:
  1. Email/Username
     - Icon: Mail envelope
     - Placeholder: "you@example.com"
     - Validation: Email format check
  
  2. Password
     - Icon: Lock
     - Placeholder: "Enter your password"
     - Toggle: Show/hide password button
  
  3. Remember Me Checkbox
  
  4. Forgot Password Link (right-aligned)
  
  5. Sign In Button (primary, full-width)

Social Login:
  - Divider: "Or continue with"
  - Buttons: Google, GitHub (side-by-side)
```

#### Signup Panel Content

```html
Header:
  - Title: "Create your account"
  - Subtitle: "Get started with PipelineIQ today"

Form Fields:
  1. Full Name
     - Icon: User
     - Placeholder: "John Doe"
     - Validation: Min 2 characters, non-empty
  
  2. Email Address
     - Icon: Mail envelope
     - Placeholder: "you@example.com"
     - Validation: Email format, uniqueness (server-side)
  
  3. Password
     - Icon: Lock
     - Placeholder: "Create a strong password"
     - Toggle: Show/hide password button
     - Strength Indicator: Real-time visual bar (weak/medium/strong)
     - Requirements: Below field in small text
  
  4. Confirm Password
     - Icon: Checkmark
     - Placeholder: "Confirm your password"
     - Validation: Match with password field
  
  5. Terms Agreement Checkbox
     - Text: "I agree to the Terms of Service and Privacy Policy"
     - Links: Clickable terms/privacy
  
  6. Create Account Button (primary, full-width)

Social Signup:
  - Divider: "Or sign up with"
  - Buttons: Google, GitHub (side-by-side)
```

### 2.3 Message Components

#### Success Message
```
[✓] Success!
    Your account has been created. Redirecting...
    [×] Close
```

#### Error Message
```
[!] Error
    Invalid email or password. Please try again.
    [×] Close
```

---

## 3. Visual & UI Design System

### 3.1 Color Palette

```css
/* Brand Colors */
--brand-primary: #3b82f6       /* Blue 500 - Primary actions */
--brand-primary-hover: #2563eb  /* Blue 600 - Hover state */
--brand-primary-active: #1d4ed8 /* Blue 700 - Active state */
--brand-accent: #06b6d4         /* Cyan 500 - Accent highlights */

/* Neutral Grays */
--gray-50: #f9fafb    /* Backgrounds */
--gray-100: #f3f4f6   /* Subtle backgrounds */
--gray-200: #e5e7eb   /* Borders */
--gray-400: #9ca3af   /* Placeholders */
--gray-600: #4b5563   /* Secondary text */
--gray-700: #374151   /* Labels */
--gray-900: #111827   /* Primary text */

/* Semantic Colors */
--success: #10b981    /* Green 500 */
--error: #ef4444      /* Red 500 */
--warning: #f59e0b    /* Amber 500 */
```

### 3.2 Typography

```css
/* Font Stack */
--font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 
               Roboto, 'Helvetica Neue', Arial, sans-serif;

/* Type Scale */
- Page Title (h1): 1.875rem (30px), weight 700, tracking -0.025em
- Section Title (h2): 1.5rem (24px), weight 700
- Body: 1rem (16px), weight 400, line-height 1.5
- Small: 0.875rem (14px)
- Tiny: 0.8125rem (13px)

/* Font Weights */
- Regular: 400
- Medium: 500
- Semibold: 600
- Bold: 700
```

### 3.3 Spacing System

```css
--space-1: 0.25rem   /* 4px */
--space-2: 0.5rem    /* 8px */
--space-3: 0.75rem   /* 12px */
--space-4: 1rem      /* 16px */
--space-5: 1.25rem   /* 20px */
--space-6: 1.5rem    /* 24px */
--space-8: 2rem      /* 32px */
--space-12: 3rem     /* 48px */
```

### 3.4 Border Radius

```css
--radius-sm: 0.375rem   /* 6px - Small elements */
--radius-md: 0.5rem     /* 8px - Inputs, buttons */
--radius-lg: 0.75rem    /* 12px - Cards */
--radius-xl: 1rem       /* 16px - Large cards */
--radius-full: 9999px   /* Fully rounded */
```

### 3.5 Shadows

```css
--shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05)
--shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1)
--shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1)
--shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1)
```

### 3.6 Form Element Styling

#### Input Fields

**Default State**
```css
- Background: --gray-50
- Border: 2px solid --gray-200
- Padding: 12px 16px 12px 48px (with icon)
- Border radius: --radius-md
- Font size: 1rem
- Transition: all 150ms
```

**Focus State**
```css
- Background: white
- Border: 2px solid --brand-primary
- Box shadow: 0 0 0 3px rgba(59, 130, 246, 0.1)
- Icon color: --brand-primary
```

**Error State**
```css
- Background: --error-bg (#fee2e2)
- Border: 2px solid --error
- Box shadow (focus): 0 0 0 3px rgba(239, 68, 68, 0.1)
```

#### Buttons

**Primary Button**
```css
Default:
- Background: --brand-primary
- Color: white
- Padding: 12px 24px
- Border radius: --radius-md
- Font weight: 600
- Box shadow: none
- Transition: all 150ms

Hover:
- Background: --brand-primary-hover
- Box shadow: 0 4px 12px rgba(59, 130, 246, 0.4)
- Transform: translateY(-1px)

Active:
- Transform: translateY(0)
- Box shadow: 0 2px 6px rgba(59, 130, 246, 0.3)

Disabled:
- Opacity: 0.6
- Cursor: not-allowed
```

**Social Login Buttons**
```css
- Background: white
- Border: 2px solid --gray-200
- Padding: 12px 16px
- Border radius: --radius-md
- Display: flex with icon + text
- Gap: 8px

Hover:
- Border: 2px solid --gray-300
- Background: --gray-50
- Transform: translateY(-1px)
- Box shadow: --shadow-sm
```

### 3.7 Animations

```css
/* Timing Functions */
--transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1)
--transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1)
--transition-slow: 300ms cubic-bezier(0.4, 0, 0.2, 1)

/* Keyframe Animations */
@keyframes slideUp {
  from: opacity 0, translateY(20px)
  to: opacity 1, translateY(0)
}

@keyframes fadeIn {
  from: opacity 0
  to: opacity 1
}

@keyframes spin {
  from: rotate(0deg)
  to: rotate(360deg)
}
```

---

## 4. Technical Implementation

### 4.1 Technology Stack

**Frontend**
- Pure HTML5 with semantic markup
- CSS3 with CSS Variables (custom properties)
- Vanilla JavaScript (ES6+)
- No frameworks required for simplicity

**Backend**
- Flask (Python web framework)
- SQLite3 (user database)
- Werkzeug (password hashing)
- Flask sessions (authentication)

### 4.2 File Structure

```
project/
├── templates/
│   ├── index.html          # Main dashboard
│   └── auth.html           # Authentication page (NEW)
├── static/
│   ├── auth.css            # Auth page styles (NEW)
│   ├── auth.js             # Auth page logic (NEW)
│   ├── style.css           # Main app styles
│   └── app.js              # Main app logic
├── app.py                  # Main Flask application
├── auth_routes.py          # Authentication routes (NEW)
└── pipeline_state.sqlite3  # Database
```

### 4.3 Component Architecture

#### JavaScript Modules

```javascript
// State Management
AuthState = {
  activeTab: 'login',
  isSubmitting: false,
  passwordStrength: 'none'
}

// Utility Functions
utils = {
  isValidEmail(email),
  getPasswordStrength(password),
  isValidPassword(password),
  debounce(func, wait)
}

// UI Management
UI = {
  showError(title, message),
  showSuccess(title, message),
  hideMessages(),
  showFieldError(fieldId, message),
  clearFieldError(fieldId),
  setButtonLoading(buttonId, isLoading)
}

// Form Validation
Validation = {
  validateLogin(formData),
  validateSignup(formData),
  displayErrors(errors, formPrefix)
}

// API Communication
API = {
  login(email, password, remember),
  signup(name, email, password),
  socialAuth(provider, action)
}

// Form Handlers
FormHandlers = {
  handleLogin(event),
  handleSignup(event)
}
```

### 4.4 Client-Side Validation Rules

#### Email Validation
```javascript
Pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/
Trigger: On blur
Error: "Please enter a valid email address"
```

#### Password Validation (Signup)
```javascript
Rules:
- Minimum 8 characters
- At least one lowercase letter
- At least one uppercase letter
- At least one number

Strength Calculation:
score = 0
if (length >= 8) score++
if (length >= 12) score++
if (has lowercase) score++
if (has uppercase) score++
if (has number) score++
if (has special char) score++

Rating:
- 0-2: Weak (red)
- 3-4: Medium (yellow)
- 5-6: Strong (green)
```

#### Confirm Password Validation
```javascript
Rule: Must match password field exactly
Trigger: On blur
Error: "Passwords do not match"
```

#### Name Validation
```javascript
Rule: Minimum 2 characters, non-empty
Trigger: On blur
Error: "Name must be at least 2 characters"
```

### 4.5 State Management Flow

```
User Action → Validation → UI Update → API Call → Response Handler → UI Update → Redirect

Example: Signup Flow
1. User fills form
2. Client validates all fields
3. If valid: Show loading state
4. POST to /api/auth/signup
5. If success: Show success message, redirect after 1.5s
6. If error: Show error message, clear loading state
```

---

## 5. API Specification

### 5.1 Authentication Endpoints

#### POST /api/auth/signup

**Description**: Register a new user account

**Request Headers**:
```
Content-Type: application/json
```

**Request Body**:
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "SecurePass123"
}
```

**Success Response (200)**:
```json
{
  "message": "Account created successfully",
  "redirect": "/",
  "user": {
    "id": 1,
    "name": "John Doe",
    "email": "john@example.com"
  }
}
```

**Error Responses**:
```json
// 400 - Validation Error
{
  "error": "Name must be at least 2 characters"
}

// 400 - Duplicate Email
{
  "error": "An account with this email already exists"
}

// 400 - Weak Password
{
  "error": "Password must contain at least one uppercase letter"
}
```

---

#### POST /api/auth/login

**Description**: Authenticate existing user

**Request Headers**:
```
Content-Type: application/json
```

**Request Body**:
```json
{
  "email": "john@example.com",
  "password": "SecurePass123",
  "remember": false
}
```

**Success Response (200)**:
```json
{
  "message": "Login successful",
  "redirect": "/",
  "user": {
    "id": 1,
    "name": "John Doe",
    "email": "john@example.com"
  }
}
```

**Error Responses**:
```json
// 401 - Invalid Credentials
{
  "error": "Invalid email or password"
}

// 401 - Account Disabled
{
  "error": "Account is disabled. Contact support."
}

// 400 - Missing Fields
{
  "error": "Email and password are required"
}
```

---

#### POST /api/auth/logout

**Description**: Log out current user

**Request Headers**:
```
Authorization: Session token (from cookie)
```

**Success Response (200)**:
```json
{
  "message": "Logged out successfully"
}
```

---

#### GET /api/auth/me

**Description**: Get current authenticated user

**Request Headers**:
```
Authorization: Session token (from cookie)
```

**Success Response (200)**:
```json
{
  "user": {
    "id": 1,
    "name": "John Doe",
    "email": "john@example.com",
    "created_at": "2026-10-11T12:00:00Z",
    "last_login": "2026-10-11T12:30:00Z",
    "email_verified": false
  }
}
```

**Error Response (401)**:
```json
{
  "error": "Not authenticated"
}
```

---

#### GET /api/auth/check

**Description**: Check authentication status

**Success Response (200)**:
```json
{
  "authenticated": true
}
```

### 5.2 Database Schema

#### users Table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login TEXT,
    is_active INTEGER DEFAULT 1,
    email_verified INTEGER DEFAULT 0
);

CREATE INDEX idx_users_email ON users(email);
```

#### sessions Table
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
```

---

## 6. Security Considerations

### 6.1 Password Security

- **Hashing Algorithm**: PBKDF2-SHA256 (Werkzeug default)
- **Minimum Requirements**: 8 chars, uppercase, lowercase, number
- **Storage**: Never store plaintext passwords
- **Transmission**: Always over HTTPS in production

### 6.2 Session Management

- **Session Duration**: 
  - Default: 24 hours
  - "Remember Me": 30 days
- **Session Token**: 32-byte URL-safe random token
- **Storage**: Server-side in database
- **Cleanup**: Expired sessions removed on login

### 6.3 CSRF Protection

- Flask session cookies with `httponly` flag
- Same-site cookie policy
- Session validation on protected routes

### 6.4 Rate Limiting (Recommended)

```python
# Recommended implementation
- Login: 5 attempts per 15 minutes per IP
- Signup: 3 attempts per hour per IP
- Password reset: 3 attempts per hour per email
```

### 6.5 Input Sanitization

- Email: Lowercase, trim whitespace
- Name: Trim whitespace, max 100 chars
- Password: No transformation (preserve case and special chars)

---

## 7. Responsive Design

### 7.1 Breakpoints

```css
/* Mobile First Approach */

/* Small devices (phones) */
@media (max-width: 640px) {
  - Reduce card padding: 16px
  - Stack social buttons vertically
  - Reduce heading size: 1.5rem
  - Reduce logo size: 32px
}

/* Medium devices (tablets) */
@media (min-width: 641px) and (max-width: 1024px) {
  - Default card layout
  - Side-by-side social buttons
}

/* Large devices (desktops) */
@media (min-width: 1025px) {
  - Maximum card width: 480px
  - Full feature set
}
```

### 7.2 Mobile Optimizations

- Touch-friendly targets (minimum 44px)
- Appropriate input types (`type="email"`, `autocomplete`)
- Prevent zoom on input focus
- Optimized loading performance
- Reduced motion for animations on mobile

---

## 8. Accessibility

### 8.1 WCAG 2.1 Level AA Compliance

#### Keyboard Navigation
- All interactive elements focusable
- Visible focus indicators (2px outline)
- Tab order follows visual order
- Enter/Space activates buttons
- Arrow keys navigate tabs

#### Screen Reader Support
- Semantic HTML5 elements
- ARIA roles for tabs (`tablist`, `tab`, `tabpanel`)
- ARIA labels for icon-only buttons
- ARIA live regions for messages
- Form error announcements

#### Color Contrast
- Text: 4.5:1 minimum
- UI components: 3:1 minimum
- Focus indicators: 3:1 against background

### 8.2 Accessibility Features

```html
<!-- Focus Management -->
<input aria-required="true" 
       aria-invalid="false"
       aria-describedby="field-error field-hint">

<!-- Error Announcement -->
<span id="field-error" role="alert">Error message</span>

<!-- Loading State -->
<button aria-busy="true" aria-live="polite">
  <span class="sr-only">Loading...</span>
</button>
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
# test_auth_validation.py
def test_valid_email()
def test_invalid_email()
def test_password_strength_weak()
def test_password_strength_strong()
def test_password_requirements()
```

### 9.2 Integration Tests

```python
# test_auth_api.py
def test_signup_success()
def test_signup_duplicate_email()
def test_login_success()
def test_login_invalid_credentials()
def test_logout()
def test_session_expiry()
```

### 9.3 E2E Tests (Manual Checklist)

- [ ] Tab switching works smoothly
- [ ] All form validations trigger correctly
- [ ] Error messages display and dismiss
- [ ] Success flow redirects properly
- [ ] Password strength indicator updates
- [ ] Password toggle shows/hides text
- [ ] Social login buttons trigger OAuth
- [ ] Mobile responsive layout works
- [ ] Keyboard navigation works
- [ ] Screen reader announces properly

---

## 10. Deployment Guide

### 10.1 Integration with Existing App

```python
# app.py
from flask import Flask, session
from auth_routes import auth_bp, init_auth_db

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change in production!

# Register authentication blueprint
app.register_blueprint(auth_bp)

# Initialize auth database
init_auth_db()

# Add route to serve auth page
@app.get('/auth')
def auth_page():
    return render_template('auth.html')
```

### 10.2 Environment Configuration

```python
# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    SESSION_COOKIE_SECURE = True  # HTTPS only in production
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
```

### 10.3 Production Checklist

- [ ] Change `SECRET_KEY` to random value
- [ ] Enable HTTPS
- [ ] Set secure cookie flags
- [ ] Add rate limiting
- [ ] Configure email verification
- [ ] Set up OAuth credentials (Google, GitHub)
- [ ] Add logging and monitoring
- [ ] Test password reset flow
- [ ] Review security headers
- [ ] Run security audit

### 10.4 URLs

```
/auth          - Authentication page (GET)
/api/auth/signup  - User registration (POST)
/api/auth/login   - User login (POST)
/api/auth/logout  - User logout (POST)
/api/auth/me      - Current user info (GET)
/api/auth/check   - Auth status check (GET)
```

---

## Conclusion

The implementation provides basic account access for a private, single-instance PipelineIQ deployment. It does not provide a complete identity service. Current controls include:

- **User Experience**: Smooth, intuitive interface with clear feedback
- **Security**: Industry-standard password hashing, session management, and validation
- **Accessibility**: semantic forms, labels, keyboard-operable controls, and focus styling; a formal WCAG audit has not been performed
- **Maintainability**: Clean, modular code with comprehensive documentation
- **Performance**: Optimized for fast load times and smooth interactions

Before public deployment, configure edge rate limits and operational controls. Additional product features could include:
- Email verification
- Password reset flow
- Two-factor authentication
- OAuth provider integration
- User profile management
- Admin user management interface
