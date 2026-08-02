param(
    [Parameter(Mandatory = $true)]
    [string]$TradeDate
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    throw "Virtual environment not found. Run scripts/setup_windows.ps1 first."
}

& .\.venv\Scripts\Activate.ps1

market-vault --settings config/settings.yaml init-catalog
market-vault --settings config/settings.yaml collect `
    --date $TradeDate `
    --groups core_universe `
    --interval 1m `
    --session ALL `
    --adjustment NONE
