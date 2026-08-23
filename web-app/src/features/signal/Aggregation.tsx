import { useMemo, useState } from 'react'
import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import type { BandsInfo, CaCapabilityEntry, ObservedLayout } from '../../types'
import { Select } from '../../ui/controls'
import { Card, Chip, Skeleton } from '../../ui/primitives'

type Kind = 'lte' | 'mrdc' | 'nr' | 'validated' | 'observed'

interface GroupedEntry {
  label: string
  components: CaCapabilityEntry['components']
  variants: number
}

function groupByLabel(items: CaCapabilityEntry[]): GroupedEntry[] {
  const grouped = new Map<string, GroupedEntry>()
  for (const item of items ?? []) {
    const found = grouped.get(item.label)
    if (found) found.variants += 1
    else grouped.set(item.label, { label: item.label, components: item.components ?? [], variants: 1 })
  }
  return [...grouped.values()]
}

export default function Aggregation() {
  const combos = usePoll('ca-combos', api.caCombinations, 30000)
  const bands = usePoll('bands', api.bands, 30000)
  const [kind, setKind] = useState<Kind>('mrdc')
  const [eligibleOnly, setEligibleOnly] = useState(false)

  const data = combos.data
  const bandData: BandsInfo | null = bands.data

  const eligibleSets = useMemo(() => {
    const prefs = bandData?.preferences
    return {
      lte: new Set(prefs?.lte_bands_ext ?? prefs?.lte_bands ?? []),
      sa: new Set(prefs?.nr5g_sa_bands ?? []),
      nsa: new Set(prefs?.nr5g_nsa_bands ?? []),
    }
  }, [bandData])

  if (!data && !combos.error) return <Skeleton className="h-72" />
  if (!data) return <p className="text-[13px] text-danger">{combos.error}</p>

  const summary = data.summary ?? {}
  const capture = data.capture ?? {}
  const validation = data.nr_ca_validation ?? {}
  const validatedCases = validation.cases ?? []

  function isEligible(entry: GroupedEntry): boolean {
    const nrSet = kind === 'nr' ? eligibleSets.sa : eligibleSets.nsa
    return (entry.components ?? []).every((c) =>
      c.rat === 'lte' ? eligibleSets.lte.has(c.band) : nrSet.has(c.band),
    )
  }

  let body: React.ReactNode
  if (kind === 'validated') {
    body = (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[12.5px]">
          <thead>
            <tr className="text-ink3">
              <th className="py-1 pr-3 font-medium">Allowed SA mask</th>
              <th className="py-1 pr-3 font-medium">Decoded RRC result</th>
              <th className="py-1 pr-3 font-medium">SCell configured</th>
              <th className="py-1 font-medium">Captured</th>
            </tr>
          </thead>
          <tbody>
            {validatedCases.map((c, i) => (
              <tr key={i} className="border-t border-line/8">
                <td className="py-1 pr-3">{(c.requested_sa_bands ?? []).map((b) => `n${b}`).join(' + ')}</td>
                <td className="tnum py-1 pr-3">{c.label}</td>
                <td className="py-1 pr-3">
                  <Chip tone={c.scell_configured ? 'ok' : 'warn'}>{c.scell_configured ? 'yes' : 'no'}</Chip>
                </td>
                <td className="py-1 text-ink2">
                  {c.capture?.completed_at ? new Date(c.capture.completed_at).toLocaleString() : '\u2014'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {validatedCases.length === 0 && (
          <p className="mt-2 text-[12px] text-ink3">No DIAG-validated NR-CA cases are installed.</p>
        )}
      </div>
    )
  } else if (kind === 'observed') {
    const observed = (data.observed ?? []) as ObservedLayout[]
    body = (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[12.5px]">
          <thead>
            <tr className="text-ink3">
              <th className="py-1 pr-3 font-medium">Observed layout</th>
              <th className="py-1 pr-3 font-medium">First seen</th>
              <th className="py-1 pr-3 font-medium">Last seen</th>
              <th className="py-1 font-medium">Polls</th>
            </tr>
          </thead>
          <tbody>
            {observed.map((item) => (
              <tr key={item.key} className="border-t border-line/8">
                <td className="tnum py-1 pr-3">{item.label}</td>
                <td className="py-1 pr-3 text-ink2">{new Date(item.first_seen * 1000).toLocaleString()}</td>
                <td className="py-1 pr-3 text-ink2">{new Date(item.last_seen * 1000).toLocaleString()}</td>
                <td className="tnum py-1">{item.seen_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {observed.length === 0 && (
          <p className="mt-2 text-[12px] text-ink3">No aggregated layout has been observed since tracking began.</p>
        )}
      </div>
    )
  } else {
    const entries =
      kind === 'lte'
        ? (data.lte ?? []).filter((x) => x.is_ca)
        : kind === 'mrdc'
          ? data.mrdc ?? []
          : data.nr ?? []
    let grouped = groupByLabel(entries).map((item) => ({ ...item, eligible: isEligible(item) }))
    if (eligibleOnly) grouped = grouped.filter((item) => item.eligible)
    body = (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[12.5px]">
          <thead>
            <tr className="text-ink3">
              <th className="py-1 pr-3 font-medium">Band / bandwidth-class layout</th>
              <th className="py-1 pr-3 font-medium">Variants</th>
              <th className="py-1 font-medium">Selected bands</th>
            </tr>
          </thead>
          <tbody>
            {grouped.map((item) => (
              <tr key={item.label} className="border-t border-line/8">
                <td className="tnum py-1 pr-3">{item.label}</td>
                <td className="tnum py-1 pr-3">{item.variants}</td>
                <td className="py-1">
                  <Chip tone={item.eligible ? 'ok' : 'default'}>{item.eligible ? 'allowed' : 'excluded'}</Chip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {grouped.length === 0 && (
          <p className="mt-2 text-[12px] text-ink3">No advertised layouts match this view.</p>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Card title="Advertised carrier combinations">
        {data.active && (
          <p className="mb-2 text-[13px] text-ink">
            Active now: <span className="font-semibold text-ok">{data.active.label}</span>
          </p>
        )}
        {validatedCases.length > 0 && (
          <p className="mb-2 text-[12px] text-ink3">
            DIAG-verified SA maximum: <b>{validation.conclusion?.max_component_count ?? 1} NR carriers</b>.
            Captured RRC evidence, not a continuously live SCell reading.
          </p>
        )}
        <div className="mb-3 flex flex-wrap gap-1.5">
          <Chip>
            {summary.lte_ca_configurations ?? 0} LTE CA entries /{' '}
            {groupByLabel((data.lte ?? []).filter((x) => x.is_ca)).length} layouts
          </Chip>
          <Chip tone="nr">
            {summary.mrdc_configurations ?? 0} MR-DC entries / {groupByLabel(data.mrdc ?? []).length} layouts
          </Chip>
          <Chip tone="nr">{summary.nr_ca_configurations ?? 0} NR-CA entries</Chip>
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-3">
          <div className="w-56">
            <Select value={kind} onChange={(e) => setKind(e.target.value as Kind)} aria-label="Combination view">
              <option value="lte">LTE CA</option>
              <option value="mrdc">LTE + NR (NSA/MR-DC)</option>
              <option value="nr">NR CA capability</option>
              <option value="validated">Validated SA cases</option>
              <option value="observed">Observed live</option>
            </Select>
          </div>
          {(kind === 'lte' || kind === 'mrdc' || kind === 'nr') && (
            <label className="flex items-center gap-2 text-[12px] text-ink2">
              <input
                type="checkbox"
                checked={eligibleOnly}
                onChange={(e) => setEligibleOnly(e.target.checked)}
                className="accent-accent"
              />
              only layouts allowed by the current band selection
            </label>
          )}
        </div>

        {body}

        <p className="mt-3 text-[11px] text-ink3">
          {capture.scope ?? ''} · {capture.network ?? ''} · captured{' '}
          {capture.completed_at ? new Date(capture.completed_at).toLocaleString() : 'unknown'}. Classes A/C etc.
          are 3GPP bandwidth classes. These are modem-advertised capabilities, not a promise that the carrier
          will deploy or schedule them.
        </p>
      </Card>
    </div>
  )
}
