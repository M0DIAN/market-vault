from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "src" / "market_vault" / "desktop" / "qml"
COMPONENTS_ROOT = QML_ROOT / "components"
PAGES_ROOT = QML_ROOT / "pages"


def test_pixel_date_field_runtime_contract(tmp_path):
    pytest.importorskip("PySide6")
    components_uri = COMPONENTS_ROOT.as_uri()
    script = f'''
import json
import math
import time

from PySide6.QtCore import QByteArray, QMetaObject, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

QQuickStyle.setStyle("Basic")
app = QGuiApplication([])
engine = QQmlApplicationEngine()
qml = r"""
import QtQuick
import QtQuick.Controls
import "{components_uri}" as Components

ApplicationWindow {{
    id: root
    width: 640
    height: 480
    visible: true
    property bool inspectionComplete: false
    property var edits: []
    property int emptyYear: -1
    property int emptyMonth: -1
    property int validYear: -1
    property int validMonth: -1
    property int validDay: -1
    property bool januaryRollover: false
    property bool decemberRollover: false
    property string zhTitle: ""
    property string enTitle: ""
    property string zhLocale: ""
    property string enLocale: ""
    property string selectedText: ""
    property bool popupClosedAfterSelection: false
    property bool popupVisibleAfterOpen: false
    property real popupYAfterOpen: -1
    property bool popupOpenedByClick: false
    property bool popupOpenedByEnter: false
    property bool popupOpenedBySpace: false
    property string storageFieldName: ""
    property string storageFieldValue: ""
    property bool storagePlanInvalidated: false

    QtObject {{
        id: storageController
        property var scope: ({{"start_date": "2026-08-01"}})
        property string planId: "plan-1"
        property string confirmation: "PURGE plan-1"
        property string lastFieldName: ""
        property string lastFieldValue: ""
        function setScopeField(name, value) {{
            lastFieldName = name
            lastFieldValue = value
            scope = {{"start_date": value}}
            planId = ""
            confirmation = ""
        }}
    }}

    Components.PixelDateField {{
        id: field
        objectName: "dateField"
        width: 220
        label: "Date"
        language: "en"
        onEdited: function(value) {{
            const next = root.edits.slice()
            next.push(value)
            root.edits = next
        }}
    }}

    Components.PixelDateField {{
        id: storageField
        objectName: "storageDateField"
        y: 60
        width: 220
        label: "Start date"
        language: "en"
        text: storageController.scope.start_date
        onEdited: value => storageController.setScopeField("start_date", value)
    }}

    function inspect() {{
        field.text = ""
        field.openCalendar()
        root.popupVisibleAfterOpen = field.popupVisible
        const now = new Date()
        root.emptyYear = field.displayYear
        root.emptyMonth = field.displayMonth
        if (root.emptyYear !== now.getFullYear() || root.emptyMonth !== now.getMonth())
            throw new Error("empty date did not open the current month")
        field.closeCalendar()

        field.text = "2026-08-29"
        field.openCalendar()
        root.validYear = field.displayYear
        root.validMonth = field.displayMonth
        root.validDay = field.selectedDay
        field.closeCalendar()

        field.text = "2026-01-15"
        field.openCalendar()
        field.previousMonth()
        const previousDecember = field.displayYear === 2025 && field.displayMonth === 11
        field.nextMonth()
        root.januaryRollover = previousDecember
            && field.displayYear === 2026 && field.displayMonth === 0
        field.closeCalendar()

        field.text = "2026-12-15"
        field.openCalendar()
        field.nextMonth()
        const nextJanuary = field.displayYear === 2027 && field.displayMonth === 0
        field.previousMonth()
        root.decemberRollover = nextJanuary
            && field.displayYear === 2026 && field.displayMonth === 11
        field.closeCalendar()

        field.language = "zh-CN"
        field.text = "2026-08-29"
        field.openCalendar()
        root.zhTitle = field.monthTitle
        root.zhLocale = field.calendarLocale.name
        field.closeCalendar()

        field.language = "en"
        field.openCalendar()
        root.enTitle = field.monthTitle
        root.enLocale = field.calendarLocale.name
        field.commitDate(new Date(2026, 8, 3, 12))
        root.selectedText = field.text
        root.popupClosedAfterSelection = !field.popupVisible

        storageField.openCalendar()
        storageField.commitDate(new Date(2026, 8, 4, 12))
        root.storageFieldName = storageController.lastFieldName
        root.storageFieldValue = storageController.lastFieldValue
        root.storagePlanInvalidated = storageController.planId === ""
            && storageController.confirmation === ""
        root.inspectionComplete = true
    }}

    Component.onCompleted: Qt.callLater(root.inspect)
}}
"""
engine.loadData(QByteArray(qml.encode("utf-8")), QUrl("date-picker-runtime.qml"))
if not engine.rootObjects():
    raise RuntimeError("PixelDateField runtime fixture did not load")
root = engine.rootObjects()[0]
deadline = time.monotonic() + 10
while not root.property("inspectionComplete") and time.monotonic() < deadline:
    app.processEvents()
if not root.property("inspectionComplete"):
    raise RuntimeError("PixelDateField runtime fixture timed out")

field_input = root.findChild(QObject, "dateFieldInput")
if field_input is None:
    raise RuntimeError("PixelDateField manual input was not exposed")
field_input.setProperty("text", "2026-10-04")
if not QMetaObject.invokeMethod(
    field_input, "textEdited", Qt.ConnectionType.DirectConnection
):
    raise RuntimeError("PixelDateField manual textEdited signal could not be invoked")
app.processEvents()

calendar_popup = root.findChild(QObject, "dateFieldCalendarPopup")
if calendar_popup is None:
    raise RuntimeError("PixelDateField popup was not exposed")
calendar_trigger = root.findChild(QObject, "dateFieldCalendarButton")
if calendar_trigger is None:
    raise RuntimeError("PixelDateField calendar trigger was not exposed")
calendar_glyph = root.findChild(QObject, "dateFieldCalendarGlyph")
if calendar_glyph is None:
    raise RuntimeError("PixelDateField calendar glyph was not exposed")
date_field = root.findChild(QObject, "dateField")
if date_field is None or not QMetaObject.invokeMethod(
    date_field, "openCalendar", Qt.ConnectionType.DirectConnection
):
    raise RuntimeError("PixelDateField popup could not be reopened")
app.processEvents()
root.setProperty("popupYAfterOpen", calendar_popup.property("y"))
root.setProperty("popupVisibleAfterOpen", calendar_popup.property("visible"))
date_field.closeCalendar()

if not QMetaObject.invokeMethod(
    calendar_trigger, "click", Qt.ConnectionType.DirectConnection
):
    raise RuntimeError("PixelDateField calendar trigger could not be clicked")
app.processEvents()
root.setProperty("popupOpenedByClick", calendar_popup.property("visible"))
date_field.closeCalendar()

if not QMetaObject.invokeMethod(
    calendar_trigger, "forceActiveFocus", Qt.ConnectionType.DirectConnection
):
    raise RuntimeError("PixelDateField calendar trigger could not receive focus")
QTest.keyClick(root, Qt.Key.Key_Return)
app.processEvents()
root.setProperty("popupOpenedByEnter", calendar_popup.property("visible"))
date_field.closeCalendar()

QMetaObject.invokeMethod(
    calendar_trigger, "forceActiveFocus", Qt.ConnectionType.DirectConnection
)
QTest.keyClick(root, Qt.Key.Key_Space)
app.processEvents()
root.setProperty("popupOpenedBySpace", calendar_popup.property("visible"))

calendar_background = calendar_trigger.property("background")
glyph_width = float(calendar_glyph.property("width"))
glyph_height = float(calendar_glyph.property("height"))
glyph_unit = int(calendar_glyph.property("pixelUnitOverride"))
glyph_origin = calendar_glyph.mapToItem(calendar_trigger, QPointF(0, 0))
offset_x = math.floor((glyph_width - 12 * glyph_unit) / 2)
offset_y = math.floor((glyph_height - 12 * glyph_unit) / 2)
visible_bounds = [
    glyph_origin.x() + offset_x + 2 * glyph_unit,
    glyph_origin.y() + offset_y + 2 * glyph_unit,
    glyph_origin.x() + offset_x + 10 * glyph_unit,
    glyph_origin.y() + offset_y + 10 * glyph_unit,
]
trigger_width = float(calendar_trigger.property("width"))
trigger_height = float(calendar_trigger.property("height"))

print(json.dumps({{
    "empty_year": root.property("emptyYear"),
    "empty_month": root.property("emptyMonth"),
    "valid_year": root.property("validYear"),
    "valid_month": root.property("validMonth"),
    "valid_day": root.property("validDay"),
    "january_rollover": root.property("januaryRollover"),
    "december_rollover": root.property("decemberRollover"),
    "zh_title": root.property("zhTitle"),
    "en_title": root.property("enTitle"),
    "zh_locale": root.property("zhLocale"),
    "en_locale": root.property("enLocale"),
    "selected_text": root.property("selectedText"),
    "popup_closed": root.property("popupClosedAfterSelection"),
    "popup_visible_after_open": root.property("popupVisibleAfterOpen"),
    "popup_y_after_open": root.property("popupYAfterOpen"),
    "popup_opened_by_click": root.property("popupOpenedByClick"),
    "popup_opened_by_enter": root.property("popupOpenedByEnter"),
    "popup_opened_by_space": root.property("popupOpenedBySpace"),
    "trigger_background_visible": calendar_background.property("visible"),
    "trigger_width": trigger_width,
    "trigger_height": trigger_height,
    "glyph_name": calendar_glyph.property("glyph"),
    "glyph_width": glyph_width,
    "glyph_height": glyph_height,
    "glyph_pixel_unit": glyph_unit,
    "glyph_visible_bounds": visible_bounds,
    "glyph_contained": visible_bounds[0] >= 0 and visible_bounds[1] >= 0
        and visible_bounds[2] <= trigger_width and visible_bounds[3] <= trigger_height,
    "glyph_centered": abs((visible_bounds[0] + visible_bounds[2]) / 2 - trigger_width / 2) < 0.01
        and abs((visible_bounds[1] + visible_bounds[3]) / 2 - trigger_height / 2) < 0.01,
    "edits": root.property("edits").toVariant(),
    "storage_field_name": root.property("storageFieldName"),
    "storage_field_value": root.property("storageFieldValue"),
    "storage_plan_invalidated": root.property("storagePlanInvalidated"),
}}, ensure_ascii=False))
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
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
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip())
    assert evidence["valid_year"] == 2026
    assert evidence["valid_month"] == 7
    assert evidence["valid_day"] == 29
    assert evidence["january_rollover"] is True
    assert evidence["december_rollover"] is True
    assert evidence["zh_locale"].replace("-", "_").startswith("zh_CN")
    assert evidence["en_locale"].replace("-", "_").startswith("en_US")
    assert "2026" in evidence["zh_title"] and "8" in evidence["zh_title"]
    assert "August" in evidence["en_title"] and "2026" in evidence["en_title"]
    assert evidence["selected_text"] == "2026-09-03"
    assert evidence["popup_closed"] is True
    assert evidence["popup_visible_after_open"] is True
    assert evidence["popup_y_after_open"] >= 0
    assert evidence["popup_opened_by_click"] is True
    assert evidence["popup_opened_by_enter"] is True
    assert evidence["popup_opened_by_space"] is True
    assert evidence["trigger_background_visible"] is False
    assert evidence["trigger_width"] == pytest.approx(evidence["trigger_height"])
    assert evidence["trigger_width"] == pytest.approx(34)
    assert evidence["glyph_name"] == "calendar"
    assert evidence["glyph_width"] == pytest.approx(evidence["glyph_height"])
    assert evidence["glyph_width"] == pytest.approx(evidence["trigger_width"])
    assert evidence["glyph_pixel_unit"] == 3
    assert evidence["glyph_visible_bounds"] == pytest.approx([5, 5, 29, 29])
    assert evidence["glyph_contained"] is True
    assert evidence["glyph_centered"] is True
    assert evidence["edits"] == ["2026-09-03", "2026-10-04"]
    assert evidence["storage_field_name"] == "start_date"
    assert evidence["storage_field_value"] == "2026-09-04"
    assert evidence["storage_plan_invalidated"] is True


def test_only_true_date_inputs_use_pixel_date_field():
    expected_counts = {
        "HistoricalDataPage.qml": 3,
        "TradingCalendarPage.qml": 2,
        "MarketDataPage.qml": 2,
        "InventoryPage.qml": 2,
        "AuditPage.qml": 2,
        "StorageCleanupPage.qml": 2,
    }
    for name, count in expected_counts.items():
        text = (PAGES_ROOT / name).read_text(encoding="utf-8")
        assert text.count("Components.PixelDateField") == count

    historical = (PAGES_ROOT / "HistoricalDataPage.qml").read_text(
        encoding="utf-8"
    )
    assert 'id: symbols; objectName: "backfillSymbols"' in historical
    assert 'id: retries; label: root.i18n.catalog["field.max_retries"]' in historical
    assert 'id: backoff; label: root.i18n.catalog["field.retry_backoff"]' in historical

    market_data = (PAGES_ROOT / "MarketDataPage.qml").read_text(encoding="utf-8")
    assert 'id: code; objectName: "marketDataCode"' in market_data
    assert 'id: pageSize; label: root.i18n.catalog["field.page_size"]' in market_data


def test_storage_date_pickers_preserve_exact_scope_authority():
    storage = (PAGES_ROOT / "StorageCleanupPage.qml").read_text(encoding="utf-8")
    assert (
        'Components.PixelDateField { objectName: "storageStartDate"; '
        'label: root.i18n.catalog["field.start_date"]; '
        'language: root.i18n.language; text: root.controller.scope.start_date; '
        'onEdited: value => root.controller.setScopeField("start_date", value) }'
        in storage
    )
    assert (
        'Components.PixelDateField { objectName: "storageEndDate"; '
        'label: root.i18n.catalog["field.end_date"]; '
        'language: root.i18n.language; text: root.controller.scope.end_date; '
        'onEdited: value => root.controller.setScopeField("end_date", value) }'
        in storage
    )
    assert "root.controller.scope.start_date =" not in storage
    assert "root.controller.scope.end_date =" not in storage


def test_pixel_date_field_uses_qt_calendar_and_is_packaged():
    component = (COMPONENTS_ROOT / "PixelDateField.qml").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "MarketVault.spec").read_text(encoding="utf-8")

    assert "MonthGrid" in component
    assert "DayOfWeekRow" in component
    assert "onTextEdited: root.edited(text)" in component
    assert "root.edited(canonical)" in component
    assert "calendarPopup.close()" in component
    assert 'glyph: "calendar"' in component
    assert '"PixelDateField.qml"' in spec


def test_pixel_date_field_calendar_trigger_is_borderless_and_scaled():
    component = (COMPONENTS_ROOT / "PixelDateField.qml").read_text(encoding="utf-8")
    trigger = component.split("id: calendarTrigger", maxsplit=1)[1].split(
        "Popup {", maxsplit=1
    )[0]

    assert "PixelButton" not in trigger
    assert "background: Item { visible: false }" in trigger
    assert 'glyph: "calendar"' in trigger
    assert "Layout.preferredWidth: field.height" in trigger
    assert "Layout.preferredHeight: field.height" in trigger
    assert "readonly property int glyphSize" not in trigger
    assert "width: calendarTrigger.width" in trigger
    assert "height: calendarTrigger.height" in trigger
    assert "pixelUnitOverride: 3" in trigger
    assert "Theme.PixelTheme.inkMuted" in trigger
    assert "Theme.PixelTheme.goldDark" in trigger
    assert "Accessible.name: root.label" in trigger
    assert "event.key === Qt.Key_Return" in trigger
    assert "event.key === Qt.Key_Enter" in trigger
    assert "event.key === Qt.Key_Space" in trigger


def test_pixel_glyph_unit_override_is_opt_in_and_date_field_only():
    glyph = (COMPONENTS_ROOT / "PixelGlyph.qml").read_text(encoding="utf-8")

    assert "property int pixelUnitOverride: 0" in glyph
    assert "onPixelUnitOverrideChanged: requestPaint()" in glyph
    assert "root.pixelUnitOverride > 0 ? root.pixelUnitOverride" in glyph
    assert ": Math.max(1, Math.floor(Math.min(width, height) / 12))" in glyph

    override_users = []
    for path in QML_ROOT.rglob("*.qml"):
        if "pixelUnitOverride: 3" in path.read_text(encoding="utf-8"):
            override_users.append(path.relative_to(QML_ROOT).as_posix())
    assert override_users == ["components/PixelDateField.qml"]
