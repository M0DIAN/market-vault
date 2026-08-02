from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import pandas as pd

from .collectors import MoomooHistoryCollector, MoomooOptionCollector
from .collectors.moomoo_options import select_option_volatility_period
from .models import DatasetRunManifest, RunManifest, Settings
from .normalization import normalize_bars, normalize_option_contracts, normalize_option_volatility
from .quality import (
    run_bar_quality_checks,
    run_option_contract_quality_checks,
    run_option_volatility_quality_checks,
)
from .storage import Catalog, ParquetStore


def _hash_config(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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

    manifest = DatasetRunManifest(
        dataset="option_contracts",
        requested_items=[underlying],
        parameters={
            "underlying": underlying,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "option_type": option_type.upper(),
            "option_cond_type": option_cond_type.upper(),
            "source_schema_version": settings.source_schema_version,
        },
    )
    manifest.config_hash = _hash_config(manifest.parameters)

    raw = pd.DataFrame()
    curated = pd.DataFrame()
    captured_at = pd.Timestamp.now(tz="UTC")
    try:
        with MoomooOptionCollector(settings) as collector:
            raw = collector.fetch_option_chain(
                underlying=underlying,
                start_date=start_date,
                end_date=end_date,
                option_type=option_type,
                option_cond_type=option_cond_type,
            )
        if raw.empty:
            raise RuntimeError("No option contracts returned")
        raw = raw.copy()
        raw["underlying_code"] = underlying
        raw["capture_date"] = captured_at.date()
        raw["captured_at"] = captured_at
        raw["ingestion_run_id"] = manifest.run_id
        curated = normalize_option_contracts(
            frame=raw,
            underlying_code=underlying,
            captured_at=captured_at,
            source=settings.source,
            source_schema_version=settings.source_schema_version,
            run_id=manifest.run_id,
        )
        manifest.successful_items.append(underlying)
    except Exception as exc:
        manifest.failed_items[underlying] = str(exc)

    store = ParquetStore(settings)
    catalog = Catalog(settings)
    quality_results = run_option_contract_quality_checks(curated)
    if not raw.empty:
        raw_path = store.write_option_chain_raw(raw, underlying, captured_at.date(), manifest.run_id)
        curated_path = store.write_option_contracts_curated(curated, underlying, captured_at.date(), manifest.run_id)
        manifest.raw_file = str(raw_path)
        manifest.curated_file = str(curated_path)
        manifest.row_count = len(curated)
        catalog.refresh_option_contract_views()

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
            "hv_time_period": hv_time_period,
            "as_of_date": effective_as_of_date.isoformat(),
            "requested_start_date": start_date.isoformat(),
            "requested_end_date": end_date.isoformat(),
            "returned_min_date": None,
            "returned_max_date": None,
            "range_complete": False,
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
                    raw["ingestion_run_id"] = manifest.run_id
                    raw_frames.append(raw)
                    curated = normalize_option_volatility(
                        frame=raw,
                        option_code=code,
                        start_date=start_date,
                        end_date=end_date,
                        source=settings.source,
                        run_id=manifest.run_id,
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
    returned_dates = _extract_option_volatility_dates(raw_all)
    returned_min_date = min(returned_dates) if returned_dates else None
    returned_max_date = max(returned_dates) if returned_dates else None
    range_complete = returned_min_date is not None and returned_min_date <= start_date
    manifest.parameters["returned_min_date"] = returned_min_date.isoformat() if returned_min_date else None
    manifest.parameters["returned_max_date"] = returned_max_date.isoformat() if returned_max_date else None
    manifest.parameters["range_complete"] = range_complete
    quality_results = run_option_volatility_quality_checks(
        curated_all,
        start_date,
        end_date,
        returned_min_date=returned_min_date,
        range_complete=range_complete,
    )
    if raw_frames:
        raw_path = store.write_option_volatility_raw(raw_all, start_date, end_date, manifest.run_id)
        curated_path = store.write_option_volatility_curated(curated_all, start_date, end_date, manifest.run_id)
        manifest.raw_file = str(raw_path)
        manifest.curated_file = str(curated_path)
        manifest.row_count = len(curated_all)
        catalog.refresh_option_volatility_views()

    return _finish_dataset_run(settings, catalog, manifest, quality_results)


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
