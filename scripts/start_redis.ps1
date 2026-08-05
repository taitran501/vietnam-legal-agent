# Start Redis the same way as production (docker-compose service `redis`).
# Requires Docker Desktop (or Docker Engine) running.
# From repo root:  powershell -File scripts/start_redis.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Starting Redis (epr_redis)..." -ForegroundColor Cyan
docker compose up -d redis
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "PING test:" -ForegroundColor Cyan
docker exec epr_redis redis-cli ping
Write-Host "OK. Backend .env should use: REDIS_URL=redis://localhost:6379/0" -ForegroundColor Green
