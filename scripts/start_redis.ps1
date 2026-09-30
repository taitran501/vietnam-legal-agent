# Start Redis the same way as production (docker-compose service `redis`).
# Requires Docker Desktop (or Docker Engine) running.
# From repo root:  powershell -File scripts/start_redis.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Starting the legal-agent Redis service..." -ForegroundColor Cyan
docker compose up -d redis
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $env:REDIS_PASSWORD) {
    Write-Error "Set REDIS_PASSWORD in this PowerShell session before running the health check."
    exit 1
}

Write-Host "PING test:" -ForegroundColor Cyan
docker compose exec -T redis redis-cli -a $env:REDIS_PASSWORD ping
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "OK. Backend .env should use: REDIS_URL=redis://localhost:6379/0" -ForegroundColor Green
