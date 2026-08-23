import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../data/api'
import { usePoll } from '../../data/poll'
import { formatBytes, formatDuration } from '../../format'
import type { LoggerDownload, LoggerStatus, ProcessListResult } from '../../types'
import { IInfo, IRefresh } from '../../icons'
import { Button, Field, Select } from '../../ui/controls'
import { toastError } from '../../ui/feedback'
import { Card, Empty, Meter } from '../../ui/primitives'

function downloadCsv(csv: string, prefix: string) {
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${prefix}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const DURATION_OPTS = [
  [300, '5 minutes'],
  [900, '15 minutes'],
  [1800, '30 minutes'],
  [3600, '1 hour'],
  [7200, '2 hours'],
  [14400, '4 hours'],
  [28800, '8 hours'],
  [43200, '12 hours'],
  [86400, '24 hours'],
] as const

const INTERVAL_OPTS = [
  [2, '2 seconds'],
  [3, '3 seconds'],
  [5, '5 seconds'],
  [10, '10 seconds'],
  [30, '30 seconds'],
  [60, '1 minute'],
] as const

// ── Signal logger ─────────────────────────────────────────────────────────────

function SignalLogger() {
  const [duration, setDuration] = useState(3600)
  const [interval, setInterval_] = useState(3)
  const [busy, setBusy] = useState(false)
  // Only worth watching closely while a run is in flight; idle is the common case.
  const [live, setLive] = useState(false)
  const { data: status, refresh } = usePoll<LoggerStatus>(
    'logger-signal',
    api.loggerSignalStatus,
    live ? 3000 : 15000,
  )

  const isRunning = status?.running ?? false
  useEffect(() => setLive(isRunning), [isRunning])

  async function handleStart() {
    setBusy(true)
    try {
      await api.loggerSignalStart(duration, interval)
      refresh()
    } catch (e) {
      toastError(e, 'Failed to start logger')
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    try {
      await api.loggerSignalStop()
      refresh()
    } catch (e) {
      toastError(e, 'Failed to stop logger')
    }
  }

  async function handleDownload() {
    try {
      const data: LoggerDownload = await api.loggerSignalDownload()
      downloadCsv(data.csv, 'm3200_signal_log')
    } catch (e) {
      toastError(e, 'No data to download')
    }
  }

  const progress = status && status.duration_secs > 0 ? (status.elapsed_secs / status.duration_secs) * 100 : 0

  return (
    <Card title="Signal logger">
      <p className="mb-3 text-[12px] text-ink2">
        Logs LTE/NR signal metrics (RSRP, RSRQ, RSSI, SINR) to CSV on the device. Maximum 24 hours.
      </p>

      {!isRunning && (
        <div className="mb-3 grid grid-cols-2 gap-2">
          <Field label="Duration">
            <Select value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
              {DURATION_OPTS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Interval">
            <Select value={interval} onChange={(e) => setInterval_(Number(e.target.value))}>
              {INTERVAL_OPTS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {!isRunning ? (
          <Button variant="primary" onClick={handleStart} loading={busy}>
            Start
          </Button>
        ) : (
          <Button variant="danger" onClick={handleStop}>
            Stop
          </Button>
        )}
        <Button variant="outline" onClick={handleDownload}>
          Download CSV
        </Button>
      </div>

      {status && (
        <div className="mt-3 grid grid-cols-3 gap-3 border-t border-line/8 pt-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-ink3">Status</p>
            <p className={`mt-0.5 text-[13px] font-bold ${isRunning ? 'text-ok' : 'text-ink3'}`}>
              {isRunning ? 'Running' : 'Stopped'}
            </p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-ink3">Samples</p>
            <p className="tnum mt-0.5 text-[13px] font-bold text-ink">{status.samples ?? 0}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-ink3">Elapsed</p>
            <p className="tnum mt-0.5 text-[13px] font-medium text-ink2">
              {formatDuration(status.elapsed_secs)} / {formatDuration(status.duration_secs)}
            </p>
          </div>
          {isRunning && <Meter pct={progress} className="col-span-3" />}
        </div>
      )}
    </Card>
  )
}

// ── AT console ────────────────────────────────────────────────────────────────

function AtConsole() {
  const [command, setCommand] = useState('')
  const [history, setHistory] = useState<{ cmd: string; response: string; error?: boolean }[]>([])
  const [busy, setBusy] = useState(false)
  const outputRef = useRef<HTMLDivElement>(null)

  async function handleSend() {
    if (!command.trim() || busy) return
    const cmd = command.trim()
    setCommand('')
    setBusy(true)
    try {
      const data = await api.atSend(cmd)
      setHistory((h) => [...h, { cmd, response: data.response || '(empty response)' }])
    } catch (e) {
      setHistory((h) => [...h, { cmd, response: (e as Error).message, error: true }])
    }
    setBusy(false)
    setTimeout(() => outputRef.current?.scrollTo(0, outputRef.current.scrollHeight), 50)
  }

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-1.5">
          AT console
          <span
            className="inline-flex cursor-help text-warn"
            title="The agent only accepts its allowlisted read-only AT queries."
            aria-label="AT command safety information"
          >
            <IInfo size={14} />
          </span>
        </span>
      }
    >
      <div role="alert" className="mb-3 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-[12px] text-warn">
        <strong>Safety:</strong> commands run through the device AT bridge. Only allowlisted read-only
        queries (CSQ, COPS?, CxREG?, CSCA?, CPMS?, CMGL/CMGR, CGDCONT?, GSN, CIMI,
        ICCID, NUM, CLAC, CUSD?) are accepted; anything that writes modem state is
        rejected.
      </div>

      <div
        ref={outputRef}
        className="mb-3 h-72 overflow-y-auto rounded-lg border border-line/8 bg-surface2/50 p-3 font-mono text-[12px]"
      >
        {history.length === 0 && (
          <p className="text-ink3">No commands sent yet. Try: AT+CSQ, AT+COPS?, AT+C5GREG?, AT+CPMS?</p>
        )}
        {history.map((h, i) => (
          <div key={i} className="mb-2">
            <p className="text-accent">{'>'} {h.cmd}</p>
            <p className={`whitespace-pre-wrap break-words ${h.error ? 'text-danger' : 'text-ok'}`}>{h.response}</p>
          </div>
        ))}
        {busy && <p className="animate-pulse text-ink3">Waiting for response…</p>}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="AT+COPS?"
          className="h-9 min-w-0 flex-1 rounded-lg border border-line/12 bg-surface2/50 px-3 font-mono text-[13px] text-ink outline-none transition-colors placeholder:text-ink3 focus:border-accent/60"
          autoComplete="off"
        />
        <Button variant="primary" onClick={handleSend} disabled={!command.trim()} loading={busy}>
          Send
        </Button>
      </div>
    </Card>
  )
}

// ── Processes ─────────────────────────────────────────────────────────────────

function Processes() {
  const [data, setData] = useState<ProcessListResult | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    try {
      setData(await api.top())
    } catch (e) {
      toastError(e, 'Failed to load processes')
    } finally {
      setBusy(false)
    }
  }, [])

  const procs = data?.processes ?? []

  return (
    <Card
      title="Top processes"
      action={
        <Button size="sm" variant="ghost" onClick={load} loading={busy}>
          <IRefresh size={13} /> {data ? 'Refresh' : 'Load'}
        </Button>
      }
      pad={false}
    >
      {data == null ? (
        <div className="p-4">
          <Empty title="Load on demand" body="Reading /proc for all processes is expensive — load when needed." />
        </div>
      ) : (
        <div className="overflow-x-auto px-4 py-3">
          <p className="mb-2 text-[12px] text-ink3">{data.total_count} processes · top {procs.length} by memory</p>
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-line/8 text-left text-[11px] uppercase tracking-wider text-ink3">
                <th className="pb-1.5 pr-3 font-semibold">PID</th>
                <th className="pb-1.5 pr-3 font-semibold">Name</th>
                <th className="pb-1.5 pr-3 font-semibold">State</th>
                <th className="pb-1.5 pr-3 text-right font-semibold">CPU%</th>
                <th className="pb-1.5 text-right font-semibold">Mem</th>
              </tr>
            </thead>
            <tbody>
              {procs.map((p) => (
                <tr key={p.pid} className="border-b border-line/6 last:border-0">
                  <td className="tnum py-1 pr-3 text-ink3">{p.pid}</td>
                  <td className="max-w-[180px] truncate py-1 pr-3 font-medium text-ink">{p.name}</td>
                  <td className="py-1 pr-3 text-ink2">{p.state}</td>
                  <td className="tnum py-1 pr-3 text-right text-ink2">{p.cpu_pct.toFixed(1)}</td>
                  <td className="tnum py-1 text-right text-ink2">{formatBytes(p.rss_kb * 1024)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

// ── Tab ───────────────────────────────────────────────────────────────────────

export default function ToolsTab() {
  return (
    <div className="space-y-3">
      <SignalLogger />
      <AtConsole />
      <Processes />
    </div>
  )
}
