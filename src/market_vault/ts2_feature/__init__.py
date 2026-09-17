"""Parallel TS2-only Feature authority; no Dataset or provider integration."""

from ._validation import TS2FeatureError
from .execution import execute_ts2_features
from .models import TS2FeatureExecutionResult, TS2FeatureSampleResult, TS2FeatureValueResult
from .registry import (
    TS2_FEATURE_REGISTRY_CONTRACT_VERSION,
    TS2_FEATURE_EXECUTION_CONTRACT_VERSION,
    TS2_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION,
    TS2_FEATURE_IMPLEMENTATION_FINGERPRINT_VERSION,
)

__all__ = [
    "execute_ts2_features", "TS2FeatureError", "TS2FeatureExecutionResult",
    "TS2FeatureSampleResult", "TS2FeatureValueResult",
    "TS2_FEATURE_REGISTRY_CONTRACT_VERSION", "TS2_FEATURE_EXECUTION_CONTRACT_VERSION",
    "TS2_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION", "TS2_FEATURE_IMPLEMENTATION_FINGERPRINT_VERSION",
]
