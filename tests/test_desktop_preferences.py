from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_vault.desktop import preferences
from market_vault.desktop.preferences import (
    DESKTOP_PREFERENCE_SCHEMA,
    DesktopPreferenceStore,
)


@pytest.mark.parametrize(
    "contents",
    [
        None,
        "",
        "{not-json",
        json.dumps({"schema": "unknown", "language": "zh-CN"}),
        json.dumps({"schema": DESKTOP_PREFERENCE_SCHEMA}),
        json.dumps({"schema": DESKTOP_PREFERENCE_SCHEMA, "language": "fr"}),
        json.dumps({"schema": DESKTOP_PREFERENCE_SCHEMA, "language": "ja"}),
    ],
)
def test_missing_or_invalid_preferences_fail_safely_to_english(tmp_path, contents):
    store = DesktopPreferenceStore(root=tmp_path)
    if contents is not None:
        store.path.write_text(contents, encoding="utf-8")

    assert store.load_language() == "en"


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_supported_language_save_and_load_uses_exact_schema(tmp_path, language):
    store = DesktopPreferenceStore(root=tmp_path)

    assert store.save_language(language) is True
    assert json.loads(store.path.read_text(encoding="utf-8")) == {
        "schema": DESKTOP_PREFERENCE_SCHEMA,
        "language": language,
    }
    assert store.load_language() == language


def test_latest_supported_language_wins_and_unsupported_save_is_rejected(tmp_path):
    store = DesktopPreferenceStore(root=tmp_path)

    assert store.save_language("zh-CN") is True
    original = store.path.read_bytes()
    assert store.save_language("ja") is False
    assert store.path.read_bytes() == original
    assert store.save_language("en") is True
    assert store.load_language() == "en"


def test_constructing_store_and_loading_do_not_create_preference_file(tmp_path):
    store = DesktopPreferenceStore(root=tmp_path / "isolated")

    assert store.load_language() == "en"
    assert store.path.exists() is False
    assert store.path.parent.exists() is False


def test_injected_root_is_cwd_independent_and_isolated(monkeypatch, tmp_path):
    root = tmp_path / "preference root"
    unrelated = tmp_path / "unrelated cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    store = DesktopPreferenceStore(root=root)
    assert store.path == root / "desktop-preferences.json"
    assert store.save_language("zh-CN") is True
    assert not list(unrelated.iterdir())


def test_default_windows_path_uses_localappdata(monkeypatch, tmp_path):
    local_appdata = tmp_path / "Local App Data"
    monkeypatch.setattr(preferences.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    assert preferences.default_desktop_preference_path() == (
        local_appdata / "MarketVault" / "desktop-preferences.json"
    )


def test_non_windows_fallback_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setattr(preferences.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    assert preferences.default_desktop_preference_path() == (
        tmp_path / "home" / ".config" / "market-vault" / "desktop-preferences.json"
    )


def test_explicit_path_and_root_are_mutually_exclusive(tmp_path):
    with pytest.raises(ValueError, match="either preference root or path"):
        DesktopPreferenceStore(root=tmp_path, path=tmp_path / "preferences.json")


def test_atomic_save_disables_direct_fallback_and_failed_commit_retains_bytes(tmp_path):
    path = tmp_path / "desktop-preferences.json"
    path.write_text(
        json.dumps({"schema": DESKTOP_PREFERENCE_SCHEMA, "language": "en"}),
        encoding="utf-8",
    )
    original = path.read_bytes()

    class FailingSaveFile:
        def __init__(self, destination):
            assert destination == str(path)
            self.direct_fallback = None
            self.cancelled = False

        def setDirectWriteFallback(self, enabled):
            self.direct_fallback = enabled
            assert enabled is False

        def open(self, mode):
            return True

        def write(self, data):
            return len(data)

        def commit(self):
            return False

        def cancelWriting(self):
            self.cancelled = True

    created = []

    def factory(destination):
        item = FailingSaveFile(destination)
        created.append(item)
        return item

    store = DesktopPreferenceStore(path=path, save_file_factory=factory)
    assert store.save_language("zh-CN") is False
    assert path.read_bytes() == original
    assert created[0].direct_fallback is False
    assert created[0].cancelled is True


def test_successful_atomic_save_leaves_no_temporary_residue(tmp_path):
    store = DesktopPreferenceStore(root=tmp_path)
    assert store.save_language("zh-CN") is True
    assert [path.name for path in tmp_path.iterdir()] == ["desktop-preferences.json"]
