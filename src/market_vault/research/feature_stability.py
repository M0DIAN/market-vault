"""Feature Stability V1 across chronological ML Dataset splits.

This module compares already-computed Feature Research semantics across
TRAIN / VALIDATION / TEST. It does not rebuild a Dataset, recalculate market
data, shuffle samples, train a model, rank Features, or produce a composite
selection score.

For each Feature it carries the split-specific Pearson IC, Rank IC and
top-minus-bottom Label spread, plus:

- number of splits where the metric is available;
- sign consistency across available splits;
- max-minus-min range across available splits.

A consistency value is None when fewer than two split values are available.
Zero is treated as neutral: [positive, zero] is sign-consistent, while
[positive, zero, negative] is not.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .feature_research import (
    FeatureResearchError,
    analyze_features,
)
from .ml import MLDatasetBundle


FEATURE_STABILITY_VERSION = "market-vault-feature-stability-v1"
_SPLITS = ("TRAIN", "VALIDATION", "TEST")


class FeatureStabilityError(ValueError):
    """Fail-closed Feature Stability V1 input or result error."""


def _optional_finite(value, label: str):
    if value is None:
        return None
    if type(value) is bool or not isinstance(value, (int, float)):
        raise FeatureStabilityError(f"{label} must be numeric or None")
    number = float(value)
    if not math.isfinite(number):
        raise FeatureStabilityError(f"{label} must be finite")
    return 0.0 if number == 0.0 else number


def _available(values) -> tuple[float, ...]:
    return tuple(value for value in values if value is not None)


def _range(values) -> float | None:
    present = _available(values)
    if len(present) < 2:
        return None
    return max(present) - min(present)


def _sign_consistent(values) -> bool | None:
    present = _available(values)
    if len(present) < 2:
        return None
    return all(value >= 0.0 for value in present) or all(
        value <= 0.0 for value in present
    )


@dataclass(frozen=True, slots=True)
class FeatureStabilityMetric:
    feature_name: str

    train_sample_count: int
    validation_sample_count: int
    test_sample_count: int

    train_pearson_ic: float | None
    validation_pearson_ic: float | None
    test_pearson_ic: float | None
    pearson_available_count: int
    pearson_sign_consistent: bool | None
    pearson_range: float | None

    train_rank_ic: float | None
    validation_rank_ic: float | None
    test_rank_ic: float | None
    rank_available_count: int
    rank_sign_consistent: bool | None
    rank_range: float | None

    train_top_bottom_spread: float | None
    validation_top_bottom_spread: float | None
    test_top_bottom_spread: float | None
    spread_available_count: int
    spread_sign_consistent: bool | None
    spread_range: float | None

    def __post_init__(self) -> None:
        if type(self.feature_name) is not str or not self.feature_name:
            raise FeatureStabilityError("feature_name must be non-empty")

        for name in (
            "train_sample_count",
            "validation_sample_count",
            "test_sample_count",
            "pearson_available_count",
            "rank_available_count",
            "spread_available_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise FeatureStabilityError(f"{name} must be a non-negative integer")

        split_counts = (
            self.train_sample_count,
            self.validation_sample_count,
            self.test_sample_count,
        )
        metric_groups = (
            (
                "pearson",
                (
                    self.train_pearson_ic,
                    self.validation_pearson_ic,
                    self.test_pearson_ic,
                ),
                self.pearson_available_count,
                self.pearson_sign_consistent,
                self.pearson_range,
            ),
            (
                "rank",
                (
                    self.train_rank_ic,
                    self.validation_rank_ic,
                    self.test_rank_ic,
                ),
                self.rank_available_count,
                self.rank_sign_consistent,
                self.rank_range,
            ),
            (
                "spread",
                (
                    self.train_top_bottom_spread,
                    self.validation_top_bottom_spread,
                    self.test_top_bottom_spread,
                ),
                self.spread_available_count,
                self.spread_sign_consistent,
                self.spread_range,
            ),
        )

        for prefix, values, available_count, sign_consistent, value_range in metric_groups:
            normalized = tuple(
                _optional_finite(value, f"{prefix} split value")
                for value in values
            )
            for field_name, value in zip(
                {
                    "pearson": (
                        "train_pearson_ic",
                        "validation_pearson_ic",
                        "test_pearson_ic",
                    ),
                    "rank": (
                        "train_rank_ic",
                        "validation_rank_ic",
                        "test_rank_ic",
                    ),
                    "spread": (
                        "train_top_bottom_spread",
                        "validation_top_bottom_spread",
                        "test_top_bottom_spread",
                    ),
                }[prefix],
                normalized,
            ):
                object.__setattr__(self, field_name, value)

            expected_count = len(_available(normalized))
            if available_count != expected_count:
                raise FeatureStabilityError(
                    f"{prefix}_available_count differs from split values"
                )
            expected_sign = _sign_consistent(normalized)
            if sign_consistent is not expected_sign and sign_consistent != expected_sign:
                raise FeatureStabilityError(
                    f"{prefix}_sign_consistent differs from split values"
                )
            expected_range = _range(normalized)
            normalized_range = _optional_finite(value_range, f"{prefix}_range")
            object.__setattr__(self, f"{prefix}_range", normalized_range)
            if expected_range is None:
                if normalized_range is not None:
                    raise FeatureStabilityError(
                        f"{prefix}_range requires at least two available splits"
                    )
            elif normalized_range != expected_range:
                raise FeatureStabilityError(
                    f"{prefix}_range differs from split values"
                )

        if any(value < 0 for value in split_counts):
            raise FeatureStabilityError("sample counts must be non-negative")


@dataclass(frozen=True, slots=True)
class FeatureStabilityReport:
    version: str
    dataset_id: str
    label_name: str
    quantile_count: int
    metrics: tuple[FeatureStabilityMetric, ...]

    def __post_init__(self) -> None:
        if self.version != FEATURE_STABILITY_VERSION:
            raise FeatureStabilityError("unsupported Feature Stability version")
        if type(self.dataset_id) is not str or len(self.dataset_id) != 64:
            raise FeatureStabilityError("dataset_id must be a 64-character identity")
        if type(self.label_name) is not str or not self.label_name:
            raise FeatureStabilityError("label_name must be non-empty")
        if type(self.quantile_count) is not int or not 2 <= self.quantile_count <= 10:
            raise FeatureStabilityError(
                "quantile_count must be an integer within [2, 10]"
            )
        if type(self.metrics) is not tuple or not all(
            type(metric) is FeatureStabilityMetric for metric in self.metrics
        ):
            raise FeatureStabilityError(
                "metrics must be an immutable FeatureStabilityMetric tuple"
            )
        names = tuple(metric.feature_name for metric in self.metrics)
        if len(names) != len(set(names)):
            raise FeatureStabilityError("Feature Stability metrics contain duplicates")


def _metric_from_split_reports(feature_name, reports):
    split_metrics = []
    for report in reports:
        matches = tuple(
            metric for metric in report.metrics
            if metric.feature_name == feature_name
        )
        if len(matches) != 1:
            raise FeatureStabilityError(
                f"Feature Research report mismatch for {feature_name}"
            )
        split_metrics.append(matches[0])

    train, validation, test = split_metrics
    pearson = (
        train.pearson_ic,
        validation.pearson_ic,
        test.pearson_ic,
    )
    rank = (
        train.rank_ic,
        validation.rank_ic,
        test.rank_ic,
    )
    spread = (
        train.top_bottom_spread,
        validation.top_bottom_spread,
        test.top_bottom_spread,
    )
    return FeatureStabilityMetric(
        feature_name,
        train.sample_count,
        validation.sample_count,
        test.sample_count,

        *pearson,
        len(_available(pearson)),
        _sign_consistent(pearson),
        _range(pearson),

        *rank,
        len(_available(rank)),
        _sign_consistent(rank),
        _range(rank),

        *spread,
        len(_available(spread)),
        _sign_consistent(spread),
        _range(spread),
    )


def compare_feature_stability(
    bundle: MLDatasetBundle,
    *,
    feature_names=None,
    quantile_count: int = 5,
) -> FeatureStabilityReport:
    """Compare Feature Research metrics across TRAIN/VALIDATION/TEST."""
    if type(bundle) is not MLDatasetBundle:
        raise FeatureStabilityError(
            "Feature Stability V1 requires MLDatasetBundle"
        )
    try:
        reports = tuple(
            analyze_features(
                bundle,
                split=split,
                feature_names=feature_names,
                quantile_count=quantile_count,
            )
            for split in _SPLITS
        )
    except FeatureResearchError as exc:
        raise FeatureStabilityError(str(exc)) from exc

    feature_order = tuple(metric.feature_name for metric in reports[0].metrics)
    for report in reports[1:]:
        if tuple(metric.feature_name for metric in report.metrics) != feature_order:
            raise FeatureStabilityError(
                "Feature Research split reports disagree on Feature ordering"
            )
        if (
            report.dataset_id != reports[0].dataset_id
            or report.label_name != reports[0].label_name
            or report.quantile_count != reports[0].quantile_count
        ):
            raise FeatureStabilityError(
                "Feature Research split reports disagree on identity/configuration"
            )

    return FeatureStabilityReport(
        FEATURE_STABILITY_VERSION,
        bundle.dataset_id,
        bundle.label_name,
        quantile_count,
        tuple(
            _metric_from_split_reports(feature_name, reports)
            for feature_name in feature_order
        ),
    )
