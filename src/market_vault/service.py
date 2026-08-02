from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from .collectors import MoomooCalendarCollector, MoomooHistoryCollector, MoomooOptionCollector
from .collectors.moomoo_options import OPTION_VOLATILITY_PERIOD_VALUES, select_option_volatility_period
from .models import DatasetRunManifest, RunManifest, Settings
from .normalization import (
    normalize_bars,
    normalize_option_contracts,
    normalize_option_volatility,
    normalize_trading_calendar,
)
from .quality import (
    run_bar_quality_checks,
    run_option_contract_quality_checks,
    run_option_volatility_quality_checks,
    run_trading_calendar_quality_checks,
)
from .storage import Catalog, ParquetStore


def _hash_config(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def option_chain_date_chunks(start_date: date, end_date: date) -> list[tuple[date, date]]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    chunks: list[tuple[date, date]] = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=29), end_date)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def collect_history(
    settings: Settings,
    trade_date: date,
    symbols: list[str],
    interval: str,
    session: str,
    adjustment: str,
) -> RunManifest:
    if not symbols:
        raise ValueError("At least one symbol is required")

    manifest = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=sorted(set(symbols)),
        interval=interval.lower(),
        session=session.upper(),
        adjustment=adjustment.upper(),
    )
    manifest.config_hash = _hash_config(
        {
            "trade_date": trade_date.isoformat(),
            "symbols": manifest.requested_symbols,
            "interval": manifest.interval,
            "session": manifest.session,
            "adjustment": manifest.adjustment,
            "source_schema_version": settings.source_schema_version,
        }
    )

    raw_frames: list[pd.DataFrame] = []
    curated_frames: list[pd.DataFrame] = []

    with MoomooHistoryCollector(settings) as collector:
        for symbol in manifest.requested_symbols:
            try:
                raw = collector.fetch_history(
                    code=symbol,
                    trade_date=trade_date,
                    interval=manifest.interval,
                    adjustment=manifest.adjustment,
                    session=manifest.session,
                )
                if raw.empty:
                    raise RuntimeError("No data returned")
                raw = raw.copy()
                raw["requested_trade_date"] = trade_date
                raw["interval"] = manifest.interval
                raw["adjustment"] = manifest.adjustment
                raw["requested_session"] = manifest.session
                raw["ingestion_run_id"] = manifest.run_id
                raw_frames.append(raw)

                curated = normalize_bars(
                    frame=raw,
                    requested_trade_date=trade_date,
                    interval=manifest.interval,
                    adjustment=manifest.adjustment,
                    source=settings.source,
                    source_schema_version=settings.source_schema_version,
                    run_id=manifest.run_id,
                )
                curated_frames.append(curated)
                manifest.successful_symbols.append(symbol)
            except Exception as exc:  # preserve per-symbol failures and continue the batch
                manifest.failed_symbols[symbol] = str(exc)

    store = ParquetStore(settings)
    catalog = Catalog(settings)
    quality_results = []

    if raw_frames:
        raw_all = pd.concat(raw_frames, ignore_index=True)
        curated_all = pd.concat(curated_frames, ignore_index=True)
        raw_path = store.write_raw(
            raw_all,
            trade_date,
            manifest.interval,
            manifest.requested_symbols,
            manifest.session,
            manifest.adjustment,
        )
        curated_path = store.write_curated(
            curated_all,
            trade_date,
            manifest.interval,
            manifest.requested_symbols,
            manifest.session,
            manifest.adjustment,
        )
        manifest.raw_file = str(raw_path)
        manifest.curated_file = str(curated_path)
        manifest.row_count = len(curated_all)
        quality_results = run_bar_quality_checks(curated_all)
        catalog.refresh_market_bars_view()

    manifest.finished_at = datetime.now(timezone.utc)
    if not manifest.successful_symbols:
        manifest.status = "FAILED"
    elif manifest.failed_symbols:
        manifest.status = "PARTIAL"
    elif any(r.result == "FAIL" for r in quality_results):
        manifest.status = "PARTIAL"
    else:
        manifest.status = "SUCCESS"

    settings.manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.manifest_dir / f"{trade_date.isoformat()}_{manifest.run_id}.json"
    manifest_path.write_text(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    settings.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.report_dir / f"{trade_date.isoformat()}_{manifest.run_id}.json"
    report_path.write_text(
        json.dumps([r.as_dict() for r in quality_results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    catalog.record_run(manifest)
    catalog.record_quality(manifest.run_id, quality_results)
    return manifest


def _finish_dataset_run(
    settings: Settings,
    catalog: Catalog,
    manifest: DatasetRunManifest,
    quality_results: list,
) -> DatasetRunManifest:
    manifest.finished_at = datetime.now(timezone.utc)
    if not manifest.successful_items:
        manifest.status = "FAILED"
    elif manifest.failed_items:
        manifest.status = "PARTIAL"
    elif any(r.result in {"FAIL", "WARN"} for r in quality_results):
        manifest.status = "PARTIAL"
    else:
        manifest.status = "SUCCESS"

    settings.manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.manifest_dir / f"{manifest.dataset}_{manifest.run_id}.json"
    manifest_path.write_text(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    settings.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.report_dir / f"{manifest.dataset}_{manifest.run_id}.json"
    report_path.write_text(
        json.dumps([r.as_dict() for r in quality_results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest.quality_report = str(report_path)

    manifest_path.write_text(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    catalog.record_dataset_run(manifest)
    catalog.record_quality(manifest.run_id, quality_results)
    return manifest


def collect_option_chain(
    settings: Settings,
    underlying: str,
    start_date: date,
    end_date: date,
    option_type: str = "ALL",
    option_cond_type: str = "ALL",
) -> DatasetRunManifest:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    chunk_ranges = option_chain_date_chunks(start_date, end_date)
    chunk_range_dicts = [
        {"start_date": chunk_start.isoformat(), "end_date": chunk_end.isoformat()}
        for chunk_start, chunk_end in chunk_ranges
    ]

    manifest = DatasetRunManifest(
        dataset="option_contracts",
        requested_items=[underlying],
        parameters={
            "underlying": underlying,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "requested_start_date": start_date.isoformat(),
            "requested_end_date": end_date.isoformat(),
            "option_type": option_type.upper(),
            "option_cond_type": option_cond_type.upper(),
            "source_schema_version": settings.source_schema_version,
            "chunk_count": len(chunk_ranges),
            "chunk_ranges": chunk_range_dicts,
            "successful_chunks": [],
            "failed_chunks": [],
            "returned_contract_count": 0,
            "api_request_count": len(chunk_ranges),
            "successful_api_request_count": 0,
            "failed_api_request_count": 0,
        },
    )
    manifest.config_hash = _hash_config(manifest.parameters)

    raw_frames: list[pd.DataFrame] = []
    curated = pd.DataFrame()
    captured_at = pd.Timestamp.now(tz="UTC")
    try:
        with MoomooOptionCollector(settings) as collector:
            for index, (chunk_start, chunk_end) in enumerate(chunk_ranges):
                chunk_info = {"start_date": chunk_start.isoformat(), "end_date": chunk_end.isoformat()}
                try:
                    raw_chunk = collector.fetch_option_chain(
                        underlying=underlying,
                        start_date=chunk_start,
                        end_date=chunk_end,
                        option_type=option_type,
                        option_cond_type=option_cond_type,
                    )
                    if raw_chunk.empty:
                        raise RuntimeError("No option contracts returned")
                    raw_chunk = raw_chunk.copy()
                    raw_chunk["underlying_code"] = underlying
                    raw_chunk["requested_start_date"] = start_date
                    raw_chunk["requested_end_date"] = end_date
                    raw_chunk["chunk_start_date"] = chunk_start
                    raw_chunk["chunk_end_date"] = chunk_end
                    raw_chunk["capture_date"] = captured_at.date()
                    raw_chunk["captured_at"] = captured_at
                    raw_chunk["ingestion_run_id"] = manifest.run_id
                    raw_frames.append(raw_chunk)
                    manifest.parameters["successful_chunks"].append(chunk_info)
                except Exception as exc:
                    failed = dict(chunk_info)
                    failed["error"] = str(exc)
                    manifest.parameters["failed_chunks"].append(failed)
                    manifest.failed_items[f"{chunk_start.isoformat()}_{chunk_end.isoformat()}"] = str(exc)
                if index < len(chunk_ranges) - 1:
                    time.sleep(settings.request_pause_seconds)
    except Exception as exc:
        for chunk_start, chunk_end in chunk_ranges:
            failed = {
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "error": str(exc),
            }
            manifest.parameters["failed_chunks"].append(failed)
            manifest.failed_items[f"{chunk_start.isoformat()}_{chunk_end.isoformat()}"] = str(exc)

    store = ParquetStore(settings)
    catalog = Catalog(settings)
    raw = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()
    if not raw.empty:
        curated = normalize_option_contracts(
            frame=raw,
            underlying_code=underlying,
            captured_at=captured_at,
            source=settings.source,
            source_schema_version=settings.source_schema_version,
            run_id=manifest.run_id,
        )
        manifest.successful_items.append(underlying)
        manifest.parameters["returned_contract_count"] = len(curated)
    manifest.parameters["successful_api_request_count"] = len(manifest.parameters["successful_chunks"])
    manifest.parameters["failed_api_request_count"] = len(manifest.parameters["failed_chunks"])
    quality_results = run_option_contract_quality_checks(curated)
    if not raw.empty:
        raw_path = store.write_option_chain_raw(raw, underlying, captured_at.date(), manifest.run_id)
        curated_path = store.write_option_contracts_curated(curated, underlying, captured_at.date(), manifest.run_id)
        manifest.raw_file = str(raw_path)
        manifest.curated_file = str(curated_path)
        manifest.row_count = len(curated)
        catalog.refresh_option_contract_views()

    if not manifest.successful_items and not manifest.failed_items:
        manifest.failed_items[underlying] = "No option contracts returned"

    return _finish_dataset_run(settings, catalog, manifest, quality_results)


def collect_option_volatility(
    settings: Settings,
    codes: list[str],
    start_date: date,
    end_date: date,
    as_of_date: date | None = None,
    hv_time_period: int = 30,
) -> DatasetRunManifest:
    if not codes:
        raise ValueError("At least one option code is required")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    effective_as_of_date = as_of_date or datetime.now(timezone.utc).date()
    query_time_period = select_option_volatility_period(start_date, effective_as_of_date)
    query_time_period_value = OPTION_VOLATILITY_PERIOD_VALUES[query_time_period]
    captured_at = pd.Timestamp.now(tz="UTC")

    requested_codes = sorted(set(codes))
    manifest = DatasetRunManifest(
        dataset="option_volatility_daily",
        requested_items=requested_codes,
        parameters={
            "codes": requested_codes,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source": settings.source,
            "query_time_period": query_time_period,
            "query_time_period_value": query_time_period_value,
            "hv_time_period": hv_time_period,
            "as_of_date": effective_as_of_date.isoformat(),
            "requested_start_date": start_date.isoformat(),
            "requested_end_date": end_date.isoformat(),
            "returned_min_date": None,
            "returned_max_date": None,
            "range_complete": False,
            "coverage_by_code": {},
            "api_request_count": len(requested_codes),
            "successful_api_request_count": 0,
            "failed_api_request_count": 0,
        },
    )
    manifest.config_hash = _hash_config(manifest.parameters)

    raw_frames: list[pd.DataFrame] = []
    curated_frames: list[pd.DataFrame] = []
    try:
        with MoomooOptionCollector(settings) as collector:
            for code in requested_codes:
                try:
                    raw = collector.fetch_option_volatility(code, query_time_period, hv_time_period)
                    if raw.empty:
                        raise RuntimeError("API returned no option volatility rows")
                    raw = raw.copy()
                    raw["option_code"] = code
                    raw["requested_start_date"] = start_date
                    raw["requested_end_date"] = end_date
                    raw["query_time_period"] = query_time_period
                    raw["hv_time_period"] = hv_time_period
                    raw["captured_at"] = captured_at
                    raw["ingestion_run_id"] = manifest.run_id
                    raw_frames.append(raw)
                    curated = normalize_option_volatility(
                        frame=raw,
                        option_code=code,
                        start_date=start_date,
                        end_date=end_date,
                        source=settings.source,
                        run_id=manifest.run_id,
                        source_schema_version=settings.source_schema_version,
                        captured_at=captured_at,
                    )
                    if curated.empty:
                        raise RuntimeError("API returned rows, but none were inside the requested date range")
                    curated_frames.append(curated)
                    manifest.successful_items.append(code)
                except Exception as exc:
                    manifest.failed_items[code] = str(exc)
    except Exception as exc:
        for code in requested_codes:
            manifest.failed_items[code] = str(exc)

    store = ParquetStore(settings)
    catalog = Catalog(settings)
    curated_all = pd.concat(curated_frames, ignore_index=True) if curated_frames else pd.DataFrame()
    raw_all = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()
    coverage_by_code = _option_volatility_coverage_by_code(curated_all, start_date, end_date)
    returned_mins = [item["returned_min_date"] for item in coverage_by_code.values() if item["returned_min_date"]]
    returned_maxes = [item["returned_max_date"] for item in coverage_by_code.values() if item["returned_max_date"]]
    returned_min_date = min(date.fromisoformat(item) for item in returned_mins) if returned_mins else None
    returned_max_date = max(date.fromisoformat(item) for item in returned_maxes) if returned_maxes else None
    range_complete = bool(coverage_by_code) and all(item["range_complete"] for item in coverage_by_code.values())
    manifest.parameters["returned_min_date"] = returned_min_date.isoformat() if returned_min_date else None
    manifest.parameters["returned_max_date"] = returned_max_date.isoformat() if returned_max_date else None
    manifest.parameters["range_complete"] = range_complete
    manifest.parameters["coverage_by_code"] = coverage_by_code
    manifest.parameters["successful_api_request_count"] = len(manifest.successful_items)
    manifest.parameters["failed_api_request_count"] = len(manifest.failed_items)
    quality_results = run_option_volatility_quality_checks(
        curated_all,
        start_date,
        end_date,
        returned_min_date=returned_min_date,
        returned_max_date=returned_max_date,
        range_complete=range_complete,
        coverage_by_code=coverage_by_code,
    )
    if raw_frames:
        raw_path = store.write_option_volatility_raw(raw_all, start_date, end_date, manifest.run_id)
        curated_path = store.write_option_volatility_curated(curated_all, start_date, end_date, manifest.run_id)
        manifest.raw_file = str(raw_path)
        manifest.curated_file = str(curated_path)
        manifest.row_count = len(curated_all)
        catalog.refresh_option_volatility_views()

    return _finish_dataset_run(settings, catalog, manifest, quality_results)


def collect_trading_calendar(
    settings: Settings,
    start_date: date,
    end_date: date,
    market: str | None = None,
    code: str | None = None,
) -> DatasetRunManifest:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if bool(market) == bool(code):
        raise ValueError("Provide exactly one of market or code")

    normalized_market = market.upper() if market else None
    scope_type = "MARKET" if normalized_market else "CODE"
    scope_value = normalized_market or code or ""
    captured_at = pd.Timestamp.now(tz="UTC")
    manifest = DatasetRunManifest(
        dataset="trading_calendar",
        requested_items=[scope_value],
        parameters={
            "scope_type": scope_type,
            "scope_value": scope_value,
            "market": normalized_market,
            "code": code,
            "requested_start_date": start_date.isoformat(),
            "requested_end_date": end_date.isoformat(),
            "returned_min_date": None,
            "returned_max_date": None,
            "returned_trade_date_count": 0,
            "api_request_count": 1,
            "successful_api_request_count": 0,
            "failed_api_request_count": 0,
            "source_schema_version": settings.source_schema_version,
        },
    )
    manifest.config_hash = _hash_config(manifest.parameters)

    raw = pd.DataFrame()
    curated = pd.DataFrame()
    try:
        with MoomooCalendarCollector(settings) as collector:
            raw = collector.fetch_trading_calendar(
                start_date=start_date,
                end_date=end_date,
                market=normalized_market,
                code=code,
            )
            if raw.empty:
                raise RuntimeError("No trading calendar rows were returned")
        raw = raw.copy()
        raw["scope_type"] = scope_type
        raw["scope_value"] = scope_value
        raw["requested_start_date"] = start_date
        raw["requested_end_date"] = end_date
        raw["captured_at"] = captured_at
        raw["ingestion_run_id"] = manifest.run_id
        if "trade_date_type" in raw.columns:
            raw["trade_date_type"] = raw["trade_date_type"].map(_sdk_name)
        curated = normalize_trading_calendar(
            raw,
            market=normalized_market,
            code=code,
            captured_at=captured_at,
            source=settings.source,
            source_schema_version=settings.source_schema_version,
            run_id=manifest.run_id,
        )
        if curated.empty:
            raise RuntimeError("No trading calendar rows remained after normalization")
        manifest.successful_items.append(scope_value)
        manifest.parameters["successful_api_request_count"] = 1
        returned_dates = sorted(pd.to_datetime(curated["trade_date"], errors="coerce").dropna().dt.date.unique())
        if returned_dates:
            manifest.parameters["returned_min_date"] = returned_dates[0].isoformat()
            manifest.parameters["returned_max_date"] = returned_dates[-1].isoformat()
            manifest.parameters["returned_trade_date_count"] = len(returned_dates)
    except Exception as exc:
        manifest.failed_items[scope_value] = str(exc)
        manifest.parameters["failed_api_request_count"] = 1

    store = ParquetStore(settings)
    catalog = Catalog(settings)
    quality_results = run_trading_calendar_quality_checks(curated, start_date, end_date)
    if not curated.empty:
        raw_path = store.write_trading_calendar_raw(
            raw,
            scope_type,
            scope_value,
            start_date,
            end_date,
            manifest.run_id,
        )
        curated_path = store.write_trading_calendar_curated(
            curated,
            scope_type,
            scope_value,
            start_date,
            end_date,
            manifest.run_id,
        )
        manifest.raw_file = str(raw_path)
        manifest.curated_file = str(curated_path)
        manifest.row_count = len(curated)
        catalog.refresh_trading_calendar_views()

    return _finish_dataset_run(settings, catalog, manifest, quality_results)


def _sdk_name(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    name = getattr(value, "name", None)
    text = str(name if name is not None else value).strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text or None


def _extract_option_volatility_dates(raw: pd.DataFrame) -> list[date]:
    if raw.empty:
        return []
    values = None
    for column in ["trade_date", "timestamp_str", "date"]:
        if column in raw.columns:
            values = raw[column]
            break
    if values is None and "timestamp" in raw.columns:
        parsed = pd.to_datetime(raw["timestamp"], unit="s", utc=True, errors="coerce")
    elif values is not None:
        parsed = pd.to_datetime(values, errors="coerce")
    else:
        return []
    return [item.date() for item in parsed.dropna()]


def _option_volatility_coverage_by_code(
    df: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> dict[str, dict]:
    if df.empty or "option_code" not in df.columns:
        return {}
    coverage: dict[str, dict] = {}
    for option_code, group in df.groupby("option_code", sort=True):
        returned_dates = _extract_option_volatility_dates(group)
        returned_min_date = min(returned_dates) if returned_dates else None
        returned_max_date = max(returned_dates) if returned_dates else None
        complete = _option_volatility_range_complete(
            returned_min_date,
            returned_max_date,
            start_date,
            end_date,
        )
        coverage[str(option_code)] = {
            "returned_min_date": returned_min_date.isoformat() if returned_min_date else None,
            "returned_max_date": returned_max_date.isoformat() if returned_max_date else None,
            "range_complete": complete,
            "row_count": int(len(group)),
        }
    return coverage


def _option_volatility_range_complete(
    returned_min_date: date | None,
    returned_max_date: date | None,
    start_date: date,
    end_date: date,
) -> bool:
    if returned_min_date is None or returned_max_date is None:
        return False
    expected_start = _next_weekday(start_date)
    expected_end = _previous_weekday(end_date)
    if expected_start is None or expected_end is None:
        return True
    return returned_min_date <= expected_start and returned_max_date >= expected_end


def _next_weekday(value: date) -> date | None:
    current = value
    for _ in range(7):
        if current.weekday() < 5:
            return current
        current = current + timedelta(days=1)
    return None


def _previous_weekday(value: date) -> date | None:
    current = value
    for _ in range(7):
        if current.weekday() < 5:
            return current
        current = current - timedelta(days=1)
    return None
