"""Offline deterministic tests of the v0.6.0 Sample Generator core (PR-3).

Covers the frozen result models, the real verified input chain (real
Canonical artifacts through ``load_verified_canonical_build``, real
Feature / Label spec files through the formal loaders and the built-in
registry preflight, real split-spec JSON), exact request geometry, stride
semantics, gap/segment boundaries, insufficient windows, Feature / Label
BARS coverage, duplicate rejection, Generation identity stability,
no-side-effect guarantees, and determinism. No network, no OpenD, no
stored market data beyond offline synthetic fixtures.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault.canonical import (
    materialize_canonical_market_bars,
    load_verified_canonical_build,
)
from market_vault.canonical.models import CanonicalRequestKey
from market_vault.dataset import (
    SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
    SAMPLE_GENERATOR_CORE_VERSION,
    DatasetScope,
    PITSampleRequest,
    SampleGenerationDiagnostics,
    SampleGenerationError,
    SampleGenerationPlan,
    SampleGenerationResult,
    SampleGenerationRule,
    generate_sample_requests,
    parse_sample_generation_plan_bytes,
    serialize_sample_generation_plan,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
NY = "America/New_York"
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
)
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
CANONICAL_SCHEMA_VERSION = "market-bars-canonical-schema-v1"
SOURCE_SCHEMA_VERSION = "10.9"
BUILT_AT = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)

#: Frozen Generation content ID of the standard fixture (computed once and
#: fixed; see test_identity_frozen_fixture).
FIXTURE_GENERATION_ID = "1ccc7266e9f548db3e5c67098c5ad758c4ef965d71e7d8c5fc9579922dc1bf4a"


@pytest.fixture(autouse=True)
def _deterministic_wall_clock(monkeypatch):
    """The existing ``normalize_bars`` fills the legacy ``ingested_at``
    column from ``pd.Timestamp.now``; pinning it makes every offline
    Canonical build in this file byte-deterministic, so the frozen fixture
    Generation content ID is stable across runs and machines."""
    monkeypatch.setattr(
        pd.Timestamp,
        "now",
        classmethod(lambda *args, **kwargs: pd.Timestamp("2026-08-01T01:00:00Z")),
    )


def utc(hour: int, minute: int, day: int = 1) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Real canonical-build fixtures (mirrors the PIT assembly tests).
# ---------------------------------------------------------------------------


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


def calendar(cfg: Settings, *, trade_date: date = date(2026, 7, 1)) -> None:
    frame = pd.DataFrame({"time": [trade_date.isoformat()], "trade_date_type": ["WHOLE"]})
    curated = normalize_trading_calendar(
        frame, market="US", code=None,
        requested_start_date=trade_date, requested_end_date=trade_date,
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"), source="moomoo",
        source_schema_version=cfg.source_schema_version, run_id="cal",
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated, "MARKET", "US", trade_date, trade_date, "cal"
    )
    Catalog(cfg).refresh_trading_calendar_views()


def minute_keys(start: str, count: int) -> list[str]:
    base = pd.Timestamp(start, tz=NY)
    return [
        (base + pd.Timedelta(int(i), unit="m")).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(count)
    ]


def write_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    time_keys: list[str],
    close: float = 100.5,
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = pd.DataFrame(
        {
            "code": [code] * len(time_keys),
            "name": [code] * len(time_keys),
            "time_key": time_keys,
            "open": [100.0] * len(time_keys),
            "high": [101.0] * len(time_keys),
            "low": [99.0] * len(time_keys),
            "close": [close] * len(time_keys),
            "volume": [100] * len(time_keys),
        }
    )
    curated = normalize_bars(
        raw, requested_trade_date=trade_date, interval="1m",
        requested_session="ALL", adjustment="NONE", source=cfg.source,
        source_schema_version=cfg.source_schema_version, run_id=run_id,
    )
    store.write_curated(curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize(cfg: Settings, *, symbols, trade_dates, root=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols,
        trade_dates=trade_dates,
        request_key=DEFAULT_KEY,
        output_root=root or output_root(cfg),
        created_at=CREATED_AT,
    )


def make_build(
    tmp_path,
    *,
    code: str = "US.MU",
    trade_date: date = date(2026, 7, 1),
    start: str = "2026-07-01 09:30:00",
    count: int = 10,
    run_id: str = "run-a",
    cfg=None,
):
    """One real verified Canonical build with ``count`` 1m bars starting at
    ``start`` (NY market time)."""
    cfg = cfg or settings(tmp_path)
    calendar(cfg, trade_date=trade_date)
    write_snapshot(
        cfg, code=code, trade_date=trade_date, run_id=run_id,
        time_keys=minute_keys(start, count),
    )
    return load_verified_canonical_build(
        materialize(cfg, symbols=[code], trade_dates=[trade_date]).build_path
    )


def make_gap_build(tmp_path):
    """One real build with an internal gap: 09:30 and 09:32 (09:31 missing)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap",
        time_keys=minute_keys("2026-07-01 09:30:00", 1)
        + minute_keys("2026-07-01 09:32:00", 1),
    )
    return load_verified_canonical_build(
        materialize(cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)]).build_path
    )


def make_multi_session_build(tmp_path):
    """One real build whose bars span two sessions: 09:30-09:31 (REGULAR)
    and 16:00-16:01 (AFTER_HOURS) on the same market-calendar date."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-sess",
        time_keys=minute_keys("2026-07-01 09:30:00", 2)
        + minute_keys("2026-07-01 16:00:00", 2),
    )
    return load_verified_canonical_build(
        materialize(cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)]).build_path
    )


def make_two_date_build(tmp_path):
    """One real build with two bars per market-calendar date (09:30-09:31)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    calendar(cfg, trade_date=date(2026, 7, 2))
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-d1",
        time_keys=minute_keys("2026-07-01 09:30:00", 2),
    )
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 2), run_id="run-d2",
        time_keys=minute_keys("2026-07-02 09:30:00", 2),
    )
    return load_verified_canonical_build(
        materialize(
            cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1), date(2026, 7, 2)]
        ).build_path
    )


def make_empty_build(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    return load_verified_canonical_build(
        materialize(cfg, symbols=["US.XYZ"], trade_dates=[date(2026, 7, 1)]).build_path
    )


def make_duplicate_logical_builds(tmp_path):
    """The same logical build materialized into two output roots (identical
    ``canonical_build_id``)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 4),
    )
    first = materialize(
        cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)],
        root=output_root(cfg) / "root-one",
    )
    second = materialize(
        cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)],
        root=output_root(cfg) / "root-two",
    )
    return (
        load_verified_canonical_build(first.build_path),
        load_verified_canonical_build(second.build_path),
    )


# ---------------------------------------------------------------------------
# Real spec-file fixtures (built-in registry resolvable).
# ---------------------------------------------------------------------------


def feature_spec_yaml(
    name: str = "simple_return",
    window_bars: int = 2,
    inputs: tuple = ("close",),
    parameters: dict | None = None,
) -> str:
    parameters = parameters if parameters is not None else {"window_bars": window_bars}
    inputs_yaml = "\n".join(f"    - {field}" for field in inputs)
    parameters_yaml = (
        "\n".join(f"  {key}: {value}" for key, value in parameters.items())
        if parameters
        else "  {}"
    )
    return f"""\
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: {name}
version: v1
output:
  name: {name}
  logical_type: float64
  nullable: false
inputs:
  canonical_fields:
{inputs_yaml}
transform:
  ref: market_vault.dataset.feature_transforms.{name}:{name}
parameters:
{parameters_yaml}
requirements:
  canonical_schema_versions:
    - {CANONICAL_SCHEMA_VERSION}
  source_schema_versions:
    - "{SOURCE_SCHEMA_VERSION}"
"""


def label_spec_yaml(
    name: str = "forward_return",
    horizon: int = 5,
    unit: str = "BARS",
    cross_day: bool = False,
    output_type: str = "float64",
) -> str:
    boundary = (
        "  allow: true\n  boundary_rule: END_OF_TRADING_DAY"
        if cross_day
        else "  allow: false\n  boundary_rule: null"
    )
    return f"""\
spec_schema_version: market-vault-label-spec-v1
kind: LABEL
name: {name}
version: v1
output:
  name: {name}
  logical_type: {output_type}
  nullable: false
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.dataset.label_transforms.{name}:{name}
parameters: {{}}
requirements:
  canonical_schema_versions:
    - {CANONICAL_SCHEMA_VERSION}
  source_schema_versions:
    - "{SOURCE_SCHEMA_VERSION}"
observation_window:
  unit: {unit}
  start_offset: 0
  end_offset: {horizon}
horizon:
  unit: {unit}
  value: {horizon}
alignment_rule: ALIGN_CLOSE
missing_data_policy: INCOMPLETE
cross_trading_day:
{boundary}
"""


def split_spec_json() -> str:
    return json.dumps(
        {
            "spec_schema_version": "market-vault-chronological-split-spec-v1",
            "name": "chronological_split",
            "version": "v1",
            "boundary_timezone": "America/New_York",
            "train_end_date": "2026-06-30",
            "validation_end_date": "2026-07-15",
            "test_end_date": "2026-07-31",
            "assignment_rule": "FEATURE_WINDOW_CLOSE_DATE",
            "purge_rule": "ACTUAL_LABEL_END",
            "incomplete_label_policy": "EXCLUDE",
            "out_of_range_policy": "EXCLUDE",
        }
    )


def write_fixture_files(
    tmp_path,
    *,
    feature_specs=("simple_return",),
    label_specs=("forward_return",),
    horizon: int = 2,
    window_bars: int = 2,
) -> tuple:
    """Real Feature / Label YAML files and a split-spec JSON file; returns
    their absolute paths."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    feature_paths = []
    for name in feature_specs:
        path = spec_dir / f"{name}.yaml"
        path.write_text(feature_spec_yaml(name=name, window_bars=window_bars), encoding="utf-8")
        feature_paths.append(str(path))
    label_paths = []
    for name in label_specs:
        path = spec_dir / f"{name}.yaml"
        path.write_text(label_spec_yaml(name=name, horizon=horizon), encoding="utf-8")
        label_paths.append(str(path))
    split_path = spec_dir / "chronological_split.json"
    split_path.write_text(split_spec_json(), encoding="utf-8")
    return tuple(feature_paths), tuple(label_paths), str(split_path)


def write_candle_fixture(tmp_path, *, horizon: int = 1) -> tuple:
    """A candle_body-only fixture set (FIXED 1-bar lookback, no
    parameters), used where feature_window_bars == 1 (simple_return's
    window_bars lower bound is 2)."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    candle = spec_dir / "candle_body.yaml"
    candle.write_text(
        feature_spec_yaml(
            name="candle_body", inputs=("open", "close"), parameters={}
        ),
        encoding="utf-8",
    )
    label = spec_dir / "forward_return.yaml"
    label.write_text(label_spec_yaml(horizon=horizon), encoding="utf-8")
    split = spec_dir / "chronological_split.json"
    split.write_text(split_spec_json(), encoding="utf-8")
    return (str(candle),), (str(label),), str(split)


def make_plan(
    *,
    build_paths,
    feature_paths,
    label_paths,
    split_path,
    symbols=("US.MU",),
    trade_dates=(date(2026, 7, 1),),
    feature_window_bars: int = 3,
    label_window_bars: int = 2,
    stride_bars: int = 2,
    dataset_as_of=None,
    output_root: str = "datasets",
    built_at=BUILT_AT,
    output_plan_path: str = "plans/generated/plan-1.json",
) -> SampleGenerationPlan:
    return SampleGenerationPlan(
        generation_plan_schema_version=SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
        canonical_build_dirs=tuple(build_paths),
        feature_spec_files=tuple(feature_paths),
        label_spec_files=tuple(label_paths),
        split_spec_file=split_path,
        scope=DatasetScope(
            symbols=symbols,
            trade_dates=trade_dates,
            interval="1m",
            adjustment="NONE",
            requested_session="ALL",
        ),
        generation_rule=SampleGenerationRule(
            rule_schema_version=SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
            feature_window_bars=feature_window_bars,
            label_window_bars=label_window_bars,
            stride_bars=stride_bars,
            anchor_source="VERIFIED_CANONICAL_BARS",
            anchor_rule="FEATURE_WINDOW_CLOSE",
            cross_day_policy="REJECT",
        ),
        dataset_as_of=dataset_as_of,
        output_root=output_root,
        built_at=built_at,
        output_plan_path=output_plan_path,
    )


@pytest.fixture()
def std_fixture(tmp_path):
    """The standard fixture: one 10-bar build, one Feature spec
    (window_bars=2), one Label spec (horizon=5), one split spec; the plan
    uses feature_window_bars=3, label_window_bars=2, stride_bars=2."""
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )
    return {
        "tmp_path": tmp_path,
        "build": build,
        "feature_paths": feature_paths,
        "label_paths": label_paths,
        "split_path": split_path,
        "plan": plan,
    }


# ---------------------------------------------------------------------------
# A. Public models / API.
# ---------------------------------------------------------------------------


def test_result_is_frozen(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.requests = ()


def test_diagnostics_is_frozen(std_fixture):
    diagnostics = SampleGenerationDiagnostics(1, 10, 10, 1, 4, 3, 0, 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostics.generated_request_count = 0


def test_result_nested_sequences_are_tuples(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    assert type(result.requests) is tuple
    assert type(result.canonical_build_pins) is tuple
    assert type(result.feature_spec_pins) is tuple
    assert type(result.label_spec_pins) is tuple


def test_result_wrong_model_type_fails(std_fixture):
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(
            "not a plan", path_base=std_fixture["tmp_path"]  # type: ignore[arg-type]
        )


def test_core_public_exports_exact():
    import market_vault.dataset as dataset

    for name in (
        "SAMPLE_GENERATOR_CORE_VERSION",
        "SampleGenerationDiagnostics",
        "SampleGenerationResult",
        "generate_sample_requests",
    ):
        assert name in dataset.__all__


def test_core_version_exact():
    assert SAMPLE_GENERATOR_CORE_VERSION == "market-vault-sample-generator-core-v1"


def test_diagnostics_invariant():
    with pytest.raises(SampleGenerationError):
        SampleGenerationDiagnostics(1, 10, 10, 1, 4, 3, 0, 0)  # 4 != 3 + 0
    SampleGenerationDiagnostics(1, 10, 10, 1, 4, 3, 0, 1)  # 4 == 3 + 1


def test_result_requires_matching_request_count(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    with pytest.raises(SampleGenerationError):
        dataclasses.replace(
            result,
            diagnostics=SampleGenerationDiagnostics(
                1, 10, 10, 1, 4, 99, 0, 1
            ),
        )


# ---------------------------------------------------------------------------
# B. Real verified input chain.
# ---------------------------------------------------------------------------


def test_generates_through_real_verified_chain(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    assert result.generator_core_version == SAMPLE_GENERATOR_CORE_VERSION
    assert re.fullmatch(r"[0-9a-f]{64}", result.generation_content_id)
    assert result.requests
    assert len(result.canonical_build_pins) == 1
    assert len(result.feature_spec_pins) == 1
    assert len(result.label_spec_pins) == 1
    assert result.split_spec_pin.kind == "SPLIT"
    assert result.scope.symbols == ("US.MU",)
    assert result.scope.adjustment == "NONE"
    assert result.diagnostics.canonical_build_count == 1
    assert result.diagnostics.canonical_bar_count == 10
    assert result.diagnostics.in_scope_bar_count == 10
    assert result.diagnostics.contiguous_segment_count == 1
    assert result.diagnostics.generated_request_count == 3
    assert result.diagnostics.insufficient_label_future_count == 1


def test_canonical_build_pin_maps_verified_facts(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    pin = result.canonical_build_pins[0]
    build = std_fixture["build"]
    assert pin.canonical_build_id == build.canonical_build_id
    assert pin.canonical_content_id == build.canonical_content_id
    assert pin.canonical_builder_version == build.canonical_builder_version
    assert pin.canonical_schema_version == build.canonical_schema_version
    assert pin.materializer_version == build.materializer_version
    assert pin.gap_policy_version == build.gap_policy_version
    assert pin.gap_content_id == build.gap_content_id
    assert pin.status == build.status
    assert pin.canonical_row_version_ids == build.canonical_row_version_ids
    assert len(pin.source_snapshots) >= 1


def test_spec_pins_come_from_formal_identity(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    assert result.feature_spec_pins[0].kind == "FEATURE"
    assert result.label_spec_pins[0].kind == "LABEL"
    assert re.fullmatch(r"[0-9a-f]{64}", result.feature_spec_pins[0].content_sha256)
    assert re.fullmatch(r"[0-9a-f]{64}", result.label_spec_pins[0].content_sha256)


def test_missing_build_path_fails(tmp_path):
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(tmp_path / "does-not-exist"),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


def test_missing_spec_path_fails(tmp_path):
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=(str(tmp_path / "specs" / "missing.yaml"),),
        label_paths=label_paths,
        split_path=split_path,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


def test_path_base_is_required_explicitly(std_fixture):
    # No implicit default exists: a non-str/Path path_base fails.
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(std_fixture["plan"], path_base=None)  # type: ignore[arg-type]


def test_relative_plan_paths_resolve_against_path_base(tmp_path):
    """Relative plan paths are lexically joined to path_base (absolute
    paths are used as-is); the same files work through either form."""
    build = make_build(tmp_path, count=10)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    absolute_plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )
    relative_plan = make_plan(
        build_paths=(str(build.build_path.relative_to(tmp_path)),),
        feature_paths=tuple(
            str(Path(path).relative_to(tmp_path)) for path in feature_paths
        ),
        label_paths=tuple(
            str(Path(path).relative_to(tmp_path)) for path in label_paths
        ),
        split_path=str(Path(split_path).relative_to(tmp_path)),
    )
    result_abs = generate_sample_requests(absolute_plan, path_base=tmp_path)
    result_rel = generate_sample_requests(relative_plan, path_base=tmp_path)
    assert result_abs == result_rel


# ---------------------------------------------------------------------------
# C. Exact request geometry (1m bars; 09:30 NY == 13:30 UTC).
# ---------------------------------------------------------------------------


def test_exact_request_geometry(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    assert len(result.requests) == 3
    first, second, third = result.requests
    # Anchor index 2: feature [09:30, 09:31, 09:32], label [09:33, 09:34].
    assert first.code == "US.MU"
    assert first.interval == "1m"
    assert first.adjustment == "NONE"
    assert first.requested_session == "ALL"
    assert first.anchor_market_calendar_date == date(2026, 7, 1)
    assert first.feature_window_start == utc(13, 30)
    assert first.feature_window_close == utc(13, 33)
    assert first.label_window_start == utc(13, 33)
    assert first.label_window_close == utc(13, 35)
    # Anchor index 4: feature [09:32..09:34], label [09:35, 09:36].
    assert second.feature_window_start == utc(13, 32)
    assert second.feature_window_close == utc(13, 35)
    assert second.label_window_start == utc(13, 35)
    assert second.label_window_close == utc(13, 37)
    # Anchor index 6: feature [09:34..09:36], label [09:37, 09:38].
    assert third.feature_window_start == utc(13, 34)
    assert third.feature_window_close == utc(13, 37)
    assert third.label_window_start == utc(13, 37)
    assert third.label_window_close == utc(13, 39)
    # Canonical stable request order: feature_window_close ascending.
    closes = [request.feature_window_close for request in result.requests]
    assert closes == sorted(closes)


def test_frozen_request_tuple_regression(std_fixture):
    """The complete first request tuple is frozen as a regression value."""
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    first = result.requests[0]
    assert (
        first.code,
        first.interval,
        first.adjustment,
        first.requested_session,
        first.anchor_market_calendar_date,
        first.feature_window_start,
        first.feature_window_close,
        first.label_window_start,
        first.label_window_close,
    ) == (
        "US.MU",
        "1m",
        "NONE",
        "ALL",
        date(2026, 7, 1),
        utc(13, 30),
        utc(13, 33),
        utc(13, 33),
        utc(13, 35),
    )


# ---------------------------------------------------------------------------
# D. Stride semantics.
# ---------------------------------------------------------------------------


def test_stride_one_generates_maximal_anchors(tmp_path):
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        stride_bars=1,
        label_window_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    # Candidate anchors 2..9 (stride 1); the last anchor has no label bar:
    # 7 requests, 1 insufficient label future.
    assert result.diagnostics.generated_request_count == 7
    assert result.diagnostics.candidate_anchor_count == 8
    assert result.diagnostics.insufficient_label_future_count == 1


def test_stride_greater_than_one_skips_anchors(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    assert result.diagnostics.generated_request_count == 3
    anchors = [request.feature_window_close for request in result.requests]
    assert anchors == [utc(13, 33), utc(13, 35), utc(13, 37)]


def test_each_segment_has_its_own_stride_origin(tmp_path):
    """Two segments (gap-split) each start their stride at
    feature_window_bars - 1, so the second segment's first anchor is its own
    third bar."""
    build = make_gap_build(tmp_path)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=2,
        label_window_bars=1,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.contiguous_segment_count == 2
    # Each segment has exactly 1 bar, so no anchor can be established.
    assert result.diagnostics.generated_request_count == 0
    assert result.diagnostics.insufficient_feature_history_count == 2


def test_bar_input_order_does_not_affect_result(tmp_path):
    """Two builds with different codes: swapping canonical_build_dirs order
    never changes the result."""
    build_a = make_build(tmp_path, code="US.MU", count=10, run_id="run-a")
    build_b = make_build(
        tmp_path, code="US.NVDA", count=6, run_id="run-b",
        cfg=settings(tmp_path),
    )
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan_ab = make_plan(
        build_paths=(str(build_a.build_path), str(build_b.build_path)),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        symbols=("US.MU", "US.NVDA"),
    )
    plan_ba = make_plan(
        build_paths=(str(build_b.build_path), str(build_a.build_path)),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        symbols=("US.MU", "US.NVDA"),
    )
    result_ab = generate_sample_requests(plan_ab, path_base=tmp_path)
    result_ba = generate_sample_requests(plan_ba, path_base=tmp_path)
    assert result_ab == result_ba


# ---------------------------------------------------------------------------
# E. Gaps and segments.
# ---------------------------------------------------------------------------


def test_internal_gap_terminates_segment(tmp_path):
    build = make_gap_build(tmp_path)
    feature_paths, label_paths, split_path = write_candle_fixture(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=1,
        label_window_bars=1,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.contiguous_segment_count == 2
    # Each segment holds one bar; no request can be formed.
    assert result.diagnostics.generated_request_count == 0


def test_gap_sides_are_never_spliced(tmp_path):
    """Bars on both sides of a gap never join one window: with
    feature_window_bars=2 and a 09:30/09:32 gap build, the two bars are in
    different segments and produce no request."""
    build = make_gap_build(tmp_path)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=2,
        label_window_bars=1,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count == 0


def test_market_calendar_date_change_terminates_segment(tmp_path):
    build = make_two_date_build(tmp_path)
    feature_paths, label_paths, split_path = write_candle_fixture(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        trade_dates=(date(2026, 7, 1), date(2026, 7, 2)),
        feature_window_bars=1,
        label_window_bars=1,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.contiguous_segment_count == 2
    assert result.diagnostics.generated_request_count == 2
    assert {request.anchor_market_calendar_date for request in result.requests} == {
        date(2026, 7, 1),
        date(2026, 7, 2),
    }


def test_session_change_terminates_segment(tmp_path):
    build = make_multi_session_build(tmp_path)
    feature_paths, label_paths, split_path = write_candle_fixture(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=1,
        label_window_bars=1,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.contiguous_segment_count == 2
    # 09:30 and 16:00 are in different sessions; each segment has two
    # consecutive bars, so exactly one request per segment.
    assert result.diagnostics.generated_request_count == 2


def test_segment_restarts_deterministically_after_gap(tmp_path):
    """A gap build with a longer first segment: 09:30-09:31 and 09:34-09:36
    (gap at 09:32-09:33) yields two segments with independent stride
    origins."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap2",
        time_keys=minute_keys("2026-07-01 09:30:00", 2)
        + minute_keys("2026-07-01 09:34:00", 3),
    )
    build = load_verified_canonical_build(
        materialize(cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)]).build_path
    )
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=2,
        label_window_bars=1,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.contiguous_segment_count == 2
    # Segment 1: [09:30, 09:31] -> anchor 09:31 has no label bar left.
    # Segment 2: [09:34, 09:35, 09:36] -> anchor 09:35 (label 09:36);
    # anchor 09:36 has no label bar left.
    assert result.diagnostics.generated_request_count == 1
    assert result.diagnostics.insufficient_label_future_count == 2


# ---------------------------------------------------------------------------
# F. Insufficient windows.
# ---------------------------------------------------------------------------


def test_insufficient_feature_bars_produces_zero_requests(tmp_path):
    build = make_build(tmp_path, count=2)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=1)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=3,
        label_window_bars=1,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count == 0
    assert result.diagnostics.insufficient_feature_history_count == 1


def test_insufficient_label_future_produces_zero_requests(tmp_path):
    build = make_build(tmp_path, count=3)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=5)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=3,
        label_window_bars=5,
        stride_bars=1,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count == 0
    assert result.diagnostics.insufficient_label_future_count == 1
    assert result.diagnostics.candidate_anchor_count == 1


def test_empty_canonical_build_produces_zero_requests(tmp_path):
    build = make_empty_build(tmp_path)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count == 0
    assert result.requests == ()


def test_scope_key_without_bars_produces_zero_requests(tmp_path):
    build = make_build(tmp_path, code="US.MU", count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        symbols=("US.OTHER",),
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count == 0
    assert result.diagnostics.in_scope_bar_count == 0


# ---------------------------------------------------------------------------
# G. Feature BARS coverage.
# ---------------------------------------------------------------------------


def test_feature_window_bars_cover_parameter_lookback(tmp_path):
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, window_bars=2)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=2,
        label_window_bars=2,
        stride_bars=2,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count >= 1


def test_feature_window_bars_smaller_than_parameter_lookback_fails(tmp_path):
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, window_bars=4)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=3,
        label_window_bars=2,
        stride_bars=2,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


def test_fixed_lookback_coverage(tmp_path):
    """candle_range declares a FIXED 1-bar lookback; feature_window_bars=1
    covers it."""
    build = make_build(tmp_path, count=10)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    candle = spec_dir / "candle_range.yaml"
    candle.write_text(
        feature_spec_yaml(
            name="candle_range", inputs=("high", "low"), parameters={}
        ),
        encoding="utf-8",
    )
    label = spec_dir / "forward_return.yaml"
    label.write_text(label_spec_yaml(horizon=2), encoding="utf-8")
    split = spec_dir / "chronological_split.json"
    split.write_text(split_spec_json(), encoding="utf-8")
    feature_paths, label_paths, split_path = (str(candle),), (str(label),), str(split)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=1,
        label_window_bars=2,
        stride_bars=2,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count >= 1


def test_multiple_features_take_maximum_requirement(tmp_path):
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(
        tmp_path,
        feature_specs=("simple_return", "rolling_mean"),
        window_bars=2,
    )
    # simple_return declares window_bars=2; rolling_mean declares
    # window_bars=1 (default contract). Required = max = 2.
    plan_ok = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=2,
        label_window_bars=2,
        stride_bars=2,
    )
    result = generate_sample_requests(plan_ok, path_base=tmp_path)
    assert result.diagnostics.generated_request_count >= 1
    plan_bad = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=1,
        label_window_bars=2,
        stride_bars=2,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan_bad, path_base=tmp_path)


def test_bool_or_zero_parameter_cannot_bypass_registry(tmp_path):
    """An invalid parameter value fails the formal registry preflight
    (converted to SampleGenerationError), never reaching coverage math."""
    build = make_build(tmp_path, count=10)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    bad = spec_dir / "bad.yaml"
    bad.write_text(
        feature_spec_yaml(name="simple_return", window_bars=0), encoding="utf-8"
    )
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=(str(bad),),
        label_paths=label_paths,
        split_path=split_path,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


# ---------------------------------------------------------------------------
# H. Label BARS coverage.
# ---------------------------------------------------------------------------


def test_label_horizon_within_window_succeeds(tmp_path):
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=5)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=3,
        label_window_bars=5,
        stride_bars=2,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count >= 1


def test_label_horizon_exceeding_window_fails(tmp_path):
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path, horizon=6)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        label_window_bars=5,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


def test_label_minutes_fails(tmp_path):
    build = make_build(tmp_path, count=10)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    bad = spec_dir / "minutes_label.yaml"
    bad.write_text(
        label_spec_yaml(name="forward_return", horizon=5, unit="MINUTES"),
        encoding="utf-8",
    )
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=(str(bad),),
        split_path=split_path,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


def test_label_trading_days_fails(tmp_path):
    build = make_build(tmp_path, count=10)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    bad = spec_dir / "trading_days_label.yaml"
    bad.write_text(
        label_spec_yaml(name="forward_return", horizon=1, unit="TRADING_DAYS"),
        encoding="utf-8",
    )
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=(str(bad),),
        split_path=split_path,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


def test_label_cross_trading_day_true_fails(tmp_path):
    build = make_build(tmp_path, count=10)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    bad = spec_dir / "cross_day_label.yaml"
    bad.write_text(
        label_spec_yaml(name="forward_return", horizon=5, cross_day=True),
        encoding="utf-8",
    )
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=(str(bad),),
        split_path=split_path,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


def test_multiple_labels_take_maximum_horizon(tmp_path):
    build = make_build(tmp_path, count=10)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    direction = spec_dir / "forward_direction.yaml"
    direction.write_text(
        label_spec_yaml(
            name="forward_direction", horizon=3, output_type="int64"
        ),
        encoding="utf-8",
    )
    feature_paths, label_paths, split_path = write_fixture_files(
        tmp_path, horizon=3
    )
    label_paths = (str(direction),) + label_paths
    plan = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=3,
        label_window_bars=3,
        stride_bars=2,
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.diagnostics.generated_request_count >= 1
    plan_bad = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        feature_window_bars=3,
        label_window_bars=2,
        stride_bars=2,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan_bad, path_base=tmp_path)


# ---------------------------------------------------------------------------
# I. Duplicate rejection (overlapping verified inputs).
# ---------------------------------------------------------------------------


def test_duplicate_canonical_build_id_fails(tmp_path):
    """Two verified builds with the same logical content (overlapping
    inputs) fail closed; nothing is silently deduplicated."""
    build_one, build_two = make_duplicate_logical_builds(tmp_path)
    assert build_one.canonical_build_id == build_two.canonical_build_id
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan = make_plan(
        build_paths=(str(build_one.build_path), str(build_two.build_path)),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )
    with pytest.raises(SampleGenerationError):
        generate_sample_requests(plan, path_base=tmp_path)


# ---------------------------------------------------------------------------
# J. Generation identity.
# ---------------------------------------------------------------------------


def test_identity_is_64_character_lowercase_hex(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    assert len(result.generation_content_id) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", result.generation_content_id)


def test_identity_frozen_fixture(std_fixture):
    result = generate_sample_requests(std_fixture["plan"], path_base=std_fixture["tmp_path"])
    assert result.generation_content_id == FIXTURE_GENERATION_ID


def _recompute_with(std_fixture, tmp_path, **plan_changes):
    plan = make_plan(
        build_paths=plan_changes.pop(
            "build_paths", (str(std_fixture["build"].build_path),)
        ),
        feature_paths=std_fixture["feature_paths"],
        label_paths=std_fixture["label_paths"],
        split_path=std_fixture["split_path"],
        **plan_changes,
    )
    return generate_sample_requests(plan, path_base=tmp_path)


def test_identity_output_root_change_does_not_change(std_fixture, tmp_path):
    base = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    other = _recompute_with(std_fixture, tmp_path, output_root="elsewhere")
    assert other.generation_content_id == base.generation_content_id


def test_identity_built_at_change_does_not_change(std_fixture, tmp_path):
    base = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    other = _recompute_with(
        std_fixture, tmp_path, built_at=BUILT_AT + timedelta(days=1)
    )
    assert other.generation_content_id == base.generation_content_id


def test_identity_output_plan_path_change_does_not_change(std_fixture, tmp_path):
    base = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    other = _recompute_with(std_fixture, tmp_path, output_plan_path="plans/other.json")
    assert other.generation_content_id == base.generation_content_id


def test_identity_path_base_change_does_not_change(tmp_path):
    """Relocating the whole fixture tree (path_base) with identical content
    never changes the identity."""
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan_a = make_plan(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )
    result_a = generate_sample_requests(plan_a, path_base=tmp_path)
    # The same absolute paths with a different path_base still resolve to
    # the same files, so the identity is unchanged.
    result_b = generate_sample_requests(plan_a, path_base=Path(tmp_path) / "..")
    assert result_a.generation_content_id == result_b.generation_content_id


def test_identity_dataset_as_of_semantic_change_changes(std_fixture, tmp_path):
    base = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    other = _recompute_with(
        std_fixture, tmp_path, dataset_as_of=datetime(2026, 8, 1, tzinfo=UTC)
    )
    assert other.generation_content_id != base.generation_content_id


def test_identity_timezone_equivalence(std_fixture, tmp_path):
    base = _recompute_with(
        std_fixture, tmp_path, dataset_as_of=datetime(2026, 8, 1, tzinfo=UTC)
    )
    other = _recompute_with(
        std_fixture,
        tmp_path,
        dataset_as_of=datetime(2026, 8, 1, 9, 0, tzinfo=timezone(timedelta(hours=9))),
    )
    assert other.generation_content_id == base.generation_content_id


def test_identity_scope_change_changes(std_fixture, tmp_path):
    base = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    other = _recompute_with(
        std_fixture, tmp_path, trade_dates=(date(2026, 7, 1), date(2026, 7, 2))
    )
    assert other.generation_content_id != base.generation_content_id


def test_identity_rule_change_changes(std_fixture, tmp_path):
    base = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    other = _recompute_with(std_fixture, tmp_path, stride_bars=1)
    assert other.generation_content_id != base.generation_content_id


def test_identity_spec_content_change_changes(std_fixture, tmp_path):
    base = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    build = make_build(tmp_path, count=10, run_id="run-other")
    other = _recompute_with(
        std_fixture, tmp_path, build_paths=(str(build.build_path),)
    )
    assert other.generation_content_id != base.generation_content_id


def test_identity_canonical_build_change_changes(tmp_path):
    build_a = make_build(tmp_path, code="US.MU", count=10, run_id="run-a")
    build_b = make_build(
        tmp_path, code="US.NVDA", count=10, run_id="run-b", cfg=settings(tmp_path)
    )
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan_a = make_plan(
        build_paths=(str(build_a.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        symbols=("US.MU",),
    )
    plan_b = make_plan(
        build_paths=(str(build_b.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        symbols=("US.NVDA",),
    )
    assert (
        generate_sample_requests(plan_a, path_base=tmp_path).generation_content_id
        != generate_sample_requests(plan_b, path_base=tmp_path).generation_content_id
    )


def test_identity_input_order_invariance(std_fixture, tmp_path):
    result = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    # The identity is computed from the normalized pins; the result pins are
    # exactly the identity's normalized pins.
    from market_vault.dataset import SampleGenerationIdentityInput

    identity_input = SampleGenerationIdentityInput(
        canonical_build_pins=tuple(reversed(result.canonical_build_pins)),
        feature_spec_pins=tuple(reversed(result.feature_spec_pins)),
        label_spec_pins=tuple(reversed(result.label_spec_pins)),
        split_spec_pin=result.split_spec_pin,
        scope=result.scope,
        generation_rule=result.generation_rule,
        dataset_as_of=result.dataset_as_of,
    )
    from market_vault.dataset import sample_generation_content_id

    assert sample_generation_content_id(identity_input) == result.generation_content_id


# ---------------------------------------------------------------------------
# K. No side effects.
# ---------------------------------------------------------------------------


def test_no_current_time_anywhere(std_fixture, monkeypatch, tmp_path):
    from datetime import datetime as _real_datetime

    import market_vault.dataset.sample_generation_core_models as core_models

    class _NoNowDatetime(_real_datetime):
        @classmethod
        def now(cls, *args, **kwargs):
            pytest.fail("current time must never be read")

        @classmethod
        def utcnow(cls, *args, **kwargs):
            pytest.fail("current time must never be read")

    monkeypatch.setattr(core_models, "datetime", _NoNowDatetime)
    result = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    assert result.requests


def test_no_settings_network_or_opend(std_fixture, monkeypatch, tmp_path):
    import market_vault.config as config
    import socket

    monkeypatch.setattr(
        config, "load_settings", lambda *a, **k: pytest.fail("settings must not load")
    )
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("no network"))
    result = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    assert result.requests


def test_no_dataset_orchestration_materialization_or_reader(std_fixture, monkeypatch, tmp_path):
    from market_vault.dataset import materialization, orchestration, reader

    monkeypatch.setattr(
        orchestration,
        "orchestrate_dataset_build",
        lambda *a, **k: pytest.fail("orchestration must not be called"),
    )
    monkeypatch.setattr(
        materialization,
        "materialize_dataset_artifacts",
        lambda *a, **k: pytest.fail("materialization must not be called"),
    )
    monkeypatch.setattr(
        reader,
        "load_verified_dataset",
        lambda *a, **k: pytest.fail("verified reader must not be called"),
    )
    result = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    assert result.requests


def test_no_file_writes(std_fixture, monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(
        Path, "write_bytes", lambda self, *a, **k: pytest.fail("no file writes")
    )
    monkeypatch.setattr(
        Path, "write_text", lambda self, *a, **k: pytest.fail("no file writes")
    )
    result = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    assert result.requests


def test_no_cli_registration():
    text = (ROOT / "src" / "market_vault" / "cli.py").read_text(encoding="utf-8")
    assert "sample-generate" not in text
    text = (ROOT / "src" / "market_vault" / "dataset" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "sample-generate" not in text


def test_core_sources_have_no_forbidden_calls():
    sources = []
    for rel in (
        "src/market_vault/dataset/sample_generation_core.py",
        "src/market_vault/dataset/sample_generation_core_models.py",
    ):
        sources.append((ROOT / rel).read_text(encoding="utf-8"))
    text = "\n".join(sources)
    for forbidden in (
        "datetime.now",
        "datetime.utcnow",
        "Path.cwd",
        "random",
        "uuid",
        "urllib",
        "socket",
        "requests.",
        "load_settings",
        "rglob",
        "glob",
        "iterdir",
        "orchestrate_dataset_build",
        "materialize_dataset_artifacts",
        "load_verified_dataset",
        "write_text",
        "write_bytes",
        'open(..., "w")',
    ):
        assert forbidden not in text, f"forbidden token {forbidden!r} in core sources"


# ---------------------------------------------------------------------------
# L. Determinism.
# ---------------------------------------------------------------------------


def test_repeated_generation_is_identical(std_fixture, tmp_path):
    first = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    second = generate_sample_requests(std_fixture["plan"], path_base=tmp_path)
    assert second == first
    assert second.requests == first.requests
    assert second.generation_content_id == first.generation_content_id
    assert second.diagnostics == first.diagnostics


def test_shuffled_input_orders_give_identical_results(tmp_path):
    build_a = make_build(tmp_path, code="US.MU", count=10, run_id="run-a")
    build_b = make_build(
        tmp_path, code="US.NVDA", count=6, run_id="run-b", cfg=settings(tmp_path)
    )
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plan_a = make_plan(
        build_paths=(str(build_a.build_path), str(build_b.build_path)),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
        symbols=("US.MU", "US.NVDA"),
        trade_dates=(date(2026, 7, 1),),
    )
    plan_b = make_plan(
        build_paths=(str(build_b.build_path), str(build_a.build_path)),
        feature_paths=tuple(reversed(feature_paths)),
        label_paths=tuple(reversed(label_paths)),
        split_path=split_path,
        symbols=("US.NVDA", "US.MU"),
        trade_dates=(date(2026, 7, 1),),
    )
    result_a = generate_sample_requests(plan_a, path_base=tmp_path)
    result_b = generate_sample_requests(plan_b, path_base=tmp_path)
    assert result_a == result_b
