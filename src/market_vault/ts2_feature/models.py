"""Read-only issued records. Public construction is deliberately unavailable."""

from dataclasses import dataclass
from datetime import datetime

from ..dataset.models import SpecPin, ImplementationPin
from ..dataset.spec_models import FeatureSpec
from ._validation import TS2FeatureError
from . import identity as ids
from .registry import TS2_FEATURE_EXECUTION_CONTRACT_VERSION


class _Issued:
    __slots__ = ()

    def __new__(cls, *args, **kwargs):
        raise TS2FeatureError("RESULT_AUTHORITY", "execute_ts2_features is the sole issuer")


@dataclass(frozen=True, slots=True, init=False)
class TS2FeatureValueResult(_Issued):
    sample_key: str
    bar_sample_version_id: str
    feature_name: str
    spec_pin: SpecPin
    implementation_pin: ImplementationPin
    feature_window_close: datetime
    dataset_as_of: datetime | None
    considered_canonical_build_ids: tuple[str, ...]
    candidate_canonical_row_version_ids: tuple[str, ...]
    consumed_canonical_row_version_ids: tuple[str, ...]
    status: str
    value: float | None
    reason_code: str | None

    @property
    def value_id(self):
        return ids.value_id(dict(
            execution_contract_version=TS2_FEATURE_EXECUTION_CONTRACT_VERSION,
            sample_key=self.sample_key, bar_sample_version_id=self.bar_sample_version_id,
            feature_name=self.feature_name, feature_spec_pin_id=ids.spec_pin_id(self.spec_pin),
            implementation_pin_id=ids.implementation_pin_id(self.implementation_pin),
            feature_window_close=self.feature_window_close, dataset_as_of=self.dataset_as_of,
            considered_canonical_build_ids_digest=ids.considered_builds_digest(self.considered_canonical_build_ids),
            candidate_row_version_ids_digest=ids.input_rows_digest(self.candidate_canonical_row_version_ids),
            consumed_row_version_ids_digest=ids.input_rows_digest(self.consumed_canonical_row_version_ids),
            status=self.status, value=self.value, reason_code=self.reason_code))


@dataclass(frozen=True, slots=True, init=False)
class TS2FeatureSampleResult(_Issued):
    sample_key: str
    bar_sample_version_id: str
    values: tuple[TS2FeatureValueResult, ...]
    status: str

    @property
    def values_content_id(self):
        return ids.values_content_id(self.values)

    @property
    def sample_id(self):
        return ids.sample_id(dict(sample_key=self.sample_key, bar_sample_version_id=self.bar_sample_version_id,
                                  status=self.status, values_content_id=self.values_content_id))


@dataclass(frozen=True, slots=True, init=False)
class TS2FeatureExecutionResult(_Issued):
    execution_contract_version: str
    registry_contract_version: str
    feature_association_content_id: str
    feature_association_schema_id: str
    dataset_as_of: datetime | None
    considered_canonical_build_ids: tuple[str, ...]
    feature_specs: tuple[FeatureSpec, ...]
    feature_spec_pins: tuple[SpecPin, ...]
    registry_implementation_pins: tuple[ImplementationPin, ...]
    samples: tuple[TS2FeatureSampleResult, ...]
    status: str

    @property
    def sample_count(self):
        return len(self.samples)

    @property
    def feature_count(self):
        return len(self.feature_specs)

    @property
    def values_content_id(self):
        return ids.values_content_id(tuple(v for s in self.samples for v in s.values))

    @property
    def samples_content_id(self):
        return ids.samples_content_id(self.samples)

    @property
    def execution_id(self):
        return ids.execution_id(dict(
            execution_contract_version=self.execution_contract_version, registry_contract_version=self.registry_contract_version,
            feature_association_content_id=self.feature_association_content_id,
            feature_association_schema_id=self.feature_association_schema_id, dataset_as_of=self.dataset_as_of,
            considered_canonical_build_ids_digest=ids.considered_builds_digest(self.considered_canonical_build_ids),
            feature_spec_pins_digest=ids.spec_pins_digest(self.feature_spec_pins),
            registry_implementation_pins_digest=ids.registry_pins_digest(self.registry_implementation_pins),
            sample_count=self.sample_count, feature_count=self.feature_count, status=self.status,
            values_content_id=self.values_content_id, samples_content_id=self.samples_content_id))
