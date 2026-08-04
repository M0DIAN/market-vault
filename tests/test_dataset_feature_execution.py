"""Offline deterministic tests for the built-in Feature execution core
(v0.5.0 PR-3).

Covers the built-in registrations, the eight basic OHLCV transforms and
their exact formulas, domain failures, PIT row binding and clock checks,
trailing-window and contiguity validation, explicit COMPLETE / EXCLUDED
results, the frozen result models, execution determinism, and the
offline / no-side-effect boundary. All fixtures are micro offline canonical
builds produced through the verified reader and materializer with synthetic
data; no network, no OpenD, no current time, and no real market data.
"""

from __future__ import annotations

import hashlib
import linecache
import math
import os
import re
import sys
import time
import types
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.canonical.schema import CANONICAL_SCHEMA_VERSION
from market_vault.dataset import (
    FEATURE_EXECUTION_CONTRACT_VERSION,
    FEATURE_EXCLUSION_CROSS_MARKET_DATE,
    FEATURE_EXCLUSION_INSUFFICIENT_ROWS,
    FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS,
    FEATURE_SPEC_SCHEMA_VERSION,
    FEATURE_TRANSFORM_CALL_CONTRACT_VERSION,
    FEATURE_VALUE_STATUS_COMPLETE,
    FEATURE_VALUE_STATUS_EXCLUDED,
    LABEL_SPEC_SCHEMA_VERSION,
    MISSING_POLICY_EXCLUDE_SAMPLE,
    PIT_ASSEMBLER_VERSION,
    SPEC_KIND_FEATURE,
    BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
    CanonicalBuildPin,
    CrossTradingDayPolicy,
    SourceSnapshotPin,
    DatasetField,
    FeatureExecutionDiagnostics,
    FeatureExecutionError,
    FeatureExecutionResult,
    FeatureSampleResult,
    FeatureSpec,
    FeatureTransformInput,
    FeatureValueResult,
    ImplementationPin,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITAssemblyDiagnostics,
    PITAssemblyResult,
    PITDiagnostics,
    PITSample,
    PITSampleRequest,
    SpecParameter,
    SpecPin,
    SpecVersionRequirements,
    TransformRegistration,
    TransformRegistry,
    TransformRegistryError,
    TransformWindowRequirement,
    assemble_point_in_time_samples,
    built_in_feature_registrations,
    built_in_feature_registry,
    dataset_schema_id,
    execute_builtin_features,
    feature_label_spec_pin,
    logical_dataset_content_id,
    pit_association_schema,
    pit_sample_key,
    pit_sample_version_id,
    transform_implementation_fingerprint,
    transform_implementation_pin,
)
from market_vault.dataset import WINDOW_BOUNDARY_INCLUSIVE, WINDOW_SOURCE_FIXED, WINDOW_SOURCE_NONE, WINDOW_SOURCE_PARAMETER, WINDOW_UNIT_BARS, WINDOW_UNIT_NONE
from market_vault.dataset.feature_execution import _validate_output_value
from market_vault.dataset.feature_transforms import (
    candle_body,
    candle_range,
    log_return,
    rolling_mean,
    rolling_std,
    rolling_volume_mean,
    simple_return,
    volume_ratio,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"

REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_LOG = "market_vault.dataset.feature_transforms.log_return:log_return"
REF_MEAN = "market_vault.dataset.feature_transforms.rolling_mean:rolling_mean"
REF_STD = "market_vault.dataset.feature_transforms.rolling_std:rolling_std"
REF_VMEAN = "market_vault.dataset.feature_transforms.rolling_volume_mean:rolling_volume_mean"
REF_VRATIO = "market_vault.dataset.feature_transforms.volume_ratio:volume_ratio"
REF_RANGE = "market_vault.dataset.feature_transforms.candle_range:candle_range"
REF_BODY = "market_vault.dataset.feature_transforms.candle_body:candle_body"

ALL_REFS = (
    REF_SIMPLE,
    REF_LOG,
    REF_MEAN,
    REF_STD,
    REF_VMEAN,
    REF_VRATIO,
    REF_RANGE,
    REF_BODY,
)

_SHA_HEX = re.compile(r"^[0-9a-f]{64}$")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_key() -> CanonicalRequestKey:
    return CanonicalRequestKey(
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )


# ---------------------------------------------------------------------------
# Offline canonical-build fixtures (mirrors the PIT assembly tests; every
# fixture goes through the verified reader, never a plain object).
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
        (base + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(count)
    ]


def write_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    time_keys: list[str],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
    volumes: list[float] | None = None,
    run_finished_at: datetime | None = None,
) -> None:
    count = len(time_keys)
    opens = opens or [100.0] * count
    highs = highs or [101.0] * count
    lows = lows or [99.0] * count
    closes = closes or [100.5] * count
    volumes = volumes or [100.0] * count
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = pd.DataFrame(
        {
            "code": [code] * count,
            "name": [code] * count,
            "time_key": time_keys,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
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
    run.finished_at = run_finished_at or datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize(cfg: Settings, *, symbols=None, trade_dates=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=default_key(),
        output_root=output_root(cfg),
        created_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def verified(build_result):
    return load_verified_canonical_build(build_result.build_path)


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    """One shared offline catalog with all micro builds:

    ``a``  US.MU 2026-07-01 09:30..09:35 NY, per-bar OHLCV:
          opens 100,102,110,112,118,120; highs 105,108,115,120,122,125;
          lows 95,98,100,105,110,115; closes 100,110,112,118,120,110;
          volumes 100,200,300,400,500,600; archived 14:00Z
    ``b``  US.MU 2026-07-01 09:36..09:37 NY (label-window rows), archived 14:00Z
    ``g``  US.MU 2026-07-01 09:30 + 09:32 NY (one internal gap), archived 14:00Z
    ``d``  US.NVDA 2026-07-02 09:30..09:31 NY, archived 2026-07-02T14:00Z
    ``zero``  US.MU 2026-07-01 09:30..09:31 NY, closes 0,110
    ``neg``   US.MU 2026-07-01 09:30..09:31 NY, closes -5,110
    ``volzero``  US.MU 2026-07-01 09:30..09:31 NY, volumes 0,100
    """
    root = tmp_path_factory.mktemp("mv_feature_execution")
    cfg = settings(root)
    calendar(cfg)
    calendar(cfg, trade_date=date(2026, 7, 2))

    def build(code, trade_date, run_id, time_keys, **kwargs):
        write_snapshot(
            cfg, code=code, trade_date=trade_date, run_id=run_id,
            time_keys=time_keys, **kwargs,
        )
        return verified(
            materialize(cfg, symbols=[code], trade_dates=[trade_date])
        )

    a = build(
        "US.MU", date(2026, 7, 1), "run-a", minute_keys("2026-07-01 09:30:00", 6),
        opens=[100.0, 102.0, 110.0, 112.0, 118.0, 120.0],
        highs=[105.0, 108.0, 115.0, 120.0, 122.0, 125.0],
        lows=[95.0, 98.0, 100.0, 105.0, 110.0, 115.0],
        closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
        volumes=[100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
    )
    b = build(
        "US.MU", date(2026, 7, 1), "run-b", minute_keys("2026-07-01 09:36:00", 2),
    )
    g = build(
        "US.MU", date(2026, 7, 1), "run-gap",
        minute_keys("2026-07-01 09:30:00", 1) + minute_keys("2026-07-01 09:32:00", 1),
    )
    d = build(
        "US.NVDA", date(2026, 7, 2), "run-d", minute_keys("2026-07-02 09:30:00", 2),
        run_finished_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC),
    )
    zero = build(
        "US.MU", date(2026, 7, 1), "run-zero",
        minute_keys("2026-07-01 09:30:00", 2), closes=[0.0, 110.0],
    )
    neg = build(
        "US.MU", date(2026, 7, 1), "run-neg",
        minute_keys("2026-07-01 09:30:00", 2), closes=[-5.0, 110.0],
    )
    volzero = build(
        "US.MU", date(2026, 7, 1), "run-volzero",
        minute_keys("2026-07-01 09:30:00", 2), volumes=[0.0, 100.0],
    )
    return SimpleNamespace(a=a, b=b, g=g, d=d, zero=zero, neg=neg, volzero=volzero)


# ---------------------------------------------------------------------------
# Spec / request / hand-built PIT result helpers.
# ---------------------------------------------------------------------------


def feature_spec(
    name: str,
    transform_ref: str,
    fields: tuple[str, ...],
    *,
    parameters=(),
    canonical=("market-bars-canonical-schema-v1",),
    source=("10.9",),
) -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=fields,
        transform_ref=transform_ref,
        parameters=parameters,
        requirements=SpecVersionRequirements(
            canonical_schema_versions=canonical, source_schema_versions=source
        ),
    )


def wb(value: int) -> SpecParameter:
    return SpecParameter("window_bars", value)


def request(
    *,
    code: str = "US.MU",
    interval: str = "1m",
    adjustment: str = "NONE",
    requested_session: str = "ALL",
    anchor: date = date(2026, 7, 1),
    feature_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
    feature_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    label_start=None,
    label_close=None,
) -> PITSampleRequest:
    return PITSampleRequest(
        code=code,
        interval=interval,
        adjustment=adjustment,
        requested_session=requested_session,
        anchor_market_calendar_date=anchor,
        feature_window_start=feature_start,
        feature_window_close=feature_close,
        label_window_start=label_start,
        label_window_close=label_close,
    )


def assemble(builds, requests, *, dataset_as_of=None) -> PITAssemblyResult:
    return assemble_point_in_time_samples(builds, requests, dataset_as_of=dataset_as_of)


def hand_sample(
    builds,
    versions,
    req: PITSampleRequest,
    *,
    dataset_as_of=None,
    label_versions=(),
    considered=None,
) -> PITSample:
    considered = (
        tuple(sorted({build.canonical_build_id for build in builds}))
        if considered is None
        else tuple(considered)
    )
    key = pit_sample_key(req)
    version_id = pit_sample_version_id(
        sample_key=key,
        dataset_as_of=dataset_as_of,
        feature_canonical_row_version_ids=versions,
        label_canonical_row_version_ids=label_versions,
        considered_canonical_build_ids=considered,
        assembler_version=PIT_ASSEMBLER_VERSION,
    )
    return PITSample(
        sample_key=key,
        sample_version_id=version_id,
        request=req,
        dataset_as_of=dataset_as_of,
        feature_canonical_row_version_ids=versions,
        label_canonical_row_version_ids=label_versions,
        considered_canonical_build_ids=considered,
        diagnostics=PITDiagnostics(
            feature_candidate_count=len(versions),
            feature_selected_count=len(versions),
            feature_market_future_excluded_count=0,
            feature_archive_future_excluded_count=0,
            label_candidate_count=len(label_versions),
            label_selected_count=len(label_versions),
            label_market_future_excluded_count=0,
            label_archive_future_excluded_count=0,
            known_feature_gap_ids=(),
            known_label_gap_ids=(),
            empty_observation_window=not versions,
        ),
    )


def source_snapshot_of(bar) -> SourceSnapshotPin:
    """The source snapshot pin of one canonical bar, mirroring the PIT
    ``_build_pins`` rule."""
    return SourceSnapshotPin(
        ingestion_run_id=bar.ingestion_run_id,
        physical_snapshot_hash=bar.physical_snapshot_hash,
        logical_source_rows_hash=bar.logical_source_rows_hash,
        source_schema_version=bar.source_schema_version,
        requested_trade_date=bar.requested_trade_date,
        requested_session=bar.requested_session,
    )


def make_pin(
    build,
    selected,
    bars_by_version,
    *,
    row_versions=None,
    source_snapshots=None,
    **overrides,
) -> CanonicalBuildPin:
    """A canonical build pin for ``build`` over the selected row versions,
    reconstructing the source snapshots from the actual bars; overrides
    allow deliberate tampering for the fail-closed tests."""
    selected_for_build = (
        tuple(sorted(selected & set(build.canonical_row_version_ids)))
        if row_versions is None
        else tuple(sorted(row_versions))
    )
    snapshots = source_snapshots
    if snapshots is None:
        snapshots = [
            source_snapshot_of(bars_by_version[version])
            for version in selected_for_build
        ]
    fields = dict(
        canonical_build_id=build.canonical_build_id,
        canonical_content_id=build.canonical_content_id,
        canonical_builder_version=build.canonical_builder_version,
        canonical_schema_version=build.canonical_schema_version,
        materializer_version=build.materializer_version,
        gap_policy_version=build.gap_policy_version,
        gap_content_id=build.gap_content_id,
        status=build.status,
        canonical_row_version_ids=selected_for_build,
        source_snapshots=snapshots,
    )
    fields.update(overrides)
    return CanonicalBuildPin(**fields)


def hand_result(
    builds,
    samples,
    *,
    pins=None,
    row_version_ids=None,
    considered_diagnostics=None,
) -> PITAssemblyResult:
    """A PITAssemblyResult whose pins are exactly reconstructed from
    ``builds`` and the samples' selected rows (mirroring the PIT
    ``_build_pins`` rule) unless overridden. Used to exercise the
    executor's defensive invariants that the PIT assembler already
    guarantees on its legal path."""
    selected = set()
    for sample in samples:
        selected.update(sample.feature_canonical_row_version_ids)
        selected.update(sample.label_canonical_row_version_ids)
    bars_by_version = {
        bar.canonical_row_version_id: bar
        for build in builds
        for bar in build.bars
    }
    if pins is None:
        pins = [make_pin(build, selected, bars_by_version) for build in builds]
    schema = pit_association_schema()
    return PITAssemblyResult(
        samples=tuple(samples),
        canonical_build_pins=tuple(pins),
        canonical_row_version_ids=(
            tuple(sorted(selected))
            if row_version_ids is None
            else tuple(row_version_ids)
        ),
        gap_references=(),
        association_schema=schema,
        association_rows=(),
        association_schema_id=dataset_schema_id(schema),
        association_content_id=logical_dataset_content_id(schema, ()),
        diagnostics=PITAssemblyDiagnostics(
            sample_count=len(samples),
            total_feature_rows=sum(
                len(sample.feature_canonical_row_version_ids) for sample in samples
            ),
            total_label_rows=sum(
                len(sample.label_canonical_row_version_ids) for sample in samples
            ),
            feature_market_future_excluded_count=0,
            feature_archive_future_excluded_count=0,
            label_market_future_excluded_count=0,
            label_archive_future_excluded_count=0,
            considered_canonical_build_ids=(
                tuple(sorted({build.canonical_build_id for build in builds}))
                if considered_diagnostics is None
                else tuple(considered_diagnostics)
            ),
        ),
    )


def last_versions(build, count: int) -> tuple[str, ...]:
    return tuple(bar.canonical_row_version_id for bar in build.bars[-count:])


def bar_of(build, event_time_text: str):
    for bar in build.bars:
        if bar.event_time.strftime("%Y-%m-%d %H:%M:%S") == event_time_text:
            return bar
    raise AssertionError(f"no bar at {event_time_text} in {build.canonical_build_id}")


def executed_value(result: FeatureExecutionResult, sample_key: str, feature_name: str):
    for sample in result.samples:
        if sample.sample_key == sample_key:
            for value in sample.values:
                if value.feature_name == feature_name:
                    return value
            raise AssertionError(f"no feature {feature_name} in sample {sample_key}")
    raise AssertionError(f"no sample {sample_key}")


# ---------------------------------------------------------------------------
# A. Built-in registrations.
# ---------------------------------------------------------------------------


def test_builtin_registrations_all_present():
    registrations = built_in_feature_registrations()
    assert len(registrations) == 8
    assert tuple(reg.transform_ref for reg in registrations) == tuple(sorted(ALL_REFS))
    assert set(reg.transform_ref for reg in registrations) == set(ALL_REFS)


def test_builtin_registrations_no_aliases_or_short_names():
    for reg in built_in_feature_registrations():
        assert ":" in reg.transform_ref
        short = reg.transform_ref.rsplit(":", 1)[1]
        assert reg.transform_ref != short
        assert not any(
            other.transform_ref.rsplit(":", 1)[1] == short
            and other.transform_ref != reg.transform_ref
            for other in built_in_feature_registrations()
        )


def test_builtin_registrations_stable_sorting_and_repeatable():
    first = built_in_feature_registrations()
    second = built_in_feature_registrations()
    assert first == second
    refs = [reg.transform_ref for reg in first]
    assert refs == sorted(refs)


def test_builtin_registration_shared_metadata():
    for reg in built_in_feature_registrations():
        assert reg.kind == SPEC_KIND_FEATURE
        assert reg.implementation_version == "v1"
        assert reg.output_logical_type == "float64"
        assert reg.output_nullable is False
        assert reg.lookforward.source == WINDOW_SOURCE_NONE
        assert reg.lookforward.unit == WINDOW_UNIT_NONE
        assert reg.lookforward.value is None
        assert reg.lookforward.parameter_name is None
        assert reg.boundary_policy == BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE
        assert reg.missing_policy == MISSING_POLICY_EXCLUDE_SAMPLE
        assert reg.supported_canonical_schema_versions == (CANONICAL_SCHEMA_VERSION,)
        assert reg.supported_source_schema_versions == ("10.9",)
        assert reg.display_name


def test_contract_version_constants():
    assert FEATURE_EXECUTION_CONTRACT_VERSION == "market-vault-feature-execution-v1"
    assert FEATURE_TRANSFORM_CALL_CONTRACT_VERSION == "market-vault-feature-transform-call-v1"


def test_builtin_registration_input_fields_and_windows():
    expected = {
        REF_SIMPLE: (("close",), "PARAMETER", "window_bars", 2),
        REF_LOG: (("close",), "PARAMETER", "window_bars", 2),
        REF_MEAN: (("close",), "PARAMETER", "window_bars", 1),
        REF_STD: (("close",), "PARAMETER", "window_bars", 2),
        REF_VMEAN: (("volume",), "PARAMETER", "window_bars", 1),
        REF_VRATIO: (("volume",), "PARAMETER", "window_bars", 2),
        REF_RANGE: (("high", "low"), "FIXED", None, 1),
        REF_BODY: (("open", "close"), "FIXED", None, 1),
    }
    for reg in built_in_feature_registrations():
        fields, source, parameter_name, value = expected[reg.transform_ref]
        assert reg.input_canonical_fields == fields
        lookback = reg.lookback
        assert lookback.source == source
        assert lookback.unit == WINDOW_UNIT_BARS
        assert lookback.boundary == WINDOW_BOUNDARY_INCLUSIVE
        assert lookback.parameter_name == parameter_name
        if source == WINDOW_SOURCE_PARAMETER:
            assert lookback.value is None
            (contract,) = reg.parameters
            assert contract.name == "window_bars"
            assert contract.value_type == "int64"
            assert contract.nullable is False
            assert contract.lower_bound == value
            assert contract.upper_bound is None
            assert contract.allowed_values is None
        else:
            assert lookback.value == value
            assert reg.parameters == ()


def test_builtin_registry_immutable_and_exact():
    registry = built_in_feature_registry()
    assert len(registry.registrations) == 8
    with pytest.raises(FrozenInstanceError):
        registry.registrations = ()
    with pytest.raises(AttributeError):
        registry.register = lambda spec: None  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        registry.replace = lambda spec: None  # type: ignore[attr-defined]


def test_builtin_registry_duplicate_registration_impossible():
    registrations = built_in_feature_registrations()
    with pytest.raises(TransformRegistryError):
        TransformRegistry(registrations + registrations[:1])


def test_implementation_pin_deterministic():
    pins = [
        transform_implementation_pin(reg) for reg in built_in_feature_registrations()
    ]
    pins_again = [
        transform_implementation_pin(reg) for reg in built_in_feature_registrations()
    ]
    assert pins == pins_again
    for pin in pins:
        assert _SHA_HEX.fullmatch(pin.content_sha256)
        assert pin.version == "v1"
        assert pin.name in ALL_REFS
        assert pin == ImplementationPin(name=pin.name, version="v1", content_sha256=pin.content_sha256)


# ---------------------------------------------------------------------------
# B. Exact formulas over the shared fixture (window [13:30, 13:36) UTC).
# ---------------------------------------------------------------------------


def test_formula_simple_return(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))],
    )
    value = executed_value(result, pit_sample_key(request()), "sr")
    assert value.status == FEATURE_VALUE_STATUS_COMPLETE
    assert value.value == 110.0 / 120.0 - 1.0


def test_formula_simple_return_full_window(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(6),))],
    )
    value = executed_value(result, pit_sample_key(request()), "sr")
    assert value.value == 110.0 / 100.0 - 1.0


def test_formula_log_return(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("lr", REF_LOG, ("close",), parameters=(wb(2),))],
    )
    value = executed_value(result, pit_sample_key(request()), "lr")
    assert value.value == math.log(110.0 / 120.0)


def test_formula_rolling_mean(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("rm", REF_MEAN, ("close",), parameters=(wb(3),))],
    )
    value = executed_value(result, pit_sample_key(request()), "rm")
    assert value.value == (118.0 + 120.0 + 110.0) / 3.0


def test_formula_rolling_std_ddof_zero(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("rs", REF_STD, ("close",), parameters=(wb(3),))],
    )
    value = executed_value(result, pit_sample_key(request()), "rs")
    closes = [118.0, 120.0, 110.0]
    mean = sum(closes) / 3.0
    expected = math.sqrt(sum((x - mean) ** 2 for x in closes) / 3.0)
    assert value.value == expected
    # Not the pandas ddof=1 sample standard deviation.
    assert value.value != math.sqrt(sum((x - mean) ** 2 for x in closes) / 2.0)


def test_formula_rolling_volume_mean(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("rv", REF_VMEAN, ("volume",), parameters=(wb(3),))],
    )
    value = executed_value(result, pit_sample_key(request()), "rv")
    assert value.value == 500.0


def test_formula_volume_ratio_excludes_current_bar(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("vr", REF_VRATIO, ("volume",), parameters=(wb(3),))],
    )
    value = executed_value(result, pit_sample_key(request()), "vr")
    # Current bar (600) must NOT enter the denominator: (400+500)/2.
    assert value.value == 600.0 / 450.0


def test_formula_candle_range(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("cr", REF_RANGE, ("high", "low"))],
    )
    value = executed_value(result, pit_sample_key(request()), "cr")
    assert value.value == 125.0 - 115.0


def test_formula_candle_body_signed(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("cb", REF_BODY, ("open", "close"))],
    )
    value = executed_value(result, pit_sample_key(request()), "cb")
    assert value.value == 110.0 - 120.0
    assert value.value < 0.0


def test_formula_no_rounding_no_formatting(fixtures):
    result = execute_builtin_features(
        [fixtures.a],
        assemble([fixtures.a], [request()]),
        [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))],
    )
    value = executed_value(result, pit_sample_key(request()), "sr")
    assert type(value.value) is float
    assert value.value == 110.0 / 120.0 - 1.0


def test_formula_large_finite_values_no_rounding():
    inp = FeatureTransformInput(
        field_names=("close",),
        rows=((1e12,), (2e12,)),
        parameters=(wb(2),),
    )
    assert rolling_mean(inp) == 1.5e12


def test_negative_zero_input_normalization():
    inp = FeatureTransformInput(
        field_names=("open", "close"),
        rows=((-0.0, -0.0),),
        parameters=(),
    )
    assert inp.rows == ((0.0, 0.0),)
    assert candle_body(inp) == 0.0


def test_negative_zero_output_normalization():
    assert _validate_output_value(-0.0, feature_spec("c", REF_BODY, ("open", "close")), built_in_feature_registry().resolve_feature_spec(
        feature_spec("c", REF_BODY, ("open", "close"))
    ).registration) == 0.0


# ---------------------------------------------------------------------------
# C. Domain failures (fail closed, never EXCLUDED).
# ---------------------------------------------------------------------------


def test_simple_return_zero_denominator_wrapped(fixtures):
    pit = assemble([fixtures.zero], [request()])
    with pytest.raises(FeatureExecutionError) as excinfo:
        execute_builtin_features(
            [fixtures.zero],
            pit,
            [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))],
        )
    message = str(excinfo.value)
    assert REF_SIMPLE in message
    assert "sr" in message
    assert pit_sample_key(request()) in message


def test_log_return_zero_input_fails(fixtures):
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.zero],
            assemble([fixtures.zero], [request()]),
            [feature_spec("lr", REF_LOG, ("close",), parameters=(wb(2),))],
        )


def test_log_return_negative_input_fails(fixtures):
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.neg],
            assemble([fixtures.neg], [request()]),
            [feature_spec("lr", REF_LOG, ("close",), parameters=(wb(2),))],
        )


def test_volume_ratio_zero_previous_mean_fails(fixtures):
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.volzero],
            assemble([fixtures.volzero], [request()]),
            [feature_spec("vr", REF_VRATIO, ("volume",), parameters=(wb(2),))],
        )


def test_candle_range_high_below_low_fails(fixtures):
    bad_bar = replace(
        bar_of(fixtures.a, "2026-07-01 13:35:00"), high=110.0, low=115.0
    )
    bad_build = replace(
        fixtures.a,
        bars=(bad_bar,),
        canonical_row_version_ids=(bad_bar.canonical_row_version_id,),
    )
    pit = hand_result([bad_build], [hand_sample([bad_build], (bad_bar.canonical_row_version_id,), request())])
    with pytest.raises(FeatureExecutionError) as excinfo:
        execute_builtin_features(
            [bad_build], pit, [feature_spec("cr", REF_RANGE, ("high", "low"))]
        )
    assert REF_RANGE in str(excinfo.value)


def test_transform_overflow_fails_closed():
    # math.fsum raises OverflowError on intermediate overflow; either way
    # the transform never silently returns infinity.
    with pytest.raises((ValueError, OverflowError)):
        rolling_mean(
            FeatureTransformInput(
                field_names=("close",),
                rows=((1e308,), (1e308,)),
                parameters=(wb(2),),
            )
        )


def test_transform_input_rejects_nan_and_infinities():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(FeatureExecutionError):
            FeatureTransformInput(field_names=("close",), rows=((bad,),), parameters=(wb(1),))
        with pytest.raises(FeatureExecutionError):
            FeatureTransformInput(field_names=("close",), rows=((1.0, bad),), parameters=(wb(2),))


def test_transform_input_rejects_bool_and_int():
    for bad in (True, 5, "5"):
        with pytest.raises(FeatureExecutionError):
            FeatureTransformInput(field_names=("close",), rows=((bad,),), parameters=(wb(1),))


def test_transform_input_rejects_row_length_mismatch():
    with pytest.raises(FeatureExecutionError):
        FeatureTransformInput(field_names=("open", "close"), rows=((1.0,),), parameters=())
    with pytest.raises(FeatureExecutionError):
        FeatureTransformInput(field_names=("close",), rows=((),), parameters=(wb(1),))


def test_transform_input_rejects_unsorted_parameters():
    with pytest.raises(FeatureExecutionError):
        FeatureTransformInput(
            field_names=("close",),
            rows=((1.0,),),
            parameters=(SpecParameter("z", 1), SpecParameter("a", 2)),
        )


def test_output_validation_rejects_nan_inf_and_type_drift():
    spec = feature_spec("c", REF_BODY, ("open", "close"))
    registration = built_in_feature_registry().resolve_feature_spec(spec).registration
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(FeatureExecutionError):
            _validate_output_value(bad, spec, registration)
    for bad in (True, 5, "5", None, [1.0]):
        with pytest.raises(FeatureExecutionError):
            _validate_output_value(bad, spec, registration)
    assert _validate_output_value(2.5, spec, registration) == 2.5


# ---------------------------------------------------------------------------
# D. PIT binding and clocks.
# ---------------------------------------------------------------------------


def test_only_pit_feature_rows_consumed_label_ids_ignored(fixtures):
    req = request(label_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
                  label_close=datetime(2026, 7, 1, 13, 38, tzinfo=UTC))
    pit = assemble([fixtures.a, fixtures.b], [req])
    sample = pit.samples[0]
    assert sample.label_canonical_row_version_ids
    result = execute_builtin_features(
        [fixtures.a, fixtures.b],
        pit,
        [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))],
    )
    out = executed_value(result, sample.sample_key, "sr")
    consumed = set(out.consumed_canonical_row_version_ids)
    assert consumed
    assert consumed.issubset(set(sample.feature_canonical_row_version_ids))
    assert consumed.isdisjoint(set(sample.label_canonical_row_version_ids))


def test_market_available_at_equal_close_accepted(fixtures):
    # The 13:35 bar becomes market-available exactly at the 13:36 close.
    pit = assemble([fixtures.a], [request(feature_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC))])
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    )
    value = executed_value(result, pit.samples[0].sample_key, "sr")
    assert value.status == FEATURE_VALUE_STATUS_COMPLETE


def test_market_available_at_after_close_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    late = replace(bar, market_available_at=datetime(2026, 7, 1, 13, 37, tzinfo=UTC))
    bad_build = replace(
        fixtures.a,
        bars=(late,),
        canonical_row_version_ids=(late.canonical_row_version_id,),
    )
    pit = hand_result([bad_build], [hand_sample([bad_build], (late.canonical_row_version_id,), request())])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [bad_build], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_archive_available_at_equal_dataset_as_of_accepted(fixtures):
    as_of = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    pit = assemble([fixtures.a], [request()], dataset_as_of=as_of)
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
    )
    value = executed_value(result, pit.samples[0].sample_key, "cb")
    assert value.status == FEATURE_VALUE_STATUS_COMPLETE


def test_archive_available_at_after_dataset_as_of_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample([fixtures.a], (bar.canonical_row_version_id,), request(),
                         dataset_as_of=datetime(2026, 7, 1, 13, 59, tzinfo=UTC))
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_dataset_as_of_none_skips_archive_clock(fixtures):
    pit = assemble([fixtures.a], [request()])
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
    )
    assert result.samples[0].status == FEATURE_VALUE_STATUS_COMPLETE


def test_wrong_code_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    req = request(code="US.NVDA")
    pit = hand_result([fixtures.a], [hand_sample([fixtures.a], (bar.canonical_row_version_id,), req)])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_wrong_interval_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    req = request(interval="5m")
    pit = hand_result([fixtures.a], [hand_sample([fixtures.a], (bar.canonical_row_version_id,), req)])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_wrong_adjustment_rejected(fixtures):
    bar = replace(bar_of(fixtures.a, "2026-07-01 13:35:00"), adjustment="SPLIT")
    bad_build = replace(
        fixtures.a,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    pit = hand_result([bad_build], [hand_sample([bad_build], (bar.canonical_row_version_id,), request())])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [bad_build], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_wrong_requested_session_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    req = request(requested_session="REGULAR")
    pit = hand_result([fixtures.a], [hand_sample([fixtures.a], (bar.canonical_row_version_id,), req)])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_event_time_outside_feature_window_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    req = request(feature_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
                  feature_close=datetime(2026, 7, 1, 13, 34, tzinfo=UTC))
    pit = hand_result([fixtures.a], [hand_sample([fixtures.a], (bar.canonical_row_version_id,), req)])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_source_schema_version_mismatch_rejected(fixtures):
    bar = replace(bar_of(fixtures.a, "2026-07-01 13:35:00"), source_schema_version="11.0")
    bad_build = replace(
        fixtures.a,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    pit = hand_result([bad_build], [hand_sample([bad_build], (bar.canonical_row_version_id,), request())])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [bad_build], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_canonical_schema_version_mismatch_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    bad_build = replace(
        fixtures.a,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
        canonical_schema_version="market-bars-canonical-schema-v9",
    )
    pit = hand_result([bad_build], [hand_sample([bad_build], (bar.canonical_row_version_id,), request())])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [bad_build], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_missing_row_version_id_rejected(fixtures):
    phantom = "a" * 64
    pit = hand_result([fixtures.a], [hand_sample([fixtures.a], (phantom,), request())])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_conflicting_row_version_mapping_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    conflicting = replace(bar, close=999.0)
    second = replace(
        fixtures.a,
        canonical_build_id=sha("second-build"),
        bars=(conflicting,),
        canonical_row_version_ids=(conflicting.canonical_row_version_id,),
    )
    pit = hand_result(
        [fixtures.a, second],
        [hand_sample([fixtures.a, second], (bar.canonical_row_version_id,), request())],
    )
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a, second],
            pit,
            [feature_spec("cb", REF_BODY, ("open", "close"))],
        )


def test_pin_binding_mismatch_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    pit = hand_result([fixtures.a], [hand_sample([fixtures.a], (bar.canonical_row_version_id,), request())])
    # Pass only part of the pinned builds: pins must correspond exactly.
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a, fixtures.b],
            pit,
            [feature_spec("cb", REF_BODY, ("open", "close"))],
        )


def test_duplicate_build_id_rejected(fixtures):
    pit = assemble([fixtures.a], [request()])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a, fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_non_verified_build_object_rejected(fixtures):
    pit = assemble([fixtures.a], [request()])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [{"not": "a build"}], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_label_spec_rejected(fixtures):
    pit = assemble([fixtures.a], [request()])
    label_spec = LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name="my_label",
        version="v1",
        output=DatasetField(name="my_label", logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_SIMPLE,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=(CANONICAL_SCHEMA_VERSION,),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow(unit="BARS", start_offset=0, end_offset=1),
        horizon=LabelHorizon(unit="BARS", value=1),
        alignment_rule="END",
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(allow=False, boundary_rule=None),
    )
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [label_spec]
        )


# ---------------------------------------------------------------------------
# E. Trailing windows, contiguity, and exclusions.
# ---------------------------------------------------------------------------


def test_exact_required_row_count_extra_older_rows_ignored(fixtures):
    pit = assemble([fixtures.a], [request()])
    sample = pit.samples[0]
    assert len(sample.feature_canonical_row_version_ids) == 6
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    )
    value = executed_value(result, sample.sample_key, "sr")
    assert value.consumed_canonical_row_version_ids == sample.feature_canonical_row_version_ids[-2:]


def test_insufficient_rows_excluded_no_invocation(fixtures):
    req = request(feature_start=datetime(2026, 7, 1, 13, 35, tzinfo=UTC),
                  feature_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC))
    pit = assemble([fixtures.a], [req])
    sample = pit.samples[0]
    assert len(sample.feature_canonical_row_version_ids) == 1
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    )
    value = executed_value(result, sample.sample_key, "sr")
    assert value.status == FEATURE_VALUE_STATUS_EXCLUDED
    assert value.value is None
    assert value.reason_code == FEATURE_EXCLUSION_INSUFFICIENT_ROWS
    assert value.consumed_canonical_row_version_ids == ()
    assert result.diagnostics.transform_invocation_count == 0
    assert result.diagnostics.complete_value_count == 0
    assert result.diagnostics.excluded_value_count == 1


def test_window_boundaries_one_and_two_bars(fixtures):
    pit = assemble([fixtures.a], [request()])
    sample = pit.samples[0]
    one = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("rm", REF_MEAN, ("close",), parameters=(wb(1),))]
    )
    two = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("rm", REF_MEAN, ("close",), parameters=(wb(2),))]
    )
    assert executed_value(one, sample.sample_key, "rm").value == 110.0
    assert executed_value(two, sample.sample_key, "rm").value == (120.0 + 110.0) / 2.0


def test_missing_middle_bar_excluded(fixtures):
    req = request(feature_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
                  feature_close=datetime(2026, 7, 1, 13, 34, tzinfo=UTC))
    pit = assemble([fixtures.g], [req])
    sample = pit.samples[0]
    assert len(sample.feature_canonical_row_version_ids) == 2
    result = execute_builtin_features(
        [fixtures.g], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    )
    value = executed_value(result, sample.sample_key, "sr")
    assert value.status == FEATURE_VALUE_STATUS_EXCLUDED
    assert value.reason_code == FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS
    assert value.value is None
    assert result.diagnostics.transform_invocation_count == 0


def test_cross_market_calendar_date_excluded(fixtures):
    req = request(
        code="US.NVDA",
        anchor=date(2026, 7, 1),
        feature_start=datetime(2026, 7, 2, 13, 30, tzinfo=UTC),
        feature_close=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
    )
    pit = assemble([fixtures.d], [req])
    sample = pit.samples[0]
    result = execute_builtin_features(
        [fixtures.d], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    )
    value = executed_value(result, sample.sample_key, "sr")
    assert value.status == FEATURE_VALUE_STATUS_EXCLUDED
    assert value.reason_code == FEATURE_EXCLUSION_CROSS_MARKET_DATE
    assert value.value is None


def test_duplicate_event_time_rejected(fixtures):
    first = bar_of(fixtures.a, "2026-07-01 13:34:00")
    duplicate = replace(
        first,
        canonical_bar_key=first.canonical_bar_key + "-dup",
        canonical_row_version_id=sha("dup-version"),
    )
    bad_build = replace(
        fixtures.a,
        bars=(first, duplicate),
        canonical_row_version_ids=tuple(
            sorted((first.canonical_row_version_id, duplicate.canonical_row_version_id))
        ),
    )
    pit = hand_result(
        [bad_build],
        [hand_sample([bad_build], (first.canonical_row_version_id, duplicate.canonical_row_version_id), request())],
    )
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [bad_build], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
        )


def test_out_of_order_binding_rejected(fixtures):
    earlier = bar_of(fixtures.a, "2026-07-01 13:34:00")
    later = bar_of(fixtures.a, "2026-07-01 13:35:00")
    pit = hand_result(
        [fixtures.a],
        [hand_sample([fixtures.a], (later.canonical_row_version_id, earlier.canonical_row_version_id), request())],
    )
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
        )


def test_bool_as_window_rejected(fixtures):
    pit = assemble([fixtures.a], [request()])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a],
            pit,
            [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(SpecParameter("window_bars", True),))],
        )


def test_contiguous_window_accepted(fixtures):
    pit = assemble([fixtures.a], [request()])
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("rs", REF_STD, ("close",), parameters=(wb(6),))]
    )
    value = executed_value(result, pit.samples[0].sample_key, "rs")
    assert value.status == FEATURE_VALUE_STATUS_COMPLETE


# ---------------------------------------------------------------------------
# F. Result models.
# ---------------------------------------------------------------------------


def test_result_models_frozen(fixtures):
    pit = assemble([fixtures.a], [request()])
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
    )
    sample = result.samples[0]
    value = sample.values[0]
    with pytest.raises(FrozenInstanceError):
        value.value = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        sample.values = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.samples = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        FeatureTransformInput(field_names=("close",), rows=((1.0,),), parameters=(wb(1),)).rows = ()  # type: ignore[misc]


def test_complete_value_invariants(fixtures):
    pit = assemble([fixtures.a], [request()])
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
    )
    value = result.samples[0].values[0]
    assert value.status == FEATURE_VALUE_STATUS_COMPLETE
    assert type(value.value) is float
    assert value.reason_code is None
    assert value.consumed_canonical_row_version_ids
    assert isinstance(value.spec_pin, SpecPin)
    assert isinstance(value.implementation_pin, ImplementationPin)


def test_excluded_value_invariants():
    spec = feature_spec("cb", REF_BODY, ("open", "close"))
    resolved = built_in_feature_registry().resolve_feature_spec(spec)
    value = FeatureValueResult(
        feature_name="cb",
        spec_pin=feature_label_spec_pin(spec),
        implementation_pin=resolved.pin,
        status=FEATURE_VALUE_STATUS_EXCLUDED,
        value=None,
        reason_code=FEATURE_EXCLUSION_INSUFFICIENT_ROWS,
        consumed_canonical_row_version_ids=(),
    )
    assert value.status == FEATURE_VALUE_STATUS_EXCLUDED
    with pytest.raises(FeatureExecutionError):
        FeatureValueResult(
            feature_name="cb",
            spec_pin=feature_label_spec_pin(spec),
            implementation_pin=resolved.pin,
            status=FEATURE_VALUE_STATUS_EXCLUDED,
            value=1.0,
            reason_code=FEATURE_EXCLUSION_INSUFFICIENT_ROWS,
            consumed_canonical_row_version_ids=(),
        )
    with pytest.raises(FeatureExecutionError):
        FeatureValueResult(
            feature_name="cb",
            spec_pin=feature_label_spec_pin(spec),
            implementation_pin=resolved.pin,
            status=FEATURE_VALUE_STATUS_EXCLUDED,
            value=None,
            reason_code="UNKNOWN_REASON",
            consumed_canonical_row_version_ids=(),
        )


def test_stable_value_ordering_by_spec_pin(fixtures):
    pit = assemble([fixtures.a], [request()])
    specs = [
        feature_spec("zz_feature", REF_BODY, ("open", "close")),
        feature_spec("aa_feature", REF_SIMPLE, ("close",), parameters=(wb(2),)),
    ]
    result = execute_builtin_features([fixtures.a], pit, specs)
    names = [value.feature_name for value in result.samples[0].values]
    assert names == ["aa_feature", "zz_feature"]


def test_stable_sample_ordering(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    req_a = request()
    req_b = request(feature_start=datetime(2026, 7, 1, 13, 34, tzinfo=UTC),
                    feature_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC))
    sample_a = hand_sample([fixtures.a], (bar.canonical_row_version_id,), req_a)
    sample_b = hand_sample([fixtures.a], (bar.canonical_row_version_id,), req_b)
    pit = hand_result([fixtures.a], [sample_b, sample_a])
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
    )
    keys = [sample.sample_key for sample in result.samples]
    assert keys == sorted(keys)
    assert set(keys) == {pit_sample_key(req_a), pit_sample_key(req_b)}
    assert result.samples[0].sample_key == min(pit_sample_key(req_a), pit_sample_key(req_b))


def test_duplicate_feature_name_rejected(fixtures):
    pit = assemble([fixtures.a], [request()])
    specs = [
        feature_spec("dup", REF_BODY, ("open", "close")),
        feature_spec("dup", REF_SIMPLE, ("close",), parameters=(wb(2),)),
    ]
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features([fixtures.a], pit, specs)


def test_diagnostic_counts_recomputed(fixtures):
    pit = assemble([fixtures.a], [request()])
    result = execute_builtin_features(
        [fixtures.a],
        pit,
        [
            feature_spec("cb", REF_BODY, ("open", "close")),
            feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),)),
        ],
    )
    diagnostics = result.diagnostics
    assert diagnostics.sample_count == 1
    assert diagnostics.feature_spec_count == 2
    assert diagnostics.complete_sample_count == 1
    assert diagnostics.excluded_sample_count == 0
    assert diagnostics.complete_value_count == 2
    assert diagnostics.excluded_value_count == 0
    assert diagnostics.transform_invocation_count == 2
    # A tampered diagnostics object must fail closed at construction.
    tampered = FeatureExecutionDiagnostics(
        sample_count=1, feature_spec_count=2, complete_sample_count=1,
        excluded_sample_count=0, complete_value_count=1,
        excluded_value_count=1, transform_invocation_count=1,
    )
    with pytest.raises(FeatureExecutionError):
        FeatureExecutionResult(
            samples=result.samples,
            feature_spec_pins=result.feature_spec_pins,
            implementation_pins=result.implementation_pins,
            diagnostics=tampered,
            execution_contract_version=FEATURE_EXECUTION_CONTRACT_VERSION,
        )


def test_invalid_spec_pin_rejected():
    spec = feature_spec("cb", REF_BODY, ("open", "close"))
    resolved = built_in_feature_registry().resolve_feature_spec(spec)
    wrong_pin = SpecPin(kind=SPEC_KIND_FEATURE, name="other", version="v1", content_sha256="b" * 64)
    with pytest.raises(FeatureExecutionError):
        FeatureValueResult(
            feature_name="cb",
            spec_pin=wrong_pin,
            implementation_pin=resolved.pin,
            status=FEATURE_VALUE_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            consumed_canonical_row_version_ids=("a" * 64,),
        )


def test_invalid_implementation_pin_rejected():
    spec = feature_spec("cb", REF_BODY, ("open", "close"))
    with pytest.raises(FeatureExecutionError):
        FeatureValueResult(
            feature_name="cb",
            spec_pin=feature_label_spec_pin(spec),
            implementation_pin="not-a-pin",
            status=FEATURE_VALUE_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            consumed_canonical_row_version_ids=("a" * 64,),
        )


def test_consumed_ids_stable_across_executions(fixtures):
    pit = assemble([fixtures.a], [request()])
    first = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(3),))]
    )
    second = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(3),))]
    )
    consumed = first.samples[0].values[0].consumed_canonical_row_version_ids
    expected = tuple(bar.canonical_row_version_id for bar in fixtures.a.bars[-3:])
    assert consumed == expected
    assert consumed == second.samples[0].values[0].consumed_canonical_row_version_ids


def test_empty_feature_spec_set_allowed(fixtures):
    pit = assemble([fixtures.a], [request()])
    result = execute_builtin_features([fixtures.a], pit, [])
    assert len(result.samples) == 1
    assert result.samples[0].status == FEATURE_VALUE_STATUS_COMPLETE
    assert result.samples[0].values == ()
    assert result.diagnostics.feature_spec_count == 0
    assert result.diagnostics.complete_value_count == 0
    assert result.diagnostics.transform_invocation_count == 0
    assert result.feature_spec_pins == ()


# ---------------------------------------------------------------------------
# G. Determinism.
# ---------------------------------------------------------------------------


def test_builds_permutation_equivalence(fixtures):
    req = request(label_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
                  label_close=datetime(2026, 7, 1, 13, 38, tzinfo=UTC))
    specs = [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    forward = execute_builtin_features(
        [fixtures.a, fixtures.b], assemble([fixtures.a, fixtures.b], [req]), specs
    )
    reverse = execute_builtin_features(
        [fixtures.b, fixtures.a], assemble([fixtures.b, fixtures.a], [req]), specs
    )
    assert forward == reverse


def test_specs_permutation_equivalence(fixtures):
    pit = assemble([fixtures.a], [request()])
    specs = [
        feature_spec("aa", REF_SIMPLE, ("close",), parameters=(wb(2),)),
        feature_spec("bb", REF_BODY, ("open", "close")),
    ]
    forward = execute_builtin_features([fixtures.a], pit, specs)
    reverse = execute_builtin_features([fixtures.a], pit, list(reversed(specs)))
    assert forward == reverse


def test_repeated_execution_equality(fixtures):
    pit = assemble([fixtures.a], [request()])
    specs = [
        feature_spec("aa", REF_SIMPLE, ("close",), parameters=(wb(2),)),
        feature_spec("bb", REF_BODY, ("open", "close")),
    ]
    first = execute_builtin_features([fixtures.a], pit, specs)
    second = execute_builtin_features([fixtures.a], pit, specs)
    assert first == second
    assert first.execution_contract_version == FEATURE_EXECUTION_CONTRACT_VERSION


def test_local_timezone_independence(fixtures, monkeypatch):
    pit = assemble([fixtures.a], [request()])
    specs = [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    baseline = execute_builtin_features([fixtures.a], pit, specs)
    monkeypatch.setenv("TZ", "America/New_York")
    if hasattr(time, "tzset"):
        time.tzset()
    changed = execute_builtin_features([fixtures.a], pit, specs)
    assert baseline == changed


def test_no_current_time_dependence(fixtures, monkeypatch):
    pit = assemble([fixtures.a], [request()])

    def boom():
        raise AssertionError("current time must not be used")

    monkeypatch.setattr(time, "time", boom)
    result = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
    )
    assert result.samples[0].status == FEATURE_VALUE_STATUS_COMPLETE


def test_no_filesystem_mtime_dependence(fixtures):
    import importlib

    module_names = [
        "candle_body", "candle_range", "log_return", "rolling_mean",
        "rolling_std", "rolling_volume_mean", "simple_return", "volume_ratio",
    ]
    pit = assemble([fixtures.a], [request()])
    specs = [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    baseline = execute_builtin_features([fixtures.a], pit, specs)
    for name in module_names:
        module = importlib.import_module(
            f"market_vault.dataset.feature_transforms.{name}"
        )
        os.utime(module.__file__)
    linecache.clearcache()
    changed = execute_builtin_features([fixtures.a], pit, specs)
    assert baseline == changed


def test_implementation_version_change_affects_pin(tmp_path, monkeypatch):
    source = '''\
"""temp implementation."""

def f(input_):
    return 1.0
'''
    file = tmp_path / "impl_mod.py"
    file.write_text(source, encoding="utf-8")
    module = types.ModuleType("test_mv_impl_version")
    module.__file__ = str(file)
    exec(compile(source, str(file), "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ref = f"{module.__name__}:f"
    common = dict(
        kind=SPEC_KIND_FEATURE,
        input_canonical_fields=("close",),
        supported_canonical_schema_versions=(CANONICAL_SCHEMA_VERSION,),
        supported_source_schema_versions=("10.9",),
        output_logical_type="float64",
        output_nullable=False,
        parameters=(),
        lookback=TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE),
        lookforward=TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE),
        boundary_policy=BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
        missing_policy=MISSING_POLICY_EXCLUDE_SAMPLE,
    )
    v1 = TransformRegistration(transform_ref=ref, implementation_version="v1",
                               implementation=module.f, **common)
    v2 = TransformRegistration(transform_ref=ref, implementation_version="v2",
                               implementation=module.f, **common)
    assert transform_implementation_fingerprint(v1) != transform_implementation_fingerprint(v2)
    assert transform_implementation_pin(v1) != transform_implementation_pin(v2)


def test_implementation_source_change_affects_pin(tmp_path, monkeypatch):
    def build(source, name):
        file = tmp_path / f"{name}.py"
        file.write_text(source, encoding="utf-8")
        module = types.ModuleType(name)
        module.__file__ = str(file)
        exec(compile(source, str(file), "exec"), module.__dict__)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    base = '''\
"""temp implementation."""

def f(input_):
    return 1.0
'''
    changed = base.replace("1.0", "2.0")
    module_a = build(base, "test_mv_impl_source_a")
    module_b = build(changed, "test_mv_impl_source_b")
    common = dict(
        kind=SPEC_KIND_FEATURE,
        implementation_version="v1",
        input_canonical_fields=("close",),
        supported_canonical_schema_versions=(CANONICAL_SCHEMA_VERSION,),
        supported_source_schema_versions=("10.9",),
        output_logical_type="float64",
        output_nullable=False,
        parameters=(),
        lookback=TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE),
        lookforward=TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE),
        boundary_policy=BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
        missing_policy=MISSING_POLICY_EXCLUDE_SAMPLE,
    )
    reg_a = TransformRegistration(transform_ref=f"{module_a.__name__}:f",
                                  implementation=module_a.f, **common)
    reg_b = TransformRegistration(transform_ref=f"{module_b.__name__}:f",
                                  implementation=module_b.f, **common)
    assert reg_a.implementation_fingerprint != reg_b.implementation_fingerprint


def test_spec_parameter_change_affects_pin_and_result(fixtures):
    pit = assemble([fixtures.a], [request()])
    two = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))]
    )
    three = execute_builtin_features(
        [fixtures.a], pit, [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(3),))]
    )
    assert two.feature_spec_pins != three.feature_spec_pins
    assert (
        two.samples[0].values[0].value
        != three.samples[0].values[0].value
    )


# ---------------------------------------------------------------------------
# H. Offline / no side effects.
# ---------------------------------------------------------------------------


def test_no_arbitrary_registration_execution(fixtures):
    pit = assemble([fixtures.a], [request()])
    unknown = feature_spec(
        "ema", "market_vault.dataset.feature_transforms.ema:ema", ("close",),
        parameters=(wb(2),),
    )
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features([fixtures.a], pit, [unknown])


def test_no_dataset_artifacts_and_cwd_unchanged(fixtures, monkeypatch):
    repo_root = Path(__file__).resolve().parent.parent
    monkeypatch.chdir(repo_root)
    pit = assemble([fixtures.a], [request()])
    execute_builtin_features([fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))])
    assert os.getcwd() == str(repo_root)
    assert not (repo_root / "data" / "datasets").exists()


def test_no_manifest_and_no_label_artifacts(fixtures):
    repo_root = Path(__file__).resolve().parent.parent
    assert not (repo_root / "data" / "datasets" / "manifest.json").exists()
    assert not (repo_root / "data" / "datasets" / "label_specs").exists()


def test_execution_never_writes_to_repo(fixtures):
    repo_root = Path(__file__).resolve().parent.parent
    datasets_dir = repo_root / "data" / "datasets"
    before = {p for p in datasets_dir.rglob("*")} if datasets_dir.exists() else set()
    pit = assemble([fixtures.a], [request()])
    execute_builtin_features([fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))])
    after = {p for p in datasets_dir.rglob("*")} if datasets_dir.exists() else set()
    assert before == after


def test_transforms_are_pure_module_level_functions():
    for fn in (simple_return, log_return, rolling_mean, rolling_std,
               rolling_volume_mean, volume_ratio, candle_range, candle_body):
        assert isinstance(fn, types.FunctionType)
        assert fn.__module__.startswith("market_vault.dataset.feature_transforms")
        assert fn.__closure__ is None
        assert fn.__name__ in fn.__qualname__


# ---------------------------------------------------------------------------
# I. Exact PIT Pin binding (bidirectional reconstruction).
# ---------------------------------------------------------------------------


def _single_bar_sample(fixtures, bar):
    return hand_sample(
        [fixtures.a], (bar.canonical_row_version_id,), request()
    )


def _bars_by_version(build):
    return {bar.canonical_row_version_id: bar for bar in build.bars}


def test_pin_missing_selected_row_version_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = _single_bar_sample(fixtures, bar)
    pin = make_pin(
        fixtures.a, {bar.canonical_row_version_id}, _bars_by_version(fixtures.a),
        row_versions=(),  # the actually selected row is missing from the pin
    )
    pit = hand_result([fixtures.a], [sample], pins=[pin])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_pin_extra_unselected_row_version_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    extra = bar_of(fixtures.a, "2026-07-01 13:34:00")
    sample = _single_bar_sample(fixtures, bar)
    pin = make_pin(
        fixtures.a, {bar.canonical_row_version_id}, _bars_by_version(fixtures.a),
        row_versions=(bar.canonical_row_version_id, extra.canonical_row_version_id),
    )
    pit = hand_result([fixtures.a], [sample], pins=[pin])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_pin_empty_source_snapshots_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = _single_bar_sample(fixtures, bar)
    pin = make_pin(
        fixtures.a, {bar.canonical_row_version_id}, _bars_by_version(fixtures.a),
        source_snapshots=(),  # selected rows exist, so provenance must exist
    )
    pit = hand_result([fixtures.a], [sample], pins=[pin])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_pin_source_snapshot_content_mismatch_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = _single_bar_sample(fixtures, bar)
    wrong_snapshot = replace(source_snapshot_of(bar), ingestion_run_id="wrong-run")
    pin = make_pin(
        fixtures.a, {bar.canonical_row_version_id}, _bars_by_version(fixtures.a),
        source_snapshots=[wrong_snapshot],
    )
    pit = hand_result([fixtures.a], [sample], pins=[pin])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_duplicate_canonical_build_pin_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = _single_bar_sample(fixtures, bar)
    pin = make_pin(
        fixtures.a, {bar.canonical_row_version_id}, _bars_by_version(fixtures.a)
    )
    pit = hand_result([fixtures.a], [sample], pins=[pin, pin])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_canonical_row_version_ids_missing_selected_row_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = _single_bar_sample(fixtures, bar)
    pit = hand_result([fixtures.a], [sample], row_version_ids=())
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_canonical_row_version_ids_extra_row_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = _single_bar_sample(fixtures, bar)
    pit = hand_result(
        [fixtures.a], [sample],
        row_version_ids=(bar.canonical_row_version_id, "b" * 64),
    )
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_sample_considered_build_ids_mismatch_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a], (bar.canonical_row_version_id,), request(),
        considered=("a" * 64,),
    )
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_diagnostics_considered_build_ids_mismatch_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = _single_bar_sample(fixtures, bar)
    pit = hand_result([fixtures.a], [sample], considered_diagnostics=("b" * 64,))
    with pytest.raises(FeatureExecutionError):
        execute_builtin_features(
            [fixtures.a], pit, [feature_spec("cb", REF_BODY, ("open", "close"))]
        )


def test_normal_assembler_pit_result_passes_exact_pin_binding(fixtures):
    # A real assembler result (Feature + Label rows, two builds) must pass
    # the exact reconstruction comparison unchanged.
    req = request(
        label_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_close=datetime(2026, 7, 1, 13, 38, tzinfo=UTC),
    )
    pit = assemble([fixtures.a, fixtures.b], [req])
    result = execute_builtin_features(
        [fixtures.a, fixtures.b],
        pit,
        [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))],
    )
    assert result.samples[0].status == FEATURE_VALUE_STATUS_COMPLETE


# ---------------------------------------------------------------------------
# J. Result-model tightening (direct construction).
# ---------------------------------------------------------------------------


def spec_and_impl(name, transform_ref, fields, **kwargs):
    spec = feature_spec(name, transform_ref, fields, **kwargs)
    resolved = built_in_feature_registry().resolve_feature_spec(spec)
    return feature_label_spec_pin(spec), resolved.pin


def value_of(spec_pin, impl_pin, *, name=None, consumed=("a" * 64,)):
    return FeatureValueResult(
        feature_name=name or spec_pin.name,
        spec_pin=spec_pin,
        implementation_pin=impl_pin,
        status=FEATURE_VALUE_STATUS_COMPLETE,
        value=1.0,
        reason_code=None,
        consumed_canonical_row_version_ids=consumed,
    )


def sample_of(sample_key, values, *, code="US.MU"):
    values = tuple(values)
    status = (
        FEATURE_VALUE_STATUS_COMPLETE
        if all(v.status == FEATURE_VALUE_STATUS_COMPLETE for v in values)
        else FEATURE_VALUE_STATUS_EXCLUDED
    )
    return FeatureSampleResult(
        sample_key=sample_key,
        sample_version_id=sha(sample_key),
        code=code,
        feature_window_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        values=values,
        status=status,
    )


def result_of(samples, spec_pins, impl_pins, *, diagnostics=None):
    samples = tuple(samples)
    spec_pins = tuple(spec_pins)
    impl_pins = tuple(impl_pins)
    complete_samples = sum(
        1 for s in samples if s.status == FEATURE_VALUE_STATUS_COMPLETE
    )
    complete_values = sum(
        1 for s in samples for v in s.values if v.status == FEATURE_VALUE_STATUS_COMPLETE
    )
    excluded_values = sum(len(s.values) for s in samples) - complete_values
    diagnostics = diagnostics or FeatureExecutionDiagnostics(
        sample_count=len(samples),
        feature_spec_count=len(spec_pins),
        complete_sample_count=complete_samples,
        excluded_sample_count=len(samples) - complete_samples,
        complete_value_count=complete_values,
        excluded_value_count=excluded_values,
        transform_invocation_count=complete_values,
    )
    return FeatureExecutionResult(
        samples=samples,
        feature_spec_pins=spec_pins,
        implementation_pins=impl_pins,
        diagnostics=diagnostics,
        execution_contract_version=FEATURE_EXECUTION_CONTRACT_VERSION,
    )


def test_value_rejects_label_spec_pin():
    spec = feature_spec("cb", REF_BODY, ("open", "close"))
    resolved = built_in_feature_registry().resolve_feature_spec(spec)
    label_pin = SpecPin(
        kind="LABEL", name="cb", version="v1", content_sha256="b" * 64
    )
    with pytest.raises(FeatureExecutionError):
        FeatureValueResult(
            feature_name="cb",
            spec_pin=label_pin,
            implementation_pin=resolved.pin,
            status=FEATURE_VALUE_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            consumed_canonical_row_version_ids=("a" * 64,),
        )


def test_value_rejects_null_implementation_hash():
    spec = feature_spec("cb", REF_BODY, ("open", "close"))
    null_hash = ImplementationPin(name=REF_BODY, version="v1", content_sha256=None)
    with pytest.raises(FeatureExecutionError):
        FeatureValueResult(
            feature_name="cb",
            spec_pin=feature_label_spec_pin(spec),
            implementation_pin=null_hash,
            status=FEATURE_VALUE_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            consumed_canonical_row_version_ids=("a" * 64,),
        )


def test_value_rejects_duplicate_consumed_ids():
    spec = feature_spec("cb", REF_BODY, ("open", "close"))
    resolved = built_in_feature_registry().resolve_feature_spec(spec)
    with pytest.raises(FeatureExecutionError):
        FeatureValueResult(
            feature_name="cb",
            spec_pin=feature_label_spec_pin(spec),
            implementation_pin=resolved.pin,
            status=FEATURE_VALUE_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            consumed_canonical_row_version_ids=("a" * 64, "a" * 64),
        )


def test_value_consumed_order_preserved():
    spec = feature_spec("cb", REF_BODY, ("open", "close"))
    resolved = built_in_feature_registry().resolve_feature_spec(spec)
    value = FeatureValueResult(
        feature_name="cb",
        spec_pin=feature_label_spec_pin(spec),
        implementation_pin=resolved.pin,
        status=FEATURE_VALUE_STATUS_COMPLETE,
        value=1.0,
        reason_code=None,
        consumed_canonical_row_version_ids=("b" * 64, "a" * 64),
    )
    assert value.consumed_canonical_row_version_ids == ("b" * 64, "a" * 64)


def test_sample_rejects_unsorted_values():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    pin_z, impl_z = spec_and_impl("zz", REF_SIMPLE, ("close",), parameters=(wb(2),))
    with pytest.raises(FeatureExecutionError):
        sample_of("s1", [value_of(pin_z, impl_z), value_of(pin_a, impl_a)])


def test_result_rejects_missing_feature_in_sample():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    pin_b, impl_b = spec_and_impl("bb", REF_SIMPLE, ("close",), parameters=(wb(2),))
    sample = sample_of("s1", [value_of(pin_a, impl_a)])
    with pytest.raises(FeatureExecutionError):
        result_of([sample], [pin_a, pin_b], [impl_a, impl_b])


def test_result_rejects_extra_feature_in_sample():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    pin_b, impl_b = spec_and_impl("bb", REF_SIMPLE, ("close",), parameters=(wb(2),))
    sample = sample_of("s1", [value_of(pin_a, impl_a), value_of(pin_b, impl_b)])
    with pytest.raises(FeatureExecutionError):
        result_of([sample], [pin_a], [impl_a])


def test_result_rejects_unused_spec_pin():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    pin_b, impl_b = spec_and_impl("bb", REF_SIMPLE, ("close",), parameters=(wb(2),))
    sample = sample_of("s1", [value_of(pin_a, impl_a)])
    with pytest.raises(FeatureExecutionError):
        result_of([sample], [pin_a, pin_b], [impl_a, impl_b])


def test_result_rejects_unused_implementation_pin():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    _, impl_b = spec_and_impl("bb", REF_SIMPLE, ("close",), parameters=(wb(2),))
    sample = sample_of("s1", [value_of(pin_a, impl_a)])
    with pytest.raises(FeatureExecutionError):
        result_of([sample], [pin_a], [impl_a, impl_b])


def test_result_rejects_spec_implementation_drift_across_samples():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    _, impl_b = spec_and_impl("bb", REF_SIMPLE, ("close",), parameters=(wb(2),))
    first = sample_of("s1", [value_of(pin_a, impl_a)])
    second = sample_of("s2", [value_of(pin_a, impl_b)])
    with pytest.raises(FeatureExecutionError):
        result_of([first, second], [pin_a], [impl_a, impl_b])


def test_result_rejects_spec_pin_identity_hash_conflict():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    conflicting = SpecPin(
        kind=SPEC_KIND_FEATURE, name="aa", version="v1", content_sha256="b" * 64
    )
    sample = sample_of("s1", [value_of(pin_a, impl_a)])
    with pytest.raises(FeatureExecutionError):
        result_of([sample], [pin_a, conflicting], [impl_a])


def test_result_rejects_implementation_pin_identity_hash_conflict():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    conflicting = ImplementationPin(name=impl_a.name, version="v1", content_sha256="b" * 64)
    sample = sample_of("s1", [value_of(pin_a, impl_a)])
    with pytest.raises(FeatureExecutionError):
        result_of([sample], [pin_a], [impl_a, conflicting])


def test_result_empty_samples_nonempty_specs_vacuous_execution():
    # Documented decision: an empty sample set with a non-empty spec set is
    # a vacuous execution; the coverage invariants are vacuous and the
    # result-level pins stay normalized.
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    result = result_of([], [pin_a], [impl_a])
    assert result.samples == ()
    assert result.feature_spec_pins == (pin_a,)
    assert result.diagnostics.sample_count == 0
    assert result.diagnostics.feature_spec_count == 1


def test_diagnostics_matrix_validation():
    pin_a, impl_a = spec_and_impl("aa", REF_BODY, ("open", "close"))
    pin_b, impl_b = spec_and_impl("bb", REF_SIMPLE, ("close",), parameters=(wb(2),))
    sample = sample_of("s1", [value_of(pin_a, impl_a), value_of(pin_b, impl_b)])
    bad = FeatureExecutionDiagnostics(
        sample_count=1, feature_spec_count=2, complete_sample_count=1,
        excluded_sample_count=0, complete_value_count=1,
        excluded_value_count=0, transform_invocation_count=1,
    )
    with pytest.raises(FeatureExecutionError):
        result_of([sample], [pin_a, pin_b], [impl_a, impl_b], diagnostics=bad)


# ---------------------------------------------------------------------------
# K. Registry construction error wrapping and exclusion priority.
# ---------------------------------------------------------------------------


def test_registry_construction_error_wrapped(fixtures, monkeypatch):
    import market_vault.dataset.feature_execution as feature_execution_module

    def boom():
        raise TransformRegistryError("registry exploded")

    monkeypatch.setattr(feature_execution_module, "built_in_feature_registry", boom)
    with pytest.raises(FeatureExecutionError) as excinfo:
        execute_builtin_features(
            [fixtures.a],
            assemble([fixtures.a], [request()]),
            [feature_spec("cb", REF_BODY, ("open", "close"))],
        )
    assert "failed to construct built-in Feature registry" in str(excinfo.value)
    assert excinfo.value.__cause__ is not None


def test_cross_market_date_priority_over_contiguity(fixtures):
    # Two consumed rows of different market-calendar dates with a
    # non-nominal overnight interval between them: the reason must be
    # CROSS_MARKET_DATE, never NON_CONTIGUOUS_ROWS.
    bar1 = bar_of(fixtures.a, "2026-07-01 13:35:00")  # market date 2026-07-01
    bar2 = replace(
        bar_of(fixtures.d, "2026-07-02 13:30:00"),  # market date 2026-07-02
        code="US.MU",
    )
    second_build = replace(
        fixtures.d,
        bars=(bar2,),
        canonical_row_version_ids=(bar2.canonical_row_version_id,),
    )
    req = request(
        feature_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
        feature_close=datetime(2026, 7, 2, 13, 31, tzinfo=UTC),
    )
    sample = hand_sample(
        [fixtures.a, second_build],
        (bar1.canonical_row_version_id, bar2.canonical_row_version_id),
        req,
    )
    pit = hand_result([fixtures.a, second_build], [sample])
    result = execute_builtin_features(
        [fixtures.a, second_build],
        pit,
        [feature_spec("sr", REF_SIMPLE, ("close",), parameters=(wb(2),))],
    )
    value = executed_value(result, sample.sample_key, "sr")
    assert value.status == FEATURE_VALUE_STATUS_EXCLUDED
    assert value.reason_code == FEATURE_EXCLUSION_CROSS_MARKET_DATE
    assert value.value is None
    assert result.diagnostics.transform_invocation_count == 0
