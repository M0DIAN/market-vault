from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, time
from pathlib import Path

import pandas as pd
import pytest

from market_vault.normalization.bars import (
    MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
    normalize_bars,
)
from market_vault.normalization.rth_session_geometry import (
    EXCHANGE_AUTHORITY_CAPTURE_METADATA,
    EXCHANGE_AUTHORITY_REFERENCE,
    EXCHANGE_AUTHORITY_REVIEW_METADATA,
    PROVIDER_PROBE_MANIFEST_SHA256,
    PROVIDER_PROFILE_VERSION,
    RTH_TIMEZONE,
    SPECIAL_RTH_SESSION_GEOMETRIES,
    SPECIAL_SESSION_AUTHORITY_VERSION,
    resolve_rth_session_geometry,
)

EVIDENCE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "evidence"
    / "early_close_rth_geometry_v1"
)
PROBE_MANIFEST_SHA256 = (
    "b82628b3b8810c7717c23af02e531f6af79f0c9409682074a71062088b52535b"
)
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
QUALIFIED_DATES = (date(2025, 11, 28), date(2025, 12, 24))
NORMAL_CONTROL_DATE = date(2025, 12, 26)

SEALED_PROFILES = (
    (date(2025, 11, 28), "1m", 210, "09:31", "13:00"),
    (date(2025, 11, 28), "5m", 42, "09:35", "13:00"),
    (date(2025, 11, 28), "15m", 14, "09:45", "13:00"),
    (date(2025, 11, 28), "30m", 7, "10:00", "13:00"),
    (date(2025, 11, 28), "60m", 4, "10:30", "13:00"),
    (date(2025, 12, 24), "1m", 210, "09:31", "13:00"),
    (date(2025, 12, 24), "5m", 42, "09:35", "13:00"),
    (date(2025, 12, 24), "15m", 14, "09:45", "13:00"),
    (date(2025, 12, 24), "30m", 7, "10:00", "13:00"),
    (date(2025, 12, 24), "60m", 4, "10:30", "13:00"),
    (date(2025, 12, 26), "1m", 390, "09:31", "16:00"),
    (date(2025, 12, 26), "5m", 78, "09:35", "16:00"),
    (date(2025, 12, 26), "15m", 26, "09:45", "16:00"),
    (date(2025, 12, 26), "30m", 13, "10:00", "16:00"),
    (date(2025, 12, 26), "60m", 7, "10:30", "16:00"),
)


def _load_evidence(trade_date: date, interval: str) -> dict[str, object]:
    path = EVIDENCE_ROOT / f"{trade_date.isoformat()}_US.SPY_RTH_{interval}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _sealed_bytes(path: Path) -> bytes:
    # Git may materialize LF text blobs as CRLF on Windows worktrees.
    return path.read_bytes().replace(b"\r\n", b"\n")


def _raw_frame(time_keys: list[str], code: str = "US.SPY") -> pd.DataFrame:
    count = len(time_keys)
    return pd.DataFrame(
        {
            "code": [code] * count,
            "time_key": time_keys,
            "open": [100.0 + value for value in range(count)],
            "high": [101.0 + value for value in range(count)],
            "low": [99.0 + value for value in range(count)],
            "close": [100.5 + value for value in range(count)],
            "volume": [1000 + value for value in range(count)],
        }
    )


def _normalize(
    frame: pd.DataFrame,
    *,
    trade_date: date,
    interval: str,
    session: str = "RTH",
    schema: str = MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA,
) -> pd.DataFrame:
    return normalize_bars(
        frame,
        requested_trade_date=trade_date,
        interval=interval,
        requested_session=session,
        adjustment="NONE",
        source="moomoo",
        source_schema_version=schema,
        run_id="early-close-rth-v1-test",
    )


def _rth_provider_sequence(
    trade_date: date, interval: str, *, close_clock: str
) -> list[str]:
    minutes = INTERVAL_MINUTES[interval]
    market_open = pd.Timestamp(
        f"{trade_date.isoformat()} 09:30:00", tz=RTH_TIMEZONE
    )
    market_close = pd.Timestamp(
        f"{trade_date.isoformat()} {close_clock}:00", tz=RTH_TIMEZONE
    )
    endpoints = list(
        pd.date_range(
            market_open + pd.Timedelta(minutes, unit="m"),
            market_close,
            freq=f"{minutes}min",
        )
    )
    if not endpoints or endpoints[-1] != market_close:
        endpoints.append(market_close)
    return [value.strftime("%Y-%m-%d %H:%M:%S") for value in endpoints]


def _expected_canonical_starts(
    trade_date: date, interval: str, *, count: int
) -> list[pd.Timestamp]:
    return list(
        pd.date_range(
            pd.Timestamp(f"{trade_date.isoformat()} 09:30:00", tz=RTH_TIMEZONE),
            periods=count,
            freq=f"{INTERVAL_MINUTES[interval]}min",
        )
    )


def test_sealed_evidence_hashes_remain_exact() -> None:
    manifest_path = EVIDENCE_ROOT / "PROBE_MANIFEST.json"
    manifest_bytes = _sealed_bytes(manifest_path)
    assert hashlib.sha256(manifest_bytes).hexdigest() == PROBE_MANIFEST_SHA256
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    hashes = manifest["individual_evidence_sha256"]
    assert len(hashes) == 15
    assert all(
        hashlib.sha256(_sealed_bytes(EVIDENCE_ROOT / name)).hexdigest() == digest
        for name, digest in hashes.items()
    )


@pytest.mark.parametrize(
    ("trade_date", "interval", "expected_rows", "expected_first", "expected_last"),
    SEALED_PROFILES,
)
def test_sealed_rth_profiles_normalize_to_exact_canonical_starts(
    trade_date: date,
    interval: str,
    expected_rows: int,
    expected_first: str,
    expected_last: str,
) -> None:
    evidence = _load_evidence(trade_date, interval)
    time_keys = list(evidence["full_ordered_time_key_sequence"])
    original = _raw_frame(time_keys)
    original_copy = original.copy(deep=True)

    curated = _normalize(original, trade_date=trade_date, interval=interval)

    pd.testing.assert_frame_equal(original, original_copy)
    assert evidence["row_count"] == expected_rows
    assert time_keys[0].endswith(f"{expected_first}:00")
    assert time_keys[-1].endswith(f"{expected_last}:00")
    assert curated["time_key"].tolist() == time_keys
    assert curated["time_market"].tolist() == _expected_canonical_starts(
        trade_date, interval, count=expected_rows
    )
    assert curated["session"].value_counts().to_dict() == {
        "REGULAR": expected_rows
    }


def test_early_close_60m_sequence_is_the_sealed_provider_sequence() -> None:
    for trade_date in QUALIFIED_DATES:
        evidence = _load_evidence(trade_date, "60m")
        assert [
            value[-8:-3]
            for value in evidence["full_ordered_time_key_sequence"]
        ] == ["10:30", "11:30", "12:30", "13:00"]


def test_special_session_table_is_an_immutable_exact_override_allowlist() -> None:
    assert tuple(item.trade_date for item in SPECIAL_RTH_SESSION_GEOMETRIES) == (
        date(2025, 11, 28),
        date(2025, 12, 24),
    )
    assert NORMAL_CONTROL_DATE not in {
        item.trade_date for item in SPECIAL_RTH_SESSION_GEOMETRIES
    }
    assert all(
        item.authority_version == SPECIAL_SESSION_AUTHORITY_VERSION
        for item in SPECIAL_RTH_SESSION_GEOMETRIES
    )
    with pytest.raises(FrozenInstanceError):
        setattr(SPECIAL_RTH_SESSION_GEOMETRIES[0], "close_time", time(14, 0))


def test_special_entries_bind_deterministic_two_authority_metadata() -> None:
    for entry in SPECIAL_RTH_SESSION_GEOMETRIES:
        assert entry.authority_reference == EXCHANGE_AUTHORITY_REFERENCE
        assert (
            entry.authority_capture_metadata
            == EXCHANGE_AUTHORITY_CAPTURE_METADATA
        )
        assert entry.authority_review_metadata == (
            EXCHANGE_AUTHORITY_REVIEW_METADATA
        )
        assert entry.provider_profile_version == PROVIDER_PROFILE_VERSION
        assert entry.provider_probe_manifest_sha256 == PROBE_MANIFEST_SHA256
        assert entry.provider_probe_manifest_sha256 == PROVIDER_PROBE_MANIFEST_SHA256


def test_absent_normal_profile_does_not_claim_special_authority() -> None:
    geometry = resolve_rth_session_geometry(date(2026, 8, 20))
    assert geometry.classification == "NORMAL"
    assert geometry.authority_capture_metadata is None
    assert geometry.authority_review_metadata is None
    assert geometry.provider_profile_version is None
    assert geometry.provider_probe_manifest_sha256 is None


@pytest.mark.parametrize("trade_date", QUALIFIED_DATES)
def test_qualified_special_dates_resolve_with_two_authority_chain(
    trade_date: date,
) -> None:
    geometry = resolve_rth_session_geometry(trade_date)
    assert geometry.classification == "EARLY_CLOSE"
    assert geometry.authority_capture_metadata == (
        EXCHANGE_AUTHORITY_CAPTURE_METADATA
    )
    assert geometry.authority_review_metadata == (
        EXCHANGE_AUTHORITY_REVIEW_METADATA
    )
    assert geometry.provider_profile_version == PROVIDER_PROFILE_VERSION
    assert geometry.provider_probe_manifest_sha256 == PROBE_MANIFEST_SHA256


@pytest.mark.parametrize("interval", INTERVAL_MINUTES)
def test_absent_ordinary_date_uses_unchanged_normal_profile(interval: str) -> None:
    trade_date = date(2026, 8, 20)
    sequence = _rth_provider_sequence(trade_date, interval, close_clock="16:00")
    curated = _normalize(
        _raw_frame(sequence), trade_date=trade_date, interval=interval
    )
    expected_rows = {"1m": 390, "5m": 78, "15m": 26, "30m": 13, "60m": 7}
    assert len(curated) == expected_rows[interval]
    assert curated["time_market"].tolist() == _expected_canonical_starts(
        trade_date, interval, count=expected_rows[interval]
    )


@pytest.mark.parametrize("interval", INTERVAL_MINUTES)
def test_unlisted_early_close_shape_fails_against_normal_profile(interval: str) -> None:
    trade_date = date(2025, 7, 3)
    sequence = _rth_provider_sequence(trade_date, interval, close_clock="13:00")
    with pytest.raises(ValueError, match="geometry mismatch"):
        _normalize(_raw_frame(sequence), trade_date=trade_date, interval=interval)


@pytest.mark.parametrize(
    "mutation",
    ["wrong-final", "missing-final", "middle-gap", "extra-after-close"],
)
def test_listed_special_date_rejects_any_sequence_mismatch(mutation: str) -> None:
    trade_date = QUALIFIED_DATES[0]
    sequence = list(
        _load_evidence(trade_date, "1m")["full_ordered_time_key_sequence"]
    )
    if mutation == "wrong-final":
        sequence[-1] = f"{trade_date.isoformat()} 13:01:00"
    elif mutation == "missing-final":
        sequence.pop()
    elif mutation == "middle-gap":
        sequence.pop(60)
    else:
        sequence.append(f"{trade_date.isoformat()} 13:01:00")
    with pytest.raises(ValueError, match="geometry mismatch"):
        _normalize(_raw_frame(sequence), trade_date=trade_date, interval="1m")


@pytest.mark.parametrize(
    "mutation", ["continuous-prefix", "missing-final", "middle-gap"]
)
def test_partial_normal_day_is_rejected(mutation: str) -> None:
    trade_date = date(2026, 8, 20)
    sequence = _rth_provider_sequence(trade_date, "1m", close_clock="16:00")
    if mutation == "continuous-prefix":
        sequence = sequence[:210]
    elif mutation == "missing-final":
        sequence.pop()
    else:
        sequence.pop(60)
    with pytest.raises(ValueError, match="geometry mismatch"):
        _normalize(_raw_frame(sequence), trade_date=trade_date, interval="1m")


def test_duplicate_and_nonmonotonic_special_endpoints_are_rejected() -> None:
    trade_date = QUALIFIED_DATES[0]
    sequence = list(
        _load_evidence(trade_date, "1m")["full_ordered_time_key_sequence"]
    )
    duplicate = sequence.copy()
    duplicate[10] = duplicate[9]
    with pytest.raises(ValueError, match="duplicate"):
        _normalize(_raw_frame(duplicate), trade_date=trade_date, interval="1m")

    nonmonotonic = sequence.copy()
    nonmonotonic[10], nonmonotonic[11] = nonmonotonic[11], nonmonotonic[10]
    with pytest.raises(ValueError, match="non-monotonic"):
        _normalize(_raw_frame(nonmonotonic), trade_date=trade_date, interval="1m")


def test_malformed_conflicting_and_unsupported_authority_fails_closed() -> None:
    valid = SPECIAL_RTH_SESSION_GEOMETRIES[0]
    malformed = replace(valid, timezone="UTC")
    with pytest.raises(ValueError, match="Malformed"):
        resolve_rth_session_geometry(valid.trade_date, authorities=(malformed,))

    conflicting = replace(valid, authority_reference="conflicting-authority")
    with pytest.raises(ValueError, match="Conflicting"):
        resolve_rth_session_geometry(
            valid.trade_date, authorities=(valid, conflicting)
        )

    unsupported = replace(valid, close_time=time(14, 0))
    with pytest.raises(ValueError, match="Unsupported"):
        resolve_rth_session_geometry(valid.trade_date, authorities=(unsupported,))


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ({"authority_reference": ""}, "exchange authority reference"),
        ({"provider_profile_version": None}, "provider profile version"),
        (
            {"provider_profile_version": "unknown-profile"},
            "provider profile version",
        ),
        ({"provider_probe_manifest_sha256": None}, "provider probe manifest seal"),
        (
            {"provider_probe_manifest_sha256": "0" * 64},
            "provider probe manifest seal",
        ),
        ({"authority_capture_metadata": None}, "authority capture metadata"),
        ({"authority_review_metadata": None}, "authority review metadata"),
    ],
)
def test_incomplete_or_unknown_two_authority_identity_fails_closed(
    replacement: dict[str, object], message: str
) -> None:
    valid = SPECIAL_RTH_SESSION_GEOMETRIES[0]
    invalid = replace(valid, **replacement)
    with pytest.raises(ValueError, match=message):
        resolve_rth_session_geometry(valid.trade_date, authorities=(invalid,))


def test_session_all_geometry_does_not_use_the_rth_override() -> None:
    trade_date = QUALIFIED_DATES[0]
    clocks = [
        *(f"{hour:02d}:00" for hour in range(0, 10)),
        "09:30",
        "10:30",
        "11:30",
        "12:30",
        "13:30",
        "14:30",
        "15:30",
        *(f"{hour:02d}:00" for hour in range(16, 24)),
    ]
    sequence = [f"{trade_date.isoformat()} {clock}:00" for clock in clocks]
    curated = _normalize(
        _raw_frame(sequence),
        trade_date=trade_date,
        interval="60m",
        session="ALL",
    )
    assert curated["time_key"].tolist() == sequence
    assert curated["time_market"].tolist() == [
        pd.Timestamp(value, tz=RTH_TIMEZONE) for value in sequence
    ]


def test_legacy_109_keeps_provider_labels_on_a_qualified_date() -> None:
    trade_date = QUALIFIED_DATES[0]
    sequence = list(
        _load_evidence(trade_date, "1m")["full_ordered_time_key_sequence"]
    )
    original = _raw_frame(sequence)
    original_copy = original.copy(deep=True)
    curated = _normalize(
        original, trade_date=trade_date, interval="1m", schema="10.9"
    )
    pd.testing.assert_frame_equal(original, original_copy)
    assert curated["time_key"].tolist() == sequence
    assert curated["time_market"].tolist() == [
        pd.Timestamp(value, tz=RTH_TIMEZONE) for value in sequence
    ]
