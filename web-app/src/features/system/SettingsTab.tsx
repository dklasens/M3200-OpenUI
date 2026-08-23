import { useCallback, useEffect, useState } from 'react'
import { api } from '../../data/api'
import { formatUptime } from '../../format'
import type { DeviceInfo } from '../../types'
import { ILogout, IRefresh, IRestart } from '../../icons'
import { Button } from '../../ui/controls'
import { confirm, toast, toastError } from '../../ui/feedback'
import { Card, Row } from '../../ui/primitives'
import UpdatesCard from './UpdatesCard'
import PasswordCard from './PasswordCard'

export default function SettingsTab({ onLogout }: { onLogout: () => void }) {
  const [device, setDevice] = useState<DeviceInfo | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    const [d] = await Promise.allSettled([api.device()])
    if (d.status === 'fulfilled') setDevice(d.value)
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  async function restartAgent() {
    const ok = await confirm({
      title: 'Restart the OpenUI agent?',
      body: 'The dashboard backend restarts; this page reloads after a few seconds.',
      confirmLabel: 'Restart',
    })
    if (!ok) return
    setBusy('restart')
    try {
      await api.restartAgent()
      toast('Agent restarting — reloading in a few seconds')
      setTimeout(() => window.location.reload(), 5000)
    } catch (e) {
      toastError(e, 'Failed to restart agent')
      setBusy(null)
    }
  }

  async function reboot() {
    const ok = await confirm({
      title: 'Reboot the device?',
      body: 'All connections will drop for about 30-60 seconds. Band preferences written as permanent survive the reboot.',
      confirmLabel: 'Reboot',
      danger: true,
    })
    if (!ok) return
    setBusy('reboot')
    try {
      await api.reboot()
      toast('Reboot command sent')
    } catch (e) {
      toastError(e, 'Failed to reboot device')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card title="Device">
          <Row label="Model" value={device ? `${device.manufacturer ?? ''} ${device.model ?? ''}`.trim() : '\u2014'} />
          <Row label="Firmware" value={device?.firmware_revision ?? '\u2014'} mono wrap />
          <Row label="Hardware" value={device?.hardware_revision ?? '\u2014'} mono wrap />
          <Row label="Uptime" value={formatUptime(device?.uptime_secs)} />
          <Row label="Load" value={device?.load_avg?.map((v) => v.toFixed(2)).join(', ') ?? '\u2014'} mono />
        </Card>

        <Card title="Identifiers / SIM">
          <Row label="IMEI" value={device?.imei ?? '\u2014'} mono />
          <Row label="IMSI" value={device?.imsi ?? '\u2014'} mono />
          <Row label="ICCID" value={device?.iccid ?? '\u2014'} mono />
        </Card>
      </div>

      <UpdatesCard />

      <PasswordCard />

      <Card title="Service controls">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={restartAgent} loading={busy === 'restart'}>
            <IRefresh size={14} /> Restart agent
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              toast('Reloading dashboard…')
              setTimeout(() => window.location.reload(), 400)
            }}
          >
            <IRestart size={14} /> Reload dashboard
          </Button>
          <Button variant="danger" onClick={reboot} loading={busy === 'reboot'}>
            <IRestart size={14} /> Reboot
          </Button>
        </div>
        <p className="mt-2.5 text-[12px] text-ink3">
          Restart agent briefly interrupts the backend. Reboot interrupts all connections.
        </p>
      </Card>

      <Card title="Session">
        <Row label="Dashboard" value={window.location.origin} mono />
        <Row label="Agent" value="same origin, /api/*" mono />
        <div className="mt-3 border-t border-line/8 pt-3">
          <Button variant="ghost" onClick={onLogout}>
            <ILogout size={14} /> Sign out
          </Button>
        </div>
      </Card>
    </div>
  )
}
