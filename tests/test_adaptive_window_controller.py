"""Exercise the production geometry controller against a small Qt API substitute.

This does not claim to emulate Windows frame/DPI events or render QML.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
import sys

import pytest

from market_vault.desktop.window_geometry import AdaptiveWindowGeometry, Rect


class Signal:
    def __init__(self):
        self.listeners = []

    def connect(self, callback):
        self.listeners.append(callback)

    def emit(self, *args):
        for callback in list(self.listeners):
            callback(*args)


@dataclass
class QFakeRect:
    xx: int
    yy: int
    ww: int
    hh: int

    def x(self): return self.xx
    def y(self): return self.yy
    def width(self): return self.ww
    def height(self): return self.hh


class QFakeSize:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def width(self): return self._width
    def height(self): return self._height


@dataclass
class QFakeMargins:
    ll: int
    tt: int
    rr: int
    bb: int

    def left(self): return self.ll
    def top(self): return self.tt
    def right(self): return self.rr
    def bottom(self): return self.bb


class QFakeTimer:
    def __init__(self, _parent):
        self.timeout = Signal()
        self.pending = False

    def setSingleShot(self, _value): pass
    def setInterval(self, _value): pass
    def start(self): self.pending = True
    def stop(self): self.pending = False

    @staticmethod
    def singleShot(_ms, callback): callback()


@pytest.fixture(autouse=True)
def fake_qtcore(monkeypatch):
    qtcore = ModuleType("PySide6.QtCore")
    qtcore.QRect = QFakeRect
    qtcore.QSize = QFakeSize
    qtcore.QTimer = QFakeTimer

    class Qt:
        WindowMaximized = 1
        WindowMinimized = 2
        WindowFullScreen = 4

    qtcore.Qt = Qt
    pyside = ModuleType("PySide6")
    pyside.QtCore = qtcore
    monkeypatch.setitem(sys.modules, "PySide6", pyside)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore)


class Screen:
    def __init__(self, name, area):
        self._name = name
        self.area = area
        self.availableGeometryChanged = Signal()

    def name(self): return self._name
    def availableGeometry(self): return self.area


class App:
    def __init__(self, screens):
        self._screens = screens
        self.screenRemoved = Signal()
        self.aboutToQuit = Signal()

    def screens(self): return self._screens
    def primaryScreen(self): return self._screens[0]


class Window:
    def __init__(self, screen):
        self._screen = screen
        self._rect = QFakeRect(0, 0, 1100, 700)
        self._state = 0
        self._min = None
        self.xChanged = Signal()
        self.yChanged = Signal()
        self.widthChanged = Signal()
        self.heightChanged = Signal()
        self.windowStateChanged = Signal()
        self.screenChanged = Signal()

    def frameMargins(self): return QFakeMargins(8, 44, 8, 8)
    def setScreen(self, screen): self._screen = screen
    def setMinimumSize(self, value): self._min = value
    def minimumSize(self): return self._min
    def setGeometry(self, new):
        self._rect = new
        for signal in (self.xChanged, self.yChanged, self.widthChanged, self.heightChanged):
            signal.emit()

    def geometry(self): return self._rect
    def windowStates(self): return self._state
    def showMaximized(self): self.setState(1)
    def screen(self): return self._screen

    def setState(self, state):
        self._state = state
        self.windowStateChanged.emit(state)


class Prefs:
    def __init__(self, initial=None):
        self.initial = initial
        self.writes = []

    def load_window(self): return self.initial
    def save_window(self, payload):
        self.writes.append(dict(payload))
        return True


def _saved(**update):
    out = {"x": 75, "y": 100, "width": 1200, "height": 760,
           "maximized": False, "screen": "primary"}
    out.update(update)
    return out


def test_initial_geometry_and_user_resize_are_saved_not_startup_values():
    screen = Screen("primary", QFakeRect(0, 0, 1920, 1040))
    app, win, store = App([screen]), Window(screen), Prefs()
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    assert Rect(win.geometry().x(), win.geometry().y(), win.geometry().width(), win.geometry().height()).width == 1440
    assert (win._min.width(), win._min.height()) == (1024, 600)
    assert not store.writes
    win.setGeometry(QFakeRect(130, 80, 1200, 750))
    app.aboutToQuit.emit()
    assert len(store.writes) == 1
    assert store.writes[0]["width"] == 1200
    assert store.writes[0]["height"] == 750
    assert not store.writes[0]["maximized"]


def test_maximized_window_preserves_normal_restore_geometry_even_when_minimized():
    screen = Screen("primary", QFakeRect(0, 0, 1920, 1040))
    app, win, store = App([screen]), Window(screen), Prefs(_saved())
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    assert win.geometry().width() == 1200
    win.setState(1)
    win.setGeometry(QFakeRect(0, 0, 1920, 1040))
    controller._save_if_dirty()
    assert store.writes[-1]["width"] == 1200
    assert store.writes[-1]["maximized"] is True
    win.setState(1 | 2)
    controller._save_if_dirty()
    assert store.writes[-1]["maximized"] is True


def test_removed_screen_recovers_without_erasing_saved_user_geometry():
    left = Screen("left", QFakeRect(-1600, 0, 1600, 900))
    right = Screen("right", QFakeRect(0, 0, 1200, 720))
    app, win, store = App([right, left]), Window(left), Prefs(_saved(screen="left", x=-1500, width=1200, height=740))
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    assert win.geometry().x() == -1500
    app._screens = [right]
    win._screen = right
    app.screenRemoved.emit(left)
    rect = win.geometry()
    assert rect.x() >= 8
    assert rect.y() >= 44
    assert rect.x() + rect.width() + 8 <= right.area.xx + right.area.ww
    assert rect.y() + rect.height() + 8 <= right.area.yy + right.area.hh
    assert not store.writes


def test_workarea_reduction_shrinks_window_and_dynamic_minimum():
    screen = Screen("primary", QFakeRect(0, 0, 1920, 1040))
    app, win, store = App([screen]), Window(screen), Prefs()
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    screen.area = QFakeRect(0, 0, 900, 500)
    screen.availableGeometryChanged.emit()
    assert win.geometry().width() <= 884
    assert win.geometry().height() <= 448
    assert win._min.width() == 640
    assert win._min.height() == 360
    assert not store.writes


def test_dragging_across_two_monitors_does_not_snap_back_to_one():
    left = Screen("left", QFakeRect(-1200, 0, 1200, 900))
    right = Screen("right", QFakeRect(0, 0, 1600, 900))
    app, win, store = App([left, right]), Window(left), Prefs()
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    win.setGeometry(QFakeRect(-120, 85, 1100, 730))
    win.setScreen(right)
    win.screenChanged.emit(right)
    rect = win.geometry()
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (-120, 85, 1100, 730)
