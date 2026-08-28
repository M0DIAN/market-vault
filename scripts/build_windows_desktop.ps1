[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [string]$OutputRoot = "",
    [string]$DashboardSmokeSettings = "",
    [switch]$DashboardSmokeRequireRecentRuns,
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
    $OutputRoot = Join-Path $ProjectRoot "dist"
} elseif (-not [IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot = Join-Path $ProjectRoot $OutputRoot
}
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$ResolvedDashboardSmokeSettings = $null
if ($DashboardSmokeSettings) {
    if (-not [IO.Path]::IsPathRooted($DashboardSmokeSettings)) {
        throw "Dashboard smoke settings path must be absolute: $DashboardSmokeSettings"
    }
    $ResolvedDashboardSmokeSettings = [IO.Path]::GetFullPath($DashboardSmokeSettings)
    if (-not (Test-Path -LiteralPath $ResolvedDashboardSmokeSettings -PathType Leaf)) {
        throw "Dashboard smoke settings file not found: $ResolvedDashboardSmokeSettings"
    }
} elseif ($DashboardSmokeRequireRecentRuns) {
    throw "DashboardSmokeRequireRecentRuns requires DashboardSmokeSettings."
}
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
$WorkPath = Join-Path $OutputRoot "_build\$RunId"
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $WorkPath | Out-Null

$PythonVersion = (& $PythonExecutable --version 2>&1).ToString().Trim()
$PyInstallerVersion = (& $PythonExecutable -m PyInstaller --version 2>&1).ToString().Trim()
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is unavailable. Install the windows-exe extra first."
}
$PySideVersion = (& $PythonExecutable -c "import PySide6; print(PySide6.__version__)" 2>&1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or $PySideVersion -ne "6.11.2") {
    throw "PySide6 6.11.2 is required for the production Windows build. Found: $PySideVersion"
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

$ExePath = Join-Path $FinalApp "MarketVault.exe"
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "MarketVault.exe was not produced: $ExePath"
}
New-Item -ItemType Directory -Path (Join-Path $FinalApp "config") | Out-Null
Copy-Item -LiteralPath $ConfigTemplate -Destination (Join-Path $FinalApp "config\settings.yaml")

$QWindows = @(Get-ChildItem -LiteralPath $FinalApp -Filter "qwindows.dll" -File -Recurse)
if ($QWindows.Count -ne 1) {
    throw "Expected exactly one qwindows.dll in the bundle, found $($QWindows.Count)."
}
$QmlControlsRoot = Join-Path $FinalApp "_internal\PySide6\qml\QtQuick\Controls"
$ForbiddenQmlDirectories = @("designer", "Fusion", "Imagine", "Material", "Universal")
$BundledForbiddenQml = @($ForbiddenQmlDirectories | Where-Object {
    Test-Path -LiteralPath (Join-Path $QmlControlsRoot $_)
})
if ($BundledForbiddenQml.Count -gt 0) {
    throw "Non-runtime QML controls entered the production bundle: $($BundledForbiddenQml -join ', ')"
}

$BundleEntries = @(Get-ChildItem -LiteralPath $FinalApp -Force -Recurse)
$RequiredQmlAssets = @(
    "_internal\market_vault\desktop\qml\Main.qml",
    "_internal\market_vault\desktop\qml\theme\PixelTheme.qml",
    "_internal\market_vault\desktop\qml\theme\qmldir",
    "_internal\market_vault\desktop\qml\pages\AuditPage.qml",
    "_internal\market_vault\desktop\qml\pages\HistoricalDataPage.qml",
    "_internal\market_vault\desktop\qml\pages\HomePage.qml",
    "_internal\market_vault\desktop\qml\pages\InventoryPage.qml",
    "_internal\market_vault\desktop\qml\pages\MarketDataPage.qml",
    "_internal\market_vault\desktop\qml\pages\RunsPage.qml",
    "_internal\market_vault\desktop\qml\pages\StorageCleanupPage.qml",
    "_internal\market_vault\desktop\qml\pages\TradingCalendarPage.qml"
)
$MissingQmlAssets = @($RequiredQmlAssets | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $FinalApp $_) -PathType Leaf)
})
if ($MissingQmlAssets.Count -gt 0) {
    throw "Required production QML assets are missing: $($MissingQmlAssets -join ', ')"
}
$BundledFontRoot = Join-Path $FinalApp "_internal\market_vault\desktop\assets\fonts\fusion-pixel-12px-proportional-zh_hans-v2026.07.20"
$BundledFont = Join-Path $BundledFontRoot "fusion-pixel-12px-proportional-zh_hans.otf"
$ExpectedFontHash = "9955f9e20abd758316418a2942aa6ee773754060da4a3f9286581fd11312f6c3"
foreach ($FontAsset in @($BundledFont, (Join-Path $BundledFontRoot "NOTICE.md"), (Join-Path $BundledFontRoot "OFL.txt"))) {
    if (-not (Test-Path -LiteralPath $FontAsset -PathType Leaf)) {
        throw "Required production font asset is missing: $FontAsset"
    }
}
$BundledFontHash = (Get-FileHash -LiteralPath $BundledFont -Algorithm SHA256).Hash.ToLowerInvariant()
if ($BundledFontHash -ne $ExpectedFontHash) {
    throw "Bundled Fusion Pixel hash mismatch: $BundledFontHash"
}
$ForbiddenTkEntries = @($BundleEntries | Where-Object {
    $_.FullName -match '(?i)(^|[\\/])(?:_tkinter[^\\/]*|tkinter|tcl\d[^\\/]*|tk\d[^\\/]*)($|[\\/])'
})
if ($ForbiddenTkEntries.Count -gt 0) {
    throw "Tk runtime content entered the production QML bundle: $($ForbiddenTkEntries.FullName -join ', ')"
}
$ForbiddenQtEntries = @($BundleEntries | Where-Object {
    $_.Name -match '(?i)^Qt6Widgets\.dll$' -or
    $_.Name -match '(?i)^Qt6WebEngine' -or
    $_.FullName -match '(?i)[\\/]PySide6[\\/](?:QtWidgets|QtWebEngine[^\\/]*)\.pyd$'
})
if ($ForbiddenQtEntries.Count -gt 0) {
    throw "Unapproved QtWidgets/WebEngine content entered the production bundle: $($ForbiddenQtEntries.FullName -join ', ')"
}
$ArchiveListing = (& $PythonExecutable -m PyInstaller.utils.cliutils.archive_viewer -l -r $ExePath 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Cannot inspect the production executable module archive."
}
if ($ArchiveListing -match '(?im)(^|[^A-Za-z0-9_])_?tkinter([^A-Za-z0-9_]|$)' -or
    $ArchiveListing -match '(?im)market_vault\.console\.ui') {
    throw "Tk UI modules entered the production executable archive."
}
if ($ArchiveListing -match '(?im)PySide6\.(?:QtWidgets|QtWebEngine\w*)') {
    throw "Unapproved QtWidgets/WebEngine modules entered the production executable archive."
}

$ForbiddenTopLevel = @(".git", "tests", "data", "catalog", "manifests", "reports", "quarantine")
$TopLevelNames = Get-ChildItem -LiteralPath $FinalApp -Force | ForEach-Object { $_.Name }
$ForbiddenFound = @($TopLevelNames | Where-Object { $ForbiddenTopLevel -contains $_ })
if ($ForbiddenFound.Count -gt 0) {
    throw "Forbidden repository/runtime content entered the distributable: $($ForbiddenFound -join ', ')"
}
$ForbiddenFiles = @($BundleEntries | Where-Object {
    -not $_.PSIsContainer -and (
        $_.Name -eq ".env" -or $_.Name -like ".env.*" -or
        $_.Extension -in @(".duckdb", ".parquet")
    )
})
if ($ForbiddenFiles.Count -gt 0) {
    throw "Forbidden runtime or credential files entered the distributable: $($ForbiddenFiles.FullName -join ', ')"
}

$SmokeRoot = Join-Path $OutputRoot "_smoke\$RunId"
$SmokeConfig = Join-Path $SmokeRoot "config\settings.yaml"
$SmokeCwd = Join-Path $SmokeRoot "unrelated cwd"
$SmokeLocalAppData = Join-Path $SmokeRoot "LocalAppData"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SmokeConfig) | Out-Null
New-Item -ItemType Directory -Force -Path $SmokeCwd | Out-Null
New-Item -ItemType Directory -Force -Path $SmokeLocalAppData | Out-Null
Copy-Item -LiteralPath $ConfigTemplate -Destination $SmokeConfig

$OriginalLocalAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = $SmokeLocalAppData
try {
    $QuotedSmokeSettings = '"{0}"' -f $SmokeConfig
    $SmokeProcess = Start-Process `
        -FilePath $ExePath `
        -ArgumentList @("--settings", $QuotedSmokeSettings, "--smoke-exit-ms", "500") `
        -WorkingDirectory $SmokeCwd `
        -Wait `
        -PassThru
} finally {
    $env:LOCALAPPDATA = $OriginalLocalAppData
}
if ($SmokeProcess.ExitCode -ne 0) {
    throw "Frozen startup smoke failed with exit code $($SmokeProcess.ExitCode)."
}
$UnexpectedSmokeCwdEntries = @(Get-ChildItem -LiteralPath $SmokeCwd -Force)
if ($UnexpectedSmokeCwdEntries.Count -ne 0) {
    throw "Frozen startup smoke created unexpected CWD state: $($UnexpectedSmokeCwdEntries.FullName -join ', ')"
}
$UnexpectedRuntimePaths = @(@("data", "catalog", "manifests", "reports", "quarantine") | Where-Object {
    Test-Path -LiteralPath (Join-Path $SmokeRoot $_)
})
$UnexpectedRuntimeFiles = @(Get-ChildItem -LiteralPath $SmokeRoot -File -Recurse -Force | Where-Object {
    $_.Extension -in @(".duckdb", ".parquet") -or $_.Name -eq "desktop-preferences.json"
})
if ($UnexpectedRuntimePaths.Count -gt 0 -or $UnexpectedRuntimeFiles.Count -gt 0) {
    throw "Frozen startup smoke mutated runtime state under $SmokeRoot."
}

$DashboardSmokeProcess = $null
$DashboardSmokeRoot = $null
if ($ResolvedDashboardSmokeSettings) {
    $DashboardSmokeRoot = Join-Path $OutputRoot "_dashboard_smoke\$RunId"
    New-Item -ItemType Directory -Force -Path $DashboardSmokeRoot | Out-Null
    $QuotedDashboardSettings = '"{0}"' -f $ResolvedDashboardSmokeSettings
    $DashboardSmokeArguments = @(
        "--settings",
        $QuotedDashboardSettings,
        "--dashboard-smoke"
    )
    if ($DashboardSmokeRequireRecentRuns) {
        $DashboardSmokeArguments += "--dashboard-smoke-require-recent-runs"
    }
    $DashboardSmokeProcess = Start-Process `
        -FilePath $ExePath `
        -ArgumentList $DashboardSmokeArguments `
        -WorkingDirectory $DashboardSmokeRoot `
        -Wait `
        -PassThru
    if ($DashboardSmokeProcess.ExitCode -ne 0) {
        throw "Frozen dashboard smoke failed with exit code $($DashboardSmokeProcess.ExitCode)."
    }
    $UnexpectedDashboardCwdEntries = @(Get-ChildItem -LiteralPath $DashboardSmokeRoot -Force)
    if ($UnexpectedDashboardCwdEntries.Count -ne 0) {
        throw "Frozen dashboard smoke created unexpected CWD state: $($UnexpectedDashboardCwdEntries.FullName -join ', ')"
    }
}

$ExeFile = Get-Item -LiteralPath $ExePath
$ExeHash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
$Metadata = [ordered]@{
    schema = "market-vault-windows-build-v2"
    build_head_sha = $HeadSha
    packaging_mode = "pyinstaller-onedir"
    desktop_ui = "pyside6-qml"
    executable = "MarketVault.exe"
    executable_size_bytes = $ExeFile.Length
    executable_sha256 = $ExeHash
    python_version = $PythonVersion
    pyside6_version = $PySideVersion
    qt_version = $QtVersion
    pyinstaller_version = $PyInstallerVersion
    windows_version = [Environment]::OSVersion.VersionString
    architecture = if ([Environment]::Is64BitProcess) { "x64" } else { "x86" }
    build_path_sanitized = $true
    tkinter_bundle_audit = "absent"
    fusion_pixel_sha256 = $BundledFontHash
    unrelated_cwd_smoke_exit_code = $SmokeProcess.ExitCode
    startup_runtime_mutation = $false
    dashboard_smoke_settings = $ResolvedDashboardSmokeSettings
    dashboard_smoke_require_recent_runs = [bool]$DashboardSmokeRequireRecentRuns
    dashboard_smoke_exit_code = if ($DashboardSmokeProcess) { $DashboardSmokeProcess.ExitCode } else { $null }
    application_context = "shared-lazy"
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
    qwindows_plugin = $QWindows[0].FullName
    smoke_path = $SmokeRoot
    dashboard_smoke_path = $DashboardSmokeRoot
    zip = $ZipEvidence
    build = $Metadata
    work_path = $WorkPath
}
Write-Output ($Evidence | ConvertTo-Json -Depth 6 -Compress)
Write-Output "MARKET_VAULT_WINDOWS_BUILD_OK"
