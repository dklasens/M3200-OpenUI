import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import { ICable, ILaptop, IPhone, IUsers, IWifi } from '../../icons'
import { Card, Chip, Empty, Skeleton } from '../../ui/primitives'

function mediumIcon(iface?: string | null) {
  const kind = (iface ?? '').toLowerCase()
  if (kind.includes('wifi') || kind.includes('wlan')) return <IWifi size={15} />
  if (kind.includes('eth')) return <ICable size={15} />
  if (kind.includes('usb')) return <ILaptop size={15} />
  return <IPhone size={15} />
}

export default function ClientsTab() {
  const clients = usePoll('clients', api.clients, 10000)
  const data = clients.data

  if (!data && !clients.error) return <Skeleton className="h-48" />
  if (!data) return <p className="text-[13px] text-danger">{clients.error}</p>

  return (
    <Card
      title="Connected clients"
      action={
        data.count != null ? (
          <Chip tone="accent">
            <IUsers size={12} /> {data.count}
          </Chip>
        ) : undefined
      }
      pad={false}
    >
      {data.devices.length > 0 ? (
        <div className="overflow-x-auto px-4 py-3">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-line/8 text-left text-[11px] uppercase tracking-wider text-ink3">
                <th className="pb-1.5 pr-3 font-semibold">Device</th>
                <th className="pb-1.5 font-semibold">Connection</th>
              </tr>
            </thead>
            <tbody>
              {data.devices.map((d, i) => (
                <tr key={i} className="border-b border-line/6 last:border-0">
                  <td className="py-1.5 pr-3 font-medium text-ink">
                    <span className="inline-flex items-center gap-2">
                      <span className="text-ink3">{mediumIcon(d.interface)}</span>
                      {d.hostname}
                    </span>
                  </td>
                  <td className="py-1.5 text-ink2">{d.interface ?? '\u2014'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty
          icon={<IUsers size={26} />}
          title="No connected clients"
          body="Devices tethered over USB, Ethernet or Wi-Fi appear here."
        />
      )}
    </Card>
  )
}
