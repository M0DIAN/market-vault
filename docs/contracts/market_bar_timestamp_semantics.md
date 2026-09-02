# Market-Bar Timestamp Semantics Contract

Status: the canonical interval-start model is active. The legacy `10.9`
OpenD-label interpretation is contradicted by later live evidence; the
`10.9-mv-ts2` compatibility transition is approved by design but is not yet
implemented. See
[`market_bar_timestamp_semantics_v2_compatibility.md`](../market_bar_timestamp_semantics_v2_compatibility.md).

This contract answers the timestamp questions that
[ADR 0001](../adr/0001-canonical-ml-dataset-boundary.md) flagged before any
canonical builder implementation may begin. Every rule below is enforced by
deterministic offline tests in `tests/test_timestamp_semantics_v03.py`.

## 1. Time model

| Instant | Definition | Clock |
|---|---|---|
| `event_time` | the instant a bar describes: the bar's interval start in market time, expressed in UTC | market (America/New_York) -> UTC |
| `market_available_at` | earliest instant the complete OHLCV bar could be known: `event_time + interval` | UTC |
| `archive_available_at` | instant the snapshot became available inside MarketVault: the run's `finished_at` (`run_finished_at`) | UTC |

`event_time` is derived from `time_market` (the normalized market timestamp)
converted to UTC. `market_available_at` is computed by
`market_vault.normalization.bar_available_at(time_market, interval_seconds)`.
`archive_available_at` is the run's `finished_at` recorded in
`ingestion_runs`.

## 2. What the OpenD historical K-line `time_key` represents

**Official documentation wording:** the official Moomoo field documentation
defines the K-line time as the candlestick time in the market timezone; it
does **not** explicitly distinguish interval start from interval end. This
repository does not contain the official documentation itself.

The legacy `10.9` runtime adopted `time_key` directly as interval start. That
interpretation was based on synthetic and stored-data shape evidence, not on
an explicit provider definition, and is retained only as the immutable
historical meaning of existing `10.9` Curated files.

Mandatory live re-verification was completed against OpenD 10.10.7008 using
`US.SPY`, 2026-08-20, and `NONE`. It established session-dependent behavior:

- RTH 1m, 5m, 15m, and 30m values are interval-end labels;
- RTH 60m values are interval-end labels with a truncated final 30m segment;
- ALL 1m, 5m, 15m, and 30m values are interval-start labels;
- ALL 60m values are interval-start labels with observed session-boundary
  splits.

For example, OpenD returned 390 RTH 1m Raw labels from 09:31 through 16:00.
The canonical interval-start sequence is 09:30 through 15:59. Direct adoption
incorrectly labels the final row `AFTER_HOURS` and omits canonical 09:30.

Therefore no global "parse and adopt" or "subtract the interval" rule is
valid. `parse_market_time_key` continues to mean only "parse this value as a
market-time instant." A future source-specific normalizer must translate
verified Moomoo historical K-line conventions before deriving canonical
`time_market`, `time_utc`, and `session`, and must reject unsupported geometry
rather than guess.

Raw `time_key` remains provider-native. Corrected Curated output belongs to a
new archive compatibility cohort, `source_schema_version = 10.9-mv-ts2`.
Existing `10.9` files are never rewritten. The approved cohort and default
view isolation rules are frozen in the linked compatibility design; this
design-only change does not claim the runtime already implements them.

**Re-verification requirement remains mandatory:** provider version changes,
new intervals, new sessions, early-close behavior, or any timestamp geometry
outside the recorded evidence require new live evidence before support. Tests
must not silently generalize the conversion.

## 3. `market_available_at` derivation

Rule: `market_available_at = event_time + interval` (UTC), computed by the
pure function `bar_available_at`.

Precision of the rule:

- `event_time + interval` is **exact** for bars known to span the complete
  nominal interval: under interval-start semantics, such a bar's OHLCV values
  are not complete before the interval ends, so the earliest instant the
  complete bar could be known is the interval end.
- For bars that may be truncated at a session boundary or an early close,
  `event_time + interval` is a **conservative leakage-safe not-before bound**,
  not an exact earliest instant: the exact bar-end time would require
  authoritative per-date session schedules, which V0.3 does not have.
- It is therefore **not** claimed to be the universally exact earliest
  instant for every supported interval and every bar; exactness holds only
  when the bar is known to span its full nominal interval.

Collection latency never affects `market_available_at`; it is captured by
`archive_available_at`.

Example (EDT): `time_market = 2026-07-01 09:30:00-04:00`,
`interval = 1m` -> `event_time = 2026-07-01 13:30:00+00:00`,
`market_available_at = 2026-07-01 13:31:00+00:00` (exact for a full 1m bar;
a conservative not-before bound otherwise).

## 4. UTC / America/New_York conversion behavior

`parse_market_time_key` (and therefore `normalize_bars`) behaves as follows:

- Naive `time_key` values are localized to America/New_York with
  `ambiguous="raise"` and `nonexistent="raise"`:
  - **DST spring-forward nonexistent times raise** (e.g. 2026-03-08 02:30
    does not exist in America/New_York);
  - **DST fall-back ambiguous times raise** (e.g. 2026-11-01 01:30 occurs
    twice; zoneinfo resolves neither side silently).
- Already timezone-aware values are converted to America/New_York.
- Normal dates convert with the correct offset (-05:00 EST, -04:00 EDT), and
  the conversion to UTC is exact (`time_utc = time_market converted to UTC`).

## 5. Per-row `ingested_at` semantics

- Stamped once per `normalize_bars` call as `pd.Timestamp.now(tz="UTC")`
  (see `bars.py`).
- **Every row in one normalized batch has the same value.**
- Across batches within one run (one `normalize_bars` call per symbol in
  `collect_history`), values can differ by microseconds.
- Precision: microseconds (`datetime64[us]`); timezone: UTC.
- It records when MarketVault normalized the data, not when the market event
  occurred.

## 6. `run_finished_at` semantics

- Created as `RunManifest.finished_at = datetime.now(timezone.utc)` at the
  end of every `collect_history` call, before the run manifest is recorded
  (see `service.py`).
- Present for every recorded run, including SUCCESS, PARTIAL, and FAILED.
- Precision: microseconds; timezone: UTC; stored in `ingestion_runs`.
- Relationship to `ingested_at`: `finished_at` is stamped after all
  normalization, so within one run `run_finished_at >=` every `ingested_at`
  of that run (the tests assert the weak inequality to avoid timing races).
- `archive_available_at` is defined as `run_finished_at`.

## 7. Parquet / DuckDB timestamp round-trip

- **pandas -> Parquet (PyArrow)**: tz-aware datetimes are written as
  `timestamp[us, tz="America/New_York"]` (or UTC); `pd.read_parquet`
  preserves the original timezone.
- **DuckDB `read_parquet`**: timestamps are stored internally as UTC
  instants; the wall-clock value DuckDB returns depends on the **session
  timezone**. With the session timezone set to UTC the wall clock equals the
  UTC instant; with a different session timezone (e.g. America/New_York or a
  machine-local zone) the same instant is surfaced with that zone's offset.
- Consequence for consumers: never compare DuckDB-returned wall clocks
  without converting both sides to a common instant; convert explicitly to
  UTC (this is what the intraday audit already does).

## 8. Unresolved evidence gaps

1. The official Moomoo documentation still does not explicitly define
   interval start versus interval end. Support is limited to the exact live
   geometries recorded in section 2 and the compatibility design.
2. Early-close RTH behavior and other provider/session/interval combinations
   remain unresolved. A future implementation must fail honestly outside its
   verified conversion rules.
3. The approved `10.9-mv-ts2` cohort, current-view filter, and production
   settings cutover are not implemented by this design-only contract update.
4. The current `market_bars` row-version partition omits
   `requested_session`; that separate possible RTH/ALL collision is recorded
   but not authorized for correction by this design.
5. `ingested_at` cross-batch differences within a run are allowed but not
   asserted to be distinct; the contract only pins same-batch equality.
6. Exact bar-end times at unverified session boundaries and early closes are
   not known;
   `market_available_at = event_time + interval` is exact only for bars known
   to span their full nominal interval and is otherwise a conservative
   not-before bound (see section 3).
