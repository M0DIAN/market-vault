"""Offline comparison contracts; declared fixture provenance is not market evidence."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys

import pytest

from market_vault.quality.market_data_comparison import (
    SNAPSHOT_SCHEMA_VERSION,
    compare_snapshot_files,
    compare_snapshots,
    json_bytes,
    normalize_scope,
    read_json_file,
)


OPEN = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)


def stamp(minutes):
    return (OPEN + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def bar(slot, **changes):
    return {
        "start": stamp(slot), "end": stamp(slot + 1),
        "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 100,
        **changes,
    }


def snapshot(bars=None, *, slots=5, provider="fixture-left", data_kind="SYNTHETIC"):
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source": {
            "provider": provider, "version": "fixture-v1", "captured_at": "2026-08-04T12:00:00Z",
            "data_kind": data_kind, "upstream_id": None, "upstream_evidence": None,
        },
        "scope": {
            "symbol": "US.SPY", "asset_class": "ETF", "adjustment": "NONE", "session": "RTH",
            "interval": "1m", "currency": "USD", "aggregation": "TRADES_OHLC",
            "volume_basis": "SHARES", "window_start": stamp(0), "window_end": stamp(slots),
        },
        "bars": [bar(slot) for slot in range(slots)] if bars is None else deepcopy(bars),
    }


def tolerances(**changes):
    return {"price_absolute": 0, "price_relative": 0, "volume_absolute": 0, **changes}


@pytest.mark.parametrize("present", [(0, 1, 3, 4), ()], ids=["same-gap", "both-empty"])
def test_shared_missing_slots_remain_in_the_complete_denominator(present):
    left = snapshot([bar(slot) for slot in present])
    right = snapshot([bar(slot) for slot in present], provider="fixture-right")

    report = compare_snapshots(left, right)

    assert report["status"] == "INCOMPLETE"
    assert report["expected_slots"] == 5
    assert report["counts"] == {
        "matched": len(present), "different": 0, "left_only": 0, "right_only": 0,
        "both_missing": 5 - len(present), "blocked": 0,
    }
    assert [row["start"] for row in report["rows"]] == [stamp(slot) for slot in range(5)]
    assert [row["end"] for row in report["rows"]] == [stamp(slot + 1) for slot in range(5)]
    for slot in set(range(5)) - set(present):
        row = report["rows"][slot]
        assert row["status"] == "BOTH_MISSING"
        assert row["left"] == row["right"] == {"state": "MISSING", "row_indices": [], "bar": None}
        assert row["differences"] == {}
    for item in report["inputs"].values():
        assert item["summary"]["declared_grid_coverage"] == {
            "numerator": len(present), "denominator": 5, "ratio": len(present) / 5,
        }
        assert item["summary"]["duplicate_rate"] == {
            "numerator": 0, "denominator": len(present), "ratio": 0 if present else None,
        }
    assert report["market_accuracy_certified"] is False


def test_price_volume_differences_and_both_one_sided_gaps_are_retained_together():
    left = snapshot([bar(0), bar(1, close=104.0), bar(2, volume=0), bar(4)])
    right = snapshot([bar(0), bar(1), bar(2), bar(3)], provider="fixture-right")

    report = compare_snapshots(left, right)

    assert report["status"] == "INCOMPLETE"
    assert report["expected_slots"] == 5
    assert report["counts"] == {
        "matched": 1, "different": 2, "left_only": 1, "right_only": 1,
        "both_missing": 0, "blocked": 0,
    }
    assert sum(report["counts"].values()) == report["expected_slots"]
    assert [row["status"] for row in report["rows"]] == [
        "MATCH", "DIFFERENT", "DIFFERENT", "RIGHT_ONLY", "LEFT_ONLY",
    ]
    price = report["rows"][1]["differences"]["close"]
    assert (price["left"], price["right"], price["signed"], price["absolute"], price["relative"]) == (
        104.0, 100.0, 4.0, 4.0, 0.04,
    )
    assert price["within_tolerance"] is False
    volume = report["rows"][2]["differences"]["volume"]
    assert volume == {"left": 0, "right": 100, "signed": -100, "absolute": 100, "within_tolerance": False}
    assert report["rows"][2]["left"]["state"] == "VALID_UNIQUE"
    assert all(report["rows"][slot]["differences"] == {} for slot in (3, 4))


def test_duplicate_and_invalid_rows_keep_original_indices_and_values():
    rows = [
        bar(0, origin={"fixture": "first duplicate"}),
        bar(0, close=104.0, origin={"fixture": "different duplicate value"}),
        bar(1, close=0),
        bar(2, end=stamp(4)),
        bar(3, start="2026-08-03T13:33:00"),
        bar(6),
        bar(4.5),
        bar(5),
    ]
    left = snapshot(rows, slots=6)
    before = deepcopy(left)

    report = compare_snapshots(left, snapshot(slots=6, provider="fixture-right"))

    assert left == before
    assert report["status"] == "INVALID_INPUT"
    assert report["expected_slots"] == 6
    assert report["counts"] == {
        "matched": 1, "different": 0, "left_only": 0, "right_only": 2,
        "both_missing": 0, "blocked": 3,
    }
    inspected = report["inputs"]["left"]
    assert inspected["summary"] == {
        "input_rows": 8, "valid_unique_slots": 1, "invalid_rows": 5,
        "duplicate_keys": 1, "duplicate_rows": 2, "duplicate_excess_rows": 1,
        "declared_grid_coverage": {"numerator": 1, "denominator": 6, "ratio": 1 / 6},
        "duplicate_rate": {"numerator": 1, "denominator": 8, "ratio": 1 / 8},
    }
    assert inspected["duplicate_keys"] == [{"start": stamp(0), "row_indices": [0, 1], "rows": rows[:2]}]
    assert [item["index"] for item in inspected["invalid_rows"]] == [2, 3, 4, 5, 6]
    assert [item["row"] for item in inspected["invalid_rows"]] == rows[2:7]
    assert all(item["errors"] for item in inspected["invalid_rows"])
    assert report["rows"][0]["left"] == {"state": "DUPLICATE", "row_indices": [0, 1], "bar": None}
    for slot, index in ((1, 2), (2, 3)):
        assert report["rows"][slot]["left"] == {"state": "INVALID", "row_indices": [index], "bar": None}
    assert report["rows"][5]["left"]["bar"] == rows[7]


def test_tolerances_add_absolute_and_right_reference_relative_terms_and_accept_zero_volume():
    left = snapshot([bar(0, open=111, high=111, low=111, close=111, volume=0)], slots=1)
    right = snapshot([bar(0, open=100, high=100, low=100, close=100, volume=1)], slots=1)

    combined = compare_snapshots(left, right, tolerances(price_absolute=1, price_relative=0.1, volume_absolute=1))

    assert combined["status"] == "MATCH"  # 11 == 1 + 10; max(1, 10) would fail.
    assert combined["rows"][0]["differences"]["close"]["relative"] == 0.11
    assert combined["rows"][0]["differences"]["volume"] == {
        "left": 0, "right": 1, "signed": -1, "absolute": 1, "within_tolerance": True,
    }
    right["bars"][0]["volume"] = 0
    forward = compare_snapshots(left, right, tolerances(price_relative=0.1))
    reverse = compare_snapshots(right, left, tolerances(price_relative=0.1))
    assert forward["status"] == "DIFFERENT"  # Reference 100: 11 > 10.
    assert reverse["status"] == "MATCH"  # Reference 111: 11 <= 11.1.
    assert reverse["rows"][0]["differences"]["volume"]["within_tolerance"] is True


@pytest.mark.parametrize("bad", [
    tolerances(price_absolute=-1),
    tolerances(price_relative=float("inf")),
    tolerances(volume_absolute=True),
    tolerances(price_absolute="0.1"),
    tolerances(extra_option=0),
    {"price_absolute": 0},
], ids=["negative", "nonfinite", "boolean", "string", "unknown-field", "missing-field"])
def test_invalid_tolerances_raise_instead_of_becoming_a_comparison_result(bad):
    with pytest.raises(ValueError):
        compare_snapshots(snapshot(), snapshot(), bad)


@pytest.mark.parametrize("field,value", [
    ("currency", "CAD"), ("aggregation", "QUOTE_MIDPOINT_OHLC"), ("volume_basis", "LOTS"),
])
def test_different_declared_bases_refuse_value_comparison(field, value):
    right = snapshot(provider="fixture-right")
    right["scope"][field] = value

    report = compare_snapshots(snapshot(), right)

    assert report["status"] == "NOT_COMPARABLE"
    assert report["scope_differences"] == [field]
    assert report["rows"] == []
    assert report["expected_slots"] is None and report["counts"] is None
    assert report["inputs"]["right"]["scope"][field] == value


@pytest.mark.parametrize("kind,upstreams,evidence,expected", [
    ("SYNTHETIC", ("a", "b"), ("fixture:a", "fixture:b"), "SYNTHETIC"),
    ("OBSERVED", (None, None), (None, None), "UNKNOWN"),
    ("OBSERVED", ("same-feed", "same-feed"), ("fixture:a", "fixture:b"), "SHARED_UPSTREAM"),
    ("OBSERVED", ("a", "b"), ("fixture:a", None), "UNKNOWN"),
    ("OBSERVED", ("a", "b"), ("fixture:a", "fixture:b"), "DECLARED_DISTINCT_UPSTREAM"),
])
def test_source_labels_and_declarations_do_not_certify_market_accuracy(kind, upstreams, evidence, expected):
    left = snapshot(provider="different-name-a", data_kind=kind)
    right = snapshot(provider="different-name-b", data_kind="OBSERVED")
    for payload, upstream, declaration in zip((left, right), upstreams, evidence):
        payload["source"].update(upstream_id=upstream, upstream_evidence=declaration)

    report = compare_snapshots(left, right)

    assert report["status"] == "MATCH"
    assert report["independence"] == {"status": expected, "evidence_scope": "SOURCE_DECLARATIONS_ONLY"}
    assert report["market_accuracy_certified"] is False


@pytest.mark.parametrize("replacement", [
    '"close":100.0,"close":104.0', '"close":NaN', '"close":Infinity',
], ids=["duplicate-key", "nan-literal", "infinity-literal"])
def test_strict_json_rejects_ambiguous_or_nonfinite_file_content(tmp_path, replacement):
    left_path, right_path = tmp_path / "left.json", tmp_path / "right.json"
    malformed = json.dumps(snapshot(), separators=(",", ":")).replace('"close":100.0', replacement, 1)
    left_path.write_text(malformed, encoding="utf-8")
    right_path.write_bytes(json_bytes(snapshot(provider="fixture-right")))
    before = left_path.read_bytes()

    with pytest.raises(ValueError):
        read_json_file(left_path)
    report = compare_snapshot_files(left_path, right_path)

    assert report["status"] == "INVALID_INPUT"
    assert report["inputs"]["left"]["status"] == "INVALID_INPUT"
    assert report["inputs"]["left"]["file_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["expected_slots"] is None and report["counts"] is None
    assert left_path.read_bytes() == before


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf")], ids=["nan", "infinity"])
def test_python_api_rejects_nonfinite_values_without_emitting_nonfinite_json(nonfinite):
    left = snapshot([bar(0, close=nonfinite)], slots=1)

    with pytest.raises(ValueError):
        json_bytes(left)
    report = compare_snapshots(left, snapshot(slots=1))

    assert report["status"] == "INVALID_INPUT"
    assert report["inputs"]["left"]["status"] == "INVALID_INPUT"
    assert json.loads(json_bytes(report))["status"] == "INVALID_INPUT"


def test_missing_files_are_not_confused_with_valid_empty_bar_arrays(tmp_path):
    empty_path = tmp_path / "empty.json"
    empty_path.write_bytes(json_bytes(snapshot([])))

    for absent in (None, tmp_path / "not-present.json"):
        report = compare_snapshot_files(absent, empty_path)
        assert report["status"] == "NOT_RUN"
        assert report["inputs"]["left"]["status"] == "NOT_RUN"
        assert report["inputs"]["right"]["summary"]["input_rows"] == 0
        assert report["expected_slots"] is None and report["counts"] is None
    compared = compare_snapshot_files(empty_path, empty_path)
    assert compared["status"] == "INCOMPLETE"
    assert compared["expected_slots"] == compared["counts"]["both_missing"] == 5


def test_repeated_api_and_file_comparison_is_stable_and_inputs_are_unchanged(tmp_path):
    left, right = snapshot(), snapshot(provider="fixture-right")
    right["bars"][2]["close"] = 101.0
    before = deepcopy((left, right))
    first = compare_snapshots(left, right)
    assert first["status"] == "DIFFERENT"
    assert first["tolerances"] == tolerances()
    assert first == compare_snapshots(deepcopy(left), deepcopy(right))
    assert (left, right) == before
    left_path, right_path = tmp_path / "left.json", tmp_path / "right.json"
    left_bytes, right_bytes = json_bytes(left), json.dumps(right, indent=2).encode("utf-8")
    left_path.write_bytes(left_bytes)
    right_path.write_bytes(right_bytes)
    assert read_json_file(left_path) == left

    from_files = compare_snapshot_files(left_path, right_path)

    assert from_files == compare_snapshot_files(left_path, right_path)
    assert from_files["rows"] == first["rows"]
    for side, encoded in (("left", left_bytes), ("right", right_bytes)):
        assert from_files["inputs"][side]["file_sha256"] == hashlib.sha256(encoded).hexdigest()
        assert from_files["inputs"][side]["content_sha256"] == first["inputs"][side]["content_sha256"]
    assert left_path.read_bytes() == left_bytes
    assert right_path.read_bytes() == right_bytes
    assert json_bytes(first) == json_bytes(compare_snapshots(left, right))


@pytest.mark.parametrize("left_price,right_price", [
    (2**53 + 1, 2**53), (sys.float_info.max, 1e-308),
], ids=["distinct-large-integers", "relative-outside-float-range"])
def test_extreme_finite_values_do_not_overflow_or_match_at_zero_tolerance(left_price, right_price):
    def priced(value):
        return snapshot([bar(0, open=value, high=value, low=value, close=value, volume=0)], slots=1)

    report = compare_snapshots(priced(left_price), priced(right_price))

    assert report["status"] == "DIFFERENT"
    assert report["counts"]["different"] == report["expected_slots"] == 1
    difference = report["rows"][0]["differences"]["close"]
    assert difference["left"] == left_price and difference["right"] == right_price
    assert difference["within_tolerance"] is False
    if isinstance(left_price, int):
        assert difference["absolute"] == difference["signed"] == 1
    else:
        assert difference["relative"] is None
        assert difference["relative_unavailable_reason"] == "OUTSIDE_FLOAT_RANGE"
    assert json.loads(json_bytes(report))["status"] == "DIFFERENT"


def test_scope_requires_explicit_utc_and_a_declared_aligned_window():
    scope = snapshot()["scope"]
    equivalent = {**scope, "window_start": scope["window_start"].replace("Z", "+00:00")}
    assert normalize_scope(equivalent) == scope
    for changes in (
        {"window_start": "2026-08-03T13:30:00"},
        {"window_start": stamp(0.5), "window_end": stamp(5.5)},
    ):
        with pytest.raises(ValueError):
            normalize_scope({**scope, **changes})
