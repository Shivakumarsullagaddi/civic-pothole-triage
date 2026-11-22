import { BrowserRouter, Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { AuthProvider, RequireStaff, useAuth } from './lib/auth'
import AdminPage from './pages/AdminPage'
import AuthorityPage from './pages/AuthorityPage'
import DashboardPage from './pages/DashboardPage'
import HealthPage from './pages/HealthPage'
import HomePage from './pages/HomePage'
import IssuePage from './pages/IssuePage'
import LoginPage from './pages/LoginPage'
import MapPage from './pages/MapPage'
import ReportPage from './pages/ReportPage'

const LINKS = [
  { to: '/report', label: 'Report', icon: '📷' },
  { to: '/map', label: 'Map', icon: '🗺️' },
  { to: '/dashboard', label: 'Dashboard', icon: '📊' },
]

function UserArea() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  if (!user) {
    return (
      <NavLink to="/login" className={({ isActive }) => `health-link${isActive ? ' active' : ''}`}>
        🏛️ Staff sign in
      </NavLink>
    )
  }
  return (
    <>
      <NavLink to="/authority" className={({ isActive }) => `health-link${isActive ? ' active' : ''}`}>🏛️ Console</NavLink>
      {user.role === 'admin' && (
        <NavLink to="/admin" className={({ isActive }) => `health-link${isActive ? ' active' : ''}`}>🛠️ Admin</NavLink>
      )}
      <button
        className="user-chip"
        title={`${user.email} · ${user.role}. Click to sign out`}
        onClick={async () => {
          await signOut()
          navigate('/')
        }}
      >
        <span className="user-avatar">{user.name.slice(0, 1).toUpperCase()}</span>
        <span className="user-name">Sign out</span>
      </button>
    </>
  )
}

function Shell() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <ellipse cx="12" cy="14" rx="9" ry="5" fill="currentColor" opacity="0.35" />
              <ellipse cx="12" cy="13" rx="5.5" ry="2.8" fill="currentColor" />
            </svg>
          </span>
          <span className="brand-text">
            Pothole<strong>Triage</strong>
          </span>
        </Link>
        <nav className="navtabs" aria-label="Main">
          {LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? 'active' : '')}>
              <span aria-hidden="true">{l.icon}</span>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <UserArea />
        <NavLink to="/status" className={({ isActive }) => `health-link${isActive ? ' active' : ''}`} title="System health">
          <span className="health-dot" aria-hidden="true" /> Status
        </NavLink>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/report" element={<ReportPage />} />
        <Route path="/map" element={<MapPage />} />
        <Route path="/issue/:id" element={<IssuePage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/authority" element={<RequireStaff><AuthorityPage /></RequireStaff>} />
        <Route path="/admin" element={<RequireStaff admin><AdminPage /></RequireStaff>} />
        <Route path="/status" element={<HealthPage />} />
      </Routes>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </BrowserRouter>
  )
}
