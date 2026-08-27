[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [string]$OutputRoot = "",
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)) {
    throw "MarketVault QML canary packaging requires Windows."
}

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$SpecPath = Join-Path $ProjectRoot "packaging\MarketVaultQmlCanary.spec"
if (-not (Test-Path -LiteralPath $SpecPath -PathType Leaf)) {
    throw "PyInstaller spec not found: $SpecPath"
}

if (-not $PythonExecutable) {
    $PythonExecutable = (Get-Command python -ErrorAction Stop).Source
}
$PythonExecutable = [IO.Path]::GetFullPath($PythonExecutable)
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python executable not found: $PythonExecutable"
}

$HeadSha = (& git -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $HeadSha -notmatch "^[0-9a-f]{40}$") {
    throw "Cannot determine the exact Git HEAD."
}
$GitStatus = (& git -C $ProjectRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Cannot inspect Git worktree status."
}
if ($GitStatus) {
    throw "Refusing to package a dirty worktree. Commit pending changes first."
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $ProjectRoot "dist-qml-canary"
} elseif (-not [IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot = Join-Path $ProjectRoot $OutputRoot
}
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$SourceRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot "src"))
if ($OutputRoot.Equals($ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $OutputRoot.Equals($SourceRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $OutputRoot.StartsWith($SourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Output root must be outside the project source package: $OutputRoot"
}

$FinalApp = Join-Path $OutputRoot "MarketVaultQmlCanary"
$ShortSha = $HeadSha.Substring(0, 12)
$ZipPath = Join-Path $OutputRoot "MarketVaultQmlCanary-windows-x64-$ShortSha.zip"
if (Test-Path -LiteralPath $FinalApp) {
    throw "Refusing to overwrite an existing distributable: $FinalApp"
}
if (-not $NoZip -and (Test-Path -LiteralPath $ZipPath)) {
    throw "Refusing to overwrite an existing ZIP: $ZipPath"
}

$RunId = "run-{0}-{1}" -f [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$WorkPath = Join-Path $OutputRoot "_build\$RunId"
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $WorkPath | Out-Null

$PythonVersion = (& $PythonExecutable --version 2>&1).ToString().Trim()
$PyInstallerVersion = (& $PythonExecutable -m PyInstaller --version 2>&1).ToString().Trim()
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is unavailable. Install the windows-exe extra first."
}
$PySideVersion = (& $PythonExecutable -c "import PySide6; print(PySide6.__version__)" 2>&1).ToString().Trim()
if ($LASTEXITCODE -ne 0) {
    throw "PySide6 is unavailable. Install the desktop extra first."
}
$QtVersion = (& $PythonExecutable -c "from PySide6.QtCore import qVersion; print(qVersion())" 2>&1).ToString().Trim()

$BuildArguments = @(
    "-m", "PyInstaller",
    "--distpath", $OutputRoot,
    "--workpath", $WorkPath,
    $SpecPath
)

Write-Output "Project root: $ProjectRoot"
Write-Output "Output root: $OutputRoot"
Write-Output "Python: $PythonExecutable ($PythonVersion)"
Write-Output "PySide6: $PySideVersion"
Write-Output "Qt: $QtVersion"
Write-Output "PyInstaller: $PyInstallerVersion"
Write-Output "Git HEAD: $HeadSha"
Write-Output ("Build command: {0} {1}" -f $PythonExecutable, ($BuildArguments -join " "))

$OriginalPath = $env:PATH
$env:PATH = @(
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot "System32\Wbem")
) -join [IO.Path]::PathSeparator
try {
    & $PythonExecutable @BuildArguments
    $PyInstallerExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $OriginalPath
}
if ($PyInstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $PyInstallerExitCode"
}

$ExePath = Join-Path $FinalApp "MarketVaultQmlCanary.exe"
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "MarketVaultQmlCanary.exe was not produced: $ExePath"
}
$QWindows = @(Get-ChildItem -LiteralPath $FinalApp -Filter "qwindows.dll" -File -Recurse)
if ($QWindows.Count -ne 1) {
    throw "Expected exactly one qwindows.dll in the bundle, found $($QWindows.Count)."
}

$ForbiddenTopLevel = @(".git", "tests", "data", "catalog", "manifests", "reports", "quarantine")
$TopLevelNames = Get-ChildItem -LiteralPath $FinalApp -Force | ForEach-Object { $_.Name }
$ForbiddenFound = @($TopLevelNames | Where-Object { $ForbiddenTopLevel -contains $_ })
if ($ForbiddenFound.Count -gt 0) {
    throw "Forbidden repository/runtime content entered the distributable: $($ForbiddenFound -join ', ')"
}
$ForbiddenFiles = @(Get-ChildItem -LiteralPath $FinalApp -File -Recurse -Force | Where-Object {
    $_.Name -eq ".env" -or $_.Name -like ".env.*" -or
    $_.Extension -in @(".duckdb", ".parquet")
})
if ($ForbiddenFiles.Count -gt 0) {
    throw "Forbidden runtime or credential files entered the distributable: $($ForbiddenFiles.FullName -join ', ')"
}

$SmokeRoot = Join-Path $OutputRoot "_smoke\$RunId"
New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
$SmokeProcess = Start-Process -FilePath $ExePath -ArgumentList @("--smoke-exit-ms", "500") -WorkingDirectory $SmokeRoot -Wait -PassThru
if ($SmokeProcess.ExitCode -ne 0) {
    throw "Frozen smoke failed with exit code $($SmokeProcess.ExitCode)."
}
$UnexpectedSmokeEntries = @(Get-ChildItem -LiteralPath $SmokeRoot -Force)
if ($UnexpectedSmokeEntries.Count -ne 0) {
    throw "Frozen smoke created unexpected CWD state: $($UnexpectedSmokeEntries.FullName -join ', ')"
}

$ExeFile = Get-Item -LiteralPath $ExePath
$ExeHash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
$Metadata = [ordered]@{
    schema = "market-vault-windows-qml-canary-build-v1"
    build_head_sha = $HeadSha
    packaging_mode = "pyinstaller-onedir"
    executable = "MarketVaultQmlCanary.exe"
    executable_size_bytes = $ExeFile.Length
    executable_sha256 = $ExeHash
    python_version = $PythonVersion
    pyside6_version = $PySideVersion
    qt_version = $QtVersion
    pyinstaller_version = $PyInstallerVersion
    windows_version = [Environment]::OSVersion.VersionString
    architecture = if ([Environment]::Is64BitProcess) { "x64" } else { "x86" }
    build_path_sanitized = $true
    unrelated_cwd_smoke_exit_code = $SmokeProcess.ExitCode
    built_at_utc = [DateTime]::UtcNow.ToString("o")
}
$MetadataPath = Join-Path $FinalApp "build-metadata.json"
[IO.File]::WriteAllText(
    $MetadataPath,
    ($Metadata | ConvertTo-Json -Depth 4),
    (New-Object Text.UTF8Encoding($false))
)

$DistributionFiles = @(Get-ChildItem -LiteralPath $FinalApp -File -Recurse -Force)
$DistributionBytes = ($DistributionFiles | Measure-Object -Property Length -Sum).Sum
$ZipEvidence = $null
if (-not $NoZip) {
    Compress-Archive -LiteralPath $FinalApp -DestinationPath $ZipPath -CompressionLevel Optimal
    $ZipFile = Get-Item -LiteralPath $ZipPath
    $ZipEvidence = [ordered]@{
        path = $ZipFile.FullName
        size_bytes = $ZipFile.Length
        sha256 = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$Evidence = [ordered]@{
    executable = [ordered]@{
        path = $ExeFile.FullName
        size_bytes = $ExeFile.Length
        sha256 = $ExeHash
    }
    distributable = [ordered]@{
        path = $FinalApp
        file_count = $DistributionFiles.Count
        total_size_bytes = $DistributionBytes
    }
    qwindows_plugin = $QWindows[0].FullName
    smoke_path = $SmokeRoot
    zip = $ZipEvidence
    build = $Metadata
    work_path = $WorkPath
}
Write-Output ($Evidence | ConvertTo-Json -Depth 6 -Compress)
Write-Output "MARKET_VAULT_QML_CANARY_BUILD_OK"
