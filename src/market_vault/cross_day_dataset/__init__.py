"""Parallel pure Cross-Day Dataset join and explicit generator. No artifact API."""

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

__all__ = [
    "CrossDayAnchor", "generate_cross_day_feature_requests", "MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION",
    "MultiSourceCrossDayDatasetError", "join_multi_source_cross_day_dataset",
    "MultiSourceCrossDayDatasetIdentityInput", "MultiSourceCrossDayDatasetResult",
    "MultiSourceCrossDaySampleAudit", "MultiSourceCrossDayCompletionEntry", "MultiSourceCrossDayCompletionSummary",
    "MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION", "MULTI_SOURCE_CROSS_DAY_DATASET_ORCHESTRATION_CONTRACT_VERSION",
    "MULTI_SOURCE_CROSS_DAY_SAMPLE_AUDIT_VERSION", "cross_day_dataset_sequence_id",
    "multi_source_cross_day_dataset_id", "multi_source_cross_day_sample_audit_id",
    "multi_source_cross_day_completion_entry_id", "multi_source_cross_day_completion_content_id",
]
