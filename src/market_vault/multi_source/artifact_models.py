"""Independent A4.3 immutable artifact boundary; no legacy cohort extension."""

from dataclasses import dataclass
from pathlib import Path

from ..dataset.encoding import DatasetError

MULTI_SOURCE_DATASET_MANIFEST_SCHEMA_VERSION = "multi-source-dataset-manifest-v1"
MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION = "multi-source-dataset-parquet-v1"
MULTI_SOURCE_DATASET_MATERIALIZER_VERSION = "multi-source-dataset-materializer-v1"
MULTI_SOURCE_DATASET_READER_CONTRACT_VERSION = "multi-source-dataset-reader-v1"
MULTI_SOURCE_DATASET_BUILD_REPORT_VERSION = "multi-source-dataset-build-report-v1"


class MultiSourceDatasetArtifactError(DatasetError):
    """Documented physical or recorded-authority verification failure."""


class MultiSourceDatasetMaterializationError(MultiSourceDatasetArtifactError):
    """Publication failed; immutable final artifacts are never rolled back."""


@dataclass(frozen=True, slots=True)
class MultiSourceDatasetOutputFile:
    relative_path: str
    file_role: str
    byte_size: int
    sha256: str
    row_count: int | None
    content_role: str
    content_id: str | None
    artifact_version: str

    def __post_init__(self):
        from ._serialization import require
        from ..observation._validation import sha256
        from ._artifact_paths import member_path
        member_path(self.relative_path)
        require(type(self.byte_size) is int and self.byte_size >= 0, "invalid byte size")
        require(self.row_count is None or type(self.row_count) is int and self.row_count >= 0, "invalid row count")
        sha256(self.sha256, "physical hash")
        if self.content_id is not None:
            sha256(self.content_id, "content ID")
        require(self.file_role == self.content_role, "content/file role mismatch")
        parquet_roles = {"MATRIX", "BAR_ASSOCIATION", "OBSERVATION_ASSOCIATION", "SAMPLE_BINDING", "OBSERVATION_FEATURE_VALUES"}
        versions = {role: MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION for role in parquet_roles}
        versions.update(OBSERVATION_EVIDENCE="multi-source-observation-evidence-v1", BAR_FEATURE_SPEC="market-vault-feature-spec-v1",
            OBSERVATION_FEATURE_SPEC="observation-feature-spec-yaml-v1", LABEL_SPEC="market-vault-label-spec-v1",
            SPLIT_SPEC="market-vault-chronological-split-spec-v1", BUILD_REPORT=MULTI_SOURCE_DATASET_BUILD_REPORT_VERSION)
        require(self.file_role in versions and self.artifact_version == versions[self.file_role], "unsupported output role/version")
        require((self.content_id is None) == (self.file_role == "BUILD_REPORT"), "invalid null output content ID")
        require((self.row_count is not None) == (self.file_role in parquet_roles), "invalid output row-count kind")


@dataclass(frozen=True, slots=True, init=False)
class VerifiedMultiSourceDatasetBuild:
    dataset_id: str
    status: str
    manifest: object
    schema: object
    rows: tuple
    bar_associations: tuple
    observation_decisions: tuple
    sample_bindings: tuple
    observation_feature_result: object
    observation_evidence: tuple
    sample_audit: tuple
    bar_feature_specs: tuple
    observation_feature_specs: tuple
    label_specs: tuple
    split_spec: object
    split_result: object
    build_report: object
    build_dir: Path

    def __init__(self, *args, **kwargs):
        raise TypeError("use load_verified_multi_source_dataset")


@dataclass(frozen=True, slots=True)
class MultiSourceDatasetMaterializationResult:
    build: VerifiedMultiSourceDatasetBuild
    created_new_build: bool

    def __post_init__(self):
        if type(self.build) is not VerifiedMultiSourceDatasetBuild or type(self.created_new_build) is not bool:
            raise MultiSourceDatasetMaterializationError("invalid publication result")

    @property
    def dataset_id(self):
        return self.build.dataset_id

    @property
    def build_dir(self):
        return self.build.build_dir
