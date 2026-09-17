"""Real recorded-closure joins and the remediated TS2 candidate boundary."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, timedelta

import pytest

import cross_day_helpers as cd
from cross_day_dataset_helpers import fixture, tamper
from market_vault.cross_day_dataset import (
    join_multi_source_cross_day_dataset, MultiSourceCrossDayDatasetError,
    MultiSourceCrossDayDatasetResult, multi_source_cross_day_dataset_id,
)
from market_vault.cross_day_dataset.identity import _payload
from market_vault.observation.pit_identity import observation_build_pin_id


@pytest.mark.parametrize("slots,n,reason", [((0, 1, 2), 2, None), ((0,), 2, "INSUFFICIENT_ROWS"),
                                          ((0, 1, 3), 2, "NON_CONTIGUOUS_ROWS")])
def test_canary_41_full_selection_and_candidate_tail(tmp_path, slots, n, reason):
    inputs = fixture(tmp_path, slots=slots, n=n)
    result = join_multi_source_cross_day_dataset(**inputs)
    selected = result.feature_pit.samples[0].feature_canonical_row_version_ids
    value = result.ts2_features.samples[0].values[0]
    expected = selected[-min(n, len(selected)):]
    assert value.candidate_canonical_row_version_ids == expected
    assert value.consumed_canonical_row_version_ids == (() if reason else expected)
    assert value.reason_code == reason
    assert len(result.rows) == (0 if reason else 1)
    assert len(result.sample_audit) == 1
    if len(selected) > n:
        assert value.candidate_canonical_row_version_ids != selected


@pytest.mark.parametrize("case,row_count", [("A", 1), ("B", 1), ("C", 0), ("D", 0), ("E", 0),
                                           ("F", 1), ("G", 1), ("H_considered", 1), ("H_backing", 1)])
def test_recorded_scenario_admission(tmp_path, case, row_count):
    result = join_multi_source_cross_day_dataset(**fixture(tmp_path, case))
    assert len(result.rows) == row_count
    assert result.status == ("COMPLETE" if row_count else "EMPTY")


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    return fixture(tmp_path_factory.mktemp("join-recorded-closure"), slots=(0, 1, 2))


@pytest.mark.parametrize("change", ["widen", "shorten", "reorder", "consume", "pin", "sample", "bar",
                                    "clock", "reason", "value_type", "registry", "spec_set", "association",
                                    "samples_missing", "samples_extra", "values_missing", "contract"])
def test_ts2_recorded_tamper_rejected(inputs, change):
    ts2 = inputs["ts2_features"]
    sample = ts2.samples[0]
    value = sample.values[0]
    changes = {
        "widen": dict(candidate_canonical_row_version_ids=inputs["feature_pit"].samples[0].feature_canonical_row_version_ids),
        "shorten": dict(candidate_canonical_row_version_ids=value.candidate_canonical_row_version_ids[:1]),
        "reorder": dict(candidate_canonical_row_version_ids=value.candidate_canonical_row_version_ids[::-1]),
        "consume": dict(consumed_canonical_row_version_ids=()), "pin": dict(implementation_pin=replace(value.implementation_pin, content_sha256="0" * 64)),
        "sample": dict(sample_key="0" * 64), "bar": dict(bar_sample_version_id="0" * 64),
        "clock": dict(feature_window_close=value.feature_window_close + timedelta(microseconds=1)),
        "reason": dict(reason_code="INSUFFICIENT_ROWS"), "value_type": dict(value=1),
    }
    if change in changes:
        ts2 = tamper(ts2, samples=(tamper(sample, values=(tamper(value, **changes[change]),)),))
    else:
        alterations = {
            "registry": dict(registry_implementation_pins=ts2.registry_implementation_pins[:-1]),
            "spec_set": dict(feature_specs=()), "association": dict(feature_association_content_id="0" * 64),
            "samples_missing": dict(samples=()), "samples_extra": dict(samples=ts2.samples * 2),
            "values_missing": dict(samples=(tamper(sample, values=()),)), "contract": dict(execution_contract_version="wrong"),
        }
        ts2 = tamper(ts2, **alterations[change])
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**(inputs | dict(ts2_features=ts2)))


@pytest.mark.parametrize("target", ["sample_key", "bar_sample_version_id", "multi_source_sample_version_id", "missing", "extra", "null"])
def test_a3_binding_tamper_rejected(inputs, target):
    a3 = inputs["observation_pit"]
    binding = a3.sample_bindings[0]
    if target == "missing":
        bindings = ()
    elif target == "extra":
        bindings = a3.sample_bindings * 2
    else:
        name = "multi_source_sample_version_id" if target == "null" else target
        bindings = (tamper(binding, **{name: None if target == "null" else "0" * 64}),)
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**(inputs | dict(observation_pit=tamper(a3, sample_bindings=bindings))))


@pytest.mark.parametrize("target", ["coverage", "pin", "duplicate_pair", "build_rows", "missing_build", "duplicate_build"])
def test_observation_proof_tamper_rejected(inputs, target):
    a3 = inputs["observation_pit"]
    evidence = a3.evidence[0]
    data = dict(inputs)
    if target == "coverage":
        evidence = tamper(evidence, coverages=(replace(evidence.coverages[0], revision_inventory_complete=False),))
    elif target == "pin":
        evidence = tamper(evidence, build_pins=(replace(evidence.build_pins[0], coverage_proof_available_at=cd.AS_OF),))
    elif target == "duplicate_pair":
        evidence = tamper(evidence, build_pins=evidence.build_pins * 2, coverages=evidence.coverages * 2)
    elif target == "build_rows":
        data["observation_builds"] = (tamper(data["observation_builds"][0], rows=()),)
    elif target == "missing_build":
        data["observation_builds"] = ()
    else:
        data["observation_builds"] *= 2
    data["observation_pit"] = tamper(a3, evidence=(evidence,))
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**data)


@pytest.mark.parametrize("target", ["sample", "version", "value_type", "pin", "decision", "consumed", "status", "missing", "extra"])
def test_observation_feature_tamper_rejected(inputs, target):
    result = inputs["observation_features"]
    sample, = result.samples
    value, = sample.values
    if target in ("missing", "extra"):
        result = tamper(result, samples=() if target == "missing" else result.samples * 2)
    else:
        changes = {
            "sample": dict(sample_key="0" * 64), "version": dict(multi_source_sample_version_id="0" * 64),
            "value_type": dict(value=True), "pin": dict(implementation_pin=replace(value.implementation_pin, content_sha256="0" * 64)),
            "decision": dict(decision_id="0" * 64), "consumed": dict(consumed_observation_version_id="0" * 64),
            "status": dict(status="EXCLUDED", value=None, reason_code="STALE", consumed_observation_version_id=None),
        }
        result = tamper(result, samples=(tamper(sample, values=(tamper(value, **changes[target]),)),))
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**(inputs | dict(observation_features=result)))


@pytest.mark.parametrize("target", ["binding_version", "binding_missing", "binding_extra", "decision_reason", "decision_end",
                                    "slot", "selected", "backing", "considered", "value_pin", "value_source", "value_version",
                                    "value_end", "value_missing", "value_extra", "schedule"])
def test_l2_recorded_tamper_rejected(inputs, target):
    association = inputs["cross_day_association"]
    execution = inputs["cross_day_labels"]
    decision, = association.decisions
    binding, = association.sample_bindings
    value, = execution.values
    if target == "binding_version":
        association = tamper(association, sample_bindings=(tamper(binding, multi_source_sample_version_id=None),))
    elif target.startswith("binding_"):
        association = tamper(association, sample_bindings=() if target.endswith("missing") else association.sample_bindings * 2)
    elif target == "decision_reason":
        association = tamper(association, decisions=(tamper(decision, reason_code="ARCHIVE_FUTURE"),))
    elif target == "decision_end":
        association = tamper(association, decisions=(tamper(decision, actual_label_end_time=cd.AS_OF),))
    elif target == "slot":
        slot, = decision.required_slots
        association = tamper(association, decisions=(tamper(decision,
            required_slots=(tamper(slot, event_time=slot.event_time + timedelta(minutes=5)),)),))
    elif target in ("selected", "backing"):
        ref, = decision.selected_rows
        ref = tamper(ref, **(dict(canonical_row_version_id="0" * 64) if target == "selected" else
                            dict(backing_canonical_build_ids=association.considered_canonical_build_ids)))
        association = tamper(association, decisions=(tamper(decision, selected_rows=(ref,)),))
    elif target == "considered":
        association = tamper(association, decisions=(tamper(decision, considered_canonical_build_ids=decision.selected_rows[0].backing_canonical_build_ids),))
    elif target == "value_pin":
        execution = tamper(execution, values=(tamper(value, implementation_pin=replace(value.implementation_pin, content_sha256="0" * 64)),))
    elif target == "value_source":
        execution = tamper(execution, implementation_source_hashes=((execution.implementation_source_hashes[0][0], "0" * 64),))
    elif target == "value_version":
        execution = tamper(execution, values=(tamper(value, multi_source_sample_version_id="0" * 64),))
    elif target == "value_end":
        execution = tamper(execution, values=(tamper(value, actual_label_end_time=cd.AS_OF),))
    elif target.startswith("value_"):
        execution = tamper(execution, values=() if target.endswith("missing") else execution.values * 2)
    else:
        association = tamper(association, schedule=replace(association.schedule, archive_available_at=cd.ARCHIVE - timedelta(microseconds=1)))
    execution = tamper(execution, association=association)
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**(inputs | dict(cross_day_association=association, cross_day_labels=execution)))


def test_full_pit_rows_outside_tail_are_still_validated(inputs):
    association = inputs["cross_day_association"]
    build, = association.feature_builds
    first, *tail = build.bars
    assert first.canonical_row_version_id not in inputs["ts2_features"].samples[0].values[0].candidate_canonical_row_version_ids
    altered = tamper(build, bars=(replace(first, close=999.0), *tail))
    association = tamper(association, feature_builds=(altered,))
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**(inputs | dict(cross_day_association=association)))


def test_distinct_physical_proofs_retained_and_identity_bearing(tmp_path):
    one = join_multi_source_cross_day_dataset(**fixture(tmp_path / "one"))
    data = fixture(tmp_path / "two", two_proofs=True)
    two = join_multi_source_cross_day_dataset(**data)
    assert data["observation_builds"][0].observation_build_id == data["observation_builds"][1].observation_build_id
    pins = two.observation_pit.evidence[0].build_pins
    assert len(pins) == len({observation_build_pin_id(p) for p in pins}) == 2
    assert len({p.coverage_proof_available_at for p in pins}) == 2
    assert one.observation_features.samples[0].values[0].value == two.observation_features.samples[0].values[0].value
    for field in ("observation_evidence_content_id", "observation_input_proofs_digest", "observation_build_pin_ids_digest"):
        assert _payload(one.identity_input)[field] != _payload(two.identity_input)[field]
    assert one.dataset_id != two.dataset_id
    assert join_multi_source_cross_day_dataset(**(data | dict(observation_builds=data["observation_builds"][::-1]))).dataset_id == two.dataset_id


@pytest.mark.parametrize("case", ["B", "C", "D", "E"])
def test_eligibility_audit_and_completion(tmp_path, case):
    result = join_multi_source_cross_day_dataset(**fixture(tmp_path, case))
    if case == "E":
        assert result.sample_audit == () and result.completion.missing_count == 1
        assert result.identity_input.observation_input_proofs
        assert all((result.ts2_features.feature_specs, result.observation_feature_specs, result.cross_day_labels.label_specs))
        return
    audit, = result.sample_audit
    assert result.feature_pit.samples and result.observation_pit.evidence and result.cross_day_association.decisions
    assert result.completion.incomplete_count == 1
    assert audit.bar_sample_version_id == result.feature_pit.samples[0].sample_version_id
    if case == "B":
        row = dict(zip((f.name for f in result.schema.fields), result.rows[0]))
        assert row["cd_return_1d"] is None and row["label_status"] == "INCOMPLETE"
        assert row["sample_version_id"] == audit.multi_source_sample_version_id != audit.bar_sample_version_id
        assert row["assignment_status"] == "EXCLUDED"
    else:
        assert result.rows == () and result.split_result.assignments == ()
        assert not audit.matrix_eligible
        assert all(getattr(audit, "split_" + name) is None for name in
                   ("feature_window_close_date", "nominal_split", "final_split", "assignment_status", "reason_code", "purge_boundary"))


def test_direct_construction_replace_and_nested_immutability(inputs):
    result = join_multi_source_cross_day_dataset(**inputs)
    payload = {f.name: getattr(result, f.name) for f in fields(result)}
    with pytest.raises(MultiSourceCrossDayDatasetError, match="RESULT_AUTHORITY"):
        MultiSourceCrossDayDatasetResult(**payload)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="RESULT_AUTHORITY"):
        replace(result, dataset_id="0" * 64)
    with pytest.raises(FrozenInstanceError):
        result.status = "EMPTY"
    with pytest.raises(TypeError):
        result.rows[0][0] = "US.OTHER"
    with pytest.raises(TypeError):
        result.split_result.assignment_rows[0]["sample_key"] = "0" * 64
    with pytest.raises(TypeError):
        result.feature_pit.association_rows[0]["sample_key"] = "0" * 64


@pytest.mark.parametrize("field", ["rows", "sample_audit", "canonical_build_pins", "observation_input_proofs", "gap_references"])
def test_identity_declaration_is_not_trust_entry(inputs, field):
    result = join_multi_source_cross_day_dataset(**inputs)
    declaration = replace(result.identity_input, **{field: ()})
    with pytest.raises(MultiSourceCrossDayDatasetError):
        multi_source_cross_day_dataset_id(declaration)
