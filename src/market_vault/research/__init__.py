"""Research-facing standard Label library.

This package contains thin, deterministic research-spec helpers only. The
actual Label formulas and Cross-Day execution authority remain in the existing
dataset/cross_day layers.
"""

from .labels import (
    RESEARCH_LABEL_LIBRARY_VERSION,
    STANDARD_LABEL_HORIZONS,
    forward_direction_label,
    forward_open_to_close_return_label,
    forward_return_label,
    label_preset,
    label_preset_names,
    maximum_adverse_excursion_label,
    maximum_favorable_excursion_label,
)

__all__ = [
    "RESEARCH_LABEL_LIBRARY_VERSION",
    "STANDARD_LABEL_HORIZONS",
    "forward_direction_label",
    "forward_open_to_close_return_label",
    "forward_return_label",
    "label_preset",
    "label_preset_names",
    "maximum_adverse_excursion_label",
    "maximum_favorable_excursion_label",
]

from .ml import (
    ML_DATASET_ADAPTER_VERSION,
    ML_SPLITS,
    MLDatasetBundle,
    MLDatasetError,
    MLDatasetSplit,
    MLSampleMetadata,
    build_ml_dataset,
)

__all__ += [
    "ML_DATASET_ADAPTER_VERSION",
    "ML_SPLITS",
    "MLDatasetBundle",
    "MLDatasetError",
    "MLDatasetSplit",
    "MLSampleMetadata",
    "build_ml_dataset",
]

from .feature_research import (
    FEATURE_RESEARCH_VERSION,
    FeatureResearchError,
    FeatureResearchMetric,
    FeatureResearchReport,
    analyze_features,
)

__all__ += [
    "FEATURE_RESEARCH_VERSION",
    "FeatureResearchError",
    "FeatureResearchMetric",
    "FeatureResearchReport",
    "analyze_features",
]

from .feature_stability import (
    FEATURE_STABILITY_VERSION,
    FeatureStabilityError,
    FeatureStabilityMetric,
    FeatureStabilityReport,
    compare_feature_stability,
)

__all__ += [
    "FEATURE_STABILITY_VERSION",
    "FeatureStabilityError",
    "FeatureStabilityMetric",
    "FeatureStabilityReport",
    "compare_feature_stability",
]

from .feature_selection import (
    FEATURE_SELECTION_VERSION,
    FeatureSelectionDecision,
    FeatureSelectionError,
    FeatureSelectionPolicy,
    FeatureSelectionReport,
    select_features,
)

__all__ += [
    "FEATURE_SELECTION_VERSION",
    "FeatureSelectionDecision",
    "FeatureSelectionError",
    "FeatureSelectionPolicy",
    "FeatureSelectionReport",
    "select_features",
]

from .experiment import (
    EXPERIMENT_METADATA_VERSION,
    ExperimentDatasetBundle,
    ExperimentMetadataError,
    ExperimentSampleMetadata,
    ExperimentSplit,
    build_experiment_dataset,
)

__all__ += [
    "EXPERIMENT_METADATA_VERSION",
    "ExperimentDatasetBundle",
    "ExperimentMetadataError",
    "ExperimentSampleMetadata",
    "ExperimentSplit",
    "build_experiment_dataset",
]

from .walk_forward import (
    WALK_FORWARD_VERSION,
    WalkForwardError,
    WalkForwardFold,
    WalkForwardPlan,
    WalkForwardSlice,
    build_walk_forward_plan,
)

__all__ += [
    "WALK_FORWARD_VERSION",
    "WalkForwardError",
    "WalkForwardFold",
    "WalkForwardPlan",
    "WalkForwardSlice",
    "build_walk_forward_plan",
]

from .ridge_baseline import (
    RIDGE_BASELINE_VERSION,
    RidgeBaselineError,
    RidgeBaselineReport,
    RidgeFoldResult,
    evaluate_ridge_baseline,
)

__all__ += [
    "RIDGE_BASELINE_VERSION",
    "RidgeBaselineError",
    "RidgeBaselineReport",
    "RidgeFoldResult",
    "evaluate_ridge_baseline",
]


from .ridge_selection import (
    RIDGE_ALPHA_SELECTION_METRIC,
    RIDGE_ALPHA_SELECTION_VERSION,
    RidgeAlphaCandidate,
    RidgeAlphaSelectionError,
    RidgeAlphaSelectionResult,
    select_ridge_alpha,
)

__all__ += [
    "RIDGE_ALPHA_SELECTION_METRIC",
    "RIDGE_ALPHA_SELECTION_VERSION",
    "RidgeAlphaCandidate",
    "RidgeAlphaSelectionError",
    "RidgeAlphaSelectionResult",
    "select_ridge_alpha",
]


from .ridge_final_test import (
    RIDGE_FINAL_TEST_VERSION,
    RidgeFinalTestError,
    RidgeFinalTestPrediction,
    RidgeFinalTestResult,
    evaluate_ridge_final_test,
)

__all__ += [
    "RIDGE_FINAL_TEST_VERSION",
    "RidgeFinalTestError",
    "RidgeFinalTestPrediction",
    "RidgeFinalTestResult",
    "evaluate_ridge_final_test",
]


from .ridge_final_trading import (
    RIDGE_FINAL_TRADING_SIGNAL_RULE,
    RIDGE_FINAL_TRADING_VERSION,
    RidgeFinalTradingError,
    RidgeFinalTradingMetrics,
    RidgeFinalTradingResult,
    RidgeFinalTradingTrade,
    evaluate_ridge_final_trading,
)

__all__ += [
    "RIDGE_FINAL_TRADING_SIGNAL_RULE",
    "RIDGE_FINAL_TRADING_VERSION",
    "RidgeFinalTradingError",
    "RidgeFinalTradingMetrics",
    "RidgeFinalTradingResult",
    "RidgeFinalTradingTrade",
    "evaluate_ridge_final_trading",
]


from .ridge_trading_selection import (
    RIDGE_TRADING_THRESHOLD_SELECTION_METRIC,
    RIDGE_TRADING_THRESHOLD_SELECTION_VERSION,
    RidgeTradingThresholdCandidate,
    RidgeTradingThresholdSelectionError,
    RidgeTradingThresholdSelectionResult,
    RidgeValidationTradingPrediction,
    select_ridge_trading_threshold,
)

__all__ += [
    "RIDGE_TRADING_THRESHOLD_SELECTION_METRIC",
    "RIDGE_TRADING_THRESHOLD_SELECTION_VERSION",
    "RidgeTradingThresholdCandidate",
    "RidgeTradingThresholdSelectionError",
    "RidgeTradingThresholdSelectionResult",
    "RidgeValidationTradingPrediction",
    "select_ridge_trading_threshold",
]


from .ridge_selected_final_trading import (
    RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
    RIDGE_SELECTED_FINAL_TRADING_VERSION,
    RidgeSelectedFinalTradingError,
    RidgeSelectedFinalTradingResult,
    RidgeSelectedFinalTradingTrade,
    evaluate_ridge_selected_final_trading,
)

__all__ += [
    "RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE",
    "RIDGE_SELECTED_FINAL_TRADING_VERSION",
    "RidgeSelectedFinalTradingError",
    "RidgeSelectedFinalTradingResult",
    "RidgeSelectedFinalTradingTrade",
    "evaluate_ridge_selected_final_trading",
]

from .ridge_final_evaluation import (
    RIDGE_FINAL_EVALUATION_VERSION,
    RidgeFinalEvaluationDelta,
    RidgeFinalEvaluationError,
    RidgeFinalEvaluationReport,
    compare_ridge_final_trading,
)

__all__ += [
    "RIDGE_FINAL_EVALUATION_VERSION",
    "RidgeFinalEvaluationDelta",
    "RidgeFinalEvaluationError",
    "RidgeFinalEvaluationReport",
    "compare_ridge_final_trading",
]
