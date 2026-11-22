import type { components } from './schema'

// Types are generated from the backend's OpenAPI schema (npm run gen:api).
export type ReportOut = components['schemas']['ReportOut']
export type IssueDetail = components['schemas']['IssueDetail']
export type WardOut = components['schemas']['WardOut']
export type Stats = components['schemas']['Stats']
export type WardProps = { ward_no: number; name: string; name_kn: string | null; corporation: string; zone: string | null }

export type IssueProps = Omit<IssueDetail, 'lat' | 'lng' | 'events'>
export type IssueFeatureCollection = GeoJSON.FeatureCollection<GeoJSON.Point, IssueProps>

export type Health = {
  status: 'ok' | 'degraded'
  database: { ok: boolean; postgis?: string; error?: string; detail?: string }
  model: { loaded: boolean; mode?: string; file?: string; error?: string; pothole_classes?: string[] }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep the status text */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export type AuthorityIssue = components['schemas']['AuthorityIssue']
export type IssueSummary = components['schemas']['AuthorityIssueRow']
export type IssueRow = components['schemas']['AuthorityIssueRow']
export type ReportRow = components['schemas']['ReportRow']
export type ReportDetail = components['schemas']['ReportDetail']
export type StatusAction = 'acknowledge' | 'claim_fixed' | 'dismiss'

// Staff are identified by the httpOnly session cookie (sent automatically, same origin).
// A token is only sent when given (legacy scripts); the app passes ''.
const authHeaders = (token: string): Record<string, string> => (token ? { 'X-Authority-Token': token } : {})

export const authority = {
  list: (token: string) =>
    fetch('/api/authority/issues', { headers: authHeaders(token) }).then((r) => json<IssueRow[]>(r)),
  reports: (token: string, limit = 200) =>
    fetch(`/api/authority/reports?limit=${limit}`, { headers: authHeaders(token) }).then((r) => json<ReportRow[]>(r)),
  report: (token: string, id: string) =>
    fetch(`/api/authority/reports/${id}`, { headers: authHeaders(token) }).then((r) => json<ReportDetail>(r)),
  item: (token: string, id: string) =>
    fetch(`/api/authority/issues/${id}`, { headers: authHeaders(token) }).then((r) => json<AuthorityIssue>(r)),
  photo: async (token: string, reportId: string, index: number): Promise<string> => {
    const r = await fetch(`/api/authority/reports/${reportId}/frames/${index}`, { headers: authHeaders(token) })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return URL.createObjectURL(await r.blob())
  },
  act: (token: string, id: string, action: StatusAction, note: string | null) =>
    fetch(`/api/issues/${id}/status`, {
      method: 'POST',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, note }),
    }).then((r) => json<IssueDetail>(r)),
  escalate: () =>
    fetch('/api/admin/escalate', { method: 'POST' }).then((r) => json<{ overdue: number; moved_up: number; at_top: number }>(r)),
}

export type User = components['schemas']['UserOut']
export type UserCreate = components['schemas']['UserCreate']
export type UserUpdate = components['schemas']['UserUpdate']
export type Office = components['schemas']['AuthorityOut']

const postJson = (url: string, body: unknown, method = 'POST') =>
  fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const auth = {
  me: () => fetch('/api/auth/me').then((r) => json<User | null>(r)),
  login: (email: string, password: string) => postJson('/api/auth/login', { email, password }).then((r) => json<User>(r)),
  logout: () => fetch('/api/auth/logout', { method: 'POST' }),
}

export const admin = {
  users: () => fetch('/api/admin/users').then((r) => json<User[]>(r)),
  create: (body: UserCreate) => postJson('/api/admin/users', body).then((r) => json<User>(r)),
  update: (id: number, body: UserUpdate) => postJson(`/api/admin/users/${id}`, body, 'PATCH').then((r) => json<User>(r)),
  deletePhoto: (reportId: string, index: number) =>
    fetch(`/api/admin/reports/${reportId}/frames/${index}`, { method: 'DELETE' }).then((r) => json<{ remaining_photos: number }>(r)),
  deleteReport: (reportId: string) =>
    fetch(`/api/admin/reports/${reportId}`, { method: 'DELETE' }).then((r) => json<{ issue_deleted: boolean }>(r)),
  offices: (q: string) => fetch(`/api/admin/authorities?q=${encodeURIComponent(q)}`).then((r) => json<Office[]>(r)),
}

export const api = {
  health: () => fetch('/health').then((r) => json<Health>(r)),
  stats: () => fetch('/api/stats').then((r) => json<Stats>(r)),
  issues: () => fetch('/api/issues.geojson').then((r) => json<IssueFeatureCollection>(r)),
  issue: (id: string) => fetch(`/api/issues/${id}`).then((r) => json<IssueDetail>(r)),
  wards: () => fetch('/api/wards.geojson').then((r) => json<GeoJSON.FeatureCollection<GeoJSON.Geometry, WardProps>>(r)),
  wardAt: (lat: number, lng: number) =>
    fetch(`/api/wards/lookup?lat=${lat}&lng=${lng}`).then((r) => (r.status === 404 ? null : json<WardOut>(r))),
  createReport: (form: FormData) =>
    fetch('/api/reports', { method: 'POST', body: form }).then((r) => json<ReportOut>(r)),
}
