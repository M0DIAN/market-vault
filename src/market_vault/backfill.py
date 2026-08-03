from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .models import DatasetRunManifest, QualityResult, Settings
from .normalization.calendar import normalize_calendar_code, normalize_calendar_market
from .service import _hash_config, collect_history
from .storage import Catalog


QUALITY_FAIL_ERROR = "Child run failed bar quality checks"


def _record_successful_date(manifest: DatasetRunManifest, symbol: str, trade_date: date) -> None:
    """Record a successful symbol/trade-date pair, at most once.

    A symbol can be retried within the same trade date (e.g. after a child
    run failed bar quality checks and later recovered), so the date must not
    be appended a second time on a successful retry.
    """
    dates = manifest.parameters["successful_dates_by_symbol"].setdefault(symbol, [])
    iso_date = trade_date.isoformat()
    if iso_date not in dates:
        dates.append(iso_date)


@dataclass(frozen=True)
class BackfillItem:
    code: str
    trade_date: date


@dataclass
class BackfillPlan:
    symbols: list[str]
    trading_dates: list[date]
    pending_items: list[BackfillItem]
    skipped_items: list[BackfillItem]
    calendar_scope_type: str
    calendar_scope_value: str
    start_date_by_symbol: dict[str, date] = field(default_factory=dict)


def normalize_backfill_symbols(symbols: list[str]) -> list[str]:
    normalized: list[str] = []
    for symbol in symbols:
        cleaned = symbol.strip().upper()
        if not cleaned:
            raise ValueError("symbols cannot include blank values")
        normalized.append(cleaned)
    unique = sorted(set(normalized))
    if not unique:
        raise ValueError("At least one symbol is required")
    return unique


def normalize_history_parameters(
    interval: str,
    session: str,
    adjustment: str,
    max_retries: int,
    retry_backoff_seconds: float,
) -> tuple[str, str, str]:
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")
    if retry_backoff_seconds < 0:
        raise ValueError("retry_backoff_seconds cannot be negative")
    return interval.lower(), session.upper(), adjustment.upper()


def resolve_calendar_scope(calendar_market: str | None, calendar_code: str | None) -> tuple[str, str]:
    normalized_market = normalize_calendar_market(calendar_market)
    normalized_code = normalize_calendar_code(calendar_code)
    if bool(normalized_market) == bool(normalized_code):
        raise ValueError("Provide exactly one of calendar_market or calendar_code")
    if normalized_market:
        return "MARKET", normalized_market
    assert normalized_code is not None
    return "CODE", normalized_code


def merge_date_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[tuple[date, date]] = []
    current_start, current_end = ordered[0]
    for start_date, end_date in ordered[1:]:
        if start_date <= current_end + timedelta(days=1):
            current_end = max(current_end, end_date)
            continue
        merged.append((current_start, current_end))
        current_start, current_end = start_date, end_date
    merged.append((current_start, current_end))
    return merged


def missing_coverage_ranges(
    requested_start_date: date,
    requested_end_date: date,
    ranges: list[tuple[date, date]],
) -> list[tuple[date, date]]:
    gaps: list[tuple[date, date]] = []
    cursor = requested_start_date
    for start_date, end_date in merge_date_ranges(ranges):
        if end_date < requested_start_date or start_date > requested_end_date:
            continue
        effective_start = max(start_date, requested_start_date)
        effective_end = min(end_date, requested_end_date)
        if effective_start > cursor:
            gaps.append((cursor, effective_start - timedelta(days=1)))
        cursor = max(cursor, effective_end + timedelta(days=1))
        if cursor > requested_end_date:
            break
    if cursor <= requested_end_date:
        gaps.append((cursor, requested_end_date))
    return gaps


def plan_history_backfill(
    settings: Settings,
    *,
    symbols: list[str],
    end_date: date,
    calendar_market: str | None = None,
    calendar_code: str | None = None,
    start_date: date | None = None,
    interval: str = "1m",
    session: str = "ALL",
    adjustment: str = "NONE",
    force: bool = False,
    incremental: bool = False,
    bootstrap_start_date: date | None = None,
    today: date | None = None,
) -> BackfillPlan:
    effective_today = today or datetime.now(timezone.utc).date()
    if end_date >= effective_today:
        raise ValueError("end_date must be before today's UTC date")
    if bootstrap_start_date is not None and bootstrap_start_date >= effective_today:
        raise ValueError("bootstrap_start_date must be before today's UTC date")

    normalized_symbols = normalize_backfill_symbols(symbols)
    interval, session, adjustment = normalize_history_parameters(interval, session, adjustment, 0, 0.0)
    scope_type, scope_value = resolve_calendar_scope(calendar_market, calendar_code)
    catalog = Catalog(settings)

    start_date_by_symbol: dict[str, date] = {}
    if incremental:
        if start_date is not None:
            raise ValueError("start_date is not used with incremental mode")
        latest_dates = catalog.latest_completed_market_bar_dates(
            symbols=normalized_symbols,
            interval=interval,
            requested_session=session,
            adjustment=adjustment,
            source_schema_version=settings.source_schema_version,
            end_date=end_date,
        )
        missing_bootstrap = [symbol for symbol in normalized_symbols if symbol not in latest_dates and bootstrap_start_date is None]
        if missing_bootstrap:
            raise ValueError(
                "bootstrap_start_date is required for symbols with no completed history: "
                + ", ".join(sorted(missing_bootstrap))
            )
        for symbol in normalized_symbols:
            latest_date = latest_dates.get(symbol)
            if latest_date is not None:
                next_date = catalog.next_trading_date(scope_type, scope_value, latest_date, end_date)
                if next_date is not None:
                    start_date_by_symbol[symbol] = next_date
                else:
                    # The local calendar has no trading day after the latest
                    # completed date within end_date: the symbol is caught up
                    # and has no pending work for this run. Start beyond
                    # end_date so it contributes no items and no coverage
                    # requirement.
                    start_date_by_symbol[symbol] = end_date + timedelta(days=1)
            else:
                assert bootstrap_start_date is not None
                start_date_by_symbol[symbol] = bootstrap_start_date
    else:
        if start_date is None:
            raise ValueError("start_date is required unless incremental mode is enabled")
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        if start_date >= effective_today:
            raise ValueError("start_date must be before today's UTC date")
        start_date_by_symbol = {symbol: start_date for symbol in normalized_symbols}

    requested_start_candidates = [value for value in start_date_by_symbol.values() if value <= end_date]
    if not requested_start_candidates:
        return BackfillPlan(
            symbols=normalized_symbols,
            trading_dates=[],
            pending_items=[],
            skipped_items=[],
            calendar_scope_type=scope_type,
            calendar_scope_value=scope_value,
            start_date_by_symbol=start_date_by_symbol,
        )

    requested_start_date = min(requested_start_candidates)
    coverage_ranges = catalog.trading_calendar_requested_ranges(
        scope_type,
        scope_value,
        requested_start_date,
        end_date,
    )
    if not coverage_ranges:
        raise ValueError(
            "Local trading calendar has no coverage for the requested range. "
            "Run the calendar command before backfill."
        )
    gaps = missing_coverage_ranges(requested_start_date, end_date, coverage_ranges)
    if gaps:
        gap_text = ", ".join(f"{item[0].isoformat()} to {item[1].isoformat()}" for item in gaps)
        raise ValueError(
            "Local trading calendar does not fully cover the requested range. "
            f"Missing coverage: {gap_text}. Run the calendar command first."
        )

    trading_dates = catalog.trading_calendar_dates(scope_type, scope_value, requested_start_date, end_date)
    all_items: list[BackfillItem] = []
    for trade_date in trading_dates:
        for symbol in normalized_symbols:
            symbol_start_date = start_date_by_symbol[symbol]
            if trade_date >= symbol_start_date and trade_date <= end_date:
                all_items.append(BackfillItem(code=symbol, trade_date=trade_date))
    all_items.sort(key=lambda item: (item.trade_date, item.code))
    if force or not all_items:
        return BackfillPlan(
            symbols=normalized_symbols,
            trading_dates=trading_dates,
            pending_items=all_items,
            skipped_items=[],
            calendar_scope_type=scope_type,
            calendar_scope_value=scope_value,
            start_date_by_symbol=start_date_by_symbol,
        )

    completed = catalog.completed_market_bar_items(
        symbols=normalized_symbols,
        trade_dates=sorted({item.trade_date for item in all_items}),
        interval=interval,
        requested_session=session,
        adjustment=adjustment,
        source_schema_version=settings.source_schema_version,
    )
    pending_items: list[BackfillItem] = []
    skipped_items: list[BackfillItem] = []
    for item in all_items:
        if (item.code, item.trade_date) in completed:
            skipped_items.append(item)
        else:
            pending_items.append(item)
    return BackfillPlan(
        symbols=normalized_symbols,
        trading_dates=trading_dates,
        pending_items=pending_items,
        skipped_items=skipped_items,
        calendar_scope_type=scope_type,
        calendar_scope_value=scope_value,
        start_date_by_symbol=start_date_by_symbol,
    )


def collect_history_backfill(
    settings: Settings,
    *,
    symbols: list[str],
    end_date: date,
    calendar_market: str | None = None,
    calendar_code: str | None = None,
    start_date: date | None = None,
    interval: str = "1m",
    session: str = "ALL",
    adjustment: str = "NONE",
    force: bool = False,
    incremental: bool = False,
    bootstrap_start_date: date | None = None,
    max_retries: int = 2,
    retry_backoff_seconds: float = 2.0,
    today: date | None = None,
) -> DatasetRunManifest:
    requested_items = _safe_requested_items(symbols)
    interval, session, adjustment = normalize_history_parameters(
        interval,
        session,
        adjustment,
        max_retries,
        retry_backoff_seconds,
    )
    scope_type, scope_value = resolve_calendar_scope(calendar_market, calendar_code)
    parameters = {
        "mode": "INCREMENTAL" if incremental else "BACKFILL",
        "calendar_scope_type": scope_type,
        "calendar_scope_value": scope_value,
        "requested_start_date": start_date.isoformat() if start_date else None,
        "requested_end_date": end_date.isoformat(),
        "bootstrap_start_date": bootstrap_start_date.isoformat() if bootstrap_start_date else None,
        "interval": interval,
        "session": session,
        "adjustment": adjustment,
        "source_schema_version": settings.source_schema_version,
        "force": force,
        "max_retries": max_retries,
        "retry_backoff_seconds": retry_backoff_seconds,
        "trading_date_count": 0,
        "total_item_count": 0,
        "planned_item_count": 0,
        "skipped_item_count": 0,
        "successful_item_count": 0,
        "failed_item_count": 0,
        "child_run_ids": [],
        "successful_dates_by_symbol": {item: [] for item in requested_items},
        "skipped_dates_by_symbol": {item: [] for item in requested_items},
        "failed_dates_by_symbol": {item: [] for item in requested_items},
    }
    manifest = DatasetRunManifest(
        dataset="market_bars_backfill",
        requested_items=requested_items,
        parameters=parameters,
    )
    manifest.config_hash = _hash_config(
        {
            "requested_items": requested_items,
            "mode": parameters["mode"],
            "calendar_scope_type": scope_type,
            "calendar_scope_value": scope_value,
            "requested_start_date": parameters["requested_start_date"],
            "requested_end_date": parameters["requested_end_date"],
            "bootstrap_start_date": parameters["bootstrap_start_date"],
            "interval": interval,
            "session": session,
            "adjustment": adjustment,
            "source_schema_version": settings.source_schema_version,
            "force": force,
            "max_retries": max_retries,
            "retry_backoff_seconds": retry_backoff_seconds,
        }
    )

    catalog = Catalog(settings)
    quality_results: list[QualityResult] = []
    try:
        plan = plan_history_backfill(
            settings,
            symbols=symbols,
            end_date=end_date,
            calendar_market=calendar_market,
            calendar_code=calendar_code,
            start_date=start_date,
            interval=interval,
            session=session,
            adjustment=adjustment,
            force=force,
            incremental=incremental,
            bootstrap_start_date=bootstrap_start_date,
            today=today,
        )
    except Exception as exc:
        manifest.failed_items["PLAN"] = str(exc)
        quality_results.append(
            QualityResult(
                check_name="backfill_plan",
                result="FAIL",
                expected_value="valid local calendar coverage and historical-only date range",
                actual_value=str(exc),
            )
        )
        return _finish_backfill_manifest(settings, catalog, manifest, quality_results)

    manifest.requested_items = plan.symbols
    manifest.parameters["requested_start_date"] = _requested_start_text(plan, start_date, bootstrap_start_date)
    manifest.parameters["trading_date_count"] = len(plan.trading_dates)
    manifest.parameters["total_item_count"] = len(plan.pending_items) + len(plan.skipped_items)
    manifest.parameters["planned_item_count"] = len(plan.pending_items)
    manifest.parameters["skipped_item_count"] = len(plan.skipped_items)
    manifest.parameters["planned_start_date_by_symbol"] = {
        symbol: value.isoformat() for symbol, value in sorted(plan.start_date_by_symbol.items())
    }
    for item in plan.skipped_items:
        manifest.parameters["skipped_dates_by_symbol"][item.code].append(item.trade_date.isoformat())

    quality_results.append(
        QualityResult(
            check_name="calendar_coverage",
            result="PASS",
            expected_value=f"{plan.calendar_scope_type}:{plan.calendar_scope_value}",
            actual_value=f"{len(plan.trading_dates)} trading dates",
        )
    )

    if not plan.pending_items:
        manifest.successful_items = list(plan.symbols)
        return _finalize_backfill_counts(settings, catalog, manifest, quality_results)

    pending_by_date: dict[date, list[str]] = {}
    for item in plan.pending_items:
        pending_by_date.setdefault(item.trade_date, []).append(item.code)
    for trade_date in sorted(pending_by_date):
        remaining_symbols = sorted(pending_by_date[trade_date])
        last_errors: dict[str, str] = {}
        for attempt in range(max_retries + 1):
            if not remaining_symbols:
                break
            try:
                child_manifest = collect_history(
                    settings=settings,
                    trade_date=trade_date,
                    symbols=remaining_symbols,
                    interval=interval,
                    session=session,
                    adjustment=adjustment,
                )
                manifest.parameters["child_run_ids"].append(child_manifest.run_id)
                manifest.row_count += child_manifest.row_count
                last_errors = {
                    symbol: str(error) for symbol, error in child_manifest.failed_symbols.items()
                }
                if catalog.run_has_quality_fail(child_manifest.run_id):
                    # Bar quality checks are recorded at the child-run level,
                    # so a failing run cannot tell us which symbol failed the
                    # checks. Conservatively treat every symbol this run
                    # reported as successful as still incomplete for this
                    # trade date: do not record it as successful and keep it
                    # in the retry set together with the network failures.
                    for symbol in child_manifest.successful_symbols:
                        last_errors[symbol] = QUALITY_FAIL_ERROR
                else:
                    for symbol in child_manifest.successful_symbols:
                        _record_successful_date(manifest, symbol, trade_date)
                remaining_symbols = sorted(last_errors)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                error_text = str(exc)
                last_errors = {symbol: error_text for symbol in remaining_symbols}
            if not remaining_symbols:
                break
            if attempt >= max_retries:
                break
            delay = min(60.0, retry_backoff_seconds * (2 ** attempt))
            if delay > 0:
                time.sleep(delay)
        for symbol in remaining_symbols:
            manifest.parameters["failed_dates_by_symbol"][symbol].append(
                {"date": trade_date.isoformat(), "error": last_errors.get(symbol, "Unknown error")}
            )

    for symbol in plan.symbols:
        failures = manifest.parameters["failed_dates_by_symbol"][symbol]
        if failures:
            summary = "; ".join(f"{item['date']}: {item['error']}" for item in failures)
            manifest.failed_items[symbol] = summary
        else:
            manifest.successful_items.append(symbol)
    return _finalize_backfill_counts(settings, catalog, manifest, quality_results)


def _finalize_backfill_counts(
    settings: Settings,
    catalog: Catalog,
    manifest: DatasetRunManifest,
    quality_results: list[QualityResult],
) -> DatasetRunManifest:
    manifest.parameters["successful_item_count"] = sum(
        len(items) for items in manifest.parameters["successful_dates_by_symbol"].values()
    )
    manifest.parameters["failed_item_count"] = sum(
        len(items) for items in manifest.parameters["failed_dates_by_symbol"].values()
    )
    return _finish_backfill_manifest(settings, catalog, manifest, quality_results)


def _requested_start_text(
    plan: BackfillPlan,
    start_date: date | None,
    bootstrap_start_date: date | None,
) -> str | None:
    if start_date is not None:
        return start_date.isoformat()
    if plan.start_date_by_symbol:
        return min(plan.start_date_by_symbol.values()).isoformat()
    if bootstrap_start_date is not None:
        return bootstrap_start_date.isoformat()
    return None


def _safe_requested_items(symbols: list[str]) -> list[str]:
    items = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    return items


def _finish_backfill_manifest(
    settings: Settings,
    catalog: Catalog,
    manifest: DatasetRunManifest,
    quality_results: list[QualityResult],
) -> DatasetRunManifest:
    successful_item_count = int(manifest.parameters.get("successful_item_count", 0))
    skipped_item_count = int(manifest.parameters.get("skipped_item_count", 0))
    failed_item_count = int(manifest.parameters.get("failed_item_count", 0))
    manifest.finished_at = datetime.now(timezone.utc)
    if successful_item_count == 0 and skipped_item_count == 0:
        # Nothing was collected or skipped. This relies on two invariants:
        # (1) any plan or item failure records an entry in failed_items
        # (plan failures under the "PLAN" key, item failures under their
        # symbol), and (2) an empty plan that completed normally never
        # records failures. So an empty failed_items means the plan had
        # no work to do -> SUCCESS; a non-empty failed_items means the
        # plan failed or all items failed -> FAILED.
        manifest.status = "SUCCESS" if not manifest.failed_items else "FAILED"
    elif failed_item_count > 0:
        manifest.status = "PARTIAL"
    elif any(result.result in {"FAIL", "WARN"} for result in quality_results):
        manifest.status = "PARTIAL"
    else:
        manifest.status = "SUCCESS"

    settings.manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.manifest_dir / f"{manifest.dataset}_{manifest.run_id}.json"
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.report_dir / f"{manifest.dataset}_{manifest.run_id}.json"
    report_path.write_text(json.dumps([item.as_dict() for item in quality_results], ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.quality_report = str(report_path)
    manifest_path.write_text(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    catalog.record_dataset_run(manifest)
    catalog.record_quality(manifest.run_id, quality_results)
    return manifest
