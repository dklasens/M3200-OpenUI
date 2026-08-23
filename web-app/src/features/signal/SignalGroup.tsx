import { useState } from 'react'
import { Tabs } from '../../ui/Tabs'
import Overview from './Overview'
import Bands from './Bands'
import Aggregation from './Aggregation'
import Cells from './Cells'

type Tab = 'overview' | 'bands' | 'aggregation' | 'cells'

export default function SignalGroup() {
  const [tab, setTab] = useState<Tab>('overview')

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-ink">Signal</h1>
        <p className="mt-0.5 text-[13px] text-ink2">
          Live radio metrics, band preferences and carrier aggregation
        </p>
      </div>

      <Tabs
        tabs={[
          { id: 'overview', label: 'Overview' },
          { id: 'bands', label: 'Band control' },
          { id: 'aggregation', label: 'Aggregation' },
          { id: 'cells', label: 'Cells' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === 'overview' && <Overview />}
      {tab === 'bands' && <Bands />}
      {tab === 'aggregation' && <Aggregation />}
      {tab === 'cells' && <Cells />}
    </div>
  )
}
