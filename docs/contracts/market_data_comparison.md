# Explicit market-data comparison (Q44)

## Purpose and limits

Compare two explicitly supplied local bar snapshots. This is an offline Python
API and settings-independent CLI. It does not discover a latest dataset, query
a GUI page, call OpenD, download a provider feed, repair an archive, or certify
market accuracy. `MATCH` means agreement on the **entire declared bar grid**.
Every report has `market_accuracy_certified=false`.

The bounded scope is a declared US EQUITY or ETF, NONE, RTH, and one of
1m/5m/15m/30m. A scope is one continuous window on one New York trading date.
60m, truncated bars, daily bars, extended sessions, adjusted prices, arbitrary
adapters, corporate-action returns and historical security-master claims are
outside this contract. The asset class and symbol are caller declarations.

## Snapshot v1

The top-level fields are exactly `schema_version`, `source`, `scope`, `bars`,
and an optional object `origin`. Schema version is
`market-vault-market-data-snapshot-v1`.

| Source field | Required meaning |
|---|---|
| `provider` | Explicit provider/source name; a different label does not establish independence |
| `version` | Explicit source version, never inferred from the installed SDK or a file timestamp |
| `captured_at` | Caller-declared observation/acquisition instant in UTC; not first publication or revision-publication time |
| `data_kind` | `OBSERVED`, `SYNTHETIC`, or `UNKNOWN` |
| `upstream_id` | Declared underlying source identity, or null |
| `upstream_evidence` | Reference supporting that declaration, or null; stored for external review |

| Scope field | Required meaning |
|---|---|
| `symbol` | Explicit uppercase `US.` symbol |
| `asset_class` | `EQUITY` or `ETF` declaration |
| `adjustment` / `session` | Exactly `NONE` / `RTH` |
| `interval` | `1m`, `5m`, `15m`, or `30m` |
| `currency` | Explicit price currency |
| `aggregation` | Explicit aggregation convention identifier |
| `volume_basis` | Explicit volume convention identifier, such as shares |
| `window_start` / `window_end` | UTC endpoints of the half-open declared window |

All ten normalized scope fields must agree between sources. Currency,
aggregation and volume basis are not guessed or fitted. Each bar contains
exactly `start`, `end`, `open`, `high`, `low`, `close`, `volume`, and optional
object `origin`. Scope fixes the symbol and interval, so the business key is
`start`; an incorrect `end` is an invalid row, not another key.

Timestamp text requires ISO date, `T`, seconds, at most six fractional digits,
and `Z` or `+00:00`. Naive timestamps and non-UTC offsets are refused rather
than interpreted using the machine timezone. Bars are interval-start labeled,
represent `[start,end)`, and require `end = start + interval`.

The existing bundled exchange calendar validates the declared RTH window,
including closures, early closes and DST-dependent UTC boundaries. The current
calendar covers 2025–2027; unsupported dates fail clearly. Both window endpoints
must align to the interval grid anchored at the exchange open. A partial RTH
window is allowed when explicitly declared; its coverage is not full-day
coverage. The report records the calendar version and source reference.

## Invalid data stays visible

File-level errors include invalid UTF-8/JSON, duplicate JSON fields,
NaN/Infinity literals or numeric values outside finite JSON representation,
incorrect metadata/schema, and a non-array `bars`. Python snapshot arguments
use the same JSON-value contract. A file-level error produces `INVALID_INPUT`
with an input-specific error and the original file hash when bytes were read.

Row-level errors retain their original row index, original JSON value and all
detected reasons. They include missing/extra fields, wrong types (including
booleans and numeric strings), nonpositive prices, negative volume, invalid
OHLC order, wrong endpoints, ambiguous timestamps, and off-grid/outside-window
records. Q42's shared positive-price/nonnegative-volume predicates are reused;
volume zero is legal. CSV invalid numeric text is retained as a string so it
can reach these diagnostics without introducing non-JSON NaN values.

Every key maps to a list of input row indices. Duplicate keys retain all
participating rows and cannot be resolved by last-write-wins. Each side/slot is
`VALID_UNIQUE`, `MISSING`, `INVALID`, or `DUPLICATE`.

## Coverage, duplicates and differences

Expected slots come from the declared window, not the input intersection or
union. Per-slot results are MATCH, DIFFERENT, LEFT_ONLY, RIGHT_ONLY,
BOTH_MISSING, or BLOCKED (an invalid/duplicate row on either side).

The following invariant always holds when a common scope is established:

```text
expected_slots = matched + different + left_only + right_only
                 + both_missing + blocked
```

Both empty snapshots therefore remain INCOMPLETE with a nonzero denominator.
Missing files instead produce NOT_RUN. A missing bar always means an absent
input record; this contract cannot distinguish no trades from missing data.

Each input summary records input rows, valid unique slots, invalid rows,
duplicate keys, participating duplicate rows and duplicate excess rows.
`declared_grid_coverage` is valid unique slots / expected slots.
`duplicate_rate` is **duplicate excess rows / input rows**, where a key with
three rows contributes two excess rows and three participating rows. Every
ratio includes its numerator and denominator; empty-input duplicate rate is
null. Invalid and duplicate metrics can overlap; original rows are never
dropped to force mutually exclusive statistics.

The three tolerances are finite nonnegative numbers, excluding booleans, and
default to zero: `price_absolute`, `price_relative`, `volume_absolute`.
**Right is the numerical reference.** For each OHLC field:

```text
signed = left - right
relative = (left - right) / right
within_tolerance = abs(left - right)
                   <= price_absolute + price_relative * abs(right)
```

Volume uses only `abs(left-right) <= volume_absolute`. Both values, signed and
absolute differences, and the field decision are retained. Bounded high
precision decimal arithmetic avoids float overflow in the tolerance and
avoids collapsing distinct large integers before a zero-tolerance comparison.
Displayed fractional differences use finite floats; an unrepresentable
relative difference is null with `OUTSIDE_FLOAT_RANGE`. This display limit
does not change the comparison decision or remove original values.

## Result and evidence meanings

| Overall result | Meaning |
|---|---|
| NOT_RUN | At least one input path is absent or not provided |
| INVALID_INPUT | A file cannot be interpreted, or same-scope inputs have invalid/duplicate rows |
| NOT_COMPARABLE | Interpretable source scopes differ; their individual row diagnostics remain visible |
| INCOMPLETE | Same scope and legal unique rows, with at least one declared-grid coverage gap |
| DIFFERENT | Complete legal coverage, with at least one value beyond tolerance |
| MATCH | Complete legal coverage and all compared values within tolerance |

Missing/file-invalid inputs are handled before scope comparison. Scope
mismatch is handled before numerical comparison. Invalid rows take priority
over gaps; gaps take priority over differences, but all same-scope counts and
details remain present. If no common scope is established, joint scope/counts
are null; input-specific evidence is still retained. Invalid tolerance options
are API `ValueError`, not a statement about either market-data input.

`independence.status` is separate from the numerical result:

- SYNTHETIC when either interpretable source declares synthetic data;
- UNKNOWN when source nature, upstream identity or distinct-source evidence
  is missing;
- SHARED_UPSTREAM for the same declared upstream;
- DECLARED_DISTINCT_UPSTREAM for different declared upstreams with references.

All are explicitly scoped to `SOURCE_DECLARATIONS_ONLY`. References and origin
objects are declarations carried for review, not signatures or authenticity
proofs. Even OBSERVED plus DECLARED_DISTINCT_UPSTREAM plus MATCH does not cause
the code to certify market accuracy. No independent real-market source files
were supplied for this implementation; synthetic tests qualify the tool only.

Original file SHA256 and a deterministic snapshot content SHA256 are distinct.
The latter normalizes source/scope metadata and JSON formatting while retaining
original bar records/order and origins. Neither hash establishes an independent
market source. Reports use stable JSON bytes with no current-time defaults.

## Explicit input bridges

Both bridges require a metadata JSON object containing exactly `source` and
`scope` as above. No observation time, source/version, lineage, currency,
aggregation, volume basis or data nature is inferred.

**CSV** has the exact ordered header:

```csv
start,end,open,high,low,close,volume
```

Finite numeric text is converted to JSON numbers. Bad numeric text remains
text; missing values remain null; extra values remain `csv_extra_fields` for
row-level rejection. Every record after the header is retained, including
malformed rows and duplicates. Header/syntax errors fail clearly. There are no
column aliases, timezone guesses, inferred scales or adapters. The original
CSV SHA256 is retained in `origin`.

**Canonical** accepts one explicit build directory and always calls the real
`load_verified_canonical_build` on disk. It requires matching interval,
RTH/NONE and source schema `10.9-mv-ts2`; legacy `10.9` is not relabeled. It
validates actual selected-date rows against the existing qualified provider
RTH geometry, including row classification and date/start-grid consistency.
Known but unqualified provider early-close dates fail closed. This does not
apply Moomoo-specific qualification rules to external CSV snapshots.

Every bar in the declared symbol/date/window is exported, with no query limit.
An explicit empty window remains empty and compares as INCOMPLETE. Canonical
build/content/resolution IDs, request, versions and typed source provenance
are retained. Each exported bar retains its own row/source identities and
separately named `market_available_at` and `archive_available_at`. Build-level
provenance may include equivalent-discarded sources; it is not substituted for
the selected source of each bar. Captured time comes only from metadata.
Synthetic fixtures can produce verified Canonical builds and remain synthetic.

## API and CLI

```python
from market_vault.quality.market_data_comparison import (
    compare_snapshots, compare_snapshot_files, write_market_data_json,
)
from market_vault.market_data_exports import snapshot_from_csv, snapshot_from_canonical

report = compare_snapshot_files("left.json", "right.json")
write_market_data_json("new-comparison.json", report)
```

```shell
market-vault market-data-snapshot-from-csv --csv source.csv --metadata metadata.json --output left.json
market-vault market-data-snapshot-from-canonical --build path/to/explicit-build --metadata metadata.json --output right.json
market-vault market-data-compare --left left.json --right right.json --output comparison.json
```

The comparison command also accepts `--price-absolute`, `--price-relative` and
`--volume-absolute`. Paths are explicit; relative CLI paths are relative to the
working directory. These commands dispatch before application settings load.

Successful CLI execution prints `{status: SUCCESS, output, report}` and returns
0, meaning a report/export was created; inspect the nested comparison status
for MATCH/DIFFERENT/etc. A NOT_RUN or INVALID_INPUT comparison report can be a
successfully created diagnostic artifact. Input/export/publication execution
errors return 1 with JSON on stderr; argparse retains its standard behavior
for malformed command syntax.

Writes reuse the existing `_write_file_no_replace`: every existing target is
refused, including an identical previous output. Use a new destination for
another observation. A publication uncertainty preserves the helper's
`published` boolean/null in the CLI error; already published output is never
described as absent or retried as an overwrite. Inputs and earlier reports
remain untouched. No storage layout, existing schema, dependency, version,
release or CI gate is changed; only new test-family ownership is registered.
