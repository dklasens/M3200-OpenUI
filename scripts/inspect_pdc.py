#!/usr/bin/env python3
"""Read selected Qualcomm PDC profiles and their public metadata.

This helper is deliberately read-only.  It issues Get Selected Config and Get
Config Info requests; it cannot load, select, activate, or delete a profile.
"""

import json
import socket
import struct
import sys
import time


AGENT_DIR = "/data/m3200-openui"
PDC_SERVICE = 0x24
PDC_GET_SELECTED_CONFIG = 0x22
PDC_GET_CONFIG_INFO = 0x28
CONFIG_TYPES = {"platform": 0, "software": 1}

sys.path.insert(0, AGENT_DIR)

from qmi import M3200Modem, QmiError, QmiService, check_result, parse_tlvs  # noqa: E402


def tlv(kind, payload):
    return struct.pack("<BH", kind, len(payload)) + payload


def indication(service, msgid, transaction, timeout=5.0):
    service.sock.settimeout(timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data, address = service.sock.recvfrom(4096)
        except socket.timeout as error:
            raise QmiError(
                f"PDC indication 0x{msgid:04x} timed out") from error
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
    response_token = struct.unpack("<I", response.get(0x10, [struct.pack("<I", token)])[0])[0]
    if response_token != token:
        raise QmiError(
            f"PDC response token {response_token} did not match {token}")
    result = indication(service, msgid, transaction)
    if 0x01 in result:
        code = struct.unpack("<H", result[0x01][0][:2])[0]
        if code:
            raise QmiError(f"PDC indication error 0x{code:04x}")
    return result


def prefixed_bytes(value):
    if not value:
        return b""
    length = value[0]
    return value[1:1 + length]


def selected_config(service, config_type, token):
    result = request_indication(
        service,
        PDC_GET_SELECTED_CONFIG,
        tlv(0x01, struct.pack("<I", config_type)) +
        tlv(0x10, struct.pack("<I", token)),
        token,
    )
    active = prefixed_bytes(result.get(0x11, [b""])[0])
    pending = prefixed_bytes(result.get(0x12, [b""])[0])
    return active, pending


def config_info(service, config_type, config_id, token):
    if not config_id:
        return {}
    type_and_id = struct.pack("<IB", config_type, len(config_id)) + config_id
    result = request_indication(
        service,
        PDC_GET_CONFIG_INFO,
        tlv(0x01, type_and_id) + tlv(0x10, struct.pack("<I", token)),
        token,
    )
    output = {}
    if 0x11 in result and len(result[0x11][0]) >= 4:
        output["total_size"] = struct.unpack("<I", result[0x11][0][:4])[0]
    if 0x12 in result:
        output["description"] = prefixed_bytes(result[0x12][0]).decode(
            "utf-8", "replace")
    if 0x13 in result and len(result[0x13][0]) >= 4:
        output["version"] = struct.unpack("<I", result[0x13][0][:4])[0]
    return output


def main():
    sock = M3200Modem._new_sock()
    service = None
    try:
        service = QmiService(sock, PDC_SERVICE)
        output = {}
        token = 0x4D320000
        for name, config_type in CONFIG_TYPES.items():
            try:
                token += 1
                active, pending = selected_config(service, config_type, token)
                entry = {
                    "active_id": active.hex(),
                    "pending_id": pending.hex(),
                }
                if active:
                    token += 1
                    entry.update(config_info(service, config_type, active, token))
                output[name] = entry
            except QmiError as error:
                # Some embedded builds have no separately provisioned platform
                # config. Preserve that fact without hiding a valid software MCFG.
                output[name] = {"error": str(error)}
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, QmiError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
