import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import { rsrpColorClass } from '../../format'
import type { CellReading } from '../../types'
import { Card, Skeleton } from '../../ui/primitives'

function fmt(v: number | undefined | null, digits = 1): string {
  return v == null ? '\u2014' : v.toFixed(digits)
}

function CellTable({ rows }: { rows: { tag: string; cell: CellReading }[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[12.5px]">
        <thead>
          <tr className="text-ink3">
            <th className="py-1 pr-3 font-medium">Carrier</th>
            <th className="tnum py-1 pr-3 font-medium">PCI</th>
            <th className="tnum py-1 pr-3 font-medium">RSRP</th>
            <th className="tnum py-1 pr-3 font-medium">RSRQ</th>
            <th className="tnum py-1 pr-3 font-medium">RSSI</th>
            <th className="tnum py-1 font-medium">SINR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ tag, cell }, i) => (
            <tr key={i} className="border-t border-line/8">
              <td className="py-1 pr-3 text-ink2">{tag}</td>
              <td className="tnum py-1 pr-3">{cell.pci}</td>
              <td className={`tnum py-1 pr-3 ${rsrpColorClass(cell.rsrp_dbm)}`}>{fmt(cell.rsrp_dbm)}</td>
              <td className="tnum py-1 pr-3">{fmt(cell.rsrq_db)}</td>
              <td className="tnum py-1 pr-3">{fmt(cell.rssi_dbm)}</td>
              <td className="tnum py-1">{fmt(cell.sinr_db)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="mt-2 text-[12px] text-ink3">No cells reported</p>}
    </div>
  )
}

export default function Cells() {
  const cells = usePoll('cells', api.cells, 5000)
  const data = cells.data

  if (!data && !cells.error) return <Skeleton className="h-64" />
  if (!data) return <p className="text-[13px] text-danger">{cells.error}</p>

  const rows: { tag: string; cell: CellReading }[] = []
  if (data.intra_freq) {
    const band = data.intra_freq.band ? `B${data.intra_freq.band}` : 'LTE'
    for (const [i, cell] of (data.intra_freq.cells ?? []).entries()) {
      rows.push({ tag: i === 0 ? `${band} serving` : band, cell })
    }
  }
  for (const group of data.inter_freq ?? []) {
    const tag = `B${group.band ?? '?'} @${group.earfcn}`
    for (const cell of group.cells ?? []) rows.push({ tag, cell })
  }

  return (
    <div className="space-y-4">
      <Card title="LTE serving + neighbour cells">
        <CellTable rows={rows} />
      </Card>
      {data.nr && (
        <Card title="NR measurement">
          <p className="tnum text-[13px] text-ink">
            {data.nr.band ?? 'NR'} · ARFCN {data.nr.arfcn ?? '\u2014'}
          </p>
        </Card>
      )}
    </div>
  )
}
