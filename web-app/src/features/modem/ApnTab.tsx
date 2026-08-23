import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import { Card, Chip, Skeleton } from '../../ui/primitives'

export default function ApnTab() {
  const apn = usePoll('apn', api.apn, 60000)
  const data = apn.data

  if (!data && !apn.error) return <Skeleton className="h-48" />
  if (!data) return <p className="text-[13px] text-danger">{apn.error}</p>

  return (
    <Card title="PDP contexts (read-only)" pad={false}>
      <div className="overflow-x-auto px-4 py-3">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="border-b border-line/8 text-left text-[11px] uppercase tracking-wider text-ink3">
              <th className="pb-1.5 pr-3 font-semibold">CID</th>
              <th className="pb-1.5 pr-3 font-semibold">Protocol</th>
              <th className="pb-1.5 font-semibold">APN</th>
            </tr>
          </thead>
          <tbody>
            {(data.profiles ?? []).map((p) => (
              <tr key={p.cid} className="border-b border-line/6 last:border-0">
                <td className="tnum py-1.5 pr-3 text-ink3">{p.cid}</td>
                <td className="py-1.5 pr-3">
                  <Chip>{p.protocol}</Chip>
                </td>
                <td className="tnum py-1.5 font-medium text-ink">{p.apn}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(data.profiles ?? []).length === 0 && (
          <p className="text-[13px] text-ink3">No PDP contexts reported.</p>
        )}
        <p className="mt-2 text-[11px] text-ink3">
          Read from `AT+CGDCONT?`. Editing APNs is not exposed: no safe write path has
          been identified on this firmware.
        </p>
      </div>
    </Card>
  )
}
