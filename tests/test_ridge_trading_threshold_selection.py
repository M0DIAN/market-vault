"""Focused tests for Ridge trading threshold selection V1."""

from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

import pytest

from market_vault.cross_day_dataset import VerifiedMultiSourceCrossDayDataset
from market_vault.research.labels import forward_open_to_close_return_label
from market_vault.research.ridge_selection import select_ridge_alpha
from market_vault.research.ridge_trading_selection import (
    RIDGE_TRADING_THRESHOLD_SELECTION_METRIC,
    RIDGE_TRADING_THRESHOLD_SELECTION_VERSION,
    RidgeTradingThresholdSelectionError,
    select_ridge_trading_threshold,
)
from market_vault.research.walk_forward import build_walk_forward_plan
from test_ridge_final_trading import LABEL, _claimed_verified, _execution_bundle


ALPHAS = (0.1, 1.0, 10.0)


def _plan_and_selection(bundle):
    plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=3,
        validation_periods=2,
        step_periods=2,
    )
    selection = select_ridge_alpha(plan, alphas=ALPHAS)
    return plan, selection


def _install_authority(monkeypatch, bundle):
    from market_vault.research import trading_authority as authority

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
        calls.append(("rebuild", dataset, label_field, feature_fields))
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
    return calls


def _select(tmp_path, monkeypatch, bundle, *, thresholds=(-1.0, 0.0, 1.0), **costs):
    plan, ridge = _plan_and_selection(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)
    calls = _install_authority(monkeypatch, bundle)
    result = select_ridge_trading_threshold(
        claimed,
        bundle,
        plan,
        ridge,
        thresholds=thresholds,
        **costs,
    )
    return result, plan, ridge, claimed, calls


def test_selection_uses_validation_only_and_test_targets_cannot_change_result(
    tmp_path, monkeypatch
):
    one = _execution_bundle(test_y_shift=0.0)
    two = _execution_bundle(test_y_shift=9999.0)

    plan_one, ridge_one = _plan_and_selection(one)
    plan_two, ridge_two = _plan_and_selection(two)
    assert plan_one == plan_two
    assert ridge_one == ridge_two

    left, *_ = _select(
        tmp_path / "left",
        monkeypatch,
        one,
        thresholds=(-1.0, 0.0, 1.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )
    right, *_ = _select(
        tmp_path / "right",
        monkeypatch,
        two,
        thresholds=(-1.0, 0.0, 1.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )

    assert left == right
    assert left.version == RIDGE_TRADING_THRESHOLD_SELECTION_VERSION
    assert left.metric == RIDGE_TRADING_THRESHOLD_SELECTION_METRIC
    assert left.walk_forward_id == plan_one.walk_forward_id
    assert left.ridge_selection_id == ridge_one.selection_id
    assert left.dataset_id == one.dataset_id
    assert left.label_name == LABEL
    assert left.selected_alpha == ridge_one.selected_alpha
    assert len(left.validation_predictions) == sum(
        fold.validation.row_count for fold in plan_one.folds
    )
    assert all(
        prediction.sample_key
        not in {item.sample_key for item in one.test.metadata}
        for prediction in left.validation_predictions
    )


def test_threshold_order_is_not_semantic_and_candidates_are_sorted(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    one, *_ = _select(
        tmp_path / "one",
        monkeypatch,
        bundle,
        thresholds=(1.0, -1.0, 0.0),
    )
    two, *_ = _select(
        tmp_path / "two",
        monkeypatch,
        bundle,
        thresholds=(0.0, 1.0, -1.0),
    )

    assert one == two
    assert tuple(item.threshold for item in one.candidates) == (-1.0, 0.0, 1.0)
    assert len(one.threshold_selection_id) == 64
    assert len(one.validation_prediction_ids_digest) == 64
    assert all(len(item.candidate_id) == 64 for item in one.candidates)


def test_exact_no_trade_tie_prefers_higher_more_conservative_threshold(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    result, *_ = _select(
        tmp_path,
        monkeypatch,
        bundle,
        thresholds=(1e9, 2e9),
    )
    assert all(item.trade_count == 0 for item in result.candidates)
    assert all(item.total_return == 0.0 for item in result.candidates)
    assert all(item.realized_max_drawdown == 0.0 for item in result.candidates)
    assert result.selected_threshold == 2e9
    assert result.selected_candidate_id == result.candidates[-1].candidate_id


def test_costs_change_selection_identity_and_candidate_economics(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    free, *_ = _select(
        tmp_path / "free",
        monkeypatch,
        bundle,
        thresholds=(-1.0, 0.0),
    )
    costly, *_ = _select(
        tmp_path / "costly",
        monkeypatch,
        bundle,
        thresholds=(-1.0, 0.0),
        commission_bps=10.0,
        slippage_bps=5.0,
    )
    assert free.threshold_selection_id != costly.threshold_selection_id
    assert free.costs != costly.costs
    assert tuple(item.total_return for item in free.candidates) != tuple(
        item.total_return for item in costly.candidates
    )


def _forged_selection(selection):
    forged = object.__new__(type(selection))
    for field in fields(selection):
        object.__setattr__(
            forged,
            field.name,
            (
                "0" * 64
                if field.name == "selection_id"
                else getattr(selection, field.name)
            ),
        )
    return forged


def test_forged_ridge_selection_is_revalidated_before_predictions(
    tmp_path, monkeypatch
):
    bundle = _execution_bundle()
    plan, selection = _plan_and_selection(bundle)
    forged = _forged_selection(selection)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)
    _install_authority(monkeypatch, bundle)

    with pytest.raises(
        RidgeTradingThresholdSelectionError,
        match="identity validation failed",
    ):
        select_ridge_trading_threshold(
            claimed,
            bundle,
            plan,
            forged,
            thresholds=(-1.0, 0.0),
        )


@pytest.mark.parametrize(
    "thresholds,match",
    [
        ((), "at least two"),
        ((1.0,), "at least two"),
        ((1.0, 1.0), "unique"),
        ((True, 1.0), "numeric"),
        ((float("inf"), 1.0), "finite"),
        ("0,1", "iterable"),
    ],
)
def test_invalid_threshold_candidates_fail_before_artifact_io(
    tmp_path, monkeypatch, thresholds, match
):
    bundle = _execution_bundle()
    plan, selection = _plan_and_selection(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)

    from market_vault.research import trading_authority as authority

    monkeypatch.setattr(
        authority,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: pytest.fail("invalid thresholds reached artifact I/O"),
    )

    with pytest.raises(RidgeTradingThresholdSelectionError, match=match):
        select_ridge_trading_threshold(
            claimed,
            bundle,
            plan,
            selection,
            thresholds=thresholds,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"commission_bps": -1.0},
        {"slippage_bps": 10000.0},
    ],
)
def test_invalid_costs_fail_before_artifact_io(
    tmp_path, monkeypatch, kwargs
):
    bundle = _execution_bundle()
    plan, selection = _plan_and_selection(bundle)
    claimed = _claimed_verified(tmp_path, bundle.dataset_id)

    from market_vault.research import trading_authority as authority

    monkeypatch.setattr(
        authority,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: pytest.fail("invalid costs reached artifact I/O"),
    )

    with pytest.raises(RidgeTradingThresholdSelectionError):
        select_ridge_trading_threshold(
            claimed,
            bundle,
            plan,
            selection,
            thresholds=(-1.0, 0.0),
            **kwargs,
        )
