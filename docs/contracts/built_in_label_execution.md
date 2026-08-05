# Built-in Label Execution Contract

Status: implemented in the v0.5.0 PR-4 dataset layer
(`market_vault.dataset.label_models`,
`market_vault.dataset.label_registry`,
`market_vault.dataset.label_execution`, and
`market_vault.dataset.label_transforms`).

This contract defines the deterministic execution of the built-in Label
catalog over PIT-selected future Canonical rows: the frozen invocation
input, the exact Feature-close anchor binding, the horizon-target and
observation-window alignment, the market / archive clock and provenance
checks, the explicit COMPLETE / INCOMPLETE result semantics with fixed
reason codes, `actual_label_end_time` from the last actually consumed row,
the output type and finite-value validation, and the deterministic result
models. It builds on [ADR 0002](../adr/0002-deterministic-dataset-builder-boundary.md)
(decisions 3, 4, 5, and 8), the
[transform implementation registry](transform_implementation_registry.md)
(PR-2), the [PIT sample assembly](point_in_time_sample_assembly.md)
foundation, and the [built-in Feature execution](built_in_feature_execution.md)
contract (PR-3), and hands off Dataset orchestration to later PRs.

## 1. Status and scope

- **Implemented:** four built-in Label registrations and implementations;
  the frozen `LabelTransformInput` invocation contract; the immutable
  built-in Label registry; the exact Feature-close anchor binding; exact
  horizon-target and observation-window alignment; PIT-to-Canonical row
  binding; market-clock / archive-clock and provenance validation; explicit
  COMPLETE / INCOMPLETE Label results with fixed reason codes;
  `actual_label_end_time`; output type / finite-value validation;
  deterministic result models; offline tests; contract documentation.
- **Not implemented (future PRs):** chronological split invocation,
  Dataset orchestration (PR-5), Dataset identity finalization, Dataset
  Parquet and materialization (PR-6), the verified Dataset reader (PR-7),
  and the Dataset CLI (PR-8).
- **Version:** the package version remains `0.4.0` (no pyproject.toml,
  dependency, or version change).

## 2. Relationship to ADR 0002, the PIT contract, the PR-2 registry, and Feature execution

ADR 0002 decision 5 requires that labels read real future rows after the
feature window close, subject to the `LabelSpec` horizon, the default
no-cross-trading-day policy, and `adjustment = NONE`; that missing required
actual inputs produce `label_status: INCOMPLETE`; that
`actual_label_end_time` is the market availability instant of the last
actual label input row (never the nominal horizon close); and that
completeness is proved from the actual label input rows, never inferred
from the absence of gap records. PR-2 provided the frozen registration
models and the exact-key registry (including the v0.5 boundary gates for
TRADING_DAYS horizons and cross-trading-day opt-ins); PR-3 provided the
Feature executor and the shared PIT-to-Canonical binding machinery. PR-4
adds the **Label implementations** (in dedicated per-transform modules), the
**fixed built-in Label registration set**, and the **Label executor** that
is the first and only place any registered Label implementation is ever
called.

The Label executor resolves every LabelSpec against
`built_in_label_registry()`; no external registration can be injected, and
no low-level Label invocation entry point is exported. The PIT-to-Canonical
row reconciliation and the exact bidirectional Pin verification shared with
the Feature executor live in the private
`market_vault.dataset.execution_provenance` module (extracted from the
Feature executor in this PR without changing any Feature behavior); the
Label executor reuses that exact machinery, so the two executors cannot
drift into two subtly different provenance implementations.

## 3. Public API

Public constants:

- `LABEL_EXECUTION_CONTRACT_VERSION = "market-vault-label-execution-v1"`
- `LABEL_TRANSFORM_CALL_CONTRACT_VERSION =
  "market-vault-label-transform-call-v1"`
- `LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED = "FEATURE_CLOSE_ALIGNED"`
- `LABEL_INCOMPLETE_MISSING_ANCHOR_ROW = "MISSING_ANCHOR_ROW"`
- `LABEL_INCOMPLETE_MISSING_TARGET_ROW = "MISSING_TARGET_ROW"`
- `LABEL_INCOMPLETE_INSUFFICIENT_ROWS = "INSUFFICIENT_ROWS"`
- `LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS = "NON_CONTIGUOUS_ROWS"`
- `LABEL_STATUS_COMPLETE` / `LABEL_STATUS_INCOMPLETE` (reused from the
  existing split layer; no second status vocabulary)

Public types and functions:

| API | Behavior |
| --- | --- |
| `LabelExecutionError` | Unified fail-closed error (subclass of `DatasetError`). |
| `LabelTransformInput` | Frozen invocation input: `field_names`, `anchor_row`, `rows`, `parameters`, `alignment_rule`. |
| `LabelValueResult` | One Label value result of one sample. |
| `LabelSampleResult` | One sample's complete Label execution result. |
| `LabelExecutionDiagnostics` | Deterministic execution-level counts. |
| `LabelExecutionResult` | Deterministic output of one execution. |
| `built_in_label_registrations()` | The fixed tuple of built-in registrations, sorted by `transform_ref`. |
| `built_in_label_registry()` | A fresh immutable `TransformRegistry` over the built-in registrations. |
| `execute_builtin_labels(builds, pit_result, label_specs)` | The single execution entry point. |

Internal row-reconciliation, anchor/window selection, and output-validation
helpers and the private `execution_provenance` module are not exported; the
executor has no registry parameter, there is no public way to call a Label
transform outside the executor or to inject a custom registry. The PR-2
registry constants and the fingerprint algorithm are unchanged.

## 4. Built-in catalog

Exactly four built-in Label transforms are registered:

1. `forward_return`
2. `forward_direction`
3. `maximum_favorable_excursion`
4. `maximum_adverse_excursion`

Deliberately **not** implemented in this PR (never aliases): any
MINUTES-unit or TRADING_DAYS-unit label execution, cross-trading-day
execution, volatility-target / trailing-stop labels, and any bullish /
bearish or buy/sell signal output.

## 5. Transform refs

All `transform_ref` values are the complete stable v1 references
(`module.path:function`); there is no short-name alias:

```text
market_vault.dataset.label_transforms.forward_return:forward_return
market_vault.dataset.label_transforms.forward_direction:forward_direction
market_vault.dataset.label_transforms.maximum_favorable_excursion:maximum_favorable_excursion
market_vault.dataset.label_transforms.maximum_adverse_excursion:maximum_adverse_excursion
```

Each implementation lives in its own module: the PR-2 implementation
fingerprint hashes the complete module source, so a change to one transform
only churns that transform's pin.

## 6. BARS-only scope

This PR executes **BARS** horizons and observation windows only:

- a LabelSpec with `horizon.unit == BARS` and
  `observation_window.unit == BARS` resolves and executes;
- a LabelSpec with `horizon.unit == MINUTES` fails closed at registry
  preflight, because every built-in registration declares a BARS
  lookforward requirement and the PR-2 window-requirement unit match fails
  (no registry contract was modified to support multiple units);
- a LabelSpec with `horizon.unit == TRADING_DAYS` (which requires the
  explicit cross-trading-day opt-in) fails closed at registry preflight;
- a LabelSpec with `cross_trading_day.allow == true` fails closed at
  registry preflight even with a BARS horizon.

The LabelSpec model continues to express the full v1 schema; units without
a matching built-in registration fail closed at resolve time.

## 7. Unsupported MINUTES / TRADING_DAYS

MINUTES and TRADING_DAYS label execution are explicitly not implemented in
v0.5. A spec using them fails closed as `LabelExecutionError` (with the
underlying `TransformRegistryError` preserved in `__cause__`) before any
sample is processed — never a warning, never a partial result, never a
silently completed label.

## 8. Alignment rule

The only alignment rule this PR executes is
`LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED = "FEATURE_CLOSE_ALIGNED"`. Any
other `alignment_rule` value on a LabelSpec fails closed as a
configuration-contract error (not INCOMPLETE).

## 9. Anchor row semantics

- The Feature baseline is the bar that completed exactly at
  `feature_window_close`: its `event_time` must be exactly
  `feature_window_close - nominal_interval`.
- The anchor's `market_available_at` must be `<= feature_window_close`
  (equal is allowed).
- The anchor must come from `sample.feature_canonical_row_version_ids`
  (the PIT Feature row list), never from the Label rows and never from an
  unselected Canonical row.
- The anchor must satisfy code / interval / adjustment / requested_session
  match, `market_calendar_date == anchor_market_calendar_date`,
  `event_time` inside the Feature window, `market_available_at <=
  feature_window_close`, `archive_available_at <= dataset_as_of` when
  `dataset_as_of` is set, and the spec's source/canonical schema
  requirements.
- Feature rows must be strictly ascending in `event_time`; duplicates and
  inversions are provenance inconsistencies and fail closed.
- When the exact anchor does not exist the label is INCOMPLETE
  (`MISSING_ANCHOR_ROW`) and the transform is never invoked; an older
  Feature row never substitutes for the anchor.

## 10. 0-based observation offsets

BARS observation-window offsets use 0-based future-bar event positions:

- offset 0 = the first future bar, `event_time == feature_window_close`;
- offset 1 = the second future bar, `event_time == feature_window_close +
  nominal_interval`;
- and so on.

## 11. Horizon target event_time

For `horizon.value = H` the nominal target row position is H, and its exact
event time is

```text
feature_window_close + (H - 1) * nominal_interval
```

The Label rows are read from `sample.label_canonical_row_version_ids` only,
and only exact event-time matches count.

## 12. PIT label-window coverage

When `label_specs` is non-empty, every PIT sample request must carry a
complete Label window:

- `label_window_start` and `label_window_close` are both non-null;
- `label_window_start == feature_window_close`;
- for every LabelSpec,
  `label_window_close >= feature_window_close + horizon.value * nominal_interval`.

A wider PIT Label window can serve multiple LabelSpecs of different
horizons; the executor consumes only each spec's own required rows and
never passes farther rows to a transform. A missing or insufficient Label
window is a builder/request configuration error: it raises
`LabelExecutionError` and is never recorded as ordinary INCOMPLETE data.

## 13. Exact formulas

With `anchor_close` = the Feature anchor row's close and future rows in
ascending `event_time` order:

1. **forward_return** — inputs `("close",)`:
   `target_close / anchor_close - 1.0`. Requires `anchor_close > 0`,
   `target_close > 0`, a finite ratio, and a real finite float result.
2. **forward_direction** — inputs `("close",)`:
   `target_close > anchor_close -> 1`; `== -> 0`; `< -> -1`. Requires
   `anchor_close > 0`, `target_close > 0`; the output is a real `int`
   (bool never passes) with logical type int64, and the executor verifies
   the value is one of `-1`, `0`, `1`.
3. **maximum_favorable_excursion** — inputs `("close", "high")`:
   `max(0.0, max(row_high / anchor_close - 1.0 for row in future_rows))`.
   Long-direction favorable excursion anchored at the Feature-close price;
   the output is always `>= 0.0` and is never a bullish/bearish or
   buy/sell signal. Requires `anchor_close > 0`, every `high > 0`, finite
   ratios, and a real finite float result.
4. **maximum_adverse_excursion** — inputs `("close", "low")`:
   `min(0.0, min(row_low / anchor_close - 1.0 for row in future_rows))`.
   Signed long-direction adverse excursion; the output is always `<= 0.0`,
   never converted to an absolute value, and never a trading
   recommendation. Requires `anchor_close > 0`, every `low > 0`, finite
   ratios, and a real finite float result.

Nothing is rounded, nothing is formatted into a percent string, nothing is
auto-converted from an arbitrary object, and every arithmetic / domain
failure fails closed.

## 14. Registration metadata

Every built-in Label registration carries fixed shared metadata:

- `kind = LABEL`; `implementation_version = "v1"`;
- `supported_canonical_schema_versions` contains exactly the current
  authoritative `CANONICAL_SCHEMA_VERSION`
  (`market-bars-canonical-schema-v1`); no wildcard or version placeholder
  is ever used;
- `supported_source_schema_versions` contains exactly the codebase's
  current authoritative source schema version (`10.9`, the `Settings`
  default);
- `output_nullable = false`; no parameters are declared;
- `lookback = FIXED 1 BARS INCLUSIVE` (the exact Feature-close anchor row);
- `boundary_policy = NO_CROSS_TRADING_DAY`;
- `missing_policy = LABEL_INCOMPLETE`;
- `lookforward` derives from the LabelSpec: `LABEL_HORIZON / BARS /
  INCLUSIVE` for `forward_return` and `forward_direction`,
  `LABEL_OBSERVATION_WINDOW / BARS / INCLUSIVE` for
  `maximum_favorable_excursion` and `maximum_adverse_excursion`;
- a stable English `display_name` (descriptive only, never identity);
- the PR-2 versioned implementation fingerprint is computed at construction
  and maps to the existing `ImplementationPin` via
  `transform_implementation_pin`.

Input field contracts and output types:

| transform | fields | output | lookforward |
| --- | --- | --- | --- |
| forward_return | `close` | float64 | LABEL_HORIZON BARS INCLUSIVE |
| forward_direction | `close` | int64 | LABEL_HORIZON BARS INCLUSIVE |
| maximum_favorable_excursion | `close`, `high` | float64 | LABEL_OBSERVATION_WINDOW BARS INCLUSIVE |
| maximum_adverse_excursion | `close`, `low` | float64 | LABEL_OBSERVATION_WINDOW BARS INCLUSIVE |

`TransformRegistration` itself is unchanged (PR-2 model).

## 15. Invocation contract

The built-in callable signature is fixed by v1:

```python
def <transform_name>(input_: LabelTransformInput) -> float | int
```

- a plain module-level function (no lambda, no closure, no bound method);
- exactly one positional parameter with no default value;
- no `*args`, no `**kwargs`;
- non-async, non-generator;
- never modifies its input;
- returns exactly one scalar `float` or `int`;
- reads no global mutable state, file path, network, current time, or
  environment.

The executor validates the callable signature before any invocation and
fails closed on violation. Any future incompatible change to this signature
contract must bump `LABEL_TRANSFORM_CALL_CONTRACT_VERSION` and the affected
`implementation_version` values.

## 16. `LabelTransformInput`

Frozen and tuple-only, validated at construction:

- `field_names` — must equal the registration's `input_canonical_fields`
  exactly, including order (the executor guarantees this);
- `anchor_row` — the exact Feature-close anchor bar's values in that order
  (exactly `len(field_names)` real finite floats);
- `rows` — the future Label rows the executor proved satisfy the
  LabelSpec's required-input semantics, in ascending `event_time` order,
  each with exactly `len(field_names)` real finite floats; never more,
  never fewer;
- `parameters` — the spec's own validated `SpecParameter` values in stable
  name order (empty for this catalog);
- `alignment_rule` — must be `LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED`.

Every market value must be a real `float` (bool and int are never numeric;
`-0.0` normalizes to `0.0`); NaN and ±Infinity are rejected. The input
carries no paths, no time functions, no environment, no `LabelSpec`
objects, and no `CanonicalBar` objects. The transform never sees Feature
rows as future observation rows, undeclared Canonical fields, Label rows
outside the proved set, or any global environment.

## 17. PIT / Canonical provenance

The executor builds a read-only mapping from `canonical_row_version_id`
to its reconciled `CanonicalBar` over the supplied verified builds using
the same reconciliation and exact bidirectional Pin verification the
Feature executor uses (shared `execution_provenance` module): identical
rows across builds deduplicate deterministically, conflicting rows fail
closed, the union of every sample's Feature and Label row-version ids must
equal `pit_result.canonical_row_version_ids` exactly, and every
`CanonicalBuildPin` must equal the pin exactly reconstructed from the
supplied build and the actually selected rows (identity fields, selected
row-version intersection, and one `SourceSnapshotPin` per selected row).

For Label execution specifically:

- only `sample.label_canonical_row_version_ids` are read as future rows;
  no alternative row is searched for inside the full Canonical builds;
- only `sample.feature_canonical_row_version_ids` provide the anchor;
- Label rows never enter the Feature executor and Feature rows never serve
  as future Label observation rows;
- `CanonicalBar` objects are never modified;
- the PIT result is never modified and PIT selection is never redone;
- `sample_key` / `sample_version_id` are never redefined.

## 18. Market and archive clocks

For every Label row and the anchor row, the executor re-verifies
(defensively; the PIT assembler already performed the legal selection):

- `bar.code`, `interval`, `adjustment`, and `requested_session` equal the
  sample request's values;
- Label rows: `label_window_start <= event_time < label_window_close`;
  anchor: `feature_window_start <= event_time < feature_window_close`;
- `market_available_at <= feature_window_close` (anchor) /
  `<= label_window_close` (Label rows) — equal is allowed;
- when the sample's `dataset_as_of` is set:
  `archive_available_at <= dataset_as_of` (equal is allowed);
- `market_calendar_date == anchor_market_calendar_date` for the anchor and
  every Label row.

Any clock violation raises `LabelExecutionError` — it is never treated as
ordinary INCOMPLETE data, and a future row is never silently dropped so
computation can continue.

## 19. Required input proof

- **forward_return / forward_direction** require exactly the anchor row
  and the exact horizon target row (`event_time == feature_window_close +
  (H - 1) * nominal_interval`). Other intermediate future bars are not
  transform-required inputs; their absence never makes a forward target
  label INCOMPLETE. Target present and aligned proves the required inputs
  complete.
- **maximum_favorable_excursion / maximum_adverse_excursion** require
  every expected future bar from offset 0 to offset `H - 1`, each with its
  exact nominal `event_time`; adjacent expected rows differ by exactly the
  nominal interval by construction (only exact event times are accepted).

PIT known-gap emptiness, a gap sidecar with no records, "there look like
enough rows", a nearby row standing in for the target, or a farther row
replacing a missing one never prove completeness. Only exact required event
times make a label COMPLETE.

## 20. COMPLETE / INCOMPLETE

- `LABEL_STATUS_COMPLETE` is declared only when the anchor row exists and
  every required future row of the spec exists at its exact event time.
- `LABEL_STATUS_INCOMPLETE` is declared in exactly the four designed cases
  of section 21; the transform is never invoked for an INCOMPLETE label.
- An INCOMPLETE label is an explicit designed outcome recorded in the
  result; nothing is fabricated, filled, or patched, and a non-null
  `actual_label_end_time` on an INCOMPLETE value never upgrades it.

## 21. Reason codes

Fixed reason codes (no free text):

```text
LABEL_INCOMPLETE_MISSING_ANCHOR_ROW    = "MISSING_ANCHOR_ROW"
LABEL_INCOMPLETE_MISSING_TARGET_ROW    = "MISSING_TARGET_ROW"
LABEL_INCOMPLETE_INSUFFICIENT_ROWS     = "INSUFFICIENT_ROWS"
LABEL_INCOMPLETE_NON_CONTIGUOUS_ROWS   = "NON_CONTIGUOUS_ROWS"
```

- `MISSING_ANCHOR_ROW` — the exact Feature-close anchor does not exist in
  the PIT Feature rows; no future row is consumed.
- `MISSING_TARGET_ROW` — the exact horizon target row does not exist in
  the PIT Label rows (any transform).
- `INSUFFICIENT_ROWS` — an excursion window whose first boundary row
  (offset 0) is missing while the target exists.
- `NON_CONTIGUOUS_ROWS` — an excursion window with a missing interior row
  (offset 1..H-2) while the target exists.

## 22. Forward target completeness

A forward label (`forward_return` / `forward_direction`) with the exact
target present is COMPLETE even when intermediate future bars are missing:
those bars are not required inputs, and their absence must not wrongly make
the label INCOMPLETE. The executor passes exactly the anchor and the target
row to the transform.

## 23. Excursion contiguity

An excursion label must have every expected row from offset 0 to
`horizon.value - 1`. When the target exists but an interior bar is missing
the reason is `NON_CONTIGUOUS_ROWS`; when the first boundary row is missing
the reason is `INSUFFICIENT_ROWS`; when the target itself is missing the
reason is `MISSING_TARGET_ROW` (checked first). The consumed row-version
IDs always record the actually present required rows in expected position
order.

## 24. `actual_label_end_time`

Every `LabelValueResult` carries `actual_label_end_time`:

- it is the **market availability instant** (`market_available_at`) of the
  last actually consumed Label row, normalized to UTC microseconds;
- it is never the nominal horizon, never `label_window_close`, never the
  target `event_time`, and never the current time;
- it must never precede `feature_window_close` (violation fails closed);
- COMPLETE values always carry it; for this PR's four transforms it equals
  the target row's `market_available_at`;
- INCOMPLETE values carry it only when a required subset was actually
  consumed (then it is the subset's last row's availability); it never
  changes the status.

The sample-level `actual_label_end_time` is the max of the non-null value
ends (`None` when every value end is null), recomputed and verified at
construction; a COMPLETE sample must carry a non-null end. PR-5 consumes
the sample status and the sample `actual_label_end_time` to construct
`ChronologicalSplitSample` facts; this PR never calls the split layer.

## 25. Output type and finite-value validation

The executor validates every transform result against the spec output and
the registration contract before recording it:

- float64: `type(value) is float` exactly — bool / int never masquerade as
  float64; NaN, +Inf, and -Inf fail the build; `-0.0` normalizes to `0.0`;
- int64: `type(value) is int` exactly — bool never passes; signed int64
  range `[-2**63, 2**63-1]`; `forward_direction` additionally requires the
  value to be one of `-1`, `0`, `1`;
- `spec.output.logical_type == registration.output_logical_type` and
  `spec.output.nullable == registration.output_nullable == false`.

`float(...)` / `int(...)` are never applied to arbitrary objects, and an
implementation returning the wrong type is never auto-corrected.

## 26. Result models

All result models are frozen and validated at construction
(`LabelExecutionError` on any inconsistency):

- `LabelValueResult` — `label_name`, `spec_pin` (must carry the spec name
  **and** kind LABEL), `implementation_pin` (must carry a non-null content
  hash), `status`, `value`, `reason_code`,
  `anchor_canonical_row_version_id`, `consumed_label_canonical_row_version_ids`
  (unique, order preserved), `actual_label_end_time`. COMPLETE requires a
  real float64/int64 value, a null reason code, a non-null anchor ID, a
  non-empty consumed set, and a non-null end; INCOMPLETE requires a null
  value and one of the fixed reason codes.
- `LabelSampleResult` — `sample_key`, `sample_version_id`, `code`,
  `feature_window_close` (normalized UTC microseconds), `values`, `status`,
  `actual_label_end_time`. Values are strictly ordered by the stable
  SpecPin key with no duplicate SpecPin identities; the sample status is
  COMPLETE only when every value is COMPLETE and INCOMPLETE when any value
  is INCOMPLETE (recomputed at construction); the sample end must equal the
  max of the value ends and must be non-null for a COMPLETE sample; every
  non-null value end must not precede `feature_window_close`.
- `LabelExecutionDiagnostics` — `sample_count`, `label_spec_count`,
  `complete_sample_count`, `incomplete_sample_count`,
  `complete_value_count`, `incomplete_value_count`,
  `transform_invocation_count` (exactly one invocation per COMPLETE value,
  zero for INCOMPLETE). The value-count matrix must hold:
  `complete_value_count + incomplete_value_count == sample_count *
  label_spec_count`, and `transform_invocation_count ==
  complete_value_count`.
- `LabelExecutionResult` — `samples` (sorted by `sample_key`),
  `label_spec_pins` (SpecPins of kind LABEL only, sorted; duplicate
  `(kind, name, version)` identities fail — even with conflicting hashes),
  `implementation_pins`, `diagnostics` (must equal the recomputed counts),
  and `execution_contract_version` (must be
  `LABEL_EXECUTION_CONTRACT_VERSION`). When samples are non-empty,
  complete coverage is verified: every sample carries exactly the result's
  `label_spec_pins` in the same order, one LabelSpec maps to exactly one
  ImplementationPin across all samples, and the pins actually used by the
  values equal the result pins exactly. An empty sample set with a
  non-empty spec set is a documented vacuous execution.

## 27. Shared ImplementationPin

`implementation_pins` is the unique set of implementations actually used,
not one pin per LabelSpec. Multiple LabelSpecs may legally share one
transform implementation (for example `forward_return` at different
horizons), in which case their resolved `ImplementationPin`s are
byte-identical; identical pins deduplicate deterministically (kept exactly
once, sorted by `(name, version, content_sha256)`), while the same
`(name, version)` identity with a different content hash is a conflict and
fails closed. Consequently `len(implementation_pins) <=
len(label_spec_pins)`, and every `LabelValueResult` still carries its own
`implementation_pin`.

## 28. Determinism

The following never change the result: builds input order, LabelSpecs input
order, PIT sample order (already normalized), Python dict insertion order,
local timezone, checkout path, filesystem mtimes, and the current time. The
following necessarily change the relevant pin or result: LabelSpec
semantic content, horizon, observation window, implementation source,
implementation version, anchor Canonical values, future Canonical values,
PIT `sample_version_id`, and `dataset_as_of`-visible row changes. This PR
defines no new `LabelExecutionResult` identity hash.

## 29. Security: no arbitrary code

- The executor resolves every spec only against `built_in_label_registry`
  and invokes only those four function objects; there is no registry
  parameter, no `replace`, no external registration injection, and no
  low-level public invocation function.
- No `importlib` dynamic imports, no YAML-path module loading, no `eval`,
  no `exec`, no package / entry-point / filesystem scanning, and no network
  or OpenD access.
- An unknown `transform_ref` fails closed as `LabelExecutionError`.

## 30. Error behavior

Every public execution failure surfaces as `LabelExecutionError` (a
`DatasetError` subclass); no bare `KeyError`, `TypeError`, `ValueError`,
`ArithmeticError`, `OverflowError`, `TransformRegistryError`, other
`DatasetError`, provenance-helper error, or transform implementation
exception leaks. The `TransformRegistryError` raised by the built-in
registry construction and by spec resolution is wrapped at the public
boundary, and every SpecPin computation is wrapped; the `__cause__` chain
is never swallowed. Transform failure messages include the
`transform_ref`, the spec name, and the sample key — never memory
addresses or unstable `repr`s. Nothing is swallowed, nothing is retried,
and no warning ever precedes a seemingly valid result. Fail closed
everywhere; there is no "warn and continue" path.

## 31. PR-5 handoff

PR-5 consumes, per sample: the sample status (`LABEL_STATUS_COMPLETE` /
`LABEL_STATUS_INCOMPLETE`), the sample `actual_label_end_time`, and the
pins (`label_spec_pins`, `implementation_pins`) to construct the
`ChronologicalSplitSample` facts and `DatasetIdentityInput` entries. Until
PR-5, the Label results are recorded explicitly and never silently enter a
final Dataset row.

## 32. Explicit non-goals

This PR does **not** modify Feature transforms, recompute Feature values,
call `ChronologicalSplitSpec` / `assign_chronological_splits`, assign
TRAIN / VALIDATION / TEST, purge, orchestrate a Dataset build, finalize
`DatasetIdentityInput` / `logical_dataset_content_id` / `dataset_id`, write
Dataset Parquet, materialize a Dataset, add a Dataset reader or CLI, run
ML / training / walk-forward / backtests, or access the network. No
existing identity algorithm or version constant is modified (including the
PR-2 registry and fingerprint versions, the PIT identities, the Canonical
identities, the FeatureSpec/LabelSpec semantic hashes, and the
chronological split identities), no dependency or package-version change is
made, and no tag, Release, or PyPI publication happens.
