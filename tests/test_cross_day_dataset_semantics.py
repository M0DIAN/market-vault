"""Cohort admission, evidence identity roles, completion and unchanged splitting."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

import cross_day_helpers as cd
import ts2_feature_helpers as ts
from cross_day_dataset_helpers import fixture, tamper
from market_vault.cross_day import identity as label_ids
from market_vault.cross_day import execute_cross_day_labels
from market_vault.ts2_feature import execute_ts2_features
from market_vault.cross_day_dataset import join_multi_source_cross_day_dataset, MultiSourceCrossDayDatasetError
from market_vault.cross_day_dataset.identity import _payload
from market_vault.cross_day_dataset.closure import RESERVED_NAMES


def test_considered_backing_schedule_and_observation_independence(tmp_path):
    values = {case: join_multi_source_cross_day_dataset(**fixture(tmp_path / case, case))
              for case in ("A", "G", "H_considered", "H_backing")}
    original = values["A"]
    original_ref = label_ids.row_reference_id(original.cross_day_association.decisions[0].selected_rows[0])
    for case in ("G", "H_considered", "H_backing"):
        changed = values[case]
        assert changed.dataset_id != original.dataset_id
        assert changed.ts2_features.execution_id == original.ts2_features.execution_id
        assert changed.observation_pit.combined_association_content_id == original.observation_pit.combined_association_content_id
        assert changed.cross_day_association.association_content_id != original.cross_day_association.association_content_id
        assert changed.cross_day_labels.values_content_id != original.cross_day_labels.values_content_id
    assert label_ids.row_reference_id(values["H_considered"].cross_day_association.decisions[0].selected_rows[0]) == original_ref
    assert label_ids.row_reference_id(values["H_backing"].cross_day_association.decisions[0].selected_rows[0]) != original_ref
    changed = join_multi_source_cross_day_dataset(**fixture(tmp_path / "proof", two_proofs=True))
    assert changed.ts2_features.execution_id == original.ts2_features.execution_id
    assert _payload(changed.identity_input)["observation_values_content_id"] != _payload(original.identity_input)["observation_values_content_id"]
    assert changed.split_result.assignments == original.split_result.assignments or all(
        (a.assignment_status, a.purge_boundary) == (b.assignment_status, b.purge_boundary)
        for a, b in zip(changed.split_result.assignments, original.split_result.assignments))


def test_signed_zero_canonical_input_preserves_ts2_admission(tmp_path, monkeypatch):
    from math import copysign

    original_bar, original_spec = cd.bar, ts.spec
    monkeypatch.setattr(cd, "bar", lambda *args, **kwargs: replace(original_bar(*args, **kwargs), volume=-0.0))
    monkeypatch.setattr(ts, "spec", lambda **kwargs: original_spec("rolling_volume_mean", **kwargs))
    data = fixture(tmp_path)
    bar = data["cross_day_association"].feature_builds[0].bars[0]
    value = data["ts2_features"].samples[0].values[0]
    assert copysign(1.0, bar.volume) == -1.0
    assert value.value == 0.0 and copysign(1.0, value.value) == 1.0
    result = join_multi_source_cross_day_dataset(**data)
    column = next(i for i, field in enumerate(result.schema.fields) if field.name == value.feature_name)
    assert result.rows[0][column] == 0.0 and copysign(1.0, result.rows[0][column]) == 1.0
    assert result.ts2_features is data["ts2_features"]


def test_real_ts2_outcome_changes_dataset_id(tmp_path):
    inputs = fixture(tmp_path)
    before = join_multi_source_cross_day_dataset(**inputs)
    ts2 = execute_ts2_features(inputs["cross_day_association"].feature_builds, inputs["feature_pit"],
                               (ts.spec("rolling_mean", n=1),), dataset_as_of=inputs["dataset_as_of"])
    after = join_multi_source_cross_day_dataset(**(inputs | dict(ts2_features=ts2)))
    assert before.dataset_id != after.dataset_id
    assert before.observation_pit == after.observation_pit
    assert before.cross_day_labels == after.cross_day_labels


def test_gap_recorded_closure_partial_consumption_and_actual_end(tmp_path):
    schedule = cd.schedule((("2025-03-03", "N"), ("2025-03-04", "N"), ("2025-03-05", "N")))
    specs = (cd.spec(n=2, transform="maximum_favorable_excursion"), cd.spec())
    bars = (cd.bar("2025-03-04", close=150.0), cd.bar("2025-03-05", slot=0), cd.bar("2025-03-05", slot=2))
    inputs = fixture(tmp_path, schedule=schedule, label_specs=specs, label_bars=bars)
    result = join_multi_source_cross_day_dataset(**inputs)
    decisions = result.cross_day_association.decisions
    incomplete = next(d for d in decisions if d.status == "INCOMPLETE")
    assert incomplete.absence_proofs and incomplete.selected_rows
    assert incomplete.reason_code == "MISSING_TARGET_ROW"
    actual = cd.local("2025-03-04", 9, 40)
    assert incomplete.actual_label_end_time == actual
    assert result.sample_audit[0].actual_label_end_time == actual
    assert result.split_result.assignments[0].actual_label_end_time == actual
    row = dict(zip((f.name for f in result.schema.fields), result.rows[0]))
    assert row["cd_mfe_2d"] is None and row["label_status"] == "INCOMPLETE"
    assert row["assignment_status"] == "EXCLUDED"
    proof = incomplete.absence_proofs[0]
    bad = tamper(proof, backing_canonical_build_ids=inputs["cross_day_association"].considered_canonical_build_ids)
    forged = tamper(incomplete, absence_proofs=(bad,))
    association = tamper(inputs["cross_day_association"], decisions=tuple(forged if d is incomplete else d for d in decisions))
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**(inputs | dict(cross_day_association=association,
            cross_day_labels=tamper(inputs["cross_day_labels"], association=association))))


@pytest.mark.parametrize("offset,status", [(-1, "ASSIGNED"), (0, "PURGED"), (1, "PURGED")])
def test_split_actual_end_boundary_and_matrix_retention(tmp_path, offset, status):
    boundary = cd.local("2025-03-05", 0, 0)
    bar = cd.bar("2025-03-04", market=boundary + timedelta(microseconds=offset))
    result = join_multi_source_cross_day_dataset(**fixture(tmp_path, label_bars=(bar,)))
    assignment, = result.split_result.assignments
    assert assignment.assignment_status == status
    assert len(result.rows) == 1 and result.completion.complete_count == 1
    assert result.sample_audit[0].actual_label_end_time == bar.market_available_at
    assert assignment.actual_label_end_time == bar.market_available_at
    assert assignment.purge_boundary == (boundary if status == "PURGED" else None)


@pytest.mark.parametrize("n,label_future,reason", [(2, False, "OBSERVATION_FEATURE_EXCLUDED"),
    (3, False, "TS2_AND_OBSERVATION_FEATURE_EXCLUDED"),
    (2, True, "FEATURE_EXCLUDED_AND_CROSS_DAY_LABEL_INCOMPLETE"),
    (3, True, "FEATURE_EXCLUDED_AND_CROSS_DAY_LABEL_INCOMPLETE")])
def test_completion_priority_and_missing_scope_cells(tmp_path, n, label_future, reason):
    bars = (cd.bar("2025-03-04", archive=cd.AS_OF + timedelta(days=1) if label_future else cd.ARCHIVE),)
    data = fixture(tmp_path, "D", n=n, label_bars=bars)
    data["scope"] = replace(data["scope"], symbols=("US.AAPL", "US.MSFT"), trade_dates=(date(2025, 3, 3), date(2025, 3, 4)))
    result = join_multi_source_cross_day_dataset(**data)
    assert len(result.completion.entries) == 4
    assert result.completion.incomplete_count == 1 and result.completion.missing_count == 3
    assert result.completion.entries[0].reason_code == reason


@pytest.mark.parametrize("kind", ["legacy", "unknown", "conflicting_future", "symbol", "duplicate"])
def test_unused_canonical_boundary_is_validated_before_clocks(tmp_path, kind):
    data = fixture(tmp_path / "base")
    if kind == "duplicate":
        labels = data["cross_day_association"].label_builds * 2
    else:
        schema = "10.9" if kind == "legacy" else "10.9-mv-ts2"
        bar = cd.bar("2025-03-04" if kind == "conflicting_future" else "2025-03-05", schema=schema,
                     close=200.0, source="b", archive=cd.AS_OF + timedelta(days=1),
                     code="US.MSFT" if kind == "symbol" else "US.AAPL")
        extra = cd.build(tmp_path / kind, (bar,), schema=schema)
        if kind == "unknown":
            extra = tamper(extra, normalized_request=replace(extra.normalized_request, source_schema_version="unknown"))
        labels = data["cross_day_association"].label_builds + (extra,)
    association = tamper(data["cross_day_association"], label_builds=labels)
    with pytest.raises(MultiSourceCrossDayDatasetError) as error:
        join_multi_source_cross_day_dataset(**(data | dict(cross_day_association=association)))
    assert error.value.reason_code == ("DUPLICATE_INPUT" if kind == "duplicate" else
                                       "PIT_BINDING" if kind == "conflicting_future" else "SCOPE")


@pytest.mark.parametrize("cutoff", [None, cd.ARCHIVE, cd.AS_OF])
def test_explicit_cutoff_null_equality_and_schema(tmp_path, cutoff):
    result = join_multi_source_cross_day_dataset(**fixture(tmp_path, cutoff=cutoff))
    assert ("dataset_as_of" in tuple(f.name for f in result.schema.fields)) == (cutoff is not None)
    assert len(result.rows) == 1


@pytest.mark.parametrize("field", ["dataset_as_of", "feature_association", "schedule", "duplicate_sample"])
def test_common_authority_mismatches_fail(tmp_path, field):
    data = fixture(tmp_path)
    if field == "dataset_as_of":
        data[field] += timedelta(microseconds=1)
    elif field == "feature_association":
        data["feature_pit"] = tamper(data["feature_pit"], association_schema_id="0" * 64)
    elif field == "schedule":
        data["schedule"] = replace(data["schedule"], archive_available_at=cd.ARCHIVE - timedelta(microseconds=1))
    else:
        data["feature_pit"] = tamper(data["feature_pit"], samples=data["feature_pit"].samples * 2)
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**data)


@pytest.mark.parametrize("name", tuple(sorted(RESERVED_NAMES)) + ("obs_rate", "cd_return_1d"))
def test_cross_family_and_reserved_names_rejected(tmp_path, name):
    data = fixture(tmp_path)
    spec = data["ts2_features"].feature_specs[0]
    spec = replace(spec, name=name, output=replace(spec.output, name=name))
    data["ts2_features"] = tamper(data["ts2_features"], feature_specs=(spec,))
    with pytest.raises(MultiSourceCrossDayDatasetError):
        join_multi_source_cross_day_dataset(**data)


def test_relocation_and_physical_metadata_are_not_join_authority(tmp_path):
    data = fixture(tmp_path / "original", "H_backing")
    original = join_multi_source_cross_day_dataset(**data)
    def moved(build):
        return replace(build, build_path=Path("D:/does-not-exist/build"), manifest_payload=b"descriptive metadata only",
                       bars=tuple(replace(b, snapshot_file="D:/does-not-exist/source") for b in build.bars),
                       source_snapshot_provenance=tuple(replace(s, snapshot_file="D:/does-not-exist/source") for s in build.source_snapshot_provenance))
    association = tamper(data["cross_day_association"], feature_builds=tuple(moved(b) for b in data["cross_day_association"].feature_builds),
                         label_builds=tuple(moved(b) for b in data["cross_day_association"].label_builds)[::-1])
    moved_obs = tuple(tamper(b, build_dir=Path("D:/does-not-exist/observation")) for b in data["observation_builds"])
    result = join_multi_source_cross_day_dataset(**(data | dict(cross_day_association=association,
        cross_day_labels=tamper(data["cross_day_labels"], association=association), observation_builds=moved_obs)))
    assert result.dataset_id == original.dataset_id
    assert result.rows == original.rows


def test_zero_samples_input_proofs_and_missing_families_remain_strict(tmp_path):
    data = fixture(tmp_path, "E", two_proofs=True)
    result = join_multi_source_cross_day_dataset(**data)
    assert len(result.identity_input.observation_input_proofs) == 2
    assert result.observation_pit.evidence == ()
    for field in ("observation_feature_specs", "observation_builds"):
        changed = data | {field: ()}
        if field == "observation_builds":
            # A zero-input proof set is a different legal zero-sample declaration.
            assert join_multi_source_cross_day_dataset(**changed).dataset_id != result.dataset_id
        else:
            with pytest.raises(MultiSourceCrossDayDatasetError):
                join_multi_source_cross_day_dataset(**changed)


def test_zero_sample_a41_helper_exception_is_local_only(tmp_path, monkeypatch):
    import market_vault.cross_day_dataset._observation_closure as closure
    inputs = fixture(tmp_path, "E", two_proofs=True)
    original = closure.verify_execution_inputs
    represented = []
    def trace(result, builds, specs):
        represented.append(builds)
        return original(result, builds, specs)
    monkeypatch.setattr(closure, "verify_execution_inputs", trace)
    result = join_multi_source_cross_day_dataset(**inputs)
    assert represented == [()]
    assert len(result.observation_builds) == len(result.identity_input.observation_input_proofs) == 2
    with pytest.raises(ValueError, match="unmatched extra"):
        original(inputs["observation_pit"], inputs["observation_builds"], inputs["observation_feature_specs"])
