// Agent API bindings + response mappers.
//
// The M3200 agent returns structured QMI-decoded JSON (no string parsing of
// vendor netinfo blobs). The route surface below must stay in lockstep with
// the agent's ROUTES table — scripts/check-api-contract.py enforces it.

import { get, post, put } from './client'
import type {
  AtSendResult,
  ApnResult,
  BandApplyResult,
  BandDuration,
  BandsInfo,
  BandSelection,
  BatteryInfo,
  CaCombinations,
  CaInfo,
  CellsInfo,
  ClientsInfo,
  CpuInfo,
  DeviceInfo,
  HomeData,
  LoggerDownload,
  LoggerStatus,
  MemInfo,
  NrCaValidation,
  ProcessListResult,
  SignalInfo,
  SmsListResult,
  StockStatus,
  SystemInfo,
  ThermalInfo,
  UpdateCheckResult,
  UpdateSettings,
  UpdateStatus,
  WifiStatus,
} from '../types'

// ── EARFCN / NR-ARFCN to frequency (MHz) ─────────────────────────────────────

const LTE_BANDS: Record<number, { fdl_low: number; noffs_dl: number }> = {
  1: { fdl_low: 2110, noffs_dl: 0 },
  2: { fdl_low: 1930, noffs_dl: 600 },
  3: { fdl_low: 1805, noffs_dl: 1200 },
  4: { fdl_low: 2110, noffs_dl: 1950 },
  5: { fdl_low: 869, noffs_dl: 2400 },
  7: { fdl_low: 2620, noffs_dl: 2750 },
  8: { fdl_low: 925, noffs_dl: 3450 },
  12: { fdl_low: 729, noffs_dl: 5010 },
  13: { fdl_low: 746, noffs_dl: 5180 },
  17: { fdl_low: 734, noffs_dl: 5730 },
  18: { fdl_low: 860, noffs_dl: 5850 },
  19: { fdl_low: 875, noffs_dl: 6000 },
  20: { fdl_low: 791, noffs_dl: 6150 },
  25: { fdl_low: 1930, noffs_dl: 8040 },
  26: { fdl_low: 859, noffs_dl: 8690 },
  28: { fdl_low: 758, noffs_dl: 9210 },
  40: { fdl_low: 2300, noffs_dl: 38650 },
  42: { fdl_low: 3400, noffs_dl: 41590 },
  43: { fdl_low: 3600, noffs_dl: 43590 },
  48: { fdl_low: 3550, noffs_dl: 55240 },
  66: { fdl_low: 2110, noffs_dl: 66436 },
}

export function earfcnToFreq(earfcn: number, bandNum: number): number | undefined {
  const band = LTE_BANDS[bandNum]
  if (!band) return undefined
  return band.fdl_low + 0.1 * (earfcn - band.noffs_dl)
}

export function nrarfcnToFreq(arfcn: number): number | undefined {
  if (arfcn <= 599999) return 0.005 * arfcn
  if (arfcn <= 2016666) return 3000 + 0.015 * (arfcn - 600000)
  if (arfcn <= 3279165) return 24250 + 0.06 * (arfcn - 2016667)
  return undefined
}

// ── Derived radio view ────────────────────────────────────────────────────────

export interface CarrierView {
  label: string // "PCC", "SCC0", "SA", "SCG"
  rat: 'lte' | 'nr'
  band: string // "B7", "n78"
  pci?: number | null
  channel?: number | null
  bandwidth_mhz?: number | null
  freq?: number
}

/** Flatten ca + system info into the carrier chips shown by Home and Signal. */
export function deriveCarriers(ca: CaInfo | null, system: SystemInfo | null): CarrierView[] {
  const carriers: CarrierView[] = []
  const pcc = ca && !ca.error ? ca.pcc : null
  if (pcc && pcc.band) {
    carriers.push({
      label: 'PCC',
      rat: 'lte',
      band: `B${pcc.band}`,
      pci: pcc.pci,
      channel: pcc.earfcn,
      bandwidth_mhz: pcc.dl_bw_mhz,
      freq: earfcnToFreq(pcc.earfcn ?? 0, pcc.band),
    })
    for (const [i, scc] of (ca?.scc ?? []).entries()) {
      if (!scc.band) continue
      carriers.push({
        label: `SCC${i}`,
        rat: 'lte',
        band: `B${scc.band}`,
        pci: scc.pci,
        channel: scc.earfcn,
        bandwidth_mhz: scc.dl_bw_mhz,
        freq: earfcnToFreq(scc.earfcn ?? 0, scc.band),
      })
    }
  }
  const nr = system && !system.error ? system.nr : null
  if (nr && nr.band && nr.pci != null) {
    carriers.push({
      label: pcc ? 'SCG' : 'SA',
      rat: 'nr',
      band: String(nr.band).startsWith('n') ? String(nr.band) : `n${nr.band}`,
      pci: nr.pci,
      channel: nr.arfcn,
      bandwidth_mhz: nr.bandwidth_mhz ?? null,
      freq: nr.arfcn ? nrarfcnToFreq(nr.arfcn) : undefined,
    })
  }
  return carriers
}

/** Overall mode pill: 5G SA / 5G NSA / LTE / searching. */
export function deriveMode(ca: CaInfo | null, system: SystemInfo | null): string {
  const nr = system && !system.error ? system.nr : null
  const lte = system && !system.error ? system.lte : null
  const nrActive = !!nr && nr.pci != null && !!nr.band
  const lteActive = (!!lte && lte.cell_id != null) || (!!ca && !ca.error && !!ca.pcc)
  if (nrActive && lteActive) return '5G NSA'
  if (nrActive) return '5G SA'
  if (lteActive) return 'LTE'
  return 'searching'
}

export function signalBars(stock: StockStatus | null): number | undefined {
  const bars = parseInt(String(stock?.statusBarSignalBars ?? ''), 10)
  return Number.isFinite(bars) ? bars : undefined
}

// ── API surface (mirrors the agent ROUTES table) ──────────────────────────────

const CONFIRM_BANDS = { 'X-M3200-Confirm': 'apply-bands' }
const CONFIRM_DESTRUCTIVE = { 'X-Confirm': 'true' }

export const api = {
  // Batched heartbeat
  home: () => get('/api/dashboard').then((d) => d as unknown as HomeData),

  // Radio
  signal: () => get('/api/signal').then((d) => d as unknown as SignalInfo),
  ca: () => get('/api/ca').then((d) => d as unknown as CaInfo),
  caCombinations: () => get('/api/ca/combinations').then((d) => d as unknown as CaCombinations),
  caValidation: () => get('/api/ca/validation').then((d) => d as unknown as NrCaValidation),
  cells: () => get('/api/cells').then((d) => d as unknown as CellsInfo),
  bands: () => get('/api/bands').then((d) => d as unknown as BandsInfo),
  bandsApply: (selection: BandSelection, duration: BandDuration) =>
    post('/api/bands/apply', { ...selection, duration }, CONFIRM_BANDS).then(
      (d) => d as unknown as BandApplyResult,
    ),
  bandsRestore: (duration: BandDuration) =>
    post('/api/bands/restore', { duration }, CONFIRM_BANDS).then(
      (d) => d as unknown as BandApplyResult,
    ),

  // Device / system status
  device: () => get('/api/device').then((d) => d as unknown as DeviceInfo),
  cpu: () => get('/api/cpu').then((d) => d as unknown as CpuInfo),
  memory: () => get('/api/memory').then((d) => d as unknown as MemInfo),
  thermal: () => get('/api/thermal').then((d) => d as unknown as ThermalInfo),
  battery: () => get('/api/battery').then((d) => d as unknown as BatteryInfo),
  clients: () => get('/api/clients').then((d) => d as unknown as ClientsInfo),
  wifiStatus: () => get('/api/wifi/status').then((d) => d as unknown as WifiStatus),
  wifiSettingsSet: (enabled: boolean) =>
    put('/api/wifi/settings', { enabled }).then((d) => d as unknown as WifiStatus),
  smsList: () => get('/api/sms/list').then((d) => d as unknown as SmsListResult),
  apn: () => get('/api/modem/apn').then((d) => d as unknown as ApnResult),
  top: () => get('/api/system/top').then((d) => d as unknown as ProcessListResult),

  // Actions
  restartAgent: () => post('/api/system/restart-agent', {}, CONFIRM_DESTRUCTIVE),
  reboot: () => post('/api/device/reboot', {}, CONFIRM_DESTRUCTIVE),
  atSend: (command: string) =>
    post('/api/at/send', { command }).then((d) => d as unknown as AtSendResult),

  // Signal logger
  loggerSignalStart: (duration_secs: number, interval_secs: number) =>
    post('/api/logger/signal/start', { duration_secs, interval_secs }).then(
      (d) => d as unknown as LoggerStatus,
    ),
  loggerSignalStop: () =>
    post('/api/logger/signal/stop', {}).then((d) => d as unknown as LoggerStatus),
  loggerSignalStatus: () =>
    get('/api/logger/signal/status').then((d) => d as unknown as LoggerStatus),
  loggerSignalDownload: () =>
    get('/api/logger/signal/download').then((d) => d as unknown as LoggerDownload),

  // Updates
  updateStatus: () => get('/api/update/status').then((d) => d as unknown as UpdateStatus),
  updateCheck: () =>
    post('/api/update/check', {}).then((d) => d as unknown as UpdateCheckResult),
  updateInstall: (allowSame: boolean) =>
    post('/api/update/install', { allow_same: allowSame }, CONFIRM_DESTRUCTIVE).then(
      (d) => d as unknown as UpdateStatus,
    ),
  updateSettings: () =>
    get('/api/update/settings').then((d) => d as unknown as UpdateSettings),
  updateSettingsSet: (body: Partial<UpdateSettings>) =>
    put('/api/update/settings', body).then((d) => d as unknown as UpdateSettings),

  // Auth
  changePassword: (current_password: string, new_password: string) =>
    post('/api/auth/password', { current_password, new_password }),
}
