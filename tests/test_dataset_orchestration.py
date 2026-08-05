"""Offline deterministic tests for the Dataset orchestration core
(v0.5.0 PR-5).

Covers the public API and contract constants, the explicit supervised-build
input contract, scope/request validation, the authoritative logical schema
derivation and exact-match check, the fixed orchestration order (PIT,
Feature, Label, Split each exactly once over the same PIT result), strict
cross-layer sample binding, Feature EXCLUDED filtering, Label COMPLETE /
INCOMPLETE handling with the true ``actual_label_end_time`` handoff,
chronological split / purge invocation, the final logical rows under the
fixed physical sort, the scope-wide CompletionSummary with the four fixed
reason codes, the merged ImplementationPins, the identity core
(``dataset_schema_id`` / ``logical_dataset_content_id`` /
``DatasetIdentityInput`` / ``dataset_id``), identity sensitivity, empty
results, the fail-closed result model, the unified error boundary, and the
offline / no-side-effect boundary. All fixtures are micro synthetic
canonical builds produced through the verified reader; no network, no
OpenD, no current time, and no real market data.
"""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import market_vault.dataset as dataset_pkg
import market_vault.dataset.orchestration as orch_mod
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    DATASET_COMPLETION_REASON_FEATURE_EXCLUDED,
    DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE,
    DATASET_COMPLETION_REASON_LABEL_INCOMPLETE,
    DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST,
    DATASET_KIND_SUPERVISED,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_ORCHESTRATION_CONTRACT_VERSION,
    DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    FEATURE_EXECUTION_CONTRACT_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    FEATURE_VALUE_STATUS_COMPLETE,
    FEATURE_VALUE_STATUS_EXCLUDED,
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_EXECUTION_CONTRACT_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    PITAssemblyError,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY,
    REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
    REASON_CODE_INCOMPLETE_LABEL,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPLIT_STATUS_ASSIGNED,
    SPLIT_STATUS_EXCLUDED,
    SPLIT_STATUS_PURGED,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    ChronologicalSplitSpec,
    CompletionEntry,
    CompletionSummary,
    CrossTradingDayPolicy,
    DatasetField,
    DatasetOrchestrationDiagnostics,
    DatasetOrchestrationError,
    DatasetOrchestrationResult,
    DatasetSchema,
    DatasetScope,
    FeatureExecutionDiagnostics,
    FeatureExecutionError,
    FeatureExecutionResult,
    FeatureSampleResult,
    FeatureSpec,
    FeatureValueResult,
    ImplementationPin,
    LabelExecutionDiagnostics,
    LabelExecutionError,
    LabelExecutionResult,
    LabelHorizon,
    LabelObservationWindow,
    LabelSampleResult,
    LabelSpec,
    LabelValueResult,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    SplitValidationError,
    assemble_point_in_time_samples,
    dataset_id,
    dataset_orchestration_schema,
    dataset_schema_id,
    execute_builtin_features,
    execute_builtin_labels,
    feature_label_spec_pin,
    logical_dataset_content_id,
    orchestrate_dataset_build,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"

REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"
REF_MFE = "market_vault.dataset.label_transforms.maximum_favorable_excursion:maximum_favorable_excursion"

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


# ---------------------------------------------------------------------------
# Offline canonical-build fixtures (mirrors the Feature/Label execution
# tests; every fixture goes through the verified reader).
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
    frame = pd.DataFrame(
        {"time": [trade_date.isoformat()], "trade_date_type": ["WHOLE"]}
    )
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
    closes: list[float] | None = None,
    run_finished_at: datetime | None = None,
) -> None:
    count = len(time_keys)
    closes = closes or [100.5] * count
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = pd.DataFrame(
        {
            "code": [code] * count,
            "name": [code] * count,
            "time_key": time_keys,
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": closes,
            "volume": [100.0] * count,
        }
    )
    curated = normalize_bars(
        raw, requested_trade_date=trade_date, interval="1m",
        requested_session="ALL", adjustment="NONE", source=cfg.source,
        source_schema_version=cfg.source_schema_version, run_id=run_id,
    )
    store.write_curated(
        curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id
    )
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


def default_key() -> CanonicalRequestKey:
    return CanonicalRequestKey(
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )


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
    """One shared offline catalog with the micro builds:

    ``a``     US.MU 2026-07-01 09:30..09:35 NY (feature window + anchor),
              closes 100,110,112,118,120,110
    ``f``     US.MU 2026-07-01 09:36..09:41 NY (future label window),
              closes 100,110,120,130,140,150
    ``fmin``  US.MU 2026-07-01 09:36 NY only (single future bar)
    ``c``     US.MU 2026-06-30 09:30..09:35 NY (TRAIN-day feature window)
    ``d``     US.NVDA 2026-07-02 09:30..09:31 NY (TEST-day, second symbol)
    ``e``     US.MU 2026-07-03 09:30..09:31 NY (out-of-range day)
    """
    root = tmp_path_factory.mktemp("mv_orchestration")
    cfg = settings(root)
    for trade_date in (
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    ):
        calendar(cfg, trade_date=trade_date)

    def build(code, trade_date, run_id, time_keys, **kwargs):
        write_snapshot(
            cfg, code=code, trade_date=trade_date, run_id=run_id,
            time_keys=time_keys, **kwargs,
        )
        return verified(
            materialize(cfg, symbols=[code], trade_dates=[trade_date])
        )

    a = build(
        "US.MU", date(2026, 7, 1), "run-a",
        minute_keys("2026-07-01 09:30:00", 6),
        closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
    )
    f = build(
        "US.MU", date(2026, 7, 1), "run-f",
        minute_keys("2026-07-01 09:36:00", 6),
        closes=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
    )
    fmin = build(
        "US.MU", date(2026, 7, 1), "run-fmin",
        minute_keys("2026-07-01 09:36:00", 1),
        closes=[100.0],
    )
    c = build(
        "US.MU", date(2026, 6, 30), "run-c",
        minute_keys("2026-06-30 09:30:00", 6),
        closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
        run_finished_at=datetime(2026, 6, 30, 14, 0, tzinfo=UTC),
    )
    d = build(
        "US.NVDA", date(2026, 7, 2), "run-d",
        minute_keys("2026-07-02 09:30:00", 2),
        run_finished_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC),
    )
    e = build(
        "US.MU", date(2026, 7, 3), "run-e",
        minute_keys("2026-07-03 09:30:00", 2),
        run_finished_at=datetime(2026, 7, 3, 14, 0, tzinfo=UTC),
    )
    return SimpleNamespace(root=root, a=a, f=f, fmin=fmin, c=c, d=d, e=e)


# ---------------------------------------------------------------------------
# Spec / request / scope / split / input helpers.
# ---------------------------------------------------------------------------


def feature_spec(name: str = "sr", *, window_bars: int = 2) -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_SIMPLE,
        parameters=(SpecParameter("window_bars", window_bars),),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )


def label_spec(name: str = "fr", *, horizon: int = 2) -> LabelSpec:
    return LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_FORWARD,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow(
            "BARS", horizon - 1, horizon - 1
        ),
        horizon=LabelHorizon("BARS", horizon),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )


def mfe_spec(name: str = "mfe", *, horizon: int = 2) -> LabelSpec:
    return LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=("close", "high"),
        transform_ref=REF_MFE,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow("BARS", 0, horizon - 1),
        horizon=LabelHorizon("BARS", horizon),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )


def chronological_spec(
    *,
    name: str = "chrono",
    train_end: date = date(2026, 6, 30),
    validation_end: date = date(2026, 7, 1),
    test_end: date = date(2026, 7, 2),
) -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version="market-vault-chronological-split-spec-v1",
        name=name,
        version="v1",
        boundary_timezone=NY,
        train_end_date=train_end,
        validation_end_date=validation_end,
        test_end_date=test_end,
        assignment_rule="FEATURE_WINDOW_CLOSE_DATE",
        purge_rule="ACTUAL_LABEL_END",
        incomplete_label_policy="EXCLUDE",
        out_of_range_policy="EXCLUDE",
    )


def request(
    *,
    code: str = "US.MU",
    anchor: date = date(2026, 7, 1),
    f_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
    f_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    l_start=None,
    l_close=None,
) -> PITSampleRequest:
    if l_start is None:
        l_start = f_close
    if l_close is None:
        l_close = datetime(2026, 7, 1, 13, 42, tzinfo=UTC)
    return PITSampleRequest(
        code=code,
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
        anchor_market_calendar_date=anchor,
        feature_window_start=f_start,
        feature_window_close=f_close,
        label_window_start=l_start,
        label_window_close=l_close,
    )


def dataset_scope(
    *,
    symbols=("US.MU",),
    trade_dates=(date(2026, 7, 1),),
) -> DatasetScope:
    return DatasetScope(
        symbols=symbols,
        trade_dates=trade_dates,
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )


def inputs(
    fixtures,
    *,
    requests,
    builds=None,
    feature_specs=None,
    label_specs=None,
    split_spec=None,
    scope=None,
    dataset_as_of=None,
    **extra,
) -> dict:
    """Standard keyword-only entry arguments for one orchestration call.

    The authoritative schema is derived from the *final* spec and
    ``dataset_as_of`` values, so overrides stay consistent.
    """
    builds = builds if builds is not None else [fixtures.a, fixtures.f]
    feature_specs = (
        feature_specs if feature_specs is not None else [feature_spec()]
    )
    label_specs = label_specs if label_specs is not None else [label_spec()]
    split_spec = split_spec if split_spec is not None else chronological_spec()
    scope = scope if scope is not None else dataset_scope()
    schema = dataset_orchestration_schema(
        feature_specs, label_specs,
        include_dataset_as_of=dataset_as_of is not None,
    )
    kwargs = dict(
        builds=tuple(builds),
        requests=tuple(requests),
        feature_specs=tuple(feature_specs),
        label_specs=tuple(label_specs),
        split_spec=split_spec,
        scope=scope,
        schema=schema,
        dataset_as_of=dataset_as_of,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )
    kwargs.update(extra)
    return kwargs


def orchestrate(fixtures, *, requests, **overrides) -> DatasetOrchestrationResult:
    if "split" in overrides:
        overrides["split_spec"] = overrides.pop("split")
    if "scope_value" in overrides:
        overrides["scope"] = overrides.pop("scope_value")
    kwargs = inputs(fixtures, requests=requests, **overrides)
    return orchestrate_dataset_build(**kwargs)


# ---------------------------------------------------------------------------
# Hand-built result helpers for the stub / fail-closed tests.
# ---------------------------------------------------------------------------


def real_feature_pins(fixtures, spec: FeatureSpec) -> tuple[ImplementationPin, ...]:
    pit = assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()])
    return execute_builtin_features([fixtures.a, fixtures.f], pit, [spec]).implementation_pins


def real_label_pins(fixtures, spec: LabelSpec) -> tuple[ImplementationPin, ...]:
    pit = assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()])
    return execute_builtin_labels([fixtures.a, fixtures.f], pit, [spec]).implementation_pins


def stub_feature_result(
    samples, spec: FeatureSpec, impl_pins
) -> FeatureExecutionResult:
    complete = sum(
        1 for sample in samples if sample.status == FEATURE_VALUE_STATUS_COMPLETE
    )
    return FeatureExecutionResult(
        samples=tuple(samples),
        feature_spec_pins=(feature_label_spec_pin(spec),),
        implementation_pins=tuple(impl_pins),
        diagnostics=FeatureExecutionDiagnostics(
            sample_count=len(samples),
            feature_spec_count=1,
            complete_sample_count=complete,
            excluded_sample_count=len(samples) - complete,
            complete_value_count=complete,
            excluded_value_count=len(samples) - complete,
            transform_invocation_count=complete,
        ),
        execution_contract_version=FEATURE_EXECUTION_CONTRACT_VERSION,
    )


def stub_label_result(
    samples, spec: LabelSpec, impl_pins
) -> LabelExecutionResult:
    complete = sum(
        1 for sample in samples if sample.status == LABEL_STATUS_COMPLETE
    )
    return LabelExecutionResult(
        samples=tuple(samples),
        label_spec_pins=(feature_label_spec_pin(spec),),
        implementation_pins=tuple(impl_pins),
        diagnostics=LabelExecutionDiagnostics(
            sample_count=len(samples),
            label_spec_count=1,
            complete_sample_count=complete,
            incomplete_sample_count=len(samples) - complete,
            complete_value_count=complete,
            incomplete_value_count=len(samples) - complete,
            transform_invocation_count=complete,
        ),
        execution_contract_version=LABEL_EXECUTION_CONTRACT_VERSION,
    )


def hand_label_sample(
    pit_sample,
    spec: LabelSpec,
    impl_pin: ImplementationPin,
    *,
    status: str,
    actual_end=None,
    value=None,
    reason_code=None,
) -> LabelSampleResult:
    value_result = LabelValueResult(
        label_name=spec.name,
        spec_pin=feature_label_spec_pin(spec),
        implementation_pin=impl_pin,
        status=status,
        value=value,
        reason_code=reason_code,
        anchor_canonical_row_version_id=SHA_A,
        consumed_label_canonical_row_version_ids=(SHA_B,),
        actual_label_end_time=actual_end,
    )
    return LabelSampleResult(
        sample_key=pit_sample.sample_key,
        sample_version_id=pit_sample.sample_version_id,
        code=pit_sample.request.code,
        feature_window_close=pit_sample.request.feature_window_close,
        values=(value_result,),
        status=status,
        actual_label_end_time=actual_end,
    )


def hand_feature_sample(
    key: str,
    spec: FeatureSpec,
    impl_pin: ImplementationPin,
    *,
    sample_version_id: str = "v1",
    code: str = "US.MU",
    close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    value: float = 1.0,
    status: str = FEATURE_VALUE_STATUS_COMPLETE,
    reason_code: str | None = None,
) -> FeatureSampleResult:
    value_result = FeatureValueResult(
        feature_name=spec.name,
        spec_pin=feature_label_spec_pin(spec),
        implementation_pin=impl_pin,
        status=status,
        value=value,
        reason_code=reason_code,
        consumed_canonical_row_version_ids=(SHA_A,),
    )
    return FeatureSampleResult(
        sample_key=key,
        sample_version_id=sample_version_id,
        code=code,
        feature_window_close=close,
        values=(value_result,),
        status=status,
    )


# ---------------------------------------------------------------------------
# A. Public API and explicit input contract.
# ---------------------------------------------------------------------------


def test_public_api_exports():
    for name in (
        "DATASET_ORCHESTRATION_CONTRACT_VERSION",
        "DATASET_KIND_SUPERVISED",
        "DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY",
        "DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST",
        "DATASET_COMPLETION_REASON_FEATURE_EXCLUDED",
        "DATASET_COMPLETION_REASON_LABEL_INCOMPLETE",
        "DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE",
        "DatasetOrchestrationError",
        "DatasetOrchestrationDiagnostics",
        "DatasetOrchestrationResult",
        "dataset_orchestration_schema",
        "orchestrate_dataset_build",
        "DatasetScope",
        "DatasetSchema",
        "DatasetIdentityInput",
        "CompletionSummary",
        "PITAssemblyResult",
        "FeatureExecutionResult",
        "LabelExecutionResult",
        "ChronologicalSplitResult",
    ):
        assert hasattr(dataset_pkg, name), name


def test_contract_constants_exact():
    assert DATASET_ORCHESTRATION_CONTRACT_VERSION == (
        "market-vault-dataset-orchestration-v1"
    )
    assert DATASET_KIND_SUPERVISED == "SUPERVISED"
    assert DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY == (
        "CODE_FEATURE_CLOSE_SAMPLE_KEY"
    )
    assert DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST == "NO_SAMPLE_REQUEST"
    assert DATASET_COMPLETION_REASON_FEATURE_EXCLUDED == "FEATURE_EXCLUDED"
    assert DATASET_COMPLETION_REASON_LABEL_INCOMPLETE == "LABEL_INCOMPLETE"
    assert DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE == (
        "FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE"
    )


def test_entry_is_keyword_only(fixtures):
    with pytest.raises(TypeError):
        orchestrate_dataset_build([fixtures.a])
    with pytest.raises(TypeError):
        orchestrate_dataset_build([fixtures.a], [request()])


def test_builds_must_be_non_empty(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], builds=[])


def test_builds_must_be_verified_canonical_build(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], builds=[object()])


def test_requests_type_validated(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[object()])


def test_feature_specs_must_be_non_empty(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], feature_specs=[])


def test_feature_specs_must_be_feature_only(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures, requests=[request()], feature_specs=[label_spec()]
        )


def test_label_specs_must_be_non_empty(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], label_specs=[])


def test_label_specs_must_be_label_only(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures, requests=[request()], label_specs=[feature_spec()]
        )


def test_split_spec_type_validated(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], split=object())


def test_scope_type_validated(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], scope_value=object())


def test_schema_type_validated(fixtures):
    kwargs = inputs(fixtures, requests=[request()])
    kwargs["schema"] = object()
    with pytest.raises(DatasetOrchestrationError):
        orchestrate_dataset_build(**kwargs)


def test_dataset_kind_rejected(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], dataset_kind="UNSUPERVISED")


def test_manifest_schema_version_rejected(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            manifest_schema_version="other-version",
        )


def test_serialization_format_rejected(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures, requests=[request()], serialization_format="csv"
        )


def test_serialization_version_rejected(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            serialization_format_version="other-version",
        )


def test_empty_requests_are_allowed(fixtures):
    result = orchestrate(fixtures, requests=[])
    assert result.status == STATUS_EMPTY


# ---------------------------------------------------------------------------
# B. Scope / request consistency.
# ---------------------------------------------------------------------------


def test_request_code_must_be_in_scope(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request(code="US.OTHER")],
            scope_value=dataset_scope(),
        )


def test_request_trade_date_must_be_in_scope(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request(anchor=date(2026, 7, 2))],
            scope_value=dataset_scope(),
        )


def test_request_interval_must_equal_scope(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            scope_value=DatasetScope(
                symbols=("US.MU",),
                trade_dates=(date(2026, 7, 1),),
                interval="5m",
                adjustment="NONE",
                requested_session="ALL",
            ),
        )


def test_request_adjustment_must_equal_scope(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            scope_value=DatasetScope(
                symbols=("US.MU",),
                trade_dates=(date(2026, 7, 1),),
                interval="1m",
                adjustment="SPLIT",
                requested_session="ALL",
            ),
        )


def test_request_session_must_equal_scope(fixtures):
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            scope_value=DatasetScope(
                symbols=("US.MU",),
                trade_dates=(date(2026, 7, 1),),
                interval="1m",
                adjustment="NONE",
                requested_session="REG",
            ),
        )


def test_scope_keys_without_request_are_missing(fixtures):
    result = orchestrate(
        fixtures,
        requests=[request()],
        scope_value=dataset_scope(trade_dates=(date(2026, 7, 1), date(2026, 7, 2))),
    )
    by_key = {
        (entry.code, entry.trade_date): entry
        for entry in result.completion.entries
    }
    assert by_key[("US.MU", date(2026, 7, 1))].status == "COMPLETE"
    assert by_key[("US.MU", date(2026, 7, 2))].status == "MISSING"
    assert (
        by_key[("US.MU", date(2026, 7, 2))].reason_code
        == DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST
    )


def test_scope_input_order_irrelevant(fixtures):
    first = orchestrate(
        fixtures,
        requests=[request()],
        scope_value=dataset_scope(trade_dates=(date(2026, 7, 1), date(2026, 7, 2))),
    )
    second = orchestrate(
        fixtures,
        requests=[request()],
        scope_value=dataset_scope(trade_dates=(date(2026, 7, 2), date(2026, 7, 1))),
    )
    assert first == second
    assert first.dataset_id == second.dataset_id


# ---------------------------------------------------------------------------
# C. Authoritative schema.
# ---------------------------------------------------------------------------


def schema_names(schema: DatasetSchema) -> list[str]:
    return [field.name for field in schema.fields]


def test_schema_fixed_core_field_order():
    schema = dataset_orchestration_schema(
        [feature_spec("sr")], [label_spec("fr")], include_dataset_as_of=False
    )
    assert schema_names(schema) == [
        "code",
        "sample_key",
        "sample_version_id",
        "feature_window_close",
        "actual_label_end_time",
        "label_status",
        "sr",
        "fr",
        "feature_window_close_date",
        "nominal_split",
        "final_split",
        "assignment_status",
        "reason_code",
        "purge_boundary",
    ]


def test_schema_has_no_as_of_field_when_disabled():
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=False
    )
    assert "dataset_as_of" not in schema_names(schema)


def test_schema_as_of_field_when_enabled():
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=True
    )
    by_name = {field.name: field for field in schema.fields}
    assert by_name["dataset_as_of"].logical_type == "timestamp_us_utc"
    assert by_name["dataset_as_of"].nullable is False


def test_schema_feature_fields_sorted_by_spec_pin():
    schema = dataset_orchestration_schema(
        [feature_spec("zb"), feature_spec("aa")],
        [label_spec()],
        include_dataset_as_of=False,
    )
    names = schema_names(schema)
    assert names.index("aa") < names.index("zb")


def test_schema_label_fields_sorted_by_spec_pin():
    schema = dataset_orchestration_schema(
        [feature_spec()],
        [label_spec("zb"), label_spec("aa")],
        include_dataset_as_of=False,
    )
    names = schema_names(schema)
    assert names.index("aa") < names.index("zb")


def test_schema_feature_fields_non_nullable():
    schema = dataset_orchestration_schema(
        [feature_spec("sr")], [label_spec()], include_dataset_as_of=False
    )
    field = next(f for f in schema.fields if f.name == "sr")
    assert field.nullable is False


def test_schema_label_fields_nullable():
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec("fr")], include_dataset_as_of=False
    )
    field = next(f for f in schema.fields if f.name == "fr")
    assert field.nullable is True


def test_schema_split_fields_exact_order():
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=False
    )
    assert schema_names(schema)[-6:] == [
        "feature_window_close_date",
        "nominal_split",
        "final_split",
        "assignment_status",
        "reason_code",
        "purge_boundary",
    ]


def test_schema_requires_real_bool_flag():
    with pytest.raises(DatasetOrchestrationError):
        dataset_orchestration_schema(
            [feature_spec()], [label_spec()], include_dataset_as_of=1
        )


def test_schema_rejects_feature_label_same_name():
    with pytest.raises(DatasetOrchestrationError):
        dataset_orchestration_schema(
            [feature_spec("dup")], [label_spec("dup")],
            include_dataset_as_of=False,
        )


def test_schema_rejects_reserved_collision():
    with pytest.raises(DatasetOrchestrationError):
        dataset_orchestration_schema(
            [feature_spec("code")], [label_spec()], include_dataset_as_of=False
        )
    with pytest.raises(DatasetOrchestrationError):
        dataset_orchestration_schema(
            [feature_spec()], [label_spec("label_status")],
            include_dataset_as_of=False,
        )
    with pytest.raises(DatasetOrchestrationError):
        dataset_orchestration_schema(
            [feature_spec("purge_boundary")], [label_spec()],
            include_dataset_as_of=False,
        )


def test_schema_rejects_duplicate_spec_names():
    with pytest.raises(DatasetOrchestrationError):
        dataset_orchestration_schema(
            [feature_spec("sr"), feature_spec("sr")], [label_spec()],
            include_dataset_as_of=False,
        )


def test_provided_schema_must_match_exact(fixtures):
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=False
    )
    reordered = DatasetSchema(
        tuple(
            (schema.fields[6], schema.fields[7])
            + schema.fields[:6]
            + schema.fields[8:]
        )
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures, requests=[request()], schema=reordered
        )


def test_provided_schema_type_change_rejected(fixtures):
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=False
    )
    fields = list(schema.fields)
    fields[6] = DatasetField("sr", "int64", nullable=False)
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            schema=DatasetSchema(tuple(fields)),
        )


def test_provided_schema_nullability_change_rejected(fixtures):
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=False
    )
    fields = list(schema.fields)
    fields[7] = DatasetField("fr", "float64", nullable=False)
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            schema=DatasetSchema(tuple(fields)),
        )


def test_provided_schema_extra_field_rejected(fixtures):
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=False
    )
    extra = DatasetSchema(tuple(schema.fields) + (DatasetField("extra", "string", False),))
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], schema=extra)


def test_provided_schema_missing_field_rejected(fixtures):
    schema = dataset_orchestration_schema(
        [feature_spec()], [label_spec()], include_dataset_as_of=False
    )
    missing = DatasetSchema(tuple(schema.fields[:-1]))
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], schema=missing)


# ---------------------------------------------------------------------------
# D. Pipeline invocation order (exactly once, same PIT result).
# ---------------------------------------------------------------------------


def test_pipeline_invocations_exactly_once(fixtures, monkeypatch):
    calls = {"pit": 0, "feature": 0, "label": 0, "split": 0}
    real_pit = orch_mod.assemble_point_in_time_samples
    real_feature = orch_mod.execute_builtin_features
    real_label = orch_mod.execute_builtin_labels
    real_split = orch_mod.assign_chronological_splits
    captured = {}

    def pit_spy(*args, **kwargs):
        calls["pit"] += 1
        result = real_pit(*args, **kwargs)
        captured["pit"] = result
        return result

    def feature_spy(*args, **kwargs):
        calls["feature"] += 1
        assert args[1] is captured["pit"]
        return real_feature(*args, **kwargs)

    def label_spy(*args, **kwargs):
        calls["label"] += 1
        assert args[1] is captured["pit"]
        return real_label(*args, **kwargs)

    def split_spy(*args, **kwargs):
        calls["split"] += 1
        return real_split(*args, **kwargs)

    monkeypatch.setattr(orch_mod, "assemble_point_in_time_samples", pit_spy)
    monkeypatch.setattr(orch_mod, "execute_builtin_features", feature_spy)
    monkeypatch.setattr(orch_mod, "execute_builtin_labels", label_spy)
    monkeypatch.setattr(orch_mod, "assign_chronological_splits", split_spy)

    result = orchestrate(fixtures, requests=[request()])
    assert calls == {"pit": 1, "feature": 1, "label": 1, "split": 1}
    assert result.status == STATUS_COMPLETE


def test_no_manifest_writer_or_filesystem(fixtures, monkeypatch):
    """The entry never calls a manifest builder or a writer; the fixture
    directory gains no files and no Dataset directory appears."""
    root = fixtures.root
    before = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    }
    orchestrate(fixtures, requests=[request()])
    after = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert not (root / "data" / "datasets").exists()
    assert not any("dataset.parquet" in name for name in after)


# ---------------------------------------------------------------------------
# E. Cross-layer sample binding.
# ---------------------------------------------------------------------------


def test_binding_normal_happy_path(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    assert result.status == STATUS_COMPLETE
    assert len(result.pit_result.samples) == 1


def test_missing_feature_sample_rejected(fixtures, monkeypatch):
    spec = feature_spec()
    pins = real_feature_pins(fixtures, spec)
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_features",
        lambda *a, **k: stub_feature_result([], spec, pins),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_extra_feature_sample_rejected(fixtures, monkeypatch):
    spec = feature_spec()
    pins = real_feature_pins(fixtures, spec)
    extra = hand_feature_sample(SHA_C, spec, pins[0], code="US.MU")
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_features",
        lambda *a, **k: stub_feature_result([extra], spec, pins),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_missing_label_sample_rejected(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_labels",
        lambda *a, **k: stub_label_result([], spec, pins),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_extra_label_sample_rejected(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    extra = hand_label_sample(
        SimpleNamespace(
            sample_key=SHA_C,
            sample_version_id="v1",
            request=PITSampleRequest(
                code="US.MU",
                interval="1m",
                adjustment="NONE",
                requested_session="ALL",
                anchor_market_calendar_date=date(2026, 7, 1),
                feature_window_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
                feature_window_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            ),
        ),
        spec,
        pins[0],
        status=LABEL_STATUS_COMPLETE,
        actual_end=datetime(2026, 7, 1, 13, 38, tzinfo=UTC),
        value=1.0,
    )
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_labels",
        lambda *a, **k: stub_label_result([extra], spec, pins),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_sample_version_id_mismatch_rejected(fixtures, monkeypatch):
    spec = feature_spec()
    pins = real_feature_pins(fixtures, spec)
    real = execute_builtin_features(
        [fixtures.a, fixtures.f],
        assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()]),
        [spec],
    )
    tampered = replace(real.samples[0], sample_version_id="other")
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_features",
        lambda *a, **k: stub_feature_result([tampered], spec, pins),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_code_mismatch_rejected(fixtures, monkeypatch):
    spec = feature_spec()
    pins = real_feature_pins(fixtures, spec)
    real = execute_builtin_features(
        [fixtures.a, fixtures.f],
        assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()]),
        [spec],
    )
    tampered = replace(real.samples[0], code="US.OTHER")
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_features",
        lambda *a, **k: stub_feature_result([tampered], spec, pins),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_feature_window_close_mismatch_rejected(fixtures, monkeypatch):
    spec = feature_spec()
    pins = real_feature_pins(fixtures, spec)
    real = execute_builtin_features(
        [fixtures.a, fixtures.f],
        assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()]),
        [spec],
    )
    tampered = replace(
        real.samples[0],
        feature_window_close=datetime(2026, 7, 1, 13, 40, tzinfo=UTC),
    )
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_features",
        lambda *a, **k: stub_feature_result([tampered], spec, pins),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_dataset_as_of_mismatch_rejected(fixtures, monkeypatch):
    real_pit = orch_mod.assemble_point_in_time_samples

    def pit_without_cutoff(*args, **kwargs):
        kwargs["dataset_as_of"] = None
        return real_pit(*args, **kwargs)

    monkeypatch.setattr(
        orch_mod, "assemble_point_in_time_samples", pit_without_cutoff
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            dataset_as_of=datetime(2026, 8, 1, tzinfo=UTC),
        )


# ---------------------------------------------------------------------------
# F. Feature EXCLUDED handling.
# ---------------------------------------------------------------------------


def excluded_request() -> PITSampleRequest:
    """Feature window [13:30, 13:31): one row < window_bars=2 -> EXCLUDED."""
    return request(
        f_close=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
        l_start=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
        l_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
    )


def test_feature_excluded_not_in_split_or_rows(fixtures):
    result = orchestrate(
        fixtures,
        requests=[request(), excluded_request()],
    )
    complete_keys = {
        sample.sample_key
        for sample in result.feature_result.samples
        if sample.status == FEATURE_VALUE_STATUS_COMPLETE
    }
    assert len(result.feature_result.samples) == 2
    assert len(complete_keys) == 1
    assert {a.sample_key for a in result.split_result.assignments} == complete_keys
    assert len(result.rows) == 1
    assert result.diagnostics.feature_complete_sample_count == 1
    assert result.diagnostics.feature_excluded_sample_count == 1
    assert result.diagnostics.split_sample_count == 1
    assert result.diagnostics.logical_row_count == 1


def test_feature_excluded_enters_completion_incomplete(fixtures):
    result = orchestrate(
        fixtures,
        requests=[request(), excluded_request()],
    )
    entry = result.completion.entries[0]
    assert entry.status == "INCOMPLETE"
    assert entry.reason_code == DATASET_COMPLETION_REASON_FEATURE_EXCLUDED


def test_all_feature_excluded_empty_rows(fixtures):
    result = orchestrate(fixtures, requests=[excluded_request()])
    assert result.status == STATUS_EMPTY
    assert result.rows == ()
    assert result.diagnostics.split_sample_count == 0
    assert result.diagnostics.logical_row_count == 0
    entry = result.completion.entries[0]
    assert entry.status == "INCOMPLETE"
    assert entry.reason_code == DATASET_COMPLETION_REASON_FEATURE_EXCLUDED
    # Pins stay non-empty even with an empty row set.
    assert result.identity_input.feature_specs
    assert result.identity_input.label_specs
    assert result.identity_input.implementations


# ---------------------------------------------------------------------------
# G. Label facts and split handoff.
# ---------------------------------------------------------------------------


def test_label_complete_constructs_complete_split_sample(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    assignment = result.split_result.assignments[0]
    assert assignment.label_status == LABEL_STATUS_COMPLETE
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_VALIDATION


def test_label_incomplete_constructs_incomplete_split_sample(fixtures):
    result = orchestrate(
        fixtures,
        requests=[request()],
        builds=[fixtures.a, fixtures.fmin],
    )
    sample = result.label_result.samples[0]
    assert sample.status == LABEL_STATUS_INCOMPLETE
    assignment = result.split_result.assignments[0]
    assert assignment.label_status == LABEL_STATUS_INCOMPLETE
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL


def test_actual_label_end_time_passthrough(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    label_sample = result.label_result.samples[0]
    row = result.rows[0]
    row_map = dict(zip(schema_names(result.schema), row))
    assert row_map["actual_label_end_time"] == label_sample.actual_label_end_time
    # The actual end is the last consumed label row's availability, never
    # the nominal label window close.
    assert label_sample.actual_label_end_time != datetime(
        2026, 7, 1, 13, 42, tzinfo=UTC
    )
    assert label_sample.actual_label_end_time is not None
    assert row_map["label_status"] == LABEL_STATUS_COMPLETE


def test_label_incomplete_row_retained_with_null_values(fixtures):
    result = orchestrate(
        fixtures,
        requests=[request()],
        builds=[fixtures.a, fixtures.fmin],
    )
    row = result.rows[0]
    row_map = dict(zip(schema_names(result.schema), row))
    assert row_map["label_status"] == LABEL_STATUS_INCOMPLETE
    assert row_map["fr"] is None
    assert row_map["assignment_status"] == SPLIT_STATUS_EXCLUDED
    assert row_map["reason_code"] == REASON_CODE_INCOMPLETE_LABEL
    assert row_map["actual_label_end_time"] is None


def test_train_crossing_actual_end_purged(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.c],
        [request(anchor=date(2026, 6, 30), f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC), f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC))],
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                spec,
                pins[0],
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 1, 5, 0, tzinfo=UTC),
                value=1.0,
            )
        ],
        spec,
        pins,
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    result = orchestrate(
        fixtures,
        requests=[request(anchor=date(2026, 6, 30), f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC), f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC))],
        builds=[fixtures.c],
        scope_value=dataset_scope(trade_dates=(date(2026, 6, 30),)),
    )
    assignment = result.split_result.assignments[0]
    assert assignment.nominal_split == SPLIT_TRAIN
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert (
        assignment.reason_code
        == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
    )
    assert assignment.purge_boundary == datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    # The purged row is retained for audit.
    row_map = dict(zip(schema_names(result.schema), result.rows[0]))
    assert row_map["assignment_status"] == SPLIT_STATUS_PURGED
    assert row_map["actual_label_end_time"] == datetime(
        2026, 7, 1, 5, 0, tzinfo=UTC
    )


def test_validation_crossing_actual_end_purged(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.a, fixtures.f], [request()]
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                spec,
                pins[0],
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 2, 5, 0, tzinfo=UTC),
                value=1.0,
            )
        ],
        spec,
        pins,
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    result = orchestrate(fixtures, requests=[request()])
    assignment = result.split_result.assignments[0]
    assert assignment.nominal_split == SPLIT_VALIDATION
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert (
        assignment.reason_code
        == REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
    )
    assert assignment.purge_boundary == datetime(2026, 7, 2, 4, 0, tzinfo=UTC)


def test_test_has_no_fourth_split_purge(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.d],
        [
            request(
                code="US.NVDA",
                anchor=date(2026, 7, 2),
                f_close=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
                l_start=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
                l_close=datetime(2026, 7, 2, 13, 42, tzinfo=UTC),
            )
        ],
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                spec,
                pins[0],
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 3, 5, 0, tzinfo=UTC),
                value=1.0,
            )
        ],
        spec,
        pins,
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    result = orchestrate(
        fixtures,
        requests=[
            request(
                code="US.NVDA",
                anchor=date(2026, 7, 2),
                f_close=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
                l_start=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
                l_close=datetime(2026, 7, 2, 13, 42, tzinfo=UTC),
            )
        ],
        builds=[fixtures.d],
        scope_value=dataset_scope(
            symbols=("US.NVDA",), trade_dates=(date(2026, 7, 2),)
        ),
    )
    assignment = result.split_result.assignments[0]
    assert assignment.nominal_split == SPLIT_TEST
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TEST
    assert assignment.reason_code is None


def test_out_of_range_excluded_by_existing_split_contract(fixtures):
    # Close date 2026-07-03 > test_end 2026-07-02 -> EXCLUDED by the
    # existing splitter even though the label is INCOMPLETE.
    result = orchestrate(
        fixtures,
        requests=[
            request(
                anchor=date(2026, 7, 3),
                f_close=datetime(2026, 7, 3, 13, 32, tzinfo=UTC),
                l_start=datetime(2026, 7, 3, 13, 32, tzinfo=UTC),
                l_close=datetime(2026, 7, 3, 13, 42, tzinfo=UTC),
            )
        ],
        builds=[fixtures.e],
        scope_value=dataset_scope(trade_dates=(date(2026, 7, 3),)),
    )
    assert result.label_result.samples[0].status == LABEL_STATUS_INCOMPLETE
    assignment = result.split_result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END
    row_map = dict(zip(schema_names(result.schema), result.rows[0]))
    assert row_map["assignment_status"] == SPLIT_STATUS_EXCLUDED
    assert row_map["reason_code"] == REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END
    assert row_map["fr"] is None


# ---------------------------------------------------------------------------
# H. Final logical rows.
# ---------------------------------------------------------------------------


def test_row_core_and_output_values(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    assert len(result.rows) == 1
    row = result.rows[0]
    assert isinstance(row, tuple)
    row_map = dict(zip(schema_names(result.schema), row))
    pit_sample = result.pit_result.samples[0]
    feature_value = result.feature_result.samples[0].values[0].value
    label_value = result.label_result.samples[0].values[0].value
    assignment = result.split_result.assignments[0]
    assert row_map["code"] == "US.MU"
    assert row_map["sample_key"] == pit_sample.sample_key
    assert row_map["sample_version_id"] == pit_sample.sample_version_id
    assert row_map["feature_window_close"] == datetime(
        2026, 7, 1, 13, 36, tzinfo=UTC
    )
    assert row_map["label_status"] == LABEL_STATUS_COMPLETE
    assert row_map["sr"] == feature_value
    assert row_map["fr"] == label_value
    assert row_map["feature_window_close_date"] == date(2026, 7, 1)
    assert row_map["nominal_split"] == SPLIT_VALIDATION
    assert row_map["final_split"] == SPLIT_VALIDATION
    assert row_map["assignment_status"] == SPLIT_STATUS_ASSIGNED
    assert row_map["reason_code"] is None
    assert row_map["purge_boundary"] is None


def test_mixed_complete_incomplete_labels(fixtures):
    # fr H=1 completes (target 13:36 exists); mfe H=2 stays INCOMPLETE
    # (only the 13:36 bar exists in fmin). The row keeps the COMPLETE
    # value and uses a true null for the INCOMPLETE label.
    labels = [label_spec("fr", horizon=1), mfe_spec("mfe", horizon=2)]
    result = orchestrate(
        fixtures,
        requests=[request()],
        builds=[fixtures.a, fixtures.fmin],
        label_specs=labels,
    )
    sample = result.label_result.samples[0]
    assert sample.status == LABEL_STATUS_INCOMPLETE
    row_map = dict(zip(schema_names(result.schema), result.rows[0]))
    # H=1: target is the 13:36 bar (close 100) over the anchor 13:35 (110).
    assert row_map["fr"] == pytest.approx(100.0 / 110.0 - 1.0)
    assert row_map["mfe"] is None
    assert row_map["label_status"] == LABEL_STATUS_INCOMPLETE


def test_rows_tuple_only_and_exact_length(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    for row in result.rows:
        assert isinstance(row, tuple)
        assert len(row) == len(result.schema.fields)
    mappings = result.logical_row_mappings()
    assert len(mappings) == len(result.rows)
    for mapping in mappings:
        assert isinstance(mapping, dict)
        assert len(mapping) == len(result.schema.fields)


def test_fixed_physical_row_sort(fixtures):
    requests_list = [
        request(
            f_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            l_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        ),
        request(
            f_close=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
            l_start=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
        ),
    ]
    result = orchestrate(fixtures, requests=requests_list)
    assert len(result.rows) == 2
    closes = [
        dict(zip(schema_names(result.schema), row))["feature_window_close"]
        for row in result.rows
    ]
    assert closes == sorted(closes)
    keys = [
        dict(zip(schema_names(result.schema), row))["sample_key"]
        for row in result.rows
    ]
    assert len(keys) == len(set(keys))


def test_request_reversal_same_result(fixtures):
    requests_list = [
        request(
            f_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            l_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        ),
        request(
            f_close=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
            l_start=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
        ),
    ]
    first = orchestrate(fixtures, requests=requests_list)
    second = orchestrate(fixtures, requests=list(reversed(requests_list)))
    assert first == second
    assert first.dataset_id == second.dataset_id


def test_spec_reversal_same_result(fixtures):
    specs = [feature_spec("sr"), feature_spec("sr2", window_bars=3)]
    labels = [label_spec("fr"), label_spec("fr2", horizon=3)]
    first = orchestrate(
        fixtures, requests=[request()], feature_specs=specs, label_specs=labels
    )
    second = orchestrate(
        fixtures,
        requests=[request()],
        feature_specs=list(reversed(specs)),
        label_specs=list(reversed(labels)),
    )
    assert first == second
    assert first.dataset_id == second.dataset_id


def test_build_reversal_same_result(fixtures):
    first = orchestrate(fixtures, requests=[request()], builds=[fixtures.a, fixtures.f])
    second = orchestrate(fixtures, requests=[request()], builds=[fixtures.f, fixtures.a])
    assert first == second
    assert first.dataset_id == second.dataset_id


def test_nan_never_enters_rows(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    row = list(result.rows[0])
    row[6] = float("nan")  # sr column
    with pytest.raises(DatasetOrchestrationError):
        DatasetOrchestrationResult(**replace_args_with_rows(result, (tuple(row),)))


def test_wrong_value_type_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    row = list(result.rows[0])
    row[0] = 123  # code must be string
    with pytest.raises(DatasetOrchestrationError):
        DatasetOrchestrationResult(**replace_args_with_rows(result, (tuple(row),)))


def test_duplicate_sample_key_rows_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        DatasetOrchestrationResult(
            **replace_args_with_rows(result, result.rows + result.rows)
        )


def replace_args_with_rows(result: DatasetOrchestrationResult, rows):
    """dataclasses.replace arguments for a result with tampered rows."""
    return dict(
        status=result.status,
        dataset_kind=result.dataset_kind,
        scope=result.scope,
        dataset_as_of=result.dataset_as_of,
        feature_specs=result.feature_specs,
        label_specs=result.label_specs,
        split_spec=result.split_spec,
        pit_result=result.pit_result,
        feature_result=result.feature_result,
        label_result=result.label_result,
        split_result=result.split_result,
        schema=result.schema,
        rows=rows,
        dataset_schema_id=result.dataset_schema_id,
        logical_dataset_content_id=result.logical_dataset_content_id,
        identity_input=result.identity_input,
        dataset_id=result.dataset_id,
        completion=result.completion,
        diagnostics=result.diagnostics,
        manifest_schema_version=result.manifest_schema_version,
        serialization_format=result.serialization_format,
        serialization_format_version=result.serialization_format_version,
        row_order=result.row_order,
        orchestration_contract_version=result.orchestration_contract_version,
    )


# ---------------------------------------------------------------------------
# I. CompletionSummary semantics.
# ---------------------------------------------------------------------------


def test_completion_all_complete(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    assert result.completion.complete_count == 1
    assert result.completion.incomplete_count == 0
    assert result.completion.missing_count == 0
    entry = result.completion.entries[0]
    assert entry.code == "US.MU"
    assert entry.trade_date == date(2026, 7, 1)
    assert entry.status == "COMPLETE"
    assert entry.reason_code is None


def test_completion_label_incomplete(fixtures):
    result = orchestrate(
        fixtures,
        requests=[request()],
        builds=[fixtures.a, fixtures.fmin],
    )
    entry = result.completion.entries[0]
    assert entry.status == "INCOMPLETE"
    assert entry.reason_code == DATASET_COMPLETION_REASON_LABEL_INCOMPLETE


def test_completion_feature_and_label_both_incomplete(fixtures):
    spec = feature_spec(window_bars=5)
    labels = [label_spec(horizon=6)]
    req = request(
        f_close=datetime(2026, 7, 1, 13, 33, tzinfo=UTC),
        l_start=datetime(2026, 7, 1, 13, 33, tzinfo=UTC),
        l_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
    )
    result = orchestrate(
        fixtures,
        requests=[req],
        builds=[fixtures.a, fixtures.fmin],
        feature_specs=[spec],
        label_specs=labels,
    )
    entry = result.completion.entries[0]
    assert entry.status == "INCOMPLETE"
    assert (
        entry.reason_code
        == DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE
    )


def test_completion_no_request_missing(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    entry = result.completion.entries[0]
    assert entry.status == "COMPLETE"
    # A second scope key without a request is MISSING with the fixed code.
    extended = orchestrate(
        fixtures,
        requests=[request()],
        scope_value=dataset_scope(trade_dates=(date(2026, 7, 1), date(2026, 7, 2))),
    )
    by_key = {
        (entry.code, entry.trade_date): entry
        for entry in extended.completion.entries
    }
    missing = by_key[("US.MU", date(2026, 7, 2))]
    assert missing.status == "MISSING"
    assert missing.reason_code == DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST


def test_completion_any_sample_incomplete_makes_key_incomplete(fixtures):
    result = orchestrate(
        fixtures,
        requests=[request(), excluded_request()],
    )
    entry = result.completion.entries[0]
    assert entry.status == "INCOMPLETE"
    assert entry.reason_code == DATASET_COMPLETION_REASON_FEATURE_EXCLUDED


def test_split_purge_does_not_change_completion(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.c],
        [request(anchor=date(2026, 6, 30), f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC), f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC))],
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                spec,
                pins[0],
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 1, 5, 0, tzinfo=UTC),
                value=1.0,
            )
        ],
        spec,
        pins,
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    result = orchestrate(
        fixtures,
        requests=[request(anchor=date(2026, 6, 30), f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC), f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC), l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC))],
        builds=[fixtures.c],
        scope_value=dataset_scope(trade_dates=(date(2026, 6, 30),)),
    )
    assert result.split_result.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert result.completion.entries[0].status == "COMPLETE"


def test_split_out_of_range_does_not_change_completion(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.e],
        [
            request(
                anchor=date(2026, 7, 3),
                f_close=datetime(2026, 7, 3, 13, 32, tzinfo=UTC),
                l_start=datetime(2026, 7, 3, 13, 32, tzinfo=UTC),
                l_close=datetime(2026, 7, 3, 13, 42, tzinfo=UTC),
            )
        ],
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                spec,
                pins[0],
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 3, 13, 38, tzinfo=UTC),
                value=1.0,
            )
        ],
        spec,
        pins,
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    result = orchestrate(
        fixtures,
        requests=[
            request(
                anchor=date(2026, 7, 3),
                f_close=datetime(2026, 7, 3, 13, 32, tzinfo=UTC),
                l_start=datetime(2026, 7, 3, 13, 32, tzinfo=UTC),
                l_close=datetime(2026, 7, 3, 13, 42, tzinfo=UTC),
            )
        ],
        builds=[fixtures.e],
        scope_value=dataset_scope(trade_dates=(date(2026, 7, 3),)),
    )
    assert (
        result.split_result.assignments[0].assignment_status
        == SPLIT_STATUS_EXCLUDED
    )
    assert result.completion.entries[0].status == "COMPLETE"


def test_completion_covers_full_cartesian(fixtures):
    requests_list = [
        request(),  # US.MU 2026-07-01 complete
        request(
            code="US.NVDA",
            anchor=date(2026, 7, 2),
            f_close=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
            l_start=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
            l_close=datetime(2026, 7, 2, 13, 42, tzinfo=UTC),
        ),  # US.NVDA 2026-07-02 label incomplete
    ]
    result = orchestrate(
        fixtures,
        requests=requests_list,
        builds=[fixtures.a, fixtures.f, fixtures.d],
        scope_value=dataset_scope(
            symbols=("US.MU", "US.NVDA"),
            trade_dates=(date(2026, 7, 1), date(2026, 7, 2)),
        ),
    )
    by_key = {
        (entry.code, entry.trade_date): entry
        for entry in result.completion.entries
    }
    assert len(by_key) == 4
    assert by_key[("US.MU", date(2026, 7, 1))].status == "COMPLETE"
    assert by_key[("US.MU", date(2026, 7, 2))].status == "MISSING"
    assert by_key[("US.NVDA", date(2026, 7, 1))].status == "MISSING"
    assert by_key[("US.NVDA", date(2026, 7, 2))].status == "INCOMPLETE"
    assert (
        by_key[("US.NVDA", date(2026, 7, 2))].reason_code
        == DATASET_COMPLETION_REASON_LABEL_INCOMPLETE
    )
    assert (
        result.completion.complete_count,
        result.completion.incomplete_count,
        result.completion.missing_count,
    ) == (1, 1, 2)
    assert (
        result.diagnostics.completion_complete_key_count,
        result.diagnostics.completion_incomplete_key_count,
        result.diagnostics.completion_missing_key_count,
    ) == (1, 1, 2)


def test_completion_reason_codes_are_fixed():
    assert DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST == "NO_SAMPLE_REQUEST"
    assert DATASET_COMPLETION_REASON_FEATURE_EXCLUDED == "FEATURE_EXCLUDED"
    assert DATASET_COMPLETION_REASON_LABEL_INCOMPLETE == "LABEL_INCOMPLETE"
    assert (
        DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE
        == "FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE"
    )


# ---------------------------------------------------------------------------
# J. Identity core.
# ---------------------------------------------------------------------------


def test_schema_and_content_ids_recomputed(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    assert result.dataset_schema_id == dataset_schema_id(result.schema)
    assert result.logical_dataset_content_id == logical_dataset_content_id(
        result.schema, result.logical_row_mappings()
    )
    assert result.dataset_id == dataset_id(result.identity_input)


def test_identity_input_fields_exact(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    identity = result.identity_input
    assert identity.dataset_kind == DATASET_KIND_SUPERVISED
    assert identity.scope == result.scope
    assert identity.dataset_as_of is None
    assert identity.schema == result.schema
    assert identity.dataset_schema_id == result.dataset_schema_id
    assert identity.logical_dataset_content_id == result.logical_dataset_content_id
    assert identity.canonical_builds == result.pit_result.canonical_build_pins
    assert (
        identity.canonical_row_version_ids
        == result.pit_result.canonical_row_version_ids
    )
    assert identity.feature_specs == result.feature_result.feature_spec_pins
    assert identity.label_specs == result.label_result.label_spec_pins
    assert identity.split_spec == result.split_result.split_spec_pin
    assert identity.implementations == result.identity_input.implementations
    assert identity.completion == result.completion
    assert identity.gap_references == result.pit_result.gap_references
    assert identity.manifest_schema_version == DATASET_MANIFEST_SCHEMA_VERSION
    assert identity.serialization_format == SERIALIZATION_FORMAT_PARQUET
    assert (
        identity.serialization_format_version
        == SERIALIZATION_FORMAT_VERSION_PARQUET
    )


def test_canonical_pins_and_gap_references_from_pit(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    identity = result.identity_input
    assert set(identity.canonical_builds) == set(
        result.pit_result.canonical_build_pins
    )
    assert set(identity.canonical_row_version_ids) == set(
        result.pit_result.canonical_row_version_ids
    )
    assert identity.gap_references == result.pit_result.gap_references


def test_implementation_pins_merged(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    expected = tuple(
        sorted(
            set(result.feature_result.implementation_pins)
            | set(result.label_result.implementation_pins),
            key=lambda pin: (pin.name, pin.version, pin.content_sha256),
        )
    )
    assert result.identity_input.implementations == expected
    # Only actually resolved pins; no orchestration pseudo-pin exists.
    real_names = {
        pin.name
        for pin in (
            *result.feature_result.implementation_pins,
            *result.label_result.implementation_pins,
        )
    }
    assert {pin.name for pin in result.identity_input.implementations} == real_names


def test_identical_shared_implementation_pin_deduped(fixtures, monkeypatch):
    # A Label result that shares the Feature implementation pin exactly is
    # merged into one entry, never duplicated.
    feature_spec_ = feature_spec()
    label_spec_ = label_spec()
    feature_pins = real_feature_pins(fixtures, feature_spec_)
    shared = feature_pins[0]
    pit = assemble_point_in_time_samples(
        [fixtures.a, fixtures.f], [request()]
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                label_spec_,
                shared,
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 1, 13, 38, tzinfo=UTC),
                value=1.0,
            )
        ],
        label_spec_,
        (shared,),
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    result = orchestrate(fixtures, requests=[request()])
    merged = result.identity_input.implementations
    assert merged.count(shared) == 1


def test_same_name_version_conflicting_hash_rejected(fixtures, monkeypatch):
    feature_spec_ = feature_spec()
    label_spec_ = label_spec()
    feature_pins = real_feature_pins(fixtures, feature_spec_)
    real = feature_pins[0]
    conflicting = ImplementationPin(real.name, real.version, SHA_C)
    pit = assemble_point_in_time_samples(
        [fixtures.a, fixtures.f], [request()]
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                label_spec_,
                conflicting,
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 1, 13, 38, tzinfo=UTC),
                value=1.0,
            )
        ],
        label_spec_,
        (conflicting,),
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


def test_input_permutation_identity_stable(fixtures):
    requests_list = [
        request(
            f_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
            l_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        ),
        request(
            f_close=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
            l_start=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
        ),
    ]
    specs = [feature_spec("sr"), feature_spec("sr2", window_bars=3)]
    labels = [label_spec("fr"), label_spec("fr2", horizon=3)]
    baseline = orchestrate(
        fixtures, requests=requests_list, feature_specs=specs, label_specs=labels
    )
    permuted = orchestrate(
        fixtures,
        requests=list(reversed(requests_list)),
        builds=[fixtures.f, fixtures.a],
        feature_specs=list(reversed(specs)),
        label_specs=list(reversed(labels)),
    )
    assert baseline.dataset_id == permuted.dataset_id
    assert baseline.logical_dataset_content_id == permuted.logical_dataset_content_id


def test_identity_has_no_time_path_or_mtime_facts(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    identity = result.identity_input
    assert not hasattr(identity, "built_at")
    assert not hasattr(identity, "path")
    assert not hasattr(identity, "mtime")
    assert not hasattr(result, "built_at")
    assert not hasattr(result, "output_path")
    assert not hasattr(result, "manifest")
    assert not hasattr(result, "parquet")


# ---------------------------------------------------------------------------
# K. Identity sensitivity.
# ---------------------------------------------------------------------------


def test_dataset_id_changes_with_dataset_as_of(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        dataset_as_of=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_canonical_row_version(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        builds=[fixtures.a, fixtures.fmin],
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_feature_value(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        feature_specs=[feature_spec(window_bars=3)],
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_label_value(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        label_specs=[label_spec(horizon=3)],
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_label_status(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        builds=[fixtures.a, fixtures.fmin],
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_actual_label_end(fixtures, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.a, fixtures.f], [request()]
    )

    def build_stub(end):
        return stub_label_result(
            [
                hand_label_sample(
                    pit.samples[0],
                    spec,
                    pins[0],
                    status=LABEL_STATUS_COMPLETE,
                    actual_end=end,
                    value=1.0,
                )
            ],
            spec,
            pins,
        )

    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_labels",
        lambda *a, **k: build_stub(datetime(2026, 7, 1, 13, 38, tzinfo=UTC)),
    )
    baseline = orchestrate(fixtures, requests=[request()])
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_labels",
        lambda *a, **k: build_stub(datetime(2026, 7, 1, 15, 0, tzinfo=UTC)),
    )
    variant = orchestrate(fixtures, requests=[request()])
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_split_assignment(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        split=chronological_spec(name="chrono2"),
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_feature_spec_pin(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        feature_specs=[feature_spec("sr2")],
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_label_spec_pin(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        label_specs=[label_spec("fr2")],
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_implementation_pin(fixtures, monkeypatch):
    feature_spec_ = feature_spec()
    label_spec_ = label_spec()
    feature_pins = real_feature_pins(fixtures, feature_spec_)
    pit = assemble_point_in_time_samples(
        [fixtures.a, fixtures.f], [request()]
    )
    other_impl = ImplementationPin("other_impl", "v1", SHA_C)

    def build_stub(impl):
        return stub_label_result(
            [
                hand_label_sample(
                    pit.samples[0],
                    label_spec_,
                    impl,
                    status=LABEL_STATUS_COMPLETE,
                    actual_end=datetime(2026, 7, 1, 13, 38, tzinfo=UTC),
                    value=1.0,
                )
            ],
            label_spec_,
            (impl,),
        )

    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_labels",
        lambda *a, **k: build_stub(feature_pins[0]),
    )
    baseline = orchestrate(fixtures, requests=[request()])
    monkeypatch.setattr(
        orch_mod,
        "execute_builtin_labels",
        lambda *a, **k: build_stub(other_impl),
    )
    variant = orchestrate(fixtures, requests=[request()])
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_completion(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request(), excluded_request()],
    )
    assert variant.completion != baseline.completion
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_scope(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        scope_value=dataset_scope(trade_dates=(date(2026, 7, 1), date(2026, 7, 2))),
    )
    assert variant.dataset_id != baseline.dataset_id


def test_dataset_id_changes_with_schema(fixtures):
    baseline = orchestrate(fixtures, requests=[request()])
    variant = orchestrate(
        fixtures,
        requests=[request()],
        dataset_as_of=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert variant.schema != baseline.schema
    assert variant.dataset_id != baseline.dataset_id


def test_serialization_version_visible_in_identity(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    identity = replace(
        result.identity_input, serialization_format_version="other-version"
    )
    assert dataset_id(identity) != result.dataset_id
    # The entry itself rejects any non-current serialization contract.
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(
            fixtures,
            requests=[request()],
            serialization_format_version="other-version",
        )


# ---------------------------------------------------------------------------
# L. Empty results.
# ---------------------------------------------------------------------------


def test_empty_result_semantics(fixtures):
    first = orchestrate(fixtures, requests=[])
    second = orchestrate(fixtures, requests=[])
    assert first.status == STATUS_EMPTY
    assert first.rows == ()
    assert first.pit_result.samples == ()
    assert first.split_result.assignments == ()
    assert first.diagnostics.logical_row_count == 0
    assert first.diagnostics.split_sample_count == 0
    assert first.diagnostics.pit_sample_count == 0
    assert first.completion.complete_count == 0
    assert first.completion.incomplete_count == 0
    assert first.completion.missing_count == 1
    entry = first.completion.entries[0]
    assert entry.status == "MISSING"
    assert entry.reason_code == DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST
    # Deterministic zero-row identities.
    assert first.logical_dataset_content_id == second.logical_dataset_content_id
    assert first.dataset_id == second.dataset_id
    assert first == second
    # Pins and implementations stay non-empty.
    assert first.identity_input.feature_specs
    assert first.identity_input.label_specs
    assert first.identity_input.implementations
    assert first.identity_input.split_spec is not None


def test_empty_result_uses_verified_identity_core(fixtures):
    result = orchestrate(fixtures, requests=[])
    assert result.dataset_id == dataset_id(result.identity_input)
    assert result.logical_dataset_content_id == logical_dataset_content_id(
        result.schema, ()
    )


# ---------------------------------------------------------------------------
# M. Result model fail-closed re-verification.
# ---------------------------------------------------------------------------


def test_result_is_frozen(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_EMPTY  # type: ignore[misc]


def test_wrong_status_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        replace(result, status=STATUS_EMPTY)


def test_wrong_row_order_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        replace(result, row_order="OTHER_ORDER")


def test_wrong_contract_version_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        replace(result, orchestration_contract_version="other")


def test_wrong_schema_id_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        replace(result, dataset_schema_id="0" * 64)


def test_wrong_content_id_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        replace(result, logical_dataset_content_id="0" * 64)


def test_wrong_identity_input_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    tampered = replace(result.identity_input, dataset_schema_id="0" * 64)
    with pytest.raises(DatasetOrchestrationError):
        replace(result, identity_input=tampered)


def test_wrong_dataset_id_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        replace(result, dataset_id="0" * 64)


def test_wrong_completion_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    entry = result.completion.entries[0]
    tampered = CompletionSummary(
        complete_count=0,
        incomplete_count=1,
        missing_count=0,
        entries=(
            CompletionEntry(
                entry.code,
                entry.trade_date,
                "INCOMPLETE",
                DATASET_COMPLETION_REASON_LABEL_INCOMPLETE,
            ),
        ),
    )
    with pytest.raises(DatasetOrchestrationError):
        replace(result, completion=tampered)


def test_wrong_diagnostics_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    diagnostics = result.diagnostics
    # request_count is not covered by the count matrix, so this tampered
    # diagnostics passes its own construction but must fail the result's
    # recomputed-diagnostics equality.
    tampered = DatasetOrchestrationDiagnostics(
        scope=diagnostics.scope,
        request_count=0,
        pit_sample_count=diagnostics.pit_sample_count,
        feature_complete_sample_count=diagnostics.feature_complete_sample_count,
        feature_excluded_sample_count=diagnostics.feature_excluded_sample_count,
        label_complete_sample_count=diagnostics.label_complete_sample_count,
        label_incomplete_sample_count=diagnostics.label_incomplete_sample_count,
        split_sample_count=diagnostics.split_sample_count,
        assigned_sample_count=diagnostics.assigned_sample_count,
        purged_sample_count=diagnostics.purged_sample_count,
        excluded_sample_count=diagnostics.excluded_sample_count,
        logical_row_count=diagnostics.logical_row_count,
        completion_complete_key_count=diagnostics.completion_complete_key_count,
        completion_incomplete_key_count=diagnostics.completion_incomplete_key_count,
        completion_missing_key_count=diagnostics.completion_missing_key_count,
    )
    with pytest.raises(DatasetOrchestrationError):
        replace(result, diagnostics=tampered)


def test_wrong_subresult_binding_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetOrchestrationError):
        replace(result, pit_result=replace(result.pit_result, samples=()))


def test_dataclasses_replace_tamper_rejected(fixtures):
    result = orchestrate(fixtures, requests=[request()])
    fields = list(result.schema.fields)
    fields[6], fields[7] = fields[7], fields[6]
    with pytest.raises(DatasetOrchestrationError):
        replace(result, schema=DatasetSchema(tuple(fields)))
    with pytest.raises(DatasetOrchestrationError):
        replace(
            result,
            split_spec=chronological_spec(name="other"),
        )
    with pytest.raises(DatasetOrchestrationError):
        replace(
            result,
            manifest_schema_version="other",
        )


# ---------------------------------------------------------------------------
# N. Unified error boundary.
# ---------------------------------------------------------------------------


def test_pit_assembly_error_wrapped_with_cause(fixtures):
    duplicate = request()
    with pytest.raises(DatasetOrchestrationError) as excinfo:
        orchestrate(fixtures, requests=[duplicate, request()])
    assert isinstance(excinfo.value.__cause__, PITAssemblyError)


def test_feature_execution_error_wrapped_with_cause(fixtures, monkeypatch):
    def boom(*args, **kwargs):
        raise FeatureExecutionError("feature boom")

    monkeypatch.setattr(orch_mod, "execute_builtin_features", boom)
    with pytest.raises(DatasetOrchestrationError) as excinfo:
        orchestrate(fixtures, requests=[request()])
    assert isinstance(excinfo.value.__cause__, FeatureExecutionError)


def test_label_execution_error_wrapped_with_cause(fixtures, monkeypatch):
    def boom(*args, **kwargs):
        raise LabelExecutionError("label boom")

    monkeypatch.setattr(orch_mod, "execute_builtin_labels", boom)
    with pytest.raises(DatasetOrchestrationError) as excinfo:
        orchestrate(fixtures, requests=[request()])
    assert isinstance(excinfo.value.__cause__, LabelExecutionError)


def test_split_validation_error_wrapped_with_cause(fixtures, monkeypatch):
    def boom(*args, **kwargs):
        raise SplitValidationError("split boom")

    monkeypatch.setattr(orch_mod, "assign_chronological_splits", boom)
    with pytest.raises(DatasetOrchestrationError) as excinfo:
        orchestrate(fixtures, requests=[request()])
    assert isinstance(excinfo.value.__cause__, SplitValidationError)


def test_dataset_error_wrapped_with_cause(fixtures, monkeypatch):
    def boom(*args, **kwargs):
        raise dataset_pkg.DatasetError("dataset boom")

    monkeypatch.setattr(orch_mod, "assemble_point_in_time_samples", boom)
    with pytest.raises(DatasetOrchestrationError) as excinfo:
        orchestrate(fixtures, requests=[request()])
    assert isinstance(excinfo.value.__cause__, dataset_pkg.DatasetError)


def test_error_boundary_never_returns_partial(fixtures, monkeypatch):
    def boom(*args, **kwargs):
        raise FeatureExecutionError("feature boom")

    monkeypatch.setattr(orch_mod, "execute_builtin_features", boom)
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()])


# ---------------------------------------------------------------------------
# P. Offline / no-side-effect boundary and determinism.
# ---------------------------------------------------------------------------


def test_no_side_effects_and_cwd_unchanged(fixtures):
    cwd_before = os.getcwd()
    root = fixtures.root
    before = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    }
    result = orchestrate(fixtures, requests=[request()])
    assert result is not None
    after = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert os.getcwd() == cwd_before
    assert not (root / "data" / "datasets").exists()


def test_deterministic_rebuild_equivalence(fixtures):
    first = orchestrate(fixtures, requests=[request()])
    second = orchestrate(fixtures, requests=[request()])
    assert first == second
    assert first.dataset_id == second.dataset_id
    assert first.rows == second.rows
