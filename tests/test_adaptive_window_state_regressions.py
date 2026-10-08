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


def test_window_manager_rehome_before_screen_notification_is_not_persisted():
    left = Screen("left", QFakeRect(-1600, 0, 1600, 900))
    right = Screen("right", QFakeRect(0, 0, 1200, 720))
    app, win = App([right, left]), Window(left)
    store = Prefs(_saved(screen="left", x=-1500, width=1200, height=740))
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    original = controller._normal
    app._screens = [right]
    win._screen = right
    # Native geometry notification arrives before the deferred screen signal.
    fallback = QFakeRect(20, 60, 1100, 620)
    win.setGeometry(fallback)
    app.screenRemoved.emit(left)
    win.setGeometry(fallback)  # Late duplicate notification must stay temporary.
    app.aboutToQuit.emit()
    assert not store.writes
    assert controller._normal == original
    # A subsequent intentional change is persisted, on the new monitor.
    win.setGeometry(QFakeRect(35, 70, 1080, 610))
    app.aboutToQuit.emit()
    assert store.writes[-1]["screen"] == "right"
    assert (store.writes[-1]["x"], store.writes[-1]["width"]) == (35, 1080)


def test_native_resize_before_workarea_signal_preserves_preferred_geometry():
    screen = Screen("primary", QFakeRect(0, 0, 1920, 1040))
    app, win, store = App([screen]), Window(screen), Prefs(_saved())
    controller = AdaptiveWindowGeometry(app, win, store)
    controller.install()
    original = controller._normal
    screen.area = QFakeRect(0, 0, 900, 500)
    win.setGeometry(QFakeRect(20, 60, 840, 380))
    screen.availableGeometryChanged.emit()
    app.aboutToQuit.emit()
    assert not store.writes
    assert controller._normal == original
