"""Offline deterministic tests for the versioned Feature/Label spec contracts.

Covers frozen typed models, strict fail-closed YAML parsing, deterministic
semantic content hashing, conversion to the existing SpecPin, and the
DatasetIdentityInput / dataset_id integration. No network, no OpenD, no
stored market data, no current time, no locale, no filesystem mtimes, and no
dict insertion order is ever depended on.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone

import numpy as np
import pytest

from market_vault.dataset import (
    FEATURE_LABEL_SPEC_CONTENT_ID_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    CanonicalBuildPin,
    CompletionEntry,
    CompletionSummary,
    CrossTradingDayPolicy,
    DatasetError,
    DatasetField,
    DatasetIdentityInput,
    DatasetScope,
    DatasetSchema,
    FeatureSpec,
    GapReference,
    ImplementationPin,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    SourceSnapshotPin,
    SpecParameter,
    SpecPin,
    SpecValidationError,
    SpecVersionRequirements,
    dataset_id,
    dataset_schema_id,
    feature_label_spec_content_id,
    feature_label_spec_pin,
    load_feature_spec,
    load_label_spec,
    logical_dataset_content_id,
    parse_feature_spec,
    parse_label_spec,
)

UTC = timezone.utc
_SHA_HEX = re.compile(r"^[0-9a-f]{64}$")


def sha(text) -> str:
    payload = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Canonical spec fixtures.
# ---------------------------------------------------------------------------

FEATURE_YAML = """\
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: close_return
version: v1
output:
  name: close_return
  logical_type: float64
  nullable: true
inputs:
  canonical_fields:
    - close
    - open
transform:
  ref: market_vault.features.transforms:close_return
parameters:
  lookback: 5
  mode: simple
  use_log: true
  scale: 1.5
  nothing: null
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
"""

# Same semantics as FEATURE_YAML with reordered keys, reordered parameters,
# comments, CRLF, and blank lines. Parsing both must produce the same spec
# and the same content ID. Input field order (close, open) is preserved
# because it is authoritative semantics.
FEATURE_YAML_REORDERED = (
    "# reordered key order, comments, CRLF\n"
    "requirements:\r\n"
    "  source_schema_versions:\r\n"
    "    - \"10.9\"\r\n"
    "  canonical_schema_versions:\r\n"
    "    - market-bars-canonical-schema-v1\r\n"
    "\r\n"
    "parameters:\r\n"
    "  use_log: true\r\n"
    "  nothing: null\r\n"
    "  scale: 1.5\r\n"
    "  mode: simple\r\n"
    "  lookback: 5\r\n"
    "transform:\r\n"
    "  ref: market_vault.features.transforms:close_return\r\n"
    "inputs:\r\n"
    "  canonical_fields:\r\n"
    "    - close\r\n"
    "    - open\r\n"
    "output:\r\n"
    "  nullable: true\r\n"
    "  logical_type: float64\r\n"
    "  name: close_return\r\n"
    "version: v1\r\n"
    "name: close_return\r\n"
    "kind: FEATURE\r\n"
    "spec_schema_version: market-vault-feature-spec-v1\r\n"
)

LABEL_YAML = """\
spec_schema_version: market-vault-label-spec-v1
kind: LABEL
name: next_day_ret
version: v1
output:
  name: next_day_ret
  logical_type: float64
  nullable: true
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.labels.transforms:next_day_ret
parameters:
  multiplier: 1
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
observation_window:
  unit: TRADING_DAYS
  start_offset: 0
  end_offset: 1
horizon:
  unit: TRADING_DAYS
  value: 1
alignment_rule: ALIGN_CLOSE
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: true
  boundary_rule: END_OF_TRADING_DAY
"""

# BARS-horizon label with the default no-cross-trading-day policy.
LABEL_BARS_YAML = LABEL_YAML.replace(
    """observation_window:
  unit: TRADING_DAYS
  start_offset: 0
  end_offset: 1
horizon:
  unit: TRADING_DAYS
  value: 1
alignment_rule: ALIGN_CLOSE
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: true
  boundary_rule: END_OF_TRADING_DAY
""",
    """observation_window:
  unit: BARS
  start_offset: 0
  end_offset: 5
horizon:
  unit: BARS
  value: 5
alignment_rule: ALIGN_CLOSE
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: false
  boundary_rule: null
""",
)


def patch(text: str, old: str, new: str) -> str:
    assert old in text, f"pattern not found: {old!r}"
    return text.replace(old, new)


def feature_yaml(
    spec_schema_version="spec_schema_version: market-vault-feature-spec-v1",
    kind="kind: FEATURE",
    name="name: close_return",
    version="version: v1",
    logical_type="  logical_type: float64",
    nullable="  nullable: true",
    ref="  ref: market_vault.features.transforms:close_return",
    **extra,
) -> str:
    """Full-line YAML variant builder; extra kwargs are {old_line: new_line}."""
    text = FEATURE_YAML
    for old, new in [
        ("spec_schema_version: market-vault-feature-spec-v1", spec_schema_version),
        ("kind: FEATURE", kind),
        ("name: close_return", name),
        ("version: v1", version),
        ("  logical_type: float64", logical_type),
        ("  nullable: true", nullable),
        ("  ref: market_vault.features.transforms:close_return", ref),
    ] + list(extra.items()):
        text = patch(text, old, new)
    return text


def label_yaml(
    spec_schema_version="spec_schema_version: market-vault-label-spec-v1",
    kind="kind: LABEL",
    name="name: next_day_ret",
    version="version: v1",
    ref="  ref: market_vault.labels.transforms:next_day_ret",
    alignment_rule="alignment_rule: ALIGN_CLOSE",
    missing_data_policy="missing_data_policy: INCOMPLETE",
    **extra,
) -> str:
    text = LABEL_YAML
    for old, new in [
        ("spec_schema_version: market-vault-label-spec-v1", spec_schema_version),
        ("kind: LABEL", kind),
        ("name: next_day_ret", name),
        ("version: v1", version),
        ("  ref: market_vault.labels.transforms:next_day_ret", ref),
        ("alignment_rule: ALIGN_CLOSE", alignment_rule),
        ("missing_data_policy: INCOMPLETE", missing_data_policy),
    ] + list(extra.items()):
        text = patch(text, old, new)
    return text


def _remove_field(text: str, field: str) -> str:
    """Remove a top-level field block (indentation-aware)."""
    lines = text.splitlines(keepends=True)
    out, skipping = [], False
    for line in lines:
        if not skipping and line.startswith(f"{field}:"):
            skipping = True
            continue
        if skipping:
            if line and not line[0].isspace():
                skipping = False
            else:
                continue
        out.append(line)
    return "".join(out)


def parsed_feature() -> FeatureSpec:
    return parse_feature_spec(FEATURE_YAML)


def parsed_label() -> LabelSpec:
    return parse_label_spec(LABEL_YAML)


def mutate_feature(spec: FeatureSpec, **changes) -> FeatureSpec:
    """Model-level mutation that keeps output.name consistent with name."""
    data = dict(
        spec_schema_version=spec.spec_schema_version,
        name=spec.name,
        version=spec.version,
        output=spec.output,
        input_canonical_fields=spec.input_canonical_fields,
        transform_ref=spec.transform_ref,
        parameters=spec.parameters,
        requirements=spec.requirements,
    )
    data.update(changes)
    if "name" in changes and "output" not in changes:
        data["output"] = DatasetField(changes["name"], spec.output.logical_type, False)
    return FeatureSpec(**data)


def mutate_label(spec: LabelSpec, **changes) -> LabelSpec:
    data = dict(
        spec_schema_version=spec.spec_schema_version,
        name=spec.name,
        version=spec.version,
        output=spec.output,
        input_canonical_fields=spec.input_canonical_fields,
        transform_ref=spec.transform_ref,
        parameters=spec.parameters,
        requirements=spec.requirements,
        observation_window=spec.observation_window,
        horizon=spec.horizon,
        alignment_rule=spec.alignment_rule,
        missing_data_policy=spec.missing_data_policy,
        cross_trading_day=spec.cross_trading_day,
    )
    data.update(changes)
    if "name" in changes and "output" not in changes:
        data["output"] = DatasetField(changes["name"], spec.output.logical_type, False)
    return LabelSpec(**data)


def set_parameter(spec, name: str, value) -> tuple[SpecParameter, ...]:
    return tuple(
        SpecParameter(p.name, value) if p.name == name else p for p in spec.parameters
    )


# ---------------------------------------------------------------------------
# Valid parsing.
# ---------------------------------------------------------------------------


def test_parse_valid_feature_spec():
    spec = parsed_feature()
    assert isinstance(spec, FeatureSpec)
    assert spec.kind == "FEATURE"
    assert spec.spec_schema_version == FEATURE_SPEC_SCHEMA_VERSION
    assert spec.name == "close_return"
    assert spec.version == "v1"
    assert spec.output == DatasetField("close_return", "float64", True)
    assert spec.input_canonical_fields == ("close", "open")
    assert spec.transform_ref == "market_vault.features.transforms:close_return"
    # Parameters sort deterministically by name, whatever the YAML order.
    assert tuple(p.name for p in spec.parameters) == (
        "lookback", "mode", "nothing", "scale", "use_log",
    )
    assert dict((p.name, p.value) for p in spec.parameters) == {
        "lookback": 5, "mode": "simple", "nothing": None, "scale": 1.5,
        "use_log": True,
    }
    # Requirements sort deterministically; input order is preserved.
    assert spec.requirements.canonical_schema_versions == ("market-bars-canonical-schema-v1",)
    assert spec.requirements.source_schema_versions == ("10.9",)


def test_parse_valid_label_spec():
    spec = parsed_label()
    assert isinstance(spec, LabelSpec)
    assert spec.kind == "LABEL"
    assert spec.spec_schema_version == LABEL_SPEC_SCHEMA_VERSION
    assert spec.observation_window == LabelObservationWindow("TRADING_DAYS", 0, 1)
    assert spec.horizon == LabelHorizon("TRADING_DAYS", 1)
    assert spec.alignment_rule == "ALIGN_CLOSE"
    assert spec.missing_data_policy == "INCOMPLETE"
    assert spec.cross_trading_day == CrossTradingDayPolicy(True, "END_OF_TRADING_DAY")


def test_models_are_frozen_and_deeply_immutable():
    spec = parsed_feature()
    label = parsed_label()
    for model in (
        spec,
        label,
        label.horizon,
        label.observation_window,
        label.cross_trading_day,
        spec.requirements,
        spec.parameters[0],
        spec.output,
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(model, "x", 1)
    # Nested values are tuples, never mutable lists or dicts.
    assert isinstance(spec.input_canonical_fields, tuple)
    assert isinstance(spec.parameters, tuple)
    assert isinstance(spec.requirements.canonical_schema_versions, tuple)
    assert isinstance(label.cross_trading_day.boundary_rule, str)
    # replace() builds new instances without mutating the original.
    original_id = feature_label_spec_content_id(spec)
    variant = replace(spec, version="v2")
    assert variant.version == "v2"
    assert spec.version == "v1"
    assert feature_label_spec_content_id(spec) == original_id


def test_kind_is_fixed_and_not_forgeable():
    spec = parsed_feature()
    label = parsed_label()
    assert spec.kind == "FEATURE"
    assert label.kind == "LABEL"
    # kind is not a constructor parameter.
    with pytest.raises(TypeError):
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="x", version="v1",
            output=DatasetField("x", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(),
            requirements=SpecVersionRequirements(("a",), ("b",)),
            kind="LABEL",
        )
    # dataclasses.replace cannot change an init=False field either.
    with pytest.raises((TypeError, ValueError)):
        replace(spec, kind="LABEL")


def test_schema_version_gate_fails_closed():
    for version in ("market-vault-feature-spec-v2", "market-vault-feature-spec-v0",
                    "future-v3", "v1"):
        with pytest.raises(SpecValidationError):
            parse_feature_spec(feature_yaml(spec_schema_version=f"spec_schema_version: {version}"))
    for version in ("market-vault-label-spec-v2", "market-vault-label-spec-v1.1", "v0"):
        with pytest.raises(SpecValidationError):
            parse_label_spec(label_yaml(spec_schema_version=f"spec_schema_version: {version}"))
    # Direct construction gates too.
    with pytest.raises(SpecValidationError):
        FeatureSpec(
            spec_schema_version="market-vault-feature-spec-v2",
            name="x", version="v1",
            output=DatasetField("x", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(),
            requirements=SpecVersionRequirements(("a",), ("b",)),
        )
    with pytest.raises(SpecValidationError):
        LabelSpec(
            spec_schema_version="market-vault-label-spec-v0",
            name="x", version="v1",
            output=DatasetField("x", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(),
            requirements=SpecVersionRequirements(("a",), ("b",)),
            observation_window=LabelObservationWindow("BARS", 0, 1),
            horizon=LabelHorizon("BARS", 1),
            alignment_rule="ALIGN_CLOSE",
            missing_data_policy="INCOMPLETE",
            cross_trading_day=CrossTradingDayPolicy(False, None),
        )


def test_kind_mismatch_fails():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml(kind="kind: LABEL"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml(kind="kind: SPLIT"))
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml(kind="kind: FEATURE"))
    with pytest.raises(SpecValidationError):
        parse_label_spec(_remove_field(LABEL_YAML, "kind"))


def test_root_not_mapping_fails():
    for text in ("", "   ", "---\n- 1\n- 2\n", "close_return", "null", "--- 5\n"):
        with pytest.raises(SpecValidationError):
            parse_feature_spec(text)
    with pytest.raises(SpecValidationError):
        parse_label_spec("[1, 2]")


def test_parse_rejects_non_string_text():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(FEATURE_YAML.encode("utf-8"))
    with pytest.raises(SpecValidationError):
        parse_label_spec(123)


def test_unknown_top_level_fields_fail():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml() + "extra_field: 1\n")
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml() + "extra_field: 1\n")


def test_missing_top_level_fields_fail():
    for field in ("spec_schema_version", "kind", "name", "version", "output", "inputs",
                  "transform", "parameters", "requirements"):
        with pytest.raises(SpecValidationError):
            parse_feature_spec(_remove_field(FEATURE_YAML, field))
    for field in ("observation_window", "horizon", "alignment_rule",
                  "missing_data_policy", "cross_trading_day"):
        with pytest.raises(SpecValidationError):
            parse_label_spec(_remove_field(LABEL_YAML, field))


def test_unknown_nested_fields_fail():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("logical_type: float64", "logical_type: float64\n  extra: 1"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("canonical_fields:", "extra_field:\n    - z\n  canonical_fields:"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("ref: market_vault", "ref: market_vault\n  extra: 1"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("canonical_schema_versions:", "extra: 1\n  canonical_schema_versions:"))
    for block in ("observation_window", "horizon", "cross_trading_day"):
        with pytest.raises(SpecValidationError):
            parse_label_spec(patch(label_yaml(), f"{block}:", f"{block}:\n  extra_field: 1\n"))


def test_missing_nested_fields_fail():
    # output missing name
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  name: close_return\n", ""))
    # inputs missing canonical_fields
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  canonical_fields:\n    - close\n    - open\n", ""))
    # transform missing ref
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  ref: market_vault.features.transforms:close_return\n", ""))
    # requirements missing source_schema_versions
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  source_schema_versions:\n    - \"10.9\"\n", ""))
    # label nested fields
    with pytest.raises(SpecValidationError):
        parse_label_spec(_remove_field(LABEL_YAML, "observation_window"))
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace("  value: 1\n", ""))
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace("  allow: true\n", ""))
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace("  boundary_rule: END_OF_TRADING_DAY\n", ""))


def test_duplicate_yaml_keys_fail():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml() + "name: close_ret\n")
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml() + "horizon:\n  value: 2\n")


def test_nested_duplicate_yaml_keys_fail():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace(
            "  name: close_return\n", "  name: close_return\n  name: close_ret\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace(
            "  lookback: 5\n", "  lookback: 5\n  lookback: 6\n"))
    # Flow-style duplicates are caught too.
    with pytest.raises(SpecValidationError):
        parse_feature_spec(
            "spec_schema_version: market-vault-feature-spec-v1\n"
            "kind: FEATURE\n"
            "name: x\n"
            "version: v1\n"
            "output: {name: x, logical_type: float64, nullable: false}\n"
            "inputs: {canonical_fields: [close]}\n"
            "transform: {ref: m:f}\n"
            "parameters: {a: 1, a: 2}\n"
            "requirements: {canonical_schema_versions: [c1], source_schema_versions: [s1]}\n"
        )


def test_duplicate_list_entries_fail():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("    - close\n", "    - close\n    - close\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace(
            "    - market-bars-canonical-schema-v1\n",
            "    - market-bars-canonical-schema-v1\n    - market-bars-canonical-schema-v1\n"))
    with pytest.raises(SpecValidationError):
        SpecVersionRequirements(("a", "a"), ("b",))


def test_anchors_rejected():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  lookback: 5\n", "  lookback: &five 5\n"))
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace("alignment_rule: ALIGN_CLOSE", "alignment_rule: &a ALIGN_CLOSE"))


def test_aliases_rejected():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml() + "other: *five\n")
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace("  allow: true\n", "  allow: *five\n"))


def test_merge_keys_rejected():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(
            "spec_schema_version: market-vault-feature-spec-v1\n"
            "kind: FEATURE\n"
            "name: x\n"
            "version: v1\n"
            "output: {name: x, logical_type: float64, nullable: false}\n"
            "inputs: {canonical_fields: [close]}\n"
            "transform: {ref: m:f}\n"
            "parameters:\n"
            "  <<: {a: 1}\n"
            "  b: 2\n"
            "requirements: {canonical_schema_versions: [c1], source_schema_versions: [s1]}\n"
        )


def test_custom_tags_rejected():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  lookback: 5\n", "  lookback: !custom 5\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  nothing: null\n", "  nothing: !!python/object/apply:os.system [echo]\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  nothing: null\n", "  nothing: !!binary aGVsbG8=\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  mode: simple\n", "  mode: !<tag:example.com,2026:custom> simple\n"))


def test_timestamp_scalars_rejected():
    # YAML 1.1 timestamps are not part of the v1 scalar set.
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  nothing: null\n", "  date_value: 2026-01-01\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  nothing: null\n", "  ts: 2026-01-01T12:00:00Z\n"))


def test_multi_document_rejected():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(FEATURE_YAML + "---\nkind: FEATURE\n")
    with pytest.raises(SpecValidationError):
        parse_label_spec(LABEL_YAML + "\n---\n")


def test_bom_rejected():
    with pytest.raises(SpecValidationError):
        parse_feature_spec("﻿" + FEATURE_YAML)
    with pytest.raises(SpecValidationError):
        parse_label_spec("﻿" + LABEL_YAML)


def test_load_rejects_bom_and_invalid_utf8(tmp_path):
    bom_file = tmp_path / "bom.spec.yaml"
    bom_file.write_text(FEATURE_YAML, encoding="utf-8-sig")
    with pytest.raises(SpecValidationError):
        load_feature_spec(bom_file)

    bad_file = tmp_path / "bad.spec.yaml"
    bad_file.write_bytes(b"\xff\xfe\x00\x41\x42\x43")
    with pytest.raises(SpecValidationError):
        load_label_spec(bad_file)


def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(SpecValidationError):
        load_feature_spec(tmp_path / "does-not-exist.spec.yaml")


def test_load_round_trip(tmp_path):
    feature_file = tmp_path / "close_return_v1.spec.yaml"
    feature_file.write_text(FEATURE_YAML, encoding="utf-8")
    assert load_feature_spec(feature_file) == parsed_feature()
    label_file = tmp_path / "next_day_ret_v1.spec.yaml"
    label_file.write_text(LABEL_YAML, encoding="utf-8")
    assert load_label_spec(label_file) == parsed_label()


def test_unsafe_text_rejected():
    cases = [
        ("  lookback: 5\n", "  lookback: 5\n"),  # control char in parameter name
        ("name: close_return\n", "name: close\x1freturn\n"),  # separator in spec name
        ("  mode: simple\n", "  mode: bad\x1evalue\n"),  # separator in string value
        ("    - close\n", "    - cl\x1fose\n"),  # separator in input field
        ("  ref: market_vault.features.transforms:close_return\n",
         "  ref: market_vault.\x1ffeatures.transforms:close_return\n"),  # separator in ref
    ]
    for old, new in cases:
        with pytest.raises(SpecValidationError):
            parse_feature_spec(patch(feature_yaml(), old, new))
    with pytest.raises(SpecValidationError):
        SpecParameter("ok", "bad\x1fvalue")


def test_name_format():
    # "close_return_" is valid: the contract regex is ^[a-z][a-z0-9_]*$ and
    # allows trailing underscores.
    for bad in ("CloseReturn", "1close", "close return", "_close",
                "close-return", "café", ""):
        with pytest.raises(SpecValidationError):
            parse_feature_spec(feature_yaml(name=f"name: {bad}"))
    for good in ("close_return", "rsi_14", "x", "close_return_"):
        spec = parse_feature_spec(feature_yaml(name=f"name: {good}"))
        assert spec.name == good


def test_version_format():
    # Note: "v1 " cannot be represented in YAML (plain scalars strip
    # trailing whitespace at parse time), so the model-level rejection is
    # pinned via direct construction below.
    for bad in ("v0", "v01", "1", "V1", "v1.0", "v-1", "vv1", ""):
        with pytest.raises(SpecValidationError):
            parse_feature_spec(feature_yaml(version=f"version: {bad}"))
    with pytest.raises(SpecValidationError):
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="x", version="v1 ",
            output=DatasetField("x", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(),
            requirements=SpecVersionRequirements(("c",), ("s",)),
        )
    for good in ("v1", "v2", "v42"):
        spec = parse_feature_spec(feature_yaml(version=f"version: {good}"))
        assert spec.version == good


def test_transform_ref_format():
    for bad in ("module", "module:", ":func", "module.func", "module::func", "1a:b",
                "a:b:c", "a.b:c.d", "a.b:", "a .b:c", "a.b:c d"):
        with pytest.raises(SpecValidationError):
            parse_feature_spec(feature_yaml(ref=f"  ref: {bad}"))
    for good in ("m:f", "a.b.c:d", "my_module_1.inner2:function_name"):
        spec = parse_feature_spec(feature_yaml(ref=f"  ref: {good}"))
        assert spec.transform_ref == good


def test_output_logical_type_and_nullable():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml(logical_type="  logical_type: object"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml(nullable="  nullable: \"true\""))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml(nullable="  nullable: 1"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml(nullable="  nullable: null"))
    spec = parse_feature_spec(feature_yaml(logical_type="  logical_type: bool", nullable="  nullable: false"))
    assert spec.output == DatasetField("close_return", "bool", False)


def test_output_name_must_match_spec_name():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  name: close_return\n", "  name: close_ret\n"))
    with pytest.raises(SpecValidationError):
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="a", version="v1",
            output=DatasetField("b", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(),
            requirements=SpecVersionRequirements(("c",), ("s",)),
        )


def test_input_fields_required_nonempty_unique():
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("    - close\n    - open\n", ""))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("    - open\n", "    - close\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("    - close\n", "    - \" close\"\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("    - close\n", "    - 5\n"))
    with pytest.raises(SpecValidationError):
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="a", version="v1",
            output=DatasetField("a", "float64", False),
            input_canonical_fields=(),  # empty fails
            transform_ref="m:f",
            parameters=(),
            requirements=SpecVersionRequirements(("c",), ("s",)),
        )
    with pytest.raises(SpecValidationError):
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="a", version="v1",
            output=DatasetField("a", "float64", False),
            input_canonical_fields="ab",  # a bare string must not split into chars
            transform_ref="m:f",
            parameters=(),
            requirements=SpecVersionRequirements(("c",), ("s",)),
        )


def test_input_field_order_is_preserved_and_semantic():
    spec = parsed_feature()
    assert spec.input_canonical_fields == ("close", "open")
    swapped = mutate_feature(spec, input_canonical_fields=("open", "close"))
    assert swapped.input_canonical_fields == ("open", "close")
    assert feature_label_spec_content_id(swapped) != feature_label_spec_content_id(spec)


def test_parameters_sorted_and_typed():
    spec = parsed_feature()
    assert tuple(p.name for p in spec.parameters) == (
        "lookback", "mode", "nothing", "scale", "use_log",
    )
    # Direct construction with unsorted parameters sorts deterministically.
    direct = FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="x", version="v1",
        output=DatasetField("x", "float64", False),
        input_canonical_fields=("close",),
        transform_ref="m:f",
        parameters=(SpecParameter("z", 1), SpecParameter("a", 2), SpecParameter("m", 3)),
        requirements=SpecVersionRequirements(("c",), ("s",)),
    )
    assert tuple(p.name for p in direct.parameters) == ("a", "m", "z")
    # Duplicate parameter names fail even when not adjacent.
    with pytest.raises(SpecValidationError):
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="x", version="v1",
            output=DatasetField("x", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(SpecParameter("a", 1), SpecParameter("b", 2), SpecParameter("a", 3)),
            requirements=SpecVersionRequirements(("c",), ("s",)),
        )


def test_parameter_value_types_fail_closed():
    for value in ([1, 2], ("a", "b"), {"k": 1}, b"bytes", object()):
        with pytest.raises(SpecValidationError):
            SpecParameter("p", value)
    # YAML lists and nested mappings inside parameters fail.
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  nothing: null\n", "  nested: [1, 2]\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  nothing: null\n", "  nested: {k: 1}\n"))
    # numpy integers and floats normalize to int/float.
    assert SpecParameter("p", np.int64(7)).value == 7
    assert type(SpecParameter("p", np.int64(7)).value) is int
    assert SpecParameter("p", np.float64(1.25)).value == 1.25
    assert type(SpecParameter("p", np.float64(1.25)).value) is float
    with pytest.raises(SpecValidationError):
        SpecParameter("p", np.bool_(True))


def test_bool_is_never_int():
    assert SpecParameter("p", True).value is True
    assert SpecParameter("p", 1).value == 1
    assert feature_label_spec_content_id(
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="x", version="v1",
            output=DatasetField("x", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(SpecParameter("p", True),),
            requirements=SpecVersionRequirements(("c",), ("s",)),
        )
    ) != feature_label_spec_content_id(
        FeatureSpec(
            spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
            name="x", version="v1",
            output=DatasetField("x", "float64", False),
            input_canonical_fields=("close",),
            transform_ref="m:f",
            parameters=(SpecParameter("p", 1),),
            requirements=SpecVersionRequirements(("c",), ("s",)),
        )
    )
    # bool is rejected where a real integer is required.
    with pytest.raises(SpecValidationError):
        LabelHorizon("BARS", True)
    with pytest.raises(SpecValidationError):
        LabelObservationWindow("BARS", False, 5)
    with pytest.raises(SpecValidationError):
        CrossTradingDayPolicy(1, None)


def test_int64_bounds():
    SpecParameter("p", 2**63 - 1)
    SpecParameter("p", -(2**63))
    for value in (2**63, -(2**63) - 1):
        with pytest.raises(SpecValidationError):
            SpecParameter("p", value)
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  lookback: 5\n", "  lookback: 9223372036854775808\n"))
    spec = parse_feature_spec(feature_yaml().replace("  lookback: 5\n", "  lookback: 9223372036854775807\n"))
    assert dict((p.name, p.value) for p in spec.parameters)["lookback"] == 2**63 - 1


def test_nan_and_infinity_rejected():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(SpecValidationError):
            SpecParameter("p", value)
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  scale: 1.5\n", "  scale: .nan\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  scale: 1.5\n", "  scale: .inf\n"))
    with pytest.raises(SpecValidationError):
        parse_feature_spec(feature_yaml().replace("  scale: 1.5\n", "  scale: -.inf\n"))


def test_negative_zero_normalizes():
    assert SpecParameter("p", -0.0).value == 0.0
    base = feature_label_spec_content_id(parsed_feature())
    zero = parse_feature_spec(patch(feature_yaml(), "  scale: 1.5\n", "  scale: 0.0\n"))
    neg_zero = parse_feature_spec(patch(feature_yaml(), "  scale: 1.5\n", "  scale: -0.0\n"))
    assert dict((p.name, p.value) for p in zero.parameters)["scale"] == 0.0
    assert dict((p.name, p.value) for p in neg_zero.parameters)["scale"] == 0.0
    assert feature_label_spec_content_id(zero) == feature_label_spec_content_id(neg_zero)
    assert feature_label_spec_content_id(zero) != base


def test_requirements_normalization():
    direct = SpecVersionRequirements(("b", "a", "c"), ("s2", "s1"))
    assert direct.canonical_schema_versions == ("a", "b", "c")
    assert direct.source_schema_versions == ("s1", "s2")
    for bad in ((), (""), ("a ",), (1,), ("a", "a")):
        with pytest.raises(SpecValidationError):
            SpecVersionRequirements(bad, ("s",))
    with pytest.raises(SpecValidationError):
        SpecVersionRequirements("market-v1", ("s",))  # bare string must not split
    with pytest.raises(SpecValidationError):
        SpecVersionRequirements(("c",), ())
    # NFC-equivalent version entries are the same entry.
    decomposed = "café"
    assert SpecVersionRequirements((decomposed,), ("s",)).canonical_schema_versions == ("café",)


def test_label_window_range():
    LabelObservationWindow("BARS", 0, 0)
    LabelObservationWindow("BARS", 5, 5)
    with pytest.raises(SpecValidationError):
        LabelObservationWindow("BARS", 2, 1)
    with pytest.raises(SpecValidationError):
        LabelObservationWindow("BARS", -1, 0)
    with pytest.raises(SpecValidationError):
        LabelObservationWindow("BARS", 0, -1)
    with pytest.raises(SpecValidationError):
        LabelObservationWindow("BARS", True, 5)
    with pytest.raises(SpecValidationError):
        LabelObservationWindow("BARS", 0.5, 1)


def test_horizon_positive_integer_and_unit():
    for value in (0, -1, True, 1.5, "1"):
        with pytest.raises(SpecValidationError):
            LabelHorizon("BARS", value)
    assert LabelHorizon("BARS", 1).value == 1
    assert LabelHorizon("TRADING_DAYS", 10).value == 10
    for unit in ("bars", "DAYS", "TRADING", "Bars", "SESSIONS", "", 1):
        with pytest.raises(SpecValidationError):
            LabelHorizon(unit, 1)
    with pytest.raises(SpecValidationError):
        LabelObservationWindow("MINUTESx", 0, 1)


def test_window_horizon_unit_consistency():
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace(
            "  unit: TRADING_DAYS\n  start_offset: 0\n", "  unit: BARS\n  start_offset: 0\n"))
    with pytest.raises(SpecValidationError):
        mutate_label(parsed_label(), observation_window=LabelObservationWindow("BARS", 0, 1))


def test_missing_data_policy_only_incomplete():
    for policy in ("NONE", "FILL_FORWARD", "FORWARD_FILL", "ZERO_FILL", "INTERPOLATE",
                   "incomplete", "INCOMPLETE_NOTE", ""):
        with pytest.raises(SpecValidationError):
            parse_label_spec(label_yaml(missing_data_policy=f"missing_data_policy: {policy}"))
    assert parsed_label().missing_data_policy == "INCOMPLETE"


def test_cross_day_allow_boundary_combinations():
    # allow false requires null boundary_rule.
    with pytest.raises(SpecValidationError):
        CrossTradingDayPolicy(False, "END_OF_TRADING_DAY")
    CrossTradingDayPolicy(False, None)
    # allow true requires a non-empty safe boundary rule.
    for rule in (None, "", " ", 1):
        with pytest.raises(SpecValidationError):
            CrossTradingDayPolicy(True, rule)
    CrossTradingDayPolicy(True, "END_OF_TRADING_DAY")
    # YAML-level: allow must be a real bool.
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace("  allow: true\n", "  allow: \"true\"\n"))
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace("  allow: true\n", "  allow: 1\n"))
    # allow false with a boundary rule fails in YAML too.
    with pytest.raises(SpecValidationError):
        parse_label_spec(label_yaml().replace(
            "  allow: true\n  boundary_rule: END_OF_TRADING_DAY\n",
            "  allow: false\n  boundary_rule: END_OF_TRADING_DAY\n"))


def test_trading_days_requires_explicit_opt_in():
    # Default no-cross-trading-day policy is valid for BARS.
    bars = parse_label_spec(LABEL_BARS_YAML)
    assert bars.cross_trading_day == CrossTradingDayPolicy(False, None)
    # A TRADING_DAYS horizon without the opt-in fails closed.
    with pytest.raises(SpecValidationError):
        parse_label_spec(LABEL_BARS_YAML.replace(
            "  unit: BARS\n  start_offset: 0\n  end_offset: 5\nhorizon:\n  unit: BARS\n  value: 5\n",
            "  unit: TRADING_DAYS\n  start_offset: 0\n  end_offset: 1\nhorizon:\n  unit: TRADING_DAYS\n  value: 1\n"))


def test_key_order_comments_newlines_do_not_affect_hash():
    reordered = parse_feature_spec(FEATURE_YAML_REORDERED)
    assert reordered == parsed_feature()
    assert feature_label_spec_content_id(reordered) == feature_label_spec_content_id(parsed_feature())
    # The raw YAML bytes differ; the semantic content does not.
    assert sha(FEATURE_YAML.encode("utf-8")) != sha(FEATURE_YAML_REORDERED.encode("utf-8"))
    # Adding comments and blank lines changes nothing.
    commented = "# header\n" + FEATURE_YAML + "\n# trailer\n\n"
    assert feature_label_spec_content_id(parse_feature_spec(commented)) == feature_label_spec_content_id(parsed_feature())


def test_nfc_equivalent_text_hashes_identically():
    composed = "café"
    decomposed = "café"
    a = FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="x", version="v1",
        output=DatasetField("x", "float64", False),
        input_canonical_fields=("close",),
        transform_ref="m:f",
        parameters=(SpecParameter(composed, "v"),),
        requirements=SpecVersionRequirements(("c",), ("s",)),
    )
    b = FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="x", version="v1",
        output=DatasetField("x", "float64", False),
        input_canonical_fields=("close",),
        transform_ref="m:f",
        parameters=(SpecParameter(decomposed, "v"),),
        requirements=SpecVersionRequirements(("c",), ("s",)),
    )
    assert a.parameters[0].name == b.parameters[0].name
    assert feature_label_spec_content_id(a) == feature_label_spec_content_id(b)


def test_path_never_enters_identity(tmp_path):
    first = tmp_path / "one.spec.yaml"
    second = tmp_path / "nested" / "two.spec.yaml"
    second.parent.mkdir()
    first.write_text(FEATURE_YAML, encoding="utf-8")
    second.write_text(FEATURE_YAML, encoding="utf-8")
    id_one = feature_label_spec_content_id(load_feature_spec(first))
    id_two = feature_label_spec_content_id(load_feature_spec(second))
    assert id_one == id_two
    assert feature_label_spec_content_id(load_feature_spec(first)) == feature_label_spec_content_id(parsed_feature())


def test_every_semantic_change_changes_hash():
    base = parsed_feature()
    base_id = feature_label_spec_content_id(base)
    mutations = [
        ("name", lambda s: mutate_feature(s, name="close_ret")),
        ("version", lambda s: mutate_feature(s, version="v2")),
        ("output logical type", lambda s: mutate_feature(s, output=DatasetField("close_return", "string", False))),
        ("output nullability", lambda s: mutate_feature(s, output=DatasetField("close_return", "float64", False))),
        ("input content", lambda s: mutate_feature(s, input_canonical_fields=("high", "open"))),
        ("input order", lambda s: mutate_feature(s, input_canonical_fields=("open", "close"))),
        ("input count", lambda s: mutate_feature(s, input_canonical_fields=("close", "open", "volume"))),
        ("transform ref", lambda s: mutate_feature(s, transform_ref="market_vault.features.transforms:close_delta")),
        ("parameter name", lambda s: mutate_feature(
            s, parameters=tuple(SpecParameter("window", 5) if p.name == "lookback" else p for p in s.parameters))),
        ("parameter value", lambda s: mutate_feature(s, parameters=set_parameter(s, "lookback", 6))),
        ("parameter bool value", lambda s: mutate_feature(s, parameters=set_parameter(s, "use_log", False))),
        ("parameter float value", lambda s: mutate_feature(s, parameters=set_parameter(s, "scale", 2.5))),
        ("parameter null value", lambda s: mutate_feature(s, parameters=set_parameter(s, "nothing", "x"))),
        ("parameter removed", lambda s: mutate_feature(
            s, parameters=tuple(p for p in s.parameters if p.name != "nothing"))),
        ("parameter added", lambda s: mutate_feature(s, parameters=s.parameters + (SpecParameter("extra", 1),))),
        ("canonical requirement", lambda s: mutate_feature(
            s, requirements=SpecVersionRequirements(("market-bars-canonical-schema-v2",), s.requirements.source_schema_versions))),
        ("source requirement", lambda s: mutate_feature(
            s, requirements=SpecVersionRequirements(s.requirements.canonical_schema_versions, ("10.8",)))),
    ]
    for label, mutator in mutations:
        assert feature_label_spec_content_id(mutator(base)) != base_id, label

    label_base = parsed_label()
    label_id = feature_label_spec_content_id(label_base)
    label_mutations = [
        ("label name", lambda s: mutate_label(s, name="next_day_return")),
        ("label version", lambda s: mutate_label(s, version="v2")),
        ("label output type", lambda s: mutate_label(s, output=DatasetField("next_day_ret", "string", False))),
        ("label input", lambda s: mutate_label(s, input_canonical_fields=("open",))),
        ("label input order", lambda s: mutate_label(s, input_canonical_fields=("close", "open"))),
        ("label transform", lambda s: mutate_label(s, transform_ref="market_vault.labels.transforms:other")),
        ("label parameter", lambda s: mutate_label(s, parameters=set_parameter(s, "multiplier", 2))),
        ("label requirement", lambda s: mutate_label(
            s, requirements=SpecVersionRequirements(("market-bars-canonical-schema-v2",), s.requirements.source_schema_versions))),
        ("window start", lambda s: mutate_label(
            s, observation_window=LabelObservationWindow("TRADING_DAYS", 1, 1))),
        ("window end", lambda s: mutate_label(
            s, observation_window=LabelObservationWindow("TRADING_DAYS", 0, 2))),
        ("horizon value", lambda s: mutate_label(s, horizon=LabelHorizon("TRADING_DAYS", 2))),
        ("alignment rule", lambda s: mutate_label(s, alignment_rule="ALIGN_OPEN")),
    ]
    for label, mutator in label_mutations:
        assert feature_label_spec_content_id(mutator(label_base)) != label_id, label

    # Cross-trading-day policy is identity-bearing (BARS label: allow+rule).
    bars = parse_label_spec(LABEL_BARS_YAML)
    bars_opted = mutate_label(
        bars, cross_trading_day=CrossTradingDayPolicy(True, "END_OF_SESSION"),
    )
    assert feature_label_spec_content_id(bars_opted) != feature_label_spec_content_id(bars)

    # v1 validation only permits missing_data_policy INCOMPLETE, so no other
    # policy can be constructed; prove the field is identity-bearing by
    # bypassing validation at the identity-test level only.
    forged = replace(label_base, missing_data_policy="INCOMPLETE")
    assert feature_label_spec_content_id(forged) == label_id
    object.__setattr__(label_base, "missing_data_policy", "FILL_FORWARD")
    assert feature_label_spec_content_id(label_base) != label_id


def test_feature_label_same_name_version_different_kind_different_hash():
    feature = FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="same_name", version="v1",
        output=DatasetField("same_name", "float64", False),
        input_canonical_fields=("close",),
        transform_ref="m:f",
        parameters=(),
        requirements=SpecVersionRequirements(("c",), ("s",)),
    )
    label = LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name="same_name", version="v1",
        output=DatasetField("same_name", "float64", False),
        input_canonical_fields=("close",),
        transform_ref="m:f",
        parameters=(),
        requirements=SpecVersionRequirements(("c",), ("s",)),
        observation_window=LabelObservationWindow("BARS", 0, 1),
        horizon=LabelHorizon("BARS", 1),
        alignment_rule="ALIGN_CLOSE",
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )
    assert (feature.name, feature.version) == (label.name, label.version)
    assert feature.kind != label.kind
    assert feature_label_spec_content_id(feature) != feature_label_spec_content_id(label)


def test_content_id_is_versioned_sha256():
    spec_id = feature_label_spec_content_id(parsed_feature())
    assert len(spec_id) == 64
    assert _SHA_HEX.fullmatch(spec_id)
    # Semantic hash differs from the raw YAML byte hash.
    assert spec_id != sha(FEATURE_YAML.encode("utf-8"))


def test_spec_pin_conversion():
    feature = parsed_feature()
    pin = feature_label_spec_pin(feature)
    assert isinstance(pin, SpecPin)
    assert pin.kind == "FEATURE"
    assert pin.name == feature.name
    assert pin.version == feature.version
    assert pin.content_sha256 == feature_label_spec_content_id(feature)
    label_pin = feature_label_spec_pin(parsed_label())
    assert label_pin.kind == "LABEL"
    with pytest.raises(SpecValidationError):
        feature_label_spec_pin("not a spec")


def test_pin_never_fabricates_implementation_pin():
    feature_pin = feature_label_spec_pin(parsed_feature())
    label_pin = feature_label_spec_pin(parsed_label())
    assert not isinstance(feature_pin, ImplementationPin)
    assert not isinstance(label_pin, ImplementationPin)
    assert feature_pin.kind == "FEATURE"
    assert label_pin.kind == "LABEL"


# ---------------------------------------------------------------------------
# DatasetIdentityInput / dataset_id integration.
# ---------------------------------------------------------------------------


def identity_input(feature_specs=(), label_specs=(), implementations=()):
    schema = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("close", "float64", True))
    )
    scope = DatasetScope(
        ["US.MU"], [date(2026, 7, 1)], adjustment="NONE", interval="1m",
        requested_session="ALL",
    )
    build = CanonicalBuildPin(
        canonical_build_id=sha("build"),
        canonical_content_id=sha("content"),
        canonical_builder_version="market-bars-canonical-builder-v1",
        canonical_schema_version="market-bars-canonical-schema-v1",
        materializer_version="market-bars-materializer-v1",
        gap_policy_version="market-bars-gap-policy-v1",
        gap_content_id=sha("gap"),
        status="COMPLETE",
        canonical_row_version_ids=(sha("row-1"), sha("row-2")),
        source_snapshots=(
            SourceSnapshotPin("run-1", sha("phys"), sha("logical"), "10.9",
                              date(2026, 7, 1), "ALL"),
        ),
    )
    rows = [
        {"ts": datetime(2026, 7, 1, 13, 30, tzinfo=UTC), "close": 100.5},
        {"ts": datetime(2026, 7, 1, 13, 31, tzinfo=UTC), "close": 101.25},
    ]
    return DatasetIdentityInput(
        dataset_kind="market_bars_dataset",
        scope=scope,
        dataset_as_of=None,
        schema=schema,
        dataset_schema_id=dataset_schema_id(schema),
        logical_dataset_content_id=logical_dataset_content_id(schema, rows),
        canonical_builds=(build,),
        canonical_row_version_ids=build.canonical_row_version_ids,
        feature_specs=tuple(feature_specs),
        label_specs=tuple(label_specs),
        split_spec=None,
        implementations=tuple(implementations),
        completion=CompletionSummary(
            1, 0, 0, (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),)
        ),
        gap_references=(GapReference(build.canonical_build_id, build.gap_content_id, 0),),
    )


def test_dataset_id_integration():
    feature = parsed_feature()
    label = parsed_label()
    pin = feature_label_spec_pin(feature)
    label_pin = feature_label_spec_pin(label)

    first = dataset_id(identity_input(feature_specs=(pin,), label_specs=(label_pin,)))
    # Equivalent semantics (any YAML layout) produce the same dataset_id.
    again = dataset_id(identity_input(
        feature_specs=(feature_label_spec_pin(parse_feature_spec(FEATURE_YAML_REORDERED)),),
        label_specs=(label_pin,),
    ))
    assert first == again

    # A semantic change changes the dataset_id.
    changed = mutate_feature(feature, parameters=set_parameter(feature, "lookback", 6))
    other = dataset_id(identity_input(
        feature_specs=(feature_label_spec_pin(changed),),
        label_specs=(label_pin,),
    ))
    assert other != first

    # Duplicate (kind, name, version) pins fail closed under the existing
    # duplicate contract, whether content is identical or drifted.
    with pytest.raises(DatasetError):
        dataset_id(identity_input(feature_specs=(pin, pin), label_specs=(label_pin,)))
    drifted = SpecPin("FEATURE", feature.name, feature.version, sha("drifted"))
    with pytest.raises(DatasetError):
        dataset_id(identity_input(feature_specs=(pin, drifted), label_specs=(label_pin,)))

    # ImplementationPin is a separate binding: it changes dataset_id but is
    # never produced by the spec parser.
    with_impl = dataset_id(identity_input(
        feature_specs=(pin,), label_specs=(label_pin,),
        implementations=(ImplementationPin("close_return_impl", "v1", sha("impl")),),
    ))
    assert with_impl != first
    with_impl_v2 = dataset_id(identity_input(
        feature_specs=(pin,), label_specs=(label_pin,),
        implementations=(ImplementationPin("close_return_impl", "v2", sha("impl2")),),
    ))
    assert with_impl_v2 != with_impl


# ---------------------------------------------------------------------------
# Unified error contract and public API surface.
# ---------------------------------------------------------------------------

BAD_SNIPPETS = [
    ("malformed yaml", "a: [1, 2"),
    ("undefined alias", "b: *x"),
    ("root list", "- 1"),
    ("unknown field", "spec_schema_version: market-vault-feature-spec-v1\nunknown: 1\n"),
    ("bad nested shape", "spec_schema_version: market-vault-feature-spec-v1\nkind: FEATURE\nname: x\nversion: v1\noutput: [1]\ninputs: {canonical_fields: [close]}\ntransform: {ref: m:f}\nparameters: {}\nrequirements: {canonical_schema_versions: [c], source_schema_versions: [s]}\n"),
    ("non-mapping output", "spec_schema_version: market-vault-feature-spec-v1\nkind: FEATURE\nname: x\nversion: v1\noutput: 5\ninputs: {canonical_fields: [close]}\ntransform: {ref: m:f}\nparameters: {}\nrequirements: {canonical_schema_versions: [c], source_schema_versions: [s]}\n"),
    ("int version", "spec_schema_version: market-vault-feature-spec-v1\nkind: FEATURE\nname: x\nversion: 1\noutput: {name: x, logical_type: float64, nullable: false}\ninputs: {canonical_fields: [close]}\ntransform: {ref: m:f}\nparameters: {}\nrequirements: {canonical_schema_versions: [c], source_schema_versions: [s]}\n"),
    ("bool parameter key", "spec_schema_version: market-vault-feature-spec-v1\nkind: FEATURE\nname: x\nversion: v1\noutput: {name: x, logical_type: float64, nullable: false}\ninputs: {canonical_fields: [close]}\ntransform: {ref: m:f}\nparameters: {true: 1}\nrequirements: {canonical_schema_versions: [c], source_schema_versions: [s]}\n"),
    ("list parameter value", "spec_schema_version: market-vault-feature-spec-v1\nkind: FEATURE\nname: x\nversion: v1\noutput: {name: x, logical_type: float64, nullable: false}\ninputs: {canonical_fields: [close]}\ntransform: {ref: m:f}\nparameters: {p: [1]}\nrequirements: {canonical_schema_versions: [c], source_schema_versions: [s]}\n"),
    ("unquoted numeric schema version", "spec_schema_version: market-vault-feature-spec-v1\nkind: FEATURE\nname: x\nversion: v1\noutput: {name: x, logical_type: float64, nullable: false}\ninputs: {canonical_fields: [close]}\ntransform: {ref: m:f}\nparameters: {}\nrequirements: {canonical_schema_versions: [c], source_schema_versions: [10.9]}\n"),
    ("custom tag", "a: !custom x"),
    ("tab indentation", "spec_schema_version: market-vault-feature-spec-v1\n\tkind: FEATURE\n"),
]


@pytest.mark.parametrize("label,text", BAD_SNIPPETS)
def test_all_errors_are_spec_validation_error(label, text):
    with pytest.raises(SpecValidationError) as caught:
        parse_feature_spec(text)
    assert isinstance(caught.value, DatasetError)
    assert isinstance(caught.value, ValueError)
    assert str(caught.value)


def test_transform_ref_is_never_imported_or_executed():
    # A ref to a module that does not exist must parse and hash fine.
    spec = parse_feature_spec(feature_yaml(ref="  ref: this_module_does_not_exist_xyz.qq:fn"))
    assert spec.transform_ref == "this_module_does_not_exist_xyz.qq:fn"
    assert _SHA_HEX.fullmatch(feature_label_spec_content_id(spec))


def test_parse_never_touches_filesystem(monkeypatch):
    def fail_open(*args, **kwargs):
        raise AssertionError("spec parse must never open files")

    monkeypatch.setattr("builtins.open", fail_open)
    assert parse_feature_spec(FEATURE_YAML).name == "close_return"
    assert parse_label_spec(LABEL_YAML).name == "next_day_ret"


def test_public_all_stable_and_no_internal_leaks():
    import market_vault.dataset as dataset
    assert not any(name.startswith("_") for name in dataset.__all__)
    for name in (
        "FEATURE_SPEC_SCHEMA_VERSION",
        "LABEL_SPEC_SCHEMA_VERSION",
        "FEATURE_LABEL_SPEC_CONTENT_ID_VERSION",
        "SpecValidationError",
        "SpecParameter",
        "SpecVersionRequirements",
        "FeatureSpec",
        "LabelSpec",
        "LabelHorizon",
        "LabelObservationWindow",
        "CrossTradingDayPolicy",
        "parse_feature_spec",
        "parse_label_spec",
        "load_feature_spec",
        "load_label_spec",
        "feature_label_spec_content_id",
        "feature_label_spec_pin",
    ):
        assert name in dataset.__all__
        assert hasattr(dataset, name)
    from market_vault.dataset.spec_models import __all__ as models_all
    from market_vault.dataset.specs import __all__ as specs_all
    assert not any(name.startswith("_") for name in models_all + specs_all)
    namespace = {}
    exec("from market_vault.dataset import *", namespace)
    for name in dataset.__all__:
        assert name in namespace
    assert "FeatureSpec" in namespace
    assert "SpecValidationError" in namespace
