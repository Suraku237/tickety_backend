import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AuthLayout from '../components/AuthLayout';
import FormField from '../components/FormField';
import OtpGrid from '../components/OtpGrid';
import { requestPasswordReset, verifyPasswordResetOtp, resetPassword } from '../services/api.service';
import { useAuth } from '../hooks/useAuth';
import { validateEmail, validatePassword, validate } from '../utils/validators';
import { RESEND_COOLDOWN_SECONDS } from '../utils/constants';

// =============================================================
// FORGOT PASSWORD PAGE
// Flow:
//   Step 1 → Email entry (request reset)
//   Step 2 → OTP verification
//   Step 3 → New password entry (reset password)
// OOP Principle: State Machine, Encapsulation, Single Responsibility
// =============================================================
export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const { loading, error, setError, successMsg, setSuccessMsg, submit } = useAuth();

  // Form state
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetToken, setResetToken] = useState('');

  // Cooldown for resend OTP
  const [cooldown, setCooldown] = useState(0);
  const [coolRef, setCoolRef] = useState(null);

  // ────────────────────────────────────────────────────────
  // STEP 1: Request password reset
  // ────────────────────────────────────────────────────────
  const handleRequestReset = (e) => {
    e.preventDefault();

    const err = validate(validateEmail(email));
    if (err) {
      setError(err);
      return;
    }

    submit(async () => {
      const data = await requestPasswordReset({
        email: email.toLowerCase().trim(),
      });

      if (data.success) {
        setStep(2);
        startCooldown(RESEND_COOLDOWN_SECONDS);
        setSuccessMsg('');
      } else {
        setError(data.message || 'Could not send reset code. Please try again.');
      }
    });
  };

  // ────────────────────────────────────────────────────────
  // STEP 2: Verify OTP and get reset token
  // ────────────────────────────────────────────────────────
  const handleOtpComplete = (code) => {
    submit(async () => {
      const data = await verifyPasswordResetOtp({
        email: email.toLowerCase().trim(),
        code,
      });

      if (data.success) {
        // Backend returns token for password reset
        setResetToken(data.token || data.reset_token || '');
        setStep(3);
        setSuccessMsg('');
      } else {
        setError(data.message || 'Invalid code. Please try again.');
      }
    });
  };

  // ────────────────────────────────────────────────────────
  // STEP 3: Reset password with token
  // ────────────────────────────────────────────────────────
  const handleResetPassword = (e) => {
    e.preventDefault();

    const passwordErr = validate(
      validatePassword(newPassword),
    );
    if (passwordErr) {
      setError(passwordErr);
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    submit(async () => {
      const data = await resetPassword({
        email: email.toLowerCase().trim(),
        token: resetToken,
        newPassword,
      });

      if (data.success) {
        setSuccessMsg('Password reset successful! Redirecting to login...');
        setError('');
        setTimeout(() => {
          navigate('/login');
        }, 2000);
      } else {
        setError(data.message || 'Password reset failed. Please try again.');
      }
    });
  };

  // ────────────────────────────────────────────────────────
  // Resend OTP
  // ────────────────────────────────────────────────────────
  const handleResendOtp = () => {
    if (cooldown > 0) return;
    setError('');
    setSuccessMsg('');

    submit(async () => {
      const data = await requestPasswordReset({
        email: email.toLowerCase().trim(),
      });

      if (data.success) {
        setSuccessMsg('New code sent to your email!');
        startCooldown(RESEND_COOLDOWN_SECONDS);
      } else {
        setError(data.message || 'Could not resend code.');
      }
    });
  };

  // ────────────────────────────────────────────────────────
  // Cooldown timer for resend
  // ────────────────────────────────────────────────────────
  const startCooldown = (secs) => {
    if (coolRef) clearInterval(coolRef);
    setCooldown(secs);
    const t = setInterval(() => {
      setCooldown(prev => {
        if (prev <= 1) {
          clearInterval(t);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    setCoolRef(t);
  };

  // ────────────────────────────────────────────────────────
  // LEFT PANEL CONTENT
  // ────────────────────────────────────────────────────────
  const leftContent = (
    <>
      <div className="reg-steps">
        {['Email', 'Verify', 'Password'].map((label, i) => (
          <div
            key={label}
            className={`reg-step ${step === i + 1 ? 'active' : ''} ${
              step > i + 1 ? 'done' : ''
            }`}
          >
            <div className="rs-circle">{step > i + 1 ? '✓' : i + 1}</div>
            <span className="rs-label">{label}</span>
            {i < 2 && <div className="rs-line" />}
          </div>
        ))}
      </div>
      <h2 className="auth-left-title">
        {step === 1 && <>Reset your password</>}
        {step === 2 && <>Check your inbox</>}
        {step === 3 && <>Create new password</>}
      </h2>
      <p className="auth-left-sub">
        {step === 1 && 'Enter your email to get a reset code'}
        {step === 2 && `We sent a 6-digit code to ${email}`}
        {step === 3 && 'Set a strong new password for your account'}
      </p>
    </>
  );

  return (
    <AuthLayout leftContent={leftContent}>
      {/* ────────────────────────────────────────────────────────
          STEP 1: Email Entry
          ──────────────────────────────────────────────────────── */}
      {step === 1 && (
        <>
          <div className="auth-card-badge">STEP 1 OF 3 — EMAIL</div>
          <h1 className="auth-card-title">Forgot password?</h1>
          <p className="auth-card-sub">
            Enter your email address and we'll send you a code to reset your
            password
          </p>

          {error && (
            <div className="auth-error">
              <span className="auth-error-icon">⚠</span>
              {error}
            </div>
          )}

          <form className="auth-form" onSubmit={handleRequestReset}>
            <FormField
              label="EMAIL ADDRESS"
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={setEmail}
              autoComplete="email"
              autoFocus
              icon={
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
              }
            />

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? <span className="auth-spinner" /> : 'SEND RESET CODE'}
            </button>
          </form>

          <div className="auth-divider">
            <span>or</span>
          </div>
          <p className="auth-switch">
            Remember your password?{' '}
            <button
              className="auth-link"
              onClick={() => navigate('/login')}
              type="button"
            >
              Sign in
            </button>
          </p>
        </>
      )}

      {/* ────────────────────────────────────────────────────────
          STEP 2: OTP Verification
          ──────────────────────────────────────────────────────── */}
      {step === 2 && (
        <>
          <div className="auth-card-badge">STEP 2 OF 3 — VERIFICATION</div>
          <h1 className="auth-card-title">Verify email</h1>
          <p className="auth-card-sub">
            Code sent to{' '}
            <strong style={{ color: 'var(--crimson)' }}>{email}</strong>
          </p>

          {error && (
            <div className="auth-error">
              <span className="auth-error-icon">⚠</span>
              {error}
            </div>
          )}
          {successMsg && (
            <div className="auth-success">
              <span>✓</span>
              {successMsg}
            </div>
          )}

          <OtpGrid onComplete={handleOtpComplete} disabled={loading} />

          {loading && (
            <div style={{ display: 'flex', justifyContent: 'center', margin: '16px 0' }}>
              <span className="auth-spinner" />
            </div>
          )}

          <div className="otp-resend">
            <span>Didn't receive it?</span>
            <button
              className="auth-link"
              onClick={handleResendOtp}
              disabled={cooldown > 0}
              style={{ opacity: cooldown > 0 ? 0.5 : 1 }}
              type="button"
            >
              {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
            </button>
          </div>
          <p className="otp-expiry">Code expires in 10 minutes</p>
        </>
      )}

      {/* ────────────────────────────────────────────────────────
          STEP 3: Password Reset
          ──────────────────────────────────────────────────────── */}
      {step === 3 && (
        <>
          <div className="auth-card-badge">STEP 3 OF 3 — NEW PASSWORD</div>
          <h1 className="auth-card-title">Create new password</h1>
          <p className="auth-card-sub">Enter a strong password for your account</p>

          {error && (
            <div className="auth-error">
              <span className="auth-error-icon">⚠</span>
              {error}
            </div>
          )}
          {successMsg && (
            <div className="auth-success">
              <span>✓</span>
              {successMsg}
            </div>
          )}

          <form className="auth-form" onSubmit={handleResetPassword}>
            <FormField
              label="NEW PASSWORD"
              type="password"
              placeholder="Min 6 chars with a number"
              value={newPassword}
              onChange={setNewPassword}
              autoComplete="new-password"
              autoFocus
              icon={
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
              }
            />

            <FormField
              label="CONFIRM PASSWORD"
              type="password"
              placeholder="Re-enter your password"
              value={confirmPassword}
              onChange={setConfirmPassword}
              autoComplete="new-password"
              icon={
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              }
            />

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? <span className="auth-spinner" /> : 'RESET PASSWORD'}
            </button>
          </form>

          <div className="auth-divider">
            <span>or</span>
          </div>
          <p className="auth-switch">
            Remember your password?{' '}
            <button
              className="auth-link"
              onClick={() => navigate('/login')}
              type="button"
            >
              Sign in
            </button>
          </p>
        </>
      )}
    </AuthLayout>
  );
}
