"""Real QML small-viewport access; explicitly not physical-DPI validation."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None,
                    reason="requires the desktop extra")
def test_small_workspace_and_settings_completion_are_reachable(tmp_path):
    source = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(r'''
        from pathlib import Path
        import sys
        from PySide6.QtCore import QObject, Qt, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuick import QQuickItem
        from PySide6.QtQuickControls2 import QQuickStyle
        from PySide6.QtTest import QTest
        from market_vault.application import build_application_context
        from market_vault.desktop.bootstrap import create_qml_application_session
        from market_vault.desktop.preferences import DesktopPreferenceStore

        source, temp = Path(sys.argv[1]), Path(sys.argv[2])
        settings = temp / "settings.yaml"
        settings.write_text("storage:\n  root_dir: ./data\n", encoding="utf-8")
        QQuickStyle.setStyle("Basic")
        app = QGuiApplication([])
        engine = QQmlApplicationEngine()
        errors = []
        sys.excepthook = lambda kind, value, tb: errors.append(repr(value))
        session = create_qml_application_session(
            build_application_context(settings), engine,
            preference_store=DesktopPreferenceStore(root=temp / "preferences"))
        engine.load(QUrl.fromLocalFile(str(source / "src/market_vault/desktop/qml/Main.qml")))
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        session.shell.selectPage("quant_research")
        def find(name):
            obj = window.findChild(QObject, name)
            if obj is None:
                todo = [window.contentItem()]
                while todo:
                    candidate = todo.pop()
                    if candidate.objectName() == name:
                        obj = candidate
                        break
                    todo.extend(candidate.childItems())
            assert obj is not None, name
            return obj
        def reveal(obj, scroll):
            flick = scroll.property("contentItem")
            rect = obj.mapRectToItem(flick, obj.boundingRect())
            dx = rect.left() if rect.left() < 0 else max(0, rect.right() - flick.width())
            dy = rect.top() if rect.top() < 0 else max(0, rect.bottom() - flick.height())
            for axis, delta, extent in (("X", dx, flick.width()), ("Y", dy, flick.height())):
                span = flick.property("contentWidth" if axis == "X" else "contentHeight")
                value = min(max(0, flick.property("content" + axis) + delta), max(0, span - extent))
                flick.setProperty("content" + axis, value)
            QTest.qWait(40)
            rect = obj.mapRectToItem(flick, obj.boundingRect())
            assert rect.left() >= -1 and rect.top() >= -1, (obj.objectName(), rect)
            assert rect.right() <= flick.width() + 1 and rect.bottom() <= flick.height() + 1, (obj.objectName(), rect)
        def click(name, scroll):
            obj = find(name)
            reveal(obj, scroll)
            assert obj.property("visible") and obj.property("enabled"), name
            point = obj.mapToScene(obj.boundingRect().center()).toPoint()
            assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            QTest.qWait(50)
        workspace = find("adaptiveWorkspaceViewport")
        for language in ("en", "zh-CN"):
            session.i18n.setLanguage(language)
            for width, height in ((1100, 700), (1024, 600), (640, 360)):
                window.setWidth(width)
                window.setHeight(height)
                QTest.qWait(100)
                assert (window.width(), window.height()) == (width, height)
                click("quantIntradayTab", workspace)
                click("intradayComparisonTab", workspace)
                click("intradayResearchSettingsButton", workspace)
                dialog = find("intradayResearchSettings")
                assert dialog.property("visible")
                assert dialog.property("y") >= 0
                assert dialog.property("y") + dialog.property("height") <= height
                click("intradayResearchSettingsDone", find("intradaySettingsScroll"))
                assert not dialog.property("visible")
                print("QML_COMPLETION_ACCESS", language, width, height, flush=True)
        assert not errors, errors
        assert session.shutdown()
        window.close()
    ''')
    result = subprocess.run(
        [sys.executable, "-c", script, str(source), str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
             "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(source / "src")},
        text=True, capture_output=True, timeout=90,
    )
    print(result.stdout)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert result.stdout.count("QML_COMPLETION_ACCESS") == 6
