"""Frozen A3 typed record and fixed-width sequence identities; no I/O."""

from dataclasses import fields, replace

from ..dataset.encoding import DatasetError, encode_identity
from ..dataset.models import SpecPin
from ._validation import sha256
from .pit_models import (
    ObservationPITError, ObservationSourceSpec,
    OBSERVATION_SOURCE_SPEC_ID_VERSION, OBSERVATION_FEATURE_SPEC_PIN_ID_VERSION,
    OBSERVATION_BINDING_ID_VERSION, MULTI_SOURCE_SAMPLE_VERSION_ID_VERSION,
    MULTI_SOURCE_PIT_CONTRACT_VERSION, OBSERVATION_ASSOCIATION_SCHEMA_VERSION,
    OBSERVATION_SAMPLE_BINDING_SCHEMA_VERSION, OBSERVATION_SAMPLE_BINDING_CONTENT_ID_VERSION,
    OBSERVATION_ASSOCIATION_CONTENT_ID_VERSION,
)


def _record(value):
    return {f.name: getattr(value, f.name) for f in fields(value)}


def _sequence(domain, members):
    members = tuple(members)
    for member in members:
        sha256(member, "sequence member")
    return encode_identity(domain, {"count": len(members), "members": "".join(members)})


def observation_source_spec_id(source):
    if type(source) is not ObservationSourceSpec:
        raise ObservationPITError("source identity requires ObservationSourceSpec")
    source = replace(source)
    data = _record(source)
    data["dimensions_digest"] = _sequence("observation-source-dimensions-v1", (
        encode_identity("observation-source-dimension-v1", _record(d)) for d in data.pop("dimensions")))
    data["code_entity_map_content_id"] = _sequence("observation-entity-map-v1", (
        encode_identity("observation-entity-map-entry-v1", {"code": c, "entity_id": e})
        for c, e in data.pop("code_entity_map")))
    data["input_field_names_digest"] = _sequence("observation-input-fields-v1", (
        encode_identity("observation-input-field-v1", {"name": n}) for n in data.pop("input_field_names")))
    return encode_identity(OBSERVATION_SOURCE_SPEC_ID_VERSION, data)


def feature_spec_pin_id(pin):
    if type(pin) is not SpecPin or pin.kind != "FEATURE":
        raise ObservationPITError("feature identity requires FEATURE SpecPin")
    try:
        return encode_identity(OBSERVATION_FEATURE_SPEC_PIN_ID_VERSION, _record(replace(pin)))
    except DatasetError as exc:
        raise ObservationPITError(str(exc)) from exc


def observation_snapshot_pin_id(pin):
    return encode_identity("observation-snapshot-pin-v1", _record(pin))


def observation_build_pin_id(pin):
    data = _record(pin)
    for field, domain in (("provider_contracts", "observation-provider-pins-v1"),
                          ("normalizations", "observation-normalizer-pins-v1")):
        pins = sorted(data.pop(field), key=lambda p: (p.version, p.content_id))
        data[field + "_digest"] = _sequence(domain, (
            encode_identity("observation-provenance-contract-pin-v1", _record(p)) for p in pins))
    data["source_snapshots_digest"] = _sequence("observation-snapshot-pins-v1", (
        observation_snapshot_pin_id(p) for p in sorted(data.pop("source_snapshots"), key=lambda p: p.source_snapshot_id)))
    for field, domain in (("authority_evidence_ids", "observation-authority-pins-v1"),
                          ("selected_observation_version_ids", "observation-selected-versions-v1")):
        data[field + "_digest"] = _sequence(domain, sorted(data.pop(field)))
    return encode_identity("observation-build-pin-v1", data)


def considered_observation_builds_digest(pins):
    return _sequence("observation-considered-builds-v1", sorted({observation_build_pin_id(p) for p in pins}))


def observation_decision_id(decision):
    return encode_identity("observation-decision-v1", _record(decision))


def observation_binding_id(decisions):
    return _sequence(OBSERVATION_BINDING_ID_VERSION, (
        observation_decision_id(d) for d in sorted(decisions, key=lambda d: d.feature_spec_pin_id)))


def multi_source_sample_version_id(sample_key, bar_sample_version_id, binding_id):
    return encode_identity(MULTI_SOURCE_SAMPLE_VERSION_ID_VERSION, {
        "sample_key": sample_key, "bar_sample_version_id": bar_sample_version_id,
        "observation_binding_id": binding_id,
        "observation_association_schema_version": OBSERVATION_ASSOCIATION_SCHEMA_VERSION,
        "multi_source_pit_contract_version": MULTI_SOURCE_PIT_CONTRACT_VERSION,
    })


def sample_binding_content_id(rows):
    return encode_identity(OBSERVATION_SAMPLE_BINDING_CONTENT_ID_VERSION, {
        "schema_version": OBSERVATION_SAMPLE_BINDING_SCHEMA_VERSION,
        "rows_digest": _sequence("observation-sample-binding-rows-v1", (
            encode_identity("observation-sample-binding-row-v1", _record(r))
            for r in sorted(rows, key=lambda r: r.sample_key))),
    })


def observation_association_content_id(decisions):
    return encode_identity(OBSERVATION_ASSOCIATION_CONTENT_ID_VERSION, {
        "schema_version": OBSERVATION_ASSOCIATION_SCHEMA_VERSION,
        "multi_source_pit_contract_version": MULTI_SOURCE_PIT_CONTRACT_VERSION,
        "rows_digest": _sequence("observation-association-rows-v1", (
            observation_decision_id(d) for d in sorted(decisions, key=lambda d: (d.sample_key, d.feature_spec_pin_id)))),
    })


def combined_association_content_id(bar_content_id, bar_schema_id, observation_content_id, binding_content_id):
    return encode_identity("multi-source-association-content-v1", {
        "bar_association_content_id": bar_content_id, "bar_association_schema_id": bar_schema_id,
        "bar_association_schema_version": "pit-association-schema-v1",
        "observation_association_content_id": observation_content_id,
        "observation_association_schema_version": OBSERVATION_ASSOCIATION_SCHEMA_VERSION,
        "sample_binding_content_id": binding_content_id,
        "sample_binding_schema_version": OBSERVATION_SAMPLE_BINDING_SCHEMA_VERSION,
        "multi_source_pit_contract_version": MULTI_SOURCE_PIT_CONTRACT_VERSION,
    })
