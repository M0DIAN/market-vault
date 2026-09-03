# MarketVault Console v0.1 Contract

## 1. Scope

MarketVault Console v0.1 is a Windows-oriented desktop operator surface for
the existing historical database. It is launched with:

```powershell
python -m market_vault.console --settings config/settings.yaml
```

The implementation uses Python stdlib Tkinter/ttk. Tkinter is loaded lazily;
importing `market_vault.console`, its backend, or its models remains headless
safe. A usable Tcl/Tk runtime is required, as provided by the standard
Python.org Windows installer. Missing Tcl/Tk fails with a concise startup
error rather than an exception traceback. No third-party GUI dependency is
part of this contract.

## 2. Trust Boundary

Widgets never issue SQL, open DuckDB directly, edit Parquet, or manipulate
runtime data paths. All business reads and operations go through
`ConsoleBackend` and the public `MarketVault` API/service abstraction.

The Console provides no arbitrary SQL editor, Parquet editor, file browser
delete action, permanent-delete action, or repair action. Its Storage / Purge
workspace can only call the reviewed two-phase Safe Purge API. Existing
immutable Canonical, Dataset, and Catalog artifacts are retained without
cascade.

## 3. Operation Classification

The default mode is local-only. These actions never connect to OpenD:

- Dashboard refresh and run history;
- paginated Data Explorer and trading-calendar queries;
- Inventory, Coverage Audit, and Intraday Audit;
- backfill planning; and
- export of the currently loaded page.

Only these v0.1 operator actions may connect to OpenD:

- **Fetch from OpenD** in Trading Calendar; and
- **Execute via OpenD** in Backfill.

Both are explicit button actions and require a confirmation that names the
configured OpenD host and port. Opening the Console, switching tabs,
refreshing local views, planning, querying, auditing, or exporting never
implicitly invokes either action.

## 4. Bounded Data Contract

`MarketVault.load_bars_page`, `load_trading_calendar_page`, and
`load_run_history_page` use parameterized filters plus `LIMIT`/`OFFSET`.
Page size must be between 1 and 1000. Each response includes exact total row
count and page navigation facts. The widget layer receives immutable
`TablePage` values, not an unbounded DataFrame.

Market-bar queries distinguish the collection request identity
`requested_session` (`RTH`/`ALL`/`ETH`) from the normalized per-row
`bar_session` (`OVERNIGHT`/`PRE_MARKET`/`REGULAR`/`AFTER_HOURS`). If the
request session is omitted and multiple request cohorts match, the API fails
closed before counting or selecting a page. The QML Market Data page already
passes the two filters separately.

Console export is intentionally **current-page only**, supports CSV and JSON,
and rejects more than 1000 loaded rows. It does not export Parquet or execute
an unbounded database scan. Backfill plan display is capped at 1000 items;
Inventory and audit detail displays are likewise capped at 1000 rows. Their
full summary and total counts remain visible.

## 5. Execution and Errors

The GUI runs one operation at a time through a serial background task runner.
This keeps the Tk event loop responsive and preserves the existing serial
OpenD request contract. The status bar exposes running, completed, and failed
states. Failures are shown as concise messages; exception tracebacks are not
displayed to ordinary users.

Run-history projection combines collection and dataset run metadata through
the public API and exposes run ID, dataset, timestamps, status, row count,
requested items, and serialized failure summary. It does not mutate run
records.

## 6. Compatibility

The legacy unbounded `MarketVault.load_bars` method remains available and its
`session` parameter remains a normalized row-session filter. It accepts a new
optional `requested_session` filter. Calls that omit it remain compatible for
zero or one matching request cohort and fail closed when multiple cohorts
would otherwise be combined. The CLI preserves `query --session` as the
legacy row-session alias while adding explicit `--requested-session` and
`--bar-session` options. No source schema, Parquet layout, DuckDB table,
manifest, quality, version, tag, or release contract changes.

Storage / Purge requires an exact physical-scope preview followed by typed
`PURGE <plan_id>` confirmation. A refused plan, including a partial symbol
selection of a multi-symbol file, never enables execution. Successful
execution moves whole Raw/Curated pairs to quarantine and never permanently
deletes them. The normative lifecycle behavior is recorded in
[`safe_purge_v01.md`](safe_purge_v01.md).
