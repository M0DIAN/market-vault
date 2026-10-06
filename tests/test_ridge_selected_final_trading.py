"""Focused tests for validation-selected Ridge permanent TEST trading V1."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from market_vault.research.ridge_selected_final_trading import (
    RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
    RIDGE_SELECTED_FINAL_TRADING_VERSION,
    RidgeSelectedFinalTradingError,
    _evaluate,
    evaluate_ridge_selected_final_trading,
)
from test_ridge_final_trading import _execution_bundle, _final
from test_ridge_trading_threshold_selection import _select


def _forged_threshold(selection, **changes):
    forged = object.__new__(type(selection))
    for field in fields(selection):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(selection, field.name)),
        )
    return forged


def test_validation_selected_threshold_drives_permanent_test(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    threshold, _plan, ridge, claimed, _calls = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(-1.0, 0.0, 1.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )
    final = _final(bundle)

    result = evaluate_ridge_selected_final_trading(
        claimed,
        bundle,
        final,
        threshold,
    )

    assert result.version == RIDGE_SELECTED_FINAL_TRADING_VERSION
    assert result.signal_rule == RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE
    assert result.threshold_selection_id == threshold.threshold_selection_id
    assert result.selected_candidate_id == threshold.selected_candidate_id
    assert result.selected_threshold == threshold.selected_threshold
    assert result.costs == threshold.costs
    assert result.ridge_selection_id == ridge.selection_id
    assert result.walk_forward_id == final.walk_forward_id
    assert result.final_test_id == final.final_test_id
    assert result.model_id == final.model_id
    assert result.dataset_id == bundle.dataset_id
    assert result.feature_names == bundle.feature_names
    assert result.label_name == bundle.label_name
    assert result.selected_alpha == final.alpha
    assert len(result.trading_id) == 64

    expected_signals = sum(
        item.predicted > threshold.selected_threshold
        for item in final.predictions
    )
    assert result.metrics.candidate_count == final.test_count
    assert result.metrics.signal_count == expected_signals
    assert all(
        trade.predicted_return > threshold.selected_threshold
        and trade.selected_threshold == threshold.selected_threshold
        for trade in result.trades
    )


def test_threshold_selection_costs_are_frozen_into_test_economics(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    threshold, *_rest = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(-100.0, -99.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )
    final = _final(bundle)
    claimed = _rest[2]

    result = evaluate_ridge_selected_final_trading(
        claimed,
        bundle,
        final,
        threshold,
    )
    assert result.costs == threshold.costs
    assert result.metrics.signal_count == final.test_count
    assert result.trades

    first = result.trades[0]
    side = 1.0 - threshold.costs.per_side_rate
    expected = (1.0 + first.gross_return) * side * side - 1.0
    assert first.net_return == pytest.approx(expected)


def test_test_targets_change_final_economics_not_selected_threshold_or_model(
    tmp_path, monkeypatch
):
    one = _execution_bundle(test_y_shift=0.0)
    two = _execution_bundle(test_y_shift=100.0)

    threshold_one, *_ = _select(
        tmp_path / "one",
        monkeypatch,
        one,
        thresholds=(-1.0, 0.0, 1.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )
    threshold_two, *_ = _select(
        tmp_path / "two",
        monkeypatch,
        two,
        thresholds=(-1.0, 0.0, 1.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )
    assert threshold_one == threshold_two

    final_one = _final(one)
    final_two = _final(two)
    assert final_one.model_id == final_two.model_id
    assert tuple(item.predicted for item in final_one.predictions) == tuple(
        item.predicted for item in final_two.predictions
    )

    from test_ridge_final_trading import _claimed_verified
    claimed_one = _claimed_verified(tmp_path / "claim-one", one.dataset_id)
    claimed_two = _claimed_verified(tmp_path / "claim-two", two.dataset_id)

    # Reinstall the authority for each exact Experiment bundle immediately
    # before its public TEST evaluation.
    from test_ridge_trading_threshold_selection import _install_authority
    _install_authority(monkeypatch, one)
    left = evaluate_ridge_selected_final_trading(
        claimed_one,
        one,
        final_one,
        threshold_one,
    )
    _install_authority(monkeypatch, two)
    right = evaluate_ridge_selected_final_trading(
        claimed_two,
        two,
        final_two,
        threshold_two,
    )

    assert left.selected_threshold == right.selected_threshold
    assert left.threshold_selection_id == right.threshold_selection_id
    assert left.model_id == right.model_id
    assert left.trading_id != right.trading_id
    assert left.metrics.total_return != right.metrics.total_return


def test_no_trade_validation_threshold_stays_no_trade_on_test_when_predictions_below_it(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    threshold, _plan, _ridge, claimed, _calls = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(1e9, 2e9),
    )
    assert threshold.selected_threshold == 2e9
    final = _final(bundle)

    result = evaluate_ridge_selected_final_trading(
        claimed,
        bundle,
        final,
        threshold,
    )
    assert result.metrics.signal_count == 0
    assert result.metrics.trade_count == 0
    assert result.trades == ()
    assert result.metrics.total_return == 0.0


def test_threshold_selection_must_match_frozen_final_model_schema(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    threshold, _plan, _ridge, claimed, _calls = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(-1.0, 0.0),
    )
    final = _final(bundle)

    forged = _forged_threshold(
        threshold,
        ridge_selection_id="0" * 64,
    )
    with pytest.raises(
        RidgeSelectedFinalTradingError,
        match="identity validation failed",
    ):
        evaluate_ridge_selected_final_trading(
            claimed,
            bundle,
            final,
            forged,
        )


def test_valid_other_selection_schema_is_rejected(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    threshold, _plan, _ridge, claimed, _calls = _select(
        tmp_path / "main",
        monkeypatch,
        bundle,
        thresholds=(-1.0, 0.0),
    )
    final = _final(bundle)

    other = _execution_bundle(dataset_id="b" * 64)
    other_threshold, *_ = _select(
        tmp_path / "other",
        monkeypatch,
        other,
        thresholds=(-1.0, 0.0),
    )

    from test_ridge_trading_threshold_selection import _install_authority
    _install_authority(monkeypatch, bundle)
    with pytest.raises(
        RidgeSelectedFinalTradingError,
        match="differs from frozen final TEST model/schema",
    ):
        evaluate_ridge_selected_final_trading(
            claimed,
            bundle,
            final,
            other_threshold,
        )


def test_result_and_trade_identity_tampering_fail_closed(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    threshold, _plan, _ridge, claimed, _calls = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(-100.0, -99.0),
    )
    final = _final(bundle)
    result = evaluate_ridge_selected_final_trading(
        claimed,
        bundle,
        final,
        threshold,
    )
    assert result.trades

    with pytest.raises(
        RidgeSelectedFinalTradingError,
        match="trading_id differs",
    ):
        replace(result, trading_id="0" * 64)

    first = result.trades[0]
    with pytest.raises(
        RidgeSelectedFinalTradingError,
        match="trade_id differs",
    ):
        replace(first, gross_return=first.gross_return + 1.0)


def test_internal_evaluator_rejects_prediction_not_above_selected_threshold(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    threshold, *_ = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(1e9, 2e9),
    )
    final = _final(bundle)
    result = _evaluate(bundle, final, threshold)
    assert result.trades == ()
