# Install aop-node as a Windows service (requires Administrator).
# Usage (elevated PowerShell or CMD):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-service.ps1
#   .\scripts\install-service.cmd
#   sc start aop-node
#
# Important: stop any console aopd first (port 7920), then:
#   Get-Process aopd -ErrorAction SilentlyContinue | Stop-Process -Force
#   sc start aop-node

$ErrorActionPreference = "Stop"
$NodeRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $NodeRoot

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script in an elevated PowerShell/CMD (Administrator). Tip: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-service.ps1"
}

if (-not (Test-Path "aop-node.toml")) {
    Copy-Item "config\aop-node.example.toml" "aop-node.toml"
}

Write-Host "Building release aopd (with Windows service support)..."
cargo build -p aopd --release
if ($LASTEXITCODE -ne 0) { throw "cargo build failed" }

$td = (cargo metadata --format-version 1 --no-deps | ConvertFrom-Json).target_directory
$aopd = Join-Path $td "release\aopd.exe"
if (-not (Test-Path $aopd)) {
    $aopd = Join-Path $NodeRoot "target\release\aopd.exe"
}
if (-not (Test-Path $aopd)) { throw "aopd.exe not found after build: $aopd" }

$pluginsAbs = (Resolve-Path (Join-Path $NodeRoot "plugins")).Path
$logAbs = Join-Path $env:USERPROFILE ".aop\node\logs"
$versionsAbs = Join-Path $env:USERPROFILE ".aop\node\versions"

# Materialize install config with absolute paths (service cwd is System32).
$installDir = Join-Path $env:LOCALAPPDATA "aop-node"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item -Force $aopd (Join-Path $installDir "aopd.exe")

$cfgText = Get-Content (Join-Path $NodeRoot "aop-node.toml") -Raw
$cfgText = $cfgText -replace 'plugins_dir\s*=\s*"[^"]*"', ("plugins_dir = `"{0}`"" -f ($pluginsAbs -replace '\\','\\'))
if ($cfgText -notmatch 'plugins_dir\s*=') {
    $cfgText += "`nplugins_dir = `"$($pluginsAbs -replace '\\','\\')`"`n"
}
$cfgText = $cfgText -replace 'log_dir\s*=\s*"[^"]*"', ("log_dir = `"{0}`"" -f ($logAbs -replace '\\','\\'))
$cfgText = $cfgText -replace 'versions_dir\s*=\s*"[^"]*"', ("versions_dir = `"{0}`"" -f ($versionsAbs -replace '\\','\\'))
Set-Content -Path (Join-Path $installDir "aop-node.toml") -Value $cfgText -Encoding UTF8

$bin = Join-Path $installDir "aopd.exe"
$cfg = Join-Path $installDir "aop-node.toml"

Write-Host "Stopping console aopd (if any) and old service..."
Get-Process aopd -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
sc.exe stop aop-node 2>$null | Out-Null
sc.exe delete aop-node 2>$null | Out-Null
Start-Sleep 2

$binPath = "`"$bin`" --config `"$cfg`" --service"
sc.exe create aop-node binPath= $binPath start= auto DisplayName= "AOP Node Supervisor"
if ($LASTEXITCODE -ne 0) { throw "sc create failed ($LASTEXITCODE)" }
sc.exe description aop-node "AOP Node Supervisor (aopd) — edge harness lifecycle + Gateway register"

Write-Host ""
Write-Host "Installed to $installDir"
Write-Host "Start:  sc start aop-node"
Write-Host "Status: sc query aop-node"
Write-Host "Logs:   $env:LOCALAPPDATA\aop-node\aopd-service.log"
Write-Host "Stop:   sc stop aop-node"
