// =============================================================
// API SERVICE
// Responsibilities:
//   - Single source of all HTTP communication with the backend
//   - Every page/component imports from here — never fetch() directly
//   - Sends X-App-Source: web on every request (auto admin role)
//   - Centralises base URL via environment variable
// OOP Principle: Singleton, Encapsulation, Abstraction
//   (mirrors ApiService singleton in the Flutter app)
// =============================================================

const BASE_URL = import.meta.env.VITE_API_URL ?? 'https://tickety.duckdns.org/api';

const WEB_HEADERS = {
  'Content-Type': 'application/json',
  'X-App-Source': 'web',
};


// ----------------------------------------------------------
// PRIVATE: Generic POST handler
// ----------------------------------------------------------
async function _post(endpoint, body, includeStatus = false) {
  try {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
      method:  'POST',
      headers: WEB_HEADERS,
      body:    JSON.stringify(body),
    });

    const data = await response.json();

    if (includeStatus) {
      return { ...data, statusCode: response.status };
    }

    return data;
  } catch {
    return {
      success: false,
      message: 'Connection error. Please check your network.',
    };
  }
}

// ----------------------------------------------------------
// PRIVATE: Generic GET handler
// ----------------------------------------------------------
async function _get(endpoint, params = {}) {
  try {
    const query    = new URLSearchParams(params).toString();
    const url      = `${BASE_URL}${endpoint}${query ? `?${query}` : ''}`;
    const response = await fetch(url, { headers: WEB_HEADERS });
    return await response.json();
  } catch {
    return {
      success: false,
      message: 'Connection error. Please check your network.',
    };
  }
}

// =============================================================
// AUTH ENDPOINTS
// =============================================================

/**
 * Register a new admin user.
 * Backend assigns role='admin' from X-App-Source: web header.
 */
export async function register({ username, email, password }) {
  return _post('/register', { username, email, password });
}

/**
 * Log in with email and password.
 * Returns statusCode so UI can detect 403 (unverified) vs 401 (wrong creds).
 */
export async function login({ email, password }) {
  return _post('/login', { email, password }, true);
}

/**
 * Verify the 6-digit OTP sent by email.
 */
export async function verifyEmail({ email, code }) {
  return _post('/verify-email', { email, code });
}

/**
 * Resend a fresh OTP to the user's email.
 */
export async function resendOtp({ email }) {
  return _post('/resend-otp', { email });
}

// =============================================================
// SERVICE ENDPOINTS
// =============================================================

/**
 * Create a new service/enterprise.
 * Atomically creates: Service row + Admin row (admin_role='boss').
 * Called at Step 3 of registration — after email is verified.
 */
export async function createService({ email, serviceName }) {
  return _post('/services', { email, service_name: serviceName });
}

/**
 * Fetch all services owned by a user (by email).
 * Useful later for a service-selector screen.
 */
export async function getMyServices({ email }) {
  return _get('/services/mine', { email });
}

// =============================================================
// PASSWORD RESET ENDPOINTS
// =============================================================

/**
 * Initiate password reset flow.
 * Sends OTP to user's email.
 */
export async function requestPasswordReset({ email }) {
  return _post('/password-reset/request', { email });
}

/**
 * Verify OTP and get reset token.
 * Called after user enters 6-digit code from email.
 */
export async function verifyPasswordResetOtp({ email, code }) {
  return _post('/password-reset/verify-otp', { email, code });
}

/**
 * Reset password using token.
 * Called after OTP verification — user enters new password.
 */
export async function resetPassword({ email, token, newPassword }) {
  return _post('/password-reset/confirm', { email, token, new_password: newPassword });
}