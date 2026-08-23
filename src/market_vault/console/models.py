from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TablePage:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    page: int = 1
    page_size: int = 100
    total_rows: int = 0

    @property
    def total_pages(self) -> int:
        if self.total_rows == 0:
            return 1
        return (self.total_rows + self.page_size - 1) // self.page_size

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


@dataclass(frozen=True)
class DashboardSnapshot:
    status: str
    metrics: dict[str, str]
    recent_runs: TablePage
    message: str = ""


@dataclass(frozen=True)
class BackfillPlanView:
    scope: str
    symbols: tuple[str, ...]
    trading_date_count: int
    pending_count: int
    skipped_count: int
    items: TablePage


@dataclass(frozen=True)
class PurgePlanView:
    plan_id: str
    status: str
    executable: bool
    summary: dict[str, Any]
    refusal_reasons: tuple[dict[str, Any], ...]
    items: TablePage


@dataclass(frozen=True)
class ExportResult:
    path: str
    format: str
    row_count: int


@dataclass(frozen=True)
class OperationResult:
    name: str
    status: str
    message: str
    payload: Any = None
    details: dict[str, Any] = field(default_factory=dict)
