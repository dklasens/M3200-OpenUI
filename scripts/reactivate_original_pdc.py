#!/usr/bin/env python3
"""Guarded selection/activation of the preserved original software MCFG.

This helper intentionally cannot accept an arbitrary profile ID, load a profile,
delete a profile, or operate on platform configuration.  The only mutable target
is the software-profile ID recorded in the root-owned preservation manifest.
"""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import time


AGENT_DIR = Path("/data/m3200-openui")
DEFAULT_MANIFEST = AGENT_DIR / "backups/vodafone-mcfg/manifest.json"
SOFTWARE_CONFIG = 1
PDC_SERVICE = 0x24
PDC_GET_SELECTED_CONFIG = 0x22
PDC_SET_SELECTED_CONFIG = 0x23
PDC_ACTIVATE_CONFIG = 0x27
CONFIRMATION = "REACTIVATE-ORIGINAL-VODAFONE"

if AGENT_DIR.is_dir():
    sys.path.insert(0, str(AGENT_DIR))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from qmi import M3200Modem, QmiError, QmiService, check_result, parse_tlvs  # noqa: E402


def tlv(kind, payload):
    return struct.pack("<BH", kind, len(payload)) + payload


def indication(service, msgid, transaction, timeout=8.0):
    service.sock.settimeout(timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data, address = service.sock.recvfrom(4096)
        except socket.timeout as error:
            raise QmiError(f"PDC indication 0x{msgid:04x} timed out") from error
        if address != service.server or len(data) < 7:
            continue
        flags, txn, received_msgid, length = struct.unpack("<BHHH", data[:7])
        if flags == 0x04 and txn == transaction and received_msgid == msgid:
            return parse_tlvs(data[7:7 + length])
    raise QmiError(f"PDC indication 0x{msgid:04x} timed out")


def request_indication(service, msgid, payload, token):
    response = parse_tlvs(service.request(msgid, payload, timeout=5.0))
    check_result(response)
    transaction = service.txn
    response_token = struct.unpack(
        "<I", response.get(0x10, [struct.pack("<I", token)])[0][:4])[0]
    if response_token != token:
        raise QmiError(f"PDC response token {response_token} did not match {token}")
    result = indication(service, msgid, transaction)
    if 0x01 in result:
        code = struct.unpack("<H", result[0x01][0][:2])[0]
        if code:
            raise QmiError(f"PDC indication error 0x{code:04x}")
    return result


def prefixed_bytes(value):
    if not value:
        return b""
    return value[1:1 + value[0]]


def selected_config(service, token):
    result = request_indication(
        service,
        PDC_GET_SELECTED_CONFIG,
        tlv(0x01, struct.pack("<I", SOFTWARE_CONFIG)) +
        tlv(0x10, struct.pack("<I", token)),
        token,
    )
    return {
        "active_id": prefixed_bytes(result.get(0x11, [b""])[0]),
        "pending_id": prefixed_bytes(result.get(0x12, [b""])[0]),
    }


def set_selected_config(service, config_id, token):
    type_and_id = struct.pack("<IB", SOFTWARE_CONFIG, len(config_id)) + config_id
    request_indication(
        service,
        PDC_SET_SELECTED_CONFIG,
        tlv(0x01, type_and_id) + tlv(0x10, struct.pack("<I", token)),
        token,
    )


def activate_config(service, token):
    request_indication(
        service,
        PDC_ACTIVATE_CONFIG,
        tlv(0x01, struct.pack("<I", SOFTWARE_CONFIG)) +
        tlv(0x10, struct.pack("<I", token)),
        token,
    )


def preserved_original(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config_id = bytes.fromhex(manifest["pdc"]["software"]["active_id"])
    backup = Path(manifest["on_device_backup"])
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError(
            f"preserved MBN hash mismatch: expected {manifest['sha256']}, got {digest}")
    return manifest, config_id, digest


def render_state(state):
    return {key: value.hex() for key, value in state.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "stage", "activate"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--confirm")
    args = parser.parse_args()

    manifest, original_id, digest = preserved_original(args.manifest)
    if args.action != "check" and args.confirm != CONFIRMATION:
        raise ValueError(f"mutable action requires --confirm {CONFIRMATION}")

    sock = M3200Modem._new_sock()
    try:
        service = QmiService(sock, PDC_SERVICE)
        token = 0x4D325000
        before = selected_config(service, token + 1)
        if before["active_id"] != original_id:
            raise ValueError(
                "refusing mutation: current active software profile is not the "
                "preserved original")
        if before["pending_id"] not in (b"", original_id):
            raise ValueError(
                "refusing mutation: a different software profile is pending")

        output = {
            "action": args.action,
            "description": manifest["pdc"]["software"]["description"],
            "preserved_mbn_sha256": digest,
            "original_id": original_id.hex(),
            "before": render_state(before),
        }
        if args.action == "stage":
            set_selected_config(service, original_id, token + 2)
            after = selected_config(service, token + 3)
            if original_id not in (after["active_id"], after["pending_id"]):
                raise QmiError("original profile was not active or pending after selection")
            output["after"] = render_state(after)
        elif args.action == "activate":
            activate_config(service, token + 2)
            output["activation_indication"] = "success"

        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, QmiError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
