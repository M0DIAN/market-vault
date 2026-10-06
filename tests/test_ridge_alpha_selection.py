"""Focused leakage and determinism tests for Ridge alpha selection V1."""

from __future__ import annotations

from dataclasses import replace

import pytest

from market_vault.research import ridge_selection
from market_vault.research.ridge_baseline import evaluate_ridge_baseline
from market_vault.research.ridge_selection import (
    RIDGE_ALPHA_SELECTION_METRIC,
    RIDGE_ALPHA_SELECTION_VERSION,
    RidgeAlphaSelectionError,
    select_ridge_alpha,
)
from test_ridge_baseline import _plan


def test_selection_uses_aggregate_validation_rmse_and_is_order_independent():
    plan = _plan()
    alphas = (10.0, 0.1, 1.0)

    result = select_ridge_alpha(plan, alphas=alphas)
    expected_reports = tuple(
        evaluate_ridge_baseline(plan, alpha=alpha)
        for alpha in sorted(alphas)
    )
    expected = min(
        expected_reports,
        key=lambda report: (report.rmse, report.alpha),
    )

    assert result.version == RIDGE_ALPHA_SELECTION_VERSION
    assert result.metric == RIDGE_ALPHA_SELECTION_METRIC == "RMSE"
    assert result.walk_forward_id == plan.walk_forward_id
    assert result.dataset_id == plan.dataset_id
    assert result.feature_names == plan.feature_names
    assert result.label_name == plan.label_name
    assert tuple(candidate.alpha for candidate in result.candidates) == (
        0.1,
        1.0,
        10.0,
    )
    assert tuple(candidate.report for candidate in result.candidates) == (
        expected_reports
    )
    assert result.selected_alpha == expected.alpha
    assert result.selected_report == expected
    assert len(result.selection_id) == 64
    assert len({candidate.candidate_id for candidate in result.candidates}) == 3

    reordered = select_ridge_alpha(
        plan,
        alphas=tuple(reversed(alphas)),
    )
    assert reordered == result


def test_exact_rmse_tie_selects_smaller_alpha(monkeypatch):
    plan = _plan()

    def tied(value, *, alpha):
        report = evaluate_ridge_baseline(value, alpha=alpha)
        return replace(
            report,
            mae=1.0,
            rmse=2.0,
            r2=None,
        )

    monkeypatch.setattr(
        ridge_selection,
        "evaluate_ridge_baseline",
        tied,
    )

    result = select_ridge_alpha(
        plan,
        alphas=(10.0, 1.0, 5.0),
    )
    assert result.selected_alpha == 1.0
    assert result.selected_report.rmse == 2.0


def test_held_out_test_count_cannot_change_selection():
    plan = _plan(held_out_test_count=7)
    changed_test = replace(plan, held_out_test_count=999)

    original = select_ridge_alpha(
        plan,
        alphas=(0.1, 1.0, 10.0),
    )
    changed = select_ridge_alpha(
        changed_test,
        alphas=(0.1, 1.0, 10.0),
    )

    assert changed == original


@pytest.mark.parametrize(
    "alphas,match",
    [
        ((), "at least two"),
        ((1.0,), "at least two"),
        ((1.0, 1.0), "unique"),
        ((0.0, 1.0), "strictly positive"),
        ((-1.0, 1.0), "strictly positive"),
        ((True, 1.0), "numeric"),
        ((float("inf"), 1.0), "finite"),
        ("1,2", "iterable of numeric"),
    ],
)
def test_invalid_alpha_candidates_fail_closed(alphas, match):
    with pytest.raises(RidgeAlphaSelectionError, match=match):
        select_ridge_alpha(_plan(), alphas=alphas)


def test_selection_requires_exact_walk_forward_plan():
    with pytest.raises(
        RidgeAlphaSelectionError,
        match="requires WalkForwardPlan",
    ):
        select_ridge_alpha(object(), alphas=(0.1, 1.0))


def test_result_rejects_wrong_selected_candidate():
    result = select_ridge_alpha(
        _plan(),
        alphas=(0.1, 1.0, 10.0),
    )
    wrong = next(
        candidate
        for candidate in result.candidates
        if candidate.alpha != result.selected_alpha
    )
    with pytest.raises(
        RidgeAlphaSelectionError,
        match="differs from RMSE/tie-break rule",
    ):
        replace(
            result,
            selected_alpha=wrong.alpha,
            selected_candidate_id=wrong.candidate_id,
            selected_report=wrong.report,
        )
