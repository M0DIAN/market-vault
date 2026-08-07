"""PR-8: static reference artifact portability tests (PyArrow 24 / 25).

The static Canonical artifact frozen at PR-8 time (``tests/fixtures/
v060_portability/canonical_fixture.b64``, produced by PyArrow 25.0.0) must
decode, verify, and reproduce both frozen regression values unchanged on
every supported PyArrow writer version — in particular on the CI
``portability-pyarrow24`` job (``pyarrow==24.0.0``).

Covers: bundle well-formedness and provenance metadata, strict decode,
``load_verified_canonical_build`` over the decoded artifact, the frozen
generation content id (core chain) and the frozen relative build-plan sha256
(CLI chain), hive-style parent directory reads, POSIX path text in the
manifest, snapshot relocation identity stability, and the no-OS-separator
identity invariants. Fully offline.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pyarrow
import pytest

from market_vault.canonical import load_verified_canonical_build
from market_vault.dataset import (
    SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
    DatasetScope,
    SampleGenerationPlan,
    SampleGenerationRule,
    generate_sample_requests,
)

from v060_acceptance_helpers import (
    BUILT_AT,
    CANONICAL_BARS_REL,
    CANONICAL_MANIFEST_REL,
    CANONICAL_RESOLUTION_REL,
    CANONICAL_SUCCESS_REL,
    FIXTURE_BUILD_ID,
    FIXTURE_BUNDLE,
    FIXTURE_GENERATION_ID,
    FIXTURE_METADATA,
    FROZEN_RELATIVE_PLAN_SHA256,
    SPLIT_SPEC_CLI_PAYLOAD,
    SPLIT_SPEC_CORE_PAYLOAD,
    decode_canonical_fixture,
    fixture_metadata,
    relative_payload,
    run_cli,
    write_fixture_files,
    write_generation_plan,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# A. Bundle well-formedness and provenance.
# ---------------------------------------------------------------------------


def test_bundle_lines_are_strict_tsv_with_integrity_hashes():
    """Every bundle line parses as ``<POSIX path>\\t<size>\\t<sha256>\\t
    <base64>`` with strict member-path checks, and every member's payload
    matches its recorded size and sha256 (self-checking fixture)."""
    lines = FIXTURE_BUNDLE.read_text(encoding="ascii").splitlines()
    assert len(lines) >= 4  # _SUCCESS + manifest + resolution + bars parquet
    member_paths = []
    for line in lines:
        member, size_text, digest, encoded = line.split("\t")
        parts = member.split("/")
        assert member and not member.startswith("/"), member
        assert not any(part in (".", "..", "") for part in parts), member
        assert "\\" not in member, member
        assert not (len(member) > 1 and member[1] == ":"), member
        payload = base64.b64decode(encoded)
        assert len(payload) == int(size_text), member
        assert hashlib.sha256(payload).hexdigest() == digest, member
        member_paths.append(member)
    assert CANONICAL_SUCCESS_REL in member_paths
    assert CANONICAL_MANIFEST_REL in member_paths
    assert CANONICAL_RESOLUTION_REL in member_paths
    assert CANONICAL_BARS_REL in member_paths


def test_fixture_metadata_records_provenance_and_frozen_values():
    """The metadata JSON records the producing writer, the artifact
    contract, the decode contract, and the two frozen regression values."""
    metadata = fixture_metadata()
    assert metadata["fixture_name"] == "canonical_fixture"
    assert metadata["produced_by_pyarrow_version"] == "25.0.0"
    assert metadata["canonical_build_id"] == FIXTURE_BUILD_ID
    assert metadata["frozen_generation_content_id"] == FIXTURE_GENERATION_ID
    assert (
        metadata["frozen_relative_plan_sha256"] == FROZEN_RELATIVE_PLAN_SHA256
    )
    assert "POSIX" in metadata["bundle_format"]
    assert metadata["logical_content"]["bar_count"] == 10
    assert metadata["logical_content"]["symbol"] == "US.MU"
    recorded = {m["path"] for m in metadata["members"]}
    assert recorded == {
        CANONICAL_SUCCESS_REL,
        CANONICAL_MANIFEST_REL,
        CANONICAL_RESOLUTION_REL,
        CANONICAL_BARS_REL,
    }


def test_fixture_reproduces_under_audited_pyarrow_writer():
    """The artifact was frozen under PyArrow 25.0.0 and the portability
    audit covers exactly the two audited writer versions (24.0.0 and
    25.0.0); the CI ``portability-pyarrow24`` job therefore proves the
    frozen regression values on the other audited writer."""
    major, minor, _ = (int(part) for part in pyarrow.__version__.split("."))
    assert (major, minor) in ((24, 0), (25, 0)), pyarrow.__version__


# ---------------------------------------------------------------------------
# B. Static artifact -> verified Canonical build.
# ---------------------------------------------------------------------------


def test_static_artifact_loads_as_verified_build(tmp_path):
    build_dir = decode_canonical_fixture(tmp_path)
    verified = load_verified_canonical_build(build_dir)
    assert verified.canonical_build_id == FIXTURE_BUILD_ID
    assert verified.status == "COMPLETE"
    assert verified.gap_count == 0
    assert len(verified.bars) == 10
    assert verified.normalized_request.symbols == ("US.MU",)
    assert verified.normalized_request.trade_dates == (date(2026, 7, 1),)
    assert verified.normalized_request.interval == "1m"
    assert verified.normalized_request.requested_session == "ALL"
    assert verified.normalized_request.adjustment == "NONE"
    assert verified.normalized_request.source_schema_version == "10.9"
    assert verified.build_path == build_dir
    # The recorded build path is descriptive metadata only, never an
    # identity input; the identity values are pure 64-hex.
    assert HEX64.fullmatch(verified.canonical_build_id)
    assert HEX64.fullmatch(verified.canonical_content_id)
    assert HEX64.fullmatch(verified.resolution_content_id)
    assert HEX64.fullmatch(verified.gap_content_id)


def test_static_artifact_bars_logical_content(tmp_path):
    verified = load_verified_canonical_build(
        decode_canonical_fixture(tmp_path)
    )
    bars = verified.bars
    assert all(bar.code == "US.MU" for bar in bars)
    assert all(bar.interval == "1m" for bar in bars)
    first, last = bars[0], bars[-1]
    # event_time is stored in UTC (13:30 UTC == 09:30 America/New_York).
    assert first.event_time.strftime("%Y-%m-%d %H:%M") == "2026-07-01 13:30"
    assert last.event_time.strftime("%Y-%m-%d %H:%M") == "2026-07-01 13:39"
    assert first.open == 100.0
    # Deterministic ordering: event_time ASC, then canonical_bar_key ASC.
    event_times = [bar.event_time for bar in bars]
    assert event_times == sorted(event_times)
    bar_keys = [bar.canonical_bar_key for bar in bars]
    assert all(HEX64.fullmatch(key) for key in bar_keys)


def test_hive_style_parent_directories_read(tmp_path):
    """The bars Parquet lives under hive-style partition directories
    (``bars/interval=1m/...``); the verified reader must read it with
    ``pq.ParquetFile`` semantics and never mis-infer partitions."""
    build_dir = decode_canonical_fixture(tmp_path)
    bars_path = build_dir / CANONICAL_BARS_REL
    assert bars_path.is_file()
    verified = load_verified_canonical_build(build_dir)
    assert len(verified.bars) == 10
    assert all(
        HEX64.fullmatch(bar.physical_snapshot_hash) for bar in verified.bars
    )


def test_manifest_paths_are_posix_text(tmp_path):
    """Every stored path string in the manifest (output files and snapshot
    provenance) is POSIX slash text with no OS separators, so the artifact
    is byte-identical on every platform."""
    build_dir = decode_canonical_fixture(tmp_path)
    manifest = json.loads(
        (build_dir / CANONICAL_MANIFEST_REL).read_text(encoding="utf-8")
    )
    recorded = set()
    for entry in manifest["output_files"]:
        recorded.add(entry["relative_path"])
    for entry in manifest["source_snapshot_provenance"]:
        recorded.add(entry["snapshot_file"])
    assert recorded
    for path_text in recorded:
        # POSIX slash text: no OS separators, no ".", "..", empty parts
        # (root-level files legitimately carry no "/").
        assert "\\" not in path_text
        assert not any(
            part in (".", "..", "") for part in path_text.split("/")
        )
    assert any("bars/" in path_text for path_text in recorded)


# ---------------------------------------------------------------------------
# C. Frozen regression values reproduce from the decoded artifact.
# ---------------------------------------------------------------------------


def test_frozen_generation_content_id_reproduces(tmp_path):
    """The core chain over the decoded artifact reproduces the frozen
    generation content id exactly (PyArrow-writer independent)."""
    build_dir = decode_canonical_fixture(tmp_path)
    feature_paths, label_paths, split_path = write_fixture_files(
        tmp_path, split_payload=SPLIT_SPEC_CORE_PAYLOAD
    )
    plan = SampleGenerationPlan(
        generation_plan_schema_version=SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
        canonical_build_dirs=(str(build_dir),),
        feature_spec_files=feature_paths,
        label_spec_files=label_paths,
        split_spec_file=split_path,
        scope=DatasetScope(
            symbols=("US.MU",),
            trade_dates=(date(2026, 7, 1),),
            interval="1m",
            adjustment="NONE",
            requested_session="ALL",
        ),
        generation_rule=SampleGenerationRule(
            rule_schema_version=SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
            feature_window_bars=3,
            label_window_bars=2,
            stride_bars=2,
            anchor_source="VERIFIED_CANONICAL_BARS",
            anchor_rule="FEATURE_WINDOW_CLOSE",
            cross_day_policy="REJECT",
        ),
        dataset_as_of=None,
        output_root="datasets",
        built_at=BUILT_AT,
        output_plan_path="plans/generated/plan-1.json",
    )
    result = generate_sample_requests(plan, path_base=tmp_path)
    assert result.generation_content_id == FIXTURE_GENERATION_ID


def test_frozen_relative_plan_bytes_reproduce(tmp_path, capsys):
    """The CLI chain with relative paths over the decoded artifact
    reproduces the frozen relative build-plan sha256 exactly."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path, split_payload=SPLIT_SPEC_CLI_PAYLOAD)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        relative_payload(build_dir, tmp_path, output_plan_path="generated-plan.json"),
    )
    code, out, err = run_cli(["sample-generate", "--plan", str(plan_path)], capsys)
    assert code == 0, err
    generated = (tmp_path / "generated-plan.json").read_bytes()
    assert (
        hashlib.sha256(generated).hexdigest() == FROZEN_RELATIVE_PLAN_SHA256
    )


# ---------------------------------------------------------------------------
# D. Snapshot relocation and identity invariants.
# ---------------------------------------------------------------------------


def test_snapshot_relocation_keeps_identity_and_content(tmp_path):
    """Copying the decoded build tree to a different parent (a relocated
    snapshot) changes nothing about the verified identity or the logical
    content; only the recorded build path (descriptive metadata) changes."""
    build_dir = decode_canonical_fixture(tmp_path)
    original = load_verified_canonical_build(build_dir)
    relocated_root = tmp_path / "relocated" / "elsewhere"
    relocated_dir = relocated_root / f"build_id={FIXTURE_BUILD_ID}"
    shutil.copytree(build_dir, relocated_dir)
    relocated = load_verified_canonical_build(relocated_dir)
    assert relocated.build_path == relocated_dir
    assert relocated.build_path != original.build_path
    assert relocated.canonical_build_id == original.canonical_build_id
    assert relocated.canonical_content_id == original.canonical_content_id
    assert relocated.resolution_content_id == original.resolution_content_id
    assert relocated.gap_content_id == original.gap_content_id
    assert [
        (bar.event_time.isoformat(), bar.close) for bar in relocated.bars
    ] == [(bar.event_time.isoformat(), bar.close) for bar in original.bars]


def test_identity_values_contain_no_os_separators(tmp_path):
    """No identity value or source file reference may carry an OS separator
    (backslash on Windows); every identity value is pure lowercase hex."""
    verified = load_verified_canonical_build(
        decode_canonical_fixture(tmp_path)
    )
    hex_values = [
        verified.canonical_build_id,
        verified.canonical_content_id,
        verified.resolution_content_id,
        verified.gap_content_id,
        *verified.canonical_row_version_ids,
        *[bar.canonical_bar_key for bar in verified.bars],
        *[bar.physical_snapshot_hash for bar in verified.bars],
        *[bar.logical_source_rows_hash for bar in verified.bars],
        *[ref.physical_snapshot_hash for ref in verified.source_snapshot_provenance],
        *[ref.logical_source_rows_hash for ref in verified.source_snapshot_provenance],
    ]
    assert hex_values
    for value in hex_values:
        assert "\\" not in value
        assert "/" not in value
        assert HEX64.fullmatch(value)
    for ref in verified.source_snapshot_provenance:
        assert "\\" not in ref.snapshot_file
        assert "/" in ref.snapshot_file
