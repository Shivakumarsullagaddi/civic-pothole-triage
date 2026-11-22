import { deadlineUsed, dueText, SEVERITY_LABEL, STATUS_COLORS, STATUS_LABEL, when } from '../lib/format'

/** Status pill: coloured dot + text label (never colour alone). */
export function StatusPill({ status }: { status: string }) {
  return (
    <span className="pill">
      <span className="pill-dot" style={{ background: STATUS_COLORS[status] ?? '#6b7280' }} />
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

const SEVERITY_BARS: Record<string, number> = { low: 1, medium: 2, high: 3, critical: 4 }

/** Severity as a 4-step signal meter plus its name. */
export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  if (!severity) return <span className="sev sev-none">Not scored</span>
  const n = SEVERITY_BARS[severity] ?? 0
  return (
    <span className={`sev sev-${severity}`} title={`Severity: ${SEVERITY_LABEL[severity] ?? severity}`}>
      <span className="sev-bars" aria-hidden="true">
        {[1, 2, 3, 4].map((i) => (
          <i key={i} className={i <= n ? 'on' : ''} style={{ height: 4 + i * 3 }} />
        ))}
      </span>
      {SEVERITY_LABEL[severity] ?? severity}
    </span>
  )
}

const STATE_INFO: Record<string, { label: string; tone: string }> = {
  accepted: { label: 'Accepted', tone: 'good' },
  needs_review: { label: 'Held', tone: 'warn' },
  rejected: { label: 'Rejected', tone: 'bad' },
  no_damage: { label: 'No pothole', tone: 'muted' },
  received: { label: 'Received', tone: 'muted' },
}

export function StatePill({ state }: { state: string }) {
  const s = STATE_INFO[state] ?? { label: state, tone: 'muted' }
  return <span className={`pill pill-${s.tone}`}>{s.label}</span>
}

/** Trust score 0..1 as a short meter with its percentage. */
export function TrustMeter({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="muted">—</span>
  const pct = Math.round(score * 100)
  const tone = score >= 0.7 ? 'good' : score >= 0.4 ? 'warn' : 'bad'
  return (
    <span className="trust" title={`Trust ${pct}%`}>
      <span className="trust-track">
        <span className={`trust-fill ${tone}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="trust-num">{pct}%</span>
    </span>
  )
}

/** How much of the deadline window is used, plus "due in / overdue by". */
export function DeadlineBar({ opened, due, overdue }: { opened: string; due: string | null | undefined; overdue: boolean }) {
  const used = deadlineUsed(opened, due)
  return (
    <span className="deadline" title={due ? `Deadline ${when(due)}` : 'No deadline yet'}>
      <span className={overdue ? 'bad' : used != null && used > 0.75 ? 'warn-text' : undefined}>{dueText(due)}</span>
      {used != null && (
        <span className="deadline-track">
          <span className={`deadline-fill ${overdue ? 'bad' : used > 0.75 ? 'warn' : 'ok'}`} style={{ width: `${used * 100}%` }} />
        </span>
      )}
    </span>
  )
}

export type TimelineEvent = { type: string; to_status?: string | null; note?: string | null; at: string; actor?: string }

const EVENT_LABEL: Record<string, string> = {
  created: 'Reported',
  report_added: 'Another report',
  status_changed: 'Status changed',
  escalated: 'Escalated',
  routed: 'Routed',
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="timeline">
      {[...events].reverse().map((e, i) => (
        <li key={i} className={`tl-${e.type}`}>
          <span className="tl-dot" style={e.to_status ? { background: STATUS_COLORS[e.to_status] } : undefined} />
          <div className="tl-body">
            <div className="tl-head">
              <strong>{EVENT_LABEL[e.type] ?? e.type}</strong>
              {e.to_status && <StatusPill status={e.to_status} />}
              <span className="muted tl-time">{when(e.at)}</span>
            </div>
            {e.note && <div className="tl-note">{e.note}</div>}
            {e.actor && e.actor !== 'system' && <div className="muted tl-actor">by {e.actor}</div>}
          </div>
        </li>
      ))}
    </ol>
  )
}
