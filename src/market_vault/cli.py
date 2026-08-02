from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .api import MarketVault
from .config import load_settings, load_universe
from .doctor import run_doctor
from .collectors.moomoo_calendar import SUPPORTED_TRADE_DATE_MARKETS
from .service import collect_history, collect_option_chain, collect_option_volatility, collect_trading_calendar
from .storage import Catalog


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD") from exc


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

    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings(args.settings)

    if args.command == "init-catalog":
        Catalog(settings).initialize()
        print(f"Catalog initialized: {settings.catalog_path}")
        return

    if args.command == "doctor":
        print(json.dumps(run_doctor(settings), ensure_ascii=False, indent=2))
        return

    if args.command == "collect":
        symbols = list(args.symbols or [])
        if args.groups:
            universe = load_universe(args.universe)
            for group in args.groups:
                symbols.extend(universe.get(group, []))
        symbols = sorted(set(symbols))
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


if __name__ == "__main__":
    main()
