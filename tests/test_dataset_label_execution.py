"""Offline deterministic tests for the built-in Label execution core
(v0.5.0 PR-4).

Covers the built-in Label registrations, the four transforms and their exact
formulas, the exact Feature-close anchor binding, horizon-target and
observation-window alignment, PIT / Canonical provenance and clock checks,
explicit COMPLETE / INCOMPLETE results with fixed reason codes,
``actual_label_end_time``, the frozen result models, deterministic
multi-label execution, and the offline / no-side-effect boundary. All
fixtures are micro offline canonical builds produced through the verified
reader and materializer with synthetic data; no network, no OpenD, no
current time, and no real market data.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
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
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_EXECUTION_CONTRACT_VERSION,
    LABEL_INCOMPLETE_INSUFFICIENT_ROWS,
    LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
    LABEL_INCOMPLETE_MISSING_TARGET_ROW,
    LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
    LABEL_SPEC_SCHEMA_VERSION,
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    LABEL_TRANSFORM_CALL_CONTRACT_VERSION,
    PIT_ASSEMBLER_VERSION,
    SPEC_KIND_LABEL,
    BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
    MISSING_POLICY_LABEL_INCOMPLETE,
    CanonicalBuildPin,
    CrossTradingDayPolicy,
    SourceSnapshotPin,
    DatasetField,
    LabelExecutionDiagnostics,
    LabelExecutionError,
    LabelExecutionResult,
    LabelHorizon,
    LabelObservationWindow,
    LabelSampleResult,
    LabelSpec,
    LabelTransformInput,
    LabelValueResult,
    ImplementationPin,
    PITAssemblyDiagnostics,
    PITAssemblyResult,
    PITDiagnostics,
    PITSample,
    PITSampleRequest,
    SpecParameter,
    SpecPin,
    SpecVersionRequirements,
    TransformRegistryError,
    TransformWindowRequirement,
    assemble_point_in_time_samples,
    built_in_label_registrations,
    built_in_label_registry,
    dataset_schema_id,
    execute_builtin_features,
    execute_builtin_labels,
    feature_label_spec_pin,
    logical_dataset_content_id,
    pit_association_schema,
    pit_sample_key,
    pit_sample_version_id,
    transform_implementation_fingerprint,
    transform_implementation_pin,
)
from market_vault.dataset import WINDOW_BOUNDARY_INCLUSIVE, WINDOW_SOURCE_FIXED, WINDOW_SOURCE_LABEL_HORIZON, WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW, WINDOW_UNIT_BARS
from market_vault.dataset.feature_models import FeatureExecutionError
from market_vault.dataset.feature_registry import built_in_feature_registry
from market_vault.dataset.label_execution import _validate_output_value
from market_vault.dataset.label_transforms import (
    forward_direction,
    forward_return,
    maximum_adverse_excursion,
    maximum_favorable_excursion,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"

REF_FORWARD_RETURN = (
    "market_vault.dataset.label_transforms.forward_return:forward_return"
)
REF_FORWARD_DIRECTION = (
    "market_vault.dataset.label_transforms.forward_direction:forward_direction"
)
REF_MFE = (
    "market_vault.dataset.label_transforms."
    "maximum_favorable_excursion:maximum_favorable_excursion"
)
REF_MAE = (
    "market_vault.dataset.label_transforms."
    "maximum_adverse_excursion:maximum_adverse_excursion"
)

ALL_REFS = (
    REF_FORWARD_RETURN,
    REF_FORWARD_DIRECTION,
    REF_MFE,
    REF_MAE,
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
# Offline canonical-build fixtures (mirrors the Feature execution tests;
# every fixture goes through the verified reader, never a plain object).
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

    ``a``       US.MU 2026-07-01 09:30..09:35 NY (feature window + anchor),
                closes 100,110,112,118,120,110; highs 105,108,115,120,122,125;
                lows 95,98,100,105,110,115; archived 14:00Z
    ``f``       US.MU 2026-07-01 09:36..09:41 NY (full future window),
                closes 100,110,120,130,140,150; highs 102,112,122,132,142,152;
                lows 98,108,118,128,138,148; archived 14:00Z
    ``fgap``    US.MU 2026-07-01 09:36,09:37,09:39,09:40,09:41 NY (missing
                the 09:38 bar inside the excursion window)
    ``ffirst``  US.MU 2026-07-01 09:37..09:41 NY (missing the first future
                bar at 09:36)
    ``ftarget`` US.MU 2026-07-01 09:36..09:39 NY (missing the horizon target
                at 09:40 for a H=5 excursion)
    ``fmin``    US.MU 2026-07-01 09:36 NY only (single future bar)
    ``d``       US.NVDA 2026-07-02 09:30..09:31 NY, archived 2026-07-02T14:00Z
    """
    root = tmp_path_factory.mktemp("mv_label_execution")
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
    f = build(
        "US.MU", date(2026, 7, 1), "run-f", minute_keys("2026-07-01 09:36:00", 6),
        opens=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
        highs=[102.0, 112.0, 122.0, 132.0, 142.0, 152.0],
        lows=[98.0, 108.0, 118.0, 128.0, 138.0, 148.0],
        closes=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
        volumes=[100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
    )
    fgap = build(
        "US.MU", date(2026, 7, 1), "run-fgap",
        minute_keys("2026-07-01 09:36:00", 2) + minute_keys("2026-07-01 09:39:00", 3),
        closes=[100.0, 110.0, 130.0, 140.0, 150.0],
    )
    ffirst = build(
        "US.MU", date(2026, 7, 1), "run-ffirst",
        minute_keys("2026-07-01 09:37:00", 5),
        closes=[110.0, 120.0, 130.0, 140.0, 150.0],
    )
    ftarget = build(
        "US.MU", date(2026, 7, 1), "run-ftarget",
        minute_keys("2026-07-01 09:36:00", 4),
        closes=[100.0, 110.0, 120.0, 130.0],
    )
    fmin = build(
        "US.MU", date(2026, 7, 1), "run-fmin",
        minute_keys("2026-07-01 09:36:00", 1),
        closes=[100.0],
    )
    d = build(
        "US.NVDA", date(2026, 7, 2), "run-d", minute_keys("2026-07-02 09:30:00", 2),
        run_finished_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC),
    )
    return SimpleNamespace(a=a, f=f, fgap=fgap, ffirst=ffirst,
                           ftarget=ftarget, fmin=fmin, d=d)


# ---------------------------------------------------------------------------
# Spec / request / hand-built PIT result helpers.
# ---------------------------------------------------------------------------


def label_spec(
    name: str,
    transform_ref: str,
    fields: tuple[str, ...],
    output_type: str,
    *,
    horizon: int = 2,
    start_offset: int = 1,
    end_offset: int = 1,
    unit: str = "BARS",
    alignment: str = LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    cross_trading_day: bool = False,
    canonical=("market-bars-canonical-schema-v1",),
    source=("10.9",),
) -> LabelSpec:
    return LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type=output_type, nullable=False),
        input_canonical_fields=fields,
        transform_ref=transform_ref,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=canonical, source_schema_versions=source
        ),
        observation_window=LabelObservationWindow(unit, start_offset, end_offset),
        horizon=LabelHorizon(unit, horizon),
        alignment_rule=alignment,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(
            cross_trading_day,
            "END_OF_TRADING_DAY" if cross_trading_day else None,
        ),
    )


def forward_spec(name: str, *, horizon: int = 2) -> LabelSpec:
    """A forward_return LabelSpec with the fixed v1 shape
    (start_offset == end_offset == horizon - 1)."""
    return label_spec(
        name, REF_FORWARD_RETURN, ("close",), "float64",
        horizon=horizon, start_offset=horizon - 1, end_offset=horizon - 1,
    )


def mfe_spec(name: str = "mfe", *, horizon: int = 5) -> LabelSpec:
    return label_spec(
        name, REF_MFE, ("close", "high"), "float64",
        horizon=horizon, start_offset=0, end_offset=horizon - 1,
    )


def mae_spec(name: str = "mae", *, horizon: int = 5) -> LabelSpec:
    return label_spec(
        name, REF_MAE, ("close", "low"), "float64",
        horizon=horizon, start_offset=0, end_offset=horizon - 1,
    )


def request(
    *,
    code: str = "US.MU",
    interval: str = "1m",
    adjustment: str = "NONE",
    requested_session: str = "ALL",
    anchor: date = date(2026, 7, 1),
    feature_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
    feature_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    label_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    label_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
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
    ``_build_pins`` rule) unless overridden."""
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


def versions_of(build, *time_texts: str) -> tuple[str, ...]:
    """The row-version ids of the given bars (``YYYY-MM-DD HH:MM:SS`` in
    NY local time) in the requested order."""
    by_time = {bar.event_time.strftime("%Y-%m-%d %H:%M:%S"): bar for bar in build.bars}
    return tuple(by_time[text].canonical_row_version_id for text in time_texts)


def bar_of(build, event_time_text: str):
    for bar in build.bars:
        if bar.event_time.strftime("%Y-%m-%d %H:%M:%S") == event_time_text:
            return bar
    raise AssertionError(f"no bar at {event_time_text} in {build.canonical_build_id}")


def executed_value(result: LabelExecutionResult, sample_key: str, label_name: str):
    for sample in result.samples:
        if sample.sample_key == sample_key:
            for value in sample.values:
                if value.label_name == label_name:
                    return value
            raise AssertionError(f"no label {label_name} in sample {sample_key}")
    raise AssertionError(f"no sample {sample_key}")


def resolved_registration(spec: LabelSpec):
    return built_in_label_registry().resolve_label_spec(spec).registration


def transform_input(
    *,
    fields: tuple[str, ...],
    anchor: tuple[float, ...],
    rows: tuple[tuple[float, ...], ...],
) -> LabelTransformInput:
    return LabelTransformInput(
        field_names=fields,
        anchor_row=anchor,
        rows=rows,
        parameters=(),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    )


# ---------------------------------------------------------------------------
# A. Built-in registrations.
# ---------------------------------------------------------------------------


def test_builtin_registrations_all_present():
    registrations = built_in_label_registrations()
    assert len(registrations) == 4
    assert tuple(reg.transform_ref for reg in registrations) == tuple(sorted(ALL_REFS))
    assert set(reg.transform_ref for reg in registrations) == set(ALL_REFS)


def test_builtin_registrations_no_aliases_or_short_names():
    for reg in built_in_label_registrations():
        assert ":" in reg.transform_ref
        short = reg.transform_ref.rsplit(":", 1)[1]
        assert reg.transform_ref != short
        assert not any(
            other.transform_ref.rsplit(":", 1)[1] == short
            and other.transform_ref != reg.transform_ref
            for other in built_in_label_registrations()
        )


def test_builtin_registrations_stable_sorting_and_repeatable():
    first = built_in_label_registrations()
    second = built_in_label_registrations()
    assert first == second
    refs = [reg.transform_ref for reg in first]
    assert refs == sorted(refs)


def test_builtin_registration_shared_metadata():
    for reg in built_in_label_registrations():
        assert reg.kind == SPEC_KIND_LABEL
        assert reg.implementation_version == "v1"
        assert reg.output_nullable is False
        assert reg.parameters == ()
        assert reg.lookback.source == WINDOW_SOURCE_FIXED
        assert reg.lookback.unit == WINDOW_UNIT_BARS
        assert reg.lookback.value == 1
        assert reg.lookback.parameter_name is None
        assert reg.lookback.boundary == WINDOW_BOUNDARY_INCLUSIVE
        assert reg.boundary_policy == BOUNDARY_POLICY_NO_CROSS_TRADING_DAY
        assert reg.missing_policy == MISSING_POLICY_LABEL_INCOMPLETE
        assert reg.supported_canonical_schema_versions == (CANONICAL_SCHEMA_VERSION,)
        assert reg.supported_source_schema_versions == ("10.9",)
        assert reg.display_name


def test_contract_version_constants():
    assert LABEL_EXECUTION_CONTRACT_VERSION == "market-vault-label-execution-v1"
    assert LABEL_TRANSFORM_CALL_CONTRACT_VERSION == "market-vault-label-transform-call-v1"
    assert LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED == "FEATURE_CLOSE_ALIGNED"


def test_builtin_registration_input_fields_output_types_and_lookforward():
    expected = {
        REF_FORWARD_RETURN: (("close",), "float64", WINDOW_SOURCE_LABEL_HORIZON),
        REF_FORWARD_DIRECTION: (("close",), "int64", WINDOW_SOURCE_LABEL_HORIZON),
        REF_MFE: (("close", "high"), "float64", WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW),
        REF_MAE: (("close", "low"), "float64", WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW),
    }
    for reg in built_in_label_registrations():
        fields, output_type, lookforward_source = expected[reg.transform_ref]
        assert reg.input_canonical_fields == fields
        assert reg.output_logical_type == output_type
        lookforward = reg.lookforward
        assert lookforward.source == lookforward_source
        assert lookforward.unit == WINDOW_UNIT_BARS
        assert lookforward.value is None
        assert lookforward.parameter_name is None
        assert lookforward.boundary == WINDOW_BOUNDARY_INCLUSIVE


def test_builtin_registry_immutable_and_exact():
    registry = built_in_label_registry()
    assert len(registry.registrations) == 4
    with pytest.raises(FrozenInstanceError):
        registry.registrations = ()
    with pytest.raises(AttributeError):
        registry.register = lambda spec: None  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        registry.replace = lambda spec: None  # type: ignore[attr-defined]


def test_builtin_registry_bars_only_preflight():
    registry = built_in_label_registry()
    # BARS resolves; MINUTES and TRADING_DAYS fail closed at registry
    # preflight, and cross_trading_day.allow=true fails closed even with a
    # BARS horizon.
    registry.resolve_label_spec(forward_spec("fr", horizon=2))
    registry.resolve_label_spec(mfe_spec("mfe", horizon=5))
    minutes = label_spec(
        "fr_min", REF_FORWARD_RETURN, ("close",), "float64",
        unit="MINUTES", horizon=2, start_offset=1, end_offset=1,
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_label_spec(minutes)
    trading_days = label_spec(
        "fr_td", REF_FORWARD_RETURN, ("close",), "float64",
        unit="TRADING_DAYS", horizon=2, start_offset=1, end_offset=1,
        cross_trading_day=True,
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_label_spec(trading_days)
    cross_day = label_spec(
        "fr_cd", REF_FORWARD_RETURN, ("close",), "float64",
        horizon=2, start_offset=1, end_offset=1, cross_trading_day=True,
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_label_spec(cross_day)


def test_builtin_registration_deterministic_pins():
    first = built_in_label_registrations()
    second = built_in_label_registrations()
    for left, right in zip(first, second):
        assert transform_implementation_fingerprint(left) == (
            transform_implementation_fingerprint(right)
        )
        assert transform_implementation_pin(left) == transform_implementation_pin(right)
        assert re.fullmatch(_SHA_HEX, left.implementation_fingerprint)


def test_builtin_registration_ref_matches_function_identity():
    for reg in built_in_label_registrations():
        assert reg.transform_ref == (
            reg.implementation.__module__ + ":" + reg.implementation.__name__
        )


# ---------------------------------------------------------------------------
# B. Formulas.
# ---------------------------------------------------------------------------


def test_forward_return_formula():
    # Up / down / unchanged.
    assert forward_return(
        transform_input(fields=("close",), anchor=(110.0,), rows=((121.0,),))
    ) == pytest.approx(0.1)
    assert forward_return(
        transform_input(fields=("close",), anchor=(110.0,), rows=((99.0,),))
    ) == pytest.approx(-0.1)
    assert forward_return(
        transform_input(fields=("close",), anchor=(110.0,), rows=((110.0,),))
    ) == 0.0


def test_forward_direction_formula():
    assert forward_direction(
        transform_input(fields=("close",), anchor=(110.0,), rows=((121.0,),))
    ) == 1
    assert forward_direction(
        transform_input(fields=("close",), anchor=(110.0,), rows=((110.0,),))
    ) == 0
    assert forward_direction(
        transform_input(fields=("close",), anchor=(110.0,), rows=((99.0,),))
    ) == -1
    result = forward_direction(
        transform_input(fields=("close",), anchor=(110.0,), rows=((121.0,),))
    )
    assert type(result) is int


def test_forward_return_domain_errors():
    with pytest.raises(ValueError):
        forward_return(transform_input(fields=("close",), anchor=(0.0,), rows=((1.0,),)))
    with pytest.raises(ValueError):
        forward_return(transform_input(fields=("close",), anchor=(1.0,), rows=((0.0,),)))
    with pytest.raises(ValueError):
        forward_return(transform_input(fields=("close",), anchor=(-5.0,), rows=((1.0,),)))
    with pytest.raises(ValueError):
        forward_return(
            transform_input(fields=("close",), anchor=(1.0,), rows=((1.0,), (2.0,)))
        )


def test_mfe_formula():
    mfe = maximum_favorable_excursion(
        transform_input(
            fields=("close", "high"),
            anchor=(100.0, 100.0),
            rows=((90.0, 95.0), (110.0, 120.0), (80.0, 85.0)),
        )
    )
    assert mfe == pytest.approx(0.2)  # 120/100 - 1
    assert mfe > 0.0


def test_mfe_zero_when_no_rise():
    mfe = maximum_favorable_excursion(
        transform_input(
            fields=("close", "high"),
            anchor=(100.0, 100.0),
            rows=((90.0, 95.0), (80.0, 85.0)),
        )
    )
    assert mfe == 0.0
    assert type(mfe) is float


def test_mae_formula():
    mae = maximum_adverse_excursion(
        transform_input(
            fields=("close", "low"),
            anchor=(100.0, 100.0),
            rows=((90.0, 85.0), (110.0, 105.0), (80.0, 75.0)),
        )
    )
    assert mae == pytest.approx(-0.25)  # 75/100 - 1, signed, not absolute
    assert mae < 0.0


def test_mae_zero_when_no_fall():
    mae = maximum_adverse_excursion(
        transform_input(
            fields=("close", "low"),
            anchor=(100.0, 100.0),
            rows=((110.0, 105.0), (120.0, 115.0)),
        )
    )
    assert mae == 0.0
    assert type(mae) is float


def test_excursion_domain_errors():
    with pytest.raises(ValueError):
        maximum_favorable_excursion(
            transform_input(fields=("close", "high"), anchor=(0.0, 0.0), rows=((1.0, 2.0),))
        )
    with pytest.raises(ValueError):
        maximum_favorable_excursion(
            transform_input(fields=("close", "high"), anchor=(1.0, 1.0), rows=((1.0, 0.0),))
        )
    with pytest.raises(ValueError):
        maximum_adverse_excursion(
            transform_input(fields=("close", "low"), anchor=(1.0, 1.0), rows=((1.0, -3.0),))
        )


def test_negative_zero_normalization_and_no_rounding():
    value = forward_return(
        transform_input(fields=("close",), anchor=(100.0,), rows=((100.0,),))
    )
    assert value == 0.0
    assert math.copysign(1.0, value) == 1.0  # never -0.0
    # No rounding: the result is the raw double division, exactly equal to
    # the same computation evaluated inline.
    value = forward_return(
        transform_input(fields=("close",), anchor=(3.0,), rows=((4.0,),))
    )
    assert value == 4.0 / 3.0 - 1.0


# ---------------------------------------------------------------------------
# C. Anchor binding.
# ---------------------------------------------------------------------------


def test_exact_aligned_anchor_accepted(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.value == pytest.approx(0.0)  # 110 / 110 - 1
    assert value.anchor_canonical_row_version_id == (
        bar_of(fixtures.a, "2026-07-01 13:35:00").canonical_row_version_id
    )


def test_anchor_missing_incomplete_no_invocation(fixtures):
    req = request()
    versions = versions_of(fixtures.a, "2026-07-01 13:30:00", "2026-07-01 13:31:00")
    sample = hand_sample([fixtures.a, fixtures.f], versions, req,
                         label_versions=versions_of(fixtures.f, "2026-07-01 13:36:00"))
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, sample.sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_ANCHOR_ROW
    assert value.value is None
    assert value.anchor_canonical_row_version_id is None
    assert value.consumed_label_canonical_row_version_ids == ()
    assert value.actual_label_end_time is None
    assert result.diagnostics.transform_invocation_count == 0


def test_older_feature_row_never_substitutes_for_anchor(fixtures):
    # The 13:34 row is present but the exact 13:35 anchor is not; the older
    # row never substitutes, so the label stays MISSING_ANCHOR_ROW.
    req = request()
    versions = versions_of(fixtures.a, "2026-07-01 13:34:00")
    sample = hand_sample([fixtures.a, fixtures.f], versions, req,
                         label_versions=versions_of(fixtures.f, "2026-07-01 13:36:00"))
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, sample.sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_ANCHOR_ROW


def test_anchor_wrong_code_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    req = request(code="US.NVDA")
    sample = hand_sample([fixtures.a], (bar.canonical_row_version_id,), req)
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=1)])


def test_anchor_wrong_interval_rejected(fixtures):
    bar = replace(bar_of(fixtures.a, "2026-07-01 13:35:00"), interval="5m")
    bad_build = replace(
        fixtures.a,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    sample = hand_sample([bad_build], (bar.canonical_row_version_id,), request())
    pit = hand_result([bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([bad_build], pit, [forward_spec("fr", horizon=1)])


def test_anchor_wrong_session_rejected(fixtures):
    bar = replace(bar_of(fixtures.a, "2026-07-01 13:35:00"), requested_session="REGULAR")
    bad_build = replace(
        fixtures.a,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    sample = hand_sample([bad_build], (bar.canonical_row_version_id,), request())
    pit = hand_result([bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([bad_build], pit, [forward_spec("fr", horizon=1)])


def test_anchor_wrong_market_calendar_date_rejected(fixtures):
    bar = replace(
        bar_of(fixtures.a, "2026-07-01 13:35:00"),
        market_calendar_date=date(2026, 7, 2),
    )
    bad_build = replace(
        fixtures.a,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    sample = hand_sample([bad_build], (bar.canonical_row_version_id,), request())
    pit = hand_result([bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([bad_build], pit, [forward_spec("fr", horizon=1)])


def test_anchor_market_future_rejected(fixtures):
    bar = replace(
        bar_of(fixtures.a, "2026-07-01 13:35:00"),
        market_available_at=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
    )
    bad_build = replace(
        fixtures.a,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    sample = hand_sample([bad_build], (bar.canonical_row_version_id,), request())
    pit = hand_result([bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([bad_build], pit, [forward_spec("fr", horizon=1)])


def test_anchor_archive_future_rejected(fixtures):
    bar = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a],
        (bar.canonical_row_version_id,),
        request(),
        dataset_as_of=datetime(2026, 7, 1, 13, 59, tzinfo=UTC),
    )
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=1)])


def test_out_of_order_feature_rows_rejected(fixtures):
    # Reversed PIT position order is a provenance inconsistency and fails
    # closed; it is never downgraded to INCOMPLETE.
    req = request()
    reversed_versions = versions_of(
        fixtures.a, "2026-07-01 13:35:00", "2026-07-01 13:34:00"
    )
    sample = hand_sample([fixtures.a], reversed_versions, req)
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=1)])


# ---------------------------------------------------------------------------
# D. Label target / window.
# ---------------------------------------------------------------------------


def test_h1_target_event_time_equals_feature_close(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.value == pytest.approx(100.0 / 110.0 - 1.0)
    consumed = value.consumed_label_canonical_row_version_ids
    assert consumed == (bar_of(fixtures.f, "2026-07-01 13:36:00").canonical_row_version_id,)


def test_h2_target_event_time_equals_feature_close_plus_interval(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.value == pytest.approx(0.0)  # 110 / 110 - 1
    assert value.consumed_label_canonical_row_version_ids == (
        bar_of(fixtures.f, "2026-07-01 13:37:00").canonical_row_version_id,
    )


def test_request_window_covers_multiple_horizons(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f],
        pit,
        [forward_spec("fr", horizon=2), mfe_spec("mfe", horizon=5)],
    )
    assert result.samples[0].status == LABEL_STATUS_COMPLETE
    assert result.samples[0].values[0].status == LABEL_STATUS_COMPLETE
    assert result.samples[0].values[1].status == LABEL_STATUS_COMPLETE


def test_extra_later_rows_ignored(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    # The 13:36..13:41 rows exist in the window, but only the exact 13:37
    # target enters the forward transform.
    assert value.consumed_label_canonical_row_version_ids == (
        bar_of(fixtures.f, "2026-07-01 13:37:00").canonical_row_version_id,
    )
    mfe_value = executed_value(
        execute_builtin_labels(
            [fixtures.a, fixtures.f], pit, [mfe_spec("mfe", horizon=2)]
        ),
        pit.samples[0].sample_key,
        "mfe",
    )
    assert mfe_value.consumed_label_canonical_row_version_ids == versions_of(
        fixtures.f, "2026-07-01 13:36:00", "2026-07-01 13:37:00"
    )


def test_target_missing_incomplete_no_invocation(fixtures):
    pit = assemble([fixtures.a, fixtures.fmin], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.fmin], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_TARGET_ROW
    assert value.value is None
    assert value.consumed_label_canonical_row_version_ids == ()
    assert result.diagnostics.transform_invocation_count == 0


def test_nearest_other_row_never_substitutes_for_target(fixtures):
    # The 13:36 row is present but the exact 13:37 target is not; the
    # nearby row never substitutes.
    pit = assemble([fixtures.a, fixtures.fmin], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.fmin], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_TARGET_ROW


def test_label_window_missing_rejected(fixtures):
    req = request(label_start=None, label_close=None)
    sample = hand_sample([fixtures.a], versions_of(fixtures.a, "2026-07-01 13:35:00"), req)
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=1)])


def test_label_window_start_mismatch_rejected(fixtures):
    req = request(label_start=datetime(2026, 7, 1, 13, 37, tzinfo=UTC))
    sample = hand_sample([fixtures.a], versions_of(fixtures.a, "2026-07-01 13:35:00"), req)
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=1)])


def test_label_window_close_insufficient_rejected(fixtures):
    req = request(
        label_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_close=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
    )
    sample = hand_sample([fixtures.a], versions_of(fixtures.a, "2026-07-01 13:35:00"), req)
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=2)])


# ---------------------------------------------------------------------------
# E. Forward completeness.
# ---------------------------------------------------------------------------


def test_forward_target_present_middle_bars_missing_complete(fixtures):
    # The 13:37 target exists while the 13:36 intermediate bar is missing;
    # the forward label is still COMPLETE because it only requires the
    # anchor and the exact target.
    req = request()
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    target = bar_of(fixtures.f, "2026-07-01 13:37:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(target.canonical_row_version_id,),
    )
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, sample.sample_key, "fr")
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.value == pytest.approx(0.0)
    assert value.consumed_label_canonical_row_version_ids == (
        target.canonical_row_version_id,
    )


def test_forward_invocation_receives_only_anchor_and_target(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert value.value == pytest.approx(0.0)  # target 110 over anchor 110
    assert result.diagnostics.transform_invocation_count == 1


def test_forward_actual_end_from_target_market_available_at(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    # The 13:37 target bar becomes market-available at 13:38 UTC.
    assert value.actual_label_end_time == datetime(2026, 7, 1, 13, 38, tzinfo=UTC)


# ---------------------------------------------------------------------------
# F. Excursion completeness.
# ---------------------------------------------------------------------------


def test_excursion_full_window_complete(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [mfe_spec("mfe", horizon=5)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "mfe")
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.value == pytest.approx(142.0 / 110.0 - 1.0)
    assert value.consumed_label_canonical_row_version_ids == versions_of(
        fixtures.f,
        "2026-07-01 13:36:00", "2026-07-01 13:37:00", "2026-07-01 13:38:00",
        "2026-07-01 13:39:00", "2026-07-01 13:40:00",
    )


def test_excursion_mae_signed_not_absolute(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [mae_spec("mae", horizon=5)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "mae")
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.value == pytest.approx(98.0 / 110.0 - 1.0)
    assert value.value < 0.0


def test_excursion_internal_gap_non_contiguous(fixtures):
    pit = assemble([fixtures.a, fixtures.fgap], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.fgap], pit, [mfe_spec("mfe", horizon=5)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "mfe")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS
    assert value.value is None
    # The actually present required rows are recorded in expected position
    # order: 13:36, 13:37, 13:39, 13:40.
    assert value.consumed_label_canonical_row_version_ids == versions_of(
        fixtures.fgap,
        "2026-07-01 13:36:00", "2026-07-01 13:37:00",
        "2026-07-01 13:39:00", "2026-07-01 13:40:00",
    )
    # The subset's last row's actual availability is recorded (13:40 ->
    # 13:41 UTC), but it never makes the label COMPLETE.
    assert value.actual_label_end_time == datetime(2026, 7, 1, 13, 41, tzinfo=UTC)


def test_excursion_boundary_row_insufficient(fixtures):
    pit = assemble([fixtures.a, fixtures.ffirst], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.ffirst], pit, [mfe_spec("mfe", horizon=5)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "mfe")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_INSUFFICIENT_ROWS
    assert value.value is None
    assert value.consumed_label_canonical_row_version_ids == versions_of(
        fixtures.ffirst,
        "2026-07-01 13:37:00", "2026-07-01 13:38:00",
        "2026-07-01 13:39:00", "2026-07-01 13:40:00",
    )


def test_excursion_target_missing(fixtures):
    pit = assemble([fixtures.a, fixtures.ftarget], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.ftarget], pit, [mfe_spec("mfe", horizon=5)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "mfe")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_TARGET_ROW
    assert value.value is None
    assert value.consumed_label_canonical_row_version_ids == versions_of(
        fixtures.ftarget,
        "2026-07-01 13:36:00", "2026-07-01 13:37:00",
        "2026-07-01 13:38:00", "2026-07-01 13:39:00",
    )
    assert value.actual_label_end_time == datetime(2026, 7, 1, 13, 40, tzinfo=UTC)


def test_excursion_incomplete_never_invokes_transform(fixtures):
    pit = assemble([fixtures.a, fixtures.fgap], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.fgap], pit, [mfe_spec("mfe", horizon=5)]
    )
    assert result.diagnostics.transform_invocation_count == 0


# ---------------------------------------------------------------------------
# G. PIT / clocks / provenance.
# ---------------------------------------------------------------------------


def test_only_pit_label_ids_consumed(fixtures):
    # The build contains the 13:41 bar, but the sample's PIT Label window
    # stops at 13:41 (half-open), so the unselected row never enters the
    # transform; the consumed ids equal the PIT label list exactly.
    req = request(label_close=datetime(2026, 7, 1, 13, 41, tzinfo=UTC))
    pit = assemble([fixtures.a, fixtures.f], [req])
    sample = pit.samples[0]
    assert len(sample.label_canonical_row_version_ids) == 5  # 13:36..13:40
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [mfe_spec("mfe", horizon=5)]
    )
    value = executed_value(result, sample.sample_key, "mfe")
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.value == pytest.approx(142.0 / 110.0 - 1.0)
    assert value.consumed_label_canonical_row_version_ids == (
        sample.label_canonical_row_version_ids
    )


def test_feature_rows_only_serve_as_anchor(fixtures):
    # A 13:36 row in the Feature list never serves as a future observation
    # row: the forward target stays MISSING_TARGET_ROW.
    req = request()
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    future_in_feature = bar_of(fixtures.f, "2026-07-01 13:36:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f],
        (anchor.canonical_row_version_id, future_in_feature.canonical_row_version_id),
        req,
    )
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, sample.sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_TARGET_ROW


def test_label_row_market_available_at_equal_close_accepted(fixtures):
    req = request(label_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC))
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"),
        market_available_at=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
    )
    bad_build = replace(
        fixtures.f,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a, bad_build],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(bar.canonical_row_version_id,),
    )
    pit = hand_result([fixtures.a, bad_build], [sample])
    result = execute_builtin_labels(
        [fixtures.a, bad_build], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, sample.sample_key, "fr")
    assert value.status == LABEL_STATUS_COMPLETE


def test_label_row_market_available_at_after_close_rejected(fixtures):
    req = request(label_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC))
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"),
        market_available_at=datetime(2026, 7, 1, 13, 43, tzinfo=UTC),
    )
    bad_build = replace(
        fixtures.f,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a, bad_build],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(bar.canonical_row_version_id,),
    )
    pit = hand_result([fixtures.a, bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, bad_build], pit, [forward_spec("fr", horizon=1)]
        )


def test_label_row_archive_available_at_equal_as_of_accepted(fixtures):
    as_of = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    pit = assemble([fixtures.a, fixtures.f], [request()], dataset_as_of=as_of)
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    assert result.samples[0].status == LABEL_STATUS_COMPLETE


def test_label_row_archive_available_at_after_as_of_rejected(fixtures):
    req = request()
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    bar = bar_of(fixtures.f, "2026-07-01 13:36:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(bar.canonical_row_version_id,),
        dataset_as_of=datetime(2026, 7, 1, 13, 59, tzinfo=UTC),
    )
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
        )


def test_dataset_as_of_none_skips_archive_clock(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    assert result.samples[0].status == LABEL_STATUS_COMPLETE


def test_label_row_cross_market_date_rejected(fixtures):
    req = request()
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"),
        market_calendar_date=date(2026, 7, 2),
    )
    bad_build = replace(
        fixtures.f,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a, bad_build],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(bar.canonical_row_version_id,),
    )
    pit = hand_result([fixtures.a, bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, bad_build], pit, [forward_spec("fr", horizon=1)]
        )


def test_label_row_wrong_code_rejected(fixtures):
    req = request()
    bar = replace(bar_of(fixtures.f, "2026-07-01 13:36:00"), code="US.NVDA")
    bad_build = replace(
        fixtures.f,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a, bad_build],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(bar.canonical_row_version_id,),
    )
    pit = hand_result([fixtures.a, bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, bad_build], pit, [forward_spec("fr", horizon=1)]
        )


def test_missing_row_version_rejected(fixtures):
    # The sample references a row version no supplied build contains; the
    # executor fails closed instead of guessing.
    req = request()
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    phantom = sha("phantom-row-version")
    sample = hand_sample(
        [fixtures.a, fixtures.f],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(phantom,),
    )
    pit = hand_result(
        [fixtures.a, fixtures.f], [sample], pins=[make_pin(b, set(), {}, row_versions=()) for b in (fixtures.a, fixtures.f)]
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
        )


def test_conflicting_row_mapping_rejected(fixtures):
    # The same row version id with conflicting content across builds fails
    # closed during reconciliation — the "newest build" never wins.
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"),
        close=999.0,
    )
    bad_build = replace(
        fixtures.f,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f, bad_build],
        (anchor.canonical_row_version_id,),
        request(),
    )
    pit = hand_result([fixtures.a, fixtures.f, bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, fixtures.f, bad_build], pit, [forward_spec("fr", horizon=1)]
        )


def test_pin_binding_still_enforced(fixtures):
    # A tampered pin (extra source snapshot) fails the exact bidirectional
    # verification before any value is computed.
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    future = bar_of(fixtures.f, "2026-07-01 13:36:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f],
        (anchor.canonical_row_version_id,),
        request(),
        label_versions=(future.canonical_row_version_id,),
    )
    bars_by_version = {
        bar.canonical_row_version_id: bar
        for build in (fixtures.a, fixtures.f)
        for bar in build.bars
    }
    selected = {anchor.canonical_row_version_id, future.canonical_row_version_id}
    tampered = [
        make_pin(build, selected, bars_by_version,
                 source_snapshots=()) for build in (fixtures.a, fixtures.f)
    ]
    pit = hand_result([fixtures.a, fixtures.f], [sample], pins=tampered)
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
        )


def test_build_and_spec_input_permutation_deterministic(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    specs = [forward_spec("fr", horizon=2), mfe_spec("mfe", horizon=5)]
    first = execute_builtin_labels([fixtures.a, fixtures.f], pit, specs)
    second = execute_builtin_labels([fixtures.f, fixtures.a], pit, list(reversed(specs)))
    assert first == second


# ---------------------------------------------------------------------------
# H. actual_label_end_time.
# ---------------------------------------------------------------------------


def test_complete_actual_end_uses_market_available_at(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    # The consumed 13:36 target bar: event_time 13:36, market_available_at
    # 13:37. The end uses market availability, never event_time and never
    # the nominal horizon close.
    assert value.actual_label_end_time == datetime(2026, 7, 1, 13, 37, tzinfo=UTC)


def test_incomplete_without_future_subset_actual_end_none(fixtures):
    pit = assemble([fixtures.a, fixtures.fmin], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.fmin], pit, [forward_spec("fr", horizon=2)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.actual_label_end_time is None


def test_incomplete_with_subset_actual_end_last_availability(fixtures):
    pit = assemble([fixtures.a, fixtures.ftarget], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.ftarget], pit, [mfe_spec("mfe", horizon=5)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "mfe")
    assert value.status == LABEL_STATUS_INCOMPLETE
    # Subset ends at 13:39 -> market_available_at 13:40; a non-null end
    # never upgrades the status.
    assert value.actual_label_end_time == datetime(2026, 7, 1, 13, 40, tzinfo=UTC)
    assert value.status == LABEL_STATUS_INCOMPLETE


def test_sample_actual_end_is_max_of_value_ends(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f],
        pit,
        [forward_spec("fr", horizon=1), forward_spec("fr3", horizon=3)],
    )
    sample = result.samples[0]
    assert sample.status == LABEL_STATUS_COMPLETE
    assert sample.actual_label_end_time == datetime(2026, 7, 1, 13, 39, tzinfo=UTC)
    assert sample.actual_label_end_time == max(
        value.actual_label_end_time for value in sample.values
    )


def test_sample_complete_requires_actual_end(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    sample = result.samples[0]
    assert sample.status == LABEL_STATUS_COMPLETE
    assert sample.actual_label_end_time is not None


def test_actual_end_before_feature_close_rejected(fixtures):
    req = request()
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"),
        market_available_at=datetime(2026, 7, 1, 13, 35, tzinfo=UTC),
    )
    bad_build = replace(
        fixtures.f,
        bars=(bar,),
        canonical_row_version_ids=(bar.canonical_row_version_id,),
    )
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a, bad_build],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=(bar.canonical_row_version_id,),
    )
    pit = hand_result([fixtures.a, bad_build], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, bad_build], pit, [forward_spec("fr", horizon=1)]
        )


# ---------------------------------------------------------------------------
# I. Outputs.
# ---------------------------------------------------------------------------


def test_output_float64_strict_type(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, pit.samples[0].sample_key, "fr")
    assert type(value.value) is float


def test_output_validation_rejects_nan_inf_and_type_drift():
    spec = forward_spec("fr", horizon=1)
    registration = resolved_registration(spec)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(LabelExecutionError):
            _validate_output_value(bad, spec, registration)
    for bad in (True, 5, "5", None, [1.0]):
        with pytest.raises(LabelExecutionError):
            _validate_output_value(bad, spec, registration)
    assert _validate_output_value(2.5, spec, registration) == 2.5


def test_output_int64_strict_type_and_direction_range():
    spec = label_spec(
        "fd", REF_FORWARD_DIRECTION, ("close",), "int64",
        horizon=2, start_offset=1, end_offset=1,
    )
    registration = resolved_registration(spec)
    for bad in (1.5, True, 5, -2, "1", None, [1]):
        with pytest.raises(LabelExecutionError):
            _validate_output_value(bad, spec, registration)
    for good in (-1, 0, 1):
        assert _validate_output_value(good, spec, registration) == good
    with pytest.raises(LabelExecutionError):
        _validate_output_value(2**63, spec, registration)
    with pytest.raises(LabelExecutionError):
        _validate_output_value(-(2**63) - 1, spec, registration)


def test_transform_exception_wrapped(fixtures):
    # A non-positive anchor close makes the built-in transform raise; the
    # executor wraps it as LabelExecutionError with the __cause__ chain.
    anchor = replace(
        bar_of(fixtures.a, "2026-07-01 13:35:00"),
        close=-5.0,
    )
    bad_build = replace(
        fixtures.a,
        bars=(anchor,),
        canonical_row_version_ids=(anchor.canonical_row_version_id,),
    )
    future = bar_of(fixtures.f, "2026-07-01 13:36:00")
    sample = hand_sample(
        [bad_build, fixtures.f],
        (anchor.canonical_row_version_id,),
        request(),
        label_versions=(future.canonical_row_version_id,),
    )
    pit = hand_result([bad_build, fixtures.f], [sample])
    with pytest.raises(LabelExecutionError) as exc_info:
        execute_builtin_labels(
            [bad_build, fixtures.f], pit, [forward_spec("fr", horizon=1)]
        )
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_registry_resolve_errors_wrapped_as_label_execution_error(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    minutes = label_spec(
        "fr_min", REF_FORWARD_RETURN, ("close",), "float64",
        unit="MINUTES", horizon=2, start_offset=1, end_offset=1,
    )
    with pytest.raises(LabelExecutionError) as exc_info:
        execute_builtin_labels([fixtures.a, fixtures.f], pit, [minutes])
    assert isinstance(exc_info.value.__cause__, TransformRegistryError)


def test_shape_violation_fails_closed(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    bad_shape = label_spec(
        "fr_bad", REF_FORWARD_RETURN, ("close",), "float64",
        horizon=3, start_offset=0, end_offset=1,
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a, fixtures.f], pit, [bad_shape])
    bad_end = label_spec(
        "mfe_bad", REF_MFE, ("close", "high"), "float64",
        horizon=5, start_offset=0, end_offset=3,
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a, fixtures.f], pit, [bad_end])


# ---------------------------------------------------------------------------
# J. Result models.
# ---------------------------------------------------------------------------


def test_result_models_frozen():
    with pytest.raises(FrozenInstanceError):
        LabelTransformInput(
            field_names=("close",),
            anchor_row=(1.0,),
            rows=((2.0,),),
            parameters=(),
            alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        ).anchor_row = ()
    with pytest.raises(FrozenInstanceError):
        LabelValueResult(
            label_name="x",
            spec_pin=SpecPin(kind="LABEL", name="x", version="v1", content_sha256=sha("x")),
            implementation_pin=ImplementationPin(name="i", version="v1", content_sha256=sha("i")),
            status=LABEL_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            anchor_canonical_row_version_id=sha("a"),
            consumed_label_canonical_row_version_ids=(sha("c"),),
            actual_label_end_time=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        ).value = 2.0


def test_value_result_requires_label_spec_pin():
    pin = SpecPin(kind="FEATURE", name="x", version="v1", content_sha256=sha("x"))
    implementation = ImplementationPin(name="i", version="v1", content_sha256=sha("i"))
    with pytest.raises(LabelExecutionError):
        LabelValueResult(
            label_name="x",
            spec_pin=pin,
            implementation_pin=implementation,
            status=LABEL_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            anchor_canonical_row_version_id=sha("a"),
            consumed_label_canonical_row_version_ids=(sha("c"),),
            actual_label_end_time=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        )


def test_value_result_requires_non_null_implementation_hash():
    label_pin = SpecPin(kind="LABEL", name="x", version="v1", content_sha256=sha("x"))
    with pytest.raises(LabelExecutionError):
        LabelValueResult(
            label_name="x",
            spec_pin=label_pin,
            implementation_pin=ImplementationPin(name="i", version="v1", content_sha256=None),
            status=LABEL_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            anchor_canonical_row_version_id=sha("a"),
            consumed_label_canonical_row_version_ids=(sha("c"),),
            actual_label_end_time=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        )


def test_value_result_rejects_duplicate_consumed_ids():
    label_pin = SpecPin(kind="LABEL", name="x", version="v1", content_sha256=sha("x"))
    implementation = ImplementationPin(name="i", version="v1", content_sha256=sha("i"))
    with pytest.raises(LabelExecutionError):
        LabelValueResult(
            label_name="x",
            spec_pin=label_pin,
            implementation_pin=implementation,
            status=LABEL_STATUS_COMPLETE,
            value=1.0,
            reason_code=None,
            anchor_canonical_row_version_id=sha("a"),
            consumed_label_canonical_row_version_ids=(sha("c"), sha("c")),
            actual_label_end_time=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        )


def test_sample_result_requires_stable_value_ordering():
    label_pin = SpecPin(kind="LABEL", name="z", version="v1", content_sha256=sha("z"))
    implementation = ImplementationPin(name="i", version="v1", content_sha256=sha("i"))
    value = LabelValueResult(
        label_name="z",
        spec_pin=label_pin,
        implementation_pin=implementation,
        status=LABEL_STATUS_COMPLETE,
        value=1.0,
        reason_code=None,
        anchor_canonical_row_version_id=sha("a"),
        consumed_label_canonical_row_version_ids=(sha("c"),),
        actual_label_end_time=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
    )
    with pytest.raises(LabelExecutionError):
        LabelSampleResult(
            sample_key="k",
            sample_version_id="v",
            code="US.MU",
            feature_window_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            values=(value,),
            status=LABEL_STATUS_INCOMPLETE,
            actual_label_end_time=None,
        )
    with pytest.raises(LabelExecutionError):
        LabelSampleResult(
            sample_key="k",
            sample_version_id="v",
            code="US.MU",
            feature_window_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            values=(value,),
            status=LABEL_STATUS_COMPLETE,
            actual_label_end_time=None,
        )


def test_sample_status_recomputed(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    assert result.samples[0].status == LABEL_STATUS_COMPLETE
    incomplete_pit = assemble([fixtures.a, fixtures.fmin], [request()])
    incomplete = execute_builtin_labels(
        [fixtures.a, fixtures.fmin], incomplete_pit, [forward_spec("fr", horizon=2)]
    )
    assert incomplete.samples[0].status == LABEL_STATUS_INCOMPLETE


def test_execution_result_coverage_and_diagnostics(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    diagnostics = result.diagnostics
    assert diagnostics.sample_count == 1
    assert diagnostics.label_spec_count == 1
    assert diagnostics.complete_sample_count == 1
    assert diagnostics.incomplete_sample_count == 0
    assert diagnostics.complete_value_count == 1
    assert diagnostics.incomplete_value_count == 0
    assert diagnostics.transform_invocation_count == 1
    assert diagnostics.complete_value_count + diagnostics.incomplete_value_count == (
        diagnostics.sample_count * diagnostics.label_spec_count
    )
    assert diagnostics.transform_invocation_count == diagnostics.complete_value_count


def test_execution_result_rejects_duplicate_spec_pin_identity(fixtures):
    pin = SpecPin(kind="LABEL", name="x", version="v1", content_sha256=sha("x"))
    conflict = SpecPin(kind="LABEL", name="x", version="v1", content_sha256=sha("y"))
    implementation = ImplementationPin(name="i", version="v1", content_sha256=sha("i"))
    diagnostics = LabelExecutionDiagnostics(
        sample_count=0,
        label_spec_count=0,
        complete_sample_count=0,
        incomplete_sample_count=0,
        complete_value_count=0,
        incomplete_value_count=0,
        transform_invocation_count=0,
    )
    with pytest.raises(LabelExecutionError):
        LabelExecutionResult(
            samples=(),
            label_spec_pins=(pin, conflict),
            implementation_pins=(implementation,),
            diagnostics=diagnostics,
            execution_contract_version=LABEL_EXECUTION_CONTRACT_VERSION,
        )


def test_execution_result_diagnostics_recomputed(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    wrong = LabelExecutionDiagnostics(
        sample_count=1,
        label_spec_count=1,
        complete_sample_count=1,
        incomplete_sample_count=0,
        complete_value_count=0,
        incomplete_value_count=1,
        transform_invocation_count=0,
    )
    with pytest.raises(LabelExecutionError):
        LabelExecutionResult(
            samples=result.samples,
            label_spec_pins=result.label_spec_pins,
            implementation_pins=result.implementation_pins,
            diagnostics=wrong,
            execution_contract_version=LABEL_EXECUTION_CONTRACT_VERSION,
        )


# ---------------------------------------------------------------------------
# K. Multiple labels.
# ---------------------------------------------------------------------------


def test_different_transforms_executed_together(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f],
        pit,
        [
            forward_spec("fr", horizon=2),
            label_spec(
                "fd", REF_FORWARD_DIRECTION, ("close",), "int64",
                horizon=2, start_offset=1, end_offset=1,
            ),
            mfe_spec("mfe", horizon=5),
            mae_spec("mae", horizon=5),
        ],
    )
    sample = result.samples[0]
    assert sample.status == LABEL_STATUS_COMPLETE
    values = {value.label_name: value for value in sample.values}
    assert values["fr"].value == pytest.approx(0.0)
    assert values["fd"].value == 0
    assert values["mfe"].value == pytest.approx(142.0 / 110.0 - 1.0)
    assert values["mae"].value == pytest.approx(98.0 / 110.0 - 1.0)
    assert result.diagnostics.transform_invocation_count == 4


def test_different_horizons_share_one_pit_window(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f],
        pit,
        [forward_spec("fr2", horizon=2), mfe_spec("mfe", horizon=5)],
    )
    assert result.samples[0].status == LABEL_STATUS_COMPLETE
    assert all(value.status == LABEL_STATUS_COMPLETE for value in result.samples[0].values)


def test_same_transform_shared_implementation_pin(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f],
        pit,
        [forward_spec("fr2", horizon=2), forward_spec("fr5", horizon=5)],
    )
    assert len(result.label_spec_pins) == 2
    assert len(result.implementation_pins) == 1
    pins = {value.implementation_pin for value in result.samples[0].values}
    assert len(pins) == 1


def test_spec_input_reversal_equals(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    specs = [forward_spec("fr", horizon=2), mfe_spec("mfe", horizon=5)]
    first = execute_builtin_labels([fixtures.a, fixtures.f], pit, specs)
    second = execute_builtin_labels([fixtures.a, fixtures.f], pit, list(reversed(specs)))
    assert first == second


def test_empty_pit_samples_with_nonempty_specs_deterministic(fixtures):
    pit = hand_result([], [])
    result = execute_builtin_labels(
        [], pit, [forward_spec("fr", horizon=2), mfe_spec("mfe", horizon=5)]
    )
    assert result.samples == ()
    assert result.diagnostics.sample_count == 0
    assert result.diagnostics.label_spec_count == 2
    assert result.diagnostics.transform_invocation_count == 0
    assert result.label_spec_pins
    assert result.implementation_pins
    again = execute_builtin_labels(
        [], pit, [mfe_spec("mfe", horizon=5), forward_spec("fr", horizon=2)]
    )
    assert result == again


def test_empty_label_specs_rejected(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a, fixtures.f], pit, [])


def test_feature_spec_directly_rejected(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    from market_vault.dataset import (
        FEATURE_SPEC_SCHEMA_VERSION,
        DatasetField as Field,
        FeatureSpec as FSpec,
    )

    spec = FSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="cb",
        version="v1",
        output=Field(name="cb", logical_type="float64", nullable=False),
        input_canonical_fields=("open", "close"),
        transform_ref=(
            "market_vault.dataset.feature_transforms.candle_body:candle_body"
        ),
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a, fixtures.f], pit, [spec])


# ---------------------------------------------------------------------------
# L. Feature regression through the shared provenance path.
# ---------------------------------------------------------------------------


def test_feature_execution_still_works_with_shared_provenance(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    from market_vault.dataset import FeatureSpec as FSpec
    from market_vault.dataset import FEATURE_SPEC_SCHEMA_VERSION
    from market_vault.dataset import DatasetField as Field

    spec = FSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="sr",
        version="v1",
        output=Field(name="sr", logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=(
            "market_vault.dataset.feature_transforms.simple_return:simple_return"
        ),
        parameters=(SpecParameter("window_bars", 2),),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )
    result = execute_builtin_features([fixtures.a, fixtures.f], pit, [spec])
    assert result.samples[0].status == "COMPLETE"
    # Label rows never enter the Feature transform.
    consumed = result.samples[0].values[0].consumed_canonical_row_version_ids
    assert set(consumed).isdisjoint(set(pit.samples[0].label_canonical_row_version_ids))


# ---------------------------------------------------------------------------
# M. Offline / no side effects.
# ---------------------------------------------------------------------------


def test_no_dataset_artifacts_or_side_effects(fixtures, tmp_path):
    cwd_before = os.getcwd()
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=2)]
    )
    assert os.getcwd() == cwd_before
    # No Dataset artifacts are generated anywhere near the repository.
    assert not (Path.cwd() / "data" / "datasets").exists()
    # No split was invoked: the label result is not a split result and
    # carries no split assignment fields.
    assert not hasattr(result, "split_assignment")
    assert not hasattr(result, "assignments")
    # No Parquet / Dataset / split artifacts were produced by the execution.
    root_before = sorted(str(path) for path in Path.cwd().iterdir())
    execute_builtin_labels([fixtures.a, fixtures.f], pit, [mfe_spec("mfe", horizon=5)])
    root_after = sorted(str(path) for path in Path.cwd().iterdir())
    assert root_after == root_before


def test_public_api_surface():
    from market_vault import dataset

    for name in (
        "LABEL_EXECUTION_CONTRACT_VERSION",
        "LABEL_TRANSFORM_CALL_CONTRACT_VERSION",
        "LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED",
        "LABEL_INCOMPLETE_MISSING_ANCHOR_ROW",
        "LABEL_INCOMPLETE_MISSING_TARGET_ROW",
        "LABEL_INCOMPLETE_INSUFFICIENT_ROWS",
        "LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS",
        "LABEL_STATUS_COMPLETE",
        "LABEL_STATUS_INCOMPLETE",
        "LabelExecutionError",
        "LabelTransformInput",
        "LabelValueResult",
        "LabelSampleResult",
        "LabelExecutionDiagnostics",
        "LabelExecutionResult",
        "built_in_label_registrations",
        "built_in_label_registry",
        "execute_builtin_labels",
    ):
        assert hasattr(dataset, name)
    # The private provenance helper and row-selection internals are never
    # part of the public export surface.
    for private in (
        "execution_provenance",
        "ExecutionProvenanceError",
        "normalize_verified_builds",
        "reconcile_canonical_rows",
        "verify_pit_pin_binding",
        "expected_canonical_build_pin",
        "ResolvedRow",
    ):
        assert private not in dataset.__all__


# ---------------------------------------------------------------------------
# N. Spec preflight independent of samples.
# ---------------------------------------------------------------------------


def test_alignment_rule_must_be_feature_close_aligned(fixtures):
    pit = assemble([fixtures.a, fixtures.f], [request()])
    bad = label_spec(
        "fr_align", REF_FORWARD_RETURN, ("close",), "float64",
        horizon=2, start_offset=1, end_offset=1, alignment="ALIGN_OPEN",
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a, fixtures.f], pit, [bad])


def test_alignment_rule_rejected_with_empty_samples(fixtures):
    pit = hand_result([], [])
    bad = label_spec(
        "fr_align", REF_FORWARD_RETURN, ("close",), "float64",
        horizon=2, start_offset=1, end_offset=1, alignment="ALIGN_OPEN",
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([], pit, [bad])


def test_forward_shape_violation_rejected_with_empty_samples(fixtures):
    pit = hand_result([], [])
    bad = label_spec(
        "fr_bad", REF_FORWARD_RETURN, ("close",), "float64",
        horizon=3, start_offset=0, end_offset=1,
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([], pit, [bad])


def test_excursion_shape_violation_rejected_with_empty_samples(fixtures):
    pit = hand_result([], [])
    bad = label_spec(
        "mfe_bad", REF_MFE, ("close", "high"), "float64",
        horizon=5, start_offset=0, end_offset=3,
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([], pit, [bad])


def test_spec_preflight_raises_before_any_invocation(fixtures):
    # The preflight rejection aborts the execution before the sample loop:
    # the error is raised even with zero samples, so no transform can ever
    # have been invoked (invocation count stays structurally zero).
    pit = hand_result([], [])
    bad = label_spec(
        "fr_align", REF_FORWARD_RETURN, ("close",), "float64",
        horizon=2, start_offset=1, end_offset=1, alignment="ALIGN_OPEN",
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([], pit, [bad])


def test_legal_empty_samples_with_legal_specs_still_succeed():
    pit = hand_result([], [])
    result = execute_builtin_labels(
        [], pit, [forward_spec("fr", horizon=2), mfe_spec("mfe", horizon=5)]
    )
    assert result.samples == ()
    assert result.diagnostics.transform_invocation_count == 0


# ---------------------------------------------------------------------------
# O. Anchor-missing must not skip Label-row validation.
# ---------------------------------------------------------------------------


def missing_anchor_pit(fixtures, label_bar):
    """A PIT result whose sample carries no exact anchor (only the 13:34
    Feature row) but includes the given (possibly tampered) Label bar.

    Returns ``(pit_result, sample, builds)`` where ``builds`` is the exact
    build set the PIT result was assembled from (the untampered ``a`` build
    plus the single-bar tampered Label build)."""
    req = request()
    versions = versions_of(fixtures.a, "2026-07-01 13:34:00")
    builds = [fixtures.a, label_bar.build]
    sample = hand_sample(
        builds,
        versions,
        req,
        label_versions=(label_bar.bar.canonical_row_version_id,),
    )
    return hand_result(builds, [sample]), sample, builds


class TamperedBuild:
    """A build carrying exactly one (possibly tampered) Label bar."""

    def __init__(self, fixtures, bar):
        self.build = replace(
            fixtures.f,
            bars=(bar,),
            canonical_row_version_ids=(bar.canonical_row_version_id,),
        )
        self.bar = bar


def test_missing_anchor_valid_label_rows_incomplete(fixtures):
    # The exact 13:35 anchor is absent from the Feature list while the
    # selected Label rows are perfectly legal: the label is INCOMPLETE
    # (MISSING_ANCHOR_ROW) and no transform is invoked.
    req = request()
    versions = versions_of(fixtures.a, "2026-07-01 13:30:00", "2026-07-01 13:31:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f], versions, req,
        label_versions=versions_of(fixtures.f, "2026-07-01 13:36:00"),
    )
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
    )
    value = executed_value(result, sample.sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_ANCHOR_ROW
    assert value.anchor_canonical_row_version_id is None
    assert value.consumed_label_canonical_row_version_ids == ()
    assert value.actual_label_end_time is None
    assert result.diagnostics.transform_invocation_count == 0


def test_missing_anchor_cross_market_date_label_row_rejected(fixtures):
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"),
        market_calendar_date=date(2026, 7, 2),
    )
    pit, _sample, builds = missing_anchor_pit(
        fixtures, TamperedBuild(fixtures, bar)
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(builds, pit, [forward_spec("fr", horizon=1)])


def test_missing_anchor_wrong_code_label_row_rejected(fixtures):
    bar = replace(bar_of(fixtures.f, "2026-07-01 13:36:00"), code="US.NVDA")
    pit, _sample, builds = missing_anchor_pit(
        fixtures, TamperedBuild(fixtures, bar)
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(builds, pit, [forward_spec("fr", horizon=1)])


def test_missing_anchor_wrong_interval_label_row_rejected(fixtures):
    bar = replace(bar_of(fixtures.f, "2026-07-01 13:36:00"), interval="5m")
    pit, _sample, builds = missing_anchor_pit(
        fixtures, TamperedBuild(fixtures, bar)
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(builds, pit, [forward_spec("fr", horizon=1)])


def test_missing_anchor_wrong_session_label_row_rejected(fixtures):
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"), requested_session="REGULAR"
    )
    pit, _sample, builds = missing_anchor_pit(
        fixtures, TamperedBuild(fixtures, bar)
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(builds, pit, [forward_spec("fr", horizon=1)])


def test_missing_anchor_wrong_adjustment_label_row_rejected(fixtures):
    bar = replace(bar_of(fixtures.f, "2026-07-01 13:36:00"), adjustment="DIV")
    pit, _sample, builds = missing_anchor_pit(
        fixtures, TamperedBuild(fixtures, bar)
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(builds, pit, [forward_spec("fr", horizon=1)])


def test_missing_anchor_market_future_label_row_rejected(fixtures):
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"),
        market_available_at=datetime(2026, 7, 1, 13, 43, tzinfo=UTC),
    )
    pit, _sample, builds = missing_anchor_pit(
        fixtures, TamperedBuild(fixtures, bar)
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(builds, pit, [forward_spec("fr", horizon=1)])


def test_missing_anchor_archive_future_label_row_rejected(fixtures):
    bar = bar_of(fixtures.f, "2026-07-01 13:36:00")
    req = request()
    versions = versions_of(fixtures.a, "2026-07-01 13:34:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f],
        versions,
        req,
        label_versions=(bar.canonical_row_version_id,),
        dataset_as_of=datetime(2026, 7, 1, 13, 59, tzinfo=UTC),
    )
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(
            [fixtures.a, fixtures.f], pit, [forward_spec("fr", horizon=1)]
        )


def test_missing_anchor_source_schema_mismatch_label_row_rejected(fixtures):
    bar = replace(
        bar_of(fixtures.f, "2026-07-01 13:36:00"), source_schema_version="9.9"
    )
    pit, _sample, builds = missing_anchor_pit(
        fixtures, TamperedBuild(fixtures, bar)
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels(builds, pit, [forward_spec("fr", horizon=1)])


# ---------------------------------------------------------------------------
# P. Safe horizon time arithmetic.
# ---------------------------------------------------------------------------


def test_huge_horizon_rejected_fast_without_overflow_leak(fixtures):
    # A horizon far beyond any realizable window fails the safe capacity
    # comparison immediately — no giant timedelta multiplication, no
    # range(horizon) loop, no OverflowError leak.
    pit = assemble([fixtures.a, fixtures.f], [request()])
    huge = label_spec(
        "mfe_huge", REF_MFE, ("close", "high"), "float64",
        horizon=2**40, start_offset=0, end_offset=2**40 - 1,
    )
    with pytest.raises(LabelExecutionError):
        execute_builtin_labels([fixtures.a, fixtures.f], pit, [huge])


def test_huge_horizon_with_covering_window_does_not_loop(fixtures):
    # A window can legally span ~4e9 minutes; with the excursion check
    # iterating actual rows only, the huge horizon is decided instantly
    # (target missing) instead of looping range(4e9).
    span = 4_000_000_000
    close = datetime(2026, 7, 1, 13, 36, tzinfo=UTC)
    label_close = close + timedelta(minutes=span)
    req = request(feature_close=close, label_close=label_close)
    anchor = bar_of(fixtures.a, "2026-07-01 13:35:00")
    sample = hand_sample(
        [fixtures.a, fixtures.f],
        (anchor.canonical_row_version_id,),
        req,
        label_versions=versions_of(fixtures.f, "2026-07-01 13:36:00", "2026-07-01 13:37:00"),
    )
    pit = hand_result([fixtures.a, fixtures.f], [sample])
    huge = label_spec(
        "mfe_huge", REF_MFE, ("close", "high"), "float64",
        horizon=span, start_offset=0, end_offset=span - 1,
    )
    result = execute_builtin_labels([fixtures.a, fixtures.f], pit, [huge])
    value = executed_value(result, sample.sample_key, "mfe_huge")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_TARGET_ROW
    assert value.consumed_label_canonical_row_version_ids == versions_of(
        fixtures.f, "2026-07-01 13:36:00", "2026-07-01 13:37:00"
    )


def test_feature_close_near_datetime_min_anchor_underflow_wrapped(fixtures):
    # The anchor subtraction underflows datetime.min; the raw OverflowError
    # never leaks past the public executor.
    req = request(
        feature_start=datetime(1, 1, 1, 0, 0, 0, tzinfo=UTC),
        feature_close=datetime(1, 1, 1, 0, 0, 30, tzinfo=UTC),
        label_start=datetime(1, 1, 1, 0, 0, 30, tzinfo=UTC),
        label_close=datetime(1, 1, 1, 0, 1, 30, tzinfo=UTC),
    )
    sample = hand_sample([fixtures.a], (), req)
    pit = hand_result([fixtures.a], [sample])
    with pytest.raises(LabelExecutionError) as exc_info:
        execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=1)])
    assert isinstance(exc_info.value.__cause__, OverflowError)


def test_feature_close_near_datetime_max_safe(fixtures):
    # Near datetime.max the window capacity and the anchor subtraction stay
    # exact and fail closed instead of leaking a raw date arithmetic error.
    close = datetime(9999, 12, 31, 23, 58, 0, tzinfo=UTC)
    req = request(
        feature_start=datetime(9999, 12, 31, 23, 57, 0, tzinfo=UTC),
        feature_close=close,
        label_start=close,
        label_close=datetime(9999, 12, 31, 23, 59, 0, tzinfo=UTC),
    )
    sample = hand_sample([fixtures.a], (), req)
    pit = hand_result([fixtures.a], [sample])
    result = execute_builtin_labels([fixtures.a], pit, [forward_spec("fr", horizon=1)])
    value = executed_value(result, sample.sample_key, "fr")
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.reason_code == LABEL_INCOMPLETE_MISSING_ANCHOR_ROW


def test_normal_horizons_unchanged_and_reason_priority_unchanged(fixtures):
    # H=1 / H=2 / H=5 results and the excursion reason priority are
    # unchanged by the actual-row traversal.
    pit = assemble([fixtures.a, fixtures.f], [request()])
    result = execute_builtin_labels(
        [fixtures.a, fixtures.f],
        pit,
        [
            forward_spec("fr1", horizon=1),
            forward_spec("fr2", horizon=2),
            mfe_spec("mfe", horizon=5),
        ],
    )
    assert result.samples[0].status == LABEL_STATUS_COMPLETE
    values = {value.label_name: value for value in result.samples[0].values}
    assert values["fr1"].value == pytest.approx(100.0 / 110.0 - 1.0)
    assert values["fr2"].value == pytest.approx(0.0)
    assert values["mfe"].value == pytest.approx(142.0 / 110.0 - 1.0)
    # Priority: target missing wins over the missing first row.
    pit_gap = assemble([fixtures.a, fixtures.ftarget], [request()])
    gap_result = execute_builtin_labels(
        [fixtures.a, fixtures.ftarget], pit_gap, [mfe_spec("mfe", horizon=5)]
    )
    assert gap_result.samples[0].values[0].reason_code == (
        LABEL_INCOMPLETE_MISSING_TARGET_ROW
    )
    # Priority: interior gap with the target present is NON_CONTIGUOUS.
    pit_mid = assemble([fixtures.a, fixtures.fgap], [request()])
    mid_result = execute_builtin_labels(
        [fixtures.a, fixtures.fgap], pit_mid, [mfe_spec("mfe", horizon=5)]
    )
    assert mid_result.samples[0].values[0].reason_code == (
        LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS
    )


# ---------------------------------------------------------------------------
# Q. INCOMPLETE LabelValueResult structural invariants.
# ---------------------------------------------------------------------------


def incomplete_value(
    *,
    reason: str,
    value=None,
    anchor=None,
    consumed=(),
    actual_end=None,
) -> LabelValueResult:
    label_pin = SpecPin(kind="LABEL", name="x", version="v1", content_sha256=sha("x"))
    implementation = ImplementationPin(name="i", version="v1", content_sha256=sha("i"))
    return LabelValueResult(
        label_name="x",
        spec_pin=label_pin,
        implementation_pin=implementation,
        status=LABEL_STATUS_INCOMPLETE,
        value=value,
        reason_code=reason,
        anchor_canonical_row_version_id=anchor,
        consumed_label_canonical_row_version_ids=consumed,
        actual_label_end_time=actual_end,
    )


def test_incomplete_missing_anchor_must_be_fully_empty():
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
            anchor=sha("a"),
            consumed=(),
            actual_end=None,
        )
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
            anchor=None,
            consumed=(sha("c"),),
            actual_end=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        )
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_MISSING_ANCHOR_ROW,
            anchor=None,
            consumed=(),
            actual_end=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        )
    ok = incomplete_value(reason=LABEL_INCOMPLETE_MISSING_ANCHOR_ROW)
    assert ok.anchor_canonical_row_version_id is None
    assert ok.consumed_label_canonical_row_version_ids == ()
    assert ok.actual_label_end_time is None


def test_incomplete_non_anchor_reasons_require_anchor_id():
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_MISSING_TARGET_ROW,
            anchor=None,
            consumed=(),
            actual_end=None,
        )
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_INSUFFICIENT_ROWS,
            anchor=None,
            consumed=(sha("c"),),
            actual_end=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        )
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
            anchor=None,
            consumed=(sha("c"),),
            actual_end=datetime(2026, 7, 1, 13, 37, tzinfo=UTC),
        )


def test_incomplete_consumed_and_actual_end_coupled():
    end = datetime(2026, 7, 1, 13, 37, tzinfo=UTC)
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_MISSING_TARGET_ROW,
            anchor=sha("a"),
            consumed=(sha("c"),),
            actual_end=None,
        )
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_MISSING_TARGET_ROW,
            anchor=sha("a"),
            consumed=(),
            actual_end=end,
        )


def test_incomplete_excursion_reasons_require_consumed_rows():
    end = datetime(2026, 7, 1, 13, 37, tzinfo=UTC)
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
            anchor=sha("a"),
            consumed=(),
            actual_end=None,
        )
    with pytest.raises(LabelExecutionError):
        incomplete_value(
            reason=LABEL_INCOMPLETE_INSUFFICIENT_ROWS,
            anchor=sha("a"),
            consumed=(),
            actual_end=None,
        )
    ok = incomplete_value(
        reason=LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS,
        anchor=sha("a"),
        consumed=(sha("c"), sha("d")),
        actual_end=end,
    )
    assert ok.status == LABEL_STATUS_INCOMPLETE


def test_execution_result_rejects_empty_pins():
    diagnostics = LabelExecutionDiagnostics(
        sample_count=0,
        label_spec_count=0,
        complete_sample_count=0,
        incomplete_sample_count=0,
        complete_value_count=0,
        incomplete_value_count=0,
        transform_invocation_count=0,
    )
    pin = SpecPin(kind="LABEL", name="x", version="v1", content_sha256=sha("x"))
    implementation = ImplementationPin(name="i", version="v1", content_sha256=sha("i"))
    with pytest.raises(LabelExecutionError):
        LabelExecutionResult(
            samples=(),
            label_spec_pins=(),
            implementation_pins=(implementation,),
            diagnostics=diagnostics,
            execution_contract_version=LABEL_EXECUTION_CONTRACT_VERSION,
        )
    with pytest.raises(LabelExecutionError):
        LabelExecutionResult(
            samples=(),
            label_spec_pins=(pin,),
            implementation_pins=(),
            diagnostics=diagnostics,
            execution_contract_version=LABEL_EXECUTION_CONTRACT_VERSION,
        )
