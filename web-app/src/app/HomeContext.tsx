/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { api } from '../data/api'
import { usePoll, type PollResult } from '../data/poll'
import type { HomeData } from '../types'

/**
 * The home poll is the app's heartbeat: one batched request that feeds the
 * Home screen, the Signal group and the global alert banner. Those screens
 * read it instead of re-fetching the same QMI data.
 *
 * `fast` is set for the groups that render live radio data; elsewhere the poll
 * only feeds the alert banner, so it idles. Changing the interval does not
 * restart the loop (see `usePoll`), so switching groups costs no extra request.
 */
const HomeContext = createContext<PollResult<HomeData> | null>(null)

export function HomeProvider({ fast, children }: { fast: boolean; children: ReactNode }) {
  const poll = usePoll('home', api.home, fast ? 3000 : 15000)
  return <HomeContext.Provider value={poll}>{children}</HomeContext.Provider>
}

export function useHome(): PollResult<HomeData> {
  const ctx = useContext(HomeContext)
  if (!ctx) throw new Error('useHome outside HomeProvider')
  return ctx
}

// ── Alerts derived from the home poll (no extra requests) ─────────────────────

export interface Alert {
  level: 'warning' | 'error'
  message: string
}

export function deriveAlerts(data: HomeData | null): Alert[] {
  if (!data) return []
  const alerts: Alert[] = []
  const { battery, thermal, signal } = data

  if (battery && battery.available) {
    const temp = battery.temperature_c
    if (temp != null && temp >= 50) {
      alerts.push({ level: 'error', message: `Battery temperature critically high (${temp.toFixed(0)}°C)` })
    } else if (temp != null && temp >= 45) {
      alerts.push({ level: 'warning', message: `Battery temperature high (${temp.toFixed(0)}°C)` })
    }
    if (!battery.charging) {
      const pct = battery.percent
      if (pct != null && pct <= 5) {
        alerts.push({ level: 'error', message: `Battery critically low (${pct}%)` })
      } else if (pct != null && pct <= 15) {
        alerts.push({ level: 'warning', message: `Battery low (${pct}%)` })
      }
    }
  }

  if (thermal?.cpu != null) {
    if (thermal.cpu >= 95) {
      alerts.push({ level: 'error', message: `CPU temperature critically high (${thermal.cpu}°C)` })
    } else if (thermal.cpu >= 80) {
      alerts.push({ level: 'warning', message: `CPU temperature elevated (${thermal.cpu}°C)` })
    }
  }

  if (signal && !signal.error && data.mode === 'searching') {
    alerts.push({ level: 'warning', message: 'No serving cell — modem is searching' })
  }

  return alerts
}

export function useAlerts(): Alert[] {
  const { data } = useHome()
  return useMemo(() => deriveAlerts(data), [data])
}
