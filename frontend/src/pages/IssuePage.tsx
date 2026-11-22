import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type IssueDetail } from '../api/client'
import { DeadlineBar, SeverityBadge, StatusPill, Timeline } from '../components/ui'
import { ago, STATUS_LABEL, when } from '../lib/format'

function complaintEmail(issue: IssueDetail): string {
  const where = issue.ward_name ? `Ward ${issue.ward_no} ${issue.ward_name}, ${issue.corporation} City Corporation` : 'Bengaluru'
  const subject = `Pothole complaint: ${where}`
  const body = [
    'Dear Sir/Madam,',
    '',
    `A pothole has been reported at ${issue.lat.toFixed(6)}, ${issue.lng.toFixed(6)} (${where}).`,
    `Severity estimate: ${issue.severity ?? 'not scored'}. Independent reports: ${issue.report_count}.`,
    `Map: https://www.openstreetmap.org/?mlat=${issue.lat}&mlon=${issue.lng}#map=19/${issue.lat}/${issue.lng}`,
    `Responsible office (from GBA ward boundaries): ${issue.authority_name ?? 'unknown'}.`,
    '',
    'Please inspect and repair it.',
    '',
    'Thank you.',
  ].join('\n')
  // No recipient is filled in: officer emails are added only when officially published.
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}

/** Where the issue is on the road to a verified repair. */
const STAGES = [
  { key: 'reported', label: 'Reported' },
  { key: 'acknowledged', label: 'Acknowledged' },
  { key: 'fixed', label: 'Marked fixed' },
  { key: 'verified', label: 'Verified by citizens' },
]
function stageOf(status: string): number {
  if (status === 'verified_fixed') return 3
  if (status === 'claimed_fixed') return 2
  if (status === 'acknowledged') return 1
  return 0
}

export default function IssuePage() {
  const { id = '' } = useParams()
  const [issue, setIssue] = useState<IssueDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.issue(id).then(setIssue).catch((e: Error) => setError(e.message))
  }, [id])

  if (error) return <div className="page"><div className="panel callout bad"><h3>Could not load this pothole</h3><p>{error}</p></div></div>
  if (!issue) return <div className="page"><div className="skeleton" style={{ height: 320 }} /></div>

  const stage = stageOf(issue.status)
  const special = ['reopened', 'escalated', 'dismissed', 'unverified'].includes(issue.status)
  const where = issue.ward_name ? `Ward ${issue.ward_no} · ${issue.ward_name}` : 'Outside GBA wards'

  async function share() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked: the address bar still has the link */
    }
  }

  return (
    <div className="issue">
      <header className="issue-hero">
        <div className="issue-pills">
          <StatusPill status={issue.status} />
          <SeverityBadge severity={issue.severity} />
          {issue.overdue && <span className="pill pill-bad">Overdue</span>}
        </div>
        <h1>Pothole in {where}</h1>
        <p className="muted">
          {issue.corporation ? `${issue.corporation} City Corporation · ` : ''}reported {ago(issue.opened_at)} · {issue.report_count}{' '}
          {issue.report_count === 1 ? 'report' : 'reports'}
        </p>
      </header>

      <section className="panel">
        <ol className="tracker" aria-label="Repair progress">
          {STAGES.map((s, i) => (
            <li key={s.key} className={i < stage ? 'done' : i === stage ? 'current' : ''}>
              <span className="tracker-dot">{i < stage ? '✓' : i + 1}</span>
              <span>{s.label}</span>
            </li>
          ))}
        </ol>
        {special && (
          <p className={`tracker-note ${issue.status === 'reopened' || issue.status === 'escalated' ? 'bad' : 'muted'}`}>
            {issue.status === 'reopened' && 'A citizen photo after the "fixed" claim still showed the pothole, so it was reopened.'}
            {issue.status === 'escalated' && `The deadline was missed, so it moved up to ${issue.authority_name ?? 'a higher office'}.`}
            {issue.status === 'dismissed' && 'The office dismissed this report.'}
            {issue.status === 'unverified' && 'Waiting for a second person to report the same pothole.'}
          </p>
        )}
      </section>

      <section className="panel facts">
        <div><span>Responsible office</span><strong>{issue.authority_name ?? 'None assigned'}</strong></div>
        <div><span>Deadline</span><DeadlineBar opened={issue.opened_at} due={issue.due_at} overdue={issue.overdue} /></div>
        <div><span>Escalation level</span><strong>{issue.escalation_level === 0 ? 'Ward office' : `Level ${issue.escalation_level}`}</strong></div>
        <div><span>First reported</span><strong>{when(issue.opened_at)}</strong></div>
      </section>

      <div className="issue-actions">
        <Link className="btn primary" to={`/map?focus=${issue.id}`}>🗺️ Show on map</Link>
        <a className="btn" href={complaintEmail(issue)}>✉️ Draft complaint email</a>
        <button onClick={share}>{copied ? '✓ Link copied' : '🔗 Copy link'}</button>
      </div>

      <section className="panel">
        <h3>History</h3>
        <Timeline events={issue.events} />
      </section>

      <p className="muted small">
        Current status: {STATUS_LABEL[issue.status] ?? issue.status}. Photos are shared only with the responsible office, never published.
      </p>
    </div>
  )
}
