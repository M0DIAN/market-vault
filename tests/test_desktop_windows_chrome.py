from __future__ import annotations

import ctypes

import pytest

from market_vault.desktop import windows_chrome


class _Window:
    def __init__(self, handle: int = 1234) -> None:
        self.handle = handle

    def winId(self) -> int:
        return self.handle


def test_colorref_uses_win32_bgr_layout() -> None:
    assert windows_chrome.colorref("#15130F") == 0x0F1315
    assert windows_chrome.colorref("#F7E8B1") == 0xB1E8F7
    assert windows_chrome.colorref("#725318") == 0x185372
    with pytest.raises(ValueError, match="#RRGGBB"):
        windows_chrome.colorref("15130F")
    with pytest.raises(ValueError, match="#RRGGBB"):
        windows_chrome.colorref("#GG0000")


def test_documented_dwm_attribute_numbers_are_exact() -> None:
    assert windows_chrome.DWMWA_USE_IMMERSIVE_DARK_MODE == 20
    assert windows_chrome.DWMWA_BORDER_COLOR == 34
    assert windows_chrome.DWMWA_CAPTION_COLOR == 35
    assert windows_chrome.DWMWA_TEXT_COLOR == 36


def test_non_windows_is_a_noop() -> None:
    calls = []

    def setter(*args):
        calls.append(args)
        return 0

    assert not windows_chrome.apply_native_caption(
        _Window(), platform="linux", setter=setter
    )
    assert calls == []


def test_successful_caption_application_uses_exact_sequence_and_values() -> None:
    calls = []

    def setter(hwnd, attribute, pointer, size):
        value = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value
        calls.append((hwnd.value, attribute, value, size))
        return 0

    assert windows_chrome.apply_native_caption(
        _Window(), platform="win32", setter=setter
    )
    assert calls == [
        (1234, 20, 1, 4),
        (1234, 35, 0x0F1315, 4),
        (1234, 36, 0xB1E8F7, 4),
        (1234, 34, 0x185372, 4),
    ]


def test_dwm_failure_is_contained_and_supported_attributes_are_still_attempted() -> None:
    attempted = []

    def setter(hwnd, attribute, pointer, size):
        attempted.append(attribute)
        if attribute == windows_chrome.DWMWA_CAPTION_COLOR:
            raise OSError("unsupported")
        return -1 if attribute == windows_chrome.DWMWA_TEXT_COLOR else 0

    assert not windows_chrome.apply_native_caption(
        _Window(), platform="win32", setter=setter
    )
    assert attempted == [20, 35, 36, 34]


def test_ctypes_argument_error_is_contained() -> None:
    def setter(*_args):
        raise ctypes.ArgumentError("unsupported signature")

    assert not windows_chrome.apply_native_caption(
        _Window(), platform="win32", setter=setter
    )


def test_missing_or_invalid_native_handle_fails_closed() -> None:
    assert not windows_chrome.apply_native_caption(_Window(0), platform="win32")

    class MissingHandle:
        pass

    assert not windows_chrome.apply_native_caption(MissingHandle(), platform="win32")
