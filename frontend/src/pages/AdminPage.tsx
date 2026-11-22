import { useCallback, useEffect, useState } from 'react'
import { admin, type Office, type User } from '../api/client'
import { useAuth } from '../lib/auth'
import { ago } from '../lib/format'

type Toast = { msg: string; tone: 'good' | 'bad' } | null

function OfficePicker({ value, onChange }: { value: Office | null; onChange: (o: Office | null) => void }) {
  const [q, setQ] = useState('')
  const [options, setOptions] = useState<Office[]>([])
  useEffect(() => {
    const t = setTimeout(() => admin.offices(q).then(setOptions).catch(() => setOptions([])), 200)
    return () => clearTimeout(t)
  }, [q])
  if (value) {
    return (
      <div className="office-chip">
        <span>{value.name}</span>
        <button type="button" className="link-btn" onClick={() => onChange(null)}>change</button>
      </div>
    )
  }
  return (
    <div className="office-picker">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search office: ward, zone, corporation… (optional)" />
      {q && (
        <ul>
          {options.map((o) => (
            <li key={o.id}>
              <button type="button" onClick={() => onChange(o)}>
                {o.name} <span className="muted small">{o.level}</span>
              </button>
            </li>
          ))}
          {options.length === 0 && <li className="muted small">No match</li>}
        </ul>
      )}
    </div>
  )
}

export default function AdminPage() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[] | null>(null)
  const [toast, setToast] = useState<Toast>(null)
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'officer' as 'officer' | 'admin' })
  const [office, setOffice] = useState<Office | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    admin.users().then(setUsers).catch((e: Error) => setToast({ msg: e.message, tone: 'bad' }))
  }, [])
  useEffect(load, [load])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const u = await admin.create({ ...form, authority_id: office?.id ?? null })
      setToast({ msg: `Created ${u.email}`, tone: 'good' })
      setForm({ name: '', email: '', password: '', role: 'officer' })
      setOffice(null)
      load()
    } catch (err) {
      setToast({ msg: err instanceof Error ? err.message : 'Could not create account', tone: 'bad' })
    } finally {
      setBusy(false)
    }
  }

  async function update(u: User, body: Parameters<typeof admin.update>[1], done: string) {
    try {
      await admin.update(u.id, body)
      setToast({ msg: done, tone: 'good' })
      load()
    } catch (err) {
      setToast({ msg: err instanceof Error ? err.message : 'Update failed', tone: 'bad' })
    }
  }

  function resetPassword(u: User) {
    const pw = window.prompt(`New password for ${u.email} (min 8 characters):`)
    if (pw) update(u, { password: pw }, `Password reset for ${u.email}`)
  }

  return (
    <div className="console">
      <header className="console-head">
        <div>
          <h1>Admin · Staff accounts</h1>
          <p className="muted">Create officer accounts and manage access. Citizens never need an account.</p>
        </div>
      </header>

      <form className="panel admin-form" onSubmit={create}>
        <h3>Add a staff member</h3>
        <div className="admin-grid">
          <label className="field"><span>Name</span>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
          <label className="field"><span>Email</span>
            <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></label>
          <label className="field"><span>Temporary password</span>
            <input type="text" value={form.password} minLength={8} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></label>
          <label className="field"><span>Role</span>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as 'officer' | 'admin' })}>
              <option value="officer">Officer: review and update potholes</option>
              <option value="admin">Admin: also manage accounts and escalation</option>
            </select></label>
          <div className="field wide"><span>Office</span><OfficePicker value={office} onChange={setOffice} /></div>
        </div>
        <button className="primary" type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
      </form>

      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr><th>Name</th><th>Role</th><th>Office</th><th>Last sign-in</th><th>Status</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {!users && <tr><td colSpan={6}><div className="skeleton" style={{ height: 40 }} /></td></tr>}
            {users?.map((u) => (
              <tr key={u.id} style={{ cursor: 'default' }}>
                <td><div className="cell-main">{u.name}</div><div className="muted cell-sub">{u.email}</div></td>
                <td><span className={`pill ${u.role === 'admin' ? 'pill-warn' : ''}`}>{u.role}</span></td>
                <td>{u.authority_name ?? <span className="muted">—</span>}</td>
                <td>{u.last_login ? ago(u.last_login) : <span className="muted">never</span>}</td>
                <td><span className={`pill ${u.active ? 'pill-good' : 'pill-bad'}`}>{u.active ? 'Active' : 'Disabled'}</span></td>
                <td>
                  <div className="row" style={{ margin: 0 }}>
                    <button className="small-btn" onClick={() => resetPassword(u)}>Reset password</button>
                    {u.id !== me?.id && (
                      <button className={`small-btn ${u.active ? 'danger' : ''}`}
                              onClick={() => update(u, { active: !u.active }, `${u.email} ${u.active ? 'disabled' : 'enabled'}`)}>
                        {u.active ? 'Disable' : 'Enable'}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {toast && <div className={`toast ${toast.tone}`} role="status">{toast.msg}</div>}
    </div>
  )
}
