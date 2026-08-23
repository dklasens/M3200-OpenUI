import { useState } from 'react'
import { login, setToken } from '../data/client'
import { ILogo } from '../icons'
import { Button } from '../ui/controls'

export default function Login({ onAuthed }: { onAuthed: () => void }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      const { token } = await login(pw)
      setToken(token)
      onAuthed()
    } catch (error) {
      setErr(error instanceof Error ? error.message : 'Sign in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-bg p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-accent text-white">
            <ILogo size={26} strokeWidth={2.1} />
          </div>
          <h1 className="text-lg font-bold text-ink">Inseego M3200</h1>
          <p className="mt-0.5 text-[13px] text-ink2">Sign in to the dashboard</p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-xl border border-line/8 bg-surface p-5"
        >
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            className="h-11 w-full rounded-lg border border-line/12 bg-surface2/50 px-3.5 text-sm text-ink outline-none transition-colors placeholder:text-ink3 focus:border-accent/60"
            placeholder="Agent password"
            autoFocus
            autoComplete="current-password"
            aria-label="Agent password"
          />

          {err && <p className="text-xs font-medium text-danger">{err}</p>}

          <Button type="submit" variant="primary" loading={busy} disabled={pw.length === 0} className="w-full !h-11">
            Sign in
          </Button>
        </form>
      </div>
    </div>
  )
}
