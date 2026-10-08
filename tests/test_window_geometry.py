"""Focused Qt-DIP calculations; no desktop environment required."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from market_vault.desktop.window_geometry import (
    Frame,
    Rect,
    is_valid_saved_window,
    select_screen,
    window_plan,
)


def _saved(**replacements):
    result = {"x": 0, "y": 0, "width": 1280, "height": 740, "maximized": False, "screen": "left"}
    result.update(replacements)
    return result


@pytest.mark.parametrize(
    "area,expected_size",
    [
        (Rect(0, 0, 1920, 1040), (1440, 900)),
        (Rect(0, 0, 1280, 680), (1264, 628)),
        (Rect(0, 0, 1366, 728), (1350, 676)),
        (Rect(0, 0, 1024, 600), (1008, 548)),
        (Rect(-1280, 40, 800, 500), (784, 448)),
        (Rect(0, 0, 550, 260), (534, 208)),
    ],
)
def test_default_window_fits_workarea_with_native_frame(area, expected_size):
    frame = Frame(8, 44, 8, 8)
    got = window_plan(area, frame=frame)
    assert (got.geometry.width, got.geometry.height) == expected_size
    assert area.x <= got.geometry.x - frame.left
    assert area.y <= got.geometry.y - frame.top
    assert got.geometry.right + frame.right <= area.right
    assert got.geometry.bottom + frame.bottom <= area.bottom
    assert got.minimum_width <= got.geometry.width
    assert got.minimum_height <= got.geometry.height


def test_saves_user_normal_window_if_it_fits():
    area = Rect(-1800, 100, 1800, 1000)
    saved = _saved(x=-1500, y=200, width=1200, height=720)
    got = window_plan(area, saved=saved, frame=Frame(8, 36, 8, 8))
    assert got.geometry == Rect(-1500, 200, 1200, 720)


def test_old_monitor_location_recenters_and_does_not_reuse_physical_gap():
    area = Rect(0, 0, 1400, 800)
    saved = _saved(x=-3500, y=200, width=1100, height=700)
    got = window_plan(area, saved=saved, frame=Frame(8, 40, 8, 8))
    assert got.geometry.x >= 8
    assert got.geometry.y >= 40
    assert got.geometry.width == 1100
    assert got.geometry.height == 700


def test_restored_partly_offscreen_is_clamped_without_resizing_if_possible():
    area = Rect(300, -200, 1200, 800)
    saved = _saved(x=1400, y=-500, width=1030, height=600)
    got = window_plan(area, saved=saved, frame=Frame(8, 40, 8, 8))
    assert got.geometry.x == 1500 - 8 - 1030
    assert got.geometry.y == -200 + 40
    assert got.geometry.width == 1030
    assert got.geometry.height == 600


@pytest.mark.parametrize(
    "bad",
    [
        {"x": 0, "y": 0, "width": True, "height": 700},
        {"x": "0", "y": 0, "width": 1100, "height": 700},
        {"x": 0, "y": 0, "width": -1, "height": 700},
        _saved(screen=999),
        _saved(maximized=1),
        _saved(width=2**31),
        _saved(x=2**31),
    ],
)
def test_invalid_window_preferences_do_not_change_defaults(bad):
    assert not is_valid_saved_window(bad)
    assert window_plan(Rect(0, 0, 1920, 1080), saved=bad).geometry.width == 1440


def test_invalid_screen_or_frame_rejected():
    with pytest.raises(ValueError, match="screen work area"):
        window_plan(Rect(0, 0, 0, 400))
    with pytest.raises(ValueError, match="frame insets"):
        window_plan(Rect(0, 0, 1000, 400), frame=Frame(-1, 10, 0, 0))


@dataclass
class FakeQRect:
    _x: int
    _y: int
    _w: int
    _h: int

    def x(self): return self._x
    def y(self): return self._y
    def width(self): return self._w
    def height(self): return self._h


@dataclass
class FakeScreen:
    label: str
    area: FakeQRect

    def name(self): return self.label
    def availableGeometry(self): return self.area


def test_screen_picker_keeps_monitor_geometry_islands_separate():
    left = FakeScreen("left", FakeQRect(-1800, 0, 1800, 900))
    right = FakeScreen("right", FakeQRect(0, 0, 1200, 660))
    assert select_screen([left, right], _saved(x=-900, y=100, width=700), right) is left
    assert select_screen([left, right], _saved(screen="missing", x=300, y=120, width=850), left) is right
    assert select_screen([left, right], _saved(screen="missing", x=10_000, y=120), right) is right
