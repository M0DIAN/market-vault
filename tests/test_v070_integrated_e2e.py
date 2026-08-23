"""Integrated v0.7.0 PR-5 acceptance: real-artifact-chain E2E.

Builds a REAL deterministic offline artifact chain in ``tmp_path`` with
the existing production builders and materializers:

    minimal valid source inputs
        -> real committed Canonical build
        -> real committed Dataset build
        -> real committed Dataset Catalog snapshot
        -> ArtifactClient verified reads of all three

and verifies the full PR-5 acceptance surface:

1. ``ArtifactClient()`` succeeds with zero arguments;
2-4. every client read returns the exact formal verified object type;
5. every client result matches the corresponding direct formal verified
   reader result exactly;
6. the identity chain: the Canonical build ID matches the committed
   Canonical output, the Dataset ID matches the committed Dataset
   output, and the Catalog snapshot refers to the Dataset ID (and its
   pinned Canonical build IDs) according to the existing formal Catalog
   contract — no new identity relationship is invented;
7. the complete artifact trees are byte-identical before and after all
   client reads (no new / removed / modified file);
8. fail-closed integration: corrupting a COPY of each artifact type
   independently makes the ArtifactClient call raise the exact existing
   public validation error (never a replacement error);
9. a fresh-interpreter probe proves importing and binding the client
   (and all three methods) stays lazy — no config / storage / canonical
   / dataset / duckdb / pandas / moomoo / futu load;
10. the source-tree example
   ``examples/python_client/read_verified_artifacts.py`` runs against
   the real chain with all three explicit paths, prints one parseable
   deterministic JSON object whose IDs / status / counts equal the
   already verified objects, keeps stderr empty, and leaves every
   artifact tree unchanged.

No fake raw-file trust path: fixtures are constructed with the
production builders only, mirroring the deterministic patterns of the
formal reader tests. No production code is modified to make the fixture
easier. No network, no OpenD, no current time.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault import ArtifactClient
from market_vault.canonical import (
    CanonicalArtifactValidationError,
    CanonicalRequestKey,
    VerifiedCanonicalBuild,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    DATASET_KIND_SUPERVISED,
    DATASET_MANIFEST_SCHEMA_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    ChronologicalSplitSpec,
    CrossTradingDayPolicy,
    DatasetArtifactValidationError,
    DatasetCatalogArtifactValidationError,
    DatasetField,
    DatasetScope,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    VerifiedDatasetBuild,
    VerifiedDatasetCatalogSnapshot,
    build_dataset_catalog,
    dataset_orchestration_schema,
    load_verified_dataset,
    load_verified_dataset_catalog,
    materialize_dataset_artifacts,
    materialize_dataset_catalog_snapshot,
    orchestrate_dataset_build,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.purge import purge_execute, purge_plan
from market_vault.storage import Catalog, ParquetStore

NY = "America/New_York"
UTC = timezone.utc
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m",
    requested_session="ALL",
    adjustment="NONE",
    source_schema_version="10.9",
)
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"


# ---------------------------------------------------------------------------
# Minimal deterministic artifact fixtures (production builders only).
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
            "close": [100.5] * len(time_keys),
            "volume": [100] * len(time_keys),
        }
    )
    curated = normalize_bars(
        raw, requested_trade_date=trade_date, interval="1m",
        requested_session="ALL", adjustment="NONE", source=cfg.source,
        source_schema_version=cfg.source_schema_version, run_id=run_id,
    )
    raw["requested_trade_date"] = trade_date
    raw["interval"] = "1m"
    raw["requested_session"] = "ALL"
    raw["adjustment"] = "NONE"
    raw["ingestion_run_id"] = run_id
    raw_path = store.write_raw(
        raw, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id
    )
    curated_path = store.write_curated(
        curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id
    )
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.raw_file = str(raw_path)
    run.curated_file = str(curated_path)
    run.row_count = len(curated)
    run.status = "SUCCESS"
    run.finished_at = datetime(
        trade_date.year, trade_date.month, trade_date.day, 14, 0, tzinfo=UTC
    )
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def canonical_output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize_canonical(cfg: Settings, *, symbols=None, trade_dates=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=DEFAULT_KEY,
        output_root=canonical_output_root(cfg),
        created_at=CREATED_AT,
    )


def build_canonical(
    cfg: Settings,
    *,
    run_id: str,
    time_keys: list[str],
) -> Path:
    """One real Canonical build directory via the production materializer."""
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id=run_id,
        time_keys=time_keys,
    )
    result = materialize_canonical(
        cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)]
    )
    return Path(result.build_path)


def feature_spec() -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="sr",
        version="v1",
        output=DatasetField(name="sr", logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_SIMPLE,
        parameters=(SpecParameter("window_bars", 2),),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )


def label_spec() -> LabelSpec:
    return LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name="fr",
        version="v1",
        output=DatasetField(name="fr", logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_FORWARD,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow("BARS", 1, 1),
        horizon=LabelHorizon("BARS", 2),
        alignment_rule="FEATURE_CLOSE_ALIGNED",
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )


def split_spec() -> ChronologicalSplitSpec:
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


def dataset_request() -> PITSampleRequest:
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


def build_dataset(cfg: Settings, canonical_builds: list[Path], tmp_path: Path) -> Path:
    """One real Dataset build directory via the production orchestration
    and materialization pipeline."""
    feature_specs = (feature_spec(),)
    label_specs = (label_spec(),)
    scope = DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )
    schema = dataset_orchestration_schema(
        feature_specs, label_specs, include_dataset_as_of=False
    )
    result = orchestrate_dataset_build(
        builds=tuple(
            load_verified_canonical_build(b) for b in canonical_builds
        ),
        requests=(dataset_request(),),
        feature_specs=feature_specs,
        label_specs=label_specs,
        split_spec=split_spec(),
        scope=scope,
        schema=schema,
        dataset_as_of=None,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )
    mresult = materialize_dataset_artifacts(
        result, output_root=tmp_path / "datasets", built_at=BUILT_AT
    )
    return Path(mresult.build_path)


def build_catalog_snapshot(dataset_build: Path, tmp_path: Path) -> Path:
    """One immutable Dataset Catalog snapshot via the production builders:
    ``build_dataset_catalog`` + ``materialize_dataset_catalog_snapshot``."""
    result = build_dataset_catalog(
        candidate_build_dirs=tuple([str(dataset_build)])
    )
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=tmp_path / "catalog_snapshots", built_at=BUILT_AT
    )
    return Path(mresult.snapshot_path)


def tree_snapshot(root: Path) -> dict[str, str]:
    """Deterministic full-tree snapshot: {relative posix path: sha256} over
    every regular file under ``root`` (files sorted within each directory,
    so the mapping is independent of scan order)."""
    snap = {}
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            snap[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snap


@dataclass(frozen=True)
class ArtifactChain:
    """The real committed artifact chain: two Canonical builds pinning the
    Dataset's feature and label windows, one Dataset build, and one
    Catalog snapshot referencing the Dataset."""

    canonical_a: Path
    canonical_f: Path
    dataset: Path
    catalog: Path

    def all_trees(self) -> dict[str, dict[str, str]]:
        return {
            "canonical_a": tree_snapshot(self.canonical_a),
            "canonical_f": tree_snapshot(self.canonical_f),
            "dataset": tree_snapshot(self.dataset),
            "catalog": tree_snapshot(self.catalog),
        }


@pytest.fixture(scope="module")
def artifact_chain(tmp_path_factory) -> ArtifactChain:
    """The real deterministic offline artifact chain built entirely with
    the production builders / materializers in one tmp tree."""
    root = tmp_path_factory.mktemp("mv_e2e")
    cfg = settings(root)
    calendar(cfg)
    canonical_a = build_canonical(
        cfg,
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 6),
    )
    canonical_f = build_canonical(
        cfg,
        run_id="run-f",
        time_keys=minute_keys("2026-07-01 09:36:00", 6),
    )
    dataset = build_dataset(cfg, [canonical_a, canonical_f], root)
    catalog = build_catalog_snapshot(dataset, root)
    return ArtifactChain(
        canonical_a=canonical_a,
        canonical_f=canonical_f,
        dataset=dataset,
        catalog=catalog,
    )


def test_verified_derived_chain_survives_source_snapshot_quarantine(tmp_path):
    """The formal retention policy is backed by the existing readers.

    Canonical embeds source identities, Dataset is self-contained, and the
    Catalog reader never reloads recorded Dataset paths. Quarantining the
    original Raw/Curated pairs therefore cannot invalidate committed official
    derived artifacts and never cascades into them.
    """
    cfg = settings(tmp_path)
    calendar(cfg)
    canonical_a = build_canonical(
        cfg,
        run_id="purge-run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 6),
    )
    canonical_f = build_canonical(
        cfg,
        run_id="purge-run-f",
        time_keys=minute_keys("2026-07-01 09:36:00", 6),
    )
    dataset = build_dataset(cfg, [canonical_a, canonical_f], tmp_path)
    catalog_snapshot = build_catalog_snapshot(dataset, tmp_path)
    before = (
        load_verified_canonical_build(canonical_a),
        load_verified_canonical_build(canonical_f),
        load_verified_dataset(dataset),
        load_verified_dataset_catalog(catalog_snapshot),
    )

    sealed = purge_plan(
        cfg,
        source="moomoo",
        symbols=["US.MU"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )
    assert sealed.executable
    result = purge_execute(
        cfg,
        plan_id=sealed.plan_id,
        confirmation=f"PURGE {sealed.plan_id}",
    )
    assert result.status == "SUCCESS"

    after = (
        load_verified_canonical_build(canonical_a),
        load_verified_canonical_build(canonical_f),
        load_verified_dataset(dataset),
        load_verified_dataset_catalog(catalog_snapshot),
    )
    assert after == before
    assert canonical_a.exists() and canonical_f.exists()
    assert dataset.exists() and catalog_snapshot.exists()


# ---------------------------------------------------------------------------
# 1-4. Zero-argument construction and exact formal return types.
# ---------------------------------------------------------------------------


def test_artifact_client_constructs_with_zero_arguments():
    client = ArtifactClient()
    assert type(client) is ArtifactClient


def test_canonical_read_returns_exact_formal_type(artifact_chain):
    result = ArtifactClient().load_canonical_build(artifact_chain.canonical_a)
    assert type(result) is VerifiedCanonicalBuild
    assert isinstance(result, VerifiedCanonicalBuild)


def test_dataset_read_returns_exact_formal_type(artifact_chain):
    result = ArtifactClient().load_dataset(artifact_chain.dataset)
    assert type(result) is VerifiedDatasetBuild
    assert isinstance(result, VerifiedDatasetBuild)


def test_catalog_read_returns_exact_formal_type(artifact_chain):
    result = ArtifactClient().load_dataset_catalog(artifact_chain.catalog)
    assert type(result) is VerifiedDatasetCatalogSnapshot
    assert isinstance(result, VerifiedDatasetCatalogSnapshot)


# ---------------------------------------------------------------------------
# 5. Client results match the direct formal verified readers exactly.
# ---------------------------------------------------------------------------


def test_client_results_match_direct_verified_readers_exactly(artifact_chain):
    client = ArtifactClient()

    direct_canonical = load_verified_canonical_build(artifact_chain.canonical_a)
    client_canonical = client.load_canonical_build(artifact_chain.canonical_a)
    assert client_canonical.canonical_build_id == direct_canonical.canonical_build_id
    assert client_canonical.canonical_content_id == (
        direct_canonical.canonical_content_id
    )
    assert client_canonical.resolution_content_id == (
        direct_canonical.resolution_content_id
    )
    assert client_canonical.gap_content_id == direct_canonical.gap_content_id
    assert client_canonical.status == direct_canonical.status
    assert client_canonical.manifest_payload == direct_canonical.manifest_payload
    assert client_canonical.bars == direct_canonical.bars
    assert client_canonical.canonical_row_version_ids == (
        direct_canonical.canonical_row_version_ids
    )

    direct_dataset = load_verified_dataset(artifact_chain.dataset)
    client_dataset = client.load_dataset(artifact_chain.dataset)
    assert client_dataset.dataset_id == direct_dataset.dataset_id
    assert client_dataset.dataset_kind == direct_dataset.dataset_kind
    assert client_dataset.status == direct_dataset.status
    assert client_dataset.schema == direct_dataset.schema
    assert client_dataset.rows == direct_dataset.rows
    assert client_dataset.split_result == direct_dataset.split_result
    assert client_dataset.manifest_payload == direct_dataset.manifest_payload
    assert client_dataset.build_report_payload == (
        direct_dataset.build_report_payload
    )

    direct_catalog = load_verified_dataset_catalog(artifact_chain.catalog)
    client_catalog = client.load_dataset_catalog(artifact_chain.catalog)
    assert client_catalog.snapshot_id == direct_catalog.snapshot_id
    assert client_catalog.catalog_content_id == direct_catalog.catalog_content_id
    assert client_catalog.dataset_count == direct_catalog.dataset_count
    assert client_catalog.manifest == direct_catalog.manifest
    assert client_catalog.entries == direct_catalog.entries
    assert client_catalog.built_at == direct_catalog.built_at


# ---------------------------------------------------------------------------
# 6. Identity chain (existing formal contracts only, no invented facts).
# ---------------------------------------------------------------------------


def test_identity_chain_build_ids_match_committed_outputs(artifact_chain):
    client = ArtifactClient()

    canonical = client.load_canonical_build(artifact_chain.canonical_a)
    dataset = client.load_dataset(artifact_chain.dataset)
    catalog = client.load_dataset_catalog(artifact_chain.catalog)

    # The committed Canonical output directory carries the
    # canonical_build_id in its name; the formal reader accepts either
    # ``<canonical_build_id>`` or ``build_id=<canonical_build_id>`` and
    # enforces the binding against the manifest (reader.py).
    assert artifact_chain.canonical_a.name.removeprefix("build_id=") == (
        canonical.canonical_build_id
    )
    assert artifact_chain.canonical_f.name.removeprefix("build_id=") == (
        client.load_canonical_build(artifact_chain.canonical_f).canonical_build_id
    )

    # The committed Dataset output directory is named exactly the
    # dataset_id (the materializer names the final directory by it).
    assert artifact_chain.dataset.name == dataset.dataset_id

    # The committed Catalog snapshot directory is named exactly the
    # snapshot_id (the formal reader enforces the name binding).
    assert artifact_chain.catalog.name == catalog.snapshot_id


def test_identity_chain_catalog_refers_to_dataset_and_pins(artifact_chain):
    client = ArtifactClient()

    canonical = client.load_canonical_build(artifact_chain.canonical_a)
    dataset = client.load_dataset(artifact_chain.dataset)
    catalog = client.load_dataset_catalog(artifact_chain.catalog)

    # The Dataset manifest pins the Canonical build IDs it was built from.
    dataset_canonical_pins = {
        pin.canonical_build_id for pin in dataset.manifest.canonical_builds
    }
    assert canonical.canonical_build_id in dataset_canonical_pins

    # The Catalog snapshot contains exactly one entry referring to the
    # Dataset ID, and the entry's facts mirror the verified Dataset and
    # pin the same Canonical build IDs (the existing formal Catalog
    # contract: projection over the verified Dataset facts).
    assert catalog.dataset_count == 1
    entry = catalog.entries[0]
    assert entry.dataset_id == dataset.dataset_id
    assert entry.dataset_facts.dataset_id == dataset.dataset_id
    assert entry.dataset_facts.status == dataset.status
    assert entry.dataset_facts.logical_row_count == dataset.manifest.logical_row_count
    assert entry.dataset_facts.logical_dataset_content_id == (
        dataset.manifest.logical_dataset_content_id
    )
    assert {
        pin.canonical_build_id for pin in entry.dataset_facts.canonical_build_pins
    } == dataset_canonical_pins
    assert entry.dataset_facts.canonical_row_version_ids == (
        dataset.manifest.canonical_row_version_ids
    )


# ---------------------------------------------------------------------------
# 7. Read-only guarantee: complete trees byte-identical after all reads.
# ---------------------------------------------------------------------------


def test_all_client_reads_leave_every_artifact_tree_byte_identical(artifact_chain):
    client = ArtifactClient()
    before = artifact_chain.all_trees()

    client.load_canonical_build(artifact_chain.canonical_a)
    client.load_canonical_build(artifact_chain.canonical_f)
    client.load_dataset(artifact_chain.dataset)
    client.load_dataset_catalog(artifact_chain.catalog)

    after = artifact_chain.all_trees()
    assert after == before
    for tree_name, snapshot in after.items():
        assert snapshot == before[tree_name]


# ---------------------------------------------------------------------------
# 8. Fail-closed integration: corrupt a COPY of each artifact type
#    independently; the exact existing public validation error raises.
# ---------------------------------------------------------------------------


def test_fail_closed_corrupt_canonical_copy_raises_formal_error(
    artifact_chain, tmp_path
):
    copy_dir = tmp_path / artifact_chain.canonical_a.name
    shutil.copytree(artifact_chain.canonical_a, copy_dir)
    manifest = copy_dir / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original[: len(original) // 2])
    with pytest.raises(CanonicalArtifactValidationError):
        ArtifactClient().load_canonical_build(copy_dir)


def test_fail_closed_corrupt_dataset_copy_raises_formal_error(
    artifact_chain, tmp_path
):
    copy_dir = tmp_path / artifact_chain.dataset.name
    shutil.copytree(artifact_chain.dataset, copy_dir)
    manifest = copy_dir / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original[: len(original) // 2])
    with pytest.raises(DatasetArtifactValidationError):
        ArtifactClient().load_dataset(copy_dir)


def test_fail_closed_corrupt_catalog_copy_raises_formal_error(
    artifact_chain, tmp_path
):
    copy_dir = tmp_path / artifact_chain.catalog.name
    shutil.copytree(artifact_chain.catalog, copy_dir)
    manifest = copy_dir / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original[: len(original) // 2])
    with pytest.raises(DatasetCatalogArtifactValidationError):
        ArtifactClient().load_dataset_catalog(copy_dir)


# ---------------------------------------------------------------------------
# 9. Fresh-interpreter integration: import and binding stay lazy.
# ---------------------------------------------------------------------------

FRESH_INTERPRETER_PROBE = """
import sys
from market_vault import ArtifactClient
client = ArtifactClient()

# Importing and constructing must not load the reader packages or any
# heavy module merely because ArtifactClient exists.
assert 'market_vault.canonical' not in sys.modules, sorted(
    m for m in sys.modules if m.startswith('market_vault.canonical'))
assert 'market_vault.dataset' not in sys.modules, sorted(
    m for m in sys.modules if m.startswith('market_vault.dataset'))
assert 'market_vault.config' not in sys.modules
assert 'market_vault.storage' not in sys.modules
assert 'duckdb' not in sys.modules
assert 'pandas' not in sys.modules
assert 'moomoo' not in sys.modules
assert 'futu' not in sys.modules

# Binding all three methods must stay lazy before invocation.
methods = (
    client.load_canonical_build,
    client.load_dataset,
    client.load_dataset_catalog,
)
assert len(methods) == 3
assert 'market_vault.canonical' not in sys.modules
assert 'market_vault.dataset' not in sys.modules
assert 'market_vault.config' not in sys.modules
assert 'market_vault.storage' not in sys.modules
assert 'duckdb' not in sys.modules
assert 'pandas' not in sys.modules
assert 'moomoo' not in sys.modules
assert 'futu' not in sys.modules

print('V070_E2E_FRESH_INTERPRETER_OK')
"""


def test_fresh_interpreter_import_and_binding_stays_lazy():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(
        Path(__file__).resolve().parents[1] / "src"
    )
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-c", FRESH_INTERPRETER_PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "V070_E2E_FRESH_INTERPRETER_OK" in result.stdout


# ---------------------------------------------------------------------------
# 10. Example execution against the real valid artifact chain.
# ---------------------------------------------------------------------------


EXAMPLE_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "python_client"
    / "read_verified_artifacts.py"
)


def test_example_execution_against_real_chain(artifact_chain):
    assert EXAMPLE_SCRIPT.is_file()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONIOENCODING"] = "utf-8"

    before = artifact_chain.all_trees()

    result = subprocess.run(
        [
            sys.executable,
            str(EXAMPLE_SCRIPT),
            "--canonical-build-dir",
            str(artifact_chain.canonical_a),
            "--dataset-build-dir",
            str(artifact_chain.dataset),
            "--catalog-snapshot-dir",
            str(artifact_chain.catalog),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == "", result.stderr

    payload = json.loads(result.stdout)

    # IDs / status / counts equal the already verified objects.
    client = ArtifactClient()
    canonical = client.load_canonical_build(artifact_chain.canonical_a)
    dataset = client.load_dataset(artifact_chain.dataset)
    catalog = client.load_dataset_catalog(artifact_chain.catalog)

    assert payload["canonical"]["canonical_build_id"] == canonical.canonical_build_id
    assert payload["canonical"]["status"] == canonical.status
    assert payload["canonical"]["row_count"] == len(canonical.bars)

    assert payload["dataset"]["dataset_id"] == dataset.dataset_id
    assert payload["dataset"]["status"] == dataset.status
    assert payload["dataset"]["row_count"] == len(dataset.rows)

    assert payload["dataset_catalog"]["snapshot_id"] == catalog.snapshot_id
    assert payload["dataset_catalog"]["catalog_content_id"] == (
        catalog.catalog_content_id
    )
    assert payload["dataset_catalog"]["dataset_count"] == catalog.dataset_count

    # Artifact trees remain unchanged after the example ran.
    assert artifact_chain.all_trees() == before
