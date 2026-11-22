import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { auth, type User } from '../api/client'

type AuthState = {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<User>
  signOut: () => Promise<void>
  refresh: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(() => {
    auth.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false))
  }, [])
  useEffect(refresh, [refresh])

  const signIn = useCallback(async (email: string, password: string) => {
    const u = await auth.login(email, password)
    setUser(u)
    return u
  }, [])
  const signOut = useCallback(async () => {
    await auth.logout()
    setUser(null)
  }, [])

  return <AuthContext.Provider value={{ user, loading, signIn, signOut, refresh }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** Renders children only for signed-in staff (optionally admins only); otherwise sends to /login. */
export function RequireStaff({ admin = false, children }: { admin?: boolean; children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page"><div className="skeleton" style={{ height: 200 }} /></div>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  if (admin && user.role !== 'admin') {
    return (
      <div className="page">
        <div className="panel callout bad"><h3>Admins only</h3><p>Your account ({user.email}) is an officer account.</p></div>
      </div>
    )
  }
  return <>{children}</>
}
