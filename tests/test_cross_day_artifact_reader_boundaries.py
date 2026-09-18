"""Cohort/recorded authority boundaries; memory relocation is not OS qualification."""

import pytest

from market_vault.cross_day_dataset import reader as r, materialization as m, execution
from market_vault.cross_day_dataset._artifact_encoding import canonical_json, decode_json
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError as Error
from test_cross_day_artifact_publication_state import setup, publish
from test_cross_day_artifact_manifest import fixture


def test_old_readers_reject_cross_day_discriminator(tmp_path, monkeypatch):
    from market_vault.dataset.manifest import validate_dataset_manifest
    from market_vault.multi_source import reader as old
    _, _, _, manifest = fixture(tmp_path)
    with pytest.raises(ValueError):
        validate_dataset_manifest(decode_json(manifest))
    monkeypatch.setattr(old, "safe_path", lambda path, **kw: path)
    monkeypatch.setattr(old, "object_identity", lambda path: (1, 2))
    monkeypatch.setattr(old, "read_bytes", lambda path: manifest)
    with pytest.raises(ValueError, match="unsupported manifest version/fields"):
        old.load_verified_multi_source_dataset(tmp_path / "old-reader-probe")


@pytest.mark.parametrize("version", ["dataset-manifest-v1", "multi-source-dataset-manifest-v1", "observation-manifest-v1"])
def test_reader_rejects_old_manifest_discriminators(tmp_path, monkeypatch, version):
    _, result, model = setup(tmp_path, monkeypatch)
    final = publish(result, model).verified.build_path
    payload = decode_json(model.nodes[final / "manifest.json"][2])
    payload["manifest_schema_version"] = version
    model.mutate(final / "manifest.json", canonical_json(payload))
    with pytest.raises(Error):
        r.load_verified_multi_source_cross_day_dataset(final)


def test_relocation_and_full_observation_proofs(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch, two_proofs=True)
    final = publish(result, model).verified.build_path
    original = r.load_verified_multi_source_cross_day_dataset(final)
    old_root, new_root = model.root, model.root.parent / "SECOND_IN_MEMORY_ROOT"
    model.nodes = {new_root / path.relative_to(old_root): (object(), n[1], n[2]) for path, n in model.nodes.items()}
    model.root = new_root
    relocated = r.load_verified_multi_source_cross_day_dataset(new_root / final.name)
    assert relocated.dataset_id == original.dataset_id == result.dataset_id
    assert relocated.identity_input.observation_input_proofs == result.identity_input.observation_input_proofs
    assert len(relocated.identity_input.observation_builds) == len(result.observation_builds)
    assert len(relocated.identity_input.observation_input_proofs) == 2
    assert len({p.observation_build_id for p in relocated.identity_input.observation_input_proofs}) == 1
    assert len({p.coverage_proof_available_at for p in relocated.identity_input.observation_input_proofs}) == 2
    assert relocated.rows == original.rows


def test_output_root_independence(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    first = publish(result, model)
    model.root = model.root.parent / "DIFFERENT_IN_MEMORY_OUTPUT_ROOT"
    model.nodes[model.root] = (object(), True, b"")
    second = publish(result, model)
    assert first.created_new_build is second.created_new_build is True
    assert first.verified.dataset_id == second.verified.dataset_id == result.dataset_id
    assert first.verified.manifest_payload["identity"] == second.verified.manifest_payload["identity"]


def test_reader_never_reexecutes_upstream_or_enrolls(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    final = publish(result, model).verified.build_path
    import market_vault.dataset.pit as pit
    import market_vault.ts2_feature.execution as ts2
    import market_vault.observation.pit as observation
    import market_vault.multi_source.feature_execution as features
    import market_vault.cross_day.assembly as assembly
    import market_vault.cross_day.execution as labels
    def forbidden(*args, **kwargs):
        raise AssertionError("reader reran execution/selection or enrolled a live result")
    for module, names in (
        (execution, ("join_multi_source_cross_day_dataset", "_require_live_issued_multi_source_cross_day_dataset_result",
                     "_require_live_issued_multi_source_cross_day_dataset_artifact_facts")),
        (pit, ("assemble_point_in_time_samples", "_select", "_assemble_sample")), (ts2, ("execute_ts2_features",)),
        (observation, ("assemble_observation_pit_sidecar",)), (features, ("execute_observation_features",)),
        (assembly, ("assemble_cross_day_labels", "_facts")), (labels, ("execute_cross_day_labels",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    assert r.load_verified_multi_source_cross_day_dataset(final).dataset_id == result.dataset_id
