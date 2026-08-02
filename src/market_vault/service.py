from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .collectors import MoomooHistoryCollector
from .models import RunManifest, Settings
from .normalization import normalize_bars
from .quality import run_bar_quality_checks
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
