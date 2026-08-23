#!/usr/bin/env python3
"""Temporarily isolate NR NSA or SA using their independent QMI band masks."""

import argparse
import json
import os
import sys
import tempfile


AGENT_DIR = "/data/m3200-openui"
BASELINE = os.path.join(AGENT_DIR, "nr-path-baseline.json")
sys.path.insert(0, AGENT_DIR)

from qmi import M3200Modem, QmiError  # noqa: E402


def selection(preferences):
    return {
        "lte_bands": (preferences.get("lte_bands_ext") or
                      preferences.get("lte_bands") or []),
        "nr5g_sa_bands": preferences.get("nr5g_sa_bands") or [],
        "nr5g_nsa_bands": preferences.get("nr5g_nsa_bands") or [],
    }


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".nr-path-", dir=AGENT_DIR)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("show", "nsa-only", "sa-only",
                                           "restore"))
    parser.add_argument("--duration", choices=("power_cycle", "permanent"),
                        default="power_cycle")
    args = parser.parse_args()

    modem = M3200Modem(ttl=0)
    try:
        before = selection(modem.band_prefs())
        if args.action == "show":
            print(json.dumps({"current": before,
                              "baseline_saved": os.path.exists(BASELINE)},
                             sort_keys=True))
            return 0

        if not os.path.exists(BASELINE):
            if not all(before.values()):
                raise QmiError("cannot save an incomplete NR-path baseline")
            atomic_json(BASELINE, before)

        if args.action == "restore":
            with open(BASELINE, encoding="ascii") as stream:
                requested = json.load(stream)
        elif args.action == "nsa-only":
            requested = dict(before)
            if not requested["nr5g_nsa_bands"]:
                with open(BASELINE, encoding="ascii") as stream:
                    requested["nr5g_nsa_bands"] = json.load(stream)["nr5g_nsa_bands"]
            if not requested["nr5g_nsa_bands"]:
                raise QmiError("no NSA bands are available in the saved baseline")
            requested["nr5g_sa_bands"] = []
        else:
            requested = dict(before)
            if not requested["nr5g_sa_bands"]:
                with open(BASELINE, encoding="ascii") as stream:
                    requested["nr5g_sa_bands"] = json.load(stream)["nr5g_sa_bands"]
            if not requested["nr5g_sa_bands"]:
                raise QmiError("no SA bands are available in the saved baseline")
            requested["nr5g_nsa_bands"] = []

        after = modem.set_band_prefs(
            requested["lte_bands"], requested["nr5g_sa_bands"],
            requested["nr5g_nsa_bands"], duration=args.duration,
            allow_empty_nr=True)
        actual = selection(after)
        verified = actual == requested
        print(json.dumps({"before": before, "requested": requested,
                          "after": actual, "duration": args.duration,
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
