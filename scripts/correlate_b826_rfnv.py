#!/usr/bin/env python3
"""Correlate captured Qualcomm 0xB826 band records with RFNV backups.

This is deliberately read-only.  It looks for exact component and combination
byte sequences in the raw files and in any discoverable zlib streams; a match
is evidence about storage provenance, not permission to edit the containing
item.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import zlib

from decode_rrc_capabilities import decode_b826_body, records


def zlib_streams(data):
    """Yield successfully decoded zlib streams and their source offsets."""
    for offset in range(len(data) - 1):
        if data[offset] != 0x78:
            continue
        try:
            decoded = zlib.decompress(data[offset:])
        except zlib.error:
            continue
        if decoded:
            yield offset, decoded


def patterns(dlf):
    components = Counter()
    combinations = Counter()
    tables = []
    for log_type, body in records(dlf):
        if log_type != 0xB826:
            continue
        decoded = decode_b826_body(body)
        tables.append({key: decoded[key] for key in ("total", "start", "count")})
        for combo in decoded["combinations"]:
            sequence = bytearray()
            for band in combo["bands"]:
                record = bytes.fromhex(band["flags"])
                components[record] += 1
                sequence.extend(record)
            combinations[bytes(sequence)] += 1
    return tables, components, combinations


def scan_blob(name, data, components, combinations, representation, source_offset=0):
    hits = []
    for kind, candidates in (("combination", combinations), ("component", components)):
        for candidate, capture_count in candidates.items():
            start = 0
            while True:
                offset = data.find(candidate, start)
                if offset < 0:
                    break
                hits.append({
                    "kind": kind,
                    "representation": representation,
                    "source_offset": source_offset,
                    "offset": offset,
                    "length": len(candidate),
                    "hex": candidate.hex(),
                    "capture_occurrences": capture_count,
                })
                start = offset + 1
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dlf", type=Path)
    parser.add_argument("rfnv", type=Path, nargs="+", help="RFNV files or directories")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    files = []
    for candidate in args.rfnv:
        if candidate.is_dir():
            files.extend(sorted(candidate.glob("rfnv-*.bin")))
        else:
            files.append(candidate)

    tables, components, combinations = patterns(args.dlf)
    matches = {}
    for path in files:
        data = path.read_bytes()
        hits = scan_blob(path.name, data, components, combinations, "raw")
        for offset, decoded in zlib_streams(data):
            hits.extend(scan_blob(
                path.name, decoded, components, combinations,
                "zlib", source_offset=offset))
        if hits:
            matches[path.as_posix()] = hits

    report = {
        "capture": args.dlf.as_posix(),
        "tables": tables,
        "unique_component_patterns": len(components),
        "unique_combination_patterns": len(combinations),
        "files_scanned": len(files),
        "matching_files": matches,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
