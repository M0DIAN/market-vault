from pathlib import Path


PROJECT_ROOT = Path(SPECPATH).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
ENTRY_POINT = SOURCE_ROOT / "market_vault" / "desktop" / "app.py"
QML_ENTRY_POINT = SOURCE_ROOT / "market_vault" / "desktop" / "qml" / "Main.qml"
WINDOWS_ICON = PROJECT_ROOT / "assets" / "windows" / "market-vault.ico"

analysis = Analysis(
    [str(ENTRY_POINT)],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=[
        (str(QML_ENTRY_POINT), "market_vault/desktop/qml"),
        (str(WINDOWS_ICON), "assets/windows"),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "duckdb",
        "market_vault.api",
        "market_vault.artifact_client",
        "moomoo",
        "pandas",
        "pyarrow",
        "pytest",
        "tests",
        "yaml",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MarketVaultQmlCanary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(WINDOWS_ICON),
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="MarketVaultQmlCanary",
)
