from __future__ import annotations

import inspect
from types import SimpleNamespace

from market_vault.console.i18n import LANGUAGE_NAMES, LocalizationBindings, Translator
from market_vault.console.models import DashboardSnapshot, TablePage
from market_vault.console.shell import (
    HOME_METRICS,
    NAVIGATION_GROUPS,
    PAGE_TAB_KEYS,
    HomeState,
    PageId,
    dashboard_home_state,
)
from market_vault.console.ui import (
    ActivityIndicator,
    APP_BG,
    CARD_BG,
    CARD_BORDER,
    CARD_HIGHLIGHT,
    ERROR,
    GOLD,
    GOLD_DARK,
    GOLD_SOFT,
    HEADER_BG,
    HOME_METRIC_COLUMNS,
    NAV_HOVER,
    NAV_SELECTED,
    SIDEBAR_BG,
    STATUS_BG,
    TABLE_ALT_BG,
    TABLE_BG,
    TABLE_HEADER_BG,
    TABLE_HEADER_TEXT,
    TABLE_ROWHEIGHT,
    TABLE_SELECTION_BG,
    TABLE_SELECTION_TEXT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    WORKSPACE_BG,
    ConsoleApp,
    TableView,
    compact_settings_path,
    configure_table_styles,
)


class FakeWidget:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


class FakeNotebook:
    def __init__(self):
        self.selected = None

    def select(self, page=None):
        if page is not None:
            self.selected = page
        return self.selected


class FakeCanvas:
    def __init__(self):
        self.coordinates = None
        self.options = {}

    def coords(self, _item, *coordinates):
        self.coordinates = coordinates

    def itemconfigure(self, _item, **options):
        self.options.update(options)


class FakeStyle:
    def __init__(self):
        self.configurations = {}
        self.mappings = {}

    def configure(self, name, **options):
        self.configurations.setdefault(name, {}).update(options)

    def map(self, name, **options):
        self.mappings.setdefault(name, {}).update(options)


class FakeTableTree:
    def __init__(self):
        self.options = {}
        self.headings = {}
        self.columns = {}
        self.items = []
        self.deleted = []
        self.selected = ()
        self.insert_count = 0

    def __setitem__(self, key, value):
        self.options[key] = value

    def get_children(self):
        return tuple(item[0] for item in self.items)

    def delete(self, *items):
        self.deleted.extend(items)
        self.items = []

    def heading(self, column, **options):
        self.headings.setdefault(column, {}).update(options)

    def column(self, column, **options):
        self.columns.setdefault(column, {}).update(options)

    def insert(self, parent, index, *, values, tags=()):
        item_id = f"item-{self.insert_count}"
        self.insert_count += 1
        self.items.append((item_id, parent, index, values, tags))
        return item_id

    def selection(self):
        return self.selected


class FakeInfoBinding:
    def __init__(self):
        self.key = None
        self.values = None

    def update(self, key=None, **values):
        self.key = key
        self.values = values


def make_table_view(localization: LocalizationBindings | None = None) -> TableView:
    localization = localization or LocalizationBindings(Translator("en"))
    view = TableView.__new__(TableView)
    view.localization = localization
    view.translator = localization.translator
    view.current_page = TablePage((), ())
    view._previous = None
    view._next = None
    view.tree = FakeTableTree()
    view.previous_button = FakeWidget()
    view.next_button = FakeWidget()
    view._info_binding = FakeInfoBinding()
    localization.on_refresh(view._refresh_headings)
    return view


def make_activity_indicator() -> tuple[ActivityIndicator, list[str], list[tuple[int, object]]]:
    indicator = object.__new__(ActivityIndicator)
    indicator.canvas = FakeCanvas()
    indicator._segment = "segment"
    indicator._width = 160
    indicator._height = 8
    indicator._segment_width = 34
    indicator._position = 0
    indicator._interval = 12
    indicator._after_job = None
    indicator._running = False
    cancelled = []
    scheduled = []

    def after(interval, callback):
        scheduled.append((interval, callback))
        return f"job-{len(scheduled)}"

    indicator.after = after
    indicator.after_cancel = cancelled.append
    return indicator, cancelled, scheduled


def make_navigation_app() -> ConsoleApp:
    app = ConsoleApp.__new__(ConsoleApp)
    app.notebook = FakeNotebook()
    app.pages = {page_id: object() for page_id in PageId}
    app.navigation_buttons = {page_id: FakeWidget() for page_id in PageId}
    app.navigation_indicators = {page_id: FakeWidget() for page_id in PageId}
    app.current_page_id = PageId.HOME
    return app


def snapshot(*, symbols: str, snapshots: str) -> DashboardSnapshot:
    metrics = {
        "Symbols": symbols,
        "Snapshots": snapshots,
        "Completed dates": "4",
        "Incomplete dates": "1",
        "Latest trade date": "2026-08-21",
        "Latest rows": "2400",
    }
    return DashboardSnapshot("SUCCESS", metrics, TablePage(("run_id",), (("run-1",),)))


def test_page_identities_and_navigation_order_are_stable():
    assert tuple(PageId) == (
        PageId.HOME,
        PageId.HISTORICAL_DATA,
        PageId.TRADING_CALENDAR,
        PageId.MARKET_DATA,
        PageId.INVENTORY,
        PageId.COVERAGE_AUDIT,
        PageId.INTRADAY_AUDIT,
        PageId.RUNS,
        PageId.STORAGE_CLEANUP,
    )
    assert tuple(item.page_id for group in NAVIGATION_GROUPS for item in group.items) == tuple(
        PageId
    )
    assert set(PAGE_TAB_KEYS) == set(PageId)


def test_every_navigation_item_selects_existing_page_without_rebuilding_pages():
    app = make_navigation_app()
    original_pages = dict(app.pages)

    for page_id in PageId:
        app.select_page(page_id)
        assert app.current_page_id == page_id
        assert app.notebook.selected is original_pages[page_id]
        assert app.navigation_buttons[page_id].options["background"] == NAV_SELECTED
        assert app.navigation_buttons[page_id].options["foreground"] == GOLD_DARK
        assert app.navigation_indicators[page_id].options["background"] == GOLD

    assert app.pages == original_pages
    assert all(app.pages[key] is value for key, value in original_pages.items())


def test_navigation_preserves_forms_tables_pagination_and_purge_preview_state():
    app = make_navigation_app()
    business_state = {
        "form_value": "US.SPY US.QQQ",
        "table_page": TablePage(("code",), (("US.SPY",),), page=3, total_rows=250),
        "purge_plan_id": "plan-123",
        "purge_confirmation": "PURGE plan-123",
        "purge_execute_enabled": True,
    }

    app.select_page(PageId.STORAGE_CLEANUP)
    app.select_page(PageId.HISTORICAL_DATA)
    app.select_page(PageId.MARKET_DATA)

    assert business_state["form_value"] == "US.SPY US.QQQ"
    assert business_state["table_page"].page == 3
    assert business_state["purge_plan_id"] == "plan-123"
    assert business_state["purge_confirmation"] == "PURGE plan-123"
    assert business_state["purge_execute_enabled"] is True


def test_language_switch_preserves_workspace_and_loaded_business_state():
    class Variable:
        def get(self):
            return "简体中文"

    app = make_navigation_app()
    app.select_page(PageId.STORAGE_CLEANUP)
    app.translator = Translator("en")
    app.localization = LocalizationBindings(app.translator)
    app.language_name = Variable()
    app.preference_store = SimpleNamespace(save_language=lambda locale: locale == "zh-CN")
    app._configure_fonts = lambda: None
    app.root = SimpleNamespace(update_idletasks=lambda: None)
    state = {
        "form": "US.SPY",
        "table": TablePage(("code",), (("US.SPY",),), page=2, total_rows=75),
        "purge_plan_id": "plan-123",
    }

    app._change_language()

    assert app.translator.locale == "zh-CN"
    assert app.current_page_id == PageId.STORAGE_CLEANUP
    assert app.notebook.selected is app.pages[PageId.STORAGE_CLEANUP]
    assert state["form"] == "US.SPY"
    assert state["table"].page == 2
    assert state["purge_plan_id"] == "plan-123"


def test_live_language_switch_refreshes_every_shell_home_binding_before_return():
    keys = (
        "header.subtitle",
        "header.local_mode",
        "header.settings_path",
        "navigation.groups.data",
        "navigation.groups.explore",
        "navigation.groups.quality",
        "navigation.groups.activity",
        "navigation.groups.advanced",
        "navigation.items.home",
        "home.title",
        "home.unloaded.body",
        "navigation.items.historical_data",
        "navigation.items.trading_calendar",
        "sections.recent_runs",
        "buttons.refresh",
        "empty.no_data",
    )

    class Variable:
        value = LANGUAGE_NAMES["en"]

        def get(self):
            return self.value

    rendered = {}
    saved = []
    flushes = []
    app = ConsoleApp.__new__(ConsoleApp)
    app.translator = Translator("en")
    app.localization = LocalizationBindings(app.translator)
    for key in keys:
        values = (
            {"settings_path": "C:/MarketVault/config/settings.yaml"}
            if key == "header.settings_path"
            else {}
        )
        app.localization.bind(
            lambda value, binding_key=key: rendered.__setitem__(binding_key, value),
            key,
            **values,
        )
    app.language_name = Variable()
    app.preference_store = SimpleNamespace(save_language=lambda locale: saved.append(locale))
    app._configure_fonts = lambda: None
    app.root = SimpleNamespace(update_idletasks=lambda: flushes.append(True))
    app.pages = {page_id: object() for page_id in PageId}
    original_pages = dict(app.pages)
    app.backend = SimpleNamespace()

    for locale in ("zh-CN", "ja", "en"):
        app.language_name.value = LANGUAGE_NAMES[locale]
        app._change_language()
        for key in keys:
            values = (
                {"settings_path": "C:/MarketVault/config/settings.yaml"}
                if key == "header.settings_path"
                else {}
            )
            assert rendered[key] == app.translator.t(key, **values)

    assert saved == ["zh-CN", "ja", "en"]
    assert len(flushes) == 3
    assert app.pages == original_pages
    assert all(app.pages[key] is value for key, value in original_pages.items())


def test_navigation_method_has_no_business_or_network_operation():
    source = inspect.getsource(ConsoleApp.select_page)
    forbidden = ("backend", "OpenD", "backfill", "purge_execute", "_submit")
    assert all(token not in source for token in forbidden)


def test_shell_uses_hidden_notebook_and_home_is_default():
    source = inspect.getsource(ConsoleApp._build_shell)
    assert 'style="Hidden.TNotebook"' in source
    assert "self.select_page(PageId.HOME)" in source
    assert source.index("self._build_navigation()") < source.index("self._configure_fonts()")
    assert "backend.dashboard" not in inspect.getsource(ConsoleApp.__init__)
    assert "_refresh_dashboard()" not in inspect.getsource(ConsoleApp._build_dashboard)


def test_root_grid_reserves_status_bar_at_minimum_geometry():
    init_source = inspect.getsource(ConsoleApp.__init__)
    header_source = inspect.getsource(ConsoleApp._build_header)
    shell_source = inspect.getsource(ConsoleApp._build_shell)
    status_source = inspect.getsource(ConsoleApp._build_status_bar)

    assert 'root.geometry("1280x820")' in init_source
    assert 'root.minsize(1100, 700)' in init_source
    assert "root.rowconfigure(1, weight=1)" in init_source
    assert "header.grid(row=0, column=0" in header_source
    assert "shell.grid(row=1, column=0" in shell_source
    assert "bar.grid(row=2, column=0" in status_source


def test_custom_activity_indicator_is_idle_until_started_and_clears_on_stop():
    indicator, cancelled, scheduled = make_activity_indicator()

    indicator.stop()
    assert indicator.is_active is False
    assert indicator.canvas.coordinates == (0, 0, 0, 8)
    assert indicator.canvas.options["state"] == "hidden"

    indicator.start(12)
    assert indicator.is_active is True
    assert indicator.canvas.coordinates == (0, 0, 34, 8)
    assert indicator.canvas.options == {"state": "normal", "fill": GOLD}
    assert scheduled[0][0] == 12

    indicator.stop()
    assert indicator.is_active is False
    assert indicator.canvas.coordinates == (0, 0, 0, 8)
    assert indicator.canvas.options["state"] == "hidden"
    assert cancelled == ["job-1"]


def test_custom_activity_indicator_repeated_start_stop_is_callback_safe():
    indicator, cancelled, scheduled = make_activity_indicator()

    indicator.start(1)
    indicator.start(20)
    indicator.stop()
    indicator.stop()

    assert [interval for interval, _callback in scheduled] == [10, 20]
    assert cancelled == ["job-1", "job-2"]
    assert indicator.is_active is False
    assert indicator._after_job is None
    assert indicator.canvas.options["state"] == "hidden"


def test_completed_and_failed_paths_clear_activity_before_presenting_result():
    completed = inspect.getsource(ConsoleApp._poll_future)
    failed = inspect.getsource(ConsoleApp._finish_error)
    status_bar = inspect.getsource(ConsoleApp._build_status_bar)
    indicator = inspect.getsource(ActivityIndicator)

    assert completed.index("self.progress.stop()") < completed.index("future.result()")
    assert failed.index("self.progress.stop()") < failed.index(
        'self._set_status("status.failed"'
    )
    assert "ActivityIndicator(" in status_bar
    assert "ttk.Progressbar" not in status_bar
    assert "green" not in indicator.lower()
    assert ActivityIndicator.ACTIVE_COLOR == GOLD


def test_shared_table_style_uses_golden_archive_palette_and_density():
    style = FakeStyle()

    configure_table_styles(style, font_family="Segoe UI")

    tree = style.configurations["MarketVault.Treeview"]
    heading = style.configurations["MarketVault.Treeview.Heading"]
    selection = style.mappings["MarketVault.Treeview"]
    assert tree["background"] == TABLE_BG == CARD_BG
    assert tree["fieldbackground"] == TABLE_BG
    assert tree["foreground"] == TEXT_PRIMARY
    assert tree["rowheight"] == TABLE_ROWHEIGHT
    assert 28 <= TABLE_ROWHEIGHT <= 30
    assert heading["background"] == TABLE_HEADER_BG == GOLD_SOFT
    assert heading["foreground"] == TABLE_HEADER_TEXT == GOLD_DARK
    assert selection["background"] == [("selected", TABLE_SELECTION_BG)]
    assert selection["foreground"] == [("selected", TABLE_SELECTION_TEXT)]
    assert TABLE_SELECTION_BG == NAV_SELECTED
    assert TABLE_ALT_BG == "#F7F2E7"
    assert "#0078D7" not in inspect.getsource(configure_table_styles)


def test_table_page_preserves_data_order_pagination_and_callbacks_with_zebra_rows():
    view = make_table_view()
    calls = []
    rows = (("run-2", "SUCCESS"), ("run-1", "FAILED"), ("run-0", "WARN"))
    page = TablePage(
        ("run_id", "status"),
        rows,
        page=2,
        page_size=3,
        total_rows=8,
    )
    previous = lambda: calls.append("previous")
    next_ = lambda: calls.append("next")

    view.set_page(page, previous=previous, next_=next_)

    assert view.current_page is page
    assert view.tree.options["columns"] == page.columns
    assert tuple(item[3] for item in view.tree.items) == rows
    assert tuple(item[4] for item in view.tree.items) == (
        ("table-even",),
        ("table-odd",),
        ("table-even",),
    )
    assert page.columns == ("run_id", "status")
    assert page.rows == rows
    assert page.page == 2
    assert page.page_size == 3
    assert page.total_rows == 8
    assert view._info_binding.key == "pagination.info"
    assert view._info_binding.values == {
        "start": 4,
        "end": 6,
        "total": 8,
        "page": 2,
        "pages": 3,
    }
    assert view.previous_button.options["state"] == "normal"
    assert view.next_button.options["state"] == "normal"
    view._go_previous()
    view._go_next()
    assert calls == ["previous", "next"]

    view.set_page(page)
    assert view.previous_button.options["state"] == "disabled"
    assert view.next_button.options["state"] == "disabled"


def test_table_heading_localization_preserves_rows_page_and_selection():
    localization = LocalizationBindings(Translator("en"))
    view = make_table_view(localization)
    page = TablePage(
        ("run_id", "status"),
        (("run-1", "SUCCESS"), ("run-2", "FAILED")),
        page=3,
        page_size=2,
        total_rows=6,
    )
    view.set_page(page)
    view.tree.selected = ("item-1",)
    original_items = tuple(view.tree.items)
    original_insert_count = view.tree.insert_count
    expected = {
        "en": ("Run ID", "Status"),
        "zh-CN": ("运行 ID", "状态"),
        "ja": ("実行 ID", "ステータス"),
    }

    for locale in ("zh-CN", "ja", "en"):
        localization.set_locale(locale)
        assert tuple(view.tree.headings[column]["text"] for column in page.columns) == expected[
            locale
        ]
        assert tuple(view.tree.items) == original_items
        assert view.tree.insert_count == original_insert_count
        assert view.tree.selection() == ("item-1",)
        assert view.current_page is page
        assert view.current_page.page == 3


def test_tableview_is_presentation_only_and_uses_shared_styles():
    source = inspect.getsource(TableView)
    for forbidden in ("backend", "OpenD", "collect", "backfill", "purge", "DuckDB", "Parquet", "_submit"):
        assert forbidden not in source
    assert 'style="MarketVault.Treeview"' in source
    assert 'style="MarketVault.Vertical.TScrollbar"' in source
    assert 'style="MarketVault.Horizontal.TScrollbar"' in source
    assert "background=CARD_BORDER" in source
    assert 'padding=(8, 6, 6, 5)' in source


def test_settings_path_compaction_preserves_internal_value_and_path_components():
    deep_windows = (
        r"C:\Users\Example\Documents\MarketVault\feature\config\settings.yaml"
    )
    deep_unicode = r"C:\用户\市场仓库\config\settings.yaml"
    short_windows = r"config\settings.yaml"
    short_posix = "config/settings.yaml"

    app = ConsoleApp.__new__(ConsoleApp)
    app.settings_path = deep_windows

    assert compact_settings_path(app.settings_path) == r"…\config\settings.yaml"
    assert compact_settings_path(deep_unicode) == r"…\config\settings.yaml"
    assert compact_settings_path(short_windows) == short_windows
    assert compact_settings_path(short_posix) == short_posix
    assert compact_settings_path(deep_windows) == compact_settings_path(deep_windows)
    assert app.settings_path == deep_windows
    assert len(compact_settings_path(deep_windows)) < len(deep_windows)
    assert "compact_settings_path(self.settings_path)" in inspect.getsource(
        ConsoleApp._build_header
    )


def test_golden_archive_palette_is_exact_and_preserves_visual_hierarchy():
    assert {
        "APP_BG": APP_BG,
        "HEADER_BG": HEADER_BG,
        "SIDEBAR_BG": SIDEBAR_BG,
        "WORKSPACE_BG": WORKSPACE_BG,
        "CARD_BG": CARD_BG,
        "CARD_BORDER": CARD_BORDER,
        "CARD_HIGHLIGHT": CARD_HIGHLIGHT,
        "GOLD": GOLD,
        "GOLD_DARK": GOLD_DARK,
        "GOLD_SOFT": GOLD_SOFT,
        "TEXT_PRIMARY": TEXT_PRIMARY,
        "TEXT_SECONDARY": TEXT_SECONDARY,
        "NAV_HOVER": NAV_HOVER,
        "NAV_SELECTED": NAV_SELECTED,
        "STATUS_BG": STATUS_BG,
        "ERROR": ERROR,
        "WARNING": WARNING,
    } == {
        "APP_BG": "#EEEAE0",
        "HEADER_BG": "#F8F5ED",
        "SIDEBAR_BG": "#E5E0D4",
        "WORKSPACE_BG": "#F5F1E8",
        "CARD_BG": "#FBF8F0",
        "CARD_BORDER": "#C8B98F",
        "CARD_HIGHLIGHT": "#FFFDF7",
        "GOLD": "#B58A2A",
        "GOLD_DARK": "#80601B",
        "GOLD_SOFT": "#EEE6D2",
        "TEXT_PRIMARY": "#282722",
        "TEXT_SECONDARY": "#777166",
        "NAV_HOVER": "#ECE6D9",
        "NAV_SELECTED": "#F2E7C9",
        "STATUS_BG": "#E9E3D6",
        "ERROR": "#A4262C",
        "WARNING": "#8A3B00",
    }
    assert len({APP_BG, HEADER_BG, SIDEBAR_BG, WORKSPACE_BG, STATUS_BG}) == 5
    assert ERROR != WARNING != GOLD


def test_dashboard_state_uses_only_authoritative_symbol_and_snapshot_counts():
    assert dashboard_home_state(snapshot(symbols="0", snapshots="0")) == HomeState.EMPTY
    assert dashboard_home_state(snapshot(symbols="1", snapshots="0")) == HomeState.POPULATED
    assert dashboard_home_state(snapshot(symbols="0", snapshots="2")) == HomeState.POPULATED
    assert tuple(name for name, _key in HOME_METRICS) == (
        "Symbols",
        "Snapshots",
        "Completed dates",
        "Incomplete dates",
        "Latest trade date",
        "Latest rows",
    )


def test_home_metrics_use_six_hard_edge_cards_in_a_fixed_three_by_two_grid():
    source = inspect.getsource(ConsoleApp._build_dashboard)

    assert HOME_METRIC_COLUMNS == 3
    assert len(HOME_METRICS) == 6
    assert "row = index // HOME_METRIC_COLUMNS" in source
    assert "column = index % HOME_METRIC_COLUMNS" in source
    assert "self.metric_cards[name] = panel" in source
    assert "background=CARD_BORDER" in source
    assert "background=CARD_HIGHLIGHT" in source
    assert "background=GOLD_SOFT, height=1" in source
    assert "background=GOLD, width=3" in source
    assert "ttk.LabelFrame(self.dashboard_metrics" not in source


def test_visual_shell_builders_do_not_cross_business_operation_boundaries():
    presentation_methods = (
        ConsoleApp._configure_style,
        ConsoleApp._build_header,
        ConsoleApp._build_navigation,
        ConsoleApp._build_status_bar,
        ConsoleApp._home_button,
    )

    for method in presentation_methods:
        source = inspect.getsource(method)
        assert "backend." not in source
        assert "OpenD" not in source
        assert "_submit(" not in source
        assert "purge_execute" not in source


def test_home_buttons_have_explicit_primary_and_secondary_visual_boundaries():
    source = inspect.getsource(ConsoleApp._home_button)

    assert "background=GOLD_SOFT if primary else CARD_BG" in source
    assert "activebackground=NAV_SELECTED if primary else NAV_HOVER" in source
    assert "highlightbackground=GOLD if primary else CARD_BORDER" in source
    assert "highlightthickness=1" in source
    assert 'relief="flat"' in source


def test_dashboard_refresh_uses_existing_submit_path_and_preserves_exact_data():
    app = ConsoleApp.__new__(ConsoleApp)
    dashboard_operation = object()
    app.backend = SimpleNamespace(dashboard=dashboard_operation)
    app.metric_values = {
        name: SimpleNamespace(set=lambda value, name=name: values.__setitem__(name, value))
        for name, _key in HOME_METRICS
    }
    app.dashboard_runs = SimpleNamespace(set_page=lambda page: pages.append(page))
    app._set_home_state = lambda state: states.append(state)
    submissions = []
    values = {}
    pages = []
    states = []

    def submit(operation_key, operation, success):
        submissions.append((operation_key, operation))
        success(snapshot(symbols="3", snapshots="9"))

    app._submit = submit
    app._refresh_dashboard()

    assert submissions == [("operations.dashboard_refresh", dashboard_operation)]
    assert values == snapshot(symbols="3", snapshots="9").metrics
    assert pages == [snapshot(symbols="3", snapshots="9").recent_runs]
    assert states == [HomeState.POPULATED]


def test_home_copy_does_not_claim_unproven_health_or_completeness():
    source = inspect.getsource(ConsoleApp._build_dashboard)
    assert "100%" not in source
    assert "health" not in source.lower()
    assert "boundary" not in source.lower()
