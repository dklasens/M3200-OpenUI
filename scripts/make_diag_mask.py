#!/usr/bin/env python3
"""Build a minimal Qualcomm DIAG mask for M3200 CA capability capture.

The output is a QXDM-style stream of pseudo-HDLC framed DIAG commands, suitable
for ``diag_mdlog -f``.  Only four APPS/LTE/NR records are enabled:

* 0xB0C0 LTE RRC OTA messages
* 0xB0CD LTE supported CA combinations
* 0xB821 NR RRC OTA messages
* 0xB826 NR supported CA combinations
"""

import argparse
import struct
from pathlib import Path


DIAG_LOG_CONFIG_F = 0x73
LOG_CONFIG_SET_MASK_OP = 3
EQUIPMENT_ID_APPS_LTE_NR = 0x0B
LAST_ITEM = 0x09FF
LOG_ITEMS = (0x0C0, 0x0CD, 0x821, 0x826)


def crc16_ccitt(payload: bytes) -> int:
    """Qualcomm DIAG CRC-16 (poly 0x1021, reflected, xor-out 0xffff)."""
    crc = 0xFFFF
    for octet in payload:
        crc ^= octet
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def hdlc_frame(payload: bytes) -> bytes:
    payload += struct.pack("<H", crc16_ccitt(payload))
    framed = bytearray()
    for octet in payload:
        if octet in (0x7D, 0x7E):
            framed.extend((0x7D, octet ^ 0x20))
        else:
            framed.append(octet)
    framed.append(0x7E)
    return bytes(framed)


def log_mask_command() -> bytes:
    mask = bytearray((LAST_ITEM // 8) + 1)
    for item in LOG_ITEMS:
        mask[item // 8] |= 1 << (item % 8)
    return struct.pack(
        "<IIII",
        DIAG_LOG_CONFIG_F,
        LOG_CONFIG_SET_MASK_OP,
        EQUIPMENT_ID_APPS_LTE_NR,
        LAST_ITEM,
    ) + mask


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = hdlc_frame(log_mask_command())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"wrote {len(data)} bytes to {args.output}")


if __name__ == "__main__":
    main()
