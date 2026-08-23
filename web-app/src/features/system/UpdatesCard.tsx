import { useEffect, useState } from 'react'
import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import { formatBytes } from '../../format'
import { IRefresh, IShield } from '../../icons'
import { Button, Select, Toggle } from '../../ui/controls'
import { confirm, toast, toastError } from '../../ui/feedback'
import { Card, Chip, Row } from '../../ui/primitives'

const INTERVAL_OPTS = [
  { value: 3600, label: 'Hourly' },
  { value: 86400, label: 'Daily' },
  { value: 604800, label: 'Weekly' },
  { value: 2592000, label: 'Monthly' },
]

export default function UpdatesCard() {
  const status = usePoll('update-status', api.updateStatus, 10000)
  const settings = usePoll('update-settings', api.updateSettings, 30000)
  const [checking, setChecking] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [settingsBusy, setSettingsBusy] = useState(false)
  const data = status.data
  const auto = settings.data
  const check = data?.last_check?.result ?? null
  const install = data?.last_install ?? null
  const busy = data?.busy ?? false

  // While an install runs, watch closely; when it finishes, the agent is
  // about to restart — reload the dashboard like the restart-agent flow.
  useEffect(() => {
    if (busy) {
      setInstalling(true)
      return
    }
    if (installing && !busy && install?.finished) {
      setInstalling(false)
      if (install.ok) {
        toast(`Update installed: ${install.message}`)
        setTimeout(() => window.location.reload(), 4000)
      } else {
        toastError(install.message ?? 'Update failed', 'Update failed')
      }
    }
  }, [busy, install, installing])

  async function handleCheck() {
    setChecking(true)
    try {
      const result = await api.updateCheck()
      status.refresh()
      if (result.update_available) {
        toast(`Update available: ${result.latest_version}`)
      } else if (result.same_version) {
        toast(`Up to date (${result.current_version}); reinstall available`)
      } else {
        toast('No newer release published')
      }
    } catch (e) {
      toastError(e, 'Update check failed')
    } finally {
      setChecking(false)
    }
  }

  async function handleInstall(allowSame: boolean, version: string) {
    const ok = await confirm({
      title: `Install ${version} from GitHub?`,
      body:
        'The release package is downloaded, sha256-verified and applied as root. ' +
        'The agent restarts at the end; the previous agent is kept as .prev.',
      confirmLabel: 'Install',
      danger: true,
    })
    if (!ok) return
    setInstalling(true)
    try {
      await api.updateInstall(allowSame)
      status.refresh()
    } catch (e) {
      setInstalling(false)
      toastError(e, 'Failed to start update')
    }
  }

  async function setAuto(enabled?: boolean, interval_secs?: number) {
    setSettingsBusy(true)
    try {
      await api.updateSettingsSet({ enabled, interval_secs })
      settings.refresh()
    } catch (e) {
      toastError(e, 'Failed to save update settings')
    } finally {
      setSettingsBusy(false)
    }
  }

  const offer = check && (check.update_available || check.same_version) ? check : null

  return (
    <Card
      title="Updates"
      action={
        <Button size="sm" variant="outline" onClick={handleCheck} loading={checking || busy}>
          <IRefresh size={13} /> Check for updates
        </Button>
      }
    >
      <Row label="Installed" value={data?.current_version ?? '\u2014'} mono />
      <Row label="Source" value={data?.repo ?? '\u2014'} mono wrap />
      {data?.last_check && (
        <Row
          label="Last check"
          value={new Date(data.last_check.ts * 1000).toLocaleString()}
        />
      )}
      {install?.finished != null && (
        <Row
          label="Last update applied"
          value={new Date(install.finished * 1000).toLocaleString()}
        />
      )}

      {busy && (
        <p className="mt-2 animate-pulse text-[13px] font-medium text-warn">
          Installing update… {(install?.steps ?? []).join(' → ')}
        </p>
      )}
      {!busy && install?.finished && (
        <p className={`mt-2 text-[13px] font-medium ${install.ok ? 'text-ok' : 'text-danger'}`}>
          Last install: {install.message}
        </p>
      )}
      {!busy && data?.error && !install?.finished && (
        <p className="mt-2 text-[13px] font-medium text-danger">{data.error}</p>
      )}

      {offer && !busy && (
        <div className="mt-3 rounded-lg border border-accent/25 bg-accent/8 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="accent">
              <IShield size={12} /> {offer.latest_version}
            </Chip>
            <span className="text-[13px] font-semibold text-ink">{offer.name}</span>
            {offer.published_at && (
              <span className="text-[11px] text-ink3">
                {new Date(offer.published_at).toLocaleString()}
              </span>
            )}
            {offer.size != null && (
              <span className="text-[11px] text-ink3">{formatBytes(offer.size)}</span>
            )}
          </div>
          {offer.notes && (
            <p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-[12px] text-ink2">
              {offer.notes}
            </p>
          )}
          <div className="mt-3">
            <Button
              variant="primary"
              onClick={() => handleInstall(offer.same_version, offer.latest_version)}
            >
              {offer.update_available ? `Update to ${offer.latest_version}` : 'Reinstall'}
            </Button>
          </div>
        </div>
      )}

      <div className="mt-4 space-y-3 border-t border-line/8 pt-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[13px] font-semibold text-ink">Automatic checks</p>
            <p className="text-[12px] text-ink2">
              The agent checks GitHub for new releases on a schedule. Installing
              always stays manual.
            </p>
          </div>
          <Toggle
            checked={auto?.enabled ?? true}
            disabled={settingsBusy}
            onChange={(next) => setAuto(next, undefined)}
            label="Automatic update checks"
          />
        </div>
        <div className="flex items-center justify-between gap-3">
          <p className="text-[13px] font-medium text-ink2">Check interval</p>
          <div className="w-32">
            <Select
              value={String(auto?.interval_secs ?? 604800)}
              disabled={settingsBusy || !(auto?.enabled ?? true)}
              onChange={(e) => setAuto(undefined, Number(e.target.value))}
              aria-label="Update check interval"
            >
              {INTERVAL_OPTS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </div>
    </Card>
  )
}
