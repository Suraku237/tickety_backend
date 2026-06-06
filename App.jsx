import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import LandingPage      from './pages/LandingPage';
import LoginPage        from './pages/LoginPage';
import RegistrationPage from './pages/RegistrationPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ServiceSetupPage from './pages/ServiceSetupPage';
import DashboardPage    from './pages/DashboardPage';
import QueuesPage       from './pages/QueuesPage';
import CounterPage      from './pages/CountersPage';
import TeamPage         from './pages/TeamPage';
import AnalyticsPage    from './pages/AnalyticsPage';
import SettingsPage     from './pages/SettingsPage';
import NotFoundPage     from './pages/NotFoundPage';
import ProtectedRoute   from './components/ProtectedRoute';

// =============================================================
// APP  — Route definitions
// OOP Principle: Single Responsibility (routing only)
// =============================================================
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public */}
        <Route path="/"              element={<LandingPage />}      />
        <Route path="/login"         element={<LoginPage />}         />
        <Route path="/register"      element={<RegistrationPage />}  />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/setup-service" element={<ServiceSetupPage />}  />

        {/* Protected — all wrapped in ProtectedRoute */}
        <Route path="/dashboard" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
        <Route path="/queues"    element={<ProtectedRoute><QueuesPage /></ProtectedRoute>}    />
        <Route path="/counter"   element={<ProtectedRoute><CounterPage /></ProtectedRoute>}   />
        <Route path="/team"      element={<ProtectedRoute><TeamPage /></ProtectedRoute>}      />
        <Route path="/analytics" element={<ProtectedRoute><AnalyticsPage /></ProtectedRoute>} />
        <Route path="/settings"  element={<ProtectedRoute><SettingsPage /></ProtectedRoute>}  />

        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}