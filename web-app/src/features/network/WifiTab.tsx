import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import { IWifi } from '../../icons'
import { Card, Chip, Row, Skeleton } from '../../ui/primitives'

export default function WifiTab() {
  const wifi = usePoll('wifi', api.wifiStatus, 10000)
  const data = wifi.data

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

  const profiles = data.profiles ?? []

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <Card title="Access point">
        <div className="mb-2 flex items-center gap-2">
          <Chip tone={data.enabled ? 'ok' : 'default'}>
            <IWifi size={12} /> AP {data.enabled ? 'on' : 'off'}
          </Chip>
          <Chip tone={data.feature_enabled ? 'ok' : 'default'}>
            Wi-Fi {data.feature_enabled ? 'enabled' : 'disabled'}
          </Chip>
          {data.country && <Chip>Region {data.country}</Chip>}
        </div>
        <Row label="Max clients" value={data.max_clients ?? '\u2014'} />
        <Row label="Associated stations" value={data.associated_stations ?? '\u2014'} />
        {!data.enabled && (
          <p className="mt-2 text-[12px] text-ink3">
            The AP is disabled, so SSID and security details cannot be read — the
            firmware's Wi-Fi CLI stalls on profile queries until the AP is on.
          </p>
        )}
      </Card>

      <Card title="Profiles">
        {profiles.length > 0 ? (
          <div className="space-y-2">
            {profiles.map((p, i) => (
              <div key={i} className="rounded-lg border border-line/8 bg-surface2/40 px-3 py-2">
                <p className="text-[13px] font-semibold text-ink">{p.ssid ?? '(hidden)'}</p>
                <p className="text-[11px] text-ink3">
                  {[p.interface, p.security, p.channel ? `ch ${p.channel}` : null]
                    .filter(Boolean)
                    .join(' · ') || '\u2014'}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-ink3">No profile details available.</p>
        )}
      </Card>

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
          {Object.entries(data.channels ?? {}).map(([band, channels]) => (
            <div key={band}>
              <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-ink2">
                {band} GHz channels
              </p>
              <div className="flex flex-wrap gap-1.5">
                {channels.map((c) => (
                  <Chip key={c}>{c}</Chip>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
