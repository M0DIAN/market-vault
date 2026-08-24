from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class Settings:
    project_root: Path
    opend_host: str
    opend_port: int
    data_root: Path
    catalog_path: Path
    manifest_dir: Path
    report_dir: Path
    max_count: int = 1000
    source: str = "moomoo"
    source_schema_version: str = "10.9"
    default_session: str = "ALL"
    default_adjustment: str = "NONE"
    request_pause_seconds: float = 0.35


@dataclass
class QualityResult:
    check_name: str
    result: str
    expected_value: str | None = None
    actual_value: str | None = None
    details: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "result": self.result,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "details": self.details,
        }


@dataclass(frozen=True)
class MarketBarSnapshotPair:
    run_id: str
    symbol: str
    requested_trade_date: date
    interval: str
    session: str
    adjustment: str
    source: str
    source_schema_version: str
    raw_file: str
    curated_file: str
    row_count: int

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        symbol: str,
        requested_trade_date: date,
        interval: str,
        session: str,
        adjustment: str,
        source: str,
        source_schema_version: str,
        raw_file: str,
        curated_file: str,
        row_count: int,
    ) -> "MarketBarSnapshotPair":
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol cannot be blank")
        if row_count < 0:
            raise ValueError("row_count cannot be negative")
        return cls(
            run_id=run_id,
            symbol=normalized_symbol,
            requested_trade_date=requested_trade_date,
            interval=interval.lower(),
            session=session.upper(),
            adjustment=adjustment.upper(),
            source=source,
            source_schema_version=source_schema_version,
            raw_file=raw_file,
            curated_file=curated_file,
            row_count=int(row_count),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "symbol": self.symbol,
            "requested_trade_date": self.requested_trade_date.isoformat(),
            "interval": self.interval,
            "session": self.session,
            "adjustment": self.adjustment,
            "source": self.source,
            "source_schema_version": self.source_schema_version,
            "raw_file": self.raw_file,
            "curated_file": self.curated_file,
            "row_count": self.row_count,
        }


@dataclass
class RunManifest:
    requested_trade_date: date
    requested_symbols: list[str]
    interval: str
    session: str
    adjustment: str
    run_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    status: str = "RUNNING"
    successful_symbols: list[str] = field(default_factory=list)
    failed_symbols: dict[str, str] = field(default_factory=dict)
    raw_file: str | None = None
    curated_file: str | None = None
    row_count: int = 0
    config_hash: str = ""
    snapshot_binding_mode: str | None = None
    snapshot_pairs: list[MarketBarSnapshotPair] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "requested_trade_date": self.requested_trade_date.isoformat(),
            "requested_symbols": self.requested_symbols,
            "interval": self.interval,
            "session": self.session,
            "adjustment": self.adjustment,
            "successful_symbols": self.successful_symbols,
            "failed_symbols": self.failed_symbols,
            "raw_file": self.raw_file,
            "curated_file": self.curated_file,
            "row_count": self.row_count,
            "status": self.status,
            "config_hash": self.config_hash,
            "snapshot_binding_mode": self.snapshot_binding_mode,
            "snapshot_pairs": [
                pair.as_dict() for pair in sorted(self.snapshot_pairs, key=lambda item: item.symbol)
            ],
        }


@dataclass
class DatasetRunManifest:
    dataset: str
    requested_items: list[str]
    parameters: dict[str, Any]
    run_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    status: str = "RUNNING"
    successful_items: list[str] = field(default_factory=list)
    failed_items: dict[str, str] = field(default_factory=dict)
    raw_file: str | None = None
    curated_file: str | None = None
    quality_report: str | None = None
    row_count: int = 0
    config_hash: str = ""

    @property
    def request_count(self) -> int:
        return len(self.requested_items)

    @property
    def success_count(self) -> int:
        return len(self.successful_items)

    @property
    def failure_count(self) -> int:
        return len(self.failed_items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset": self.dataset,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "parameters": self.parameters,
            "requested_items": self.requested_items,
            "request_count": self.request_count,
            "successful_items": self.successful_items,
            "success_count": self.success_count,
            "failed_items": self.failed_items,
            "failure_count": self.failure_count,
            "row_count": self.row_count,
            "raw_file": self.raw_file,
            "curated_file": self.curated_file,
            "quality_report": self.quality_report,
            "config_hash": self.config_hash,
        }
