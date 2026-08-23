# Inseego M3200 Root Exploit

A single-file exploit that takes the **Inseego M3200** (Telstra 5G Wi-Fi Pro / MiFi Pro X) from web-admin access to **persistent root SSH** — no physical teardown, survives reboots.

Tested against firmware `THN-1.33.1.1-5.4-2.526.1.1-144.1.2-144.1.2` (do not update the device — updates patch this).

## Quick start

```bash
pip install requests paramiko cryptography
python exploit.py                 # prompts for the device's web admin password
```

Defaults to `192.168.1.1` over the USB-C tether. Options:

```
-t, --target IP          device address (default 192.168.1.1)
-p, --password PW        web admin password (else prompt / $M3200_ADMIN_PASSWORD)
--root-password PW       root SSH password to set (default: generated, printed at the end)
--pubkey FILE            your public key to install (see key-type note below)
--http-port / --vpn-port local server ports (default 8000 / 1194)
--attempts N             full-chain retries (default 2)
--force                  re-run even if root SSH already answers
```

At the end you get:

```
ssh root@192.168.1.1                    # password you chose / was generated
ssh -i artifacts/id_ecdsa -o HostKeyAlgorithms=+ssh-rsa root@192.168.1.1
```

Runtime is typically 5–10 minutes; the device is slow to launch its VPN client.

## How it works

1. **Web login** — the UI authenticates with `sha1(password + gSecureToken)`.
2. **Command injection** — the VPN settings page lets an admin upload an `.ovpn` profile. The device's `validate_openvpn_configuration` allowlist can be bypassed with a TAB-prefixed, quoted line, so a profile can carry:
   ```
   <TAB>tls-verify "/bin/sh -c 'echo XXX_START_XXX;CMD; echo XXX_END_XXX; exit 255'"
   ```
   The device's OpenVPN 2.4.9 client executes `tls-verify` commands as **root** during the TLS handshake (credit: WetFart1337 / Geofferey / ph1048, XDA thread 4711646, originally for the Inseego M2000).
3. **Fake OpenVPN server** — the exploit runs a minimal OpenVPN server locally (UDP 1194, TLS 1.2 via `ssl.MemoryBIO`) purely so the client completes a handshake and the `tls-verify` hook fires. `exit 255` aborts the handshake afterwards so OpenVPN never retries the script.
4. **Fetch-and-run** — the injected line is kept short and quote-free (anything else trips the validator), so it just downloads `s.sh` from the exploit's HTTP server and runs it. The setup script:
   - installs your public key in `/home/root/.ssh/authorized_keys`
   - sets the root password
   - removes the `-w`/`-s` flags from `/etc/default/dropbear` (root + password logins were disabled; dropbear is systemd socket-activated on this device and re-reads that file on every new connection, so the change applies immediately)
5. **Verify** — the exploit confirms root SSH, then clears the VPN profile it created.

The root filesystem is writable ubifs, so all changes **persist across reboots**.

## Device quirks worth knowing

- **User keys must be ECDSA.** This dropbear build rejects SHA-1-signed RSA keys (offers no rsa-sha2) and has no ed25519 support. The exploit generates an ECDSA P-256 key by default; if you pass `--pubkey`, pass an ECDSA one.
- **Host key is ssh-rsa**, so OpenSSH ≥ 8.8 clients need `-o HostKeyAlgorithms=+ssh-rsa` (paramiko-based tools don't).
- **No SFTP subsystem** — push files with `ssh root@IP "cat > /path" < localfile`.
- A web-UI "restart" page exists but doesn't actually reboot; use `systemctl reboot` once you have root.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Stage 1 fails with "device fetched an EMPTY setup script", or openvpn logs reach `UDPv4 link remote` but never `TLS: Initial packet` | The device can't connect back to your PC. **#1 cause on Windows: the adapter's network profile is "Public"** (inbound UDP 1194 / TCP 8000 silently dropped). Set it to Private, allow Python through the firewall, re-run. |
| `cannot reach http://192.168.1.1` | USB-C tether not up; check the adapter / replug. |
| Login fails | Wrong web admin password (the one for the device's web page, not Wi-Fi). |
| Long stall at "uploading payload" | Normal — the device takes 1–4 minutes per cycle to launch openvpn. The exploit auto-recovers the VPN state machine between attempts. |
| Re-running on a rooted device | Detected automatically and skipped; use `--force` to re-run. |

Notes: the exploit **clears any VPN profile** configured on the device, and each run rewrites `/home/root/.ssh/authorized_keys` with the key you specified.

## Updates (OTA from GitHub)

The device can update itself from published releases of this repo
(`dklasens/M3200-OpenUI`):

- **Cutting a release**: push a `v*` tag. `.github/workflows/release.yml`
  builds the dashboard, packages `www/` + agent + service unit + optional
  `apply.sh` into `m3200-openui-<tag>.tar.gz`, publishes `manifest.json`
  (version, asset name, sha256, size) and creates the GitHub release
  (prerelease when the tag has a `-`, e.g. `v0.2-beta`).
- **Checking**: dashboard *System → Updates* ("Check for updates"), or
  `POST /api/update/check`. The agent reads the newest non-draft release's
  `manifest.json` and compares versions (prerelease-aware).
- **Installing**: the dashboard offers the update with release notes; install
  requires the login session plus `X-Confirm: true`. The agent downloads the
  tarball with curl, verifies sha256 + size, extracts with path-traversal and
  symlink guards, `py_compile`s the staged agent (preflight), backs the running
  agent up to `*.prev`, applies files, runs `apply.sh` as root if present,
  reloads systemd and restarts itself. Progress/result survive the restart in
  `update/state.json`.
- **Device-side changes with a release**: edit `apply.sh` (run as root after
  the files land, before the restart) — e.g. the guarded EFS toggle that
  enables/disables 5G SA. A non-zero exit is reported as a failed install.

Verified live: a device on `0.2-beta` detected `v0.2.1`, installed it over the
air and came back at `0.2.1` with `ok=true`.

## Legal

For use on hardware you own (security research, custom firmware/UI work). Unauthorized access to someone else's device is illegal in most jurisdictions.

## Credits

- Original M2000 `tls-verify` injection: WetFart1337, Geofferey, ph1048 — [XDA thread 4711646](https://xdaforums.com/t/root-inseego-mifi-2000-5g-hotspot.4711646/)
- This packaged tooling (single-file runner, fake OpenVPN server, dropbear/ECDSA quirks, systemd findings) was developed against the Telstra M3200.
