# Intraday Boundary Schedule Evidence

## Decision

MarketVault cannot currently obtain an authoritative historical, per-date
session schedule for Moomoo `Session.ALL`. Boundary verification therefore
remains **not evaluated**. MarketVault must not infer leading or trailing
coverage from observed bars, `trade_date_type`, current market state, or
generic published trading hours.

This is a research and design decision only. It does not change runtime
behavior, schemas, storage, dependencies, CLI contracts, CI, or release state.

## Evidence Reviewed

The official Moomoo interfaces available through the project's unified SDK
loader were reviewed against SDK module `moomoo` 10.10.7008:

- [`request_trading_days`](https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-trading-days.html)
  returns a date and coarse `trade_date_type` (`WHOLE`, `MORNING`, or
  `AFTERNOON`). It does not return session open/close instants, and the
  documentation says temporary market closures are not excluded.
- [`request_history_kline`](https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-history-kline.html)
  accepts `Session.ALL` for US 24-hour historical bars. Its response contains
  observed candlesticks, not an independent schedule. Those bars cannot be
  used to prove their own completeness.
- [`get_market_state`](https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-market-state.html)
  reports current state for requested securities. It does not provide a
  historical per-date schedule.
- The official [quote Q&A](https://openapi.moomoo.com/moomoo-api-doc/en/qa/quote.html)
  describes generic US session windows. Static windows do not establish
  provider behavior for a particular date.

SDK source inspection found no additional historical schedule method on
`OpenQuoteContext`. The available evidence cannot independently cover all of:

- `OVERNIGHT`, `PRE_MARKET`, `REGULAR`, and `AFTER_HOURS` boundaries;
- Friday/weekend transitions and holidays;
- early-close or other special-session dates; and
- daylight-saving transitions with exact timestamp semantics.

`TradeDateType` is intentionally insufficient: it classifies a trading date
but does not define exact intraday boundaries for every `Session.ALL` segment.

## Existing Fail-Honest Contract

`intraday-audit` remains local-only and preserves its current checks for exact
request identity, timestamp validity, UTC/market-time consistency, market
calendar dates, session labels, duplicates, minute alignment, interval grids,
and gaps inside observed segments. Its boundary result remains
`evaluated=false` with the reason that no authoritative per-date schedule is
available. Missing first/last bars and wholly absent sessions are not silently
treated as verified boundary coverage.

## Smallest Safe Future Design

Implementation should wait for an authoritative source whose contract exposes
historical, per-date boundaries for the actual provider sessions requested by
`Session.ALL`. Once that source is identified and independently reviewed:

1. Collect it explicitly into an immutable local session-schedule artifact,
   including source/version provenance, scope, effective date, timezone, exact
   boundary instants, session label, capture time, and special-session status.
2. Preserve schedule snapshots without deriving them from market bars or
   silently substituting generic hours.
3. Make `intraday-audit` read only the local artifact; never add a live-network
   dependency to the audit command.
4. Report each boundary as verified `PASS`, missing according to an explicitly
   reviewed WARN/FAIL contract, or `NOT_EVALUATED` when the schedule is absent,
   unsupported, stale, ambiguous, or does not cover the requested scope/date.
5. Add normal-day, Friday/weekend, holiday, early-close/special-session, DST,
   missing-first, missing-last, and unavailable-schedule regression fixtures
   sourced from the authoritative schedule contract.

That future work requires explicit review visibility because it would add a
new data/storage contract and extend the audit report contract. No schedule
schema or compatibility behavior is introduced by this decision record.
