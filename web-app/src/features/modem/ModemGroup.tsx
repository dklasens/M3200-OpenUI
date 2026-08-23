import { useState } from 'react'
import { Tabs } from '../../ui/Tabs'
import SmsTab from './SmsTab'
import ApnTab from './ApnTab'
import DataTab from './DataTab'

type Tab = 'sms' | 'apn' | 'data'

export default function ModemGroup() {
  const [tab, setTab] = useState<Tab>('data')

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-ink">Modem</h1>
        <p className="mt-0.5 text-[13px] text-ink2">Data usage, SMS inbox and APN profiles</p>
      </div>

      <Tabs
        tabs={[
          { id: 'data', label: 'Data usage' },
          { id: 'sms', label: 'SMS' },
          { id: 'apn', label: 'APN' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === 'data' && <DataTab />}
      {tab === 'sms' && <SmsTab />}
      {tab === 'apn' && <ApnTab />}
    </div>
  )
}
