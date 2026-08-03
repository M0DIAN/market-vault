from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pandas as pd

from .audit import FAILED, PASS, WARN
from .backfill import normalize_backfill_symbols, resolve_calendar_scope
from .coverage import load_market_bar_coverage_state
from .models import Settings
from .normalization import market_session_label
from .reporting import write_json_report_atomic
from .storage import Catalog

INTRADAY_REPORT_TYPE = "MARKET_BARS_INTRADAY_INTEGRITY_AUDIT"

#: Supported intraday intervals and their length in seconds.
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600}

CHECK_REQUIRED_COLUMNS = "REQUIRED_COLUMNS"
CHECK_NON_EMPTY = "NON_EMPTY"
CHECK_EXACT_REQUEST_METADATA = "EXACT_REQUEST_METADATA"
CHECK_VALID_TIMESTAMPS = "VALID_TIMESTAMPS"
CHECK_TIMEZONE_INSTANT_CONSISTENCY = "TIMEZONE_INSTANT_CONSISTENCY"
CHECK_MARKET_CALENDAR_DATE_CONSISTENCY = "MARKET_CALENDAR_DATE_CONSISTENCY"
CHECK_SESSION_LABEL_CONSISTENCY = "SESSION_LABEL_CONSISTENCY"
CHECK_REQUESTED_SESSION_SCOPE = "REQUESTED_SESSION_SCOPE"
CHECK_DUPLICATE_TIMESTAMPS = "DUPLICATE_TIMESTAMPS"
CHECK_MINUTE_BOUNDARY_ALIGNMENT = "MINUTE_BOUNDARY_ALIGNMENT"
CHECK_DELTA_GRID_ALIGNMENT = "DELTA_GRID_ALIGNMENT"
CHECK_INTERNAL_GAPS = "INTERNAL_GAPS"

REQUIRED_COLUMNS = {
    "code",
    "time_market",
    "time_utc",
    "market_calendar_date",
    "requested_trade_date",
    "requested_session",
    "session",
    "interval",
    "adjustment",
    "source_schema_version",
    "ingestion_run_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ingested_at",
}

SESSION_LABELS = ("OVERNIGHT", "PRE_MARKET", "REGULAR", "AFTER_HOURS")
BOUNDARY_REASON = "No authoritative per-date session schedule is available."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_timestamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def parse_intraday_interval(value: str) -> timedelta:
    """Parse a minute-bar interval into a timedelta.

    Accepts 1m, 5m, 15m, 30m, 60m after strip()/lower(). Anything else
    (daily bars, empty strings, unknown or non-positive values) raises
    ValueError.
    """
    text = (value or "").strip().lower()
    if text not in INTERVAL_SECONDS:
        raise ValueError(
            f"Unsupported intraday interval: {value!r}. Supported: 1m, 5m, 15m, 30m, 60m"
        )
    return timedelta(seconds=INTERVAL_SECONDS[text])


def session_occurrence_date(time_market: pd.Timestamp, session: str) -> date:
    """Calendar-date key of a session occurrence in market time.

    20:00 D through 03:59 D+1 belong to the same OVERNIGHT occurrence keyed
    by D; every other session is keyed by its own local calendar date. The
    key only separates observations, never predicts session boundaries.
    """
    local_date = time_market.date()
    local_time = time_market.timetz().replace(tzinfo=None)
    if session == "OVERNIGHT" and local_time < time(4, 0):
        return local_date - timedelta(days=1)
    return local_date


@dataclass
class CheckResult:
    name: str
    status: str
    details: str | None = None
    mismatch_count: int | None = None
    field_mismatch_counts: dict[str, int] | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "details": self.details,
            "mismatch_count": self.mismatch_count,
            "field_mismatch_counts": self.field_mismatch_counts,
        }


@dataclass
class SegmentInfo:
    segment_id: int
    session: str
    first_time_market: str | None
    last_time_market: str | None
    row_count: int
    internal_gap_count: int
    estimated_missing_bar_count: int

    def as_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "session": self.session,
            "first_time_market": self.first_time_market,
            "last_time_market": self.last_time_market,
            "row_count": self.row_count,
            "internal_gap_count": self.internal_gap_count,
            "estimated_missing_bar_count": self.estimated_missing_bar_count,
        }


@dataclass
class GapDetail:
    session: str
    segment_id: int
    previous_time_market: str
    next_time_market: str
    delta_seconds: int
    estimated_missing_bars: int

    def as_dict(self) -> dict:
        return {
            "session": self.session,
            "segment_id": self.segment_id,
            "previous_time_market": self.previous_time_market,
            "next_time_market": self.next_time_market,
            "delta_seconds": self.delta_seconds,
            "estimated_missing_bars": self.estimated_missing_bars,
        }


@dataclass
class SelectedSnapshotInfo:
    ingestion_run_id: str
    snapshot_file: str
    snapshot_ingested_at: str | None
    run_finished_at: str | None
    row_count: int

    def as_dict(self) -> dict:
        return {
            "ingestion_run_id": self.ingestion_run_id,
            "snapshot_file": self.snapshot_file,
            "snapshot_ingested_at": self.snapshot_ingested_at,
            "run_finished_at": self.run_finished_at,
            "row_count": self.row_count,
        }


@dataclass
class ItemObservedInfo:
    first_time_market: str | None
    last_time_market: str | None
    session_row_counts: dict[str, int]

    def as_dict(self) -> dict:
        return {
            "first_time_market": self.first_time_market,
            "last_time_market": self.last_time_market,
            "session_row_counts": self.session_row_counts,
        }


@dataclass
class BoundaryCoverageInfo:
    evaluated: bool = False
    reason: str = BOUNDARY_REASON

    def as_dict(self) -> dict:
        return {"evaluated": self.evaluated, "reason": self.reason}


@dataclass
class ItemAuditResult:
    requested_trade_date: str
    source_state: str
    audit_status: str
    selected_snapshot: SelectedSnapshotInfo | None = None
    observed: ItemObservedInfo | None = None
    boundary_coverage: BoundaryCoverageInfo = field(default_factory=BoundaryCoverageInfo)
    checks: list[CheckResult] = field(default_factory=list)
    segments: list[SegmentInfo] = field(default_factory=list)
    internal_gaps: list[GapDetail] = field(default_factory=list)
    gap_details_truncated: bool = False
    incomplete_reasons: list[str] = field(default_factory=list)
    selection_failure_reason: str | None = None

    def as_dict(self, include_pass_checks: bool = False) -> dict:
        checks = self.checks if include_pass_checks else [c for c in self.checks if c.status != PASS]
        result: dict = {
            "requested_trade_date": self.requested_trade_date,
            "source_state": self.source_state,
            "audit_status": self.audit_status,
            "boundary_coverage": self.boundary_coverage.as_dict(),
            "checks": [check.as_dict() for check in checks],
            "segments": [segment.as_dict() for segment in self.segments],
            "internal_gaps": [gap.as_dict() for gap in self.internal_gaps],
            "gap_details_truncated": self.gap_details_truncated,
        }
        if self.selected_snapshot is not None:
            result["selected_snapshot"] = self.selected_snapshot.as_dict()
        if self.observed is not None:
            result["observed"] = self.observed.as_dict()
        if self.incomplete_reasons:
            result["incomplete_reasons"] = self.incomplete_reasons
        if self.selection_failure_reason is not None:
            result["selection_failure_reason"] = self.selection_failure_reason
        return result


@dataclass
class IntradayCalendarInfo:
    coverage_complete: bool
    coverage_gaps: list[dict]
    expected_trade_date_count: int
    expected_trade_dates: list[str]

    def as_dict(self) -> dict:
        return {
            "coverage_complete": self.coverage_complete,
            "coverage_gaps": self.coverage_gaps,
            "expected_trade_date_count": self.expected_trade_date_count,
            "expected_trade_dates": self.expected_trade_dates,
        }


@dataclass
class IntradaySummary:
    total_expected_items: int = 0
    complete_source_item_count: int = 0
    incomplete_source_item_count: int = 0
    missing_source_item_count: int = 0
    audited_item_count: int = 0
    pass_item_count: int = 0
    warn_item_count: int = 0
    fail_item_count: int = 0
    total_snapshot_rows: int = 0
    duplicate_timestamp_count: int = 0
    invalid_timestamp_count: int = 0
    internal_gap_count: int = 0
    estimated_missing_bar_count: int = 0
    coverage_percentage: float = 100.0

    def as_dict(self) -> dict:
        return {
            "total_expected_items": self.total_expected_items,
            "complete_source_item_count": self.complete_source_item_count,
            "incomplete_source_item_count": self.incomplete_source_item_count,
            "missing_source_item_count": self.missing_source_item_count,
            "audited_item_count": self.audited_item_count,
            "pass_item_count": self.pass_item_count,
            "warn_item_count": self.warn_item_count,
            "fail_item_count": self.fail_item_count,
            "total_snapshot_rows": self.total_snapshot_rows,
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "invalid_timestamp_count": self.invalid_timestamp_count,
            "internal_gap_count": self.internal_gap_count,
            "estimated_missing_bar_count": self.estimated_missing_bar_count,
            "coverage_percentage": self.coverage_percentage,
        }


@dataclass
class IntradaySymbolReport:
    code: str
    items: list[ItemAuditResult] = field(default_factory=list)

    def as_dict(self, include_pass_checks: bool = False) -> dict:
        return {
            "code": self.code,
            "items": [item.as_dict(include_pass_checks) for item in self.items],
        }


@dataclass
class IntradayAuditReport:
    run_id: str
    started_at: str
    finished_at: str | None = None
    status: str = FAILED
    parameters: dict = field(default_factory=dict)
    calendar: IntradayCalendarInfo | None = None
    summary: IntradaySummary | None = None
    symbols: list[IntradaySymbolReport] = field(default_factory=list)
    report_file: str | None = None

    def as_dict(self) -> dict:
        include_pass_checks = bool(self.parameters.get("include_pass_checks", False))
        return {
            "run_id": self.run_id,
            "report_type": INTRADAY_REPORT_TYPE,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "parameters": self.parameters,
            "calendar": self.calendar.as_dict() if self.calendar else None,
            "summary": self.summary.as_dict() if self.summary else None,
            "symbols": [symbol.as_dict(include_pass_checks) for symbol in self.symbols],
            "report_file": self.report_file,
        }


def _finish_intraday_report(report: IntradayAuditReport, settings: Settings) -> None:
    report.finished_at = _now_iso()
    report_path = settings.report_dir / f"market_bars_intraday_audit_{report.run_id}.json"
    payload = report.as_dict()
    payload["report_file"] = str(report_path)
    write_json_report_atomic(report_path, payload)
    report.report_file = str(report_path)


def run_intraday_audit(
    settings: Settings,
    *,
    symbols: list[str],
    start_date: date,
    end_date: date,
    calendar_market: str | None = None,
    calendar_code: str | None = None,
    interval: str = "1m",
    requested_session: str | None = None,
    adjustment: str | None = None,
    source_schema_version: str | None = None,
    include_pass_checks: bool = False,
    max_gap_details: int = 100,
    today: date | None = None,
) -> IntradayAuditReport:
    """Audit the intraday structure of the latest complete snapshot per
    (symbol, trade date).

    Pure local: no OpenD connection, no data mutation, no automatic repair.
    Validates structural integrity and internal continuity of observed
    session segments only; session boundary coverage is not evaluated.
    """
    effective_today = today or datetime.now(timezone.utc).date()
    normalized_symbols = normalize_backfill_symbols(symbols)
    interval_delta = parse_intraday_interval(interval)
    interval_seconds = int(interval_delta.total_seconds())
    interval_value = interval.strip().lower()
    session_value = (requested_session or settings.default_session).upper()
    adjustment_value = (adjustment or settings.default_adjustment).upper()
    schema_value = (source_schema_version or settings.source_schema_version).strip()
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if end_date >= effective_today:
        raise ValueError("end_date must be before today's UTC date")
    if max_gap_details < 0:
        raise ValueError("max_gap_details cannot be negative")
    scope_type, scope_value = resolve_calendar_scope(calendar_market, calendar_code)

    report = IntradayAuditReport(run_id=str(uuid4()), started_at=_now_iso())
    report.parameters = {
        "calendar_scope_type": scope_type,
        "calendar_scope_value": scope_value,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "symbols": normalized_symbols,
        "interval": interval_value,
        "requested_session": session_value,
        "adjustment": adjustment_value,
        "source_schema_version": schema_value,
        "include_pass_checks": include_pass_checks,
        "max_gap_details": max_gap_details,
    }

    state = load_market_bar_coverage_state(
        settings,
        scope_type=scope_type,
        scope_value=scope_value,
        symbols=normalized_symbols,
        start_date=start_date,
        end_date=end_date,
        interval=interval_value,
        requested_session=session_value,
        adjustment=adjustment_value,
        source_schema_version=schema_value,
    )
    report.calendar = IntradayCalendarInfo(
        coverage_complete=not bool(state.calendar_coverage_gaps),
        coverage_gaps=[
            {"start_date": gap_start.isoformat(), "end_date": gap_end.isoformat()}
            for gap_start, gap_end in state.calendar_coverage_gaps
        ],
        expected_trade_date_count=len(state.expected_trade_dates),
        expected_trade_dates=[value.isoformat() for value in state.expected_trade_dates],
    )
    if state.calendar_coverage_gaps:
        # The expected trading-day set is not fully determined: no summary,
        # no coverage percentage, and no bar-level classification.
        report.status = FAILED
        report.summary = None
        _finish_intraday_report(report, settings)
        return report

    catalog = Catalog(settings)
    refs = catalog.latest_complete_market_bar_snapshots(
        symbols=normalized_symbols,
        trade_dates=state.expected_trade_dates,
        interval=interval_value,
        requested_session=session_value,
        adjustment=adjustment_value,
        source_schema_version=schema_value,
    )

    item_results: dict[str, list[ItemAuditResult]] = {}
    for code in normalized_symbols:
        item_results[code] = []
        for trade_date in state.expected_trade_dates:
            key = (code, trade_date)
            if key in state.complete_items:
                ref = refs.get(key)
                if ref is None:
                    item_results[code].append(
                        ItemAuditResult(
                            requested_trade_date=trade_date.isoformat(),
                            source_state="COMPLETE",
                            audit_status=FAILED,
                            selection_failure_reason="COMPLETE_SNAPSHOT_SELECTION_FAILED",
                        )
                    )
                else:
                    item_results[code].append(
                        _audit_complete_snapshot(
                            catalog,
                            ref,
                            interval_value=interval_value,
                            interval_seconds=interval_seconds,
                            requested_session=session_value,
                            adjustment=adjustment_value,
                            schema=schema_value,
                            max_gap_details=max_gap_details,
                        )
                    )
            elif key in state.present_items:
                item_results[code].append(
                    ItemAuditResult(
                        requested_trade_date=trade_date.isoformat(),
                        source_state="INCOMPLETE",
                        audit_status="NOT_AUDITED",
                        incomplete_reasons=state.incomplete_reasons.get(key, []),
                    )
                )
            else:
                item_results[code].append(
                    ItemAuditResult(
                        requested_trade_date=trade_date.isoformat(),
                        source_state="MISSING",
                        audit_status="NOT_AUDITED",
                    )
                )

    report.symbols = [
        IntradaySymbolReport(code=code, items=item_results[code]) for code in normalized_symbols
    ]
    report.summary = _build_intraday_summary(item_results, state, normalized_symbols)
    report.status = _intraday_overall_status(report.summary)
    _finish_intraday_report(report, settings)
    return report


def _audit_complete_snapshot(
    catalog: Catalog,
    ref,
    *,
    interval_value: str,
    interval_seconds: int,
    requested_session: str,
    adjustment: str,
    schema: str,
    max_gap_details: int,
) -> ItemAuditResult:
    rows = catalog.market_bar_snapshot_rows(
        ref,
        interval=interval_value,
        requested_session=requested_session,
        adjustment=adjustment,
        source_schema_version=schema,
    )
    structure = _audit_snapshot_structure(
        rows.frame,
        ref,
        physical_columns=rows.physical_columns,
        interval_value=interval_value,
        interval_seconds=interval_seconds,
        requested_session=requested_session,
        adjustment=adjustment,
        schema=schema,
    )
    checks = structure["checks"]
    has_fail = any(check.status == "FAIL" for check in checks)
    has_warn = any(check.status == "WARN" for check in checks)
    gaps = sorted(structure["gaps"], key=lambda gap: gap.previous_time_market)
    truncated = len(gaps) > max_gap_details
    shown_gaps = gaps[:max_gap_details] if max_gap_details > 0 else []
    return ItemAuditResult(
        requested_trade_date=ref.requested_trade_date.isoformat(),
        source_state="COMPLETE",
        audit_status=FAILED if has_fail else WARN if has_warn else PASS,
        selected_snapshot=SelectedSnapshotInfo(
            ingestion_run_id=ref.ingestion_run_id,
            snapshot_file=ref.snapshot_file,
            snapshot_ingested_at=_iso_timestamp(ref.snapshot_ingested_at),
            run_finished_at=_iso_timestamp(ref.run_finished_at),
            row_count=ref.row_count,
        ),
        observed=ItemObservedInfo(
            first_time_market=structure["first_time_market"],
            last_time_market=structure["last_time_market"],
            session_row_counts=structure["session_row_counts"],
        ),
        checks=checks,
        segments=structure["segments"],
        internal_gaps=shown_gaps,
        gap_details_truncated=truncated,
    )


def _audit_snapshot_structure(
    df: pd.DataFrame,
    ref,
    *,
    physical_columns: set[str],
    interval_value: str,
    interval_seconds: int,
    requested_session: str,
    adjustment: str,
    schema: str,
) -> dict:
    checks: list[CheckResult] = []
    gaps: list[GapDetail] = []

    # REQUIRED_COLUMNS is judged against the selected physical file's own
    # schema; a union schema from other snapshot files must not mask a
    # missing column here.
    missing_columns = REQUIRED_COLUMNS - physical_columns
    if missing_columns:
        checks.append(
            CheckResult(
                CHECK_REQUIRED_COLUMNS,
                "FAIL",
                f"Missing columns: {sorted(missing_columns)}",
                mismatch_count=len(missing_columns),
            )
        )
        for name in (
            CHECK_NON_EMPTY,
            CHECK_EXACT_REQUEST_METADATA,
            CHECK_VALID_TIMESTAMPS,
            CHECK_TIMEZONE_INSTANT_CONSISTENCY,
            CHECK_MARKET_CALENDAR_DATE_CONSISTENCY,
            CHECK_SESSION_LABEL_CONSISTENCY,
            CHECK_REQUESTED_SESSION_SCOPE,
            CHECK_DUPLICATE_TIMESTAMPS,
            CHECK_MINUTE_BOUNDARY_ALIGNMENT,
            CHECK_DELTA_GRID_ALIGNMENT,
            CHECK_INTERNAL_GAPS,
        ):
            checks.append(CheckResult(name, "INFO", "NOT_EVALUATED"))
        return {
            "checks": checks,
            "gaps": gaps,
            "first_time_market": None,
            "last_time_market": None,
            "session_row_counts": {},
            "segments": [],
        }

    if df.empty:
        checks.append(CheckResult(CHECK_NON_EMPTY, "FAIL", "Snapshot contains no rows"))
        for name in (
            CHECK_EXACT_REQUEST_METADATA,
            CHECK_VALID_TIMESTAMPS,
            CHECK_TIMEZONE_INSTANT_CONSISTENCY,
            CHECK_MARKET_CALENDAR_DATE_CONSISTENCY,
            CHECK_SESSION_LABEL_CONSISTENCY,
            CHECK_REQUESTED_SESSION_SCOPE,
            CHECK_DUPLICATE_TIMESTAMPS,
            CHECK_MINUTE_BOUNDARY_ALIGNMENT,
            CHECK_DELTA_GRID_ALIGNMENT,
            CHECK_INTERNAL_GAPS,
        ):
            checks.append(CheckResult(name, "INFO", "NOT_EVALUATED"))
        return {
            "checks": checks,
            "gaps": gaps,
            "first_time_market": None,
            "last_time_market": None,
            "session_row_counts": {},
            "segments": [],
        }

    checks.append(CheckResult(CHECK_NON_EMPTY, "PASS", f"{len(df)} rows"))

    # EXACT_REQUEST_METADATA
    expected_metadata = {
        "code": ref.code,
        "requested_trade_date": ref.requested_trade_date,
        "interval": interval_value,
        "requested_session": requested_session,
        "adjustment": adjustment,
        "source_schema_version": schema,
        "ingestion_run_id": ref.ingestion_run_id,
    }
    # Rows with any mismatching field are counted once; field_mismatch_counts
    # keeps the per-field row counts for diagnosis.
    mismatch_mask = pd.Series(False, index=df.index)
    field_mismatch_counts: dict[str, int] = {}
    for column, expected in expected_metadata.items():
        if isinstance(expected, date):
            column_dates = pd.to_datetime(df[column], errors="coerce").dt.date
            field_mismatch = column_dates != expected
        else:
            field_mismatch = df[column].astype(str) != str(expected)
        field_mismatch_counts[column] = int(field_mismatch.sum())
        mismatch_mask |= field_mismatch
    mismatch_rows = int(mismatch_mask.sum())
    if mismatch_rows:
        checks.append(
            CheckResult(
                CHECK_EXACT_REQUEST_METADATA,
                "FAIL",
                f"{mismatch_rows} rows differ from the requested request key",
                mismatch_count=mismatch_rows,
                field_mismatch_counts=field_mismatch_counts,
            )
        )
    else:
        checks.append(CheckResult(CHECK_EXACT_REQUEST_METADATA, "PASS"))

    time_utc = pd.to_datetime(df["time_utc"], errors="coerce", utc=True)
    time_market = pd.to_datetime(df["time_market"], errors="coerce")
    if time_market.dt.tz is not None:
        # Parquet round trips may surface a session timezone (e.g. the local
        # machine timezone); the stored instant must be read in New York.
        time_market = time_market.dt.tz_convert("America/New_York")
    else:
        time_market = time_market.dt.tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="NaT"
        )
    valid_mask = time_utc.notna() & time_market.notna()

    invalid_count = int((~valid_mask).sum())
    if invalid_count:
        checks.append(
            CheckResult(
                CHECK_VALID_TIMESTAMPS,
                "FAIL",
                f"{invalid_count} rows have invalid or null timestamps",
                mismatch_count=invalid_count,
            )
        )
    else:
        checks.append(CheckResult(CHECK_VALID_TIMESTAMPS, "PASS"))

    if not valid_mask.any():
        for name in (
            CHECK_TIMEZONE_INSTANT_CONSISTENCY,
            CHECK_MARKET_CALENDAR_DATE_CONSISTENCY,
            CHECK_SESSION_LABEL_CONSISTENCY,
            CHECK_REQUESTED_SESSION_SCOPE,
            CHECK_DUPLICATE_TIMESTAMPS,
            CHECK_MINUTE_BOUNDARY_ALIGNMENT,
            CHECK_DELTA_GRID_ALIGNMENT,
            CHECK_INTERNAL_GAPS,
        ):
            checks.append(CheckResult(name, "INFO", "NOT_EVALUATED"))
        return {
            "checks": checks,
            "gaps": gaps,
            "first_time_market": None,
            "last_time_market": None,
            "session_row_counts": {},
            "segments": [],
        }

    # TIMEZONE_INSTANT_CONSISTENCY
    market_utc = (
        time_market.dt.tz_convert("UTC")
        if time_market.dt.tz is not None
        else time_market
    )
    tz_mismatches = int((market_utc[valid_mask] != time_utc[valid_mask]).sum())
    if tz_mismatches:
        checks.append(
            CheckResult(
                CHECK_TIMEZONE_INSTANT_CONSISTENCY,
                "FAIL",
                f"{tz_mismatches} rows disagree between market time and UTC",
                mismatch_count=tz_mismatches,
            )
        )
    else:
        checks.append(CheckResult(CHECK_TIMEZONE_INSTANT_CONSISTENCY, "PASS"))

    # MARKET_CALENDAR_DATE_CONSISTENCY
    if time_market.dt.tz is not None:
        ny_dates = time_market.dt.tz_convert("America/New_York").dt.date
    else:
        ny_dates = time_market.dt.date
    stored_dates = pd.to_datetime(df["market_calendar_date"], errors="coerce").dt.date
    calendar_mismatches = int((stored_dates[valid_mask] != ny_dates[valid_mask]).sum())
    if calendar_mismatches:
        checks.append(
            CheckResult(
                CHECK_MARKET_CALENDAR_DATE_CONSISTENCY,
                "FAIL",
                f"{calendar_mismatches} rows have a market_calendar_date that "
                "differs from their New York calendar date",
                mismatch_count=calendar_mismatches,
            )
        )
    else:
        checks.append(CheckResult(CHECK_MARKET_CALENDAR_DATE_CONSISTENCY, "PASS"))

    # SESSION_LABEL_CONSISTENCY
    recomputed = time_market[valid_mask].map(market_session_label)
    stored_sessions = df.loc[valid_mask, "session"].astype(str)
    session_mismatches = int((stored_sessions != recomputed).sum())
    unknown_sessions = int((recomputed == "UNKNOWN").sum())
    if session_mismatches or unknown_sessions:
        checks.append(
            CheckResult(
                CHECK_SESSION_LABEL_CONSISTENCY,
                "FAIL",
                f"{session_mismatches} label mismatches, {unknown_sessions} UNKNOWN",
                mismatch_count=session_mismatches + unknown_sessions,
            )
        )
    else:
        checks.append(CheckResult(CHECK_SESSION_LABEL_CONSISTENCY, "PASS"))

    # REQUESTED_SESSION_SCOPE
    if requested_session == "RTH":
        allowed = {"REGULAR"}
    elif requested_session == "ALL":
        allowed = set(SESSION_LABELS)
    else:
        allowed = None
    if allowed is None:
        checks.append(
            CheckResult(
                CHECK_REQUESTED_SESSION_SCOPE,
                "INFO",
                "SESSION_SCOPE_NOT_EVALUATED",
            )
        )
    else:
        stored_sessions = df["session"].astype(str)
        scope_mismatch_mask = ~stored_sessions.isin(allowed)
        scope_mismatch_count = int(scope_mismatch_mask.sum())
        if scope_mismatch_count:
            per_label = stored_sessions[scope_mismatch_mask].value_counts()
            label_counts = ", ".join(f"{label}: {count}" for label, count in per_label.items())
            checks.append(
                CheckResult(
                    CHECK_REQUESTED_SESSION_SCOPE,
                    "FAIL",
                    f"{scope_mismatch_count} rows outside the requested scope ({label_counts})",
                    mismatch_count=scope_mismatch_count,
                )
            )
        else:
            checks.append(CheckResult(CHECK_REQUESTED_SESSION_SCOPE, "PASS"))

    # DUPLICATE_TIMESTAMPS
    duplicate_count = int(df.duplicated(subset=["code", "time_utc"], keep=False).sum())
    if duplicate_count:
        checks.append(
            CheckResult(
                CHECK_DUPLICATE_TIMESTAMPS,
                "FAIL",
                f"{duplicate_count} rows share a duplicate (code, time_utc)",
                mismatch_count=duplicate_count,
            )
        )
    else:
        checks.append(CheckResult(CHECK_DUPLICATE_TIMESTAMPS, "PASS"))

    # MINUTE_BOUNDARY_ALIGNMENT
    seconds_off = time_utc.dt.second != 0
    micros_off = time_utc.dt.microsecond != 0
    boundary_violations = int((seconds_off | micros_off).sum())
    if boundary_violations:
        checks.append(
            CheckResult(
                CHECK_MINUTE_BOUNDARY_ALIGNMENT,
                "FAIL",
                f"{boundary_violations} rows are not aligned to a minute boundary",
                mismatch_count=boundary_violations,
            )
        )
    else:
        checks.append(CheckResult(CHECK_MINUTE_BOUNDARY_ALIGNMENT, "PASS"))

    # Segments, delta grid, internal gaps -- only inside contiguous observed
    # session segments.
    work = df.loc[valid_mask].copy()
    work["time_utc"] = time_utc[valid_mask]
    work["time_market"] = time_market[valid_mask]
    segments = _split_session_segments(work, interval_seconds)

    grid_violations = 0
    internal_gap_count = 0
    estimated_missing_total = 0
    for segment in segments:
        grid_violations += segment["grid_violations"]
        for gap in segment["gaps"]:
            gaps.append(gap)
            internal_gap_count += 1
            estimated_missing_total += gap.estimated_missing_bars

    if grid_violations:
        checks.append(
            CheckResult(
                CHECK_DELTA_GRID_ALIGNMENT,
                "FAIL",
                f"{grid_violations} adjacent deltas are non-positive or not an "
                f"integer multiple of {interval_seconds}s",
                mismatch_count=grid_violations,
            )
        )
    else:
        checks.append(CheckResult(CHECK_DELTA_GRID_ALIGNMENT, "PASS"))

    if internal_gap_count:
        checks.append(
            CheckResult(
                CHECK_INTERNAL_GAPS,
                "WARN",
                f"{internal_gap_count} internal gaps, ~{estimated_missing_total} "
                "estimated missing bars",
                mismatch_count=internal_gap_count,
            )
        )
    else:
        checks.append(CheckResult(CHECK_INTERNAL_GAPS, "PASS"))

    first_market = work["time_market"].iloc[0] if not work.empty else None
    last_market = work["time_market"].iloc[-1] if not work.empty else None
    session_counts = {label: 0 for label in SESSION_LABELS}
    for label, count in df["session"].value_counts().items():
        session_counts[str(label)] = int(count)

    return {
        "checks": checks,
        "gaps": gaps,
        "first_time_market": _iso_timestamp(first_market),
        "last_time_market": _iso_timestamp(last_market),
        "session_row_counts": session_counts,
        "segments": [segment["info"] for segment in segments],
    }


def _split_session_segments(df: pd.DataFrame, interval_seconds: int) -> list[dict]:
    """Split rows into contiguous observed session segments.

    A new segment starts whenever the canonical session label (recomputed
    with market_session_label) differs from the previous row, or when the
    session occurrence date changes -- so two OVERNIGHT observations on
    consecutive calendar days stay separate. Deltas and gaps are only
    computed inside one segment; JSON output uses market time while delta
    arithmetic always uses UTC instants.
    """
    segments: list[dict] = []
    current_session: str | None = None
    current_occurrence: date | None = None
    utc_rows: list[pd.Timestamp] = []
    market_rows: list[pd.Timestamp] = []
    segment_first_market: pd.Timestamp | None = None
    segment_last_market: pd.Timestamp | None = None

    def flush() -> None:
        nonlocal utc_rows, market_rows, current_session, current_occurrence
        nonlocal segment_first_market, segment_last_market
        if not utc_rows:
            return
        segment_id = len(segments) + 1
        grid_violations = 0
        gap_details: list[GapDetail] = []
        for prev_utc, cur_utc, prev_market, cur_market in zip(
            utc_rows, utc_rows[1:], market_rows, market_rows[1:]
        ):
            delta = (cur_utc - prev_utc).total_seconds()
            if delta <= 0 or delta % interval_seconds != 0:
                grid_violations += 1
            elif delta > interval_seconds:
                gap_details.append(
                    GapDetail(
                        session=current_session or "UNKNOWN",
                        segment_id=segment_id,
                        previous_time_market=_iso_timestamp(prev_market) or "",
                        next_time_market=_iso_timestamp(cur_market) or "",
                        delta_seconds=int(delta),
                        estimated_missing_bars=int(delta // interval_seconds - 1),
                    )
                )
        segments.append(
            {
                "info": SegmentInfo(
                    segment_id=segment_id,
                    session=current_session or "UNKNOWN",
                    first_time_market=_iso_timestamp(segment_first_market),
                    last_time_market=_iso_timestamp(segment_last_market),
                    row_count=len(utc_rows),
                    internal_gap_count=len(gap_details),
                    estimated_missing_bar_count=sum(
                        gap.estimated_missing_bars for gap in gap_details
                    ),
                ),
                "grid_violations": grid_violations,
                "gaps": gap_details,
            }
        )
        utc_rows = []
        market_rows = []
        current_session = None
        current_occurrence = None
        segment_first_market = None
        segment_last_market = None

    for row in df.itertuples(index=False):
        time_utc_ts = getattr(row, "time_utc")
        time_market_ts = getattr(row, "time_market")
        session = market_session_label(time_market_ts)
        occurrence = session_occurrence_date(time_market_ts, session)
        if session != current_session or occurrence != current_occurrence:
            flush()
            current_session = session
            current_occurrence = occurrence
            segment_first_market = time_market_ts
        utc_rows.append(time_utc_ts)
        market_rows.append(time_market_ts)
        segment_last_market = time_market_ts
    flush()
    return segments


def _build_intraday_summary(
    item_results: dict[str, list[ItemAuditResult]],
    state,
    normalized_symbols: list[str],
) -> IntradaySummary:
    audited = [
        item
        for code in normalized_symbols
        for item in item_results[code]
        if item.audit_status in (PASS, WARN, FAILED)
    ]
    summary = IntradaySummary(
        total_expected_items=sum(len(items) for items in item_results.values()),
        complete_source_item_count=len(state.complete_items),
        incomplete_source_item_count=len(state.incomplete_items),
        missing_source_item_count=sum(
            1 for code in normalized_symbols for item in item_results[code]
            if item.source_state == "MISSING"
        ),
        audited_item_count=len(audited),
        pass_item_count=sum(1 for item in audited if item.audit_status == PASS),
        warn_item_count=sum(1 for item in audited if item.audit_status == WARN),
        fail_item_count=sum(1 for item in audited if item.audit_status == FAILED),
        total_snapshot_rows=sum(
            item.selected_snapshot.row_count for item in audited if item.selected_snapshot
        ),
        duplicate_timestamp_count=sum(
            _check_mismatch(item, CHECK_DUPLICATE_TIMESTAMPS) for item in audited
        ),
        invalid_timestamp_count=sum(
            _check_mismatch(item, CHECK_VALID_TIMESTAMPS) for item in audited
        ),
        internal_gap_count=sum(
            _check_mismatch(item, CHECK_INTERNAL_GAPS) for item in audited
        ),
        estimated_missing_bar_count=sum(
            _estimated_missing(item) for item in audited
        ),
        coverage_percentage=_coverage_percentage(
            len(state.complete_items),
            sum(len(items) for items in item_results.values()),
        ),
    )
    return summary


def _check_mismatch(item: ItemAuditResult, check_name: str) -> int:
    for check in item.checks:
        if check.name == check_name:
            return check.mismatch_count or 0
    return 0


def _estimated_missing(item: ItemAuditResult) -> int:
    total = 0
    for segment in item.segments:
        total += segment.estimated_missing_bar_count
    return total


def _coverage_percentage(complete_count: int, expected_count: int) -> float:
    if expected_count <= 0:
        return 100.0
    return round(complete_count / expected_count * 100, 2)


def _intraday_overall_status(summary: IntradaySummary) -> str:
    if summary.fail_item_count > 0:
        return FAILED
    if (
        summary.warn_item_count > 0
        or summary.incomplete_source_item_count > 0
        or summary.missing_source_item_count > 0
    ):
        return WARN
    return PASS
