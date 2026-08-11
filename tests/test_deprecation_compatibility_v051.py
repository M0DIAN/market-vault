"""V0.5.1 regression tests: NumPy generic-timedelta deprecation compatibility.

The pandas keyword Timedelta constructors (``pd.Timedelta(seconds=60)``,
``pd.Timedelta(minutes=1)``, ...) route bare integers through the deprecated
generic NumPy timedelta path, which raises

    DeprecationWarning: The 'generic' unit for NumPy timedelta is deprecated,
    and will raise an error in the future. This includes implicit conversion
    of bare integers (e.g. `+ 1`). Please use a specific unit instead.

MarketVault's public functions now construct Timedeltas with an explicit
value and unit (``pd.Timedelta(int(value), unit="s")``), and the pytest
filterwarnings guard turns the exact target warning into an error. These
tests prove that:

- ``bar_available_at`` accepts both plain Python ``int`` and ``numpy``
  integers and produces identical, warning-free UTC instants;
- ``derive_internal_gap_ranges`` accepts both plain Python ``int`` and
  ``numpy`` integers with identical gap ranges, identities, counts, and
  ordering, and never emits the target warning;
- the non-multiple fail-closed boundary
  (``CanonicalGapArithmeticError``) is unchanged.

Tests call the real public functions only; they never copy their
implementation.
"""

from __future__ import annotations

import datetime
import os
import sys
import warnings
from contextlib import contextmanager
from datetime import date

import numpy as np
import pandas as pd
import pytest

from market_vault.canonical.gaps import derive_internal_gap_ranges, gap_range_id
from market_vault.canonical.models import CanonicalBar, CanonicalGapArithmeticError
from market_vault.normalization import bar_available_at

NY = "America/New_York"
TARGET_WARNING_MESSAGE = "The 'generic' unit for NumPy timedelta is deprecated.*"


@contextmanager
def target_warning_as_error():
    """Turn the exact NumPy generic-timedelta warning into an error."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error",
            message=TARGET_WARNING_MESSAGE,
            category=DeprecationWarning,
        )
        yield


def make_bar(event_time: str) -> CanonicalBar:
    """One minimal canonical bar with a fixed NY market time instant."""
    ts = pd.Timestamp(event_time, tz=NY)
    return CanonicalBar(
        canonical_bar_key=f"key-{ts.strftime('%H%M%S')}",
        canonical_row_version_id="row-v1",
        dataset_kind="MARKET",
        code="US.MU",
        interval="1m",
        adjustment="NONE",
        event_time=ts,
        market_available_at=ts + pd.Timedelta(60, unit="s"),
        archive_available_at=ts + pd.Timedelta(60, unit="s"),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=100,
        extra_fields=(),
        ingestion_run_id="run-a",
        physical_snapshot_hash="snap-a",
        logical_source_rows_hash="rows-a",
        source_schema_version="10.9",
        canonical_builder_version="v1",
        requested_trade_date=date(2026, 7, 1),
        requested_session="ALL",
        market_calendar_date=date(2026, 7, 1),
        session="REGULAR",
        snapshot_file="snapshot.parquet",
    )


def gap_bars() -> tuple[CanonicalBar, ...]:
    """Bars with two internal nominal-interval gaps: 09:30->09:32 and
    09:33->09:35 (each skipping exactly one 60-second bar)."""
    return (
        make_bar("2026-07-01 09:30:00"),
        make_bar("2026-07-01 09:32:00"),
        make_bar("2026-07-01 09:33:00"),
        make_bar("2026-07-01 09:35:00"),
    )


# --- bar_available_at --------------------------------------------------------


def test_bar_available_at_python_int_interval_no_deprecation_warning():
    # TEMPORARY P2-1 rerun-evidence canary: fail only the first GitHub
    # Actions attempt of the Python 3.14 leg so the failed-jobs rerun
    # naturally passes on attempt 2. Remove with the canary PR.
    if (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and sys.version_info[:2] == (3, 14)
    ):
        pytest.fail("P2_PARTIAL_REUSE_RERUN_CANARY_ATTEMPT1")
    market_time = pd.Timestamp("2026-07-01 09:30:00", tz=NY)
    with target_warning_as_error():
        result = bar_available_at(market_time, 60)
    assert result == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")
    assert result.tz is not None
    assert result.utcoffset() == datetime.timedelta(0)


def test_bar_available_at_numpy_int_interval_matches_python_int():
    market_time = pd.Timestamp("2026-07-01 09:30:00", tz=NY)
    with target_warning_as_error():
        py_result = bar_available_at(market_time, 60)
    with target_warning_as_error():
        np_result = bar_available_at(market_time, np.int64(60))
    assert np_result == py_result
    assert np_result == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")


# --- derive_internal_gap_ranges ---------------------------------------------


def test_gap_derivation_python_int_no_deprecation_warning():
    with target_warning_as_error():
        gaps = derive_internal_gap_ranges(gap_bars(), 60)

    assert len(gaps) == 2

    first, second = gaps
    assert first.missing_bar_count == 1
    assert first.missing_from_event_time == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")
    assert first.missing_to_event_time == pd.Timestamp("2026-07-01 13:31:00", tz="UTC")
    assert second.missing_bar_count == 1
    assert second.missing_from_event_time == pd.Timestamp("2026-07-01 13:34:00", tz="UTC")
    assert second.missing_to_event_time == pd.Timestamp("2026-07-01 13:34:00", tz="UTC")

    # Gap IDs are the deterministic versioned identity, recomputable here.
    assert first.gap_id == gap_range_id(
        dataset_kind="MARKET",
        code="US.MU",
        interval="1m",
        adjustment="NONE",
        market_calendar_date=date(2026, 7, 1),
        session="REGULAR",
        previous_event_time=pd.Timestamp("2026-07-01 13:30:00", tz="UTC"),
        next_event_time=pd.Timestamp("2026-07-01 13:32:00", tz="UTC"),
    )
    assert second.gap_id == gap_range_id(
        dataset_kind="MARKET",
        code="US.MU",
        interval="1m",
        adjustment="NONE",
        market_calendar_date=date(2026, 7, 1),
        session="REGULAR",
        previous_event_time=pd.Timestamp("2026-07-01 13:33:00", tz="UTC"),
        next_event_time=pd.Timestamp("2026-07-01 13:35:00", tz="UTC"),
    )

    # Sorting: by group key, then previous event time ascending.
    assert first.previous_event_time < second.previous_event_time
    assert gaps == tuple(sorted(gaps, key=lambda gap: gap.previous_event_time))


def test_gap_derivation_numpy_int_matches_python_int():
    with target_warning_as_error():
        py_gaps = derive_internal_gap_ranges(gap_bars(), 60)
    with target_warning_as_error():
        np_gaps = derive_internal_gap_ranges(gap_bars(), np.int64(60))

    assert np_gaps == py_gaps
    assert len(np_gaps) == len(py_gaps)
    for np_gap, py_gap in zip(np_gaps, py_gaps):
        assert np_gap.gap_id == py_gap.gap_id
        assert np_gap.missing_from_event_time == py_gap.missing_from_event_time
        assert np_gap.missing_to_event_time == py_gap.missing_to_event_time
        assert np_gap.missing_bar_count == py_gap.missing_bar_count
        assert np_gap.previous_event_time == py_gap.previous_event_time
        assert np_gap.next_event_time == py_gap.next_event_time


def test_gap_derivation_non_multiple_fails_closed():
    # 09:30:00 -> 09:31:30 is 90 seconds, not an exact multiple of the
    # 60-second nominal interval: the fail-closed boundary is unchanged.
    bars = (make_bar("2026-07-01 09:30:00"), make_bar("2026-07-01 09:31:30"))
    with target_warning_as_error():
        with pytest.raises(CanonicalGapArithmeticError):
            derive_internal_gap_ranges(bars, 60)
