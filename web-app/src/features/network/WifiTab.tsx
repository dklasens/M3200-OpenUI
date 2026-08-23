import { useEffect, useState } from 'react'
import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import type { WifiApProfile, WifiApSettings } from '../../types'
import { IAlert, IWifi } from '../../icons'
import { Button, Field, Input, Select, Toggle } from '../../ui/controls'
import { confirm, toast, toastError } from '../../ui/feedback'
import { Card, Chip, Row, Skeleton } from '../../ui/primitives'

const MODES_2G = new Set(['BGN', 'BG', 'B', 'G', 'GN', 'N2', 'ACN2', 'BGNPLUSAX'])
const MODES_5G = new Set(['A', 'N5', 'AN', 'ACN5.', 'AC5ONLY', 'ACNPLUSAX'])

const SECURITY_OPTS = [
  { value: 'wpa3transition', label: 'WPA3 Transition (recommended)' },
  { value: 'wpa3', label: 'WPA3' },
  { value: 'wpa2', label: 'WPA2' },
  { value: 'wpa2mix', label: 'WPA2 Mixed' },
  { value: 'none', label: 'Open (no password)' },
]

function mainProfiles(profiles: WifiApProfile[]) {
  let main2g: WifiApProfile | undefined
  let main5g: WifiApProfile | undefined
  for (const p of profiles) {
    if (p.privacy) continue // guest profiles
    if (!main2g && p.mode && MODES_2G.has(p.mode)) main2g = p
    else if (!main5g && p.mode && MODES_5G.has(p.mode)) main5g = p
  }
  return { main2g, main5g }
}

export default function WifiTab() {
  const wifi = usePoll('wifi', api.wifiStatus, 10000)
  const [busy, setBusy] = useState(false)
  const data = wifi.data

  const [form, setForm] = useState<WifiApSettings | null>(null)
  const [apBusy, setApBusy] = useState(false)

  const enabled = !!data?.enabled
  const { main2g, main5g } = mainProfiles(data?.ap_profiles ?? [])

  // Seed the form from the live profiles whenever they (re)appear.
  useEffect(() => {
    if (!enabled || !main2g || !main5g || form) return
    setForm({
      combined: (main2g.ssid ?? '') === (main5g.ssid ?? ''),
      ssid: main2g.ssid ?? '',
      ssid_2g: main2g.ssid ?? '',
      ssid_5g: main5g.ssid ?? '',
      security: main2g.security ?? 'wpa3transition',
      passphrase: main2g.passphrase ?? '',
      channel_2g: main2g.channel ?? 0,
      channel_5g: main5g.channel ?? 0,
      width_2g: main2g.width_mhz ?? 20,
      width_5g: main5g.width_mhz ?? 80,
      hidden: main2g.hidden ?? false,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, main2g, main5g])

  async function setEnabled(next: boolean) {
    if (!next) {
      const ok = await confirm({
        title: 'Turn off Wi-Fi?',
        body:
          'The access point stops broadcasting and every connected device ' +
          'drops off the network until Wi-Fi is turned back on.',
        confirmLabel: 'Turn off',
        danger: true,
      })
      if (!ok) return
    }
    setBusy(true)
    try {
      const status = await api.wifiSettingsSet(next)
      wifi.mutate(status)
      toast(next ? 'Wi-Fi enabled' : 'Wi-Fi disabled')
    } catch (e) {
      toastError(e, 'Failed to change Wi-Fi')
    } finally {
      setBusy(false)
    }
  }

  async function applyAp() {
    if (!form) return
    const ok = await confirm({
      title: 'Apply Wi-Fi access point settings?',
      body:
        'The access point restarts with the new SSID, security and channel ' +
        'plan; connected devices drop and must rejoin.',
      confirmLabel: 'Apply',
    })
    if (!ok) return
    setApBusy(true)
    try {
      const status = await api.wifiApSet(form)
      wifi.mutate(status)
      setForm(null)
      toast('Access point settings applied')
    } catch (e) {
      toastError(e, 'Failed to apply AP settings')
    } finally {
      setApBusy(false)
    }
  }

  if (!data && !wifi.error) return <Skeleton className="h-64" />
  if (!data) return <p className="text-[13px] text-danger">{wifi.error}</p>
  if (!data.available) {
    return (
      <Card>
        <p className="text-[13px] text-ink3">
          The Wi-Fi daemon did not answer. The agent talks to `wifid` over the message
          bus; check that the stock Wi-Fi stack is running.
        </p>
      </Card>
    )
  }

  const openEnabled = (data.ap_profiles ?? []).find(
    (p) => p.status && p.security === 'none',
  )
  const ch24 = data.channels?.['2.4'] ?? []
  const ch5 = data.channels?.['5'] ?? []

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <Card
        title="Access point"
        action={
          <Toggle checked={enabled} disabled={busy} onChange={setEnabled} label="Wi-Fi switch" />
        }
      >
        <div className="mb-2 flex items-center gap-2">
          <Chip tone={enabled ? 'ok' : 'default'}>
            <IWifi size={12} /> Wi-Fi {enabled ? 'on' : 'off'}
          </Chip>
          <Chip tone={data.feature_enabled ? 'ok' : 'default'}>
            feature {data.feature_enabled ? 'enabled' : 'disabled'}
          </Chip>
          {data.country && <Chip>Region {data.country}</Chip>}
        </div>
        <Row label="Max clients" value={data.max_clients ?? '\u2014'} />
        <Row label="Associated stations" value={data.associated_stations ?? '\u2014'} />
        {openEnabled && (
          <p className="mt-2 flex items-start gap-1.5 text-[12px] text-warn">
            <IAlert size={14} className="mt-0.5 shrink-0" />
            Stock profile {openEnabled.index} (“{openEnabled.ssid}”) is enabled with no
            password. Anyone nearby can join until it is disabled on the device.
          </p>
        )}
        {!enabled && (
          <p className="mt-2 text-[12px] text-ink3">
            Wi-Fi is off. Turn it on to read or change SSID, security and channels —
            the firmware stalls profile queries while the AP is down.
          </p>
        )}
      </Card>

      <Card title="Profiles">
        {(data.ap_profiles ?? []).filter((p) => p.status).length > 0 ? (
          <div className="space-y-2">
            {(data.ap_profiles ?? [])
              .filter((p) => p.status)
              .map((p) => (
                <div key={p.index} className="rounded-lg border border-line/8 bg-surface2/40 px-3 py-2">
                  <p className="text-[13px] font-semibold text-ink">{p.ssid ?? '(hidden)'}</p>
                  <p className="text-[11px] text-ink3">
                    {[
                      MODES_2G.has(p.mode ?? '') ? '2.4 GHz' : MODES_5G.has(p.mode ?? '') ? '5 GHz' : p.mode,
                      p.width_mhz ? `${p.width_mhz} MHz` : null,
                      p.channel ? `ch ${p.channel}` : 'ch auto',
                      p.security,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </div>
              ))}
          </div>
        ) : (
          <p className="text-[13px] text-ink3">No enabled profiles.</p>
        )}
      </Card>

      {enabled && form && (
        <Card title="Access point settings" className="lg:col-span-2">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[13px] font-semibold text-ink">Combined bands</p>
                  <p className="text-[12px] text-ink2">
                    One SSID on 2.4 + 5 GHz; devices pick their own band (steering).
                    Off = separate SSIDs per band.
                  </p>
                </div>
                <Toggle
                  checked={form.combined}
                  onChange={(next) => setForm({ ...form, combined: next })}
                  label="Combined bands"
                />
              </div>

              {form.combined ? (
                <Field label="Wi-Fi name (both bands)">
                  <Input
                    value={form.ssid ?? ''}
                    maxLength={32}
                    onChange={(e) => setForm({ ...form, ssid: e.target.value })}
                  />
                </Field>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  <Field label="2.4 GHz name">
                    <Input
                      value={form.ssid_2g ?? ''}
                      maxLength={32}
                      onChange={(e) => setForm({ ...form, ssid_2g: e.target.value })}
                    />
                  </Field>
                  <Field label="5 GHz name">
                    <Input
                      value={form.ssid_5g ?? ''}
                      maxLength={32}
                      onChange={(e) => setForm({ ...form, ssid_5g: e.target.value })}
                    />
                  </Field>
                </div>
              )}

              <Field label="Security">
                <Select
                  value={form.security}
                  onChange={(e) => setForm({ ...form, security: e.target.value })}
                >
                  {SECURITY_OPTS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              </Field>
              {form.security !== 'none' && (
                <Field label="Passphrase" hint="8-63 characters, no spaces (firmware limit)">
                  <Input
                    type="text"
                    value={form.passphrase ?? ''}
                    maxLength={63}
                    onChange={(e) => setForm({ ...form, passphrase: e.target.value })}
                  />
                </Field>
              )}

              <div className="flex items-center justify-between gap-3">
                <p className="text-[13px] font-medium text-ink2">Hide SSID</p>
                <Toggle
                  checked={form.hidden ?? false}
                  onChange={(next) => setForm({ ...form, hidden: next })}
                  label="Hide SSID"
                />
              </div>
            </div>

            <div className="space-y-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-ink2">2.4 GHz</p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Channel">
                  <Select
                    value={String(form.channel_2g ?? 0)}
                    onChange={(e) => setForm({ ...form, channel_2g: Number(e.target.value) })}
                  >
                    <option value="0">Auto</option>
                    {ch24.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Width">
                  <Select
                    value={String(form.width_2g ?? 20)}
                    onChange={(e) => setForm({ ...form, width_2g: Number(e.target.value) })}
                  >
                    <option value="20">20 MHz</option>
                    <option value="40">40 MHz</option>
                  </Select>
                </Field>
              </div>

              <p className="text-[11px] font-bold uppercase tracking-wider text-ink2">5 GHz</p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Channel">
                  <Select
                    value={String(form.channel_5g ?? 0)}
                    onChange={(e) => setForm({ ...form, channel_5g: Number(e.target.value) })}
                  >
                    <option value="0">Auto</option>
                    {ch5.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Width">
                  <Select
                    value={String(form.width_5g ?? 80)}
                    onChange={(e) => setForm({ ...form, width_5g: Number(e.target.value) })}
                  >
                    <option value="20">20 MHz</option>
                    <option value="40">40 MHz</option>
                    <option value="80">80 MHz</option>
                  </Select>
                </Field>
              </div>

              <p className="text-[12px] text-ink3">
                Channel 0 = auto. Widths are validated by the firmware against the
                selected mode; the AP restarts when settings are applied.
              </p>
            </div>
          </div>

          <div className="mt-4 flex items-center gap-2 border-t border-line/8 pt-3">
            <Button variant="primary" onClick={applyAp} loading={apBusy}>
              Apply AP settings
            </Button>
            <Button
              variant="ghost"
              onClick={() => setForm(null)}
              disabled={apBusy}
            >
              Discard
            </Button>
          </div>
        </Card>
      )}

      <Card title="Capabilities" className="lg:col-span-2">
        <div className="space-y-3">
          <div>
            <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-ink2">Modes</p>
            <div className="flex flex-wrap gap-1.5">
              {(data.modes ?? []).map((m) => (
                <Chip key={m}>{m}</Chip>
              ))}
              {(data.modes ?? []).length === 0 && (
                <span className="text-[13px] text-ink3">Not reported</span>
              )}
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}
