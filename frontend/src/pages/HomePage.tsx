import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Stats } from '../api/client'
import { useAuth } from '../lib/auth'

const STEPS = [
  { icon: '📷', title: 'Snap', text: 'Open the app, point at the pothole, tap once. Three quick frames and your GPS. No account.' },
  { icon: '🛡️', title: 'Verify', text: 'Every photo is checked: reused images, photos of screens, fake GPS and frames that do not match.' },
  { icon: '🔎', title: 'Detect', text: 'Our own AI model finds the pothole on the photo and estimates how severe it is, on a plain CPU.' },
  { icon: '🏛️', title: 'Route', text: 'The location is matched to one of 369 GBA wards and sent to that ward office with a deadline.' },
  { icon: '⏫', title: 'Escalate', text: 'Missed the deadline? It moves up: ward → zone → city corporation → GBA, automatically.' },
  { icon: '✅', title: 'Prove', text: 'Marked fixed? A later citizen photo confirms the repair, or reopens it as "falsely closed".' },
]

const CHECKS = [
  ['Reused photo', 'Perceptual hash spots the same image, even resized or recompressed.'],
  ['Photo of a screen', 'Moiré patterns in the frequency spectrum reveal a re-photographed screen.'],
  ['Live capture', 'Three frames must show one real scene with natural camera shake.'],
  ['Location', 'GPS accuracy, impossible travel, and the GBA boundary are all checked.'],
  ['Corroboration', 'Uncertain reports wait until a second, independent person reports the same spot.'],
  ['Rate limits', 'Per device and per network, so nobody can flood the system.'],
]

const PROFILES = [
  {
    icon: '🙋', title: 'Citizen', tag: 'No sign-in',
    can: ['Report a pothole with the camera or a photo', 'Track its status, deadline and history', 'Explore the public map and dashboard'],
    cta: { to: '/report', label: 'Report a pothole' },
  },
  {
    icon: '👷', title: 'Authority officer', tag: 'Staff sign-in',
    can: ['See every report with photos and AI boxes', 'Acknowledge, mark fixed, or dismiss fakes', 'Work from a deadline-sorted queue'],
    cta: { to: '/login?next=/authority', label: 'Officer sign in' },
  },
  {
    icon: '🛠️', title: 'Admin', tag: 'Staff sign-in',
    can: ['Everything an officer can do', 'Create and disable staff accounts', 'Run escalation on demand'],
    cta: { to: '/login?next=/admin', label: 'Admin sign in' },
  },
]

const MODEL_ROWS = [
  ['Lane markings & manholes wrongly flagged', '8.8%', '1.8%'],
  ['Close-up potholes found', '63%', '71%'],
  ['Dashcam potholes found (India)', '31%', '39%'],
]

const DATASETS = [
  ['RDD2022 (India, Japan, Czech, US)', 'Road damage from vehicle-mounted phones', 'CC BY 4.0'],
  ['Annotated Potholes (Kaggle)', 'Close-up pothole photos', 'DbCL-1.0'],
  ['Pothole Detection (Kaggle)', 'Close-up pothole photos', 'CC0-1.0'],
  ['Pothole Segmentation (Kaggle)', 'Pothole outlines → boxes', 'Apache-2.0'],
  ['Road Damage, Rome (Kaggle)', 'Street photos; cracks & manholes as negatives', 'MIT'],
  ['GBA 369 wards (Dec 2025)', 'Routing to the right ward office', 'Public domain'],
]

function fmt(n: number | undefined) {
  return n == null ? '—' : n.toLocaleString('en-IN')
}

export default function HomePage() {
  const { user } = useAuth()
  const [stats, setStats] = useState<Stats | null>(null)
  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats(null))
  }, [])

  return (
    <div className="home">
      <section className="home-hero">
        <div className="home-hero-text">
          <span className="home-kicker">Bengaluru · Civic grievance triage</span>
          <h1>Report a pothole in 10 seconds. <span className="grad">We make sure it gets fixed.</span></h1>
          <p className="home-lead">
            Citizens snap a photo. Our AI checks it is real, finds the pothole, and sends it to the right ward office with a
            deadline. If nothing happens, it escalates, and a later photo proves whether it was really fixed.
          </p>
          <div className="home-cta">
            <Link className="btn primary big" to="/report">📷 Report a pothole</Link>
            <Link className="btn big" to="/map">🗺️ See the live map</Link>
            {user ? (
              <Link className="btn big" to={user.role === 'admin' ? '/admin' : '/authority'}>🏛️ Open console</Link>
            ) : (
              <Link className="btn big ghost" to="/login?next=/authority">🏛️ Authority sign in</Link>
            )}
          </div>
          <p className="muted small">No account needed to report. Photos are shared only with the responsible office.</p>
        </div>
        <div className="home-stats" aria-label="Live numbers">
          <div><strong>{fmt(stats?.reports_total)}</strong><span>reports received</span></div>
          <div><strong>{fmt(stats?.open_issues)}</strong><span>open potholes tracked</span></div>
          <div><strong>{fmt(stats?.fakes_blocked)}</strong><span>fake reports blocked</span></div>
          <div><strong>369</strong><span>GBA wards covered</span></div>
        </div>
      </section>

      <section className="home-section">
        <h2>How it works</h2>
        <div className="home-steps">
          {STEPS.map((s, i) => (
            <div key={s.title} className="home-step">
              <div className="home-step-num">{i + 1}</div>
              <div className="home-step-icon" aria-hidden="true">{s.icon}</div>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="home-section">
        <h2>Who it's for</h2>
        <div className="home-profiles">
          {PROFILES.map((p) => (
            <div key={p.title} className="home-profile">
              <div className="home-profile-head">
                <span className="home-profile-icon" aria-hidden="true">{p.icon}</span>
                <div><h3>{p.title}</h3><span className="pill">{p.tag}</span></div>
              </div>
              <ul>{p.can.map((c) => <li key={c}>{c}</li>)}</ul>
              <Link className="btn" to={p.cta.to}>{p.cta.label} →</Link>
            </div>
          ))}
        </div>
      </section>

      <section className="home-section home-split">
        <div>
          <h2>Our pothole model</h2>
          <p className="muted">
            A YOLO11s detector we trained ourselves on 11,709 road images, including 5,410 tricky "no pothole" photos
            (lane paint, manholes, cracks) so it stops mistaking road markings for damage. It runs on an ordinary CPU in about
            0.1 s per photo: no paid AI API.
          </p>
          <table className="data home-table">
            <thead><tr><th>Held-out test</th><th>Before retraining</th><th>Now</th></tr></thead>
            <tbody>
              {MODEL_ROWS.map(([k, a, b]) => (
                <tr key={k}><td>{k}</td><td>{a}</td><td><strong>{b}</strong></td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Validation: precision 0.72, recall 0.61, mAP50 0.685. A report is accepted only when the model is confident across
            all three frames; uncertain ones wait for a second report.
          </p>
        </div>
        <div>
          <h2>Data we use</h2>
          <table className="data home-table">
            <thead><tr><th>Dataset</th><th>Used for</th><th>Licence</th></tr></thead>
            <tbody>
              {DATASETS.map(([n, u, l]) => <tr key={n}><td>{n}</td><td>{u}</td><td>{l}</td></tr>)}
            </tbody>
          </table>
        </div>
      </section>

      <section className="home-section">
        <h2>Built to resist fake reports</h2>
        <div className="home-checks">
          {CHECKS.map(([t, d]) => (
            <div key={t} className="home-check"><strong>✓ {t}</strong><p>{d}</p></div>
          ))}
        </div>
        <p className="muted small">These checks reduce abuse; no system can remove it entirely, so every decision is logged with its reasons.</p>
      </section>

      <section className="home-band">
        <div>
          <h2>Seen a pothole today?</h2>
          <p>It takes ten seconds, and you can follow it until it is fixed.</p>
        </div>
        <Link className="btn primary big" to="/report">📷 Report it now</Link>
      </section>

      <footer className="home-foot muted small">
        IDEA//FORGE hackathon · Track 1, Civic Grievance & Infrastructure Triage · Map © OpenStreetMap contributors
      </footer>
    </div>
  )
}
