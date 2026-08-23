import { useEffect, useState } from 'react'
import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import type { BandDuration, NetworkMode } from '../../types'
import { confirm } from '../../ui/feedback'
import { Button, Segmented, Select } from '../../ui/controls'
import { Card, Chip, Skeleton } from '../../ui/primitives'

type BandKind = 'lte' | 'sa' | 'nsa'

const MODE_OPTIONS: { value: NetworkMode; label: string }[] = [
  { value: 'auto', label: 'Automatic' },
  { value: 'lte', label: '4G LTE only' },
  { value: 'nsa', label: '5G NSA' },
  { value: 'sa', label: '5G SA' },
]

const MODE_TITLES: Record<NetworkMode, string> = {
  auto: 'Apply bands (automatic mode)?',
  lte: 'Switch to 4G LTE only?',
  nsa: 'Switch to 5G NSA?',
  sa: 'Switch to 5G SA?',
}

const MODE_WARNINGS: Record<NetworkMode, string> = {
  auto: '',
  lte: ' 5G will be disabled until you switch back.',
  nsa: ' Attaching 5G additionally requires the LTE anchor cell to support EN-DC.',
  sa: ' If 5G SA never attaches, SA may be disabled at firmware level (nr5g_disable_mode, see device.md).',
}

function BandPicker({
  title,
  kind,
  selected,
  supported,
  prefix,
  nr,
  disabled,
  onToggle,
}: {
  title: string
  kind: BandKind
  selected: Set<number>
  supported: number[]
  prefix: string
  nr?: boolean
  disabled?: boolean
  onToggle: (kind: BandKind, band: number) => void
}) {
  return (
    <div className={disabled ? 'opacity-55' : undefined}>
      <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-ink2">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {supported.map((band) => {
          const checked = selected.has(band)
          return (
            <label
              key={`${kind}-${band}`}
              className={`inline-flex select-none items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors ${
                disabled ? 'pointer-events-none' : 'cursor-pointer'
              } ${
                checked
                  ? nr
                    ? 'border-violet-500/40 bg-violet-500/10 text-violet-600 dark:text-violet-400'
                    : 'border-accent/40 bg-accent/10 text-accent'
                  : 'border-line/10 bg-surface2 text-ink3 opacity-60'
              }`}
            >
              <input
                type="checkbox"
                className="accent-current"
                checked={checked}
                disabled={disabled}
                onChange={() => onToggle(kind, band)}
              />
              {prefix}
              {band}
            </label>
          )
        })}
      </div>
    </div>
  )
}

export default function Bands() {
  const bands = usePoll('bands', api.bands, 30000)
  const [selected, setSelected] = useState<Record<BandKind, Set<number>> | null>(null)
  const [dirty, setDirty] = useState(false)
  const [mode, setMode] = useState<NetworkMode>('auto')
  const [duration, setDuration] = useState<BandDuration>('power_cycle')
  const [message, setMessage] = useState<{ text: string; ok?: boolean } | null>(null)
  const [busy, setBusy] = useState(false)

  const data = bands.data
  const prefs = data?.preferences
  const caps = data?.capabilities
  const control = data?.control

  // Seed the pickers from the live preferences whenever they refresh,
  // unless the user has an unapplied selection in progress.
  useEffect(() => {
    if (!prefs || dirty) return
    setSelected({
      lte: new Set(prefs.lte_bands_ext ?? prefs.lte_bands ?? []),
      sa: new Set(prefs.nr5g_sa_bands ?? []),
      nsa: new Set(prefs.nr5g_nsa_bands ?? []),
    })
  }, [prefs, dirty])

  // Track the modem's derived network mode until the user overrides it.
  useEffect(() => {
    if (dirty) return
    const current = control?.current_mode
    if (current === 'auto' || current === 'lte' || current === 'nsa' || current === 'sa') {
      setMode(current)
    }
  }, [control, dirty])

  if (!data && !bands.error) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-56" />
        <Skeleton className="h-16" />
      </div>
    )
  }
  if (!data) return <p className="text-[13px] text-danger">{bands.error}</p>

  const sel = selected ?? { lte: new Set<number>(), sa: new Set<number>(), nsa: new Set<number>() }
  const allLte = new Set(caps?.lte_bands_ext ?? caps?.lte_bands ?? [])

  // The masks each mode will actually write.  NSA forces the full hardware
  // LTE anchor set and empties SA; SA empties NSA and keeps LTE inert; LTE
  // only leaves the NR masks in place (inert) so switching back is seamless.
  const effective = {
    lte: mode === 'nsa' ? allLte : sel.lte,
    sa: mode === 'nsa' ? new Set<number>() : sel.sa,
    nsa: mode === 'sa' ? new Set<number>() : sel.nsa,
  }

  function toggle(kind: BandKind, band: number) {
    setSelected((prev) => {
      const next = {
        lte: new Set(prev?.lte ?? []),
        sa: new Set(prev?.sa ?? []),
        nsa: new Set(prev?.nsa ?? []),
      }
      if (next[kind].has(band)) next[kind].delete(band)
      else next[kind].add(band)
      return next
    })
    setDirty(true)
    setMessage({ text: 'Selection changed; not yet applied.' })
  }

  function selectMode(next: NetworkMode) {
    setMode(next)
    setDirty(true)
    let note = 'Selection changed; not yet applied.'
    // An NSA/SA lock needs at least one band on that NR path; preselect the
    // full hardware set when the path is currently empty.
    if ((next === 'nsa' && sel.nsa.size === 0) || (next === 'sa' && sel.sa.size === 0)) {
      const fill = next === 'nsa' ? (caps?.nr5g_nsa_bands ?? []) : (caps?.nr5g_sa_bands ?? [])
      setSelected((prev) => {
        const updated = {
          lte: new Set(prev?.lte ?? []),
          sa: new Set(prev?.sa ?? []),
          nsa: new Set(prev?.nsa ?? []),
        }
        if (updated[next].size === 0) updated[next] = new Set(fill)
        return updated
      })
      note = `No ${next.toUpperCase()} bands were selected; all hardware ${next.toUpperCase()} bands are now selected.`
    }
    setMessage({ text: note })
  }

  function preset(kind: 'current' | 'all') {
    if (!prefs || !caps) return
    const values =
      kind === 'all'
        ? {
            lte: caps.lte_bands_ext ?? caps.lte_bands ?? [],
            sa: caps.nr5g_sa_bands ?? [],
            nsa: caps.nr5g_nsa_bands ?? [],
          }
        : {
            lte: prefs.lte_bands_ext ?? prefs.lte_bands ?? [],
            sa: prefs.nr5g_sa_bands ?? [],
            nsa: prefs.nr5g_nsa_bands ?? [],
          }
    setSelected({ lte: new Set(values.lte), sa: new Set(values.sa), nsa: new Set(values.nsa) })
    setDirty(kind !== 'current')
    setMessage(
      kind === 'all'
        ? { text: 'All hardware-supported bands selected; click Apply selection.' }
        : { text: 'Reverted to the current live selection.' },
    )
  }

  async function apply() {
    if (effective.lte.size === 0) {
      setMessage({ text: 'Select at least one LTE band.', ok: false })
      return
    }
    if (mode === 'nsa' && effective.nsa.size === 0) {
      setMessage({ text: '5G NSA requires at least one selected NSA band.', ok: false })
      return
    }
    if (mode === 'sa' && effective.sa.size === 0) {
      setMessage({ text: '5G SA requires at least one selected SA band.', ok: false })
      return
    }
    if (mode === 'auto' && effective.sa.size === 0 && effective.nsa.size === 0) {
      setMessage({ text: 'Automatic mode needs at least one NR band on either path.', ok: false })
      return
    }
    const body = {
      lte_bands: [...effective.lte].sort((a, b) => a - b),
      nr5g_sa_bands: [...effective.sa].sort((a, b) => a - b),
      nr5g_nsa_bands: [...effective.nsa].sort((a, b) => a - b),
    }
    const ok = await confirm({
      title: MODE_TITLES[mode] + (duration === 'permanent' ? ' (permanent)' : ''),
      body: 'Cellular service may briefly drop while the modem re-attaches.' + MODE_WARNINGS[mode],
      confirmLabel: 'Apply',
      danger: duration === 'permanent' || mode !== 'auto',
    })
    if (!ok) return
    setBusy(true)
    setMessage({ text: 'Applying and verifying…' })
    try {
      const result = await api.bandsApply(body, duration, mode)
      setDirty(false)
      bands.refresh()
      setMessage(
        result.ok
          ? { text: 'Selection applied and verified by QMI read-back.', ok: true }
          : { text: 'The modem read-back did not match the request.', ok: false },
      )
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Apply failed', ok: false })
    } finally {
      setBusy(false)
    }
  }

  async function restore() {
    const ok = await confirm({
      title: 'Restore original carrier bands?',
      body: `Restores the baseline captured before the first write — bands and, when recorded, the network mode (${duration === 'permanent' ? 'permanently' : 'until reboot'}).`,
      confirmLabel: 'Restore',
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    try {
      const result = await api.bandsRestore(duration)
      setDirty(false)
      bands.refresh()
      setMessage(
        result.ok
          ? { text: 'Original carrier preferences restored and verified.', ok: true }
          : { text: 'Restore read-back did not match the baseline.', ok: false },
      )
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Restore failed', ok: false })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card title="Allowed bands within hardware capability">
        <div className="space-y-4">
          <div>
            <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-ink2">
              Network mode
            </p>
            <Segmented options={MODE_OPTIONS} value={mode} onChange={selectMode} />
            <p className="mt-1.5 text-[12px] text-ink3">
              Live RAT preference: {prefs?.mode_pref?.join(', ') || '—'}
              {control?.current_mode === 'custom' && ' (custom combination)'}
            </p>
          </div>

          <BandPicker
            title={
              mode === 'nsa'
                ? 'LTE — all bands (anchor for NSA)'
                : mode === 'sa'
                  ? 'LTE (inert in 5G SA mode)'
                  : 'LTE'
            }
            kind="lte"
            selected={effective.lte}
            supported={caps?.lte_bands_ext ?? caps?.lte_bands ?? []}
            prefix="B"
            disabled={mode === 'nsa' || mode === 'sa'}
            onToggle={toggle}
          />
          <BandPicker
            title={
              mode === 'nsa'
                ? 'NR5G SA (emptied in NSA mode)'
                : mode === 'lte'
                  ? 'NR5G SA (inert while LTE only)'
                  : 'NR5G SA'
            }
            kind="sa"
            selected={effective.sa}
            supported={caps?.nr5g_sa_bands ?? []}
            prefix="n"
            nr
            disabled={mode === 'nsa' || mode === 'lte'}
            onToggle={toggle}
          />
          <BandPicker
            title={
              mode === 'sa'
                ? 'NR5G NSA (emptied in SA mode)'
                : mode === 'lte'
                  ? 'NR5G NSA (inert while LTE only)'
                  : 'NR5G NSA'
            }
            kind="nsa"
            selected={effective.nsa}
            supported={caps?.nr5g_nsa_bands ?? []}
            prefix="n"
            nr
            disabled={mode === 'sa' || mode === 'lte'}
            onToggle={toggle}
          />
        </div>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => preset('current')}>Current</Button>
          <Button onClick={() => preset('all')}>All hardware bands</Button>
          <div className="w-44">
            <Select
              value={duration}
              onChange={(e) => setDuration(e.target.value as BandDuration)}
              aria-label="Write duration"
            >
              <option value="power_cycle">Until reboot</option>
              {control?.permanent_enabled && <option value="permanent">Permanent</option>}
            </Select>
          </div>
          <Button variant="primary" onClick={apply} loading={busy} disabled={!control?.write_enabled}>
            Apply selection
          </Button>
          <Button variant="danger" onClick={restore} loading={busy} disabled={!control?.baseline}>
            Restore original
          </Button>
          {control?.baseline && (
            <Chip tone="default">
              baseline: B{(control.baseline.lte_bands ?? []).join(',B')}
            </Chip>
          )}
        </div>
        {message && (
          <p
            className={`mt-2 text-[13px] font-medium ${
              message.ok === true ? 'text-ok' : message.ok === false ? 'text-danger' : 'text-ink2'
            }`}
          >
            {message.text}
          </p>
        )}
        <p className="mt-2 text-[12px] text-ink3">
          Changing bands or network mode can briefly interrupt cellular service. LTE cannot be
          empty, and automatic mode keeps at least one NR path selected.{' '}
          {control?.permanent_enabled
            ? 'Permanent writes have passed reboot verification.'
            : 'Permanent writes remain disabled pending reboot verification.'}
        </p>
      </Card>
    </div>
  )
}
