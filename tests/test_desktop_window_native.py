"""Native Windows window-state coverage; not a mixed-DPI hardware claim."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows Qt")
def test_native_window_geometry_and_restore(tmp_path):
    script = textwrap.dedent(r'''
        import json
        from pathlib import Path
        import sys
        from PySide6.QtCore import QRect, Qt
        from PySide6.QtGui import QGuiApplication, QWindow
        from PySide6.QtTest import QTest
        from market_vault.desktop.preferences import DesktopPreferenceStore
        from market_vault.desktop.window_geometry import AdaptiveWindowGeometry

        app = QGuiApplication([])
        assert app.platformName() == "windows", app.platformName()
        errors = []
        sys.excepthook = lambda kind, value, tb: errors.append(repr(value))
        screens = app.screens()
        assert screens
        print("NATIVE_WINDOWS_EVIDENCE", json.dumps({
            "platform": app.platformName(),
            "screens": [{"name": s.name(),
                         "available_dip": s.availableGeometry().getRect(),
                         "dpr": s.devicePixelRatio(),
                         "logical_dpi": s.logicalDotsPerInch()} for s in screens],
            "physical_mixed_dpi_tested": False,
        }), flush=True)
        store = DesktopPreferenceStore(root=Path(sys.argv[1]))
        window = QWindow()
        window.setTitle("MarketVault native window verification")
        window.setGeometry(0, 0, 1100, 700)
        window.show()
        QTest.qWait(150)
        controller = AdaptiveWindowGeometry(app, window, store)
        controller.install()
        QTest.qWait(500)
        area = window.screen().availableGeometry()
        assert area.contains(window.frameGeometry()), (
            area.getRect(), window.frameGeometry().getRect())
        size = window.minimumSize()
        assert size.width() <= area.width() and size.height() <= area.height()
        # An actual resize is tracked through Qt signals and the debounce timer.
        rect = QRect(window.geometry())
        rect.setWidth(max(size.width(), rect.width() - 60))
        rect.setHeight(max(size.height(), rect.height() - 30))
        window.setGeometry(rect)
        QTest.qWait(500)
        normal = window.geometry().getRect()
        saved = store.load_window()
        assert saved is not None
        assert tuple(saved[k] for k in ("x", "y", "width", "height")) == normal
        window.showMaximized()
        QTest.qWait(500)
        assert window.windowStates() & Qt.WindowMaximized
        saved = store.load_window()
        assert saved["maximized"] is True
        assert tuple(saved[k] for k in ("width", "height")) == normal[2:]
        window.showMinimized()
        QTest.qWait(400)
        assert store.load_window()["maximized"] is True
        window.showMaximized()
        QTest.qWait(400)
        window.showFullScreen()
        QTest.qWait(500)
        assert window.windowStates() & Qt.WindowFullScreen
        saved = store.load_window()
        assert saved["maximized"] is True
        assert tuple(saved[k] for k in ("width", "height")) == normal[2:]
        window.showNormal()
        QTest.qWait(500)
        assert not window.windowStates() & (
            Qt.WindowMaximized | Qt.WindowMinimized | Qt.WindowFullScreen)
        assert window.screen().availableGeometry().contains(window.frameGeometry())
        assert store.load_window()["maximized"] is False
        assert window.geometry().getRect()[2:] == normal[2:]
        assert not errors, errors
        print("NATIVE_STATE_ROUNDTRIP=PASS", flush=True)
        window.close()
    ''')
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "windows"
    env["QT_QUICK_BACKEND"] = "software"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "preferences")],
        env=env, text=True, capture_output=True, timeout=60,
    )
    print(result.stdout)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "NATIVE_STATE_ROUNDTRIP=PASS" in result.stdout
