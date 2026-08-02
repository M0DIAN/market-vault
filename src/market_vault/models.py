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
        }
