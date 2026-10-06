"""Focused tests for VALIDATION-selected threshold Final TEST trading."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from market_vault.research.ridge_final_test import evaluate_ridge_final_test
from market_vault.research.ridge_selected_threshold_trading import (
    RIDGE_SELECTED_THRESHOLD_FINAL_SIGNAL_RULE,
    RIDGE_SELECTED_THRESHOLD_FINAL_TRADING_VERSION,
    RidgeSelectedThresholdFinalTrade,
    RidgeSelectedThresholdFinalTradingError,
    _trade_id,
    evaluate_ridge_selected_threshold_final_trading,
)
from market_vault.research.ridge_trading_selection import (
    select_ridge_trading_threshold,
)
from test_ridge_final_trading import _claimed_verified, _execution_bundle
from test_ridge_trading_threshold_selection import (
    _install_authority,
    _plan_and_selection,
)


UTC = timezone.utc


def _threshold_selection(tmp_path, monkeypatch, bundle, thresholds=(-1.0, 0.0, 1.0)):
    plan, ridge = _plan_and_selection(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)
    _install_authority(monkeypatch, bundle)
    selected = select_ridge_trading_threshold(
        claimed,
        bundle,
        plan,
        ridge,
        thresholds=thresholds,
        commission_bps=10.0,
        slippage_bps=5.0,
    )
    final = evaluate_ridge_final_test(bundle, plan, ridge)
    return claimed, plan, ridge, selected, final


def test_validation_selected_threshold_is_applied_once_to_final_test(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    claimed, _, ridge, selected, final = _threshold_selection(
        tmp_path,
        monkeypatch,
        bundle,
    )
    _install_authority(monkeypatch, bundle)

    result = evaluate_ridge_selected_threshold_final_trading(
        claimed,
        bundle,
        final,
        selected,
    )

    assert result.version == RIDGE_SELECTED_THRESHOLD_FINAL_TRADING_VERSION
    assert result.signal_rule == RIDGE_SELECTED_THRESHOLD_FINAL_SIGNAL_RULE
    assert result.threshold_selection_id == selected.threshold_selection_id
    assert result.ridge_selection_id == ridge.selection_id
    assert result.final_test_id == final.final_test_id
    assert result.model_id == final.model_id
    assert result.walk_forward_id == final.walk_forward_id
    assert result.dataset_id == bundle.dataset_id
    assert result.label_name == bundle.label_name
    assert result.selected_alpha == selected.selected_alpha
    assert result.selected_threshold == selected.selected_threshold
    assert result.costs == selected.costs
    assert result.metrics.candidate_count == final.test_count
    assert result.metrics.trade_count == len(result.trades)
    assert all(
        trade.predicted_return > selected.selected_threshold
        for trade in result.trades
    )
    assert all(
        trade.selected_threshold == selected.selected_threshold
        for trade in result.trades
    )
    assert len(result.trading_id) == 64


def test_test_targets_cannot_change_validation_threshold_model_or_signals(
    tmp_path, monkeypatch
):
    left_bundle = _execution_bundle(test_y_shift=0.0)
    right_bundle = _execution_bundle(test_y_shift=100.0)

    left_claimed, left_plan, left_ridge, left_selection, left_final = (
        _threshold_selection(
            tmp_path / "left",
            monkeypatch,
            left_bundle,
        )
    )
    right_claimed, right_plan, right_ridge, right_selection, right_final = (
        _threshold_selection(
            tmp_path / "right",
            monkeypatch,
            right_bundle,
        )
    )

    assert left_plan == right_plan
    assert left_ridge == right_ridge
    assert left_selection == right_selection
    assert left_selection.selected_threshold == right_selection.selected_threshold
    assert left_final.model_id == right_final.model_id
    assert left_final.intercept == right_final.intercept
    assert left_final.coefficients == right_final.coefficients
    assert tuple(item.predicted for item in left_final.predictions) == tuple(
        item.predicted for item in right_final.predictions
    )

    _install_authority(monkeypatch, left_bundle)
    left = evaluate_ridge_selected_threshold_final_trading(
        left_claimed,
        left_bundle,
        left_final,
        left_selection,
    )
    _install_authority(monkeypatch, right_bundle)
    right = evaluate_ridge_selected_threshold_final_trading(
        right_claimed,
        right_bundle,
        right_final,
        right_selection,
    )

    assert tuple(item.sample_key for item in left.trades) == tuple(
        item.sample_key for item in right.trades
    )
    assert left.metrics.signal_count == right.metrics.signal_count
    assert left.metrics.trade_count == right.metrics.trade_count
    assert left.trading_id != right.trading_id


def test_negative_selected_threshold_can_accept_negative_prediction():
    signal = datetime(2026, 1, 1, 15, tzinfo=UTC)
    exit_time = datetime(2026, 1, 2, 15, tzinfo=UTC)
    kwargs = dict(
        prediction_id="1" * 64,
        label_value_id="2" * 64,
        sample_key="3" * 64,
        code="US.AAPL",
        signal_time=signal,
        exit_time=exit_time,
        selected_threshold=-0.01,
        predicted_return=-0.005,
        gross_return=0.10,
        net_return=0.10,
        equity_before=1.0,
        equity_after=1.10,
    )
    trade_id = _trade_id(**kwargs)
    trade = RidgeSelectedThresholdFinalTrade(trade_id=trade_id, **kwargs)
    assert trade.predicted_return < 0.0
    assert trade.predicted_return > trade.selected_threshold

    with pytest.raises(
        RidgeSelectedThresholdFinalTradingError,
        match="exceed selected_threshold",
    ):
        replace(trade, predicted_return=-0.02)


def test_threshold_selection_must_match_final_model_schema(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    claimed, _, _, selected, final = _threshold_selection(
        tmp_path / "primary",
        monkeypatch,
        bundle,
    )

    other_bundle = _execution_bundle(dataset_id="b" * 64)
    other_claimed, _, _, other_selection, _ = _threshold_selection(
        tmp_path / "other",
        monkeypatch,
        other_bundle,
    )
    assert other_claimed.dataset_id != claimed.dataset_id

    _install_authority(monkeypatch, bundle)
    with pytest.raises(
        RidgeSelectedThresholdFinalTradingError,
        match="differs from Final TEST model schema",
    ):
        evaluate_ridge_selected_threshold_final_trading(
            claimed,
            bundle,
            final,
            other_selection,
        )

    # The matching selection remains accepted after the mismatch challenge.
    result = evaluate_ridge_selected_threshold_final_trading(
        claimed,
        bundle,
        final,
        selected,
    )
    assert result.dataset_id == bundle.dataset_id


def test_selected_threshold_result_identity_tampering_fails_closed(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    claimed, _, _, selected, final = _threshold_selection(
        tmp_path,
        monkeypatch,
        bundle,
    )
    _install_authority(monkeypatch, bundle)
    result = evaluate_ridge_selected_threshold_final_trading(
        claimed,
        bundle,
        final,
        selected,
    )

    with pytest.raises(
        RidgeSelectedThresholdFinalTradingError,
        match="trading_id differs",
    ):
        replace(result, trading_id="0" * 64)
