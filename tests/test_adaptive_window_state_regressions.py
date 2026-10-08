"""State-transition regressions using the existing, explicitly non-native fixture."""

from test_adaptive_window_controller import (
    App, Prefs, QFakeRect, Rect, Screen, Window, _saved,
    AdaptiveWindowGeometry, fake_qtcore,
)


def test_reduced_workarea_updates_minimum_while_maximized():
    screen = Screen("primary", QFakeRect(0, 0, 1920, 1040))
    app, win, store = App([screen]), Window(screen), Prefs(_saved())
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    win.setState(1)
    win.setGeometry(QFakeRect(0, 0, 1920, 1040))
    before = win.geometry()
    screen.area = QFakeRect(0, 0, 900, 500)
    screen.availableGeometryChanged.emit()
    assert (win.minimumSize().width(), win.minimumSize().height()) == (640, 360)
    # The window manager, not the application, owns maximized geometry.
    assert win.geometry() == before
    assert controller._normal == Rect(75, 100, 1200, 760)


def test_fullscreen_does_not_erase_maximized_preference():
    screen = Screen("primary", QFakeRect(0, 0, 1920, 1040))
    app, win, store = App([screen]), Window(screen), Prefs(_saved())
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    win.setState(1)
    win.setState(4)
    win.setGeometry(QFakeRect(0, 0, 1920, 1080))
    controller._save_if_dirty()
    assert store.writes[-1]["maximized"] is True
    assert (store.writes[-1]["width"], store.writes[-1]["height"]) == (1200, 760)
