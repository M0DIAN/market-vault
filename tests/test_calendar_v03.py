from __future__ import annotations
# P2-9 PHASE-T marker; source P=a275008388ee0af0dd528fb6deacaaa76cd2e912

import importlib.util
from datetime import date
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from market_vault.api import MarketVault
from market_vault.cli import build_parser
from market_vault.collectors.moomoo_calendar import MoomooCalendarCollector, resolve_trade_date_market
from market_vault.collectors.moomoo_history import MoomooRequestError
from market_vault.models import Settings
from market_vault.normalization.calendar import normalize_trading_calendar
from market_vault.quality import run_trading_calendar_quality_checks
from market_vault.service import collect_trading_calendar
from market_vault.storage import Catalog, ParquetStore


TRADING_CALENDAR_PUBLIC_COLUMNS = [
    "scope_type",
    "scope_value",
    "market",
    "reference_code",
    "trade_date",
    "trade_date_type",
    "requested_start_date",
    "requested_end_date",
    "captured_at",
    "source",
    "source_schema_version",
    "ingestion_run_id",
]


def settings(tmp_path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        request_pause_seconds=0,
    )


class TradeDateType(Enum):
    WHOLE = "whole"
    MORNING = "morning"
    AFTERNOON = "afternoon"


def calendar_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": ["2026-07-01", "2026-07-02", "2026-07-03"],
            "trade_date_type": [TradeDateType.WHOLE, "TradeDateType.MORNING", "AFTERNOON"],
        }
    )


def test_resolve_trade_date_market_uses_sdk_enum():
    sdk = {"TradeDateMarket": SimpleNamespace(US="SDK_US")}

    assert resolve_trade_date_market("us", sdk) == "SDK_US"


def test_resolve_trade_date_market_fails_when_sdk_enum_missing():
    with pytest.raises(ValueError, match="TradeDateMarket.US"):
        resolve_trade_date_market("US", {"TradeDateMarket": None})


def test_resolve_trade_date_market_rejects_unsupported_market():
    with pytest.raises(ValueError, match="Supported values"):
        resolve_trade_date_market("EU", {"TradeDateMarket": SimpleNamespace()})


class FakeCalendarContext:
    def __init__(self, response=None, ret=0):
        self.response = response if response is not None else [
            {"time": "2026-07-01", "trade_date_type": "WHOLE"}
        ]
        self.ret = ret
        self.calls = []
        self.closed = False

    def request_trading_days(self, **kwargs):
        self.calls.append(kwargs)
        return self.ret, self.response

    def close(self):
        self.closed = True


def collector_with_context(tmp_path, ctx):
    collector = MoomooCalendarCollector(settings(tmp_path))
    collector._ctx = ctx
    collector._sdk = {
        "RET_OK": 0,
        "OpenQuoteContext": lambda host=None, port=None: ctx,
        "TradeDateMarket": SimpleNamespace(US="SDK_US"),
    }
    return collector


def test_calendar_collector_market_mode_calls_request_trading_days(tmp_path):
    ctx = FakeCalendarContext()
    collector = collector_with_context(tmp_path, ctx)

    out = collector.fetch_trading_calendar(date(2026, 7, 1), date(2026, 7, 31), market="US")

    assert len(out) == 1
    assert ctx.calls[0] == {"start": "2026-07-01", "end": "2026-07-31", "market": "SDK_US"}


def test_calendar_collector_code_mode_calls_request_trading_days(tmp_path):
    ctx = FakeCalendarContext(response=pd.DataFrame({"time": ["2026-07-01"], "trade_date_type": ["WHOLE"]}))
    collector = collector_with_context(tmp_path, ctx)

    out = collector.fetch_trading_calendar(date(2026, 7, 1), date(2026, 7, 31), code=" us.mu ")

    assert len(out) == 1
    assert ctx.calls[0] == {"start": "2026-07-01", "end": "2026-07-31", "code": "US.MU"}


def test_calendar_collector_requires_exactly_one_scope(tmp_path):
    collector = collector_with_context(tmp_path, FakeCalendarContext())

    with pytest.raises(ValueError):
        collector.fetch_trading_calendar(date(2026, 7, 1), date(2026, 7, 31))
    with pytest.raises(ValueError):
        collector.fetch_trading_calendar(date(2026, 7, 1), date(2026, 7, 31), market="US", code="US.MU")
    with pytest.raises(ValueError, match="code cannot be empty"):
        collector.fetch_trading_calendar(date(2026, 7, 1), date(2026, 7, 31), code="   ")


def test_calendar_collector_api_failure_and_close(tmp_path):
    ctx = FakeCalendarContext(response="bad", ret=1)
    collector = collector_with_context(tmp_path, ctx)

    with pytest.raises(MoomooRequestError):
        with collector:
            collector.fetch_trading_calendar(date(2026, 7, 1), date(2026, 7, 31), market="US")

    assert ctx.closed is True


def test_calendar_collector_rejects_unsupported_response_type(tmp_path):
    collector = collector_with_context(tmp_path, FakeCalendarContext(response="bad"))

    with pytest.raises(MoomooRequestError, match="unsupported"):
        collector.fetch_trading_calendar(date(2026, 7, 1), date(2026, 7, 31), market="US")


def test_calendar_normalization_maps_dates_types_captured_at_dedup_and_sort():
    raw = pd.concat([calendar_frame(), calendar_frame().iloc[[0]]], ignore_index=True)
    out = normalize_trading_calendar(
        raw,
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-1",
    )

    assert out["trade_date"].tolist() == [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    assert out["trade_date_type"].tolist() == ["WHOLE", "MORNING", "AFTERNOON"]
    assert str(out["captured_at"].dt.tz) == "UTC"
    assert out.loc[0, "scope_type"] == "MARKET"
    assert out.loc[0, "scope_value"] == "US"
    assert out.loc[0, "requested_start_date"] == date(2026, 7, 1)
    assert out.loc[0, "requested_end_date"] == date(2026, 7, 31)


def test_calendar_normalization_preserves_unknown_type():
    out = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-01"], "trade_date_type": ["NIGHT"]}),
        market=None,
        code=" Us.Mu ",
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-1",
    )

    assert out.loc[0, "trade_date_type"] == "NIGHT"
    assert out.loc[0, "scope_type"] == "CODE"
    assert out.loc[0, "reference_code"] == "US.MU"
    assert out.loc[0, "scope_value"] == "US.MU"


def test_calendar_quality_checks_failures_and_warns():
    df = pd.DataFrame(
        {
            "scope_type": ["MARKET", "MARKET", "BAD"],
            "scope_value": ["US", "US", ""],
            "trade_date": [date(2026, 7, 1), date(2026, 7, 1), "bad"],
            "trade_date_type": ["NIGHT", "NIGHT", None],
            "captured_at": [pd.Timestamp("2026-08-02T01:00:00Z")] * 3,
            "source": ["moomoo"] * 3,
        }
    )

    checks = {item.check_name: item for item in run_trading_calendar_quality_checks(df, date(2026, 7, 2), date(2026, 7, 31))}

    assert checks["trade_date_valid"].result == "FAIL"
    assert checks["trade_date_in_requested_range"].result == "FAIL"
    assert checks["duplicate_trading_calendar"].result == "FAIL"
    assert checks["scope_type_valid"].result == "FAIL"
    assert checks["scope_value_non_empty"].result == "FAIL"
    assert checks["trade_date_type_known"].result == "WARN"


def test_calendar_quality_valid_data_passes():
    df = normalize_trading_calendar(
        calendar_frame(),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-1",
    )

    assert {item.result for item in run_trading_calendar_quality_checks(df, date(2026, 7, 1), date(2026, 7, 31))} == {
        "PASS"
    }


class ServiceCalendarCollector:
    response = calendar_frame()
    error: Exception | None = None

    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def fetch_trading_calendar(self, start_date, end_date, market=None, code=None):
        if self.error:
            raise self.error
        return self.response.copy()


def test_calendar_service_success_manifest_and_files(monkeypatch, tmp_path):
    import market_vault.service as service

    ServiceCalendarCollector.response = calendar_frame()
    ServiceCalendarCollector.error = None
    monkeypatch.setattr(service, "MoomooCalendarCollector", ServiceCalendarCollector)

    manifest = collect_trading_calendar(settings(tmp_path), date(2026, 7, 1), date(2026, 7, 31), market="US")

    assert manifest.status == "SUCCESS"
    assert manifest.parameters["api_request_count"] == 1
    assert manifest.parameters["successful_api_request_count"] == 1
    assert manifest.parameters["failed_api_request_count"] == 0
    assert manifest.parameters["returned_min_date"] == "2026-07-01"
    assert manifest.parameters["returned_max_date"] == "2026-07-03"
    assert Path(manifest.raw_file).exists()
    assert Path(manifest.curated_file).exists()
    assert Path(manifest.quality_report).exists()


def test_calendar_service_failed_and_empty_manifest(monkeypatch, tmp_path):
    import market_vault.service as service

    ServiceCalendarCollector.response = pd.DataFrame()
    ServiceCalendarCollector.error = None
    monkeypatch.setattr(service, "MoomooCalendarCollector", ServiceCalendarCollector)

    empty_manifest = collect_trading_calendar(settings(tmp_path), date(2026, 7, 1), date(2026, 7, 31), market="US")
    assert empty_manifest.status == "FAILED"
    assert empty_manifest.parameters["failed_api_request_count"] == 1

    ServiceCalendarCollector.error = RuntimeError("boom")
    failed_manifest = collect_trading_calendar(settings(tmp_path), date(2026, 7, 1), date(2026, 7, 31), code="US.MU")
    assert failed_manifest.status == "FAILED"
    assert "US.MU" in failed_manifest.failed_items


def test_calendar_paths_and_duckdb_latest_use_captured_at(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    older = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-01"], "trade_date_type": ["WHOLE"]}),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="zzzz-run",
    )
    newer = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-01"], "trade_date_type": ["MORNING"]}),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="aaaa-run",
    )

    raw_path = store.write_trading_calendar_raw(
        pd.DataFrame({"time": ["2026-07-01"], "trade_date_type": ["WHOLE"]}),
        "MARKET",
        "US",
        date(2026, 7, 1),
        date(2026, 7, 31),
        "raw-run",
    )
    curated_path = store.write_trading_calendar_curated(
        older,
        "MARKET",
        "US",
        date(2026, 7, 1),
        date(2026, 7, 31),
        "zzzz-run",
    )
    store.write_trading_calendar_curated(newer, "MARKET", "US", date(2026, 7, 1), date(2026, 7, 31), "aaaa-run")

    assert "raw/source=moomoo/dataset=trading_calendar/scope_type=MARKET/scope_value=US" in raw_path.as_posix()
    assert "curated/trading_calendar/scope_type=MARKET/scope_value=US" in curated_path.as_posix()
    assert catalog.refresh_trading_calendar_views()
    with duckdb.connect(str(cfg.catalog_path)) as con:
        row = con.execute("SELECT trade_date_type, ingestion_run_id FROM trading_calendar_latest").fetchone()
        history_columns = con.sql("SELECT * FROM trading_calendar LIMIT 0").df().columns.tolist()
        latest_columns = con.sql("SELECT * FROM trading_calendar_latest LIMIT 0").df().columns.tolist()

    assert row == ("MORNING", "aaaa-run")
    assert history_columns == TRADING_CALENDAR_PUBLIC_COLUMNS
    assert latest_columns == TRADING_CALENDAR_PUBLIC_COLUMNS
    assert "start_date" not in latest_columns
    assert "end_date" not in latest_columns


def test_calendar_latest_withdraws_dates_missing_from_new_covering_snapshot(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    older = normalize_trading_calendar(
        pd.DataFrame(
            {
                "time": ["2026-07-01", "2026-07-02", "2026-07-03"],
                "trade_date_type": ["WHOLE", "WHOLE", "WHOLE"],
            }
        ),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="zzzz-run",
    )
    newer = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-01", "2026-07-02"], "trade_date_type": ["WHOLE", "MORNING"]}),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="aaaa-run",
    )
    store.write_trading_calendar_curated(older, "MARKET", "US", date(2026, 7, 1), date(2026, 7, 31), "zzzz-run")
    store.write_trading_calendar_curated(newer, "MARKET", "US", date(2026, 7, 1), date(2026, 7, 31), "aaaa-run")

    assert catalog.refresh_trading_calendar_views()
    with duckdb.connect(str(cfg.catalog_path)) as con:
        latest = con.execute("SELECT trade_date, trade_date_type FROM trading_calendar_latest ORDER BY trade_date").fetchall()
        history_0703 = con.execute(
            "SELECT count(*) FROM trading_calendar WHERE trade_date = DATE '2026-07-03'"
        ).fetchone()[0]

    assert latest == [(date(2026, 7, 1), "WHOLE"), (date(2026, 7, 2), "MORNING")]
    assert history_0703 == 1


def test_calendar_latest_partial_range_snapshot_leaves_outside_old_rows(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    older = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-01", "2026-07-15"], "trade_date_type": ["WHOLE", "WHOLE"]}),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="zzzz-run",
    )
    newer = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-15"], "trade_date_type": ["AFTERNOON"]}),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 15),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="aaaa-run",
    )
    store.write_trading_calendar_curated(older, "MARKET", "US", date(2026, 7, 1), date(2026, 7, 31), "zzzz-run")
    store.write_trading_calendar_curated(newer, "MARKET", "US", date(2026, 7, 15), date(2026, 7, 31), "aaaa-run")

    assert catalog.refresh_trading_calendar_views()
    with duckdb.connect(str(cfg.catalog_path)) as con:
        rows = con.execute("SELECT trade_date, trade_date_type FROM trading_calendar_latest ORDER BY trade_date").fetchall()

    assert rows == [(date(2026, 7, 1), "WHOLE"), (date(2026, 7, 15), "AFTERNOON")]


def test_calendar_latest_supports_old_parquet_without_requested_range(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    old_columns = [
        "scope_type",
        "scope_value",
        "market",
        "reference_code",
        "trade_date",
        "trade_date_type",
        "captured_at",
        "source",
        "source_schema_version",
        "ingestion_run_id",
    ]
    old = pd.DataFrame(
        [
            {
                "scope_type": "MARKET",
                "scope_value": "US",
                "market": "US",
                "reference_code": None,
                "trade_date": date(2026, 7, 3),
                "trade_date_type": "WHOLE",
                "captured_at": pd.Timestamp("2026-08-01T01:00:00Z"),
                "source": "moomoo",
                "source_schema_version": "10.9",
                "ingestion_run_id": "old-run",
            }
        ],
        columns=old_columns,
    )
    store.write_trading_calendar_curated(old, "MARKET", "US", date(2026, 7, 3), date(2026, 7, 3), "old-run")

    assert catalog.refresh_trading_calendar_views()
    with duckdb.connect(str(cfg.catalog_path)) as con:
        rows = con.execute("SELECT trade_date, trade_date_type FROM trading_calendar_latest").fetchall()
        columns = con.sql("SELECT * FROM trading_calendar_latest LIMIT 0").df().columns.tolist()

    assert rows == [(date(2026, 7, 3), "WHOLE")]
    assert columns == TRADING_CALENDAR_PUBLIC_COLUMNS


def test_calendar_market_and_code_scopes_do_not_mix(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    market = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-01"], "trade_date_type": ["WHOLE"]}),
        market="US",
        code=None,
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-market",
    )
    code = normalize_trading_calendar(
        pd.DataFrame({"time": ["2026-07-01"], "trade_date_type": ["AFTERNOON"]}),
        market=None,
        code=" Us.Mu ",
        requested_start_date=date(2026, 7, 1),
        requested_end_date=date(2026, 7, 31),
        captured_at=pd.Timestamp("2026-08-02T01:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="run-code",
    )
    store.write_trading_calendar_curated(market, "MARKET", "US", date(2026, 7, 1), date(2026, 7, 31), "run-market")
    store.write_trading_calendar_curated(code, "CODE", "US.MU", date(2026, 7, 1), date(2026, 7, 31), "run-code")

    vault = MarketVault(cfg)
    market_rows = vault.load_trading_calendar(market="US")
    code_rows = vault.load_trading_calendar(code="us.mu")

    assert market_rows.columns.tolist() == TRADING_CALENDAR_PUBLIC_COLUMNS
    assert code_rows.columns.tolist() == TRADING_CALENDAR_PUBLIC_COLUMNS
    assert "start_date" not in code_rows.columns
    assert "end_date" not in code_rows.columns
    assert market_rows["scope_type"].tolist() == ["MARKET"]
    assert code_rows["scope_type"].tolist() == ["CODE"]
    assert code_rows.loc[0, "trade_date_type"] == "AFTERNOON"
    assert Catalog(settings(tmp_path / "empty")).refresh_trading_calendar_views() is False


def test_calendar_query_no_files_returns_empty(tmp_path):
    assert MarketVault(settings(tmp_path)).load_trading_calendar(market="US").empty


def test_calendar_cli_parsing_and_mutual_exclusion():
    parser = build_parser()
    market_args = parser.parse_args(
        ["calendar", "--market", "US", "--start-date", "2026-01-01", "--end-date", "2026-12-31"]
    )
    code_args = parser.parse_args(
        ["calendar", "--code", "US.MU", "--start-date", "2026-01-01", "--end-date", "2026-12-31"]
    )
    query_args = parser.parse_args(
        ["calendar-query", "--market", "US", "--start-date", "2026-01-01", "--end-date", "2026-12-31"]
    )

    assert market_args.market == "US"
    assert code_args.code == "US.MU"
    assert query_args.limit == 30
    with pytest.raises(SystemExit):
        parser.parse_args(["calendar", "--market", "US", "--code", "US.MU", "--start-date", "2026-01-01", "--end-date", "2026-12-31"])
    with pytest.raises(SystemExit):
        parser.parse_args(["calendar", "--start-date", "2026-01-01", "--end-date", "2026-12-31"])


def _load_hygiene_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_repo_hygiene.py"
    spec = importlib.util.spec_from_file_location("check_repo_hygiene", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ci_workflow_contains_required_checks():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text()

    assert 'python-version: ["3.11", "3.14"]' in workflow
    assert "python -m compileall -q src tests scripts" in workflow
    assert "python -m pytest" in workflow
    assert "python scripts/check_repo_hygiene.py" in workflow
    assert "git diff --check" in workflow


def test_repo_hygiene_script_flags_forbidden_paths_and_large_files(tmp_path):
    hygiene = _load_hygiene_module()
    big = tmp_path / "large.txt"
    big.write_bytes(b"x" * (10 * 1024 * 1024 + 1))

    violations = hygiene.check_tracked_files(
        tmp_path,
        ["src/app.py", "data/raw/file.txt", ".env", "catalog/local.duckdb", "fixtures/sample.parquet", "large.txt"],
    )

    assert any("data/raw/file.txt" in item for item in violations)
    assert any(".env" in item for item in violations)
    assert any("local.duckdb" in item for item in violations)
    assert any("sample.parquet" in item for item in violations)
    assert any("large.txt" in item for item in violations)
    assert hygiene.check_tracked_files(tmp_path, ["src/app.py", "tests/test_app.py"]) == []
