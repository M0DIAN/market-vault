$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"

Write-Host ""
Write-Host "MarketVault environment is ready." -ForegroundColor Green
Write-Host "Next: start and log in to moomoo OpenD, then run scripts/first_collection.ps1"
