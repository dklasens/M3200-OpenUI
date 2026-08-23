import { useHome } from '../../app/HomeContext'
import { formatBytes, formatDuration, formatSpeed } from '../../format'
import { IDownload, IUpload } from '../../icons'
import { Card, Row, Skeleton, Stat } from '../../ui/primitives'

export default function DataTab() {
  const { data, error } = useHome()

  if (!data && !error) return <Skeleton className="h-64" />
  if (!data) return <p className="text-[13px] text-danger">{error}</p>

  const usage = data.usage
  const speed = data.speed

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <Card title="This connection">
        {usage ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Stat
                label="Downlink"
                value={formatBytes(usage.rx_bytes)}
                tone="text-ok"
              />
              <Stat
                label="Uplink"
                value={formatBytes(usage.tx_bytes)}
                tone="text-accent"
              />
            </div>
            <Row label="Total reported" value={formatBytes(usage.total_bytes)} />
            <Row
              label="Connected for"
              value={usage.connected ? formatDuration(usage.duration_secs) : 'Disconnected'}
            />
            <p className="text-[11px] text-ink3">
              Counters come from the stock status API and reset when the WAN
              connection drops.
            </p>
          </div>
        ) : (
          <p className="text-[13px] text-ink3">Usage not available</p>
        )}
      </Card>

      <Card title="Live throughput">
        {speed ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center gap-1.5">
                <IDownload size={14} className="shrink-0 text-ok" />
                <span className="tnum text-lg font-bold text-ink">{formatSpeed(speed.rx_bps)}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <IUpload size={14} className="shrink-0 text-accent" />
                <span className="tnum text-lg font-bold text-ink">{formatSpeed(speed.tx_bps)}</span>
              </div>
            </div>
            <Row label="Peak down" value={speed.max_rx_bps > 0 ? formatSpeed(speed.max_rx_bps) : '\u2014'} />
            <Row label="Peak up" value={speed.max_tx_bps > 0 ? formatSpeed(speed.max_tx_bps) : '\u2014'} />
            <p className="text-[11px] text-ink3">
              Rates are derived from the stock byte counters; peaks are since the
              agent started.
            </p>
          </div>
        ) : (
          <p className="text-[13px] text-ink3">Throughput not available</p>
        )}
      </Card>
    </div>
  )
}
