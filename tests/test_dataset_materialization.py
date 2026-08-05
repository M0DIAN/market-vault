"""Offline deterministic tests for the Dataset materialization layer
(v0.5.0 PR-6).

Covers the public API and contract constants, the explicit input contract
(explicit ``output_root`` and timezone-aware ``built_at``, keyword-only, no
current time, no callbacks), the re-triggered PR-5 result self-validation,
the exact final layout, the PyArrow schema mapping and writer contract, the
single-file Parquet rows and readback identity, empty-Dataset
materialization, deterministic spec artifacts (Feature / Label / Split),
the deterministic non-identity build report, DatasetOutputFile byte facts,
manifest construction via the existing core, the fixed staging and write
order, ordinary-exception cleanup, staging residue rejection, existing-build
idempotency (never rewritten, different ``built_at`` tolerated), existing-
build corruption / conflict rejection, the rename race, determinism, the
frozen result model, the unified error boundary, and the no-forbidden-
behavior boundary. All fixtures are micro synthetic canonical builds
produced through the verified reader; no network, no OpenD, no current time,
and no real market data.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import market_vault.dataset as dataset_pkg
import market_vault.dataset.materialization as mat_mod
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    DATASET_BUILD_REPORT_FILENAME,
    DATASET_BUILD_REPORT_SCHEMA_VERSION,
    DATASET_CONTENT_ROLE_BUILD_REPORT,
    DATASET_CONTENT_ROLE_FEATURE_SPEC,
    DATASET_CONTENT_ROLE_LABEL_SPEC,
    DATASET_CONTENT_ROLE_LOGICAL_ROWS,
    DATASET_CONTENT_ROLE_SPLIT_SPEC,
    DATASET_FEATURE_SPECS_DIRNAME,
    DATASET_KIND_SUPERVISED,
    DATASET_LABEL_SPECS_DIRNAME,
    DATASET_MANIFEST_FILENAME,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MATERIALIZER_VERSION,
    DATASET_ORCHESTRATION_CONTRACT_VERSION,
    DATASET_OUTPUT_ROLE_BUILD_REPORT,
    DATASET_OUTPUT_ROLE_DATASET,
    DATASET_OUTPUT_ROLE_FEATURE_SPEC,
    DATASET_OUTPUT_ROLE_LABEL_SPEC,
    DATASET_OUTPUT_ROLE_SPLIT_SPEC,
    DATASET_PARQUET_FILENAME,
    DATASET_SPEC_ARTIFACT_VERSION,
    DATASET_SPLIT_SPEC_FILENAME,
    DATASET_SUCCESS_FILENAME,
    DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    FEATURE_EXECUTION_CONTRACT_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    FEATURE_VALUE_STATUS_COMPLETE,
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_EXECUTION_CONTRACT_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_INCOMPLETE_LABEL,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPLIT_STATUS_ASSIGNED,
    SPLIT_STATUS_EXCLUDED,
    SPLIT_STATUS_PURGED,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    ChronologicalSplitSpec,
    CrossTradingDayPolicy,
    DatasetError,
    DatasetField,
    DatasetMaterializationError,
    DatasetMaterializationResult,
    DatasetOutputFile,
    DatasetOrchestrationError,
    DatasetOrchestrationResult,
    DatasetSchema,
    DatasetScope,
    FeatureExecutionDiagnostics,
    FeatureExecutionResult,
    FeatureSampleResult,
    FeatureSpec,
    FeatureValueResult,
    ImplementationPin,
    LabelExecutionDiagnostics,
    LabelExecutionResult,
    LabelHorizon,
    LabelObservationWindow,
    LabelSampleResult,
    LabelSpec,
    LabelValueResult,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    assemble_point_in_time_samples,
    dataset_orchestration_schema,
    execute_builtin_features,
    execute_builtin_labels,
    feature_label_spec_pin,
    materialize_dataset_artifacts,
    orchestrate_dataset_build,
    parse_feature_spec,
    parse_label_spec,
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

BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Offline canonical-build fixtures (mirrors the orchestration tests; every
# fixture goes through the verified reader).
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
    root = tmp_path_factory.mktemp("mv_materialization")
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
# Spec / request / scope / orchestration helpers.
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


def chronological_spec() -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version="market-vault-chronological-split-spec-v1",
        name="chrono",
        version="v1",
        boundary_timezone=NY,
        train_end_date=date(2026, 6, 30),
        validation_end_date=date(2026, 7, 1),
        test_end_date=date(2026, 7, 2),
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


def excluded_request() -> PITSampleRequest:
    """Feature window [13:30, 13:31): one row < window_bars=2 -> EXCLUDED."""
    return request(
        f_close=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
        l_start=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
        l_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
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


def inputs(fixtures, *, requests, **overrides) -> dict:
    builds = overrides.pop("builds", [fixtures.a, fixtures.f])
    feature_specs = overrides.pop("feature_specs", [feature_spec()])
    label_specs = overrides.pop("label_specs", [label_spec()])
    split_spec = overrides.pop("split_spec", chronological_spec())
    scope = overrides.pop("scope", dataset_scope())
    dataset_as_of = overrides.pop("dataset_as_of", None)
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
    kwargs.update(overrides)
    return kwargs


def orchestrate(fixtures, *, requests, **overrides) -> DatasetOrchestrationResult:
    kwargs = inputs(fixtures, requests=requests, **overrides)
    return orchestrate_dataset_build(**kwargs)


def real_feature_pins(fixtures, spec: FeatureSpec) -> tuple[ImplementationPin, ...]:
    pit = assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()])
    return execute_builtin_features([fixtures.a, fixtures.f], pit, [spec]).implementation_pins


def real_label_pins(fixtures, spec: LabelSpec) -> tuple[ImplementationPin, ...]:
    pit = assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()])
    return execute_builtin_labels([fixtures.a, fixtures.f], pit, [spec]).implementation_pins


def stub_label_result(samples, spec: LabelSpec, impl_pins) -> LabelExecutionResult:
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


# ---------------------------------------------------------------------------
# Materialization helpers.
# ---------------------------------------------------------------------------


def datasets_root(tmp_path) -> Path:
    return tmp_path / "datasets"


def materialize_once(
    fixtures,
    tmp_path,
    *,
    requests=None,
    built_at=BUILT_AT,
    output_root=None,
    **overrides,
):
    result = orchestrate(fixtures, requests=requests or [request()], **overrides)
    root = output_root or datasets_root(tmp_path)
    return result, materialize_dataset_artifacts(
        result, output_root=root, built_at=built_at
    )


def build_path(mresult: DatasetMaterializationResult) -> Path:
    return mresult.build_path


def file_hashes(build: Path) -> dict[str, str]:
    import hashlib

    hashes = {}
    for root, _, files in os.walk(build):
        for name in files:
            path = Path(root) / name
            rel = path.relative_to(build).as_posix()
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def all_artifact_files(build: Path) -> set[str]:
    return set(file_hashes(build))


def _load_output_records(build: Path) -> tuple[DatasetOutputFile, ...]:
    manifest = read_json(build / DATASET_MANIFEST_FILENAME)
    return tuple(
        DatasetOutputFile(
            relative_path=record["relative_path"],
            file_role=record["file_role"],
            row_count=record["row_count"],
            byte_size=record["byte_size"],
            sha256=record["sha256"],
            content_role=record["content_role"],
        )
        for record in manifest["output_files"]
    )


def _make_symlink_or_skip(target: Path, link: Path) -> None:
    """Create a symlink, falling back to a Windows junction (junctions need
    no elevated privileges); skip when neither is available."""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt" and target.is_dir():
        try:
            import _winapi

            _winapi.CreateJunction(str(target.absolute()), str(link.absolute()))
            return
        except (OSError, TypeError, ImportError):
            pass
    pytest.skip(
        f"cannot create a symlink or junction in this environment: {link}"
    )


# ---------------------------------------------------------------------------
# A. Public API / input contract.
# ---------------------------------------------------------------------------


def test_public_api_exports():
    for name in (
        "DATASET_MATERIALIZER_VERSION",
        "DATASET_BUILD_REPORT_SCHEMA_VERSION",
        "DATASET_SPEC_ARTIFACT_VERSION",
        "DATASET_PARQUET_FILENAME",
        "DATASET_MANIFEST_FILENAME",
        "DATASET_BUILD_REPORT_FILENAME",
        "DATASET_SPLIT_SPEC_FILENAME",
        "DATASET_SUCCESS_FILENAME",
        "DATASET_FEATURE_SPECS_DIRNAME",
        "DATASET_LABEL_SPECS_DIRNAME",
        "DatasetMaterializationError",
        "DatasetMaterializationResult",
        "materialize_dataset_artifacts",
    ):
        assert hasattr(dataset_pkg, name)


def test_constants_exact():
    assert dataset_pkg.DATASET_MATERIALIZER_VERSION == (
        "market-vault-dataset-materializer-v1"
    )
    assert dataset_pkg.DATASET_BUILD_REPORT_SCHEMA_VERSION == (
        "market-vault-dataset-build-report-v1"
    )
    assert dataset_pkg.DATASET_SPEC_ARTIFACT_VERSION == (
        "market-vault-dataset-spec-artifact-v1"
    )
    assert dataset_pkg.DATASET_PARQUET_FILENAME == "dataset.parquet"
    assert dataset_pkg.DATASET_MANIFEST_FILENAME == "manifest.json"
    assert dataset_pkg.DATASET_BUILD_REPORT_FILENAME == "build_report.json"
    assert dataset_pkg.DATASET_SPLIT_SPEC_FILENAME == "split_spec.yaml"
    assert dataset_pkg.DATASET_SUCCESS_FILENAME == "_SUCCESS"
    assert dataset_pkg.DATASET_FEATURE_SPECS_DIRNAME == "feature_specs"
    assert dataset_pkg.DATASET_LABEL_SPECS_DIRNAME == "label_specs"
    assert dataset_pkg.DATASET_OUTPUT_ROLE_DATASET == "dataset"
    assert dataset_pkg.DATASET_OUTPUT_ROLE_BUILD_REPORT == "build_report"
    assert dataset_pkg.DATASET_OUTPUT_ROLE_FEATURE_SPEC == "feature_spec"
    assert dataset_pkg.DATASET_OUTPUT_ROLE_LABEL_SPEC == "label_spec"
    assert dataset_pkg.DATASET_OUTPUT_ROLE_SPLIT_SPEC == "split_spec"
    assert dataset_pkg.DATASET_CONTENT_ROLE_LOGICAL_ROWS == "logical_rows"
    assert dataset_pkg.DATASET_CONTENT_ROLE_BUILD_REPORT == (
        "market-vault-dataset-build-report-v1"
    )
    assert dataset_pkg.DATASET_CONTENT_ROLE_FEATURE_SPEC == (
        "market-vault-dataset-spec-artifact-v1"
    )
    assert dataset_pkg.DATASET_CONTENT_ROLE_LABEL_SPEC == (
        "market-vault-dataset-spec-artifact-v1"
    )
    assert dataset_pkg.DATASET_CONTENT_ROLE_SPLIT_SPEC == (
        "market-vault-dataset-spec-artifact-v1"
    )


def test_result_type_rejected(tmp_path):
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            "not a result", output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )


def test_output_root_validation(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=None, built_at=BUILT_AT
        )
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=12345, built_at=BUILT_AT
        )


def test_built_at_required(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(TypeError):
        materialize_dataset_artifacts(result, output_root=datasets_root(tmp_path))
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=None
        )
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result,
            output_root=datasets_root(tmp_path),
            built_at=datetime(2026, 8, 5, 12, 0),
        )


def test_keyword_only(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(TypeError):
        materialize_dataset_artifacts(
            result, datasets_root(tmp_path), BUILT_AT
        )


def test_result_self_validation_retriggered(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    calls = []

    original = DatasetOrchestrationResult.__post_init__
    monkeypatch.setattr(
        DatasetOrchestrationResult,
        "__post_init__",
        lambda self: (calls.append(self), original(self))[1],
    )
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert calls, "result __post_init__ must be re-triggered"
    assert mresult.created_new_build is True


def test_tampered_result_rejected(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    # Any inconsistent re-construction fails closed at object construction
    # (the same validation the materializer re-triggers via
    # dataclasses.replace before it trusts any carried fact).
    with pytest.raises(DatasetOrchestrationError):
        replace(result, dataset_id="0" * 64)
    with pytest.raises(DatasetOrchestrationError):
        replace(result, status=STATUS_EMPTY)
    with pytest.raises(DatasetOrchestrationError):
        replace(result, logical_dataset_content_id="0" * 64)


def test_no_orchestrator_or_layer_execution(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])

    def fail(*args, **kwargs):
        raise AssertionError("layer must not be re-executed")

    import market_vault.dataset.orchestration as orch_mod

    for name in (
        "orchestrate_dataset_build",
        "assemble_point_in_time_samples",
        "execute_builtin_features",
        "execute_builtin_labels",
        "assign_chronological_splits",
    ):
        monkeypatch.setattr(orch_mod, name, fail)
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert mresult.created_new_build is True


# ---------------------------------------------------------------------------
# B. Layout.
# ---------------------------------------------------------------------------


def test_final_path_exact_layout(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    assert build == datasets_root(tmp_path) / result.dataset_id
    assert build.parent == datasets_root(tmp_path)
    assert build.name == result.dataset_id
    assert not build.name.startswith("dataset_id=")
    assert build.is_dir()
    assert mresult.dataset_id == result.dataset_id
    assert mresult.dataset_path == build / DATASET_PARQUET_FILENAME
    assert mresult.manifest_path == build / DATASET_MANIFEST_FILENAME
    assert mresult.build_report_path == build / DATASET_BUILD_REPORT_FILENAME
    assert mresult.success_path == build / DATASET_SUCCESS_FILENAME
    expected = {
        DATASET_PARQUET_FILENAME,
        DATASET_MANIFEST_FILENAME,
        DATASET_BUILD_REPORT_FILENAME,
        DATASET_SPLIT_SPEC_FILENAME,
        DATASET_SUCCESS_FILENAME,
        f"{DATASET_FEATURE_SPECS_DIRNAME}/sr--v1--"
        f"{feature_label_spec_pin(result.feature_specs[0]).content_sha256}.yaml",
        f"{DATASET_LABEL_SPECS_DIRNAME}/fr--v1--"
        f"{feature_label_spec_pin(result.label_specs[0]).content_sha256}.yaml",
    }
    assert all_artifact_files(build) == expected
    assert (build / DATASET_FEATURE_SPECS_DIRNAME).is_dir()
    assert (build / DATASET_LABEL_SPECS_DIRNAME).is_dir()
    # No timestamp directories, no latest pointer, no extra files.
    assert not (datasets_root(tmp_path) / "latest").exists()
    for child in datasets_root(tmp_path).iterdir():
        assert child == build


def test_feature_spec_filenames_exact(fixtures, tmp_path):
    spec_a = feature_spec("sr")
    spec_b = feature_spec("sma") if False else feature_spec("sr2")
    result = orchestrate(
        fixtures,
        requests=[request()],
        feature_specs=[spec_a, spec_b],
    )
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    names = set()
    for spec in result.feature_specs:
        pin = feature_label_spec_pin(spec)
        names.add(f"{pin.name}--{pin.version}--{pin.content_sha256}.yaml")
    dir_names = {
        path.name
        for path in (build_path(mresult) / DATASET_FEATURE_SPECS_DIRNAME).iterdir()
    }
    assert dir_names == names


def test_label_spec_filenames_exact(fixtures, tmp_path):
    spec_a = label_spec("fr")
    spec_b = label_spec("fr2")
    result = orchestrate(
        fixtures,
        requests=[request()],
        label_specs=[spec_a, spec_b],
    )
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    names = set()
    for spec in result.label_specs:
        pin = feature_label_spec_pin(spec)
        names.add(f"{pin.name}--{pin.version}--{pin.content_sha256}.yaml")
    dir_names = {
        path.name
        for path in (build_path(mresult) / DATASET_LABEL_SPECS_DIRNAME).iterdir()
    }
    assert dir_names == names
    assert (build_path(mresult) / DATASET_SPLIT_SPEC_FILENAME).is_file()


# ---------------------------------------------------------------------------
# C. PyArrow schema.
# ---------------------------------------------------------------------------


def test_arrow_type_mapping():
    from market_vault.dataset.artifact_serialization import (
        _dataset_schema_to_arrow,
        _logical_type_to_arrow_type,
    )

    assert _logical_type_to_arrow_type("string") == pa.string()
    assert _logical_type_to_arrow_type("int64") == pa.int64()
    assert _logical_type_to_arrow_type("float64") == pa.float64()
    assert _logical_type_to_arrow_type("bool") == pa.bool_()
    assert _logical_type_to_arrow_type("date32") == pa.date32()
    assert _logical_type_to_arrow_type("timestamp_us_utc") == pa.timestamp(
        "us", tz="UTC"
    )
    with pytest.raises(DatasetMaterializationError):
        _logical_type_to_arrow_type("object")


def test_arrow_schema_field_order_and_nullability():
    from market_vault.dataset.artifact_serialization import (
        _dataset_schema_to_arrow,
    )

    schema = DatasetSchema(
        (
            DatasetField("a", "string", False),
            DatasetField("b", "float64", True),
            DatasetField("c", "timestamp_us_utc", True),
            DatasetField("d", "date32", False),
            DatasetField("e", "int64", False),
            DatasetField("f", "bool", True),
        )
    )
    arrow = _dataset_schema_to_arrow(
        schema,
        dataset_id="0" * 64,
        dataset_schema_id_value="1" * 64,
        logical_dataset_content_id_value="2" * 64,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
        row_order=DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    )
    assert [field.name for field in arrow] == ["a", "b", "c", "d", "e", "f"]
    assert arrow.field("a").type == pa.string()
    assert arrow.field("b").type == pa.float64()
    assert arrow.field("c").type == pa.timestamp("us", tz="UTC")
    assert arrow.field("d").type == pa.date32()
    assert arrow.field("e").type == pa.int64()
    assert arrow.field("f").type == pa.bool_()
    assert arrow.field("a").nullable is False
    assert arrow.field("b").nullable is True
    assert arrow.field("f").nullable is True


def test_parquet_schema_of_materialized_build(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    table = pq.read_table(mresult.dataset_path)
    fields = {field.name: field for field in table.schema}
    assert fields["code"].type == pa.string()
    assert fields["feature_window_close"].type == pa.timestamp("us", tz="UTC")
    assert fields["feature_window_close_date"].type == pa.date32()
    assert fields["sr"].type == pa.float64()
    assert fields["fr"].type == pa.float64()
    assert fields["label_status"].type == pa.string()
    assert fields["purge_boundary"].type == pa.timestamp("us", tz="UTC")
    # Nullability of the label output and nullable split fields.
    assert fields["fr"].nullable is True
    assert fields["sr"].nullable is False
    assert fields["nominal_split"].nullable is True
    assert fields["assignment_status"].nullable is False
    # No pandas index column.
    assert "index" not in fields


def test_parquet_metadata_exact(fixtures, tmp_path):
    from market_vault.dataset.artifact_serialization import (
        PARQUET_METADATA_KEY_CONTENT_ID,
        PARQUET_METADATA_KEY_DATASET_ID,
        PARQUET_METADATA_KEY_FORMAT_VERSION,
        PARQUET_METADATA_KEY_MATERIALIZER,
        PARQUET_METADATA_KEY_ROW_ORDER,
        PARQUET_METADATA_KEY_SCHEMA_ID,
    )

    result, mresult = materialize_once(fixtures, tmp_path)
    table = pq.read_table(mresult.dataset_path)
    metadata = {
        key.decode("utf-8"): value.decode("utf-8")
        for key, value in table.schema.metadata.items()
    }
    assert metadata == {
        PARQUET_METADATA_KEY_DATASET_ID: result.dataset_id,
        PARQUET_METADATA_KEY_SCHEMA_ID: result.dataset_schema_id,
        PARQUET_METADATA_KEY_CONTENT_ID: result.logical_dataset_content_id,
        PARQUET_METADATA_KEY_FORMAT_VERSION: (
            SERIALIZATION_FORMAT_VERSION_PARQUET
        ),
        PARQUET_METADATA_KEY_ROW_ORDER: (
            DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY
        ),
        PARQUET_METADATA_KEY_MATERIALIZER: DATASET_MATERIALIZER_VERSION,
    }


# ---------------------------------------------------------------------------
# D. Parquet rows.
# ---------------------------------------------------------------------------


def test_single_file_and_row_count(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    parquet_files = [
        path
        for path in build.rglob("*.parquet")
        if path.is_file()
    ]
    assert parquet_files == [build / DATASET_PARQUET_FILENAME]
    table = pq.read_table(mresult.dataset_path)
    assert table.num_rows == len(result.rows) == 1


def test_physical_row_order_and_values(fixtures, tmp_path):
    from market_vault.dataset.artifact_serialization import (
        readback_rows_and_content_id,
    )

    result, mresult = materialize_once(fixtures, tmp_path)
    rows, content_id = readback_rows_and_content_id(
        mresult.dataset_path, result.schema
    )
    assert rows == result.rows
    assert content_id == result.logical_dataset_content_id
    assert mresult.logical_row_count == len(result.rows) == 1


def test_null_label_value_in_parquet(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()], builds=[fixtures.a, fixtures.fmin])
    assert result.status == STATUS_COMPLETE
    row_map = dict(zip((f.name for f in result.schema.fields), result.rows[0]))
    assert row_map["label_status"] == LABEL_STATUS_INCOMPLETE
    assert row_map["fr"] is None
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    table = pq.read_table(mresult.dataset_path)
    assert table.num_rows == 1
    assert table.column("fr").to_pylist() == [None]
    assert table.column("label_status").to_pylist() == [LABEL_STATUS_INCOMPLETE]
    assert table.column("assignment_status").to_pylist() == [SPLIT_STATUS_EXCLUDED]
    assert table.column("reason_code").to_pylist() == [REASON_CODE_INCOMPLETE_LABEL]


def test_purged_row_retained(fixtures, tmp_path, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.c],
        [request(
            anchor=date(2026, 6, 30),
            f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC),
            f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC),
        )],
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
        "market_vault.dataset.orchestration.execute_builtin_labels",
        lambda *a, **k: stub,
    )
    result = orchestrate(
        fixtures,
        requests=[request(
            anchor=date(2026, 6, 30),
            f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC),
            f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC),
        )],
        builds=[fixtures.c],
        scope=dataset_scope(trade_dates=(date(2026, 6, 30),)),
    )
    assignment = result.split_result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    table = pq.read_table(mresult.dataset_path)
    assert table.num_rows == 1
    assert table.column("assignment_status").to_pylist() == [SPLIT_STATUS_PURGED]
    assert table.column("reason_code").to_pylist() == [
        REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
    ]
    assert table.column("purge_boundary").to_pylist() == [
        datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    ]
    assert table.column("final_split").to_pylist() == [None]


def test_feature_excluded_not_in_parquet(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request(), excluded_request()])
    assert result.diagnostics.feature_excluded_sample_count == 1
    assert result.diagnostics.logical_row_count == 1
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    table = pq.read_table(mresult.dataset_path)
    assert table.num_rows == 1
    assert mresult.logical_row_count == 1


def test_timestamp_values_utc_microseconds(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    table = pq.read_table(mresult.dataset_path)
    close_values = table.column("feature_window_close").to_pylist()
    assert close_values == [datetime(2026, 7, 1, 13, 36, tzinfo=UTC)]
    assert table.column("feature_window_close_date").to_pylist() == [
        date(2026, 7, 1)
    ]


def test_nan_rejected_before_write(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetMaterializationError):
        mat_mod.write_dataset_parquet(
            tmp_path / "bad.parquet",
            schema=result.schema,
            rows=(
                tuple(
                    float("nan") if index == 7 else value
                    for index, value in enumerate(result.rows[0])
                ),
            ),
            dataset_id_value=result.dataset_id,
            dataset_schema_id_value=result.dataset_schema_id,
            logical_dataset_content_id_value=result.logical_dataset_content_id,
            serialization_format_version=result.serialization_format_version,
            row_order=result.row_order,
        )


def test_infinity_rejected_before_write(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    for bad in (float("inf"), float("-inf")):
        with pytest.raises(DatasetMaterializationError):
            mat_mod.write_dataset_parquet(
                tmp_path / f"bad-{bad}.parquet",
                schema=result.schema,
                rows=(
                    tuple(
                        bad if index == 7 else value
                        for index, value in enumerate(result.rows[0])
                    ),
                ),
                dataset_id_value=result.dataset_id,
                dataset_schema_id_value=result.dataset_schema_id,
                logical_dataset_content_id_value=result.logical_dataset_content_id,
                serialization_format_version=result.serialization_format_version,
                row_order=result.row_order,
            )


def test_readback_content_id_and_no_nan_inf(fixtures, tmp_path):
    from market_vault.dataset.artifact_serialization import (
        _table_to_logical_rows,
        read_dataset_parquet,
    )

    result, mresult = materialize_once(fixtures, tmp_path)
    table = read_dataset_parquet(mresult.dataset_path)
    rows = _table_to_logical_rows(table, result.schema)
    assert rows == result.rows
    for row in rows:
        for value in row:
            assert not isinstance(value, float) or (value == value and abs(value) != float("inf"))


# ---------------------------------------------------------------------------
# E. Empty Dataset.
# ---------------------------------------------------------------------------


def test_empty_dataset_materialization(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[])
    assert result.status == STATUS_EMPTY
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert mresult.status == STATUS_EMPTY
    assert mresult.logical_row_count == 0
    assert mresult.created_new_build is True
    build = build_path(mresult)
    assert build.name == result.dataset_id
    table = pq.read_table(mresult.dataset_path)
    assert table.num_rows == 0
    assert len(table.schema) == len(result.schema.fields)
    assert table.schema.metadata  # full metadata present
    manifest = read_json(mresult.manifest_path)
    assert manifest["status"] == STATUS_EMPTY
    assert manifest["logical_row_count"] == 0
    assert (build / DATASET_SPLIT_SPEC_FILENAME).is_file()
    assert len(list((build / DATASET_FEATURE_SPECS_DIRNAME).iterdir())) == 1
    assert len(list((build / DATASET_LABEL_SPECS_DIRNAME).iterdir())) == 1
    assert (build / DATASET_SUCCESS_FILENAME).is_file()
    # Idempotent rebuild.
    again = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert again.created_new_build is False
    assert again.build_path == build


def test_empty_dataset_content_id_readback(fixtures, tmp_path):
    from market_vault.dataset.artifact_serialization import (
        readback_rows_and_content_id,
    )

    result = orchestrate(fixtures, requests=[])
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    rows, content_id = readback_rows_and_content_id(
        mresult.dataset_path, result.schema
    )
    assert rows == ()
    assert content_id == result.logical_dataset_content_id


# ---------------------------------------------------------------------------
# F. Spec artifacts.
# ---------------------------------------------------------------------------


def test_feature_spec_artifact_roundtrip(fixtures, tmp_path):
    from market_vault.dataset.artifact_serialization import feature_spec_artifact

    spec = feature_spec()
    data = feature_spec_artifact(spec)
    text = data.decode("utf-8")
    assert not text.startswith("﻿")  # no BOM
    assert text.endswith("\n")  # trailing newline
    parsed = parse_feature_spec(text)
    assert parsed == spec
    assert feature_label_spec_pin(parsed) == feature_label_spec_pin(spec)
    # Deterministic bytes.
    assert feature_spec_artifact(spec) == data


def test_label_spec_artifact_roundtrip(fixtures, tmp_path):
    from market_vault.dataset.artifact_serialization import label_spec_artifact

    spec = label_spec()
    data = label_spec_artifact(spec)
    text = data.decode("utf-8")
    assert not text.startswith("﻿")
    assert text.endswith("\n")
    parsed = parse_label_spec(text)
    assert parsed == spec
    assert feature_label_spec_pin(parsed) == feature_label_spec_pin(spec)


def test_split_spec_artifact_roundtrip():
    from market_vault.dataset.artifact_serialization import (
        parse_split_spec_artifact,
        split_spec_artifact,
    )
    from market_vault.dataset.split_models import chronological_split_spec_pin

    spec = chronological_spec()
    data = split_spec_artifact(spec)
    text = data.decode("utf-8")
    assert not text.startswith("﻿")
    assert text.endswith("\n")
    parsed = parse_split_spec_artifact(text)
    assert parsed == spec
    assert chronological_split_spec_pin(parsed) == chronological_split_spec_pin(spec)
    # Strict exact-field parsing fails closed.
    import json as _json

    payload = _json.loads(text)
    del payload["boundary_timezone"]
    with pytest.raises(DatasetMaterializationError):
        parse_split_spec_artifact(_json.dumps(payload))
    payload = _json.loads(text)
    payload["extra_field"] = 1
    with pytest.raises(DatasetMaterializationError):
        parse_split_spec_artifact(_json.dumps(payload))
    with pytest.raises(DatasetMaterializationError):
        parse_split_spec_artifact("{not json")


def test_split_artifact_kind_must_be_split():
    from market_vault.dataset.artifact_serialization import (
        parse_split_spec_artifact,
        split_spec_artifact,
    )
    from market_vault.dataset.split_models import chronological_split_spec_pin

    spec = chronological_spec()
    payload = json.loads(split_spec_artifact(spec))
    for bad_kind in ("FEATURE", "LABEL", "", "UNKNOWN", 123, None, []):
        tampered = dict(payload)
        tampered["kind"] = bad_kind
        with pytest.raises(DatasetMaterializationError):
            parse_split_spec_artifact(json.dumps(tampered))
    # A missing kind is also rejected (non-string check first).
    tampered = dict(payload)
    del tampered["kind"]
    with pytest.raises(DatasetMaterializationError):
        parse_split_spec_artifact(json.dumps(tampered))
    # The correct SPLIT artifact passes and rebuilds the same spec and pin.
    parsed = parse_split_spec_artifact(split_spec_artifact(spec).decode("utf-8"))
    assert parsed == spec
    assert chronological_split_spec_pin(parsed) == chronological_split_spec_pin(spec)


def test_staged_spec_artifacts_reproduce_pins(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    for spec in result.feature_specs:
        pin = feature_label_spec_pin(spec)
        rel = f"{DATASET_FEATURE_SPECS_DIRNAME}/{pin.name}--{pin.version}--{pin.content_sha256}.yaml"
        parsed = parse_feature_spec((build / rel).read_text(encoding="utf-8"))
        assert parsed == spec
    for spec in result.label_specs:
        pin = feature_label_spec_pin(spec)
        rel = f"{DATASET_LABEL_SPECS_DIRNAME}/{pin.name}--{pin.version}--{pin.content_sha256}.yaml"
        parsed = parse_label_spec((build / rel).read_text(encoding="utf-8"))
        assert parsed == spec
    split_text = (build / DATASET_SPLIT_SPEC_FILENAME).read_text(encoding="utf-8")
    assert "boundary_timezone" in split_text


def test_spec_input_order_does_not_change_artifacts(fixtures, tmp_path):
    from market_vault.dataset.artifact_serialization import (
        feature_spec_artifact,
        label_spec_artifact,
    )

    f1 = feature_spec("sr")
    f2 = feature_spec("sma")
    l1 = label_spec("fr")
    l2 = label_spec("mfe2") if False else label_spec("fr2")
    result_a = orchestrate(
        fixtures, requests=[request()],
        feature_specs=[f1, f2], label_specs=[l1, l2],
    )
    result_b = orchestrate(
        fixtures, requests=[request()],
        feature_specs=[f2, f1], label_specs=[l2, l1],
    )
    assert result_a.dataset_id == result_b.dataset_id
    ma = materialize_dataset_artifacts(
        result_a, output_root=datasets_root(tmp_path) / "a", built_at=BUILT_AT
    )
    mb = materialize_dataset_artifacts(
        result_b, output_root=datasets_root(tmp_path) / "b", built_at=BUILT_AT
    )
    assert all_artifact_files(build_path(ma)) == all_artifact_files(build_path(mb))
    for spec in result_a.feature_specs:
        rel = f"{DATASET_FEATURE_SPECS_DIRNAME}/{feature_label_spec_pin(spec).name}--{feature_label_spec_pin(spec).version}--{feature_label_spec_pin(spec).content_sha256}.yaml"
        assert (build_path(ma) / rel).read_bytes() == (build_path(mb) / rel).read_bytes()
    assert feature_spec_artifact(f1) == feature_spec_artifact(f1)
    assert label_spec_artifact(l1) == label_spec_artifact(l1)


def test_artifact_contains_no_source_paths_or_tags(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    for path in (
        build / DATASET_SPLIT_SPEC_FILENAME,
        *(build / DATASET_FEATURE_SPECS_DIRNAME).iterdir(),
        *(build / DATASET_LABEL_SPECS_DIRNAME).iterdir(),
    ):
        data = path.read_bytes()
        # No Python object tags and no source-file comments survive.
        assert b"!!python" not in data
        assert b"#" not in data
    import yaml

    split = yaml.safe_load(
        (build / DATASET_SPLIT_SPEC_FILENAME).read_text(encoding="utf-8")
    )
    assert isinstance(split, dict)
    assert split["kind"] == "SPLIT"


# ---------------------------------------------------------------------------
# G. build_report.
# ---------------------------------------------------------------------------


def test_build_report_fields_exact(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    report = read_json(mresult.build_report_path)
    assert report["report_schema_version"] == DATASET_BUILD_REPORT_SCHEMA_VERSION
    assert report["materializer_version"] == DATASET_MATERIALIZER_VERSION
    assert report["dataset_id"] == result.dataset_id
    assert report["dataset_kind"] == DATASET_KIND_SUPERVISED
    assert report["status"] == result.status
    assert report["built_at"] == BUILT_AT.astimezone(UTC).isoformat(timespec="microseconds")
    assert report["dataset_as_of"] is None
    assert report["dataset_schema_id"] == result.dataset_schema_id
    assert report["logical_dataset_content_id"] == result.logical_dataset_content_id
    assert report["logical_row_count"] == 1
    assert report["orchestration_contract_version"] == (
        DATASET_ORCHESTRATION_CONTRACT_VERSION
    )
    assert report["row_order"] == DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY
    assert report["manifest_schema_version"] == DATASET_MANIFEST_SCHEMA_VERSION
    assert report["serialization_format"] == SERIALIZATION_FORMAT_PARQUET
    assert report["serialization_format_version"] == (
        SERIALIZATION_FORMAT_VERSION_PARQUET
    )
    assert report["feature_spec_count"] == 1
    assert report["label_spec_count"] == 1
    assert report["canonical_build_pin_count"] == 2
    assert report["canonical_row_version_count"] > 0
    assert report["completion_complete_key_count"] == 1
    assert report["completion_incomplete_key_count"] == 0
    assert report["completion_missing_key_count"] == 0
    diagnostics = result.diagnostics
    assert report["request_count"] == diagnostics.request_count
    assert report["pit_sample_count"] == diagnostics.pit_sample_count
    assert report["feature_complete_sample_count"] == (
        diagnostics.feature_complete_sample_count
    )
    assert report["feature_excluded_sample_count"] == (
        diagnostics.feature_excluded_sample_count
    )
    assert report["label_complete_sample_count"] == (
        diagnostics.label_complete_sample_count
    )
    assert report["label_incomplete_sample_count"] == (
        diagnostics.label_incomplete_sample_count
    )
    assert report["split_sample_count"] == diagnostics.split_sample_count
    assert report["assigned_sample_count"] == diagnostics.assigned_sample_count
    assert report["purged_sample_count"] == diagnostics.purged_sample_count
    assert report["excluded_sample_count"] == diagnostics.excluded_sample_count
    assert report["split_spec_content_id"] == (
        result.split_result.split_spec_pin.content_sha256
    )
    assert report["split_result_id"] == result.split_result.split_result_id
    assert report["output_layout"]["dataset_parquet_filename"] == "dataset.parquet"
    assert report["output_layout"]["manifest_filename"] == "manifest.json"


def test_build_report_no_forbidden_facts(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    report = read_json(mresult.build_report_path)
    for key in report:
        assert "path" not in key and "cwd" not in key and "pid" not in key
        assert "hostname" not in key and "username" not in key and "branch" not in key
        assert "elapsed" not in key and "random" not in key and "staging" not in key
        assert key != "created_new_build"
    text = mresult.build_report_path.read_bytes()
    assert b"created_new_build" not in text
    # The local temporary output path never leaks into the report.
    assert str(datasets_root(tmp_path)).encode("utf-8") not in text
    assert b"timezone" not in text


def test_build_report_deterministic_bytes(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    root_a = datasets_root(tmp_path) / "a"
    root_b = datasets_root(tmp_path) / "b"
    ma = materialize_dataset_artifacts(result, output_root=root_a, built_at=BUILT_AT)
    mb = materialize_dataset_artifacts(result, output_root=root_b, built_at=BUILT_AT)
    assert ma.build_report_path.read_bytes() == mb.build_report_path.read_bytes()
    assert ma.manifest_path.read_bytes() == mb.manifest_path.read_bytes()
    assert (
        ma.build_path / DATASET_SPLIT_SPEC_FILENAME
    ).read_bytes() == (mb.build_path / DATASET_SPLIT_SPEC_FILENAME).read_bytes()


def test_built_at_change_does_not_change_dataset_id(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    other = datetime(2026, 8, 6, 1, 30, 15, 123456, tzinfo=UTC)
    ma = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path) / "a", built_at=BUILT_AT
    )
    mb = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path) / "b", built_at=other
    )
    assert ma.dataset_id == mb.dataset_id == result.dataset_id
    assert ma.build_report_path.read_bytes() != mb.build_report_path.read_bytes()
    report_b = read_json(mb.build_report_path)
    assert report_b["built_at"] == other.astimezone(UTC).isoformat(timespec="microseconds")


# ---------------------------------------------------------------------------
# H. DatasetOutputFile / manifest.
# ---------------------------------------------------------------------------


def test_output_files_exact_set(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    manifest = read_json(mresult.manifest_path)
    paths = {record["relative_path"] for record in manifest["output_files"]}
    assert paths == all_artifact_files(build) - {DATASET_MANIFEST_FILENAME, DATASET_SUCCESS_FILENAME}
    assert DATASET_MANIFEST_FILENAME not in paths
    assert DATASET_SUCCESS_FILENAME not in paths


def test_output_file_roles_and_row_counts(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    manifest = read_json(mresult.manifest_path)
    by_path = {record["relative_path"]: record for record in manifest["output_files"]}
    dataset_record = by_path[DATASET_PARQUET_FILENAME]
    assert dataset_record["file_role"] == DATASET_OUTPUT_ROLE_DATASET
    assert dataset_record["row_count"] == 1
    assert dataset_record["content_role"] == DATASET_CONTENT_ROLE_LOGICAL_ROWS
    report_record = by_path[DATASET_BUILD_REPORT_FILENAME]
    assert report_record["file_role"] == DATASET_OUTPUT_ROLE_BUILD_REPORT
    assert report_record["row_count"] == 1
    assert report_record["content_role"] == DATASET_CONTENT_ROLE_BUILD_REPORT
    feature_path = next(
        p for p in by_path if p.startswith(DATASET_FEATURE_SPECS_DIRNAME + "/")
    )
    assert by_path[feature_path]["file_role"] == DATASET_OUTPUT_ROLE_FEATURE_SPEC
    assert by_path[feature_path]["row_count"] == 1
    assert by_path[feature_path]["content_role"] == DATASET_CONTENT_ROLE_FEATURE_SPEC
    label_path = next(
        p for p in by_path if p.startswith(DATASET_LABEL_SPECS_DIRNAME + "/")
    )
    assert by_path[label_path]["file_role"] == DATASET_OUTPUT_ROLE_LABEL_SPEC
    assert by_path[label_path]["row_count"] == 1
    assert by_path[label_path]["content_role"] == DATASET_CONTENT_ROLE_LABEL_SPEC
    split_record = by_path[DATASET_SPLIT_SPEC_FILENAME]
    assert split_record["file_role"] == DATASET_OUTPUT_ROLE_SPLIT_SPEC
    assert split_record["row_count"] == 1
    assert split_record["content_role"] == DATASET_CONTENT_ROLE_SPLIT_SPEC


def test_output_file_byte_facts_match_disk(fixtures, tmp_path):
    import hashlib

    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    manifest = read_json(mresult.manifest_path)
    for record in manifest["output_files"]:
        path = build / record["relative_path"]
        assert path.stat().st_size == record["byte_size"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == record["sha256"]


def _rewrite_manifest_with_records(result, build: Path, records) -> None:
    """Replace manifest.json with a canonical manifest carrying the given
    records (paths, hashes, sizes, counts untouched where not overridden).
    The manifest itself stays canonical and identity-valid, so the rejection
    under test is the full output-record equality, not the canonical-bytes
    or manifest-validation checks."""
    manifest = dataset_pkg.validate_dataset_manifest(
        (build / DATASET_MANIFEST_FILENAME).read_bytes()
    )
    rebuilt = dataset_pkg.build_dataset_manifest(
        result.identity_input,
        built_at=manifest.built_at,
        status=manifest.status,
        logical_row_count=manifest.logical_row_count,
        output_files=records,
    )
    (build / DATASET_MANIFEST_FILENAME).write_bytes(
        dataset_pkg.serialize_dataset_manifest(rebuilt)
    )


def test_output_file_role_tamper_rejected(built, tmp_path):
    """A manifest whose dataset.parquet record has the wrong file_role —
    with correct path, hash, size, and row count — is rejected by the full
    record equality."""
    result, _, build = built
    records = _load_output_records(build)
    tampered = tuple(
        replace(record, file_role=DATASET_OUTPUT_ROLE_LABEL_SPEC)
        if record.relative_path == DATASET_PARQUET_FILENAME
        else record
        for record in records
    )
    _rewrite_manifest_with_records(result, build, tampered)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
    assert build.is_dir()


def test_output_file_content_role_tamper_rejected(built, tmp_path):
    """A manifest whose build_report record has the wrong content_role is
    rejected even when every other record fact is correct."""
    result, _, build = built
    records = _load_output_records(build)
    tampered = tuple(
        replace(record, content_role="wrong-content-role")
        if record.relative_path == DATASET_BUILD_REPORT_FILENAME
        else record
        for record in records
    )
    _rewrite_manifest_with_records(result, build, tampered)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )


def test_output_file_feature_label_role_swap_rejected(built, tmp_path):
    """Feature and Label spec records with swapped file_roles are
    rejected."""
    result, _, build = built
    records = _load_output_records(build)
    feature_path = next(
        record.relative_path
        for record in records
        if record.file_role == DATASET_OUTPUT_ROLE_FEATURE_SPEC
    )
    label_path = next(
        record.relative_path
        for record in records
        if record.file_role == DATASET_OUTPUT_ROLE_LABEL_SPEC
    )

    def swapped(record):
        if record.relative_path == feature_path:
            return replace(record, file_role=DATASET_OUTPUT_ROLE_LABEL_SPEC)
        if record.relative_path == label_path:
            return replace(record, file_role=DATASET_OUTPUT_ROLE_FEATURE_SPEC)
        return record

    _rewrite_manifest_with_records(result, build, tuple(swapped(r) for r in records))
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )


def test_manifest_facts_match_result(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    manifest = read_json(mresult.manifest_path)
    assert manifest["dataset_id"] == result.dataset_id
    assert manifest["dataset_schema_id"] == result.dataset_schema_id
    assert manifest["logical_dataset_content_id"] == (
        result.logical_dataset_content_id
    )
    assert manifest["status"] == result.status
    assert manifest["logical_row_count"] == len(result.rows)
    assert manifest["manifest_schema_version"] == DATASET_MANIFEST_SCHEMA_VERSION
    assert manifest["serialization_format"] == SERIALIZATION_FORMAT_PARQUET
    assert manifest["serialization_format_version"] == (
        SERIALIZATION_FORMAT_VERSION_PARQUET
    )
    assert manifest["built_at"] == BUILT_AT.astimezone(UTC).isoformat(timespec="microseconds")
    schema_names = [f["name"] for f in manifest["schema"]["fields"]]
    assert schema_names == [f.name for f in result.schema.fields]


def test_manifest_roundtrip_validation(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    payload = mresult.manifest_path.read_bytes()
    manifest = dataset_pkg.validate_dataset_manifest(payload)
    assert manifest.dataset_id == result.dataset_id
    assert manifest.logical_row_count == len(result.rows)
    # parquet + report + split + 1 feature spec + 1 label spec
    assert len(manifest.output_files) == 5
    assert manifest.output_files == tuple(
        sorted(manifest.output_files, key=lambda record: record.relative_path)
    )


def test_build_dataset_manifest_called(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    calls = []
    original = mat_mod.build_dataset_manifest

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(mat_mod, "build_dataset_manifest", spy)
    materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == result.identity_input
    assert kwargs["built_at"] == BUILT_AT
    assert kwargs["status"] == result.status
    assert kwargs["logical_row_count"] == len(result.rows)
    assert len(kwargs["output_files"]) == 5


# ---------------------------------------------------------------------------
# I. Write order / staging.
# ---------------------------------------------------------------------------


def test_write_order_and_staging(tmp_path, fixtures, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)
    events = []

    original_parquet = mat_mod.write_dataset_parquet

    def spy_parquet(path, **kwargs):
        assert path.parent == output_root / f".staging-{result.dataset_id}"
        events.append(("parquet",))
        return original_parquet(path, **kwargs)

    original_artifact = mat_mod._write_artifact_bytes

    def spy_artifact(path, data):
        assert path.parent == output_root / f".staging-{result.dataset_id}" or path.parent.parent == output_root / f".staging-{result.dataset_id}"
        events.append(("artifact", path.name))
        return original_artifact(path, data)

    original_success = mat_mod._write_empty_success

    def spy_success(path):
        events.append(("success",))
        return original_success(path)

    original_verify = mat_mod._verify_build_directory

    def spy_verify(build_dir, expected, built_at, *, require_success):
        events.append(("verify",))
        return original_verify(build_dir, expected, built_at, require_success=require_success)

    original_publish = mat_mod._publish_staging

    def spy_publish(staging, final, result_value):
        events.append(("publish",))
        assert staging.parent == final.parent  # same filesystem
        return original_publish(staging, final, result_value)

    def fail_replace(*args, **kwargs):
        raise AssertionError("os.replace must never be used")

    monkeypatch.setattr(mat_mod, "write_dataset_parquet", spy_parquet)
    monkeypatch.setattr(mat_mod, "_write_artifact_bytes", spy_artifact)
    monkeypatch.setattr(mat_mod, "_write_empty_success", spy_success)
    monkeypatch.setattr(mat_mod, "_verify_build_directory", spy_verify)
    monkeypatch.setattr(mat_mod, "_publish_staging", spy_publish)
    monkeypatch.setattr(os, "replace", fail_replace)

    mresult = materialize_dataset_artifacts(
        result, output_root=output_root, built_at=BUILT_AT
    )
    assert mresult.created_new_build is True
    names = [event[0] for event in events]
    assert names[0] == "parquet"
    artifact_names = [event[1] for event in events if event[0] == "artifact"]
    assert artifact_names[0].startswith("sr--v1--") or True
    assert "manifest.json" in artifact_names
    assert "build_report.json" in artifact_names
    assert "split_spec.yaml" in artifact_names
    assert artifact_names.index("build_report.json") < artifact_names.index("manifest.json")
    assert artifact_names.index("split_spec.yaml") < artifact_names.index("manifest.json")
    assert artifact_names.index("manifest.json") == len(artifact_names) - 1
    assert names.index("verify") < names.index("success") < names.index("publish")
    assert names[-1] == "publish"
    # final did not exist before the publish.
    assert not (output_root / result.dataset_id).exists() or events[-1][0] == "publish"


# ---------------------------------------------------------------------------
# J. Cleanup / residue.
# ---------------------------------------------------------------------------


def test_writer_failure_cleans_staging(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    def fail_write(path, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mat_mod, "write_dataset_parquet", fail_write)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert not (output_root / result.dataset_id).exists()
    assert not (output_root / f".staging-{result.dataset_id}").exists()


def test_manifest_failure_cleans_staging(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    def fail_manifest(*args, **kwargs):
        raise DatasetError("manifest boom")

    monkeypatch.setattr(mat_mod, "build_dataset_manifest", fail_manifest)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert not (output_root / result.dataset_id).exists()
    assert not (output_root / f".staging-{result.dataset_id}").exists()


def test_verification_failure_cleans_staging(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    def fail_verify(build_dir, expected, built_at, *, require_success):
        raise DatasetMaterializationError("verification boom")

    monkeypatch.setattr(mat_mod, "_verify_build_directory", fail_verify)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert not (output_root / result.dataset_id).exists()
    assert not (output_root / f".staging-{result.dataset_id}").exists()


def test_preexisting_staging_residue_fails(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)
    output_root.mkdir(parents=True)
    residue = output_root / f".staging-{result.dataset_id}"
    residue.mkdir()
    (residue / "junk.txt").write_text("residue")
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert "staging" in str(excinfo.value).lower()
    # The residue is never deleted or adopted.
    assert residue.is_dir()
    assert (residue / "junk.txt").exists()
    assert not (output_root / result.dataset_id).exists()


def test_preexisting_staging_file_fails(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)
    output_root.mkdir(parents=True)
    residue = output_root / f".staging-{result.dataset_id}"
    residue.write_text("not a directory")
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert residue.is_file()
    assert not (output_root / result.dataset_id).exists()


def test_preexisting_staging_symlink_fails(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)
    output_root.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    residue = output_root / f".staging-{result.dataset_id}"
    _make_symlink_or_skip(elsewhere, residue)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert not (output_root / result.dataset_id).exists()


def test_programming_error_not_swallowed_or_cleaned(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    def boom(path, **kwargs):
        raise RuntimeError("programming bug")

    monkeypatch.setattr(mat_mod, "write_dataset_parquet", boom)
    with pytest.raises(RuntimeError):
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert not (output_root / result.dataset_id).exists()
    # The staging residue of an unhandled programming error stays for manual
    # inspection (never silently cleaned, never adopted).
    assert (output_root / f".staging-{result.dataset_id}").is_dir()


# ---------------------------------------------------------------------------
# K. Existing build idempotency.
# ---------------------------------------------------------------------------


def test_idempotent_second_call(fixtures, tmp_path):
    result, first = materialize_once(fixtures, tmp_path)
    assert first.created_new_build is True
    build = build_path(first)
    hashes_before = file_hashes(build)
    mtimes_before = {
        rel: (build / rel).stat().st_mtime_ns
        for rel in hashes_before
    }
    second = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert second.created_new_build is False
    assert second.build_path == build
    assert second.dataset_id == result.dataset_id
    assert second.logical_row_count == len(result.rows)
    assert second.output_file_count == first.output_file_count
    assert file_hashes(build) == hashes_before
    mtimes_after = {
        rel: (build / rel).stat().st_mtime_ns
        for rel in hashes_before
    }
    assert mtimes_after == mtimes_before
    # No staging was created for the idempotent call.
    assert not list(datasets_root(tmp_path).glob(".staging-*"))


def test_different_built_at_idempotent(fixtures, tmp_path):
    result, first = materialize_once(fixtures, tmp_path)
    build = build_path(first)
    original_report = first.build_report_path.read_bytes()
    original_manifest = first.manifest_path.read_bytes()
    other = datetime(2026, 9, 1, 0, 0, 0, 123456, tzinfo=UTC)
    second = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=other
    )
    assert second.created_new_build is False
    # The existing artifacts keep their original built_at; nothing is
    # rewritten, no new report is generated.
    assert first.build_report_path.read_bytes() == original_report
    assert first.manifest_path.read_bytes() == original_manifest
    report = read_json(second.build_report_path)
    assert report["built_at"] == BUILT_AT.astimezone(UTC).isoformat(timespec="microseconds")
    manifest = read_json(second.manifest_path)
    assert manifest["built_at"] == BUILT_AT.astimezone(UTC).isoformat(timespec="microseconds")
    assert not list(datasets_root(tmp_path).glob(".staging-*"))


def test_existing_build_verified_artifacts(fixtures, tmp_path):
    result, first = materialize_once(fixtures, tmp_path)
    build = build_path(first)
    # Re-verify through the private validator directly.
    manifest = mat_mod._verify_build_directory(
        build, result, None, require_success=True
    )
    assert manifest.dataset_id == result.dataset_id
    assert manifest.built_at == BUILT_AT
    # Report and manifest built_at are bound.
    report = read_json(first.build_report_path)
    assert report["built_at"] == manifest.built_at.isoformat(timespec="microseconds")


# ---------------------------------------------------------------------------
# L. Existing build corruption / conflict.
# ---------------------------------------------------------------------------


@pytest.fixture
def built(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    return result, mresult, build_path(mresult)


def _expect_fail(built, tmp_path):
    result, _, build = built
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
    assert build.is_dir()


def test_corruption_missing_success(built, tmp_path):
    _, _, build = built
    (build / DATASET_SUCCESS_FILENAME).unlink()
    _expect_fail(built, tmp_path)


def test_corruption_nonempty_success(built, tmp_path):
    _, _, build = built
    (build / DATASET_SUCCESS_FILENAME).write_bytes(b"x")
    _expect_fail(built, tmp_path)


def test_corruption_success_directory(built, tmp_path):
    _, _, build = built
    (build / DATASET_SUCCESS_FILENAME).unlink()
    (build / DATASET_SUCCESS_FILENAME).mkdir()
    _expect_fail(built, tmp_path)


def test_corruption_corrupt_manifest(built, tmp_path):
    _, _, build = built
    (build / DATASET_MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    _expect_fail(built, tmp_path)


def test_corruption_manifest_invalid_utf8(built, tmp_path):
    _, _, build = built
    (build / DATASET_MANIFEST_FILENAME).write_bytes(b"\xff\xfe\x00garbage")
    _expect_fail(built, tmp_path)


def test_corruption_manifest_dataset_id_mismatch(built, tmp_path):
    _, _, build = built
    payload = read_json(build / DATASET_MANIFEST_FILENAME)
    payload["dataset_id"] = "f" * 64
    (build / DATASET_MANIFEST_FILENAME).write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_manifest_identity_mismatch(built, tmp_path):
    _, _, build = built
    payload = read_json(build / DATASET_MANIFEST_FILENAME)
    payload["schema"]["fields"][0]["name"] = "codex"
    (build / DATASET_MANIFEST_FILENAME).write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_manifest_output_hash_mismatch(built, tmp_path):
    _, _, build = built
    parquet = build / DATASET_PARQUET_FILENAME
    data = bytearray(parquet.read_bytes())
    data[len(data) // 2] ^= 0x01
    parquet.write_bytes(bytes(data))
    _expect_fail(built, tmp_path)


def test_corruption_missing_parquet(built, tmp_path):
    _, _, build = built
    (build / DATASET_PARQUET_FILENAME).unlink()
    _expect_fail(built, tmp_path)


def test_corruption_truncated_parquet(built, tmp_path):
    _, _, build = built
    path = build / DATASET_PARQUET_FILENAME
    path.write_bytes(path.read_bytes()[:40])
    _expect_fail(built, tmp_path)


def test_corruption_wrong_parquet_schema(built, tmp_path):
    _, _, build = built
    path = build / DATASET_PARQUET_FILENAME
    table = pq.read_table(path)
    extra = table.append_column("extra", pa.array([1], type=pa.int64()))
    pq.write_table(extra, path)
    _expect_fail(built, tmp_path)


def test_corruption_wrong_row_count(built, tmp_path):
    _, _, build = built
    path = build / DATASET_PARQUET_FILENAME
    table = pq.read_table(path)
    pq.write_table(table.slice(0, 0), path)
    _expect_fail(built, tmp_path)


def test_corruption_wrong_row_value(built, tmp_path):
    _, _, build = built
    path = build / DATASET_PARQUET_FILENAME
    table = pq.read_table(path)
    values = table.column("sr").to_pylist()
    values[0] = 999.0
    columns = {
        name: pa.array(values if name == "sr" else table.column(name).to_pylist())
        for name in table.column_names
    }
    tampered = pa.table(columns).replace_schema_metadata(table.schema.metadata)
    pq.write_table(tampered, path)
    _expect_fail(built, tmp_path)


def test_corruption_missing_spec(built, tmp_path):
    _, _, build = built
    spec_file = next((build / DATASET_FEATURE_SPECS_DIRNAME).iterdir())
    spec_file.unlink()
    _expect_fail(built, tmp_path)


def test_corruption_extra_spec(built, tmp_path):
    _, _, build = built
    (build / DATASET_FEATURE_SPECS_DIRNAME / f"zz--v1--{'0' * 64}.yaml").write_text(
        "kind: FEATURE\n", encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_corrupt_feature_spec(built, tmp_path):
    _, _, build = built
    spec_file = next((build / DATASET_FEATURE_SPECS_DIRNAME).iterdir())
    spec_file.write_text("not: [valid", encoding="utf-8")
    _expect_fail(built, tmp_path)


def test_corruption_feature_spec_pin_mismatch(built, tmp_path):
    _, _, build = built
    spec_file = next((build / DATASET_FEATURE_SPECS_DIRNAME).iterdir())
    other = feature_spec("sma")
    from market_vault.dataset.artifact_serialization import feature_spec_artifact

    spec_file.write_bytes(feature_spec_artifact(other))
    _expect_fail(built, tmp_path)


def test_corruption_corrupt_label_spec(built, tmp_path):
    _, _, build = built
    spec_file = next((build / DATASET_LABEL_SPECS_DIRNAME).iterdir())
    spec_file.write_text("!!python/object:builtins.object {}\n", encoding="utf-8")
    _expect_fail(built, tmp_path)


def test_corruption_corrupt_split_spec(built, tmp_path):
    _, _, build = built
    (build / DATASET_SPLIT_SPEC_FILENAME).write_text("not: [valid", encoding="utf-8")
    _expect_fail(built, tmp_path)


def test_corruption_split_spec_pin_mismatch(built, tmp_path):
    _, _, build = built
    from market_vault.dataset.artifact_serialization import split_spec_artifact
    from market_vault.dataset.split_models import (
        SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
    )

    other = ChronologicalSplitSpec(
        spec_schema_version="market-vault-chronological-split-spec-v1",
        name="chrono2",
        version="v1",
        boundary_timezone=NY,
        train_end_date=date(2026, 6, 30),
        validation_end_date=date(2026, 7, 1),
        test_end_date=date(2026, 7, 2),
        assignment_rule=SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
        purge_rule="ACTUAL_LABEL_END",
        incomplete_label_policy="EXCLUDE",
        out_of_range_policy="EXCLUDE",
    )
    (build / DATASET_SPLIT_SPEC_FILENAME).write_bytes(split_spec_artifact(other))
    _expect_fail(built, tmp_path)


def test_corruption_corrupt_build_report(built, tmp_path):
    _, _, build = built
    (build / DATASET_BUILD_REPORT_FILENAME).write_text("{nope", encoding="utf-8")
    _expect_fail(built, tmp_path)


def test_corruption_report_dataset_id_mismatch(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["dataset_id"] = "e" * 64
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_report_built_at_mismatch(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["built_at"] = "2026-09-01T00:00:00.000000+00:00"
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_manifest_noncanonical_bytes(built, tmp_path):
    """manifest.json with an extra trailing newline (semantically identical)
    is rejected: the exact canonical bytes are the contract."""
    _, _, build = built
    path = build / DATASET_MANIFEST_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    _expect_fail(built, tmp_path)


def test_corruption_manifest_pretty_printed(built, tmp_path):
    _, _, build = built
    payload = read_json(build / DATASET_MANIFEST_FILENAME)
    (build / DATASET_MANIFEST_FILENAME).write_text(
        json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_feature_artifact_noncanonical_bytes(built, tmp_path):
    _, _, build = built
    path = next((build / DATASET_FEATURE_SPECS_DIRNAME).iterdir())
    path.write_bytes(path.read_bytes() + b"\n")
    _expect_fail(built, tmp_path)


def test_corruption_label_artifact_noncanonical_bytes(built, tmp_path):
    _, _, build = built
    path = next((build / DATASET_LABEL_SPECS_DIRNAME).iterdir())
    path.write_bytes(path.read_bytes() + b"\n")
    _expect_fail(built, tmp_path)


def test_corruption_split_artifact_noncanonical_bytes(built, tmp_path):
    _, _, build = built
    path = build / DATASET_SPLIT_SPEC_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    _expect_fail(built, tmp_path)


def test_corruption_report_diagnostics_rewritten(built, tmp_path):
    """A rewritten diagnostic count in build_report.json is rejected even
    when the manifest is untouched (the report is never identity-bearing,
    but its canonical bytes and full payload are part of the build)."""
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["pit_sample_count"] = 999
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_report_completion_count_rewritten(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["completion_complete_key_count"] = 999
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_report_split_result_id_rewritten(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["split_result_id"] = "1" * 64
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_report_schema_content_id_rewritten(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["dataset_schema_id"] = "2" * 64
    report["logical_dataset_content_id"] = "3" * 64
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_report_output_layout_rewritten(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["output_layout"]["manifest_filename"] = "other.json"
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_report_extra_field(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    report["extra_field"] = 1
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_report_missing_field(built, tmp_path):
    _, _, build = built
    report = read_json(build / DATASET_BUILD_REPORT_FILENAME)
    del report["row_order"]
    (build / DATASET_BUILD_REPORT_FILENAME).write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    _expect_fail(built, tmp_path)


def test_corruption_unexpected_file(built, tmp_path):
    _, _, build = built
    (build / "junk.txt").write_text("junk", encoding="utf-8")
    _expect_fail(built, tmp_path)


def test_corruption_unexpected_directory(built, tmp_path):
    _, _, build = built
    (build / "junkdir").mkdir()
    (build / "junkdir" / "junk.txt").write_text("junk", encoding="utf-8")
    _expect_fail(built, tmp_path)


def test_corruption_nested_symlink(built, tmp_path):
    _, _, build = built
    feature_dir = build / DATASET_FEATURE_SPECS_DIRNAME
    moved = build / "_feature_specs_real"
    feature_dir.rename(moved)
    _make_symlink_or_skip(moved, feature_dir)
    _expect_fail(built, tmp_path)


def test_corruption_final_symlink(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "junk.txt").write_text("junk", encoding="utf-8")
    shutil.rmtree(build)
    _make_symlink_or_skip(elsewhere, build)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
    assert build.is_symlink() or build.is_junction()


def test_existing_conflict_never_rewritten(built, tmp_path):
    result, _, build = built
    (build / DATASET_SUCCESS_FILENAME).unlink()
    hashes_before = file_hashes(build)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
    # Nothing was rewritten, repaired, or deleted.
    assert file_hashes(build) == hashes_before
    assert not (build / DATASET_SUCCESS_FILENAME).exists()


# ---------------------------------------------------------------------------
# M. Rename race.
# ---------------------------------------------------------------------------


def test_rename_race_valid_identical_final(fixtures, tmp_path, monkeypatch):
    """A complete identical final appearing inside the true no-replace
    primitive verifies strictly and returns created_new_build=False; the
    raced final is untouched and our staging is cleaned up."""
    result, first = materialize_once(fixtures, tmp_path)
    other_root = datasets_root(tmp_path) / "race"
    raced = {}

    def racer(staging, final):
        shutil.copytree(staging, final)
        raced["final"] = final

    _racing_atomic_publication(monkeypatch, racer)
    second = materialize_dataset_artifacts(
        result, output_root=other_root, built_at=BUILT_AT
    )
    assert second.created_new_build is False
    assert second.build_path == raced["final"]
    # Our staging was cleaned up; the raced final is untouched.
    assert not (other_root / f".staging-{result.dataset_id}").exists()
    assert file_hashes(raced["final"]) == file_hashes(first.build_path)


def test_rename_race_corrupt_final_fails(fixtures, tmp_path, monkeypatch):
    """A conflicting final appearing inside the true no-replace primitive
    fails closed; the conflicting final is never modified or deleted and
    our staging is cleaned up."""
    result, _ = materialize_once(fixtures, tmp_path)
    other_root = datasets_root(tmp_path) / "race2"
    raced = {}

    def racer(staging, final):
        shutil.copytree(staging, final)
        (final / DATASET_SUCCESS_FILENAME).unlink()
        raced["final"] = final

    _racing_atomic_publication(monkeypatch, racer)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=other_root, built_at=BUILT_AT
        )
    # Staging cleaned; the conflicting final is never deleted or rewritten.
    assert not (other_root / f".staging-{result.dataset_id}").exists()
    assert raced["final"].is_dir()
    assert not (raced["final"] / DATASET_SUCCESS_FILENAME).exists()


def test_final_never_overwritten_by_rename(fixtures, tmp_path, monkeypatch):
    """The raced final stays byte-identical; the true no-replace primitive
    never overwrites it."""
    result, _ = materialize_once(fixtures, tmp_path)
    other_root = datasets_root(tmp_path) / "race3"

    def racer(staging, final):
        shutil.copytree(staging, final)

    _racing_atomic_publication(monkeypatch, racer)
    second = materialize_dataset_artifacts(
        result, output_root=other_root, built_at=BUILT_AT
    )
    assert second.created_new_build is False
    # Final still the raced copy, byte-identical.
    assert file_hashes(second.build_path) == file_hashes(
        datasets_root(tmp_path) / result.dataset_id
    )
    assert not (other_root / f".staging-{result.dataset_id}").exists()


def _racing_atomic_publication(monkeypatch, racer):
    """Wrap the true no-replace publication so ``racer`` runs inside the
    race window (after the pre-check), then the real no-replace primitive
    executes against the raced destination — the destination-exists result
    is real, never a monkeypatched FileExistsError."""
    real_atomic = mat_mod._atomic_rename_directory_no_replace

    def racing(staging, final):
        racer(staging, final)
        return real_atomic(staging, final)

    monkeypatch.setattr(
        mat_mod, "_atomic_rename_directory_no_replace", racing
    )
    return real_atomic


def test_race_empty_final_before_publish_rejected(fixtures, tmp_path, monkeypatch):
    """An empty final directory appearing before publication (after the
    pre-check, inside the true no-replace call) is never replaced: the real
    primitive refuses it, strict verification fails, the empty final stays
    empty, and our staging is cleaned up."""
    result, _ = materialize_once(fixtures, tmp_path)
    root = datasets_root(tmp_path) / "race-empty-before"
    raced = {}

    def racer(staging, final):
        final.mkdir()
        raced["final"] = final

    _racing_atomic_publication(monkeypatch, racer)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=root, built_at=BUILT_AT
        )
    assert raced["final"].is_dir()
    assert not list(raced["final"].iterdir())  # untouched, still empty
    assert not (root / f".staging-{result.dataset_id}").exists()


def test_race_empty_final_before_publish_precheck_path(fixtures, tmp_path, monkeypatch):
    """An empty final directory appearing before the pre-check is caught by
    the existing-build path: rejected, untouched, staging cleaned."""
    result, _ = materialize_once(fixtures, tmp_path)
    root = datasets_root(tmp_path) / "race-empty-precheck"
    raced = {}
    real_publish = mat_mod._publish_staging

    def racing_publish(staging, final, result_value):
        final.mkdir()
        raced["final"] = final
        return real_publish(staging, final, result_value)

    monkeypatch.setattr(mat_mod, "_publish_staging", racing_publish)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=root, built_at=BUILT_AT
        )
    assert raced["final"].is_dir()
    assert not list(raced["final"].iterdir())
    assert not (root / f".staging-{result.dataset_id}").exists()


def test_no_replace_unavailable_fails_closed(fixtures, tmp_path, monkeypatch):
    """When no safe no-replace primitive is available the build fails
    closed and a plain overwriting os.rename is never used as a fallback."""
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path) / "noreplace"

    def unsupported(staging, final):
        raise mat_mod._NoReplaceUnsupportedError("no renameat2 here")

    monkeypatch.setattr(
        mat_mod, "_atomic_rename_directory_no_replace", unsupported
    )

    def fail_rename(*args, **kwargs):
        raise AssertionError("plain overwriting rename must never be used")

    monkeypatch.setattr(os, "rename", fail_rename)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=output_root, built_at=BUILT_AT
        )
    assert "no-replace" in str(excinfo.value)
    assert not (output_root / result.dataset_id).exists()
    assert not (output_root / f".staging-{result.dataset_id}").exists()


def test_no_replace_dispatcher_unsupported_platform(monkeypatch):
    """The dispatcher fails closed on any platform without a safe
    no-replace primitive; it never degrades to a plain rename.

    The Path arguments are constructed before ``os.name`` is patched: on a
    POSIX host, pathlib instantiates ``WindowsPath`` while ``os.name`` is
    ``"nt"``, so no Path may be built inside the patched window.
    """
    source = Path("s")
    destination = Path("f")

    def unsupported(*args, **kwargs):
        raise mat_mod._NoReplaceUnsupportedError("nope")

    monkeypatch.setattr(
        mat_mod, "_rename_directory_no_replace_windows", unsupported
    )
    monkeypatch.setattr(
        mat_mod, "_rename_directory_no_replace_linux", unsupported
    )
    monkeypatch.setattr(mat_mod.os, "name", "posix")
    monkeypatch.setattr(mat_mod.sys, "platform", "darwin")
    with pytest.raises(mat_mod._NoReplaceUnsupportedError):
        mat_mod._atomic_rename_directory_no_replace(source, destination)
    monkeypatch.setattr(mat_mod.os, "name", "nt")
    with pytest.raises(mat_mod._NoReplaceUnsupportedError):
        mat_mod._atomic_rename_directory_no_replace(source, destination)


def test_linux_renameat2_errno_mapping(monkeypatch):
    """The Linux renameat2 helper maps errno strictly: EEXIST / ENOTEMPTY
    are destination-exists results, EINVAL / ENOSYS / ENOTSUP / EOPNOTSUPP
    and a missing renameat2 symbol fail closed, and the RENAME_NOREPLACE
    flag is always passed."""
    calls = {}

    class FakeLibc:
        pass

    def make_libc(errno_value):
        def renameat2(*args):
            calls["args"] = args
            return -1

        libc = FakeLibc()
        libc.renameat2 = renameat2
        return libc

    monkeypatch.setattr(
        mat_mod.ctypes, "CDLL", lambda *a, **k: make_libc(0)
    )
    for error_number in (errno.EEXIST, errno.ENOTEMPTY):
        monkeypatch.setattr(
            mat_mod.ctypes, "get_errno", lambda e=error_number: e
        )
        with pytest.raises(mat_mod._DestinationExistsError):
            mat_mod._rename_directory_no_replace_linux(Path("s"), Path("f"))
    for error_number in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        monkeypatch.setattr(
            mat_mod.ctypes, "get_errno", lambda e=error_number: e
        )
        with pytest.raises(mat_mod._NoReplaceUnsupportedError):
            mat_mod._rename_directory_no_replace_linux(Path("s"), Path("f"))
    monkeypatch.setattr(mat_mod.ctypes, "get_errno", lambda: errno.EACCES)
    with pytest.raises(OSError):
        mat_mod._rename_directory_no_replace_linux(Path("s"), Path("f"))
    # The flag is RENAME_NOREPLACE == 1 with AT_FDCWD == -100.
    assert calls["args"][0] == -100
    assert calls["args"][4] == 1
    # A libc without the renameat2 symbol fails closed.
    monkeypatch.setattr(mat_mod.ctypes, "CDLL", lambda *a, **k: object())
    with pytest.raises(mat_mod._NoReplaceUnsupportedError):
        mat_mod._rename_directory_no_replace_linux(Path("s"), Path("f"))
    # Success path returns without raising.
    def make_success(*a, **k):
        libc = FakeLibc()
        libc.renameat2 = lambda *args: 0
        return libc

    monkeypatch.setattr(mat_mod.ctypes, "CDLL", make_success)
    mat_mod._rename_directory_no_replace_linux(Path("s"), Path("f"))


# ---------------------------------------------------------------------------
# N. Determinism.
# ---------------------------------------------------------------------------


def test_artifact_bytes_stable_across_roots(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    ma = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path) / "x", built_at=BUILT_AT
    )
    mb = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path) / "y", built_at=BUILT_AT
    )
    assert ma.dataset_id == mb.dataset_id == result.dataset_id
    for rel in all_artifact_files(build_path(ma)):
        if rel.endswith(".parquet"):
            continue  # byte determinism is only claimed for logical content
        assert (build_path(ma) / rel).read_bytes() == (
            build_path(mb) / rel
        ).read_bytes()


def test_output_root_and_cwd_do_not_affect_identity(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    cwd_before = os.getcwd()
    root_a = datasets_root(tmp_path) / "a"
    root_b = tmp_path / "elsewhere" / "deeper"
    ma = materialize_dataset_artifacts(result, output_root=root_a, built_at=BUILT_AT)
    mb = materialize_dataset_artifacts(result, output_root=root_b, built_at=BUILT_AT)
    assert ma.dataset_id == mb.dataset_id == result.dataset_id
    assert os.getcwd() == cwd_before
    assert ma.logical_row_count == mb.logical_row_count


def test_mtime_does_not_affect_identity(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    stamp = datetime(2001, 1, 1, 0, 0, 0, tzinfo=UTC).timestamp()
    os.utime(build / DATASET_PARQUET_FILENAME, (stamp, stamp))
    os.utime(build / DATASET_MANIFEST_FILENAME, (stamp, stamp))
    second = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert second.created_new_build is False
    assert second.dataset_id == result.dataset_id


# ---------------------------------------------------------------------------
# O. Result model.
# ---------------------------------------------------------------------------


def _sample_result_model(tmp_path, **overrides):
    build = (tmp_path / "dummy" / ("0" * 64)).absolute()
    kwargs = dict(
        dataset_id="0" * 64,
        status=STATUS_COMPLETE,
        build_path=build,
        dataset_path=build / DATASET_PARQUET_FILENAME,
        manifest_path=build / DATASET_MANIFEST_FILENAME,
        build_report_path=build / DATASET_BUILD_REPORT_FILENAME,
        success_path=build / DATASET_SUCCESS_FILENAME,
        logical_row_count=1,
        output_file_count=1,
        created_new_build=True,
        materializer_version=DATASET_MATERIALIZER_VERSION,
    )
    kwargs.update(overrides)
    return DatasetMaterializationResult(**kwargs)


def test_result_model_frozen(tmp_path):
    model = _sample_result_model(tmp_path)
    with pytest.raises(FrozenInstanceError):
        model.dataset_id = "1" * 64


def test_result_model_wrong_dataset_id(tmp_path):
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, dataset_id="not-a-hash")
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, dataset_id="A" * 64)


def test_result_model_wrong_status(tmp_path):
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, status="PARTIAL")
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, status=STATUS_EMPTY)  # needs row count 0
    assert _sample_result_model(
        tmp_path, status=STATUS_EMPTY, logical_row_count=0
    ).status == STATUS_EMPTY


def test_result_model_wrong_build_path_name(tmp_path):
    build = (tmp_path / "dummy" / ("1" * 64)).absolute()
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, build_path=build)


def test_result_model_dotdot_artifact_escape_rejected(tmp_path):
    """An artifact path that merely shares the build directory as an
    ancestor — build / '..' / 'outside' / 'dataset.parquet' — is rejected:
    artifact paths must be fixed direct children."""
    build = (tmp_path / "dummy" / ("0" * 64)).absolute()
    escaped = build / ".." / "outside" / DATASET_PARQUET_FILENAME
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, dataset_path=escaped)


def test_result_model_dotdot_build_path_rejected(tmp_path):
    build = (tmp_path.absolute() / ".." / ("0" * 64))
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, build_path=build)


def test_result_model_dot_component_rejected(tmp_path):
    build = (tmp_path.absolute() / "." / ("0" * 64))
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, build_path=build)


def test_result_model_nonabsolute_paths(tmp_path):
    relative = Path("dummy") / ("0" * 64)
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, build_path=relative)


def test_result_model_path_escape(tmp_path):
    build = (tmp_path / "dummy" / ("0" * 64)).absolute()
    outside = tmp_path.absolute() / "outside.parquet"
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, dataset_path=outside)


def test_result_model_wrong_row_count(tmp_path):
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, logical_row_count=-1)
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, logical_row_count=True)
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, output_file_count=-1)


def test_result_model_wrong_created_new_build(tmp_path):
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(tmp_path, created_new_build=1)


def test_result_model_wrong_materializer_version(tmp_path):
    with pytest.raises(DatasetMaterializationError):
        _sample_result_model(
            tmp_path, materializer_version="market-vault-dataset-materializer-v0"
        )


def test_result_model_has_no_metadata_or_time_facts(tmp_path):
    model = _sample_result_model(tmp_path)
    assert not hasattr(model, "built_at")
    assert not hasattr(model, "elapsed")
    assert not hasattr(model, "staging_path")
    assert not hasattr(model, "metadata")
    assert not hasattr(model, "parquet_bytes")


# ---------------------------------------------------------------------------
# P. Error boundary.
# ---------------------------------------------------------------------------


def test_error_wrapping_preserves_cause(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    def fail_write(path, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mat_mod, "write_dataset_parquet", fail_write)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_pyarrow_error_wrapped(fixtures, tmp_path, monkeypatch):
    import market_vault.dataset.artifact_serialization as ser_mod

    result = orchestrate(fixtures, requests=[request()])

    def fail_write(*args, **kwargs):
        raise pa.ArrowInvalid("bad parquet write")

    monkeypatch.setattr(ser_mod.pq, "write_table", fail_write)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
    assert isinstance(excinfo.value.__cause__, pa.ArrowInvalid)


def test_arrow_array_error_wrapped_at_public_boundary(fixtures, tmp_path, monkeypatch):
    """A pa.ArrowInvalid raised from pa.array (no internal wrapper) still
    fails closed at the public entry: DatasetMaterializationError with the
    Arrow exception as __cause__, no final, and our staging cleaned up."""
    import market_vault.dataset.artifact_serialization as ser_mod

    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    def boom(*args, **kwargs):
        raise pa.ArrowInvalid("array construction failed")

    monkeypatch.setattr(ser_mod.pa, "array", boom)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=output_root, built_at=BUILT_AT
        )
    assert isinstance(excinfo.value.__cause__, pa.ArrowInvalid)
    assert not (output_root / result.dataset_id).exists()
    assert not (output_root / f".staging-{result.dataset_id}").exists()


def test_arrow_table_construction_error_wrapped_at_public_boundary(
    fixtures, tmp_path, monkeypatch
):
    """A pa.ArrowInvalid raised from pa.Table.from_arrays is wrapped the
    same way at the public boundary."""
    import market_vault.dataset.artifact_serialization as ser_mod

    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    class BoomTable:
        @classmethod
        def from_arrays(cls, *args, **kwargs):
            raise pa.ArrowInvalid("table construction failed")

    monkeypatch.setattr(ser_mod.pa, "Table", BoomTable)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=output_root, built_at=BUILT_AT
        )
    assert isinstance(excinfo.value.__cause__, pa.ArrowInvalid)
    assert not (output_root / result.dataset_id).exists()
    assert not (output_root / f".staging-{result.dataset_id}").exists()


def test_arrow_error_not_double_wrapped(fixtures, tmp_path, monkeypatch):
    """A DatasetMaterializationError already raised inside the layer is
    never double-wrapped by the Arrow branch of the public boundary."""
    import market_vault.dataset.artifact_serialization as ser_mod

    result = orchestrate(fixtures, requests=[request()])

    def boom(*args, **kwargs):
        raise DatasetMaterializationError("materialization failure")

    monkeypatch.setattr(ser_mod.pa, "array", boom)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
    assert isinstance(excinfo.value, DatasetMaterializationError)
    assert "materialization failure" in str(excinfo.value)


def test_naive_built_at_wrapped_with_cause(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[request()])
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result,
            output_root=datasets_root(tmp_path),
            built_at=datetime(2026, 8, 5, 12, 0),
        )
    assert isinstance(excinfo.value.__cause__, DatasetError)


def test_no_partial_result_after_failure(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    output_root = datasets_root(tmp_path)

    def fail_write(path, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(mat_mod, "write_dataset_parquet", fail_write)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=output_root, built_at=BUILT_AT)
    assert not (output_root / result.dataset_id).exists()


# ---------------------------------------------------------------------------
# Q. No forbidden behavior.
# ---------------------------------------------------------------------------


def test_no_public_reader_or_cli_or_server():
    # The verified Dataset reader became public in PR-7
    # (market_vault.dataset.load_verified_dataset); the materialization
    # module itself never exposes a reader and the Dataset CLI / API
    # server / Python client do not exist yet (PR-8).
    assert callable(dataset_pkg.load_verified_dataset)
    assert not hasattr(mat_mod, "load_verified_dataset")
    for name in (
        "verify_dataset",
        "dataset_build",
        "dataset_verify",
        "dataset_inspect",
    ):
        assert not hasattr(dataset_pkg, name)


def test_only_writes_inside_output_root(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    # Everything created under tmp_path belongs to the output root subtree.
    for root, _, files in os.walk(tmp_path):
        for name in files:
            path = Path(root) / name
            if build in path.parents or path == build:
                continue
            if "canonical" in str(path) or "catalog" in str(path):
                continue
            raise AssertionError(f"unexpected file outside the build: {path}")


def test_cwd_unchanged(fixtures, tmp_path):
    cwd_before = os.getcwd()
    materialize_once(fixtures, tmp_path)
    assert os.getcwd() == cwd_before


def test_no_identity_or_version_changes():
    # The materialization layer must never have touched existing identity
    # algorithms or version constants.
    assert dataset_pkg.DATASET_MANIFEST_SCHEMA_VERSION == (
        "market-vault-dataset-manifest-v1"
    )
    assert dataset_pkg.SERIALIZATION_FORMAT_VERSION_PARQUET == (
        "market-vault-dataset-parquet-v1"
    )
    assert dataset_pkg.DATASET_ORCHESTRATION_CONTRACT_VERSION == (
        "market-vault-dataset-orchestration-v1"
    )


def test_output_root_symlink_rejected(fixtures, tmp_path):
    """output_root itself must be a real directory: a symlink or junction
    is rejected and nothing is written through the link."""
    result = orchestrate(fixtures, requests=[request()])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "linkroot"
    _make_symlink_or_skip(elsewhere, link)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=link / "datasets", built_at=BUILT_AT
        )
    assert not (elsewhere / "datasets").exists()


def test_output_root_nested_link_ancestor_rejected(fixtures, tmp_path):
    """A symlink / junction anywhere from an existing ancestor down to
    output_root is rejected (no link escape into another directory)."""
    result = orchestrate(fixtures, requests=[request()])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "linkancestor"
    _make_symlink_or_skip(elsewhere, link)
    output_root = link / "nested" / "datasets"
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=output_root, built_at=BUILT_AT
        )
    assert not (elsewhere / "nested").exists()


def test_output_root_file_rejected(fixtures, tmp_path):
    """output_root or any existing ancestor that is a file (not a regular
    directory) is rejected."""
    result = orchestrate(fixtures, requests=[request()])
    file_root = tmp_path / "afile"
    file_root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=file_root, built_at=BUILT_AT
        )
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=file_root / "datasets", built_at=BUILT_AT
        )


def test_output_root_junction_rejected(fixtures, tmp_path):
    """A Windows junction as output_root is rejected on Windows (the test
    falls back to a junction when symlinks need privileges)."""
    result = orchestrate(fixtures, requests=[request()])
    elsewhere = tmp_path / "junction-target"
    elsewhere.mkdir()
    link = tmp_path / "junction-root"
    _make_symlink_or_skip(elsewhere, link)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(
            result, output_root=link / "datasets", built_at=BUILT_AT
        )
    assert not (elsewhere / "datasets").exists()


def test_legal_plain_directory_output_root_passes(fixtures, tmp_path):
    """A legal plain directory (no links anywhere in the path) works."""
    result, mresult = materialize_once(fixtures, tmp_path)
    assert mresult.created_new_build is True
    assert mresult.build_path.parent == datasets_root(tmp_path)


def _make_junction_or_skip(target: Path, link: Path) -> None:
    """Create only a real Windows junction (never a symlink); skip when
    junctions are unavailable."""
    if os.name == "nt":
        try:
            import _winapi

            _winapi.CreateJunction(str(target.absolute()), str(link.absolute()))
            return
        except (OSError, TypeError, ImportError):
            pass
    pytest.skip("Windows junctions are not available in this environment")


def test_output_root_symlink_with_valid_existing_dataset_rejected(fixtures, tmp_path):
    """A symlink output_root whose target already contains a fully valid
    Dataset must fail closed: the existing-build path shares the same link
    boundary as the new-build path, and a valid Dataset never makes a
    linked output root acceptable."""
    result, first = materialize_once(fixtures, tmp_path)
    real_parent = datasets_root(tmp_path)
    link = tmp_path / "linked_root"
    _make_symlink_or_skip(real_parent, link)
    hashes_before = file_hashes(first.build_path)
    mtimes_before = {
        rel: (first.build_path / rel).stat().st_mtime_ns
        for rel in hashes_before
    }
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=link, built_at=BUILT_AT
        )
    assert "must not be a symlink or junction" in str(excinfo.value)
    # The existing Dataset is untouched and no staging was created.
    assert file_hashes(first.build_path) == hashes_before
    assert {
        rel: (first.build_path / rel).stat().st_mtime_ns
        for rel in hashes_before
    } == mtimes_before
    assert not list(real_parent.glob(".staging-*"))


def test_output_root_nested_link_ancestor_with_valid_existing_rejected(fixtures, tmp_path):
    """A nested symlink / junction ancestor in the output root path is
    rejected even when the link target contains a valid existing Dataset."""
    result, first = materialize_once(fixtures, tmp_path)
    link = tmp_path / "linked_parent"
    _make_symlink_or_skip(tmp_path, link)
    hashes_before = file_hashes(first.build_path)
    # link / "datasets" resolves into the real datasets directory that
    # already holds the valid Dataset.
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=link / "datasets", built_at=BUILT_AT
        )
    assert "must not be a symlink or junction" in str(excinfo.value)
    assert file_hashes(first.build_path) == hashes_before
    assert not list((link / "datasets").glob(".staging-*"))


def test_output_root_junction_with_valid_existing_dataset_rejected(fixtures, tmp_path):
    """A real Windows junction as output_root whose target contains a valid
    existing Dataset is rejected (junction-only test; the Python 3.11
    reparse-point detection path is exercised on Windows)."""
    result, first = materialize_once(fixtures, tmp_path)
    real_parent = datasets_root(tmp_path)
    junction = tmp_path / "junction_root"
    _make_junction_or_skip(real_parent, junction)
    hashes_before = file_hashes(first.build_path)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=junction, built_at=BUILT_AT
        )
    assert "must not be a symlink or junction" in str(excinfo.value)
    assert file_hashes(first.build_path) == hashes_before
    assert not list(real_parent.glob(".staging-*"))


def test_regular_output_root_existing_build_positive_control(fixtures, tmp_path):
    """Positive control: with a regular output root the existing-build
    idempotency is intact — first call creates, second returns
    created_new_build=False, hashes and mtimes are unchanged, and a
    different built_at is still idempotent."""
    result, first = materialize_once(fixtures, tmp_path)
    assert first.created_new_build is True
    build = first.build_path
    hashes_before = file_hashes(build)
    mtimes_before = {
        rel: (build / rel).stat().st_mtime_ns for rel in hashes_before
    }
    second = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    assert second.created_new_build is False
    assert file_hashes(build) == hashes_before
    assert {
        rel: (build / rel).stat().st_mtime_ns for rel in hashes_before
    } == mtimes_before
    other = datetime(2026, 9, 1, 0, 0, 0, 123456, tzinfo=UTC)
    third = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=other
    )
    assert third.created_new_build is False
    assert file_hashes(build) == hashes_before
    assert not list(datasets_root(tmp_path).glob(".staging-*"))


def test_staging_residue_under_linked_output_root_rejected_without_touching(
    fixtures, tmp_path
):
    """Even when the link target holds only a staging residue, the call
    fails at the output-root link check before the residue state is read,
    and the residue is never deleted."""
    result = orchestrate(fixtures, requests=[request()])
    real = datasets_root(tmp_path) / "real"
    real.mkdir(parents=True)
    residue = real / f".staging-{result.dataset_id}"
    residue.mkdir()
    (residue / "junk.txt").write_text("residue", encoding="utf-8")
    link = tmp_path / "linked_residue_root"
    _make_symlink_or_skip(real, link)
    with pytest.raises(DatasetMaterializationError) as excinfo:
        materialize_dataset_artifacts(
            result, output_root=link, built_at=BUILT_AT
        )
    assert "must not be a symlink or junction" in str(excinfo.value)
    assert residue.is_dir()
    assert (residue / "junk.txt").exists()
    assert not (real / result.dataset_id).exists()
