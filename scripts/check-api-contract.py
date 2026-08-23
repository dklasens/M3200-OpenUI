#!/usr/bin/env python3
"""Assert the agent, the dashboard and the mock agent agree on the API surface.

Ported from MU5250-OpenUI: the dashboard is developed against
`web-app/tools/mock_agent.py` rather than the real agent, and the two can
silently drift.  This check closes the loop on the *route* half of that
problem.

Fails if:
  - the dashboard calls an endpoint the agent does not serve  (broken at runtime)
  - the agent serves an endpoint nothing calls                (dead surface)
  - the mock is missing an endpoint the dashboard calls       (broken demos)

Run from anywhere:  python3 scripts/check-api-contract.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_PY = ROOT / "agent/m3200_agent.py"
API_TS = ROOT / "web-app/src/data/api.ts"
CLIENT_TS = ROOT / "web-app/src/data/client.ts"
MOCK_PY = ROOT / "web-app/tools/mock_agent.py"

# Routes the agent serves on purpose even though the dashboard never calls
# them (monitoring probes, automation entry points).
ALLOWED_UNUSED = {"/api/health"}

# The mock answers any unlisted POST with `{"ok": true, "data": {}}`, which is
# an adequate stub for fire-and-forget mutations. It only needs a real fixture
# where the dashboard reads a payload back: every GET, plus these POSTs.
MOCK_PAYLOAD_POSTS = {
    "/api/bands/apply",
    "/api/bands/restore",
    "/api/at/send",
    "/api/logger/signal/start",
    "/api/logger/signal/stop",
}

ROUTE_RE = re.compile(r'\("(\w+)",\s*"(/api/[^"]+)"\)')
PATH_RE = re.compile(r'["\'](/api/[a-zA-Z0-9/_-]+)["\']')


def read(path: Path) -> str:
    if not path.exists():
        sys.exit(f"missing file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def agent_routes() -> set[tuple[str, str]]:
    """(method, path) pairs from the agent's ROUTES table."""
    src = read(AGENT_PY)
    block = re.search(r"^ROUTES = \[(.*?)^\]", src, re.S | re.M)
    if not block:
        sys.exit("could not locate ROUTES table in agent/m3200_agent.py")
    return set(ROUTE_RE.findall(block.group(1)))


def dashboard_routes() -> set[str]:
    return set(PATH_RE.findall(read(API_TS))) | set(PATH_RE.findall(read(CLIENT_TS)))


def mock_routes() -> set[str]:
    src = read(MOCK_PY)
    routes: set[str] = set()
    for block in ("ROUTES_GET", "ROUTES_POST"):
        m = re.search(rf"^{block} = \{{(.*?)^\}}", src, re.S | re.M)
        if m:
            routes |= set(PATH_RE.findall(m.group(1)))
    return routes


def report(title: str, items: set[str], hint: str) -> bool:
    if not items:
        return True
    print(f"\n  {title}")
    for path in sorted(items):
        print(f"    - {path}")
    print(f"    -> {hint}")
    return False


def main() -> int:
    routes = agent_routes()
    agent = {path for _, path in routes}
    dash, mock = dashboard_routes(), mock_routes()
    # Login lives in client.ts and is special-cased by the mock, but it is a
    # real route on both sides.
    needs_fixture = ({p for m, p in routes if m == "GET"} | MOCK_PAYLOAD_POSTS) & dash

    print(
        f"agent serves {len(routes)} routes over {len(agent)} paths; "
        f"dashboard calls {len(dash)}; mock stubs {len(mock)}"
    )

    ok = True
    ok &= report(
        "Dashboard calls endpoints the agent does not serve:",
        dash - agent,
        "these 404 at runtime — add the route or drop the call",
    )
    ok &= report(
        "Agent serves endpoints nothing calls:",
        agent - dash - ALLOWED_UNUSED,
        "dead surface — delete it or wire it into the dashboard",
    )
    ok &= report(
        "Mock lacks a fixture for endpoints the dashboard reads:",
        needs_fixture - mock,
        "local demos will render empty — add a fixture to mock_agent.py",
    )
    ok &= report(
        "Mock stubs endpoints that no longer exist:",
        mock - agent,
        "stale fixture — remove it from mock_agent.py",
    )

    print("\nOK: agent, dashboard and mock agree." if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
