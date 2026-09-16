"""Literal known answers for design 12.1/12.2; synthetic pins are encoder-only."""

from dataclasses import replace
from pathlib import Path

import pytest

from market_vault.dataset.encoding import encode_identity
from market_vault.dataset.identity import _implementation_digest
from market_vault.dataset.models import ImplementationPin
from market_vault.observation.pit_identity import feature_spec_pin_id
from market_vault.multi_source import *
from market_vault.multi_source.feature_identity import _source_sha256, _implementation_fingerprint
from market_vault.multi_source.feature_registry import built_in_observation_feature_registrations
from market_vault.multi_source import feature_transforms
from test_multi_source_feature_specs import vector_spec

SPEC = "0b4a8fc8b3150e13e939f71cf6a5628629a376a5f82b4feb2e808d0c7d7d0d0b"
SPEC_PIN = "9a8d16050fac48dd54935d3b3715529a174c93fe493a7712f78f08a271452f7e"
SOURCE = "4e3db3aaf56c8a3737c092843d1b7aee914a99ef44a3144981d07304ca9a2a64"
IMPLEMENTATION = "6d73b7374e37e211bf946aa80ce59ae2074ed36aae8e71581765eeaebbbb012e"
IMPLEMENTATION_PIN = "87d4dea41b02bafe4237f147574d45c6c867a0ca79385753cdc261c6167f7998"
COMPLETE = "ad28f0f465cd4d3d33148f3beb6d3fc956a91b1f333721af9cb4715ed87c371e"
EXCLUDED = "40922e263938f7be69797b31c3eee9204e613ac8a2f91eb78a0e2752b27f0172"
COMPLETE_CONTENT = "b68c7e771908501b35f714f2799fb7a26fdceafa0845882fdf3aff24148d1e27"
EXCLUDED_CONTENT = "824e3e29a9af0e44280a1bce0e33aa7f8a2b1eb07f814096ea49e04a04012652"
EMPTY_CONTENT = "9bc13606480a2d351ba490198f58a1e715ba713f11a0be3774e2c5538dd9b720"
CANONICAL = (
    '{"kind":"FEATURE","name":"obs_rate","output":{"logical_type":"float64","name":"obs_rate","nullable":false},'
    '"parameters":{},"source_spec":{"alignment":"LATEST_EFFECTIVE_AT_OR_BEFORE","code_entity_map":[],"dimensions":'
    '[{"logical_type":"int64","name":"tenor","value":10}],"entity_binding":"EXACT_ENTITY","entity_id":"US",'
    '"exact_target_binding":null,"input_field_names":["value"],"known_at_authority_policy_content_id":'
    '"3333333333333333333333333333333333333333333333333333333333333333","known_at_authority_policy_version":"v1",'
    '"max_age_us":1000000,"missing_policy":"EXCLUDE_SAMPLE","normalization_content_id":'
    '"2222222222222222222222222222222222222222222222222222222222222222","normalization_version":"v1",'
    '"observation_name":"rate","provider_contract_content_id":'
    '"1111111111111111111111111111111111111111111111111111111111111111","provider_contract_version":"v1",'
    '"provider_id":"offline","source_kind":"series","value_schema_id":'
    '"0000000000000000000000000000000000000000000000000000000000000000"},"spec_schema_version":"observation-feature-spec-v1",'
    '"transform_ref":"market_vault.multi_source.feature_transforms:identity_float64","version":"v1"}\n'
).encode("utf-8")


def fixture_value(excluded=False):
    spec = vector_spec()
    impl = ImplementationPin(spec.transform_ref, "v1", IMPLEMENTATION)
    return ObservationFeatureValueResult("0" * 64, "1" * 64, "obs_rate", observation_feature_spec_pin(spec), impl,
        "2" * 64, "EXCLUDED" if excluded else "COMPLETE", None if excluded else 1.25,
        "STALE" if excluded else None, None if excluded else "3" * 64)


def execution(value, *, empty=False):
    samples = () if empty else (ObservationFeatureSampleResult(value.sample_key, value.multi_source_sample_version_id, value.status, (value,)),)
    return ObservationFeatureExecutionResult(samples, (value.spec_pin,), (value.implementation_pin,))


def test_literal_spec_pin_and_canonical_bytes():
    spec = vector_spec()
    assert observation_feature_spec_content_id(spec) == SPEC
    assert feature_spec_pin_id(observation_feature_spec_pin(spec)) == SPEC_PIN
    assert serialize_observation_feature_spec(spec) == CANONICAL
    assert parse_observation_feature_spec(CANONICAL) == spec


def test_literal_fixture_source_and_implementation():
    ref = vector_spec().transform_ref
    assert _source_sha256(b"fixture-module-v1\n") == SOURCE
    assert _source_sha256(b"fixture-module-v1\r\n") == SOURCE
    assert _source_sha256(b"fixture-module-v1\r") == SOURCE
    assert _implementation_fingerprint(ref, SOURCE, "float64") == IMPLEMENTATION
    assert _implementation_digest(ImplementationPin(ref, "v1", IMPLEMENTATION)) == IMPLEMENTATION_PIN
    with pytest.raises(UnicodeError):
        _source_sha256(b"\xff")


@pytest.mark.parametrize("excluded,expected,content", [(False, COMPLETE, COMPLETE_CONTENT), (True, EXCLUDED, EXCLUDED_CONTENT)])
def test_literal_value_and_content(excluded, expected, content):
    value = fixture_value(excluded)
    assert observation_feature_value_id(value) == expected
    assert observation_feature_values_content_id(execution(value)) == content
    # A separately written payload checks the field/domain mapping, not only a wrapper.
    assert encode_identity("observation-feature-value-v1", {
        "sample_key": "0" * 64, "multi_source_sample_version_id": "1" * 64, "feature_name": "obs_rate",
        "feature_spec_pin_id": SPEC_PIN, "implementation_pin_id": IMPLEMENTATION_PIN,
        "decision_id": "2" * 64, "status": "EXCLUDED" if excluded else "COMPLETE",
        "value": None if excluded else 1.25, "reason_code": "STALE" if excluded else None,
        "consumed_observation_version_id": None if excluded else "3" * 64}) == expected


def test_literal_empty_sequence():
    assert observation_feature_values_content_id(execution(fixture_value(), empty=True)) == EMPTY_CONTENT


def test_canary_13_fingerprint_changes_upstream_values_not_yet_dataset():
    value = fixture_value()
    digest = _implementation_fingerprint(value.implementation_pin.name, _source_sha256(b"fixture-module-v2\n"), "float64")
    changed = replace(value, implementation_pin=replace(value.implementation_pin, content_sha256=digest))
    assert changed.implementation_pin != value.implementation_pin
    assert observation_feature_value_id(changed) != COMPLETE
    assert observation_feature_values_content_id(execution(changed)) != COMPLETE_CONTENT


def test_both_production_pins_bind_normalized_complete_module():
    source = Path(feature_transforms.__file__).read_bytes()
    digest = _source_sha256(source)
    for r in built_in_observation_feature_registrations():
        assert r.implementation_content_sha256 == _implementation_fingerprint(r.transform_ref, digest, r.output_logical_type)
        assert r.implementation_content_sha256 != _implementation_fingerprint(r.transform_ref, _source_sha256(source + b"\n"), r.output_logical_type)


@pytest.mark.parametrize("field,change", [("sample_key", "4" * 64), ("multi_source_sample_version_id", "4" * 64),
    ("decision_id", "4" * 64), ("value", 1.5), ("consumed_observation_version_id", "4" * 64)])
def test_value_provenance_fields_are_identity_bearing(field, change):
    assert observation_feature_value_id(replace(fixture_value(), **{field: change})) != COMPLETE
