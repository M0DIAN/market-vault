"""Immutable A2 results; declarations alone do not confer artifact trust."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from ._validation import ObservationError
from .models import (
    Observation, ObservationContractPin, ObservationCoverage,
    ObservationSourceSnapshotInput,
)


class ObservationArtifactError(ObservationError):
    """An Observation artifact failed admission or physical verification."""


class ObservationMaterializationError(ObservationArtifactError):
    """An immutable build could not be safely materialized."""


@dataclass(frozen=True, slots=True, init=False)
class VerifiedObservationBuild:
    """Read-only result issued only by the formal verified reader."""

    observation_build_id: str
    observation_content_id: str
    status: str
    rows: tuple[Observation, ...]
    source_snapshots: tuple[ObservationSourceSnapshotInput, ...]
    authority_evidence_ids: tuple[str, ...]
    provider_contracts: tuple[ObservationContractPin, ...]
    normalizations: tuple[ObservationContractPin, ...]
    coverage: ObservationCoverage
    created_at: datetime
    manifest_payload: Mapping
    build_dir: Path

    def __init__(self, *args, **kwargs):
        raise TypeError("use load_verified_observation_build")


@dataclass(frozen=True, slots=True)
class ObservationMaterializationResult:
    verified_build: VerifiedObservationBuild
    created_new_build: bool

    @property
    def build_dir(self) -> Path:
        return self.verified_build.build_dir

    @property
    def observation_build_id(self) -> str:
        return self.verified_build.observation_build_id

    @property
    def observation_content_id(self) -> str:
        return self.verified_build.observation_content_id
