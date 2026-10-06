"""Deterministic Ridge Regression Baseline V1 over Walk-Forward folds.

This is the first model-fitting layer in the MarketVault research mainline.

V1 deliberately stays narrow:

- input is one exact WalkForwardPlan;
- TEST is inaccessible because WalkForwardPlan contains development folds only;
- only float64 regression Labels are supported;
- every fold fits on TRAIN and evaluates on its future VALIDATION slice;
- Feature standardization uses TRAIN statistics only;
- ridge alpha is explicit and strictly positive;
- no shuffle, random split, hyperparameter search, external ML framework, or
  model persistence is performed.

The solver uses the closed-form ridge normal equations with deterministic
partial-pivot Gaussian elimination.  Ridge regularization is applied in the
standardized Feature space; the reported coefficients/intercept are converted
back to the original Feature scale.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .walk_forward import WalkForwardPlan


RIDGE_BASELINE_VERSION = "market-vault-ridge-baseline-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeBaselineError(ValueError):
    """Fail-closed Ridge Regression Baseline V1 error."""


def _finite_number(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeBaselineError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RidgeBaselineError(f"{label} must be finite")
    return 0.0 if number == 0.0 else number


def _alpha(value) -> float:
    number = _finite_number(value, "alpha")
    if number <= 0.0:
        raise RidgeBaselineError("alpha must be strictly positive")
    return number


def _optional_finite(value, label: str):
    if value is None:
        return None
    return _finite_number(value, label)


@dataclass(frozen=True, slots=True)
class RidgeFoldResult:
    fold_index: int
    fold_id: str
    train_count: int
    validation_count: int
    alpha: float
    intercept: float
    coefficients: tuple[float, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    mae: float
    rmse: float
    r2: float | None

    def __post_init__(self) -> None:
        if type(self.fold_index) is not int or self.fold_index < 0:
            raise RidgeBaselineError("fold_index must be a non-negative integer")
        if type(self.fold_id) is not str or _SHA256_RE.fullmatch(self.fold_id) is None:
            raise RidgeBaselineError("fold_id must be a lowercase SHA-256 identity")
        for name in ("train_count", "validation_count"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise RidgeBaselineError(f"{name} must be a positive integer")
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        object.__setattr__(
            self,
            "intercept",
            _finite_number(self.intercept, "intercept"),
        )
        for name in ("coefficients", "feature_means", "feature_scales"):
            values = getattr(self, name)
            if type(values) is not tuple or not values:
                raise RidgeBaselineError(f"{name} must be a non-empty tuple")
            normalized = tuple(
                _finite_number(value, f"{name} value")
                for value in values
            )
            object.__setattr__(self, name, normalized)
        width = len(self.coefficients)
        if (
            len(self.feature_means) != width
            or len(self.feature_scales) != width
        ):
            raise RidgeBaselineError("ridge parameter vector widths differ")
        if any(scale < 0.0 for scale in self.feature_scales):
            raise RidgeBaselineError("feature scales must be non-negative")
        object.__setattr__(self, "mae", _finite_number(self.mae, "mae"))
        object.__setattr__(self, "rmse", _finite_number(self.rmse, "rmse"))
        if self.mae < 0.0 or self.rmse < 0.0:
            raise RidgeBaselineError("MAE/RMSE must be non-negative")
        object.__setattr__(self, "r2", _optional_finite(self.r2, "r2"))


@dataclass(frozen=True, slots=True)
class RidgeBaselineReport:
    version: str
    walk_forward_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    alpha: float
    folds: tuple[RidgeFoldResult, ...]
    validation_sample_count: int
    mae: float
    rmse: float
    r2: float | None

    def __post_init__(self) -> None:
        if self.version != RIDGE_BASELINE_VERSION:
            raise RidgeBaselineError("unsupported Ridge Baseline version")
        for name in ("walk_forward_id", "dataset_id"):
            value = getattr(self, name)
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                raise RidgeBaselineError(
                    f"{name} must be a lowercase SHA-256 identity"
                )
        if (
            type(self.feature_names) is not tuple
            or not self.feature_names
            or not all(type(name) is str and name for name in self.feature_names)
            or len(self.feature_names) != len(set(self.feature_names))
        ):
            raise RidgeBaselineError(
                "feature_names must be a unique non-empty string tuple"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise RidgeBaselineError("label_name must be non-empty")
        object.__setattr__(self, "alpha", _alpha(self.alpha))
        if (
            type(self.folds) is not tuple
            or not self.folds
            or not all(type(item) is RidgeFoldResult for item in self.folds)
        ):
            raise RidgeBaselineError(
                "folds must be a non-empty immutable RidgeFoldResult tuple"
            )
        if tuple(item.fold_index for item in self.folds) != tuple(range(len(self.folds))):
            raise RidgeBaselineError("Ridge fold indices must be contiguous")
        if any(
            len(item.coefficients) != len(self.feature_names)
            for item in self.folds
        ):
            raise RidgeBaselineError("Ridge fold coefficient width mismatch")
        if any(item.alpha != self.alpha for item in self.folds):
            raise RidgeBaselineError("Ridge fold alpha differs from report alpha")
        if type(self.validation_sample_count) is not int or self.validation_sample_count <= 0:
            raise RidgeBaselineError(
                "validation_sample_count must be a positive integer"
            )
        if self.validation_sample_count != sum(
            item.validation_count for item in self.folds
        ):
            raise RidgeBaselineError(
                "validation_sample_count differs from fold totals"
            )
        object.__setattr__(self, "mae", _finite_number(self.mae, "mae"))
        object.__setattr__(self, "rmse", _finite_number(self.rmse, "rmse"))
        if self.mae < 0.0 or self.rmse < 0.0:
            raise RidgeBaselineError("MAE/RMSE must be non-negative")
        object.__setattr__(self, "r2", _optional_finite(self.r2, "r2"))


def _column_stats(X: tuple[tuple[float, ...], ...]):
    if not X:
        raise RidgeBaselineError("ridge TRAIN matrix must not be empty")
    width = len(X[0])
    if width == 0 or any(len(row) != width for row in X):
        raise RidgeBaselineError("ridge TRAIN matrix width is invalid")

    means = tuple(
        math.fsum(row[column] for row in X) / len(X)
        for column in range(width)
    )
    scales = []
    for column, mean in enumerate(means):
        variance = math.fsum(
            (row[column] - mean) ** 2 for row in X
        ) / len(X)
        scale = math.sqrt(variance)
        if not math.isfinite(scale):
            raise RidgeBaselineError("Feature scale is not finite")
        scales.append(0.0 if scale == 0.0 else scale)
    return means, tuple(scales)


def _standardize(
    X: tuple[tuple[float, ...], ...],
    means: tuple[float, ...],
    scales: tuple[float, ...],
):
    return tuple(
        tuple(
            0.0 if scales[column] == 0.0
            else (row[column] - means[column]) / scales[column]
            for column in range(len(means))
        )
        for row in X
    )


def _solve(matrix, vector) -> tuple[float, ...]:
    n = len(vector)
    if n == 0 or len(matrix) != n or any(len(row) != n for row in matrix):
        raise RidgeBaselineError("ridge linear system shape is invalid")

    a = [list(row) for row in matrix]
    b = list(vector)

    for column in range(n):
        pivot = max(
            range(column, n),
            key=lambda row: abs(a[row][column]),
        )
        pivot_value = a[pivot][column]
        if not math.isfinite(pivot_value) or abs(pivot_value) <= 1e-15:
            raise RidgeBaselineError("ridge linear system is singular")
        if pivot != column:
            a[column], a[pivot] = a[pivot], a[column]
            b[column], b[pivot] = b[pivot], b[column]

        for row in range(column + 1, n):
            factor = a[row][column] / a[column][column]
            if factor == 0.0:
                continue
            a[row][column] = 0.0
            for inner in range(column + 1, n):
                a[row][inner] -= factor * a[column][inner]
            b[row] -= factor * b[column]

    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        remainder = b[row] - math.fsum(
            a[row][column] * solution[column]
            for column in range(row + 1, n)
        )
        value = remainder / a[row][row]
        if not math.isfinite(value):
            raise RidgeBaselineError("ridge coefficient is not finite")
        solution[row] = 0.0 if value == 0.0 else value
    return tuple(solution)


def _fit(
    X: tuple[tuple[float, ...], ...],
    y: tuple[float, ...],
    alpha: float,
):
    if len(X) != len(y) or not X:
        raise RidgeBaselineError("ridge TRAIN X/y row counts are invalid")
    means, scales = _column_stats(X)
    Z = _standardize(X, means, scales)
    y_mean = math.fsum(y) / len(y)
    centered_y = tuple(value - y_mean for value in y)
    width = len(means)

    matrix = []
    vector = []
    for left in range(width):
        matrix.append(tuple(
            math.fsum(
                row[left] * row[right] for row in Z
            ) + (alpha if left == right else 0.0)
            for right in range(width)
        ))
        vector.append(
            math.fsum(
                row[left] * target
                for row, target in zip(Z, centered_y)
            )
        )

    standardized_coefficients = _solve(
        tuple(matrix),
        tuple(vector),
    )
    coefficients = tuple(
        0.0 if scales[index] == 0.0
        else standardized_coefficients[index] / scales[index]
        for index in range(width)
    )
    intercept = y_mean - math.fsum(
        coefficient * mean
        for coefficient, mean in zip(coefficients, means)
    )
    if not math.isfinite(intercept):
        raise RidgeBaselineError("ridge intercept is not finite")
    return (
        0.0 if intercept == 0.0 else intercept,
        coefficients,
        means,
        scales,
    )


def _predict(
    X: tuple[tuple[float, ...], ...],
    intercept: float,
    coefficients: tuple[float, ...],
) -> tuple[float, ...]:
    predictions = []
    for row in X:
        if len(row) != len(coefficients):
            raise RidgeBaselineError("ridge prediction matrix width mismatch")
        value = intercept + math.fsum(
            coefficient * feature
            for coefficient, feature in zip(coefficients, row)
        )
        if not math.isfinite(value):
            raise RidgeBaselineError("ridge prediction is not finite")
        predictions.append(0.0 if value == 0.0 else value)
    return tuple(predictions)


def _metrics(actual: tuple[float, ...], predicted: tuple[float, ...]):
    if len(actual) != len(predicted) or not actual:
        raise RidgeBaselineError("validation metric vectors are invalid")
    residuals = tuple(
        target - prediction
        for target, prediction in zip(actual, predicted)
    )
    absolute_error = math.fsum(abs(value) for value in residuals)
    squared_error = math.fsum(value * value for value in residuals)
    mae = absolute_error / len(actual)
    rmse = math.sqrt(squared_error / len(actual))

    mean = math.fsum(actual) / len(actual)
    total = math.fsum((value - mean) ** 2 for value in actual)
    r2 = None if total == 0.0 else 1.0 - squared_error / total

    return (
        0.0 if mae == 0.0 else mae,
        0.0 if rmse == 0.0 else rmse,
        None if r2 is None else (0.0 if r2 == 0.0 else r2),
        absolute_error,
        squared_error,
        math.fsum(actual),
        math.fsum(value * value for value in actual),
    )


def evaluate_ridge_baseline(
    plan: WalkForwardPlan,
    *,
    alpha: float = 1.0,
) -> RidgeBaselineReport:
    """Fit/evaluate one deterministic ridge baseline across development folds."""
    if type(plan) is not WalkForwardPlan:
        raise RidgeBaselineError(
            "Ridge Baseline V1 requires WalkForwardPlan"
        )
    if plan.label_logical_type != "float64":
        raise RidgeBaselineError(
            "Ridge Baseline V1 supports float64 regression Labels only"
        )
    alpha = _alpha(alpha)

    fold_results = []
    total_count = 0
    total_abs_error = 0.0
    total_squared_error = 0.0
    total_y_sum = 0.0
    total_y_squared_sum = 0.0

    for fold in plan.folds:
        train_y = tuple(float(value) for value in fold.train.y)
        validation_y = tuple(float(value) for value in fold.validation.y)
        intercept, coefficients, means, scales = _fit(
            fold.train.X,
            train_y,
            alpha,
        )
        predictions = _predict(
            fold.validation.X,
            intercept,
            coefficients,
        )
        (
            mae,
            rmse,
            r2,
            absolute_error,
            squared_error,
            y_sum,
            y_squared_sum,
        ) = _metrics(validation_y, predictions)

        fold_results.append(
            RidgeFoldResult(
                fold.fold_index,
                fold.fold_id,
                fold.train.row_count,
                fold.validation.row_count,
                alpha,
                intercept,
                coefficients,
                means,
                scales,
                mae,
                rmse,
                r2,
            )
        )
        total_count += len(validation_y)
        total_abs_error += absolute_error
        total_squared_error += squared_error
        total_y_sum += y_sum
        total_y_squared_sum += y_squared_sum

    if total_count <= 0:
        raise RidgeBaselineError("Walk-Forward plan has no validation samples")

    mae = total_abs_error / total_count
    rmse = math.sqrt(total_squared_error / total_count)
    total_variance = (
        total_y_squared_sum
        - (total_y_sum * total_y_sum) / total_count
    )
    if total_variance <= 0.0:
        r2 = None
    else:
        r2 = 1.0 - total_squared_error / total_variance

    return RidgeBaselineReport(
        RIDGE_BASELINE_VERSION,
        plan.walk_forward_id,
        plan.dataset_id,
        plan.feature_names,
        plan.label_name,
        alpha,
        tuple(fold_results),
        total_count,
        0.0 if mae == 0.0 else mae,
        0.0 if rmse == 0.0 else rmse,
        None if r2 is None else (0.0 if r2 == 0.0 else r2),
    )
