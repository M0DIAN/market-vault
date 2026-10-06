"""Focused tests for read-only final Ridge research evaluation V1."""

from __future__ import annotations

from dataclasses import replace

import pytest

from market_vault.research.ridge_final_evaluation import (
    RIDGE_FINAL_EVALUATION_VERSION,
    RidgeFinalEvaluationError,
    compare_ridge_final_trading,
)
from market_vault.research.ridge_final_trading import (
    evaluate_ridge_final_trading,
)
from market_vault.research.ridge_selected_final_trading import (
    evaluate_ridge_selected_final_trading,
)
from test_ridge_final_trading import _execution_bundle, _final
from test_ridge_trading_threshold_selection import (
    _install_authority,
    _select,
)


def _results(tmp_path, monkeypatch, *, costs=(10.0, 5.0)):
    bundle = _execution_bundle()
    threshold, _plan, _ridge, claimed, _calls = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(-1.0, 0.0, 1.0),
        commission_bps=costs[0],
        slippage_bps=costs[1],
    )
    final = _final(bundle)

    _install_authority(monkeypatch, bundle)
    fixed = evaluate_ridge_final_trading(
        claimed,
        bundle,
        final,
        commission_bps=costs[0],
        slippage_bps=costs[1],
    )

    _install_authority(monkeypatch, bundle)
    selected = evaluate_ridge_selected_final_trading(
        claimed,
        bundle,
        final,
        threshold,
    )
    return bundle, final, threshold, fixed, selected


def test_report_compares_same_frozen_test_without_making_a_decision(
    tmp_path, monkeypatch
):
    _bundle, final, threshold, fixed, selected = _results(
        tmp_path,
        monkeypatch,
    )
    report = compare_ridge_final_trading(
        final,
        fixed,
        threshold,
        selected,
    )

    assert report.version == RIDGE_FINAL_EVALUATION_VERSION
    assert len(report.report_id) == 64
    assert report.final_test_id == final.final_test_id
    assert report.model_id == final.model_id
    assert report.ridge_selection_id == final.selection_id
    assert report.walk_forward_id == final.walk_forward_id
    assert report.dataset_id == final.dataset_id
    assert report.feature_names == final.feature_names
    assert report.label_name == final.label_name
    assert report.selected_alpha == final.alpha
    assert report.test_count == final.test_count
    assert report.test_mae == final.mae
    assert report.test_rmse == final.rmse
    assert report.test_r2 == final.r2

    assert report.threshold_selection_id == (
        threshold.threshold_selection_id
    )
    assert report.selected_candidate_id == threshold.selected_candidate_id
    assert report.selected_threshold == threshold.selected_threshold
    assert report.costs == threshold.costs

    assert report.fixed_trading_id == fixed.trading_id
    assert report.selected_trading_id == selected.trading_id
    assert report.fixed_metrics == fixed.metrics
    assert report.selected_metrics == selected.metrics

    delta = report.delta
    assert delta.signal_count == (
        selected.metrics.signal_count - fixed.metrics.signal_count
    )
    assert delta.overlap_skipped_count == (
        selected.metrics.overlap_skipped_count
        - fixed.metrics.overlap_skipped_count
    )
    assert delta.trade_count == (
        selected.metrics.trade_count - fixed.metrics.trade_count
    )
    assert delta.gross_total_return == pytest.approx(
        selected.metrics.gross_total_return
        - fixed.metrics.gross_total_return
    )
    assert delta.total_return == pytest.approx(
        selected.metrics.total_return - fixed.metrics.total_return
    )
    assert delta.realized_max_drawdown == pytest.approx(
        selected.metrics.realized_max_drawdown
        - fixed.metrics.realized_max_drawdown
    )
    assert delta.win_rate == pytest.approx(
        selected.metrics.win_rate - fixed.metrics.win_rate
    )
    assert delta.average_trade_return == pytest.approx(
        selected.metrics.average_trade_return
        - fixed.metrics.average_trade_return
    )
    assert delta.average_signal_to_exit_seconds == pytest.approx(
        selected.metrics.average_signal_to_exit_seconds
        - fixed.metrics.average_signal_to_exit_seconds
    )
    if (
        fixed.metrics.profit_factor is None
        or selected.metrics.profit_factor is None
    ):
        assert delta.profit_factor is None
    else:
        assert delta.profit_factor == pytest.approx(
            selected.metrics.profit_factor - fixed.metrics.profit_factor
        )

    # M11 is reporting-only. TEST comparison is never another selection gate.
    assert not hasattr(report, "winner")
    assert not hasattr(report, "decision")
    assert not hasattr(report, "recommended_threshold")


def test_comparison_requires_identical_frozen_costs(
    tmp_path, monkeypatch
):
    bundle, final, threshold, _fixed, selected = _results(
        tmp_path,
        monkeypatch,
        costs=(10.0, 5.0),
    )
    _install_authority(monkeypatch, bundle)
    from test_ridge_final_trading import _claimed_verified
    claimed = _claimed_verified(tmp_path / "fixed-zero", bundle.dataset_id)
    fixed_other_cost = evaluate_ridge_final_trading(
        claimed,
        bundle,
        final,
        commission_bps=0.0,
        slippage_bps=0.0,
    )

    with pytest.raises(
        RidgeFinalEvaluationError,
        match="identical frozen costs",
    ):
        compare_ridge_final_trading(
            final,
            fixed_other_cost,
            threshold,
            selected,
        )


def test_other_valid_threshold_selection_is_rejected(
    tmp_path, monkeypatch
):
    _bundle, final, _threshold, fixed, selected = _results(
        tmp_path / "main",
        monkeypatch,
    )

    other = _execution_bundle(dataset_id="b" * 64)
    other_threshold, *_ = _select(
        tmp_path / "other",
        monkeypatch,
        other,
        thresholds=(-1.0, 0.0, 1.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )

    with pytest.raises(
        RidgeFinalEvaluationError,
        match="threshold selection differs from frozen final TEST",
    ):
        compare_ridge_final_trading(
            final,
            fixed,
            other_threshold,
            selected,
        )


def test_report_identity_tampering_fails_closed(
    tmp_path, monkeypatch
):
    _bundle, final, threshold, fixed, selected = _results(
        tmp_path,
        monkeypatch,
    )
    report = compare_ridge_final_trading(
        final,
        fixed,
        threshold,
        selected,
    )

    with pytest.raises(
        RidgeFinalEvaluationError,
        match="report_id differs",
    ):
        replace(report, report_id="0" * 64)

    with pytest.raises(
        RidgeFinalEvaluationError,
        match="reported deltas differ",
    ):
        replace(
            report,
            delta=replace(
                report.delta,
                total_return=report.delta.total_return + 1.0,
            ),
        )


def test_input_identity_tampering_is_revalidated(
    tmp_path, monkeypatch
):
    _bundle, final, threshold, fixed, selected = _results(
        tmp_path,
        monkeypatch,
    )

    with pytest.raises(
        RidgeFinalEvaluationError,
        match="final TEST identity validation failed",
    ):
        forged_final = object.__new__(type(final))
        for field in final.__dataclass_fields__:
            object.__setattr__(
                forged_final,
                field,
                (
                    "0" * 64
                    if field == "final_test_id"
                    else getattr(final, field)
                ),
            )
        compare_ridge_final_trading(
            forged_final,
            fixed,
            threshold,
            selected,
        )
