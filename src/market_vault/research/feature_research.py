"""Feature Research V1 over ML Dataset Adapter outputs.

This module is a deterministic statistics layer only. It does not access
market data, rebuild a Dataset, shuffle samples, train a model, or infer a
trading strategy.

V1 reports per-Feature:

- population mean / standard deviation
- Pearson information coefficient (IC)
- Spearman rank IC using deterministic average ranks for ties
- bottom/top quantile Label means
- top-minus-bottom Label spread

All analysis is performed inside one already-authorized chronological split.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .ml import MLDatasetBundle, MLDatasetSplit


FEATURE_RESEARCH_VERSION = "market-vault-feature-research-v1"


class FeatureResearchError(ValueError):
    """Fail-closed Feature Research V1 input or calculation error."""


def _finite_optional(value, label: str):
    if value is None:
        return None
    if type(value) is bool or not isinstance(value, (int, float)):
        raise FeatureResearchError(f"{label} must be numeric or None")
    number = float(value)
    if not math.isfinite(number):
        raise FeatureResearchError(f"{label} must be finite")
    return 0.0 if number == 0.0 else number


@dataclass(frozen=True, slots=True)
class FeatureResearchMetric:
    feature_name: str
    sample_count: int
    feature_mean: float | None
    feature_std: float | None
    pearson_ic: float | None
    rank_ic: float | None
    bottom_count: int
    top_count: int
    bottom_label_mean: float | None
    top_label_mean: float | None
    top_bottom_spread: float | None

    def __post_init__(self) -> None:
        if type(self.feature_name) is not str or not self.feature_name:
            raise FeatureResearchError("feature_name must be a non-empty string")
        for name in ("sample_count", "bottom_count", "top_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise FeatureResearchError(f"{name} must be a non-negative integer")
        if self.bottom_count > self.sample_count or self.top_count > self.sample_count:
            raise FeatureResearchError("tail counts cannot exceed sample_count")
        for name in (
            "feature_mean",
            "feature_std",
            "pearson_ic",
            "rank_ic",
            "bottom_label_mean",
            "top_label_mean",
            "top_bottom_spread",
        ):
            object.__setattr__(
                self,
                name,
                _finite_optional(getattr(self, name), name),
            )
        if self.feature_std is not None and self.feature_std < 0.0:
            raise FeatureResearchError("feature_std must be non-negative")
        for name in ("pearson_ic", "rank_ic"):
            value = getattr(self, name)
            if value is not None and not -1.0 <= value <= 1.0:
                raise FeatureResearchError(f"{name} must be within [-1, 1]")
        if (self.bottom_count == 0) != (self.bottom_label_mean is None):
            raise FeatureResearchError("bottom count/mean presence mismatch")
        if (self.top_count == 0) != (self.top_label_mean is None):
            raise FeatureResearchError("top count/mean presence mismatch")
        expected_spread = (
            None
            if self.bottom_label_mean is None or self.top_label_mean is None
            else self.top_label_mean - self.bottom_label_mean
        )
        if expected_spread is None:
            if self.top_bottom_spread is not None:
                raise FeatureResearchError("spread requires both tail means")
        elif self.top_bottom_spread != expected_spread:
            raise FeatureResearchError("top_bottom_spread differs from tail means")


@dataclass(frozen=True, slots=True)
class FeatureResearchReport:
    version: str
    dataset_id: str
    split: str
    label_name: str
    quantile_count: int
    metrics: tuple[FeatureResearchMetric, ...]

    def __post_init__(self) -> None:
        if self.version != FEATURE_RESEARCH_VERSION:
            raise FeatureResearchError("unsupported Feature Research version")
        if type(self.dataset_id) is not str or len(self.dataset_id) != 64:
            raise FeatureResearchError("dataset_id must be a 64-character identity")
        if self.split not in ("TRAIN", "VALIDATION", "TEST"):
            raise FeatureResearchError("invalid Feature Research split")
        if type(self.label_name) is not str or not self.label_name:
            raise FeatureResearchError("label_name must be non-empty")
        if type(self.quantile_count) is not int or not 2 <= self.quantile_count <= 10:
            raise FeatureResearchError("quantile_count must be an integer within [2, 10]")
        if type(self.metrics) is not tuple or not all(
            type(item) is FeatureResearchMetric for item in self.metrics
        ):
            raise FeatureResearchError("metrics must be an immutable FeatureResearchMetric tuple")
        names = tuple(metric.feature_name for metric in self.metrics)
        if len(names) != len(set(names)):
            raise FeatureResearchError("Feature Research metrics contain duplicate names")


def _mean(values: tuple[float, ...]) -> float | None:
    return None if not values else math.fsum(values) / len(values)


def _std(values: tuple[float, ...], mean: float | None) -> float | None:
    if mean is None:
        return None
    return math.sqrt(
        math.fsum((value - mean) ** 2 for value in values) / len(values)
    )


def _pearson(x: tuple[float, ...], y: tuple[float, ...]) -> float | None:
    if len(x) != len(y):
        raise FeatureResearchError("correlation vectors have different lengths")
    if len(x) < 2:
        return None
    mx = math.fsum(x) / len(x)
    my = math.fsum(y) / len(y)
    dx = tuple(value - mx for value in x)
    dy = tuple(value - my for value in y)
    denominator = math.sqrt(
        math.fsum(value * value for value in dx)
        * math.fsum(value * value for value in dy)
    )
    if denominator == 0.0:
        return None
    result = math.fsum(a * b for a, b in zip(dx, dy)) / denominator
    # Bound tiny floating drift without masking a real out-of-range result.
    if 1.0 < result <= 1.0 + 1e-15:
        result = 1.0
    elif -1.0 - 1e-15 <= result < -1.0:
        result = -1.0
    if not math.isfinite(result) or not -1.0 <= result <= 1.0:
        raise FeatureResearchError("correlation calculation produced an invalid value")
    return 0.0 if result == 0.0 else result


def _average_ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        value = indexed[start][1]
        while end < len(indexed) and indexed[end][1] == value:
            end += 1
        # One-based ranks: [start+1, ..., end].
        average = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[indexed[position][0]] = average
        start = end
    return tuple(ranks)


def _tail_statistics(
    feature_values: tuple[float, ...],
    label_values: tuple[float, ...],
    quantile_count: int,
):
    if not feature_values:
        return 0, 0, None, None, None
    ranks = _average_ranks(feature_values)
    n = len(ranks)
    lower = 1.0 / quantile_count
    upper = 1.0 - lower
    percentiles = tuple((rank - 0.5) / n for rank in ranks)
    bottom = tuple(
        label for label, percentile in zip(label_values, percentiles)
        if percentile <= lower
    )
    top = tuple(
        label for label, percentile in zip(label_values, percentiles)
        if percentile >= upper
    )
    bottom_mean = _mean(bottom)
    top_mean = _mean(top)
    spread = (
        None
        if bottom_mean is None or top_mean is None
        else top_mean - bottom_mean
    )
    return len(bottom), len(top), bottom_mean, top_mean, spread


def _feature_selection(
    bundle: MLDatasetBundle,
    feature_names,
) -> tuple[str, ...]:
    if feature_names is None:
        return bundle.feature_names
    if isinstance(feature_names, (str, bytes)):
        raise FeatureResearchError("feature_names must be an iterable of Feature names")
    try:
        selected = tuple(feature_names)
    except TypeError as exc:
        raise FeatureResearchError("feature_names must be an iterable") from exc
    if not selected:
        raise FeatureResearchError("feature_names must not be empty")
    if not all(type(name) is str and name for name in selected):
        raise FeatureResearchError("feature_names must contain non-empty strings")
    if len(selected) != len(set(selected)):
        raise FeatureResearchError("feature_names must be unique")
    unknown = tuple(name for name in selected if name not in bundle.feature_names)
    if unknown:
        raise FeatureResearchError(
            "unknown Feature names: " + ", ".join(unknown)
        )
    return selected


def _analyze_one(
    split: MLDatasetSplit,
    feature_name: str,
    quantile_count: int,
) -> FeatureResearchMetric:
    try:
        index = split.feature_names.index(feature_name)
    except ValueError as exc:
        raise FeatureResearchError(f"Feature not present in ML split: {feature_name}") from exc

    x = tuple(row[index] for row in split.X)
    y = tuple(float(value) for value in split.y)
    mean = _mean(x)
    std = _std(x, mean)
    pearson = _pearson(x, y)
    rank_ic = _pearson(_average_ranks(x), _average_ranks(y))
    bottom_count, top_count, bottom_mean, top_mean, spread = _tail_statistics(
        x,
        y,
        quantile_count,
    )
    return FeatureResearchMetric(
        feature_name,
        len(x),
        mean,
        std,
        pearson,
        rank_ic,
        bottom_count,
        top_count,
        bottom_mean,
        top_mean,
        spread,
    )


def analyze_features(
    bundle: MLDatasetBundle,
    *,
    split: str = "TRAIN",
    feature_names=None,
    quantile_count: int = 5,
) -> FeatureResearchReport:
    """Analyze selected Features against one ML Dataset Label in one split."""
    if type(bundle) is not MLDatasetBundle:
        raise FeatureResearchError("Feature Research V1 requires MLDatasetBundle")
    if type(quantile_count) is not int or not 2 <= quantile_count <= 10:
        raise FeatureResearchError("quantile_count must be an integer within [2, 10]")
    if split not in ("TRAIN", "VALIDATION", "TEST"):
        raise FeatureResearchError("split must be TRAIN, VALIDATION, or TEST")
    selected = _feature_selection(bundle, feature_names)
    ml_split = bundle.split(split)
    metrics = tuple(
        _analyze_one(ml_split, feature_name, quantile_count)
        for feature_name in selected
    )
    return FeatureResearchReport(
        FEATURE_RESEARCH_VERSION,
        bundle.dataset_id,
        split,
        bundle.label_name,
        quantile_count,
        metrics,
    )
