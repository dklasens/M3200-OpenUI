#!/bin/bash
# Local demo: dashboard preview on :8080 + mock agent on :9090 (no device).
# Vite proxies /api/* from the preview to the mock agent.
#   bash tools/demo.sh        start (foreground; Ctrl-C stops both)
#   bash tools/demo.sh stop   stop a backgrounded demo
set -e
cd "$(dirname "$0")/.."

stop() {
  [ -f /tmp/m3200-mock-agent.pid ] && kill "$(cat /tmp/m3200-mock-agent.pid)" 2>/dev/null && echo "mock agent stopped"
  [ -f /tmp/m3200-preview.pid ] && kill "$(cat /tmp/m3200-preview.pid)" 2>/dev/null && echo "preview stopped"
  rm -f /tmp/m3200-mock-agent.pid /tmp/m3200-preview.pid
}

if [ "${1:-}" = "stop" ]; then stop; exit 0; fi

npm run build >/dev/null

python3 tools/mock_agent.py --port 9090 >/tmp/m3200-mock-agent.log 2>&1 &
echo $! > /tmp/m3200-mock-agent.pid

npm run preview -- --port 8080 --strictPort >/tmp/m3200-preview.log 2>&1 &
echo $! > /tmp/m3200-preview.pid

sleep 2
echo "=================================================="
echo "  Dashboard:  http://localhost:8080"
echo "  Mock agent: http://localhost:9090"
echo "  Sign in with password 'demo'"
echo "  Stop with Ctrl-C or: bash tools/demo.sh stop"
echo "=================================================="

trap 'stop' INT TERM
wait
