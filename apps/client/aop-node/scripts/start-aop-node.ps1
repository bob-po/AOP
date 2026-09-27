# Start local deps + aopd (dev). Run from anywhere.
# Usage: powershell -File apps/client/aop-node/scripts/start-aop-node.ps1 [-Offline] [-Release]

param(
    [switch]$Offline,
    [switch]$Release
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent  # apps/client/aop-node -> apps -> ? 
# PSScriptRoot = .../aop-node/scripts
$NodeRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $NodeRoot

$docker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
if (Test-Path $docker) {
    Write-Host "Starting aop-postgres / aop-redis (if present)..."
    & $docker start aop-postgres aop-redis 2>$null | Out-Null
} else {
    Write-Host "Docker CLI not found; ensure Postgres :5432 is up before online mode."
}

if (-not (Test-Path "aop-node.toml")) {
    Copy-Item "config\aop-node.example.toml" "aop-node.toml"
    Write-Host "Created aop-node.toml from example (api_key empty for AUTH_REQUIRED=false)."
}

$profile = if ($Release) { "release" } else { "dev" }
Write-Host "Building aopd ($profile)..."
if ($Release) {
    cargo build -q -p aopd --release
    $exe = "target\release\aopd.exe"
} else {
    cargo build -q -p aopd
    # Prefer cargo target dir (may be sandbox-relocated)
    $td = (cargo metadata --format-version 1 --no-deps | ConvertFrom-Json).target_directory
    $exe = Join-Path $td "debug\aopd.exe"
    if (-not (Test-Path $exe)) { $exe = "target\debug\aopd.exe" }
}

Get-Process aopd -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1

$args = @("--config", (Join-Path $NodeRoot "aop-node.toml"))
if ($Offline) { $args += "--offline" }

Write-Host "Starting $exe $($args -join ' ')"
Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $NodeRoot -WindowStyle Hidden
Start-Sleep 2

$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $s = Invoke-RestMethod "http://127.0.0.1:7920/v1/status" -TimeoutSec 2
        Write-Host ("registered={0} children={1}" -f $s.registered, $s.children.Count)
        $ok = $true
        if ($Offline -or $s.registered) { break }
    } catch {
        Start-Sleep 1
    }
}
if (-not $ok) { throw "aopd mgmt HTTP did not come up on :7920" }
Write-Host "OK — use: cargo run -p aop-cli -- status"
