"""Shared trading authority for Research economic evaluation layers.

This module owns one narrow trust boundary:

Verified Research Dataset handle
-> strict artifact re-read
-> execution-safe return LabelSpec verification
-> exact ExperimentDatasetBundle rebuild

It deliberately does not know about Ridge models, thresholds, TEST evaluation,
or trading metrics.
"""

from __future__ import annotations

from ..cross_day_dataset import (
    VerifiedMultiSourceCrossDayDataset,
    load_verified_multi_source_cross_day_dataset,
)
from ..cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError
from .experiment import (
    ExperimentDatasetBundle,
    ExperimentMetadataError,
    build_experiment_dataset,
)


EXECUTION_SAFE_RETURN_REF = (
    "market_vault.dataset.label_transforms.forward_open_to_close_return:"
    "forward_open_to_close_return"
)


class TradingAuthorityError(ValueError):
    """Fail-closed shared Research trading authority error."""


def validate_execution_safe_experiment(
    dataset: VerifiedMultiSourceCrossDayDataset,
    bundle: ExperimentDatasetBundle,
):
    """Re-read artifact, verify Label semantics, and rebuild exact Experiment."""
    if type(dataset) is not VerifiedMultiSourceCrossDayDataset:
        raise TradingAuthorityError(
            "trading evaluation requires a Verified Research Dataset artifact"
        )
    if type(bundle) is not ExperimentDatasetBundle:
        raise TradingAuthorityError(
            "trading evaluation requires ExperimentDatasetBundle"
        )

    try:
        fresh = load_verified_multi_source_cross_day_dataset(
            dataset.build_path
        )
    except (
        MultiSourceCrossDayArtifactError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise TradingAuthorityError(
            "verified Research Dataset revalidation failed"
        ) from exc
    if fresh.dataset_id != dataset.dataset_id:
        raise TradingAuthorityError(
            "verified Research Dataset identity changed since load"
        )

    specs = tuple(
        spec for spec in fresh.cross_day_labels.label_specs
        if spec.name == bundle.label_name
    )
    if len(specs) != 1:
        raise TradingAuthorityError(
            "Experiment Label must select exactly one verified Dataset Label"
        )
    spec = specs[0]
    if (
        spec.transform_ref != EXECUTION_SAFE_RETURN_REF
        or spec.output.logical_type != "float64"
        or spec.input_canonical_fields != ("open", "close")
    ):
        raise TradingAuthorityError(
            "trading evaluation requires execution-safe "
            "forward_open_to_close_return Label semantics"
        )

    try:
        rebuilt = build_experiment_dataset(
            fresh,
            label_field=bundle.label_name,
            feature_fields=bundle.feature_names,
        )
    except ExperimentMetadataError as exc:
        raise TradingAuthorityError(
            "Experiment Dataset rebuild failed"
        ) from exc
    if rebuilt != bundle:
        raise TradingAuthorityError(
            "Experiment Dataset differs from the verified Research Dataset"
        )

    return fresh, rebuilt
