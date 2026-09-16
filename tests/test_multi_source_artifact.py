"""Real offline A4.3 artifact fixtures and end-to-end authority regressions."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone, timedelta
import hashlib
import shutil

import pytest

from market_vault.multi_source import (
    orchestrate_multi_source_dataset_build, materialize_multi_source_dataset_build,
    load_verified_multi_source_dataset, MultiSourceDatasetArtifactError,
)
from market_vault.multi_source._serialization import canonical_json, read_json
from test_multi_source_orchestration import fixtures, artifacts, observation_factory, inputs, feature_spec, spec

BUILT_AT = datetime(2026, 1, 3, tzinfo=timezone.utc)


@pytest.fixture
def candidate(fixtures, observation_factory):
    return orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory()))


@pytest.fixture
def artifact(candidate, tmp_path):
    return materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "output", built_at=BUILT_AT).build_dir


def rewrite(root, name, data):
    (root / name).write_bytes(data)
    manifest = read_json((root / "manifest.json").read_bytes())
    for fact in manifest["output_files"]:
        if fact["relative_path"] == name:
            fact["byte_size"], fact["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    (root / "manifest.json").write_bytes(canonical_json(manifest))


def test_complete_roundtrip_and_idempotence(candidate, tmp_path):
    first = materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "output", built_at=BUILT_AT)
    assert first.created_new_build
    verified = load_verified_multi_source_dataset(first.build_dir)
    assert verified.dataset_id == candidate.dataset_id
    assert verified.rows == candidate.rows
    assert verified.sample_audit == candidate.sample_audit
    assert verified.observation_evidence == candidate.observation_evidence
    assert verified.observation_feature_result == candidate.observation_feature_result
    before = {p.relative_to(first.build_dir): p.read_bytes() for p in first.build_dir.rglob("*") if p.is_file()}
    second = materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "output", built_at=BUILT_AT + timedelta(days=1))
    assert not second.created_new_build
    assert before == {p.relative_to(first.build_dir): p.read_bytes() for p in first.build_dir.rglob("*") if p.is_file()}


@pytest.mark.parametrize("case", ["bar", "observation", "both", "label", "zero"])
def test_empty_and_incomplete_keep_provenance(fixtures, observation_factory, tmp_path, case):
    changes = {}
    if case in ("bar", "both"):
        changes["bar_feature_specs"] = (feature_spec(window_bars=100),)
    if case in ("observation", "both"):
        changes["observation_feature_specs"] = (spec(max_age_us=1),)
    if case == "label":
        changes["canonical_builds"] = (fixtures.a,)
    if case == "zero":
        changes["requests"] = ()
    result = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory(), **changes))
    published = materialize_multi_source_dataset_build(result, output_root=tmp_path / "out", built_at=BUILT_AT)
    verified = load_verified_multi_source_dataset(published.build_dir)
    assert verified.rows == result.rows
    assert verified.sample_audit == result.sample_audit
    assert verified.observation_evidence == result.observation_evidence
    assert verified.manifest.identity_input == result.identity_input
    assert verified.status == ("COMPLETE" if case == "label" else "EMPTY")


def test_same_logical_build_distinct_physical_proofs(fixtures, observation_factory, tmp_path):
    one, two = observation_factory(created_shift=300), observation_factory(created_shift=400)
    assert one.observation_build_id == two.observation_build_id
    result = orchestrate_multi_source_dataset_build(**inputs(fixtures, one, observation_builds=(one, two)))
    verified = materialize_multi_source_dataset_build(result, output_root=tmp_path / "out", built_at=BUILT_AT).build
    assert len(verified.observation_evidence[0].build_pins) == 2
    assert verified.manifest.identity_input.observation_build_pin_ids == result.identity_input.observation_build_pin_ids
    assert {p.coverage_proof_available_at for p in verified.observation_evidence[0].build_pins} == {one.created_at, two.created_at}


def test_relocation_and_built_at_are_nonidentity(candidate, artifact, tmp_path):
    moved = tmp_path / "relocated" / artifact.name
    shutil.copytree(artifact, moved)
    assert load_verified_multi_source_dataset(moved).dataset_id == candidate.dataset_id
    other = materialize_multi_source_dataset_build(candidate, output_root=tmp_path / "other", built_at=BUILT_AT + timedelta(days=1))
    assert other.dataset_id == candidate.dataset_id
    assert (other.build_dir / "manifest.json").read_bytes() != (artifact / "manifest.json").read_bytes()


def test_deep_immutability(artifact):
    build = load_verified_multi_source_dataset(artifact)
    with pytest.raises(FrozenInstanceError):
        build.dataset_id = "0" * 64
    with pytest.raises(TypeError):
        build.bar_associations[0]["code"] = "BAD"
    with pytest.raises(TypeError):
        build.build_report["completion"]["complete_count"] = 5
    with pytest.raises(FrozenInstanceError):
        build.observation_evidence[0].build_pins[0].coverage_proof_available_at = BUILT_AT
    with pytest.raises(TypeError):
        build.split_result.assignment_rows[0]["sample_key"] = "0" * 64


def test_old_reader_rejects_new_artifact(artifact):
    from market_vault.dataset import load_verified_dataset
    with pytest.raises(ValueError):
        load_verified_dataset(artifact)
