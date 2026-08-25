from __future__ import annotations

import inspect
from types import SimpleNamespace

from market_vault.console.i18n import LocalizationBindings, Translator
from market_vault.console.models import DashboardSnapshot, TablePage
from market_vault.console.shell import (
    HOME_METRICS,
    NAVIGATION_GROUPS,
    PAGE_TAB_KEYS,
    HomeState,
    PageId,
    dashboard_home_state,
)
from market_vault.console.ui import ConsoleApp


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
        assert app.navigation_buttons[page_id].options["background"] == "#eee6d2"
        assert app.navigation_indicators[page_id].options["background"] == "#b48a28"

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


def test_navigation_method_has_no_business_or_network_operation():
    source = inspect.getsource(ConsoleApp.select_page)
    forbidden = ("backend", "OpenD", "backfill", "purge_execute", "_submit")
    assert all(token not in source for token in forbidden)


def test_shell_uses_hidden_notebook_and_home_is_default():
    source = inspect.getsource(ConsoleApp._build_shell)
    assert 'style="Hidden.TNotebook"' in source
    assert "self.select_page(PageId.HOME)" in source
    assert "backend.dashboard" not in inspect.getsource(ConsoleApp.__init__)
    assert "_refresh_dashboard()" not in inspect.getsource(ConsoleApp._build_dashboard)


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
