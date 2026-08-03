"""Canonical dataset layer (ADR 0001).

The in-memory canonical market-bar builder core lives in
:mod:`market_vault.canonical.bars`; identity encodings in
:mod:`market_vault.canonical.identity`; data models in
:mod:`market_vault.canonical.models`. No materialization, features, labels,
samples, or datasets are implemented yet.
"""

from .bars import (
    CANONICAL_BUILDER_VERSION,
    DEFAULT_DATASET_KIND,
    build_canonical_market_bars,
)
from .identity import canonical_bar_key, canonical_row_version_id
from .models import (
    CanonicalBar,
    CanonicalBuildError,
    CanonicalBuildResult,
    CanonicalConflictError,
    CanonicalRequestKey,
    CanonicalResolutionEntry,
    CanonicalSnapshotInput,
    CanonicalSourceRef,
)

__all__ = [
    "CANONICAL_BUILDER_VERSION",
    "DEFAULT_DATASET_KIND",
    "CanonicalBar",
    "CanonicalBuildError",
    "CanonicalBuildResult",
    "CanonicalConflictError",
    "CanonicalRequestKey",
    "CanonicalResolutionEntry",
    "CanonicalSnapshotInput",
    "CanonicalSourceRef",
    "build_canonical_market_bars",
    "canonical_bar_key",
    "canonical_row_version_id",
]
