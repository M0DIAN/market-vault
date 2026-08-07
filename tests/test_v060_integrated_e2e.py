"""PR-8: v0.6.0 integrated acceptance — one full offline chain and the
integrated determinism / corruption / recovery / security / usability proof
(PR-8; tests and documentation only, production sources frozen).

The COMPLETE chain runs the real operators end to end: static reference
Canonical artifact -> ``sample-generate`` -> ``dataset-build`` ->
``load_verified_dataset`` -> ``dataset-catalog-build`` -> verify -> list ->
show. The EMPTY chain proves EMPTY is a success, never a failure. The
determinism matrix proves generation, Dataset identity, and Catalog content
identity are cwd- and location-independent and that the snapshot ID tracks
the recorded build path while the content identity does not. The corruption
cascade proves every layer fails closed and never repairs. The recovery
contract proves Recovery != repair: partial output is cleaned, committed
finals are never deleted, reruns are idempotent, and foreign staging is
never adopted. The security matrix proves links, dot components, wrong
basenames, and ambiguous duplicates fail closed. The read-only proof proves
verify / list / show never write and survive deletion of the Dataset tree
(the recorded build path is historical metadata only).

Fully offline: no settings, no OpenD, no network, no current time.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault.canonical import (
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.canonical.models import CanonicalRequestKey
from market_vault.canonical.reader import CanonicalArtifactValidationError
from market_vault.dataset import load_verified_dataset
from market_vault.models import Settings
from market_vault.normalization import normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

from v060_acceptance_helpers import (
    BUILT_AT_ISO,
    CANONICAL_BARS_REL,
    CANONICAL_MANIFEST_REL,
    CANONICAL_RESOLUTION_REL,
    CANONICAL_SUCCESS_REL,
    FIXTURE_GENERATION_ID,
    _assert_failed_json,
    _make_symlink_or_skip,
    corrupt_bars,
    corrupt_manifest,
    corrupt_resolution,
    decode_canonical_fixture,
    default_build_plan_dict,
    delete_member,
    generation_plan_dict,
    relative_payload,
    run_cli,
    run_cli_subprocess,
    sha256_bytes,
    snapshot,
    write_fixture_files,
    write_generation_plan,
    write_json,
)

FAILURE_FIELDS = frozenset(
    {
        "result_schema_version",
        "cli_contract_version",
        "command",
        "result",
        "error_type",
        "error",
    }
)


# ---------------------------------------------------------------------------
# Materializer-based helpers (only for the legal EMPTY Canonical build; the
# COMPLETE chain always starts from the static reference artifact).
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> Settings:
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


def _calendar(cfg: Settings) -> None:
    trade_date = date(2026, 7, 1)
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


def _make_empty_build(tmp_path: Path):
    """A legal EMPTY Canonical build: the scope key has no bars at all."""
    cfg = _settings(tmp_path)
    _calendar(cfg)
    build = materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=["US.XYZ"],
        trade_dates=[date(2026, 7, 1)],
        request_key=CanonicalRequestKey(
            interval="1m", requested_session="ALL", adjustment="NONE",
            source_schema_version="10.9",
        ),
        output_root=cfg.data_root / "canonical" / "dataset=market_bars_canonical",
        created_at=pd.Timestamp("2026-08-04T12:00:00Z").to_pydatetime(),
    )
    return load_verified_canonical_build(build.build_path)


def _build_verified_catalog(tmp_path: Path, capsys) -> SimpleNamespace:
    """In-process COMPLETE chain: static Canonical artifact -> sample-generate
    -> dataset-build -> dataset-catalog-build. Returns the key payloads."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)  # core split payload -> frozen Generation ID
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        relative_payload(
            build_dir, tmp_path, output_plan_path="generated-plan.json"
        ),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    assert code == 0, err
    generation = json.loads(out)
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(tmp_path / "generated-plan.json")],
        capsys,
    )
    assert code == 0, err
    build = json.loads(out)
    snapshot_root = tmp_path / "catalog-snapshots"
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(tmp_path / "datasets"),
            "--output-root", str(snapshot_root),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    assert code == 0, err
    catalog = json.loads(out)
    return SimpleNamespace(
        tmp_path=tmp_path,
        build_dir=build_dir,
        generation=generation,
        build=build,
        catalog=catalog,
        dataset_dir=Path(build["build_path"]),
        snapshot_dir=Path(catalog["snapshot_path"]),
    )


# ---------------------------------------------------------------------------
# A. Integrated COMPLETE chain (all six CLI steps in separate processes).
# ---------------------------------------------------------------------------


def test_complete_chain_all_six_cli_steps(tmp_path):
    """The operator chain: static reference Canonical artifact ->
    ``sample-generate`` -> ``dataset-build`` -> ``load_verified_dataset`` ->
    ``dataset-catalog-build`` -> verify -> list -> show. Every step emits
    exactly one JSON to stdout, nothing to stderr."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)  # core split payload -> frozen Generation ID
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        relative_payload(
            build_dir, tmp_path, output_plan_path="generated-plan.json"
        ),
    )

    # Step 1: sample-generate (own process; never builds anything).
    first = run_cli_subprocess(
        "sample-generate", "--plan", str(plan_path), cwd=tmp_path
    )
    assert first.returncode == 0, first.stderr
    assert first.stderr == ""
    generation = json.loads(first.stdout)
    assert generation["result"] == "SUCCESS"
    assert generation["command"] == "sample-generate"
    assert generation["generation_content_id"] == FIXTURE_GENERATION_ID
    assert generation["generated_request_count"] > 0
    output_plan = tmp_path / "generated-plan.json"
    assert output_plan.is_file()

    # Step 2: dataset-build consumes the generated plan (own process).
    second = run_cli_subprocess(
        "dataset-build", "--plan", str(output_plan), cwd=tmp_path
    )
    assert second.returncode == 0, second.stderr
    assert second.stderr == ""
    build = json.loads(second.stdout)
    assert build["result"] == "SUCCESS"
    assert build["command"] == "dataset-build"
    assert build["created_new_build"] is True
    assert build["dataset_status"] == "COMPLETE"
    assert build["logical_row_count"] > 0
    assert len(build["dataset_id"]) == 64
    dataset_dir = Path(build["build_path"])
    assert dataset_dir.is_dir()

    # Step 3: the library reader agrees with the CLI build facts.
    verified = load_verified_dataset(build["build_path"])
    assert verified.dataset_id == build["dataset_id"]
    assert verified.status == "COMPLETE"
    assert len(verified.rows) == build["logical_row_count"]

    # Step 4: dataset-catalog-build over the committed Dataset tree (own
    # process; bounded direct-child discovery).
    snapshot_root = tmp_path / "catalog-snapshots"
    third = run_cli_subprocess(
        "dataset-catalog-build",
        "--dataset-root", str(tmp_path / "datasets"),
        "--output-root", str(snapshot_root),
        "--built-at", BUILT_AT_ISO,
        cwd=tmp_path,
    )
    assert third.returncode == 0, third.stderr
    assert third.stderr == ""
    catalog = json.loads(third.stdout)
    assert catalog["result"] == "SUCCESS"
    assert catalog["command"] == "dataset-catalog-build"
    assert catalog["created_new_snapshot"] is True
    assert catalog["dataset_count"] == 1
    assert len(catalog["snapshot_id"]) == 64
    assert len(catalog["catalog_content_id"]) == 64
    assert catalog["built_at"] == "2026-08-05T01:00:00.000000+00:00"
    snapshot_dir = Path(catalog["snapshot_path"])
    assert snapshot_dir.is_dir()
    assert snapshot_dir.name == catalog["snapshot_id"]

    # Step 5: dataset-catalog-verify over the committed snapshot.
    fourth = run_cli_subprocess(
        "dataset-catalog-verify", "--snapshot-dir", str(snapshot_dir), cwd=tmp_path
    )
    assert fourth.returncode == 0, fourth.stderr
    assert fourth.stderr == ""
    summary = json.loads(fourth.stdout)
    assert summary["result"] == "VERIFIED"
    assert summary["snapshot_id"] == catalog["snapshot_id"]
    assert summary["catalog_content_id"] == catalog["catalog_content_id"]

    # Step 6: dataset-catalog-list with filters.
    fifth = run_cli_subprocess(
        "dataset-catalog-list",
        "--snapshot-dir", str(snapshot_dir),
        "--status", "COMPLETE",
        "--dataset-kind", "SUPERVISED",
        cwd=tmp_path,
    )
    assert fifth.returncode == 0, fifth.stderr
    assert fifth.stderr == ""
    listing = json.loads(fifth.stdout)
    assert listing["result"] == "LISTED"
    assert listing["returned_count"] == 1
    entry = listing["datasets"][0]
    assert entry["dataset_id"] == build["dataset_id"]
    assert entry["status"] == "COMPLETE"
    assert entry["logical_row_count"] == build["logical_row_count"]
    assert "US.MU" in entry["scope"]["symbols"]

    # Step 7: dataset-catalog-show by exact dataset_id.
    sixth = run_cli_subprocess(
        "dataset-catalog-show",
        "--snapshot-dir", str(snapshot_dir),
        "--dataset-id", build["dataset_id"],
        cwd=tmp_path,
    )
    assert sixth.returncode == 0, sixth.stderr
    assert sixth.stderr == ""
    shown = json.loads(sixth.stdout)
    assert shown["result"] == "SHOWN"
    assert shown["dataset"]["content_id"] == entry["content_id"]
    observed = shown["dataset"]["observed_metadata"]
    assert Path(observed["build_path"]) == dataset_dir
    assert observed["built_at"] == build["built_at"]


def test_empty_chain_through_catalog(tmp_path):
    """A legal EMPTY Canonical build produces zero requests, an EMPTY
    verified Dataset, and an EMPTY Catalog entry — EMPTY is a success,
    never a failure, and no bar is ever fabricated."""
    build = _make_empty_build(tmp_path)
    write_fixture_files(tmp_path)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(build.build_path),),
            feature_paths=("specs/simple_return.yaml",),
            label_paths=("specs/forward_return.yaml",),
            split_path="specs/chronological_split.json",
            symbols=("US.XYZ",),
            output_root="datasets",
            output_plan_path="generated-plan.json",
        ),
    )
    first = run_cli_subprocess(
        "sample-generate", "--plan", str(plan_path), cwd=tmp_path
    )
    assert first.returncode == 0, first.stderr
    generation = json.loads(first.stdout)
    assert generation["result"] == "SUCCESS"
    assert generation["generated_request_count"] == 0
    assert generation["canonical_build_count"] == 1

    second = run_cli_subprocess(
        "dataset-build", "--plan", str(tmp_path / "generated-plan.json"),
        cwd=tmp_path,
    )
    assert second.returncode == 0, second.stderr
    build_payload = json.loads(second.stdout)
    assert build_payload["result"] == "SUCCESS"
    assert build_payload["dataset_status"] == "EMPTY"
    assert build_payload["logical_row_count"] == 0
    verified = load_verified_dataset(build_payload["build_path"])
    assert verified.status == "EMPTY"
    assert len(verified.rows) == 0

    snapshot_root = tmp_path / "catalog-snapshots"
    third = run_cli_subprocess(
        "dataset-catalog-build",
        "--dataset-root", str(tmp_path / "datasets"),
        "--output-root", str(snapshot_root),
        "--built-at", BUILT_AT_ISO,
        cwd=tmp_path,
    )
    assert third.returncode == 0, third.stderr
    catalog = json.loads(third.stdout)
    assert catalog["result"] == "SUCCESS"
    assert catalog["dataset_count"] == 1
    snapshot_dir = Path(catalog["snapshot_path"])

    fourth = run_cli_subprocess(
        "dataset-catalog-list",
        "--snapshot-dir", str(snapshot_dir),
        "--status", "EMPTY",
        cwd=tmp_path,
    )
    assert fourth.returncode == 0, fourth.stderr
    listing = json.loads(fourth.stdout)
    assert listing["returned_count"] == 1
    assert listing["datasets"][0]["status"] == "EMPTY"
    assert listing["datasets"][0]["dataset_id"] == build_payload["dataset_id"]

    fifth = run_cli_subprocess(
        "dataset-catalog-list",
        "--snapshot-dir", str(snapshot_dir),
        "--status", "COMPLETE",
        cwd=tmp_path,
    )
    assert fifth.returncode == 0, fifth.stderr
    assert json.loads(fifth.stdout)["returned_count"] == 0

    sixth = run_cli_subprocess(
        "dataset-catalog-show",
        "--snapshot-dir", str(snapshot_dir),
        "--dataset-id", build_payload["dataset_id"],
        cwd=tmp_path,
    )
    assert sixth.returncode == 0, sixth.stderr
    shown = json.loads(sixth.stdout)
    assert shown["dataset"]["dataset_facts"]["status"] == "EMPTY"


# ---------------------------------------------------------------------------
# B. Determinism matrix (A: generation, B: Dataset identity, C: Catalog
# content identity, D: snapshot ID vs build path, E: snapshot relocation).
# ---------------------------------------------------------------------------


def test_matrix_a_generation_identical_across_roots(tmp_path, capsys):
    """Two independent generation runs in different root directories
    (identical relative content) produce identical generation content IDs
    and byte-identical generated build-plan files."""
    payloads = []
    plan_bytes = []
    for name in ("one", "two"):
        root = tmp_path / name
        build_dir = decode_canonical_fixture(root, under_dataset=True)
        write_fixture_files(root)
        plan_path = write_generation_plan(
            root / "generation-plan.json",
            relative_payload(
                build_dir, root, output_plan_path="generated-plan.json"
            ),
        )
        code, out, err = run_cli(
            ["sample-generate", "--plan", str(plan_path)], capsys
        )
        assert code == 0, err
        payloads.append(json.loads(out))
        plan_bytes.append((root / "generated-plan.json").read_bytes())
    assert payloads[0]["generation_content_id"] == FIXTURE_GENERATION_ID
    assert payloads[1]["generation_content_id"] == FIXTURE_GENERATION_ID
    assert payloads[0]["generated_request_count"] == payloads[1]["generated_request_count"]
    assert plan_bytes[0] == plan_bytes[1]


def test_matrix_b_dataset_identity_cwd_and_location_independent(tmp_path):
    """The same relative generation plan executed in two different working
    directories / absolute locations produces byte-identical generated plan
    bytes and identical Dataset identity (``dataset_id`` and
    ``logical_dataset_content_id``), while the recorded build paths differ."""
    results = []
    for name in ("one", "two"):
        root = tmp_path / name
        build_dir = decode_canonical_fixture(root, under_dataset=True)
        write_fixture_files(root)
        plan_path = write_generation_plan(
            root / "generation-plan.json",
            relative_payload(
                build_dir, root, output_plan_path="generated-plan.json"
            ),
        )
        gen = run_cli_subprocess(
            "sample-generate", "--plan", str(plan_path), cwd=root
        )
        assert gen.returncode == 0, gen.stderr
        generated_bytes = (root / "generated-plan.json").read_bytes()
        bld = run_cli_subprocess(
            "dataset-build", "--plan", str(root / "generated-plan.json"),
            cwd=root,
        )
        assert bld.returncode == 0, bld.stderr
        results.append((generated_bytes, json.loads(bld.stdout)))
    (bytes_one, build_one), (bytes_two, build_two) = results
    assert bytes_one == bytes_two
    assert build_one["dataset_id"] == build_two["dataset_id"]
    assert (
        build_one["logical_dataset_content_id"]
        == build_two["logical_dataset_content_id"]
    )
    assert build_one["logical_row_count"] == build_two["logical_row_count"]
    assert build_one["build_path"] != build_two["build_path"]


def test_matrix_c_catalog_content_identity_location_independent(
    tmp_path, capsys
):
    """The PR-5 Catalog content identity is location-independent: the same
    Dataset cataloged into two different snapshot output roots yields the
    same ``catalog_content_id`` (and, with the same explicit built_at, the
    same snapshot ID)."""
    state = _build_verified_catalog(tmp_path, capsys)
    other_root = tmp_path / "other-snapshots"
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent),
            "--output-root", str(other_root),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    assert code == 0, err
    second = json.loads(out)
    assert second["catalog_content_id"] == state.catalog["catalog_content_id"]
    assert second["snapshot_id"] == state.catalog["snapshot_id"]
    assert second["snapshot_path"] != state.catalog["snapshot_path"]


def test_matrix_d_snapshot_id_tracks_recorded_build_path(tmp_path, capsys):
    """The snapshot ID changes when the recorded build path changes (the
    snapshot records the observed Dataset location as historical text),
    while the Catalog content identity stays the same: content identity is
    location-independent, the snapshot ID is not."""
    state = _build_verified_catalog(tmp_path, capsys)
    relocated = tmp_path / "relocated-datasets"
    shutil.copytree(state.dataset_dir, relocated / state.dataset_dir.name)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(relocated),
            "--output-root", str(tmp_path / "snapshots-B"),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    assert code == 0, err
    second = json.loads(out)
    assert second["dataset_count"] == 1
    assert second["catalog_content_id"] == state.catalog["catalog_content_id"]
    assert second["snapshot_id"] != state.catalog["snapshot_id"]


def test_matrix_e_snapshot_relocation_verify_stable(tmp_path, capsys):
    """A committed Catalog snapshot relocated to another directory verifies
    unchanged: the snapshot ID and Catalog content identity never depend on
    where the snapshot directory physically sits."""
    state = _build_verified_catalog(tmp_path, capsys)
    relocated = tmp_path / "moved" / "snapshots"
    shutil.copytree(state.snapshot_dir, relocated / state.snapshot_dir.name)
    code, out, err = run_cli(
        [
            "dataset-catalog-verify",
            "--snapshot-dir", str(relocated / state.snapshot_dir.name),
        ],
        capsys,
    )
    assert code == 0, err
    summary = json.loads(out)
    assert summary["snapshot_id"] == state.catalog["snapshot_id"]
    assert summary["catalog_content_id"] == state.catalog["catalog_content_id"]


# ---------------------------------------------------------------------------
# C. Corruption cascade: every layer fails closed and never repairs.
# ---------------------------------------------------------------------------


def _corrupt_canonical(build_dir: Path, corruption: str) -> None:
    if corruption == "manifest":
        corrupt_manifest(build_dir)
    elif corruption == "resolution":
        corrupt_resolution(build_dir)
    elif corruption == "success-missing":
        # _SUCCESS content is not part of the reader's verification contract
        # (only existence, regular-file type, and link-free); its absence is.
        delete_member(build_dir, CANONICAL_SUCCESS_REL)
    elif corruption == "bars":
        corrupt_bars(build_dir)
    elif corruption == "deleted":
        delete_member(build_dir, CANONICAL_BARS_REL)
    else:
        raise AssertionError(corruption)


@pytest.mark.parametrize(
    "corruption",
    ["manifest", "resolution", "success-missing", "bars", "deleted"],
)
def test_corruption_cascade_canonical_fails_closed(tmp_path, capsys, corruption):
    """Every Canonical artifact member is strictly verified: a corrupted
    member fails ``sample-generate`` closed (exit 1, empty stdout, single
    failure JSON) and the corrupted bytes are never repaired or rewritten."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)
    _corrupt_canonical(build_dir, corruption)
    before = snapshot(build_dir)  # the corrupted state must stay as-is
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        relative_payload(
            build_dir, tmp_path, output_plan_path="generated-plan.json"
        ),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert failure["command"] == "sample-generate"
    assert failure["error_type"].endswith("CLIError")
    assert not (tmp_path / "generated-plan.json").exists()
    assert snapshot(build_dir) == before  # no repair, no rewrite, no cleanup


@pytest.mark.parametrize(
    "corruption",
    ["manifest", "resolution", "success-missing", "bars", "deleted"],
)
def test_corruption_cascade_canonical_reader_fails_closed(
    tmp_path, corruption
):
    """The verified reader itself rejects each corrupted member."""
    build_dir = decode_canonical_fixture(tmp_path)
    _corrupt_canonical(build_dir, corruption)
    with pytest.raises(
        (CanonicalArtifactValidationError, OSError, ValueError, KeyError)
    ):
        load_verified_canonical_build(build_dir)


@pytest.mark.parametrize(
    "corruption",
    [
        "bom",
        "dup-key",
        "unknown-field",
    ],
)
def test_corruption_cascade_build_plan_fails_closed(tmp_path, capsys, corruption):
    """A dataset-build plan with a UTF-8 BOM, a duplicate JSON key, or an
    unknown root field fails closed before any file is touched, and no
    Dataset output appears."""
    payload = default_build_plan_dict(canonical_dirs=["/never-used"])
    plan_path = tmp_path / "plan.json"
    if corruption == "bom":
        plan_path.write_bytes(
            b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
    elif corruption == "dup-key":
        plan_path.write_text(
            '{"plan_schema_version": "'
            + payload["plan_schema_version"]
            + '", "plan_schema_version": "'
            + payload["plan_schema_version"]
            + '"}',
            encoding="utf-8",
        )
    else:
        payload["surprise"] = 1
        write_json(plan_path, payload)
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(plan_path)], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert failure["command"] == "dataset-build"
    output_root = tmp_path / "out"
    if output_root.exists():
        assert list(output_root.iterdir()) == []


@pytest.mark.parametrize("corruption", ["bom"])
def test_corruption_cascade_generation_plan_bom_fails_closed(
    tmp_path, capsys, corruption
):
    """A generation plan with a UTF-8 BOM fails ``sample-generate`` closed
    and nothing is written."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)
    payload = relative_payload(
        build_dir, tmp_path, output_plan_path="generated-plan.json"
    )
    plan_path = tmp_path / "generation-plan.json"
    plan_path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert failure["command"] == "sample-generate"
    assert not (tmp_path / "generated-plan.json").exists()


def test_corruption_cascade_dataset_fails_closed(tmp_path, capsys):
    """A corrupted Dataset artifact fails ``load_verified_dataset`` and the
    Catalog builder rejects the corrupted candidate closed — the snapshot
    is never created from a corrupt Dataset."""
    state = _build_verified_catalog(tmp_path, capsys)
    dataset_parquet = state.dataset_dir / "dataset.parquet"
    with dataset_parquet.open("ab") as handle:
        handle.write(b"CORRUPTED-ACCEPTANCE")
    before = sha256_bytes(dataset_parquet.read_bytes())  # corrupted state
    with pytest.raises((Exception,)):  # any documented artifact error
        load_verified_dataset(str(state.dataset_dir))
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent),
            "--output-root", str(tmp_path / "snapshots-fail"),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    _assert_failed_json(code, out, err)
    assert sha256_bytes(dataset_parquet.read_bytes()) == before  # no repair
    out_root = tmp_path / "snapshots-fail"
    if out_root.exists():
        assert list(out_root.iterdir()) == []


@pytest.mark.parametrize(
    "corruption",
    ["catalog-json", "manifest", "success"],
)
@pytest.mark.parametrize(
    "command",
    ["dataset-catalog-verify", "dataset-catalog-list", "dataset-catalog-show"],
)
def test_corruption_cascade_catalog_snapshot_fails_closed(
    tmp_path, capsys, corruption, command
):
    """A corrupted Catalog snapshot member fails every read command closed;
    the corrupted bytes are never repaired."""
    state = _build_verified_catalog(tmp_path, capsys)
    if corruption == "catalog-json":
        target = state.snapshot_dir / "catalog.json"
    elif corruption == "manifest":
        target = state.snapshot_dir / "manifest.json"
    else:
        target = state.snapshot_dir / "_SUCCESS"
    with target.open("ab") as handle:
        handle.write(b"CORRUPTED-ACCEPTANCE")
    before = sha256_bytes(target.read_bytes())  # corrupted state
    argv = [command, "--snapshot-dir", str(state.snapshot_dir)]
    if command == "dataset-catalog-show":
        argv += ["--dataset-id", state.build["dataset_id"]]
    code, out, err = run_cli(argv, capsys)
    _assert_failed_json(code, out, err)
    assert sha256_bytes(target.read_bytes()) == before  # no repair


# ---------------------------------------------------------------------------
# D. Recovery contract: Recovery != repair.
# ---------------------------------------------------------------------------


def test_recovery_partial_generation_output_cleaned(tmp_path, capsys):
    """A failed generation leaves no partial output plan file behind."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)
    corrupt_manifest(build_dir)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        relative_payload(
            build_dir, tmp_path, output_plan_path="generated-plan.json"
        ),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    _assert_failed_json(code, out, err)
    assert not (tmp_path / "generated-plan.json").exists()


def test_recovery_failed_dataset_build_leaves_no_build_dir(tmp_path, capsys):
    """A dataset-build that fails on a corrupted plan leaves no Dataset
    directory (and no staging residue) under the output root."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        relative_payload(
            build_dir, tmp_path, output_plan_path="generated-plan.json"
        ),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    assert code == 0, err
    generated = tmp_path / "generated-plan.json"
    with generated.open("ab") as handle:
        handle.write(b"\x00junk")
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(generated)], capsys
    )
    _assert_failed_json(code, out, err)
    output_root = tmp_path / "datasets"
    if output_root.exists():
        assert list(output_root.iterdir()) == []


def test_recovery_failed_catalog_build_leaves_no_snapshot(tmp_path, capsys):
    """A catalog build that fails on a corrupted Dataset candidate leaves no
    snapshot directory and no staging residue under the output root."""
    state = _build_verified_catalog(tmp_path, capsys)
    with (state.dataset_dir / "dataset.parquet").open("ab") as handle:
        handle.write(b"CORRUPTED-ACCEPTANCE")
    out_root = tmp_path / "snapshots-fail"
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent),
            "--output-root", str(out_root),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    _assert_failed_json(code, out, err)
    assert not out_root.exists()


def test_recovery_committed_dataset_never_deleted_on_rerun(tmp_path, capsys):
    """Rerunning an identical dataset-build returns the committed build
    unchanged (``created_new_build`` False); the committed final is never
    deleted or rewritten."""
    state = _build_verified_catalog(tmp_path, capsys)
    before = snapshot(state.dataset_dir)
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(tmp_path / "generated-plan.json")],
        capsys,
    )
    assert code == 0, err
    rerun = json.loads(out)
    assert rerun["result"] == "SUCCESS"
    assert rerun["created_new_build"] is False
    assert rerun["dataset_id"] == state.build["dataset_id"]
    assert rerun["build_path"] == state.build["build_path"]
    assert snapshot(state.dataset_dir) == before


def test_recovery_committed_snapshot_never_deleted_on_rerun(tmp_path, capsys):
    """Rerunning an identical catalog build returns the committed snapshot
    unchanged (``created_new_snapshot`` False); the committed final is never
    deleted or rewritten."""
    state = _build_verified_catalog(tmp_path, capsys)
    before = snapshot(state.snapshot_dir)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent),
            "--output-root", str(state.snapshot_dir.parent),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    assert code == 0, err
    rerun = json.loads(out)
    assert rerun["result"] == "SUCCESS"
    assert rerun["created_new_snapshot"] is False
    assert rerun["snapshot_id"] == state.catalog["snapshot_id"]
    assert snapshot(state.snapshot_dir) == before


def test_recovery_foreign_staging_never_adopted(tmp_path, capsys):
    """A pre-existing staging directory whose path is the exact staging path
    of the snapshot being built is crash residue or a concurrent build: the
    catalog build fails closed and never adopts, deletes, or overwrites it.
    (A differently-named ``.staging-*`` child is foreign residue, never
    entered and never touched, exactly like any other non-snapshot child.)"""
    state = _build_verified_catalog(tmp_path, capsys)
    out_root = tmp_path / "snapshots-residue"
    staging = out_root / f".staging-{state.catalog['snapshot_id']}"
    staging.mkdir(parents=True)
    marker = staging / "marker.txt"
    marker.write_text("foreign", encoding="utf-8")
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent),
            "--output-root", str(out_root),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    _assert_failed_json(code, out, err)
    assert marker.read_text(encoding="utf-8") == "foreign"
    assert staging.exists()

    foreign = out_root / ".staging-deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    foreign.mkdir(parents=True)
    foreign_marker = foreign / "marker.txt"
    foreign_marker.write_text("unrelated", encoding="utf-8")
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent),
            "--output-root", str(tmp_path / "snapshots-ok"),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    assert code == 0, err
    assert json.loads(out)["dataset_count"] == 1
    assert foreign_marker.read_text(encoding="utf-8") == "unrelated"


def test_recovery_foreign_dataset_child_never_adopted(tmp_path, capsys):
    """A foreign (non-64-hex) directory under the dataset root is ignored,
    never entered, and never adopted; the catalog build succeeds over the
    real Dataset only."""
    state = _build_verified_catalog(tmp_path, capsys)
    foreign = state.dataset_dir.parent / "README.md"
    foreign.write_text("documentation", encoding="utf-8")
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent),
            "--output-root", str(tmp_path / "snapshots-ok"),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    assert code == 0, err
    assert json.loads(out)["dataset_count"] == 1
    assert foreign.read_text(encoding="utf-8") == "documentation"


# ---------------------------------------------------------------------------
# E. Security matrix: links, dot components, wrong basenames, ambiguous
# duplicates — all fail closed.
# ---------------------------------------------------------------------------


def test_security_symlinked_canonical_dir_fails_closed(tmp_path, capsys):
    """A symlink (or junction) to a canonical build directory is rejected;
    the link target is never followed."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)
    link = tmp_path / "data" / "canonical" / "link-to-build"
    _make_symlink_or_skip(build_dir, link)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(link),),
            feature_paths=("specs/simple_return.yaml",),
            label_paths=("specs/forward_return.yaml",),
            split_path="specs/chronological_split.json",
            output_root="datasets",
            output_plan_path="generated-plan.json",
        ),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    _assert_failed_json(code, out, err)


def test_security_symlinked_generation_plan_fails_closed(tmp_path, capsys):
    """A symlinked generation-plan file is rejected."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)
    real = write_generation_plan(
        tmp_path / "real-plan.json",
        relative_payload(
            build_dir, tmp_path, output_plan_path="generated-plan.json"
        ),
    )
    link = tmp_path / "generation-plan.json"
    _make_symlink_or_skip(real, link)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(link)], capsys
    )
    _assert_failed_json(code, out, err)


def test_security_symlinked_dataset_candidate_fails_closed(tmp_path, capsys):
    """A symlinked Dataset build directory is rejected as a Catalog
    candidate; the link target is never adopted."""
    state = _build_verified_catalog(tmp_path, capsys)
    link = tmp_path / "dataset-link"
    _make_symlink_or_skip(state.dataset_dir, link)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--candidate-build-dir", str(link),
            "--output-root", str(tmp_path / "snapshots-link"),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    _assert_failed_json(code, out, err)


def test_security_symlinked_snapshot_dir_fails_closed(tmp_path, capsys):
    """A symlinked Catalog snapshot directory is rejected by verify."""
    state = _build_verified_catalog(tmp_path, capsys)
    link = tmp_path / "snapshot-link"
    _make_symlink_or_skip(state.snapshot_dir, link)
    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", str(link)], capsys
    )
    _assert_failed_json(code, out, err)


def test_security_dot_components_fail_closed(tmp_path, capsys):
    """Lexical ``.`` / ``..`` components are rejected on every CLI path
    boundary."""
    state = _build_verified_catalog(tmp_path, capsys)
    code, out, err = run_cli(
        [
            "sample-generate",
            "--plan", str(tmp_path / ".." / "generation-plan.json"),
        ],
        capsys,
    )
    _assert_failed_json(code, out, err)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(state.dataset_dir.parent / ".."),
            "--output-root", str(tmp_path / "snapshots-dot"),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    _assert_failed_json(code, out, err)
    code, out, err = run_cli(
        [
            "dataset-catalog-verify",
            "--snapshot-dir", str(state.snapshot_dir.parent / "."),
        ],
        capsys,
    )
    _assert_failed_json(code, out, err)


def test_security_wrong_basename_fails_closed(tmp_path, capsys):
    """A directory whose basename does not carry its own identity is
    rejected: the Canonical build dir must be ``build_id=<id>``, the Dataset
    dir must be the 64-hex ``dataset_id``, and the snapshot dir must be the
    64-hex ``snapshot_id``."""
    build_dir = decode_canonical_fixture(tmp_path)
    renamed = build_dir.parent / "wrong-name"
    build_dir.rename(renamed)
    with pytest.raises(
        (CanonicalArtifactValidationError, OSError, ValueError, KeyError)
    ):
        load_verified_canonical_build(renamed)

    state = _build_verified_catalog(tmp_path, capsys)
    moved_dataset = state.dataset_dir.parent / "not-hex"
    state.dataset_dir.rename(moved_dataset)
    with pytest.raises(Exception):
        load_verified_dataset(str(moved_dataset))

    moved_snapshot = state.snapshot_dir.parent / "not-hex-snapshot"
    state.snapshot_dir.rename(moved_snapshot)
    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", str(moved_snapshot)],
        capsys,
    )
    _assert_failed_json(code, out, err)


def test_security_ambiguous_duplicate_dataset_location_fails_closed(
    tmp_path, capsys
):
    """The same Dataset observed at two different locations is ambiguous:
    the catalog build fails closed and never picks one silently."""
    state = _build_verified_catalog(tmp_path, capsys)
    second = tmp_path / "datasets-copy"
    shutil.copytree(state.dataset_dir, second / state.dataset_dir.name)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--candidate-build-dir", str(state.dataset_dir),
            "--candidate-build-dir", str(second / state.dataset_dir.name),
            "--output-root", str(tmp_path / "snapshots-ambiguous"),
            "--built-at", BUILT_AT_ISO,
        ],
        capsys,
    )
    failure = _assert_failed_json(code, out, err)
    assert "ambiguous duplicate Dataset location" in failure["error"]


# ---------------------------------------------------------------------------
# F. Read-only proof: verify / list / show never write and survive Dataset
# deletion (the recorded build path is historical metadata only).
# ---------------------------------------------------------------------------


def test_verify_list_show_read_only_and_survive_dataset_deletion(
    tmp_path, capsys
):
    """verify / list / show never write to the snapshot tree or the Dataset
    tree (byte-level no-write proof), and keep working after the Dataset
    tree — and the Canonical tree — are deleted: the recorded build path is
    historical metadata, never reloaded."""
    state = _build_verified_catalog(tmp_path, capsys)
    before_snapshot = snapshot(state.snapshot_dir)
    before_dataset = snapshot(state.dataset_dir)

    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", str(state.snapshot_dir)],
        capsys,
    )
    assert code == 0, err
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", str(state.snapshot_dir)],
        capsys,
    )
    assert code == 0, err
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(state.snapshot_dir),
            "--dataset-id", state.build["dataset_id"],
        ],
        capsys,
    )
    assert code == 0, err

    assert snapshot(state.snapshot_dir) == before_snapshot
    assert snapshot(state.dataset_dir) == before_dataset

    shutil.rmtree(state.dataset_dir)
    shutil.rmtree(state.build_dir)
    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", str(state.snapshot_dir)],
        capsys,
    )
    assert code == 0, err
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", str(state.snapshot_dir)],
        capsys,
    )
    assert code == 0, err
    shown = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(state.snapshot_dir),
            "--dataset-id", state.build["dataset_id"],
        ],
        capsys,
    )
    assert shown[0] == 0, shown[2]
    observed = json.loads(shown[1])["dataset"]["observed_metadata"]
    assert Path(observed["build_path"]) == state.dataset_dir


# ---------------------------------------------------------------------------
# G. Operator usability: strict JSON success / failure contracts.
# ---------------------------------------------------------------------------


def test_all_six_commands_failure_json_contract(tmp_path, capsys):
    """Every CLI failure is exactly: exit 1, empty stdout, one JSON object
    on stderr with the six fixed contract keys."""
    state = _build_verified_catalog(tmp_path, capsys)
    failing = [
        ["sample-generate", "--plan", str(tmp_path / "missing-plan.json")],
        [
            "dataset-build",
            "--plan", str(tmp_path / "missing-build-plan.json"),
        ],
        [
            "dataset-catalog-build",
            "--dataset-root", str(tmp_path / "missing-datasets"),
            "--output-root", str(tmp_path / "snapshots-missing"),
            "--built-at", BUILT_AT_ISO,
        ],
        [
            "dataset-catalog-verify",
            "--snapshot-dir", str(tmp_path / "missing-snapshot"),
        ],
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(tmp_path / "missing-snapshot"),
        ],
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(tmp_path / "missing-snapshot"),
            "--dataset-id", state.build["dataset_id"],
        ],
    ]
    for argv in failing:
        code, out, err = run_cli(argv, capsys)
        failure = _assert_failed_json(code, out, err)
        assert set(failure) == FAILURE_FIELDS
        assert failure["result"] == "FAILED"
        assert failure["error_type"].endswith("CLIError")
        assert failure["error"]
