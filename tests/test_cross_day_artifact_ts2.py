"""Recorded TS2 identities and tail closure without re-execution or issuance."""

import pytest

from test_cross_day_artifact_canonical import prepared, change
from market_vault.cross_day_dataset._artifact_canonical import _canonical_closure, _pit_closure
from market_vault.cross_day_dataset._artifact_ts2 import _ts2_closure
from market_vault.cross_day_dataset._artifact_values import _value
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError
from market_vault.cross_day_dataset._validation import MultiSourceCrossDayDatasetError


def validation_inputs(data):
    builds = data.sidecar("canonical_evidence.json")[1]
    association = data.sidecar("cross_day_association.json")[1][0]
    scope = _value(data.scope)
    union, _, _, _ = _canonical_closure(builds, scope)
    features = tuple(b for b in union if b.canonical_build_id in association.feature_build_ids)
    features, pins, gaps, rows = _canonical_closure(features, scope)
    pit = _pit_closure(data.sidecar("feature_pit.json")[1][0], features, pins, gaps, rows, scope, data.dataset_as_of)
    return pit, features, rows, data.dataset_as_of


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"])
def test_recorded_ts2_exact_all_component_identities(tmp_path, case, monkeypatch):
    from market_vault.ts2_feature import execution

    result, data = prepared(tmp_path, case)
    args = validation_inputs(data)

    def denied(*args, **kwargs):
        raise AssertionError("TS2 invocation forbidden")

    monkeypatch.setattr(execution, "execute_ts2_features", denied)
    monkeypatch.setattr(execution, "_invoke", denied)
    actual = _ts2_closure(data.sidecar("ts2_features.json")[1][0], *args)
    assert type(actual) is not type(result.ts2_features)
    for name in ("execution_id", "values_content_id", "samples_content_id", "status"):
        assert getattr(actual, name) == getattr(result.ts2_features, name)
    for a, b in zip(actual.samples, result.ts2_features.samples):
        assert a.sample_id == b.sample_id
        assert a.values_content_id == b.values_content_id
        assert tuple(v.value_id for v in a.values) == tuple(v.value_id for v in b.values)


@pytest.mark.parametrize("field,value", [
    ("execution_contract_version", "wrong"), ("registry_contract_version", "wrong"),
    ("feature_association_content_id", "0" * 64), ("feature_association_schema_id", "0" * 64),
    ("implementation_source_hashes", ()), ("registry_implementation_pins", ()),
    ("feature_spec_pins", ()), ("samples", ()), ("status", "EMPTY"),
])
def test_ts2_recorded_top_level_tamper(tmp_path, field, value):
    _, data = prepared(tmp_path)
    record = data.sidecar("ts2_features.json")[1][0]
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _ts2_closure(change(record, **{field: value}), *validation_inputs(data))


@pytest.mark.parametrize("mutation", ["shorten", "reorder", "widen", "consumed", "status", "bar"])
def test_ts2_recorded_value_provenance_tamper(tmp_path, mutation):
    _, data = prepared(tmp_path)
    record = data.sidecar("ts2_features.json")[1][0]
    sample = record.samples[0]
    value = sample.values[0]
    changes = {
        "shorten": dict(candidate_canonical_row_version_ids=value.candidate_canonical_row_version_ids[:1]),
        "reorder": dict(candidate_canonical_row_version_ids=value.candidate_canonical_row_version_ids[::-1]),
        "widen": dict(candidate_canonical_row_version_ids=value.candidate_canonical_row_version_ids + ("0" * 64,)),
        "consumed": dict(consumed_canonical_row_version_ids=()),
        "status": dict(status="EXCLUDED"),
        "bar": dict(bar_sample_version_id="0" * 64),
    }[mutation]
    changed = change(record, samples=(change(sample, values=(change(value, **changes),)),))
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _ts2_closure(changed, *validation_inputs(data))


@pytest.mark.parametrize("scalar,error", [
    (-0.0, MultiSourceCrossDayDatasetError),
    (True, MultiSourceCrossDayArtifactError), (1, MultiSourceCrossDayArtifactError),
])
def test_recorded_ts2_requires_exact_normalized_output(tmp_path, scalar, error):
    _, data = prepared(tmp_path)
    record = data.sidecar("ts2_features.json")[1][0]
    sample = record.samples[0]
    changed = change(record, samples=(change(sample, values=(change(sample.values[0], value=scalar),)),))
    with pytest.raises(error):
        _ts2_closure(changed, *validation_inputs(data))


def test_recorded_l2_cannot_silently_normalize_signed_zero(tmp_path):
    _, data = prepared(tmp_path)
    record = data.sidecar("cross_day_values.json")[1][0].values[0]
    with pytest.raises(MultiSourceCrossDayArtifactError, match="normalization"):
        _value(change(record, value=-0.0))
