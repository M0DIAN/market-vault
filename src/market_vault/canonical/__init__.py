"""Canonical dataset layer (ADR 0001).

The in-memory canonical market-bar builder core lives in
:mod:`market_vault.canonical.bars`; identity encodings in
:mod:`market_vault.canonical.identity`; the immutable build materialization
layer (explicit-schema Canonical Parquet, conservative gap sidecar,
resolution JSONL, immutable manifest, atomic commit, EMPTY builds) lives in
:mod:`market_vault.canonical.materialization` and
:mod:`market_vault.canonical.schema`; verified read-only access to committed
build artifacts lives in :mod:`market_vault.canonical.reader`. The
point-in-time sample association foundation exists in
:mod:`market_vault.dataset.pit`; Feature/Label transforms and exported
datasets are not implemented yet.
"""

from .bars import (
    CANONICAL_BUILDER_VERSION,
    DEFAULT_DATASET_KIND,
    build_canonical_market_bars,
)
from .gaps import GAP_POLICY_VERSION, derive_internal_gap_ranges
from .identity import (
    canonical_bar_key,
    canonical_build_id,
    canonical_content_id,
    canonical_row_version_id,
    gap_content_id,
    resolution_content_id,
)
from .manifest import MANIFEST_SCHEMA_VERSION
from .materialization import (
    load_canonical_snapshot_inputs,
    materialize_build_result,
    materialize_canonical_market_bars,
)
from .models import (
    CanonicalBar,
    CanonicalBuildError,
    CanonicalBuildResult,
    CanonicalConflictError,
    CanonicalGapArithmeticError,
    CanonicalMaterializationError,
    CanonicalMaterializationRequest,
    CanonicalMaterializationResult,
    CanonicalRequestKey,
    CanonicalResolutionEntry,
    CanonicalSnapshotInput,
    CanonicalSourceRef,
)
from .reader import (
    CanonicalArtifactValidationError,
    GapBoundaryBars,
    VerifiedCanonicalBuild,
    VerifiedCanonicalRequest,
    load_verified_canonical_build,
)
from .schema import (
    CANONICAL_MATERIALIZER_VERSION,
    CANONICAL_SCHEMA_VERSION,
    canonical_bars_schema,
)

__all__ = [
    "CANONICAL_BUILDER_VERSION",
    "CANONICAL_MATERIALIZER_VERSION",
    "CANONICAL_SCHEMA_VERSION",
    "DEFAULT_DATASET_KIND",
    "GAP_POLICY_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "CanonicalArtifactValidationError",
    "CanonicalBar",
    "CanonicalBuildError",
    "CanonicalBuildResult",
    "CanonicalConflictError",
    "CanonicalGapArithmeticError",
    "CanonicalMaterializationError",
    "CanonicalMaterializationRequest",
    "CanonicalMaterializationResult",
    "CanonicalRequestKey",
    "CanonicalResolutionEntry",
    "CanonicalSnapshotInput",
    "CanonicalSourceRef",
    "GapBoundaryBars",
    "VerifiedCanonicalBuild",
    "VerifiedCanonicalRequest",
    "build_canonical_market_bars",
    "canonical_bar_key",
    "canonical_build_id",
    "canonical_content_id",
    "canonical_row_version_id",
    "canonical_bars_schema",
    "derive_internal_gap_ranges",
    "gap_content_id",
    "load_canonical_snapshot_inputs",
    "load_verified_canonical_build",
    "materialize_build_result",
    "materialize_canonical_market_bars",
    "resolution_content_id",
]
