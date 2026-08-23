import { useEffect, useState } from 'react'
import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import type { BandDuration } from '../../types'
import { confirm } from '../../ui/feedback'
import { Button, Select } from '../../ui/controls'
import { Card, Chip, Skeleton } from '../../ui/primitives'

type BandKind = 'lte' | 'sa' | 'nsa'

function BandPicker({
  title,
  kind,
  selected,
  supported,
  prefix,
  nr,
  onToggle,
}: {
  title: string
  kind: BandKind
  selected: Set<number>
  supported: number[]
  prefix: string
  nr?: boolean
  onToggle: (kind: BandKind, band: number) => void
}) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-ink2">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {supported.map((band) => {
          const checked = selected.has(band)
          return (
            <label
              key={`${kind}-${band}`}
              className={`inline-flex cursor-pointer select-none items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors ${
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
    const body = {
      lte_bands: [...sel.lte].sort((a, b) => a - b),
      nr5g_sa_bands: [...sel.sa].sort((a, b) => a - b),
      nr5g_nsa_bands: [...sel.nsa].sort((a, b) => a - b),
    }
    const ok = await confirm({
      title: duration === 'permanent' ? 'Apply bands permanently?' : 'Apply bands until reboot?',
      body: 'Cellular service may briefly drop while the modem re-attaches.',
      confirmLabel: 'Apply',
      danger: duration === 'permanent',
    })
    if (!ok) return
    setBusy(true)
    setMessage({ text: 'Applying and verifying…' })
    try {
      const result = await api.bandsApply(body, duration)
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
      body: `Restores the baseline captured before the first write (${duration === 'permanent' ? 'permanently' : 'until reboot'}).`,
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
          <div className="flex items-center justify-between text-[13px]">
            <span className="text-ink2">Mode preference (unchanged by this control)</span>
            <span className="font-medium text-ink">{prefs?.mode_pref?.join(', ') || '\u2014'}</span>
          </div>

          <BandPicker
            title="LTE"
            kind="lte"
            selected={sel.lte}
            supported={caps?.lte_bands_ext ?? caps?.lte_bands ?? []}
            prefix="B"
            onToggle={toggle}
          />
          <BandPicker
            title="NR5G SA"
            kind="sa"
            selected={sel.sa}
            supported={caps?.nr5g_sa_bands ?? []}
            prefix="n"
            nr
            onToggle={toggle}
          />
          <BandPicker
            title="NR5G NSA"
            kind="nsa"
            selected={sel.nsa}
            supported={caps?.nr5g_nsa_bands ?? []}
            prefix="n"
            nr
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
          Changing bands can briefly interrupt cellular service. LTE cannot be empty, and at least
          one NR path must remain selected.{' '}
          {control?.permanent_enabled
            ? 'Permanent writes have passed reboot verification.'
            : 'Permanent writes remain disabled pending reboot verification.'}
        </p>
      </Card>
    </div>
  )
}
