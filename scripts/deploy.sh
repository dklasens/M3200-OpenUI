#!/usr/bin/env bash
# Deploys the M3200-OpenUI agent + dashboard to the device over SSH.
# macOS / Linux counterpart of scripts/deploy.ps1.
#
# Usage:
#   scripts/deploy.sh [target-ip]            # default 192.168.1.1
#   SKIP_WEB_BUILD=1 scripts/deploy.sh       # reuse an existing web-app/dist
#
# Prerequisites: ssh, node+npm (for the dashboard build), and root SSH on the
# device (run exploit.py first; it installs artifacts/id_ecdsa).
set -euo pipefail

TARGET="${1:-192.168.1.1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${M3200_SSH_KEY:-$ROOT/artifacts/id_ecdsa}"

if [ ! -f "$KEY" ]; then
  echo "missing SSH key: $KEY (run exploit.py first, or set M3200_SSH_KEY)" >&2
  exit 1
fi
chmod 600 "$KEY" 2>/dev/null || true

SSH=(ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no \
      -o HostKeyAlgorithms=+ssh-rsa -i "$KEY" "root@$TARGET")

push_file() {
  echo "-> $2"
  "${SSH[@]}" "cat > $2" < "$1"
}

if [ "${SKIP_WEB_BUILD:-0}" != "1" ]; then
  echo "== building dashboard =="
  (
    cd "$ROOT/web-app"
    [ -d node_modules ] || npm ci --no-audit --no-fund
    npm run build
  )
fi
[ -f "$ROOT/web-app/dist/index.html" ] || {
  echo "web-app/dist missing - build first" >&2; exit 1; }

echo "== creating directories + backing up previous agent =="
"${SSH[@]}" 'mkdir -p /data/m3200-openui/www/assets && cp -f /data/m3200-openui/m3200_agent.py /data/m3200-openui/m3200_agent.py.bak 2>/dev/null; true'

push_file "$ROOT/agent/qmi.py" "/data/m3200-openui/qmi.py"
push_file "$ROOT/agent/m3200_agent.py" "/data/m3200-openui/m3200_agent.py"
push_file "$ROOT/agent/update.py" "/data/m3200-openui/update.py"
push_file "$ROOT/VERSION" "/data/m3200-openui/version"
push_file "$ROOT/agent/ca-combinations.json" "/data/m3200-openui/ca-combinations.json"
push_file "$ROOT/agent/nr-ca-validation.json" "/data/m3200-openui/nr-ca-validation.json"
push_file "$ROOT/agent/m3200-agent.service" "/etc/systemd/system/m3200-agent.service"

echo "== pushing dashboard =="
"${SSH[@]}" 'rm -f /data/m3200-openui/www/assets/*'
push_file "$ROOT/web-app/dist/index.html" "/data/m3200-openui/www/index.html"
for f in "$ROOT"/web-app/dist/assets/*; do
  push_file "$f" "/data/m3200-openui/www/assets/$(basename "$f")"
done
for f in "$ROOT"/web-app/dist/*; do
  [ -f "$f" ] && [ "$(basename "$f")" != "index.html" ] && \
    push_file "$f" "/data/m3200-openui/www/$(basename "$f")"
done

echo "== enabling + restarting service =="
"${SSH[@]}" 'chmod 644 /etc/systemd/system/m3200-agent.service && systemctl daemon-reload && systemctl enable m3200-agent && systemctl restart m3200-agent'
sleep 3

echo "== health check =="
"${SSH[@]}" 'systemctl is-active m3200-agent; curl -s --max-time 5 http://192.168.1.1:8080/api/health'
echo
echo -n "Dashboard password: "
"${SSH[@]}" 'cat /data/m3200-openui/agent-password'
echo -n "Band write automation token (not required by the GUI): "
"${SSH[@]}" 'cat /data/m3200-openui/write-token'
echo "Dashboard: http://$TARGET:8080/"
