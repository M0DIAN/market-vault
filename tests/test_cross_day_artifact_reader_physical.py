"""Retained-object reader closure using the explicit memory fault model, not qualification."""

import pytest

from market_vault.cross_day_dataset import reader as r, materialization as m
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError as Error
from test_cross_day_artifact_publication_state import setup, publish


MEMBERS = (
    "dataset.parquet", "feature_pit.json", "canonical_evidence.json", "ts2_features.json",
    "observation_pit.json", "observation_evidence.json", "observation_features.json",
    "cross_day_association.json", "cross_day_values.json", "schedule.json", "sample_audit.json",
    "split.json", "build_report.json", "specs/split.yaml", "manifest.json", "_SUCCESS",
)


@pytest.mark.parametrize("member", MEMBERS)
@pytest.mark.parametrize("fault", ["missing", "bytes"])
def test_every_member_missing_or_mutated_fails_read_only(tmp_path, monkeypatch, member, fault):
    _, result, model = setup(tmp_path, monkeypatch)
    final = publish(result, model).verified.build_path
    if fault == "missing":
        del model.nodes[final / member]
    else:
        model.mutate(final / member, b"x" * max(1, len(model.nodes[final / member][2])))
    before, events = model.artifact(result.dataset_id), model.mutations
    with pytest.raises(Error):
        r.load_verified_multi_source_cross_day_dataset(final)
    assert model.artifact(result.dataset_id) == before
    assert model.mutations == events


@pytest.mark.parametrize("member", ["", "manifest.json", "_SUCCESS", "dataset.parquet", "sample_audit.json", "specs"])
def test_second_physical_pass_rejects_identical_byte_object_replacement(tmp_path, monkeypatch, member):
    _, result, model = setup(tmp_path, monkeypatch)
    final = publish(result, model).verified.build_path
    original = r._validate_manifest_content
    def replace_after_logical_validation(*args):
        validated = original(*args)
        model.mutate(final / member, replace=True)
        return validated
    monkeypatch.setattr(r, "_validate_manifest_content", replace_after_logical_validation)
    events = model.mutations
    with pytest.raises(Error, match="replacement"):
        r.load_verified_multi_source_cross_day_dataset(final)
    assert model.mutations == events


@pytest.mark.parametrize("kind", ["extra", "same_size", "marker"])
def test_second_physical_pass_rejects_other_drift(tmp_path, monkeypatch, kind):
    _, result, model = setup(tmp_path, monkeypatch)
    final = publish(result, model).verified.build_path
    original = r._validate_manifest_content
    def change_after_validation(*args):
        validated = original(*args)
        if kind == "extra":
            model.nodes[final / "unlisted"] = (object(), False, b"")
        elif kind == "marker":
            model.mutate(final / "_SUCCESS", b"x")
        else:
            data = model.nodes[final / "dataset.parquet"][2]
            model.mutate(final / "dataset.parquet", data[:-1] + bytes([data[-1] ^ 1]))
        return validated
    monkeypatch.setattr(r, "_validate_manifest_content", change_after_validation)
    with pytest.raises(Error):
        r.load_verified_multi_source_cross_day_dataset(final)


@pytest.mark.parametrize("error", [TypeError("programming error"), KeyError("programming error"), RuntimeError("programming error")])
def test_reader_does_not_suppress_programming_errors(tmp_path, monkeypatch, error):
    _, result, model = setup(tmp_path, monkeypatch)
    final = publish(result, model).verified.build_path
    def broken(*args):
        raise error
    monkeypatch.setattr(r, "_validate_manifest_content", broken)
    with pytest.raises(type(error)) as caught:
        r.load_verified_multi_source_cross_day_dataset(final)
    assert caught.value is error


def test_materializer_preserves_programming_error_and_cleans_only_owned_staging(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    error = RuntimeError("programming error")
    def broken(*args):
        raise error
    model.write_hook = broken
    with pytest.raises(RuntimeError) as caught:
        publish(result, model)
    assert caught.value is error
    assert model.events.count("REMOVE") == 1
    assert len(model.nodes) == 1
