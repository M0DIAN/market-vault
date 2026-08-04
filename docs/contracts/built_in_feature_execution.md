# Built-in Feature Execution Contract

Status: implemented in the v0.5.0 PR-3 dataset layer
(`market_vault.dataset.feature_models`,
`market_vault.dataset.feature_registry`,
`market_vault.dataset.feature_execution`, and
`market_vault.dataset.feature_transforms`).

This contract defines the deterministic execution of the built-in basic
OHLCV Feature catalog over PIT-selected Canonical rows: the frozen
invocation input, the strict PIT-to-Canonical row binding, the market /
archive clock and provenance checks, the trailing contiguous window
selection, the explicit COMPLETE / EXCLUDED result semantics, the output
type and finite-value validation, and the deterministic result models. It
builds on [ADR 0002](../adr/0002-deterministic-dataset-builder-boundary.md)
(decisions 3, 4, and 8) and the
[transform implementation registry](transform_implementation_registry.md)
(PR-2), and hands off Label execution and Dataset orchestration to later
PRs.

## 1. Status and scope

- **Implemented:** eight built-in basic OHLCV Feature registrations and
  implementations; the frozen `FeatureTransformInput` invocation contract;
  the immutable built-in Feature registry; PIT-to-Canonical row binding;
  market-clock / archive-clock and provenance validation; trailing-window
  and interval-contiguity validation; explicit COMPLETE / EXCLUDED Feature
  results; output type / finite-value validation; deterministic result
  models; offline tests; contract documentation.
- **Not implemented (future PRs):** built-in Label transforms and Label
  execution (PR-4), `label_status`, `actual_label_end_time`, chronological
  split invocation, Dataset orchestration (PR-5), Dataset identity
  finalization, Dataset Parquet and materialization (PR-6), the verified
  Dataset reader (PR-7), and the Dataset CLI (PR-8).
- **Version:** the package version remains `0.4.0` (no pyproject.toml,
  dependency, or version change).

## 2. Relationship to ADR 0002 and the PR-2 registry

ADR 0002 decision 3 requires that v0.5 executes only built-in, registered,
versioned transforms and that `transform_ref` resolves only against the
registry. PR-2 implemented the frozen registration models, the exact-key
registry, the compatibility preflight, and the versioned implementation
fingerprints. PR-3 adds the **implementations** (in dedicated per-transform
modules so one transform's source change only churns that transform's pin),
the **fixed built-in registration set**, and the **executor** that is the
first and only place any registered implementation is ever called. The
executor resolves every FeatureSpec against
`built_in_feature_registry()`; no external registration can be injected,
and no low-level invocation entry point is exported.

## 3. Public API

Public constants:

- `FEATURE_EXECUTION_CONTRACT_VERSION = "market-vault-feature-execution-v1"`
- `FEATURE_TRANSFORM_CALL_CONTRACT_VERSION =
  "market-vault-feature-transform-call-v1"`
- `FEATURE_VALUE_STATUS_COMPLETE = "COMPLETE"` /
  `FEATURE_VALUE_STATUS_EXCLUDED = "EXCLUDED"`
- `FEATURE_EXCLUSION_INSUFFICIENT_ROWS`,
  `FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS`,
  `FEATURE_EXCLUSION_CROSS_MARKET_DATE`

Public types and functions:

| API | Behavior |
| --- | --- |
| `FeatureExecutionError` | Unified fail-closed error (subclass of `DatasetError`). |
| `FeatureTransformInput` | Frozen invocation input: `field_names`, `rows`, `parameters`. |
| `FeatureValueResult` | One Feature value result of one sample. |
| `FeatureSampleResult` | One sample's complete Feature execution result. |
| `FeatureExecutionDiagnostics` | Deterministic execution-level counts. |
| `FeatureExecutionResult` | Deterministic output of one execution. |
| `built_in_feature_registrations()` | The fixed tuple of built-in registrations, sorted by `transform_ref`. |
| `built_in_feature_registry()` | A fresh immutable `TransformRegistry` over the built-in registrations. |
| `execute_builtin_features(builds, pit_result, feature_specs)` | The single execution entry point. |

Internal row-reconciliation and window-selection helpers, the
output-validation helper, and any lower-level invocation function are not
exported; there is no public way to call a transform outside the executor
or to inject a custom registry. The PR-2 registry constants
(`TRANSFORM_REGISTRY_CONTRACT_VERSION`,
`TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION`) and the fingerprint
algorithm are unchanged.

## 4. Built-in catalog

Exactly eight basic OHLCV Feature transforms are registered:

1. `simple_return`
2. `log_return`
3. `rolling_mean`
4. `rolling_std`
5. `rolling_volume_mean`
6. `volume_ratio`
7. `candle_range`
8. `candle_body`

Deliberately **not** implemented in this PR (candidates for later review,
never aliases): `time_of_day`, `session`, EMA, RSI, MACD, KDJ, OBV,
Bollinger Bands, candlestick patterns, and any bullish / bearish or
buy/sell signal output.

## 5. Transform refs

All `transform_ref` values are the complete stable v1 references
(`module.path:function`); there is no short-name alias:

```text
market_vault.dataset.feature_transforms.simple_return:simple_return
market_vault.dataset.feature_transforms.log_return:log_return
market_vault.dataset.feature_transforms.rolling_mean:rolling_mean
market_vault.dataset.feature_transforms.rolling_std:rolling_std
market_vault.dataset.feature_transforms.rolling_volume_mean:rolling_volume_mean
market_vault.dataset.feature_transforms.volume_ratio:volume_ratio
market_vault.dataset.feature_transforms.candle_range:candle_range
market_vault.dataset.feature_transforms.candle_body:candle_body
```

Each implementation lives in its own module: the PR-2 implementation
fingerprint hashes the complete module source, so a change to one transform
only churns that transform's pin.

## 6. Invocation contract

The built-in callable signature is fixed by v1:

```python
def <transform_name>(input_: FeatureTransformInput) -> float
```

- a plain module-level function (no lambda, no closure, no bound method);
- exactly one positional parameter with no default value;
- no `*args`, no `**kwargs`;
- non-async, non-generator;
- never modifies its input;
- returns exactly one scalar `float` (never a Series, DataFrame, dict,
  list, or tuple);
- reads no global mutable state, file path, network, current time, or
  environment.

The executor validates the callable signature before any invocation
(statelessly, per execution) and fails closed on violation. Any future
incompatible change to this signature contract must bump
`FEATURE_TRANSFORM_CALL_CONTRACT_VERSION` and the affected
`implementation_version` values.

## 7. `FeatureTransformInput`

Frozen and tuple-only, validated at construction:

- `field_names` — must equal the registration's `input_canonical_fields`
  exactly, including order (the executor guarantees this);
- `rows` — the trailing contiguous rows the executor actually selected, in
  ascending `event_time` order; every value is a real finite `float`
  (`bool` and `int` are never numeric; `-0.0` normalizes to `0.0`);
- `parameters` — the spec's own validated `SpecParameter` values in stable
  name order (no implicit defaults; unsorted input fails closed).

The transform never sees Label rows, undeclared Canonical fields, file
paths, the network, the current time, or any global environment. The
executor passes exactly the rows the transform must consume — never more,
never fewer.

## 8. Parameter semantics

Windowed Features use one uniform parameter:

- `window_bars` — the **total number of trailing contiguous bars the
  transform actually consumes**, not an extra lookahead offset. The
  registration's PARAMETER lookback value therefore equals the consumed row
  count exactly; there is no hidden `+1` rule.

Lower bounds (enforced by the registration parameter contract and the
registry window preflight): `simple_return` 2, `log_return` 2,
`rolling_mean` 1, `rolling_std` 2, `rolling_volume_mean` 1, `volume_ratio`
2. `candle_range` and `candle_body` take no parameters and use a FIXED
1-bar lookback. There is no implicit default: every FeatureSpec carries its
parameters explicitly, and the spec parameter set must match the
registration schema exactly (PR-2 preflight).

## 9. Exact formulas

The executor passes the consumed rows in ascending `event_time` order;
`window_bars` is the parameter value.

1. **simple_return** — close-to-close return over the trailing window:
   `last_close / first_close - 1.0`. `first_close != 0` is required;
   `window_bars == 2` is an ordinary one-bar-interval return.
2. **log_return** — `math.log(last_close / first_close)`. Requires
   `first_close > 0`, `last_close > 0`, a finite positive ratio, and a
   finite result.
3. **rolling_mean** — arithmetic mean of the trailing `window_bars` closes:
   `math.fsum(close_values) / window_bars`.
4. **rolling_std** — population standard deviation (`ddof = 0`) of the
   trailing closes:
   `mean = math.fsum(values) / n`;
   `variance = math.fsum((x - mean) ** 2 for x in values) / n`;
   `result = math.sqrt(variance)`. Never pandas' default `std` and never
   the sample `ddof = 1` formula.
5. **rolling_volume_mean** — arithmetic mean of the trailing `window_bars`
   volumes: `math.fsum(volume_values) / window_bars`.
6. **volume_ratio** — the last bar's volume divided by the mean volume of
   the preceding `window_bars - 1` bars:
   `previous_mean = math.fsum(previous_volumes) / (window_bars - 1)`;
   `result = current_volume / previous_mean`. The current bar never enters
   `previous_mean`; `previous_mean > 0` is required.
7. **candle_range** — `high - low` of the single current bar; `high >= low`
   is required.
8. **candle_body** — signed `close - open` of the single current bar; the
   sign is preserved.

All float outputs are real `float`, finite, with `-0.0` normalized to
`0.0`. Nothing is rounded and nothing is formatted into a percent string.

## 10. Registration metadata

Every built-in registration carries fixed shared metadata:

- `kind = FEATURE`; `implementation_version = "v1"`;
- `supported_canonical_schema_versions` contains exactly the current
  authoritative `CANONICAL_SCHEMA_VERSION`
  (`market-bars-canonical-schema-v1`); no wildcard or version placeholder
  is ever used;
- `supported_source_schema_versions` contains exactly the codebase's
  current authoritative source schema version (`10.9`, the `Settings`
  default);
- `output_logical_type = "float64"`, `output_nullable = false`;
- `lookforward = NONE`;
- `boundary_policy = SAME_MARKET_CALENDAR_DATE`;
- `missing_policy = EXCLUDE_SAMPLE`;
- a stable English `display_name` (descriptive only, never identity);
- the PR-2 versioned implementation fingerprint is computed at construction
  and maps to the existing `ImplementationPin` via
  `transform_implementation_pin`.

Input field contracts:

| transform | fields | lookback |
| --- | --- | --- |
| simple_return | `close` | PARAMETER `window_bars` INCLUSIVE |
| log_return | `close` | PARAMETER `window_bars` INCLUSIVE |
| rolling_mean | `close` | PARAMETER `window_bars` INCLUSIVE |
| rolling_std | `close` | PARAMETER `window_bars` INCLUSIVE |
| rolling_volume_mean | `volume` | PARAMETER `window_bars` INCLUSIVE |
| volume_ratio | `volume` | PARAMETER `window_bars` INCLUSIVE |
| candle_range | `high`, `low` | FIXED 1 BARS INCLUSIVE |
| candle_body | `open`, `close` | FIXED 1 BARS INCLUSIVE |

## 11. Source / canonical schema support

A consumed row's `source_schema_version` must be declared by the
FeatureSpec's `requirements.source_schema_versions`, and every build that
carries the row must have its `canonical_schema_version` declared by the
spec's `requirements.canonical_schema_versions`. The spec requirements must
also pass the PR-2 registry preflight against the registration's supported
versions (the spec may require fewer versions than the registration
supports; it is never modified to match). Violations fail closed.

## 12. PIT row binding

The executor builds a read-only mapping from
`canonical_row_version_id` to its reconciled `CanonicalBar` over the
supplied verified builds, reusing the PIT reconciliation comparison
semantics (no second winner-selection algorithm):

- every bar must be covered by its build's declared row-version set, and
  every declared version must have a bar;
- one version id must never map to different bar content — identical rows
  across builds deduplicate deterministically, conflicting rows fail
  closed (the "newest build", mtime, and input order never pick a winner);
- every row version id referenced by a PIT sample's feature row list must
  resolve;
- Label row version ids never enter Feature input;
- bars not selected by the PIT feature association never enter Feature
  input;
- `CanonicalBar` objects are never modified;
- the PIT result's `CanonicalBuildPin`s must correspond exactly to the
  supplied builds (identical ids, identical identity fields, pin row
  versions covered by the build's provenance).

## 13. Market and archive clocks

For every Feature row of every sample, the executor re-verifies
(defensively; the PIT assembler already performed the legal selection):

- `bar.code`, `interval`, `adjustment`, and `requested_session` equal the
  sample request's values;
- `feature_window_start <= event_time < feature_window_close`;
- `market_available_at <= feature_window_close` (equal is allowed);
- when the sample's `dataset_as_of` is set:
  `archive_available_at <= dataset_as_of` (equal is allowed).

Any clock violation raises `FeatureExecutionError` — it is never treated
as an ordinary warm-up EXCLUDED, and a future row is never silently
dropped so computation can continue.

## 14. Required trailing rows

For each sample and spec:

1. take the PIT-selected Feature rows in their deterministic
   position/`event_time` order (strictly ascending; duplicate or inverted
   `event_time` is a provenance inconsistency and fails closed);
2. resolve the registration's lookback to the required row count
   (PARAMETER → the spec's `window_bars` value; FIXED → the fixed value;
   NONE → one row);
3. take the last `required_row_count` rows only — extra older PIT Feature
   rows never enter the transform but remain in PIT provenance;
4. when fewer rows are available, apply the missing policy (section 17);
5. verify contiguity and the market-calendar-date boundary (sections 15
   and 16);
6. construct the `FeatureTransformInput` and invoke the built-in transform
   exactly once.

A missing middle bar is never patched with an older extra bar; nothing is
interpolated and nothing is forward-filled.

## 15. Interval contiguity

Adjacent consumed rows must differ in `event_time` by exactly the nominal
interval of the sample request (parsed with the existing
`parse_intraday_interval`; 1m / 5m / 15m / 30m / 60m). A duplicate
`event_time` or a non-ascending order fails closed; a missing middle bar
within the required window is a non-contiguous window (section 17).

## 16. Market-calendar-date boundary

Every consumed row's `market_calendar_date` must equal
`sample.request.anchor_market_calendar_date`: the required window never
crosses a market-calendar date, per the `SAME_MARKET_CALENDAR_DATE`
boundary policy. Violation is a cross-market-date exclusion (section 17),
never a silent re-window.

## 17. Missing / exclusion policy

Fixed statuses:

```text
FEATURE_VALUE_STATUS_COMPLETE = "COMPLETE"
FEATURE_VALUE_STATUS_EXCLUDED = "EXCLUDED"
```

Fixed reason codes:

```text
FEATURE_EXCLUSION_INSUFFICIENT_ROWS
FEATURE_EXCLUSION_NON_CONTIGUOUS_ROWS
FEATURE_EXCLUSION_CROSS_MARKET_DATE
```

Semantics per registration `missing_policy`:

- `EXCLUDE_SAMPLE` → an explicit `EXCLUDED` result with `value = None` and
  the matching fixed reason code; the transform is **not** invoked;
- `FAIL` → `FeatureExecutionError` (no registration in this PR uses FAIL;
  all eight use EXCLUDE_SAMPLE).

`EXCLUDED` is not a null Feature value; it is an explicit designed outcome
recorded in the result. Whether and how the final Dataset builder excludes
whole samples is decided by PR-5; this PR only records the explicit result
and never fabricates data. Exclusion provenance: `INSUFFICIENT_ROWS`
records an empty consumed set; `NON_CONTIGUOUS_ROWS` and
`CROSS_MARKET_DATE` record the actually usable trailing subset.

## 18. Arithmetic and domain failures

The following always fail closed as `FeatureExecutionError` and are never
EXCLUDED:

- division by zero (`simple_return` zero first close, `volume_ratio` zero
  or negative previous mean);
- non-positive `log_return` inputs or ratio;
- `candle_range` with `high < low`;
- NaN / ±Infinity anywhere (input or output);
- output type drift (int, bool, string, None, containers);
- transform implementation exceptions;
- clock violations, provenance mismatches, spec/registration mismatches,
  row conflicts, and illegal Canonical values.

There is no "warn and continue" path, no retry, and no partial "successful"
result. Arithmetic failures are never downgraded to ordinary warm-up
exclusions.

## 19. Output type and finite-value validation

The executor validates every transform result against the spec output and
the registration contract before recording it:

- `type(value) is float` exactly — `bool` / `int` never masquerade as
  float64, and nothing is auto-converted to hide implementation drift;
- finite — NaN, +Inf, and -Inf fail the build;
- `-0.0` normalizes to `0.0`;
- `spec.output.logical_type == registration.output_logical_type ==
  "float64"` and `spec.output.nullable == registration.output_nullable ==
  false`.

Built-in implementations themselves return explicit `float`; `float(...)`
is never applied to arbitrary objects.

## 20. Result models

All result models are frozen and validated at construction
(`FeatureExecutionError` on any inconsistency):

- `FeatureValueResult` — `feature_name`, `spec_pin` (must carry the spec
  name), `implementation_pin`, `status`, `value`, `reason_code`,
  `consumed_canonical_row_version_ids`. COMPLETE requires a finite float
  value, a null reason code, and a non-empty consumed set; EXCLUDED
  requires a null value and one of the fixed reason codes.
- `FeatureSampleResult` — `sample_key`, `sample_version_id`, `code`,
  `feature_window_close` (normalized UTC microseconds), `values`, `status`.
  The sample status is COMPLETE when every Feature value is COMPLETE and
  EXCLUDED when any value is EXCLUDED (recomputed at construction);
  feature names within a sample are unique; values follow the stable spec
  execution order.
- `FeatureExecutionDiagnostics` — `sample_count`, `feature_spec_count`,
  `complete_sample_count`, `excluded_sample_count`, `complete_value_count`,
  `excluded_value_count`, `transform_invocation_count` (exactly one
  invocation per COMPLETE value, zero for EXCLUDED).
- `FeatureExecutionResult` — `samples` (sorted by `sample_key`),
  `feature_spec_pins`, `implementation_pins` (sorted, deduplicated),
  `diagnostics` (must equal the recomputed counts), and
  `execution_contract_version` (must be
  `FEATURE_EXECUTION_CONTRACT_VERSION`).

Results carry no absolute file paths, no `built_at`, no new `dataset_id`,
and no new execution identity hash. Every COMPLETE value records the exact
consumed canonical row-version IDs for traceability.

## 21. Determinism

The following never change the result: builds input order, FeatureSpecs
input order, PIT sample order (already normalized), Python dict insertion
order, local timezone, checkout path, filesystem mtimes, and the current
time. The following necessarily change the relevant pin or result:
implementation source, implementation version, FeatureSpec semantic
content, `window_bars`, Canonical row values, PIT `sample_version_id`, and
`dataset_as_of`-visible row changes. This PR defines no new
`FeatureExecutionResult` identity hash.

## 22. Security: no arbitrary code

- The executor resolves every spec only against `built_in_feature_registry`
  and invokes only those function objects; there is no registry parameter,
  no `replace`, no external registration injection, and no low-level public
  invocation function.
- No `importlib` dynamic imports, no YAML-path module loading, no `eval`,
  no `exec`, no package / entry-point / filesystem scanning, and no network
  or OpenD access.
- An unknown `transform_ref` fails closed as `FeatureExecutionError`.

## 23. Error behavior

Every failure surfaces as `FeatureExecutionError` (a `DatasetError`
subclass); no bare `KeyError`, `TypeError`, `ValueError`,
`ArithmeticError`, `OverflowError`, or transform implementation exception
leaks. Transform failure messages include the `transform_ref`, the spec
name, and the sample key — never memory addresses or unstable `repr`s.
Nothing is swallowed, nothing is retried, and no warning ever precedes a
seemingly valid result.

## 24. Explicit non-goals

This PR does **not** compute Labels, execute Label transforms, produce
`label_status` or `actual_label_end_time`, allocate splits, build a
Dataset, write Dataset Parquet, create a `dataset_id`, add a CLI, or access
the network. No existing identity algorithm or version constant is
modified (including the PR-2 registry and fingerprint versions, the PIT
identities, the Canonical identities, the FeatureSpec semantic hash, and
the chronological split identities), and no dependency or package-version
change is made.

## 25. PR-4 / PR-5 handoff

- **PR-4** — built-in Label transforms and Label execution: real
  `label_status` / `actual_label_end_time`, completeness proofs, and
  no-cross-trading-day enforcement. The Label path must keep its own
  registrations and invocation rules; this PR's Feature machinery must not
  be reused to fake Label completeness.
- **PR-5** — Dataset orchestration: how COMPLETE / EXCLUDED Feature
  results, `dataset_as_of`, and pins flow into `DatasetIdentityInput`, and
  how whole-sample exclusion is applied. Until then, EXCLUDED Feature
  results are recorded explicitly and never silently enter a final Dataset
  row.
