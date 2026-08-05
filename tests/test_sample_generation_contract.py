"""Contract tests of the v0.6.0 Sample Generation contract foundation
(PR-2): frozen typed models and normalization, the strict generation-plan
parser, the canonical serializer, the deterministic semantic content
identity, the boundary guarantees, and compatibility with the existing
Dataset / PIT contracts.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from market_vault.dataset import (
    SAMPLE_GENERATION_CONTRACT_VERSION,
    SAMPLE_GENERATION_CONTENT_ID_VERSION,
    SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
    SampleGenerationError,
    SampleGenerationIdentityInput,
    SampleGenerationPlan,
    SampleGenerationRule,
    parse_sample_generation_plan_bytes,
    sample_generation_content_id,
    serialize_sample_generation_plan,
)
from market_vault.dataset.encoding import DatasetError
from market_vault.dataset.models import (
    CanonicalBuildPin,
    DatasetScope,
    SpecPin,
)

ROOT = Path(__file__).resolve().parents[1]

# Frozen regression constants (deterministic behavior of the public API).
BASE_IDENTITY = "87aa4bf8d510309840026a9c28ea2926737f405bce4e7f991f57ce1552fd6543"
PIT_SAMPLE_KEY = "befde94fc1cc94d00bb6074b79e36846acdfa19d1d81472c87c2a38c1f0a2091"

HEX_64 = "0123456789abcdef" * 4


# ---------------------------------------------------------------------------
# Fixtures and helpers.
# ---------------------------------------------------------------------------


def canonical_pin(build_id: str = "a" * 64, **overrides) -> CanonicalBuildPin:
    values = dict(
        canonical_build_id=build_id,
        canonical_content_id="b" * 64,
        canonical_builder_version="v1",
        canonical_schema_version="v1",
        materializer_version="v1",
        gap_policy_version="v1",
        gap_content_id="c" * 64,
        status="COMPLETE",
        canonical_row_version_ids=("d" * 64,),
        source_snapshots=(),
    )
    values.update(overrides)
    return CanonicalBuildPin(**values)


def spec_pin(
    kind: str = "FEATURE",
    name: str = "feature_simple_return",
    content: str = "e" * 64,
    version: str = "v1",
    **overrides,
) -> SpecPin:
    values = dict(kind=kind, name=name, version=version, content_sha256=content)
    values.update(overrides)
    return SpecPin(**values)


def sample_scope(**overrides) -> DatasetScope:
    values = dict(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )
    values.update(overrides)
    return DatasetScope(**values)


def generation_rule(**overrides) -> SampleGenerationRule:
    values = dict(
        rule_schema_version=SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
        feature_window_bars=60,
        label_window_bars=30,
        stride_bars=5,
        anchor_source="VERIFIED_CANONICAL_BARS",
        anchor_rule="FEATURE_WINDOW_CLOSE",
        cross_day_policy="REJECT",
    )
    values.update(overrides)
    return SampleGenerationRule(**values)


def identity_input(**overrides) -> SampleGenerationIdentityInput:
    values = dict(
        canonical_build_pins=(canonical_pin(),),
        feature_spec_pins=(spec_pin(kind="FEATURE"),),
        label_spec_pins=(spec_pin(kind="LABEL", name="label_forward_return", content="f" * 64),),
        split_spec_pin=spec_pin(kind="SPLIT", name="chronological_split", content="0" * 64),
        scope=sample_scope(),
        generation_rule=generation_rule(),
        dataset_as_of=None,
    )
    values.update(overrides)
    return SampleGenerationIdentityInput(**values)


def sample_plan(**overrides) -> SampleGenerationPlan:
    values = dict(
        generation_plan_schema_version=SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
        canonical_build_dirs=("canonical/US.MU/2026-07-01",),
        feature_spec_files=("specs/features/simple_return_v1.yaml",),
        label_spec_files=("specs/labels/forward_return_v1.yaml",),
        split_spec_file="specs/splits/chronological_v1.yaml",
        scope=sample_scope(),
        generation_rule=generation_rule(),
        dataset_as_of=None,
        output_root="datasets",
        built_at=datetime(2026, 8, 5, 10, 0, tzinfo=timezone(timedelta(hours=9))),
        output_plan_path="plans/generated/plan-1.json",
    )
    values.update(overrides)
    return SampleGenerationPlan(**values)


VALID_PLAN = {
    "generation_plan_schema_version": SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    "canonical_build_dirs": [
        "canonical/US.MU/2026-07-01",
        "canonical/US.MU/2026-07-02",
    ],
    "feature_spec_files": [
        "specs/features/simple_return_v1.yaml",
        "specs/features/rolling_mean_v1.yaml",
    ],
    "label_spec_files": ["specs/labels/forward_return_v1.yaml"],
    "split_spec_file": "specs/splits/chronological_v1.yaml",
    "scope": {
        "symbols": ["US.MU", "US.AAPL"],
        "trade_dates": ["2026-07-01", "2026-07-02"],
        "interval": "1m",
        "adjustment": "NONE",
        "requested_session": "ALL",
    },
    "generation_rule": {
        "rule_schema_version": SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
        "feature_window_bars": 60,
        "label_window_bars": 30,
        "stride_bars": 5,
        "anchor_source": "VERIFIED_CANONICAL_BARS",
        "anchor_rule": "FEATURE_WINDOW_CLOSE",
        "cross_day_policy": "REJECT",
    },
    "dataset_as_of": "2026-08-01T00:00:00+00:00",
    "output_root": "datasets",
    "built_at": "2026-08-05T10:00:00+09:00",
    "output_plan_path": "plans/generated/plan-1.json",
}


def valid_payload(**mutations) -> bytes:
    payload = json.loads(json.dumps(VALID_PLAN))
    payload.update(mutations)
    return json.dumps(payload).encode("utf-8")


def parse_payload(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# A. Model freezing and normalization.
# ---------------------------------------------------------------------------


def test_rule_is_frozen():
    rule = generation_rule()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.feature_window_bars = 1


def test_plan_is_frozen():
    plan = sample_plan()
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.output_root = "other"


def test_identity_input_is_frozen():
    entry = identity_input()
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.scope = None


def test_nested_sequences_are_tuples():
    plan = sample_plan()
    assert type(plan.canonical_build_dirs) is tuple
    assert type(plan.feature_spec_files) is tuple
    assert type(plan.label_spec_files) is tuple
    assert type(plan.scope.symbols) is tuple


def test_scope_symbol_case_normalization():
    scope = DatasetScope(
        symbols=("us.mu", "US.AAPL"),
        trade_dates=(date(2026, 7, 1),),
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )
    assert scope.symbols == ("US.AAPL", "US.MU")


def test_scope_interval_lowercase():
    scope = DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        interval="1M",
        adjustment="NONE",
        requested_session="ALL",
    )
    assert scope.interval == "1m"


def test_scope_adjustment_and_session_uppercase():
    scope = DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        interval="1m",
        adjustment="none",
        requested_session="all",
    )
    assert scope.adjustment == "NONE"
    assert scope.requested_session == "ALL"


def test_scope_trade_dates_sorted():
    scope = DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 2), date(2026, 7, 1)),
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )
    assert scope.trade_dates == (date(2026, 7, 1), date(2026, 7, 2))


def test_path_arrays_sorted_at_construction():
    plan = sample_plan(
        canonical_build_dirs=("dir/b", "dir/a"),
        feature_spec_files=("specs/b.yaml", "specs/a.yaml"),
        label_spec_files=("labels/b.yaml", "labels/a.yaml"),
    )
    assert plan.canonical_build_dirs == ("dir/a", "dir/b")
    assert plan.feature_spec_files == ("specs/a.yaml", "specs/b.yaml")
    assert plan.label_spec_files == ("labels/a.yaml", "labels/b.yaml")


def test_instants_normalized_to_utc_microseconds():
    plan = sample_plan()
    assert plan.built_at == datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    assert plan.built_at.tzinfo is timezone.utc


def test_equivalent_timezone_representations_equal():
    plan_a = sample_plan(
        built_at=datetime(2026, 8, 5, 10, 0, tzinfo=timezone(timedelta(hours=9))),
        dataset_as_of=datetime(2026, 8, 1, 9, 0, tzinfo=timezone(timedelta(hours=9))),
    )
    plan_b = sample_plan(
        built_at=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
        dataset_as_of=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert plan_a.built_at == plan_b.built_at
    assert plan_a.dataset_as_of == plan_b.dataset_as_of
    assert plan_a == plan_b


# ---------------------------------------------------------------------------
# B. Strict parser.
# ---------------------------------------------------------------------------


def test_parse_full_valid_plan():
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert plan.generation_plan_schema_version == SAMPLE_GENERATION_PLAN_SCHEMA_VERSION
    assert plan.canonical_build_dirs == (
        "canonical/US.MU/2026-07-01",
        "canonical/US.MU/2026-07-02",
    )
    assert plan.scope.symbols == ("US.AAPL", "US.MU")
    assert plan.scope.interval == "1m"
    assert plan.scope.adjustment == "NONE"
    assert plan.scope.requested_session == "ALL"
    assert plan.generation_rule.feature_window_bars == 60
    assert plan.generation_rule.label_window_bars == 30
    assert plan.generation_rule.stride_bars == 5
    assert plan.dataset_as_of == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert plan.built_at == datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    assert plan.output_root == "datasets"
    assert plan.output_plan_path == "plans/generated/plan-1.json"


def test_root_unknown_field_fails():
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(valid_payload(extra_field="x"))


def test_root_missing_field_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    del payload["output_plan_path"]
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_nested_unknown_field_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["scope"]["extra"] = "x"
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_rule_unknown_field_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["generation_rule"]["extra"] = 1
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_nested_missing_field_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    del payload["scope"]["requested_session"]
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_rule_missing_field_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    del payload["generation_rule"]["stride_bars"]
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_duplicate_root_key_fails():
    payload = (
        '{"generation_plan_schema_version": "market-vault-sample-generation-plan-v1", '
        '"generation_plan_schema_version": "market-vault-sample-generation-plan-v1"}'
    ).encode("utf-8")
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(payload)


def test_duplicate_nested_key_fails():
    payload = (
        '{"scope": {"symbols": ["US.MU"], "symbols": ["US.AAPL"]}}'
    ).encode("utf-8")
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(payload)


def test_bom_fails():
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(b"\xef\xbb\xbf" + valid_payload())


def test_invalid_utf8_fails():
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(b"\xff\xfe\x00garbage")


def test_root_non_object_fails():
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(b'["a", "b"]')


def test_null_in_wrong_position_fails():
    for key in (
        "output_root",
        "built_at",
        "split_spec_file",
        "output_plan_path",
        "scope",
        "generation_rule",
        "canonical_build_dirs",
    ):
        with pytest.raises(SampleGenerationError):
            parse_sample_generation_plan_bytes(valid_payload(**{key: None}))


def test_null_dataset_as_of_is_legal():
    plan = parse_sample_generation_plan_bytes(valid_payload(dataset_as_of=None))
    assert plan.dataset_as_of is None


def test_bool_instead_of_int_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["generation_rule"]["feature_window_bars"] = True
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_float_instead_of_int_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["generation_rule"]["feature_window_bars"] = 60.0
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_string_instead_of_int_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["generation_rule"]["feature_window_bars"] = "60"
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


@pytest.mark.parametrize("field", ("feature_window_bars", "label_window_bars", "stride_bars"))
def test_zero_and_negative_bars_fail(field):
    for value in (0, -1):
        payload = json.loads(json.dumps(VALID_PLAN))
        payload["generation_rule"][field] = value
        with pytest.raises(SampleGenerationError):
            parse_sample_generation_plan_bytes(parse_payload(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("anchor_source", "SYNTHETIC_BARS"),
        ("anchor_rule", "LABEL_WINDOW_CLOSE"),
        ("cross_day_policy", "ALLOW"),
    ),
)
def test_unknown_enum_fails(field, value):
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["generation_rule"][field] = value
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_naive_datetime_fails():
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(
            valid_payload(built_at="2026-08-05T10:00:00")
        )


def test_empty_arrays_fail():
    for key in ("canonical_build_dirs", "feature_spec_files", "label_spec_files"):
        with pytest.raises(SampleGenerationError):
            parse_sample_generation_plan_bytes(valid_payload(**{key: []}))
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["scope"]["symbols"] = []
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["scope"]["trade_dates"] = []
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_duplicate_paths_fail():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["canonical_build_dirs"] = [
        "canonical/US.MU/2026-07-01",
        "canonical/US.MU/2026-07-01",
    ]
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_duplicate_symbols_after_normalization_fail():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["scope"]["symbols"] = ["US.MU", "us.mu"]
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_duplicate_trade_dates_after_normalization_fail():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["scope"]["trade_dates"] = ["2026-07-01", "2026-07-01"]
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


@pytest.mark.parametrize(
    "path",
    (
        "canonical/./US.MU",
        "canonical/../US.MU",
        "canonical/US.MU/..",
        "canonical/*/US.MU",
        "canonical/US.MU/2026-07-?",
        "canonical/[US].MU",
        "~/canonical/US.MU",
        "$HOME/canonical/US.MU",
        "%USERPROFILE%/canonical/US.MU",
    ),
)
def test_unsafe_paths_fail(path):
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["canonical_build_dirs"] = [path]
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_null_adjustment_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["scope"]["adjustment"] = None
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_adjustment_other_than_none_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["scope"]["adjustment"] = "ADJUSTED"
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_string_payload_rejected():
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes("not bytes")  # type: ignore[arg-type]


def test_unsupported_plan_schema_version_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["generation_plan_schema_version"] = "market-vault-sample-generation-plan-v9"
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_unsupported_rule_schema_version_fails():
    payload = json.loads(json.dumps(VALID_PLAN))
    payload["generation_rule"]["rule_schema_version"] = "market-vault-sample-generation-rule-v9"
    with pytest.raises(SampleGenerationError):
        parse_sample_generation_plan_bytes(parse_payload(payload))


def test_json_key_order_does_not_matter():
    plan_a = parse_sample_generation_plan_bytes(valid_payload())
    reordered = json.loads(json.dumps(VALID_PLAN))
    plan_b = parse_sample_generation_plan_bytes(
        json.dumps(reordered, sort_keys=True).encode("utf-8")
    )
    assert plan_a == plan_b


def test_json_whitespace_does_not_matter():
    plan_a = parse_sample_generation_plan_bytes(valid_payload())
    plan_b = parse_sample_generation_plan_bytes(
        json.dumps(VALID_PLAN, indent=4, sort_keys=True).encode("utf-8")
    )
    assert plan_a == plan_b


def test_parse_does_not_require_canonical_json_form():
    # Compact and pretty forms both parse; no canonical JSON form is
    # required for parsing.
    plan = parse_sample_generation_plan_bytes(
        json.dumps(VALID_PLAN, indent=2).encode("utf-8")
    )
    assert plan is not None


# ---------------------------------------------------------------------------
# C. Canonical serializer.
# ---------------------------------------------------------------------------


def test_exact_canonical_bytes():
    plan = parse_sample_generation_plan_bytes(valid_payload())
    expected = (
        b'{"built_at":"2026-08-05T01:00:00.000000+00:00",'
        b'"canonical_build_dirs":["canonical/US.MU/2026-07-01","canonical/US.MU/2026-07-02"],'
        b'"dataset_as_of":"2026-08-01T00:00:00.000000+00:00",'
        b'"feature_spec_files":["specs/features/rolling_mean_v1.yaml","specs/features/simple_return_v1.yaml"],'
        b'"generation_plan_schema_version":"market-vault-sample-generation-plan-v1",'
        b'"generation_rule":{"anchor_rule":"FEATURE_WINDOW_CLOSE","anchor_source":"VERIFIED_CANONICAL_BARS",'
        b'"cross_day_policy":"REJECT","feature_window_bars":60,"label_window_bars":30,'
        b'"rule_schema_version":"market-vault-sample-generation-rule-v1","stride_bars":5},'
        b'"label_spec_files":["specs/labels/forward_return_v1.yaml"],'
        b'"output_plan_path":"plans/generated/plan-1.json","output_root":"datasets",'
        b'"scope":{"adjustment":"NONE","interval":"1m","requested_session":"ALL",'
        b'"symbols":["US.AAPL","US.MU"],"trade_dates":["2026-07-01","2026-07-02"]},'
        b'"split_spec_file":"specs/splits/chronological_v1.yaml"}\n'
    )
    assert serialize_sample_generation_plan(plan) == expected


def test_exactly_one_trailing_newline():
    data = serialize_sample_generation_plan(sample_plan())
    assert data.endswith(b"\n")
    assert not data.endswith(b"\n\n")


def test_no_bom():
    data = serialize_sample_generation_plan(sample_plan())
    assert not data.startswith(b"\xef\xbb\xbf")


def test_sorted_keys():
    data = serialize_sample_generation_plan(sample_plan())
    parsed = json.loads(data)
    assert list(parsed.keys()) == sorted(parsed.keys())
    assert list(parsed["scope"].keys()) == sorted(parsed["scope"].keys())
    assert list(parsed["generation_rule"].keys()) == sorted(parsed["generation_rule"].keys())


def test_compact_separators():
    data = serialize_sample_generation_plan(sample_plan()).decode("utf-8")
    assert ": " not in data
    assert ", " not in data
    assert "} " not in data


def test_ensure_ascii():
    plan = sample_plan(canonical_build_dirs=("canonical/テスト",))
    data = serialize_sample_generation_plan(plan)
    assert b"\xe3\x83\x86" not in data  # raw UTF-8 of テ must not appear
    assert b"\\u30c6" in data


def test_utc_six_digit_microseconds():
    plan = sample_plan(built_at=datetime(2026, 8, 5, 1, 0, 0, 123456, tzinfo=timezone.utc))
    data = serialize_sample_generation_plan(plan).decode("utf-8")
    assert '"built_at":"2026-08-05T01:00:00.123456+00:00"' in data


def test_roundtrip_parser_serializer_equal():
    plan = parse_sample_generation_plan_bytes(valid_payload())
    reparsed = parse_sample_generation_plan_bytes(serialize_sample_generation_plan(plan))
    assert reparsed == plan
    assert reparsed.scope == plan.scope
    assert reparsed.generation_rule == plan.generation_rule


def test_same_model_serializes_byte_identical():
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert serialize_sample_generation_plan(plan) == serialize_sample_generation_plan(plan)


def test_different_json_key_order_same_canonical_bytes():
    plan_a = parse_sample_generation_plan_bytes(valid_payload())
    plan_b = parse_sample_generation_plan_bytes(
        json.dumps(VALID_PLAN, sort_keys=True).encode("utf-8")
    )
    assert serialize_sample_generation_plan(plan_a) == serialize_sample_generation_plan(plan_b)


def test_different_path_array_input_order_same_canonical_bytes():
    payload_a = json.loads(json.dumps(VALID_PLAN))
    payload_b = json.loads(json.dumps(VALID_PLAN))
    payload_b["canonical_build_dirs"] = list(reversed(payload_a["canonical_build_dirs"]))
    payload_b["feature_spec_files"] = list(reversed(payload_a["feature_spec_files"]))
    plan_a = parse_sample_generation_plan_bytes(parse_payload(payload_a))
    plan_b = parse_sample_generation_plan_bytes(parse_payload(payload_b))
    assert serialize_sample_generation_plan(plan_a) == serialize_sample_generation_plan(plan_b)


def test_serializer_rejects_wrong_type():
    with pytest.raises(SampleGenerationError):
        serialize_sample_generation_plan("not a plan")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# D. Deterministic semantic content identity.
# ---------------------------------------------------------------------------


def test_identity_is_64_character_lowercase_hex():
    content_id = sample_generation_content_id(identity_input())
    assert len(content_id) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", content_id)


def test_identity_frozen_regression_value():
    assert sample_generation_content_id(identity_input()) == BASE_IDENTITY


def test_identity_input_order_does_not_matter():
    base = identity_input()
    canonical_pins = base.canonical_build_pins[::-1]
    feature_pins = base.feature_spec_pins[::-1]
    label_pins = base.label_spec_pins[::-1]
    assert sample_generation_content_id(
        identity_input(
            canonical_build_pins=canonical_pins,
            feature_spec_pins=feature_pins,
            label_spec_pins=label_pins,
        )
    ) == sample_generation_content_id(base)


def test_canonical_pin_order_does_not_matter():
    entry_a = identity_input(
        canonical_build_pins=(canonical_pin("1" * 64), canonical_pin("2" * 64))
    )
    entry_b = identity_input(
        canonical_build_pins=(canonical_pin("2" * 64), canonical_pin("1" * 64))
    )
    assert sample_generation_content_id(entry_a) == sample_generation_content_id(entry_b)


def test_feature_pin_order_does_not_matter():
    entry_a = identity_input(
        feature_spec_pins=(
            spec_pin(kind="FEATURE", name="feature_a", content="1" * 64),
            spec_pin(kind="FEATURE", name="feature_b", content="2" * 64),
        )
    )
    entry_b = identity_input(
        feature_spec_pins=(
            spec_pin(kind="FEATURE", name="feature_b", content="2" * 64),
            spec_pin(kind="FEATURE", name="feature_a", content="1" * 64),
        )
    )
    assert sample_generation_content_id(entry_a) == sample_generation_content_id(entry_b)


def test_label_pin_order_does_not_matter():
    entry_a = identity_input(
        label_spec_pins=(
            spec_pin(kind="LABEL", name="label_a", content="1" * 64),
            spec_pin(kind="LABEL", name="label_b", content="2" * 64),
        )
    )
    entry_b = identity_input(
        label_spec_pins=(
            spec_pin(kind="LABEL", name="label_b", content="2" * 64),
            spec_pin(kind="LABEL", name="label_a", content="1" * 64),
        )
    )
    assert sample_generation_content_id(entry_a) == sample_generation_content_id(entry_b)


def test_equivalent_timezone_does_not_change_identity():
    instant_utc = datetime(2026, 8, 1, tzinfo=timezone.utc)
    instant_jst = datetime(2026, 8, 1, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    assert sample_generation_content_id(
        identity_input(dataset_as_of=instant_utc)
    ) == sample_generation_content_id(identity_input(dataset_as_of=instant_jst))


def test_path_changes_do_not_change_identity():
    # The identity input carries no paths at all; plans that differ only in
    # path inputs produce the same identity.
    base = identity_input()
    assert sample_generation_content_id(base) == sample_generation_content_id(base)
    plan_a = sample_plan()
    plan_b = sample_plan(canonical_build_dirs=("other/dir",), split_spec_file="other/split.yaml")
    assert plan_a != plan_b
    # The identity is computed only from the normalized semantic inputs.
    assert sample_generation_content_id(
        identity_input(scope=plan_a.scope, generation_rule=plan_a.generation_rule)
    ) == sample_generation_content_id(
        identity_input(scope=plan_b.scope, generation_rule=plan_b.generation_rule)
    )


def test_output_root_change_does_not_change_identity():
    plan_a = sample_plan(output_root="datasets")
    plan_b = sample_plan(output_root="elsewhere")
    assert sample_generation_content_id(
        identity_input(scope=plan_a.scope, generation_rule=plan_a.generation_rule)
    ) == sample_generation_content_id(
        identity_input(scope=plan_b.scope, generation_rule=plan_b.generation_rule)
    )


def test_built_at_change_does_not_change_identity():
    plan_a = sample_plan(built_at=datetime(2026, 8, 5, tzinfo=timezone.utc))
    plan_b = sample_plan(built_at=datetime(2026, 8, 6, tzinfo=timezone.utc))
    assert sample_generation_content_id(
        identity_input(scope=plan_a.scope, generation_rule=plan_a.generation_rule)
    ) == sample_generation_content_id(
        identity_input(scope=plan_b.scope, generation_rule=plan_b.generation_rule)
    )


def test_output_plan_path_change_does_not_change_identity():
    plan_a = sample_plan(output_plan_path="plans/a.json")
    plan_b = sample_plan(output_plan_path="plans/b.json")
    assert sample_generation_content_id(
        identity_input(scope=plan_a.scope, generation_rule=plan_a.generation_rule)
    ) == sample_generation_content_id(
        identity_input(scope=plan_b.scope, generation_rule=plan_b.generation_rule)
    )


def test_raw_json_whitespace_does_not_change_identity():
    plan_a = parse_sample_generation_plan_bytes(valid_payload())
    plan_b = parse_sample_generation_plan_bytes(
        json.dumps(VALID_PLAN, indent=4).encode("utf-8")
    )
    assert sample_generation_content_id(
        identity_input(scope=plan_a.scope, generation_rule=plan_a.generation_rule)
    ) == sample_generation_content_id(
        identity_input(scope=plan_b.scope, generation_rule=plan_b.generation_rule)
    )


def test_canonical_build_id_change_changes_identity():
    assert sample_generation_content_id(
        identity_input(canonical_build_pins=(canonical_pin("1" * 64),))
    ) != sample_generation_content_id(
        identity_input(canonical_build_pins=(canonical_pin("2" * 64),))
    )


def test_feature_pin_change_changes_identity():
    base = identity_input()
    assert sample_generation_content_id(
        identity_input(
            feature_spec_pins=(spec_pin(kind="FEATURE", name="other_name"),)
        )
    ) != sample_generation_content_id(base)


def test_label_pin_change_changes_identity():
    base = identity_input()
    assert sample_generation_content_id(
        identity_input(
            label_spec_pins=(spec_pin(kind="LABEL", name="other_label"),)
        )
    ) != sample_generation_content_id(base)


def test_split_pin_change_changes_identity():
    base = identity_input()
    assert sample_generation_content_id(
        identity_input(
            split_spec_pin=spec_pin(kind="SPLIT", name="other_split", content="9" * 64)
        )
    ) != sample_generation_content_id(base)


def test_scope_change_changes_identity():
    base = identity_input()
    assert sample_generation_content_id(
        identity_input(scope=sample_scope(symbols=("US.OTHER",)))
    ) != sample_generation_content_id(base)


def test_rule_change_changes_identity():
    base = identity_input()
    assert sample_generation_content_id(
        identity_input(generation_rule=generation_rule(feature_window_bars=120))
    ) != sample_generation_content_id(base)


def test_dataset_as_of_change_changes_identity():
    base = identity_input(dataset_as_of=None)
    changed = identity_input(dataset_as_of=datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert sample_generation_content_id(changed) != sample_generation_content_id(base)


def test_duplicate_canonical_build_id_fails():
    with pytest.raises(SampleGenerationError):
        identity_input(
            canonical_build_pins=(canonical_pin("1" * 64), canonical_pin("1" * 64))
        )


def test_duplicate_feature_logical_key_fails():
    with pytest.raises(SampleGenerationError):
        identity_input(
            feature_spec_pins=(
                spec_pin(kind="FEATURE", name="feature_a"),
                spec_pin(kind="FEATURE", name="feature_a"),
            )
        )


def test_duplicate_label_logical_key_fails():
    with pytest.raises(SampleGenerationError):
        identity_input(
            label_spec_pins=(
                spec_pin(kind="LABEL", name="label_a", content="1" * 64),
                spec_pin(kind="LABEL", name="label_a", content="2" * 64),
            )
        )


def test_wrong_spec_pin_kind_fails():
    with pytest.raises(SampleGenerationError):
        identity_input(feature_spec_pins=(spec_pin(kind="LABEL"),))
    with pytest.raises(SampleGenerationError):
        identity_input(label_spec_pins=(spec_pin(kind="FEATURE"),))
    with pytest.raises(SampleGenerationError):
        identity_input(split_spec_pin=spec_pin(kind="FEATURE"))


def test_wrong_input_model_type_fails():
    with pytest.raises(SampleGenerationError):
        identity_input(scope="US.MU")  # type: ignore[arg-type]
    with pytest.raises(SampleGenerationError):
        identity_input(generation_rule=None)  # type: ignore[arg-type]
    with pytest.raises(SampleGenerationError):
        identity_input(canonical_build_pins=("a" * 64,))  # type: ignore[arg-type]
    with pytest.raises(SampleGenerationError):
        sample_generation_content_id("not an identity input")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# E. Boundary guarantees.
# ---------------------------------------------------------------------------


def test_parser_never_reads_files(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        Path, "read_bytes", lambda self, *a, **k: pytest.fail("parser must not read files")
    )
    monkeypatch.setattr(
        Path, "read_text", lambda self, *a, **k: pytest.fail("parser must not read files")
    )
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert plan is not None


def test_serializer_never_writes_files(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        Path, "write_bytes", lambda self, *a, **k: pytest.fail("serializer must not write")
    )
    monkeypatch.setattr(
        Path, "write_text", lambda self, *a, **k: pytest.fail("serializer must not write")
    )
    assert serialize_sample_generation_plan(sample_plan())


def test_identity_never_accesses_filesystem(monkeypatch):
    monkeypatch.setattr(
        "builtins.open", lambda *a, **k: pytest.fail("identity must not open files")
    )
    content_id = sample_generation_content_id(identity_input())
    assert len(content_id) == 64


def test_parser_serializer_identity_never_use_current_time(monkeypatch):
    # The C datetime type cannot be patched directly; the module-level
    # ``datetime`` names are replaced with a subclass that fails on any
    # current-time access, proving no ``now()`` / ``utcnow()`` call exists
    # on any contract path.
    from datetime import datetime as _real_datetime

    class _NoNowDatetime(_real_datetime):
        @classmethod
        def now(cls, *args, **kwargs):
            pytest.fail("current time must never be read")

        @classmethod
        def utcnow(cls, *args, **kwargs):
            pytest.fail("current time must never be read")

    import market_vault.dataset.sample_generation as sample_generation
    import market_vault.dataset.sample_generation_models as sample_generation_models

    monkeypatch.setattr(sample_generation, "datetime", _NoNowDatetime)
    monkeypatch.setattr(sample_generation_models, "datetime", _NoNowDatetime)
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert serialize_sample_generation_plan(plan)
    assert sample_generation_content_id(identity_input())


def test_parser_serializer_identity_never_use_network(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("no network"))
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert serialize_sample_generation_plan(plan)
    assert sample_generation_content_id(identity_input())


def test_contract_layers_never_load_settings(monkeypatch):
    import market_vault.config as config

    monkeypatch.setattr(
        config, "load_settings", lambda *a, **k: pytest.fail("settings must not be loaded")
    )
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert serialize_sample_generation_plan(plan)
    assert sample_generation_content_id(identity_input())


def test_contract_layers_never_load_verified_canonical_build(monkeypatch):
    from market_vault.canonical import reader

    monkeypatch.setattr(
        reader,
        "load_verified_canonical_build",
        lambda *a, **k: pytest.fail("verified canonical reader must not be called"),
    )
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert serialize_sample_generation_plan(plan)
    assert sample_generation_content_id(identity_input())


def test_contract_layers_never_construct_pit_sample_request(monkeypatch):
    from market_vault.dataset import pit_models

    monkeypatch.setattr(
        pit_models,
        "PITSampleRequest",
        lambda *a, **k: pytest.fail("no request may be constructed"),
    )
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert serialize_sample_generation_plan(plan)
    assert sample_generation_content_id(identity_input())


def test_contract_layers_never_orchestrate_dataset_build(monkeypatch):
    from market_vault.dataset import orchestration

    monkeypatch.setattr(
        orchestration,
        "orchestrate_dataset_build",
        lambda *a, **k: pytest.fail("dataset orchestration must not be called"),
    )
    plan = parse_sample_generation_plan_bytes(valid_payload())
    assert serialize_sample_generation_plan(plan)
    assert sample_generation_content_id(identity_input())


def test_production_sources_have_no_forbidden_calls():
    sources = []
    for rel in (
        "src/market_vault/dataset/sample_generation_models.py",
        "src/market_vault/dataset/sample_generation.py",
    ):
        sources.append((ROOT / rel).read_text(encoding="utf-8"))
    text = "\n".join(sources)
    for forbidden in (
        "datetime.now",
        "load_verified_canonical_build",
        "PITSampleRequest(",
        "orchestrate_dataset_build",
        "urllib",
        "socket",
        "requests.",
        "load_settings",
        "opend",
        "pathlib",
        "Path(",
    ):
        assert forbidden not in text, f"forbidden call {forbidden!r} found in production sources"


# ---------------------------------------------------------------------------
# F. Compatibility with existing contracts.
# ---------------------------------------------------------------------------


def test_existing_public_exports_unchanged():
    import market_vault.dataset as dataset

    for name in (
        "dataset_id",
        "pit_sample_key",
        "pit_sample_version_id",
        "DatasetScope",
        "PITSampleRequest",
        "CanonicalBuildPin",
        "SpecPin",
        "orchestrate_dataset_build",
        "parse_feature_spec",
        "parse_label_spec",
        "chronological_split_spec_pin",
        "DATASET_IDENTITY_ENCODING_VERSION",
    ):
        assert name in dataset.__all__


def test_pit_sample_key_behavior_unchanged():
    from market_vault.dataset import PITSampleRequest, pit_sample_key

    request = PITSampleRequest(
        code="US.MU",
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
        anchor_market_calendar_date=date(2026, 7, 1),
        feature_window_start=datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc),
        feature_window_close=datetime(2026, 7, 1, 13, 31, tzinfo=timezone.utc),
    )
    assert pit_sample_key(request) == PIT_SAMPLE_KEY


def test_pit_sample_request_window_constraints_unchanged():
    from market_vault.dataset import PITSampleRequest

    with pytest.raises(Exception):
        PITSampleRequest(
            code="US.MU",
            interval="1m",
            adjustment="ADJUSTED",
            requested_session="ALL",
            anchor_market_calendar_date=date(2026, 7, 1),
            feature_window_start=datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc),
            feature_window_close=datetime(2026, 7, 1, 13, 31, tzinfo=timezone.utc),
        )


def test_dataset_scope_unchanged():
    scope = DatasetScope(
        symbols=("US.MU", "US.AAPL", "us.mu"),
        trade_dates=(date(2026, 7, 2), date(2026, 7, 1)),
        interval="1M",
        adjustment="none",
        requested_session="all",
    )
    assert scope.symbols == ("US.AAPL", "US.MU")
    assert scope.trade_dates == (date(2026, 7, 1), date(2026, 7, 2))
    assert scope.interval == "1m"
    assert scope.adjustment == "NONE"
    assert scope.requested_session == "ALL"


def test_build_plan_parser_unchanged():
    from market_vault.dataset.cli import DatasetCLIError, parse_build_plan_bytes

    with pytest.raises(DatasetCLIError):
        parse_build_plan_bytes(b"not json")


def test_canonical_build_pin_and_spec_pin_unchanged():
    pin = canonical_pin()
    assert pin.status == "COMPLETE"
    assert pin.canonical_build_id == "a" * 64
    spec = spec_pin()
    assert spec.kind == "FEATURE"
    assert spec.name == "feature_simple_return"


def test_documented_example_is_parseable():
    text = (ROOT / "docs" / "contracts" / "sample_generation.md").read_text(
        encoding="utf-8"
    )
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
    assert len(blocks) == 1, "contract doc must contain exactly one JSON example"
    plan = parse_sample_generation_plan_bytes(blocks[0].encode("utf-8"))
    assert plan.generation_plan_schema_version == SAMPLE_GENERATION_PLAN_SCHEMA_VERSION
    assert len(plan.feature_spec_files) >= 2, "the example must use plural Feature inputs"
    assert len(plan.label_spec_files) >= 2, "the example must use plural Label inputs"


def test_contract_version_constants_are_exact():
    assert SAMPLE_GENERATION_CONTRACT_VERSION == "market-vault-sample-generation-contract-v1"
    assert SAMPLE_GENERATION_PLAN_SCHEMA_VERSION == "market-vault-sample-generation-plan-v1"
    assert SAMPLE_GENERATION_RULE_SCHEMA_VERSION == "market-vault-sample-generation-rule-v1"
    assert SAMPLE_GENERATION_CONTENT_ID_VERSION == "market-vault-sample-generation-content-v1"
