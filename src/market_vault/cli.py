from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .api import MarketVault
from .audit import FAILED, WARN, run_audit, run_inventory
from .backfill import collect_history_backfill
from .config import load_settings, load_universe
from .collectors.moomoo_calendar import SUPPORTED_TRADE_DATE_MARKETS
from .doctor import run_doctor
from .service import collect_history, collect_option_chain, collect_option_volatility, collect_trading_calendar
from .storage import Catalog


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD") from exc


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be non-negative")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be non-negative")
    return parsed


def _resolve_symbols(args) -> list[str]:
    symbols = list(args.symbols or [])
    if getattr(args, "groups", None):
        universe = load_universe(args.universe)
        for group in args.groups:
            symbols.extend(universe.get(group, []))
    return symbols


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-vault")
    parser.add_argument("--settings", default="config/settings.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-catalog", help="Create DuckDB metadata tables")
    init.set_defaults(command="init-catalog")

    doctor = sub.add_parser("doctor", help="Check local Python, moomoo SDK, and OpenD capabilities")
    doctor.set_defaults(command="doctor")

    collect = sub.add_parser("collect", help="Collect one closed US trading date")
    collect.add_argument("--date", required=True, type=_parse_date)
    collect.add_argument("--symbols", nargs="*")
    collect.add_argument("--universe", default="config/universe.yaml")
    collect.add_argument(
        "--groups",
        nargs="*",
        default=[],
        choices=["core_universe", "trade_universe", "event_universe", "option_universe"],
    )
    collect.add_argument("--interval", default="1m")
    collect.add_argument("--session", default=None)
    collect.add_argument("--adjustment", default=None)

    query = sub.add_parser("query", help="Query curated bars")
    query.add_argument("--code", required=True)
    query.add_argument("--trade-date")
    query.add_argument("--interval", default="1m")
    query.add_argument("--session")
    query.add_argument("--adjustment", default="NONE")
    query.add_argument("--limit", type=int, default=20)

    option_chain = sub.add_parser("option-chain", help="Collect static option contract metadata")
    option_chain.add_argument("--underlying", required=True)
    option_chain.add_argument("--start-date", required=True, type=_parse_date)
    option_chain.add_argument("--end-date", required=True, type=_parse_date)
    option_chain.add_argument("--option-type", default="ALL", choices=["ALL", "CALL", "PUT"])
    option_chain.add_argument("--option-cond-type", default="ALL", choices=["ALL", "ITM", "OTM"])

    option_volatility = sub.add_parser("option-volatility", help="Collect daily option volatility data")
    option_volatility.add_argument("--codes", nargs="+", required=True)
    option_volatility.add_argument("--start-date", required=True, type=_parse_date)
    option_volatility.add_argument("--end-date", required=True, type=_parse_date)

    calendar = sub.add_parser("calendar", help="Collect historical trading calendar days")
    calendar_scope = calendar.add_mutually_exclusive_group(required=True)
    calendar_scope.add_argument("--market", choices=SUPPORTED_TRADE_DATE_MARKETS)
    calendar_scope.add_argument("--code")
    calendar.add_argument("--start-date", required=True, type=_parse_date)
    calendar.add_argument("--end-date", required=True, type=_parse_date)

    calendar_query = sub.add_parser("calendar-query", help="Query local trading calendar data")
    calendar_query_scope = calendar_query.add_mutually_exclusive_group(required=True)
    calendar_query_scope.add_argument("--market", choices=SUPPORTED_TRADE_DATE_MARKETS)
    calendar_query_scope.add_argument("--code")
    calendar_query.add_argument("--start-date", type=_parse_date)
    calendar_query.add_argument("--end-date", type=_parse_date)
    calendar_query.add_argument("--limit", type=int, default=30)

    backfill = sub.add_parser("backfill", help="Plan and execute resumable historical backfill")
    backfill.add_argument("--start-date", type=_parse_date)
    backfill.add_argument("--end-date", required=True, type=_parse_date)
    backfill.add_argument("--symbols", nargs="*")
    backfill.add_argument("--universe", default="config/universe.yaml")
    backfill.add_argument(
        "--groups",
        nargs="*",
        default=[],
        choices=["core_universe", "trade_universe", "event_universe", "option_universe"],
    )
    backfill_scope = backfill.add_mutually_exclusive_group(required=True)
    backfill_scope.add_argument("--calendar-market", choices=SUPPORTED_TRADE_DATE_MARKETS)
    backfill_scope.add_argument("--calendar-code")
    backfill.add_argument("--interval", default="1m")
    backfill.add_argument("--session", default=None)
    backfill.add_argument("--adjustment", default=None)
    backfill.add_argument("--force", action="store_true")
    backfill.add_argument("--incremental", action="store_true")
    backfill.add_argument("--bootstrap-start-date", type=_parse_date)
    backfill.add_argument("--max-retries", type=_non_negative_int, default=2)
    backfill.add_argument("--retry-backoff-seconds", type=_non_negative_float, default=2.0)

    inventory = sub.add_parser("inventory", help="Summarize local market-bar storage, snapshots, and coverage")
    inventory.add_argument("--symbols", nargs="*")
    inventory.add_argument("--universe", default="config/universe.yaml")
    inventory.add_argument(
        "--groups",
        nargs="*",
        default=[],
        choices=["core_universe", "trade_universe", "event_universe", "option_universe"],
    )
    inventory.add_argument("--start-date", type=_parse_date)
    inventory.add_argument("--end-date", type=_parse_date)
    inventory.add_argument("--interval")
    inventory.add_argument("--session")
    inventory.add_argument("--adjustment")
    inventory.add_argument("--source-schema-version")
    inventory.add_argument("--include-files", action="store_true")

    audit = sub.add_parser("audit", help="Audit trading-day coverage against the local trading calendar")
    audit_scope = audit.add_mutually_exclusive_group(required=True)
    audit_scope.add_argument("--calendar-market", choices=SUPPORTED_TRADE_DATE_MARKETS)
    audit_scope.add_argument("--calendar-code")
    audit.add_argument("--start-date", required=True, type=_parse_date)
    audit.add_argument("--end-date", required=True, type=_parse_date)
    audit.add_argument("--symbols", nargs="*")
    audit.add_argument("--universe", default="config/universe.yaml")
    audit.add_argument(
        "--groups",
        nargs="*",
        default=[],
        choices=["core_universe", "trade_universe", "event_universe", "option_universe"],
    )
    audit.add_argument("--interval", default="1m")
    audit.add_argument("--session", default=None)
    audit.add_argument("--adjustment", default=None)
    audit.add_argument("--source-schema-version")
    audit.add_argument("--include-complete-dates", action="store_true")
    audit.add_argument("--fail-on-gaps", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.settings)

    if args.command == "init-catalog":
        Catalog(settings).initialize()
        print(f"Catalog initialized: {settings.catalog_path}")
        return

    if args.command == "doctor":
        print(json.dumps(run_doctor(settings), ensure_ascii=False, indent=2))
        return

    if args.command == "collect":
        symbols = sorted(set(_resolve_symbols(args)))
        manifest = collect_history(
            settings=settings,
            trade_date=args.date,
            symbols=symbols,
            interval=args.interval,
            session=(args.session or settings.default_session),
            adjustment=(args.adjustment or settings.default_adjustment),
        )
        print(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "query":
        vault = MarketVault(settings)
        frame = vault.load_bars(
            code=args.code,
            trade_date=args.trade_date,
            interval=args.interval,
            session=args.session,
            adjustment=args.adjustment,
        )
        print(frame.head(args.limit).to_string(index=False))
        return

    if args.command == "option-chain":
        manifest = collect_option_chain(
            settings=settings,
            underlying=args.underlying,
            start_date=args.start_date,
            end_date=args.end_date,
            option_type=args.option_type,
            option_cond_type=args.option_cond_type,
        )
        print(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "option-volatility":
        manifest = collect_option_volatility(
            settings=settings,
            codes=args.codes,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "calendar":
        manifest = collect_trading_calendar(
            settings=settings,
            market=args.market,
            code=args.code,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "calendar-query":
        vault = MarketVault(settings)
        frame = vault.load_trading_calendar(
            market=args.market,
            code=args.code,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(frame.head(args.limit).to_string(index=False))
        return

    if args.command == "backfill":
        if not args.incremental and args.start_date is None:
            build_parser().error("--start-date is required unless --incremental is used")
        if args.incremental and args.start_date is not None:
            build_parser().error("--start-date cannot be used with --incremental")
        manifest = collect_history_backfill(
            settings=settings,
            symbols=_resolve_symbols(args),
            start_date=args.start_date,
            end_date=args.end_date,
            calendar_market=args.calendar_market,
            calendar_code=args.calendar_code,
            interval=args.interval,
            session=(args.session or settings.default_session),
            adjustment=(args.adjustment or settings.default_adjustment),
            force=args.force,
            incremental=args.incremental,
            bootstrap_start_date=args.bootstrap_start_date,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
        print(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "inventory":
        report = run_inventory(
            settings,
            symbols=_resolve_symbols(args) or None,
            start_date=args.start_date,
            end_date=args.end_date,
            interval=args.interval,
            requested_session=args.session,
            adjustment=args.adjustment,
            source_schema_version=args.source_schema_version,
            include_files=args.include_files,
        )
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "audit":
        symbols = _resolve_symbols(args)
        if not symbols:
            build_parser().error("At least one symbol is required via --symbols, --universe, or --groups")
        try:
            report = run_audit(
                settings,
                symbols=symbols,
                start_date=args.start_date,
                end_date=args.end_date,
                calendar_market=args.calendar_market,
                calendar_code=args.calendar_code,
                interval=args.interval,
                requested_session=args.session,
                adjustment=args.adjustment,
                source_schema_version=args.source_schema_version,
                include_complete_dates=args.include_complete_dates,
            )
        except ValueError as exc:
            # Invalid audit parameters produce a structured FAILED report
            # instead of a Python traceback for CLI users. Argparse-level
            # errors keep the standard exit code 2.
            print(
                json.dumps(
                    {
                        "report_type": "MARKET_BARS_COVERAGE_AUDIT",
                        "status": "FAILED",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        if report.status == FAILED:
            return 1
        if report.status == WARN and args.fail_on_gaps:
            return 2
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
