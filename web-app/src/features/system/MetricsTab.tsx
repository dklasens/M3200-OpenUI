import { useHome } from '../../app/HomeContext'
import { formatBytes, tempColorClass } from '../../format'
import { Card, Meter, Row, Skeleton, Stat } from '../../ui/primitives'

export default function MetricsTab() {
  const { data, error } = useHome()

  if (!data && !error) {
    return (
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Skeleton className="h-56" />
        <Skeleton className="h-56" />
        <Skeleton className="h-56 md:col-span-2" />
      </div>
    )
  }
  if (!data) return <p className="text-[13px] text-danger">{error}</p>

  const thermal = data.thermal
  const battery = data.battery
  const cpu = data.cpu
  const mem = data.memory

  const thermalRows: { label: string; value?: number }[] = thermal
    ? [
        { label: 'CPU', value: thermal.cpu },
        { label: 'Modem', value: thermal.modem },
        { label: 'Modem skin', value: thermal.modem_skin },
        { label: 'Battery', value: thermal.battery },
        { label: 'Charger skin', value: thermal.charger_skin },
        { label: 'USB connector', value: thermal.connector },
        { label: 'Ambient', value: thermal.ambient },
        { label: 'PMIC', value: thermal.pmic },
      ].filter((r) => r.value != null)
    : []

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <Card title="Compute">
        <div className="space-y-3">
          <div>
            <div className="mb-1 flex justify-between text-[12px]">
              <span className="font-medium text-ink2">CPU</span>
              <span className="tnum text-ink">{cpu ? `${cpu.overall.toFixed(0)}%` : '\u2014'}</span>
            </div>
            <Meter pct={cpu?.overall ?? 0} />
          </div>
          <div>
            <div className="mb-1 flex justify-between text-[12px]">
              <span className="font-medium text-ink2">Memory</span>
              <span className="tnum text-ink">
                {mem ? `${mem.usage_pct.toFixed(0)}% of ${formatBytes(mem.total_kb * 1024)}` : '\u2014'}
              </span>
            </div>
            <Meter pct={mem?.usage_pct ?? 0} tone="bg-warn" />
          </div>
          {mem && (
            <p className="tnum text-[11px] text-ink3">
              used {formatBytes(mem.used_kb * 1024)} · free {formatBytes(mem.free_kb * 1024)}
            </p>
          )}
        </div>
      </Card>

      <Card title="Thermals">
        {thermalRows.length > 0 ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {thermalRows.map((r) => (
              <Stat
                key={r.label}
                label={r.label}
                value={`${r.value?.toFixed(1)}°`}
                tone={tempColorClass(r.value)}
              />
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-ink3">No thermal sensors reported</p>
        )}
      </Card>

      <Card title="Battery" className="md:col-span-2">
        {battery && battery.available ? (
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5 md:grid-cols-3">
            <Row label="Charge" value={battery.percent != null ? `${battery.percent}%` : '\u2014'} />
            <Row label="State" value={battery.charging ? 'Charging' : battery.status ?? '\u2014'} />
            <Row label="Health" value={battery.health ?? '\u2014'} />
            <Row label="Voltage" value={battery.voltage_mv != null ? `${(battery.voltage_mv / 1000).toFixed(2)} V` : '\u2014'} />
            <Row
              label="Current"
              value={battery.current_ma != null ? `${battery.current_ma > 0 ? '+' : ''}${battery.current_ma} mA` : '\u2014'}
            />
            <Row label="Temperature" value={battery.temperature_c != null ? `${battery.temperature_c.toFixed(1)}°C` : '\u2014'} />
            <Row label="Technology" value={battery.technology ?? '\u2014'} />
            <Row
              label="Capacity (full)"
              value={battery.charge_full_mah != null ? `${battery.charge_full_mah.toFixed(0)} mAh` : '\u2014'}
            />
            <Row
              label="Capacity (design)"
              value={battery.charge_full_design_mah != null ? `${battery.charge_full_design_mah.toFixed(0)} mAh` : '\u2014'}
            />
            <Row label="Charge cycles" value={battery.cycle_count ?? '\u2014'} />
            <Row
              label="USB input"
              value={
                battery.usb?.present
                  ? `${battery.usb.online ? 'online' : 'offline'}${battery.usb.type ? ` · ${battery.usb.type}` : ''}`
                  : 'not present'
              }
            />
          </div>
        ) : (
          <p className="text-[13px] text-ink3">Battery not reported</p>
        )}
      </Card>
    </div>
  )
}
