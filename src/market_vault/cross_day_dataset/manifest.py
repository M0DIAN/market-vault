"""Closed in-memory artifact manifest and recorded-content validation."""

from datetime import datetime
from hashlib import sha256
from types import MappingProxyType

from ..dataset.artifact_serialization import (
    feature_spec_artifact, label_spec_artifact, split_spec_artifact, parse_split_spec_artifact,
)
from ..dataset.identity import _spec_digest
from ..dataset.specs import parse_feature_spec, parse_label_spec, feature_label_spec_pin
from ..multi_source.feature_specs import parse_observation_feature_spec, serialize_observation_feature_spec, observation_feature_spec_pin
from ..observation.pit_identity import feature_spec_pin_id
from ._artifact_canonical import _check, _digest
from ._artifact_encoding import canonical_json, decode_json, exact_fields, decode_timestamp, timestamp_text, decode_parquet
from ._artifact_identity import _recorded_payload, _recorded_dataset_id
from ._artifact_join import _recorded_closure
from ._artifact_records import _Recorded, _read_facts, _decode_record, _encode_record
from ._artifact_values import _value
from .artifact_models import (
    MANIFEST_SCHEMA_VERSION, SERIALIZATION_FORMAT_VERSION, MATERIALIZER_VERSION,
    READER_CONTRACT_VERSION, BUILD_REPORT_CONTRACT_VERSION, _require,
)


_MANIFEST_FIELDS = (
    "manifest_schema_version dataset_id identity status built_at logical_row_count schema scope completion row_order "
    "materializer_version reader_contract_version build_report_contract_version spec_artifact_versions output_files"
).split()
_FILE_FIELDS = "relative_path file_role artifact_version row_count byte_size sha256 content_role content_id".split()
_SPEC_VERSIONS = MappingProxyType(dict(ts2_feature="market-vault-feature-spec-v1",
    observation_feature="observation-feature-spec-yaml-v1", cross_day_label="market-vault-label-spec-v1",
    split="market-vault-chronological-split-spec-v1"))
_FACTS = MappingProxyType({
    "feature_pit.json": ("PITAssemblyResult", True, "feature_association_content_id"),
    "canonical_evidence.json": ("VerifiedCanonicalBuild", False, "canonical_build_pins_digest"),
    "ts2_features.json": ("TS2Features", True, "ts2_execution_id"),
    "observation_pit.json": ("ObservationPITAssemblyResult", True, "combined_association_content_id"),
    "observation_evidence.json": ("ObservationEvidence", False, "observation_input_proofs_digest"),
    "observation_features.json": ("ObservationFeatureExecutionResult", True, "observation_values_content_id"),
    "cross_day_association.json": ("CrossDayAssociation", True, "cross_day_association_content_id"),
    "cross_day_values.json": ("CrossDayValues", True, "cross_day_values_content_id"),
    "schedule.json": ("VerifiedTradingDaySchedule", True, "schedule_pin_id"),
    "sample_audit.json": ("MultiSourceCrossDaySampleAudit", False, "sample_audit_content_id"),
    "split.json": ("ChronologicalSplitResult", True, "split_result_id"),
})


def _specs(files):
    found = dict(ts2=[], observation=[], cross_day=[])
    declarations = []
    for path in sorted(files):
        if path == "specs/split.yaml":
            decode_json(files[path])
            split = parse_split_spec_artifact(files[path].decode("utf-8"))
            _check(split_spec_artifact(split) == files[path], "noncanonical split spec")
            from ..dataset.split_models import chronological_split_spec_pin
            declarations.append((path, "SPLIT_SPEC", _SPEC_VERSIONS["split"], chronological_split_spec_pin(split)))
        elif path.startswith("specs/"):
            parts = path.split("/")
            _check(len(parts) == 3 and parts[1] in found and parts[2].endswith(".yaml"), "unknown spec path")
            family = parts[1]
            _digest(parts[2][:-5])
            decode_json(files[path])
            parser, serializer = {
                "ts2": (parse_feature_spec, feature_spec_artifact),
                "observation": (parse_observation_feature_spec, serialize_observation_feature_spec),
                "cross_day": (parse_label_spec, label_spec_artifact),
            }[family]
            spec = parser(files[path].decode("utf-8"))
            _check(serializer(spec) == files[path], "noncanonical spec bytes")
            pin = observation_feature_spec_pin(spec) if family == "observation" else feature_label_spec_pin(spec)
            pin_id = feature_spec_pin_id(pin) if family == "observation" else _spec_digest(pin)
            _check(parts[2] == pin_id + ".yaml", "spec filename/pin differs")
            found[family].append((pin_id, spec))
            role, version = {"ts2": ("TS2_SPEC", "ts2_feature"),
                "observation": ("OBSERVATION_SPEC", "observation_feature"),
                "cross_day": ("CROSS_DAY_SPEC", "cross_day_label")}[family]
            declarations.append((path, role, _SPEC_VERSIONS[version], pin))
    _check("specs/split.yaml" in files and all(found.values()), "missing spec family")
    return tuple(tuple(s for _, s in sorted(found[k])) for k in ("ts2", "observation", "cross_day")), split, tuple(declarations)


def _proof_clocks(value):
    if type(value) is tuple:
        return tuple(t for v in value for t in _proof_clocks(v))
    if type(value) is _Recorded:
        clocks = []
        for name, item in value._items:
            if name in ("created_at", "completed_possession_at", "archive_available_at", "selected_archive_available_at",
                        "proof_archive_available_at", "previous_archive_available_at", "next_archive_available_at"):
                if item is not None:
                    _check(type(item) is datetime, "proof clock type differs")
                    clocks.append(item)
            clocks.extend(_proof_clocks(item))
        return tuple(clocks)
    return ()


def _inspect_content(files, scope_record, cutoff, built_at):
    """No filesystem access and no verified-result issuance in this calculator."""
    _check(type(files) in (dict, MappingProxyType) and all(type(k) is str and type(v) is bytes for k, v in files.items()),
           "exact artifact byte mapping required")
    _check(set(_FACTS) | {"dataset.parquet", "build_report.json", "specs/split.yaml"} <= set(files), "missing content file")
    spec_families, split_spec, spec_declarations = _specs(files)
    _check(set(files) == set(_FACTS) | {"dataset.parquet", "build_report.json"} | {p for p, _, _, _ in spec_declarations},
           "extra content file")
    sidecars = {path: _read_facts(kind, files[path], singleton=singleton)
                for path, (kind, singleton, _) in _FACTS.items()}
    scope = _value(scope_record)
    closure = _recorded_closure(scope=scope, cutoff=cutoff, sidecars=sidecars, observation_specs=spec_families[1],
                                label_specs=spec_families[2], split_spec=split_spec)
    _check(closure.ts2_features.feature_specs == spec_families[0], "TS2 spec files differ from recorded execution")
    rows = decode_parquet(files["dataset.parquet"], closure.schema)
    # Typed scalar encoding distinguishes bool/int and signed zero without JSON hashing.
    for expected, actual in zip(closure.rows, rows):
        _check(len(expected) == len(actual), "matrix width differs")
        _check(all(type(e) is type(a) and _encode_scalar(e) == _encode_scalar(a) for e, a in zip(expected, actual)),
               "matrix projection differs")
    _check(len(rows) == len(closure.rows), "matrix row count differs")
    clocks = _proof_clocks(tuple(r for records in sidecars.values() for r in records))
    timestamp_text(built_at)
    _check(all(t <= built_at for t in clocks), "built_at precedes recorded acquisition/proof clock")
    identity = _recorded_payload(closure)
    dataset_id = _recorded_dataset_id(closure)
    expected_report = dict(report_contract_version=BUILD_REPORT_CONTRACT_VERSION, dataset_id=dataset_id,
        requested_sample_count=len(closure.feature_pit.samples), matrix_row_count=len(rows),
        feature_excluded_sample_count=sum(not a.matrix_eligible for a in closure.sample_audit),
        label_incomplete_sample_count=sum(a.label_status == "INCOMPLETE" for a in closure.sample_audit),
        complete_scope_count=closure.completion.complete_count, incomplete_scope_count=closure.completion.incomplete_count,
        missing_scope_count=closure.completion.missing_count)
    _check(files["build_report.json"] == canonical_json(dict(artifact_version=BUILD_REPORT_CONTRACT_VERSION,
                                                            records=[expected_report])), "build report differs")
    counts = {"feature_pit.json": len(closure.feature_pit.samples), "canonical_evidence.json": len(closure.canonical_builds),
        "ts2_features.json": sum(len(s.values) for s in closure.ts2_features.samples),
        "observation_pit.json": len(closure.observation_pit.decisions), "observation_evidence.json": len(closure.observation_input_proofs),
        "observation_features.json": sum(len(s.values) for s in closure.observation_features.samples),
        "cross_day_association.json": len(closure.cross_day_association.decisions),
        "cross_day_values.json": len(closure.cross_day_labels.values), "schedule.json": len(closure.schedule.daily_records),
        "sample_audit.json": len(closure.sample_audit), "split.json": len(closure.split_result.assignments)}
    records = []
    for path, (_, _, field) in _FACTS.items():
        role = path[:-5].upper()
        records.append(_file_record(path, role, SERIALIZATION_FORMAT_VERSION, counts[path], role, identity[field], files[path]))
    records.append(_file_record("dataset.parquet", "MATRIX", SERIALIZATION_FORMAT_VERSION, len(rows), "MATRIX",
                                identity["logical_dataset_content_id"], files["dataset.parquet"]))
    records.append(_file_record("build_report.json", "BUILD_REPORT", BUILD_REPORT_CONTRACT_VERSION, 1,
                                "NON_AUTHORITATIVE", dataset_id, files["build_report.json"]))
    records.extend(_file_record(path, role, version, 1, "SPEC", pin.content_sha256, files[path])
                   for path, role, version, pin in spec_declarations)
    return closure, identity, dataset_id, sorted(records, key=lambda r: r["relative_path"])


def _encode_scalar(value):
    import struct
    if type(value) is float:
        return struct.pack("!d", value)
    return value


def _file_record(path, role, version, count, content_role, content_id, data):
    return dict(relative_path=path, file_role=role, artifact_version=version, row_count=count,
                byte_size=len(data), sha256=sha256(data).hexdigest(), content_role=content_role, content_id=content_id)


def _physical_identity(identity):
    return {k: timestamp_text(v) if type(v) is datetime else v for k, v in identity.items()}


def _manifest_bytes(prepared, files, built_at):
    closure, identity, dataset_id, output_files = _inspect_content(files, prepared.scope, prepared.dataset_as_of, built_at)
    _check(dataset_id == prepared.dataset_id, "prepared Dataset identity differs")
    payload = dict(manifest_schema_version=MANIFEST_SCHEMA_VERSION, dataset_id=dataset_id,
        identity=_physical_identity(identity), status="COMPLETE" if closure.rows else "EMPTY", built_at=timestamp_text(built_at),
        logical_row_count=len(closure.rows), schema=_encode_record(prepared.schema, "DatasetSchema"),
        scope=_encode_record(prepared.scope, "DatasetScope"), completion=_encode_record(prepared.completion, "MultiSourceCrossDayCompletionSummary"),
        row_order="CODE_FEATURE_CLOSE_SAMPLE_KEY", materializer_version=MATERIALIZER_VERSION,
        reader_contract_version=READER_CONTRACT_VERSION, build_report_contract_version=BUILD_REPORT_CONTRACT_VERSION,
        spec_artifact_versions=dict(_SPEC_VERSIONS), output_files=output_files)
    return canonical_json(payload)


def _validate_manifest_content(manifest_bytes, files):
    manifest = exact_fields(decode_json(manifest_bytes), _MANIFEST_FIELDS)
    for key, expected in (("manifest_schema_version", MANIFEST_SCHEMA_VERSION), ("materializer_version", MATERIALIZER_VERSION),
            ("reader_contract_version", READER_CONTRACT_VERSION), ("build_report_contract_version", BUILD_REPORT_CONTRACT_VERSION),
            ("row_order", "CODE_FEATURE_CLOSE_SAMPLE_KEY"), ("spec_artifact_versions", dict(_SPEC_VERSIONS))):
        _require(manifest[key] == expected, "MANIFEST_BINDING", "unsupported " + key)
    _digest(manifest["dataset_id"])
    _check(type(manifest["logical_row_count"]) is int and manifest["logical_row_count"] >= 0, "invalid logical row count")
    _check(type(manifest["identity"]) is dict and len(manifest["identity"]) == 49, "closed 49-field identity required")
    cutoff_text = manifest["identity"].get("dataset_as_of")
    cutoff = None if cutoff_text is None else decode_timestamp(cutoff_text)
    built_at = decode_timestamp(manifest["built_at"])
    _check(type(manifest["output_files"]) is list, "output file list required")
    for record in manifest["output_files"]:
        exact_fields(record, _FILE_FIELDS)
        _check(all(type(record[n]) is int and record[n] >= 0 for n in ("byte_size", "row_count")), "invalid output count")
        _digest(record["sha256"])
        _digest(record["content_id"])
    scope = _decode_record("DatasetScope", manifest["scope"])
    closure, identity, dataset_id, expected_files = _inspect_content(files, scope, cutoff, built_at)
    _require(manifest["output_files"] == expected_files, "MANIFEST_BINDING", "physical/logical file facts differ")
    _require(manifest["identity"] == _physical_identity(identity) and manifest["dataset_id"] == dataset_id,
             "MANIFEST_BINDING", "Dataset identity assertion differs")
    _check(_value(_decode_record("DatasetSchema", manifest["schema"])) == closure.schema, "manifest schema differs")
    _check(_value(_decode_record("MultiSourceCrossDayCompletionSummary", manifest["completion"])) == closure.completion,
           "manifest completion differs")
    _check(manifest["logical_row_count"] == len(closure.rows)
           and manifest["status"] == ("COMPLETE" if closure.rows else "EMPTY"), "manifest status/count differs")
    return closure, manifest
