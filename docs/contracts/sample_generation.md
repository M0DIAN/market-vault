# Sample Generation Contract

Status: Sample Generation contract foundation and generator core implemented; Sample Generation CLI not implemented
Target release: v0.6.0
Not available in released v0.5.1

This document is the formal v1 contract of the deterministic Sample
Generator planned for v0.6.0. PR-2 (`feat/v0.6.0-sample-generation-contract`)
implements the contract foundation: the strict generation-plan JSON
schema, the frozen typed models, the deterministic normalization, the
canonical generation-plan serialization, the semantic content identity,
the public Python contract entry points, and this document. PR-3
(`feat/v0.6.0-sample-generator-core`) implements the deterministic Sample
Generator core: the verified input chain, the BARS window-coverage
preflight, the contiguous-segment traversal, the stride-based candidate
anchors, the exact request geometry, and the frozen
`SampleGenerationResult`. The Sample Generation CLI (PR-4) is not
implemented. Sample Generation is not implemented in v0.5.1.

## 1. Four version constants

```python
SAMPLE_GENERATION_CONTRACT_VERSION = "market-vault-sample-generation-contract-v1"
SAMPLE_GENERATION_PLAN_SCHEMA_VERSION = "market-vault-sample-generation-plan-v1"
SAMPLE_GENERATION_RULE_SCHEMA_VERSION = "market-vault-sample-generation-rule-v1"
SAMPLE_GENERATION_CONTENT_ID_VERSION = "market-vault-sample-generation-content-v1"
```

- All four are non-empty safe strings, fixed in code, in this document, and
  in the release tests.
- Changing a version changes the contract or identity that references it.
- None of them enters the existing Dataset identity and
  `DATASET_IDENTITY_ENCODING_VERSION` is not modified.

## 2. Exact generation-plan root field set

The root object must contain exactly these fields, no more and no less:

```text
generation_plan_schema_version
canonical_build_dirs
feature_spec_files
label_spec_files
split_spec_file
scope
generation_rule
dataset_as_of
output_root
built_at
output_plan_path
```

Unknown fields and missing fields fail at every level. The contract adds no
`settings`, no `latest`, no OpenD, no network, no current time, no random
seed, no model, no training, no backtest, no Catalog, no arbitrary
transform, and no output-format selector.

## 3. Exact scope field set

```text
symbols
trade_dates
interval
adjustment
requested_session
```

- `symbols`: JSON array of non-empty strings; at least one entry; following
  the existing `DatasetScope` semantics, symbols are stripped,
  NFC-normalized, uppercased, and sorted; duplicates after normalization
  fail closed.
- `trade_dates`: JSON array of strict `YYYY-MM-DD` strings; at least one
  entry; parsed to dates, deduplicated (duplicates fail), and sorted.
- `interval`: string; lowercased by the existing `DatasetScope`.
- `adjustment`: string; uppercased by the existing `DatasetScope`; the v1
  contract accepts only `adjustment == "NONE"`.
- `requested_session`: string; uppercased by the existing `DatasetScope`.
- The scope is constructed into and saved as the formal `DatasetScope`; its
  final normalization is never re-implemented.

## 4. Exact generation_rule field set

```text
rule_schema_version
feature_window_bars
label_window_bars
stride_bars
anchor_source
anchor_rule
cross_day_policy
```

The frozen rule model:

```python
@dataclass(frozen=True)
class SampleGenerationRule:
    rule_schema_version: str
    feature_window_bars: int
    label_window_bars: int
    stride_bars: int
    anchor_source: str
    anchor_rule: str
    cross_day_policy: str
```

Accepted values (v1):

```text
rule_schema_version: market-vault-sample-generation-rule-v1
feature_window_bars: real int > 0
label_window_bars:   real int > 0
stride_bars:         real int > 0
anchor_source:       VERIFIED_CANONICAL_BARS
anchor_rule:         FEATURE_WINDOW_CLOSE
cross_day_policy:    REJECT
```

Bool in place of int, zero, negative values, floats, string integers,
unknown enum values, `null`, and unknown fields are all rejected.

Meaning of the v1 rule:

- only BARS-style windows are supported;
- feature window length, label window length, and stride are all explicit;
- candidate anchors come only from verified Canonical bars loaded by PR-3
  through the formal verified reader;
- no synthetic bars, no interpolation, and no forward-fill;
- no window ever crosses a market-calendar date (`cross_day_policy: REJECT`);
- request generation itself belongs to PR-3; this contract generates no
  request.

PR-3 must additionally verify that Feature spec window requirements are
covered by `feature_window_bars`, that Label specs use only the currently
supported BARS horizon / observation window, that Label requirements are
covered by `label_window_bars`, that `TRADING_DAYS` / `MINUTES` /
cross-day Label windows are unsupported, and that a gap never silently
moves a window boundary. Those PR-3 constraints are fixed by this document
but not implemented by PR-2.

## 5. Per-field types

| field | type |
| --- | --- |
| `generation_plan_schema_version` | string (exactly `market-vault-sample-generation-plan-v1`) |
| `canonical_build_dirs` | JSON array[string], at least 1 |
| `feature_spec_files` | JSON array[string], at least 1 |
| `label_spec_files` | JSON array[string], at least 1 |
| `split_spec_file` | string (exactly one explicit path) |
| `scope` | object (section 3) |
| `generation_rule` | object (section 4) |
| `dataset_as_of` | timezone-aware ISO-8601 string or `null` |
| `output_root` | string |
| `built_at` | timezone-aware ISO-8601 string (required, never `null`) |
| `output_plan_path` | string |

## 6. Null rules

`null` is accepted only for `dataset_as_of`. `null` in every other field
fails closed.

## 7. Numeric ranges

The three window sizes are real positive integers. Bool is never accepted
as int; `0`, negatives, floats, and string integers are rejected.

## 8. Enum values

`anchor_source` accepts exactly `VERIFIED_CANONICAL_BARS`; `anchor_rule`
accepts exactly `FEATURE_WINDOW_CLOSE`; `cross_day_policy` accepts exactly
`REJECT`. Unknown values fail closed; there are no hidden defaults.

## 9. Strict JSON rules

The document must be a single UTF-8 JSON object without BOM. Duplicate JSON
keys at any depth fail; unknown fields fail; missing fields fail; types are
strict (bool never substitutes for int, string never substitutes for
array); the root must be an object; JSON whitespace and key order never
matter and no canonical JSON form is required for parsing. The raw plan
bytes never enter any identity.

## 10. Path string rules

All path inputs (`canonical_build_dirs`, `feature_spec_files`,
`label_spec_files`, `split_spec_file`, `output_root`, `output_plan_path`)
follow the same safety boundaries:

- each entry is an explicit string, NFC-normalized;
- empty strings fail; leading or trailing whitespace fails;
- control characters and reserved encoding separators fail;
- `.` or `..` path components fail;
- `~` is never expanded; environment variables (`$`, `%`) are never
  expanded; glob patterns (`*`, `?`, `[`, `]`) are never expanded;
- `resolve()` is never called and the filesystem is never accessed by the
  contract layer.

The generator requires one or more explicit verified Canonical build directories,
one or more explicit Feature spec file paths, one or more explicit Label spec file paths,
and one explicit split spec file/path.
`canonical_build_dirs`, `feature_spec_files`, and `label_spec_files` are
non-empty arrays with at least one entry each; they mirror the existing
build-plan array capability of `feature_spec_files` and `label_spec_files`
and are never shrunk into single-file inputs. Duplicate entries fail after
normalization. `split_spec_file` is exactly one explicit path. `output_root`
is never created by the contract layer and later flows unchanged into the
ordinary Dataset build plan's `output_root`. `output_plan_path` represents
the future CLI's written ordinary Dataset build-plan file; PR-2 creates no
file.

## 11. UTC microsecond rules

`dataset_as_of` (when not `null`) and `built_at` must be timezone-aware ISO
8601 strings; naive timestamps fail. Both are normalized to UTC with
microsecond precision, so equivalent timezone representations produce the
same model value. `built_at` is required and is never read from the current
time.

## 12. Canonical generation-plan serialization

```python
def serialize_sample_generation_plan(plan: SampleGenerationPlan) -> bytes
```

- UTF-8, no BOM, `ensure_ascii=True`, `sort_keys=True`,
  `separators=(",", ":")`, exactly one trailing `"\n"`;
- UTC timestamps with `timespec="microseconds"` and the explicit `+00:00`
  offset, never `Z`;
- arrays use the model's deterministic sorted order; the scope is
  serialized from its normalized result;
- the same model always serializes byte-identically;
- `parse_sample_generation_plan_bytes(serialize_sample_generation_plan(plan))`
  equals the plan field by field;
- no file is ever written.

This is the canonical form of the generation plan itself. It is not a
Dataset build-plan output, not a Dataset artifact, not a Dataset identity,
and not a Sample Generator run result.

## 13. Frozen models

```python
@dataclass(frozen=True)
class SampleGenerationRule: ...

@dataclass(frozen=True)
class SampleGenerationPlan: ...

@dataclass(frozen=True)
class SampleGenerationIdentityInput: ...
```

Deeply immutable: tuples, frozen nested models, no dicts or lists, no raw
JSON bytes, no `Path` objects, no current working directory, no mtimes, and
no machine name.

## 14. Identity inputs

`SampleGenerationIdentityInput` carries exactly the identity-bearing
inputs:

- `canonical_build_pins`: canonical build pins, each binding at least the
  verified, path-independent `canonical_build_id`;
- `feature_spec_pins` / `label_spec_pins` / `split_spec_pin`: spec pins,
  each binding `kind`, `name`, `version`, and `content_sha256`;
- `scope`: the normalized `DatasetScope` (symbols, trade_dates, interval,
  adjustment, requested_session);
- `generation_rule`: every rule field;
- `dataset_as_of`: null or a timezone-aware instant normalized to UTC
  microseconds.

## 15. Identity exclusions

Path inputs (`canonical_build_dirs`, `feature_spec_files`,
`label_spec_files`, `split_spec_file`), `output_root`, `built_at`, and
`output_plan_path` never enter the Sample Generation content identity.
The Sample Generation content identity never contains:

```text
canonical_build_dirs
feature_spec_files
label_spec_files
split_spec_file
output_root
built_at
output_plan_path
generation-plan file path
raw JSON bytes
JSON whitespace and key order
path order
machine name
working directory
filesystem separator representation
mtime
current time
future generated request order
future output build-plan bytes
```

The identity is computed with the existing versioned canonical encoding
(`encode_identity`); no second generic scalar encoder, no Python `hash()`,
no `repr()`, and no direct hashing of paths or raw JSON bytes is ever used.
Complex sub-models are bound through domain-separated fixed-length
sub-digests so the sequence encoding is unambiguous; input order never
affects the ID; any semantic change changes the ID; a path or `built_at`
change never does; equivalent timezone representations never do.

## 16. SpecPin kind rules

- Feature pins are exactly `SpecPin(kind="FEATURE")`;
- Label pins are exactly `SpecPin(kind="LABEL")`;
- the split pin is exactly `SpecPin(kind="SPLIT")`.

A wrong kind fails closed.

## 17. Duplicate rules

- duplicate `canonical_build_id` in the canonical pins fails, even when the
  objects are identical;
- duplicate `(kind, name, version)` keys in the Feature pins and in the
  Label pins fail;
- duplicate path entries in the path arrays fail;
- duplicate symbols and trade dates after normalization fail;
- nothing is ever silently deduplicated.

## 18. Path order has no semantics

Input order of `canonical_build_dirs`, `feature_spec_files`, and
`label_spec_files` is never semantic: entries are deterministically sorted
into the frozen model, and path order never enters any identity.

## 19. Generation content ID never enters Dataset identity

The Sample Generation content ID identifies only the semantic generation
inputs under the versioned generation contract. It never enters
`dataset_id`, never enters a `PITSampleRequest`, and never changes the
Canonical or Dataset identities. It never enters dataset_id.

## 20. The generated output is an ordinary Dataset build plan

The future generator's output is an ordinary `market-vault-dataset-build-plan-v1`
document: requests filled deterministically, all other formal fields
keeping the current build-plan contract
([dataset_cli.md](dataset_cli.md)), parseable directly by the existing
`market-vault dataset-build --plan <PATH>` command. The build plan itself
never enters Dataset identity.

## 21. PR-2 reads no Canonical and no spec

This contract layer never reads a Canonical build directory, never reads a
Feature, Label, or Split spec file, never calls
`load_verified_canonical_build`, never constructs a `PITSampleRequest`,
never implements window traversal, and never builds a Dataset. Canonical is
consumed only through the formal verified reader (`load_verified`) by PR-3,
and spec files are parsed by the existing formal parsers in PR-3. PR-2
never reads the current time, never selects a `latest`, never loads settings,
never connects to OpenD, and never accesses the network: there is no current time,
no latest, and no network anywhere in the contract. Every input is
explicit; nothing is auto-discovered or auto-scanned.

## 22. PR-2 generates no request

The contract foundation generates no sample request. Request generation
(anchor candidates, window traversal, `PITSampleRequest` construction) is
PR-3's responsibility. Every generated request of PR-3 is constructed as a
formal `PITSampleRequest` and passes its validation; the generator never
copies PIT validation logic and never claims a sample is necessarily
COMPLETE.

## 23. PR-3: Sample Generator core

PR-3 implements the deterministic Sample Generator core
(`SAMPLE_GENERATOR_CORE_VERSION = "market-vault-sample-generator-core-v1"`,
public entry `generate_sample_requests(plan, *, path_base)`, output
`SampleGenerationResult`).

The core pipeline:

1. every `canonical_build_dirs` entry is read through the formal verified
   reader; every Feature / Label file through the formal loaders and the
   built-in registry preflight; `split_spec_file` through a strict JSON
   reader into the formal `ChronologicalSplitSpec`;
2. the BARS window-coverage preflight: the maximum Feature lookback
   (NONE -> 1, FIXED -> the declared BARS value, PARAMETER -> the spec's
   declared positive int parameter) must fit `feature_window_bars`, and the
   maximum Label horizon (BARS only, no `TRADING_DAYS` / `MINUTES`, no
   cross-trading-day opt-in) must fit `label_window_bars`;
3. the v1 Generation content identity from the verified normalized inputs;
4. deterministic bar filtering, contiguous-segment traversal, stride-based
   candidate anchors, exact window geometry, and formal
   `PITSampleRequest` construction;
5. the canonical stable request order with duplicate rejection.

**Contiguous segment.** Bars are ordered by code, market-calendar date,
session, event_time, canonical bar key, canonical row version id. A
segment continues only while code, market-calendar date, session, and the
interval / adjustment / requested_session dimensions are unchanged and
every adjacent event-time delta equals the nominal interval exactly. A
market-calendar-date change, a session change, a non-nominal delta
(including duplicate or out-of-order event times), or a known or actual
gap terminates the segment. Bars are never spliced across gaps, sessions,
or market-calendar dates, and a missing bar is never replaced by the Nth
existing bar.

**Stride origin.** Every new contiguous segment establishes its own
deterministic stride origin: the first usable anchor index of a segment is
`feature_window_bars - 1` and anchors then advance by `stride_bars`. A
candidate anchor must be a real verified Canonical bar at that position.

**Window geometry.** For a candidate anchor the feature slice is the
half-open window `segment[anchor_index - feature_window_bars + 1 :
anchor_index + 1]` and the label slice is `segment[anchor_index + 1 :
anchor_index + 1 + label_window_bars]`. Both slices must be complete:
insufficient feature history produces no request and is counted in the
diagnostics, and no request is generated when the label future is insufficient.
Windows are never shortened to force a request. `feature_window_start` is
the first feature bar's event time, `feature_window_close` is the anchor
bar's event time plus one nominal interval, `label_window_start` equals
`feature_window_close`, and the label window is exactly
`label_window_bars` nominal intervals; every window assertion is
re-verified at construction, so a gap can never silently move a window
boundary and no window ever crosses a market-calendar date.

**Path base.** The generator requires an explicit absolute path_base: an
empty or relative `path_base` (including `"."`) fails, and the current
working directory never participates in input location. Absolute plan
paths are used as-is; relative plan paths are lexically joined to the
absolute `path_base`; `resolve()` is never called and nothing is expanded.

**Cross-build row reconciliation.** Loaded verified builds are normalized
through the shared cross-build authority (deterministically sorted by
`canonical_build_id`, duplicate build ids fail), and Canonical rows are
reconciled across builds before any segment is constructed: identical row
versions merge deterministically, conflicting rows fail closed, and the
same `canonical_bar_key` or the same logical event slot (code,
market-calendar date, session, event_time, interval, adjustment,
requested_session) must never resolve to multiple different Canonical
bars. Overlapping Canonical rows never become a segment boundary, never
silently change a stride origin, and never silently drop requests; a
duplicate event time is a fail-closed conflict, never a gap, never a
silent first/last pick, and never a build-time or path-based winner.

**Shared Label configuration contract.** Every Label spec must pass the
single shared built-in Label configuration contract (alignment rule
`FEATURE_CLOSE_ALIGNED`, `observation_window.end_offset ==
horizon.value - 1`, forward shape `start_offset == end_offset`, excursion
shape `start_offset == 0`, fixed built-in transform catalog) — the exact
contract the Label executor enforces — before any request is generated, so
the generator can never emit a request the formal executor would reject.

**Self-validating result.** `SampleGenerationResult` re-derives its
identity input from its carried fields through the formal
`SampleGenerationIdentityInput` (pins, scope, rule, `dataset_as_of`) and
recomputes the Generation content ID; a format-valid but
content-mismatching ID fails closed. Every request must bind to the scope
(symbols, trade dates, interval, adjustment, requested_session) and its
feature and label spans must equal the rule's window sizes times the
nominal interval.

**Output.** The core output is the frozen `SampleGenerationResult` only:
requests, verified pins, scope, rule, `dataset_as_of`, and deterministic
diagnostics. The core never executes PIT assembly, never computes Feature
or Label values, never claims a sample is COMPLETE, and writes no file.
A gap never causes a window boundary to move; a missing scope key or an
EMPTY Canonical build simply produces zero requests.

## 24. PR-4: CLI and build-plan output

PR-4 implements the Sample Generation CLI (`market-vault sample-generate`),
writes the ordinary `market-vault-dataset-build-plan-v1` document to
`output_plan_path`, and proves COMPLETE / EMPTY / determinism end to end.
The CLI is not implemented; the generator core itself writes no file and no
build plan.

## 25. Unsupported boundaries

The v0.6.0 Sample Generator does not support:

- adjusted-price PIT (`adjustment = NONE` only);
- cross-trading-day Labels;
- `TRADING_DAYS` or `MINUTES` label horizons;
- arbitrary user transforms;
- automatic `latest` selection;
- automatic Canonical discovery;
- directory scanning;
- model training;
- backtesting;
- signals;
- network access, OpenD, or settings loading;
- current time input.

## 26. Relationship to the future Catalog

The generator produces build plans that, when executed, produce immutable
Datasets; those Datasets are what the future Dataset Catalog indexes. The
generator itself never reads or writes a Catalog.

## 27. Complete example

The following document is complete, explicit, and parseable by
`parse_sample_generation_plan_bytes` (verified by the contract tests). It
uses fixed timestamps (no current time), no `latest`, no network paths, no
undefined fields, and plural Feature and Label inputs:

```json
{
  "generation_plan_schema_version": "market-vault-sample-generation-plan-v1",
  "canonical_build_dirs": [
    "canonical/US.MU/2026-07-01",
    "canonical/US.MU/2026-07-02"
  ],
  "feature_spec_files": [
    "specs/features/simple_return_v1.yaml",
    "specs/features/rolling_mean_v1.yaml"
  ],
  "label_spec_files": [
    "specs/labels/forward_return_v1.yaml",
    "specs/labels/maximum_favorable_excursion_v1.yaml"
  ],
  "split_spec_file": "specs/splits/chronological_v1.yaml",
  "scope": {
    "symbols": ["US.MU", "US.AAPL"],
    "trade_dates": ["2026-07-01", "2026-07-02"],
    "interval": "1m",
    "adjustment": "NONE",
    "requested_session": "ALL"
  },
  "generation_rule": {
    "rule_schema_version": "market-vault-sample-generation-rule-v1",
    "feature_window_bars": 60,
    "label_window_bars": 30,
    "stride_bars": 5,
    "anchor_source": "VERIFIED_CANONICAL_BARS",
    "anchor_rule": "FEATURE_WINDOW_CLOSE",
    "cross_day_policy": "REJECT"
  },
  "dataset_as_of": "2026-08-01T00:00:00+00:00",
  "output_root": "datasets",
  "built_at": "2026-08-05T10:00:00+09:00",
  "output_plan_path": "plans/generated/plan-1.json"
}
```
