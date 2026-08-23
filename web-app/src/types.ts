// Shared domain types for the M3200 agent API.

// ── Radio ─────────────────────────────────────────────────────────────────────

export interface LteSignal {
  rssi_dbm?: number | null
  rsrq_db?: number | null
  rsrp_dbm?: number | null
  snr_db?: number | null
}

export interface NrSignal {
  rsrp_dbm?: number | null
  rsrq_db?: number | null
  snr_db?: number | null
}

export interface SignalInfo {
  lte?: LteSignal
  nr?: NrSignal
  error?: string
}

export interface CaComponent {
  band?: number | null
  dl_bw_mhz?: number | null
  pci?: number | null
  earfcn?: number | null
  state?: number
}

export interface CaInfo {
  pcc?: CaComponent | null
  scc?: CaComponent[]
  total_dl_bw_mhz?: number
  error?: string
}

export interface LteSystemInfo {
  domain?: number
  roaming?: number
  forbidden?: number
  cell_id?: number | null
  mcc?: string
  mnc?: string
  tac?: number | null
}

export interface NrSystemInfo {
  service_status?: number
  true_service_status?: number
  preferred_data_path?: boolean
  pci?: number | null
  arfcn?: number | null
  band?: string | null
  plmn?: string
  /** Live NR channel bandwidth in MHz (msgbus, cross-checked vs QMI). */
  bandwidth_mhz?: number | null
}

export interface SystemInfo {
  lte?: LteSystemInfo
  nr?: NrSystemInfo
  eutra_with_nr5g?: boolean
  error?: string
}

export interface EndcInfo {
  endc_enabled?: boolean
  error?: string
}

export interface CellReading {
  pci: number
  rsrq_db: number
  rsrp_dbm: number
  rssi_dbm: number
  sinr_db: number
}

export interface IntraFreqCells {
  ue_in_idle?: boolean
  tac?: number
  cell_id?: number
  earfcn?: number
  band?: number | null
  serving_pci?: number
  cells?: CellReading[]
}

export interface InterFreqGroup {
  earfcn?: number
  band?: number | null
  cells?: CellReading[]
}

export interface CellsInfo {
  intra_freq?: IntraFreqCells | null
  inter_freq?: InterFreqGroup[]
  nr?: { arfcn?: number; band?: string | null } | null
  plmn?: string
  error?: string
}

// ── Band control ──────────────────────────────────────────────────────────────

export interface BandPreferences {
  mode_pref_mask?: number
  mode_pref?: string[]
  lte_bands?: number[]
  lte_bands_ext?: number[]
  nr5g_sa_bands?: number[]
  nr5g_nsa_bands?: number[]
  error?: string
}

export interface BandCapabilities {
  lte_bands?: number[]
  lte_bands_ext?: number[]
  nr5g_bands?: number[]
  nr5g_sa_bands?: number[]
  nr5g_nsa_bands?: number[]
  error?: string
}

export interface BandSelection {
  lte_bands: number[]
  nr5g_sa_bands: number[]
  nr5g_nsa_bands: number[]
}

export interface BandControl {
  write_enabled?: boolean
  permanent_enabled?: boolean
  baseline?: BandSelection | null
}

export interface BandsInfo {
  preferences: BandPreferences
  capabilities: BandCapabilities
  control: BandControl
}

export type BandDuration = 'power_cycle' | 'permanent'

export interface BandApplyResult {
  ok: boolean
  duration: BandDuration
  requested: BandSelection
  actual: BandSelection
  baseline: BandSelection | null
}

// ── CA capability data ────────────────────────────────────────────────────────

export interface CaCapabilityComponent {
  rat: 'lte' | 'nr'
  band: number
  class?: string
}

export interface CaCapabilityEntry {
  index?: number
  label: string
  is_ca?: boolean
  components?: CaCapabilityComponent[]
}

export interface ObservedLayout {
  key: string
  label: string
  components: {
    rat: 'lte' | 'nr'
    role: string
    band: number
    bandwidth_mhz?: number | null
    pci?: number | null
    channel?: number | null
    state?: number
  }[]
  first_seen: number
  last_seen: number
  seen_count: number
}

export interface NrCaValidationCase {
  requested_sa_bands?: number[]
  label?: string
  scell_configured?: boolean
  capture?: { completed_at?: number | string }
}

export interface NrCaValidation {
  schema_version?: number
  cases?: NrCaValidationCase[]
  conclusion?: { max_component_count?: number }
}

export interface CaCombinations {
  schema_version?: number
  capture?: { network?: string; scope?: string; completed_at?: number | string }
  summary?: {
    lte_ca_configurations?: number
    mrdc_configurations?: number
    nr_ca_configurations?: number
  }
  lte?: CaCapabilityEntry[]
  mrdc?: CaCapabilityEntry[]
  nr?: CaCapabilityEntry[]
  active?: ObservedLayout | null
  observed?: ObservedLayout[]
  nr_ca_validation?: NrCaValidation | null
}

// ── Device / system ───────────────────────────────────────────────────────────

export interface DeviceInfo {
  manufacturer?: string
  model?: string
  firmware_revision?: string
  hardware_revision?: string
  imei?: string | null
  imsi?: string | null
  iccid?: string | null
  uptime_secs?: number
  load_avg?: number[]
  error?: string
}

export interface CpuInfo {
  overall: number
  cores: number[]
}

export interface MemInfo {
  total_kb: number
  used_kb: number
  free_kb: number
  usage_pct: number
}

export interface ThermalInfo {
  available: boolean
  cpu?: number
  modem?: number
  modem_skin?: number
  battery?: number
  charger_skin?: number
  connector?: number
  ambient?: number
  pmic?: number
}

export interface BatteryInfo {
  available: boolean
  percent?: number | null
  status?: string | null
  charging?: boolean
  temperature_c?: number | null
  voltage_mv?: number | null
  current_ma?: number | null
  health?: string | null
  technology?: string | null
  cycle_count?: number | null
  charge_full_mah?: number | null
  charge_full_design_mah?: number | null
  time_to_full_secs?: number | null
  usb?: { present?: boolean; online?: boolean; type?: string | null }
}

export interface ClientDevice {
  hostname: string
  interface?: string | null
}

export interface ClientsInfo {
  count?: number | null
  wifi_count?: number | null
  devices: ClientDevice[]
}

export interface WifiProfile {
  interface?: string | null
  ssid?: string | null
  security?: string | null
  channel?: string | null
}

export interface WifiStatus {
  available: boolean
  /** Master Wi-Fi feature (wifi_cli get_enable). */
  feature_enabled?: boolean
  /** AP actually broadcasting (ap_mode != 0). */
  enabled?: boolean
  country?: string | null
  ap_mode?: number | null
  max_clients?: number | null
  associated_stations?: number | null
  modes?: string[]
  channels?: Record<string, string[]>
  profiles?: WifiProfile[]
}

export interface SmsMessage {
  id: number
  number: string
  text: string
  date?: string
  status?: number | null
}

export interface SmsListResult {
  available: boolean
  messages: SmsMessage[]
}

export interface ApnProfile {
  cid: number
  protocol: string
  apn: string
}

export interface ApnResult {
  available: boolean
  profiles: ApnProfile[]
}

/** Live WAN throughput in bytes/sec, derived from the stock byte counters. */
export interface SpeedInfo {
  rx_bps: number
  tx_bps: number
  max_rx_bps: number
  max_tx_bps: number
}

/** Data usage for the current WAN connection (stock counters). */
export interface UsageInfo {
  rx_bytes: number
  tx_bytes: number
  total_bytes: number
  duration_secs: number
  connected: boolean
}

export interface StockStatus {
  statusBarNetwork?: string | null
  statusBarNetworkID?: string | null
  statusBarTechnology?: string | null
  statusBarConnectionState?: string | null
  statusBarBatteryPercent?: string | null
  statusBarSimStatus?: string | null
  statusBarSignalBars?: string | null
  statusBarWiFiEnabled?: number | string | null
  statusBarClientListSize?: string | null
  [key: string]: unknown
}

export interface ProcessInfo {
  pid: number
  name: string
  state: string
  cpu_pct: number
  rss_kb: number
}

export interface ProcessListResult {
  processes: ProcessInfo[]
  total_count: number
}

export interface LoggerStatus {
  running: boolean
  samples: number
  elapsed_secs: number
  duration_secs: number
  interval_secs: number
  path?: string | null
}

export interface LoggerDownload {
  csv: string
}

export interface AtSendResult {
  command: string
  response: string
  elapsed_ms?: number
}

export interface UpdateCheckResult {
  repo: string
  current_version: string
  latest_version: string
  tag?: string | null
  name?: string | null
  published_at?: string | null
  notes?: string
  size?: number | null
  update_available: boolean
  same_version: boolean
}

export interface UpdateInstallLog {
  started: number
  finished?: number
  ok?: boolean
  message?: string
  steps?: string[]
  apply?: { rc: number; output: string } | null
}

export interface UpdateStatus {
  repo: string
  busy: boolean
  error?: string | null
  current_version: string
  last_check?: { ts: number; result: UpdateCheckResult } | null
  last_install?: UpdateInstallLog | null
}

export interface UpdateSettings {
  enabled: boolean
  interval_secs: number
}

/** One merged poll of /api/dashboard — the app's heartbeat request. */
export interface HomeData {
  ts: number
  signal: SignalInfo | null
  ca: CaInfo | null
  system: SystemInfo | null
  endc: EndcInfo | null
  stock: StockStatus | null
  mode: string
  battery: BatteryInfo | null
  thermal: ThermalInfo | null
  cpu: CpuInfo | null
  memory: MemInfo | null
  clients: ClientsInfo | null
  speed: SpeedInfo | null
  device: DeviceInfo | null
  usage: UsageInfo | null
}
