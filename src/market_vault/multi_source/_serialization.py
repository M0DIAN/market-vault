"""Closed-record canonical physical encoding; no filesystem or discovery."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
import json
import math

from ..dataset.encoding import normalize_utc_datetime
from ..dataset.feature_models import FeatureValueResult
from ..dataset.label_models import LabelValueResult
from ..dataset.models import ImplementationPin, SpecPin
from ..dataset.pit_models import PITSampleRequest
from ..observation.models import ObservationContractPin, ObservationCoverage, ObservationDimension, ObservationScope
from ..observation.pit_models import ObservationBuildPin, ObservationSnapshotPin
from ._audit import MultiSourceSampleAudit
from ._evidence import normalize_evidence
from ..observation.pit_identity import observation_build_pin_id
from ..observation.pit_models import ObservationDecisionEvidence
from .artifact_models import MultiSourceDatasetArtifactError


def require(condition, message):
    if not condition:
        raise MultiSourceDatasetArtifactError(message)


def payload(value):
    if isinstance(value, datetime):
        return normalize_utc_datetime(value, "timestamp").isoformat(timespec="microseconds").replace("+00:00", "Z")
    if type(value) is date:
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: payload(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: payload(v) for k, v in value.items()}
    if type(value) in (tuple, list):
        return [payload(v) for v in value]
    if type(value) is float:
        require(math.isfinite(value), "nonfinite physical scalar")
        return 0.0 if value == 0 else value
    return value


def canonical_json(value):
    return (json.dumps(payload(value), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    raise MultiSourceDatasetArtifactError("nonfinite JSON number")


def read_json(data):
    require(type(data) is bytes, "JSON requires bytes")
    result = json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    require(canonical_json(result) == data, "noncanonical JSON bytes")
    return result


def exact_fields(value, names):
    require(type(value) is dict and set(value) == set(names), "invalid physical record fields")
    return value


def timestamp(value):
    require(type(value) is str, "timestamp requires canonical text")
    result = normalize_utc_datetime(datetime.fromisoformat(value), "timestamp")
    require(payload(result) == value, "noncanonical timestamp")
    return result


# Only statically named nested record types are decoded. Artifact data never
# chooses a class, import path, or callable.
_NESTED = {
    MultiSourceSampleAudit: {"request": PITSampleRequest, "bar_feature_values": (FeatureValueResult,), "label_values": (LabelValueResult,)},
    FeatureValueResult: {"spec_pin": SpecPin, "implementation_pin": ImplementationPin},
    LabelValueResult: {"spec_pin": SpecPin, "implementation_pin": ImplementationPin},
    ObservationBuildPin: {"provider_contracts": (ObservationContractPin,), "normalizations": (ObservationContractPin,), "source_snapshots": (ObservationSnapshotPin,)},
    ObservationCoverage: {"scope": ObservationScope, "provider_contract": ObservationContractPin},
    ObservationScope: {"dimensions": (ObservationDimension,)},
}
_TIMES = frozenset(("dataset_as_of", "feature_window_start", "feature_window_close", "label_window_start",
    "label_window_close", "actual_label_end_time", "coverage_proof_available_at", "completed_possession_at",
    "effective_start", "effective_end", "knowledge_start", "knowledge_end"))


def record(cls, value):
    exact_fields(value, (f.name for f in fields(cls)))
    data = {}
    for f in fields(cls):
        if not f.init:
            continue
        v = value[f.name]
        nested = _NESTED.get(cls, {}).get(f.name)
        if isinstance(nested, tuple):
            require(type(v) is list, "record sequence requires array")
            v = tuple(record(nested[0], member) for member in v)
        elif nested is not None:
            v = record(nested, v)
        elif f.name in _TIMES and v is not None:
            v = timestamp(v)
        elif f.name == "anchor_market_calendar_date":
            require(type(v) is str, "date requires text")
            v = date.fromisoformat(v)
        elif type(v) is list:
            v = tuple(v)
        data[f.name] = v
    result = cls(**data)
    require(canonical_json(result) == canonical_json(value), "noncanonical typed record")
    return result


def evidence_payload(evidence):
    return dict(schema_version="multi-source-observation-evidence-v1", items=[dict(
        sample_key=e.sample_key, feature_spec_pin_id=e.feature_spec_pin_id,
        proofs=[dict(observation_build_pin_id=observation_build_pin_id(p), build_pin=payload(p), coverage=payload(c))
                for p, c in zip(e.build_pins, e.coverages)]) for e in normalize_evidence(evidence)])


def evidence_from_bytes(data):
    obj = exact_fields(read_json(data), ("schema_version", "items"))
    require(obj["schema_version"] == "multi-source-observation-evidence-v1" and type(obj["items"]) is list,
            "invalid evidence version/items")
    items = []
    for item in obj["items"]:
        exact_fields(item, ("sample_key", "feature_spec_pin_id", "proofs"))
        require(type(item["proofs"]) is list, "proofs requires array")
        pins, coverages = [], []
        for proof in item["proofs"]:
            exact_fields(proof, ("observation_build_pin_id", "build_pin", "coverage"))
            pin = record(ObservationBuildPin, proof["build_pin"])
            require(observation_build_pin_id(pin) == proof["observation_build_pin_id"], "BuildPin identity mismatch")
            pins.append(pin)
            coverages.append(record(ObservationCoverage, proof["coverage"]))
        items.append(ObservationDecisionEvidence(item["sample_key"], item["feature_spec_pin_id"], tuple(pins), tuple(coverages)))
    result = normalize_evidence(tuple(items))
    require(canonical_json(evidence_payload(result)) == data, "evidence order/pair identity mismatch")
    return result
