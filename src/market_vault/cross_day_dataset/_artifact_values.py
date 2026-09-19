"""Convert only closed, non-issuance value records for existing pure validators.

No assembly/execution/build/result type is admitted by this table. In particular,
the reader can never manufacture an upstream live result to borrow its authority.
"""

from types import MappingProxyType
from struct import pack

from ..canonical.reader import VerifiedCanonicalRequest, GapBoundaryBars
from ..canonical.gaps import GapRange
from ..dataset.models import DatasetScope, DatasetSchema, DatasetField, SpecPin, ImplementationPin
from ..dataset.models import CanonicalBuildPin, SourceSnapshotPin, GapReference
from ..dataset.spec_models import (
    FeatureSpec, LabelSpec, SpecParameter, SpecVersionRequirements,
    LabelObservationWindow, LabelHorizon, CrossTradingDayPolicy,
)
from ..dataset.split_models import ChronologicalSplitSpec, ChronologicalSplitAssignment, ChronologicalSplitDiagnostics
from ..dataset.pit_models import PITSampleRequest, PITDiagnostics, PITAssemblyDiagnostics, PITSample
from ..observation.models import (
    Observation, ObservationScope, ObservationDimension, ObservationContractPin,
    ObservationCoverage, ObservationBuildIdentityInput, ObservationSourceSnapshotInput, ObservationSnapshotMember,
)
from ..observation.schema import ObservationValueSchema, ObservationValueField
from ..observation.pit_models import (
    ObservationSourceSpec, ObservationPITFeatureBinding, ObservationPITDecision,
    ObservationDecisionEvidence, ObservationBuildPin, ObservationSnapshotPin, ObservationSampleBinding,
)
from ..multi_source.feature_spec_models import ObservationFeatureSpec
from ..cross_day.models import (
    CrossDayLabelDecision, CrossDayLabelGapProof, CrossDayLabelRowReference,
    CrossDayLabelSampleBinding, CrossDayLabelSlot, CrossDayLabelValueResult,
)
from ..cross_day.schedule import TradingDayRecord, VerifiedTradingDaySchedule
from .models import MultiSourceCrossDaySampleAudit, MultiSourceCrossDayCompletionEntry, MultiSourceCrossDayCompletionSummary
from ._artifact_records import _Recorded, _SCHEMAS, _encode_record
from .artifact_models import _require


_VALUE_TYPES = MappingProxyType({
    "VerifiedCanonicalRequest": VerifiedCanonicalRequest, "GapBoundaryBars": GapBoundaryBars, "GapRange": GapRange,
    "DatasetScope": DatasetScope, "DatasetSchema": DatasetSchema, "DatasetField": DatasetField,
    "SpecPin": SpecPin, "ImplementationPin": ImplementationPin, "CanonicalBuildPin": CanonicalBuildPin,
    "SourceSnapshotPin": SourceSnapshotPin, "GapReference": GapReference,
    "FeatureSpec": FeatureSpec, "LabelSpec": LabelSpec, "SpecParameter": SpecParameter,
    "SpecVersionRequirements": SpecVersionRequirements, "LabelObservationWindow": LabelObservationWindow,
    "LabelHorizon": LabelHorizon, "CrossTradingDayPolicy": CrossTradingDayPolicy,
    "ChronologicalSplitSpec": ChronologicalSplitSpec, "ChronologicalSplitAssignment": ChronologicalSplitAssignment,
    "ChronologicalSplitDiagnostics": ChronologicalSplitDiagnostics,
    "PITSampleRequest": PITSampleRequest, "PITDiagnostics": PITDiagnostics,
    "PITAssemblyDiagnostics": PITAssemblyDiagnostics, "PITSample": PITSample,
    "Observation": Observation, "ObservationScope": ObservationScope, "ObservationDimension": ObservationDimension,
    "ObservationContractPin": ObservationContractPin, "ObservationCoverage": ObservationCoverage,
    "ObservationBuildIdentityInput": ObservationBuildIdentityInput,
    "ObservationSourceSnapshotInput": ObservationSourceSnapshotInput, "ObservationSnapshotMember": ObservationSnapshotMember,
    "ObservationValueSchema": ObservationValueSchema, "ObservationValueField": ObservationValueField,
    "ObservationSourceSpec": ObservationSourceSpec, "ObservationPITFeatureBinding": ObservationPITFeatureBinding,
    "ObservationPITDecision": ObservationPITDecision, "ObservationDecisionEvidence": ObservationDecisionEvidence,
    "ObservationBuildPin": ObservationBuildPin, "ObservationSnapshotPin": ObservationSnapshotPin,
    "ObservationSampleBinding": ObservationSampleBinding, "ObservationFeatureSpec": ObservationFeatureSpec,
    "CrossDayLabelDecision": CrossDayLabelDecision, "CrossDayLabelGapProof": CrossDayLabelGapProof,
    "CrossDayLabelRowReference": CrossDayLabelRowReference, "CrossDayLabelSampleBinding": CrossDayLabelSampleBinding,
    "CrossDayLabelSlot": CrossDayLabelSlot, "CrossDayLabelValueResult": CrossDayLabelValueResult,
    "TradingDayRecord": TradingDayRecord, "VerifiedTradingDaySchedule": VerifiedTradingDaySchedule,
    "MultiSourceCrossDaySampleAudit": MultiSourceCrossDaySampleAudit,
    "MultiSourceCrossDayCompletionEntry": MultiSourceCrossDayCompletionEntry,
    "MultiSourceCrossDayCompletionSummary": MultiSourceCrossDayCompletionSummary,
})
_DERIVED = MappingProxyType({
    "FeatureSpec": ("kind",), "LabelSpec": ("kind",), "ChronologicalSplitSpec": ("kind",),
    "ObservationFeatureSpec": ("kind",),
    "Observation": ("value_schema_id", "observation_key", "observation_version_id"),
    "ObservationPITFeatureBinding": ("feature_spec_pin_id", "observation_source_spec_id"),
})


def _same_value(actual, recorded):
    if type(actual) is not type(recorded):
        return False
    if type(actual) is float:
        return pack(">d", actual) == pack(">d", recorded)
    if type(actual) is tuple:
        return len(actual) == len(recorded) and all(_same_value(a, b) for a, b in zip(actual, recorded))
    return actual == recorded


def _value(record):
    """Apply pure value-model validation, never confer live issuance."""
    _require(type(record) is _Recorded and record._schema_name in _VALUE_TYPES,
             "ARTIFACT_AUTHORITY", "record is not an admitted non-issuance value")
    kind = record._schema_name
    _encode_record(record, kind)

    def convert(value):
        if type(value) is _Recorded:
            return _value(value)
        if type(value) is tuple:
            return tuple(convert(v) for v in value)
        return value

    values = {name: convert(value) for name, value in record._items}
    result = _VALUE_TYPES[kind](**{name: value for name, value in values.items() if name not in _DERIVED.get(kind, ())})
    _require(all(_same_value(getattr(result, name), value) for name, value in values.items()),
             "ARTIFACT_AUTHORITY", "recorded value normalization/derived identity differs")
    return result
