# Smoke всей системы (Windows PowerShell): docker compose up --build -d → /ready ≤ 120 с → /api/v1/alerts.
# Запуск из корня репозитория: powershell -File scripts\smoke.ps1 [-Port 8000]
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$url = "http://localhost:$Port"
$t0 = Get-Date
docker compose up --build -d
if ($LASTEXITCODE -ne 0) { Write-Output "FAIL: docker compose up"; exit 1 }
$tUp = Get-Date
Write-Output ("compose up --build -d: {0:N0} s" -f ($tUp - $t0).TotalSeconds)
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$url/ready").StatusCode -eq 200) { $ready = $true; break } } catch { }
    Start-Sleep -Seconds 1
}
$tReady = Get-Date
if (-not $ready) { Write-Output "FAIL: $url/ready не ответил 200 за 120 с"; docker compose ps; exit 1 }
Write-Output ("cold start: up->/ready {0:N0} s (всего {1:N0} s)" -f ($tReady - $tUp).TotalSeconds, ($tReady - $t0).TotalSeconds)
(Invoke-WebRequest -UseBasicParsing "$url/api/v1/system/status").Content
Write-Output ("alerts: " + (Invoke-WebRequest -UseBasicParsing "$url/api/v1/alerts").Content)
Write-Output "SMOKE OK"
