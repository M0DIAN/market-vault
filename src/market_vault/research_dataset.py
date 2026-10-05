"""High-level Research Dataset Builder V1.

This module is intentionally a thin composition layer over the already
validated MarketVault research-data authorities. It performs no artifact
discovery, no latest selection, no OpenD/network access, and no current-time
lookup. Every upstream build, schedule, spec, clock and output path is supplied
explicitly by the caller.

The builder connects the existing pipeline in one call:

Cross-Day request generation -> PIT assembly -> TS2 Feature execution
-> Observation PIT/Feature execution -> Cross-Day Label execution
-> Multi-Source Cross-Day Dataset join -> immutable Dataset materialization.

All validation and identity authority remains in the existing component layers;
this module does not duplicate their algorithms or weaken their fail-closed
behavior.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .canonical.reader import VerifiedCanonicalBuild
from .cross_day import (
    VerifiedTradingDaySchedule,
    assemble_cross_day_labels,
    execute_cross_day_labels,
)
from .cross_day_dataset import (
    CrossDayAnchor,
    generate_cross_day_feature_requests,
    join_multi_source_cross_day_dataset,
    materialize_multi_source_cross_day_dataset_build,
)
from .cross_day_dataset.artifact_models import (
    MultiSourceCrossDayDatasetMaterializationResult,
)
from .dataset.models import DatasetScope
from .dataset.pit import assemble_point_in_time_samples
from .dataset.spec_models import FeatureSpec, LabelSpec
from .dataset.split_models import ChronologicalSplitSpec
from .multi_source import (
    ObservationFeatureSpec,
    execute_observation_features,
    observation_feature_binding,
)
from .observation import VerifiedObservationBuild, assemble_observation_pit_sidecar
from .ts2_feature import execute_ts2_features


def build_research_dataset(
    *,
    feature_builds: tuple[VerifiedCanonicalBuild, ...],
    label_builds: tuple[VerifiedCanonicalBuild, ...],
    observation_builds: tuple[VerifiedObservationBuild, ...],
    schedule: VerifiedTradingDaySchedule,
    scope: DatasetScope,
    split_spec: ChronologicalSplitSpec,
    anchors: tuple[CrossDayAnchor, ...],
    ts2_feature_specs: tuple[FeatureSpec, ...],
    observation_feature_specs: tuple[ObservationFeatureSpec, ...],
    label_specs: tuple[LabelSpec, ...],
    feature_window_bars: int,
    dataset_as_of: datetime | None,
    output_root: str | Path,
    built_at: datetime,
) -> MultiSourceCrossDayDatasetMaterializationResult:
    """Build and materialize one PIT-safe research Dataset.

    The caller supplies explicit verified upstream authorities. No filesystem
    discovery is performed for inputs and no wall clock is consulted. Empty
    observation_builds / observation_feature_specs tuples are valid when the
    requested Dataset uses only TS2 market-bar Features.

    built_at is recorded only as artifact build metadata; it does not enter the
    logical Dataset identity.
    """

    requests = generate_cross_day_feature_requests(
        scope=scope,
        anchors=anchors,
        feature_window_bars=feature_window_bars,
        schedule=schedule,
        label_specs=label_specs,
        dataset_as_of=dataset_as_of,
    )
    feature_pit = assemble_point_in_time_samples(
        feature_builds,
        requests,
        dataset_as_of=dataset_as_of,
    )

    observation_pit = assemble_observation_pit_sidecar(
        feature_pit,
        observation_builds,
        tuple(observation_feature_binding(spec) for spec in observation_feature_specs),
    )
    observation_features = execute_observation_features(
        observation_pit,
        observation_builds,
        observation_feature_specs,
    )

    ts2_features = execute_ts2_features(
        feature_builds,
        feature_pit,
        ts2_feature_specs,
        dataset_as_of=dataset_as_of,
    )

    cross_day_association = assemble_cross_day_labels(
        feature_pit,
        feature_builds,
        label_builds,
        schedule,
        label_specs,
        dataset_as_of=dataset_as_of,
        observation_pit=observation_pit,
    )
    cross_day_labels = execute_cross_day_labels(cross_day_association)

    logical = join_multi_source_cross_day_dataset(
        feature_pit=feature_pit,
        ts2_features=ts2_features,
        observation_pit=observation_pit,
        observation_builds=observation_builds,
        observation_feature_specs=observation_feature_specs,
        observation_features=observation_features,
        cross_day_association=cross_day_association,
        cross_day_labels=cross_day_labels,
        schedule=schedule,
        scope=scope,
        split_spec=split_spec,
        dataset_as_of=dataset_as_of,
    )
    return materialize_multi_source_cross_day_dataset_build(
        logical,
        output_root=output_root,
        built_at=built_at,
    )
