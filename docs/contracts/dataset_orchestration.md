# Dataset Orchestration Contract

Status: implemented in v0.5.0 PR-5
(`market_vault.dataset.orchestration_models` and
`market_vault.dataset.orchestration`).

This contract defines the pure in-memory Dataset orchestration pipeline:
the explicit supervised-build inputs, the authoritative logical Dataset
schema derivation, the fixed execution order over the already-shipped PIT /
Feature / Label / Split layers, the strict cross-layer sample binding, the
Feature EXCLUDED and Label INCOMPLETE policies, the final logical rows and
their fixed physical sort, the scope-wide CompletionSummary, the merged
ImplementationPins, the identity core (`logical_dataset_content_id`,
`DatasetIdentityInput`, `dataset_id`), the empty-result semantics, the
fail-closed result model, and the deterministic / offline boundary.
Materialization (PR-6) consumes exactly the output of this contract; this
contract itself writes nothing.

## 1. Status and scope

Implemented in v0.5.0 PR-5 (`feat: orchestrate deterministic dataset
builds`), on top of the shipped PIT assembly, built-in Feature execution,
built-in Label execution, chronological split / purge, and Dataset
identity/manifest foundations. This PR connects them into one executable
pipeline and computes — in memory only — the final logical Dataset schema,
the final logical rows, `logical_dataset_content_id`, `DatasetIdentityInput`,
and `dataset_id`. It never writes files, never creates Dataset directories,
never writes Parquet, never builds a DatasetManifest, and never calls
`build_dataset_manifest`.

## 2. Relation to ADR 0002

ADR 0002 (Deterministic Dataset Builder Boundary) fixes the builder
boundary: explicit pinned inputs, built-in registry-bound transforms only,
the fixed logical schema with the physical row sort, the `dataset_id`
lifecycle, and fail-closed behavior. This contract implements ADR 0002
decisions 2, 8, and 9's in-memory portion: every identity-bearing input is
pinned into `DatasetIdentityInput` / `dataset_id`, the fixed logical schema
and physical row order are enforced, and the content hash feeds the identity
input (the materialization steps of decision 9 are PR-6).

## 3. PIT / Feature / Label / Split dependencies

The orchestrator is a caller of the existing contracts and never a second
implementation:

- `assemble_point_in_time_samples` (PIT assembly contract) — exactly once;
- `execute_builtin_features` (built-in Feature execution contract) — exactly
  once, over the same PIT result;
- `execute_builtin_labels` (built-in Label execution contract) — exactly
  once, over the same PIT result;
- `assign_chronological_splits` (chronological splits and purging contract)
  — exactly once, over explicitly constructed `ChronologicalSplitSample`s.

No split rule, purge rule, DST boundary rule, nominal date rule, or
exclusion rule is reimplemented by the orchestrator.

## 4. Public API

`market_vault.dataset` publicly exports:

- `orchestrate_dataset_build` — the pure in-memory orchestration entry;
- `dataset_orchestration_schema` — the authoritative schema derivation;
- `DatasetOrchestrationResult`, `DatasetOrchestrationDiagnostics`,
  `DatasetOrchestrationError`;
- `DATASET_ORCHESTRATION_CONTRACT_VERSION`,
  `DATASET_KIND_SUPERVISED`,
  `DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY`, and the four
  `DATASET_COMPLETION_REASON_*` codes.

No mutable row builder, join helper, completion accumulator, pin merge
helper, callback, writer, or filesystem helper is public.

## 5. Explicit inputs

`orchestrate_dataset_build` is keyword-only:

```python
orchestrate_dataset_build(
    *, builds, requests, feature_specs, label_specs, split_spec, scope,
    schema, dataset_as_of, dataset_kind, manifest_schema_version,
    serialization_format, serialization_format_version,
) -> DatasetOrchestrationResult
```

- `builds` — at least one `VerifiedCanonicalBuild`; input order never
  matters; no paths, no "latest build" scanning, no unverified Canonical
  directories.
- `requests` — `PITSampleRequest` instances only; may be empty; every
  request must lie inside `scope`; duplicate `sample_key` fails via the
  existing PIT contract.
- `feature_specs` / `label_specs` — at least one each; order-insensitive;
  duplicate names/pins fail; no cross-kind mixing.
- `split_spec` — exactly one `ChronologicalSplitSpec`.
- `scope` — one `DatasetScope`; request `code` must belong to
  `scope.symbols`, `anchor_market_calendar_date` to `scope.trade_dates`, and
  interval / adjustment / requested_session must equal the scope's.
- `schema` — must exactly equal the authoritative schema derived by this
  contract from the specs and `dataset_as_of` (names, order, types,
  nullability); "compatible" is never accepted.
- `dataset_as_of` — `None` or a timezone-aware datetime, normalized to UTC
  microseconds by the existing PIT/identity contract and used identically by
  the PIT result, the samples, the rows, and `DatasetIdentityInput`. No
  per-sample cutoff is allowed.
- `dataset_kind`, `manifest_schema_version`, `serialization_format`,
  `serialization_format_version` — caller-declared and fail closed unless
  they equal `DATASET_KIND_SUPERVISED`, `DATASET_MANIFEST_SCHEMA_VERSION`,
  `SERIALIZATION_FORMAT_PARQUET`, and
  `SERIALIZATION_FORMAT_VERSION_PARQUET` respectively.

The entry has no output path, no registry parameter, no transform callback,
no clock, no random seed, no writer, no materializer, and no filesystem
parameter.

## 6. SUPERVISED-only dataset kind

Only `DATASET_KIND_SUPERVISED` is accepted; any other kind fails closed. No
hidden "latest" values and no directory scans are involved.

## 7. Pure in-memory boundary

The entry computes rows and identities in memory only. It never writes a
file, never creates a Dataset directory, never writes Parquet, never builds
a DatasetManifest, never calls `build_dataset_manifest`, never writes
`manifest.json`, `build_report.json`, spec artifact files, `split_spec.yaml`,
or `_SUCCESS`, never accesses OpenD or the network, and never uses current
time, random values, paths, mtimes, memory addresses, `repr()`, or the local
timezone in any identity.

## 8. Orchestration order

The fixed order, each layer invoked exactly once:

1. freeze input iterables to tuples;
2. input type and non-empty preflight;
3. scope/request consistency preflight;
4. spec deterministic ordering and authoritative schema derivation;
5. provided schema exact-match check;
6. `assemble_point_in_time_samples`;
7. `execute_builtin_features` over the same PIT result;
8. `execute_builtin_labels` over the same PIT result;
9. PIT / Feature / Label sample binding verification;
10. Feature EXCLUDED filtering;
11. `ChronologicalSplitSample` construction from the Feature COMPLETE
    samples' Label facts;
12. `assign_chronological_splits`;
13. split sample-set equality check (exactly the Feature COMPLETE set);
14. CompletionSummary generation;
15. final logical row generation;
16. fixed physical row sort;
17. `dataset_schema_id`;
18. `logical_dataset_content_id`;
19. Feature/Label ImplementationPin merge;
20. `DatasetIdentityInput` construction;
21. `dataset_id`;
22. `DatasetOrchestrationResult` construction (independent re-verification).

No retry and no second "better" result set is ever executed.

## 9. Scope / request validation

Requests are validated against the scope before any pipeline call: code in
symbols, anchor date in trade dates, interval / adjustment / requested
session equal. Scope keys without any request produce MISSING completion
entries; requests outside the scope fail closed.

## 10. Schema derivation

`dataset_orchestration_schema(feature_specs, label_specs, *,
include_dataset_as_of)` derives the authoritative schema: fixed sample
identity fields, timing facts, the conditional `dataset_as_of` field, the
Feature outputs in stable SpecPin order, the Label outputs in stable SpecPin
order, and the split assignment fields. Input order never matters; the
`include_dataset_as_of` flag must be a real bool; at least one FeatureSpec
and one LabelSpec are required; duplicate spec names and cross-kind
duplicates fail; output names may not collide with reserved fields.

## 11. Conditional `dataset_as_of` field

When `include_dataset_as_of` is true the schema carries
`dataset_as_of: timestamp_us_utc, nullable=false`. When false the schema has
no `dataset_as_of` field at all and the rows carry no placeholder null
column.

## 12. Feature field nullability

Feature output fields are always `nullable=false`: only Feature COMPLETE
samples enter the final rows, Feature EXCLUDED samples never enter the
rows, and no null is ever used to fake Feature availability. A
`FeatureSpec.output.nullable` other than false fails the schema derivation.

## 13. Label field nullability

Label output fields are `nullable=true` by explicit contract: a Feature
COMPLETE sample with an INCOMPLETE Label stays in the final rows as an audit
row whose incomplete Label values are true nulls (never NaN, never zero).
The LabelSpec registration outputs remain non-nullable; this contract only
declares how the final Dataset rows accommodate INCOMPLETE state.

## 14. Reserved column collisions

The reserved field names are all fixed sample-identity, timing, and split
fields (`code`, `sample_key`, `sample_version_id`,
`feature_window_close`, `actual_label_end_time`, `label_status`,
`dataset_as_of`, `feature_window_close_date`, `nominal_split`,
`final_split`, `assignment_status`, `reason_code`, `purge_boundary`). Any
Feature or Label output name colliding with a reserved field fails.

## 15. PIT / Feature / Label sample binding

The PIT, Feature, and Label results must carry exactly the same
`sample_key` set. For every key, `sample_version_id`, `code`, and
`feature_window_close` must be identical across the three layers, and the
PIT sample's `dataset_as_of` must equal the orchestration's normalized
cutoff. Missing, extra, replaced, or mutated samples fail closed before any
row, completion, or identity is generated. `code` is never recovered by
parsing `sample_key`.

## 16. Feature EXCLUDED filtering

A sample whose Feature status is `FEATURE_VALUE_STATUS_EXCLUDED` never
enters the `ChronologicalSplitSample` set, never enters the split result,
never enters the final rows, is never retained with null Feature values, and
is never disguised as Label INCOMPLETE. It is counted in the diagnostics and
contributes to the (code, trade date) CompletionSummary INCOMPLETE decision.
No new split reason code is introduced for Feature EXCLUDED; the split
contract is unchanged. Feature COMPLETE requires every Feature value
COMPLETE with a non-null value and exactly one value per FeatureSpec.

## 17. Label COMPLETE / INCOMPLETE handling

For each Feature COMPLETE sample, the same-key `LabelSampleResult.status`
and `LabelSampleResult.actual_label_end_time` are copied verbatim into the
`ChronologicalSplitSample`. The orchestrator never infers label status,
never reads a LabelSpec horizon to compute a purge time, never uses a label
window close or target event time as the actual end, never uses current
time, and never converts INCOMPLETE to COMPLETE.

## 18. `ChronologicalSplitSample` construction

```python
ChronologicalSplitSample(
    sample_key=..., sample_version_id=...,
    feature_window_close=..., label_status=...,
    actual_label_end_time=...,
)
```

constructed from the bound Feature and Label sample facts only.

## 19. `assign_chronological_splits` delegation

The orchestrator calls the existing `assign_chronological_splits` exactly
once with the constructed samples and the provided spec. Nominal split date
rules, DST boundary rules, TRAIN/VALIDATION purge rules, incomplete-label
exclusion, and out-of-range exclusion all live in the existing split
contract; nothing is copied. The final split result's sample set must equal
the Feature COMPLETE set exactly.

## 20. Final logical row population

The final rows contain every Feature COMPLETE sample — including Label
COMPLETE and Label INCOMPLETE, and split ASSIGNED, PURGED, and EXCLUDED —
and no Feature EXCLUDED sample. Therefore `logical_row_count ==
feature_result.diagnostics.complete_sample_count ==
split_result.diagnostics.sample_count == len(final rows)`. Each row is an
immutable tuple in the schema field order; feature values are copied
directly (never re-run, re-rounded, reformatted, or float-converted),
COMPLETE Label values are copied directly, INCOMPLETE Label values are true
nulls, and the split assignment fields are copied exactly. When some Labels
are COMPLETE and others INCOMPLETE, the COMPLETE values are kept and the
incomplete fields are null while the sample `label_status` stays INCOMPLETE.
`logical_row_mappings()` generates temporary schema-ordered dicts on demand
and is never an identity cache or mutable state.

## 21. Physical row sort

The final rows are fixed-sorted by `code` ASC, then `feature_window_close`
ASC, then `sample_key` ASC
(`DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY`). Request order, build
order, and spec order never change it. `logical_dataset_content_id` stays
row-order-independent, but the result still verifies the physical order so
PR-6 receives a fixed input for stable Parquet output. Duplicate
`sample_key` rows fail: one sample_key yields exactly one final row.

## 22. Completion semantics

The CompletionSummary covers the full `scope.symbols x scope.trade_dates`
Cartesian product with exactly one entry per (code, trade date), keyed by
`(PITSample.request.code, PITSample.request.anchor_market_calendar_date)`:

- no request/sample under the key → `MISSING` with
  `DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST`;
- every sample under the key Feature COMPLETE and Label COMPLETE →
  `COMPLETE`, no reason code;
- any sample Feature EXCLUDED and all Labels COMPLETE → `INCOMPLETE` with
  `DATASET_COMPLETION_REASON_FEATURE_EXCLUDED`;
- all Features COMPLETE but any Label INCOMPLETE → `INCOMPLETE` with
  `DATASET_COMPLETION_REASON_LABEL_INCOMPLETE`;
- both Feature EXCLUDED and Label INCOMPLETE facts present → `INCOMPLETE`
  with `DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE`.

Any incomplete sample makes the whole key INCOMPLETE. Split ASSIGNED /
PURGED / EXCLUDED never changes completion: completion describes data
computation completeness, never training eligibility, and out-of-range or
purge states never downgrade completion. Counts are recomputed from the
actual entries; entries follow the existing CompletionSummary normalization;
no free-form reason and no gap-based inference is used.

## 23. Completion reason codes

The four fixed machine codes are
`DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST`,
`DATASET_COMPLETION_REASON_FEATURE_EXCLUDED`,
`DATASET_COMPLETION_REASON_LABEL_INCOMPLETE`, and
`DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE`. No other
reason code is ever emitted.

## 24. ImplementationPin merge

`DatasetIdentityInput.implementations` is the deterministic merge of
`FeatureExecutionResult.implementation_pins` and
`LabelExecutionResult.implementation_pins`: only actually resolved pins;
identical pins deduplicate by `(name, version)`; the same `(name, version)`
with conflicting content hashes fails; content hashes must be non-null; the
final order is `(name, version, content_sha256)`. No orchestration
pseudo-pin, splitter pin, or PIT assembler pin is ever added.

## 25. Canonical pins, row IDs, and gap references

`DatasetIdentityInput` carries the complete PIT facts:
`pit_result.canonical_build_pins`, `pit_result.canonical_row_version_ids`,
and `pit_result.gap_references`. The whole build's PIT selection, Feature
exclusion, and Label incompleteness are deterministic build facts; no
reduced "consumed-by-ASSIGNED" subset is reconstructed. The PIT association
schema/content contracts are unchanged.

## 26. Logical content ID

`logical_dataset_content_id` is computed once over the authoritative schema
and the final row mappings (`row-order-independent` per the v0.4 contract,
row multiplicity preserved, zero rows deterministic). It never depends on
Parquet bytes, paths, `built_at`, or local timezone.

## 27. `DatasetIdentityInput`

Constructed exactly from the orchestration facts: `dataset_kind =
DATASET_KIND_SUPERVISED`, the validated `scope`, the normalized
`dataset_as_of`, the authoritative `schema`, `dataset_schema_id`,
`logical_dataset_content_id`, the full PIT canonical pins / row-version IDs /
gap references, the Feature and Label spec pins from the execution results,
the split spec pin, the merged implementations, the CompletionSummary, and
the caller-declared manifest schema version and serialization
format/version. No field is added; no existing identity algorithm is
modified. Never included: orchestration contract version, `built_at`,
elapsed time, paths, cwd, mtimes, diagnostics, PR numbers, branch, commit
time, or local timezone.

## 28. `dataset_id`

`dataset_id(identity_input)` is called exactly once per build over the
constructed `DatasetIdentityInput` and re-verified at result construction.
Any identity-bearing input change (Canonical pin, row version, market
values, `dataset_as_of`, sample version ID, spec content, implementation
hash, output values, label status, actual end, split assignment, scope,
completion, schema order/type/nullability, serialization format/version)
changes `dataset_id` or fails closed.

## 29. Empty orchestration result

Empty requests, zero PIT samples, all-Feature-EXCLUDED sets, and zero final
rows are allowed and produce a deterministic result: at least one
VerifiedCanonicalBuild, at least one FeatureSpec and one LabelSpec, a
`ChronologicalSplitSpec`, a non-empty scope, the correct schema, non-empty
SpecPins and ImplementationPins, a legal (possibly empty) split result, a
deterministic zero-row `logical_dataset_content_id`, a deterministic
`DatasetIdentityInput` and `dataset_id`, `status = STATUS_EMPTY`, and a
CompletionSummary that still covers the full scope (empty requests make
every key MISSING with `NO_SAMPLE_REQUEST`; all-Feature-EXCLUDED makes the
requested keys INCOMPLETE with `FEATURE_EXCLUDED`). Identity construction is
never skipped for zero rows.

## 30. Result models

`DatasetOrchestrationResult` is frozen and carries status, dataset kind,
scope, `dataset_as_of`, the spec objects, the four sub-results, the schema,
the rows, `dataset_schema_id`, `logical_dataset_content_id`,
`DatasetIdentityInput`, `dataset_id`, completion, diagnostics, the manifest
schema version, the serialization format/version, the row-order code, and
the orchestration contract version. Construction independently re-verifies:
contract version, dataset kind, row order, spec types/order/pins, the
cross-layer sample binding, the split-set equality and per-assignment
facts, the re-derived schema, the rebuilt rows (field count, schema
type/nullability, physical sort, `sample_key` uniqueness), every identity
recomputation, completion, diagnostics, `identity_input`, and status/row
count consistency. Manually constructed or `dataclasses.replace`-modified
inconsistent objects fail. Results never carry `built_at`, output paths,
DatasetManifest, `DatasetOutputFile`, Parquet bytes, temporary directories,
`created_new_build`, current time, or filesystem facts.

`DatasetOrchestrationDiagnostics` is frozen and verifies its fixed count
matrix at construction (PIT == Feature complete + excluded, PIT == Label
complete + incomplete, split == Feature complete, split == assigned +
purged + excluded, rows == split, completion keys == scope Cartesian
product).

## 31. Diagnostics

`DatasetOrchestrationDiagnostics` carries `request_count`,
`pit_sample_count`, `feature_complete_sample_count`,
`feature_excluded_sample_count`, `label_complete_sample_count`,
`label_incomplete_sample_count`, `split_sample_count`,
`assigned_sample_count`, `purged_sample_count`, `excluded_sample_count`,
`logical_row_count`, and the three completion key counts. The result model
recomputes the whole diagnostics from the actual sub-results and requires
exact equality.

## 32. Determinism

Identical pinned inputs produce identical logical schema, rows, completion,
content ID, identity input, and `dataset_id`. Build order, request order,
spec order, scope input order, Python dict insertion order, local timezone,
checkout path, cwd, file mtimes, and current time never change the result.
Every identity-bearing change changes the content ID and `dataset_id` or
fails closed; physical row-order changes are rejected by result
construction and are never masked by the content ID's order independence.

## 33. Fail-closed errors

`DatasetOrchestrationError` (a `DatasetError` subclass) is the unified
public error boundary. `PITAssemblyError`, `FeatureExecutionError`,
`LabelExecutionError`, `SplitValidationError`, `DatasetError`, and the
documented input `TypeError` / `ValueError` / `KeyError` are wrapped with
their `__cause__` preserved. No bare validation exception leaks, no real
programming error is swallowed, nothing warns-and-continues, and no partial
result is ever returned.

## 34. No arbitrary code

The orchestrator executes only the built-in registry-bound Feature and
Label transforms via the existing executors. There is no transform callback,
no arbitrary function injection, no `eval` / `exec`, and no identity derived
from a memory address.

## 35. No filesystem / network

The entry has no filesystem or network parameters and performs no I/O
beyond the verified Canonical builds handed to it. No OpenD access, no
network, no cwd changes, no temporary files, and no writes of any kind.

## 36. PR-6 handoff

The `DatasetOrchestrationResult` is the only trusted in-memory input to
PR-6 materialization: the authoritative schema, the final rows (fixed
physical order), the computed `logical_dataset_content_id`, the
`DatasetIdentityInput`, and `dataset_id` are all present and independently
re-verified. PR-6 adds staging, Parquet, manifest, spec artifacts, `_SUCCESS`,
and atomic commit; nothing in this contract writes them.

## 37. Explicit non-goals

This contract does not implement Dataset staging directories, Dataset
Parquet, DatasetManifest, `build_dataset_manifest` calls, `manifest.json`,
`build_report.json`, Feature/Label spec artifact files, `split_spec.yaml`,
`_SUCCESS`, materialization, atomic rename, idempotent or conflicting
directory handling, a verified Dataset reader, a Dataset CLI, an API
server, a Python client, ML training, backtesting, trading signals, live
data, or OpenD access. It never modifies an existing identity algorithm or
version constant and never starts PR-6.

## 38. MarketVault / quant-project boundary

This contract lives entirely inside the MarketVault repository and its
published Dataset contracts. It implements no strategy, no quant logic
beyond the documented deterministic dataset-building pipeline, and nothing
from other projects or repositories is imported, read, or modified.
