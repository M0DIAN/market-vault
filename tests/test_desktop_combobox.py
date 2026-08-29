from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS_ROOT = (
    ROOT / "src" / "market_vault" / "desktop" / "qml" / "components"
)


def test_pixel_combobox_popup_renders_simple_and_text_role_models(tmp_path):
    pytest.importorskip("PySide6")
    components_uri = COMPONENTS_ROOT.as_uri()
    script = f'''
import json
import time

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

QQuickStyle.setStyle("Basic")
app = QGuiApplication([])
engine = QQmlApplicationEngine()
qml = r"""
import QtQuick
import QtQuick.Controls
import "{components_uri}" as Components

ApplicationWindow {{
    id: root
    width: 480
    height: 360
    visible: true
    property var intervalTexts: []
    property var sessionTexts: []
    property var adjustmentTexts: []
    property var structuredTexts: []
    property bool inspectionComplete: false

    Components.PixelComboBox {{
        id: interval
        objectName: "intervalCombo"
        width: 220
        model: ["1m", "5m", "15m", "30m", "60m", "day"]
    }}
    Components.PixelComboBox {{
        id: session
        objectName: "sessionCombo"
        y: 48
        width: 220
        model: ["ALL", "RTH", "ETH"]
    }}
    Components.PixelComboBox {{
        id: adjustment
        objectName: "adjustmentCombo"
        y: 96
        width: 220
        model: ["NONE", "QFQ", "HFQ"]
    }}
    Components.PixelComboBox {{
        id: structured
        objectName: "structuredCombo"
        y: 144
        width: 220
        textRole: "label"
        valueRole: "code"
        model: [
            {{"code": "zh-CN", "label": "中文"}},
            {{"code": "en", "label": "English"}}
        ]
    }}

    function delegateTexts(combo, count) {{
        combo.popup.contentItem.forceLayout()
        const texts = []
        for (let index = 0; index < count; index += 1) {{
            const item = combo.popup.contentItem.itemAtIndex(index)
            texts.push(item && item.contentItem ? item.contentItem.text : null)
        }}
        return texts
    }}

    function inspectAdjustment() {{
        adjustment.popup.open()
        Qt.callLater(function() {{
            root.adjustmentTexts = root.delegateTexts(adjustment, 3)
            adjustment.popup.close()
            root.inspectStructured()
        }})
    }}

    function inspectStructured() {{
        structured.popup.open()
        Qt.callLater(function() {{
            root.structuredTexts = root.delegateTexts(structured, 2)
            structured.popup.close()
            interval.currentIndex = 3
            session.currentIndex = 2
            adjustment.currentIndex = 1
            structured.currentIndex = 1
            root.inspectionComplete = true
        }})
    }}

    function inspectSession() {{
        session.popup.open()
        Qt.callLater(function() {{
            root.sessionTexts = root.delegateTexts(session, 3)
            session.popup.close()
            root.inspectAdjustment()
        }})
    }}

    Component.onCompleted: Qt.callLater(function() {{
        interval.popup.open()
        Qt.callLater(function() {{
            root.intervalTexts = root.delegateTexts(interval, 6)
            interval.popup.close()
            root.inspectSession()
        }})
    }})
}}
"""
engine.loadData(QByteArray(qml.encode("utf-8")), QUrl("runtime.qml"))
if not engine.rootObjects():
    raise RuntimeError("PixelComboBox runtime fixture did not load")
root = engine.rootObjects()[0]
deadline = time.monotonic() + 10
while not root.property("inspectionComplete") and time.monotonic() < deadline:
    app.processEvents()
if not root.property("inspectionComplete"):
    raise RuntimeError("PixelComboBox runtime fixture timed out")
interval = root.findChild(object, "intervalCombo")
session = root.findChild(object, "sessionCombo")
adjustment = root.findChild(object, "adjustmentCombo")
structured = root.findChild(object, "structuredCombo")
interval_texts = root.property("intervalTexts")
session_texts = root.property("sessionTexts")
adjustment_texts = root.property("adjustmentTexts")
structured_texts = root.property("structuredTexts")
print(json.dumps({{
    "interval": interval_texts.toVariant(),
    "session": session_texts.toVariant(),
    "adjustment": adjustment_texts.toVariant(),
    "structured": structured_texts.toVariant(),
    "interval_index": interval.property("currentIndex"),
    "interval_text": interval.property("currentText"),
    "session_index": session.property("currentIndex"),
    "session_text": session.property("currentText"),
    "adjustment_index": adjustment.property("currentIndex"),
    "adjustment_text": adjustment.property("currentText"),
    "structured_index": structured.property("currentIndex"),
    "structured_text": structured.property("currentText"),
    "structured_value": structured.property("currentValue"),
}}, ensure_ascii=False))
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    env["LOCALAPPDATA"] = str(tmp_path / "local app data")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "modelData is not defined" not in result.stderr
    assert json.loads(result.stdout.strip()) == {
        "interval": ["1m", "5m", "15m", "30m", "60m", "day"],
        "session": ["ALL", "RTH", "ETH"],
        "adjustment": ["NONE", "QFQ", "HFQ"],
        "structured": ["中文", "English"],
        "interval_index": 3,
        "interval_text": "30m",
        "session_index": 2,
        "session_text": "ETH",
        "adjustment_index": 1,
        "adjustment_text": "QFQ",
        "structured_index": 1,
        "structured_text": "English",
        "structured_value": "en",
    }
