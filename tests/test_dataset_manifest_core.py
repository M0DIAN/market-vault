"""Offline deterministic tests for the derived-dataset manifest core.

Covers the explicit logical schema model, dataset_schema_id, deterministic
logical content hashing, canonical-build provenance pins, spec/implementation
fingerprints, scope and dataset_as_of normalization, completion and gap
references, deterministic dataset_id, the versioned Dataset manifest, strict
validation, and atomic standalone manifest writing. No network, no stored
market data, no Dataset Parquet.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_vault.dataset import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    CanonicalBuildPin,
    CompletionEntry,
    CompletionSummary,
    DatasetError,
    DatasetField,
    DatasetIdentityInput,
    DatasetManifest,
    DatasetOutputFile,
    DatasetSchema,
    DatasetScope,
    GapReference,
    ImplementationPin,
    SourceSnapshotPin,
    SpecPin,
    build_dataset_manifest,
    dataset_id,
    dataset_schema_id,
    encode_scalar,
    logical_dataset_content_id,
    serialize_dataset_manifest,
    validate_dataset_manifest,
    write_dataset_manifest_atomic,
)

UTC = timezone.utc
NY = "America/New_York"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Helpers: deterministic schemas, rows, pins, inputs, manifests.
# ---------------------------------------------------------------------------


def market_schema(order=("ts", "sym", "close")) -> DatasetSchema:
    """Default logical schema: timestamp, string symbol, nullable close."""
    types = {"ts": "timestamp_us_utc", "sym": "string", "close": "float64"}
    return DatasetSchema(
        tuple(DatasetField(name, types[name], name == "close") for name in order)
    )


INSTANT = datetime(2026, 7, 1, 13, 30, 0, tzinfo=UTC)


def row(ts=INSTANT, sym="US.MU", close=100.5, **overrides) -> dict:
    values = {"ts": ts, "sym": sym, "close": close}
    values.update(overrides)
    return values


def content_id(*rows) -> str:
    return logical_dataset_content_id(market_schema(), rows)


def snapshot_pin(seed: str = "a") -> SourceSnapshotPin:
    return SourceSnapshotPin(
        ingestion_run_id=f"run-{seed}",
        physical_snapshot_hash=sha(f"physical-{seed}"),
        logical_source_rows_hash=sha(f"logical-{seed}"),
        source_schema_version="10.9",
        requested_trade_date=date(2026, 7, 1),
        requested_session="ALL",
    )


def build_pin(
    seed: str = "a",
    *,
    status: str = STATUS_COMPLETE,
    row_seeds: tuple[str, ...] | None = None,
    snapshot_seeds: tuple[str, ...] = ("a",),
    gap_seed: str | None = None,
) -> CanonicalBuildPin:
    if row_seeds is None:
        row_seeds = () if status == STATUS_EMPTY else (f"row-{seed}-1", f"row-{seed}-2")
    return CanonicalBuildPin(
        canonical_build_id=sha(f"build-{seed}"),
        canonical_content_id=sha(f"content-{seed}"),
        canonical_builder_version="market-bars-canonical-builder-v1",
        canonical_schema_version="market-bars-canonical-schema-v1",
        materializer_version="market-bars-materializer-v1",
        gap_policy_version="market-bars-gap-policy-v1",
        gap_content_id=sha(f"gap-{gap_seed or seed}"),
        status=status,
        canonical_row_version_ids=tuple(sha(item) for item in row_seeds),
        source_snapshots=tuple(snapshot_pin(item) for item in snapshot_seeds),
    )


def completion(
    complete: int = 1, incomplete: int = 0, missing: int = 0, reason: str | None = None
) -> CompletionSummary:
    entries = []
    if complete:
        entries.append(
            CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE", reason_code=reason)
        )
    if incomplete:
        entries.append(
            CompletionEntry("US.MU", date(2026, 7, 1), "INCOMPLETE", reason_code=reason)
        )
    if missing:
        entries.append(
            CompletionEntry("US.MU", date(2026, 7, 1), "MISSING", reason_code=reason)
        )
    return CompletionSummary(complete, incomplete, missing, tuple(entries))


def base_input(**overrides) -> DatasetIdentityInput:
    pin = build_pin("a")
    values = dict(
        dataset_kind="market_bars_dataset",
        scope=DatasetScope(
            ["US.MU"], [date(2026, 7, 1)], adjustment="NONE", interval="1m", requested_session="ALL"
        ),
        dataset_as_of=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        schema=market_schema(),
        dataset_schema_id=dataset_schema_id(market_schema()),
        logical_dataset_content_id=content_id(row(), row(close=None)),
        canonical_builds=(pin,),
        canonical_row_version_ids=pin.canonical_row_version_ids,
        feature_specs=(
            SpecPin("FEATURE", "close_return", "v1", sha("feature-v1")),
            SpecPin("FEATURE", "close_delta", "v1", sha("feature-v2")),
        ),
        label_specs=(SpecPin("LABEL", "next_close_ret", "v1", sha("label-v1")),),
        split_spec=None,
        implementations=(
            ImplementationPin("close_return_impl", "v1", sha("impl-v1")),
            ImplementationPin("close_delta_impl", "v2", sha("impl-v2")),
        ),
        completion=completion(),
        gap_references=(GapReference(pin.canonical_build_id, pin.gap_content_id, 0),),
    )
    values.update(overrides)
    return DatasetIdentityInput(**values)


def base_manifest(**overrides) -> DatasetManifest:
    manifest = build_dataset_manifest(
        base_input(),
        built_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
        status=STATUS_COMPLETE,
        logical_row_count=2,
        output_files=(
            DatasetOutputFile(
                "data/part-00000.parquet", "dataset", 2, 1024, sha("bytes"), "parquet"
            ),
        ),
    )
    return replace(manifest, **overrides) if overrides else manifest


def two_symbol_scope(*symbols, **overrides) -> DatasetScope:
    return DatasetScope(
        list(symbols), [date(2026, 7, 1)], adjustment="NONE", interval="1m", requested_session="ALL", **overrides
    )


# ---------------------------------------------------------------------------
# Schema identity.
# ---------------------------------------------------------------------------


def test_field_order_changes_schema_id():
    assert dataset_schema_id(market_schema(("ts", "sym", "close"))) != dataset_schema_id(
        market_schema(("sym", "ts", "close"))
    )


def test_field_type_change_changes_schema_id():
    base = market_schema()
    changed = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False),
         DatasetField("close", "int64", True))
    )
    assert dataset_schema_id(base) != dataset_schema_id(changed)


def test_nullability_change_changes_schema_id():
    base = market_schema()
    changed = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False),
         DatasetField("close", "float64", False))
    )
    assert dataset_schema_id(base) != dataset_schema_id(changed)


def test_field_name_change_changes_schema_id():
    base = market_schema()
    renamed = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("symbol", "string", False),
         DatasetField("close", "float64", True))
    )
    assert dataset_schema_id(base) != dataset_schema_id(renamed)


def test_duplicate_field_names_fail():
    with pytest.raises(DatasetError, match="duplicate field names"):
        DatasetSchema(
            (DatasetField("sym", "string", False), DatasetField("sym", "int64", False))
        )


def test_unsupported_logical_type_fails():
    with pytest.raises(DatasetError, match="unsupported logical type"):
        DatasetField("meta", "list<string>", False)
    with pytest.raises(DatasetError, match="unsupported logical type"):
        DatasetField("meta", "object", False)


def test_non_string_field_name_fails():
    with pytest.raises(DatasetError, match="must be a string"):
        DatasetField(42, "string", False)


def test_empty_field_name_fails():
    with pytest.raises(DatasetError, match="must not be empty"):
        DatasetField("", "string", False)


def test_field_name_control_character_fails():
    with pytest.raises(DatasetError, match="control character"):
        DatasetField("sym\x00name", "string", False)
    # \x1f is itself a control character; the reserved separator "|" gets its
    # own message.
    with pytest.raises(DatasetError, match="control character"):
        DatasetField("sym\x1fname", "string", False)
    with pytest.raises(DatasetError, match="encoding separator"):
        DatasetField("sym|name", "string", False)


def test_nullable_must_be_real_bool():
    with pytest.raises(DatasetError, match="nullable must be a real bool"):
        DatasetField("close", "float64", 1)
    with pytest.raises(DatasetError, match="nullable must be a real bool"):
        DatasetField("close", "float64", np.bool_(True))


# ---------------------------------------------------------------------------
# Scalar encoding.
# ---------------------------------------------------------------------------


def test_timestamp_utc_equivalents_hash_identically():
    a = content_id(row(ts=datetime(2026, 7, 1, 13, 30, 0, tzinfo=UTC)))
    b = content_id(row(ts=pd.Timestamp("2026-07-01T09:30:00-04:00")))
    assert a == b


def test_naive_timestamp_fails():
    with pytest.raises(DatasetError, match="naive"):
        encode_scalar(datetime(2026, 7, 1, 13, 30, 0))
    with pytest.raises(DatasetError, match="naive"):
        content_id(row(ts=pd.Timestamp("2026-07-01T13:30:00")))


def test_timestamp_microseconds_normalized():
    ns_precision = pd.Timestamp("2026-07-01T13:30:00.123456789+00:00")
    micro = pd.Timestamp("2026-07-01T13:30:00.123456+00:00")
    assert encode_scalar(ns_precision) == encode_scalar(micro)
    assert content_id(row(ts=ns_precision)) == content_id(row(ts=micro))
    assert encode_scalar(ns_precision) == "t:2026-07-01T13:30:00.123456+00:00"


def test_date_and_datetime_are_not_confused():
    assert encode_scalar(date(2026, 7, 1)) == "d:2026-07-01"
    assert encode_scalar(datetime(2026, 7, 1, 0, 0, tzinfo=UTC)) == (
        "t:2026-07-01T00:00:00+00:00"
    )
    assert encode_scalar(date(2026, 7, 1)) != encode_scalar(
        datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    )


def test_date32_field_rejects_datetime():
    date_schema = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False),
         DatasetField("day", "date32", False))
    )
    good = logical_dataset_content_id(date_schema, ({"ts": INSTANT, "sym": "US.MU", "day": date(2026, 7, 1)},))
    assert good
    with pytest.raises(DatasetError, match="rejects datetime"):
        logical_dataset_content_id(
            date_schema,
            ({"ts": INSTANT, "sym": "US.MU", "day": datetime(2026, 7, 1, tzinfo=UTC)},),
        )


def test_bool_and_int_are_distinct():
    assert encode_scalar(True) == "b:true"
    assert encode_scalar(1) == "i:1"
    assert encode_scalar(False) != encode_scalar(0)
    bool_schema = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False),
         DatasetField("flag", "bool", False))
    )
    flags = logical_dataset_content_id(
        bool_schema, ({"ts": INSTANT, "sym": "US.MU", "flag": True},)
    )
    assert flags != logical_dataset_content_id(
        bool_schema, ({"ts": INSTANT, "sym": "US.MU", "flag": False},)
    )
    with pytest.raises(DatasetError, match="expects bool"):
        logical_dataset_content_id(
            bool_schema, ({"ts": INSTANT, "sym": "US.MU", "flag": 1},)
        )


def test_bool_rejected_as_int64():
    int_schema = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False),
         DatasetField("count", "int64", False))
    )
    with pytest.raises(DatasetError, match="expects int64"):
        logical_dataset_content_id(
            int_schema, ({"ts": INSTANT, "sym": "US.MU", "count": True},)
        )


def test_int64_accepts_numpy_integers():
    int_schema = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False),
         DatasetField("count", "int64", False))
    )
    assert logical_dataset_content_id(
        int_schema, ({"ts": INSTANT, "sym": "US.MU", "count": np.int64(42)},)
    ) == logical_dataset_content_id(
        int_schema, ({"ts": INSTANT, "sym": "US.MU", "count": 42},)
    )


def test_negative_zero_normalizes():
    assert encode_scalar(-0.0) == encode_scalar(0.0) == "f:0.0"
    assert content_id(row(close=-0.0)) == content_id(row(close=0.0))


def test_float_nan_and_infinity_fail():
    with pytest.raises(DatasetError, match="NaN"):
        encode_scalar(float("nan"))
    with pytest.raises(DatasetError, match="infinity"):
        encode_scalar(float("inf"))
    with pytest.raises(DatasetError, match="infinity"):
        encode_scalar(float("-inf"))
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(DatasetError, match="NaN|infinity"):
            content_id(row(close=bad))


def test_float64_accepts_int_coercion():
    assert content_id(row(close=100)) == content_id(row(close=100.0))


def test_string_values_not_stripped_or_case_folded():
    assert content_id(row(sym="US.MU")) != content_id(row(sym=" us.mu "))
    assert content_id(row(sym="US.MU")) != content_id(row(sym="us.mu"))


def test_string_control_character_fails():
    with pytest.raises(DatasetError, match="control character"):
        content_id(row(sym="US\x00MU"))


def test_unicode_normalization_pinned():
    assert encode_scalar("e\u0301") == "s:\u00e9"  # NFD composes to NFC
    assert content_id(row(sym="caf\u00e9")) == content_id(row(sym="cafe\u0301"))


def test_explicit_tagged_formats_pinned():
    assert encode_scalar(None) == "n"
    assert encode_scalar(False) == "b:false"
    assert encode_scalar(42) == "i:42"
    assert encode_scalar(100.5) == "f:100.5"
    assert encode_scalar("abc") == "s:abc"
    assert encode_scalar(date(2026, 7, 1)) == "d:2026-07-01"
    assert encode_scalar(datetime(2026, 7, 1, 0, 0, tzinfo=UTC)) == "t:2026-07-01T00:00:00+00:00"


def test_unsupported_scalar_type_fails():
    with pytest.raises(DatasetError, match="unsupported scalar type"):
        encode_scalar([1, 2])


# ---------------------------------------------------------------------------
# Logical content identity.
# ---------------------------------------------------------------------------


def test_row_order_does_not_change_content_id():
    first = content_id(row(ts=INSTANT, sym="US.MU"), row(ts=INSTANT, sym="US.NVDA"))
    second = content_id(row(ts=INSTANT, sym="US.NVDA"), row(ts=INSTANT, sym="US.MU"))
    assert first == second


def test_mapping_insertion_order_does_not_matter():
    a = content_id({"ts": INSTANT, "sym": "US.MU", "close": 100.5})
    b = content_id({"close": 100.5, "sym": "US.MU", "ts": INSTANT})
    assert a == b


def test_duplicate_row_multiplicity_changes_content_id():
    assert content_id(row()) != content_id(row(), row())
    assert content_id(row(), row(ts=INSTANT, sym="US.NVDA"), row()) == content_id(
        row(ts=INSTANT, sym="US.NVDA"), row(), row()
    )


def test_one_value_change_changes_content_id():
    assert content_id(row(close=100.5)) != content_id(row(close=100.25))


def test_null_versus_non_null_changes_content_id():
    assert content_id(row(close=100.5)) != content_id(row(close=None))


def test_missing_or_extra_fields_fail():
    with pytest.raises(DatasetError, match="missing field 'ts'"):
        content_id({"sym": "US.MU", "close": 100.5})
    with pytest.raises(DatasetError, match="unknown field"):
        content_id({"ts": INSTANT, "sym": "US.MU", "close": 100.5, "extra": 1})
    with pytest.raises(DatasetError, match="missing field 'close'"):
        content_id({"ts": INSTANT, "sym": "US.MU"})


def test_non_nullable_null_fails():
    non_nullable_schema = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False),
         DatasetField("close", "float64", False))
    )
    with pytest.raises(DatasetError, match="received null"):
        logical_dataset_content_id(
            non_nullable_schema,
            ({"ts": INSTANT, "sym": "US.MU", "close": None},),
        )


def test_schema_change_changes_content_id():
    wider = DatasetSchema(
        market_schema().fields + (DatasetField("volume", "int64", False),)
    )
    assert content_id(row()) != logical_dataset_content_id(
        wider, (row() | {"volume": 100},)
    )


def test_zero_row_content_is_deterministic_and_schema_tied():
    schema_a = market_schema()
    schema_b = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False), DatasetField("sym", "string", False))
    )
    empty_a_1 = logical_dataset_content_id(schema_a, ())
    empty_a_2 = logical_dataset_content_id(schema_a, ())
    empty_b = logical_dataset_content_id(schema_b, ())
    assert empty_a_1 == empty_a_2
    assert empty_a_1 != empty_b
    assert empty_a_1 != logical_dataset_content_id(schema_a, (row(),))


def test_content_id_requires_mapping_rows():
    with pytest.raises(DatasetError, match="mappings"):
        content_id([1, 2])


# ---------------------------------------------------------------------------
# Canonical build and source pins.
# ---------------------------------------------------------------------------


def test_canonical_paths_do_not_participate():
    pin = build_pin("a")
    snapshot = pin.source_snapshots[0]
    assert not hasattr(pin, "snapshot_file")
    assert not hasattr(pin, "created_at")
    assert not hasattr(snapshot, "snapshot_file")
    assert not hasattr(snapshot, "created_at")


def test_reordered_canonical_pins_same_dataset_id():
    pin_a = build_pin("a")
    pin_b = build_pin("b", row_seeds=("x-1", "x-2"), gap_seed="b")
    scope = two_symbol_scope("US.MU", "US.NVDA")
    completion_two = CompletionSummary(
        2, 0, 0,
        (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),
         CompletionEntry("US.NVDA", date(2026, 7, 1), "COMPLETE")),
    )
    common = dict(
        scope=scope,
        completion=completion_two,
        canonical_row_version_ids=pin_a.canonical_row_version_ids + pin_b.canonical_row_version_ids,
        gap_references=(
            GapReference(pin_a.canonical_build_id, pin_a.gap_content_id, 0),
            GapReference(pin_b.canonical_build_id, pin_b.gap_content_id, 0),
        ),
    )
    forward = base_input(canonical_builds=(pin_a, pin_b), **common)
    backward = base_input(canonical_builds=(pin_b, pin_a), **common)
    assert dataset_id(forward) == dataset_id(backward)


def test_physical_snapshot_hash_change_changes_dataset_id():
    pin_a = build_pin("a")
    pin_b = build_pin("a", snapshot_seeds=("b",))
    assert dataset_id(base_input(canonical_builds=(pin_a,))) != dataset_id(
        base_input(canonical_builds=(pin_b,))
    )


def test_canonical_row_version_change_changes_dataset_id():
    pin_a = build_pin("a")
    pin_b = build_pin("a", row_seeds=("other-1", "other-2"))
    assert dataset_id(
        base_input(canonical_builds=(pin_a,), canonical_row_version_ids=pin_a.canonical_row_version_ids)
    ) != dataset_id(
        base_input(canonical_builds=(pin_b,), canonical_row_version_ids=pin_b.canonical_row_version_ids)
    )


def test_row_version_subset_changes_dataset_id():
    pin = build_pin("a")
    assert dataset_id(base_input(canonical_row_version_ids=(pin.canonical_row_version_ids[0],))) != dataset_id(
        base_input(canonical_row_version_ids=pin.canonical_row_version_ids)
    )


def test_duplicate_canonical_build_pins_fail():
    pin = build_pin("a")
    with pytest.raises(DatasetError, match="duplicate canonical build pin"):
        dataset_id(base_input(canonical_builds=(pin, pin)))


def test_conflicting_canonical_build_pins_fail():
    pin_a = build_pin("a")
    pin_b = build_pin("a", gap_seed="conflicting")
    with pytest.raises(DatasetError, match="duplicate canonical build pin"):
        dataset_id(base_input(canonical_builds=(pin_a, pin_b)))


def test_invalid_hashes_fail():
    with pytest.raises(DatasetError, match="SHA-256"):
        CanonicalBuildPin(
            canonical_build_id=sha("build"), canonical_content_id=sha("content"),
            canonical_builder_version="b", canonical_schema_version="s",
            materializer_version="m", gap_policy_version="g", gap_content_id=sha("gap"),
            status=STATUS_COMPLETE,
            canonical_row_version_ids=("not-a-hash",),
            source_snapshots=(snapshot_pin("a"),),
        )
    with pytest.raises(DatasetError, match="SHA-256"):
        SourceSnapshotPin("run", "xyz", sha("logical"), "10.9", date(2026, 7, 1), "ALL")
    with pytest.raises(DatasetError, match="SHA-256"):
        SpecPin("FEATURE", "f", "v1", "ABC")
    with pytest.raises(DatasetError, match="SHA-256"):
        base_input(dataset_schema_id="not-a-sha256")


def test_uppercase_hashes_normalized_to_lowercase():
    pin = build_pin("a")
    upper = SourceSnapshotPin(
        "run-a", pin.source_snapshots[0].physical_snapshot_hash.upper(),
        pin.source_snapshots[0].logical_source_rows_hash, "10.9", date(2026, 7, 1), "ALL",
    )
    assert upper.physical_snapshot_hash == pin.source_snapshots[0].physical_snapshot_hash


def test_empty_canonical_pin_with_row_ids_fails():
    with pytest.raises(DatasetError, match="EMPTY canonical build pin"):
        build_pin("a", status=STATUS_EMPTY, row_seeds=("r-1", "r-2"))


def test_empty_canonical_pin_is_valid():
    pin = build_pin("a", status=STATUS_EMPTY, row_seeds=())
    empty_input = base_input(
        canonical_builds=(pin,),
        canonical_row_version_ids=(),
        gap_references=(GapReference(pin.canonical_build_id, pin.gap_content_id, 0),),
        completion=CompletionSummary(0, 0, 0, ()),
    )
    assert dataset_id(empty_input)
    manifest = build_dataset_manifest(
        empty_input, built_at=datetime(2026, 7, 3, tzinfo=UTC),
        status=STATUS_EMPTY, logical_row_count=0,
    )
    assert manifest.dataset_id == dataset_id(empty_input)


def test_duplicate_source_snapshots_deduplicated():
    snapshots = (snapshot_pin("a"), snapshot_pin("a"))
    pin = CanonicalBuildPin(
        canonical_build_id=sha("build"), canonical_content_id=sha("content"),
        canonical_builder_version="b", canonical_schema_version="s",
        materializer_version="m", gap_policy_version="g", gap_content_id=sha("gap"),
        status=STATUS_COMPLETE,
        canonical_row_version_ids=(sha("r1"),),
        source_snapshots=snapshots,
    )
    assert len(pin.source_snapshots) == 1


def test_reordered_specs_and_implementations_same_dataset_id():
    feature_a = SpecPin("FEATURE", "close_return", "v1", sha("feature-v1"))
    feature_b = SpecPin("FEATURE", "close_delta", "v1", sha("feature-v2"))
    impl_a = ImplementationPin("impl_a", "v1", sha("impl-a"))
    impl_b = ImplementationPin("impl_b", "v1", sha("impl-b"))
    forward = base_input(feature_specs=(feature_a, feature_b), implementations=(impl_a, impl_b))
    backward = base_input(feature_specs=(feature_b, feature_a), implementations=(impl_b, impl_a))
    assert dataset_id(forward) == dataset_id(backward)


def test_spec_content_change_changes_dataset_id():
    base = base_input()
    changed = base_input(
        feature_specs=(SpecPin("FEATURE", "close_return", "v1", sha("feature-v1-changed")),
                       SpecPin("FEATURE", "close_delta", "v1", sha("feature-v2"))),
    )
    assert dataset_id(base) != dataset_id(changed)


def test_implementation_version_or_hash_change_changes_dataset_id():
    base = base_input()
    versioned = base_input(
        implementations=(ImplementationPin("close_return_impl", "v2", sha("impl-v1")),
                         ImplementationPin("close_delta_impl", "v2", sha("impl-v2"))),
    )
    hashed = base_input(
        implementations=(ImplementationPin("close_return_impl", "v1", sha("impl-v1-changed")),
                         ImplementationPin("close_delta_impl", "v2", sha("impl-v2"))),
    )
    assert dataset_id(base) != dataset_id(versioned)
    assert dataset_id(base) != dataset_id(hashed)


def test_duplicate_spec_pins_fail():
    feature = SpecPin("FEATURE", "close_return", "v1", sha("f"))
    with pytest.raises(DatasetError, match="duplicate spec pin"):
        dataset_id(base_input(feature_specs=(feature, feature)))


def test_duplicate_implementation_pins_fail():
    impl = ImplementationPin("close_return_impl", "v1", sha("i"))
    with pytest.raises(DatasetError, match="duplicate implementation pin"):
        dataset_id(base_input(implementations=(impl, impl)))


def test_invalid_spec_kind_fails():
    with pytest.raises(DatasetError, match="kind must be FEATURE"):
        SpecPin("TRANSFORM", "f", "v1", sha("f"))


def test_row_version_not_covered_by_pinned_builds_fails():
    with pytest.raises(DatasetError, match="not covered by the pinned canonical builds"):
        dataset_id(base_input(canonical_row_version_ids=(sha("foreign-row"),)))


# ---------------------------------------------------------------------------
# Scope and dataset_as_of.
# ---------------------------------------------------------------------------


def test_symbol_and_date_order_do_not_matter():
    scope_ab = two_symbol_scope("US.MU", "US.NVDA")
    scope_ba = two_symbol_scope("US.NVDA", "US.MU")
    assert dataset_id(base_input(scope=scope_ab)) == dataset_id(base_input(scope=scope_ba))
    scope_dates_a = DatasetScope(
        ["US.MU"], [date(2026, 7, 1), date(2026, 7, 2)], "NONE", "1m", "ALL"
    )
    scope_dates_b = DatasetScope(
        ["US.MU"], [date(2026, 7, 2), date(2026, 7, 1)], "NONE", "1m", "ALL"
    )
    assert dataset_id(base_input(scope=scope_dates_a)) == dataset_id(base_input(scope=scope_dates_b))


def test_symbol_casing_and_whitespace_normalizes():
    messy = two_symbol_scope(" us.mu ", "US.NVDA ")
    clean = two_symbol_scope("US.MU", "US.NVDA")
    assert dataset_id(base_input(scope=messy)) == dataset_id(base_input(scope=clean))


def test_scope_normalization_applies():
    scope = DatasetScope([" us.nvda ", "US.MU", "us.nvda"], [date(2026, 7, 1)], "none", " 1M ", " all ")
    assert scope.symbols == ("US.MU", "US.NVDA")
    assert scope.adjustment == "NONE"
    assert scope.interval == "1m"
    assert scope.requested_session == "ALL"


def test_empty_scope_fails():
    with pytest.raises(DatasetError, match="at least one symbol"):
        DatasetScope([], [date(2026, 7, 1)], "NONE", "1m", "ALL")
    with pytest.raises(DatasetError, match="at least one trade date"):
        DatasetScope(["US.MU"], [], "NONE", "1m", "ALL")


def test_unsafe_scope_values_fail():
    with pytest.raises(DatasetError, match="control character"):
        DatasetScope(["US\x00MU"], [date(2026, 7, 1)], "NONE", "1m", "ALL")
    with pytest.raises(DatasetError, match="control character"):
        DatasetScope(["US.MU"], [date(2026, 7, 1)], "NONE", "1\x1fm", "ALL")
    with pytest.raises(DatasetError, match="encoding separator"):
        DatasetScope(["US.MU"], [date(2026, 7, 1)], "NONE", "1|m", "ALL")
    with pytest.raises(DatasetError, match="must not be empty"):
        DatasetScope(["US.MU"], [date(2026, 7, 1)], "  ", "1m", "ALL")


def test_scope_change_changes_dataset_id():
    base = base_input()
    assert dataset_id(base) != dataset_id(
        base_input(scope=two_symbol_scope("US.MU", "US.NVDA"))
    )
    assert dataset_id(base) != dataset_id(
        base_input(scope=DatasetScope(["US.MU"], [date(2026, 7, 2)], "NONE", "1m", "ALL"))
    )


def test_naive_dataset_as_of_fails():
    with pytest.raises(DatasetError, match="timezone-aware"):
        base_input(dataset_as_of=datetime(2026, 7, 2, 12, 0))


def test_timezone_equivalent_dataset_as_of_same_id():
    utc = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    ny = pd.Timestamp("2026-07-02T08:00:00-04:00")
    assert dataset_id(base_input(dataset_as_of=utc)) == dataset_id(base_input(dataset_as_of=ny))


def test_different_dataset_as_of_changes_dataset_id():
    base = base_input()
    assert dataset_id(base) != dataset_id(
        base_input(dataset_as_of=datetime(2026, 7, 3, 12, 0, tzinfo=UTC))
    )


def test_dataset_as_of_normalized_to_utc():
    from market_vault.dataset.models import DatasetIdentityInput as Model

    ny = pd.Timestamp("2026-07-02T08:00:00-04:00")
    normalized = Model(
        dataset_kind="market_bars_dataset",
        scope=DatasetScope(["US.MU"], [date(2026, 7, 1)], "NONE", "1m", "ALL"),
        dataset_as_of=ny,
        schema=market_schema(),
        dataset_schema_id=dataset_schema_id(market_schema()),
        logical_dataset_content_id=content_id(row()),
        canonical_builds=(),
        canonical_row_version_ids=(),
        feature_specs=(),
        label_specs=(),
        split_spec=None,
        implementations=(),
        completion=CompletionSummary(0, 0, 0, ()),
        gap_references=(),
    )
    assert normalized.dataset_as_of == datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Completion and gap references.
# ---------------------------------------------------------------------------


def test_completion_counts_must_match_entries():
    with pytest.raises(DatasetError, match="counts must equal"):
        CompletionSummary(2, 0, 0, (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),))
    with pytest.raises(DatasetError, match="counts must equal"):
        CompletionSummary(0, 0, 0, (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),))


def test_duplicate_completion_keys_fail():
    entry = CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE")
    with pytest.raises(DatasetError, match="duplicate completion key"):
        CompletionSummary(2, 0, 0, (entry, entry))


def test_unknown_completion_status_fails():
    with pytest.raises(DatasetError, match="completion status"):
        CompletionEntry("US.MU", date(2026, 7, 1), "BOGUS")


def test_completion_status_change_affects_dataset_id():
    base = base_input()
    changed = base_input(
        completion=CompletionSummary(
            0, 1, 0,
            (CompletionEntry("US.MU", date(2026, 7, 1), "INCOMPLETE", reason_code="no-observation"),),
        )
    )
    assert dataset_id(base) != dataset_id(changed)


def test_completion_reason_change_affects_dataset_id():
    base = base_input()
    reasoned = base_input(
        completion=CompletionSummary(
            1, 0, 0,
            (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE", reason_code="stable-code"),),
        )
    )
    assert dataset_id(base) != dataset_id(reasoned)


def test_reordered_completion_entries_same_dataset_id():
    first = CompletionSummary(
        1, 1, 0,
        (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),
         CompletionEntry("US.NVDA", date(2026, 7, 1), "INCOMPLETE", reason_code="gap")),
    )
    second = CompletionSummary(
        1, 1, 0,
        (CompletionEntry("US.NVDA", date(2026, 7, 1), "INCOMPLETE", reason_code="gap"),
         CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE")),
    )
    scope = two_symbol_scope("US.MU", "US.NVDA")
    assert dataset_id(base_input(scope=scope, completion=first)) == dataset_id(
        base_input(scope=scope, completion=second)
    )


def test_gap_content_change_affects_dataset_id():
    pin_a = build_pin("a")
    pin_b = build_pin("a", gap_seed="different")
    assert dataset_id(base_input(canonical_builds=(pin_a,))) != dataset_id(
        base_input(
            canonical_builds=(pin_b,),
            gap_references=(GapReference(pin_b.canonical_build_id, pin_b.gap_content_id, 0),),
        )
    )


def test_reordered_gap_references_same_dataset_id():
    pin_a = build_pin("a")
    pin_b = build_pin("b", row_seeds=("x-1", "x-2"), gap_seed="b")
    scope = two_symbol_scope("US.MU", "US.NVDA")
    completion_two = CompletionSummary(
        2, 0, 0,
        (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),
         CompletionEntry("US.NVDA", date(2026, 7, 1), "COMPLETE")),
    )
    refs_a = (
        GapReference(pin_a.canonical_build_id, pin_a.gap_content_id, 0),
        GapReference(pin_b.canonical_build_id, pin_b.gap_content_id, 0),
    )
    refs_b = (
        GapReference(pin_b.canonical_build_id, pin_b.gap_content_id, 0),
        GapReference(pin_a.canonical_build_id, pin_a.gap_content_id, 0),
    )
    common = dict(
        scope=scope,
        completion=completion_two,
        canonical_row_version_ids=pin_a.canonical_row_version_ids + pin_b.canonical_row_version_ids,
        canonical_builds=(pin_a, pin_b),
    )
    assert dataset_id(base_input(gap_references=refs_a, **common)) == dataset_id(
        base_input(gap_references=refs_b, **common)
    )


def test_duplicate_gap_references_deduplicated():
    pin = build_pin("a")
    ref = GapReference(pin.canonical_build_id, pin.gap_content_id, 0)
    assert dataset_id(base_input(gap_references=(ref, ref))) == dataset_id(
        base_input(gap_references=(ref,))
    )


def test_gap_reference_to_unknown_build_fails():
    with pytest.raises(DatasetError, match="unknown canonical build"):
        dataset_id(
            base_input(gap_references=(GapReference(sha("foreign"), sha("gap"), 0),))
        )


def test_gap_reference_content_mismatch_fails():
    pin = build_pin("a")
    with pytest.raises(DatasetError, match="does not match pinned build"):
        dataset_id(
            base_input(gap_references=(GapReference(pin.canonical_build_id, sha("other-gap"), 0),))
        )


# ---------------------------------------------------------------------------
# Manifest.
# ---------------------------------------------------------------------------


def test_built_at_change_does_not_change_dataset_id():
    morning = base_manifest()
    evening = build_dataset_manifest(
        base_input(),
        built_at=datetime(2026, 7, 3, 22, 45, 0, tzinfo=UTC),
        status=STATUS_COMPLETE,
        logical_row_count=2,
        output_files=morning.output_files,
    )
    assert evening.dataset_id == morning.dataset_id


def test_output_path_or_hash_change_does_not_change_dataset_id():
    base = base_manifest()
    moved = build_dataset_manifest(
        base_input(),
        built_at=base.built_at,
        status=STATUS_COMPLETE,
        logical_row_count=2,
        output_files=(
            DatasetOutputFile("other/place.parquet", "dataset", 2, 999, sha("other-bytes"), "parquet"),
        ),
    )
    assert moved.dataset_id == base.dataset_id


def test_manifest_schema_version_change_changes_dataset_id():
    base = base_input()
    changed = base_input(manifest_schema_version="market-vault-dataset-manifest-v2")
    assert dataset_id(base) != dataset_id(changed)


def test_serialization_version_change_changes_dataset_id():
    base = base_input()
    changed = base_input(serialization_format_version="market-vault-dataset-parquet-v2")
    assert dataset_id(base) != dataset_id(changed)


def test_serialization_format_change_changes_dataset_id():
    base = base_input()
    changed = base_input(serialization_format="csv")
    assert dataset_id(base) != dataset_id(changed)


def test_serialization_contract_is_declared_future_output():
    manifest = base_manifest()
    assert manifest.serialization_format == "parquet"
    assert manifest.serialization_format_version == SERIALIZATION_FORMAT_VERSION_PARQUET
    assert manifest.output_files  # recorded facts only, never in dataset_id


def test_deterministic_json_with_trailing_newline():
    first = serialize_dataset_manifest(base_manifest())
    second = serialize_dataset_manifest(base_manifest())
    assert first == second
    assert first.endswith(b"\n")
    payload = json.loads(first)
    assert list(payload.keys()) == sorted(payload.keys())
    assert b'{"' in first  # compact separators, no spaces after braces
    assert b'"built_at":"2026-07-03T10:00:00.000000+00:00"' in first
    # ensure_ascii is fixed and documented.
    unicode_manifest = replace(base_manifest(), dataset_kind="caf\u00e9_kind")
    assert "caf\\u00e9".encode("utf-8") in serialize_dataset_manifest(unicode_manifest)


def test_round_trip_validation_succeeds():
    manifest = base_manifest()
    round_tripped = validate_dataset_manifest(serialize_dataset_manifest(manifest))
    assert round_tripped == manifest
    assert round_tripped.dataset_id == manifest.dataset_id


def test_stored_dataset_id_tampering_fails():
    payload = json.loads(serialize_dataset_manifest(base_manifest()))
    payload["dataset_id"] = sha("tampered")
    with pytest.raises(DatasetError, match="dataset_id does not match"):
        validate_dataset_manifest(payload)


def test_stored_dataset_schema_id_tampering_fails():
    payload = json.loads(serialize_dataset_manifest(base_manifest()))
    payload["dataset_schema_id"] = sha("tampered")
    with pytest.raises(DatasetError, match="dataset_schema_id does not match"):
        validate_dataset_manifest(payload)


def test_unknown_or_missing_manifest_field_fails():
    payload = json.loads(serialize_dataset_manifest(base_manifest()))
    payload["mystery_field"] = 1
    with pytest.raises(DatasetError, match="unknown manifest field"):
        validate_dataset_manifest(payload)
    del payload["mystery_field"]
    del payload["status"]
    with pytest.raises(DatasetError, match="missing manifest field"):
        validate_dataset_manifest(payload)


def test_manifest_row_count_invariants():
    empty = build_dataset_manifest(
        base_input(),
        built_at=datetime(2026, 7, 3, tzinfo=UTC),
        status=STATUS_EMPTY,
        logical_row_count=0,
    )
    assert empty.status == STATUS_EMPTY
    with pytest.raises(DatasetError, match="EMPTY requires"):
        build_dataset_manifest(
            base_input(), built_at=datetime(2026, 7, 3, tzinfo=UTC),
            status=STATUS_EMPTY, logical_row_count=1,
        )
    with pytest.raises(DatasetError, match="at least one logical row"):
        build_dataset_manifest(
            base_input(), built_at=datetime(2026, 7, 3, tzinfo=UTC),
            status=STATUS_COMPLETE, logical_row_count=0,
        )


def test_duplicate_output_paths_fail():
    record = DatasetOutputFile("data/part.parquet", "dataset", 1, 10, sha("x"), "parquet")
    with pytest.raises(DatasetError, match="duplicate output file"):
        build_dataset_manifest(
            base_input(), built_at=datetime(2026, 7, 3, tzinfo=UTC),
            status=STATUS_COMPLETE, logical_row_count=2,
            output_files=(record, record),
        )


@pytest.mark.parametrize(
    "path_text",
    ["/absolute.parquet", "dir\\windows.parquet", "dir/../escape.parquet",
     "dir/./self.parquet", "dir//double.parquet", "dir\x00null.parquet"],
)
def test_unsafe_output_paths_fail(path_text):
    with pytest.raises(DatasetError, match="unsafe output relative_path|control character"):
        DatasetOutputFile(path_text, "dataset", 1, 10, sha("x"), "parquet")


def test_output_record_fact_validation():
    with pytest.raises(DatasetError, match="non-negative integer"):
        DatasetOutputFile("a.parquet", "dataset", True, 10, sha("x"), "parquet")
    with pytest.raises(DatasetError, match="non-negative integer"):
        DatasetOutputFile("a.parquet", "dataset", 1, -5, sha("x"), "parquet")
    with pytest.raises(DatasetError, match="SHA-256"):
        DatasetOutputFile("a.parquet", "dataset", 1, 10, "short", "parquet")


def test_built_at_naive_fails():
    with pytest.raises(DatasetError, match="timezone-aware"):
        build_dataset_manifest(
            base_input(), built_at=datetime(2026, 7, 3, 10, 0),
            status=STATUS_COMPLETE, logical_row_count=2,
        )


def test_dataset_schema_id_mismatch_in_input_fails():
    with pytest.raises(DatasetError, match="dataset_schema_id does not match"):
        dataset_id(base_input(dataset_schema_id=sha("wrong")))


def test_identity_input_requires_model_instances():
    with pytest.raises(DatasetError, match="DatasetIdentityInput"):
        dataset_id({"not": "an input"})


def test_output_files_empty_allowed_in_core():
    manifest = build_dataset_manifest(
        base_input(), built_at=datetime(2026, 7, 3, tzinfo=UTC),
        status=STATUS_COMPLETE, logical_row_count=2, output_files=(),
    )
    assert manifest.output_files == ()
    assert validate_dataset_manifest(serialize_dataset_manifest(manifest)) == manifest


def test_manifest_schema_section_preserves_field_order():
    payload = json.loads(serialize_dataset_manifest(base_manifest()))
    names = [field["name"] for field in payload["schema"]["fields"]]
    assert names == ["ts", "sym", "close"]


# ---------------------------------------------------------------------------
# Atomic manifest writing.
# ---------------------------------------------------------------------------


def test_atomic_write_success(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "manifest.json"
    manifest = base_manifest()
    write_dataset_manifest_atomic(path, manifest)
    assert path.read_bytes() == serialize_dataset_manifest(manifest)
    assert not list(path.parent.glob(f".{path.name}.tmp-*"))


def test_atomic_write_refuses_existing_destination(tmp_path: Path):
    path = tmp_path / "manifest.json"
    write_dataset_manifest_atomic(path, base_manifest())
    with pytest.raises(DatasetError, match="already exists"):
        write_dataset_manifest_atomic(path, base_manifest())
    assert path.read_bytes() == serialize_dataset_manifest(base_manifest())


def test_atomic_write_idempotent_accepts_identical_bytes(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = base_manifest()
    write_dataset_manifest_atomic(path, manifest)
    write_dataset_manifest_atomic(path, manifest, idempotent=True)
    assert path.read_bytes() == serialize_dataset_manifest(manifest)


def test_atomic_write_idempotent_rejects_conflicting_content(tmp_path: Path):
    path = tmp_path / "manifest.json"
    write_dataset_manifest_atomic(path, base_manifest())
    other = build_dataset_manifest(
        base_input(), built_at=datetime(2026, 7, 4, tzinfo=UTC),
        status=STATUS_COMPLETE, logical_row_count=2,
    )
    with pytest.raises(DatasetError, match="different manifest content"):
        write_dataset_manifest_atomic(path, other, idempotent=True)
    assert path.read_bytes() == serialize_dataset_manifest(base_manifest())


def test_atomic_write_injected_replace_failure_leaves_destination_unchanged(tmp_path: Path, monkeypatch):
    """Simulate a replace-stage failure with a pre-existing destination.

    The existence check runs before os.replace, so a failure at the replace
    stage is a TOCTOU race: the destination already exists on disk but the
    check reports otherwise. The writer must fail with a structured error,
    clean its temporary file, and never partially overwrite the existing
    destination.
    """
    path = tmp_path / "manifest.json"
    write_dataset_manifest_atomic(path, base_manifest())
    original = path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("injected failure")

    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr(os, "replace", fail_replace)
    other = build_dataset_manifest(
        base_input(), built_at=datetime(2026, 7, 4, tzinfo=UTC),
        status=STATUS_COMPLETE, logical_row_count=2,
    )
    with pytest.raises(DatasetError, match="atomically replace"):
        write_dataset_manifest_atomic(path, other)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".manifest.json.tmp-*"))


def test_atomic_write_injected_write_failure_cleans_temp(tmp_path: Path, monkeypatch):
    path = tmp_path / "manifest.json"

    def fail_open(*args, **kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(DatasetError, match="temporary manifest"):
        write_dataset_manifest_atomic(path, base_manifest())
    assert not path.exists()
    assert not list(tmp_path.glob(".manifest.json.tmp-*"))
