"""Qt-logical desktop window placement and narrowly scoped screen-change handling.

The geometry functions are intentionally free of Qt imports so they can be
checked without a Windows desktop or the optional PySide6 dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


DESIGN_WIDTH = 1440
DESIGN_HEIGHT = 900
NORMAL_MIN_WIDTH = 1024
NORMAL_MIN_HEIGHT = 600
# Below the normal design target these are *preferred* floors, not hard limits.
SMALL_WIDTH = 640
SMALL_HEIGHT = 360


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def intersection_area(self, other: Rect) -> int:
        return max(0, min(self.right, other.right) - max(self.x, other.x)) * max(
            0, min(self.bottom, other.bottom) - max(self.y, other.y)
        )


@dataclass(frozen=True)
class Frame:
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    @property
    def horizontal(self) -> int:
        return self.left + self.right

    @property
    def vertical(self) -> int:
        return self.top + self.bottom


@dataclass(frozen=True)
class Placement:
    geometry: Rect  # QWindow geometry: client area, excluding native frame
    minimum_width: int
    minimum_height: int


def is_valid_saved_window(value: object) -> bool:
    """Accept only reasonable, typed, normal-window geometry in Qt DIPs."""
    if not isinstance(value, dict):
        return False
    required = ("x", "y", "width", "height")
    if any(type(value.get(key)) is not int for key in required):
        return False
    if not (-1_000_000 <= value["x"] <= 1_000_000):
        return False
    if not (-1_000_000 <= value["y"] <= 1_000_000):
        return False
    if not (1 <= value["width"] <= 32_768):
        return False
    if not (1 <= value["height"] <= 32_768):
        return False
    if type(value.get("maximized", False)) is not bool:
        return False
    if not isinstance(value.get("screen", ""), str):
        return False
    if len(value.get("screen", "")) > 256:
        return False
    return True


def window_plan(
    work_area: Rect,
    *,
    saved: Mapping[str, object] | None = None,
    frame: Frame = Frame(),
) -> Placement:
    """Fit an ordinary client rectangle within one Qt availableGeometry rect.

    The caller must use *logical* Qt coordinates throughout and supply frame
    insets reported by QWindow, not values independently multiplied by DPI.
    """
    if work_area.width < 1 or work_area.height < 1:
        raise ValueError("screen work area must be positive")
    if any(v < 0 for v in (frame.left, frame.top, frame.right, frame.bottom)):
        raise ValueError("frame insets must be nonnegative")

    max_width = max(1, work_area.width - frame.horizontal)
    max_height = max(1, work_area.height - frame.vertical)
    minimum_width = min(max_width, NORMAL_MIN_WIDTH if max_width >= NORMAL_MIN_WIDTH else SMALL_WIDTH)
    minimum_height = min(max_height, NORMAL_MIN_HEIGHT if max_height >= NORMAL_MIN_HEIGHT else SMALL_HEIGHT)

    if saved is not None and is_valid_saved_window(dict(saved)):
        preferred_width = int(saved["width"])
        preferred_height = int(saved["height"])
        preferred_x = int(saved["x"])
        preferred_y = int(saved["y"])
        saved_bounds = Rect(preferred_x, preferred_y, preferred_width, preferred_height)
        # A saved window from a removed monitor is centered on the selected
        # replacement monitor rather than restored into a screen gap.
        usable_saved_position = saved_bounds.intersection_area(work_area) > 0
    else:
        preferred_width, preferred_height = DESIGN_WIDTH, DESIGN_HEIGHT
        usable_saved_position = False
        preferred_x, preferred_y = 0, 0

    width = min(max(preferred_width, minimum_width), max_width)
    height = min(max(preferred_height, minimum_height), max_height)
    min_x = work_area.x + frame.left
    min_y = work_area.y + frame.top
    max_x = work_area.right - frame.right - width
    max_y = work_area.bottom - frame.bottom - height
    if usable_saved_position:
        x = min(max(preferred_x, min_x), max_x)
        y = min(max(preferred_y, min_y), max_y)
    else:
        x = min_x + (max_x - min_x) // 2
        y = min_y + (max_y - min_y) // 2
    return Placement(Rect(x, y, width, height), minimum_width, minimum_height)


def select_screen(screens, saved: Mapping[str, object] | None, primary):
    """Choose a Qt QScreen by name *and* position, without uniting DPI islands."""
    if not screens:
        raise ValueError("at least one screen is required")
    if saved is not None and is_valid_saved_window(dict(saved)):
        original = Rect(
            int(saved["x"]), int(saved["y"]),
            int(saved["width"]), int(saved["height"]),
        )
        preferred_name = saved.get("screen", "")
        # Multiple monitors may share the same name: use actual overlap first.
        named = [screen for screen in screens if screen.name() == preferred_name]
        matching = [
            (original.intersection_area(qt_rect(screen.availableGeometry())), screen)
            for screen in (named or screens)
        ]
        best = max(matching, key=lambda pair: pair[0])
        if best[0] > 0:
            return best[1]
        if len(named) == 1:
            return named[0]
    return primary if primary in screens else screens[0]


def qt_rect(rect) -> Rect:
    return Rect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))


def _qt_frame(window) -> Frame:
    margins = window.frameMargins()
    frame = Frame(
        max(0, int(margins.left())), max(0, int(margins.top())),
        max(0, int(margins.right())), max(0, int(margins.bottom())),
    )
    # Qt reports native frame margins in logical coordinates; do not invent
    # fixed physical or logical titlebar values. The post-show reconciliation
    # observes the real margins once the platform has established them.
    return frame


class AdaptiveWindowGeometry:
    """Bind the one existing QML window to Qt screen information/preferences."""

    def __init__(self, application, window, preference_store) -> None:
        from PySide6.QtCore import QTimer

        self.application = application
        self.window = window
        self.preferences = preference_store
        self._ready = False
        self._applying = False
        self._dirty = False
        self._normal: Rect | None = None
        self._was_maximized = False
        self._normal_screen = ""
        self._known_layout = self._layout_signature()
        self._topology_recovery = False
        self._recovery_geometry: Rect | None = None
        self._connected_screens: set[object] = set()
        self._timer = QTimer(window)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._save_if_dirty)

    def install(self) -> None:
        from PySide6.QtCore import QRect, QSize
        from PySide6.QtCore import Qt

        saved = self.preferences.load_window()
        screens = list(self.application.screens())
        screen = select_screen(screens, saved, self.application.primaryScreen())
        area = qt_rect(screen.availableGeometry())
        plan = window_plan(area, saved=saved, frame=_qt_frame(self.window))
        self._applying = True
        if self.window.screen() is not screen:
            self.window.setScreen(screen)
        self.window.setMinimumSize(QSize(plan.minimum_width, plan.minimum_height))
        self.window.setGeometry(QRect(
            plan.geometry.x, plan.geometry.y,
            plan.geometry.width, plan.geometry.height,
        ))
        self._normal = plan.geometry
        self._normal_screen = screen.name()
        self._was_maximized = bool(saved and saved.get("maximized") is True)
        if self._was_maximized:
            self.window.showMaximized()
        self._applying = False
        for key in ("xChanged", "yChanged", "widthChanged", "heightChanged"):
            getattr(self.window, key).connect(self._on_geometry_changed)
        self.window.windowStateChanged.connect(self._on_window_state_changed)
        self.window.screenChanged.connect(self._on_screen_change)
        self.application.screenRemoved.connect(self._on_screen_change)
        self._connect_screens()
        self.application.aboutToQuit.connect(self._save_if_dirty)
        self._ready = True
        self._on_screen_change()

    def _connect_screens(self) -> None:
        for screen in self.application.screens():
            if screen in self._connected_screens:
                continue
            screen.availableGeometryChanged.connect(self._on_screen_change)
            self._connected_screens.add(screen)

    def _layout_signature(self):
        return tuple(
            (id(screen), qt_rect(screen.availableGeometry()))
            for screen in self.application.screens()
        )

    def _notice_topology_change(self) -> bool:
        if self._layout_signature() != self._known_layout:
            self._topology_recovery = True
            self._dirty = False
            self._timer.stop()
        return self._topology_recovery

    def _normal_state(self) -> bool:
        from PySide6.QtCore import Qt
        state = self.window.windowStates()
        return not bool(state & (Qt.WindowMaximized | Qt.WindowMinimized | Qt.WindowFullScreen))

    def _on_geometry_changed(self, *_args) -> None:
        if not self._ready or self._applying or not self._normal_state():
            return
        if self._notice_topology_change():
            self._on_screen_change()
            return
        rect = qt_rect(self.window.geometry())
        if rect.width < 1 or rect.height < 1 or rect == self._recovery_geometry:
            return
        self._recovery_geometry = None
        self._normal = rect
        screen = self.window.screen()
        self._normal_screen = screen.name() if screen is not None else ""
        self._dirty = True
        self._timer.start()

    def _on_window_state_changed(self, *_args) -> None:
        if not self._ready or self._applying:
            return
        if self._notice_topology_change():
            self._on_screen_change()
            return
        from PySide6.QtCore import Qt
        state = self.window.windowStates()
        # Temporary minimized/fullscreen states must not erase how the user
        # last wanted the ordinary desktop window restored.
        if not bool(state & (Qt.WindowMinimized | Qt.WindowFullScreen)):
            self._was_maximized = bool(state & Qt.WindowMaximized)
        self._dirty = True
        self._timer.start()
        if self._normal_state():
            self._on_screen_change()

    def _on_screen_change(self, *_args) -> None:
        from PySide6.QtCore import QTimer
        if not self._ready:
            return
        self._notice_topology_change()
        # Screen notifications can fire mid-reparent/mid-resize. Coalesce into
        # the following UI turn, not every individual QWindow geometry signal.
        QTimer.singleShot(0, self._reconcile_screens)

    def _reconcile_screens(self) -> None:
        recovering = self._notice_topology_change()
        normal, normal_screen = self._normal, self._normal_screen
        self._known_layout = self._layout_signature()
        applying = self._applying
        self._applying = True
        try:
            self._apply_screen_geometry()
        finally:
            self._applying = applying
            if recovering:
                # A window-manager relocation is not a user's new preference,
                # including when its rectangle already fitted the new display.
                self._normal, self._normal_screen = normal, normal_screen
                self._dirty = False
                self._timer.stop()
                self._recovery_geometry = qt_rect(self.window.geometry())
            else:
                screen = self.window.screen()
                if self._normal == qt_rect(self.window.geometry()) and screen is not None:
                    self._normal_screen = screen.name()
            self._topology_recovery = False

    def _apply_screen_geometry(self) -> None:
        from PySide6.QtCore import QRect, QSize
        screens = list(self.application.screens())
        if not screens:
            return
        self._connect_screens()
        current_screen = self.window.screen()
        selected = current_screen if current_screen in screens else self.application.primaryScreen()
        if selected not in screens:
            selected = screens[0]
        area = qt_rect(selected.availableGeometry())
        frame = _qt_frame(self.window)
        current = qt_rect(self.window.geometry())
        # This is called only for a screen/work-area change, not every drag.
        # Check the complete native frame against the *selected* screen; do not
        # combine multiple DPI-discontinuous Qt screen rectangles.
        usable = Rect(
            current.x - frame.left, current.y - frame.top,
            current.width + frame.horizontal, current.height + frame.vertical,
        )
        visible = (area.x <= usable.x and area.y <= usable.y
                   and usable.right <= area.right and usable.bottom <= area.bottom)
        if not self._normal_state():
            # Keep the window-manager-owned geometry, but update its minimum
            # now: a stale minimum can exceed a newly smaller work area.
            limits = window_plan(area, frame=frame)
            applying = self._applying
            self._applying = True
            try:
                self.window.setMinimumSize(QSize(
                    limits.minimum_width, limits.minimum_height,
                ))
            finally:
                self._applying = applying
            return
        reference = {"x": current.x, "y": current.y, "width": current.width,
                     "height": current.height, "maximized": False, "screen": selected.name()}
        plan = window_plan(area, saved=reference, frame=frame)
        # A user dragging across screens may span both rectangles. Leave the
        # ordinary position alone when the native titlebar remains reachable.
        title = Rect(usable.x, usable.y,
                     min(200, usable.width), min(max(28, frame.top), usable.height))
        reachable = any(
            title.intersection_area(qt_rect(screen.availableGeometry()))
            >= min(80, title.width) * min(16, title.height)
            for screen in screens
        )
        fits_selected = (
            current.width <= max(1, area.width - frame.horizontal)
            and current.height <= max(1, area.height - frame.vertical)
        )
        spanning = sum(
            usable.intersection_area(qt_rect(screen.availableGeometry())) > 0
            for screen in screens
        ) >= 2
        if reachable and fits_selected and (visible or spanning):
            if (self.window.minimumSize().width() != plan.minimum_width
                    or self.window.minimumSize().height() != plan.minimum_height):
                self.window.setMinimumSize(QSize(plan.minimum_width, plan.minimum_height))
            return
        if (visible and current == plan.geometry
                and self.window.minimumSize().width() == plan.minimum_width
                and self.window.minimumSize().height() == plan.minimum_height):
            return
        self._applying = True
        self.window.setMinimumSize(QSize(plan.minimum_width, plan.minimum_height))
        if current != plan.geometry:
            self.window.setGeometry(QRect(plan.geometry.x, plan.geometry.y,
                                          plan.geometry.width, plan.geometry.height))
        self._applying = False
        self._normal = plan.geometry
        self._dirty = False
        self._timer.stop()
        # Screen-change recovery is temporary: a disconnected display should
        # not erase the user's previously chosen size on that display.

    def _save_if_dirty(self) -> None:
        if not self._dirty or self._normal is None:
            return
        self._dirty = False
        rect = self._normal
        saved = {
            "x": rect.x, "y": rect.y, "width": rect.width,
            "height": rect.height,
            "maximized": self._was_maximized,
            "screen": self._normal_screen,
        }
        if not self.preferences.save_window(saved):
            self._dirty = True
