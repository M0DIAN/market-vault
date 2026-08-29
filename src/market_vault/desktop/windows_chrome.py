"""Best-effort native Windows caption styling for the QML desktop."""

from __future__ import annotations

import ctypes
import sys
from typing import Callable, Protocol


DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

CAPTION_COLOR = "#15130F"
TEXT_COLOR = "#F7E8B1"
BORDER_COLOR = "#725318"


class NativeWindow(Protocol):
    def winId(self) -> int: ...


DwmSetter = Callable[[object, int, object, int], int]


def colorref(hex_color: str) -> int:
    """Convert ``#RRGGBB`` to the Win32 ``0x00BBGGRR`` COLORREF form."""

    if len(hex_color) != 7 or not hex_color.startswith("#"):
        raise ValueError("color must use #RRGGBB form")
    try:
        red = int(hex_color[1:3], 16)
        green = int(hex_color[3:5], 16)
        blue = int(hex_color[5:7], 16)
    except ValueError as exc:
        raise ValueError("color must use #RRGGBB form") from exc
    return red | (green << 8) | (blue << 16)


def _load_dwm_setter() -> DwmSetter:
    dwmapi = ctypes.WinDLL("dwmapi")
    setter = dwmapi.DwmSetWindowAttribute
    setter.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_uint,
    )
    setter.restype = ctypes.c_long
    return setter


def apply_native_caption(
    window: NativeWindow,
    *,
    platform: str | None = None,
    setter: DwmSetter | None = None,
) -> bool:
    """Apply the MarketVault DWM caption palette without owning window behavior."""

    if (sys.platform if platform is None else platform) != "win32":
        return False
    try:
        hwnd = int(window.winId())
        if hwnd == 0:
            return False
        dwm_setter = setter or _load_dwm_setter()
    except (AttributeError, OSError, TypeError, ValueError):
        return False

    attributes = (
        (DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.c_int(1)),
        (DWMWA_CAPTION_COLOR, ctypes.c_uint32(colorref(CAPTION_COLOR))),
        (DWMWA_TEXT_COLOR, ctypes.c_uint32(colorref(TEXT_COLOR))),
        (DWMWA_BORDER_COLOR, ctypes.c_uint32(colorref(BORDER_COLOR))),
    )
    applied = True
    for attribute, value in attributes:
        try:
            result = dwm_setter(
                ctypes.c_void_p(hwnd),
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except (ctypes.ArgumentError, OSError, TypeError, ValueError):
            applied = False
            continue
        if result != 0:
            applied = False
    return applied
