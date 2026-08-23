import { useHome } from '../../app/HomeContext'
import { deriveCarriers } from '../../data/api'
import { formatBandwidthMHz, rsrpColorClass, rsrqColorClass, sinrColorClass } from '../../format'
import { Card, Chip, Row, Skeleton, Stat } from '../../ui/primitives'

function plmnLabel(value?: string | null): string {
  const plmn = String(value ?? '').trim()
  return /^\d{5,6}$/.test(plmn) ? `${plmn.slice(0, 3)}-${plmn.slice(3)}` : plmn || '\u2014'
}

export default function Overview() {
  const { data, error } = useHome()

  if (!data && !error) {
    return (
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Skeleton className="h-44" />
        <Skeleton className="h-44" />
        <Skeleton className="h-56 md:col-span-2" />
      </div>
    )
  }
  if (!data) return <p className="text-[13px] text-danger">{error}</p>

  const signal = data.signal && !data.signal.error ? data.signal : null
  const lte = signal?.lte ?? null
  const nr = signal?.nr ?? null
  const system = data.system && !data.system.error ? data.system : null
  const ca = data.ca && !data.ca.error ? data.ca : null
  const carriers = deriveCarriers(data.ca, data.system)
  const nrActive = !!system?.nr && system.nr.pci != null && !!system.nr.band
  const lteActive = !!system?.lte?.cell_id || !!ca?.pcc

  return (
    <div className="space-y-4">
      {/* Signal quality */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card title="LTE signal">
          {lte ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="RSRP" value={lte.rsrp_dbm ?? '\u2014'} sub="dBm" tone={rsrpColorClass(lte.rsrp_dbm ?? undefined)} />
              <Stat label="RSRQ" value={lte.rsrq_db ?? '\u2014'} sub="dB" tone={rsrqColorClass(lte.rsrq_db ?? undefined)} />
              <Stat label="RSSI" value={lte.rssi_dbm ?? '\u2014'} sub="dBm" />
              <Stat label="SINR" value={lte.snr_db ?? '\u2014'} sub="dB" tone={sinrColorClass(lte.snr_db ?? undefined)} />
            </div>
          ) : (
            <p className="text-[13px] text-ink3">No LTE signal reported</p>
          )}
        </Card>

        <Card title="5G NR signal">
          {nr && (nr.rsrp_dbm != null || nr.snr_db != null) ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Stat label="RSRP" value={nr.rsrp_dbm ?? '\u2014'} sub="dBm" tone={rsrpColorClass(nr.rsrp_dbm ?? undefined)} />
              <Stat label="RSRQ" value={nr.rsrq_db ?? '\u2014'} sub="dB" tone={rsrqColorClass(nr.rsrq_db ?? undefined)} />
              <Stat label="SINR" value={nr.snr_db ?? '\u2014'} sub="dB" tone={sinrColorClass(nr.snr_db ?? undefined)} />
            </div>
          ) : (
            <p className="text-[13px] text-ink3">NR not active on this cell</p>
          )}
        </Card>
      </div>

      {/* Serving cell + carriers */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card title="Serving cell">
          <Row label="Mode" value={data.mode} />
          {nrActive && system?.nr ? (
            <>
              <Row label="NR band" value={`${system.nr.band ?? '\u2014'}`} />
              <Row
                label="NR bandwidth"
                value={system.nr.bandwidth_mhz ? formatBandwidthMHz(system.nr.bandwidth_mhz) : '\u2014'}
              />
              <Row label="NR PCI" value={system.nr.pci ?? '\u2014'} mono />
              <Row label="NR-ARFCN" value={system.nr.arfcn ?? '\u2014'} mono />
              <Row label="NR PLMN" value={plmnLabel(system.nr.plmn)} mono />
            </>
          ) : null}
          {lteActive && system?.lte ? (
            <>
              <Row label="PLMN" value={`${system.lte.mcc ?? '?'}-${system.lte.mnc ?? '?'}${system.lte.roaming ? ' (roaming)' : ''}`} mono />
              <Row
                label="Cell ID"
                value={system.lte.cell_id != null ? `0x${system.lte.cell_id.toString(16).toUpperCase()}` : '\u2014'}
                mono
              />
              <Row label="TAC" value={system.lte.tac ?? '\u2014'} mono />
            </>
          ) : null}
          {!nrActive && !lteActive && (
            <p className="mt-1 text-[13px] text-ink3">Searching for service…</p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5 border-t border-line/8 pt-2.5">
            <Chip tone={data.endc?.endc_enabled ? 'ok' : 'default'}>
              EN-DC {data.endc?.endc_enabled ? 'enabled' : 'disabled'}
            </Chip>
            {system?.eutra_with_nr5g != null && (
              <Chip tone={system.eutra_with_nr5g ? 'ok' : 'default'}>
                EUTRA w/ NR5G {system.eutra_with_nr5g ? 'yes' : 'no'}
              </Chip>
            )}
          </div>
        </Card>

        <Card title="Active carriers">
          {carriers.length > 0 ? (
            <div className="space-y-1.5">
              {carriers.map((c, i) => (
                <div key={i} className="flex items-baseline justify-between gap-3 text-[13px]">
                  <span className="flex items-center gap-1.5">
                    <Chip tone={c.rat === 'nr' ? 'nr' : 'lte'}>{c.band}</Chip>
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-ink3">
                      {c.label}
                    </span>
                  </span>
                  <span className="tnum text-right text-ink2">
                    {[
                      c.bandwidth_mhz ? formatBandwidthMHz(c.bandwidth_mhz) : null,
                      c.pci != null ? `PCI ${c.pci}` : null,
                      c.channel != null ? `${c.rat === 'nr' ? 'ARFCN' : 'EARFCN'} ${c.channel}` : null,
                      c.freq != null ? `${c.freq.toFixed(1)} MHz` : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || '\u2014'}
                  </span>
                </div>
              ))}
              {ca && ca.total_dl_bw_mhz ? (
                <p className="mt-1 border-t border-line/8 pt-2 text-[12px] text-ink3">
                  LTE total DL bandwidth: {formatBandwidthMHz(ca.total_dl_bw_mhz)}
                </p>
              ) : null}
            </div>
          ) : (
            <p className="text-[13px] text-ink3">No carriers reported</p>
          )}
        </Card>
      </div>
    </div>
  )
}
