#!/usr/bin/env python3
"""Inspect and decode RRC capability messages from a targeted QCSuper DLF."""

import argparse
import struct
import sys
from collections import Counter
from pathlib import Path


def records(path: Path):
    with path.open("rb") as stream:
        while True:
            header = stream.read(12)
            if not header:
                return
            if len(header) != 12:
                raise ValueError("truncated DLF record header")
            length, log_type, _timestamp = struct.unpack("<HHQ", header)
            if length < 12:
                raise ValueError(f"invalid DLF record length {length}")
            payload = stream.read(length - 12)
            if len(payload) != length - 12:
                raise ValueError("truncated DLF record payload")
            yield log_type, payload


def lte_rrc_messages(path: Path):
    segments = {}
    segment_metadata = None
    for log_type, body in records(path):
        if log_type != 0xB0C0:
            continue
        version = body[0]
        segment_id = 0
        if version >= 30:
            item = struct.unpack("<BBBBBHLHBLHBBB", body[1:24])
            pdu_number, expected, segment_id = item[8], item[10], item[13]
            content = body[24:]
        elif version >= 25:
            item = struct.unpack("<BBBBBHLHBLH", body[1:21])
            pdu_number, expected = item[8], item[10]
            content = body[21:]
        elif version >= 8:
            item = struct.unpack("<BBBHLHBLH", body[1:19])
            pdu_number, expected = item[6], item[8]
            content = body[19:]
        elif version >= 5:
            item = struct.unpack("<BBBHHHBLH", body[1:17])
            pdu_number, expected = item[6], item[8]
            content = body[17:]
        else:
            item = struct.unpack("<BBBHHHBH", body[1:13])
            pdu_number, expected = item[6], item[7]
            content = body[13:]
        if expected != len(content):
            raise ValueError(
                f"LTE RRC v{version} payload is {len(content)} bytes, expected {expected}"
            )
        metadata = (version, pdu_number)
        if not segment_id:
            yield metadata, content
        elif 1 <= segment_id <= 6:
            segments[segment_id] = content
            segment_metadata = metadata
        elif segment_id == 7:
            combined = b"".join(segments[index] for index in sorted(segments)) + content
            yield segment_metadata or metadata, combined
            segments = {}
            segment_metadata = None


NR_RRC_PDU_NAMES = {
    0x01: "BCCH-BCH",
    0x02: "BCCH-DL-SCH",
    0x03: "DL-CCCH",
    0x04: "DL-DCCH",
    0x05: "PCCH",
    0x06: "UL-CCCH",
    0x07: "UL-CCCH1",
    0x08: "UL-DCCH",
    0x09: "RRCReconfiguration",
    0x0A: "UL-DCCH",
    0x18: "RadioBearerConfig",
    0x19: "RadioBearerConfig",
    0x1A: "RadioBearerConfig",
    0x1E: "UE-NR-Capability",
    0x1F: "UE-MRDC-Capability",
}


def nr_rrc_messages(path: Path):
    """Yield Qualcomm 0xB821 NR RRC records with their DIAG header decoded.

    SDX62 firmware THN-1.33.1.1 currently emits the legacy version-14
    layout.  The version-17 layout is also supported so captures remain
    usable if the modem firmware is later changed.
    """
    for log_type, body in records(path):
        if log_type != 0xB821:
            continue
        if not body:
            raise ValueError("empty 0xB821 body")
        version = body[0]
        if version >= 17:
            if len(body) < 31:
                raise ValueError("truncated 0xB821 v17 header")
            metadata = {
                "version": version,
                "release": body[4],
                "rrc_version": body[5],
                "radio_bearer": body[6],
                "pci": int.from_bytes(body[7:9], "little"),
                "arfcn": int.from_bytes(body[17:21], "little"),
                "pdu_number": body[24],
            }
            expected = int.from_bytes(body[29:31], "little")
            content = body[31:]
        else:
            if len(body) < 24:
                raise ValueError("truncated legacy 0xB821 header")
            tentative_length = int.from_bytes(body[22:24], "little")
            extra_offset = 0 if (
                version >= 14
                or (version > 7 and len(body) != 24 + tentative_length)
            ) else 1
            payload_offset = 23 + extra_offset
            metadata = {
                "version": version,
                "release": body[4],
                "rrc_version": body[5],
                "radio_bearer": body[6],
                "pci": int.from_bytes(body[7:9], "little"),
                "frequency_raw": int.from_bytes(
                    body[9 : 12 + extra_offset], "little"
                ),
                "pdu_number": body[16 + extra_offset],
            }
            expected = int.from_bytes(
                body[21 + extra_offset : 23 + extra_offset], "little"
            )
            content = body[payload_offset:]
        if expected != len(content):
            raise ValueError(
                f"NR RRC v{version} payload is {len(content)} bytes, "
                f"expected {expected}"
            )
        yield metadata, content


def choice_path(value):
    path = []
    while True:
        if isinstance(value, dict) and len(value) == 1:
            name, value = next(iter(value.items()))
            path.append(name)
        elif isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
            path.append(value[0])
            value = value[1]
        else:
            break
    return "/".join(path)


def find_key(value, wanted):
    if isinstance(value, dict):
        if wanted in value:
            yield value[wanted]
        for child in value.values():
            yield from find_key(child, wanted)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from find_key(child, wanted)


def matching_keys(value, fragment, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + (str(key),)
            if fragment in str(key):
                yield "/".join(child_path), child
            yield from matching_keys(child, fragment, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from matching_keys(child, fragment, path + (str(index),))
    elif isinstance(value, tuple) and len(value) == 2:
        yield from matching_keys(value[1], fragment, path + (str(value[0]),))


def decode_b826_body(body):
    """Decode the band/RAT skeleton of Qualcomm NR CA-combo log version 9.

    The per-band feature bitfields remain proprietary.  This intentionally
    reports neutral band numbers and raw component flags; it does not guess
    whether a component is LTE or NR.
    """
    if len(body) < 11:
        raise ValueError("truncated 0xB826 header")
    version, total, start, count = struct.unpack("<IHHH", body[:10])
    if version != 9:
        raise ValueError(f"unsupported 0xB826 version {version}")
    offset = 11  # byte 10 is reserved in version 9
    combinations = []
    for sequence in range(count):
        if offset + 13 > len(body):
            raise ValueError(f"truncated 0xB826 combo {start + sequence}")
        combo_flags, reserved, bands_length, feature_bits = struct.unpack(
            "<HBHQ", body[offset : offset + 13]
        )
        offset += 13
        if bands_length % 8 or offset + bands_length > len(body):
            raise ValueError(
                f"invalid 0xB826 band payload length {bands_length} "
                f"for combo {start + sequence}"
            )
        bands = []
        for band_offset in range(offset, offset + bands_length, 8):
            record = body[band_offset : band_offset + 8]
            bands.append(
                {
                    "band": record[0],
                    "flags": record.hex(),
                }
            )
        offset += bands_length
        combinations.append(
            {
                "index": start + sequence,
                "combo_flags": combo_flags,
                "reserved": reserved,
                "feature_bits": feature_bits,
                "bands": bands,
            }
        )
    if offset != len(body):
        raise ValueError(
            f"0xB826 record has {len(body) - offset} unparsed trailing bytes"
        )
    return {
        "version": version,
        "total": total,
        "start": start,
        "count": count,
        "combinations": combinations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dlf", type=Path)
    parser.add_argument("--show", action="store_true", help="show decoded message values")
    parser.add_argument(
        "--preview",
        type=int,
        default=0,
        help="preview this many characters of each UE capability value",
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="show counts for every LTE RRC version/PDU number",
    )
    parser.add_argument(
        "--pdu",
        type=int,
        action="append",
        help="decode only this LTE/NR RRC PDU number (may be repeated)",
    )
    parser.add_argument(
        "--raw-log",
        type=lambda value: int(value, 0),
        help="print raw bodies for this DIAG log type (for example 0xb826)",
    )
    parser.add_argument(
        "--raw-limit",
        type=int,
        default=0,
        help="limit each --raw-log body to this many bytes (0 means unlimited)",
    )
    parser.add_argument(
        "--decode-b826",
        action="store_true",
        help="decode RAT/band layouts from Qualcomm 0xB826 version 9 records",
    )
    parser.add_argument(
        "--nr",
        action="store_true",
        help="also decode Qualcomm 0xB821 NR RRC messages and embedded cell groups",
    )
    args = parser.parse_args()

    if args.raw_log is not None:
        count = 0
        for index, (log_type, body) in enumerate(records(args.dlf), start=1):
            if log_type == args.raw_log:
                count += 1
                shown = body[: args.raw_limit] if args.raw_limit else body
                print(f"#{index} log={log_type:#06x} bytes={len(body)}")
                for offset in range(0, len(shown), 16):
                    chunk = shown[offset : offset + 16]
                    print(f"  {offset:04x}: {' '.join(f'{byte:02x}' for byte in chunk)}")
        print(f"raw log records: {count}")
        return

    if args.decode_b826:
        record_count = 0
        for index, (log_type, body) in enumerate(records(args.dlf), start=1):
            if log_type != 0xB826:
                continue
            record_count += 1
            decoded = decode_b826_body(body)
            print(
                f"#{index} table-total={decoded['total']} "
                f"start={decoded['start']} count={decoded['count']}"
            )
            for combo in decoded["combinations"]:
                layout = " + ".join(
                    f"band{band['band']}[{band['flags']}]"
                    for band in combo["bands"]
                )
                print(f"  {combo['index']:03d}: {layout}")
        print(f"0xB826 records: {record_count}")
        return

    from pycrate_asn1dir import RRCLTE, RRCNR

    # Qualcomm LTE RRC OTA packet v27 channel/PDU numbering.  The adjacent
    # CCCH/DCCH values are useful during an attach because the capability
    # enquiry is downlink while the capability information is uplink.
    decoders = {
        8: ("DL-CCCH", RRCLTE.EUTRA_RRC_Definitions.DL_CCCH_Message),
        9: ("DL-DCCH", RRCLTE.EUTRA_RRC_Definitions.DL_DCCH_Message),
        10: ("UL-CCCH", RRCLTE.EUTRA_RRC_Definitions.UL_CCCH_Message),
        11: ("UL-DCCH", RRCLTE.EUTRA_RRC_Definitions.UL_DCCH_Message),
    }
    container_decoders = {
        "eutra": RRCLTE.EUTRA_RRC_Definitions.UE_EUTRA_Capability,
        "eutra-nr": RRCNR.NR_RRC_Definitions.UE_MRDC_Capability,
        "nr": RRCNR.NR_RRC_Definitions.UE_NR_Capability,
    }
    nr_frequency_band_list = RRCNR.NR_RRC_Definitions.FreqBandList
    counts = Counter()
    failures = Counter()
    inventory = Counter()
    for index, ((version, pdu_number), content) in enumerate(
        lte_rrc_messages(args.dlf), start=1
    ):
        inventory[(version, pdu_number)] += 1
        channel_decoder = decoders.get(pdu_number) if version == 27 else None
        if channel_decoder is None or (args.pdu and pdu_number not in args.pdu):
            continue
        channel, decoder = channel_decoder
        try:
            decoder.from_uper(content)
            value = decoder.get_val()
            path = choice_path(value)
            counts[(version, pdu_number, path)] += 1
            print(
                f"#{index} LTE RRC v{version} pdu={pdu_number} "
                f"channel={channel} bytes={len(content)} {path}",
                flush=True,
            )
            if args.show:
                print(repr(value), flush=True)
            elif args.preview and "ueCapabilityInformation" in path:
                print(repr(value)[: args.preview], flush=True)
            if "ueCapabilityEnquiry" in path:
                for payload in find_key(value, "requestedFreqBandsNR-MRDC-r15"):
                    nr_frequency_band_list.from_uper(payload)
                    print(
                        "  decoded requestedFreqBandsNR-MRDC-r15: "
                        f"{nr_frequency_band_list.get_val()}",
                        flush=True,
                    )
            if "ueCapabilityInformation" in path:
                for containers in find_key(value, "ue-CapabilityRAT-ContainerList"):
                    for container in containers:
                        rat = container["rat-Type"]
                        payload = container["ueCapabilityRAT-Container"]
                        rat_decoder = container_decoders.get(rat)
                        if rat_decoder is None:
                            print(f"  unhandled RAT container {rat} ({len(payload)} bytes)")
                            continue
                        rat_decoder.from_uper(payload)
                        capability = rat_decoder.get_val()
                        print(f"  decoded {rat} container ({len(payload)} bytes)")
                        for field_path, field in matching_keys(
                            capability, "supportedBandCombination"
                        ):
                            size = len(field) if isinstance(field, list) else "present"
                            preview = repr(field[:1] if isinstance(field, list) else field)[:800]
                            print(f"    {field_path}: {size}; first={preview}")
        except Exception as error:
            failures[(version, pdu_number, type(error).__name__)] += 1
            print(
                f"#{index} LTE RRC v{version} pdu={pdu_number} "
                f"channel={channel} bytes={len(content)} decode-error={error}",
                file=sys.stderr,
                flush=True,
            )
    print("message counts:")
    for key, count in counts.items():
        print(f"  {key}: {count}")
    if failures:
        print("decode failures:")
        for key, count in failures.items():
            print(f"  {key}: {count}")
    if args.inventory:
        print("LTE RRC record inventory:")
        for key, count in sorted(inventory.items()):
            print(f"  version={key[0]} pdu={key[1]}: {count}")

    if not args.nr:
        return

    nr_decoders = {
        0x01: RRCNR.NR_RRC_Definitions.BCCH_BCH_Message,
        0x02: RRCNR.NR_RRC_Definitions.BCCH_DL_SCH_Message,
        0x03: RRCNR.NR_RRC_Definitions.DL_CCCH_Message,
        0x04: RRCNR.NR_RRC_Definitions.DL_DCCH_Message,
        0x05: RRCNR.NR_RRC_Definitions.PCCH_Message,
        0x06: RRCNR.NR_RRC_Definitions.UL_CCCH_Message,
        0x07: RRCNR.NR_RRC_Definitions.UL_CCCH1_Message,
        0x08: RRCNR.NR_RRC_Definitions.UL_DCCH_Message,
        0x09: RRCNR.NR_RRC_Definitions.RRCReconfiguration,
        0x0A: RRCNR.NR_RRC_Definitions.UL_DCCH_Message,
        0x18: RRCNR.NR_RRC_Definitions.RadioBearerConfig,
        0x19: RRCNR.NR_RRC_Definitions.RadioBearerConfig,
        0x1A: RRCNR.NR_RRC_Definitions.RadioBearerConfig,
        0x1E: RRCNR.NR_RRC_Definitions.UE_NR_Capability,
        0x1F: RRCNR.NR_RRC_Definitions.UE_MRDC_Capability,
    }
    cell_group_decoder = RRCNR.NR_RRC_Definitions.CellGroupConfig
    nr_counts = Counter()
    nr_failures = Counter()
    nr_inventory = Counter()
    for index, (metadata, content) in enumerate(
        nr_rrc_messages(args.dlf), start=1
    ):
        pdu_number = metadata["pdu_number"]
        channel = NR_RRC_PDU_NAMES.get(pdu_number, f"unknown-{pdu_number:#04x}")
        nr_inventory[(metadata["version"], pdu_number)] += 1
        decoder = nr_decoders.get(pdu_number)
        if decoder is None or (args.pdu and pdu_number not in args.pdu):
            continue
        try:
            decoder.from_uper(content)
            value = decoder.get_val()
            path = choice_path(value)
            nr_counts[(metadata["version"], pdu_number, path)] += 1
            location = (
                f"arfcn={metadata['arfcn']}" if "arfcn" in metadata
                else f"frequency_raw={metadata['frequency_raw']}"
            )
            print(
                f"#{index} NR RRC v{metadata['version']} pdu={pdu_number} "
                f"channel={channel} pci={metadata['pci']} {location} "
                f"bytes={len(content)} {path}",
                flush=True,
            )
            if args.show:
                print(repr(value), flush=True)
            elif args.preview and (
                "ueCapabilityInformation" in path or pdu_number in (0x1E, 0x1F)
            ):
                print(repr(value)[: args.preview], flush=True)

            for field_path, field in matching_keys(value, "supportedBandCombination"):
                size = len(field) if isinstance(field, list) else "present"
                preview = repr(field[:1] if isinstance(field, list) else field)[:800]
                print(f"  {field_path}: {size}; first={preview}")

            for field_path, field in matching_keys(value, "sCell"):
                print(f"  {field_path}: {repr(field)[:4000]}")

            for containers in find_key(value, "ue-CapabilityRAT-ContainerList"):
                for container in containers:
                    rat = container["rat-Type"]
                    payload = (
                        container.get("ue-CapabilityRAT-Container")
                        or container.get("ueCapabilityRAT-Container")
                    )
                    rat_decoder = container_decoders.get(rat)
                    if rat_decoder is None or payload is None:
                        length = len(payload) if payload is not None else 0
                        print(f"  unhandled RAT container {rat} ({length} bytes)")
                        continue
                    rat_decoder.from_uper(payload)
                    capability = rat_decoder.get_val()
                    print(f"  decoded {rat} container ({len(payload)} bytes)")
                    for field_path, field in matching_keys(
                        capability, "supportedBandCombination"
                    ):
                        size = len(field) if isinstance(field, list) else "present"
                        preview = repr(
                            field[:1] if isinstance(field, list) else field
                        )[:800]
                        print(f"    {field_path}: {size}; first={preview}")

            for key in ("secondaryCellGroup", "masterCellGroup"):
                for payload in find_key(value, key):
                    if not isinstance(payload, (bytes, bytearray)):
                        continue
                    cell_group_decoder.from_uper(payload)
                    cell_group = cell_group_decoder.get_val()
                    print(f"  decoded {key} ({len(payload)} bytes)")
                    found = False
                    for field_path, field in matching_keys(cell_group, "sCell"):
                        found = True
                        print(f"    {field_path}: {repr(field)[:2000]}")
                    if not found:
                        print("    no SCell add/release fields present")
        except Exception as error:
            nr_failures[(metadata["version"], pdu_number, type(error).__name__)] += 1
            print(
                f"#{index} NR RRC v{metadata['version']} pdu={pdu_number} "
                f"channel={channel} bytes={len(content)} decode-error={error}",
                file=sys.stderr,
                flush=True,
            )

    print("NR message counts:")
    for key, count in nr_counts.items():
        print(f"  {key}: {count}")
    if nr_failures:
        print("NR decode failures:")
        for key, count in nr_failures.items():
            print(f"  {key}: {count}")
    if args.inventory:
        print("NR RRC record inventory:")
        for key, count in sorted(nr_inventory.items()):
            print(f"  version={key[0]} pdu={key[1]}: {count}")


if __name__ == "__main__":
    main()
