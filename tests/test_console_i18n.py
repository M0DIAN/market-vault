from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_vault.console.i18n import (
    EN,
    JA,
    LANGUAGE_NAMES,
    TRANSLATIONS,
    ZH_CN,
    LocalizationBindings,
    Translator,
    choose_ui_font,
    translation_key_parity,
)
from market_vault.console.models import TablePage
from market_vault.console.preferences import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    UI_PREFERENCES_SCHEMA,
    UiPreferenceStore,
    resolve_ui_preferences_path,
)
from market_vault.console.ui import ConsoleApp


def write_preference(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_first_run_defaults_to_english(tmp_path):
    store = UiPreferenceStore(path=tmp_path / "ui-preferences.json")
    assert store.load_language() == DEFAULT_LOCALE == "en"


@pytest.mark.parametrize("language", SUPPORTED_LOCALES)
def test_saved_supported_language_loads(tmp_path, language):
    path = tmp_path / "ui-preferences.json"
    write_preference(path, {"schema": UI_PREFERENCES_SCHEMA, "language": language})
    assert UiPreferenceStore(path=path).load_language() == language


@pytest.mark.parametrize(
    "contents",
    (
        "",
        "{broken",
        json.dumps({"schema": "unknown", "language": "ja"}),
        json.dumps({"schema": UI_PREFERENCES_SCHEMA, "language": "fr"}),
        json.dumps([UI_PREFERENCES_SCHEMA, "ja"]),
    ),
)
def test_invalid_preferences_fall_back_to_english(tmp_path, contents):
    path = tmp_path / "ui-preferences.json"
    path.write_text(contents, encoding="utf-8")
    assert UiPreferenceStore(path=path).load_language() == "en"


def test_unreadable_preference_does_not_block_startup(tmp_path):
    path = tmp_path / "ui-preferences.json"
    path.mkdir()
    assert UiPreferenceStore(path=path).load_language() == "en"


def test_windows_preference_path_uses_local_app_data():
    path = resolve_ui_preferences_path(
        environ={"LOCALAPPDATA": r"C:\Users\Tester\AppData\Local"},
        platform="win32",
        home=Path(r"C:\Users\Tester"),
    )
    assert path == Path(r"C:\Users\Tester\AppData\Local") / "MarketVault" / "ui-preferences.json"


def test_missing_windows_local_app_data_has_deterministic_fallback():
    path = resolve_ui_preferences_path(
        environ={}, platform="win32", home=Path(r"C:\Users\Tester")
    )
    assert path == Path(r"C:\Users\Tester") / "AppData" / "Local" / "MarketVault" / "ui-preferences.json"


def test_non_windows_preference_path_uses_xdg_then_home():
    assert resolve_ui_preferences_path(
        environ={"XDG_CONFIG_HOME": "/tmp/config"},
        platform="linux",
        home=Path("/home/tester"),
    ) == Path("/tmp/config/market-vault/ui-preferences.json")
    assert resolve_ui_preferences_path(
        environ={}, platform="linux", home=Path("/home/tester")
    ) == Path("/home/tester/.config/market-vault/ui-preferences.json")


def test_injected_preference_root_never_uses_real_user_directory(tmp_path):
    path = resolve_ui_preferences_path(root=tmp_path / "isolated")
    assert path == (tmp_path / "isolated" / "ui-preferences.json").resolve()


def test_save_creates_exact_schema_and_latest_language_wins(tmp_path):
    path = tmp_path / "preferences" / "ui-preferences.json"
    store = UiPreferenceStore(path=path)
    assert store.save_language("zh-CN") is True
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema": UI_PREFERENCES_SCHEMA,
        "language": "zh-CN",
    }
    assert store.load_language() == "zh-CN"

    assert store.save_language("ja") is True
    assert store.load_language() == "ja"
    assert json.loads(path.read_text(encoding="utf-8"))["language"] == "ja"

    assert store.save_language("en") is True
    assert store.load_language() == "en"


def test_unsupported_language_is_not_saved(tmp_path):
    path = tmp_path / "ui-preferences.json"
    store = UiPreferenceStore(path=path)
    assert store.save_language("fr") is False
    assert not path.exists()


def test_translation_catalogs_have_exact_key_parity():
    assert tuple(TRANSLATIONS) == SUPPORTED_LOCALES
    assert set(EN) == set(ZH_CN) == set(JA)
    assert translation_key_parity() is True
    assert all(value.strip() for catalog in TRANSLATIONS.values() for value in catalog.values())


def test_native_language_names_and_representative_page_translations():
    assert LANGUAGE_NAMES == {"en": "English", "zh-CN": "简体中文", "ja": "日本語"}
    expected = {
        "tabs.dashboard": ("Home", "首页", "ホーム"),
        "tabs.explorer": ("Data Explorer", "数据浏览", "データエクスプローラー"),
        "tabs.inventory": ("Inventory", "数据清单", "インベントリ"),
        "tabs.coverage": ("Coverage Audit", "覆盖审计", "カバレッジ監査"),
        "tabs.intraday": ("Intraday Audit", "盘中审计", "日中監査"),
        "tabs.calendar": ("Trading Calendar", "交易日历", "取引カレンダー"),
        "tabs.backfill": ("Backfill", "历史数据回填", "履歴データ補完"),
        "tabs.purge": ("Storage / Purge", "存储 / 清理", "ストレージ / パージ"),
        "tabs.runs": ("Runs", "运行记录", "実行履歴"),
    }
    for key, values in expected.items():
        assert tuple(Translator(locale).t(key) for locale in SUPPORTED_LOCALES) == values


def test_shell_and_home_translations_cover_all_three_locales():
    expected = {
        "header.subtitle": (
            "Local Market Data Vault",
            "本地市场数据仓库",
            "ローカル市場データ保管庫",
        ),
        "navigation.groups.data": ("DATA", "数据", "データ"),
        "navigation.groups.explore": ("EXPLORE", "浏览", "閲覧"),
        "navigation.groups.quality": ("QUALITY", "质量检查", "品質チェック"),
        "navigation.groups.activity": ("ACTIVITY", "运行", "実行"),
        "navigation.groups.advanced": ("ADVANCED", "高级管理", "詳細管理"),
        "navigation.items.home": ("Home", "首页", "ホーム"),
        "navigation.items.historical_data": ("Historical Data", "历史数据", "履歴データ"),
        "navigation.items.trading_calendar": ("Trading Calendar", "交易日历", "取引カレンダー"),
        "navigation.items.market_data": ("Market Data", "行情数据", "市場データ"),
        "navigation.items.inventory": ("Inventory", "数据库存", "インベントリ"),
        "navigation.items.coverage_audit": ("Coverage Audit", "覆盖检查", "カバレッジ監査"),
        "navigation.items.intraday_audit": ("Intraday Audit", "分钟数据检查", "日中データ監査"),
        "navigation.items.runs": ("Runs", "运行记录", "実行履歴"),
        "navigation.items.storage_cleanup": (
            "Storage & Cleanup",
            "存储与清理",
            "ストレージとクリーンアップ",
        ),
        "home.title": ("Local data overview", "本地数据概览", "ローカルデータ概要"),
    }
    for key, values in expected.items():
        assert tuple(Translator(locale).t(key) for locale in SUPPORTED_LOCALES) == values


def test_unknown_locale_and_missing_key_fail_safely_to_english():
    translator = Translator("fr")
    assert translator.locale == "en"
    assert translator.t("buttons.refresh") == "Refresh"
    assert translator.t("missing.key") == "missing.key"
    assert translator.t("pagination.info") == EN["pagination.info"]


def test_live_language_switch_refreshes_registered_text_without_state_reset():
    translator = Translator("en")
    bindings = LocalizationBindings(translator)
    presentation = {}
    bindings.bind(
        lambda value: presentation.__setitem__("tab", value), "tabs.explorer"
    )
    status = bindings.bind(
        lambda value: presentation.__setitem__("status", value),
        "status.running",
        operation=translator.t("operations.inventory"),
    )
    business_state = {
        "selected_tab": "explorer",
        "field_value": " US.SPY ",
        "table_page": TablePage(("code",), (("US.SPY",),), page=3, page_size=50, total_rows=151),
    }

    assert presentation["tab"] == "Data Explorer"
    bindings.set_locale("zh-CN")
    status.update("status.running", operation=translator.t("operations.inventory"))
    assert presentation == {"tab": "数据浏览", "status": "正在运行：数据清单"}

    bindings.set_locale("ja")
    status.update("status.running", operation=translator.t("operations.inventory"))
    assert presentation == {"tab": "データエクスプローラー", "status": "実行中：インベントリ"}

    bindings.set_locale("en")
    status.update("status.running", operation=translator.t("operations.inventory"))
    assert presentation == {"tab": "Data Explorer", "status": "Running: Inventory"}
    assert business_state["selected_tab"] == "explorer"
    assert business_state["field_value"] == " US.SPY "
    assert business_state["table_page"].page == 3
    assert business_state["table_page"].rows == (("US.SPY",),)


def test_console_language_handler_persists_and_only_refreshes_presentation():
    class Variable:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    class Store:
        def __init__(self):
            self.saved = []

        def save_language(self, locale):
            self.saved.append(locale)
            return True

    class Root:
        def update_idletasks(self):
            presentation["idle_flushed"] = True

    translator = Translator("en")
    presentation = {}
    app = ConsoleApp.__new__(ConsoleApp)
    app.translator = translator
    app.localization = LocalizationBindings(translator)
    app.localization.bind(
        lambda value: presentation.__setitem__("tab", value), "tabs.backfill"
    )
    app.language_name = Variable("简体中文")
    app.preference_store = Store()
    app._configure_fonts = lambda: presentation.__setitem__("font_refreshed", True)
    app.root = Root()
    business_state = {
        "selected_tab": 6,
        "form_value": "US.SPY US.QQQ",
        "page": TablePage(("code",), (("US.SPY",),), page=2, page_size=50, total_rows=80),
    }

    app._change_language()

    assert translator.locale == "zh-CN"
    assert app.preference_store.saved == ["zh-CN"]
    assert presentation == {
        "tab": "历史数据回填",
        "font_refreshed": True,
        "idle_flushed": True,
    }
    assert business_state["selected_tab"] == 6
    assert business_state["form_value"] == "US.SPY US.QQQ"
    assert business_state["page"].page == 2


def test_locale_font_selection_uses_cjk_fonts_and_safe_fallback():
    available = {"Segoe UI", "Microsoft YaHei UI", "Yu Gothic UI"}
    assert choose_ui_font("en", available) == "Segoe UI"
    assert choose_ui_font("zh-CN", available) == "Microsoft YaHei UI"
    assert choose_ui_font("ja", available) == "Yu Gothic UI"
    assert choose_ui_font("zh-CN", {"Segoe UI"}) == "Segoe UI"
    assert choose_ui_font("ja", set()) == "TkDefaultFont"
