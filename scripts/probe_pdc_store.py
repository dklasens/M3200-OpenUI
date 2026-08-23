#!/usr/bin/env python3
"""Load/delete an unselected, byte-identical clone of the preserved MCFG.

This validates PDC storage and cleanup without testing an edited signature or
changing the selected carrier profile.  Both the profile ID and expected source
are fixed; arbitrary images and IDs are intentionally unsupported.
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
PDC_DELETE_CONFIG = 0x25
PDC_LOAD_CONFIG = 0x26
PDC_GET_CONFIG_INFO = 0x28
PROBE_ID = b"M3200_OPENUI_CLONE01"
CONFIRMATION = "PROBE-UNSELECTED-PDC-STORE"
CHUNK_SIZE = 1024

if AGENT_DIR.is_dir():
    sys.path.insert(0, str(AGENT_DIR))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from qmi import M3200Modem, QmiError, QmiService, check_result, parse_tlvs  # noqa: E402


def tlv(kind, payload):
    return struct.pack("<BH", kind, len(payload)) + payload


def prefixed_bytes(value):
    if not value:
        return b""
    return value[1:1 + value[0]]


def indication(service, msgid, transaction, timeout=8.0):
    service.sock.settimeout(timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data, address = service.sock.recvfrom(8192)
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


def config_info(service, config_id, token):
    type_and_id = struct.pack("<IB", SOFTWARE_CONFIG, len(config_id)) + config_id
    result = request_indication(
        service,
        PDC_GET_CONFIG_INFO,
        tlv(0x01, type_and_id) + tlv(0x10, struct.pack("<I", token)),
        token,
    )
    output = {}
    if 0x11 in result:
        output["total_size"] = struct.unpack("<I", result[0x11][0][:4])[0]
    if 0x12 in result:
        output["description"] = prefixed_bytes(result[0x12][0]).decode(
            "utf-8", "replace")
    if 0x13 in result:
        output["version"] = struct.unpack("<I", result[0x13][0][:4])[0]
    return output


def optional_config_info(service, config_id, token):
    try:
        return config_info(service, config_id, token)
    except QmiError as error:
        # This build returns 0x0029 for an unknown software config ID and
        # 0x0010 for an unprovisioned config type.
        if str(error) in (
                "PDC indication error 0x0010",
                "PDC indication error 0x0029"):
            return None
        raise


def load_config(service, image, token):
    total = len(image)
    received_total = 0
    for offset in range(0, total, CHUNK_SIZE):
        chunk = image[offset:offset + CHUNK_SIZE]
        descriptor = (
            struct.pack("<IB", SOFTWARE_CONFIG, len(PROBE_ID)) + PROBE_ID +
            struct.pack("<IH", total, len(chunk)) + chunk
        )
        result = request_indication(
            service,
            PDC_LOAD_CONFIG,
            tlv(0x01, descriptor) + tlv(0x10, struct.pack("<I", token)),
            token,
        )
        received = struct.unpack("<I", result.get(0x11, [b"\x00" * 4])[0][:4])[0]
        remaining = struct.unpack("<I", result.get(0x12, [b"\x00" * 4])[0][:4])[0]
        received_total += len(chunk)
        if received not in (len(chunk), received_total):
            raise QmiError(
                f"unexpected PDC received count {received} at offset {offset}")
        if remaining != total - received_total:
            raise QmiError(
                f"unexpected PDC remaining size {remaining} at offset {offset}")
        token += 1
    return token


def delete_config(service, token):
    payload = (
        tlv(0x01, struct.pack("<I", SOFTWARE_CONFIG)) +
        tlv(0x10, struct.pack("<I", token)) +
        tlv(0x11, bytes([len(PROBE_ID)]) + PROBE_ID)
    )
    response = parse_tlvs(service.request(PDC_DELETE_CONFIG, payload, timeout=8.0))
    check_result(response)


def preserved_original(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_id = bytes.fromhex(manifest["pdc"]["software"]["active_id"])
    backup = Path(manifest["on_device_backup"])
    image = backup.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError(
            f"preserved MBN hash mismatch: expected {manifest['sha256']}, got {digest}")
    return manifest, original_id, image, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "load", "delete"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if args.action != "check" and args.confirm != CONFIRMATION:
        raise ValueError(f"mutable action requires --confirm {CONFIRMATION}")

    manifest, original_id, image, digest = preserved_original(args.manifest)
    if PROBE_ID == original_id:
        raise ValueError("fixed probe ID unexpectedly matches original ID")

    sock = M3200Modem._new_sock()
    try:
        service = QmiService(sock, PDC_SERVICE)
        token = 0x4D326000
        selected = selected_config(service, token + 1)
        if selected["active_id"] != original_id or selected["pending_id"]:
            raise ValueError("refusing: original is not solely active")
        before = optional_config_info(service, PROBE_ID, token + 2)
        output = {
            "action": args.action,
            "active_id": selected["active_id"].hex(),
            "probe_id_ascii": PROBE_ID.decode("ascii"),
            "probe_id_hex": PROBE_ID.hex(),
            "preserved_mbn_sha256": digest,
            "probe_before": before,
        }
        if args.action == "load":
            if before is not None:
                raise ValueError("refusing: fixed probe ID already exists")
            token = load_config(service, image, token + 3)
            after = config_info(service, PROBE_ID, token + 1)
            if after.get("total_size") != len(image):
                raise QmiError("loaded probe size does not match preserved MBN")
            output["probe_after"] = after
        elif args.action == "delete":
            if before is None:
                raise ValueError("refusing: fixed probe ID is already absent")
            if PROBE_ID in (selected["active_id"], selected["pending_id"]):
                raise ValueError("refusing to delete selected profile")
            delete_config(service, token + 3)
            time.sleep(0.5)
            after = optional_config_info(service, PROBE_ID, token + 4)
            if after is not None:
                raise QmiError("probe profile still exists after delete")
            output["probe_after"] = None
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
