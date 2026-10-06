"""Final one-shot Ridge TEST evaluation V1.

This layer is deliberately separate from walk-forward model selection.

Inputs:

- one exact ExperimentDatasetBundle carrying selected-Label end-time authority;
- one exact RidgeAlphaSelectionResult produced without TEST access.

Final fitting uses the development pool (TRAIN + VALIDATION) only.  Before
fitting, development rows are purged again against the first TEST
feature_window_close using the selected Label's exact actual_label_end_time:

    retain iff actual_label_end_time < test_start_time

A Label ending exactly at the TEST boundary is purged.

The fitted model and TEST evaluation use separate identities:

- model_id binds selection_id, retained development samples and fitted params;
- final_test_id additionally binds TEST predictions/metrics.

Therefore changing TEST values can change final_test_id while model_id remains
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re

from ..dataset.encoding import encode_identity
from .experiment import ExperimentDatasetBundle, ExperimentSampleMetadata
from .ridge_baseline import _fit, _metrics, _predict
from .ridge_selection import RidgeAlphaSelectionResult


RIDGE_FINAL_TEST_VERSION = "market-vault-ridge-final-test-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeFinalTestError(ValueError):
    """Fail-closed final Ridge TEST evaluation V1 error."""


def _finite(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeFinalTestError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise RidgeFinalTestError(f"{label} must be finite")
    return 0.0 if result == 0.0 else result


def _sha(value: str, label: str) -> str:
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


def _vector_digest(prefix: str, values: tuple[float, ...]) -> str:
    ids = tuple(
        encode_identity(
            prefix + "-member-v1",
            {
                "index": index,
                "value": value,
            },
        )
        for index, value in enumerate(values)
    )
    return _members_digest(prefix + "-members-v1", ids)


@dataclass(frozen=True, slots=True)
class RidgeTestPrediction:
    sample_key: str
    code: str
    feature_window_close: datetime
    actual_label_end_time: datetime
    actual: float
    predicted: float
    residual: float

    def __post_init__(self) -> None:
        _sha(self.sample_key, "sample_key")
        if type(self.code) is not str or not self.code.startswith("US."):
            raise RidgeFinalTestError("code must be a US market symbol")
        for name in ("feature_window_close", "actual_label_end_time"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None:
                raise RidgeFinalTestError(
                    f"{name} must be timezone-aware"
                )
        if self.actual_label_end_time <= self.feature_window_close:
            raise RidgeFinalTestError(
                "TEST selected Label must end after feature_window_close"
            )
        actual = _finite(self.actual, "actual")
        predicted = _finite(self.predicted, "predicted")
        residual = _finite(self.residual, "residual")
        expected = actual - predicted
        expected = 0.0 if expected == 0.0 else expected
        if residual != expected:
            raise RidgeFinalTestError(
                "residual differs from actual - predicted"
            )
        object.__setattr__(self, "actual", actual)
        object.__setattr__(self, "predicted", predicted)
        object.__setattr__(self, "residual", residual)


def _prediction_id(model_id: str, item: RidgeTestPrediction) -> str:
    return encode_identity(
        "market-vault-ridge-final-test-prediction-v1",
        {
            "model_id": model_id,
            "sample_key": item.sample_key,
            "code": item.code,
            "feature_window_close": item.feature_window_close,
            "actual_label_end_time": item.actual_label_end_time,
            "actual": item.actual,
            "predicted": item.predicted,
            "residual": item.residual,
        },
    )


def _model_id(
    *,
    selection_id: str,
    dataset_id: str,
    test_start_time: datetime,
    development_sample_keys: tuple[str, ...],
    development_candidate_count: int,
    purged_development_count: int,
    alpha: float,
    intercept: float,
    coefficients: tuple[float, ...],
    feature_means: tuple[float, ...],
    feature_scales: tuple[float, ...],
) -> str:
    return encode_identity(
        "market-vault-ridge-final-model-v1",
        {
            "selection_id": selection_id,
            "dataset_id": dataset_id,
            "test_start_time": test_start_time,
            "development_candidate_count": development_candidate_count,
            "purged_development_count": purged_development_count,
            "development_sample_keys_digest": _members_digest(
                "market-vault-ridge-final-development-keys-v1",
                development_sample_keys,
            ),
            "alpha": alpha,
            "intercept": intercept,
            "coefficients_digest": _vector_digest(
                "market-vault-ridge-final-coefficients",
                coefficients,
            ),
            "feature_means_digest": _vector_digest(
                "market-vault-ridge-final-means",
                feature_means,
            ),
            "feature_scales_digest": _vector_digest(
                "market-vault-ridge-final-scales",
                feature_scales,
            ),
        },
    )


def _final_test_id(
    *,
    model_id: str,
    predictions: tuple[RidgeTestPrediction, ...],
    mae: float,
    rmse: float,
    r2: float | None,
) -> str:
    prediction_ids = tuple(
        _prediction_id(model_id, item)
        for item in predictions
    )
    return encode_identity(
        RIDGE_FINAL_TEST_VERSION,
        {
            "model_id": model_id,
            "test_count": len(predictions),
            "prediction_ids_digest": _members_digest(
                "market-vault-ridge-final-prediction-ids-v1",
                prediction_ids,
            ),
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
        },
    )


@dataclass(frozen=True, slots=True)
class RidgeFinalTestReport:
    version: str
    model_id: str
    final_test_id: str
    selection_id: str
    walk_forward_id: str
    dataset_id: str
    feature_names: tuple[str, ...]
    label_name: str
    alpha: float
    test_start_time: datetime
    development_candidate_count: int
    purged_development_count: int
    development_sample_keys: tuple[str, ...]
    test_count: int
    intercept: float
    coefficients: tuple[float, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    mae: float
    rmse: float
    r2: float | None
    predictions: tuple[RidgeTestPrediction, ...]

    def __post_init__(self) -> None:
        if self.version != RIDGE_FINAL_TEST_VERSION:
            raise RidgeFinalTestError(
                "unsupported Ridge final TEST version"
            )
        for name in (
            "model_id",
            "final_test_id",
            "selection_id",
            "walk_forward_id",
            "dataset_id",
        ):
            _sha(getattr(self, name), name)
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
            raise RidgeFinalTestError(
                "test_start_time must be timezone-aware"
            )
        for name in (
            "development_candidate_count",
            "purged_development_count",
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
        retained_count = (
            self.development_candidate_count
            - self.purged_development_count
        )
        if retained_count <= 0:
            raise RidgeFinalTestError(
                "final development TRAIN must not be empty"
            )
        if (
            type(self.development_sample_keys) is not tuple
            or len(self.development_sample_keys) != retained_count
            or any(
                type(value) is not str
                or _SHA256_RE.fullmatch(value) is None
                for value in self.development_sample_keys
            )
            or len(set(self.development_sample_keys))
                != len(self.development_sample_keys)
        ):
            raise RidgeFinalTestError(
                "development_sample_keys differ from retained development rows"
            )
        if self.test_count <= 0:
            raise RidgeFinalTestError("TEST split must not be empty")
        if (
            type(self.predictions) is not tuple
            or len(self.predictions) != self.test_count
            or not all(
                type(item) is RidgeTestPrediction
                for item in self.predictions
            )
        ):
            raise RidgeFinalTestError(
                "predictions differ from test_count"
            )
        ordering = tuple(
            (
                item.feature_window_close,
                item.code,
                item.sample_key,
            )
            for item in self.predictions
        )
        if ordering != tuple(sorted(ordering)):
            raise RidgeFinalTestError(
                "TEST predictions must be chronological"
            )
        if self.predictions[0].feature_window_close != self.test_start_time:
            raise RidgeFinalTestError(
                "test_start_time differs from first TEST sample"
            )
        width = len(self.feature_names)
        for name in (
            "coefficients",
            "feature_means",
            "feature_scales",
        ):
            values = getattr(self, name)
            if type(values) is not tuple or len(values) != width:
                raise RidgeFinalTestError(
                    f"{name} width differs from feature_names"
                )
            normalized = tuple(
                _finite(value, f"{name} value")
                for value in values
            )
            object.__setattr__(self, name, normalized)
        if any(scale < 0.0 for scale in self.feature_scales):
            raise RidgeFinalTestError(
                "feature scales must be non-negative"
            )
        object.__setattr__(
            self,
            "intercept",
            _finite(self.intercept, "intercept"),
        )
        object.__setattr__(self, "mae", _finite(self.mae, "mae"))
        object.__setattr__(self, "rmse", _finite(self.rmse, "rmse"))
        if self.mae < 0.0 or self.rmse < 0.0:
            raise RidgeFinalTestError("MAE/RMSE must be non-negative")
        if self.r2 is not None:
            object.__setattr__(self, "r2", _finite(self.r2, "r2"))

        expected_model_id = _model_id(
            selection_id=self.selection_id,
            dataset_id=self.dataset_id,
            test_start_time=self.test_start_time,
            development_sample_keys=self.development_sample_keys,
            development_candidate_count=self.development_candidate_count,
            purged_development_count=self.purged_development_count,
            alpha=self.alpha,
            intercept=self.intercept,
            coefficients=self.coefficients,
            feature_means=self.feature_means,
            feature_scales=self.feature_scales,
        )
        if self.model_id != expected_model_id:
            raise RidgeFinalTestError(
                "model_id differs from final development fit"
            )
        expected_final_id = _final_test_id(
            model_id=self.model_id,
            predictions=self.predictions,
            mae=self.mae,
            rmse=self.rmse,
            r2=self.r2,
        )
        if self.final_test_id != expected_final_id:
            raise RidgeFinalTestError(
                "final_test_id differs from TEST evaluation content"
            )


@dataclass(frozen=True, slots=True)
class _DevelopmentRow:
    X: tuple[float, ...]
    y: float
    metadata: ExperimentSampleMetadata


def _development_rows(
    bundle: ExperimentDatasetBundle,
) -> tuple[_DevelopmentRow, ...]:
    rows = []
    for split in (bundle.train, bundle.validation):
        rows.extend(
            _DevelopmentRow(
                X,
                float(y),
                metadata,
            )
            for X, y, metadata in zip(
                split.X,
                split.y,
                split.metadata,
            )
        )
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
    if len({item.metadata.sample_key for item in ordered}) != len(ordered):
        raise RidgeFinalTestError(
            "development pool contains duplicate sample keys"
        )
    return ordered


def evaluate_ridge_final_test(
    bundle: ExperimentDatasetBundle,
    selection: RidgeAlphaSelectionResult,
) -> RidgeFinalTestReport:
    """Fit once on purged development data and score the held-out TEST once."""
    if type(bundle) is not ExperimentDatasetBundle:
        raise RidgeFinalTestError(
            "Ridge final TEST V1 requires ExperimentDatasetBundle"
        )
    if type(selection) is not RidgeAlphaSelectionResult:
        raise RidgeFinalTestError(
            "Ridge final TEST V1 requires RidgeAlphaSelectionResult"
        )
    if bundle.label_logical_type != "float64":
        raise RidgeFinalTestError(
            "Ridge final TEST V1 supports float64 regression Labels only"
        )
    if (
        selection.dataset_id != bundle.dataset_id
        or selection.feature_names != bundle.feature_names
        or selection.label_name != bundle.label_name
    ):
        raise RidgeFinalTestError(
            "Ridge selection schema differs from Experiment Dataset"
        )
    if bundle.test.row_count <= 0:
        raise RidgeFinalTestError(
            "Ridge final TEST V1 requires a non-empty TEST split"
        )

    test_start_time = bundle.test.metadata[0].feature_window_close
    development = _development_rows(bundle)
    if not development:
        raise RidgeFinalTestError("development pool must not be empty")
    if any(
        item.metadata.feature_window_close >= test_start_time
        for item in development
    ):
        raise RidgeFinalTestError(
            "development feature time reaches the TEST boundary"
        )

    retained = tuple(
        item for item in development
        if item.metadata.actual_label_end_time < test_start_time
    )
    purged_count = len(development) - len(retained)
    if not retained:
        raise RidgeFinalTestError(
            "selected-Label TEST-boundary purge removed all development rows"
        )

    train_X = tuple(item.X for item in retained)
    train_y = tuple(item.y for item in retained)
    (
        intercept,
        coefficients,
        feature_means,
        feature_scales,
    ) = _fit(
        train_X,
        train_y,
        selection.selected_alpha,
    )

    test_X = bundle.test.X
    test_y = tuple(float(value) for value in bundle.test.y)
    predicted = _predict(
        test_X,
        intercept,
        coefficients,
    )
    mae, rmse, r2, *_ = _metrics(test_y, predicted)

    development_keys = tuple(
        item.metadata.sample_key for item in retained
    )
    model_id = _model_id(
        selection_id=selection.selection_id,
        dataset_id=bundle.dataset_id,
        test_start_time=test_start_time,
        development_sample_keys=development_keys,
        development_candidate_count=len(development),
        purged_development_count=purged_count,
        alpha=selection.selected_alpha,
        intercept=intercept,
        coefficients=coefficients,
        feature_means=feature_means,
        feature_scales=feature_scales,
    )

    predictions = tuple(
        RidgeTestPrediction(
            metadata.sample_key,
            metadata.code,
            metadata.feature_window_close,
            metadata.actual_label_end_time,
            actual,
            prediction,
            actual - prediction,
        )
        for metadata, actual, prediction in zip(
            bundle.test.metadata,
            test_y,
            predicted,
        )
    )
    final_test_id = _final_test_id(
        model_id=model_id,
        predictions=predictions,
        mae=mae,
        rmse=rmse,
        r2=r2,
    )
    return RidgeFinalTestReport(
        RIDGE_FINAL_TEST_VERSION,
        model_id,
        final_test_id,
        selection.selection_id,
        selection.walk_forward_id,
        bundle.dataset_id,
        bundle.feature_names,
        bundle.label_name,
        selection.selected_alpha,
        test_start_time,
        len(development),
        purged_count,
        development_keys,
        len(predictions),
        intercept,
        coefficients,
        feature_means,
        feature_scales,
        mae,
        rmse,
        r2,
        predictions,
    )
