"""Existing v1 language preferences and window geometry must not overwrite one another."""

import json

from market_vault.desktop.preferences import DesktopPreferenceStore, DESKTOP_PREFERENCE_SCHEMA


class FakeSaveFile:
    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path)
        self.data = b""

    def setDirectWriteFallback(self, enabled):
        assert enabled is False

    def open(self, _mode):
        return True

    def write(self, value):
        self.data = bytes(value)
        return len(self.data)

    def commit(self):
        self.path.write_bytes(self.data)
        return True

    def cancelWriting(self):
        raise AssertionError("unexpected cancel")


def _state():
    return {"x": -100, "y": 60, "width": 1280, "height": 740, "maximized": True, "screen": "display0"}


def test_window_save_and_language_change_preserve_both_values(tmp_path):
    store = DesktopPreferenceStore(root=tmp_path, save_file_factory=FakeSaveFile)
    assert store.load_window() is None
    assert store.load_language() == "en"
    assert store.save_language("zh-CN")
    assert store.save_window(_state())
    assert store.load_window() == _state()
    assert store.save_language("en")
    assert store.load_language() == "en"
    assert store.load_window() == _state()
    assert store.save_window({**_state(), "width": 1400, "maximized": False})
    assert store.load_language() == "en"
    assert store.load_window()["width"] == 1400
    assert json.loads(store.path.read_text())["schema"] == DESKTOP_PREFERENCE_SCHEMA


def test_legacy_language_only_file_and_invalid_geometry_recover_without_crash(tmp_path):
    store = DesktopPreferenceStore(root=tmp_path, save_file_factory=FakeSaveFile)
    assert store.save_language("zh-CN")
    assert store.path.read_text() == '{\n  "schema": "market-vault-desktop-preferences-v1",\n  "language": "zh-CN"\n}\n'
    store.path.write_text(json.dumps({"schema": DESKTOP_PREFERENCE_SCHEMA,
                                      "language": "zh-CN", "window": {**_state(), "width": False}}))
    assert store.load_window() is None
    assert store.load_language() == "zh-CN"
    assert store.save_language("en")
    assert "window" not in json.loads(store.path.read_text())


def test_invalid_geometry_write_cannot_overwrite_existing_preferences(tmp_path):
    store = DesktopPreferenceStore(root=tmp_path, save_file_factory=FakeSaveFile)
    assert store.save_language("en")
    previous = store.path.read_bytes()
    assert not store.save_window({**_state(), "height": True})
    assert store.path.read_bytes() == previous
