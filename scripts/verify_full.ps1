[CmdletBinding()]
param(
    [string]$TempRoot
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryHint = Split-Path -Parent $scriptDirectory
$helper = Join-Path $scriptDirectory "verify_full.py"

if ($env:MARKET_VAULT_PYTHON) {
    $python = $env:MARKET_VAULT_PYTHON
} else {
    $worktreePython = Join-Path $repositoryHint ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $worktreePython -PathType Leaf) {
        $python = $worktreePython
    } else {
        $python = "python"
    }
}

$helperArguments = @($helper)
if ($PSBoundParameters.ContainsKey("TempRoot")) {
    $helperArguments += @("--temp-root", $TempRoot)
}

& $python @helperArguments
$validationExitCode = $LASTEXITCODE
if ($null -eq $validationExitCode) {
    throw "Python validation helper did not return a process exit code."
}
exit $validationExitCode
