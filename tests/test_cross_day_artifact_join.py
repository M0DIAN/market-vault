"""Artifact matrix/audit/split reconstruction is recorded-only."""

import pytest

from market_vault.cross_day_dataset._artifact_join import _recorded_closure
from test_cross_day_artifact_canonical import prepared, change


def validate(original, data, overrides=None):
    sidecars = {path: records for path, _, records in data.sidecars}
    sidecars.update(overrides or {})
    return _recorded_closure(scope=original.scope, cutoff=data.dataset_as_of, sidecars=sidecars,
        observation_specs=original.observation_feature_specs, label_specs=original.cross_day_labels.label_specs,
        split_spec=original.split_result.split_spec)


@pytest.mark.parametrize("case", ("A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"))
def test_recorded_join_projection(tmp_path, case, monkeypatch):
    original, data = prepared(tmp_path, case)
    def forbidden(*args, **kwargs):
        pytest.fail("upstream execution forbidden in artifact closure")
    monkeypatch.setattr("market_vault.cross_day.assembly._facts", forbidden)
    monkeypatch.setattr("market_vault.dataset.splits.assign_chronological_splits", forbidden)
    monkeypatch.setattr("market_vault.cross_day_dataset.execution.join_multi_source_cross_day_dataset", forbidden)
    result = validate(original, data)
    for name in ("schema", "rows", "sample_audit", "completion"):
        assert getattr(result, name) == getattr(original, name)
    assert result.split_result.split_result_id == original.split_result.split_result_id
    assert result.canonical_build_pins == original.identity_input.canonical_build_pins
    assert result.gap_references == original.identity_input.gap_references


@pytest.mark.parametrize("field,value", [("split_result_id", "0" * 64), ("assignment_content_id", "0" * 64),
    ("assignments", ()), ("assignment_rows", ()), ("splitter_version", "wrong")])
def test_recorded_split_tamper(tmp_path, field, value):
    original, data = prepared(tmp_path)
    record = data.sidecar("split.json")[1][0]
    with pytest.raises(ValueError):
        validate(original, data, {"split.json": (change(record, **{field: value}),)})


def test_audit_must_cover_excluded_samples(tmp_path):
    original, data = prepared(tmp_path, "C")
    with pytest.raises(ValueError):
        validate(original, data, {"sample_audit.json": ()})
