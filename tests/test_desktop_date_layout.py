from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "src" / "market_vault" / "desktop" / "qml"
PAGES_ROOT = QML_ROOT / "pages"

FORM_SURFACES = (
    ("historical_data", "historicalDataFormPanel", "historicalDataFormGrid"),
    (
        "trading_calendar",
        "tradingCalendarFormPanel",
        "tradingCalendarFormGrid",
    ),
    ("market_data", "marketDataFormPanel", "marketDataFormGrid"),
    ("inventory", "inventoryFormPanel", "inventoryFormGrid"),
    (
        "coverage_audit",
        "coverageAuditTableFormPanel",
        "coverageAuditTableFormGrid",
    ),
    (
        "intraday_audit",
        "intradayAuditTableFormPanel",
        "intradayAuditTableFormGrid",
    ),
    (
        "storage_cleanup",
        "storageCleanupFormPanel",
        "storageCleanupFormGrid",
    ),
)


def test_date_form_panels_are_sized_from_grid_content():
    pages = (
        "HistoricalDataPage.qml",
        "TradingCalendarPage.qml",
        "MarketDataPage.qml",
        "InventoryPage.qml",
        "AuditPage.qml",
        "StorageCleanupPage.qml",
    )
    for page_name in pages:
        source = (PAGES_ROOT / page_name).read_text(encoding="utf-8")
        assert "id: formPanel" in source
        assert "id: formGrid" in source
        assert "Layout.preferredHeight: formGrid.implicitHeight" in source
        assert "Layout.minimumHeight: formGrid.implicitHeight" in source
        assert source.count("2 * (formPanel.padding + 1)") == 2
        assert "Layout.preferredHeight: 116" not in source
        assert "Layout.preferredHeight: 222" not in source


@pytest.mark.parametrize("scale_factor", ("1", "1.25", "1.5", "2"))
def test_date_form_runtime_geometry_across_dpi_language_and_minimum_window(
    tmp_path: Path,
    scale_factor: str,
):
    pytest.importorskip("PySide6")
    surfaces = repr(FORM_SURFACES)
    script = f'''
import json

from PySide6.QtCore import QObject, QPointF, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from market_vault.desktop.bridge import DesktopBridge
from market_vault.desktop.controllers import (
    AuditController,
    HistoricalDataController,
    InventoryController,
    MarketDataController,
    RunsController,
    TradingCalendarController,
)
from market_vault.desktop.dashboard import DashboardController
from market_vault.desktop.localization import I18nBridge
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.runtime import DesktopOperationRuntime
from market_vault.desktop.shell import ShellController
from market_vault.desktop.storage_cleanup import StorageCleanupController


QQuickStyle.setStyle("Basic")
app = QGuiApplication([])
engine = QQmlApplicationEngine()
bridge = DesktopBridge(parent=engine)
runtime = DesktopOperationRuntime(parent=engine)
dashboard = DashboardController(runtime=runtime, parent=engine)
historical = HistoricalDataController(runtime, parent=engine)
calendar = TradingCalendarController(runtime, parent=engine)
market_data = MarketDataController(runtime, parent=engine)
inventory = InventoryController(runtime, parent=engine)
coverage = AuditController(
    runtime, method_name="coverage_audit", parent=engine
)
intraday = AuditController(
    runtime, method_name="intraday_audit", parent=engine
)
runs = RunsController(runtime, parent=engine)
storage = StorageCleanupController(runtime, parent=engine)
i18n = I18nBridge(
    preference_store=DesktopPreferenceStore(
        root={str(tmp_path / "preferences")!r}
    ),
    parent=engine,
)
shell = ShellController(parent=engine)

context = engine.rootContext()
for name, value in (
    ("desktopBridge", bridge),
    ("operationRuntime", runtime),
    ("dashboardController", dashboard),
    ("historicalDataController", historical),
    ("tradingCalendarController", calendar),
    ("marketDataController", market_data),
    ("inventoryController", inventory),
    ("coverageAuditController", coverage),
    ("intradayAuditController", intraday),
    ("runsController", runs),
    ("storageCleanupController", storage),
    ("i18nBridge", i18n),
    ("shellController", shell),
):
    context.setContextProperty(name, value)

engine.load(QUrl.fromLocalFile({str(QML_ROOT / "Main.qml")!r}))
if not engine.rootObjects():
    raise RuntimeError("Main.qml runtime geometry fixture did not load")
root = engine.rootObjects()[0]


def settle():
    for _ in range(4):
        app.processEvents()
    QTest.qWait(20)
    for _ in range(4):
        app.processEvents()


def number(item, name):
    return float(item.property(name))


def inspect_surface(page_id, panel_name, grid_name):
    if not shell.selectPage(page_id):
        raise RuntimeError(f"could not select page {{page_id}}")
    settle()
    panel = root.findChild(QObject, panel_name)
    grid = root.findChild(QObject, grid_name)
    page_content = root.findChild(QObject, "pageContent")
    if panel is None or grid is None:
        raise RuntimeError(
            f"missing geometry target {{panel_name}} / {{grid_name}}"
        )

    content_top_left = grid.mapToItem(panel, QPointF(0, 0))
    content_bottom_right = grid.mapToItem(
        panel, QPointF(number(grid, "width"), number(grid, "height"))
    )
    lowest_bottom = content_top_left.y()
    greatest_right = content_top_left.x()
    overflow = 0.0
    worst_control = ""
    controls = grid.childItems()
    for control in controls:
        position = control.mapToItem(panel, QPointF(0, 0))
        left = position.x()
        top = position.y()
        right = left + number(control, "width")
        bottom = top + number(control, "height")
        lowest_bottom = max(lowest_bottom, bottom)
        greatest_right = max(greatest_right, right)
        control_overflow = max(
            0.0,
            content_top_left.x() - left,
            content_top_left.y() - top,
            right - content_bottom_right.x(),
            bottom - content_bottom_right.y(),
        )
        if control_overflow > overflow:
            overflow = control_overflow
            worst_control = (
                control.objectName() or control.metaObject().className()
            )

    panel_height = number(panel, "height")
    grid_implicit_height = number(grid, "implicitHeight")
    padding = number(panel, "padding")
    expected_panel_height = grid_implicit_height + 2 * (padding + 1)
    return {{
        "page": page_id,
        "root_width": number(root, "width"),
        "page_content_width": number(page_content, "width"),
        "panel_parent_width": number(panel.parentItem(), "width"),
        "panel_width": number(panel, "width"),
        "grid_width": number(grid, "width"),
        "panel_height": panel_height,
        "form_grid_implicit_height": grid_implicit_height,
        "panel_content_top": content_top_left.y(),
        "panel_content_bottom": content_bottom_right.y(),
        "panel_content_left": content_top_left.x(),
        "panel_content_right": content_bottom_right.x(),
        "lowest_control_bottom": lowest_bottom,
        "greatest_control_right": greatest_right,
        "expected_panel_height": expected_panel_height,
        "overflow_px": max(0.0, overflow),
        "worst_control": worst_control,
        "control_count": len(controls),
    }}


evidence = []
for width, height in ((1100, 700), (1000, 650)):
    root.setProperty("width", width)
    root.setProperty("height", height)
    for language in ("en", "zh-CN"):
        i18n.setLanguage(language)
        settle()
        for surface in {surfaces}:
            result = inspect_surface(*surface)
            result.update({{
                "language": language,
                "window_width": width,
                "window_height": height,
            }})
            evidence.append(result)

shell.selectPage("trading_calendar")
i18n.setLanguage("en")
root.setProperty("width", 1100)
root.setProperty("height", 700)
settle()
trigger = root.findChild(QObject, "calendarStartDateCalendarButton")
glyph = root.findChild(QObject, "calendarStartDateCalendarGlyph")
field_input = root.findChild(QObject, "calendarStartDateInput")
if trigger is None or glyph is None or field_input is None:
    raise RuntimeError("calendar trigger geometry target is missing")
background = trigger.property("background")
glyph_width = number(glyph, "width")
trigger_evidence = {{
    "trigger_width": number(trigger, "width"),
    "trigger_height": number(trigger, "height"),
    "input_width": number(field_input, "width"),
    "input_height": number(field_input, "height"),
    "glyph_width": glyph_width,
    "glyph_height": number(glyph, "height"),
    "glyph_pixel_unit": int(glyph_width // 12),
    "glyph_antialiasing": bool(glyph.property("antialiasing")),
    "background_visible": bool(background.property("visible")),
}}

screen = app.primaryScreen()
print(json.dumps({{
    "device_pixel_ratio": screen.devicePixelRatio() if screen else None,
    "evidence": evidence,
    "trigger": trigger_evidence,
}}))
runtime.shutdown()
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    env["QT_SCALE_FACTOR"] = scale_factor
    env["LOCALAPPDATA"] = str(tmp_path / "local app data")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout.strip())
    assert len(output["evidence"]) == len(FORM_SURFACES) * 4
    for item in output["evidence"]:
        assert item["control_count"] > 0
        assert item["overflow_px"] == pytest.approx(
            0, abs=0.01
        ), json.dumps(item, sort_keys=True)
        assert item["panel_height"] == pytest.approx(
            item["expected_panel_height"], abs=0.01
        ), item
        assert (
            item["lowest_control_bottom"]
            <= item["panel_content_bottom"] + 0.01
        ), item

    trigger = output["trigger"]
    assert trigger["trigger_width"] == pytest.approx(trigger["trigger_height"])
    assert trigger["trigger_height"] == pytest.approx(trigger["input_height"])
    assert trigger["input_width"] > trigger["trigger_width"]
    assert 24 <= trigger["glyph_width"] <= 28
    assert trigger["glyph_width"] == pytest.approx(trigger["glyph_height"])
    assert trigger["glyph_pixel_unit"] == 2
    assert trigger["glyph_antialiasing"] is False
    assert trigger["background_visible"] is False
