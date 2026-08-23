#!/usr/bin/env python3
"""Export compact, standards-decoded NR SCell evidence from DIAG captures."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from decode_rrc_capabilities import find_key, nr_rrc_messages
from export_ca_combinations import capture_times


NR_ARFCN_BANDS = (
    (620000, 653333, 78),
    (422000, 434000, 1),
    (151600, 160600, 28),
)


def nr_band(arfcn):
    for low, high, band in NR_ARFCN_BANDS:
        if low <= arfcn <= high:
            return band
    return None


def requested_bands(path):
    return sorted({int(value) for value in re.findall(r"-n(\d+)", path.stem)})


def compact_scell(item):
    common = item.get("sCellConfigCommon", {})
    downlink = common.get("downlinkConfigCommon", {})
    frequency = downlink.get("frequencyInfoDL", {})
    bands = frequency.get("frequencyBandList", [])
    return {
        "rat": "nr",
        "role": "scell",
        "band": int(bands[0]) if bands else None,
        "pci": common.get("physCellId"),
        "arfcn": frequency.get("absoluteFrequencySSB"),
    }


def decode_capture(path, decoder):
    primaries = Counter()
    scells = {}
    reconfigurations = 0
    for metadata, content in nr_rrc_messages(path):
        if metadata["pdu_number"] != 0x04:
            continue
        arfcn = metadata.get("arfcn", metadata.get("frequency_raw"))
        if arfcn is not None and metadata.get("pci") not in (None, 0xFFFF):
            primaries[(arfcn, metadata["pci"])] += 1
        decoder.from_uper(content)
        value = decoder.get_val()
        for lists in find_key(value, "sCellToAddModList"):
            reconfigurations += 1
            for item in lists:
                scell = compact_scell(item)
                key = (scell["band"], scell["arfcn"], scell["pci"])
                scells[key] = scell

    if not primaries:
        raise ValueError(f"no NR DL-DCCH primary found in {path}")
    (primary_arfcn, primary_pci), _count = primaries.most_common(1)[0]
    primary = {
        "rat": "nr",
        "role": "pcc",
        "band": nr_band(primary_arfcn),
        "pci": primary_pci,
        "arfcn": primary_arfcn,
    }
    components = [primary] + sorted(
        scells.values(), key=lambda item: (item["band"] or 0, item["arfcn"] or 0)
    )
    label = " + ".join(
        f"n{item['band']} ({'PCC' if item['role'] == 'pcc' else 'SCell'})"
        for item in components
    )
    started, completed = capture_times(path)
    return {
        "requested_sa_bands": requested_bands(path),
        "label": label,
        "component_count": len(components),
        "scell_configured": bool(scells),
        "components": components,
        "scell_add_reconfigurations": reconfigurations,
        "capture": {
            "file": path.as_posix(),
            "started_at": started,
            "completed_at": completed,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dlf", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--network", default="Vodafone AU (505-03)")
    args = parser.parse_args()

    from pycrate_asn1dir import RRCNR

    decoder = RRCNR.NR_RRC_Definitions.DL_DCCH_Message
    cases = [decode_capture(path, decoder) for path in args.dlf]
    validated_layouts = sorted({
        tuple(sorted(item["band"] for item in case["components"]))
        for case in cases if case["scell_configured"]
    })
    result = {
        "schema_version": 1,
        "network": args.network,
        "method": "3GPP NR RRC CellGroupConfig decoded from Qualcomm 0xB821 DIAG",
        "scope": "Controlled SA band-mask tests during bounded downlink traffic",
        "cases": cases,
        "conclusion": {
            "max_component_count": max(case["component_count"] for case in cases),
            "validated_ca_layouts": [list(layout) for layout in validated_layouts],
            "non_ca_masks": [
                case["requested_sa_bands"] for case in cases
                if not case["scell_configured"]
            ],
        },
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
