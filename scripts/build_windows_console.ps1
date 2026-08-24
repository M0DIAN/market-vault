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
    throw "MarketVault Windows packaging requires Windows."
}

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$SpecPath = Join-Path $ProjectRoot "packaging\MarketVault.spec"
$ConfigTemplate = Join-Path $ProjectRoot "config\settings.yaml"
if (-not (Test-Path -LiteralPath $SpecPath -PathType Leaf)) {
    throw "PyInstaller spec not found: $SpecPath"
}
if (-not (Test-Path -LiteralPath $ConfigTemplate -PathType Leaf)) {
    throw "Settings template not found: $ConfigTemplate"
}

if (-not $PythonExecutable) {
    $PythonCommand = Get-Command python -ErrorAction Stop
    $PythonExecutable = $PythonCommand.Source
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
    throw "Refusing to package a dirty worktree. Commit or remove pending changes first."
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $ProjectRoot "dist"
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

$FinalApp = Join-Path $OutputRoot "MarketVault"
$ShortSha = $HeadSha.Substring(0, 12)
$ZipPath = Join-Path $OutputRoot "MarketVault-windows-x64-$ShortSha.zip"
if (Test-Path -LiteralPath $FinalApp) {
    throw "Refusing to overwrite an existing distributable: $FinalApp"
}
if (-not $NoZip -and (Test-Path -LiteralPath $ZipPath)) {
    throw "Refusing to overwrite an existing ZIP: $ZipPath"
}

$RunId = "run-{0}-{1}" -f [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$WorkPath = Join-Path $ProjectRoot "build\windows-console\$RunId"
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Path $WorkPath | Out-Null

$PythonVersion = (& $PythonExecutable --version 2>&1).ToString().Trim()
$PyInstallerVersion = (& $PythonExecutable -m PyInstaller --version 2>&1).ToString().Trim()
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is unavailable. Install the windows-exe extra first."
}
$BuildArguments = @(
    "-m", "PyInstaller",
    "--distpath", $OutputRoot,
    "--workpath", $WorkPath,
    $SpecPath
)

Write-Output "Project root: $ProjectRoot"
Write-Output "Output root: $OutputRoot"
Write-Output "Python: $PythonExecutable ($PythonVersion)"
Write-Output "PyInstaller: $PyInstallerVersion"
Write-Output "Git HEAD: $HeadSha"
Write-Output ("Build command: {0} {1}" -f $PythonExecutable, ($BuildArguments -join " "))

& $PythonExecutable @BuildArguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$ExePath = Join-Path $FinalApp "MarketVault.exe"
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "MarketVault.exe was not produced: $ExePath"
}
New-Item -ItemType Directory -Path (Join-Path $FinalApp "config") | Out-Null
Copy-Item -LiteralPath $ConfigTemplate -Destination (Join-Path $FinalApp "config\settings.yaml")

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

$ExeFile = Get-Item -LiteralPath $ExePath
$ExeHash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
$Metadata = [ordered]@{
    schema = "market-vault-windows-build-v1"
    build_head_sha = $HeadSha
    packaging_mode = "pyinstaller-onedir"
    executable = "MarketVault.exe"
    executable_size_bytes = $ExeFile.Length
    executable_sha256 = $ExeHash
    python_version = $PythonVersion
    pyinstaller_version = $PyInstallerVersion
    windows_version = [Environment]::OSVersion.VersionString
    architecture = if ([Environment]::Is64BitProcess) { "x64" } else { "x86" }
    external_settings = "config/settings.yaml"
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
    zip = $ZipEvidence
    build = $Metadata
    work_path = $WorkPath
}
Write-Output ($Evidence | ConvertTo-Json -Depth 6 -Compress)
Write-Output "MARKET_VAULT_WINDOWS_BUILD_OK"
