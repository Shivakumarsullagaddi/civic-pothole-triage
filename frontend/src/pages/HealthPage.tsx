import { useCallback, useEffect, useState } from 'react'
import { api, type Health } from '../api/client'

function Check({ ok, title, detail }: { ok: boolean | null; title: string; detail: string }) {
  const tone = ok === null ? 'muted' : ok ? 'good' : 'bad'
  return (
    <div className="health-card">
      <span className={`health-status ${tone}`} aria-hidden="true">{ok === null ? '…' : ok ? '✓' : '!'}</span>
      <div>
        <div className="health-title">{title}</div>
        <div className="muted small">{detail}</div>
      </div>
      <span className={`pill pill-${tone}`}>{ok === null ? 'Checking' : ok ? 'OK' : 'Problem'}</span>
    </div>
  )
}

export default function HealthPage() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  const check = useCallback(() => {
    setError(null)
    setHealth(null)
    api.health().then(setHealth).catch((e: Error) => setError(`Backend not reachable: ${e.message}`))
  }, [])
  useEffect(check, [check])

  return (
    <div className="page health-page">
      <h1>System status</h1>
      <p className="muted">Everything runs locally on this laptop: API, database and the pothole model.</p>
      <div className="health-list">
        <Check ok={error ? false : health ? true : null} title="Backend API" detail={error ?? (health ? `Status: ${health.status}` : 'Connecting…')} />
        <Check
          ok={health ? health.database.ok : error ? false : null}
          title="Database (PostgreSQL + PostGIS)"
          detail={health ? (health.database.ok ? `Connected · PostGIS ${health.database.postgis}` : `${health.database.error}: ${health.database.detail}`) : '—'}
        />
        <Check
          ok={health ? health.model.loaded : error ? false : null}
          title="Pothole detection model (CPU)"
          detail={health ? (health.model.loaded ? `${health.model.file} · ${health.model.mode} mode` : `Not loaded: ${health.model.error ?? 'unknown'}`) : '—'}
        />
      </div>
      <button onClick={check}>↻ Check again</button>
    </div>
  )
}
