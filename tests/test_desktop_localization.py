from __future__ import annotations

import json

import pytest


pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication

from market_vault.desktop.localization import (
    EN,
    TRANSLATIONS,
    ZH_CN,
    I18nBridge,
    translation_keys_match,
)
from market_vault.desktop.preferences import (
    DESKTOP_PREFERENCE_SCHEMA,
    DesktopPreferenceStore,
    SUPPORTED_LANGUAGES,
)


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_qml_language_contract_is_exactly_bilingual():
    assert SUPPORTED_LANGUAGES == ("zh-CN", "en")
    assert tuple(TRANSLATIONS) == ("en", "zh-CN")
    assert "ja" not in TRANSLATIONS


def test_translation_catalogs_have_exact_key_parity_and_representative_strings():
    assert translation_keys_match() is True
    assert set(EN) == set(ZH_CN)
    assert EN["nav.home"] == "Home"
    assert ZH_CN["nav.home"] == "首页"
    assert EN["home.recent_runs"] == "Recent Runs"
    assert ZH_CN["columns.run_id"] == "运行 ID"
    assert EN["historical.execute"] == "Execute via OpenD"
    assert ZH_CN["storage.execute"] == "执行安全清理"
    assert EN["field.cleanup_policy"] == "Cleanup policy"
    assert EN["storage.policy.exact_scope"] == "Exact Scope"
    assert EN["storage.policy.superseded_only"] == "Superseded Only"
    assert ZH_CN["field.cleanup_policy"] == "清理策略"
    assert ZH_CN["storage.policy.exact_scope"] == "精确范围清理"
    assert ZH_CN["storage.policy.superseded_only"] == "仅清理旧快照"
    assert EN["common.close_busy"].startswith("An operation")


def test_bridge_defaults_to_english_without_startup_write(qt_app, tmp_path):
    store = DesktopPreferenceStore(root=tmp_path / "preferences")
    bridge = I18nBridge(preference_store=store)

    assert bridge.language == "en"
    assert bridge.catalog == EN
    assert store.path.exists() is False


def test_live_language_change_emits_once_and_persists(qt_app, tmp_path):
    store = DesktopPreferenceStore(root=tmp_path)
    bridge = I18nBridge(preference_store=store)
    changes = []
    bridge.languageChanged.connect(lambda: changes.append(bridge.language))

    assert bridge.setLanguage("zh-CN") is True
    assert bridge.language == "zh-CN"
    assert bridge.catalog == ZH_CN
    assert changes == ["zh-CN"]
    assert json.loads(store.path.read_text(encoding="utf-8")) == {
        "schema": DESKTOP_PREFERENCE_SCHEMA,
        "language": "zh-CN",
    }

    assert bridge.setLanguage("zh-CN") is True
    assert changes == ["zh-CN"]
    assert bridge.setLanguage("en") is True
    assert changes == ["zh-CN", "en"]


def test_language_persists_across_bridge_instances(qt_app, tmp_path):
    store = DesktopPreferenceStore(root=tmp_path)
    first = I18nBridge(preference_store=store)
    assert first.setLanguage("zh-CN") is True

    second = I18nBridge(preference_store=DesktopPreferenceStore(root=tmp_path))
    assert second.language == "zh-CN"
    assert second.setLanguage("en") is True

    third = I18nBridge(preference_store=DesktopPreferenceStore(root=tmp_path))
    assert third.language == "en"


def test_unsupported_language_and_unknown_key_fail_safely(qt_app, tmp_path):
    bridge = I18nBridge(preference_store=DesktopPreferenceStore(root=tmp_path))

    assert bridge.setLanguage("ja") is False
    assert bridge.language == "en"
    assert bridge.translate("missing.translation.key") == "missing.translation.key"
    assert bridge.columnLabel("unknown_backend_column") == "unknown_backend_column"


def test_persistence_failure_retains_live_language(qt_app):
    class FailingStore:
        def load_language(self):
            return "en"

        def save_language(self, language):
            assert language == "zh-CN"
            return False

    bridge = I18nBridge(preference_store=FailingStore())
    changes = []
    bridge.languageChanged.connect(lambda: changes.append(bridge.language))

    assert bridge.setLanguage("zh-CN") is False
    assert bridge.language == "en"
    assert bridge.catalog == EN
    assert changes == []


def test_status_and_operation_labels_are_bilingual(qt_app, tmp_path):
    bridge = I18nBridge(preference_store=DesktopPreferenceStore(root=tmp_path))
    assert bridge.statusLabel("UNREVIEWED") == "Not reviewed"
    assert bridge.operationLabel("storage_execute") == "Safe Purge execution"
    assert bridge.statusLabel("UNKNOWN_STATUS") == "UNKNOWN_STATUS"
    assert bridge.setLanguage("zh-CN") is True
    assert bridge.statusLabel("UNREVIEWED") == "尚未检查"
    assert bridge.operationLabel("storage_execute") == "执行安全清理"


def test_available_languages_are_exact_native_labels(qt_app, tmp_path):
    bridge = I18nBridge(preference_store=DesktopPreferenceStore(root=tmp_path))

    assert bridge.availableLanguages == [
        {"code": "zh-CN", "label": "中文"},
        {"code": "en", "label": "English"},
    ]
