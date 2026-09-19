"""Artifact L2 validation never calls the L2 assembler/executor."""

import pytest

from market_vault.cross_day_dataset._artifact_labels import _label_closure
from market_vault.cross_day_dataset._artifact_canonical import _canonical_closure
from market_vault.cross_day_dataset._artifact_observation import _observation_closure
from market_vault.cross_day_dataset._artifact_values import _value
from test_cross_day_artifact_canonical import prepared, change
from test_cross_day_artifact_ts2 import validation_inputs


def validate(data, original, association=None, values=None, schedule=None):
    pit, _, _, cutoff = validation_inputs(data)
    builds, _, _, rows = _canonical_closure(data.sidecar("canonical_evidence.json")[1], _value(data.scope))
    a3, _, _ = _observation_closure(data.sidecar("observation_pit.json")[1][0],
        data.sidecar("observation_evidence.json")[1], original.observation_feature_specs, pit)
    return _label_closure(association or data.sidecar("cross_day_association.json")[1][0],
        values or data.sidecar("cross_day_values.json")[1][0],
        schedule or data.sidecar("schedule.json")[1][0], original.cross_day_labels.label_specs,
        pit, a3, builds, rows, cutoff)


@pytest.mark.parametrize("case", ("A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"))
def test_recorded_labels_match_upstream_without_reassembly(tmp_path, case, monkeypatch):
    original, data = prepared(tmp_path, case)
    def forbidden(*args, **kwargs):
        pytest.fail("upstream reassembly or formula execution")
    monkeypatch.setattr("market_vault.cross_day.assembly._facts", forbidden)
    monkeypatch.setattr("market_vault.cross_day.execution.execute_cross_day_labels", forbidden)
    association, values, schedule = validate(data, original)
    assert association.association_content_id == original.cross_day_association.association_content_id
    assert values.values_content_id == original.cross_day_labels.values_content_id
    assert schedule == original.schedule
    assert tuple((s.status, s.actual_label_end_time) for s in values.samples) == tuple(
        (s.status, s.actual_label_end_time) for s in original.cross_day_labels.samples)


@pytest.mark.parametrize("field", ("feature_build_ids", "label_build_ids", "decisions", "sample_bindings"))
def test_recorded_label_association_omission_fails(tmp_path, field):
    original, data = prepared(tmp_path, "A")
    record = data.sidecar("cross_day_association.json")[1][0]
    with pytest.raises(ValueError):
        validate(data, original, association=change(record, **{field: ()}))


@pytest.mark.parametrize("field", ("implementation_pins", "implementation_source_hashes", "values"))
def test_recorded_label_execution_omission_fails(tmp_path, field):
    original, data = prepared(tmp_path, "A")
    record = data.sidecar("cross_day_values.json")[1][0]
    with pytest.raises(ValueError):
        validate(data, original, values=change(record, **{field: ()}))
