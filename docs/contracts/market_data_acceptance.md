# Fixed market-data cases and observed changes (Q45)

## Purpose and dependency

Run [Q44 explicit market-data comparison](market_data_comparison.md) on six
predeclared cases, retaining cases that lack data or fail validation. Optional
explicit earlier snapshots describe changes between the supplied observations.
Q44 remains the authority for snapshot fields, UTC bar geometry, numerical
tolerances, invalid-row diagnostics, source declarations and file identities.

This is an offline Python API and settings-independent CLI. Every result has
`market_accuracy_certified=false`. There is no overall PASS: agreement between
supplied snapshots, a category label and a source reference do not certify
independent real-market data or establish that an event occurred.

## Suite manifest v1

The manifest is strict JSON with these fields:

| Field | Requirement |
|---|---|
| `schema_version` | Exactly `market-vault-market-data-suite-v1` |
| `cases` | Array containing each of the six categories below exactly once |
| `tolerances` | Optional Q44 object with `price_absolute`, `price_relative`, `volume_absolute`; omitted or null means all three are zero |

Tolerances are suite-wide finite nonnegative numbers, excluding booleans. They
apply to both periods of every cross-source comparison. There are no per-case
overrides, inferred scales, fitted tolerances or historical tolerance defaults.

Each case contains the following fields. No other fields are accepted.

| Field | Requirement |
|---|---|
| `category` | One fixed category; it is also the case ID |
| `scope` | Complete Q44 scope, including the declared UTC window |
| `current` | Exactly `{"left": path_or_null, "right": path_or_null}` |
| `previous` | Optional earlier path pair of the same shape; omitted or null means no baseline |
| `event_evidence` | Optional declaration reference; omitted or null means no event evidence |

A path is a nonempty string or null. Relative snapshot paths resolve against
the manifest's parent directory, not the process working directory. Paths are
explicit: there is no latest selection, directory discovery or automatic
download. `event_evidence`, when present, is a nonempty reference string with
no surrounding whitespace or control characters. It is retained for external
review; the program does not retrieve or authenticate its contents.

Malformed JSON, unsupported/invalid manifest fields or an invalid category set
(missing, duplicate or unknown category) rejects the manifest. These errors
cannot yield a truthful fixed-six report. After categories are established,
an invalid current-case definition remains in the report as `INVALID_INPUT`;
it is not dropped. An invalid `previous` path pair instead affects only history.
For an otherwise valid and compatible case, a null path or missing file yields
`NOT_RUN`. The original case object is retained as `definition`.

## Categories and calendar qualification

| Category | Required interpretation |
|---|---|
| `NORMAL` | The declared date has a normal session in the bundled exchange calendar |
| `EARLY_CLOSE` | The declared date has an early-close session in that calendar |
| `DST_BEFORE` | The earlier member of the paired DST cases |
| `DST_AFTER` | The next exchange trading date after DST_BEFORE, with a one-hour change in New York UTC offset |
| `CORPORATE_ACTION` | A planned event case; event evidence is a caller declaration or unknown |
| `HALT_OR_LOW_ACTIVITY` | A planned activity case; neither a halt nor a no-trade cause is inferred from missing bars |

The DST pair must be chronological, consist of consecutive exchange trading
dates and span a one-hour offset change. Two arbitrary dates cannot satisfy
the category merely through their names. Calendar facts come from the existing
[US RTH calendar](us_rth_calendar_v1.md); its supported dates and qualification
limits remain unchanged. Exchange classification does not extend the provider
qualification required by the Canonical export bridge.

The two event categories can remain unqualified planned cases. A reference
records a declaration, not verified event occurrence, corporate-action terms,
halt status, or a causal explanation for a difference. Missing event evidence
does not turn an absent input into a successful acceptance result.

`category_evidence.status` is CONFIRMED or MISMATCH for calendar/DST checks,
with `evidence_scope=BUNDLED_CALENDAR_AND_TIMEZONE`. For the event categories
it is DECLARED or UNAVAILABLE, with `evidence_scope=EVENT_DECLARATION_ONLY`.
An invalid scope has unavailable CASE_DEFINITION evidence. A calendar-category
mismatch makes the case NOT_COMPARABLE while retaining its current Q44 report;
CONFIRMED proves the calendar condition only.

## Current comparisons and fixed denominators

Every interpretable current snapshot scope must equal the declared case scope
after Q44 normalization. Equality between left and right alone is insufficient:
two sources for the wrong symbol, basis or window cannot satisfy this case.
The same requirement applies to previous snapshots.

Each case retains its complete Q44 report as `current_comparison`, including
input identities, source declarations, invalid rows, duplicates, coverage and
field-level differences. Q44 statuses retain their meanings: `NOT_RUN`,
`INVALID_INPUT`, `NOT_COMPARABLE`, `INCOMPLETE`, `DIFFERENT` and `MATCH`.
Historical errors do not erase or replace the current comparison.

`declared_expected_slots` is calculated independently from the case scope.
For a valid declared scope it remains available even when snapshots are
missing, malformed or incomparable. An invalid scope cannot establish this
denominator and must remain diagnosed rather than contributing zero slots.
The suite case denominator is always six, including invalid and missing cases.
No intersection of available inputs or successful cases becomes the denominator.

`summary.case_count` is 6; `summary.status_counts` contains the six uppercase
Q44 status names and sums to 6. `summary.declared_grid_slots` sums only scopes
whose denominators are known, while `summary.case_scopes_unavailable` counts
the remaining scopes separately. The partial slot total must not be presented
as complete coverage when scopes are unavailable.

An existing snapshot with empty `bars` is not a missing file: Q44 retains the
entire declared grid and reports incomplete coverage. If Q44 cannot establish
a common scope/grid, its empty result-row array does not represent an observed
empty market. The history calculation must not reinterpret it as such.

`report_schema_version` is `market-vault-market-data-acceptance-v1` and
`comparison_schema_version` records the Q44 version. Top-level
`status` is `NOT_RUN` when all six case statuses are NOT_RUN, and `REPORTED`
otherwise. REPORTED means the case evaluations were recorded; inspect each
case's current result, history diagnostics and source-independence declaration.
It does not assert a successful empirical acceptance.

Cases are emitted in the fixed category order above, independently of manifest
array order. A case reaching current comparison records `comparison_scope_matches_case`:
false for an observed scope mismatch, true for the common declared scope, or
null when there is insufficient input scope evidence. `manifest.locator`
records the explicit manifest path. Its `content_sha256` hashes the stable JSON
serialization of the supplied manifest, not its original whitespace bytes;
array order and explicitly supplied fields remain part of that identity.

## Explicit historical baseline

Omitted or null `previous` gives `NO_BASELINE`. It does not create an empty
old snapshot, imply no previous bars, or claim unchanged data. A supplied pair
with missing or unusable input remains an unavailable historical comparison.

Both supplied periods are compared using the **current manifest's same case
definition and tolerances**. The report explicitly records
`previous_comparison_recomputed_under_current_rules`. This recomputes the
earlier snapshots; it does not load an old result, replay earlier settings or
claim that a report generated under unknown older rules has been reproduced.
The flag is true only when the previous pair was passed through the comparator.

For each side, the earlier and current source declarations must keep
`provider`, `version`, `data_kind`, `upstream_id` and `upstream_evidence`
unchanged. `captured_at` must be strictly earlier in that side's previous
snapshot. A source-version or lineage declaration change is a definition
change, not an OHLCV revision. Such changes remain visible as
`NOT_COMPARABLE`; insufficient input evidence is `UNASSESSABLE`.

The `history` object uses these statuses independently of the case status:

| History status | Meaning |
|---|---|
| `NO_BASELINE` | `previous` was omitted or null |
| `INVALID_INPUT` | The supplied previous path pair is malformed |
| `NOT_RUN` | A supplied observation is missing in either period |
| `NOT_COMPARABLE` | Case/calendar, declared scope or source-definition requirements differ |
| `UNASSESSABLE` | A common grid cannot be established, the baseline is not earlier, or an invalid case prevents historical evaluation |
| `REPORTED` | The common grid and source/time requirements permit the per-slot analysis below |

Specific blockers are retained in `history.issues`. Missing observations are
handled before historical grid/lineage checks; a preexisting case-definition
mismatch prevents historical assessment. `previous_comparison`, when run,
keeps the full earlier Q44 result. `source_declaration_changes` preserves changed
fields with previous/current values, and `observations` records each side's
two capture times when those declarations can be examined. Without sufficient
evidence, these fields are not fabricated.

File/content hashes, build IDs, row versions and `origin` metadata may change.
Those identity or provenance changes do not themselves count as numerical bar
changes. Capture, market-availability and archive times keep their declared
meanings: none establishes when the vendor first published a revision or when
a past strategy could have known it.

Each evaluated case/period pair calls the public `compare_snapshot_files` once.
History consumes the already captured Q44 reports for identities, sources
and bar values; it does not reopen the same snapshots for a second reading.
This prevents one report from mixing its comparison with a later reread. It
does not promise a cross-file atomic snapshot, synchronize provider observation
times or retain a complete history of changes between the two observations.

## Per-side bar changes

For each declared slot, compare each side with its own previous snapshot.
OHLCV comparison uses exact numeric equality, **without tolerances**. A value
change smaller than the permitted cross-source tolerance remains CHANGED.
Formatting or provenance changes alone do not change the OHLCV value.

| State | Previous/current observation on this side |
|---|---|
| `ADDED` | Missing before, now valid and unique |
| `REMOVED` | Valid and unique before, now missing |
| `CHANGED` | Valid and unique in both; at least one OHLCV value differs |
| `UNCHANGED` | Valid and unique in both; all five values equal |
| `BOTH_MISSING` | Missing in both supplied snapshots |
| `UNASSESSABLE` | Invalid or duplicate data prevents this slot's comparison |

When history is REPORTED, `history.bar_changes.left` and `.right` each contain
`expected_slots`, lowercase `counts` and slot `rows`. The row contains `start`,
`end`, uppercase `status`, `changed_fields`, and previous/current OHLCV objects
(null where no valid unique bar is available). Counts partition that side's
declared-slot denominator; otherwise `bar_changes` is null.

ADDED and REMOVED describe observed record presence; they do not assert a
new trade, a vendor revision's publication time, or an automatic repair.
Invalid/duplicate slots remain unassessable while other valid slots can still
be reported. `history.input_diagnostics_present` identifies retained input
problems when history is REPORTED.

## Per-field discrepancy changes

Discrepancies are tracked by **(bar start, field)** for the five OHLCV fields.
Each period's left/right comparison uses the same Q44 tolerances. Tracking by
bar alone would hide a resolved open discrepancy followed by a new close
discrepancy on that same bar.

| State | Earlier/current cross-source field result |
|---|---|
| `NEW` | Within tolerance before, outside tolerance now |
| `PERSISTENT` | Outside tolerance in both periods |
| `RESOLVED` | Outside tolerance before, within tolerance now |
| `STABLE_MATCH` | Within tolerance in both periods |
| `UNASSESSABLE` | At least one period lacks valid unique bars on both sides |

When history is REPORTED, `history.discrepancy_changes` contains
`expected_fields`, lowercase `counts` and slot `rows`; otherwise it is null.
Counts partition `declared_expected_slots * 5`. Each row retains `start`, `end`,
`previous_status`, `current_status` and a `fields` map of the five uppercase
change statuses. Missing, invalid or duplicate bars are not field matches.
In particular, a previous
discrepancy followed by a missing current bar is UNASSESSABLE, never RESOLVED.
Previous and current Q44 slot statuses remain available to explain coverage
changes, and their nested field records retain the earlier/current values.

## Minimal executable manifest and entry points

The following example creates all six planned slots with **no supplied market
data**. The two event categories reuse an ordinary date solely as placeholders
for a future explicit case definition. They assert no corporate action, halt
or low-activity event. Replace their scopes and evidence only when actual case
inputs and supporting declarations are available.

Run this Python code once from the repository's configured environment:

```python
from market_vault.quality.market_data_comparison import write_market_data_json

common = {
    "symbol": "US.AAPL", "asset_class": "EQUITY",
    "adjustment": "NONE", "session": "RTH", "interval": "5m",
    "currency": "USD", "aggregation": "TRADE_OHLCV", "volume_basis": "SHARES",
}
windows = [
    ("NORMAL", "2025-03-03T14:30:00Z", "2025-03-03T21:00:00Z"),
    ("EARLY_CLOSE", "2025-11-28T14:30:00Z", "2025-11-28T18:00:00Z"),
    ("DST_BEFORE", "2025-03-07T14:30:00Z", "2025-03-07T21:00:00Z"),
    ("DST_AFTER", "2025-03-10T13:30:00Z", "2025-03-10T20:00:00Z"),
    ("CORPORATE_ACTION", "2025-03-03T14:30:00Z", "2025-03-03T21:00:00Z"),
    ("HALT_OR_LOW_ACTIVITY", "2025-03-03T14:30:00Z", "2025-03-03T21:00:00Z"),
]
manifest = {
    "schema_version": "market-vault-market-data-suite-v1",
    "cases": [
        {
            "category": category,
            "scope": {**common, "window_start": start, "window_end": end},
            "current": {"left": None, "right": None},
            "previous": None,
            "event_evidence": None,
        }
        for category, start, end in windows
    ],
}
write_market_data_json("reports/market-data-suite.json", manifest)
```

```shell
market-vault market-data-acceptance --manifest reports/market-data-suite.json --output reports/market-data-acceptance-01.json
```

This produces six NOT_RUN cases and six NO_BASELINE histories. Their declared
grids remain visible, and top-level status is NOT_RUN. It does not fabricate
bars to fill missing inputs. To supply data, use the Q44 normalized JSON
snapshot or its existing CSV/explicit Canonical export bridges, then put the
exact snapshot locators in `current` and, if available, `previous`. For example,
`"left": "snapshots/left.json"` in this manifest resolves under `reports/`.

The Python API is:

```python
from market_vault.quality.market_data_acceptance import run_market_data_acceptance
from market_vault.quality.market_data_comparison import write_market_data_json

report = run_market_data_acceptance("reports/market-data-suite.json")
write_market_data_json("reports/market-data-acceptance-api-01.json", report)
```

The CLI dispatches before settings load and prints the existing
`{status: SUCCESS, output, report}` envelope on successful creation, with exit
code 0. A report with NOT_RUN, invalid cases or unavailable history is still
a successfully created diagnostic artifact. Manifest or execution errors use
JSON on stderr and exit code 1; argparse keeps its normal syntax-error behavior.

Report/export writes reuse Q44's strict JSON encoder and existing
`_write_file_no_replace`. Every existing destination is refused, even when
bytes would be identical. Repeated evaluation with the same explicit inputs
is deterministic; choose a new output path for another saved report.
Publication errors retain the helper's `published` boolean/null. Input files,
previous snapshots and earlier reports remain untouched.

## Acceptance and exclusions

Acceptance exercises a mixed fixed-six manifest, all-missing inputs, malformed
known cases and invalid category sets; actual API/CLI use and relative paths;
calendar/DST qualification; current results retained despite history failures;
exact bar changes and per-field discrepancy counts; sub-tolerance changes;
metadata-only changes; invalid/duplicate-slot partial assessment; source/scope
and observation-time continuity; and new-file deterministic publication.
An old discrepancy becoming missing must remain unassessable. Empty Q44 rows
without a common grid must not become fictional added/removed market records.

Excluded are a database or scheduler, downloads or subscriptions, automatic
calendar updates, archive replacement, historical evidence rewriting, a full
vendor revision authority, inferred revision-publication or point-in-time
knowability, corporate-action returns, security-master reconstruction, TEST-use
registration and further strategy searches. Q45 neither broadens Q44's supported
data basis nor certifies real-market accuracy. Synthetic fixtures establish
the implementation contract only; actual qualifying independent inputs and
event evidence remain separate empirical work.
