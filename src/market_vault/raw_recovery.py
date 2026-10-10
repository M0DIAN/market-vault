"""Bounded, offline inputs for a fresh market-bar collection run."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from .lifecycle import reject_link, verify_directory_chain
from .models import MarketBarSnapshotPair, RunManifest, Settings
from .storage import ParquetStore


def _unique_json_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"Duplicate source manifest key: {key}")
        result[key] = value
    return result


def _read_source_bytes(path: Path, label: str) -> bytes:
    """Read once; both the parser and the digest consume this captured input."""
    verify_directory_chain(path.parent, label=f"{label} parent")
    reject_link(path, label)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not before.st_ino:
        raise ValueError(f"{label} must be a verifiable regular file: {path}")

    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns

    with path.open("rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError(f"{label} changed before reading: {path}")
        contents = stream.read()
        after = os.fstat(stream.fileno())
    verify_directory_chain(path.parent, label=f"{label} parent")
    reject_link(path, label)
    if identity(before) != identity(after) or identity(path.lstat()) != identity(before):
        raise ValueError(f"{label} changed while reading: {path}")
    return contents


def _symbols(value, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a nonempty list of symbols")
    result = sorted({item.strip().upper() for item in value})
    if not all(result):
        raise ValueError(f"{label} cannot contain blank symbols")
    return result


def _source_pair(value: dict, source: RunManifest, settings: Settings) -> MarketBarSnapshotPair:
    if not isinstance(value, dict) or set(value) != set(MarketBarSnapshotPair.__dataclass_fields__):
        raise ValueError("Invalid source snapshot pair shape")
    expected = {
        "run_id": source.run_id,
        "requested_trade_date": source.requested_trade_date.isoformat(),
        "interval": source.interval,
        "session": source.session,
        "adjustment": source.adjustment,
        "source": settings.source,
        "source_schema_version": settings.source_schema_version,
    }
    if any(value[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError("Source snapshot pair request/source/schema mismatch")
    symbol = value["symbol"]
    if symbol not in source.requested_symbols:
        raise ValueError("Source snapshot pair symbol is outside the original request")
    if type(value["row_count"]) is not int or value["row_count"] <= 0:
        raise ValueError("Source snapshot pair must have a positive row count")
    store = ParquetStore(settings)
    for layer in ("raw", "curated"):
        expected_path = store._path(
            layer, source.requested_trade_date, source.interval, [symbol],
            source.session, source.adjustment, source.run_id,
        )
        path = value[f"{layer}_file"]
        if not isinstance(path, str) or os.path.abspath(path) != os.path.abspath(expected_path):
            raise ValueError(f"Source snapshot pair has an unexpected {layer} path")
    return MarketBarSnapshotPair.create(
        **{**value, "requested_trade_date": source.requested_trade_date}
    )


def _parse_source_manifest(contents: bytes, settings: Settings) -> RunManifest:
    try:
        payload = json.loads(contents, object_pairs_hook=_unique_json_object)
        if not isinstance(payload, dict):
            raise ValueError("Source manifest must be an object")
        if payload.get("snapshot_binding_mode") != "REGISTERED_PER_SYMBOL":
            raise ValueError("Recovery requires snapshot_binding_mode REGISTERED_PER_SYMBOL")
        if set(payload) != set(RunManifest.__dataclass_fields__):
            raise ValueError("Recovery requires the complete modern RunManifest shape")
        if payload["status"] not in {"SUCCESS", "PARTIAL", "FAILED"}:
            raise ValueError("Recovery requires a terminal source manifest")
        for field in ("run_id", "interval", "session", "adjustment", "config_hash"):
            if not isinstance(payload[field], str) or not payload[field].strip():
                raise ValueError(f"Invalid source manifest {field}")
        ParquetStore._safe_partition_value(payload["run_id"])
        ParquetStore._safe_partition_value(payload["interval"])
        ParquetStore._safe_partition_value(settings.source)
        if (
            payload["interval"] != payload["interval"].lower()
            or payload["session"] != payload["session"].upper()
            or payload["adjustment"] != payload["adjustment"].upper()
        ):
            raise ValueError("Source manifest request fields are not canonical")
        requested = _symbols(payload["requested_symbols"], label="Original requested_symbols")
        if requested != payload["requested_symbols"]:
            raise ValueError("Original requested_symbols are not canonical")
        trade_date = date.fromisoformat(payload["requested_trade_date"])
        started_at = datetime.fromisoformat(payload["started_at"])
        finished_at = datetime.fromisoformat(payload["finished_at"])
        if started_at.tzinfo is None or finished_at.tzinfo is None or finished_at < started_at:
            raise ValueError("Source manifest needs valid terminal timestamps")
        config = {
            "trade_date": trade_date.isoformat(),
            "symbols": requested,
            "interval": payload["interval"],
            "session": payload["session"],
            "adjustment": payload["adjustment"],
            "source_schema_version": settings.source_schema_version,
        }
        expected_hash = hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if payload["config_hash"] != expected_hash:
            raise ValueError("Source config_hash does not match the request and configured source schema")
        source = RunManifest(
            **{
                **payload,
                "requested_trade_date": trade_date,
                "started_at": started_at,
                "finished_at": finished_at,
                "snapshot_pairs": [],
            }
        )
        if not isinstance(payload["snapshot_pairs"], list):
            raise ValueError("Source snapshot_pairs must be a list")
        source.snapshot_pairs = [_source_pair(value, source, settings) for value in payload["snapshot_pairs"]]
        pair_symbols = [pair.symbol for pair in source.snapshot_pairs]
        if pair_symbols != sorted(set(pair_symbols)) or source.successful_symbols != pair_symbols:
            raise ValueError("Source successful_symbols and snapshot_pairs disagree")
        if (
            not isinstance(source.failed_symbols, dict)
            or any(not isinstance(value, str) for value in source.failed_symbols.values())
            or set(source.failed_symbols) & set(pair_symbols)
            or set(source.failed_symbols) | set(pair_symbols) != set(requested)
        ):
            raise ValueError("Source manifest outcomes do not cover the original request")
        if type(source.row_count) is not int or source.row_count != sum(pair.row_count for pair in source.snapshot_pairs):
            raise ValueError("Source manifest row_count disagrees with its pairs")
        expected_raw = source.snapshot_pairs[0].raw_file if len(pair_symbols) == 1 else None
        expected_curated = source.snapshot_pairs[0].curated_file if len(pair_symbols) == 1 else None
        if source.raw_file != expected_raw or source.curated_file != expected_curated:
            raise ValueError("Source manifest compatibility pointers disagree with its pairs")
        if (source.status == "FAILED") != (not pair_symbols) or (
            source.status == "SUCCESS" and source.failed_symbols
        ):
            raise ValueError("Source terminal status disagrees with its outcomes")
        return source
    except (KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise ValueError(f"Invalid source manifest: {exc}") from exc


def _available_catalog_pairs(settings: Settings, source: RunManifest) -> list[MarketBarSnapshotPair]:
    """Validate retained authority when present; a lost run insert is recoverable."""
    if not os.path.lexists(settings.catalog_path):
        return []
    verify_directory_chain(settings.catalog_path.parent, label="source Catalog parent")
    reject_link(settings.catalog_path, "source Catalog")
    with duckdb.connect(str(settings.catalog_path), read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "ingestion_runs" in tables:
            result = con.execute("SELECT * FROM ingestion_runs WHERE run_id = ?", [source.run_id])
            columns = [column[0] for column in result.description]
            row = result.fetchone()
            if row is not None:
                facts = dict(zip(columns, row))
                expected = {**source.__dict__}
                expected.pop("snapshot_pairs")
                for field, value in expected.items():
                    recorded = facts.get(field)
                    if field in {"requested_symbols", "successful_symbols", "failed_symbols"}:
                        recorded = json.loads(recorded) if isinstance(recorded, str) else recorded
                    if recorded != value:
                        raise ValueError(f"Source Catalog run disagrees with manifest {field}")
        if "market_bar_snapshot_pairs" not in tables:
            return []
        result = con.execute(
            "SELECT * FROM market_bar_snapshot_pairs WHERE run_id = ? ORDER BY symbol", [source.run_id]
        )
        columns = [column[0] for column in result.description]
        pairs = []
        manifest_pairs = {pair.symbol: pair for pair in source.snapshot_pairs}
        for row in result.fetchall():
            facts = dict(zip(columns, row))
            facts["requested_trade_date"] = facts["requested_trade_date"].isoformat()
            pair = _source_pair(facts, source, settings)
            if pair.symbol in manifest_pairs and pair != manifest_pairs[pair.symbol]:
                raise ValueError("Source Catalog and manifest snapshot pairs disagree")
            pairs.append(pair)
        return pairs


@dataclass
class _RawHistoryReplay:
    source: RunManifest
    frames: dict[str, pd.DataFrame]
    source_manifest: dict
    raw_inputs: list[dict]

    def fetch_history(self, code: str, **_kwargs) -> pd.DataFrame:
        return self.frames[code].copy()

    def lineage(self, run: RunManifest, settings: Settings) -> dict:
        return {
            "schema_version": "market-vault-raw-history-recovery-lineage-v1",
            "replay_version": "market-bars-raw-replay-v1",
            "run_id": run.run_id,
            "started_at": run.started_at.isoformat(),
            "source": settings.source,
            "source_schema_version": settings.source_schema_version,
            "config_hash": run.config_hash,
            "source_manifest": self.source_manifest,
            "raw_inputs": self.raw_inputs,
        }


def _load_raw_history_replay(
    settings: Settings, manifest_path: str | Path, *, symbols: list[str] | None
) -> _RawHistoryReplay:
    path = Path(os.path.abspath(manifest_path))
    contents = _read_source_bytes(path, "source manifest")
    source = _parse_source_manifest(contents, settings)
    selected = source.requested_symbols if symbols is None else _symbols(symbols, label="symbols")
    if not set(selected) <= set(source.requested_symbols):
        raise ValueError("Recovery symbols must be a subset of the original request")
    pairs = [*source.snapshot_pairs, *_available_catalog_pairs(settings, source)]
    store = ParquetStore(settings)
    frames = {}
    inputs = []
    for symbol in selected:
        raw_path = Path(os.path.abspath(store._path(
            "raw", source.requested_trade_date, source.interval, [symbol],
            source.session, source.adjustment, source.run_id,
        )))
        raw_bytes = _read_source_bytes(raw_path, "source Raw")
        try:
            frame = pq.ParquetFile(BytesIO(raw_bytes)).read().to_pandas()
        except Exception as exc:
            raise ValueError(f"Cannot parse source Raw {raw_path}: {exc}") from exc
        if frame.empty:
            raise ValueError(f"Source Raw is empty: {raw_path}")
        expected = {
            "code": (symbol, lambda value: str(value).strip().upper()),
            "requested_trade_date": (source.requested_trade_date, lambda value: pd.Timestamp(value).date()),
            "interval": (source.interval, lambda value: str(value).strip().lower()),
            "requested_session": (source.session, lambda value: str(value).strip().upper()),
            "adjustment": (source.adjustment, lambda value: str(value).strip().upper()),
            "ingestion_run_id": (source.run_id, lambda value: str(value).strip()),
        }
        for field, (value, normalize) in expected.items():
            if field not in frame or {normalize(item) for item in frame[field]} != {value}:
                raise ValueError(f"Source Raw has mismatched {field}: {raw_path}")
        for field in ("source", "source_schema_version"):
            if field in frame and set(frame[field]) != {getattr(settings, field)}:
                raise ValueError(f"Source Raw has mismatched {field}: {raw_path}")
        if any(pair.symbol == symbol and pair.row_count != len(frame) for pair in pairs):
            raise ValueError(f"Source Raw row count disagrees with retained pair facts: {raw_path}")
        frames[symbol] = frame
        inputs.append({"symbol": symbol, "path": str(raw_path), "sha256": hashlib.sha256(raw_bytes).hexdigest()})
    return _RawHistoryReplay(
        source=source,
        frames=frames,
        source_manifest={"path": str(path), "sha256": hashlib.sha256(contents).hexdigest(), "run_id": source.run_id},
        raw_inputs=inputs,
    )
