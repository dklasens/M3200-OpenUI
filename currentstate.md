# M3200-OpenUI — Current State

Last updated: 2026-08-23 (session 5). See `device.md` for the full hardware/protocol reference.

## What works today

| Milestone | State |
|---|---|
| Persistent root SSH (port 22/2222, ECDSA key `artifacts/id_ecdsa`) | ✅ verified `uid=0` |
| Device recon (SDX62, writable ubifs, python3, Inseego `/opt/nvtl` stack) | ✅ done |
| Pure-Python QMI-over-QRTR client (no CID, no extra pkgs) | ✅ working |
| TLV decoders: signal, CA, system info, cells, band prefs, DMS caps | ✅ verified vs libqmi schema + live data |
| QRTR service enumeration (97 services, NAS @ node 3 port 58) | ✅ |
| `device.md` — full capabilities reference | ✅ written |
| On-device agent (`agent/`) — JSON API + dashboard on **http://192.168.1.1:8080/** | ✅ deployed, systemd `m3200-agent.service` enabled + active |
| MU5250-style port: React dashboard + bearer-token agent contract | ✅ phase 1 deployed + live-tested (session 5) |
| Phase 2: Network + Modem groups (clients, Wi-Fi, SMS, APN, data usage) | ✅ deployed + live-tested (session 5) |
| GitHub repo `dklasens/M3200-OpenUI` (public) + Actions release pipeline | ✅ v0.2-beta + v0.2.1 published |
| OTA updates: dashboard check/install vs GitHub releases (sha256, preflight, apply.sh hook) | ✅ live self-update 0.2-beta → 0.2.1 verified |
| Deploy script `scripts/deploy.ps1` (agent + built dashboard) | ✅ works |
| NR-SA capability assessment | ✅ done (see device.md) |
| Protected band-selection API and dashboard controls | ✅ deployed and live-tested |
| QMI band writes (until reboot and permanent) | ✅ exact readback; both reboot behaviours verified |
| Full hardware-reported band set selected permanently | ✅ survived reboot; Optus 5G reconnected |
| Unauthenticated root shell on TCP 9999 | ✅ removed; stayed closed across reboots |
| LTE CA / LTE+NR MR-DC capability capture and standards decode | ✅ deployed in API/UI |
| Vodafone NR-SA enable investigation | ✅ root cause found; n1 SA registration and data verified |
| SA-aware live UI (mode, band, bandwidth, PCI, NR-ARFCN) | ✅ deployed and live-tested |
| Vodafone NR-CA capability decode and controlled validation | ✅ n1+n28 and n1+n78 verified as 2CC; no 3CC advertised |

## Repo layout

```
exploit.py                  root exploit (OpenVPN tls-verify) -> persistent SSH
README.md                   exploit docs
device.md                   device specs / protocol reference (read this first)
currentstate.md             this file
artifacts/                  SSH key + exploit certs
MU5250-OpenUI-main/         reference project (ZTE MU5250) the UI was ported from
scripts/
  qrtr_probe.py             QRTR service scanner / QMI probe
  qmi.py                    standalone QMI probe (demos + band dump)
  diag_tcp_relay.py         loopback-only DIAG relay used through an SSH reverse tunnel
  capture_diag_ca.py        targeted four-record LTE/NR capability capture
  decode_rrc_capabilities.py  RRC capability-container decoder/inspector
  export_ca_combinations.py normalized standards-decoded combination export
  export_nr_ca_validation.py compact PCC/SCell evidence export from DIAG captures
  set_rat_mode.py           guarded generic RAT-mode isolation and restore helper
  set_nr_path.py            guarded SA/NSA band-mask isolation and restore helper
  lock_nsa.py               guarded combined LTE-anchor/NSA-only lock and restore
  lock_sa.py                guarded persistent SA band-lock/apply/restore helper
  m3200-boot-diag.sh        bounded early-boot power-state logger (disabled after test)
  reactivate_original_pdc.py guarded selection/activation of preserved Vodafone PDC ID
  probe_pdc_store.py        fixed-ID unselected signed-clone load/delete validation
  check-api-contract.py     agent ROUTES <-> dashboard api.ts <-> mock agent lockstep check
  deploy.ps1                build dashboard, push agent + www/, restart, health-check
agent/
  qmi.py                    QRTR/QMI library with decoders (agent copy)
  m3200_agent.py            bearer-token JSON API (25 routes) + static SPA server
  dashboard.html            legacy single-file dashboard (superseded; served at /legacy)
  ca-combinations.json      decoded LTE and LTE+NR capability dataset
  nr-ca-validation.json     controlled Vodafone SA PCC/SCell validation cases
  m3200-agent.service       systemd unit -> /data/m3200-openui/
web-app/
  src/                      React 19 + Vite + Tailwind dashboard (ported from MU5250)
  tools/mock_agent.py       fixture agent for hardware-free development + demos
  tools/demo.sh             mock + preview launcher
tests/
  test_band_control.py      QMI encoding, auth (lockout/sliding tokens), HTTP
                            envelope, band apply/restore, CA snapshot tests
```

On-device install location: `/data/m3200-openui/` (+ `www/` for the built
dashboard) and `/etc/systemd/system/m3200-agent.service`.

## Dashboard + agent contract (session 5 port)

- The MU5250 React dashboard and agent *contract* were ported; the device
  backends stayed the Python QMI/QRTR stack. The agent serves the built SPA
  and the API from one port (:8080, same origin, no CORS).
- Auth: `POST /api/auth/login` (password) issues bearer tokens with a sliding
  1 h expiry; 5 failed logins per IP arm a 30 s lockout. Every `/api/*` route
  except `/api/health` and login requires the token. The password lives
  root-only at `/data/m3200-openui/agent-password` (generated on first boot,
  printed by deploy.ps1); the salt at `auth-salt`.
- JSON envelope everywhere: `{"ok": true, "data": ...}` /
  `{"ok": false, "error": ...}`. `GET /api/dashboard` batches signal, CA,
  system, ENDC, stock status, battery, thermals (52 sysfs zones), CPU,
  memory, clients, speed, usage, device.
- Band writes now authorize via bearer token (or the root write token) plus
  `X-M3200-Confirm: apply-bands` and the same-origin check; the old
  cookie/nonce GUI session was removed. Baseline save/restore, capability
  validation and the permanent-write marker are unchanged.
- New system surface: `/api/cpu`, `/api/memory`, `/api/thermal`,
  `/api/battery`, `/api/clients`, `/api/system/top`,
  `/api/system/restart-agent`, `/api/device/reboot` (both need
  `X-Confirm: true`), `/api/at/send` (read-only AT allowlist via
  `read_atcmd`), `/api/logger/signal/*` (CSV signal logger).
- `scripts/check-api-contract.py` fails if the agent route table, the
  dashboard's calls and the mock agent drift apart (28 routes as of the
  phase-2 addition).
- Live-tested on-device: login, batched dashboard, thermal/battery/clients,
  AT allowlist (CFUN rejected 400), logger capture, write gating
  (400/401), and a zero-change band apply round-trip with exact readback.
- Phase 2 added `/api/wifi/status` (wifi_cli, every call timeout-guarded;
  `get_ap_profile`/`get_band_status` hang while the AP is off, so SSID detail
  is only readable with the AP on; `enabled` = ap_mode != 0, `feature_enabled`
  = master switch), `/api/network/clients` (stock devicesrefresh),
  `/api/sms/list` (inbox via `AT+CMGL=4`, PDU-decoded: GSM-7 + UCS-2, unit-
  tested) and `/api/modem/apn` (read-only `AT+CGDCONT?`). No APN/charge/
  Wi-Fi writes are exposed: no safe write path has been proven for them.
- Device quirks found while porting: DMS model string is literally "0"
  (agent overrides to M3200), `AT+ICCID` returns ERROR (nulled), NR signal
  sentinels are -32768 raw / -3276.8 after the 0.1-unit SNR scaling,
  `wifi_cli get_band_status`/`get_ap_profile` hang while the AP is disabled
  (phase-2 Wi-Fi work must timeout-guard every wifi_cli call), and
  `/sys/class/power_supply/battery/charge_control_limit{,_max}` exists
  (0..5) as a candidate charge-control lever for a later phase.

## Current live reading (Vodafone AU 505-03, SA)

- After the validation masks were restored, the device was healthy and registered
  on **5G SA n28, 15 MHz**, PCI 318, NR-ARFCN 159130; no LTE anchor was active.
- The live preference state was restored to all RATs, all 21 hardware-reported LTE
  bands, all seven hardware-reported SA bands, and an empty NSA mask. This is the
  deliberate post-test baseline, not the original Telstra carrier baseline.
- Recent NR RSRP was approximately -88 dBm. The temporary DIAG bridge and SSH tunnel
  were stopped after capture.
- The dashboard distinguishes the live NAS primary carrier from captured DIAG SCell
  evidence. It no longer presents a past aggregated layout as continuously active.

## Historical verified reading (Optus 505-02, NSA)

- LTE PCC B7 20 MHz (PCI 457→480, EARFCN 3350) + SCC B1 20 MHz (PCI 67, EARFCN 299)
- NR n78 100 MHz, ARFCN 633312
- LTE RSRP ≈ −102 dBm / RSRQ −11 dB / RSSI −69 dBm; NR RSRP ≈ −101 dBm, SNR 4 dB
- Neighbors: intra B7 (PCI 480, 198), inter B1 (PCI 67, 198, 423, 377, 87) w/ per-cell RSRP/RSRQ/RSSI
- Device: QUALCOMM INCORPORATED, fw `THN-1.33.1.1`, IMEI/IMSI readable via AT

## Current band-control state

- Hardware-reported LTE: **B1/2/3/4/5/7/8/12/13/17/18/19/20/25/26/28/40/42/43/48/66**.
- Hardware-reported NR: **n1/3/5/7/8/28/78**. DMS exposes one generic NR capability
  list; these are the only bands offered for both SA and NSA preference masks.
- **NR n40 is not reported.** LTE B40 is supported; those are different bands/RATs.
- The first write saved the carrier baseline in
  `/data/m3200-openui/band-baseline.json`: LTE B1/3/5/7/8/20/28 and NR
  n5/7/8/78 (SA and NSA).
- **Current restored state:** all RATs, the complete hardware-reported LTE mask, the
  complete hardware-reported SA mask, and an empty NSA mask. Vodafone is registered
  on n28 SA. The original Telstra carrier baseline remains separately recoverable.
- Earlier Vodafone NSA testing registered on B5 and later B3, but did not receive an
  NR SCG. The Vodafone capability response advertised only six MR-DC configurations,
  all based on B1/B3+n78; no B5+n78 combination was advertised. A controlled
  B1/B3+n78 test also remained LTE-only, so band-mask permission alone cannot force
  network scheduling.
- `/data/m3200-openui/nsa-lock-baseline.json` preserves the earlier full-band state,
  while `/data/m3200-openui/band-baseline.json` preserves the original carrier
  baseline. These do not revert the independent EFS SA-enable byte described below.
- The UI provides Current and All-hardware presets, separate LTE/SA/NSA selections,
  power-cycle/permanent duration, and baseline restore. Writes authenticate with the
  dashboard's bearer session; no token entry is required. Browser writes require the
  bearer token, same-origin `Origin`, and the explicit `X-M3200-Confirm` header. The
  root-only token remains available for maintenance scripts.
- The GUI accepts NSA-only or SA-only masks by allowing either NR path to be empty,
  while rejecting an empty LTE anchor selection or both NR paths empty. The live
  bearer-token flow was verified; a write without the confirmation header is rejected
  with HTTP 400 and an unauthenticated one with HTTP 401.

## Carrier-aggregation capability state

- A targeted Qualcomm DIAG capture recorded LTE RRC OTA (`0xB0C0`), LTE supported
  combinations (`0xB0CD`), NR RRC OTA (`0xB821`), and NR supported combinations
  (`0xB826`). The DIAG stream was carried only over a loopback SSH reverse tunnel;
  the temporary bridge and tunnel were removed after capture.
- A safe `AT+COPS=2` / `AT+COPS=0` reconnect caused Optus to request three
  `UECapabilityInformation` containers: `eutra`, `eutra-nr`, and `nr`.
- Standards decoding produced **89 LTE configurations**, of which **68 are CA
  entries collapsing to 11 band/class layouts**, and **65 LTE+NR MR-DC entries
  collapsing to 15 layouts**. All 21 hardware LTE bands appear as valid
  single-band configurations. The Optus MR-DC enquiry contains LTE B1/B3/B7/B28
  with n78.
- A fresh Vodafone SA attach was captured in
  `captures/vodafone-sa/sa-full-attach-20260821.dlf`. Its standards NR
  `supportedBandCombinationList` contains exactly five entries: n1; n1+n28 with UL
  on n1; n1+n78 with UL on n1; n1+n28 with UL on n28; and n1+n78 with UL on n78.
  It contains neither n28+n78 nor n1+n28+n78.
- Controlled persistent-mask tests under bounded traffic verified n28-only and
  n78-only service, **n28 PCC + n1 SCell**, and **n1 PCC + n78 SCell**. An n28+n78
  mask stayed n28-only. An n1+n28+n78 mask produced n28 PCC + one n1 SCell and never
  added n78; the maximum observed and advertised SA aggregation was therefore 2CC.
- `GET /api/ca/combinations` serves the decoded capability data and includes the
  controlled validation summary; `GET /api/ca/validation` serves the four Vodafone
  cases directly. The dashboard's **Vodafone SA verified** view keeps captured DIAG
  evidence separate from the live NAS primary-carrier reading.
- Live verification after deployment observed **B1 PCC + B7 SCC + n78 SCG**. The
  exact PCC/SCC roles can change as the network reschedules carriers.

### Can combinations be changed?

- Existing combinations can be made ineligible by removing one of their LTE or NR
  bands from the current preference masks. This is the only verified, supported
  control currently exposed.
- There is no discovered QMI/AT operation that adds, edits, prioritizes, or forces a
  CA/MR-DC combination. The eNB/gNB chooses the active combination from what the UE
  advertises and what the cell has deployed.
- The firmware contains distinct signed Qualcomm MCFG binaries for Optus, Telstra,
  and Vodafone AU. A SIM/profile change can therefore change carrier policy and the
  advertised list. Editing an MCFG or RFNV combination table would be an
  undocumented signed/calibrated modem change, not a safe dashboard feature; it
  could cause rejection, loss of service, or an invalid RF configuration.
- Seven decoded signed profiles were compared. Only the CMCC profile has the small
  proprietary NR RRC items `cap_feature_band_nr` and `pref_freq_list`; neither is a
  decoded CA-combination table, and the Australian profiles contain no equivalent.
  A 30-file RFNV correlation scan also found no schema-backed combination item.
  Consequently no MCFG/RFNV value met the agreed safety threshold and none was
  written.

## Controlled Vodafone NSA/SA result

- The apparent Vodafone “boot loop” was not demonstrated to be a modem or SIM crash.
  Retained vendor logs show affected boots remaining in the device `off` power state
  until a ten-second shutdown timer requested an orderly modem power-down. In the
  controlled run, one boot entered `low_power`; the following boot reached the normal
  online state and remained stable with the Vodafone SIM.
- LTE-only registered normally on Vodafone AU. NSA-only was then configured using
  generic LTE+NR mode plus a full NSA mask and an empty SA mask. It remained stable,
  but the serving LTE cell reported `eutra_with_nr5g: false`, so no EN-DC secondary
  could attach at that location.
- SA-only initially accepted the generic NR-only RAT/mask settings but stayed
  unregistered. The active EFS file
  `/nv/item_files/modem/mmode/nr5g_disable_mode` was then found to contain one byte,
  `01`. Qualcomm/Quectel semantics are `00` = disable neither SA nor NSA, `01` =
  disable SA, and `02` = disable NSA. This was the actual SA gate.
- Before changing it, a full 11,534,336-byte EFS2 partition snapshot was saved on the
  device and locally. The original one-byte file was also saved separately. Only that
  byte was changed, from `01` to `00`, through DIAG EFS; readback matched exactly.
  No MCFG, RFNV, calibration, or carrier-combination item was edited.
- After a normal reboot the same SA-only RAT/band selection registered on Vodafone:
  `C5GREG 0,1`, n1 15 MHz, PCI 431, NR-ARFCN 423410, PLMN 505-03, with working data.
  The bounded boot logger recorded a normal successful boot and was then disabled.
- Rollback is the saved one-byte `01` file plus a reboot. The full EFS2 image is a
  recovery/forensic artifact, not the preferred routine rollback mechanism.

## Vodafone/Telstra MCFG comparison

- The active Vodafone software profile is `VDF_Australia_Commercial`; its original
  signed MBN, SHA-256, and PDC identifier are preserved locally and in a root-only
  device backup before any profile investigation.
- The device-bundled `Telstra_Australia_Commercial` profile was also copied and
  decoded. The local copy is 54,208 bytes, passes its embedded hash check, and has
  SHA-256 `98d2025bca5c49820f3d3d2a268c2623de4e0f5d275a66880d22192cd379dad0`,
  matching the firmware source exactly.
- Both Australian profiles contain 77 MCFG items: 20 legacy numeric NV items and
  57 EFS files. Their RAT-acquisition-order files are byte-for-byte identical. Neither
  profile contains an explicit NR5G/SA enable item, NR carrier-policy file,
  `nr5g_full_voice_support`, or `nr5g_emc_support`.
- The normalized Vodafone/Telstra diff has only two changed numeric NV items (one is
  the carrier-name item), 11 changed shared files, and three unique files on each
  side. The differences are chiefly APN/URSP, IMS, ANDSF/IWLAN, and supplementary-
  service provisioning. None is an identified SA-registration gate.
- Consequently the NR5G voice/emergency flags seen in selected foreign SA-capable
  profiles are not safe candidates for blindly enabling SA: their names describe
  VoNR/emergency capability, and the local Telstra profile does not set them either.
  `captures/vodafone-mcfg/profile-comparison.json` contains the reproducible diff.
- Comparing Vodafone with the known-working Optus profile likewise found service,
  APN, IMS, and legacy-RAT differences but no NR/ENDC capability item explaining the
  failure. The live EFS `nr5g_disable_mode=1` finding supersedes the MCFG hypotheses;
  changing MCFG or RFNV was unnecessary for Vodafone SA.
- Extending the comparison to ROW, CMCC Open, TMO US, and Dish US did not reveal a
  portable CA-combination table. CMCC's five-byte `cap_feature_band_nr` has no known
  bit schema, while `pref_freq_list` is a frequency preference list rather than a
  UE capability-combination list. These are not safe candidates for transplantation.
- A harmless, uniquely named EFS probe established a complete override rollback
  mechanism: absence was confirmed through QMI, the file was written and read back
  byte-identically, DIAG EFS2 unlinked it, and QMI then confirmed absence again. The
  probe and temporary loopback-only DIAG transport were removed after the test.
- The guarded original-only PDC helper verified the backup hash, re-selected the
  saved Vodafone ID, and issued activation. This firmware returned immediate QMI
  success but no final activation indication when activating the already-active
  profile. Fresh reads still showed the exact saved profile active, no pending ID,
  SIM ready, and Vodafone LTE registered. Deactivation was deliberately not used.
- A byte-identical copy of the preserved signed Vodafone MBN was then loaded under
  the fixed unselected probe ID `M3200_OPENUI_CLONE01`. PDC reported the expected
  description, 50,952-byte size, and version while the original ID remained solely
  selected. The probe was deleted and confirmed absent. This proves safe load/store/
  cleanup mechanics for a valid signed image; it does **not** prove that this modem
  accepts an edited image with an invalidated signature.

## Pending / next steps

1. Optional: decode the proprietary `0xB0CD`/`0xB826` tables beyond the already
   decoded standards RRC containers; do not write MCFG/RFNV without a separately
   identified exact item/schema and RF-safe validation plan.
2. Optional: compare a capability capture and signed profile from a known-good SDX62
   device that actually advertises n1+n28+n78. Public chipset-family specifications
   alone are not proof that this Telstra SKU implements the RF paths or 3CC chain.
3. Optional: per-carrier RSRP via DIAG; SMS via WMS/AT; data-usage charts via msgbus
   `dmdb.dus.*`; GPS via LOC(0x1d).

## Gotchas learned (don't rediscover)

- PowerShell: no `<` redirect or heredocs; use `cmd /c 'ssh ... "cat > /f" < file'`.
- On-device CLIs need `LD_LIBRARY_PATH=/opt/nvtl/lib`.
- QRTR: local node id = 2; bind `(2, 0)`; NS at `(2, 0xFFFFFFFE)`; instance field =
  `(instance_id << 8) | version`; wire = `[flags][txn16][msgid16][len][TLVs]`, no svc/cid.
- QMI instance mismatch → silent no-reply; wrong wire format → garbage 14-byte reply.
- `nwcli qmi` raw mode is broken (sends zeros, prints zeros) — use our Python client.
- `AT+CESQ` hangs the AT bridge (avoid); Quectel `+QENG/+QCAINFO` unsupported.
- Threading + one shared QRTR socket = reply stealing; one socket per service.
- DMS Get Band Capabilities TLV 0x12 is **extended LTE**, not NR-NSA; TLV 0x13 is
  the modem's generic NR capability array. Mislabeling 0x12 falsely turns LTE B40
  into an apparent NR n40 capability.
- NAS RAT mode preference has one generic NR bit (**bit 6**). There is no standard
  NSA mode bit 7. Isolate SA versus NSA with their independent band-preference TLVs:
  GET 0x2C/0x2D and SET 0x2F/0x30.
- Band masks and RAT mode are not sufficient if the EFS gate
  `/nv/item_files/modem/mmode/nr5g_disable_mode` disables a path. On this device the
  original `01` meant SA disabled; `00` enabled both SA and NSA and required a reboot
  before the modem used the new value.
- This firmware acknowledges NAS Set System Selection Preference before GET reflects
  it. Poll fresh readback for up to 8 seconds; observed settling was about 1–3 seconds.
- NAS Get LTE Cphy CA Info returns *unpopulated SCC slots* with garbage (unknown
  dl_bw enum, zero earfcn, nonsense state). Filter SCCs to entries with a decodable
  bandwidth and non-zero EARFCN. The SCC `state` is a **u8 at +10** inside the
  13-byte struct — reading a u32 there bleeds into the next slot.
- NR channel bandwidth is not in QMI on this firmware. It lives in the msgbus
  `modem2.5g_data_signal_change` blob (u32 @42; pci@30, band@34, arfcn@38);
  cross-check PCI/ARFCN against NAS Get System Info before use.
- Replying to a POST before draining the body aborts Windows test clients with
  RSTs; the agent reads the body up front.
- `wifi_cli get_ap_profile` / `get_band_status` hang (until killed) while the AP
  is disabled; `get_enable`, `get_settings`, `get_ap_settings`, `get_sta_list`
  and `get_caps` answer normally. Timeout-guard every wifi_cli call.
- A `power_cycle`-duration band preference is discarded by `AT+COPS=2`/`AT+COPS=0`
  on this build. Persistent-duration band masks survive that reattach cycle, but COPS
  resets RAT mode to all-RAT. Controlled attach tests must use persistent masks,
  verify fresh readback, and restore the previous masks after each case.
- Stock UI's `statusBarBandwidth` can disagree with QMI ground truth (dynamic SCC activation).
- `AT+CFUN=0` also takes down the management path on this firmware. Use the proven
  `AT+COPS=2` / `AT+COPS=0` attach cycle for capability capture.
- A QXDM mask file was accepted by `diag_mdlog` but did not enable the requested
  records. The working path is `diag_socket_log` through a loopback-only SSH tunnel,
  with live DIAG log-mask negotiation and clean deinitialization.
