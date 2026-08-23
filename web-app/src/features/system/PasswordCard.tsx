import { useState } from 'react'
import { api } from '../../data/api'
import { ILock } from '../../icons'
import { Button, Field, Input } from '../../ui/controls'
import { toast } from '../../ui/feedback'
import { Card } from '../../ui/primitives'

export default function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const mismatch = confirmPw.length > 0 && next !== confirmPw

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (next.length < 8) {
      setError('New password must be at least 8 characters.')
      return
    }
    if (next !== confirmPw) {
      setError('New passwords do not match.')
      return
    }
    setBusy(true)
    try {
      await api.changePassword(current, next)
      toast('Dashboard password changed')
      setCurrent('')
      setNext('')
      setConfirmPw('')
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : 'Password change failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Dashboard password">
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Current">
            <Input
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          <Field label="New" hint="At least 8 characters">
            <Input
              type="password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>
          <Field label="Repeat new">
            <Input
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>
        </div>
        {error && <p className="text-xs font-medium text-danger">{error}</p>}
        {mismatch && !error && (
          <p className="text-xs font-medium text-warn">New passwords do not match yet.</p>
        )}
        <Button type="submit" variant="primary" loading={busy} disabled={!current || !next || mismatch}>
          <ILock size={14} /> Change password
        </Button>
        <p className="text-[12px] text-ink3">
          Changing the password signs out every other dashboard session. The root
          write token is unaffected.
        </p>
      </form>
    </Card>
  )
}
