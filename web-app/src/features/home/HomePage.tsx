import { useHome } from '../../app/HomeContext'
import { deriveCarriers, signalBars } from '../../data/api'
import { formatBandwidthMHz, formatBytes, formatDuration, formatSpeed, formatUptime, qualityBg, qualityLabel, qualityText, rsrpQuality } from '../../format'
import { IActivity, IBolt, IDownload, IRadio, IUpload } from '../../icons'
import { Card, Chip, Meter, Row, SignalBars, Skeleton } from '../../ui/primitives'

function PageSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Skeleton className="col-span-2 h-40 xl:col-span-1" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    </div>
  )
}

export default function HomePage() {
  const { data, error } = useHome()

  if (!data && !error) return <PageSkeleton />

  const signal = data?.signal ?? null
  const battery = data?.battery ?? null
  const speed = data?.speed ?? null
  const device = data?.device ?? null
  const cpu = data?.cpu ?? null
  const mem = data?.memory ?? null
  const usage = data?.usage ?? null
  const clients = data?.clients ?? null
  const stock = data?.stock ?? null

  const carriers = deriveCarriers(data?.ca ?? null, data?.system ?? null)
  const lteCarriers = carriers.filter((c) => c.rat === 'lte')
  const nrCarriers = carriers.filter((c) => c.rat === 'nr')
  const primary = lteCarriers[0] || nrCarriers[0]
  const primaryRsrp = signal?.lte?.rsrp_dbm ?? signal?.nr?.rsrp_dbm ?? undefined
  const quality = rsrpQuality(primaryRsrp)
  const lteBw = data?.ca && !data.ca.error ? data.ca.total_dl_bw_mhz ?? 0 : 0
  const nrBw = nrCarriers.reduce((sum, c) => sum + (c.bandwidth_mhz ?? 0), 0)
  const aggBw = lteBw + nrBw
  const carrierCount = carriers.length

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-ink">Overview</h1>
        <p className="mt-0.5 text-[13px] text-ink2">
          {stock?.statusBarNetwork || 'Mobile broadband status'}
        </p>
      </div>

      {error && !data && (
        <Card>
          <p className="text-[13px] text-danger">{error}</p>
        </Card>
      )}

      {/* Hero stats */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Card className="col-span-2 xl:col-span-1">
          <div className="flex h-full flex-col justify-between gap-3">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-ink3">Signal strength</p>
                <div className="mt-1.5 flex items-end gap-2">
                  <span className={`tnum text-4xl font-bold leading-none ${qualityText(quality)}`}>
                    {primaryRsrp != null ? primaryRsrp : '\u2014'}
                  </span>
                  <span className="pb-0.5 text-[11px] font-medium text-ink3">dBm RSRP</span>
                </div>
                <p className={`mt-1 text-[12px] font-semibold ${qualityText(quality)}`}>{qualityLabel(quality)}</p>
              </div>
              <SignalBars bars={signalBars(stock)} large />
            </div>
            <div className="flex flex-wrap items-center gap-1.5 border-t border-line/8 pt-2.5">
              <span className={`h-2 w-2 rounded-full ${qualityBg(quality)}`} />
              <span className="text-[12px] text-ink2">{data?.mode ?? '\u2014'}</span>
              {primary && (
                <Chip tone={primary.rat === 'nr' ? 'nr' : 'lte'}>{primary.band}</Chip>
              )}
              {primary?.pci != null && primary.pci > 0 && (
                <span className="tnum text-[11px] text-ink3">PCI {primary.pci}</span>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex h-full flex-col justify-between gap-3">
            <div>
              <div className="flex items-center gap-1.5 text-ink3">
                <IRadio size={14} />
                <p className="text-[10px] font-semibold uppercase tracking-wider">Modem mode</p>
              </div>
              <p className="tnum mt-2 text-3xl font-bold text-ink">{data?.mode ?? '\u2014'}</p>
              <p className="mt-1 text-[12px] text-ink2">
                {carrierCount} carrier{carrierCount !== 1 ? 's' : ''} active
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 border-t border-line/8 pt-2.5">
              {nrCarriers.length > 0 && (
                <Chip tone="nr">
                  {nrCarriers.map((c) => c.band).join(' + ')}
                  {nrBw > 0 ? ` · ${formatBandwidthMHz(nrBw)}` : ''}
                </Chip>
              )}
              {lteBw > 0 && <Chip tone="lte">LTE {formatBandwidthMHz(lteBw)}</Chip>}
              {nrCarriers.length === 0 && lteBw <= 0 && (
                <span className="text-[11px] text-ink3">No carriers reported</span>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex h-full flex-col justify-between gap-3">
            <div>
              <div className="flex items-center gap-1.5 text-ink3">
                <IActivity size={14} />
                <p className="text-[10px] font-semibold uppercase tracking-wider">Throughput</p>
              </div>
              <div className="mt-2 space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <IDownload size={14} className="shrink-0 text-ok" />
                  <span className="tnum text-lg font-bold leading-none text-ink">
                    {speed ? formatSpeed(speed.rx_bps) : '\u2014'}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <IUpload size={14} className="shrink-0 text-accent" />
                  <span className="tnum text-lg font-bold leading-none text-ink">
                    {speed ? formatSpeed(speed.tx_bps) : '\u2014'}
                  </span>
                </div>
              </div>
            </div>
            <p className="tnum border-t border-line/8 pt-2.5 text-[11px] text-ink3">
              Peak {speed && speed.max_rx_bps > 0 ? formatSpeed(speed.max_rx_bps) : '\u2014'} down
            </p>
          </div>
        </Card>

        <Card>
          <div className="flex h-full flex-col justify-between gap-3">
            <div>
              <div className="flex items-center gap-1.5 text-ink3">
                {battery?.charging ? <IBolt size={14} /> : <IRadio size={14} className="opacity-0" />}
                <p className="text-[10px] font-semibold uppercase tracking-wider">Battery</p>
              </div>
              <p className="tnum mt-2 text-3xl font-bold text-ink">
                {battery?.percent != null ? `${battery.percent}%` : '\u2014'}
              </p>
              <p className="mt-1 text-[12px] text-ink2">
                {battery?.charging ? 'Charging' : battery?.status ?? 'On battery'}
              </p>
            </div>
            <p className="tnum border-t border-line/8 pt-2.5 text-[11px] text-ink3">
              {battery?.voltage_mv ? `${(battery.voltage_mv / 1000).toFixed(2)} V` : '\u2014'}
              {battery?.temperature_c != null ? ` · ${battery.temperature_c.toFixed(1)}°C` : ''}
            </p>
          </div>
        </Card>
      </div>

      {/* Carriers */}
      {carriers.length > 0 && (
        <Card title="Active carriers">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-accent">LTE</p>
              {lteCarriers.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {lteCarriers.map((c, i) => (
                    <Chip key={i} tone="lte">
                      {c.label} · {c.band}
                      {c.bandwidth_mhz ? ` · ${c.bandwidth_mhz} MHz` : ''}
                    </Chip>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-ink3">No active LTE carrier</p>
              )}
            </div>
            <div>
              <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-violet-600 dark:text-violet-400">
                5G NR
              </p>
              {nrCarriers.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {nrCarriers.map((c, i) => (
                    <Chip key={i} tone="nr">
                      {c.label} · {c.band}
                      {c.bandwidth_mhz ? ` · ${c.bandwidth_mhz} MHz` : ''}
                      {c.channel ? ` · ARFCN ${c.channel}` : ''}
                    </Chip>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-ink3">No active NR carrier</p>
              )}
            </div>
          </div>
          <p className="tnum mt-3 border-t border-line/8 pt-2 text-[12px] text-ink3">
            {aggBw > 0 ? (
              <>
                Aggregated DL bandwidth:{' '}
                <span className="font-semibold text-ink">{formatBandwidthMHz(aggBw)}</span>
                {lteBw > 0 && nrBw > 0
                  ? ` (LTE ${formatBandwidthMHz(lteBw)} + NR ${formatBandwidthMHz(nrBw)})`
                  : ''}
              </>
            ) : (
              'No channel bandwidth reported'
            )}
          </p>
        </Card>
      )}

      {/* Details row */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Card title="Connection">
          <Row label="Operator" value={stock?.statusBarNetwork ?? '\u2014'} />
          <Row label="PLMN" value={stock?.statusBarNetworkID ?? '\u2014'} mono />
          <Row label="Technology" value={stock?.statusBarTechnology ?? data?.mode ?? '\u2014'} />
          <Row
            label="State"
            value={usage?.connected ? `Connected ${formatDuration(usage.duration_secs)}` : 'Disconnected'}
          />
          <Row label="SIM" value={stock?.statusBarSimStatus ?? '\u2014'} />
          <Row
            label="Clients"
            value={clients?.count != null ? `${clients.count} connected` : '\u2014'}
          />
        </Card>

        <Card title="Device">
          <Row label="Model" value={device ? `${device.manufacturer ?? ''} ${device.model ?? ''}`.trim() : '\u2014'} />
          <Row label="Firmware" value={device?.firmware_revision ?? '\u2014'} wrap />
          <Row label="Uptime" value={formatUptime(device?.uptime_secs)} />
          <div className="mt-2 space-y-2 border-t border-line/8 pt-2.5">
            <div>
              <div className="mb-1 flex justify-between text-[11px]">
                <span className="font-medium text-ink2">CPU</span>
                <span className="tnum text-ink2">{cpu ? `${cpu.overall.toFixed(0)}%` : '\u2014'}</span>
              </div>
              <Meter pct={cpu?.overall ?? 0} />
            </div>
            <div>
              <div className="mb-1 flex justify-between text-[11px]">
                <span className="font-medium text-ink2">Memory</span>
                <span className="tnum text-ink2">{mem ? `${mem.usage_pct.toFixed(0)}%` : '\u2014'}</span>
              </div>
              <Meter pct={mem?.usage_pct ?? 0} tone="bg-warn" />
            </div>
          </div>
        </Card>

        <Card title="Data this connection">
          {usage ? (
            <div className="space-y-2.5">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-ink3">Since connect</p>
                <div className="tnum mt-0.5 flex gap-3 text-[13px] font-medium">
                  <span className="flex items-center gap-1 text-ok">
                    <IDownload size={12} /> {formatBytes(usage.rx_bytes)}
                  </span>
                  <span className="flex items-center gap-1 text-accent">
                    <IUpload size={12} /> {formatBytes(usage.tx_bytes)}
                  </span>
                </div>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-ink3">Total reported</p>
                <p className="tnum mt-0.5 text-[13px] font-medium">{formatBytes(usage.total_bytes)}</p>
              </div>
              <p className="text-[11px] text-ink3">
                Counters reset when the WAN connection drops.
              </p>
            </div>
          ) : (
            <p className="text-[13px] text-ink3">Not available</p>
          )}
        </Card>
      </div>
    </div>
  )
}
