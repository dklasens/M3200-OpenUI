# Inseego M3200 — Device Capabilities & Reverse-Engineering Notes

Everything in this document was verified live on the device (firmware
`THN-1.33.1.1-5.4-2.526.1.1-144.1.2-144.1.2`) via root SSH on 2026-08-21.

## Hardware

| Item | Value |
|---|---|
| Platform | Qualcomm **Snapdragon X62 (SDX62)**, ARMv7, 1 core |
| RAM / storage | 677 MB RAM; rootfs ubifs **writable**, ~270 MB free; `/data` 75 MB usrfs (63 MB free) |
| Modem↔host IPC | QRTR (kernel NS + `qrtr-ns`), GLINK, SMD, MHI; QMI services on **QRTR node 3** |
| USB gadget | RNDIS + MBIM + diag (`usb_ffs_diag`) + AT (`at_usb0/1`) + ADB function present (adbd off) |
| Wi-Fi | 2.4/5 GHz (`wifi_cli`, `wifid`); Ethernet port; 32 max Wi-Fi clients |

## Access

- **Root SSH**: `ssh root@192.168.1.1` (port 22 = systemd socket-activated dropbear; also port 2222).
  Persistent across reboots. ECDSA user keys only; host key is ssh-rsa (`-o HostKeyAlgorithms=+ssh-rsa`).
  Key: `artifacts/id_ecdsa`. No SFTP — push files with `ssh root@IP "cat > /path" < file`.
- **Web UI**: `http://192.168.1.1` (lighttpd + `webuid` + `restapi.fcgi`); unauthenticated
  JSON status at `GET /srv/status` (rich: bands, bandwidth, PCI, SNR, bytes, clients, VPN…).
- **Security cleanup completed 2026-08-21**: the leftover unauthenticated root bind
  shell (`nc -l -p 9999 -e /bin/sh`) was killed. TCP 9999 remained closed after both
  verification reboots. SSH on port 22/2222 still listens on all interfaces; the
  mobileap firewall gates WAN-side input.
- ⚠️ **Do not accept firmware updates** — they patch the VPN `tls-verify` exploit
  (`fotad`/`nua` daemons handle updates).

## The levers

### 1. QMI over QRTR from userspace (primary lever) — `scripts/qmi.py`

Pure-Python (stdlib) QMI client, no extra packages, no CID allocation needed.

- Socket: `socket(AF_QIPCRTR=42, SOCK_DGRAM)`, `bind((2, 0))` (local node id = **2**, auto-ephemeral port).
- Service discovery via kernel nameserver at `(local_node, 0xFFFFFFFE)`,
  control pkt `[cmd u32][service u32][instance u32][node u32][port u32]`;
  `NEW_LOOKUP=10`, reply `NEW_SERVER=4`, all-zero srv = end of list.
  **Instance field = (instance_id << 8) | version** (low byte = version).
- Wire format (confirmed by stracing `modem2d`): request `[0x00][txn u16][msgid u16][len u16][TLVs]`,
  response `[0x01][txn][msgid][len][TLVs]`. No service/client bytes on the wire.
- 97 QRTR services visible: NAS(3) @ node 3 port 58, DMS(2) @ 72, WDS(1) @ 63, WMS(5),
  UIM(12), GPS/LOC(0x1d), IMS family, SAR, vendor/Inseego services (0x0a = "NW_SVC1",
  used by `nwcli qmi_idl`), etc.

### 2. Verified QMI calls

| Call | ID | What we got |
|---|---|---|
| NAS Get Signal Info | 0x004F | LTE `{rssi i8, rsrq i8, rsrp i16, snr i16 (0.1dB)}` TLV 0x14; NR5G `{rsrp i16, snr i16}` TLV 0x17; NR5G ext rsrq TLV 0x18 |
| NAS Get LTE Cphy CA Info | 0x00AC | PCC TLV 0x13 `{pci u16, earfcn u16, dl_bw u32, band u16}`, SCC array TLV 0x15 `{pci, earfcn, dl_bw, band, state u32, idx u8}`, PCC DL BW TLV 0x11 |
| NAS Get System Info | 0x004D | LTE cell-id/TAC/PLMN/roam (TLV 0x19), NR5G srv status (0x4A), EUTRA-with-NR5G flag (0x4E), **NR PCI u16 = TLV 0x54**, **NR ARFCN u32 = TLV 0x60** (both newer than public libqmi schema) |
| NAS Get Cell Location Info | 0x0043 | Intrafreq LTE (0x13) + interfreq LTE (0x14, earfcn u16 / 0x30, earfcn u32): per-cell `{pci u16, rsrq i16, rsrp i16, rssi i16, sinr i16}` in 0.1 units |
| NAS Get System Selection Pref | 0x0034 | mode pref (0x11 u16), LTE bands 1–64 (0x15 u64), LTE ext (0x23 = 4×u64), **NR5G-SA bands (0x2C = 8×u64)**, **NR5G-NSA bands (0x2D = 8×u64)** |
| NAS Set System Selection Pref | 0x0033 | **verified band write**: LTE ext mask = 0x24 (4×u64), NR SA = 0x2F (8×u64), NR NSA = 0x30 (8×u64), change duration = 0x17 (`0` until power cycle, `1` permanent) |
| NAS Get ENDC Config | 0x00E8 | TLV 0x10 enabled=1 |
| DMS Get Manufacturer/Model/Revision/MSISDN/HW rev | 0x0021–0x0024, 0x002C | device identity |
| DMS Get Band Capabilities | 0x0045 | 0x10 legacy LTE u64 mask; 0x12 extended LTE u16 array; 0x13 generic NR5G u16 array (no separate SA/NSA capability arrays) |

Band enums: QMI `QmiNasActiveBand` is **not** linear above band 14. Bands 1–14
map to enums 120–133 (126 = B7, 120 = B1), but above that the enum follows
Qualcomm's internal band list: B17=134, B18–21=143–146, B23=152, B24=147,
B25=148, B26=153, B27=164, B28=158, B32=154, B33–40=135–142 (so **B40 arrives
as enum 142**, not 159), B41–43=149–151, B46=163, B48=167, B66=161, B71=168.
The authoritative table is libqmi `qmi-enums-nas.h`; `agent/qmi.py` carries it
as `QMI_ACTIVE_BAND_TO_LTE`. Decoders must prefer the EARFCN raster (TS 36.101)
over this enum whenever an EARFCN is present — the naive `enum - 119` rule
mislabels every band above B14 (live example 2026-08-23: Optus B40 shown as
"band 23").
DL bandwidth enum: 0=1.4, 1=3, 2=5, 3=10, 4=15, 5=20 MHz.
RAT mode pref bits include bit3 UMTS, bit4 LTE, and **bit6 generic NR5G**. There is
no standard bit7 NSA selector. SA versus NSA is isolated using the independent NR
band preference masks (GET 0x2C/0x2D; SET 0x2F/0x30), not separate RAT-mode bits.
NR band from ARFCN (FR1 ranges, kHz×... global raster): n28 151600–160600, n1 422000–434000,
n3 361000–376000, n5 173800–178800, n7 524000–538000, n8 185000–192000, n78 620000–653333.

### 3. AT command channel

`/opt/nvtl/bin/read_atcmd "AT+CMD"` (needs `LD_LIBRARY_PATH=/opt/nvtl/lib`). Full 3GPP 27.007
set (253 commands via `AT+CLAC`): SMS (`+CMGF/+CMGL/+CMGS…`), `+COPS`, `+C5GREG`, `+CFUN`,
`+CGDCONT`, Qualcomm `$QC*`: `$QCSQ` (rssi/rsrp), `$QCSYSMODE`, `$QCDRX`, `$QCRMCALL`,
`$QCBANDPREF` (legacy CDMA/WCDMA only — **not** useful for LTE/NR lock).
Quectel-style `+QENG`/`+QCAINFO` are **not** supported. `+CESQ` hangs (avoid).

### 4. Message bus (msgbus / MQTT)

`msgbus_cli` (`print_channels`, `MsgBusGet`, `MsgBus_Subscribe`) and mosquitto on :1883.
Telemetry channels: `modem2.data_signal_change`, `modem2.5g_data_signal_change` (binary
blobs — NR blob contains rsrp/snr/pci/band/arfcn/bw), `modem2.registration_status`,
`ccm2.wan_stats`, `dmdb.dus.*` (data usage). Good for event-driven monitoring without QMI polling.

`MsgBusGet` returns the latest blob as hex; `modem2.5g_data_signal_change` (86 bytes,
little-endian) decodes as: i32 rsrp@2, i32 rsrq@6, i32 snr@10, u32 pci@30,
u32 band@34, u32 arfcn@38, **u32 bandwidth_mhz@42** (verified live: n78 PCI 499,
ARFCN 633312, 100 MHz). This is the only live source of NR channel bandwidth;
QMI NAS exposes no NR-bandwidth TLV on this firmware. The agent cross-checks the
blob's PCI/ARFCN against NAS Get System Info before trusting the width. The stock
UI's `statusBarBandwidth` (" 30 MHz, 100 MHz") is a per-band list derived from the
same blobs and can disagree with QMI ground truth for LTE.

### 5. NV / EFS (CA combo tables, feature flags)

`nwcli qmi_idl` interactive menu: `read_nv` (0x002E), `read_file` (0x0042 = EFS chunk read).
The firmware also carries signed Qualcomm MCFG software profiles under
`/firmware/image/modem_pr/mcfg/configs/mcfg_sw/`. Australian profiles are present
for Optus (`Optus_AU`), Telstra, and Vodafone (`VDF_AU`). They contain certificates,
signatures, and carrier-specific NV/item-file payloads. A profile/SIM change may
change advertised capability policy, but these binaries are not a safe arbitrary
CA-combination editor.

The decisive Vodafone SA gate is the live one-byte EFS file
`/nv/item_files/modem/mmode/nr5g_disable_mode`. It was originally `01` (SA
disabled); `00` means neither SA nor NSA is disabled, while `02` disables NSA. A
DIAG EFS write from `01` to `00`, followed by a normal reboot, enabled Vodafone n1
SA without changing MCFG or RFNV. The original byte and a pre-change EFS2 partition
snapshot are preserved in `captures/vodafone-b5-nsa/`.

### 6. DIAG (deepest RF access)

`diag-router` running, USB `ffs_diag` gadget. QXDM-grade data (per-carrier RSRP, RRC,
ML1 logs). The device-native `diag_socket_log` can bridge DIAG through a loopback-only
SSH reverse tunnel, avoiding a new LAN listener. Verified capture record IDs:

- `0xB0C0` LTE RRC OTA
- `0xB0CD` LTE supported CA combinations
- `0xB821` NR RRC OTA
- `0xB826` NR supported CA combinations

The temporary DIAG bridge and tunnel must be stopped after use. Do not use
`AT+CFUN=0` for a capture reconnect: it removes the management path. The safe proven
cycle is `AT+COPS=2`, wait four seconds, then `AT+COPS=0`.

## Carrier-aggregation capability capture

On 2026-08-21 an Optus attach returned `eutra`, `eutra-nr`, and `nr`
`UECapabilityInformation` containers. pycrate standards decoding found:

- LTE `supportedBandCombinationReduced-r13`: 89 entries total, 68 CA entries,
  11 unique band/bandwidth-class layouts. All 21 hardware LTE bands are present as
  single-band configurations.
- MR-DC `supportedBandCombinationList`: 65 entries, 15 unique layouts, using LTE
  B1/B3/B7/B28 with n78 for this Optus-filtered enquiry.
- NR `supportedBandCombinationList`: absent in this NSA exchange. That result applied
  only to the Optus-filtered NSA enquiry and was not proof of zero NR-CA support.

A subsequent clean Vodafone SA attach in
`captures/vodafone-sa/sa-full-attach-20260821.dlf` returned an NR capability list
with exactly five entries:

- n1A
- n1A+n28A, with UL on n1
- n1A+n78A, with UL on n1
- n1A+n28A, with UL on n28
- n1A+n78A, with UL on n78

There is no n28+n78 entry and no n1+n28+n78 entry. Controlled under-load DIAG
captures corroborated the declaration: n1+n28 and n1+n78 both formed 2CC SA;
n28+n78 remained single-carrier n28; and the three-band mask formed only n28 PCC
plus n1 SCell. The maximum advertised and observed SA aggregation on this firmware,
SKU, profile, and network is 2CC.

The API endpoint `GET /api/ca/combinations` serves the decoded capability data and
embeds the controlled validation summary. `GET /api/ca/validation` exposes the four
Vodafone cases directly. The dashboard labels the validation as captured DIAG
evidence so it is not confused with continuously live NAS telemetry.

### Modification boundary

- Verified safe lever: band preference masks can exclude combinations containing a
  deselected band.
- No QMI or AT control was found for adding, editing, prioritizing, or forcing a
  particular CA/MR-DC combination. Scheduling remains controlled by the network.
- Switching SIM/carrier profile can legitimately change the advertised policy via
  an existing signed MCFG.
- Editing MCFG/RFNV to invent combinations is undocumented and can invalidate the
  signed profile or advertise an RF path the calibrated front end cannot support.
  It should not be exposed in the UI without a proven backup/restore path, an exact
  item/schema, signature acceptance, and controlled RF validation.
- Seven signed profiles (Vodafone AU, Telstra AU, Optus AU, ROW, CMCC Open, TMO US,
  and Dish US) were decoded and compared. No decoded CA-combination table was found.
  CMCC alone contains a five-byte `cap_feature_band_nr` and a 254-byte
  `pref_freq_list`; their proprietary schema does not identify an NR-CA combination,
  and the latter is a frequency preference list. A 30-file RFNV correlation scan
  also found no schema-backed match. No MCFG/RFNV item was therefore changed.

## Live network snapshot after NR-CA validation (2026-08-21, Vodafone 505-03)

- Mode: **5G SA**, registered (`+C5GREG: 0,1`), with no LTE PCC/anchor.
- NR primary: **n28 15 MHz**, PCI 318, NR-ARFCN 159130, PLMN 505-03.
- Recent signal: NR RSRP approximately -88 dBm.
- Preferences were restored to all RATs, all 21 hardware LTE bands, all seven SA
  bands, and an empty NSA mask. Temporary DIAG processes and tunnels were stopped.
- `NAS Get LTE Cphy CA Info` returning QMI 0x004a is expected in SA because there is
  no LTE PHY carrier. Active NR SCells require RRC/DIAG evidence on this firmware.

## Historical network snapshot (2026-08-21, Optus 505-02)

- Mode: **5G NSA (EN-DC)** — `+C5GREG: 0,0`, ENDC enabled.
- LTE PCC: **B7 20 MHz**, PCI 457, EARFCN 3350; SCC1: **B1 20 MHz**, PCI 67, EARFCN 299 (activated).
- NR: **n78 100 MHz**, PCI 198, ARFCN 633312.
- Signal: LTE RSRP ≈ −102 dBm, RSRQ −11.2 dB, RSSI −69 dBm; NR RSRP ≈ −101 dBm, SNR 4.0 dB.
- LTE cell id 0x0139FE3C, TAC 0xCB2A (51914). Neighbors: intra-freq B7 PCI 480/198;
  inter-freq B1 PCI 67/198/423/377/87 with per-cell RSRP/RSRQ/RSSI.

## NR-SA/NSA capability assessment

- DMS reports one generic hardware NR list: **n1, n3, n5, n7, n8, n28, n78**.
  The UI validates both SA and NSA preference masks against that list because this
  firmware does not expose distinct SA/NSA hardware capability arrays.
- **n40 is not reported as an NR capability.** The earlier apparent NSA n40 result was
  a decoder error: DMS TLV 0x12 is extended LTE, so its value 40 means LTE B40.
- LTE bands (DMS extended array):
  **B1,2,3,4,5,7,8,12,13,17,18,19,20,25,26,28,40,42,43,48,66**.
- Saved carrier baseline: NR preferences (SA and NSA) n5/n7/n8/n78; LTE preferences
  B1/3/5/7/8/20/28. The full hardware-reported lists are now selected permanently.
- The mode preference is not an SA/NSA discriminator: QMI defines bit 6 as generic
  NR5G, and the Optus live connection used that bit while demonstrably operating as
  NSA/EN-DC. The dashboard therefore leaves RAT mode untouched during normal band
  selection.
- SA and NSA can be isolated reversibly by combining the generic NR RAT mode with an
  empty mask for the unwanted path. Acceptance of an SA mask does not prove SA
  registration, coverage, or carrier provisioning.

### Current Vodafone state after controlled testing (2026-08-21)

- The full LTE and SA hardware masks and empty NSA mask are selected, with all-RAT
  mode restored after testing. Fresh QMI readback matched this state.
- Vodafone is registered on n28 SA as described above. The original carrier baseline
  and the guarded test baselines remain available; none changes the independent EFS
  enable/disable byte.

### Controlled Vodafone SA band/CA validation (2026-08-21)

- n28-only registered on NR-ARFCN 159130, PCI 318, 15 MHz, around -89 dBm.
- n78-only registered on NR-ARFCN 643392, PCI 359, 60 MHz, around -103 dBm.
- n1+n28 produced n28 PCC (159130/318) plus n1 SCell (423410/366).
- n1+n78 produced n1 PCC (423410/431) plus n78 SCell (643392/512).
- n28+n78 produced n28 PCC only; no SCell was present in the RRC reconfigurations.
- n1+n28+n78 produced n28 PCC plus exactly one n1 SCell; n78 was never added.
- Each aggregation test ran bounded HTTPS traffic while DIAG recorded NR RRC. Three
  cases completed 10 MB; the three-band run generated sustained traffic before the
  transfer stalled at about 2.27 MB. That does not alter its RRC carrier result.

## Controlled Vodafone AU NSA/SA test (2026-08-21)

- Retained logs from the apparent boot loop show the device remaining in its `off`
  power state until the platform shutdown timer performed an orderly modem power-down;
  they do not show a confirmed modem/SIM crash. A bounded early-boot logger then caught
  one attempt entering `low_power`, followed by a stable online boot with the Vodafone
  SIM. The temporary logger was disabled after the test.
- LTE-only registered on Vodafone AU. With LTE+generic-NR mode, SA mask empty, and the
  full NSA mask selected, the device stayed stable but the serving LTE cell reported
  `eutra_with_nr5g: false`; no NSA secondary was available at the test location.
- With generic-NR-only mode, full SA mask, and NSA mask empty, all QMI writes read back
  exactly but registration initially stayed at `C5GREG 0,0`. EFS inspection then found
  `/nv/item_files/modem/mmode/nr5g_disable_mode=01`, explicitly disabling SA.
- A complete pre-change EFS2 snapshot and the original one-byte value were preserved.
  The single byte was changed to `00`, verified byte-for-byte, and the device was
  rebooted normally. It then registered on Vodafone n1 SA (`C5GREG 0,1`) and passed a
  bounded data-transfer test. No MCFG/RFNV/calibration item was modified.
- The successful boot log was saved locally and the temporary logger was disabled.
  Routine rollback is to restore the saved `01` byte and reboot; raw EFS2 restoration
  is reserved for recovery, not normal configuration changes.

## Verified write behaviour and safeguards

- NAS 0x0033 exact-mask writes were verified against fresh NAS 0x0034 readback.
  This firmware applies them asynchronously: SET can return success roughly 1–3
  seconds before GET changes, so the client polls for up to 8 seconds.
- Duration `0` survived agent reconnect/restart but reverted exactly to the saved
  carrier baseline after device reboot. Duration `1` retained the full masks after
  device reboot, and Optus NSA service reconnected on B7+n78.
- A later controlled attach test found a narrower behaviour: duration `0`
  (`power_cycle`) preferences are discarded by `AT+COPS=2`/`AT+COPS=0`. Duration `1`
  masks survive that reattach, while COPS resets RAT mode to all-RAT. Tests that use
  COPS must therefore apply persistent band masks, verify readback, and restore them
  after every case.
- Before the first write, the agent atomically saved the carrier baseline at
  `/data/m3200-openui/band-baseline.json`. The dashboard can restore it.
- Dashboard writes authenticate with the bearer session from `POST /api/auth/login`
  (sliding 1 h tokens, per-IP login lockout) plus the `X-M3200-Confirm` header and a
  same-origin `Origin`. No token entry is exposed in the UI. The root-only generated
  token remains valid for maintenance automation. LTE must be non-empty;
  one NR path may be empty for SA-only/NSA-only operation, but both may not be empty.
  All selections retain capability-subset validation. Permanent writes remained
  disabled until reboot persistence was proven, then were enabled with a root-only
  marker.
- Normal dashboard band writes change band masks only. They do not modify RAT mode,
  carrier XML, modem EFS/NV, or firmware regulatory/calibration data. The Vodafone
  SA investigation separately made the documented, backed-up one-byte EFS change;
  it is not exposed as a routine browser control.

## Repo artifacts

- `exploit.py` — root exploit (OpenVPN tls-verify injection) → persistent SSH.
- `scripts/qrtr_probe.py` — QRTR service scanner + first QMI probe.
- `scripts/qmi.py` — reusable QRTR/QMI client library + live dump of the calls above.
- `agent/` — deployed JSON API and dashboard, including guarded band apply/restore.
- `agent/ca-combinations.json` — standards-decoded Optus LTE/MR-DC plus Vodafone NR
  capability data.
- `agent/nr-ca-validation.json` — four controlled Vodafone SA PCC/SCell outcomes and
  the 2CC/3CC conclusion used by the API and dashboard.
- `scripts/capture_diag_ca.py`, `decode_rrc_capabilities.py`, and
  `export_ca_combinations.py` — targeted capture and reproducible decode/export path.
- `scripts/export_nr_ca_validation.py` — compact standards-decoded PCC/SCell evidence
  export from the controlled DLF captures.
- `scripts/set_rat_mode.py` and `set_nr_path.py` — guarded mode/path isolation with
  root-only saved baselines, exact readback, and recovery actions.
- `scripts/lock_nsa.py` — atomic guarded workflow for a combined LTE-anchor and
  NSA-only band lock, with a root-only pre-lock baseline and best-effort rollback if
  either of the two QMI writes fails.
- `scripts/lock_sa.py` — guarded persistent SA-mask test helper with exact readback,
  saved baseline, and rollback.
- `scripts/analyze_mcfg_profiles.py` and `captures/vodafone-mcfg/` — preserved
  Vodafone MCFG, decoded Telstra/Optus/ROW/foreign comparators, hashes, metadata, and
  normalized candidate/item diffs. The Telstra and Vodafone profiles share the same
  77-item structure and contain no explicit SA-enable item.
- `scripts/reactivate_original_pdc.py` — hash-gated helper that can only select or
  activate the preserved original Vodafone software PDC ID; it cannot accept an
  arbitrary ID, load, delete, or operate on platform configuration.
- `scripts/probe_pdc_store.py` — fixed-ID load/delete probe for a byte-identical,
  unselected clone of the preserved signed Vodafone MBN. It validates PDC cleanup
  without selecting the clone or claiming that edited signatures are accepted.
- `scripts/m3200-boot-diag.sh` — bounded six-slot early-boot power logger; deployed
  for the Vodafone investigation and disabled when it completed.
- `captures/vodafone-b5-nsa/efs2-pre-vodafone-mod-20260821.bin` — 11,534,336-byte
  pre-change EFS2 snapshot, SHA-256
  `04bc50c0220091e3ca89596ef2b8151e8397570f4435e39395f9ad1c6cb64376`.
- `captures/vodafone-b5-nsa/nr5g_disable_mode.bin` and
  `nr5g_disable_mode.after.bin` — original `01` rollback byte and verified `00`
  enabled byte. `boot-sa-enable.log` records the successful post-change boot.
- `captures/vodafone-sa/sa-full-capabilities-20260821.json` — standards-decoded
  Vodafone NR UE capability, including all five advertised NR combinations.
- `captures/vodafone-sa/sa-n1-n28-traffic-20260821.dlf`,
  `sa-n1-n78-traffic-20260821.dlf`, `sa-n28-n78-traffic-20260821.dlf`, and
  `sa-n1-n28-n78-traffic-20260821.dlf` — controlled under-load NR RRC evidence.
- `tests/test_band_control.py` — QMI TLV, capability decoding, polling, validation,
  baseline/restore, permanent gate, and HTTP authorization coverage.
