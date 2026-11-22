import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { admin, authority, type AuthorityIssue, type ReportDetail, type StatusAction } from '../../api/client'
import BoxedPhotos, { type PhotoFrame } from '../../components/BoxedPhotos'
import { forgetPhotos, loadPhoto } from '../../components/Thumb'
import { useAuth } from '../../lib/auth'
import { DeadlineBar, SeverityBadge, StatePill, StatusPill, Timeline, TrustMeter } from '../../components/ui'
import { ago, when } from '../../lib/format'

type ReportLike = {
  id: string
  frame_count: number
  frames: { width: number; height: number; boxes: PhotoFrame['boxes'] }[]
  best_frame?: number | null
}

/** All photos of one report with their detected boxes (and the show/hide toggle). */
export function ReportPhotos({ token, report, onChanged, notify }: {
  token: string
  report: ReportLike
  onChanged?: () => void
  notify?: (msg: string, tone?: 'good' | 'bad') => void
}) {
  const { user } = useAuth()
  const [urls, setUrls] = useState<string[]>([])
  useEffect(() => {
    let alive = true
    Promise.all(Array.from({ length: report.frame_count }, (_, i) => loadPhoto(token, report.id, i)))
      .then((list) => alive && setUrls(list))
      .catch(() => alive && setUrls([]))
    return () => {
      alive = false
    }
  }, [token, report.id, report.frame_count])
  if (!urls.length) return <div className="skeleton" style={{ height: 160 }} />
  const frames: PhotoFrame[] = urls.map((url, i) => ({
    url,
    width: report.frames[i]?.width ?? 0,
    height: report.frames[i]?.height ?? 0,
    boxes: report.frames[i]?.boxes ?? [],
  }))
  async function deletePhoto(index: number) {
    if (!window.confirm(`Delete photo ${index + 1} of this report permanently? This frees its storage and cannot be undone.`)) return
    try {
      await admin.deletePhoto(report.id, index)
      forgetPhotos(report.id)
      notify?.('Photo deleted', 'good')
      onChanged?.()
    } catch (e) {
      notify?.(e instanceof Error ? e.message : 'Delete failed', 'bad')
    }
  }
  return (
    <BoxedPhotos
      frames={frames}
      bestFrame={report.best_frame}
      onDelete={user?.role === 'admin' && onChanged ? deletePhoto : undefined}
    />
  )
}

/** Right-hand detail panel: fixed header with title + actions, tabs, independently scrolling body. */
export function Drawer({ title, subtitle, onClose, tabs, tab, setTab, header, children }: {
  title: string
  subtitle?: ReactNode
  onClose: () => void
  tabs: string[]
  tab: string
  setTab: (t: string) => void
  header?: ReactNode
  children: ReactNode
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={title}>
        <header className="drawer-head">
          <div className="drawer-title-row">
            <div>
              <h2 className="drawer-title">{title}</h2>
              {subtitle && <div className="drawer-sub">{subtitle}</div>}
            </div>
            <button className="icon-btn" onClick={onClose} aria-label="Close (Esc)" title="Close (Esc)">×</button>
          </div>
          {header}
          <nav className="drawer-tabs" role="tablist">
            {tabs.map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
                {t}
              </button>
            ))}
          </nav>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  )
}

const ACTIONS: { action: StatusAction; label: string; from: string[]; kind: string }[] = [
  { action: 'acknowledge', label: 'Acknowledge', from: ['open', 'escalated', 'reopened'], kind: '' },
  { action: 'claim_fixed', label: 'Mark fixed', from: ['open', 'acknowledged', 'escalated', 'reopened'], kind: 'primary' },
  { action: 'dismiss', label: 'Dismiss as fake', from: ['unverified', 'open'], kind: 'danger' },
]

export function IssueDrawer({ token, id, onClose, onChanged, onOpenReport, notify }: {
  token: string
  id: string
  onClose: () => void
  onChanged: () => void
  onOpenReport: (reportId: string) => void
  notify: (msg: string, tone?: 'good' | 'bad') => void
}) {
  const [item, setItem] = useState<AuthorityIssue | null>(null)
  const [tab, setTab] = useState('Overview')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    authority.item(token, id).then(setItem).catch((e: Error) => notify(e.message, 'bad'))
  }, [token, id, notify])
  useEffect(load, [load])

  async function run(action: StatusAction, label: string) {
    setBusy(true)
    try {
      await authority.act(token, id, action, note || null)
      setNote('')
      notify(`${label}: done`, 'good')
      load()
      onChanged()
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Action failed', 'bad')
    } finally {
      setBusy(false)
    }
  }

  const where = item?.ward_name ? `Ward ${item.ward_no} ${item.ward_name}` : 'Outside GBA wards'
  const available = item ? ACTIONS.filter((a) => a.from.includes(item.status)) : []

  return (
    <Drawer
      title={item ? `Pothole · ${where}` : 'Loading…'}
      subtitle={item && <>{item.corporation ? `${item.corporation} City Corporation · ` : ''}opened {ago(item.opened_at)}</>}
      onClose={onClose}
      tabs={['Overview', `Photos${item ? ` (${item.reports.length})` : ''}`, 'History']}
      tab={tab.startsWith('Photos') ? `Photos${item ? ` (${item.reports.length})` : ''}` : tab}
      setTab={(t) => setTab(t.startsWith('Photos') ? 'Photos' : t)}
      header={item && (
        <div className="drawer-pills">
          <StatusPill status={item.status} />
          <SeverityBadge severity={item.severity} />
          {item.overdue && <span className="pill pill-bad">Overdue</span>}
          {item.escalation_level > 0 && <span className="pill">Escalation level {item.escalation_level}</span>}
        </div>
      )}
    >
      {!item ? (
        <div className="skeleton" style={{ height: 240 }} />
      ) : tab === 'Overview' ? (
        <>
          <section className="panel">
            <h3>Take action</h3>
            {available.length === 0 ? (
              <p className="muted">No actions available while the issue is {item.status.replace('_', ' ')}.</p>
            ) : (
              <>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Note for the record (required to dismiss), e.g. crew assigned, patched with cold mix"
                  rows={2}
                />
                <div className="row">
                  {available.map((a) => (
                    <button key={a.action} className={a.kind} disabled={busy} onClick={() => run(a.action, a.label)}>
                      {a.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </section>

          <section className="panel facts">
            <div><span>Deadline</span><DeadlineBar opened={item.opened_at} due={item.due_at} overdue={item.overdue} /></div>
            <div><span>Responsible office</span><strong>{item.authority_name ?? 'None assigned'}</strong></div>
            <div><span>Reports</span><strong>{item.report_count}</strong></div>
            <div><span>Opened</span><strong>{when(item.opened_at)}</strong></div>
            <div>
              <span>Location</span>
              <a href={`https://www.openstreetmap.org/?mlat=${item.lat}&mlon=${item.lng}#map=19/${item.lat}/${item.lng}`} target="_blank" rel="noreferrer">
                {item.lat.toFixed(5)}, {item.lng.toFixed(5)} ↗
              </a>
            </div>
          </section>

          <section className="panel">
            <h3>Reports</h3>
            <ul className="mini-list">
              {[...item.reports].reverse().map((r) => (
                <li key={r.id} onClick={() => onOpenReport(r.id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpenReport(r.id)}>
                  <StatePill state={r.state} />
                  <TrustMeter score={r.trust_score} />
                  <span className="muted">{r.capture_source} · …{r.device_hint}</span>
                  <span className="muted mini-time">{ago(r.received_at)}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : tab === 'Photos' ? (
        [...item.reports].reverse().map((r) => (
          <section key={r.id} className="panel">
            <div className="panel-head">
              <StatePill state={r.state} />
              <TrustMeter score={r.trust_score} />
              <span className="muted">{when(r.received_at)}</span>
              <button className="link-btn" onClick={() => onOpenReport(r.id)}>Report details →</button>
            </div>
            <ReportPhotos token={token} report={r} notify={notify} onChanged={() => { load(); onChanged() }} />
          </section>
        ))
      ) : (
        <Timeline events={item.events} />
      )}
    </Drawer>
  )
}

export function ReportDrawer({ token, id, onClose, onOpenIssue, onChanged, notify }: {
  token: string
  id: string
  onClose: () => void
  onOpenIssue: (issueId: string) => void
  onChanged?: () => void
  notify: (msg: string, tone?: 'good' | 'bad') => void
}) {
  const { user } = useAuth()
  const [r, setR] = useState<ReportDetail | null>(null)
  const [tab, setTab] = useState('Photos')
  const load = useCallback(() => {
    authority.report(token, id).then(setR).catch((e: Error) => notify(e.message, 'bad'))
  }, [token, id, notify])
  useEffect(() => {
    setR(null)
    load()
  }, [load])

  async function deleteReport() {
    if (!window.confirm('Delete this whole report and all its photos permanently? If it is the only report of its pothole, the pothole is removed too.')) return
    try {
      const res = await admin.deleteReport(id)
      forgetPhotos(id)
      notify(res.issue_deleted ? 'Report and its pothole deleted' : 'Report deleted', 'good')
      onChanged?.()
      onClose()
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Delete failed', 'bad')
    }
  }

  const repair = r?.repair_check as { outcome?: string; detail?: string } | null | undefined
  return (
    <Drawer
      title={r ? `Report · ${r.ward_name ?? 'outside GBA wards'}` : 'Loading…'}
      subtitle={r && <>{when(r.received_at)} · {r.capture_source === 'camera' ? 'live camera' : 'gallery upload'} · device …{r.device_hint}</>}
      onClose={onClose}
      tabs={['Photos', 'Analysis']}
      tab={tab}
      setTab={setTab}
      header={r && (
        <div className="drawer-pills">
          <StatePill state={r.state} />
          <TrustMeter score={r.trust_score} />
          <SeverityBadge severity={r.severity} />
          {r.issue_id && (
            <button className="link-btn" onClick={() => onOpenIssue(r.issue_id!)}>
              Open issue ({r.issue_status?.replace('_', ' ')}) →
            </button>
          )}
          {user?.role === 'admin' && (
            <button className="small-btn danger" onClick={deleteReport}>🗑 Delete report</button>
          )}
        </div>
      )}
    >
      {!r ? (
        <div className="skeleton" style={{ height: 240 }} />
      ) : tab === 'Photos' ? (
        <section className="panel">
          <ReportPhotos token={token} report={r} notify={notify}
                        onChanged={() => { load(); onChanged?.() }} />
        </section>
      ) : (
        <>
          {r.reject_reason && (
            <section className="panel callout bad">
              <h3>Rejected</h3>
              <p>{r.reject_reason}</p>
            </section>
          )}
          {repair?.outcome && (
            <section className={`panel callout ${repair.outcome === 'verified_fixed' ? 'good' : repair.outcome === 'reopened' ? 'bad' : 'warn'}`}>
              <h3>Repair check: {repair.outcome.replace('_', ' ')}</h3>
              <p>{repair.detail}</p>
            </section>
          )}
          <section className="panel">
            <h3>Trust checks</h3>
            {r.reasons.length === 0 ? (
              <p className="good">All anti-spoofing checks passed.</p>
            ) : (
              <ul className="reasons">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
            )}
          </section>
          <section className="panel">
            <h3>Detection</h3>
            {r.severity_reasons.length ? (
              <ul className="reasons">{r.severity_reasons.map((x) => <li key={x}>{x}</li>)}</ul>
            ) : (
              <p className="muted">No detection result stored.</p>
            )}
          </section>
          <section className="panel facts">
            <div><span>Routed to</span><strong>{r.authority_name ?? 'No office'}</strong></div>
            <div><span>Corporation</span><strong>{r.corporation ?? '—'}</strong></div>
            <div>
              <span>Location</span>
              <a href={`https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lng}#map=19/${r.lat}/${r.lng}`} target="_blank" rel="noreferrer">
                {r.lat.toFixed(5)}, {r.lng.toFixed(5)} ↗
              </a>
            </div>
          </section>
        </>
      )}
    </Drawer>
  )
}
