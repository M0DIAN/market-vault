from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "src" / "market_vault" / "desktop" / "qml"
FONT_ROOT = (
    ROOT
    / "src"
    / "market_vault"
    / "desktop"
    / "assets"
    / "fonts"
    / "fusion-pixel-12px-proportional-zh_hans-v2026.07.20"
)


def test_visual_system_has_one_packaged_theme_and_complete_native_components():
    theme = (QML_ROOT / "theme" / "PixelTheme.qml").read_text(encoding="utf-8")
    qmldir = (QML_ROOT / "theme" / "qmldir").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "MarketVault.spec").read_text(
        encoding="utf-8"
    )
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "pragma Singleton" in theme
    assert "readonly property int pixelUnit: 2" in theme
    for color in (
        "#EEEAE0",
        "#F7F1E7",
        "#FFF9EE",
        "#2B2217",
        "#B58A2A",
        "#A14A28",
    ):
        assert color in theme
    assert qmldir.strip() == "singleton PixelTheme 1.0 PixelTheme.qml"
    assert '"qml/theme/*.qml"' in pyproject
    assert '"qml/theme/qmldir"' in pyproject
    assert '"market_vault/desktop/qml/theme"' in spec

    expected_components = {
        "AmbientBinaryField.qml",
        "GoldFloppyMark.qml",
        "MetalSheen.qml",
        "PixelButton.qml",
        "PixelCheckBox.qml",
        "PixelComboBox.qml",
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
    }
    assert expected_components <= {
        path.name for path in (QML_ROOT / "components").glob("*.qml")
    }
    for name in expected_components:
        assert f'"{name}"' in spec


def test_official_fusion_pixel_font_is_pinned_licensed_and_packaged():
    font = FONT_ROOT / "fusion-pixel-12px-proportional-zh_hans.otf"
    notice = (FONT_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    license_text = (FONT_ROOT / "OFL.txt").read_text(encoding="utf-8")
    main = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
    theme = (QML_ROOT / "theme" / "PixelTheme.qml").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "MarketVault.spec").read_text(
        encoding="utf-8"
    )

    assert hashlib.sha256(font.read_bytes()).hexdigest() == (
        "9955f9e20abd758316418a2942aa6ee773754060da4a3f9286581fd11312f6c3"
    )
    assert "https://github.com/TakWolf/fusion-pixel-font" in notice
    assert "2026.07.20" in notice
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    assert "fusion-pixel-12px-proportional-zh_hans.otf" in main
    assert 'uiFont: "Fusion Pixel 12px Prop zh_hans"' in theme
    assert "FONT_ASSETS" in spec


def test_visual_assets_are_original_native_qml_and_table_cells_stay_lightweight():
    glyphs = (QML_ROOT / "components" / "PixelGlyph.qml").read_text(
        encoding="utf-8"
    )
    mark = (QML_ROOT / "components" / "GoldFloppyMark.qml").read_text(
        encoding="utf-8"
    )
    table = (QML_ROOT / "components" / "DataTable.qml").read_text(
        encoding="utf-8"
    )
    ambient = (QML_ROOT / "components" / "AmbientBinaryField.qml").read_text(
        encoding="utf-8"
    )

    for glyph in (
        "home",
        "history",
        "calendar",
        "chart",
        "inventory",
        "audit",
        "pulse",
        "runs",
        "storage",
        "lock",
        "network",
    ):
        assert f'"{glyph}"' in glyphs
    assert "Canvas" in glyphs
    assert "Image {" not in glyphs + mark
    assert "http://" not in glyphs + mark
    assert "https://" not in glyphs + mark
    assert "ShaderEffect" not in table
    assert "MultiEffect" not in table
    assert "Animation" not in table
    assert "interval: 1600" in ambient
    assert "0.060" in ambient and "0.040" in ambient


def test_shell_retains_native_window_and_safe_purge_danger_semantics():
    main = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
    storage = (QML_ROOT / "pages" / "StorageCleanupPage.qml").read_text(
        encoding="utf-8"
    )
    home = (QML_ROOT / "pages" / "HomePage.qml").read_text(encoding="utf-8")

    assert "ApplicationWindow" in main
    assert "flags: Qt.FramelessWindowHint" not in main
    assert "minimumWidth: 1000" in main
    assert "minimumHeight: 650" in main
    assert "StackLayout" in main
    assert "operationRuntime.requestShutdown()" in main
    assert "Components.GoldFloppyMark" in main
    assert "Components.AmbientBinaryField" in home
    assert 'objectName: "storageExecuteButton"' in storage
    assert 'variant: "danger"' in storage
    assert 'placeholderText: "PURGE <plan_id>"' in storage
    assert "Keys.onReturnPressed" not in storage
    assert "Keys.onEnterPressed" not in storage
    assert "Components.PixelDivider" in main
    assert 'objectName: "pageTitleDividerSlot"' in main
    assert "Layout.preferredWidth: 640" in main
    assert "spacing: 14" in main
    assert "parent: Overlay.overlay" in main
    assert "anchors.centerIn: parent" in main
    assert "Layout.preferredWidth: operationRuntime.busy ? 54 : 0" in main

    opend_dialog = (
        QML_ROOT / "components" / "OpenDConfirmDialog.qml"
    ).read_text(encoding="utf-8")
    assert "parent: Overlay.overlay" in opend_dialog
    assert "anchors.centerIn: parent" in opend_dialog

    historical = (
        QML_ROOT / "pages" / "HistoricalDataPage.qml"
    ).read_text(encoding="utf-8")
    assert "Layout.topMargin: 4" in historical
    assert "Layout.preferredHeight: 222" in historical


def test_pixel_controls_share_stepped_metal_focus_and_press_language():
    components = QML_ROOT / "components"
    button = (components / "PixelButton.qml").read_text(encoding="utf-8")
    field = (components / "PixelTextField.qml").read_text(encoding="utf-8")
    combo = (components / "PixelComboBox.qml").read_text(encoding="utf-8")
    checkbox = (components / "PixelCheckBox.qml").read_text(encoding="utf-8")
    tag = (components / "PixelTag.qml").read_text(encoding="utf-8")
    table = (components / "DataTable.qml").read_text(encoding="utf-8")
    progress = (components / "PixelProgress.qml").read_text(encoding="utf-8")
    glyph = (components / "PixelGlyph.qml").read_text(encoding="utf-8")

    for source in (button, field, combo, checkbox, tag):
        assert "width: 2; height: 2" in source
        assert "PixelTheme.goldLight" in source
    assert "x: control.down ? 1 : 0" in button
    assert "control.activeFocus ? 3 : 1" in field
    assert "control.activeFocus ? 3 : 1" in combo
    assert "PixelTheme.goldHighlight" in table
    assert "font.family: Theme.PixelTheme.dataFont" in table
    assert "visible: running" in progress
    assert '"language": [[4,2,4,1]' in glyph


def test_pages_share_theme_and_component_primitives_without_business_imports():
    qml_files = sorted(QML_ROOT.rglob("*.qml"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in qml_files)
    for forbidden in (
        "WebView",
        "QtWebEngine",
        "ShaderEffect",
        "MultiEffect",
        "market_vault.storage",
        "market_vault.service",
    ):
        assert forbidden not in combined
    for page in (QML_ROOT / "pages").glob("*.qml"):
        assert 'import "../components" as Components' in page.read_text(
            encoding="utf-8"
        )
        assert 'import "../theme" as Theme' in page.read_text(encoding="utf-8")
