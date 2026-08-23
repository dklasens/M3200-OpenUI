#!/usr/bin/env python3
"""Build a focused, reproducible diff of decoded Qualcomm MCFG profiles."""

import argparse
import hashlib
import json
from pathlib import Path


DEFAULT_PROFILES = {
    "vodafone-au": Path("captures/vodafone-mcfg/original-decoded"),
    "dish-us": Path("captures/vodafone-mcfg/comparators/dish-us-decoded"),
    "tmo-us": Path("captures/vodafone-mcfg/comparators/tmo-us-decoded"),
    "cmcc-open": Path("captures/vodafone-mcfg/comparators/cmcc-open-decoded"),
    "optus-au": Path("captures/vodafone-mcfg/comparators/optus-au-decoded"),
    "telstra-au": Path("captures/vodafone-mcfg/comparators/telstra-au-decoded"),
    "row-commercial": Path(
        "captures/vodafone-mcfg/comparators/row-commercial-decoded"),
}

CANDIDATE_TERMS = (
    "nr5g",
    "mrdc",
    "endc",
    "carrier_policy",
    "rat_acq",
    "is_x_to_nr",
    "l2nr",
    "lte_feature",
    "cap_feature",
    "ca_combo",
    "ursp",
    "vonr",
    "dynamic_sa",
    "sa_enable",
    "disable_mode",
)

COMPARISON_PAIRS = (
    ("vodafone-au", "optus-au"),
    ("vodafone-au", "telstra-au"),
    ("vodafone-au", "row-commercial"),
    ("vodafone-au", "cmcc-open"),
)


def file_index(decoded):
    root = decoded / "files"
    output = {}
    if not root.is_dir():
        return output
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        output[relative] = {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "hex": data.hex(" ") if len(data) <= 64 else None,
        }
    return output


def metadata(decoded):
    with (decoded / "meta").open(encoding="utf-8") as stream:
        meta = json.load(stream)
    operator = meta.get("trailer", {}).get("operator", {}).get("ascii")
    return {
        "operator": operator,
        "version": meta.get("version", {}).get("hex"),
        "item_count": len(json.loads((decoded / "nv_items").read_text(
            encoding="utf-8"))),
    }


def legacy_nv_index(decoded):
    """Normalize legacy numeric NV items so profile ordering does not affect diffs."""
    items = json.loads((decoded / "nv_items").read_text(encoding="utf-8"))
    output = {}
    for item in items:
        if item.get("type") != 1:
            continue
        key = str(item["nv_id"])
        output.setdefault(key, []).append({
            "attributes": item["attributes"],
            "hex": item["data"]["hex"],
        })
    return {key: sorted(value, key=lambda entry: json.dumps(entry, sort_keys=True))
            for key, value in sorted(output.items(), key=lambda pair: int(pair[0]))}


def diff_indexes(left, right):
    left_keys = set(left)
    right_keys = set(right)
    changed = {
        key: {"left": left[key], "right": right[key]}
        for key in sorted(left_keys & right_keys)
        if left[key] != right[key]
    }
    return {
        "left_only": sorted(left_keys - right_keys),
        "right_only": sorted(right_keys - left_keys),
        "changed": changed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--summary-pair", nargs=2, metavar=("LEFT", "RIGHT"),
        choices=sorted(DEFAULT_PROFILES),
        help="print a compact full diff for two decoded profiles")
    args = parser.parse_args()

    indexes = {name: file_index(path) for name, path in DEFAULT_PROFILES.items()}
    legacy_indexes = {
        name: legacy_nv_index(path) for name, path in DEFAULT_PROFILES.items()
    }
    if args.summary_pair:
        left, right = args.summary_pair
        summary = {
            "profiles": [left, right],
            "files": diff_indexes(indexes[left], indexes[right]),
            "legacy_nv": diff_indexes(
                legacy_indexes[left], legacy_indexes[right]),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    candidates = sorted({
        path
        for index in indexes.values()
        for path in index
        if any(term in path.lower() for term in CANDIDATE_TERMS)
    })

    candidate_values = {}
    for path in candidates:
        values = {}
        for name, index in indexes.items():
            if path in index:
                values[name] = index[path]
        candidate_values[path] = values

    report = {
        "profiles": {
            name: metadata(path) | {"file_count": len(indexes[name])}
            for name, path in DEFAULT_PROFILES.items()
        },
        "candidate_terms": list(CANDIDATE_TERMS),
        "candidate_files": candidate_values,
        "comparisons": {
            "{}_vs_{}".format(left, right): {
                "files": diff_indexes(indexes[left], indexes[right]),
                "legacy_nv": diff_indexes(
                    legacy_indexes[left], legacy_indexes[right]),
            }
            for left, right in COMPARISON_PAIRS
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
