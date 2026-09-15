"""Frozen A2 physical schema, independent of all A1 identity domains.

Compound semantic fields use canonical JSON strings so int64 and float64
values retain their distinct types without a lossy common numeric column.
"""

import pyarrow as pa

OBSERVATION_ARTIFACT_MANIFEST_VERSION = "observation-artifact-manifest-v1"
OBSERVATION_ARTIFACT_FORMAT_VERSION = "observation-parquet-v1"
OBSERVATION_MATERIALIZER_VERSION = "observation-materializer-v1"
OBSERVATION_PARQUET_PATH = "observations/part-00000.parquet"

JSON_COLUMNS = frozenset({"dimensions", "value_schema", "values"})
TIME_COLUMNS = frozenset({"event_time", "event_period_start", "known_at", "archive_available_at"})
ROW_COLUMNS = (
    "provider_id", "source_kind", "entity_id", "observation_name", "dimensions",
    "event_time", "event_period_start", "value_schema", "values", "value_status",
    "known_at", "known_at_authority_id", "archive_available_at", "source_snapshot_id",
    "source_content_sha256", "provider_contract_version", "provider_contract_content_id",
    "normalization_version", "normalization_content_id", "revision_id",
    "supersedes_revision_id", "value_schema_id", "observation_key", "observation_version_id",
)
OBSERVATION_ARROW_SCHEMA = pa.schema([
    pa.field(name, pa.timestamp("us", tz="UTC") if name in TIME_COLUMNS else pa.string(),
             nullable=name in {"event_period_start", "supersedes_revision_id"})
    for name in ROW_COLUMNS
])
