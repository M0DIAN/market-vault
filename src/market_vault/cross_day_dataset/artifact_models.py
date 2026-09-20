"""Closed physical contract constants and artifact failures; no logical identity."""

from dataclasses import dataclass

from ..dataset.encoding import DatasetError


MANIFEST_SCHEMA_VERSION = "multi-source-cross-day-dataset-manifest-v1"
SERIALIZATION_FORMAT_VERSION = "multi-source-cross-day-dataset-parquet-v1"
MATERIALIZER_VERSION = "multi-source-cross-day-dataset-materializer-v1"
READER_CONTRACT_VERSION = "multi-source-cross-day-dataset-reader-v1"
BUILD_REPORT_CONTRACT_VERSION = "multi-source-cross-day-build-report-v1"
PUBLICATION_CONTRACT_VERSION = "multi-source-cross-day-dataset-atomic-publication-v1"

PUBLICATION_STATES = frozenset((
    "PREFLIGHT", "PRIVATE_STAGING", "SEALED", "COMMITTED_UNVERIFIED", "VERIFIED_FINAL",
    "EXISTING_EQUIVALENT", "FAILED_PRECOMMIT", "COMMITTED_INVALID", "PUBLICATION_UNCERTAIN",
))
ARTIFACT_REASON_CODES = frozenset((
    "INPUT_AUTHORITY", "UNSAFE_PATH", "OWNERSHIP_UNPROVEN", "PLATFORM_UNQUALIFIED",
    "FILESYSTEM_MISMATCH", "INVENTORY_MISMATCH", "CONTENT_MISMATCH", "MANIFEST_BINDING",
    "SUCCESS_MARKER", "SEAL_AUTHORITY", "EXISTING_FINAL_INVALID", "PUBLICATION_FAILED",
    "CLEANUP_REFUSED", "FINAL_VERIFICATION_FAILED", "ARTIFACT_DECODE", "ARTIFACT_AUTHORITY",
))


class MultiSourceCrossDayArtifactError(DatasetError):
    """Physical failure, distinct from logical Feature/Label outcome statuses."""

    def __init__(self, reason_code, publication_state, cause):
        if reason_code not in ARTIFACT_REASON_CODES or publication_state not in PUBLICATION_STATES:
            raise ValueError("unknown artifact reason or publication state")
        self.reason_code = reason_code
        self.publication_state = publication_state
        self.cause = cause
        super().__init__(f"{reason_code} [{publication_state}]: {cause}")


def _require(condition, reason_code, message, publication_state="PREFLIGHT"):
    if not condition:
        raise MultiSourceCrossDayArtifactError(reason_code, publication_state, message)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedMultiSourceCrossDayDataset:
    """Read-only artifact authority, never live transform/issuance authority."""

    dataset_id: str
    identity_input: object
    scope: object
    dataset_as_of: object
    schema: object
    rows: tuple
    sample_audit: tuple
    completion: object
    split_result: object
    feature_pit: object
    ts2_features: object
    observation_pit: object
    observation_features: object
    cross_day_association: object
    cross_day_labels: object
    schedule: object
    manifest_payload: object
    build_path: object
    status: str

    def __init__(self, *args, **kwargs):
        raise TypeError("verified artifacts are issued only by the strict reader")


@dataclass(frozen=True, slots=True)
class MultiSourceCrossDayDatasetMaterializationResult:
    verified: VerifiedMultiSourceCrossDayDataset
    created_new_build: bool

    def __post_init__(self):
        _require(type(self.verified) is VerifiedMultiSourceCrossDayDataset and type(self.created_new_build) is bool,
                 "INPUT_AUTHORITY", "exact verified artifact and boolean required")
