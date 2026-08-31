from __future__ import annotations

import ast
import tomllib
from threading import Event
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault.api import MarketVault, QueryPage
from market_vault.audit import AuditCalendarInfo, AuditReport
from market_vault.console.backend import (
    ConsoleBackend,
    parse_iso_date,
    parse_symbols,
    table_page_from_query,
)
from market_vault.console.models import TablePage
from market_vault.console.tasks import SerialTaskRunner
from market_vault.intraday_audit import IntradayAuditReport, IntradayCalendarInfo
from market_vault.models import DatasetRunManifest, RunManifest, Settings
from market_vault.storage import Catalog


def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports" / "data_quality",
    )


def write_bars(cfg: Settings) -> None:
    root = (
        cfg.data_root
        / "curated"
        / "source=moomoo"
        / "dataset=market_bars"
        / "interval=1m"
        / "requested_trade_date=2026-07-01"
    )
    root.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "code": ["US.SPY"] * 5,
            "time_utc": pd.date_range("2026-07-01 13:30:00", periods=5, freq="min", tz="UTC"),
            "time_market": pd.date_range(
                "2026-07-01 09:30:00", periods=5, freq="min", tz="America/New_York"
            ),
            "requested_trade_date": [date(2026, 7, 1)] * 5,
            "interval": ["1m"] * 5,
            "requested_session": ["ALL"] * 5,
            "session": ["REGULAR"] * 5,
            "adjustment": ["NONE"] * 5,
            "ingested_at": [pd.Timestamp("2026-07-02", tz="UTC")] * 5,
            "ingestion_run_id": ["run-bars"] * 5,
        }
    )
    frame.to_parquet(root / "batch.parquet", index=False)


def write_calendar(cfg: Settings) -> None:
    root = (
        cfg.data_root
        / "curated"
        / "trading_calendar"
        / "scope_type=MARKET"
        / "scope_value=US"
        / "start_date=2026-07-01"
        / "end_date=2026-07-03"
    )
    root.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "scope_type": ["MARKET"] * 3,
            "scope_value": ["US"] * 3,
            "market": ["US"] * 3,
            "reference_code": [None] * 3,
            "trade_date": [date(2026, 7, day) for day in (1, 2, 3)],
            "trade_date_type": ["WHOLE"] * 3,
            "requested_start_date": [date(2026, 7, 1)] * 3,
            "requested_end_date": [date(2026, 7, 3)] * 3,
            "captured_at": [pd.Timestamp("2026-07-04", tz="UTC")] * 3,
            "source": ["moomoo"] * 3,
            "source_schema_version": ["10.9"] * 3,
            "ingestion_run_id": ["run-calendar"] * 3,
        }
    )
    frame.to_parquet(root / "batch.parquet", index=False)


def test_bars_page_is_bounded_and_normalizes_code(tmp_path):
    cfg = settings(tmp_path)
    write_bars(cfg)
    page = MarketVault(cfg).load_bars_page(code=" us.spy ", page=2, page_size=2)
    assert page.total_rows == 5
    assert page.page == 2
    assert page.total_pages == 3
    assert page.has_previous is True
    assert page.has_next is True
    assert len(page.data) == 2
    assert page.data["time_utc"].is_monotonic_increasing


@pytest.mark.parametrize("page,page_size", [(0, 100), (1, 0), (1, 1001)])
def test_query_page_limits_fail_closed(tmp_path, page, page_size):
    with pytest.raises(ValueError):
        MarketVault(settings(tmp_path)).load_bars_page(
            code="US.SPY", page=page, page_size=page_size
        )


def test_calendar_page_uses_latest_local_view(tmp_path):
    cfg = settings(tmp_path)
    write_calendar(cfg)
    page = MarketVault(cfg).load_trading_calendar_page(
        market=" us ", page=2, page_size=2
    )
    assert page.total_rows == 3
    assert [value.date() for value in page.data["trade_date"]] == [date(2026, 7, 3)]
    assert "start_date" not in page.data.columns
    assert "requested_start_date" in page.data.columns


def test_run_history_page_combines_collection_and_dataset_runs(tmp_path):
    cfg = settings(tmp_path)
    catalog = Catalog(cfg)
    child = RunManifest(
        requested_trade_date=date(2026, 7, 1),
        requested_symbols=["US.SPY"],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        status="SUCCESS",
        row_count=5,
    )
    child.finished_at = datetime.now(timezone.utc)
    catalog.record_run(child)
    dataset = DatasetRunManifest(dataset="trading_calendar", requested_items=["US"], parameters={})
    dataset.status = "FAILED"
    dataset.failed_items = {"US": "offline fixture"}
    dataset.finished_at = datetime.now(timezone.utc)
    catalog.record_dataset_run(dataset)

    page = MarketVault(cfg).load_run_history_page(page_size=10)
    assert page.total_rows == 2
    assert set(page.data["run_kind"]) == {"COLLECTION", "DATASET"}
    failed = MarketVault(cfg).load_run_history_page(status="failed", page_size=10)
    assert failed.total_rows == 1
    assert failed.data.iloc[0]["dataset"] == "trading_calendar"


def test_empty_run_history_does_not_create_catalog(tmp_path):
    cfg = settings(tmp_path)
    page = MarketVault(cfg).load_run_history_page()
    assert page.total_rows == 0
    assert page.data.empty
    assert not cfg.catalog_path.exists()


def test_calendar_collection_api_delegates_to_service(monkeypatch, tmp_path):
    captured = {}
    manifest = SimpleNamespace(run_id="calendar-run")

    def fake_collect(cfg, **kwargs):
        captured["settings"] = cfg
        captured.update(kwargs)
        return manifest

    monkeypatch.setattr("market_vault.api.collect_trading_calendar", fake_collect)
    cfg = settings(tmp_path)
    result = MarketVault(cfg).collect_trading_calendar(
        market="US",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )
    assert result is manifest
    assert captured == {
        "settings": cfg,
        "market": "US",
        "code": None,
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 31),
    }


class FakeVault:
    def __init__(self):
        self.settings = SimpleNamespace(opend_host="127.0.0.1", opend_port=11111)
        self.calls: list[str] = []
        self.inventory_calls: list[dict] = []

    def load_bars_page(self, **kwargs):
        self.calls.append("load_bars_page")
        return QueryPage(pd.DataFrame({"code": ["US.SPY"], "close": [500.0]}), 1, 100, 1)

    def inventory_market_bars(self, **kwargs):
        self.calls.append("inventory_market_bars")
        self.inventory_calls.append(dict(kwargs))
        summary = SimpleNamespace(
            symbol_count=1,
            snapshot_count=2,
            latest_query_row_count=3,
            completed_trade_date_count=4,
            incomplete_trade_date_count=0,
            latest_trade_date="2026-07-01",
            as_dict=lambda: {"symbol_count": 1},
        )
        item = SimpleNamespace(as_dict=lambda: {"code": "US.SPY"})
        return SimpleNamespace(status="SUCCESS", summary=summary, items=[item], report_file=None)

    def load_run_history_page(self, **kwargs):
        self.calls.append("load_run_history_page")
        return QueryPage(pd.DataFrame({"run_id": ["run-1"], "status": ["SUCCESS"]}), 1, 20, 1)

    def load_trading_calendar_page(self, **kwargs):
        self.calls.append("load_trading_calendar_page")
        return QueryPage(pd.DataFrame({"trade_date": [date(2026, 7, 1)]}), 1, 100, 1)

    def collect_trading_calendar(self, **kwargs):
        self.calls.append("collect_trading_calendar")
        return SimpleNamespace(as_dict=lambda: {"status": "SUCCESS", "run_id": "cal-1"})

    def audit_market_bars(self, **kwargs):
        self.calls.append("audit_market_bars")
        summary = SimpleNamespace(as_dict=lambda: {"total_expected_items": 1})
        symbol = SimpleNamespace(as_dict=lambda: {"code": "US.SPY", "coverage_percentage": 100.0})
        return SimpleNamespace(status="PASS", summary=summary, symbols=[symbol])

    def audit_intraday_market_bars(self, **kwargs):
        self.calls.append("audit_intraday_market_bars")
        summary = SimpleNamespace(as_dict=lambda: {"audited_item_count": 1})
        item = SimpleNamespace(
            requested_trade_date="2026-07-01",
            source_state="COMPLETE",
            audit_status="PASS",
            boundary_coverage=SimpleNamespace(evaluated=False),
            observed=SimpleNamespace(session_row_counts={"REGULAR": 390}),
            internal_gaps=[],
        )
        return SimpleNamespace(
            status="PASS",
            summary=summary,
            symbols=[SimpleNamespace(code="US.SPY", items=[item])],
        )

    def plan_backfill(self, **kwargs):
        self.calls.append("plan_backfill")
        item = SimpleNamespace(code="US.SPY", trade_date=date(2026, 7, 1))
        return SimpleNamespace(
            calendar_scope_type="MARKET",
            calendar_scope_value="US",
            symbols=["US.SPY"],
            trading_dates=[date(2026, 7, 1)],
            pending_items=[item],
            skipped_items=[],
        )

    def backfill(self, **kwargs):
        self.calls.append("backfill")
        return SimpleNamespace(as_dict=lambda: {"status": "SUCCESS", "run_id": "backfill-1"})


def test_dashboard_and_queries_are_local_only():
    fake = FakeVault()
    backend = ConsoleBackend(fake)
    dashboard = backend.dashboard()
    bars = backend.query_bars(code="us.spy")
    calendar = backend.query_calendar(market="US")
    assert dashboard.metrics["Symbols"] == "1"
    assert fake.inventory_calls == [
        {"include_files": False, "persist_report": False}
    ]
    assert bars.rows == (("US.SPY", "500.0"),)
    assert calendar.rows == (("2026-07-01",),)
    assert fake.calls == [
        "inventory_market_bars",
        "load_run_history_page",
        "load_bars_page",
        "load_trading_calendar_page",
    ]
    assert "collect_trading_calendar" not in fake.calls
    assert "backfill" not in fake.calls


def test_inventory_query_disables_report_persistence_with_exact_filters():
    fake = FakeVault()

    summary, items = ConsoleBackend(fake).inventory(
        symbols="us.spy",
        start_date="2026-07-01",
        end_date="2026-07-02",
        interval="1m",
        session="ALL",
        adjustment="NONE",
    )

    assert summary == {"symbol_count": 1}
    assert items.rows == (("US.SPY",),)
    assert fake.inventory_calls == [
        {
            "symbols": ["US.SPY"],
            "start_date": date(2026, 7, 1),
            "end_date": date(2026, 7, 2),
            "interval": "1m",
            "session": "ALL",
            "adjustment": "NONE",
            "include_files": False,
            "persist_report": False,
        }
    ]


def test_real_gui_inventory_paths_do_not_add_reports(tmp_path):
    cfg = settings(tmp_path)
    write_bars(cfg)
    backend = ConsoleBackend(MarketVault(cfg))
    before = set(cfg.report_dir.glob("market_bars_inventory_*.json"))

    dashboard = backend.dashboard()
    after_dashboard = set(cfg.report_dir.glob("market_bars_inventory_*.json"))
    summary, items = backend.inventory(symbols="US.SPY", interval="1m")
    after_inventory = set(cfg.report_dir.glob("market_bars_inventory_*.json"))

    assert dashboard.status == "SUCCESS"
    assert dashboard.metrics["Symbols"] == "1"
    assert dashboard.metrics["Latest rows"] == "5"
    assert dashboard.message == ""
    assert summary["symbol_count"] == 1
    assert items.total_rows == 1
    assert before == after_dashboard == after_inventory == set()


def test_explicit_network_operations_route_through_market_vault():
    fake = FakeVault()
    backend = ConsoleBackend(fake)
    calendar = backend.collect_calendar(
        market="US", start_date="2026-07-01", end_date="2026-07-31"
    )
    plan = backend.plan_backfill(
        symbols="us.spy",
        calendar_market="US",
        start_date="2026-07-01",
        end_date="2026-07-01",
    )
    run = backend.execute_backfill(
        symbols="us.spy",
        calendar_market="US",
        start_date="2026-07-01",
        end_date="2026-07-01",
    )
    assert calendar["run_id"] == "cal-1"
    assert plan.pending_count == 1
    assert run["run_id"] == "backfill-1"
    assert fake.calls == ["collect_trading_calendar", "plan_backfill", "backfill"]


def test_audit_backends_preserve_not_evaluated_boundary_state():
    fake = FakeVault()
    backend = ConsoleBackend(fake)
    coverage_summary, coverage = backend.coverage_audit(
        symbols="US.SPY",
        start_date="2026-07-01",
        end_date="2026-07-01",
        calendar_market="US",
    )
    intraday_summary, intraday = backend.intraday_audit(
        symbols="US.SPY",
        start_date="2026-07-01",
        end_date="2026-07-01",
        calendar_market="US",
    )
    assert coverage_summary["status"] == "PASS"
    assert coverage.rows[0][0] == "US.SPY"
    assert intraday_summary["status"] == "PASS"
    boundary_index = intraday.columns.index("boundary_evaluated")
    assert intraday.rows[0][boundary_index] == "False"
    assert fake.calls == ["audit_market_bars", "audit_intraday_market_bars"]


def test_intraday_audit_preserves_failed_calendar_coverage_without_summary():
    fake = FakeVault()
    fake.audit_intraday_market_bars = lambda **kwargs: IntradayAuditReport(
        run_id="intraday-failed",
        started_at="2026-08-22T00:00:00+00:00",
        status="FAILED",
        calendar=IntradayCalendarInfo(
            coverage_complete=False,
            coverage_gaps=[{"start_date": "2026-07-02", "end_date": "2026-07-03"}],
            expected_trade_date_count=0,
            expected_trade_dates=[],
        ),
        summary=None,
    )

    summary, details = ConsoleBackend(fake).intraday_audit(
        symbols="US.SPY",
        start_date="2026-07-01",
        end_date="2026-07-03",
        calendar_market="US",
    )

    assert summary["status"] == "FAILED"
    assert summary["calendar_coverage_complete"] is False
    assert summary["calendar_coverage_gaps"] == [
        {"start_date": "2026-07-02", "end_date": "2026-07-03"}
    ]
    assert "audit classifications were not evaluated" in summary["failure_reason"]
    assert "coverage_percentage" not in summary
    assert details.rows == ()
    assert details.total_rows == 0


def test_coverage_audit_preserves_failed_calendar_coverage_without_summary():
    fake = FakeVault()
    fake.audit_market_bars = lambda **kwargs: AuditReport(
        run_id="coverage-failed",
        started_at="2026-08-22T00:00:00+00:00",
        status="FAILED",
        calendar=AuditCalendarInfo(
            coverage_complete=False,
            coverage_gaps=[{"start_date": "2026-07-02", "end_date": "2026-07-03"}],
        ),
        summary=None,
    )

    summary, details = ConsoleBackend(fake).coverage_audit(
        symbols="US.SPY",
        start_date="2026-07-01",
        end_date="2026-07-03",
        calendar_market="US",
    )

    assert summary["status"] == "FAILED"
    assert summary["calendar_coverage_complete"] is False
    assert summary["calendar_coverage_gaps"] == [
        {"start_date": "2026-07-02", "end_date": "2026-07-03"}
    ]
    assert "audit classifications were not evaluated" in summary["failure_reason"]
    assert "coverage_percentage" not in summary
    assert details.rows == ()
    assert details.total_rows == 0


def test_report_display_is_bounded_but_preserves_total_count():
    fake = FakeVault()
    base_inventory = fake.inventory_market_bars

    def oversized_inventory(**kwargs):
        report = base_inventory(**kwargs)
        report.items = [
            SimpleNamespace(as_dict=lambda index=index: {"code": f"US.TEST{index:04d}"})
            for index in range(1005)
        ]
        return report

    fake.inventory_market_bars = oversized_inventory
    _, items = ConsoleBackend(fake).inventory()
    assert len(items.rows) == 1000
    assert items.total_rows == 1005


def test_export_is_limited_to_loaded_page(tmp_path):
    backend = ConsoleBackend(FakeVault())
    page = TablePage(("code", "close"), (("US.SPY", "500"),), total_rows=1)
    csv_result = backend.export_page(page, tmp_path / "bars.csv", "csv")
    json_result = backend.export_page(page, tmp_path / "bars.json", "json")
    assert csv_result.row_count == 1
    assert (tmp_path / "bars.csv").read_text(encoding="utf-8-sig").splitlines() == [
        "code,close",
        "US.SPY,500",
    ]
    assert '"US.SPY"' in (tmp_path / "bars.json").read_text(encoding="utf-8")


def test_export_rejects_unbounded_page(tmp_path):
    backend = ConsoleBackend(FakeVault())
    oversized = TablePage(("value",), tuple((str(i),) for i in range(1001)), total_rows=1001)
    with pytest.raises(ValueError, match="more than 1000"):
        backend.export_page(oversized, tmp_path / "too-large.csv", "csv")


def test_console_parsers_normalize_and_reject_invalid_values():
    assert parse_symbols(" us.spy, US.QQQ us.spy ") == ["US.QQQ", "US.SPY"]
    assert parse_iso_date("2026-07-01", "start") == date(2026, 7, 1)
    with pytest.raises(ValueError, match="At least one symbol"):
        parse_symbols("   ")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_iso_date("07/01/2026", "start")


def test_table_page_converts_timestamps_without_retaining_dataframe():
    query = QueryPage(
        pd.DataFrame({"when": [pd.Timestamp("2026-07-01", tz="UTC")], "missing": [None]}),
        1,
        100,
        1,
    )
    table = table_page_from_query(query)
    assert table.rows == (("2026-07-01T00:00:00+00:00", ""),)
    assert not hasattr(table, "data")


def test_serial_task_runner_rejects_overlap_and_reports_failure():
    runner = SerialTaskRunner()
    release = Event()
    running = runner.submit("running", lambda: release.wait(timeout=2))
    with pytest.raises(RuntimeError, match="Operation already running"):
        runner.submit("overlap", lambda: None)
    release.set()
    assert running.result(timeout=2) is True

    future = runner.submit("failure", lambda: (_ for _ in ()).throw(ValueError("broken")))
    with pytest.raises(ValueError, match="broken"):
        future.result(timeout=2)
    assert runner.state.status == "FAILED"
    assert runner.state.error == "broken"
    runner.close()


def test_console_adapters_use_api_boundary_without_gui_dependencies():
    repository_root = Path(__file__).resolve().parents[1]
    console_root = repository_root / "src" / "market_vault" / "console"
    forbidden_imports = {
        "duckdb",
        "market_vault.service",
        "market_vault.storage",
    }
    for source_path in console_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not {
            name
            for name in imported
            if any(name == forbidden or name.startswith(f"{forbidden}.") for forbidden in forbidden_imports)
        }, source_path

    project = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    dependencies = [*project["dependencies"], *project["optional-dependencies"]["dev"]]
    forbidden_gui_dependencies = ("customtkinter", "pyside", "pyqt", "wxpython", "kivy")
    assert not any(
        dependency.lower().startswith(forbidden_gui_dependencies)
        for dependency in dependencies
    )
