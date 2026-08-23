#!/usr/bin/env python3
"""Export standards-decoded CA/MR-DC combinations from a targeted DIAG DLF."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from decode_rrc_capabilities import (
    choice_path,
    find_key,
    lte_rrc_messages,
    nr_rrc_messages,
    records,
)


def first_key(value, key):
    return next(find_key(value, key), None)


def qxdm_time(raw: int) -> str:
    seconds = (raw >> 20) / 50 + 315964800 + (raw & 0xFFFFF) / 0x100000
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def capture_times(path: Path):
    timestamps = []
    with path.open("rb") as stream:
        while True:
            header = stream.read(12)
            if not header:
                break
            length = int.from_bytes(header[0:2], "little")
            timestamps.append(int.from_bytes(header[4:12], "little"))
            stream.seek(length - 12, 1)
    return qxdm_time(timestamps[0]), qxdm_time(timestamps[-1])


def component(rat, band, dl_class=None, ul_class=None):
    return {
        "rat": rat,
        "band": int(band),
        "dl_class": dl_class.upper() if dl_class else None,
        "ul_class": ul_class.upper() if ul_class else None,
    }


def label(components):
    pieces = []
    for item in components:
        prefix = "B" if item["rat"] == "lte" else "n"
        pieces.append(f'{prefix}{item["band"]}{item["dl_class"] or ""}')
    return " + ".join(pieces)


def lte_combinations(capability):
    combinations = first_key(capability, "supportedBandCombinationReduced-r13") or []
    result = []
    for index, combination in enumerate(combinations, start=1):
        components = []
        for item in combination.get("bandParameterList-r13", []):
            dl = item.get("bandParametersDL-r13", {})
            ul = item.get("bandParametersUL-r13", {})
            components.append(
                component(
                    "lte",
                    item["bandEUTRA-r13"],
                    dl.get("ca-BandwidthClassDL-r13"),
                    ul.get("ca-BandwidthClassUL-r10"),
                )
            )
        is_ca = len(components) > 1 or any(
            item["dl_class"] not in (None, "A") for item in components
        )
        result.append(
            {
                "index": index,
                "label": label(components),
                "is_ca": is_ca,
                "components": components,
            }
        )
    return result


def mrdc_combinations(capability):
    combinations = first_key(capability, "supportedBandCombinationList") or []
    result = []
    for index, combination in enumerate(combinations, start=1):
        components = []
        for rat, item in combination.get("bandList", []):
            if rat == "eutra":
                components.append(
                    component(
                        "lte",
                        item["bandEUTRA"],
                        item.get("ca-BandwidthClassDL-EUTRA"),
                        item.get("ca-BandwidthClassUL-EUTRA"),
                    )
                )
            elif rat == "nr":
                components.append(
                    component(
                        "nr",
                        item["bandNR"],
                        item.get("ca-BandwidthClassDL-NR"),
                        item.get("ca-BandwidthClassUL-NR"),
                    )
                )
        result.append(
            {
                "index": index,
                "label": label(components),
                "feature_set_combination": combination.get("featureSetCombination"),
                "components": components,
            }
        )
    return result


def nr_combinations(capability):
    combinations = first_key(capability, "supportedBandCombinationList") or []
    result = []
    for index, combination in enumerate(combinations, start=1):
        components = []
        for item in combination.get("bandList", []):
            if isinstance(item, tuple):
                rat, item = item
                if rat != "nr":
                    continue
            components.append(
                component(
                    "nr",
                    item["bandNR"],
                    item.get("ca-BandwidthClassDL-NR"),
                    item.get("ca-BandwidthClassUL-NR"),
                )
            )
        result.append(
            {"index": index, "label": label(components), "components": components}
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dlf", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--firmware", default="THN-1.33.1.1")
    parser.add_argument("--network", default="Optus AU (505-02)")
    parser.add_argument(
        "--merge-from", type=Path,
        help="reuse LTE/MR-DC sections from an earlier standards export",
    )
    args = parser.parse_args()

    from pycrate_asn1dir import RRCLTE, RRCNR

    ul_decoder = RRCLTE.EUTRA_RRC_Definitions.UL_DCCH_Message
    decoders = {
        "eutra": RRCLTE.EUTRA_RRC_Definitions.UE_EUTRA_Capability,
        "eutra-nr": RRCNR.NR_RRC_Definitions.UE_MRDC_Capability,
        "nr": RRCNR.NR_RRC_Definitions.UE_NR_Capability,
    }
    capabilities = {}
    capture_paths = []
    for (_version, pdu_number), content in lte_rrc_messages(args.dlf):
        if pdu_number != 11:
            continue
        ul_decoder.from_uper(content)
        value = ul_decoder.get_val()
        if "ueCapabilityInformation" not in choice_path(value):
            continue
        for containers in find_key(value, "ue-CapabilityRAT-ContainerList"):
            for container_value in containers:
                rat = container_value["rat-Type"]
                decoder = decoders.get(rat)
                if decoder is None:
                    continue
                decoder.from_uper(container_value["ueCapabilityRAT-Container"])
                capabilities[rat] = decoder.get_val()
                if "LTE RRC" not in capture_paths:
                    capture_paths.append("LTE RRC")

    nr_ul_decoder = RRCNR.NR_RRC_Definitions.UL_DCCH_Message
    for metadata, content in nr_rrc_messages(args.dlf):
        if metadata["pdu_number"] not in (0x08, 0x0A):
            continue
        nr_ul_decoder.from_uper(content)
        value = nr_ul_decoder.get_val()
        if "ueCapabilityInformation" not in choice_path(value):
            continue
        for containers in find_key(value, "ue-CapabilityRAT-ContainerList"):
            for container_value in containers:
                rat = container_value["rat-Type"]
                decoder = decoders.get(rat)
                payload = (
                    container_value.get("ue-CapabilityRAT-Container")
                    or container_value.get("ueCapabilityRAT-Container")
                )
                if decoder is None or payload is None:
                    continue
                decoder.from_uper(payload)
                capabilities[rat] = decoder.get_val()
                if "NR RRC" not in capture_paths:
                    capture_paths.append("NR RRC")

    if "nr" not in capabilities:
        raise SystemExit("missing NR capability container")

    lte = lte_combinations(capabilities["eutra"]) if "eutra" in capabilities else []
    mrdc = (
        mrdc_combinations(capabilities["eutra-nr"])
        if "eutra-nr" in capabilities else []
    )
    nr = nr_combinations(capabilities["nr"])
    merged_capture = None
    if args.merge_from:
        previous = json.loads(args.merge_from.read_text(encoding="utf-8"))
        if not lte:
            lte = previous.get("lte", [])
        if not mrdc:
            mrdc = previous.get("mrdc", [])
        merged_capture = previous.get("capture")
    started, completed = capture_times(args.dlf)
    all_components = [
        item
        for combination in (*lte, *mrdc, *nr)
        for item in combination["components"]
    ]
    result = {
        "schema_version": 1,
        "device": {"platform": "Qualcomm SDX62", "firmware": args.firmware},
        "capture": {
            "started_at": started,
            "completed_at": completed,
            "network": args.network,
            "sha256": hashlib.sha256(args.dlf.read_bytes()).hexdigest(),
            "method": (
                "UECapabilityInformation decoded from Qualcomm DIAG "
                f"{' + '.join(capture_paths)} OTA"
            ),
            "scope": "Network-filtered combinations advertised during this attachment",
        },
        "summary": {
            "lte_configurations": len(lte),
            "lte_ca_configurations": sum(item["is_ca"] for item in lte),
            "mrdc_configurations": len(mrdc),
            "nr_ca_configurations": len(nr),
            "lte_bands": sorted(
                {item["band"] for item in all_components if item["rat"] == "lte"}
            ),
            "nr_bands": sorted(
                {item["band"] for item in all_components if item["rat"] == "nr"}
            ),
        },
        "lte": lte,
        "mrdc": mrdc,
        "nr": nr,
        "notes": [
            "The LTE list is supportedBandCombinationReduced-r13.",
            "The MR-DC list is supportedBandCombinationList from the eutra-nr container and represents the LTE+NR combinations advertised to this network.",
            "The NR list is supportedBandCombinationList from the standards-decoded NR capability container.",
            "Carrier deployment, cell configuration, subscription, signal, and current band preferences can further limit which advertised combination becomes active.",
        ],
    }
    if merged_capture:
        result["capture"]["supplemental_capture"] = merged_capture
        result["capture"]["scope"] = (
            "NR capability is Vodafone-SA-filtered; LTE/MR-DC capability is "
            "from the supplemental Optus NSA attachment"
        )
        result["notes"].append(
            "LTE and MR-DC sections were retained from the supplemental "
            "standards-decoded attachment because the SA enquiry did not "
            "request an MR-DC container."
        )
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
