# M3200-OpenUI

Open up the **Inseego M3200** (Telstra 5G Wi-Fi Pro / MiFi Pro X): a one-shot **root exploit**, an on-device **agent** exposing the modem over a JSON API, and a modern **web dashboard** replacing the stock UI with real telemetry and advanced controls (band selection, carrier aggregation, SMS, clients, thermals…).

Tested against firmware `THN-1.33.1.1-5.4-2.526.1.1-144.1.2-144.1.2`.

> ⚠️ **Do not accept firmware updates** on a device you want to keep open — updates patch the exploit chain.
>
<img width="2866" height="1549" alt="image" src="https://github.com/user-attachments/assets/63774168-7946-4396-b13d-43092a14b22a" />
<img width="2879" height="1552" alt="image" src="https://github.com/user-attachments/assets/ed967cd1-b7a6-43dc-ab2b-e8606b7cfb1e" />

| Component | What it is |
|---|---|
| [exploit.py](exploit.py) | Single-file Python tool: web-admin access → **persistent root SSH**, survives reboots. Prerequisite for everything else. |
| [agent/](agent/) | Stdlib-only Python daemon running as a systemd service on the device (`/data/m3200-openui/`). Talks QMI/QRTR straight to the modem; serves a bearer-token JSON API (~30 routes) plus the built dashboard on port 8080. |
| [web-app/](web-app/) | React 19 + Vite + Tailwind dashboard at `http://192.168.1.1:8080/`. Live signal/carrier telemetry, guarded band locks, CA capability views, Wi-Fi/SMS/client status, battery/thermal/CPU. |

Also in the repo: `scripts/deploy.ps1` (one-command deployment), `scripts/qmi.py` + DIAG/RRC helpers for protocol research, `tests/`, and [`device.md`](device.md) — the full reverse-engineering reference (read it first for anything deep). [`currentstate.md`](currentstate.md) tracks what works today.

## 1. Run the root exploit

```bash
pip install requests paramiko cryptography
python exploit.py                 # prompts for the device's web admin password
```

Defaults to `192.168.1.1` over the USB-C tether; takes 5–10 minutes. Useful options:

```
-t IP                device address (default 192.168.1.1)
-p PW                web admin password (else prompt / $M3200_ADMIN_PASSWORD)
--root-password PW   root SSH password to set (default: generated, printed at the end)
--pubkey FILE        your ECDSA public key to install
--force              re-run even if root SSH already answers
```

When it finishes:

```
ssh root@192.168.1.1                    # password you chose / was generated
ssh -i artifacts/id_ecdsa -o HostKeyAlgorithms=+ssh-rsa root@192.168.1.1
```

**How it works:** an admin-uploaded `.ovpn` profile can smuggle a `tls-verify` directive past the validator; the device's OpenVPN client runs it **as root** during the handshake (original M2000 finding by WetFart1337 / Geofferey / ph1048, [XDA thread 4711646](https://xdaforums.com/t/root-inseego-mifi-2000-5g-hotspot.4711646/)). The exploit plays fake OpenVPN server so the hook fires; the payload installs your SSH key, sets the root password, and re-enables dropbear logins. The rootfs is writable ubifs, so changes persist across reboots.

Notes: user keys must be **ECDSA** (no RSA-SHA2/ed25519 in this dropbear), host key is ssh-rsa, there's no SFTP (use `ssh root@IP "cat > /path" < file`). Re-running on a rooted device is detected and skipped unless `--force`; each run replaces `authorized_keys` and clears any VPN profile.

If stage 1 fails with "EMPTY setup script", the usual culprit on Windows is the tether adapter's network profile being **Public** (inbound UDP 1194/TCP 8000 silently dropped) — set it Private, allow Python through the firewall, retry.

## 2. Deploy the agent + dashboard

With root SSH working, from a machine with Node.js (^20.19 or ≥22.12) —
Windows, macOS or Linux (the device side only needs its own Python/curl):

```powershell
pwsh scripts/deploy.ps1                  # Windows: build dashboard + push everything
pwsh scripts/deploy.ps1 -SkipWebBuild    # reuse an existing web-app/dist build
```

```bash
scripts/deploy.sh                        # macOS / Linux
SKIP_WEB_BUILD=1 scripts/deploy.sh [ip]  # reuse build / other tether address
```

For **another identical M3200**: run `exploit.py` against it first (installs
your SSH key), then the deploy script; `M3200_SSH_KEY` overrides the key path.
Afterwards the device can also update itself from GitHub releases
(System → Updates in the dashboard).

The script builds the SPA, pushes agent + dashboard to `/data/m3200-openui/`, installs and restarts the `m3200-agent` systemd service, health-checks `/api/health`, then prints your credentials. Sign in at:

```
http://192.168.1.1:8080/
```

The dashboard password is generated on first deploy (root-only file `/data/m3200-openui/agent-password`). Auth is bearer-token based (sliding 1 h expiry, per-IP lockout); band writes additionally require an explicit confirm header sent automatically by the GUI. Re-running the script is the supported update path.

## Development (no device required)

```bash
cd web-app && bash tools/demo.sh     # fixture mock agent (:9090) + dashboard preview (:8080), login "demo"
python -m unittest discover tests    # agent unit tests
python scripts/check-api-contract.py # agent <-> dashboard <-> mock route lockstep check
```

## Legal & credits

For use on hardware **you own** (security research, custom firmware/UI work); unauthorized access to someone else's device is illegal in most states.

Dashboard design ported from the MU5250 OpenUI project; the exploit technique is credited above, and the device-side Python QMI/QRTR stack was developed against the Telstra M3200.
