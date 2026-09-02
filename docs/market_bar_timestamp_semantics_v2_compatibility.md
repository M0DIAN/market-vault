# Market-Bar Timestamp Semantics V2 Compatibility

## Status

This approved design contract is implemented for runtime timestamp conversion
and current-view filtering. The checked-in and production configuration remain
on `10.9`; the separately authorized configuration cutover has not occurred.
This document authorizes no production-data mutation.

The compatibility cohorts are:

```text
LEGACY_SOURCE_SCHEMA_VERSION = 10.9
NEW_SOURCE_SCHEMA_VERSION = 10.9-mv-ts2
```

`mv-ts2` means MarketVault Timestamp Semantics V2. It is a MarketVault archive
compatibility discriminator for normalized Curated semantics; it does not
claim that OpenD 10.10.7008 introduced a physical schema named `10.10`.

## Problem And Evidence

Moomoo's official field description calls `time_key` the candlestick time in
the market timezone but does not define whether that value is the left or
right edge of the interval. Live re-verification against OpenD 10.10.7008 for
`US.SPY`, 2026-08-20, and `NONE` established these shapes:

| Requested session | Interval | Rows | First Raw label | Last Raw label | Observed convention |
|---|---:|---:|---:|---:|---|
| RTH | 1m | 390 | 09:31 | 16:00 | interval end |
| RTH | 5m | 78 | 09:35 | 16:00 | interval end |
| RTH | 15m | 26 | 09:45 | 16:00 | interval end |
| RTH | 30m | 13 | 10:00 | 16:00 | interval end |
| RTH | 60m | 7 | 10:30 | 16:00 | interval end; final interval is truncated to 30m |
| ALL | 1m | 1440 | 00:00 | 23:59 | interval start |
| ALL | 5m | 288 | 00:00 | 23:55 | interval start |
| ALL | 15m | 96 | 00:00 | 23:45 | interval start |
| ALL | 30m | 48 | 00:00 | 23:30 | interval start |
| ALL | 60m | 25 | 00:00 | 23:00 | interval start with 30m session-boundary splits |

The existing `10.9` normalizer adopts Raw `time_key` directly as interval
start. For the verified 1m RTH response this creates 389 `REGULAR` rows and
one false `AFTER_HOURS` row at 16:00. A corrected snapshot would instead have
390 `REGULAR` interval starts from 09:30 through 15:59.

Old and corrected rows cannot safely share one schema cohort. An isolated
coexistence proof using the current `market_bars` view produced 391 RTH rows:
the corrected 09:30 row plus the legacy 16:00 row both survived. The new
cohort and current-view isolation below are therefore mandatory parts of one
cutover.

## Cohort Contracts

### Legacy `10.9`

Existing `10.9` Raw and Curated snapshots are immutable historical evidence.
The cutover must not rewrite their timestamps or bytes, modify their Catalog
rows, manifests, or quality results, automatically migrate them, quarantine
them, or delete them. They remain discoverable through archive-oriented
Inventory, Catalog, and explicit Safe Purge schema scope.

After the cutover, `10.9` is not current/default query data. Hiding it from the
configured current view is not deletion and does not remove lifecycle
authority.

### New `10.9-mv-ts2`

Every new market-bar collection made by a runtime after the semantic cutover
must use `source_schema_version = 10.9-mv-ts2`, regardless of requested
session. This includes ALL collections whose numeric timestamps need no
shift: cohort identity records the complete normalization contract, not the
presence of a per-row adjustment.

Raw remains provider-native. In particular, a verified 1m RTH Raw file keeps
`time_key` values 09:31 through 16:00. Registry, run, manifest, and Curated
evidence must identify the new schema cohort. Curated must represent canonical
interval starts in `time_market` and `time_utc`, and classify `session` from
that canonical start.

The future implementation must be provider-, interval-, and session-aware.
Blind subtraction for every Moomoo row is forbidden. It must implement only
geometries supported by live evidence and fail honestly for unresolved or
ambiguous boundaries.

## Current And Archive Views

`market_bars_snapshots` remains the physical archive view. It may contain both
`10.9` and `10.9-mv-ts2` Curated files and must not rewrite either cohort.

`market_bars` is the current/default logical consumer view. Its future SQL
must filter rows before applying existing row-version selection:

```sql
SELECT * EXCLUDE (_rn)
FROM (
    SELECT *,
           row_number() OVER (
               PARTITION BY code, interval, adjustment, time_utc
               ORDER BY ingested_at DESC
           ) AS _rn
    FROM market_bars_snapshots
    WHERE source = <exact settings.source>
      AND source_schema_version = <exact settings.source_schema_version>
)
WHERE _rn = 1
```

The implementation must safely quote exact, nonblank configuration values;
wildcards and substring matching are forbidden. Because `source` and
`source_schema_version` are constants after the filter, adding them to the
`row_number` partition would be redundant. This transition preserves the
existing partition key instead of changing unrelated deduplication semantics.

Inspection found that the existing partition does not include
`requested_session`. RTH and ALL rows at the same `time_utc` can therefore
collide inside one schema cohort. That is a separate query/deduplication issue
and is not authorized by this design. Its eventual correction needs its own
review and regressions; it must not be bundled into Timestamp Semantics V2.

With `settings.source_schema_version = 10.9-mv-ts2`, legacy `10.9` rows must
never survive into `market_bars`. The coexistence regression must prove 390
current RTH rows and no legacy 16:00 row, while the archive view still exposes
both physical snapshots.

## Consumer Rules

### Query API And Desktop

Use the default-current pattern. `MarketVault.load_bars`,
`MarketVault.load_bars_page`, and `ConsoleBackend.query_bars` continue to read
`market_bars` without adding a required argument. An omitted schema never
means all cohorts; it means the configured cohort through the view.

An explicit legacy schema selector for Market Data is not part of this
transition. Operators retain archive visibility through Inventory, Catalog,
and Safe Purge.

### Backfill And Incremental

Existing completion APIs already require an exact `source_schema_version`,
and Backfill supplies `settings.source_schema_version`. This remains the only
completion authority after cutover.

A COMPLETE `10.9` date is not complete for `10.9-mv-ts2`. Ordinary bounded
Backfill therefore treats it as pending and may collect a new immutable pair
without removing the old pair.

Incremental planning also queries latest completed dates using the configured
schema. When only `10.9` history exists, no latest date exists in the new
cohort, so the existing fail-closed bootstrap rule applies:
`bootstrap_start_date` is required. The planner must not use a legacy latest
date as the new cohort's starting authority.

### Coverage And Intraday Audit

Coverage and Intraday Audit already normalize an omitted schema to
`settings.source_schema_version` and pass that exact value to Catalog
completion and latest-snapshot selection. They must retain that behavior. A
quality PASS from `10.9` cannot certify `10.9-mv-ts2`, and no quality outcome
may be inherited across runs or cohorts.

### Dashboard

Dashboard is a current-data surface. Its Inventory request must be scoped to
`settings.source_schema_version` so Symbols, Snapshots, completed/incomplete
dates, latest trade date, and latest row count all describe one configured
cohort. The Dashboard must not combine archive-wide snapshot counts with a
current-cohort query count.

### Inventory

Inventory remains archive-oriented. The existing implementation reads
`market_bars_snapshots`, groups items by `source_schema_version`, includes the
schema in each item, and accepts an optional exact schema filter. That is
sufficient additive visibility for both cohorts; no new Inventory schema or
UI selector is authorized here.

When Inventory is unfiltered, archive counts may include both cohorts and
items must remain separated by schema. Its `latest_query_row_count` comes from
the configured `market_bars` view and must be described as current-cohort,
not as the row count of all archive items.

### Canonical And Dataset

Canonical materialization already selects COMPLETE snapshots using the
explicit `request_key.source_schema_version`. It must continue to select one
exact cohort and must never fall back from `10.9-mv-ts2` to `10.9`.

Dataset builds and readers remain pinned to their explicit source snapshot,
request, manifest, and source-schema evidence. Existing derived artifacts are
not reinterpreted or rebuilt by this cutover. No implicit "current schema"
lookup may merge cohorts inside a verified Dataset.

## Lifecycle Isolation

`source_schema_version` remains part of the Safe Purge and
`SUPERSEDED_ONLY` exact logical key. A `10.9-mv-ts2` snapshot never
automatically supersedes a `10.9` snapshot, or vice versa.

`SUPERSEDED_ONLY` scoped to `10.9-mv-ts2` ranks only new-cohort versions.
Scoped to `10.9`, it ranks only legacy-cohort versions. Removing legacy data
requires a separately reviewed explicit lifecycle action such as existing
`EXACT_SCOPE`; the timestamp cutover itself performs no cleanup.

The independent defect in which an EXACT_SCOPE review follows a successful
SUPERSEDED_ONLY quarantine remains out of scope. This design changes no
destructive executor, confirmation, plan evidence, or quarantine behavior.

## Configuration Cutover

Changing production from `10.9` to `10.9-mv-ts2` is an explicit deployment
operation, not an EXE-copy side effect. A future authorized deployment must:

1. stop MarketVault normally and prove no collection is active;
2. record the exact production settings path and before SHA-256;
3. parse and preserve the complete settings document;
4. change exactly `collector.source_schema_version` from `10.9` to
   `10.9-mv-ts2`;
5. prove every unrelated parsed setting is equal before and after;
6. record the after SHA-256 and exact semantic diff;
7. preserve all existing Raw, Curated, Catalog, manifest, report, and
   quarantine bytes;
8. launch and verify that the configured cohort is `10.9-mv-ts2` before any
   collection.

Build or ONEDIR promotion must not overwrite production settings. Rollback of
the executable alone must not silently switch the configured cohort. Any
rollback/cutover procedure must keep executable capability and schema setting
compatible and requires separate operational authorization.

Application version remains `0.7.0`; archive schema and package version are
independent.

## Deterministic Design Cases

### Case A: only old cohort exists

With runtime schema `10.9-mv-ts2`, `market_bars_snapshots` and Inventory expose
the `10.9` file, but `market_bars` contains no current row. Completion in the
new cohort is empty, bounded Backfill marks the date pending, and Incremental
requires its normal bootstrap date.

### Case B: both cohorts coexist

The archive view and Inventory expose separate `10.9` and `10.9-mv-ts2`
items. The default view reads only the new cohort and returns exactly the 390
corrected 1m RTH rows from 09:30 through 15:59. The legacy 16:00 row is not
visible in the default view. Legacy bytes and evidence remain unchanged.

### Case C: new cohort is recollected

Two COMPLETE `10.9-mv-ts2` snapshots use the existing deterministic
latest-version and row-deduplication semantics within that cohort. No `10.9`
row participates.

### Case D: new-cohort superseded cleanup

`SUPERSEDED_ONLY` with schema `10.9-mv-ts2` groups, retains, and targets only
new-cohort snapshots. A matching `10.9` snapshot is a different logical key.

### Case E: legacy-cohort superseded cleanup

`SUPERSEDED_ONLY` with schema `10.9` groups, retains, and targets only legacy
snapshots. A matching `10.9-mv-ts2` snapshot cannot supersede one.

### Case F: Inventory visibility

Unfiltered Inventory returns separate combination rows for both schema
values. Exact schema filters return only their requested cohort. Archive
physical counts remain honest and current-query counts remain identified as
configured-cohort counts.

### Case G: immutable legacy evidence

After new-schema collection, query, coverage, audit, and canonical selection,
the original `10.9` Raw and Curated hashes, Catalog rows, manifests, and
quality results are unchanged and still discoverable through archive
surfaces.

## Implementation Acceptance

The implementation phase must prove at least:

- provider-native Raw timestamps are byte/semantically preserved;
- the verified RTH and ALL geometries produce canonical interval starts;
- ambiguous or unsupported geometries fail rather than guess;
- every new market-bar run and pair records `10.9-mv-ts2` after cutover;
- archive view coexistence and current-view cohort isolation;
- the 391-row regression returns exactly 390 current rows;
- bounded and Incremental Backfill do not reuse legacy completion;
- Coverage, Intraday Audit, Dashboard, and query surfaces use one cohort;
- Inventory exposes both cohorts separately;
- Canonical and Dataset evidence never mixes cohorts;
- Safe Purge and `SUPERSEDED_ONLY` remain exact-schema;
- legacy files and historical evidence remain byte-identical;
- no automatic migration, rewrite, quarantine, or deletion occurs.

Production configuration cutover, new-cohort recollection, and any later
legacy cleanup are separately authorized operational phases.
