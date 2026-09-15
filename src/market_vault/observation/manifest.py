"""Canonical physical records and strict A1 reconstruction; no filesystem I/O."""

from dataclasses import fields, is_dataclass
from datetime import datetime
import json

from ._validation import instant
from .artifact_models import ObservationArtifactError
from .artifact_schema import (
    OBSERVATION_ARTIFACT_FORMAT_VERSION, OBSERVATION_ARTIFACT_MANIFEST_VERSION,
    OBSERVATION_MATERIALIZER_VERSION, OBSERVATION_PARQUET_PATH,
)
from .identity import (
    observation_build_id, observation_content_id, observation_coverage_id,
    observation_source_snapshot_id,
)
from .models import (
    Observation, ObservationBuildIdentityInput, ObservationContractPin,
    ObservationCoverage, ObservationDimension, ObservationScope,
    ObservationSnapshotMember, ObservationSourceSnapshotInput,
)
from .schema import ObservationValueField, ObservationValueSchema


def payload(value):
    if isinstance(value, datetime):
        return instant(value, "timestamp").isoformat(timespec="microseconds").replace("+00:00", "Z")
    if is_dataclass(value):
        return {f.name: payload(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (tuple, list)):
        return [payload(item) for item in value]
    if isinstance(value, dict):
        return {key: payload(item) for key, item in value.items()}
    return value


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ObservationArtifactError("duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    raise ObservationArtifactError("non-finite JSON number")


def read_json(data: bytes):
    result = json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    if canonical_json(result) != data:
        raise ObservationArtifactError("noncanonical JSON encoding")
    return result


def record(cls, value, **overrides):
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise ObservationArtifactError(f"invalid {cls.__name__} field set")
    kwargs = {f.name: value[f.name] for f in fields(cls) if f.init}
    kwargs.update(overrides)
    result = cls(**kwargs)
    if canonical_json(payload(result)) != canonical_json(value):
        raise ObservationArtifactError(f"inconsistent or noncanonical {cls.__name__} record/identity")
    return result


def timestamp(value):
    if type(value) is not str:
        raise ObservationArtifactError("timestamp must be explicit UTC microsecond text")
    result = instant(datetime.fromisoformat(value), "timestamp")
    if payload(result) != value:
        raise ObservationArtifactError("noncanonical timestamp")
    return result


def scope_from_payload(value):
    return record(ObservationScope, value,
                  dimensions=tuple(record(ObservationDimension, d) for d in value["dimensions"]))


def row_from_payload(value):
    schema = value["value_schema"]
    overrides = {
        "dimensions": tuple(record(ObservationDimension, d) for d in value["dimensions"]),
        "value_schema": record(ObservationValueSchema, schema,
                               fields=tuple(record(ObservationValueField, f) for f in schema["fields"])),
    }
    for name in ("event_time", "event_period_start", "known_at", "archive_available_at"):
        overrides[name] = None if value[name] is None else timestamp(value[name])
    return record(Observation, value, **overrides)


def snapshot_from_payload(value):
    return record(ObservationSourceSnapshotInput, value,
                  provider_contract=record(ObservationContractPin, value["provider_contract"]),
                  completed_possession_at=timestamp(value["completed_possession_at"]),
                  members=tuple(record(ObservationSnapshotMember, m) for m in value["members"]))


def coverage_from_payload(value):
    return record(ObservationCoverage, value, scope=scope_from_payload(value["scope"]),
                  provider_contract=record(ObservationContractPin, value["provider_contract"]),
                  **{name: timestamp(value[name]) for name in (
                      "effective_start", "effective_end", "knowledge_start", "knowledge_end")})


def build_from_payload(value):
    return record(ObservationBuildIdentityInput, value,
                  rows=tuple(row_from_payload(row) for row in value["rows"]),
                  provider_contracts=tuple(record(ObservationContractPin, p) for p in value["provider_contracts"]),
                  normalizations=tuple(record(ObservationContractPin, p) for p in value["normalizations"]),
                  coverage=coverage_from_payload(value["coverage"]))


def make_manifest(build, snapshots, created_at, *, byte_size, sha256):
    times = {}
    for name in ("event_time", "known_at", "archive_available_at"):
        values = [getattr(row, name) for row in build.rows]
        times[name + "_min"] = payload(min(values)) if values else None
        times[name + "_max"] = payload(max(values)) if values else None
    return {
        "manifest_version": OBSERVATION_ARTIFACT_MANIFEST_VERSION,
        "artifact_format_version": OBSERVATION_ARTIFACT_FORMAT_VERSION,
        "materializer_version": OBSERVATION_MATERIALIZER_VERSION,
        "status": "COMPLETE" if build.rows else "EMPTY",
        "observation_build_id": observation_build_id(build),
        "observation_content_id": observation_content_id(build.rows),
        "observation_schema_version": build.schema_version,
        "coverage_id": observation_coverage_id(build.coverage),
        "created_at": payload(created_at), "row_count": len(build.rows),
        "time_bounds": times, "source_snapshot_count": len(snapshots),
        "source_snapshots": [{"source_snapshot_id": observation_source_snapshot_id(s),
                              "snapshot": payload(s)} for s in snapshots],
        "authority_evidence_ids": payload(build.authority_evidence_ids),
        "provider_contracts": payload(build.provider_contracts),
        "normalizations": payload(build.normalizations), "coverage": payload(build.coverage),
        "output_files": [{"relative_path": OBSERVATION_PARQUET_PATH,
                          "file_role": "OBSERVATIONS", "content_role": "OBSERVATION_ROWS",
                          "row_count": len(build.rows), "byte_size": byte_size, "sha256": sha256}],
    }
