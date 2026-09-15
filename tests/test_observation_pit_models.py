"""A3 declaration validation and shared offline, genuinely verified A2 fixtures."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from market_vault.dataset.content import dataset_schema_id, logical_dataset_content_id
from market_vault.dataset.models import SpecPin
from market_vault.dataset.pit import pit_association_schema
from market_vault.dataset.pit_identity import pit_sample_key, pit_sample_version_id
from market_vault.dataset.pit_models import (
    PITAssemblyDiagnostics, PITAssemblyResult, PITDiagnostics, PITSample, PITSampleRequest,
)
from market_vault.observation import (
    ObservationDimension, ObservationScope, materialize_observation_build,
    observation_source_snapshot_id, assemble_observation_pit_sidecar,
)
from market_vault.observation.pit_identity import observation_source_spec_id
from market_vault.observation.pit_models import (
    ObservationPITError, ObservationSourceSpec, ObservationPITFeatureBinding, ObservationPITAssemblyResult,
)
from test_observation_models import H, T, sample_build, sample_coverage, sample_observation, sample_snapshot


def clock(us):
    return T + timedelta(microseconds=us)


SNAPSHOT = sample_snapshot(completed_possession_at=clock(0))


def observation(event=95, known=96, archive=97, **changes):
    return sample_observation(event_time=clock(event), known_at=clock(known), archive_available_at=clock(archive),
                              source_snapshot_id=observation_source_snapshot_id(SNAPSHOT), **changes)


def source(**changes):
    row = observation()
    args = dict(provider_id=row.provider_id, source_kind=row.source_kind, observation_name=row.observation_name,
                dimensions=row.dimensions, entity_binding="EXACT_ENTITY", entity_id=row.entity_id,
                code_entity_map=(), input_field_names=("rate", "count"), value_schema_id=row.value_schema_id,
                provider_contract_version=row.provider_contract_version,
                provider_contract_content_id=row.provider_contract_content_id,
                normalization_version=row.normalization_version, normalization_content_id=row.normalization_content_id,
                known_at_authority_policy_version="fixture-policy-v1", known_at_authority_policy_content_id=H[9],
                alignment="LATEST_EFFECTIVE_AT_OR_BEFORE", exact_target_binding=None,
                max_age_us=10, missing_policy="EXCLUDE_SAMPLE")
    return ObservationSourceSpec(**(args | changes))


def binding(spec=None, name="rate-feature"):
    return ObservationPITFeatureBinding(SpecPin("FEATURE", name, "v1", H[10]), source() if spec is None else spec)


def bar(*, A=None, close=100, start=90, code="US.TEST", empty=False):
    request = PITSampleRequest(code, "1m", "NONE", "RTH", T.date(), clock(start), clock(close))
    key = pit_sample_key(request)
    version = pit_sample_version_id(sample_key=key, dataset_as_of=None if A is None else clock(A),
                                   feature_canonical_row_version_ids=(), label_canonical_row_version_ids=(),
                                   considered_canonical_build_ids=())
    diagnostics = PITDiagnostics(0, 0, 0, 0, 0, 0, 0, 0, (), (), True)
    sample = PITSample(key, version, request, None if A is None else clock(A), (), (), (), diagnostics)
    schema = pit_association_schema()
    return PITAssemblyResult(() if empty else (sample,), (), (), (), schema, (), dataset_schema_id(schema),
                             logical_dataset_content_id(schema, ()),
                             PITAssemblyDiagnostics(0 if empty else 1, 0, 0, 0, 0, 0, 0, ()))


@pytest.fixture
def artifacts(tmp_path):
    """The assembler never mocks verification: each input comes from the A2 reader."""
    serial = 0

    def create(rows=None, *, effective=(0, 200), knowledge=(0, 300), created=300, snapshots=(SNAPSHOT,),
               coverage_changes=None, build_changes=None):
        nonlocal serial
        rows = (observation(),) if rows is None else tuple(rows)
        representative = rows[0] if rows else observation()
        coverage = sample_coverage(
            scope=ObservationScope(representative.provider_id, representative.source_kind, representative.entity_id,
                                   representative.observation_name, representative.dimensions),
            effective_start=clock(effective[0]), effective_end=clock(effective[1]),
            knowledge_start=clock(knowledge[0]), knowledge_end=clock(knowledge[1]), **(coverage_changes or {}))
        identity = sample_build(**(dict(rows=rows, coverage=coverage,
                                       source_snapshot_ids=tuple(observation_source_snapshot_id(s) for s in snapshots),
                                       authority_evidence_ids=(H[4], H[6], H[7], H[8], H[9])) | (build_changes or {})))
        serial += 1
        return materialize_observation_build(identity, snapshots, output_root=tmp_path / str(serial),
                                             created_at=clock(created)).verified_build

    return create


@pytest.mark.parametrize("field,value", [
    ("alignment", "LATEST_KNOWN_AT_OR_BEFORE"), ("alignment", None),
    ("exact_target_binding", "FEATURE_WINDOW_CLOSE"), ("entity_binding", "INFER"),
    ("entity_id", None), ("code_entity_map", (("US.TEST", "entity"),)),
    ("input_field_names", ()), ("input_field_names", ("rate", "rate")),
    ("input_field_names", ("rate\n",)), ("value_schema_id", "not-hash"),
    ("max_age_us", 0), ("max_age_us", -1), ("max_age_us", True), ("max_age_us", 1.0),
    ("max_age_us", 10**30), ("missing_policy", "FORWARD_FILL"),
    ("provider_id", " infer "), ("dimensions", (("variant", 1),)),
])
def test_invalid_source_declarations(field, value):
    with pytest.raises(ObservationPITError):
        source(**{field: value})


@pytest.mark.parametrize("target", [None, "T", "LATEST"])
def test_exact_requires_explicit_target(target):
    with pytest.raises(ObservationPITError):
        source(alignment="EXACT_EVENT_TIME", exact_target_binding=target)


@pytest.mark.parametrize("mapping", [(), {"US.TEST": "x"}, (("US.TEST",),),
                                    (("us.test", "x"), (" US.TEST ", "y")), (("US.TEST\n", "x"),)])
def test_sample_code_mapping_invalid(mapping):
    with pytest.raises(ObservationPITError):
        source(entity_binding="SAMPLE_CODE", entity_id=None, code_entity_map=mapping)


def test_containers_detached_and_code_normalization():
    dims = list(source().dimensions)
    mapping = [[" us.test ", "fixture:entity"], ["US.OTHER", "other"]]
    fields = ["rate", "count"]
    spec = source(dimensions=dims, entity_binding="SAMPLE_CODE", entity_id=None,
                  code_entity_map=mapping, input_field_names=fields)
    dims.clear()
    mapping[0][1] = "mutated"
    fields.clear()
    assert spec.code_entity_map == (("US.OTHER", "other"), ("US.TEST", "fixture:entity"))
    assert spec.dimensions == source().dimensions and spec.input_field_names == ("rate", "count")
    with pytest.raises(FrozenInstanceError):
        spec.max_age_us = 1


def test_bindings_only_accept_existing_feature_pin():
    for bad in (None, "FEATURE", SpecPin("LABEL", "label", "v1", H[10])):
        with pytest.raises(ObservationPITError):
            ObservationPITFeatureBinding(bad, source())
    with pytest.raises(ObservationPITError):
        ObservationPITFeatureBinding(binding().feature_spec_pin, {})
    with pytest.raises(TypeError):
        ObservationPITAssemblyResult()


def test_canary_25_unknown_alignment_even_without_samples():
    forged = source()
    object.__setattr__(forged, "alignment", "UNKNOWN")
    valid = binding()
    object.__setattr__(valid, "source_spec", forged)
    with pytest.raises(ObservationPITError, match="alignment"):
        assemble_observation_pit_sidecar(bar(empty=True), (), (valid,))


@pytest.mark.parametrize("kind,value", [("float64", 1.0), ("string", "1")])
def test_canaries_38_39_typed_dimensions_never_coerce(artifacts, kind, value):
    original = source()
    dims = tuple(ObservationDimension(d.name, kind, value) if d.name == "variant" else d for d in original.dimensions)
    changed = source(dimensions=dims)
    assert observation_source_spec_id(changed) != observation_source_spec_id(original)
    assert changed.dimensions[1].logical_type == kind
    assert type(changed.dimensions[1].value) is type(value)
    with pytest.raises(ObservationPITError, match="scope"):
        assemble_observation_pit_sidecar(bar(), (artifacts(),), (binding(changed),))


def test_canary_40_dimension_order_normalizes():
    assert observation_source_spec_id(source()) == observation_source_spec_id(source(dimensions=source().dimensions[::-1]))


def test_duplicate_dimension_name_fails():
    dim = source().dimensions[0]
    with pytest.raises(ObservationPITError, match="duplicate"):
        source(dimensions=(dim, dim))


def test_zero_sample_still_admits_all_builds_and_sources(artifacts):
    build = artifacts()
    result = assemble_observation_pit_sidecar(bar(empty=True), (build,), (binding(),))
    assert not result.decisions and not result.sample_bindings
    with pytest.raises(ObservationPITError, match="scope"):
        assemble_observation_pit_sidecar(bar(empty=True), (build,), ())
    with pytest.raises(ObservationPITError, match="policy"):
        assemble_observation_pit_sidecar(bar(empty=True), (build,),
                                         (binding(source(known_at_authority_policy_content_id=H[18])),))
