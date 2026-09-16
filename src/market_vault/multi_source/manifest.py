"""Separate deterministic manifest for the multi-source cohort."""

from dataclasses import dataclass, fields, replace
from datetime import datetime

from ..dataset import manifest as legacy
from ..dataset.encoding import normalize_utc_datetime
from ._audit import MultiSourceSampleAudit
from ._orchestration_validation import freeze_copy
from ._serialization import canonical_json, exact_fields, payload, record, require, timestamp
from .artifact_models import (
    MultiSourceDatasetOutputFile, MULTI_SOURCE_DATASET_MATERIALIZER_VERSION,
    MULTI_SOURCE_DATASET_READER_CONTRACT_VERSION,
)
from .identity import MultiSourceDatasetIdentityInput, multi_source_dataset_id

SPEC_ARTIFACT_VERSIONS = dict(bar_feature="market-vault-feature-spec-v1",
    observation_feature="observation-feature-spec-yaml-v1", label="market-vault-label-spec-v1",
    split="market-vault-chronological-split-spec-v1")
_EXTRA = frozenset(("dataset_id", "status", "built_at", "logical_row_count", "row_order",
    "bar_association_schema_version", "materializer_version", "reader_contract_version",
    "spec_artifact_versions", "output_files"))
MANIFEST_FIELDS = ({f.name for f in fields(MultiSourceDatasetIdentityInput)} - {"observation_evidence"}) | _EXTRA


@dataclass(frozen=True, slots=True)
class MultiSourceDatasetManifest:
    identity_input: MultiSourceDatasetIdentityInput
    built_at: datetime
    logical_row_count: int
    output_files: tuple[MultiSourceDatasetOutputFile, ...]

    def __post_init__(self):
        require(type(self.identity_input) is MultiSourceDatasetIdentityInput, "manifest requires exact identity input")
        identity = replace(self.identity_input)
        require(type(self.logical_row_count) is int and self.logical_row_count >= 0, "invalid logical row count")
        require(type(self.output_files) is tuple and all(type(f) is MultiSourceDatasetOutputFile for f in self.output_files),
                "invalid output facts")
        outputs = tuple(sorted((replace(f) for f in self.output_files), key=lambda f: f.relative_path))
        require(len({f.relative_path for f in outputs}) == len(outputs), "duplicate output facts")
        from ._artifact_schema import output_contracts
        contracts = output_contracts(identity)
        require({f.relative_path for f in outputs} == set(contracts), "manifest output whitelist mismatch")
        for f in outputs:
            role, content, version, _ = contracts[f.relative_path]
            require((f.file_role, f.content_id, f.artifact_version) == (role, content, version), "manifest output contract mismatch")
        object.__setattr__(self, "identity_input", freeze_copy(identity))
        object.__setattr__(self, "built_at", normalize_utc_datetime(self.built_at, "built_at"))
        object.__setattr__(self, "output_files", outputs)

    @property
    def dataset_id(self):
        return multi_source_dataset_id(self.identity_input)

    @property
    def status(self):
        return "COMPLETE" if self.logical_row_count else "EMPTY"


def manifest_payload(manifest):
    require(type(manifest) is MultiSourceDatasetManifest, "expected MultiSourceDatasetManifest")
    manifest = replace(manifest)
    result = payload(manifest.identity_input)
    result.pop("observation_evidence")
    result.update(dataset_id=manifest.dataset_id, status=manifest.status, built_at=payload(manifest.built_at),
        logical_row_count=manifest.logical_row_count, row_order="CODE_FEATURE_CLOSE_SAMPLE_KEY",
        bar_association_schema_version="pit-association-schema-v1", materializer_version=MULTI_SOURCE_DATASET_MATERIALIZER_VERSION,
        reader_contract_version=MULTI_SOURCE_DATASET_READER_CONTRACT_VERSION,
        spec_artifact_versions=SPEC_ARTIFACT_VERSIONS, output_files=payload(manifest.output_files))
    return result


def serialize_multi_source_dataset_manifest(manifest: MultiSourceDatasetManifest) -> bytes:
    return canonical_json(manifest_payload(manifest))


def manifest_from_payload(obj, evidence):
    exact_fields(obj, MANIFEST_FIELDS)
    scalar_parsers = dict(scope=legacy._parse_scope, schema=legacy._parse_schema,
        completion=legacy._parse_completion, split_spec=lambda v: legacy._parse_spec(v, "split_spec"))
    sequence_parsers = dict(canonical_builds=legacy._parse_canonical_build,
        bar_feature_specs=lambda v: legacy._parse_spec(v, "bar_feature_specs"),
        observation_feature_specs=lambda v: legacy._parse_spec(v, "observation_feature_specs"),
        label_specs=lambda v: legacy._parse_spec(v, "label_specs"),
        implementations=legacy._parse_implementation, gap_references=legacy._parse_gap_reference,
        sample_audit=lambda v: record(MultiSourceSampleAudit, v))
    kwargs = {}
    for f in fields(MultiSourceDatasetIdentityInput):
        name = f.name
        if name == "observation_evidence":
            kwargs[name] = evidence
            continue
        value = obj[name]
        if name in scalar_parsers:
            value = scalar_parsers[name](value)
        elif name in sequence_parsers:
            require(type(value) is list, "manifest sequence must be array")
            value = tuple(sequence_parsers[name](v) for v in value)
        elif name == "dataset_as_of":
            value = None if value is None else timestamp(value)
        elif type(value) is list:
            value = tuple(value)
        kwargs[name] = value
    require(type(obj["output_files"]) is list, "output_files requires array")
    result = MultiSourceDatasetManifest(MultiSourceDatasetIdentityInput(**kwargs), timestamp(obj["built_at"]),
        obj["logical_row_count"], tuple(record(MultiSourceDatasetOutputFile, f) for f in obj["output_files"]))
    require(canonical_json(obj) == serialize_multi_source_dataset_manifest(result), "manifest claims/versions/identity mismatch")
    return result
