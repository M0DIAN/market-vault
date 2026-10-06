"""Focused tests for MarketVault Backtest Engine V1."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import cross_day_helpers as cd
from cross_day_dataset_helpers import fixture, tamper
from market_vault.backtest import (
    BACKTEST_ENGINE_VERSION,
    BacktestCosts,
    BacktestError,
    BacktestRule,
    run_backtest,
)
from market_vault.backtest import engine as backtest_engine
from market_vault.backtest.engine import _Candidate, _run_candidates
from market_vault.cross_day_dataset import (
    VerifiedMultiSourceCrossDayDataset,
    join_multi_source_cross_day_dataset,
)
from market_vault.dataset.split_models import ChronologicalSplitSpec


UTC = timezone.utc


def _instant(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def test_non_overlapping_long_flat_metrics_and_drawdown():
    candidates = (
        _Candidate("1" * 64, "US.AAPL", _instant(1), _instant(2), _instant(4), 1.0, 0.10),
        _Candidate("2" * 64, "US.AAPL", _instant(2, 10), _instant(3), _instant(5), 1.0, 0.20),
        _Candidate("3" * 64, "US.AAPL", _instant(4, 10), _instant(5), _instant(6), 1.0, -0.05),
    )
    trades, metrics = _run_candidates(
        candidates,
        rule=BacktestRule("signal", "GT", 0.0),
        costs=BacktestCosts(),
    )

    assert len(trades) == 2
    assert tuple(trade.sample_key for trade in trades) == ("1" * 64, "3" * 64)
    assert metrics.candidate_count == 3
    assert metrics.signal_count == 3
    assert metrics.overlap_skipped_count == 1
    assert metrics.trade_count == 2
    assert metrics.gross_total_return == pytest.approx(0.045)
    assert metrics.total_return == pytest.approx(0.045)
    assert metrics.realized_max_drawdown == pytest.approx(0.05)
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.average_trade_return == pytest.approx(0.025)
    assert metrics.profit_factor == pytest.approx(0.10 / 0.055)
    assert metrics.average_holding_seconds == pytest.approx(1.5 * 86400)
    assert metrics.exposure == pytest.approx(0.75)


def test_trade_identity_requires_lowercase_hex_sample_key():
    from market_vault.backtest import BacktestTrade

    with pytest.raises(BacktestError, match="lowercase hex"):
        BacktestTrade(
            "Z" * 64,
            "US.AAPL",
            _instant(1),
            _instant(2),
            _instant(3),
            1.0,
            0.1,
            0.1,
            1.0,
            1.1,
        )


def test_costs_are_applied_on_entry_and_exit():
    candidate = _Candidate(
        "a" * 64,
        "US.AAPL",
        _instant(1),
        _instant(2),
        _instant(3),
        2.0,
        0.25,
    )
    trades, metrics = _run_candidates(
        (candidate,),
        rule=BacktestRule("signal", "GT", 0.0),
        costs=BacktestCosts(commission_bps=10, slippage_bps=5),
    )
    expected = 1.25 * (1.0 - 0.0015) ** 2 - 1.0
    assert trades[0].net_return == pytest.approx(expected)
    assert metrics.total_return == pytest.approx(expected)
    assert metrics.gross_total_return == pytest.approx(0.25)


def _research_result(tmp_path, *, execution_safe=True):
    if execution_safe:
        label_specs = (
            cd.spec(
                1,
                "forward_open_to_close_return",
                name="forward_open_to_close_return_1d",
            ),
        )
        label_bars = (
            cd.bar(
                "2025-03-04",
                slot=1,
                open=120.0,
                close=150.0,
            ),
        )
    else:
        label_specs = (cd.spec(),)
        label_bars = None

    inputs = fixture(
        tmp_path,
        label_specs=label_specs,
        label_bars=label_bars,
    )
    return join_multi_source_cross_day_dataset(**inputs)


def _forged_verified(path: Path, dataset_id: str):
    value = object.__new__(VerifiedMultiSourceCrossDayDataset)
    object.__setattr__(value, "build_path", path)
    object.__setattr__(value, "dataset_id", dataset_id)
    return value


def test_verified_input_is_reloaded_from_build_path(monkeypatch, tmp_path):
    dataset_id = "a" * 64
    claimed = _forged_verified(tmp_path / ("dataset_id=" + dataset_id), dataset_id)
    fresh = SimpleNamespace(dataset_id=dataset_id)
    calls = []

    def load(path):
        calls.append(path)
        return fresh

    monkeypatch.setattr(
        backtest_engine,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    assert backtest_engine._admit_dataset(claimed) is fresh
    assert calls == [claimed.build_path]


def test_verified_input_rejects_identity_change_after_reload(monkeypatch, tmp_path):
    claimed = _forged_verified(
        tmp_path / ("dataset_id=" + "a" * 64),
        "a" * 64,
    )
    monkeypatch.setattr(
        backtest_engine,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: SimpleNamespace(dataset_id="b" * 64),
    )
    with pytest.raises(BacktestError, match="identity changed"):
        backtest_engine._admit_dataset(claimed)


def test_live_research_dataset_end_to_end_execution_safe_backtest(tmp_path):
    dataset = _research_result(tmp_path)
    result = run_backtest(
        dataset,
        signal_field="ts2_simple_return",
        comparator="GT",
        threshold=0.0,
        return_label="forward_open_to_close_return_1d",
        split="TRAIN",
        commission_bps=10,
        slippage_bps=5,
    )

    assert result.engine_version == BACKTEST_ENGINE_VERSION
    assert result.dataset_id == dataset.dataset_id
    assert len(result.backtest_id) == 64
    assert result.split == "TRAIN"
    assert len(result.trades) == 1
    trade = result.trades[0]
    field_names = tuple(field.name for field in dataset.schema.fields)
    feature_window_close_index = field_names.index("feature_window_close")
    assert trade.signal_time == dataset.rows[0][feature_window_close_index]
    assert trade.signal_time < trade.entry_time < trade.exit_time
    assert trade.gross_return == pytest.approx(0.25)
    assert trade.net_return == pytest.approx(
        1.25 * (1.0 - 0.0015) ** 2 - 1.0
    )
    assert result.metrics.candidate_count == 1
    assert result.metrics.signal_count == 1
    assert result.metrics.trade_count == 1
    assert result.metrics.overlap_skipped_count == 0
    assert result.metrics.realized_max_drawdown == 0.0
    assert result.metrics.win_rate == 1.0
    assert result.metrics.profit_factor is None
    assert result.metrics.exposure == 1.0

    again = run_backtest(
        dataset,
        signal_field="ts2_simple_return",
        comparator="GT",
        threshold=0.0,
        return_label="forward_open_to_close_return_1d",
        split="TRAIN",
        commission_bps=10,
        slippage_bps=5,
    )
    assert again == result


def test_selected_return_label_controls_exit_time_in_multi_label_dataset(tmp_path):
    label_specs = (
        cd.spec(
            1,
            "forward_open_to_close_return",
            name="forward_open_to_close_return_1d",
        ),
        cd.spec(
            2,
            "maximum_favorable_excursion",
            name="maximum_favorable_excursion_2d",
        ),
    )
    label_bars = (
        cd.bar(
            "2025-03-04",
            slot=1,
            open=120.0,
            close=150.0,
            high=160.0,
        ),
        cd.bar(
            "2025-03-05",
            slot=1,
            open=130.0,
            close=140.0,
            high=170.0,
        ),
    )
    schedule = cd.schedule((
        ("2025-03-03", "N"),
        ("2025-03-04", "N"),
        ("2025-03-05", "N"),
    ))
    inputs = fixture(
        tmp_path,
        label_specs=label_specs,
        label_bars=label_bars,
        schedule=schedule,
    )
    inputs["split_spec"] = ChronologicalSplitSpec(
        "market-vault-chronological-split-spec-v1",
        "backtest_multi_label",
        "v1",
        "America/New_York",
        date(2025, 3, 6),
        date(2025, 3, 7),
        date(2025, 3, 8),
        "FEATURE_WINDOW_CLOSE_DATE",
        "ACTUAL_LABEL_END",
        "EXCLUDE",
        "EXCLUDE",
    )
    dataset = join_multi_source_cross_day_dataset(**inputs)
    fields = tuple(field.name for field in dataset.schema.fields)
    row = dict(zip(fields, dataset.rows[0]))
    assert row["actual_label_end_time"] == cd.local("2025-03-05", 9, 40)

    result = run_backtest(
        dataset,
        signal_field="ts2_simple_return",
        comparator="GT",
        threshold=0.0,
        return_label="forward_open_to_close_return_1d",
        split="TRAIN",
    )
    assert len(result.trades) == 1
    assert result.trades[0].exit_time == cd.local("2025-03-04", 9, 40)
    assert result.trades[0].exit_time < row["actual_label_end_time"]


def test_backtest_refuses_anchor_close_forward_return_as_pnl(tmp_path):
    dataset = _research_result(tmp_path, execution_safe=False)
    with pytest.raises(
        BacktestError,
        match="forward_open_to_close_return",
    ):
        run_backtest(
            dataset,
            signal_field="ts2_simple_return",
            comparator="GT",
            threshold=0.0,
            return_label="cd_return_1d",
            split="TRAIN",
        )


def test_backtest_refuses_label_as_signal_and_unissued_clone(tmp_path):
    dataset = _research_result(tmp_path)
    with pytest.raises(BacktestError, match="signal_field"):
        run_backtest(
            dataset,
            signal_field="forward_open_to_close_return_1d",
            comparator="GT",
            threshold=0.0,
            return_label="forward_open_to_close_return_1d",
            split="TRAIN",
        )

    clone = tamper(dataset)
    with pytest.raises(BacktestError, match="unissued or changed"):
        run_backtest(
            clone,
            signal_field="ts2_simple_return",
            comparator="GT",
            threshold=0.0,
            return_label="forward_open_to_close_return_1d",
            split="TRAIN",
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"comparator": "EQ"},
        {"threshold": float("nan")},
        {"commission_bps": -1},
        {"slippage_bps": 10000},
        {"split": "ALL"},
    ],
)
def test_backtest_invalid_configuration_fails_closed(tmp_path, kwargs):
    dataset = _research_result(tmp_path)
    call = dict(
        signal_field="ts2_simple_return",
        comparator="GT",
        threshold=0.0,
        return_label="forward_open_to_close_return_1d",
        split="TRAIN",
        commission_bps=0.0,
        slippage_bps=0.0,
    )
    call.update(kwargs)
    with pytest.raises(BacktestError):
        run_backtest(dataset, **call)
