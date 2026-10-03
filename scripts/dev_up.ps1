# Thin wrapper: .\scripts\dev_up.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
python "$PSScriptRoot\dev_up.py" @args
