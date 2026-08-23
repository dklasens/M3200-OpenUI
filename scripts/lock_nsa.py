#!/usr/bin/env python3
"""Apply or restore a guarded LTE-anchor + NR-NSA-only band lock."""

import argparse
import json
import os
import sys
import tempfile


AGENT_DIR = "/data/m3200-openui"
BASELINE = os.path.join(AGENT_DIR, "nsa-lock-baseline.json")
sys.path.insert(0, AGENT_DIR)

from qmi import M3200Modem, QmiError  # noqa: E402


def selection(preferences):
    return {
        "mode_pref": preferences.get("mode_pref") or [],
        "lte_bands": (preferences.get("lte_bands_ext") or
                      preferences.get("lte_bands") or []),
        "nr5g_sa_bands": preferences.get("nr5g_sa_bands") or [],
        "nr5g_nsa_bands": preferences.get("nr5g_nsa_bands") or [],
    }


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".nsa-lock-", dir=AGENT_DIR)
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


def apply_state(modem, requested, duration):
    # Set the masks while NR is still disabled where possible, then expose NR.
    modem.set_band_prefs(
        requested["lte_bands"], requested["nr5g_sa_bands"],
        requested["nr5g_nsa_bands"], duration=duration,
        allow_empty_nr=True)
    modem.set_mode_pref(requested["mode_pref"], duration=duration)
    modem._invalidate("bandprefs")
    return selection(modem.band_prefs())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("show", "apply", "restore"))
    parser.add_argument("--lte-bands", type=int, nargs="+", default=[5])
    parser.add_argument("--nr-bands", type=int, nargs="+", default=[28, 78])
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

        if args.action == "apply":
            if not os.path.exists(BASELINE):
                atomic_json(BASELINE, before)
            requested = {
                "mode_pref": ["lte", "nr5g"],
                "lte_bands": sorted(set(args.lte_bands)),
                "nr5g_sa_bands": [],
                "nr5g_nsa_bands": sorted(set(args.nr_bands)),
            }
        else:
            if not os.path.exists(BASELINE):
                raise QmiError("no NSA-lock baseline has been saved")
            with open(BASELINE, encoding="ascii") as stream:
                requested = json.load(stream)

        try:
            after = apply_state(modem, requested, args.duration)
        except Exception:
            # A partial two-message write is more dangerous than a failed lock.
            # Best-effort rollback uses the just-captured state for apply, or the
            # saved baseline for restore.
            rollback = before if args.action == "apply" else requested
            try:
                apply_state(modem, rollback, args.duration)
            except Exception:
                pass
            raise

        verified = after == requested
        print(json.dumps({
            "before": before,
            "requested": requested,
            "after": after,
            "duration": args.duration,
            "verified": verified,
            "baseline": BASELINE,
        }, sort_keys=True))
        return 0 if verified else 2
    finally:
        modem.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, QmiError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
