import { useCallback, useEffect, useState } from 'react'
import { api, type Stats } from '../api/client'
import { STATUS_LABEL, when } from '../lib/format'

type Bar = { label: string; value: number; note?: string }

/** Single-series horizontal bar chart: no legend (the title names it), value labels, hover titles. */
function BarChart({ title, unit, bars }: { title: string; unit: string; bars: Bar[] }) {
  const max = Math.max(1, ...bars.map((b) => b.value))
  return (
    <section className="card viz">
      <h3>{title}</h3>
      {bars.length === 0 ? (
        <p className="muted">Nothing yet.</p>
      ) : (
        <div role="list">
          {bars.map((b) => (
            <div key={b.label} className="bar-row" role="listitem" title={`${b.label}: ${b.value} ${unit}${b.note ? ` (${b.note})` : ''}`}>
              <span className="bar-label">{b.label}</span>
              <span className="bar-track">
                <span className="bar-fill" style={{ width: `${(b.value / max) * 100}%` }} />
              </span>
              <span className="bar-value">
                {b.value}
                {b.note && <span className="muted"> · {b.note}</span>}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Tile({ label, value, hint, tone }: { label: string; value: number | string; hint?: string; tone?: 'good' | 'bad' | 'warn' }) {
  return (
    <div className="tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">
        {tone && <span className={`tone-dot ${tone}`} aria-hidden="true" />}
        {label}
      </div>
      {hint && <div className="muted tile-hint">{hint}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.stats().then(setStats).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  if (error) return <div className="page bad">{error}</div>
  if (!stats) return <div className="page muted">Loading...</div>

  return (
    <div className="page" style={{ maxWidth: 1000 }}>
      <h1 style={{ margin: "6px 0 4px" }}>Public dashboard</h1>
      <p className="muted">
        Bengaluru (GBA wards) · updated {when(stats.generated_at)}{' '}
        <button onClick={load} style={{ padding: '2px 10px', marginLeft: 8 }}>Refresh</button>
      </p>

      <div className="tiles">
        <Tile label="Reports received" value={stats.reports_total} />
        <Tile label="Open potholes" value={stats.open_issues} hint={`${stats.overdue_issues} past deadline now`} />
        <Tile label="Escalated (missed a deadline)" value={stats.escalated_issues} tone="warn" />
        <Tile label="Fake reports blocked" value={stats.fakes_blocked} hint={`${stats.held_for_confirmation} more held for confirmation`} tone="bad" />
        <Tile label="Repairs verified by citizens" value={stats.verified_fixed}
              hint={stats.median_days_to_verified_fix != null ? `median ${stats.median_days_to_verified_fix} days` : undefined} tone="good" />
        <Tile label="Falsely closed (reopened)" value={stats.falsely_closed} tone="bad" />
      </div>

      <div className="viz-grid">
        <BarChart
          title="Open potholes by city corporation"
          unit="open"
          bars={stats.by_corporation.map((c) => ({
            label: c.corporation,
            value: c.open,
            note: c.overdue ? `${c.overdue} overdue` : undefined,
          }))}
        />
        <BarChart
          title="Why reports were blocked or held"
          unit="reports"
          bars={stats.blocked_reasons.map((r) => ({ label: r.key, value: r.count }))}
        />
        <BarChart
          title="Potholes by status"
          unit="potholes"
          bars={stats.issues_by_status.map((s) => ({ label: STATUS_LABEL[s.key] ?? s.key, value: s.count }))}
        />
        <section className="card viz wide">
          <h3>Wards with the most open potholes</h3>
          {stats.top_wards.length === 0 ? (
            <p className="muted">No open potholes.</p>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Ward</th>
                  <th>Corporation</th>
                  <th>Open</th>
                  <th>Overdue</th>
                </tr>
              </thead>
              <tbody>
                {stats.top_wards.map((w) => (
                  <tr key={`${w.corporation}-${w.ward_no}`}>
                    <td>{w.ward_no} {w.ward_name}</td>
                    <td>{w.corporation}</td>
                    <td>{w.open}</td>
                    <td>{w.overdue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
      <p className="muted">
        No photos, device ids or personal details are published. Fake-report checks reduce abuse; they cannot remove it.
      </p>
    </div>
  )
}
