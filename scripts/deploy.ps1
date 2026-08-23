# Deploys the M3200-OpenUI agent + dashboard to the device over SSH.
# Usage: pwsh scripts/deploy.ps1 [-Target 192.168.1.1] [-SkipWebBuild]
param(
  [string]$Target = "192.168.1.1",
  [string]$Key = "$PSScriptRoot\..\artifacts\id_ecdsa",
  [switch]$SkipWebBuild
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."
$ssh = "ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa -i `"$Key`" root@$Target"

function Push-File($local, $remote) {
  Write-Host "-> $remote"
  cmd /c "$ssh `"cat > $remote`" < `"$local`"" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "push failed: $local" }
}

if (-not $SkipWebBuild) {
  Write-Host "== building dashboard =="
  Push-Location "$root\web-app"
  try {
    if (-not (Test-Path node_modules)) { npm ci --no-audit --no-fund | Out-Null }
    npm run build | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "web build failed" }
  } finally { Pop-Location }
}
if (-not (Test-Path "$root\web-app\dist\index.html")) { throw "web-app/dist missing - build first" }

Write-Host "== creating directories + backing up previous agent =="
Invoke-Expression "$ssh 'mkdir -p /data/m3200-openui/www/assets && cp -f /data/m3200-openui/m3200_agent.py /data/m3200-openui/m3200_agent.py.bak 2>/dev/null; true'"

Push-File "$root\agent\qmi.py" "/data/m3200-openui/qmi.py"
Push-File "$root\agent\m3200_agent.py" "/data/m3200-openui/m3200_agent.py"
Push-File "$root\agent\update.py" "/data/m3200-openui/update.py"
Push-File "$root\VERSION" "/data/m3200-openui/version"
Push-File "$root\agent\ca-combinations.json" "/data/m3200-openui/ca-combinations.json"
Push-File "$root\agent\nr-ca-validation.json" "/data/m3200-openui/nr-ca-validation.json"
Push-File "$root\agent\m3200-agent.service" "/etc/systemd/system/m3200-agent.service"

Write-Host "== pushing dashboard =="
Invoke-Expression "$ssh 'rm -f /data/m3200-openui/www/assets/*'"
Push-File "$root\web-app\dist\index.html" "/data/m3200-openui/www/index.html"
Get-ChildItem "$root\web-app\dist\assets\*" | ForEach-Object {
  Push-File $_.FullName "/data/m3200-openui/www/assets/$($_.Name)"
}
Get-ChildItem "$root\web-app\dist\*" -File | Where-Object { $_.Name -ne "index.html" } | ForEach-Object {
  Push-File $_.FullName "/data/m3200-openui/www/$($_.Name)"
}

Write-Host "== enabling + restarting service =="
Invoke-Expression "$ssh 'chmod 644 /etc/systemd/system/m3200-agent.service && systemctl daemon-reload && systemctl enable m3200-agent && systemctl restart m3200-agent'"
Start-Sleep -Seconds 3

Write-Host "== health check =="
Invoke-Expression "$ssh 'systemctl is-active m3200-agent; curl -s --max-time 5 http://192.168.1.1:8080/api/health'"
Write-Host ""
Write-Host "Dashboard password: " -NoNewline
Invoke-Expression "$ssh 'cat /data/m3200-openui/agent-password'"
Write-Host "Band write automation token (not required by the GUI): " -NoNewline
Invoke-Expression "$ssh 'cat /data/m3200-openui/write-token'"
Write-Host "Dashboard: http://${Target}:8080/"
