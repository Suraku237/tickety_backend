import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AuthLayout     from '../components/AuthLayout';
import FormField      from '../components/FormField';
import { login }      from '../services/api.service';
import { saveSession } from '../services/session.service';
import { useAuth }    from '../hooks/useAuth';
import { validateEmail, validatePassword, validate } from '../utils/validators';

// =============================================================
// LOGIN PAGE
// OOP Principle: Encapsulation, Single Responsibility
// All HTTP logic delegated to api.service.js
// =============================================================
export default function LoginPage() {
  const navigate = useNavigate();
  const { loading, error, setError, submit } = useAuth();

  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');

  const handleLogin = (e) => {
    e.preventDefault();

    const err = validate(
      validateEmail(email),
      validatePassword(password),
    );
    if (err) { setError(err); return; }

    submit(async () => {
      const data = await login({
        email:    email.toLowerCase().trim(),
        password,
      });

      if (data.success) {
        saveSession(data);
        navigate('/dashboard');
      } else if (data.statusCode === 403 && data.message?.includes('verify')) {
        navigate('/verify', { state: { email: email.toLowerCase().trim() } });
      } else {
        setError(data.message || 'Invalid credentials.');
      }
    });
  };

  const leftContent = (
    <>
      <h2 className="auth-left-title">Manage queues.<br />Serve better.</h2>
      <p className="auth-left-sub">The admin dashboard for modern service operations.</p>
      <div className="auth-left-features">
        {[
          'Real-time queue visibility',
          'Multi-counter management',
          'Team role management',
          'Customer ticket tracking',
        ].map(f => (
          <div key={f} className="feature-row">
            <span className="feature-check">✓</span>
            <span>{f}</span>
          </div>
        ))}
      </div>
    </>
  );

  return (
    <AuthLayout leftContent={leftContent}>
      <div className="auth-card-badge">ADMIN PORTAL</div>
      <h1 className="auth-card-title">Welcome back</h1>
      <p className="auth-card-sub">Sign in to your service dashboard</p>

      {error && (
        <div className="auth-error">
          <span className="auth-error-icon">⚠</span>{error}
        </div>
      )}

      <form className="auth-form" onSubmit={handleLogin}>
        <FormField
          label="EMAIL ADDRESS"
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4
                c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
              <polyline points="22,6 12,13 2,6"/>
            </svg>
          }
        />
        <FormField
          label="PASSWORD"
          type="password"
          placeholder="Your password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          }
        />

        <button type="submit" className="auth-submit" disabled={loading}>
          {loading ? <span className="auth-spinner" /> : 'SIGN IN'}
        </button>
      </form>

      <div style={{ textAlign: 'center', margin: '12px 0' }}>
        <button 
          className="auth-link" 
          onClick={() => navigate('/forgot-password')}
          type="button"
          style={{ fontSize: '14px' }}
        >
          Forgot password?
        </button>
      </div>

      <div className="auth-divider"><span>or</span></div>
      <p className="auth-switch">
        Don't have an account?{' '}
        <button className="auth-link" onClick={() => navigate('/register')}>
          Create one
        </button>
      </p>
    </AuthLayout>
  );
}