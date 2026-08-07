"""Offline deterministic tests of the Dataset Catalog snapshot
materializer (v0.6.0 PR-6).

Covers the public API and version constants, the explicit input contract
(explicit ``output_root`` and timezone-aware ``built_at``, keyword-only,
no current time), the exact physical layout and schemas, the deterministic
catalog bytes (identical result -> byte-identical catalog.json; never the
output_root / snapshot path / built_at), the snapshot-ID behavior
(content identity vs physical identity: different output_root -> same
snapshot ID; different built_at / relocated Dataset -> different snapshot
ID with the same content ID), write-return validation, staging cleanup on
documented and programming errors, staging residue rejection,
existing-snapshot idempotency (zero rewrite, zero mtime touch),
existing-snapshot corruption rejection, the concurrent-final race (verified
identical -> idempotent; corrupt -> fail closed without deleting the
final), no-replace publication unavailability, the EMPTY Catalog, the
COMPLETE + EMPTY end-to-end chain, and the no-side-effect boundary. All
Dataset builds are produced through the public chain; no network, no
OpenD, no current time, and no real market data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import market_vault.dataset.dataset_catalog_materialization as mat_mod
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
    DATASET_CATALOG_BUILDER_VERSION,
    DATASET_CATALOG_CATALOG_FILENAME,
    DATASET_CATALOG_MANIFEST_FILENAME,
    DATASET_CATALOG_MATERIALIZER_VERSION,
    DATASET_CATALOG_READER_CONTRACT_VERSION,
    DATASET_CATALOG_SNAPSHOT_ID_VERSION,
    DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION,
    DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION,
    DATASET_CATALOG_SUCCESS_FILENAME,
    DATASET_KIND_SUPERVISED,
    DATASET_MANIFEST_SCHEMA_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_SPEC_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
    SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
    SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    ChronologicalSplitSpec,
    CrossTradingDayPolicy,
    DatasetCatalogBuildError,
    DatasetCatalogBuildResult,
    DatasetCatalogMaterializationError,
    DatasetCatalogMaterializationResult,
    DatasetField,
    DatasetScope,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    build_dataset_catalog,
    dataset_catalog_content_id,
    dataset_orchestration_schema,
    load_verified_dataset,
    materialize_dataset_artifacts,
    materialize_dataset_catalog_snapshot,
    orchestrate_dataset_build,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"
BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
BUILT_AT_2 = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"

# ---------------------------------------------------------------------------
# Real verified-Dataset-build fixtures (public chain only).
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


def default_key() -> CanonicalRequestKey:
    return CanonicalRequestKey(
        interval="1m", requested_session="ALL", adjustment="NONE",
        source_schema_version="10.9",
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


def feature_spec(name: str = "sr") -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_SIMPLE,
        parameters=(SpecParameter("window_bars", 2),),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )


def label_spec(name: str = "fr") -> LabelSpec:
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
        observation_window=LabelObservationWindow("BARS", 1, 1),
        horizon=LabelHorizon("BARS", 2),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )


def chronological_spec() -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version=CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
        name="catalog_split",
        version="v1",
        boundary_timezone=NY,
        train_end_date=date(2026, 6, 30),
        validation_end_date=date(2026, 7, 1),
        test_end_date=date(2026, 7, 2),
        assignment_rule=SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
        purge_rule=SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
        incomplete_label_policy=SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
        out_of_range_policy=SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    )


def request() -> PITSampleRequest:
    return PITSampleRequest(
        code="US.MU",
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
        anchor_market_calendar_date=date(2026, 7, 1),
        feature_window_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
        feature_window_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_window_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_window_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
    )


def dataset_scope() -> DatasetScope:
    return DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )


def orchestrate(fixtures, *, requests):
    feature_specs = [feature_spec()]
    label_specs = [label_spec()]
    split_spec = chronological_spec()
    scope = dataset_scope()
    schema = dataset_orchestration_schema(
        feature_specs, label_specs, include_dataset_as_of=False
    )
    return orchestrate_dataset_build(
        builds=tuple(fixtures.builds),
        requests=tuple(requests),
        feature_specs=tuple(feature_specs),
        label_specs=tuple(label_specs),
        split_spec=split_spec,
        scope=scope,
        schema=schema,
        dataset_as_of=None,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )


def datasets_root(tmp_path) -> Path:
    return tmp_path / "datasets"


def materialize_once(fixtures, tmp_path, *, requests, built_at=BUILT_AT):
    result = orchestrate(fixtures, requests=requests)
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=built_at
    )
    return result, mresult


def read_verified(mresult):
    return load_verified_dataset(mresult.build_path)


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    root = tmp_path_factory.mktemp("mv_catalog_materialization")
    cfg = settings(root)
    calendar(cfg)

    def build(code, trade_date, run_id, time_keys, closes):
        write_snapshot(
            cfg, code=code, trade_date=trade_date, run_id=run_id,
            time_keys=time_keys, closes=closes,
        )
        return verified(
            materialize(cfg, symbols=[code], trade_dates=[trade_date])
        )

    a = build(
        "US.MU", date(2026, 7, 1), "run-a",
        minute_keys("2026-07-01 09:30:00", 6),
        [100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
    )
    f = build(
        "US.MU", date(2026, 7, 1), "run-f",
        minute_keys("2026-07-01 09:36:00", 6),
        [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
    )
    return SimpleNamespace(builds=[a, f])


@pytest.fixture(scope="module")
def complete_build(fixtures, tmp_path_factory):
    tmp = Path(tmp_path_factory.mktemp("mv_mat_complete"))
    result, mresult = materialize_once(fixtures, tmp, requests=[request()])
    assert result.status == STATUS_COMPLETE
    return read_verified(mresult)


@pytest.fixture(scope="module")
def empty_build(fixtures, tmp_path_factory):
    tmp = Path(tmp_path_factory.mktemp("mv_mat_empty"))
    result, mresult = materialize_once(fixtures, tmp, requests=[])
    assert result.status == STATUS_EMPTY
    return read_verified(mresult)


def build_catalog(*builds) -> DatasetCatalogBuildResult:
    return build_dataset_catalog(
        candidate_build_dirs=tuple(build.build_path for build in builds)
    )


def snapshot_root(tmp_path) -> Path:
    return tmp_path / "catalog-snapshots"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_snapshot(root: Path) -> set[str]:
    return {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
    }


def _file_mtimes(path: Path) -> dict[str, int]:
    return {
        item.name: item.stat().st_mtime_ns
        for item in path.iterdir()
    }


# ---------------------------------------------------------------------------
# A. Public API / input contract.
# ---------------------------------------------------------------------------


def test_version_constants_exact():
    assert DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION == (
        "market-vault-dataset-catalog-snapshot-v1"
    )
    assert DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION == (
        "market-vault-dataset-catalog-snapshot-manifest-v1"
    )
    assert DATASET_CATALOG_SNAPSHOT_ID_VERSION == (
        "market-vault-dataset-catalog-snapshot-id-v1"
    )
    assert DATASET_CATALOG_MATERIALIZER_VERSION == (
        "market-vault-dataset-catalog-materializer-v1"
    )
    assert DATASET_CATALOG_READER_CONTRACT_VERSION == (
        "market-vault-verified-dataset-catalog-reader-v1"
    )


def test_public_api_exports():
    import market_vault.dataset as dataset_pkg

    for name in (
        "materialize_dataset_catalog_snapshot",
        "DatasetCatalogMaterializationResult",
        "DatasetCatalogMaterializationError",
    ):
        assert name in dataset_pkg.__all__
        assert hasattr(dataset_pkg, name)


def test_input_contract(complete_build, tmp_path):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(
            result, output_root=root, built_at=None
        )
    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(
            result, output_root=root, built_at=datetime(2026, 8, 5, 12, 0)
        )  # naive
    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(
            "not-a-result", output_root=root, built_at=BUILT_AT
        )


def test_result_is_frozen(complete_build, tmp_path):
    result = build_catalog(complete_build)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    with pytest.raises(FrozenInstanceError):
        mresult.snapshot_id = "f" * 64
    with pytest.raises(FrozenInstanceError):
        mresult.snapshot_path = Path("/elsewhere")


def test_result_model_self_validates(complete_build, tmp_path):
    result = build_catalog(complete_build)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    with pytest.raises(DatasetCatalogMaterializationError):
        replace(mresult, created_new_snapshot="yes")
    with pytest.raises(DatasetCatalogMaterializationError):
        replace(mresult, dataset_count=-1)
    with pytest.raises(DatasetCatalogMaterializationError):
        replace(mresult, snapshot_id="ff" * 32)
    with pytest.raises(DatasetCatalogMaterializationError):
        replace(
            mresult,
            catalog_path=mresult.snapshot_path / "wrong.json",
        )


# ---------------------------------------------------------------------------
# B. Exact physical layout and schemas.
# ---------------------------------------------------------------------------


def test_exact_physical_layout(complete_build, tmp_path):
    result = build_catalog(complete_build)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    assert mresult.created_new_snapshot is True
    assert mresult.snapshot_path.name == mresult.snapshot_id
    assert len(mresult.snapshot_id) == 64
    assert mresult.snapshot_id == mresult.snapshot_id.lower()
    assert set(mresult.snapshot_path.iterdir()) == {
        mresult.catalog_path,
        mresult.manifest_path,
        mresult.success_path,
    }
    assert mresult.catalog_path.name == "catalog.json"
    assert mresult.manifest_path.name == "manifest.json"
    assert mresult.success_path.name == "_SUCCESS"
    assert mresult.catalog_content_id == result.catalog_content_id
    assert mresult.dataset_count == 1
    assert mresult.materializer_version == DATASET_CATALOG_MATERIALIZER_VERSION
    # No staging residue, no latest, no extra files anywhere.
    assert set(snapshot_root(tmp_path).iterdir()) == {mresult.snapshot_path}
    assert (mresult.success_path).read_bytes() == b""


def test_catalog_json_exact_schema(complete_build, tmp_path):
    result = build_catalog(complete_build)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    payload = read_json(mresult.catalog_path)
    assert set(payload) == {
        "snapshot_schema_version",
        "catalog_contract_version",
        "catalog_entry_schema_version",
        "catalog_content_id_version",
        "builder_version",
        "catalog_content_id",
        "dataset_count",
        "datasets",
    }
    assert payload["snapshot_schema_version"] == DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION
    assert payload["catalog_contract_version"] == (
        "market-vault-dataset-catalog-contract-v1"
    )
    assert payload["catalog_entry_schema_version"] == (
        "market-vault-dataset-catalog-entry-v1"
    )
    assert payload["catalog_content_id_version"] == (
        "market-vault-dataset-catalog-content-v1"
    )
    assert payload["builder_version"] == DATASET_CATALOG_BUILDER_VERSION
    assert payload["catalog_content_id"] == result.catalog_content_id
    assert payload["dataset_count"] == 1
    record = payload["datasets"][0]
    assert set(record) == {"content_id", "dataset_facts", "observed_metadata"}
    assert record["content_id"] == result.entries[0].content_id
    assert set(record["observed_metadata"]) == {"built_at", "build_path"}
    facts = record["dataset_facts"]
    assert set(facts) == {
        "dataset_id",
        "dataset_kind",
        "status",
        "logical_row_count",
        "dataset_schema_id",
        "logical_dataset_content_id",
        "dataset_as_of",
        "scope",
        "feature_spec_pins",
        "label_spec_pins",
        "split_spec_pin",
        "canonical_build_pins",
        "canonical_row_version_ids",
        "completion",
    }
    expected_facts = result.entries[0].dataset_facts
    assert facts["dataset_id"] == expected_facts.dataset_id
    assert facts["status"] == expected_facts.status
    assert facts["logical_row_count"] == expected_facts.logical_row_count
    assert facts["dataset_schema_id"] == expected_facts.dataset_schema_id
    assert facts["logical_dataset_content_id"] == (
        expected_facts.logical_dataset_content_id
    )
    assert facts["dataset_as_of"] is None
    assert facts["scope"]["symbols"] == list(expected_facts.scope.symbols)
    assert facts["scope"]["trade_dates"] == [
        d.isoformat() for d in expected_facts.scope.trade_dates
    ]
    assert facts["feature_spec_pins"][0]["kind"] == "FEATURE"
    assert facts["label_spec_pins"][0]["kind"] == "LABEL"
    assert facts["split_spec_pin"]["kind"] == "SPLIT"
    assert facts["canonical_build_pins"][0]["canonical_build_id"] == (
        expected_facts.canonical_build_pins[0].canonical_build_id
    )
    assert facts["canonical_row_version_ids"] == list(
        expected_facts.canonical_row_version_ids
    )
    assert facts["completion"]["entries"][0]["code"] == "US.MU"
    assert record["observed_metadata"]["build_path"].endswith(
        f"/{expected_facts.dataset_id}"
    )
    assert "\\" not in record["observed_metadata"]["build_path"]


def test_manifest_json_exact_schema(complete_build, tmp_path):
    result = build_catalog(complete_build)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    payload = read_json(mresult.manifest_path)
    assert set(payload) == {
        "manifest_schema_version",
        "snapshot_id_version",
        "materializer_version",
        "builder_version",
        "snapshot_id",
        "catalog_content_id",
        "built_at",
        "dataset_count",
        "catalog_file",
    }
    assert payload["manifest_schema_version"] == (
        DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION
    )
    assert payload["snapshot_id_version"] == DATASET_CATALOG_SNAPSHOT_ID_VERSION
    assert payload["materializer_version"] == DATASET_CATALOG_MATERIALIZER_VERSION
    assert payload["builder_version"] == DATASET_CATALOG_BUILDER_VERSION
    assert payload["snapshot_id"] == mresult.snapshot_id
    assert payload["catalog_content_id"] == result.catalog_content_id
    assert payload["built_at"] == BUILT_AT.astimezone(UTC).isoformat(
        timespec="microseconds"
    )
    assert payload["dataset_count"] == 1
    assert set(payload["catalog_file"]) == {
        "relative_path",
        "byte_size",
        "sha256",
    }
    catalog_bytes = mresult.catalog_path.read_bytes()
    assert payload["catalog_file"] == {
        "relative_path": "catalog.json",
        "byte_size": len(catalog_bytes),
        "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
    }


def test_success_file_is_exact_empty_regular_file(complete_build, tmp_path):
    result = build_catalog(complete_build)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    assert mresult.success_path.is_file()
    assert not mresult.success_path.is_symlink()
    assert mresult.success_path.read_bytes() == b""


# ---------------------------------------------------------------------------
# C. Determinism and identity boundaries.
# ---------------------------------------------------------------------------


def test_same_result_byte_identical_across_output_roots(complete_build, tmp_path):
    result = build_catalog(complete_build)
    root_a = snapshot_root(tmp_path) / "a"
    root_b = snapshot_root(tmp_path) / "b"
    first = materialize_dataset_catalog_snapshot(
        result, output_root=root_a, built_at=BUILT_AT
    )
    second = materialize_dataset_catalog_snapshot(
        result, output_root=root_b, built_at=BUILT_AT
    )
    assert first.catalog_path.read_bytes() == second.catalog_path.read_bytes()
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_path.name == second.snapshot_path.name


def test_built_at_changes_snapshot_id_not_content_id(complete_build, tmp_path):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    first = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    second = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT_2
    )
    assert first.catalog_content_id == second.catalog_content_id
    assert first.snapshot_id != second.snapshot_id
    assert first.catalog_path.read_bytes() == second.catalog_path.read_bytes()
    # Both snapshots coexist: no overwrite ever happened.
    assert set(root.iterdir()) == {first.snapshot_path, second.snapshot_path}


def test_relocated_dataset_changes_snapshot_id_not_content_id(
    complete_build, tmp_path
):
    """The section-30 regression: the same verified Dataset moved to
    another parent keeps its facts and the Catalog content identity, but
    the catalog.json observed path (and therefore the snapshot ID)
    changes."""
    other_parent = tmp_path / "other-parent"
    shutil.copytree(complete_build.build_path, other_parent / complete_build.dataset_id)
    original = build_catalog(complete_build)
    relocated = build_dataset_catalog(
        candidate_build_dirs=(other_parent / complete_build.dataset_id,)
    )
    assert relocated.catalog_content_id == original.catalog_content_id
    root = snapshot_root(tmp_path)
    first = materialize_dataset_catalog_snapshot(
        original, output_root=root, built_at=BUILT_AT
    )
    second = materialize_dataset_catalog_snapshot(
        relocated, output_root=root, built_at=BUILT_AT
    )
    assert first.catalog_path.read_bytes() != second.catalog_path.read_bytes()
    assert first.snapshot_id != second.snapshot_id
    assert first.catalog_content_id == second.catalog_content_id


def test_tampered_result_fails_closed(complete_build, tmp_path):
    """A tampered result cannot even be constructed (the builder model
    self-validates); the materializer additionally re-validates the
    carried result before writing anything."""
    result = build_catalog(complete_build)
    with pytest.raises(DatasetCatalogBuildError):
        replace(result, catalog_content_id="f" * 64)
    with pytest.raises(DatasetCatalogBuildError):
        replace(result, dataset_count=result.dataset_count + 1)
    # The materializer re-triggers the full self-validation: a result
    # whose __post_init__ is bypassed is rejected before any write.
    class _Sneaky(DatasetCatalogBuildResult):
        def __init__(self, *args, **kwargs):
            object.__setattr__(
                self, "entries", result.entries
            )
            object.__setattr__(
                self, "catalog_content_id", "f" * 64
            )
            object.__setattr__(self, "dataset_count", result.dataset_count)
            object.__setattr__(
                self, "builder_version", DATASET_CATALOG_BUILDER_VERSION
            )

    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(
            _Sneaky(), output_root=snapshot_root(tmp_path), built_at=BUILT_AT
        )


# ---------------------------------------------------------------------------
# D. Write-return validation and staging cleanup.
# ---------------------------------------------------------------------------


class _BadWriteHandle:
    """A handle whose write returns a wrong value (None / 0 / too long)."""

    def __init__(self, return_value):
        self._return_value = return_value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, data):
        return self._return_value

    def flush(self):
        pass


@pytest.mark.parametrize("bad_return", [None, 0, 5, True])
def test_write_return_validation_fails_closed(
    complete_build, tmp_path, monkeypatch, bad_return
):
    result = build_catalog(complete_build)
    monkeypatch.setattr(
        mat_mod.Path,
        "open",
        lambda path, mode, *args, **kwargs: _BadWriteHandle(bad_return),
    )
    with pytest.raises(
        DatasetCatalogMaterializationError, match="invalid write return"
    ):
        materialize_dataset_catalog_snapshot(
            result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
        )
    # The staging directory created by this call was cleaned up.
    assert not any(
        item.name.startswith(".staging-")
        for item in snapshot_root(tmp_path).iterdir()
    )


def test_staging_cleanup_on_business_error(complete_build, tmp_path, monkeypatch):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    monkeypatch.setattr(
        mat_mod,
        "_readback_exact",
        lambda path, expected, label: (_ for _ in ()).throw(
            DatasetCatalogMaterializationError("readback boom")
        ),
    )
    with pytest.raises(DatasetCatalogMaterializationError, match="readback boom"):
        materialize_dataset_catalog_snapshot(result, output_root=root, built_at=BUILT_AT)
    assert not any(item.name.startswith(".staging-") for item in root.iterdir())


def test_staging_cleanup_preserves_programming_error(
    complete_build, tmp_path, monkeypatch
):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    monkeypatch.setattr(
        mat_mod,
        "_readback_exact",
        lambda path, expected, label: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        materialize_dataset_catalog_snapshot(result, output_root=root, built_at=BUILT_AT)
    assert not any(item.name.startswith(".staging-") for item in root.iterdir())


def test_pre_existing_staging_residue_fails_closed(complete_build, tmp_path):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    root.mkdir()
    # The residue must sit at the exact fixed staging path of THIS
    # materialization (derived exactly like the materializer derives it).
    catalog_bytes = mat_mod.catalog_payload_bytes(result)
    from market_vault.dataset.dataset_catalog_snapshot_identity import (
        dataset_catalog_snapshot_id,
    )

    snapshot_id = dataset_catalog_snapshot_id(
        catalog_content_id=result.catalog_content_id,
        dataset_count=result.dataset_count,
        built_at=BUILT_AT,
        catalog_file_byte_size=len(catalog_bytes),
        catalog_file_sha256=hashlib.sha256(catalog_bytes).hexdigest(),
    )
    residue = root / f".staging-{snapshot_id}"
    residue.mkdir()
    with pytest.raises(DatasetCatalogMaterializationError, match="staging"):
        materialize_dataset_catalog_snapshot(result, output_root=root, built_at=BUILT_AT)
    # The residue is never deleted or adopted.
    assert residue.is_dir()
    assert not any(item.name != residue.name for item in root.iterdir())


# ---------------------------------------------------------------------------
# E. Existing-snapshot idempotency.
# ---------------------------------------------------------------------------


def test_existing_identical_snapshot_idempotent(complete_build, tmp_path):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    first = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    mtimes_before = _file_mtimes(first.snapshot_path)
    catalog_before = first.catalog_path.read_bytes()
    manifest_before = first.manifest_path.read_bytes()
    second = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    assert second.created_new_snapshot is False
    assert second.snapshot_id == first.snapshot_id
    assert second.snapshot_path == first.snapshot_path
    # Zero rewrite: bytes and mtimes are untouched.
    assert first.catalog_path.read_bytes() == catalog_before
    assert first.manifest_path.read_bytes() == manifest_before
    assert _file_mtimes(first.snapshot_path) == mtimes_before
    assert set(root.iterdir()) == {first.snapshot_path}


def test_existing_corrupt_catalog_fails_closed(complete_build, tmp_path):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    first = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    with first.catalog_path.open("ab") as handle:
        handle.write(b"junk")
    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(result, output_root=root, built_at=BUILT_AT)
    # The corrupt snapshot is never overwritten or repaired.
    assert first.catalog_path.read_bytes().endswith(b"junk")


def test_existing_missing_success_fails_closed(complete_build, tmp_path):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    first = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    (first.success_path).unlink()
    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(result, output_root=root, built_at=BUILT_AT)


def test_existing_manifest_snapshot_id_tamper_fails_closed(
    complete_build, tmp_path
):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    first = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    payload = read_json(first.manifest_path)
    payload["snapshot_id"] = "f" * 64
    first.manifest_path.write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(result, output_root=root, built_at=BUILT_AT)


# ---------------------------------------------------------------------------
# F. No-replace publication and the race.
# ---------------------------------------------------------------------------


def test_no_replace_primitive_unavailable_fails_closed(
    complete_build, tmp_path, monkeypatch
):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)

    def unavailable(staging, final):
        raise mat_mod._NoReplaceUnsupportedError("not supported")

    monkeypatch.setattr(mat_mod, "_atomic_rename_directory_no_replace", unavailable)
    with pytest.raises(DatasetCatalogMaterializationError, match="no-replace"):
        materialize_dataset_catalog_snapshot(result, output_root=root, built_at=BUILT_AT)
    assert not any(item.name.startswith(".staging-") for item in root.iterdir())
    assert not any(item.name != ".staging" for item in root.iterdir())


def test_concurrent_identical_final_returns_idempotent(
    complete_build, tmp_path, monkeypatch
):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    real_verify_success = mat_mod._verify_success
    state = {"final": None}

    # The final snapshot appears concurrently while _SUCCESS is being
    # verified inside staging (after the existing-final pre-check).
    def raced(success_path):
        staging = success_path.parent
        if state["final"] is None:
            snapshot_id = staging.name[len(".staging-"):]
            final = root / snapshot_id
            shutil.copytree(staging, final)
            state["final"] = final
        return real_verify_success(success_path)

    monkeypatch.setattr(mat_mod, "_verify_success", raced)
    result_m = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    final = state["final"]
    assert final is not None
    assert result_m.created_new_snapshot is False
    assert result_m.snapshot_path == final
    # Our staging was removed; the concurrent final is untouched.
    assert not any(item.name.startswith(".staging-") for item in root.iterdir())
    assert set(root.iterdir()) == {final}


def test_concurrent_corrupt_final_fails_closed_without_deleting(
    complete_build, tmp_path, monkeypatch
):
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    real_verify_success = mat_mod._verify_success
    state = {"final": None}

    def raced(success_path):
        staging = success_path.parent
        if state["final"] is None:
            snapshot_id = staging.name[len(".staging-"):]
            final = root / snapshot_id
            shutil.copytree(staging, final)
            (final / "_SUCCESS").unlink()  # corrupt the concurrent final
            state["final"] = final
        return real_verify_success(success_path)

    monkeypatch.setattr(mat_mod, "_verify_success", raced)
    with pytest.raises(DatasetCatalogMaterializationError):
        materialize_dataset_catalog_snapshot(
            result, output_root=root, built_at=BUILT_AT
        )
    final = state["final"]
    assert final is not None
    # The corrupt concurrent final is never deleted or overwritten; only
    # our own staging was removed.
    assert final.is_dir()
    assert not (final / "_SUCCESS").exists()
    assert not any(item.name.startswith(".staging-") for item in root.iterdir())


# ---------------------------------------------------------------------------
# G. EMPTY Catalog, COMPLETE + EMPTY E2E, and side-effect boundaries.
# ---------------------------------------------------------------------------


def test_empty_catalog_materializes(complete_build, tmp_path):
    result = build_dataset_catalog(candidate_build_dirs=())
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    assert mresult.dataset_count == 0
    payload = read_json(mresult.catalog_path)
    assert payload["datasets"] == []
    assert payload["dataset_count"] == 0
    assert set(mresult.snapshot_path.iterdir()) == {
        mresult.catalog_path,
        mresult.manifest_path,
        mresult.success_path,
    }


def test_complete_and_empty_end_to_end(complete_build, empty_build, tmp_path):
    """The real E2E chain: Dataset materialize -> load_verified_dataset ->
    Catalog builder -> Catalog materializer (COMPLETE + EMPTY)."""
    result = build_catalog(complete_build, empty_build)
    assert result.dataset_count == 2
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    payload = read_json(mresult.catalog_path)
    assert {record["dataset_facts"]["status"] for record in payload["datasets"]} == {
        STATUS_COMPLETE,
        STATUS_EMPTY,
    }
    assert payload["catalog_content_id"] == result.catalog_content_id


def test_materializer_only_writes_output_root(complete_build, tmp_path):
    """The materializer must never touch the Dataset build directories;
    everything it writes stays under the explicit output_root."""
    dataset_dir = complete_build.build_path
    dataset_tree = tree_snapshot(dataset_dir)
    parent_tree = tree_snapshot(dataset_dir.parent)
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    assert tree_snapshot(dataset_dir) == dataset_tree
    assert tree_snapshot(dataset_dir.parent) == parent_tree
    assert set(root.iterdir()) == {mresult.snapshot_path}


def test_materializer_never_uses_current_time(complete_build, tmp_path):
    """built_at is the explicit argument: the manifest carries exactly the
    explicit value, never the current wall clock."""
    result = build_catalog(complete_build)
    root = snapshot_root(tmp_path)
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=root, built_at=BUILT_AT
    )
    payload = read_json(mresult.manifest_path)
    assert payload["built_at"] == BUILT_AT.astimezone(UTC).isoformat(
        timespec="microseconds"
    )
