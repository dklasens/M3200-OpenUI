#!/usr/bin/env python3
"""Safely show, set, or restore the M3200 NAS RAT mode preference.

The first state-changing invocation preserves the original preference in a
root-only file on the device.  It never changes band masks or carrier MCFG.
"""

import argparse
import json
import os
import sys
import tempfile


AGENT_DIR = "/data/m3200-openui"
BASELINE = os.path.join(AGENT_DIR, "rat-mode-baseline.json")
sys.path.insert(0, AGENT_DIR)

from qmi import M3200Modem, QmiError  # noqa: E402


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".rat-mode-", dir=AGENT_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def save_baseline(current):
    if os.path.exists(BASELINE):
        return
    modes = current.get("mode_pref") or []
    if not modes:
        raise QmiError("the modem did not report a mode preference")
    atomic_json(BASELINE, {"mode_pref": modes,
                           "mode_pref_mask": current.get("mode_pref_mask")})


def normalized_modes(modes):
    aliases = {"nr5g_sa": "nr5g", "nr5g_nsa": "nr5g"}
    normalized = []
    for mode in modes:
        mode = aliases.get(mode, mode)
        if mode not in normalized:
            normalized.append(mode)
    return normalized


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("show", "lte-only", "lte-nr",
                                           "nr-only", "restore"))
    parser.add_argument("--duration", choices=("power_cycle", "permanent"),
                        default="permanent")
    args = parser.parse_args()

    modem = M3200Modem(ttl=0)
    try:
        before = modem.band_prefs()
        if args.action == "show":
            print(json.dumps({"current": before.get("mode_pref", []),
                              "baseline_saved": os.path.exists(BASELINE)},
                             sort_keys=True))
            return 0

        save_baseline(before)
        if args.action == "lte-only":
            requested = ["lte"]
        elif args.action == "lte-nr":
            requested = ["lte", "nr5g"]
        elif args.action == "nr-only":
            requested = ["nr5g"]
        else:
            with open(BASELINE, encoding="ascii") as stream:
                requested = normalized_modes(
                    json.load(stream).get("mode_pref") or [])
            if not requested:
                raise QmiError("saved baseline contains no RAT modes")

        after = modem.set_mode_pref(requested, duration=args.duration)
        verified = after.get("mode_pref") == requested
        print(json.dumps({"before": before.get("mode_pref", []),
                          "requested": requested,
                          "after": after.get("mode_pref", []),
                          "duration": args.duration,
                          "verified": verified}, sort_keys=True))
        return 0 if verified else 2
    finally:
        modem.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, QmiError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
