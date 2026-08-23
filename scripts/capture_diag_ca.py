#!/usr/bin/env python3
"""Capture only LTE/NR RRC and supported-CA Qualcomm DIAG records.

This is a small, deliberately narrow adapter around QCSuper.  It avoids the
very broad log mask used by a normal DLF dump and writes a QXDM-compatible DLF
containing only the four records needed to determine supported CA/EN-DC
combinations.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from threading import Timer


TARGET_LOGS = {
    0xB0C0: "LTE RRC OTA",
    0xB0CD: "LTE supported CA combinations",
    0xB821: "NR RRC OTA",
    0xB826: "NR supported CA combinations",
}


def default_qcsuper_source() -> Path:
    return Path(os.environ.get("TEMP", ".")) / "M3200-QCSuper" / "src"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tcp", default="127.0.0.1:43556")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--qcsuper-src", type=Path, default=default_qcsuper_source())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.qcsuper_src.resolve()
    if not (source / "qcsuper" / "__init__.py").is_file():
        raise SystemExit(f"QCSuper source package not found at {source}")
    sys.path.insert(0, str(source))

    from qcsuper.inputs.tcp_connector import TcpConnector
    from qcsuper.modules._enable_log_mixin import EnableLogMixin

    class TargetedCapture(EnableLogMixin):
        def __init__(self, diag_input, output: Path, duration: float):
            self.diag_input = diag_input
            self.limit_registered_logs = set(TARGET_LOGS)
            self.output = output
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.stream = self.output.open("wb")
            self.duration = duration
            self.counts = Counter()
            self.timer = None

        def on_init(self):
            super().on_init()
            enabled = ", ".join(
                f"0x{code:04x} ({name})" for code, name in TARGET_LOGS.items()
            )
            print(f"capture ready; enabled {enabled}", flush=True)
            self.timer = Timer(self.duration, self._stop)
            self.timer.daemon = True
            self.timer.start()

        def _stop(self):
            with self.diag_input.shutdown_event:
                self.diag_input.shutdown_event.notify()

        def on_log(self, log_type, log_payload, log_header, timestamp=0):
            if log_type not in TARGET_LOGS:
                return
            self.stream.write(log_header + log_payload)
            self.stream.flush()
            self.counts[log_type] += 1

        def on_deinit(self):
            if self.timer is not None:
                self.timer.cancel()
            super().on_deinit()
            summary = ", ".join(
                f"0x{code:04x}={self.counts[code]}" for code in TARGET_LOGS
            )
            print(f"capture complete; {summary}", flush=True)

        def __del__(self):
            if not self.stream.closed:
                self.stream.close()

    connector = TcpConnector(args.tcp)
    capture = TargetedCapture(connector, args.output, args.duration)
    connector.add_module(capture)
    try:
        connector.run()
    finally:
        connector.dispose()


if __name__ == "__main__":
    main()
