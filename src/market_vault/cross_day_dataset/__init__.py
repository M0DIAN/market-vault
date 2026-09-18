"""Parallel Cross-Day Dataset logical authorities and separately verified artifacts."""

from ._validation import MultiSourceCrossDayDatasetError
from .execution import join_multi_source_cross_day_dataset
from .generator import (
    CrossDayAnchor, generate_cross_day_feature_requests,
    MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION,
)
from .identity import (
    MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION,
    MULTI_SOURCE_CROSS_DAY_DATASET_ORCHESTRATION_CONTRACT_VERSION,
    MULTI_SOURCE_CROSS_DAY_SAMPLE_AUDIT_VERSION,
    cross_day_dataset_sequence_id,
    multi_source_cross_day_dataset_id,
    multi_source_cross_day_sample_audit_id,
    multi_source_cross_day_completion_entry_id,
    multi_source_cross_day_completion_content_id,
)
from .models import (
    MultiSourceCrossDayDatasetIdentityInput, MultiSourceCrossDayDatasetResult,
    MultiSourceCrossDaySampleAudit, MultiSourceCrossDayCompletionEntry,
    MultiSourceCrossDayCompletionSummary,
)
from .artifact_models import (
    MultiSourceCrossDayArtifactError, MultiSourceCrossDayDatasetMaterializationResult,
    VerifiedMultiSourceCrossDayDataset,
)
from .materialization import materialize_multi_source_cross_day_dataset_build
from .reader import load_verified_multi_source_cross_day_dataset

__all__ = [
    "CrossDayAnchor", "generate_cross_day_feature_requests", "MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION",
    "MultiSourceCrossDayDatasetError", "join_multi_source_cross_day_dataset",
    "MultiSourceCrossDayDatasetIdentityInput", "MultiSourceCrossDayDatasetResult",
    "MultiSourceCrossDaySampleAudit", "MultiSourceCrossDayCompletionEntry", "MultiSourceCrossDayCompletionSummary",
    "MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION", "MULTI_SOURCE_CROSS_DAY_DATASET_ORCHESTRATION_CONTRACT_VERSION",
    "MULTI_SOURCE_CROSS_DAY_SAMPLE_AUDIT_VERSION", "cross_day_dataset_sequence_id",
    "multi_source_cross_day_dataset_id", "multi_source_cross_day_sample_audit_id",
    "multi_source_cross_day_completion_entry_id", "multi_source_cross_day_completion_content_id",
    "MultiSourceCrossDayArtifactError", "MultiSourceCrossDayDatasetMaterializationResult",
    "VerifiedMultiSourceCrossDayDataset", "materialize_multi_source_cross_day_dataset_build",
    "load_verified_multi_source_cross_day_dataset",
]
