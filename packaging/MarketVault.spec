from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
ENTRY_POINT = SOURCE_ROOT / "market_vault" / "windows_launcher.py"
QML_ENTRY_POINT = SOURCE_ROOT / "market_vault" / "desktop" / "qml" / "Main.qml"
QML_COMPONENTS = [
    SOURCE_ROOT / "market_vault" / "desktop" / "qml" / "components" / name
    for name in (
        "AmbientBinaryField.qml",
        "DataTable.qml",
        "GoldFloppyMark.qml",
        "LabeledComboBox.qml",
        "LabeledTextField.qml",
        "LanguageSwitcher.qml",
        "MetalSheen.qml",
        "OpenDConfirmDialog.qml",
        "PixelButton.qml",
        "PixelCheckBox.qml",
        "PixelComboBox.qml",
        "PixelDateField.qml",
        "PixelDivider.qml",
        "PixelEmptyState.qml",
        "PixelFrame.qml",
        "PixelGlyph.qml",
        "PixelPagination.qml",
        "PixelPanel.qml",
        "PixelProgress.qml",
        "PixelScrollBar.qml",
        "PixelStatusBadge.qml",
        "PixelTag.qml",
        "PixelTextField.qml",
        "SaveExportDialog.qml",
        "Sidebar.qml",
        "SummaryStrip.qml",
    )
]
QML_THEME = [
    SOURCE_ROOT / "market_vault" / "desktop" / "qml" / "theme" / name
    for name in ("PixelTheme.qml", "qmldir")
]
FONT_ROOT = (
    SOURCE_ROOT
    / "market_vault"
    / "desktop"
    / "assets"
    / "fonts"
    / "fusion-pixel-12px-proportional-zh_hans-v2026.07.20"
)
FONT_ASSETS = [
    FONT_ROOT / name
    for name in (
        "fusion-pixel-12px-proportional-zh_hans.otf",
        "NOTICE.md",
        "OFL.txt",
    )
]
OBSERVATION_FEATURE_TRANSFORM_SOURCE = (
    SOURCE_ROOT / "market_vault" / "multi_source" / "feature_transforms.py"
)
DATASET_FEATURE_TRANSFORM_SOURCE_ROOT = (
    SOURCE_ROOT / "market_vault" / "dataset" / "feature_transforms"
)
DATASET_LABEL_TRANSFORM_SOURCE_ROOT = (
    SOURCE_ROOT / "market_vault" / "dataset" / "label_transforms"
)
DATASET_FINGERPRINT_SOURCE_DATAS = [
    (str(path), "market_vault/dataset/feature_transforms")
    for path in sorted(DATASET_FEATURE_TRANSFORM_SOURCE_ROOT.glob("*.py"))
    if path.name != "__init__.py"
] + [
    (str(path), "market_vault/dataset/label_transforms")
    for path in sorted(DATASET_LABEL_TRANSFORM_SOURCE_ROOT.glob("*.py"))
    if path.name != "__init__.py"
]
QML_PAGES = [
    SOURCE_ROOT / "market_vault" / "desktop" / "qml" / "pages" / name
    for name in (
        "AuditPage.qml",
        "HistoricalDataPage.qml",
        "HomePage.qml",
        "InventoryPage.qml",
        "MarketDataPage.qml",
        "QuantResearchPage.qml",
        "StrategyComparisonPanel.qml",
        "StrategyListEditor.qml",
        "StrategyDiagnosticsDialog.qml",
        "IntradayResearchPanel.qml",
        "RunsPage.qml",
        "StorageCleanupPage.qml",
        "TradingCalendarPage.qml",
    )
]
WINDOWS_ICON = PROJECT_ROOT / "assets" / "windows" / "market-vault.ico"
HOOKS_ROOT = PROJECT_ROOT / "packaging" / "hooks"

hidden_imports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "duckdb",
    "market_vault.application",
    "market_vault.api",
    "market_vault.console.backend",
    "market_vault.console.tasks",
    "market_vault.desktop.bootstrap",
    "market_vault.desktop.quant_research",
    "market_vault.research_workspace",
    "market_vault.research_dataset",
    "market_vault.multi_source",
    "market_vault.multi_source.feature_execution",
    "market_vault.multi_source.feature_spec_models",
    "market_vault.multi_source.feature_specs",
    "market_vault.desktop.windows_chrome",
    "pandas",
    "pyarrow",
    "pyarrow.parquet",
    "yaml",
]
hidden_imports.extend(collect_submodules("market_vault.multi_source"))
hidden_imports.extend(
    collect_submodules(
        "moomoo",
        filter=lambda name: not name.startswith(("moomoo.examples", "moomoo.tools")),
    )
)

analysis = Analysis(
    [str(ENTRY_POINT)],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=collect_data_files("moomoo", include_py_files=False)
    + [(str(WINDOWS_ICON), "assets/windows")]
    + DATASET_FINGERPRINT_SOURCE_DATAS
    + [
        (
            str(OBSERVATION_FEATURE_TRANSFORM_SOURCE),
            "market_vault/multi_source",
        ),
        (str(QML_ENTRY_POINT), "market_vault/desktop/qml"),
        *[
            (str(path), "market_vault/desktop/qml/components")
            for path in QML_COMPONENTS
        ],
        *[
            (str(path), "market_vault/desktop/qml/pages")
            for path in QML_PAGES
        ],
        *[
            (str(path), "market_vault/desktop/qml/theme")
            for path in QML_THEME
        ],
        *[
            (
                str(path),
                "market_vault/desktop/assets/fonts/"
                "fusion-pixel-12px-proportional-zh_hans-v2026.07.20",
            )
            for path in FONT_ASSETS
        ],
    ],
    hiddenimports=hidden_imports,
    hookspath=[str(HOOKS_ROOT)],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWidgets",
        "_tkinter",
        "tkinter",
        "market_vault.artifact_client",
        "market_vault.console.ui",
        "moomoo.examples",
        "moomoo.tools",
        "pandas.tests",
        "pyarrow.tests",
        "pytest",
        "tests",
    ],
    noarchive=False,
    optimize=0,
)
analysis.datas = [
    item
    for item in analysis.datas
    if not item[0].replace("\\", "/").startswith("pyarrow/tests/")
]
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MarketVault",
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
    name="MarketVault",
)
