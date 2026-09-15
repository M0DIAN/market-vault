"""Immutable declarations and results for the parallel Observation PIT authority."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from ..dataset.encoding import DatasetError
from ..dataset.models import SpecPin
from ..dataset.pit_models import PITAssemblyError, _normalize_text
from ._validation import ObservationError, instant, items, sha256, text
from .models import ObservationContractPin, ObservationCoverage, ObservationDimension, ObservationScope

OBSERVATION_ASSOCIATION_SCHEMA_VERSION = "observation-association-v1"
OBSERVATION_SOURCE_SPEC_ID_VERSION = "observation-source-spec-v1"
OBSERVATION_FEATURE_SPEC_PIN_ID_VERSION = "observation-feature-spec-pin-v1"
OBSERVATION_BINDING_ID_VERSION = "observation-binding-v1"
MULTI_SOURCE_SAMPLE_VERSION_ID_VERSION = "multi-source-sample-version-v1"
MULTI_SOURCE_PIT_CONTRACT_VERSION = "multi-source-pit-v1"
OBSERVATION_SAMPLE_BINDING_SCHEMA_VERSION = "observation-sample-binding-v1"
OBSERVATION_SAMPLE_BINDING_CONTENT_ID_VERSION = "observation-sample-binding-content-v1"
OBSERVATION_ASSOCIATION_CONTENT_ID_VERSION = "observation-association-content-v1"


class ObservationPITError(ObservationError):
    """An A3 declaration, proof, or assembly failed closed."""


def _checked(check, value, label):
    try:
        return check(value, label)
    except (ObservationError, DatasetError) as exc:
        raise ObservationPITError(str(exc)) from exc


def _hash_tuple(value, label):
    values = _checked(lambda v, n: items(v, str, n), value, label)
    for item in values:
        _checked(sha256, item, label)
    if len(set(values)) != len(values):
        raise ObservationPITError("duplicate " + label)
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class ObservationSourceSpec:
    provider_id: str
    source_kind: str
    observation_name: str
    dimensions: tuple[ObservationDimension, ...]
    entity_binding: str
    entity_id: str | None
    code_entity_map: tuple[tuple[str, str], ...]
    input_field_names: tuple[str, ...]
    value_schema_id: str
    provider_contract_version: str
    provider_contract_content_id: str
    normalization_version: str
    normalization_content_id: str
    known_at_authority_policy_version: str
    known_at_authority_policy_content_id: str
    alignment: str
    exact_target_binding: str | None
    max_age_us: int
    missing_policy: str

    def __post_init__(self):
        try:
            self._normalize()
        except ObservationPITError:
            raise
        except (ObservationError, DatasetError, PITAssemblyError) as exc:
            raise ObservationPITError(str(exc)) from exc

    def _normalize(self):
        for name in ("provider_id", "source_kind", "observation_name",
                     "provider_contract_version", "normalization_version",
                     "known_at_authority_policy_version"):
            object.__setattr__(self, name, text(getattr(self, name), name))
        for name in ("value_schema_id", "provider_contract_content_id",
                     "normalization_content_id", "known_at_authority_policy_content_id"):
            sha256(getattr(self, name), name)
        dims = tuple(replace(d) for d in items(self.dimensions, ObservationDimension, "dimensions"))
        if len({d.name for d in dims}) != len(dims):
            raise ObservationPITError("duplicate dimension names")
        object.__setattr__(self, "dimensions", tuple(sorted(dims, key=lambda d: d.name)))
        if not isinstance(self.code_entity_map, (tuple, list)):
            raise ObservationPITError("code_entity_map requires explicit entries")
        mapping = []
        for entry in self.code_entity_map:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise ObservationPITError("invalid code mapping entry")
            mapping.append((_normalize_text(entry[0], "code", upper=True), text(entry[1], "entity_id")))
        if len({c for c, _ in mapping}) != len(mapping):
            raise ObservationPITError("duplicate normalized code")
        object.__setattr__(self, "code_entity_map", tuple(sorted(mapping)))
        if self.entity_binding == "EXACT_ENTITY":
            object.__setattr__(self, "entity_id", text(self.entity_id, "entity_id"))
            if mapping:
                raise ObservationPITError("EXACT_ENTITY requires an empty code map")
        elif self.entity_binding == "SAMPLE_CODE":
            if self.entity_id is not None or not mapping:
                raise ObservationPITError("SAMPLE_CODE requires null entity and nonempty map")
        else:
            raise ObservationPITError("unknown entity binding")
        names = tuple(text(n, "input field") for n in items(self.input_field_names, str, "input fields", nonempty=True))
        if len(set(names)) != len(names):
            raise ObservationPITError("duplicate input fields")
        object.__setattr__(self, "input_field_names", names)
        if self.alignment == "EXACT_EVENT_TIME":
            if self.exact_target_binding not in ("FEATURE_WINDOW_CLOSE", "FEATURE_WINDOW_START"):
                raise ObservationPITError("exact alignment requires a target binding")
        elif self.alignment == "LATEST_EFFECTIVE_AT_OR_BEFORE":
            if self.exact_target_binding is not None:
                raise ObservationPITError("latest alignment requires null target")
        else:
            raise ObservationPITError("unknown alignment")
        if type(self.max_age_us) is not int or self.max_age_us <= 0:
            raise ObservationPITError("max_age_us requires a positive integer, not bool")
        try:
            timedelta(microseconds=self.max_age_us)
        except OverflowError as exc:
            raise ObservationPITError("unrepresentable max_age_us") from exc
        if self.missing_policy not in ("EXCLUDE_SAMPLE", "FAIL"):
            raise ObservationPITError("unknown missing policy")

    def scope(self, entity_id):
        return ObservationScope(self.provider_id, self.source_kind, entity_id,
                                self.observation_name, self.dimensions)


@dataclass(frozen=True, slots=True)
class ObservationPITFeatureBinding:
    feature_spec_pin: SpecPin
    source_spec: ObservationSourceSpec
    feature_spec_pin_id: str = field(init=False)
    observation_source_spec_id: str = field(init=False)

    def __post_init__(self):
        from .pit_identity import feature_spec_pin_id, observation_source_spec_id
        if type(self.feature_spec_pin) is not SpecPin or self.feature_spec_pin.kind != "FEATURE":
            raise ObservationPITError("binding requires FEATURE SpecPin")
        if type(self.source_spec) is not ObservationSourceSpec:
            raise ObservationPITError("binding requires ObservationSourceSpec")
        try:
            pin = replace(self.feature_spec_pin)
            source = replace(self.source_spec)
            object.__setattr__(self, "feature_spec_pin", pin)
            object.__setattr__(self, "source_spec", source)
            object.__setattr__(self, "feature_spec_pin_id", feature_spec_pin_id(pin))
            object.__setattr__(self, "observation_source_spec_id", observation_source_spec_id(source))
        except DatasetError as exc:
            raise ObservationPITError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ObservationSnapshotPin:
    source_snapshot_id: str
    source_content_sha256: str
    provider_id: str
    source_kind: str
    provider_contract_version: str
    provider_contract_content_id: str
    normalized_request_id: str
    acquisition_receipt_id: str
    acquisition_receipt_content_id: str
    completed_possession_at: datetime

    def __post_init__(self):
        for name in ("source_snapshot_id", "source_content_sha256", "provider_contract_content_id",
                     "normalized_request_id", "acquisition_receipt_content_id"):
            _checked(sha256, getattr(self, name), name)
        for name in ("provider_id", "source_kind", "provider_contract_version", "acquisition_receipt_id"):
            object.__setattr__(self, name, _checked(text, getattr(self, name), name))
        object.__setattr__(self, "completed_possession_at",
                           _checked(instant, self.completed_possession_at, "completed_possession_at"))


@dataclass(frozen=True, slots=True)
class ObservationBuildPin:
    observation_build_id: str
    observation_content_id: str
    observation_schema_version: str
    coverage_id: str
    coverage_proof_available_at: datetime
    status: str
    authority_evidence_ids: tuple[str, ...]
    provider_contracts: tuple[ObservationContractPin, ...]
    normalizations: tuple[ObservationContractPin, ...]
    source_snapshots: tuple[ObservationSnapshotPin, ...]
    selected_observation_version_ids: tuple[str, ...]

    def __post_init__(self):
        from .schema import OBSERVATION_SCHEMA_VERSION
        for name in ("observation_build_id", "observation_content_id", "coverage_id"):
            _checked(sha256, getattr(self, name), name)
        if self.observation_schema_version != OBSERVATION_SCHEMA_VERSION or self.status not in ("COMPLETE", "EMPTY"):
            raise ObservationPITError("invalid build pin schema/status")
        object.__setattr__(self, "coverage_proof_available_at",
                           _checked(instant, self.coverage_proof_available_at, "coverage_proof_available_at"))
        for name in ("authority_evidence_ids", "selected_observation_version_ids"):
            object.__setattr__(self, name, _hash_tuple(getattr(self, name), name))
        for name, cls, key in (("provider_contracts", ObservationContractPin, lambda p: (p.version, p.content_id)),
                               ("normalizations", ObservationContractPin, lambda p: (p.version, p.content_id)),
                               ("source_snapshots", ObservationSnapshotPin, lambda p: p.source_snapshot_id)):
            try:
                values = tuple(replace(v) for v in items(getattr(self, name), cls, name, nonempty=True))
            except ObservationPITError:
                raise
            except ObservationError as exc:
                raise ObservationPITError(str(exc)) from exc
            if len({key(v) for v in values}) != len(values):
                raise ObservationPITError("duplicate " + name)
            object.__setattr__(self, name, tuple(sorted(values, key=key)))
        if not self.authority_evidence_ids or (self.status == "EMPTY" and self.selected_observation_version_ids):
            raise ObservationPITError("invalid build pin authority/selected versions")


@dataclass(frozen=True, slots=True)
class ObservationPITDecision:
    sample_key: str
    bar_sample_version_id: str
    feature_spec_pin_id: str
    observation_source_spec_id: str
    T: datetime
    A: datetime | None
    considered_observation_builds_digest: str
    status: str
    reason: str | None
    archive_limited: bool
    selected_observation_key: str | None
    selected_observation_version_id: str | None
    selected_observation_build_id: str | None
    selected_source_snapshot_id: str | None
    selected_known_at_authority_id: str | None
    selected_event_time: datetime | None
    selected_known_at: datetime | None
    selected_archive_available_at: datetime | None
    scoped_version_count: int
    future_known_excluded_count: int
    archive_future_excluded_count: int
    eligible_key_count: int
    alignment_candidate_count: int

    def __post_init__(self):
        for name in ("sample_key", "bar_sample_version_id", "feature_spec_pin_id", "observation_source_spec_id",
                     "considered_observation_builds_digest"):
            _checked(sha256, getattr(self, name), name)
        object.__setattr__(self, "T", _checked(instant, self.T, "T"))
        if self.A is not None:
            object.__setattr__(self, "A", _checked(instant, self.A, "A"))
        selected = ("selected_observation_key", "selected_observation_version_id", "selected_observation_build_id",
                    "selected_source_snapshot_id", "selected_known_at_authority_id", "selected_event_time",
                    "selected_known_at", "selected_archive_available_at")
        present = [getattr(self, n) is not None for n in selected]
        if any(present) != all(present):
            raise ObservationPITError("selected fields must be present or null together")
        if all(present):
            for name in selected[:5]:
                _checked(sha256, getattr(self, name), name)
            for name in selected[5:]:
                object.__setattr__(self, name, _checked(instant, getattr(self, name), name))
            if (self.selected_event_time > self.T or self.selected_known_at > self.T
                    or (self.A is not None and self.selected_archive_available_at > self.A)):
                raise ObservationPITError("selected clocks exceed cutoffs")
        if self.status == "COMPLETE":
            valid = self.reason is None and all(present)
        elif self.status == "EXCLUDED":
            valid = ((self.reason in ("STALE", "NOT_REPORTED", "WITHDRAWN") and all(present))
                     or (self.reason in ("NO_ELIGIBLE_OBSERVATION", "FUTURE_KNOWN", "ARCHIVE_FUTURE") and not any(present)))
        else:
            valid = False
        if not valid or type(self.archive_limited) is not bool or (self.A is None and self.archive_limited):
            raise ObservationPITError("inconsistent decision status/reason/archive flag")
        for name in ("scoped_version_count", "future_known_excluded_count", "archive_future_excluded_count",
                     "eligible_key_count", "alignment_candidate_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ObservationPITError("invalid decision count " + name)
        visible = self.scoped_version_count - self.future_known_excluded_count - self.archive_future_excluded_count
        if not 0 <= self.alignment_candidate_count <= self.eligible_key_count <= visible:
            raise ObservationPITError("inconsistent decision counts")


@dataclass(frozen=True, slots=True)
class ObservationSampleBinding:
    sample_key: str
    bar_sample_version_id: str
    observation_binding_id: str
    multi_source_sample_version_id: str

    def __post_init__(self):
        for name in ("sample_key", "bar_sample_version_id", "observation_binding_id", "multi_source_sample_version_id"):
            _checked(sha256, getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ObservationDecisionEvidence:
    sample_key: str
    feature_spec_pin_id: str
    build_pins: tuple[ObservationBuildPin, ...]
    coverages: tuple[ObservationCoverage, ...]

    def __post_init__(self):
        _checked(sha256, self.sample_key, "sample_key")
        _checked(sha256, self.feature_spec_pin_id, "feature_spec_pin_id")
        for name, cls in (("build_pins", ObservationBuildPin), ("coverages", ObservationCoverage)):
            try:
                values = tuple(replace(v) for v in items(getattr(self, name), cls, name))
            except ObservationError as exc:
                raise ObservationPITError(str(exc)) from exc
            object.__setattr__(self, name, values)
        if len(self.build_pins) != len(self.coverages):
            raise ObservationPITError("coverage/pin cardinality mismatch")


@dataclass(frozen=True, slots=True, init=False)
class ObservationPITAssemblyResult:
    decisions: tuple[ObservationPITDecision, ...]
    evidence: tuple[ObservationDecisionEvidence, ...]
    sample_bindings: tuple[ObservationSampleBinding, ...]
    bindings: tuple[ObservationPITFeatureBinding, ...]
    observation_association_content_id: str
    sample_binding_content_id: str
    combined_association_content_id: str
    bar_association_content_id: str
    bar_association_schema_id: str

    def __init__(self, *args, **kwargs):
        raise TypeError("use assemble_observation_pit_sidecar")
