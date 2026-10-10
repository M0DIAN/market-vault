# Unadjusted return assessment V1 (Q29)

## 1. Purpose and authority

Q29 makes the meaning of current `NONE` prices visible and screens explicitly
recorded price or holding windows against a caller-supplied finite restriction
list. The independent assessment version is
`market-vault-return-assessment-v1`. The approved scope is
[Research data quality Q27–Q29](../research_data_quality_next.md).

Current Labels and price-derived Features consume the recorded unadjusted
prices. Backtests and benchmarks use those prices with their existing execution
and cost rules. Split-share adjustments and cash-dividend accounting are not
applied. Existing `total_return` fields describe the cumulative return of their
simulated account; the field name does not establish complete corporate-action
accounting. The cross-day buy-and-hold benchmark remains a price benchmark.

The existing [adjusted-price PIT policy](../adjusted_price_pit_as_of_policy_v1.md)
is unchanged: PIT requests allow only `adjustment = NONE`. PIT verification
checks the established source and information-availability constraints. It
does not prove that corporate actions have been accounted for or that the
period is free of them.

The financial distinction matters even when an arithmetic result is
reproducible. A stock split changes share count and per-share price; the split
itself need not change the shareholder's equity. Investment return can also
include cash distributions. A raw-price ratio alone does not represent those
accounting effects. Financial background provenance, reviewed 2026-10-10:

- [Investor.gov — Stock Split](https://www.investor.gov/introduction-investing/investing-basics/glossary/stock-split).
- [FINRA — Key Concepts: Return and Rate of Return](https://syndication.finra.org/content/key-concepts-return-and-rate-return).

These references explain the disclosure. They are not an event feed, a sealed
corporate-action authority or evidence that a particular saved return is wrong.

## 2. Supported inputs

The command accepts exactly one explicit source:

```console
market-vault research-return-assessment (--dataset DIR | --experiment FILE) [--events FILE] [--source-dataset DIR]
```

`--dataset` selects a final multi-source cross-day Dataset directory with
`NONE` prices and requested session `RTH`, read by
`load_verified_multi_source_cross_day_dataset`. It screens the complete
recorded price-consuming Feature and supported Label windows. Embedded
Canonical rows and the recorded schedule supply the price evidence; no raw
Canonical path discovery or current calendar lookup is performed.

`--experiment` selects one saved record, read by `load_strategy_experiment`:

| Saved artifact | Assessment scope |
| --- | --- |
| Ordinary `market-vault-strategy-experiment-v1` | Actual trades in every saved strategy result; the recorded buy-and-hold benchmark when the mode is `RISK`. |
| Ordinary `market-vault-intraday-experiment-v1` / `v2` | Actual trades in every saved result and every group's benchmark, including finite intraday diagnostics in these schemas. |
| `market-vault-intraday-test-v1` / `v2` | Actual trades in the saved TEST execution and its benchmark. |

Intraday V2 and TEST V2 include the saved ML results without adding a model-
specific window interpretation. Selection-only artifacts, inner-selection
artifacts, base strategy diagnostics bundles, scenario collections and
standalone intraday data artifacts are outside this command's V1 scope.
Export or choose a supported ordinary experiment as a separate explicit input
where available.

For an ordinary base experiment, assessment also reads the exact Dataset
locator in the saved plan and requires its verified `dataset_id` to equal the
saved root's `dataset_id`. `--source-dataset` can relocate this same Dataset;
it cannot select a different economic source. Missing or mismatched evidence
refuses the assessment, including when all strategies have zero trades. The
Dataset supplies the benchmark's symbol when no trade can supply one. This
requirement belongs to the new assessment; old source-free experiment Open
continues to work under its existing contract. Other source kinds reject
`--source-dataset`.

All inputs are local and explicit. The command does not load settings,
initialize OpenD, access the network, scan for `latest`, fit a model or execute
a strategy. It produces independent stdout JSON and does not write inside a
source artifact or use an existing experiment writer for its result.

The public functions in `research.return_assessment` are
`parse_event_restrictions(payload: bytes)`, `assess_dataset(build_dir, *,
events=None)` and `assess_saved_experiment(path, *, events=None,
source_dataset=None)`. They use the same normalization and source checks as
the CLI; the optional `events` value is a parsed restriction object, not a
network source. An unsupported or contradictory required window refuses the
whole assessment. It does not return a partial success after dropping that
window.

## 3. Price-support time and information-availability time

For an embedded Canonical bar, the price-support interval ends at:

```text
price_end = min(event_time + recorded interval, recorded session_close)
```

The bar must lie within its recorded session and align with its interval
grid. The schedule's recorded daily entries supply that session's close,
including a known truncated final bar.
Q29 does not recreate a calendar or substitute the current bundled schedule.

`market_available_at` and Label `actual_label_end_time` retain their original
information-availability meanings. A later availability time does not extend
the period represented by a price bar. Assessment uses the support times to
describe economic price consumption and preserves the existing PIT meanings.

The resulting interval is a description of consumed prices, not a claim to
know the instant of each high or low. A single consumed close can form a
zero-duration price point; the implementation must not manufacture a longer
window merely to make interval matching possible.

## 4. Dataset windows

Only actual complete consumption contributes a window. Candidate rows,
nominal request bounds and unused provenance rows do not expand it.

| Calculation | Start | End and precision |
| --- | --- | --- |
| Feature consuming only `close` among the price fields | First actually consumed bar's price end | Last actually consumed bar's price end; close-price endpoints. |
| Feature consuming `open`, `high` or `low` | First actually consumed bar's `event_time` | Last actually consumed bar's price end; conservative consumed-bar span. |
| `forward_return` / `forward_direction` | Anchor bar's price end | Last actually consumed future bar's price end. |
| `maximum_favorable_excursion` / `maximum_adverse_excursion` | Anchor bar's price end | Last actually consumed future bar's price end; future extrema are supported by bar intervals. |
| `forward_open_to_close_return` | First actually consumed future bar's `event_time` | Last actually consumed future bar's price end. |

The open-to-close Label's recorded anchor ID is provenance and is not an
input price for that formula. An event between signal day and entry, but at or
before the actual entry open, does not become an exact crossing of a later
same-session open-to-close window.

Excluded/incomplete Feature or Label results do not have a fabricated complete
window. Volume-only Features and Observation Features are omitted from this
price screen and counted as omissions. Their absence from the windows is not
an assertion that their own semantics have been assessed. A Feature that uses
both price and volume receives a price-support screen only; volume adjustment
semantics are not assessed. Unknown price or
Label interpretation is unsupported rather than guessed.

## 5. Saved experiment evidence

### Ordinary base experiments

Each saved trade is locally bound to its selected execution-safe Label:
symbol, sample key, signal, entry and exit must agree with the recorded
decision. This is a correspondence check against verified saved inputs,
without recomputing Label values, predictions, returns, costs or equity.
When an equity curve is present, its ENTRY/EXIT records must also match the
accepted trades and the verified endpoint rows and prices.

For the current base engine, a saved simulation exit can validly equal Label
availability even when the supporting price bar ended earlier. When those
clocks differ, Q29 cannot claim an exact supported holding window. The new
assessment refuses with the saved simulation-exit and price-support-end
times. This is an assessment-specific precision limit: it does not declare
the source artifact corrupt, rewrite it or alter old Open/Replay acceptance.

For `RISK`, the existing buy-and-hold curve is checked as its own complete
holding window, using the recorded equity start/end and the Dataset symbol.
It can cross market dates even when strategy trades are shorter or absent.
`COMPARISON` and `EQUITY` do not acquire a synthetic benchmark.

### Intraday ordinary and TEST experiments

Ordinary V1/V2 and TEST V1/V2 use a shared interpretation of their saved
executions. Every strategy trade and benchmark trade has its own entry-to-exit
window. Cash between sessions is not combined into a continuous position, and
the earliest entry and latest exit across multiple days never stand in for
actual holdings. Current same-session execution and forced-flat behavior are
preserved.

Additional local evidence checks require the recorded daily open/close and
interval to form a complete grid; every ledger OPEN/CLOSE pair to describe the
same day, slot and row at the corresponding grid times; and each trade's
entry/exit time, slot, row and raw open to agree with that grid. Its BUY/SELL
transaction and ledger action must agree with the same endpoint. Recorded
holding quantities must agree across ledger actions, trades and transactions,
and every recorded session must end flat. These checks only associate the
saved records. They do not reexecute the kernel, reconcile all account
arithmetic or establish Canonical provenance for the saved grid.

### Economic versions and evidence labels

Q29 requires the known economic versions needed to interpret these prices and
executions. The checked keys are:

| Source | Required `algorithm_versions` keys |
| --- | --- |
| Base `COMPARISON` | `backtest` |
| Base `EQUITY` | `backtest`, `equity`, `strategy_equity` |
| Base `RISK` | `backtest`, `equity`, `strategy_equity`, `buy_and_hold`, `strategy_risk` |
| Intraday ordinary or TEST | `data`, `execution`, `cost`, `benchmark` |

The intraday execution's own economic versions and recorded event order must
also match the supported meanings. An unknown required economic version
refuses the new assessment. Unrelated model and statistical versions, such as
Ridge or Sharpe computation, are not extra Q29 interpretation gates. A direct
Dataset assessment relies on its strict reader and records no additional
saved-experiment economic version map.

Dataset evidence is labelled `STRICT_VERIFIED_DATASET`. Saved-experiment
evidence is labelled `VALIDATED_SAVED_RECORDS_NOT_REPLAYED`. Local grid and
trade correspondence checks do not upgrade either label to a new Replay or
corporate-action PIT verification claim.

## 6. Explicit finite restriction list

`--events` is optional. When present, it accepts this strict root:

```json
{
  "schema_version": "market-vault-return-restrictions-v1",
  "provenance": "Synthetic example of a finite retrospective research screen",
  "events": [
    {
      "event_id": "example-split-instant",
      "symbol": "US.EXAMPLE",
      "kind": "EFFECTIVE_INSTANT",
      "effective_at": "2026-06-01T13:30:00Z",
      "source": "Synthetic exact-time example; not a real corporate-action record"
    },
    {
      "event_id": "example-date-review",
      "symbol": "US.EXAMPLE",
      "kind": "DATE_RESTRICTION",
      "start_date": "2026-06-02",
      "end_date": "2026-06-02",
      "source": "Synthetic date-only example; not a real corporate-action record"
    }
  ]
}
```

Root and tagged event objects require exactly their declared fields. JSON is
UTF-8 without a BOM; duplicate object keys and nonfinite constants are rejected.
Provenance, event ID and source are nonempty strings; event IDs are unique
across the list. Symbol uses the canonical uppercase US form, matching
`US\.[A-Z0-9][A-Z0-9.\-]*`. `EFFECTIVE_INSTANT` requires a timezone-aware ISO
timestamp. `DATE_RESTRICTION` requires ordered inclusive `YYYY-MM-DD` dates. A
date-only fact must not be converted into an invented exact effective instant.

Provenance and each event's source describe the caller's declared evidence.
Assessment neither discovers nor independently qualifies those facts. The
list is a retrospective research-quality restriction, not proof that an
action was publicly known at a historical decision time. It is not a Feature,
an adjustment factor or a corporate-action PIT authority.

### Matching

Symbol equality is required for both kinds. For an exact effective instant,
the predicate is:

```text
window_start < effective_at <= window_end
```

An instant at or before entry is excluded from that window's exact crossing.
A zero-duration point has no such crossing. This convention does not resolve
uncertain event timing; callers must use a declared date restriction for that
case.

A date restriction matches when its inclusive date range overlaps the
window's covered calendar dates in `America/New_York`. It is a conservative
date overlap with a distinct reason, not a proven exact action crossing. It
may restrict a same-day trade; that trade's market-date classification still
remains same-day. Other symbols and disjoint dates/times do not match.

Exact-instant matches use reason `DECLARED_EFFECTIVE_INSTANT_IN_WINDOW`;
date overlaps use `CONSERVATIVE_DATE_RESTRICTION_OVERLAP`. Neither reason is an
independently verified corporate-action fact.

### Coverage and screening are separate

| Input | Coverage meaning | Screening meaning |
| --- | --- | --- |
| No restriction list | `UNKNOWN` | `NOT_CHECKED`; no event search occurred. |
| Any explicit finite list, with no assessed-window match | `PARTIAL` | `NO_LISTED_INTERSECTION`, including for an empty event array. |
| Any explicit finite list, with at least one assessed-window match | `PARTIAL` | `KNOWN_RESTRICTION_INTERSECTION`; reference the declared restriction IDs and affected windows. |

An empty list or zero listed matches never means complete event coverage,
`NO_CORPORATE_ACTIONS`, a clean bill of financial health or permission to use
adjusted PIT prices. Cross-date classification describes the window alone;
it neither proves an action nor turns unknown coverage into known coverage.

## 7. Assessment JSON, identities and CLI results

Success prints one flat JSON object without a success envelope:

| Field | V1 meaning |
| --- | --- |
| `version` | `market-vault-return-assessment-v1`. |
| `source_kind` | `DATASET`, `SAVED_BASE_EXPERIMENT` or `SAVED_INTRADAY_EXPERIMENT`. Ordinary intraday and TEST share the last value. |
| `source_id` / `dataset_id` | Original source identity and its original Dataset/data identity. For direct Dataset input the two are equal. |
| `source_evidence` | `STRICT_VERIFIED_DATASET` or `VALIDATED_SAVED_RECORDS_NOT_REPLAYED`, as defined above. |
| `source_economic_versions` | Only the checked saved economic version map; `{}` for direct Dataset input. |
| `price_basis` | `NONE_UNADJUSTED`. |
| `split_share_adjustment` / `cash_dividend_accounting` | Both `NOT_APPLIED`. |
| `total_return_semantics` | `SIMULATED_ACCOUNT_CHANGE`, describing the existing account-return field meaning. A Dataset assessment does not itself calculate account return. |
| `coverage_status` / `screening_status` | The independent coverage and listed-intersection states in section 6. |
| `restriction_list_id` / `restriction_provenance` | Normalized full-list identity and declared root provenance; both null when no list was supplied. |
| `restriction_list_version` | `market-vault-return-restrictions-v1`, or null when no list was supplied. |
| `restriction_events` | Complete normalized finite event array, retaining each event's source and exact time or date range. Null means no list; `[]` means an explicitly supplied empty list. |
| `assessed_classes` / `excluded_classes` | The source-specific scope described below. Exclusions do not become covered because no restriction matched. |
| `window_counts` | Present role counts, `total` and `crosses_market_dates`. Counts are window counts, not unique trades, events or market days. |
| `omitted_counts` | Dataset omission counts; an empty object for saved-experiment assessment. |
| `windows` | Deterministically ordered window records with their own identities. |
| `restriction_matches` | Records containing exactly `event_id`, `window_id` and `reason`. |
| `assessment_id` | Full-content identity of this assessment, excluding its own `assessment_id` field. |

Direct Dataset assessment declares `COMPLETE_PRICE_FEATURES` and
`COMPLETE_PRICE_LABELS` as assessed classes. It excludes `VOLUME_ONLY_FEATURES`,
`OBSERVATION_FEATURES` and `INCOMPLETE_CALCULATIONS`; omission counts use
`volume_only_features`, `observation_features`, `incomplete_price_features`
and `incomplete_price_labels` where applicable. Saved-experiment assessment
declares `RECORDED_STRATEGY_HOLDINGS` and `RECORDED_BENCHMARK_HOLDINGS`, and
excludes `TRAINING_FEATURES`, `TRAINING_TARGETS` and `UNEXECUTED_SIGNALS`.
Classes describe the selected assessment scope; a class can have zero windows,
including base modes without a recorded benchmark.

Each window contains exactly:

```text
role, owner_id, symbol, start_time, end_time, clock_basis,
start_row_version_id, end_row_version_id, crosses_market_dates, window_id
```

Roles are `FEATURE`, `LABEL`, `STRATEGY_TRADE` and `BENCHMARK_HOLDING`.
`owner_id` binds the originating sample/calculation or saved result/trade;
the endpoint row IDs bind the supporting recorded prices. `clock_basis` is
`PRICE_ENDPOINTS`, `CONSUMED_BAR_SPAN` or `RECORDED_EXECUTION`.
`crosses_market_dates` compares the endpoints' dates in `America/New_York`;
it is not an event indicator. Start and end are normalized UTC timestamps
with six fractional digits and a `+00:00` offset. A zero-duration close-price
point remains `PRICE_ENDPOINTS` with equal start and end times.

Restrictions are normalized to UTC timestamps and sorted by `event_id` before
their complete schema, provenance, sources and event content are hashed.
The output retains that declared evidence in `restriction_list_version`,
`restriction_provenance` and `restriction_events`. These reconstruct the
normalized list's `schema_version`, `provenance` and `events` fields for
verification of `restriction_list_id`; matches can be resolved against the
embedded event array without reopening the original event file. All these
fields also participate in the assessment's full-content identity.
Equivalent aware timestamp offsets, JSON formatting and event-array order do
not change the normalized restriction identity. Windows are sorted by
`role`, `owner_id`, then `window_id`; matches follow normalized event order
and that window order. The window identity hashes the assessment version
and the window's other fields. The assessment identity hashes the complete
result without its own identity field. These SHA-256 identities use the
existing canonical UTF-8 JSON encoder: sorted keys, compact separators,
nonfinite numbers forbidden, and one trailing newline.

No source locator, event-file path, output path, retrieval timestamp or current
clock is added to these records or identities. Existing source identities
are retained as recorded. Relocating an identical source through an explicit
path override does not change an otherwise identical assessment.

| Outcome | Stream and content | Exit |
| --- | --- | --- |
| Assessment completes without a listed restriction match | One full assessment JSON object on stdout; stderr empty. UNKNOWN/PARTIAL still applies. | `0` |
| Assessment completes with one or more listed matches | The same full assessment shape on stdout, with matches; stderr empty. | `2` |
| Input, source binding, required economic version or exact window evidence cannot be assessed | One failure JSON object on stderr; stdout empty. | `1` |

The failure object contains `version`, `status = FAILED`, `reason_code` and
`error`. Reason codes distinguish `INVALID_INPUT`, `UNSUPPORTED_SOURCE`,
`SOURCE_ID_MISMATCH`, `UNSUPPORTED_ECONOMIC_VERSION`,
`UNSUPPORTED_PRICE_CLOCK` and `CONTRADICTORY_WINDOW_EVIDENCE`. For the valid
saved simulation-exit/price-support mismatch described in section 5, the
error message includes both UTC times and the assessment-only limitation.

Selecting neither or both source options, or using `--source-dataset` for an
ineligible source, is a handler input error with exit `1`. Global argparse
syntax errors, such as an unknown option or a missing option value, keep their
normal stderr diagnostic and exit `2`; they do not produce assessment JSON.
Scripts must distinguish that syntax failure from a completed restricted
assessment using the output stream and JSON shape. The command does not
automatically prohibit an existing build or backtest invocation.

For example, a synthetic cross-day close-to-close price change from `100` to
`50` retains the existing Label value `50 / 100 - 1 = -0.5`. A declared split
instant inside its actual window can produce a restriction match; Q29 neither
replaces that result with a purported total return nor computes a new share
count. If entry and exit instead belong to a later same-session open-to-close
window, an instant at or before that entry does not match that window. Other
assessed Feature or benchmark windows are considered independently.

## 8. Compatibility and non-goals

Assessment has its own version and identity and references the source's
existing Dataset or experiment identity. It does not add fields to old raw
reports, broaden old exact-field schemas, modify stored bytes or IDs, create a
sidecar in a sealed Dataset directory, or change historical Replay behavior.
Existing transform source modules, including their docstrings and complete-
source fingerprints, are unchanged. No old numerical field is renamed.

There is no QFQ/HFQ enablement, unsafe override, split-share or dividend
accounting, total-return engine, factor feed, price-jump split inference or
complete-coverage claim. The assessment does not silently delete samples,
trades or days, alter candidate cohorts, split TRAIN/VALIDATION/TEST again or
automatically attach a mutable list to old Open/Replay. Its nonzero match
status is an explicit external gate over the declared source and restriction
list; existing build and backtest commands retain their current behavior.

The research and intraday workspace parent screens disclose the current
price/accounting basis and `UNKNOWN` corporate-action coverage in English and
Chinese. This is their unassessed default: no independent assessment result
is attached to the old GUI record state. The separate CLI assessment can
report `PARTIAL` for a supplied list. The screen text does not claim that the
CLI has already run, and no old report format is extended to store it.
