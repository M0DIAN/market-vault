"""Leakage-safe Feature Selection V1.

Feature Selection V1 is a deterministic TRAIN + VALIDATION gate over the
existing Feature Research statistics.  TEST is deliberately never consulted:
selection decisions must not learn from the final holdout split.

V1 uses Rank IC only.  There is no composite score, no ranking, no automatic
threshold search and no model fitting.  Every threshold is supplied explicitly
through FeatureSelectionPolicy and every rejection is represented by stable
reason codes.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .feature_research import (
    FeatureResearchError,
    FeatureResearchMetric,
    analyze_features,
)
from .ml import MLDatasetBundle


FEATURE_SELECTION_VERSION = "market-vault-feature-selection-v1"

REASON_TRAIN_SAMPLE_COUNT_BELOW_MINIMUM = (
    "TRAIN_SAMPLE_COUNT_BELOW_MINIMUM"
)
REASON_VALIDATION_SAMPLE_COUNT_BELOW_MINIMUM = (
    "VALIDATION_SAMPLE_COUNT_BELOW_MINIMUM"
)
REASON_TRAIN_RANK_IC_UNAVAILABLE = "TRAIN_RANK_IC_UNAVAILABLE"
REASON_VALIDATION_RANK_IC_UNAVAILABLE = "VALIDATION_RANK_IC_UNAVAILABLE"
REASON_TRAIN_ABS_RANK_IC_BELOW_MINIMUM = (
    "TRAIN_ABS_RANK_IC_BELOW_MINIMUM"
)
REASON_VALIDATION_ABS_RANK_IC_BELOW_MINIMUM = (
    "VALIDATION_ABS_RANK_IC_BELOW_MINIMUM"
)
REASON_RANK_IC_SIGN_MISMATCH = "RANK_IC_SIGN_MISMATCH"
REASON_RANK_IC_DRIFT_EXCEEDS_MAXIMUM = (
    "RANK_IC_DRIFT_EXCEEDS_MAXIMUM"
)

_REASON_CODES = frozenset((
    REASON_TRAIN_SAMPLE_COUNT_BELOW_MINIMUM,
    REASON_VALIDATION_SAMPLE_COUNT_BELOW_MINIMUM,
    REASON_TRAIN_RANK_IC_UNAVAILABLE,
    REASON_VALIDATION_RANK_IC_UNAVAILABLE,
    REASON_TRAIN_ABS_RANK_IC_BELOW_MINIMUM,
    REASON_VALIDATION_ABS_RANK_IC_BELOW_MINIMUM,
    REASON_RANK_IC_SIGN_MISMATCH,
    REASON_RANK_IC_DRIFT_EXCEEDS_MAXIMUM,
))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FeatureSelectionError(ValueError):
    """Fail-closed Feature Selection V1 input/result error."""


def _non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise FeatureSelectionError(
            f"{label} must be a non-negative integer"
        )
    return value


def _bounded_number(value, label: str, lower: float, upper: float) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise FeatureSelectionError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not lower <= number <= upper:
        raise FeatureSelectionError(
            f"{label} must be finite within [{lower}, {upper}]"
        )
    return 0.0 if number == 0.0 else number


def _optional_rank_ic(value, label: str) -> float | None:
    if value is None:
        return None
    return _bounded_number(value, label, -1.0, 1.0)


def _same_sign(left: float, right: float) -> bool:
    # Zero is neutral, matching Feature Stability semantics.
    return (
        (left >= 0.0 and right >= 0.0)
        or (left <= 0.0 and right <= 0.0)
    )


@dataclass(frozen=True, slots=True)
class FeatureSelectionPolicy:
    minimum_train_samples: int
    minimum_validation_samples: int
    minimum_abs_train_rank_ic: float
    minimum_abs_validation_rank_ic: float
    maximum_rank_ic_drift: float
    require_same_sign: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimum_train_samples",
            _non_negative_int(
                self.minimum_train_samples,
                "minimum_train_samples",
            ),
        )
        object.__setattr__(
            self,
            "minimum_validation_samples",
            _non_negative_int(
                self.minimum_validation_samples,
                "minimum_validation_samples",
            ),
        )
        object.__setattr__(
            self,
            "minimum_abs_train_rank_ic",
            _bounded_number(
                self.minimum_abs_train_rank_ic,
                "minimum_abs_train_rank_ic",
                0.0,
                1.0,
            ),
        )
        object.__setattr__(
            self,
            "minimum_abs_validation_rank_ic",
            _bounded_number(
                self.minimum_abs_validation_rank_ic,
                "minimum_abs_validation_rank_ic",
                0.0,
                1.0,
            ),
        )
        object.__setattr__(
            self,
            "maximum_rank_ic_drift",
            _bounded_number(
                self.maximum_rank_ic_drift,
                "maximum_rank_ic_drift",
                0.0,
                2.0,
            ),
        )
        if type(self.require_same_sign) is not bool:
            raise FeatureSelectionError(
                "require_same_sign must be a boolean"
            )


@dataclass(frozen=True, slots=True)
class FeatureSelectionDecision:
    feature_name: str
    selected: bool
    reason_codes: tuple[str, ...]
    train_sample_count: int
    validation_sample_count: int
    train_rank_ic: float | None
    validation_rank_ic: float | None
    rank_ic_drift: float | None
    rank_ic_sign_consistent: bool | None

    def __post_init__(self) -> None:
        if type(self.feature_name) is not str or not self.feature_name:
            raise FeatureSelectionError(
                "feature_name must be a non-empty string"
            )
        if type(self.selected) is not bool:
            raise FeatureSelectionError("selected must be a boolean")
        if (
            type(self.reason_codes) is not tuple
            or len(self.reason_codes) != len(set(self.reason_codes))
            or any(code not in _REASON_CODES for code in self.reason_codes)
        ):
            raise FeatureSelectionError(
                "reason_codes must be a unique stable reason tuple"
            )
        if self.selected != (not self.reason_codes):
            raise FeatureSelectionError(
                "selected must be true exactly when reason_codes is empty"
            )
        object.__setattr__(
            self,
            "train_sample_count",
            _non_negative_int(
                self.train_sample_count,
                "train_sample_count",
            ),
        )
        object.__setattr__(
            self,
            "validation_sample_count",
            _non_negative_int(
                self.validation_sample_count,
                "validation_sample_count",
            ),
        )
        train = _optional_rank_ic(
            self.train_rank_ic,
            "train_rank_ic",
        )
        validation = _optional_rank_ic(
            self.validation_rank_ic,
            "validation_rank_ic",
        )
        object.__setattr__(self, "train_rank_ic", train)
        object.__setattr__(self, "validation_rank_ic", validation)

        expected_drift = (
            None
            if train is None or validation is None
            else abs(validation - train)
        )
        drift = self.rank_ic_drift
        if expected_drift is None:
            if drift is not None:
                raise FeatureSelectionError(
                    "rank_ic_drift requires both split Rank IC values"
                )
        else:
            drift = _bounded_number(
                drift,
                "rank_ic_drift",
                0.0,
                2.0,
            )
            if drift != expected_drift:
                raise FeatureSelectionError(
                    "rank_ic_drift differs from split Rank IC values"
                )
        object.__setattr__(self, "rank_ic_drift", drift)

        expected_sign = (
            None
            if train is None or validation is None
            else _same_sign(train, validation)
        )
        if self.rank_ic_sign_consistent is not expected_sign:
            if self.rank_ic_sign_consistent != expected_sign:
                raise FeatureSelectionError(
                    "rank_ic_sign_consistent differs from split values"
                )


@dataclass(frozen=True, slots=True)
class FeatureSelectionReport:
    version: str
    dataset_id: str
    label_name: str
    policy: FeatureSelectionPolicy
    decisions: tuple[FeatureSelectionDecision, ...]
    selected_features: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.version != FEATURE_SELECTION_VERSION:
            raise FeatureSelectionError(
                "unsupported Feature Selection version"
            )
        if (
            type(self.dataset_id) is not str
            or _SHA256_RE.fullmatch(self.dataset_id) is None
        ):
            raise FeatureSelectionError(
                "dataset_id must be a 64-character lowercase hex identity"
            )
        if type(self.label_name) is not str or not self.label_name:
            raise FeatureSelectionError("label_name must be non-empty")
        if type(self.policy) is not FeatureSelectionPolicy:
            raise FeatureSelectionError(
                "exact FeatureSelectionPolicy required"
            )
        if (
            type(self.decisions) is not tuple
            or not all(
                type(item) is FeatureSelectionDecision
                for item in self.decisions
            )
        ):
            raise FeatureSelectionError(
                "decisions must be an immutable decision tuple"
            )
        names = tuple(item.feature_name for item in self.decisions)
        if len(names) != len(set(names)):
            raise FeatureSelectionError(
                "Feature Selection decisions contain duplicate names"
            )
        expected = tuple(
            item.feature_name for item in self.decisions
            if item.selected
        )
        if self.selected_features != expected:
            raise FeatureSelectionError(
                "selected_features differs from decision outcomes"
            )


def _feature_order(train_report, validation_report) -> tuple[str, ...]:
    if (
        train_report.dataset_id != validation_report.dataset_id
        or train_report.label_name != validation_report.label_name
    ):
        raise FeatureSelectionError(
            "TRAIN and VALIDATION Feature Research reports disagree "
            "on identity/configuration"
        )
    train_names = tuple(
        metric.feature_name for metric in train_report.metrics
    )
    validation_names = tuple(
        metric.feature_name for metric in validation_report.metrics
    )
    if train_names != validation_names:
        raise FeatureSelectionError(
            "TRAIN and VALIDATION Feature ordering differs"
        )
    return train_names


def _metric_map(report) -> dict[str, FeatureResearchMetric]:
    return {
        metric.feature_name: metric
        for metric in report.metrics
    }


def _decision(
    name: str,
    train: FeatureResearchMetric,
    validation: FeatureResearchMetric,
    policy: FeatureSelectionPolicy,
) -> FeatureSelectionDecision:
    reasons = []

    if train.sample_count < policy.minimum_train_samples:
        reasons.append(REASON_TRAIN_SAMPLE_COUNT_BELOW_MINIMUM)
    if validation.sample_count < policy.minimum_validation_samples:
        reasons.append(REASON_VALIDATION_SAMPLE_COUNT_BELOW_MINIMUM)

    train_ic = train.rank_ic
    validation_ic = validation.rank_ic

    if train_ic is None:
        reasons.append(REASON_TRAIN_RANK_IC_UNAVAILABLE)
    elif abs(train_ic) < policy.minimum_abs_train_rank_ic:
        reasons.append(REASON_TRAIN_ABS_RANK_IC_BELOW_MINIMUM)

    if validation_ic is None:
        reasons.append(REASON_VALIDATION_RANK_IC_UNAVAILABLE)
    elif abs(validation_ic) < policy.minimum_abs_validation_rank_ic:
        reasons.append(
            REASON_VALIDATION_ABS_RANK_IC_BELOW_MINIMUM
        )

    if train_ic is None or validation_ic is None:
        drift = None
        sign_consistent = None
    else:
        drift = abs(validation_ic - train_ic)
        sign_consistent = _same_sign(train_ic, validation_ic)
        if policy.require_same_sign and not sign_consistent:
            reasons.append(REASON_RANK_IC_SIGN_MISMATCH)
        if drift > policy.maximum_rank_ic_drift:
            reasons.append(REASON_RANK_IC_DRIFT_EXCEEDS_MAXIMUM)

    return FeatureSelectionDecision(
        name,
        not reasons,
        tuple(reasons),
        train.sample_count,
        validation.sample_count,
        train_ic,
        validation_ic,
        drift,
        sign_consistent,
    )


def select_features(
    bundle: MLDatasetBundle,
    *,
    policy: FeatureSelectionPolicy,
    feature_names=None,
) -> FeatureSelectionReport:
    """Select Features using TRAIN + VALIDATION only.

    TEST is intentionally never requested from Feature Research.
    """
    if type(bundle) is not MLDatasetBundle:
        raise FeatureSelectionError(
            "Feature Selection V1 requires MLDatasetBundle"
        )
    if type(policy) is not FeatureSelectionPolicy:
        raise FeatureSelectionError(
            "exact FeatureSelectionPolicy required"
        )
    try:
        train_report = analyze_features(
            bundle,
            split="TRAIN",
            feature_names=feature_names,
            quantile_count=5,
        )
        validation_report = analyze_features(
            bundle,
            split="VALIDATION",
            feature_names=feature_names,
            quantile_count=5,
        )
    except FeatureResearchError as exc:
        raise FeatureSelectionError(str(exc)) from exc

    order = _feature_order(train_report, validation_report)
    train_metrics = _metric_map(train_report)
    validation_metrics = _metric_map(validation_report)
    decisions = tuple(
        _decision(
            name,
            train_metrics[name],
            validation_metrics[name],
            policy,
        )
        for name in order
    )

    return FeatureSelectionReport(
        FEATURE_SELECTION_VERSION,
        bundle.dataset_id,
        bundle.label_name,
        policy,
        decisions,
        tuple(
            item.feature_name
            for item in decisions
            if item.selected
        ),
    )
