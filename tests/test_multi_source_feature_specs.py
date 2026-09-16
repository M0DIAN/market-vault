"""Strict spec admission, typed SourceSpec linkage and canonical artifact canaries."""

from dataclasses import FrozenInstanceError, replace
import json

import pytest
import yaml

from market_vault.dataset.models import DatasetField
from market_vault.dataset.spec_models import SpecParameter, SpecValidationError
from market_vault.observation.models import ObservationDimension
from market_vault.observation.pit_models import ObservationSourceSpec
from market_vault.multi_source import (
    ObservationFeatureSpec, parse_observation_feature_spec, serialize_observation_feature_spec,
    observation_feature_spec_content_id, observation_feature_spec_pin,
)


def vector_spec():
    source = ObservationSourceSpec(
        "offline", "series", "rate", (ObservationDimension("tenor", "int64", 10),),
        "EXACT_ENTITY", "US", (), ("value",), "0" * 64, "v1", "1" * 64,
        "v1", "2" * 64, "v1", "3" * 64, "LATEST_EFFECTIVE_AT_OR_BEFORE", None, 1000000, "EXCLUDE_SAMPLE")
    return ObservationFeatureSpec("observation-feature-spec-v1", "obs_rate", "v1",
        DatasetField("obs_rate", "float64", False), source,
        "market_vault.multi_source.feature_transforms:identity_float64")


def payload():
    return json.loads(serialize_observation_feature_spec(vector_spec()))


def test_canary_01_full_typed_source_roundtrip():
    spec = vector_spec()
    assert parse_observation_feature_spec(serialize_observation_feature_spec(spec)) == spec
    assert type(spec.source_spec) is ObservationSourceSpec
    assert spec.source_spec.dimensions == (ObservationDimension("tenor", "int64", 10),)
    with pytest.raises(FrozenInstanceError):
        spec.source_spec.max_age_us = 10


def test_canary_02_yaml_reordering_comments_crlf_canonical_stability():
    data = payload()
    reordered = dict(reversed(tuple(data.items())))
    document = "# semantic input only\r\n" + yaml.safe_dump(reordered, sort_keys=False).replace("\n", "\r\n")
    parsed = parse_observation_feature_spec(document)
    assert parsed == vector_spec()
    assert observation_feature_spec_pin(parsed) == observation_feature_spec_pin(vector_spec())
    assert serialize_observation_feature_spec(parsed) == serialize_observation_feature_spec(vector_spec())
    assert serialize_observation_feature_spec(parsed).endswith(b"\n")
    assert b"\r" not in serialize_observation_feature_spec(parsed)


@pytest.mark.parametrize("change", [
    {"max_age_us": 999}, {"missing_policy": "FAIL"}, {"provider_id": "other"},
    {"dimensions": (ObservationDimension("tenor", "float64", 10.0),)},
    {"value_schema_id": "4" * 64}, {"input_field_names": ("other",)},
])
def test_canary_03_source_mutation_changes_pin(change):
    spec = vector_spec()
    other = replace(spec, source_spec=replace(spec.source_spec, **change))
    assert observation_feature_spec_pin(other) != observation_feature_spec_pin(spec)


def test_dimension_order_is_not_input_field_order():
    spec = vector_spec()
    a, b = ObservationDimension("a", "int64", 1), ObservationDimension("b", "string", "x")
    one = replace(spec, source_spec=replace(spec.source_spec, dimensions=(a, b), input_field_names=("a", "b")))
    two = replace(one, source_spec=replace(one.source_spec, dimensions=(b, a)))
    assert observation_feature_spec_content_id(one) == observation_feature_spec_content_id(two)
    assert observation_feature_spec_content_id(one) != observation_feature_spec_content_id(
        replace(one, source_spec=replace(one.source_spec, input_field_names=("b", "a"))))


@pytest.mark.parametrize("level", ["root", "output", "source", "dimension", "map"])
@pytest.mark.parametrize("mode", ["missing", "extra"])
def test_exact_nested_field_sets(level, mode):
    data = payload()
    if level == "map":
        data["source_spec"].update(entity_binding="SAMPLE_CODE", entity_id=None, code_entity_map=[{"code": "US.TEST", "entity_id": "US"}])
    target = {"root": data, "output": data["output"], "source": data["source_spec"],
              "dimension": data["source_spec"]["dimensions"][0],
              "map": (data["source_spec"]["code_entity_map"] or [{}])[0]}[level]
    if mode == "missing":
        target.pop(next(iter(target)))
    else:
        target["unknown"] = None
    with pytest.raises(SpecValidationError):
        parse_observation_feature_spec(json.dumps(data))


@pytest.mark.parametrize("document", [
    "", "[]", "---\n---\n", "x: &a 1\ny: *a", "x: &a 1", "x: !!str a",
    "x: !custom value", "x: 1\nx: 2", "x: {a: 1, a: 2}", "1: x", "<<: {}",
    "x: 2026-01-02", "x: .nan", "x: .inf", "x: -.inf", "\ufeff{}", b"\xff",
    "\"\u00e9\": 1\n\"e\u0301\": 2", "x: \"unsafe\\u0000\"", None,
])
def test_reject_unsafe_yaml(document):
    with pytest.raises(SpecValidationError):
        parse_observation_feature_spec(document)


@pytest.mark.parametrize("path,value", [
    (("kind",), "LABEL"), (("spec_schema_version",), "future"),
    (("output", "logical_type"), "string"), (("output", "nullable"), True),
    (("output", "name"), "other"), (("output", "nullable"), "false"),
    (("source_spec", "max_age_us"), True), (("source_spec", "input_field_names"), "value"),
    (("source_spec", "dimensions"), [{"name": "tenor", "logical_type": "int64", "value": "10"}]),
    (("source_spec", "dimensions"), [{"name": "tenor", "logical_type": "float64", "value": 10}]),
    (("source_spec", "code_entity_map"), {}), (("name",), "Not_Valid"), (("version",), "v0"),
    (("parameters",), {"bad": []}), (("parameters",), {"bad": 2**63}),
])
def test_invalid_typed_shapes(path, value):
    data = payload()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(SpecValidationError):
        parse_observation_feature_spec(json.dumps(data))


def test_parameter_normalization_and_detachment():
    params = [SpecParameter("z", -0.0), SpecParameter("a", 1)]
    spec = replace(vector_spec(), parameters=params)
    params.clear()
    assert spec.parameters == (SpecParameter("a", 1), SpecParameter("z", 0.0))
    assert parse_observation_feature_spec(serialize_observation_feature_spec(spec)) == spec
    with pytest.raises(SpecValidationError):
        replace(spec, parameters=(SpecParameter("e\u0301", 1), SpecParameter("\u00e9", 2)))


def test_unsafe_unicode_parameters_fail_both_construction_and_parsing():
    with pytest.raises(SpecValidationError):
        replace(vector_spec(), parameters=(SpecParameter("x", "\u200b"),))
    data = payload()
    data["parameters"] = {"x": "\u200b"}
    with pytest.raises(SpecValidationError):
        parse_observation_feature_spec(json.dumps(data))
