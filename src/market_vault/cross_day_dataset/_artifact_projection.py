"""Artifact preparation exclusively from the issuance-time detached snapshot."""

from dataclasses import dataclass
from types import MappingProxyType

from ..dataset.artifact_serialization import feature_spec_artifact, label_spec_artifact, split_spec_artifact
from ..dataset.identity import _spec_digest
from ..dataset.specs import feature_label_spec_pin
from ..multi_source.feature_specs import serialize_observation_feature_spec, observation_feature_spec_pin
from ..observation.identity import observation_source_snapshot_id
from ..observation.pit_identity import feature_spec_pin_id, observation_build_pin_id
from ..ts2_feature.registry import _registry
from ._artifact_encoding import parquet_bytes
from ._artifact_records import (
    _Recorded, _SCHEMAS, _decode_record, _encode_record, _fact_bytes,
    _snapshot_members, _snapshot_projection, _snapshot_scalar, _snapshot_value,
)
from ._artifact_values import _value
from .artifact_models import BUILD_REPORT_CONTRACT_VERSION, _require


_RESULT_FIELDS = (
    "identity_input dataset_id scope dataset_as_of schema rows sample_audit completion split_result "
    "feature_pit ts2_features observation_pit observation_builds observation_feature_specs observation_features "
    "cross_day_association cross_day_labels schedule status"
).split()
_IDENTITY_FIELDS = (
    "scope dataset_as_of schema rows canonical_builds canonical_build_pins gap_references feature_pit "
    "ts2_features observation_pit observation_builds observation_input_proofs observation_feature_specs "
    "observation_features cross_day_association cross_day_labels schedule split_result sample_audit completion"
).split()
_OBSERVATION_BUILD_FIELDS = (
    "observation_build_id observation_content_id status rows source_snapshots authority_evidence_ids provider_contracts "
    "normalizations coverage created_at manifest_payload build_dir"
).split()
_ASSOCIATION_FIELDS = (
    "feature_pit feature_builds label_builds schedule label_specs dataset_as_of decisions sample_bindings observation_pit"
).split()


@dataclass(frozen=True, slots=True)
class _Prepared:
    dataset_id: str
    status: str
    scope: _Recorded
    dataset_as_of: object
    schema: _Recorded
    rows: tuple
    completion: _Recorded
    sidecars: tuple
    specs: tuple
    canonical_build_pins: tuple
    gap_references: tuple
    observation_input_proofs: tuple

    def sidecar(self, name):
        for path, kind, records in self.sidecars:
            if path == name:
                return kind, records
        raise KeyError(name)


def _sequence_nodes(node):
    _require(type(node) is tuple and len(node) == 2 and node[0] == "tuple" and type(node[1]) is tuple,
             "ARTIFACT_AUTHORITY", "detached tuple required")
    return node[1]


def _record(kind, **values):
    _require(kind in _SCHEMAS and set(values) == {name for name, _ in _SCHEMAS[kind]},
             "ARTIFACT_AUTHORITY", "closed preparation record required")
    result = _Recorded(kind, tuple((name, values[name]) for name, _ in _SCHEMAS[kind]))
    _encode_record(result, kind)
    return result


def _observation_evidence(node):
    values = _snapshot_members(node, "market_vault.observation.artifact_models", "VerifiedObservationBuild",
                               _OBSERVATION_BUILD_FIELDS)
    snapshots = _snapshot_value(values["source_snapshots"], "*ObservationSourceSnapshotInput")
    identity = _record("ObservationBuildIdentityInput",
        rows=_snapshot_value(values["rows"], "*Observation"),
        source_snapshot_ids=tuple(sorted(observation_source_snapshot_id(_value(s)) for s in snapshots)),
        authority_evidence_ids=_snapshot_value(values["authority_evidence_ids"], "*str"),
        provider_contracts=_snapshot_value(values["provider_contracts"], "*ObservationContractPin"),
        normalizations=_snapshot_value(values["normalizations"], "*ObservationContractPin"),
        coverage=_snapshot_projection(values["coverage"], "ObservationCoverage"),
        schema_version="observation-schema-v1")
    return _record("ObservationEvidence", identity_input=identity, source_snapshots=snapshots,
                   created_at=_snapshot_scalar(values["created_at"]))


def _prepare_artifact_facts(facts):
    """No caller result is accepted/read here; this calculator grants no authority."""
    root = _snapshot_members(facts.snapshot, "market_vault.cross_day_dataset.models",
                             "MultiSourceCrossDayDatasetResult", _RESULT_FIELDS)
    declaration = _snapshot_members(root["identity_input"], "market_vault.cross_day_dataset.models",
                                    "MultiSourceCrossDayDatasetIdentityInput", _IDENTITY_FIELDS)
    _require(_snapshot_scalar(root["dataset_id"]) == facts.dataset_id
             and _snapshot_scalar(root["status"]) == facts.status,
             "ARTIFACT_AUTHORITY", "working facts binding differs")
    for name in _IDENTITY_FIELDS:
        if name in root:
            _require(root[name] == declaration[name], "ARTIFACT_AUTHORITY", "detached projection differs: " + name)

    def projection(name, kind):
        return _snapshot_projection(declaration[name], kind)

    scope = projection("scope", "DatasetScope")
    schema = projection("schema", "DatasetSchema")
    rows = tuple(tuple(_snapshot_scalar(cell) for cell in _sequence_nodes(row))
                 for row in _sequence_nodes(declaration["rows"]))
    pit = projection("feature_pit", "PITAssemblyResult")
    ts2 = projection("ts2_features", "TS2FeatureExecutionResult")
    observation = projection("observation_pit", "ObservationPITAssemblyResult")
    observation_features = projection("observation_features", "ObservationFeatureExecutionResult")
    schedule = projection("schedule", "VerifiedTradingDaySchedule")
    split = projection("split_result", "ChronologicalSplitResult")
    completion = projection("completion", "MultiSourceCrossDayCompletionSummary")
    audits = _snapshot_value(declaration["sample_audit"], "*MultiSourceCrossDaySampleAudit")
    builds = _snapshot_value(declaration["canonical_builds"], "*VerifiedCanonicalBuild")
    input_proofs = _snapshot_value(declaration["observation_input_proofs"], "*ObservationBuildPin")
    evidence = tuple(_observation_evidence(node) for node in _sequence_nodes(declaration["observation_builds"]))
    _require(len(evidence) == len(input_proofs), "ARTIFACT_AUTHORITY", "Observation input proof count differs")
    proof_ids = tuple(observation_build_pin_id(_value(pin)) for pin in input_proofs)
    _require(proof_ids == tuple(sorted(set(proof_ids))), "ARTIFACT_AUTHORITY", "full input proof order differs")

    association = _snapshot_members(declaration["cross_day_association"], "market_vault.cross_day.assembly",
                                    "CrossDayLabelAssemblyResult", _ASSOCIATION_FIELDS)
    label_specs = _snapshot_value(association["label_specs"], "*LabelSpec")
    label_values = _snapshot_members(declaration["cross_day_labels"], "market_vault.cross_day.execution",
                                    "CrossDayLabelExecutionResult",
                                    ("association", "implementation_pins", "implementation_source_hashes", "values"))
    _require(label_values["association"] == declaration["cross_day_association"],
             "ARTIFACT_AUTHORITY", "detached L2 association differs")
    for field in ("feature_pit", "observation_pit", "schedule", "dataset_as_of"):
        _require(association[field] == declaration[field], "ARTIFACT_AUTHORITY", "detached L2 copy differs")
    association_record = _record("CrossDayAssociation",
        feature_build_ids=tuple(b.canonical_build_id for b in _snapshot_value(association["feature_builds"], "*VerifiedCanonicalBuild")),
        label_build_ids=tuple(b.canonical_build_id for b in _snapshot_value(association["label_builds"], "*VerifiedCanonicalBuild")),
        dataset_as_of=_snapshot_value(association["dataset_as_of"], "?datetime"),
        decisions=_snapshot_value(association["decisions"], "*CrossDayLabelDecision"),
        sample_bindings=_snapshot_value(association["sample_bindings"], "*CrossDayLabelSampleBinding"))
    values_record = _record("CrossDayValues", **{
        name: _snapshot_value(label_values[name], shape) for name, shape in _SCHEMAS["CrossDayValues"]})
    registrations = _registry()
    _require({_value(pin) for pin in ts2.registry_implementation_pins} == {r.pin for r in registrations}
             and len(ts2.registry_implementation_pins) == len(registrations) == 8,
             "ARTIFACT_AUTHORITY", "detached TS2 pins differ from static source fingerprints")
    ts2_record = _record("TS2Features", **dict(ts2._items), implementation_source_hashes=tuple(
        _record("ImplementationSourceHash", transform_ref=r.contract.transform_ref, source_sha256=r.source_sha256)
        for r in sorted(registrations, key=lambda r: r.contract.transform_ref)))
    report = _record("BuildReport", report_contract_version=BUILD_REPORT_CONTRACT_VERSION,
        dataset_id=facts.dataset_id, requested_sample_count=len(pit.samples), matrix_row_count=len(rows),
        feature_excluded_sample_count=sum(not a.matrix_eligible for a in audits),
        label_incomplete_sample_count=sum(a.label_status == "INCOMPLETE" for a in audits),
        complete_scope_count=completion.complete_count, incomplete_scope_count=completion.incomplete_count,
        missing_scope_count=completion.missing_count)
    sidecars = (
        ("feature_pit.json", "PITAssemblyResult", (pit,)),
        ("canonical_evidence.json", "VerifiedCanonicalBuild", builds),
        ("ts2_features.json", "TS2Features", (ts2_record,)),
        ("observation_pit.json", "ObservationPITAssemblyResult", (observation,)),
        ("observation_evidence.json", "ObservationEvidence", evidence),
        ("observation_features.json", "ObservationFeatureExecutionResult", (observation_features,)),
        ("cross_day_association.json", "CrossDayAssociation", (association_record,)),
        ("cross_day_values.json", "CrossDayValues", (values_record,)),
        ("schedule.json", "VerifiedTradingDaySchedule", (schedule,)),
        ("sample_audit.json", "MultiSourceCrossDaySampleAudit", audits),
        ("split.json", "ChronologicalSplitResult", (split,)),
        ("build_report.json", "BuildReport", (report,)),
    )
    specs = []
    for item in ts2.feature_specs:
        spec = _value(item)
        pin = feature_label_spec_pin(spec)
        specs.append((f"specs/ts2/{_spec_digest(pin)}.yaml", "TS2_SPEC", pin, feature_spec_artifact(spec)))
    for item in _snapshot_value(declaration["observation_feature_specs"], "*ObservationFeatureSpec"):
        spec = _value(item)
        pin = observation_feature_spec_pin(spec)
        specs.append((f"specs/observation/{feature_spec_pin_id(pin)}.yaml", "OBSERVATION_SPEC", pin,
                      serialize_observation_feature_spec(spec)))
    for item in label_specs:
        spec = _value(item)
        pin = feature_label_spec_pin(spec)
        specs.append((f"specs/cross_day/{_spec_digest(pin)}.yaml", "CROSS_DAY_SPEC", pin, label_spec_artifact(spec)))
    specs.append(("specs/split.yaml", "SPLIT_SPEC", _value(split.split_spec_pin), split_spec_artifact(_value(split.split_spec))))
    return _Prepared(facts.dataset_id, facts.status, scope, _snapshot_value(declaration["dataset_as_of"], "?datetime"),
        schema, rows, completion, sidecars, tuple(sorted(specs)),
        _snapshot_value(declaration["canonical_build_pins"], "*CanonicalBuildPin"),
        _snapshot_value(declaration["gap_references"], "*GapReference"), input_proofs)


def _content_bytes(prepared):
    """Pure serializer; not materialization, enrollment or publication authority."""
    files = {path: _fact_bytes(kind, values) for path, kind, values in prepared.sidecars}
    # The report has a distinct envelope version from authority fact sidecars.
    from ._artifact_encoding import canonical_json
    _, report = prepared.sidecar("build_report.json")
    files["build_report.json"] = canonical_json({"artifact_version": BUILD_REPORT_CONTRACT_VERSION,
                                                "records": [_encode_record(report[0], "BuildReport")]})
    files.update((path, data) for path, _, _, data in prepared.specs)
    files["dataset.parquet"] = parquet_bytes(_value(prepared.schema), prepared.rows)
    return MappingProxyType(files)
