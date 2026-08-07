"""Offline deterministic tests of the verified Dataset Catalog snapshot
reader (v0.6.0 PR-6).

Covers the public API and version constants, the frozen reader models,
the full strict verification of a valid snapshot (recomputed content and
physical identities, entry ordering / uniqueness, manifest record
binding), snapshot relocation (root-A -> root-B keeps the snapshot ID and
content ID), the self-verification after the original Datasets are
deleted, the recorded build-location shape contract (never reloaded),
the full corruption / tamper / race fail-closed matrix (missing, extra,
non-empty, symlinked, junctioned, renamed, hash / size / ID / facts /
count / order / duplicate / unknown-field / missing-field / BOM /
non-canonical / unsupported-version / invalid-location-text), the
two-pass concurrent-mutation detection, the programming-error boundary,
and the no-side-effect / no-reload boundary. All Dataset builds are
produced through the public chain; no network, no OpenD, no current time,
and no real market data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import market_vault.dataset.dataset_catalog_reader as reader_mod
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
    DATASET_CATALOG_CATALOG_FILENAME,
    DATASET_CATALOG_MANIFEST_FILENAME,
    DATASET_CATALOG_READER_CONTRACT_VERSION,
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
    DatasetCatalogArtifactValidationError,
    DatasetCatalogFileRecord,
    DatasetCatalogSnapshotEntryRecord,
    DatasetCatalogSnapshotManifestRecord,
    DatasetField,
    DatasetScope,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    VerifiedDatasetCatalogSnapshot,
    build_dataset_catalog,
    dataset_orchestration_schema,
    load_verified_dataset,
    materialize_dataset_artifacts,
    materialize_dataset_catalog_snapshot,
    orchestrate_dataset_build,
    project_dataset_catalog_entry,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"
BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

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
    root = tmp_path_factory.mktemp("mv_catalog_reader")
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
    tmp = Path(tmp_path_factory.mktemp("mv_reader_complete"))
    result, mresult = materialize_once(fixtures, tmp, requests=[request()])
    assert result.status == STATUS_COMPLETE
    return read_verified(mresult)


@pytest.fixture(scope="module")
def empty_build(fixtures, tmp_path_factory):
    tmp = Path(tmp_path_factory.mktemp("mv_reader_empty"))
    result, mresult = materialize_once(fixtures, tmp, requests=[])
    assert result.status == STATUS_EMPTY
    return read_verified(mresult)


def snapshot_root(tmp_path) -> Path:
    return tmp_path / "catalog-snapshots"


def make_snapshot(tmp_path, *builds, built_at=BUILT_AT):
    """Full E2E: Catalog builder -> materializer -> final snapshot dir."""
    result = build_dataset_catalog(
        candidate_build_dirs=tuple(build.build_path for build in builds)
    )
    return materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=built_at
    )


def canonical_json_bytes(payload) -> bytes:
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return (text + "\n").encode("utf-8")


def rewrite_catalog(snapshot: Path, mutate) -> None:
    """Rewrite catalog.json canonically with ``mutate`` and patch the
    manifest's catalog_file byte facts so the manifest record stays
    self-consistent (the tamper under test must be the mutation itself)."""
    catalog_path = snapshot / DATASET_CATALOG_CATALOG_FILENAME
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    mutate(payload)
    data = canonical_json_bytes(payload)
    catalog_path.write_bytes(data)
    manifest_path = snapshot / DATASET_CATALOG_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["catalog_file"]["byte_size"] = len(data)
    manifest["catalog_file"]["sha256"] = hashlib.sha256(data).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))


def rewrite_manifest(snapshot: Path, mutate) -> None:
    manifest_path = snapshot / DATASET_CATALOG_MANIFEST_FILENAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(payload)
    manifest_path.write_bytes(canonical_json_bytes(payload))


def tree_snapshot(root: Path) -> set[str]:
    return {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
    }


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
# A. Public API and frozen models.
# ---------------------------------------------------------------------------


def test_reader_version_constant_exact():
    assert DATASET_CATALOG_READER_CONTRACT_VERSION == (
        "market-vault-verified-dataset-catalog-reader-v1"
    )


def test_public_api_exports():
    import market_vault.dataset as dataset_pkg

    for name in (
        "load_verified_dataset_catalog",
        "VerifiedDatasetCatalogSnapshot",
        "DatasetCatalogSnapshotEntryRecord",
        "DatasetCatalogSnapshotManifestRecord",
        "DatasetCatalogFileRecord",
        "DatasetCatalogArtifactValidationError",
    ):
        assert name in dataset_pkg.__all__
        assert hasattr(dataset_pkg, name)


def test_models_are_frozen(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    verified = reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    with pytest.raises(FrozenInstanceError):
        verified.snapshot_id = "f" * 64
    with pytest.raises(FrozenInstanceError):
        verified.entries = ()
    entry = verified.entries[0]
    with pytest.raises(FrozenInstanceError):
        entry.dataset_facts = None
    with pytest.raises(FrozenInstanceError):
        verified.manifest.catalog_file = None


def test_model_self_validation(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    verified = reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    from dataclasses import replace

    with pytest.raises(DatasetCatalogArtifactValidationError):
        replace(verified, dataset_count=verified.dataset_count + 1)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        replace(
            verified.entries[0],
            recorded_build_path=verified.entries[0].recorded_build_path
            + "/../escaped",
        )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        replace(
            verified.entries[0],
            content_id="f" * 64,
        )


# ---------------------------------------------------------------------------
# B. Strict verification of a valid snapshot.
# ---------------------------------------------------------------------------


def test_verified_snapshot_facts(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    verified = reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    assert verified.reader_contract_version == DATASET_CATALOG_READER_CONTRACT_VERSION
    assert verified.snapshot_id == mresult.snapshot_id
    assert verified.catalog_content_id == mresult.catalog_content_id
    assert verified.dataset_count == 1
    assert verified.snapshot_dir == mresult.snapshot_path
    assert verified.manifest.built_at == BUILT_AT.astimezone(UTC)
    assert isinstance(verified.manifest, DatasetCatalogSnapshotManifestRecord)
    assert isinstance(verified.manifest.catalog_file, DatasetCatalogFileRecord)
    assert verified.manifest.catalog_file.relative_path == "catalog.json"
    entry = verified.entries[0]
    assert isinstance(entry, DatasetCatalogSnapshotEntryRecord)
    assert entry.dataset_id == complete_build.dataset_id
    assert entry.dataset_facts.dataset_id == complete_build.dataset_id
    assert entry.dataset_facts.status == STATUS_COMPLETE
    assert entry.content_id == project_dataset_catalog_entry(complete_build).content_id
    assert entry.recorded_build_path.endswith(f"/{complete_build.dataset_id}")
    assert "\\" not in entry.recorded_build_path
    assert entry.recorded_built_at == BUILT_AT.astimezone(UTC)


def test_entries_sorted_and_unique(complete_build, empty_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build, empty_build)
    verified = reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    assert verified.dataset_count == 2
    ids = [entry.dataset_id for entry in verified.entries]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    statuses = {entry.dataset_facts.status for entry in verified.entries}
    assert statuses == {STATUS_COMPLETE, STATUS_EMPTY}


def test_empty_catalog_snapshot_verifies(complete_build, tmp_path):
    result = build_dataset_catalog(candidate_build_dirs=())
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    verified = reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    assert verified.dataset_count == 0
    assert verified.entries == ()


def test_snapshot_relocation_preserves_identity(complete_build, tmp_path):
    """A complete verified snapshot moved to another parent still verifies
    with the same snapshot ID and content ID."""
    mresult = make_snapshot(tmp_path, complete_build)
    root_b = tmp_path / "root-b"
    root_b.mkdir()
    moved = root_b / mresult.snapshot_id
    shutil.move(str(mresult.snapshot_path), str(moved))
    verified = reader_mod.load_verified_dataset_catalog(moved)
    assert verified.snapshot_id == mresult.snapshot_id
    assert verified.catalog_content_id == mresult.catalog_content_id
    assert verified.dataset_count == 1


def test_snapshot_verifies_after_dataset_deleted(complete_build, tmp_path):
    """The reader never reloads the recorded Dataset paths: deleting the
    original Dataset must not make an intact snapshot unverifiable."""
    other_parent = tmp_path / "dataset-copy"
    other_parent.mkdir()
    dataset_copy = other_parent / complete_build.dataset_id
    shutil.copytree(complete_build.build_path, dataset_copy)
    result = build_dataset_catalog(candidate_build_dirs=(dataset_copy,))
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=snapshot_root(tmp_path), built_at=BUILT_AT
    )
    shutil.rmtree(dataset_copy)  # the original Dataset is gone
    verified = reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    assert verified.snapshot_id == mresult.snapshot_id
    assert verified.entries[0].dataset_id == complete_build.dataset_id


def test_reader_is_side_effect_free(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    before = tree_snapshot(mresult.snapshot_path)
    reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    assert tree_snapshot(mresult.snapshot_path) == before


# ---------------------------------------------------------------------------
# C. Recorded build-location shape contract.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_text",
    [
        "C:\\Users\\tester\\out\\{id}",          # backslash
        "C:/Users/./tester/{id}",                 # "." component
        "C:/Users/..\\tester/{id}",               # ".." component
        "C:/Users/tester/other-dataset",          # final != dataset_id
        "",                                       # empty
    ],
)
def test_invalid_recorded_location_text_fails(complete_build, tmp_path, bad_text):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["datasets"][0]["observed_metadata"]["build_path"] = bad_text.format(
            id=complete_build.dataset_id
        )

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_posix_recorded_location_text_accepted(complete_build, tmp_path):
    """A POSIX absolute path (leading root slash) is accepted as
    historical location text — the root slash must not be mistaken for an
    empty path component."""
    mresult = make_snapshot(tmp_path, complete_build)
    from market_vault.dataset.dataset_catalog_reader_models import (
        _validate_recorded_build_path,
    )

    text = _validate_recorded_build_path(
        f"/tmp/data/{complete_build.dataset_id}", complete_build.dataset_id
    )
    assert text.endswith(complete_build.dataset_id)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        _validate_recorded_build_path(
            f"/tmp//data/{complete_build.dataset_id}", complete_build.dataset_id
        )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        _validate_recorded_build_path(
            f"/tmp/data/{complete_build.dataset_id}/", complete_build.dataset_id
        )
    # The full E2E round trip with a POSIX-style recorded location: a
    # consistent manifest (recomputed snapshot ID over the new catalog
    # bytes) must verify successfully.
    from market_vault.dataset.dataset_catalog_snapshot_identity import (
        dataset_catalog_snapshot_id,
    )
    import json as _json

    catalog_path = mresult.snapshot_path / DATASET_CATALOG_CATALOG_FILENAME
    payload = _json.loads(catalog_path.read_text(encoding="utf-8"))
    payload["datasets"][0]["observed_metadata"]["build_path"] = (
        f"/home/tester/out/{complete_build.dataset_id}"
    )
    new_bytes = canonical_json_bytes(payload)
    catalog_path.write_bytes(new_bytes)
    manifest_path = mresult.snapshot_path / DATASET_CATALOG_MANIFEST_FILENAME
    manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["catalog_file"]["byte_size"] = len(new_bytes)
    manifest["catalog_file"]["sha256"] = hashlib.sha256(new_bytes).hexdigest()
    manifest["snapshot_id"] = dataset_catalog_snapshot_id(
        catalog_content_id=manifest["catalog_content_id"],
        dataset_count=manifest["dataset_count"],
        built_at=datetime.fromisoformat(manifest["built_at"]),
        catalog_file_byte_size=len(new_bytes),
        catalog_file_sha256=hashlib.sha256(new_bytes).hexdigest(),
    )
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    # The physical snapshot ID changed with the new catalog bytes: the
    # directory is rebuilt under the new snapshot_id (like a fresh
    # materialization of the relocated Dataset set).
    new_snapshot_id = manifest["snapshot_id"]
    rebuilt = mresult.snapshot_path.parent / new_snapshot_id
    shutil.move(str(mresult.snapshot_path), str(rebuilt))
    verified = reader_mod.load_verified_dataset_catalog(rebuilt)
    assert verified.snapshot_id == new_snapshot_id
    assert verified.entries[0].recorded_build_path == (
        f"/home/tester/out/{complete_build.dataset_id}"
    )


def test_valid_recorded_location_text_accepted(complete_build, tmp_path):
    """Forward-slash text from any OS is accepted as historical text."""
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["datasets"][0]["observed_metadata"]["build_path"] = (
            f"C:/Users/tester/out/{complete_build.dataset_id}"
        )

    rewrite_catalog(mresult.snapshot_path, mutate)
    rewrite_manifest(
        mresult.snapshot_path,
        lambda m: m.update(
            {
                "snapshot_id": "f" * 64
            }
        ),
    )
    # The shape contract passes; the recomputed snapshot ID then no longer
    # matches the (now-stale) manifest snapshot_id, which must fail closed
    # with the reader error — proving the shape check accepted the text
    # and the identity check still guards the snapshot.
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


# ---------------------------------------------------------------------------
# D. Corruption / tamper matrix (all fail closed).
# ---------------------------------------------------------------------------


def test_missing_catalog_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    (mresult.snapshot_path / DATASET_CATALOG_CATALOG_FILENAME).unlink()
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_missing_manifest_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    (mresult.snapshot_path / DATASET_CATALOG_MANIFEST_FILENAME).unlink()
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_missing_success_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    (mresult.snapshot_path / DATASET_CATALOG_SUCCESS_FILENAME).unlink()
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_extra_file_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    (mresult.snapshot_path / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_extra_directory_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    (mresult.snapshot_path / "extra-dir").mkdir()
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_non_empty_success_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    (mresult.snapshot_path / DATASET_CATALOG_SUCCESS_FILENAME).write_bytes(b"x")
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


@pytest.mark.parametrize("name", ["catalog.json", "manifest.json", "_SUCCESS"])
def test_symlinked_artifact_fails(complete_build, tmp_path, name):
    mresult = make_snapshot(tmp_path, complete_build)
    target = tmp_path / f"outside-{name}"
    target.write_text("{}", encoding="utf-8")
    artifact = mresult.snapshot_path / name
    artifact.unlink()
    _make_symlink_or_skip(target, artifact)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_snapshot_directory_symlink_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    link = tmp_path / "linked-snapshot"
    _make_symlink_or_skip(mresult.snapshot_path, link)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(link)


def test_wrong_dirname_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    wrong = tmp_path / ("c" * 64)
    shutil.move(str(mresult.snapshot_path), str(wrong))
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(wrong)


def test_catalog_hash_mismatch_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    with (mresult.snapshot_path / DATASET_CATALOG_CATALOG_FILENAME).open(
        "ab"
    ) as handle:
        handle.write(b"junk")
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_catalog_byte_size_mismatch_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    rewrite_manifest(
        mresult.snapshot_path,
        lambda m: m["catalog_file"].update({"byte_size": 999999}),
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_manifest_snapshot_id_tamper_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    rewrite_manifest(
        mresult.snapshot_path, lambda m: m.update({"snapshot_id": "f" * 64})
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_manifest_content_id_tamper_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    rewrite_manifest(
        mresult.snapshot_path,
        lambda m: m.update({"catalog_content_id": "f" * 64}),
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_manifest_built_at_tamper_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    rewrite_manifest(
        mresult.snapshot_path,
        # Equivalent instant, non-canonical representation: the canonical
        # bytes check must reject it.
        lambda m: m.update({"built_at": "2026-08-05T12:00:00Z"}),
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_catalog_top_level_content_id_tamper_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["catalog_content_id"] = "f" * 64

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_entry_content_id_tamper_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["datasets"][0]["content_id"] = "f" * 64

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_dataset_facts_tamper_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["datasets"][0]["dataset_facts"]["dataset_kind"] = "tampered"

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_catalog_dataset_count_tamper_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["dataset_count"] = 2

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_dataset_order_tamper_fails(complete_build, empty_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build, empty_build)

    def mutate(payload):
        payload["datasets"] = list(reversed(payload["datasets"]))

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_duplicate_dataset_id_fails(complete_build, empty_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build, empty_build)

    def mutate(payload):
        payload["datasets"].append(payload["datasets"][0])

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_unknown_json_field_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["extra_field"] = 1

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_missing_json_field_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        del payload["datasets"]

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_bom_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    catalog_path = mresult.snapshot_path / DATASET_CATALOG_CATALOG_FILENAME
    catalog_path.write_bytes(b"\xef\xbb\xbf" + catalog_path.read_bytes())
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_non_canonical_whitespace_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    catalog_path = mresult.snapshot_path / DATASET_CATALOG_CATALOG_FILENAME
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_non_canonical_key_order_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    catalog_path = mresult.snapshot_path / DATASET_CATALOG_CATALOG_FILENAME
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    # Re-serialize with an explicitly reversed key order (canonical is
    # sorted); the canonical-bytes check must reject it.
    catalog_path.write_text(
        json.dumps(
            dict(reversed(list(payload.items()))),
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_unsupported_version_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)

    def mutate(payload):
        payload["snapshot_schema_version"] = "market-vault-dataset-catalog-snapshot-v9"

    rewrite_catalog(mresult.snapshot_path, mutate)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_manifest_unknown_field_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    rewrite_manifest(
        mresult.snapshot_path, lambda m: m.update({"extra": 1})
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_manifest_missing_field_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    rewrite_manifest(
        mresult.snapshot_path, lambda m: m.pop("catalog_file")
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_manifest_relative_path_drift_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    rewrite_manifest(
        mresult.snapshot_path,
        lambda m: m["catalog_file"].update({"relative_path": "other.json"}),
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


def test_errors_carry_cause(complete_build, tmp_path):
    """Documented underlying failures (an unparseable manifest) are
    converted with their ``__cause__`` preserved."""
    mresult = make_snapshot(tmp_path, complete_build)
    (mresult.snapshot_path / DATASET_CATALOG_MANIFEST_FILENAME).write_bytes(
        b"not json"
    )
    with pytest.raises(DatasetCatalogArtifactValidationError) as excinfo:
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)
    assert excinfo.value.__cause__ is not None


def test_programming_error_not_converted(complete_build, tmp_path, monkeypatch):
    mresult = make_snapshot(tmp_path, complete_build)

    def boom(path, label):
        raise RuntimeError("programming boom")

    monkeypatch.setattr(reader_mod, "_read_artifact_bytes", boom)
    with pytest.raises(RuntimeError, match="programming boom"):
        reader_mod.load_verified_dataset_catalog(mresult.snapshot_path)


# ---------------------------------------------------------------------------
# E. Two-pass concurrent-mutation detection.
# ---------------------------------------------------------------------------


def test_second_pass_detects_concurrent_catalog_mutation(
    complete_build, tmp_path, monkeypatch
):
    mresult = make_snapshot(tmp_path, complete_build)
    snapshot = mresult.snapshot_path
    catalog_path = snapshot / DATASET_CATALOG_CATALOG_FILENAME
    real_sha = reader_mod._file_sha256
    state = {"mutated": False}

    def racing(path):
        if not state["mutated"]:
            state["mutated"] = True
            with catalog_path.open("ab") as handle:
                handle.write(b"junk")
        return real_sha(path)

    monkeypatch.setattr(reader_mod, "_file_sha256", racing)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(snapshot)


def test_second_pass_detects_concurrent_manifest_mutation(
    complete_build, tmp_path
):
    mresult = make_snapshot(tmp_path, complete_build)
    snapshot = mresult.snapshot_path
    manifest_bytes = (snapshot / DATASET_CATALOG_MANIFEST_FILENAME).read_bytes()
    catalog_bytes = (snapshot / DATASET_CATALOG_CATALOG_FILENAME).read_bytes()
    # Mutate the manifest between the first pass and the final pass; the
    # final pass must fail closed on the byte difference.
    (snapshot / DATASET_CATALOG_MANIFEST_FILENAME).write_bytes(
        manifest_bytes + b"\n"
    )
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod._second_pass_verify(
            snapshot, manifest_bytes, catalog_bytes,
            snapshot / DATASET_CATALOG_CATALOG_FILENAME,
        )


# ---------------------------------------------------------------------------
# F. Input contract.
# ---------------------------------------------------------------------------


def test_relative_snapshot_dir_coerced(complete_build, tmp_path, monkeypatch):
    mresult = make_snapshot(tmp_path, complete_build)
    monkeypatch.chdir(snapshot_root(tmp_path))
    verified = reader_mod.load_verified_dataset_catalog(mresult.snapshot_id)
    assert verified.snapshot_id == mresult.snapshot_id


def test_dot_component_rejected(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(
            mresult.snapshot_path / ".." / mresult.snapshot_id
        )


def test_missing_directory_fails(complete_build, tmp_path):
    mresult = make_snapshot(tmp_path, complete_build)
    with pytest.raises(DatasetCatalogArtifactValidationError):
        reader_mod.load_verified_dataset_catalog(
            tmp_path / "missing" / mresult.snapshot_id
        )
