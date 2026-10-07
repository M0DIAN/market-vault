from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import market_vault.research_workspace as workspace
from market_vault import MarketVault
from market_vault.models import (
    MarketBarSnapshotPair,
    QualityResult,
    RunManifest,
    Settings,
)
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        source="moomoo",
        source_schema_version="10.9",
        request_pause_seconds=0,
    )


def _calendar_frame(days: list[date]) -> pd.DataFrame:
    captured = pd.Timestamp("2026-01-20T12:00:00Z")
    return pd.DataFrame(
        {
            "scope_type": ["MARKET"] * len(days),
            "scope_value": ["US"] * len(days),
            "market": ["US"] * len(days),
            "reference_code": [None] * len(days),
            "trade_date": days,
            "trade_date_type": ["WHOLE"] * len(days),
            "requested_start_date": [days[0]] * len(days),
            "requested_end_date": [days[-1]] * len(days),
            "captured_at": [captured] * len(days),
            "source": ["moomoo"] * len(days),
            "source_schema_version": ["10.9"] * len(days),
            "ingestion_run_id": ["calendar-run"] * len(days),
        }
    )


class _CalendarCatalog:
    def __init__(self, start: date, end: date):
        self.start = start
        self.end = end

    def trading_calendar_requested_ranges(self, scope_type, scope_value, start, end):
        assert (scope_type, scope_value) == ("MARKET", "US")
        assert (start, end) == (self.start, self.end)
        return [(self.start, self.end)]


class _Vault:
    def __init__(self, settings, frame):
        self.settings = settings
        self.frame = frame
        self.catalog = _CalendarCatalog(
            frame["requested_start_date"].iloc[0],
            frame["requested_end_date"].iloc[0],
        )

    def load_trading_calendar(self, **kwargs):
        assert kwargs["market"] == "US"
        return self.frame.copy()


class _ResearchCatalog:
    complete: set[tuple[str, date]] = set()

    def __init__(self, settings):
        assert settings.source_schema_version == workspace.RESEARCH_SOURCE_SCHEMA_VERSION

    def completed_market_bar_items(self, **kwargs):
        return set(self.complete)


def _days() -> list[date]:
    return [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
        date(2026, 1, 13),
        date(2026, 1, 14),
        date(2026, 1, 15),
        date(2026, 1, 16),
    ]


def test_research_ready_settings_pins_ts2_without_moving_storage(tmp_path):
    original = _settings(tmp_path)
    resolved = workspace.research_ready_settings(original)

    assert resolved.source_schema_version == "10.9-mv-ts2"
    assert resolved.default_session == "RTH"
    assert resolved.default_adjustment == "NONE"
    assert resolved.data_root == original.data_root
    assert resolved.catalog_path == original.catalog_path
    assert original.source_schema_version == "10.9"


def test_split_spec_allows_normal_70_15_15_residual_test_capacity():
    anchors = tuple(
        date(2026, 1, 1) + timedelta(days=index)
        for index in range(80)
    )

    split = workspace._split_spec(anchors, 1)

    assert split.train_end_date == anchors[55]
    assert split.validation_end_date == anchors[67]
    assert split.test_end_date == anchors[-1]


def test_workspace_plan_uses_local_calendar_exact_cohort_and_split(tmp_path, monkeypatch):
    days = _days()
    settings = _settings(tmp_path)
    vault = _Vault(settings, _calendar_frame(days))
    _ResearchCatalog.complete = {("US.SPY", day) for day in days}
    monkeypatch.setattr(workspace, "Catalog", _ResearchCatalog)

    plan = workspace.plan_local_research_dataset(
        vault,
        symbol="us.spy",
        start_date=days[0],
        end_date=days[-1],
        interval="5m",
        preset="LIGHT_TECHNICAL",
        horizon_trading_days=1,
    )

    assert plan.ready is True
    assert plan.symbol == "US.SPY"
    assert plan.trading_dates == tuple(days)
    assert plan.anchor_dates == tuple(days[:-1])
    assert plan.scope.symbols == ("US.SPY",)
    assert plan.scope.requested_session == "RTH"
    assert plan.scope.adjustment == "NONE"
    assert plan.feature_window_bars == 5
    assert {spec.name for spec in plan.label_specs} == {
        "forward_return_1d",
        "execution_return_1d",
    }
    assert all(
        spec.requirements.source_schema_versions == ("10.9-mv-ts2",)
        for spec in plan.feature_specs + plan.label_specs
    )
    assert plan.split_spec.train_end_date < plan.split_spec.validation_end_date
    assert plan.split_spec.validation_end_date < plan.split_spec.test_end_date
    assert len(plan.anchors) == 9
    assert all(anchor.anchor_slot == 77 for anchor in plan.anchors)
    assert plan.summary["build_ready"] == "true"


def test_workspace_preview_exposes_missing_ts2_dates(tmp_path, monkeypatch):
    days = _days()
    settings = _settings(tmp_path)
    vault = _Vault(settings, _calendar_frame(days))
    _ResearchCatalog.complete = {("US.SPY", day) for day in days[:-2]}
    monkeypatch.setattr(workspace, "Catalog", _ResearchCatalog)

    plan = workspace.plan_local_research_dataset(
        vault,
        symbol="US.SPY",
        start_date=days[0],
        end_date=days[-1],
        interval="1m",
        preset="CORE_TECHNICAL",
        horizon_trading_days=1,
    )

    assert plan.ready is False
    assert plan.missing_research_dates == tuple(days[-2:])
    assert plan.summary["missing_research_dates"] == "2"
    assert plan.summary["build_ready"] == "false"
    assert [row["research_data"] for row in plan.rows[-2:]] == [
        "MISSING_TS2",
        "MISSING_TS2",
    ]


def test_morning_calendar_date_without_qualified_geometry_fails_closed(
    tmp_path, monkeypatch
):
    days = _days()
    frame = _calendar_frame(days)
    frame.loc[frame["trade_date"] == days[3], "trade_date_type"] = "MORNING"
    vault = _Vault(_settings(tmp_path), frame)
    _ResearchCatalog.complete = {("US.SPY", day) for day in days}
    monkeypatch.setattr(workspace, "Catalog", _ResearchCatalog)

    with pytest.raises(
        workspace.ResearchWorkspaceError,
        match="no qualified RTH early-close geometry",
    ):
        workspace.plan_local_research_dataset(
            vault,
            symbol="US.SPY",
            start_date=days[0],
            end_date=days[-1],
            interval="5m",
            preset="LIGHT_TECHNICAL",
            horizon_trading_days=1,
        )


def test_build_workspace_composes_canonical_and_research_authorities(
    tmp_path, monkeypatch
):
    days = _days()
    settings = _settings(tmp_path)
    settings.data_root.mkdir(parents=True, exist_ok=True)
    vault = _Vault(settings, _calendar_frame(days))
    _ResearchCatalog.complete = {("US.SPY", day) for day in days}
    monkeypatch.setattr(workspace, "Catalog", _ResearchCatalog)
    plan = workspace.plan_local_research_dataset(
        vault,
        symbol="US.SPY",
        start_date=days[0],
        end_date=days[-1],
        interval="5m",
        preset="LIGHT_TECHNICAL",
        horizon_trading_days=1,
    )
    monkeypatch.setattr(
        workspace,
        "plan_local_research_dataset",
        lambda *args, **kwargs: plan,
    )
    canonical_path = tmp_path / "canonical-final"
    dataset_path = tmp_path / "research-final"
    canonical_path.mkdir()
    dataset_path.mkdir()
    canonical_result = SimpleNamespace(
        canonical_build_id="c" * 64,
        build_path=canonical_path,
        status="COMPLETE",
        row_count=780,
    )
    monkeypatch.setattr(
        workspace,
        "materialize_canonical_market_bars",
        lambda *args, **kwargs: canonical_result,
    )
    canonical = object()
    monkeypatch.setattr(
        workspace,
        "load_verified_canonical_build",
        lambda path: canonical,
    )
    assignments = tuple(
        SimpleNamespace(assignment_status="ASSIGNED", final_split=split)
        for split in ("TRAIN", "VALIDATION", "TEST")
    )
    verified = SimpleNamespace(
        dataset_id="d" * 64,
        build_path=dataset_path,
        status="COMPLETE",
        rows=(("one",), ("two",), ("three",)),
        split_result=SimpleNamespace(assignments=assignments),
    )
    captured = {}

    def build_research_dataset(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(verified=verified)

    monkeypatch.setattr(
        workspace,
        "build_research_dataset",
        build_research_dataset,
    )

    result = workspace.build_local_research_dataset(
        vault,
        symbol="US.SPY",
        start_date=days[0],
        end_date=days[-1],
        interval="5m",
        preset="LIGHT_TECHNICAL",
        horizon_trading_days=1,
    )

    assert result.canonical_build_id == "c" * 64
    assert result.dataset_id == "d" * 64
    assert result.dataset_build_path == dataset_path
    assert result.split_counts == {"TRAIN": 1, "VALIDATION": 1, "TEST": 1}
    assert captured["feature_builds"] == (canonical,)
    assert captured["label_builds"] == (canonical,)
    assert captured["observation_builds"] == ()
    assert captured["scope"] == plan.scope
    assert captured["anchors"] == plan.anchors
    assert captured["ts2_feature_specs"] == plan.feature_specs
    assert captured["label_specs"] == plan.label_specs


def _write_real_calendar(cfg: Settings, trading_days: list[date]) -> None:
    frame = pd.DataFrame(
        {
            "time": [day.isoformat() for day in trading_days],
            "trade_date_type": ["WHOLE"] * len(trading_days),
        }
    )
    curated = normalize_trading_calendar(
        frame,
        market="US",
        code=None,
        requested_start_date=trading_days[0],
        requested_end_date=trading_days[-1],
        captured_at=pd.Timestamp("2026-01-20T12:00:00Z"),
        source="moomoo",
        source_schema_version="10.9",
        run_id="calendar-real",
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated,
        "MARKET",
        "US",
        trading_days[0],
        trading_days[-1],
        "calendar-real",
    )
    Catalog(cfg).refresh_trading_calendar_views()


def _provider_5m_times(day: date) -> list[pd.Timestamp]:
    opened = pd.Timestamp(f"{day.isoformat()} 09:30:00", tz="America/New_York")
    closed = pd.Timestamp(f"{day.isoformat()} 16:00:00", tz="America/New_York")
    return list(
        pd.date_range(
            opened + pd.Timedelta(5, unit="m"),
            closed,
            freq="5min",
        )
    )


def _write_real_ts2_day(cfg: Settings, day: date, *, ordinal: int) -> None:
    code = "US.SPY"
    run_id = f"real-ts2-{day.isoformat()}"
    provider = _provider_5m_times(day)
    count = len(provider)
    base = 100.0 + ordinal
    raw = pd.DataFrame(
        {
            "code": [code] * count,
            "name": [code] * count,
            "time_key": [value.strftime("%Y-%m-%d %H:%M:%S") for value in provider],
            "open": [base + index * 0.01 for index in range(count)],
            "high": [base + index * 0.01 + 0.15 for index in range(count)],
            "low": [base + index * 0.01 - 0.10 for index in range(count)],
            "close": [base + index * 0.01 + 0.05 for index in range(count)],
            "volume": [1000.0 + index for index in range(count)],
        }
    )
    raw["requested_trade_date"] = day
    raw["interval"] = "5m"
    raw["requested_session"] = "RTH"
    raw["adjustment"] = "NONE"
    raw["ingestion_run_id"] = run_id
    curated = normalize_bars(
        raw,
        requested_trade_date=day,
        interval="5m",
        requested_session="RTH",
        adjustment="NONE",
        source="moomoo",
        source_schema_version=workspace.RESEARCH_SOURCE_SCHEMA_VERSION,
        run_id=run_id,
    )
    assert set(curated["session"]) == {"REGULAR"}

    store = ParquetStore(cfg)
    raw_path = store.write_raw(
        raw, day, "5m", [code], "RTH", "NONE", run_id=run_id
    )
    curated_path = store.write_curated(
        curated, day, "5m", [code], "RTH", "NONE", run_id=run_id
    )
    pair = MarketBarSnapshotPair.create(
        run_id=run_id,
        symbol=code,
        requested_trade_date=day,
        interval="5m",
        session="RTH",
        adjustment="NONE",
        source="moomoo",
        source_schema_version=workspace.RESEARCH_SOURCE_SCHEMA_VERSION,
        raw_file=str(raw_path),
        curated_file=str(curated_path),
        row_count=len(curated),
    )
    run = RunManifest(
        requested_trade_date=day,
        requested_symbols=[code],
        interval="5m",
        session="RTH",
        adjustment="NONE",
        run_id=run_id,
        snapshot_binding_mode="REGISTERED_PER_SYMBOL",
    )
    run.successful_symbols = [code]
    run.snapshot_pairs = [pair]
    run.row_count = len(curated)
    run.raw_file = str(raw_path)
    run.curated_file = str(curated_path)
    run.status = "SUCCESS"
    run.finished_at = datetime.now(timezone.utc)

    catalog = Catalog(cfg)
    catalog.register_market_bar_snapshot_pair(pair)
    catalog.record_run(run)
    catalog.record_quality(run_id, [QualityResult("bars_complete", "PASS")])


def test_real_ts2_catalog_to_canonical_to_research_dataset_e2e(tmp_path):
    from market_vault.cross_day_dataset._artifact_io import _NativeScope
    from market_vault.cross_day_dataset._artifact_platform import (
        _QUALIFIED_CAPABILITIES,
        _capability,
    )

    with _NativeScope(tmp_path, output=True) as scope:
        capability = _capability(scope)
    if capability not in _QUALIFIED_CAPABILITIES:
        pytest.skip("exact native artifact publication capability is not qualified")

    days = _days()
    base = _settings(tmp_path)
    research_cfg = workspace.research_ready_settings(base)
    _write_real_calendar(base, days)
    for index, day in enumerate(days):
        _write_real_ts2_day(research_cfg, day, ordinal=index)

    result = workspace.build_local_research_dataset(
        MarketVault(base),
        symbol="US.SPY",
        start_date=days[0],
        end_date=days[-1],
        interval="5m",
        preset="LIGHT_TECHNICAL",
        horizon_trading_days=1,
    )

    assert result.plan.ready is True
    assert result.canonical_row_count == 10 * 78
    assert result.dataset_status == "COMPLETE"
    assert result.dataset_row_count == 9
    assert result.split_counts["TRAIN"] > 0
    assert result.split_counts["VALIDATION"] > 0
    assert result.split_counts["TEST"] > 0
    assert result.canonical_build_path.is_dir()
    assert result.dataset_build_path.is_dir()
