export const STATUS_LABEL: Record<string, string> = {
  unverified: 'Unverified',
  open: 'Open',
  acknowledged: 'Acknowledged',
  escalated: 'Escalated',
  claimed_fixed: 'Claimed fixed',
  verified_fixed: 'Verified fixed',
  reopened: 'Reopened (falsely closed)',
  dismissed: 'Dismissed',
}

export function when(ts: string | null | undefined): string {
  return ts ? new Date(ts).toLocaleString() : '—'
}

/** "due in 2 days" / "overdue by 5 h" */
export function dueText(due: string | null | undefined): string {
  if (!due) return 'no deadline'
  const hours = (new Date(due).getTime() - Date.now()) / 3_600_000
  const span = (h: number) => (Math.abs(h) >= 48 ? `${Math.round(Math.abs(h) / 24)} days` : `${Math.round(Math.abs(h))} h`)
  return hours >= 0 ? `due in ${span(hours)}` : `overdue by ${span(hours)}`
}

export const STATUS_COLORS: Record<string, string> = {
  unverified: '#9ca3af',
  open: '#dc2626',
  reopened: '#dc2626',
  escalated: '#7c2d12',
  acknowledged: '#f59e0b',
  claimed_fixed: '#3b82f6',
  verified_fixed: '#16a34a',
  dismissed: '#6b7280',
}

export const SEVERITY_LABEL: Record<string, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' }

/** "just now", "5 min ago", "3 h ago", "2 days ago" */
export function ago(ts: string | null | undefined): string {
  if (!ts) return '—'
  const s = (Date.now() - new Date(ts).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} days ago`
}

/** 0..1 share of the deadline window already used (1 = due or overdue). */
export function deadlineUsed(opened: string, due: string | null | undefined): number | null {
  if (!due) return null
  const a = new Date(opened).getTime(), b = new Date(due).getTime()
  if (b <= a) return 1
  return Math.min(1, Math.max(0, (Date.now() - a) / (b - a)))
}
