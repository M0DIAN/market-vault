[CmdletBinding(DefaultParameterSetName = "ExePath")]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "AppRoot")]
    [string]$AppRoot,

    [Parameter(Mandatory = $true, ParameterSetName = "ExePath")]
    [string]$ExePath,

    [string]$ShortcutPath = "",
    [ValidateNotNullOrEmpty()]
    [string]$ShortcutName = "MarketVault"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)) {
    throw "MarketVault shortcut installation requires Windows."
}

if ($PSCmdlet.ParameterSetName -eq "AppRoot") {
    $ResolvedAppRoot = [IO.Path]::GetFullPath($AppRoot)
    $ResolvedExe = Join-Path $ResolvedAppRoot "MarketVault.exe"
} else {
    $ResolvedExe = [IO.Path]::GetFullPath($ExePath)
    $ResolvedAppRoot = Split-Path -Parent $ResolvedExe
}

if (-not (Test-Path -LiteralPath $ResolvedExe -PathType Leaf)) {
    throw "MarketVault.exe does not exist: $ResolvedExe"
}

if ($ShortcutPath) {
    $ResolvedShortcut = [IO.Path]::GetFullPath($ShortcutPath)
} else {
    if ($ShortcutName.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "ShortcutName contains invalid filename characters."
    }
    $Desktop = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::DesktopDirectory
    )
    if (-not $Desktop) {
        throw "Windows Desktop directory could not be resolved."
    }
    $ResolvedShortcut = Join-Path $Desktop "$ShortcutName.lnk"
}

if ([IO.Path]::GetExtension($ResolvedShortcut) -ne ".lnk") {
    throw "ShortcutPath must end with .lnk: $ResolvedShortcut"
}
$ShortcutDirectory = Split-Path -Parent $ResolvedShortcut
if (-not (Test-Path -LiteralPath $ShortcutDirectory -PathType Container)) {
    throw "Shortcut parent directory does not exist: $ShortcutDirectory"
}
if (Test-Path -LiteralPath $ResolvedShortcut) {
    throw "Refusing to overwrite an existing shortcut: $ResolvedShortcut"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ResolvedShortcut)
$Shortcut.TargetPath = $ResolvedExe
$Shortcut.WorkingDirectory = $ResolvedAppRoot
$Shortcut.IconLocation = "$ResolvedExe,0"
$Shortcut.Description = "MarketVault Console"
$Shortcut.Save()

if (-not (Test-Path -LiteralPath $ResolvedShortcut -PathType Leaf)) {
    throw "Shortcut was not created: $ResolvedShortcut"
}
$Verified = $Shell.CreateShortcut($ResolvedShortcut)
if (-not [string]::Equals($Verified.TargetPath, $ResolvedExe, [StringComparison]::OrdinalIgnoreCase) -or
    -not [string]::Equals($Verified.WorkingDirectory, $ResolvedAppRoot, [StringComparison]::OrdinalIgnoreCase) -or
    -not [string]::Equals($Verified.IconLocation, "$ResolvedExe,0", [StringComparison]::OrdinalIgnoreCase) -or
    $Verified.Description -ne "MarketVault Console") {
    throw "Created shortcut metadata did not match the requested MarketVault target."
}

$Evidence = [ordered]@{
    shortcut_path = $ResolvedShortcut
    target_path = $Verified.TargetPath
    working_directory = $Verified.WorkingDirectory
    icon_location = $Verified.IconLocation
    description = $Verified.Description
}
Write-Output ($Evidence | ConvertTo-Json -Compress)
Write-Output "MARKET_VAULT_SHORTCUT_OK"
