"""Leakage-safe Ridge alpha selection V1 over Walk-Forward validation.

The selector consumes one exact WalkForwardPlan and a caller-declared set of
candidate alpha values.  Each alpha is evaluated by Ridge Baseline V1 over the
same TRAIN -> future VALIDATION folds.  TEST is inaccessible because the input
plan contains development folds only.

V1 deliberately supports one selection metric:

    aggregate validation RMSE (lower is better)

An exact RMSE tie is broken by the smaller alpha.  Candidate order from the
caller is not semantic: alphas are normalized to a strictly increasing tuple
before evaluation and identity construction.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from ..dataset.encoding import encode_identity
from .ridge_baseline import (
    RidgeBaselineReport,
    evaluate_ridge_baseline,
)
from .walk_forward import WalkForwardPlan


RIDGE_ALPHA_SELECTION_VERSION = "market-vault-ridge-alpha-selection-v1"
RIDGE_ALPHA_SELECTION_METRIC = "RMSE"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeAlphaSelectionError(ValueError):
    """Fail-closed Ridge alpha selection V1 error."""


def _alpha(value) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeAlphaSelectionError("alpha must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise RidgeAlphaSelectionError("alpha must be finite")
    if result <= 0.0:
        raise RidgeAlphaSelectionError("alpha must be strictly positive")
    return result


def _alphas(values) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise RidgeAlphaSelectionError(
            "alphas must be an iterable of numeric values"
        )
    try:
        normalized = tuple(_alpha(value) for value in values)
    except TypeError as exc:
        raise RidgeAlphaSelectionError(
            "alphas must be an iterable of numeric values"
        ) from exc
    if len(normalized) < 2:
        raise RidgeAlphaSelectionError(
            "Ridge alpha selection requires at least two candidates"
        )
    if len(set(normalized)) != len(normalized):
        raise RidgeAlphaSelectionError("alpha candidates must be unique")
    return tuple(sorted(normalized))


def _members_digest(prefix: str, members: tuple[str, ...]) -> str:
    framed = "".join(f"{len(member)}:{member}" for member in members)
    return encode_identity(
        prefix,
        {
            "count": len(members),
            "members": framed,
        },
    )


def _scalar_vector_digest(
    prefix: str,
    values: tuple[float, ...],
) -> str:
    member_ids = tuple(
        encode_identity(
            prefix + "-member-v1",
            {
                "index": index,
                "value": value,
            },
        )
        for index, value in enumerate(values)
    )
    return _members_digest(prefix + "-members-v1", member_ids)


def _fold_result_id(fold) -> str:
    return encode_identity(
        "market-vault-ridge-alpha-fold-result-v1",
        {
            "fold_index": fold.fold_index,
            "fold_id": fold.fold_id,
            "train_count": fold.train_count,
            "validation_count": fold.validation_count,
            "alpha": fold.alpha,
            "intercept": fold.intercept,
            "coefficients_digest": _scalar_vector_digest(
                "market-vault-ridge-alpha-fold-coefficients",
                fold.coefficients,
            ),
            "feature_means_digest": _scalar_vector_digest(
                "market-vault-ridge-alpha-fold-means",
                fold.feature_means,
            ),
            "feature_scales_digest": _scalar_vector_digest(
                "market-vault-ridge-alpha-fold-scales",
                fold.feature_scales,
            ),
            "mae": fold.mae,
            "rmse": fold.rmse,
            "r2": fold.r2,
        },
    )


def _candidate_id(report: RidgeBaselineReport) -> str:
    fold_ids = tuple(_fold_result_id(fold) for fold in report.folds)
    return encode_identity(
        "market-vault-ridge-alpha-candidate-v1",
        {
            "ridge_version": report.version,
            "walk_forward_id": report.walk_forward_id,
            "dataset_id": report.dataset_id,
            "label_name": report.label_name,
            "feature_names_digest": _members_digest(
                "market-vault-ridge-alpha-feature-names-v1",
                report.feature_names,
            ),
            "alpha": report.alpha,
            "fold_count": len(report.folds),
            "fold_ids_digest": _members_digest(
                "market-vault-ridge-alpha-fold-ids-v1",
                fold_ids,
            ),
            "validation_sample_count": report.validation_sample_count,
            "mae": report.mae,
            "rmse": report.rmse,
            "r2": report.r2,
        },
    )


@dataclass(frozen=True, slots=True)
class RidgeAlphaCandidate:
    candidate_id: str
    alpha: float
    report: RidgeBaselineReport

    def __post_init__(self) -> None:
        if (
            type(self.candidate_id) is not str
            or _SHA256_RE.fullmatch(self.candidate_id) is None
        ):
            raise RidgeAlphaSelectionError(
                "candidate_id must be a lowercase SHA-256 identity"
            )
        if type(self.report) is not RidgeBaselineReport:
            raise RidgeAlphaSelectionError(
                "candidate report must be RidgeBaselineReport"
            )
        alpha = _alpha(self.alpha)
        object.__setattr__(self, "alpha", alpha)
        if self.report.alpha != alpha:
            raise RidgeAlphaSelectionError(
                "candidate alpha differs from Ridge report alpha"
            )
        if self.candidate_id != _candidate_id(self.report):
            raise RidgeAlphaSelectionError(
                "candidate_id differs from Ridge report content"
            )


@dataclass(frozen=True, slots=True)
class RidgeAlphaSelectionResult:
    version: str
    selection_id: str
    walk_forward_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    metric: str
    candidates: tuple[RidgeAlphaCandidate, ...]
    selected_alpha: float
    selected_candidate_id: str
    selected_report: RidgeBaselineReport

    def __post_init__(self) -> None:
        if self.version != RIDGE_ALPHA_SELECTION_VERSION:
            raise RidgeAlphaSelectionError(
                "unsupported Ridge alpha selection version"
            )
        for name in (
            "selection_id",
            "walk_forward_id",
            "dataset_id",
            "selected_candidate_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                raise RidgeAlphaSelectionError(
                    f"{name} must be a lowercase SHA-256 identity"
                )
        if (
            type(self.feature_names) is not tuple
            or not self.feature_names
            or not all(type(name) is str and name for name in self.feature_names)
            or len(self.feature_names) != len(set(self.feature_names))
        ):
            raise RidgeAlphaSelectionError(
                "feature_names must be a unique non-empty tuple"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise RidgeAlphaSelectionError("label_name must be non-empty")
        if self.metric != RIDGE_ALPHA_SELECTION_METRIC:
            raise RidgeAlphaSelectionError("unsupported alpha selection metric")
        if (
            type(self.candidates) is not tuple
            or len(self.candidates) < 2
            or not all(
                type(candidate) is RidgeAlphaCandidate
                for candidate in self.candidates
            )
        ):
            raise RidgeAlphaSelectionError(
                "candidates must contain at least two RidgeAlphaCandidate values"
            )
        alphas = tuple(candidate.alpha for candidate in self.candidates)
        if alphas != tuple(sorted(set(alphas))):
            raise RidgeAlphaSelectionError(
                "candidate alphas must be unique and increasing"
            )
        selected_alpha = _alpha(self.selected_alpha)
        object.__setattr__(self, "selected_alpha", selected_alpha)

        if type(self.selected_report) is not RidgeBaselineReport:
            raise RidgeAlphaSelectionError(
                "selected_report must be RidgeBaselineReport"
            )
        reports = tuple(candidate.report for candidate in self.candidates)
        if any(
            report.walk_forward_id != self.walk_forward_id
            or report.dataset_id != self.dataset_id
            or report.feature_names != self.feature_names
            or report.label_name != self.label_name
            for report in reports
        ):
            raise RidgeAlphaSelectionError(
                "candidate Ridge reports differ from selection schema"
            )
        selected = min(
            self.candidates,
            key=lambda candidate: (
                candidate.report.rmse,
                candidate.alpha,
            ),
        )
        if (
            self.selected_alpha != selected.alpha
            or self.selected_candidate_id != selected.candidate_id
            or self.selected_report != selected.report
        ):
            raise RidgeAlphaSelectionError(
                "selected Ridge candidate differs from RMSE/tie-break rule"
            )

        expected_id = _selection_id(
            walk_forward_id=self.walk_forward_id,
            candidates=self.candidates,
            selected=selected,
        )
        if self.selection_id != expected_id:
            raise RidgeAlphaSelectionError(
                "selection_id differs from alpha selection content"
            )


def _selection_id(
    *,
    walk_forward_id: str,
    candidates: tuple[RidgeAlphaCandidate, ...],
    selected: RidgeAlphaCandidate,
) -> str:
    return encode_identity(
        RIDGE_ALPHA_SELECTION_VERSION,
        {
            "walk_forward_id": walk_forward_id,
            "metric": RIDGE_ALPHA_SELECTION_METRIC,
            "candidate_count": len(candidates),
            "candidate_ids_digest": _members_digest(
                "market-vault-ridge-alpha-candidate-ids-v1",
                tuple(candidate.candidate_id for candidate in candidates),
            ),
            "selected_alpha": selected.alpha,
            "selected_candidate_id": selected.candidate_id,
        },
    )


def select_ridge_alpha(
    plan: WalkForwardPlan,
    *,
    alphas,
) -> RidgeAlphaSelectionResult:
    """Select one Ridge alpha using aggregate walk-forward validation RMSE."""
    if type(plan) is not WalkForwardPlan:
        raise RidgeAlphaSelectionError(
            "Ridge alpha selection V1 requires WalkForwardPlan"
        )
    normalized = _alphas(alphas)

    candidates = []
    for alpha in normalized:
        report = evaluate_ridge_baseline(plan, alpha=alpha)
        candidates.append(
            RidgeAlphaCandidate(
                _candidate_id(report),
                alpha,
                report,
            )
        )
    candidate_tuple = tuple(candidates)
    selected = min(
        candidate_tuple,
        key=lambda candidate: (
            candidate.report.rmse,
            candidate.alpha,
        ),
    )
    selection_id = _selection_id(
        walk_forward_id=plan.walk_forward_id,
        candidates=candidate_tuple,
        selected=selected,
    )
    return RidgeAlphaSelectionResult(
        RIDGE_ALPHA_SELECTION_VERSION,
        selection_id,
        plan.walk_forward_id,
        plan.dataset_id,
        plan.feature_names,
        plan.label_name,
        RIDGE_ALPHA_SELECTION_METRIC,
        candidate_tuple,
        selected.alpha,
        selected.candidate_id,
        selected.report,
    )
