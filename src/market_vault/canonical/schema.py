"""Explicit Canonical Parquet schema contract.

The canonical bars table uses a fixed, versioned PyArrow schema: column order
and types are declared explicitly instead of being inferred, so readers never
depend on file layout details. Byte-identical Parquet across unpinned
serializer versions is not promised; instants and logical values round-trip
exactly.
"""

from __future__ import annotations

import pyarrow as pa

#: Canonical bars table schema version.
CANONICAL_SCHEMA_VERSION = "market-bars-canonical-schema-v1"
#: Materializer implementation version.
CANONICAL_MATERIALIZER_VERSION = "market-bars-materializer-v1"

#: Fixed, documented order of canonical bar columns.
CANONICAL_BAR_COLUMNS = (
    "canonical_bar_key",
    "canonical_row_version_id",
    "dataset_kind",
    "code",
    "interval",
    "adjustment",
    "event_time",
    "market_available_at",
    "archive_available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "last_close",
    "change_rate",
    "pe_ratio",
    "turnover_rate",
    "ingestion_run_id",
    "physical_snapshot_hash",
    "logical_source_rows_hash",
    "source_schema_version",
    "canonical_builder_version",
    "requested_trade_date",
    "requested_session",
    "market_calendar_date",
    "session",
    "snapshot_file",
)

#: Optional market fields; absent source values become null, never fabricated.
OPTIONAL_MARKET_COLUMNS = (
    "turnover",
    "last_close",
    "change_rate",
    "pe_ratio",
    "turnover_rate",
)

UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")
DATE32 = pa.date32()
MARKET_FLOAT = pa.float64()
MARKET_VOLUME = pa.float64()


def canonical_bars_schema() -> pa.Schema:
    """Explicit PyArrow schema for canonical bars, in CANONICAL_BAR_COLUMNS order."""
    fields = []
    for column in CANONICAL_BAR_COLUMNS:
        if column in ("event_time", "market_available_at", "archive_available_at"):
            fields.append(pa.field(column, UTC_TIMESTAMP, nullable=False))
        elif column in ("requested_trade_date", "market_calendar_date"):
            fields.append(pa.field(column, DATE32, nullable=False))
        elif column in ("open", "high", "low", "close"):
            fields.append(pa.field(column, MARKET_FLOAT, nullable=False))
        elif column == "volume":
            fields.append(pa.field(column, MARKET_VOLUME, nullable=False))
        elif column in OPTIONAL_MARKET_COLUMNS:
            fields.append(pa.field(column, MARKET_FLOAT, nullable=True))
        else:
            fields.append(pa.field(column, pa.string(), nullable=False))
    return pa.schema(fields)
