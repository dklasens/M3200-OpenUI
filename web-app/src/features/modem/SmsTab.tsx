import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import { IInbox, IRefresh } from '../../icons'
import { Button } from '../../ui/controls'
import { Card, Chip, Empty, Skeleton } from '../../ui/primitives'

export default function SmsTab() {
  const sms = usePoll('sms', api.smsList, 30000)
  const data = sms.data

  if (!data && !sms.error) return <Skeleton className="h-64" />
  if (!data) return <p className="text-[13px] text-danger">{sms.error}</p>
  if (!data.available) {
    return (
      <Card>
        <p className="text-[13px] text-ink3">The AT bridge did not answer for SMS.</p>
      </Card>
    )
  }

  return (
    <Card
      title="Inbox"
      action={
        <Button size="sm" variant="ghost" onClick={sms.refresh}>
          <IRefresh size={13} /> Refresh
        </Button>
      }
      pad={false}
    >
      {data.messages.length > 0 ? (
        <div className="divide-y divide-line/6">
          {data.messages.map((m) => (
            <div key={m.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="tnum text-[13px] font-semibold text-ink">{m.number}</span>
                <span className="flex items-center gap-2 text-[11px] text-ink3">
                  {m.status === 0 && <Chip tone="accent">unread</Chip>}
                  {m.date}
                </span>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-[13px] text-ink2">{m.text}</p>
            </div>
          ))}
        </div>
      ) : (
        <Empty
          icon={<IInbox size={26} />}
          title="Inbox is empty"
          body="Messages are read from the SIM/device store via the AT bridge (PDU decoded)."
        />
      )}
    </Card>
  )
}
