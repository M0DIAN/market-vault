"""Offline A1 shape checks; fixture claims are not provider qualification."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math

import pytest

from market_vault.observation import (
    Observation, ObservationBuildIdentityInput, ObservationContractPin,
    ObservationCoverage, ObservationDimension, ObservationError, ObservationScope,
    ObservationSnapshotMember, ObservationSourceSnapshotInput,
    ObservationValueField, ObservationValueSchema, observation_content_id,
    observation_source_content_id, observation_source_snapshot_id,
)

T = datetime(2026, 3, 1, 18, 0, tzinfo=timezone.utc)
H = tuple(f"{n:064x}" for n in range(1, 20))


def sample_snapshot(**changes):
    args = dict(
        provider_id="fixture-provider", source_kind="fixture-series",
        provider_contract=ObservationContractPin("fixture-contract-v1", H[0]),
        normalized_request_id=H[1], source_content_sha256=H[2],
        acquisition_receipt_id="receipt-1", acquisition_receipt_content_id=H[3],
        completed_possession_at=T + timedelta(hours=2),
    )
    return ObservationSourceSnapshotInput(**(args | changes))


def sample_observation(**changes):
    args = dict(
        provider_id="fixture-provider", source_kind="fixture-series",
        entity_id="fixture:entity", observation_name="rate",
        dimensions=(ObservationDimension("tenor", "string", "10Y"),
                    ObservationDimension("variant", "int64", 1)),
        event_time=T, event_period_start=None,
        value_schema=ObservationValueSchema((
            ObservationValueField("rate", "float64", "percent", "unscaled-binary64"),
            ObservationValueField("count", "int64", "contracts", "unscaled-integer"),
        )),
        values=(4.25, 12), value_status="VALUE",
        known_at=T + timedelta(hours=1), known_at_authority_id=H[4],
        archive_available_at=T + timedelta(hours=2),
        source_snapshot_id=observation_source_snapshot_id(sample_snapshot()),
        source_content_sha256=H[2], provider_contract_version="fixture-contract-v1",
        provider_contract_content_id=H[0], normalization_version="fixture-normalizer-v1",
        normalization_content_id=H[5], revision_id="initial-1", supersedes_revision_id=None,
    )
    return Observation(**(args | changes))


def sample_coverage(**changes):
    row = sample_observation()
    args = dict(
        scope=ObservationScope(row.provider_id, row.source_kind, row.entity_id,
                               row.observation_name, row.dimensions),
        provider_contract=ObservationContractPin(row.provider_contract_version, H[0]),
        effective_start=T - timedelta(days=1), effective_end=T + timedelta(days=2),
        knowledge_start=T - timedelta(days=1), knowledge_end=T + timedelta(days=3),
        normalized_request_id=H[1], request_completion_evidence_id=H[6],
        request_pages_complete=True, missing_semantics="explicit-not-reported-v1",
        missing_semantics_content_id=H[7], revision_inventory_content_id=H[8],
        revision_inventory_complete=True,
    )
    return ObservationCoverage(**(args | changes))


def sample_build(**changes):
    row = sample_observation()
    args = dict(
        rows=(row,), source_snapshot_ids=(row.source_snapshot_id,),
        authority_evidence_ids=(H[4], H[6], H[7], H[8]),
        provider_contracts=(ObservationContractPin(row.provider_contract_version, H[0]),),
        normalizations=(ObservationContractPin(row.normalization_version, H[5]),),
        coverage=sample_coverage(),
    )
    return ObservationBuildIdentityInput(**(args | changes))


def test_models_are_frozen_and_containers_detached():
    values = [4.25, 12]
    dims = list(sample_observation().dimensions)
    row = sample_observation(values=values, dimensions=dims)
    values[0] = 999.0
    dims.clear()
    assert row.values == (4.25, 12)
    assert len(row.dimensions) == 2
    for obj, attr in [(row, "revision_id"), (row.value_schema, "fields"),
                      (sample_snapshot(), "provider_id"), (sample_coverage(), "scope"),
                      (sample_build(), "rows")]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, attr, None)


@pytest.mark.parametrize("field", ["provider_id", "source_kind", "entity_id", "observation_name",
                                   "revision_id", "provider_contract_version", "normalization_version"])
@pytest.mark.parametrize("bad", ["", " ", " x", "x ", "a|b", "x\n", "a\x85b", "a\u200bb", "\ud800", None, 1])
def test_unsafe_or_empty_text_fails(field, bad):
    with pytest.raises(ObservationError):
        sample_observation(**{field: bad})


@pytest.mark.parametrize("field", ["known_at_authority_id", "source_snapshot_id", "source_content_sha256",
                                   "provider_contract_content_id", "normalization_content_id"])
@pytest.mark.parametrize("bad", ["Friday", "latest", "provider default", "https://invalid.test", "a" * 63,
                                 "a" * 65, "G" * 64, "A" * 64, "a" * 64 + "\n", None])
def test_strict_sha_fields(field, bad):
    with pytest.raises(ObservationError, match="SHA-256"):
        sample_observation(**{field: bad})


@pytest.mark.parametrize("field", ["event_time", "event_period_start", "known_at", "archive_available_at"])
@pytest.mark.parametrize("bad", [datetime(2026, 1, 1), "2026-01-01", 0])
def test_naive_and_non_instants_fail(field, bad):
    with pytest.raises(ObservationError, match="timezone-aware"):
        sample_observation(**{field: bad})


@pytest.mark.parametrize("values", [None, (), (1.0,), (1.0, 2, 3), (True, 1), (1, 2),
                                     (float("nan"), 1), (float("inf"), 1), (-float("inf"), 1),
                                     (1.0, True), (1.0, 2**63), (1.0, -(2**63)-1),
                                     ({"rate": 1}, 1), ([1.0], 1), ("text", 1)])
def test_values_fail_closed(values):
    with pytest.raises(ObservationError):
        sample_observation(values=values)


@pytest.mark.parametrize("status", ["NOT_REPORTED", "WITHDRAWN"])
def test_nonvalue_status_has_no_fabricated_payload(status):
    assert sample_observation(value_status=status, values=None).values is None
    for bad in [(0.0, 0), (), []]:
        with pytest.raises(ObservationError):
            sample_observation(value_status=status, values=bad)


def test_numeric_extremes_negative_zero_and_status_validation():
    assert sample_observation(values=(0.0, -(2**63))).values[1] == -(2**63)
    assert sample_observation(values=(0.0, 2**63-1)).values[1] == 2**63-1
    assert math.copysign(1, sample_observation(values=(-0.0, 0)).values[0]) == 1
    for status in ["MISSING", "value", None, True]:
        with pytest.raises(ObservationError):
            sample_observation(value_status=status)


def test_period_and_local_revision_invariants():
    assert sample_observation(event_period_start=T-timedelta(days=1)).event_period_start < T
    for start in [T, T+timedelta(microseconds=1)]:
        with pytest.raises(ObservationError):
            sample_observation(event_period_start=start)
    for predecessor in ["", "initial-1", "x\n", 1]:
        with pytest.raises(ObservationError):
            sample_observation(supersedes_revision_id=predecessor)
    # A1 binds a predecessor, without inventing a chain or performing PIT selection.
    assert sample_observation(supersedes_revision_id="unverified-predecessor").supersedes_revision_id


def test_schema_and_dimension_failures():
    for logical_type in ["bool", "string", "decimal", "FLOAT64", "json", None]:
        with pytest.raises(ObservationError):
            ObservationValueField("x", logical_type, "unit", "unscaled")
    field = ObservationValueField("x", "float64", "unit", "unscaled")
    for fields in [(), (field, field), ({"name": "x"},), None]:
        with pytest.raises(ObservationError):
            ObservationValueSchema(fields)
    dim = ObservationDimension("x", "string", "a")
    with pytest.raises(ObservationError, match="duplicate dimension"):
        sample_observation(dimensions=(dim, dim))
    for kind, value in [("int64", True), ("float64", True), ("int64", 2**63),
                        ("float64", float("nan")), ("string", " x"), ("bool", True),
                        ("string", {"x": 1})]:
        with pytest.raises(ObservationError):
            ObservationDimension("x", kind, value)


@pytest.mark.parametrize("name", ["/a", "D:/a", "D:a", "a:b", "a\\b", "../a", "a/../b",
                                "./a", ".", "..", "a//b", "a/", "", "a\x00b"])
def test_unsafe_inventory_paths_fail_without_filesystem(name):
    with pytest.raises(ObservationError):
        ObservationSnapshotMember(name, 5, H[0])


def test_inventory_seal_and_duplicate_members():
    members = (ObservationSnapshotMember("b/page.csv", 0, H[0]),
               ObservationSnapshotMember("a.csv", 5, H[1]))
    seal = observation_source_content_id(members)
    assert seal == observation_source_content_id(tuple(reversed(members)))
    snapshot = sample_snapshot(members=members, source_content_sha256=seal)
    assert snapshot.members[0].relative_name == "a.csv"
    with pytest.raises(ObservationError, match="inventory"):
        sample_snapshot(members=members)
    with pytest.raises(ObservationError, match="duplicate"):
        observation_source_content_id((members[0], members[0]))
    with pytest.raises(ObservationError, match="duplicate"):
        sample_snapshot(members=(members[0], members[0]))
    for size in [-1, True, 2**63]:
        with pytest.raises(ObservationError):
            ObservationSnapshotMember("a", size, H[0])


def test_coverage_is_an_explicit_claim_not_row_count_inference():
    coverage = sample_coverage(request_pages_complete=False, revision_inventory_complete=False)
    assert not coverage.request_pages_complete
    assert sample_build(rows=(), coverage=coverage).rows == ()
    for changes in [dict(effective_start=T+timedelta(days=4)),
                    dict(knowledge_start=T+timedelta(days=4)),
                    dict(request_pages_complete=1), dict(revision_inventory_complete="true"),
                    dict(missing_semantics=""), dict(request_completion_evidence_id="latest")]:
        with pytest.raises(ObservationError):
            sample_coverage(**changes)


@pytest.mark.parametrize("changes", [
    dict(schema_version="unknown"), dict(source_snapshot_ids=()),
    dict(source_snapshot_ids=(H[0], H[0])), dict(source_snapshot_ids=(H[0],)),
    dict(authority_evidence_ids=(H[4],)), dict(normalizations=()),
    dict(normalizations=(ObservationContractPin("other", H[5]),)),
    dict(provider_contracts=(ObservationContractPin("other", H[0]),)),
    dict(rows=("not-an-observation",)), dict(coverage=None),
])
def test_build_declaration_consistency(changes):
    with pytest.raises(ObservationError):
        sample_build(**changes)


def test_out_of_scope_rows_and_conflicting_versions_fail():
    for changes in [dict(entity_id="other"), dict(event_time=T+timedelta(days=10)),
                    dict(known_at=T+timedelta(days=10))]:
        with pytest.raises(ObservationError):
            sample_build(rows=(sample_observation(**changes),))
    row = sample_observation()
    other = replace(row, values=(5.0, 12))
    # A forged frozen instance is NOT a supported trust path; exercise defense.
    object.__setattr__(other, "observation_version_id", row.observation_version_id)
    with pytest.raises(ObservationError, match="conflicting duplicate"):
        observation_content_id((row, other))
    with pytest.raises(ObservationError, match="inconsistent derived IDs"):
        observation_content_id((other,))


def test_no_new_top_level_business_api():
    import market_vault
    import market_vault.observation as api

    assert not hasattr(market_vault, "Observation")
    assert not hasattr(api, "VerifiedObservationBuild")
    assert not hasattr(api, "load_verified_observation_build")


@pytest.mark.parametrize("field", ["name", "unit", "representation"])
@pytest.mark.parametrize("value", ["", " ", " leading", "trailing ", "bad|text", "bad\x1ftext", None])
def test_schema_semantic_tokens_fail_closed(field, value):
    original = sample_observation().value_schema.fields[0]
    with pytest.raises(ObservationError):
        replace(original, **{field: value})


@pytest.mark.parametrize("field", ["normalized_request_id", "source_content_sha256", "acquisition_receipt_content_id"])
@pytest.mark.parametrize("bad", [None, "latest", "https://invalid.test/proof", "A"*64])
def test_snapshot_requires_immutable_hashes(field, bad):
    with pytest.raises(ObservationError):
        sample_snapshot(**{field: bad})


def test_snapshot_and_coverage_time_and_pin_types_fail_closed():
    with pytest.raises(ObservationError, match="timezone-aware"):
        sample_snapshot(completed_possession_at=T.replace(tzinfo=None))
    for name in ("effective_start", "effective_end", "knowledge_start", "knowledge_end"):
        with pytest.raises(ObservationError, match="timezone-aware"):
            sample_coverage(**{name: T.replace(tzinfo=None)})
    for factory in (sample_snapshot, sample_coverage):
        with pytest.raises(ObservationError):
            factory(provider_contract={"version": "v1", "content_id": H[0]})
    with pytest.raises(ObservationError):
        ObservationContractPin("v1", "latest")
    with pytest.raises(ObservationError):
        ObservationContractPin("", H[0])
    with pytest.raises(ObservationError):
        sample_observation(value_schema={"fields": []})


def test_null_and_unrepresentable_instants_fail_closed():
    import pandas as pd

    for bad in (pd.NaT, datetime.max.replace(tzinfo=timezone(timedelta(hours=-1)))):
        with pytest.raises(ObservationError):
            sample_observation(event_time=bad)


def test_build_pin_duplicates_and_conflicts_fail_closed():
    build = sample_build()
    for name in ("provider_contracts", "normalizations"):
        pin = getattr(build, name)[0]
        for second in (pin, replace(pin, content_id=H[15])):
            with pytest.raises(ObservationError, match="duplicate/conflicting"):
                replace(build, **{name: (pin, second)})
    with pytest.raises(ObservationError, match="duplicate"):
        replace(build, authority_evidence_ids=(H[4], H[4]))


def test_build_and_snapshot_containers_are_copied():
    base = sample_build()
    mutable = {name: list(getattr(base, name)) for name in (
        "rows", "source_snapshot_ids", "authority_evidence_ids", "provider_contracts", "normalizations",
    )}
    copied = replace(base, **mutable)
    for values in mutable.values():
        values.clear()
    assert copied == base
    members = [ObservationSnapshotMember("page.csv", 5, H[0])]
    snapshot = sample_snapshot(members=members, source_content_sha256=observation_source_content_id(members))
    members.clear()
    assert len(snapshot.members) == 1


def test_no_mutable_dict_container_or_caller_supplied_identity():
    for changes in (dict(dimensions={}), dict(values={})):
        with pytest.raises(ObservationError):
            sample_observation(**changes)
    for name in ("observation_key", "observation_version_id", "value_schema_id"):
        with pytest.raises(TypeError):
            sample_observation(**{name: H[0]})
