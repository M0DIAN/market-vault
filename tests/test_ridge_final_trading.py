"""Focused tests for Ridge Final TEST Trading Evaluation V1."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_vault.backtest.models import BacktestCosts
from market_vault.cross_day_dataset import VerifiedMultiSourceCrossDayDataset
from market_vault.research.experiment import (
    ExperimentDatasetBundle,
    ExperimentSplit,
)
from market_vault.research.labels import (
    forward_open_to_close_return_label,
)
from market_vault.research.ml import (
    MLDatasetBundle,
    MLDatasetSplit,
)
from market_vault.research.ridge_final_test import evaluate_ridge_final_test
from market_vault.research.ridge_final_trading import (
    RIDGE_FINAL_TRADING_SIGNAL_RULE,
    RIDGE_FINAL_TRADING_VERSION,
    RidgeFinalTradingError,
    _evaluate,
    evaluate_ridge_final_trading,
)
from market_vault.research.ridge_selection import select_ridge_alpha
from market_vault.research.walk_forward import build_walk_forward_plan
from test_walk_forward_experiment import FEATURES, _bundle, _time


LABEL = "forward_open_to_close_return_5d"


def _execution_bundle(**kwargs):
    base = _bundle(**kwargs)

    def relabel(split):
        old = split.ml_split
        ml = MLDatasetSplit(
            old.split,
            old.feature_names,
            LABEL,
            "float64",
            old.X,
            old.y,
            old.metadata,
        )
        exp = ExperimentSplit(
            split.split,
            ml,
            split.metadata,
        )
        return ml, exp

    train_ml, train = relabel(base.train)
    validation_ml, validation = relabel(base.validation)
    test_ml, test = relabel(base.test)
    ml_bundle = MLDatasetBundle(
        base.ml_bundle.adapter_version,
        base.dataset_id,
        base.feature_names,
        LABEL,
        "float64",
        train_ml,
        validation_ml,
        test_ml,
    )
    return ExperimentDatasetBundle(
        base.version,
        base.dataset_id,
        base.feature_names,
        LABEL,
        "float64",
        ml_bundle,
        train,
        validation,
        test,
    )


def _final(bundle):
    plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=3,
        validation_periods=2,
        step_periods=2,
    )
    selection = select_ridge_alpha(
        plan,
        alphas=(0.1, 1.0, 10.0),
    )
    return evaluate_ridge_final_test(
        bundle,
        plan,
        selection,
    )


def _claimed_verified(tmp_path: Path, dataset_id: str):
    claimed = object.__new__(VerifiedMultiSourceCrossDayDataset)
    object.__setattr__(
        claimed,
        "build_path",
        tmp_path / ("dataset_id=" + dataset_id),
    )
    object.__setattr__(claimed, "dataset_id", dataset_id)
    return claimed


def test_fixed_positive_prediction_rule_skips_overlapping_test_signal():
    bundle = _execution_bundle(
        crossing_ends={
            (8, "US.AAPL"): _time(10),
        },
    )
    final = _final(bundle)
    assert all(item.predicted > 0.0 for item in final.predictions)

    costs = BacktestCosts(commission_bps=10.0, slippage_bps=5.0)
    result = _evaluate(bundle, final, costs)

    assert result.version == RIDGE_FINAL_TRADING_VERSION
    assert result.signal_rule == RIDGE_FINAL_TRADING_SIGNAL_RULE
    assert result.final_test_id == final.final_test_id
    assert result.model_id == final.model_id
    assert result.dataset_id == bundle.dataset_id
    assert result.label_name == LABEL
    assert len(result.trading_id) == 64

    assert result.metrics.candidate_count == 2
    assert result.metrics.signal_count == 2
    assert result.metrics.overlap_skipped_count == 1
    assert result.metrics.trade_count == 1
    assert len(result.trades) == 1

    trade = result.trades[0]
    assert trade.sample_key == final.predictions[0].sample_key
    assert trade.prediction_id == final.predictions[0].prediction_id
    assert trade.label_value_id == bundle.test.metadata[0].label_value_id
    assert trade.signal_time == _time(8)
    assert trade.exit_time == _time(10)
    assert trade.predicted_return == final.predictions[0].predicted
    assert trade.gross_return == pytest.approx(8.0)

    side = 1.0 - 0.0015
    expected_net = 9.0 * side * side - 1.0
    assert trade.net_return == pytest.approx(expected_net)
    assert result.metrics.gross_total_return == pytest.approx(8.0)
    assert result.metrics.total_return == pytest.approx(expected_net)
    assert result.metrics.realized_max_drawdown == 0.0
    assert result.metrics.win_rate == 1.0
    assert result.metrics.profit_factor is None
    assert result.metrics.average_signal_to_exit_seconds == pytest.approx(
        2.0 * 24.0 * 60.0 * 60.0
    )


def test_test_targets_change_economic_result_not_frozen_model_or_signals():
    one = _execution_bundle(test_y_shift=0.0)
    two = _execution_bundle(test_y_shift=100.0)

    final_one = _final(one)
    final_two = _final(two)

    assert final_one.model_id == final_two.model_id
    assert final_one.alpha == final_two.alpha
    assert final_one.intercept == final_two.intercept
    assert final_one.coefficients == final_two.coefficients
    assert tuple(item.predicted for item in final_one.predictions) == tuple(
        item.predicted for item in final_two.predictions
    )

    left = _evaluate(one, final_one, BacktestCosts())
    right = _evaluate(two, final_two, BacktestCosts())

    assert left.metrics.signal_count == right.metrics.signal_count
    assert left.metrics.trade_count == right.metrics.trade_count
    assert left.trading_id != right.trading_id
    assert left.metrics.total_return != right.metrics.total_return


def test_public_wrapper_reloads_dataset_rebuilds_experiment_and_checks_label(
    tmp_path, monkeypatch
):
    from market_vault.research import trading_authority as authority

    bundle = _execution_bundle()
    final = _final(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)
    spec = forward_open_to_close_return_label(5)
    fresh = SimpleNamespace(
        dataset_id=bundle.dataset_id,
        cross_day_labels=SimpleNamespace(label_specs=(spec,)),
    )
    calls = []

    def load(path):
        calls.append(("load", path))
        return fresh

    def rebuild(dataset, *, label_field, feature_fields):
        calls.append(
            (
                "rebuild",
                dataset,
                label_field,
                feature_fields,
            )
        )
        return bundle

    monkeypatch.setattr(
        authority,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(
        authority,
        "build_experiment_dataset",
        rebuild,
    )

    result = evaluate_ridge_final_trading(
        claimed,
        bundle,
        final,
        commission_bps=1.0,
        slippage_bps=2.0,
    )
    assert result.dataset_id == bundle.dataset_id
    assert calls == [
        ("load", claimed.build_path),
        (
            "rebuild",
            fresh,
            LABEL,
            FEATURES,
        ),
    ]


def test_public_wrapper_rejects_non_execution_safe_label_semantics(
    tmp_path, monkeypatch
):
    from market_vault.research import trading_authority as authority

    bundle = _execution_bundle()
    final = _final(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)
    wrong = SimpleNamespace(
        name=LABEL,
        transform_ref="market_vault.dataset.label_transforms.forward_return:forward_return",
        output=SimpleNamespace(logical_type="float64"),
        input_canonical_fields=("close",),
    )
    fresh = SimpleNamespace(
        dataset_id=bundle.dataset_id,
        cross_day_labels=SimpleNamespace(label_specs=(wrong,)),
    )
    monkeypatch.setattr(
        authority,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: fresh,
    )

    with pytest.raises(
        RidgeFinalTradingError,
        match="execution-safe",
    ):
        evaluate_ridge_final_trading(
            claimed,
            bundle,
            final,
        )


def test_public_wrapper_rejects_rebuilt_experiment_mismatch(
    tmp_path, monkeypatch
):
    from market_vault.research import trading_authority as authority

    bundle = _execution_bundle()
    final = _final(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)
    spec = forward_open_to_close_return_label(5)
    fresh = SimpleNamespace(
        dataset_id=bundle.dataset_id,
        cross_day_labels=SimpleNamespace(label_specs=(spec,)),
    )
    monkeypatch.setattr(
        authority,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: fresh,
    )
    monkeypatch.setattr(
        authority,
        "build_experiment_dataset",
        lambda *args, **kwargs: _execution_bundle(dataset_id="b" * 64),
    )

    with pytest.raises(
        RidgeFinalTradingError,
        match="differs from the verified Research Dataset",
    ):
        evaluate_ridge_final_trading(
            claimed,
            bundle,
            final,
        )


def test_result_and_trade_identity_tampering_fail_closed():
    bundle = _execution_bundle()
    final = _final(bundle)
    result = _evaluate(bundle, final, BacktestCosts())
    assert result.trades

    with pytest.raises(
        RidgeFinalTradingError,
        match="trading_id differs",
    ):
        replace(result, trading_id="0" * 64)

    first = result.trades[0]
    with pytest.raises(
        RidgeFinalTradingError,
        match="trade_id differs",
    ):
        replace(first, gross_return=first.gross_return + 1.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"commission_bps": -1.0},
        {"slippage_bps": 10000.0},
    ],
)
def test_public_cost_configuration_fails_closed(
    tmp_path, monkeypatch, kwargs
):
    from market_vault.research import trading_authority as authority

    bundle = _execution_bundle()
    final = _final(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)
    spec = forward_open_to_close_return_label(5)
    fresh = SimpleNamespace(
        dataset_id=bundle.dataset_id,
        cross_day_labels=SimpleNamespace(label_specs=(spec,)),
    )
    monkeypatch.setattr(
        authority,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: fresh,
    )
    monkeypatch.setattr(
        authority,
        "build_experiment_dataset",
        lambda *args, **kwargs: bundle,
    )

    with pytest.raises(RidgeFinalTradingError):
        evaluate_ridge_final_trading(
            claimed,
            bundle,
            final,
            **kwargs,
        )
