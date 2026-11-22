import { useCallback, useEffect, useMemo, useState } from 'react'
import { authority, type IssueRow, type ReportRow } from '../api/client'
import Thumb from '../components/Thumb'
import { DeadlineBar, SeverityBadge, StatePill, StatusPill, TrustMeter } from '../components/ui'
import { ago, when } from '../lib/format'
import { useAuth } from '../lib/auth'
import { IssueDrawer, ReportDrawer } from './authority/Drawers'

const SEVERITY_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 }

type Filter = 'all' | 'overdue' | 'escalated' | 'unverified' | 'claimed_fixed'
type Sort = 'deadline' | 'activity' | 'severity' | 'reports'
type Open = { kind: 'issue' | 'report'; id: string } | null
type Toast = { msg: string; tone: 'good' | 'bad'; key: number } | null

function matches(q: string, ...fields: (string | number | null | undefined)[]) {
  if (!q) return true
  const hay = fields.filter((f) => f != null).join(' ').toLowerCase()
  return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))
}

export default function AuthorityPage() {
  const { user, signOut } = useAuth()
  const token = '' // staff are identified by the session cookie
  const [issues, setIssues] = useState<IssueRow[] | null>(null)
  const [reports, setReports] = useState<ReportRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'issues' | 'reports'>('issues')
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<Sort>('deadline')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Open>(null)
  const [toast, setToast] = useState<Toast>(null)

  const notify = useCallback((msg: string, tone: 'good' | 'bad' = 'good') => {
    setToast({ msg, tone, key: Date.now() })
  }, [])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const load = useCallback(() => {
    setError(null)
    Promise.all([authority.list(token), authority.reports(token)])
      .then(([i, r]) => {
        setIssues(i)
        setReports(r)
      })
      .catch((e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  const counts = useMemo(() => {
    const list = issues ?? []
    return {
      all: list.length,
      overdue: list.filter((i) => i.overdue).length,
      escalated: list.filter((i) => i.escalation_level > 0 && i.status !== 'claimed_fixed').length,
      unverified: list.filter((i) => i.status === 'unverified').length,
      claimed_fixed: list.filter((i) => i.status === 'claimed_fixed').length,
    }
  }, [issues])

  const issueRows = useMemo(() => {
    const list = (issues ?? []).filter((i) => {
      if (filter === 'overdue' && !i.overdue) return false
      if (filter === 'escalated' && !(i.escalation_level > 0 && i.status !== 'claimed_fixed')) return false
      if (filter === 'unverified' && i.status !== 'unverified') return false
      if (filter === 'claimed_fixed' && i.status !== 'claimed_fixed') return false
      return matches(query, i.ward_name, i.ward_no, i.corporation, i.authority_name, i.status, i.severity)
    })
    const t = (s: string | null | undefined) => (s ? new Date(s).getTime() : Infinity)
    return [...list].sort((a, b) =>
      sort === 'deadline' ? t(a.due_at) - t(b.due_at)
        : sort === 'activity' ? t(b.last_activity_at) - t(a.last_activity_at)
          : sort === 'severity' ? (SEVERITY_RANK[b.severity ?? ''] ?? 0) - (SEVERITY_RANK[a.severity ?? ''] ?? 0)
            : b.report_count - a.report_count)
  }, [issues, filter, query, sort])

  const reportRows = useMemo(
    () => (reports ?? []).filter((r) => matches(query, r.ward_name, r.ward_no, r.corporation, r.state, r.capture_source, ...r.reasons)),
    [reports, query],
  )

  async function escalateNow() {
    try {
      const r = await authority.escalate()
      notify(`${r.overdue} overdue · ${r.moved_up} moved up · ${r.at_top} already at the top`)
      load()
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Escalation failed', 'bad')
    }
  }

  const chips: { key: Filter; label: string; tone?: string }[] = [
    { key: 'all', label: 'All open' },
    { key: 'overdue', label: 'Overdue', tone: 'bad' },
    { key: 'escalated', label: 'Escalated', tone: 'warn' },
    { key: 'unverified', label: 'Needs confirmation' },
    { key: 'claimed_fixed', label: 'Awaiting repair check', tone: 'info' },
  ]

  return (
    <div className="console">
      <header className="console-head">
        <div>
          <h1>Authority console</h1>
          <p className="muted">
            Signed in as <strong>{user?.name}</strong> ({user?.role}{user?.authority_name ? ` · ${user.authority_name}` : ''}) ·{' '}
            {counts.all} open potholes · {reports?.length ?? 0} recent reports
          </p>
        </div>
        <div className="row head-actions">
          <button onClick={load}>↻ Refresh</button>
          {user?.role === 'admin' && (
            <button onClick={escalateNow} title="Move overdue issues up one level now (also runs hourly)">⇪ Escalate overdue</button>
          )}
          <button onClick={() => signOut()}>Sign out</button>
        </div>
      </header>

      {error && <p className="bad">{error}</p>}

      <div className="chips" role="tablist" aria-label="Filter issues">
        {chips.map((c) => (
          <button
            key={c.key}
            className={`chip ${c.tone ?? ''} ${filter === c.key && tab === 'issues' ? 'active' : ''}`}
            onClick={() => {
              setFilter(c.key)
              setTab('issues')
            }}
          >
            <span className="chip-count">{issues ? counts[c.key] : '…'}</span>
            <span>{c.label}</span>
          </button>
        ))}
      </div>

      <div className="toolbar">
        <div className="seg" role="tablist">
          <button className={tab === 'issues' ? 'active' : ''} onClick={() => setTab('issues')}>Issues</button>
          <button className={tab === 'reports' ? 'active' : ''} onClick={() => setTab('reports')}>Recent reports</button>
        </div>
        <input className="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search ward, corporation, office, status…" />
        {tab === 'issues' && (
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
            <option value="deadline">Deadline first</option>
            <option value="activity">Latest activity</option>
            <option value="severity">Most severe</option>
            <option value="reports">Most reports</option>
          </select>
        )}
      </div>

      <div className="table-wrap">
        {tab === 'issues' ? (
          <table className="grid">
            <thead>
              <tr>
                <th style={{ width: 72 }}>Photo</th>
                <th>Pothole</th>
                <th>Location</th>
                <th>Deadline</th>
                <th className="num">Reports</th>
                <th>Last activity</th>
              </tr>
            </thead>
            <tbody>
              {!issues && [0, 1, 2, 3].map((i) => <tr key={i}><td colSpan={6}><div className="skeleton" style={{ height: 40 }} /></td></tr>)}
              {issueRows.map((i) => (
                <tr
                  key={i.id}
                  className={open?.kind === 'issue' && open.id === i.id ? 'selected' : ''}
                  onClick={() => setOpen({ kind: 'issue', id: i.id })}
                  onKeyDown={(e) => e.key === 'Enter' && setOpen({ kind: 'issue', id: i.id })}
                  tabIndex={0}
                >
                  <td><Thumb token={token} reportId={i.latest_report_id} /></td>
                  <td>
                    <div className="cell-stack">
                      <StatusPill status={i.status} />
                      <SeverityBadge severity={i.severity} />
                    </div>
                  </td>
                  <td>
                    <div className="cell-main">{i.ward_name ? `Ward ${i.ward_no} ${i.ward_name}` : 'Outside GBA'}</div>
                    <div className="muted cell-sub">{i.corporation ? `${i.corporation} · ` : ''}{i.authority_name ?? 'no office'}</div>
                  </td>
                  <td><DeadlineBar opened={i.opened_at} due={i.due_at} overdue={i.overdue} /></td>
                  <td className="num"><span className="count-badge">{i.report_count}</span></td>
                  <td title={when(i.last_activity_at)}>{ago(i.last_activity_at)}</td>
                </tr>
              ))}
              {issues && issueRows.length === 0 && (
                <tr><td colSpan={6} className="empty">Nothing here. {query || filter !== 'all' ? 'Try clearing the search or filter.' : 'No open potholes.'}</td></tr>
              )}
            </tbody>
          </table>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th style={{ width: 72 }}>Photo</th>
                <th>Received</th>
                <th>Result</th>
                <th>Trust</th>
                <th className="num">Boxes</th>
                <th>Location</th>
                <th>Issue</th>
              </tr>
            </thead>
            <tbody>
              {!reports && [0, 1, 2, 3].map((i) => <tr key={i}><td colSpan={7}><div className="skeleton" style={{ height: 40 }} /></td></tr>)}
              {reportRows.map((r) => (
                <tr
                  key={r.id}
                  className={open?.kind === 'report' && open.id === r.id ? 'selected' : ''}
                  onClick={() => setOpen({ kind: 'report', id: r.id })}
                  onKeyDown={(e) => e.key === 'Enter' && setOpen({ kind: 'report', id: r.id })}
                  tabIndex={0}
                >
                  <td><Thumb token={token} reportId={r.id} /></td>
                  <td>
                    <div className="cell-main">{ago(r.received_at)}</div>
                    <div className="muted cell-sub">{r.capture_source === 'camera' ? 'live camera' : 'upload'}</div>
                  </td>
                  <td>
                    <StatePill state={r.state} />
                    {r.reasons[0] && <div className="muted cell-sub clip" title={r.reasons.join('\n')}>{r.reasons[0]}</div>}
                  </td>
                  <td><TrustMeter score={r.trust_score} /></td>
                  <td className="num">{r.boxes}</td>
                  <td>
                    <div className="cell-main">{r.ward_name ? `Ward ${r.ward_no} ${r.ward_name}` : '—'}</div>
                    <div className="muted cell-sub">{r.corporation ?? ''}</div>
                  </td>
                  <td>{r.issue_status ? <StatusPill status={r.issue_status} /> : <span className="muted">none</span>}</td>
                </tr>
              ))}
              {reports && reportRows.length === 0 && <tr><td colSpan={7} className="empty">No reports match.</td></tr>}
            </tbody>
          </table>
        )}
      </div>

      {open?.kind === 'issue' && (
        <IssueDrawer
          token={token}
          id={open.id}
          onClose={() => setOpen(null)}
          onChanged={load}
          onOpenReport={(id) => setOpen({ kind: 'report', id })}
          notify={notify}
        />
      )}
      {open?.kind === 'report' && (
        <ReportDrawer
          token={token}
          id={open.id}
          onClose={() => setOpen(null)}
          onOpenIssue={(id) => setOpen({ kind: 'issue', id })}
          onChanged={load}
          notify={notify}
        />
      )}

      {toast && (
        <div key={toast.key} className={`toast ${toast.tone}`} role="status">
          {toast.msg}
        </div>
      )}
    </div>
  )
}
