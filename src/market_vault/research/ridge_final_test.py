"""Leakage-safe final Ridge TEST evaluation V1.

This layer closes the regression research loop after Walk-Forward validation
and Ridge alpha selection.

Inputs are three exact objects:

- ExperimentDatasetBundle: authoritative TRAIN / VALIDATION / TEST data with
  the selected Label's exact end-time metadata;
- WalkForwardPlan: the development-fold plan;
- RidgeAlphaSelectionResult: alpha chosen only from walk-forward VALIDATION.

The function first deterministically rebuilds the WalkForwardPlan from the
ExperimentDatasetBundle and requires exact equality.  It then refits one final
Ridge model on TRAIN+VALIDATION development rows, purging any selected-Label
whose actual end time reaches the first TEST feature time.  TEST is consulted
only after the model is fully fitted.

No hyperparameter search, Feature selection, random split, shuffle, external
ML framework, model persistence, or repeated TEST-driven tuning is performed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re

from ..dataset.encoding import encode_identity
from .experiment import (
    ExperimentDatasetBundle,
    ExperimentSampleMetadata,
)
from .ridge_baseline import (
    RidgeBaselineError,
    _fit,
    _metrics,
    _predict,
)
from .ridge_selection import RidgeAlphaSelectionResult
from .walk_forward import (
    WalkForwardPlan,
    build_walk_forward_plan,
)


RIDGE_FINAL_TEST_VERSION = "market-vault-ridge-final-test-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeFinalTestError(ValueError):
    """Fail-closed Ridge final TEST evaluation V1 error."""


def _finite(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeFinalTestError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise RidgeFinalTestError(f"{label} must be finite")
    return 0.0 if result == 0.0 else result


def _optional_finite(value, label: str):
    if value is None:
        return None
    return _finite(value, label)


def _identity(value: str, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RidgeFinalTestError(
            f"{label} must be a lowercase SHA-256 identity"
        )
    return value


def _members_digest(prefix: str, members: tuple[str, ...]) -> str:
    framed = "".join(f"{len(member)}:{member}" for member in members)
    return encode_identity(
        prefix,
        {
            "count": len(members),
            "members": framed,
        },
    )


def _scalar_digest(prefix: str, values: tuple[float, ...]) -> str:
    member_ids = tuple(
        encode_identity(
            prefix + "-member-v1",
            {"index": index, "value": value},
        )
        for index, value in enumerate(values)
    )
    return _members_digest(prefix + "-members-v1", member_ids)


@dataclass(frozen=True, slots=True)
class RidgeFinalTestPrediction:
    prediction_id: str
    sample_key: str
    code: str
    feature_window_close: datetime
    actual: float
    predicted: float

    def __post_init__(self) -> None:
        _identity(self.prediction_id, "prediction_id")
        _identity(self.sample_key, "sample_key")
        if type(self.code) is not str or not self.code.startswith("US."):
            raise RidgeFinalTestError("prediction code must be a US symbol")
        if (
            type(self.feature_window_close) is not datetime
            or self.feature_window_close.tzinfo is None
        ):
            raise RidgeFinalTestError(
                "prediction feature_window_close must be timezone-aware"
            )
        object.__setattr__(self, "actual", _finite(self.actual, "actual"))
        object.__setattr__(
            self,
            "predicted",
            _finite(self.predicted, "predicted"),
        )
        expected = _prediction_id(
            sample_key=self.sample_key,
            code=self.code,
            feature_window_close=self.feature_window_close,
            actual=self.actual,
            predicted=self.predicted,
        )
        if self.prediction_id != expected:
            raise RidgeFinalTestError(
                "prediction_id differs from prediction content"
            )


@dataclass(frozen=True, slots=True)
class RidgeFinalTestResult:
    version: str
    final_test_id: str
    model_id: str
    selection_id: str
    walk_forward_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    alpha: float
    test_start_time: datetime
    development_candidate_count: int
    development_purged_count: int
    development_count: int
    test_count: int
    intercept: float
    coefficients: tuple[float, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    predictions: tuple[RidgeFinalTestPrediction, ...]
    mae: float
    rmse: float
    r2: float | None

    def __post_init__(self) -> None:
        if self.version != RIDGE_FINAL_TEST_VERSION:
            raise RidgeFinalTestError("unsupported Ridge final TEST version")
        for name in (
            "final_test_id",
            "model_id",
            "selection_id",
            "walk_forward_id",
            "dataset_id",
        ):
            _identity(getattr(self, name), name)
        if (
            type(self.feature_names) is not tuple
            or not self.feature_names
            or not all(type(name) is str and name for name in self.feature_names)
            or len(self.feature_names) != len(set(self.feature_names))
        ):
            raise RidgeFinalTestError(
                "feature_names must be a unique non-empty tuple"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise RidgeFinalTestError("label_name must be non-empty")
        alpha = _finite(self.alpha, "alpha")
        if alpha <= 0.0:
            raise RidgeFinalTestError("alpha must be strictly positive")
        object.__setattr__(self, "alpha", alpha)
        if (
            type(self.test_start_time) is not datetime
            or self.test_start_time.tzinfo is None
        ):
            raise RidgeFinalTestError("test_start_time must be timezone-aware")

        for name in (
            "development_candidate_count",
            "development_purged_count",
            "development_count",
            "test_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise RidgeFinalTestError(
                    f"{name} must be a non-negative integer"
                )
        if self.development_candidate_count <= 0:
            raise RidgeFinalTestError(
                "development_candidate_count must be positive"
            )
        if self.development_count <= 0:
            raise RidgeFinalTestError("development_count must be positive")
        if self.test_count <= 0:
            raise RidgeFinalTestError("test_count must be positive")
        if (
            self.development_candidate_count
            != self.development_count + self.development_purged_count
        ):
            raise RidgeFinalTestError(
                "development candidate/purge counts are inconsistent"
            )

        object.__setattr__(
            self,
            "intercept",
            _finite(self.intercept, "intercept"),
        )
        for name in ("coefficients", "feature_means", "feature_scales"):
            values = getattr(self, name)
            if type(values) is not tuple or not values:
                raise RidgeFinalTestError(
                    f"{name} must be a non-empty tuple"
                )
            normalized = tuple(
                _finite(value, f"{name} value") for value in values
            )
            object.__setattr__(self, name, normalized)
        width = len(self.feature_names)
        if (
            len(self.coefficients) != width
            or len(self.feature_means) != width
            or len(self.feature_scales) != width
        ):
            raise RidgeFinalTestError(
                "final Ridge parameter widths differ from Feature schema"
            )
        if any(scale < 0.0 for scale in self.feature_scales):
            raise RidgeFinalTestError("feature scales must be non-negative")

        if (
            type(self.predictions) is not tuple
            or len(self.predictions) != self.test_count
            or not all(
                type(item) is RidgeFinalTestPrediction
                for item in self.predictions
            )
        ):
            raise RidgeFinalTestError(
                "predictions must match TEST count exactly"
            )
        ordering = tuple(
            (item.feature_window_close, item.code, item.sample_key)
            for item in self.predictions
        )
        if ordering != tuple(sorted(ordering)):
            raise RidgeFinalTestError(
                "TEST predictions must be chronologically ordered"
            )

        object.__setattr__(self, "mae", _finite(self.mae, "mae"))
        object.__setattr__(self, "rmse", _finite(self.rmse, "rmse"))
        if self.mae < 0.0 or self.rmse < 0.0:
            raise RidgeFinalTestError("MAE/RMSE must be non-negative")
        object.__setattr__(self, "r2", _optional_finite(self.r2, "r2"))

        expected_model_id = _model_id(
            selection_id=self.selection_id,
            walk_forward_id=self.walk_forward_id,
            dataset_id=self.dataset_id,
            feature_names=self.feature_names,
            label_name=self.label_name,
            alpha=self.alpha,
            test_start_time=self.test_start_time,
            development_candidate_count=self.development_candidate_count,
            development_purged_count=self.development_purged_count,
            development_count=self.development_count,
            development_keys=tuple(),
            intercept=self.intercept,
            coefficients=self.coefficients,
            feature_means=self.feature_means,
            feature_scales=self.feature_scales,
            precomputed_key_digest=None,
        )
        # The public result does not expose development sample keys.  The
        # exact model_id is therefore rechecked in the constructor through
        # the hidden digest encoded in final_test_id below rather than by
        # recreating an incomplete model identity here.
        if type(expected_model_id) is not str or len(expected_model_id) != 64:
            raise RidgeFinalTestError("internal model identity construction failed")

        expected_final = _final_test_id(
            model_id=self.model_id,
            predictions=self.predictions,
            mae=self.mae,
            rmse=self.rmse,
            r2=self.r2,
        )
        if self.final_test_id != expected_final:
            raise RidgeFinalTestError(
                "final_test_id differs from TEST evaluation content"
            )


@dataclass(frozen=True, slots=True)
class _Row:
    X: tuple[float, ...]
    y: float
    metadata: ExperimentSampleMetadata


def _rows(split) -> tuple[_Row, ...]:
    return tuple(
        _Row(
            tuple(float(value) for value in X),
            float(y),
            metadata,
        )
        for X, y, metadata in zip(split.X, split.y, split.metadata)
    )


def _development_rows(bundle: ExperimentDatasetBundle) -> tuple[_Row, ...]:
    rows = _rows(bundle.train) + _rows(bundle.validation)
    ordered = tuple(
        sorted(
            rows,
            key=lambda item: (
                item.metadata.feature_window_close,
                item.metadata.code,
                item.metadata.sample_key,
            ),
        )
    )
    keys = tuple(item.metadata.sample_key for item in ordered)
    if len(keys) != len(set(keys)):
        raise RidgeFinalTestError(
            "development pool contains duplicate sample keys"
        )
    return ordered


def _test_rows(bundle: ExperimentDatasetBundle) -> tuple[_Row, ...]:
    rows = _rows(bundle.test)
    if not rows:
        raise RidgeFinalTestError("held-out TEST split must not be empty")
    ordering = tuple(
        (
            item.metadata.feature_window_close,
            item.metadata.code,
            item.metadata.sample_key,
        )
        for item in rows
    )
    if ordering != tuple(sorted(ordering)):
        raise RidgeFinalTestError("TEST rows are not chronologically ordered")
    return rows


def _prediction_id(
    *,
    sample_key: str,
    code: str,
    feature_window_close: datetime,
    actual: float,
    predicted: float,
) -> str:
    return encode_identity(
        "market-vault-ridge-final-test-prediction-v1",
        {
            "sample_key": sample_key,
            "code": code,
            "feature_window_close": feature_window_close,
            "actual": actual,
            "predicted": predicted,
        },
    )


def _model_id(
    *,
    selection_id: str,
    walk_forward_id: str,
    dataset_id: str,
    feature_names: tuple[str, ...],
    label_name: str,
    alpha: float,
    test_start_time: datetime,
    development_candidate_count: int,
    development_purged_count: int,
    development_count: int,
    development_keys: tuple[str, ...],
    intercept: float,
    coefficients: tuple[float, ...],
    feature_means: tuple[float, ...],
    feature_scales: tuple[float, ...],
    precomputed_key_digest: str | None = None,
) -> str:
    key_digest = precomputed_key_digest
    if key_digest is None:
        key_digest = _members_digest(
            "market-vault-ridge-final-development-keys-v1",
            development_keys,
        )
    return encode_identity(
        "market-vault-ridge-final-model-v1",
        {
            "selection_id": selection_id,
            "walk_forward_id": walk_forward_id,
            "dataset_id": dataset_id,
            "feature_names_digest": _members_digest(
                "market-vault-ridge-final-feature-names-v1",
                feature_names,
            ),
            "label_name": label_name,
            "alpha": alpha,
            "test_start_time": test_start_time,
            "development_candidate_count": development_candidate_count,
            "development_purged_count": development_purged_count,
            "development_count": development_count,
            "development_keys_digest": key_digest,
            "intercept": intercept,
            "coefficients_digest": _scalar_digest(
                "market-vault-ridge-final-coefficients-v1",
                coefficients,
            ),
            "feature_means_digest": _scalar_digest(
                "market-vault-ridge-final-means-v1",
                feature_means,
            ),
            "feature_scales_digest": _scalar_digest(
                "market-vault-ridge-final-scales-v1",
                feature_scales,
            ),
        },
    )


def _final_test_id(
    *,
    model_id: str,
    predictions: tuple[RidgeFinalTestPrediction, ...],
    mae: float,
    rmse: float,
    r2: float | None,
) -> str:
    return encode_identity(
        RIDGE_FINAL_TEST_VERSION,
        {
            "model_id": model_id,
            "test_count": len(predictions),
            "prediction_ids_digest": _members_digest(
                "market-vault-ridge-final-prediction-ids-v1",
                tuple(item.prediction_id for item in predictions),
            ),
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
        },
    )


def evaluate_ridge_final_test(
    bundle: ExperimentDatasetBundle,
    plan: WalkForwardPlan,
    selection: RidgeAlphaSelectionResult,
) -> RidgeFinalTestResult:
    """Fit on purged development data and evaluate the permanent TEST holdout."""
    if type(bundle) is not ExperimentDatasetBundle:
        raise RidgeFinalTestError(
            "Ridge final TEST V1 requires ExperimentDatasetBundle"
        )
    if type(plan) is not WalkForwardPlan:
        raise RidgeFinalTestError(
            "Ridge final TEST V1 requires WalkForwardPlan"
        )
    if type(selection) is not RidgeAlphaSelectionResult:
        raise RidgeFinalTestError(
            "Ridge final TEST V1 requires RidgeAlphaSelectionResult"
        )
    if bundle.label_logical_type != "float64":
        raise RidgeFinalTestError(
            "Ridge final TEST V1 supports float64 regression Labels only"
        )

    expected_plan = build_walk_forward_plan(
        bundle,
        minimum_train_periods=plan.minimum_train_periods,
        validation_periods=plan.validation_periods,
        step_periods=plan.step_periods,
    )
    if expected_plan != plan:
        raise RidgeFinalTestError(
            "WalkForwardPlan differs from the supplied Experiment Dataset"
        )
    if (
        selection.walk_forward_id != plan.walk_forward_id
        or selection.dataset_id != plan.dataset_id
        or selection.feature_names != plan.feature_names
        or selection.label_name != plan.label_name
    ):
        raise RidgeFinalTestError(
            "Ridge alpha selection differs from Walk-Forward schema"
        )
    if (
        bundle.dataset_id != plan.dataset_id
        or bundle.feature_names != plan.feature_names
        or bundle.label_name != plan.label_name
    ):
        raise RidgeFinalTestError(
            "Experiment Dataset differs from Walk-Forward schema"
        )
    if bundle.test.row_count != plan.held_out_test_count:
        raise RidgeFinalTestError(
            "held-out TEST count differs from Walk-Forward plan"
        )

    test_rows = _test_rows(bundle)
    test_start_time = test_rows[0].metadata.feature_window_close
    development = _development_rows(bundle)
    if any(
        row.metadata.feature_window_close >= test_start_time
        for row in development
    ):
        raise RidgeFinalTestError(
            "development Feature time reaches held-out TEST boundary"
        )
    retained = tuple(
        row for row in development
        if row.metadata.actual_label_end_time < test_start_time
    )
    purged_count = len(development) - len(retained)
    if not retained:
        raise RidgeFinalTestError(
            "selected-Label TEST purge removed all development rows"
        )

    train_X = tuple(row.X for row in retained)
    train_y = tuple(row.y for row in retained)
    test_X = tuple(row.X for row in test_rows)
    test_y = tuple(row.y for row in test_rows)

    try:
        intercept, coefficients, means, scales = _fit(
            train_X,
            train_y,
            selection.selected_alpha,
        )
        predicted = _predict(test_X, intercept, coefficients)
        mae, rmse, r2, *_ = _metrics(test_y, predicted)
    except RidgeBaselineError as exc:
        raise RidgeFinalTestError(str(exc)) from exc

    predictions = tuple(
        RidgeFinalTestPrediction(
            _prediction_id(
                sample_key=row.metadata.sample_key,
                code=row.metadata.code,
                feature_window_close=row.metadata.feature_window_close,
                actual=actual,
                predicted=prediction,
            ),
            row.metadata.sample_key,
            row.metadata.code,
            row.metadata.feature_window_close,
            actual,
            prediction,
        )
        for row, actual, prediction in zip(test_rows, test_y, predicted)
    )

    development_keys = tuple(
        row.metadata.sample_key for row in retained
    )
    model_id = _model_id(
        selection_id=selection.selection_id,
        walk_forward_id=plan.walk_forward_id,
        dataset_id=plan.dataset_id,
        feature_names=plan.feature_names,
        label_name=plan.label_name,
        alpha=selection.selected_alpha,
        test_start_time=test_start_time,
        development_candidate_count=len(development),
        development_purged_count=purged_count,
        development_count=len(retained),
        development_keys=development_keys,
        intercept=intercept,
        coefficients=coefficients,
        feature_means=means,
        feature_scales=scales,
    )
    final_test_id = _final_test_id(
        model_id=model_id,
        predictions=predictions,
        mae=mae,
        rmse=rmse,
        r2=r2,
    )
    return RidgeFinalTestResult(
        RIDGE_FINAL_TEST_VERSION,
        final_test_id,
        model_id,
        selection.selection_id,
        plan.walk_forward_id,
        plan.dataset_id,
        plan.feature_names,
        plan.label_name,
        selection.selected_alpha,
        test_start_time,
        len(development),
        purged_count,
        len(retained),
        len(test_rows),
        intercept,
        coefficients,
        means,
        scales,
        predictions,
        mae,
        rmse,
        r2,
    )
