"""Typed logical declarations and the join-only immutable result boundary."""

from dataclasses import dataclass, fields
from datetime import date, datetime

from ..canonical.reader import VerifiedCanonicalBuild
from ..cross_day.assembly import CrossDayLabelAssemblyResult
from ..cross_day.execution import CrossDayLabelExecutionResult
from ..cross_day.schedule import VerifiedTradingDaySchedule
from ..dataset.models import DatasetScope, DatasetSchema, CanonicalBuildPin, GapReference
from ..dataset.pit_models import PITAssemblyResult, PITSampleRequest
from ..dataset.pit_identity import pit_sample_key
from ..dataset.encoding import encode_identity
from ..dataset.split_models import ChronologicalSplitResult
from ..multi_source.feature_models import ObservationFeatureExecutionResult
from ..multi_source.feature_spec_models import ObservationFeatureSpec
from ..observation.artifact_models import VerifiedObservationBuild
from ..observation.pit_models import ObservationPITAssemblyResult, ObservationBuildPin
from ..ts2_feature.models import TS2FeatureExecutionResult
from ._validation import MultiSourceCrossDayDatasetError, cutoff, digest, require


@dataclass(frozen=True, slots=True)
class MultiSourceCrossDaySampleAudit:
    sample_key: str
    bar_sample_version_id: str
    multi_source_sample_version_id: str
    code: str
    interval: str
    adjustment: str
    requested_session: str
    anchor_market_calendar_date: date
    feature_window_start: datetime
    feature_window_close: datetime
    dataset_as_of: datetime | None
    feature_association_schema_id: str
    feature_association_content_id: str
    ts2_sample_id: str
    ts2_values_content_id: str
    observation_binding_id: str
    observation_values_content_id: str
    cross_day_sample_binding_id: str
    cross_day_values_content_id: str
    schedule_pin_id: str
    ts2_feature_status: str
    observation_feature_status: str
    label_status: str
    actual_label_end_time: datetime | None
    matrix_eligible: bool
    matrix_present: bool
    split_feature_window_close_date: date | None
    split_nominal_split: str | None
    split_final_split: str | None
    split_assignment_status: str | None
    split_reason_code: str | None
    split_purge_boundary: datetime | None

    def __post_init__(self):
        code = "IDENTITY_AUTHORITY"
        for name in ("sample_key", "bar_sample_version_id", "multi_source_sample_version_id",
                     "feature_association_schema_id", "feature_association_content_id", "ts2_sample_id",
                     "ts2_values_content_id", "observation_binding_id", "observation_values_content_id",
                     "cross_day_sample_binding_id", "cross_day_values_content_id", "schedule_pin_id"):
            digest(getattr(self, name))
        for name in ("feature_window_start", "feature_window_close", "dataset_as_of",
                     "actual_label_end_time", "split_purge_boundary"):
            object.__setattr__(self, name, cutoff(getattr(self, name)))
        require(type(self.anchor_market_calendar_date) is date, code, "exact audit anchor date required")
        request = PITSampleRequest(self.code, self.interval, self.adjustment, self.requested_session,
                                  self.anchor_market_calendar_date, self.feature_window_start, self.feature_window_close,
                                  None, None)
        require(pit_sample_key(request) == self.sample_key, code, "audit/PIT sample key mismatch")
        require(self.ts2_feature_status in ("COMPLETE", "EXCLUDED")
                and self.observation_feature_status in ("COMPLETE", "EXCLUDED")
                and self.label_status in ("COMPLETE", "INCOMPLETE"), code, "invalid audit status")
        eligible = self.ts2_feature_status == self.observation_feature_status == "COMPLETE"
        require(type(self.matrix_eligible) is bool and type(self.matrix_present) is bool
                and self.matrix_eligible == self.matrix_present == eligible, "MATRIX_ELIGIBILITY", "audit eligibility mismatch")
        split = (self.split_feature_window_close_date, self.split_nominal_split, self.split_final_split,
                 self.split_assignment_status, self.split_reason_code, self.split_purge_boundary)
        require((not eligible and split == (None,) * 6) or
                (eligible and type(split[0]) is date and split[3] in ("ASSIGNED", "PURGED", "EXCLUDED")),
                "SPLIT_BINDING", "audit split presence mismatch")
        encode_identity("multi-source-cross-day-sample-audit-v1", {f.name: getattr(self, f.name) for f in fields(self)})


COMPLETION_REASONS = frozenset(("FEATURE_EXCLUDED_AND_CROSS_DAY_LABEL_INCOMPLETE",
    "TS2_AND_OBSERVATION_FEATURE_EXCLUDED", "TS2_FEATURE_EXCLUDED", "OBSERVATION_FEATURE_EXCLUDED",
    "CROSS_DAY_LABEL_INCOMPLETE"))


@dataclass(frozen=True, slots=True)
class MultiSourceCrossDayCompletionEntry:
    code: str
    trade_date: date
    status: str
    reason_code: str | None

    def __post_init__(self):
        require(type(self.code) is str and self.code.startswith("US.") and type(self.trade_date) is date,
                "SCOPE", "invalid completion scope")
        require((self.status == "COMPLETE" and self.reason_code is None)
                or (self.status == "MISSING" and self.reason_code == "NO_SAMPLE_REQUEST")
                or (self.status == "INCOMPLETE" and self.reason_code in COMPLETION_REASONS),
                "IDENTITY_AUTHORITY", "invalid completion outcome")


@dataclass(frozen=True, slots=True)
class MultiSourceCrossDayCompletionSummary:
    complete_count: int
    incomplete_count: int
    missing_count: int
    entries: tuple[MultiSourceCrossDayCompletionEntry, ...]

    def __post_init__(self):
        require(type(self.entries) is tuple and all(type(e) is MultiSourceCrossDayCompletionEntry for e in self.entries),
                "INPUT_TYPE", "exact immutable completion entries required")
        keys = tuple((e.code, e.trade_date) for e in self.entries)
        require(keys == tuple(sorted(set(keys))), "DUPLICATE_INPUT", "completion keys must be unique and ordered")
        counts = (self.complete_count, self.incomplete_count, self.missing_count)
        require(all(type(n) is int and n >= 0 for n in counts) and counts ==
                tuple(sum(e.status == s for e in self.entries) for s in ("COMPLETE", "INCOMPLETE", "MISSING")),
                "IDENTITY_AUTHORITY", "completion counts differ")


@dataclass(frozen=True, slots=True)
class MultiSourceCrossDayDatasetIdentityInput:
    scope: DatasetScope
    dataset_as_of: datetime | None
    schema: DatasetSchema
    rows: tuple[tuple, ...]
    canonical_builds: tuple[VerifiedCanonicalBuild, ...]
    canonical_build_pins: tuple[CanonicalBuildPin, ...]
    gap_references: tuple[GapReference, ...]
    feature_pit: PITAssemblyResult
    ts2_features: TS2FeatureExecutionResult
    observation_pit: ObservationPITAssemblyResult
    observation_builds: tuple[VerifiedObservationBuild, ...]
    observation_input_proofs: tuple[ObservationBuildPin, ...]
    observation_feature_specs: tuple[ObservationFeatureSpec, ...]
    observation_features: ObservationFeatureExecutionResult
    cross_day_association: CrossDayLabelAssemblyResult
    cross_day_labels: CrossDayLabelExecutionResult
    schedule: VerifiedTradingDaySchedule
    split_result: ChronologicalSplitResult
    sample_audit: tuple[MultiSourceCrossDaySampleAudit, ...]
    completion: MultiSourceCrossDayCompletionSummary


@dataclass(frozen=True, slots=True, init=False)
class MultiSourceCrossDayDatasetResult:
    identity_input: MultiSourceCrossDayDatasetIdentityInput
    dataset_id: str
    scope: DatasetScope
    dataset_as_of: datetime | None
    schema: DatasetSchema
    rows: tuple[tuple, ...]
    sample_audit: tuple[MultiSourceCrossDaySampleAudit, ...]
    completion: MultiSourceCrossDayCompletionSummary
    split_result: ChronologicalSplitResult
    feature_pit: PITAssemblyResult
    ts2_features: TS2FeatureExecutionResult
    observation_pit: ObservationPITAssemblyResult
    observation_builds: tuple[VerifiedObservationBuild, ...]
    observation_feature_specs: tuple[ObservationFeatureSpec, ...]
    observation_features: ObservationFeatureExecutionResult
    cross_day_association: CrossDayLabelAssemblyResult
    cross_day_labels: CrossDayLabelExecutionResult
    schedule: VerifiedTradingDaySchedule
    status: str

    def __new__(cls, *args, **kwargs):
        raise MultiSourceCrossDayDatasetError("RESULT_AUTHORITY", "join_multi_source_cross_day_dataset is the sole issuer")
