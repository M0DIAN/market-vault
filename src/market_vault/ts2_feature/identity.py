"""Frozen F/V/Q/E encoding helpers; these never issue trusted results."""

from dataclasses import asdict

from ..dataset.encoding import encode_identity
from ._validation import digest, require


def sequence_id(domain, members):
    members = tuple(digest(v) for v in members)
    return encode_identity(domain, {"count": len(members), "members": "".join(members)})


def spec_pin_id(pin):
    return encode_identity("dataset-spec", asdict(pin))


def implementation_pin_id(pin):
    return encode_identity("dataset-implementation", asdict(pin))


def considered_builds_digest(build_ids):
    return sequence_id("ts2-feature-considered-builds-v1", sorted(set(build_ids)))


def input_rows_digest(versions):
    return sequence_id("ts2-feature-input-rows-v1", versions)


def spec_pins_digest(pins):
    return sequence_id("ts2-feature-spec-pins-v1", sorted(spec_pin_id(p) for p in pins))


def registry_pins_digest(pins):
    return sequence_id("ts2-feature-implementation-pins-v1", sorted(implementation_pin_id(p) for p in pins))


_VALUE_FIELDS = frozenset((
    "execution_contract_version", "sample_key", "bar_sample_version_id", "feature_name",
    "feature_spec_pin_id", "implementation_pin_id", "feature_window_close", "dataset_as_of",
    "considered_canonical_build_ids_digest", "candidate_row_version_ids_digest",
    "consumed_row_version_ids_digest", "status", "value", "reason_code",
))
_SAMPLE_FIELDS = frozenset(("sample_key", "bar_sample_version_id", "status", "values_content_id"))
_EXECUTION_FIELDS = frozenset((
    "execution_contract_version", "registry_contract_version", "feature_association_content_id",
    "feature_association_schema_id", "dataset_as_of", "considered_canonical_build_ids_digest",
    "feature_spec_pins_digest", "registry_implementation_pins_digest", "sample_count", "feature_count",
    "status", "values_content_id", "samples_content_id",
))


def value_id(payload):
    require(set(payload) == _VALUE_FIELDS, "RESULT_AUTHORITY", "V field set mismatch")
    return encode_identity("ts2-feature-value-v1", payload)


def sample_id(payload):
    require(set(payload) == _SAMPLE_FIELDS, "RESULT_AUTHORITY", "Q field set mismatch")
    return encode_identity("ts2-feature-sample-v1", payload)


def execution_id(payload):
    require(set(payload) == _EXECUTION_FIELDS, "RESULT_AUTHORITY", "E field set mismatch")
    return encode_identity("ts2-feature-execution-v1", payload)


def values_content_id(values):
    ordered = sorted(values, key=lambda v: (v.sample_key, spec_pin_id(v.spec_pin)))
    return sequence_id("ts2-feature-values-v1", (v.value_id for v in ordered))


def samples_content_id(samples):
    return sequence_id("ts2-feature-samples-v1", (s.sample_id for s in sorted(samples, key=lambda s: s.sample_key)))
