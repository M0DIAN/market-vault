# Cross-Day / Trading-Days Label V1

## 1. Status and Authority

L1 design-only candidate, based on main
`bcb53974a87d79dfc6f37f250bc2e1eb3c066499` (tree
`fc6f2b8aea4fc214ecc8195ade7b6d747b5706be`). Package version remains
`0.8.0`. This document does not authorize runtime implementation or merge.
Independent semantic review and independent post-merge closure are required.

Selected architecture: `MODEL_SCHEDULE_BOUND_LABEL_SIDECAR`.

```text
unchanged PIT v1 (feature-only request) -> Feature/anchor authority
explicit VerifiedTradingDaySchedule + unchanged LabelSpec(TRADING_DAYS)
    + explicit VerifiedCanonicalBuild evidence
    -> Cross-Day Label association sidecar -> Cross-Day Label executor
    -> future NEW Dataset cohort (not the existing A4 Dataset cohort)
```

The following remain bit-for-bit unchanged: `PITSampleRequest`,
`pit_sample_key`, `pit_sample_version_id`, `PITAssemblyResult`,
`assemble_point_in_time_samples`, LabelSpec v1 parsing/content IDs, old
TransformRegistration/registry/ImplementationPins, old Label executor, old
Sample Generator, chronological split, and A1/A2/A3/A4.1/A4.2/A4.3. Old BARS
behavior remains authoritative for BARS. No extension of PIT v1 to accept
cross-calendar-date Label rows, and no in-place extension of the old executor.

Read with the frozen contracts:

- [LabelSpec v1](contracts/feature_label_spec_versioning.md).
- [Built-in Label execution](contracts/built_in_label_execution.md).
- [Canonical materialization](contracts/canonical_market_bar_materialization.md).
- [Market-bar timestamps](contracts/market_bar_timestamp_semantics.md).
- [Qualified early-close geometry](market_bar_early_close_rth_geometry_qualification_v1.md).
- [Chronological splits](contracts/chronological_splits_and_purging.md).
- [A4 Dataset cohort](multi_source_dataset_cohort_v1.md).

## 2. Closed V1 Admission

Reuse the existing immutable `LabelSpec` with every semantic field unchanged.
No LabelSpec v2. Admit a nonempty spec set only when every spec satisfies:

| Field | Exact requirement |
| --- | --- |
| horizon.unit | TRADING_DAYS |
| horizon.value | positive actual integer N; bool rejected |
| observation_window.unit | TRADING_DAYS |
| observation_window.end_offset | N-1 |
| observation_window.start_offset | N-1 for forward; 0 for excursion |
| cross_trading_day.allow | true |
| cross_trading_day.boundary_rule | SAME_REQUESTED_SESSION_BAR_SLOT |
| missing_data_policy | INCOMPLETE |
| alignment_rule | FEATURE_CLOSE_ALIGNED |
| parameters | empty |
| output.name / nullable | spec.name / false |

The exact existing four built-in transform refs are retained in LabelSpecs;
section 7 declares their separate Cross-Day registrations. Validate the old
spec's exact input fields, output type and requirements too: Canonical schema
`market-bars-canonical-schema-v1`, source schema exactly `10.9-mv-ts2`; no
wildcard or legacy `10.9` admission. Legacy `10.9` preserves the historically
incorrect Moomoo RTH timestamp interpretation; the qualified normal and
early-close same-session-slot geometry is TS2 authority. Every Cross-Day
anchor, Label row and Canonical proof must belong to this exact TS2 cohort.
Unknown transforms, duplicate semantic specs/names, unsupported requirements,
mixed BARS/TRADING_DAYS or MINUTES/TRADING_DAYS, and MINUTES-only inputs fail
preflight. No partial dispatch across executors. Zero samples still run all
spec, registry, schedule and evidence preflight; zero specs is invalid.

V1 geometry is the currently qualified US market, `America/New_York`,
`requested_session=RTH`, `adjustment=NONE`, and intervals exactly
`1m,5m,15m,30m,60m`. Other markets/geometries need separate qualification;
RTH does not imply worldwide session support. `ADJUSTED_PRICE_PIT_POLICY=
MODEL_C_NONE_ONLY` remains unchanged. QFQ/HFQ cannot be admitted without
corporate-action authority. No new unit is added to the old registration enum.

Old BARS Feature/Label registries, executors and ImplementationPins remain
`10.9` authority. Their supported source-schema sets are not widened, their
identities are not changed, and A4 is not modified by this parallel cohort.

## 3. Verified Trading-Day Schedule

`VerifiedTradingDaySchedule` is a new deeply immutable logical authority,
explicitly supplied before assembly; not a live acquisition result, Catalog
row, mutable DuckDB query, path, current/latest pointer or OpenD response.
The future sole schedule validation boundary validates the complete typed
record, recomputes IDs, and retains evidence pins. No supported trust flag,
unverified constructor shortcut, partial schedule or inferred default.

Exact logical fields (all mandatory):

```text
schedule_schema_version = trading-day-schedule-v1
market = US
requested_session = RTH
market_timezone = America/New_York
coverage_start_date : date
coverage_end_date : date
daily_records : tuple[TradingDayRecord, ...]
source_snapshot_id : sha256
source_content_hash : sha256
calendar_contract_version = cross-day-us-rth-calendar-contract-v1
normalization_version = trading-day-schedule-normalization-v1
coverage_completion_evidence_id : sha256
coverage_complete : true
archive_available_at : aware UTC-microsecond timestamp
```

`TradingDayRecord` has exactly `market_calendar_date: date`, `day_status`,
`session_open`, `session_close`, `session_profile`. Exactly one record for
EVERY civil date in inclusive coverage, including weekends and holidays.
`TRADING` requires non-null instants and profile; `CLOSED` requires all three
null. Duplicate dates, omissions, unknown status/profile, reversed coverage
or incomplete proof invalidate the schedule. Missing never means CLOSED.
Normalize input order by date; never coalesce duplicate records.

Instants are aware, UTC-normalized at microsecond precision by the existing
identity encoder. Naive times fail; submicroseconds follow its truncation
semantics. Local-date conversion must equal the record's date. TRADING open
is strictly before close. Exact profile validation, not bar observations,
determines geometry:

- `NORMAL`: local 09:30-16:00, as qualified by the frozen normal RTH profile.
- `QUALIFIED_EARLY_CLOSE`: local 09:30-13:00 only for the two checked-in
  special dates `2025-11-28` and `2025-12-24` in
  `normalization/rth_session_geometry.py` at this base. Pin the existing
  special-session authority and provider-profile qualification through the
  calendar contract/evidence. Do not generalize to other dates or profiles.
- The schedule cannot mark a listed early-close TRADING day NORMAL. An
  unlisted shortened or otherwise special geometry fails closed, even when
  bars resemble it. The old resolver's NORMAL fallback is not evidence that
  a date was open; only the complete explicit schedule can assert TRADING.

Schedule source content and completion evidence must establish this exact
market/session/date scope. A hash-shaped value alone is not proof of an
exchange calendar's truth. L2's logical verifier checks the supplied sealed
declaration and its evidence consistency; immutable source acquisition and
physical evidence verification belong to L4. Synthetic offline schedules
are test fixtures, not production qualifications. No provider is invoked to
fill an admission gap.

`archive_available_at` is the conservative possession/verification bound for
the complete schedule, including its completion evidence, not the earliest
receipt of one date. With non-null `dataset_as_of=A`, require schedule
`archive_available_at <= A` or fail authority, not Label INCOMPLETE. Without
A the explicit supplied schedule is used; there is still no current-time
lookup. Section 9 binds all fields, including this clock, into identity.

## 4. Feature Boundary and Temporal Geometry

Use unchanged PIT v1 requests with `label_window=None`. The logical Feature
key remains `pit_sample_key(feature_only_request)`; the old bar sample
version also remains unchanged. Future Label windows never enter PIT v1.
An A3 result, when used, is computed from this same Feature-side result and
keeps its `multi_source_sample_version_id` without schedule/Label inputs.

Keep explicit Feature evidence separate from Label-only future evidence.
Do not add future builds to Feature PIT's considered-build set as a shortcut.
The sidecar receives the verified Feature PIT result, its exact verified
Canonical closure, separately supplied Label Canonical builds, schedule,
LabelSpecs and the same explicit A. It verifies the complete Feature closure
without rerunning PIT selection. It never invokes the old Label executor.

L2 uses verified TS2 Canonical builds, unchanged feature-only PIT v1,
`LabelSpec(TRADING_DAYS)` and `VerifiedTradingDaySchedule` without running
old bar Feature transforms. Feature-only PIT authority is not a claim that
the old BARS Feature executor supports TS2. PIT v1 models and identities
remain unchanged; the full Dataset's Feature-side precondition is section 11.

For each sample, let `I` be the nominal interval duration, `T` the Feature
window close, and `d0` the request's anchor market date. Resolve only the
PIT-selected Feature row with `event_time=T-I`. It must match the request,
be market-available by T, and be archived by A if set. No alternative row
from the Label builds or older Feature position is an anchor. If the exact
selected anchor is absent, the eventual outcome is MISSING_ANCHOR_ROW,
subject first to all configuration/authority checks below.

Require d0 to be a schedule TRADING day. Define the intended anchor slot
even if the anchor row is missing:

```text
anchor_event_time = T - I
anchor_slot = (anchor_event_time - schedule[d0].session_open) / I
```

The numerator must be a nonnegative exact multiple of I. Require
`anchor_event_time + I <= session_close(d0)`. Wrong date, unaligned anchor
or out-of-session anchor is an authority/geometry error, not missing data.
Do not derive slots from formatted wall-clock strings. A qualified truncated
last nominal bar that fails this full-slot fit is outside this contract.

`D(k)` is the (k+1)-th TRADING civil date strictly after d0, with D(0) the
first. Skip only explicit CLOSED records. Prove every intervening civil
date, even for a forward Label requiring just its endpoint. Do not enumerate
unbounded `range(N)`: compare N with the finite supplied schedule's remaining
TRADING record count first; insufficient coverage or arithmetic overflow
fails authority/configuration. Tail anchors are never silently dropped.

For every required offset k:

```text
expected_event_time(k) = schedule[D(k)].session_open + anchor_slot * I
slot_fits(k) = expected_event_time(k) + I <= schedule[D(k)].session_close
```

DST therefore preserves the session-relative slot, not UTC wall-clock time.
For a qualified target early close whose slot does not fit, record
ALIGNED_SLOT_OUTSIDE_SESSION. Never shift to the last bar, move earlier,
skip that trading date, or substitute a later day. Normal-session mismatch
is an authority error, not an early-close exception.

## 5. Required Points and Canonical Authority

Forward return/direction require exactly offset N-1. Intermediate dates need
schedule proof but their bars are NOT required, selected, or transform inputs.
Their absence alone cannot make the forward Label incomplete.

Excursions require offsets 0 through N-1, one aligned observation from each
TRADING date, in that order. These are ALIGNED-DAILY-POINT excursions, not all
intraday bars in intervening sessions. A future all-session-bars contract
requires a new explicit boundary/call contract; old BARS offsets are never
reinterpreted.

At each fitting required slot match exact code, interval, adjustment NONE,
requested_session RTH, actual session RTH, market date and event_time. Require
the supported Canonical/source schemas and trustworthy row/build membership.
Reconcile identical row-version/content/provenance across builds, retaining
every backing build. Conflicting candidates for one Canonical bar key fail;
no latest build, archive clock or lexical revision winner. IDs are assertions
to be checked against typed verified evidence, not standalone trust tokens.

Each required fitting slot must be supported by either its exact verified row
or exact verified Canonical absence/gap evidence. Request date metadata,
manifest COMPLETE, zero rows, absence of a gap, or apparent total bar count
do not prove full-session coverage. At this frozen base the usable negative
proof is an internal nominal gap with exact matching scope, recomputed gap
ID, and both exact verified boundary rows. The expected time must lie on the
missing grid between those boundaries. Both boundary rows must be archived
by A when A exists. Retain their build pins and gap proof. A leading/trailing
missing bar, a wholly absent session, or an EMPTY build alone cannot provide
this negative proof: FAIL AUTHORITY. Do not invent a stronger Canonical
coverage mechanism or change Canonical runtime in L2.

The explicit verified schedule proves when a slot should exist; it does NOT
prove Canonical acquisition completeness. Thus unproved required date/scope
is FAIL AUTHORITY regardless of `missing_data_policy`. For a non-fitting
qualified early-close slot, schedule geometry itself proves impossibility;
no nonexistent out-of-session Canonical bar/gap is demanded.

Label rows are future ground truth, not Feature information. Their exact
market-clock admission rule is:

- No `market_available_at <= feature_window_close` constraint applies to
  Label rows (the Feature anchor's separate visibility rule still applies).
- No nominal horizon or session-close market cutoff applies to Label rows.
- `market_available_at` is verified Canonical provenance and determines
  `actual_label_end_time` under section 6; it is never replaced or inferred
  from the nominal horizon/session close.
- With `dataset_as_of=A`, consumption requires `archive_available_at <= A`.
  Without A there is no archive cutoff or current-time lookup.
- All existing Canonical row invariants remain mandatory, as do the scope,
  slot-fit and consumed-order invariants in this document.

If the exact row exists in supplied verified history but is archive-future,
record ARCHIVE_FUTURE; never
select it or another version. Such rejected evidence is explicitly marked
archive-limited diagnostic provenance only, not as-of usable/consumed input.
All supplied considered build IDs remain visible in the association audit;
no future evidence is silently promoted to as-of authority. Conflicts are
still fatal before archive filtering. Future-dated gap boundaries cannot
prove absence as of A.

No nearest search, N-th observed-date selection, forward fill, interpolation,
backward/forward substitution or implicit repair.

## 6. Decisions, Incompleteness and Purging

Run all schedule, scope, evidence consistency and per-slot authority checks
before deriving an incomplete reason or calling any transform. No missing
anchor/row may mask malformed evidence. The exact six-reason vocabulary is:

| Precedence | Reason | Condition after authority admission |
| --- | --- | --- |
| 1 | MISSING_ANCHOR_ROW | exact selected Feature-close anchor absent |
| 2 | ALIGNED_SLOT_OUTSIDE_SESSION | any required target slot does not fit a qualified early close |
| 3 | ARCHIVE_FUTURE | a required exact row exists but is not archived by A |
| 4 | MISSING_TARGET_ROW | fitting endpoint N-1 missing with exact negative proof |
| 5 | INSUFFICIENT_ROWS | excursion offset 0 missing, endpoint present |
| 6 | NON_CONTIGUOUS_TRADING_DAY_ROWS | excursion interior point missing, both endpoints present |

Every missing fitting point must have admitted proof regardless of precedence.
For N=1, a missing point is the endpoint and reason 4 applies. Otherwise
COMPLETE requires the anchor and every transform-required point. Unsupported
session/interval/rule/unit, invalid schedule, insufficient schedule coverage,
schema/scope conflict and unproved Canonical coverage are contract/authority
errors, never INCOMPLETE. There is no PARTIAL result or value imputation.

Only COMPLETE invokes the transform, exactly once. INCOMPLETE never invokes
it and has `value=null`. With an anchor present, the ordered eligible subset
of required fitting rows is retained as the actually consumed diagnostic
subset even when no arithmetic is invoked; this preserves the existing
Label end-time convention. MISSING_ANCHOR_ROW has no consumed rows/end;
admitted target evidence can remain in the audit without being consumed.
Archive-future rows and non-fitting slots are never in that subset.

```text
actual_label_end_time = last actually consumed Label row.market_available_at
                       or null when the consumed subset is empty
```

Rows sort by Trading-Day offset (equivalently increasing event time here),
not arrival order. Require valid increasing market availability in consumed
order and no end before T. Do not use target event time, horizon date,
session close, now or A. COMPLETE must have a non-null end. A sample's end is
the max non-null value end; its Label status is COMPLETE iff every value is
COMPLETE. Existing chronological split receives those explicit facts unchanged:
INCOMPLETE exclusion still precedes purge; COMPLETE TRAIN/VALIDATION purge
uses only actual_label_end_time against existing exclusive boundaries.

## 7. Separate Execution/Fingerprint Cohort

Freeze `cross-day-label-execution-v1` and
`cross-day-label-transform-call-v1`. A closed static Cross-Day registry
contains exactly these old pure callables, under NEW registration metadata:

| transform_ref suffix under market_vault.dataset.label_transforms. | fields | output | offsets |
| --- | --- | --- | --- |
| forward_return:forward_return | close | float64 | N-1 |
| forward_direction:forward_direction | close | int64 | N-1 |
| maximum_favorable_excursion:maximum_favorable_excursion | close,high | float64 | 0..N-1 |
| maximum_adverse_excursion:maximum_adverse_excursion | close,low | float64 | 0..N-1 |

All parameters empty, output nonnullable. Preserve the old numeric formulas:
return `target.close/anchor.close-1.0`; direction -1/0/1; MFE
`max(0.0,max(high/anchor.close-1.0))`; MAE
`min(0.0,min(low/anchor.close-1.0))`. Positive required prices, real finite
binary64 inputs, no int/bool coercion, int64 direction, normalized negative
zero and fail-closed nonfinite/domain errors remain unchanged. Excursion
high/low are only those of aligned daily bars, not a whole-day high/low.

The numeric immutable input shape is the existing `LabelTransformInput`:
field_names, anchor_row, ordered rows, parameters, alignment_rule. No schedule,
LabelSpec, Canonical objects, paths or clock callbacks reach a transform.
The Cross-Day executor proves temporal geometry before constructing this
numeric object; reusing it does not reuse the old BARS registry/executor.

No dynamic imports, discovery, entrypoints, eval, arbitrary callbacks, caller
registry or caller implementation pins. Every spec must resolve before any
sample is executed, including zero-sample runs. Re-resolve the exact admitted
selected row versions; verify scope, clocks, schema, provenance and decision
IDs, without picking a different winner.

Fingerprint under `cross-day-label-implementation-v1` with exactly:

```text
transform_ref, implementation_version="v1", implementation_source_sha256,
execution_contract_version="cross-day-label-execution-v1",
transform_call_contract_version="cross-day-label-transform-call-v1",
canonical_schema_version="market-bars-canonical-schema-v1",
source_schema_version="10.9-mv-ts2", boundary_rule="SAME_REQUESTED_SESSION_BAR_SLOT",
window_unit="TRADING_DAYS", offset_shape="TARGET_ONLY" or "ALIGNED_DAILY_POINTS",
input_count, input_0000, [input_0001],
output_logical_type, output_nullable=false, parameter_count=0
```

Use H from section 9. Source SHA256 is the old normalized module SOURCE
CONTENT algorithm: CRLF/CR to LF, reject unsafe controls, strip leading and
trailing blank lines, one final LF, no per-line whitespace or Unicode change.
This uses only an already-loaded statically registered callable's module.
Registry construction may perform that narrowly bounded inherited
`inspect.getsource(module)` read; this is NOT general filesystem authority.
No path/mtime/cwd enters identity. Temporal assembly and numeric invocation
perform zero I/O; inability to obtain stable source fails closed. A future
implementation must test this precise exception, not grant general reads or
alter old fingerprints. `ImplementationPin(name=transform_ref,version="v1",
content_sha256=fingerprint)` is new Cross-Day authority; its record digest
uses unchanged `H("dataset-implementation", {name,version,content_sha256})`.
Old BARS ImplementationPins must not be supplied or relabeled Cross-Day.

## 8. Logical Result Boundary

New immutable, self-validating logical records:

- `TradingDaySchedulePin`: exact scalar record in section 9.2.
- `CrossDayLabelDecision`: section 9.4 fields plus the typed collections
  represented by its digests; one per (sample_key,label_spec_pin_id).
- `CrossDayLabelSampleBinding`: section 9.5; one per Feature sample.
- `CrossDayLabelValueResult`: section 9.6, with actual typed SpecPin and
  ImplementationPin resolved from the fixed registries/specs.
- `CrossDayLabelExecutionResult`: schedule pin, normalized LabelSpecs and
  implementation pins, decisions, sample bindings, values, association ID,
  values content ID, and sample statuses/end times derived from values.

Exact cardinality, no missing/extra/duplicate samples/spec bindings, complete
bidirectional build/row/proof closure, status/reason/end coupling and all
stored IDs must be reverified. No selected reference can be justified only
by a SHA-shaped string. Evidence carried for a gap or excluded row remains
auditable. Reordering equivalent caller collections does not change IDs;
duplicate semantic inputs fail, whereas identical rows encountered inside
distinct legitimate builds reconcile with ALL backing provenance retained.

Schedule is Label-side ground-truth geometry ONLY. It is never passed to bar
Features, Observation Features, A3 selection or matrix input columns. Changing
only future schedule/Label outcome can change Label/future Dataset identity,
but cannot change Feature values, pit_sample_key, old bar sample version, A3
decisions or multi_source_sample_version_id given identical Feature evidence.

## 9. Exact Identity Payloads

### 9.1 Encoding and sequence rules

`H(domain, scalar_record)` means the unchanged
`market_vault.dataset.encoding.encode_identity`: SHA256 of UTF-8
`v1|domain|` plus sorted `key:tagged_scalar` entries separated by U+001F.
Tags: null n, bool b:true/b:false, int i:decimal, float f:IEEE754 big-endian
binary64 hex (-0 normalized, NaN/Inf rejected), NFC text s:, ISO date d:,
UTC-microsecond pandas ISO timestamp t:. A date is NOT a string/timestamp.
Reject unsafe text and normalized duplicate names before encoding. All IDs
are lowercase 64-hex. No JSON hashing, repr or platform-dependent joins.

```text
S(domain, ordered_sha256_members) =
  H(domain, {count: len(members), members: concatenation_of_64_hex_members})
```

S uses fixed-width hashes, so no ambiguous concatenation. Empty count is 0
and members is "". Every record below has exactly the listed keys; nullable
keys remain present. No hidden defaults, added clock/path fields, or implicit
sorting. Set-like collections sort as stated; temporal collections retain
their explicit chronological order. IDs cover diagnostic incomplete results
as well as successful values.

### 9.2 Schedule content and pin

```text
daily_record_id = H("trading-day-schedule-date-v1", {
  market_calendar_date, day_status, session_open, session_close, session_profile
})
schedule_content_id = H("trading-day-schedule-content-v1", {
  schedule_schema_version, market, requested_session, market_timezone,
  coverage_start_date, coverage_end_date,
  daily_records_digest: S("trading-day-schedule-dates-v1", daily_record_ids by date),
  source_snapshot_id, source_content_hash, calendar_contract_version,
  normalization_version, coverage_completion_evidence_id,
  coverage_complete, archive_available_at
})
TradingDaySchedulePin = {
  schedule_schema_version, schedule_content_id, market, requested_session,
  market_timezone, coverage_start_date, coverage_end_date,
  source_snapshot_id, source_content_hash, calendar_contract_version,
  normalization_version, coverage_completion_evidence_id,
  coverage_complete, archive_available_at
}
schedule_pin_id = H("trading-day-schedule-pin-v1", TradingDaySchedulePin)
```

Every listed schedule mutation, including archive clock and proof, changes
content and pin. No execution/physical path or nonsemantic display metadata.

### 9.3 Auxiliary records

```text
label_spec_pin_id = H("dataset-spec", {kind:"LABEL", name, version, content_sha256})
  # content_sha256 is UNCHANGED feature_label_spec_content_id(LabelSpec).
backing_canonical_build_ids_digest = S(
  "cross-day-backing-canonical-builds-v1",
  sorted unique build IDs containing the exact admitted row/proof
)
considered_canonical_build_ids_digest = S(
  "cross-day-considered-canonical-builds-v1",
  sorted unique Feature-closure + supplied Label/proof/diagnostic build IDs
)
slot_id = H("cross-day-label-slot-v1", {
  offset, market_calendar_date, event_time, session_open, session_close, slot_fits
})
row_reference_id = H("cross-day-label-row-v1", {
  offset, canonical_bar_key, canonical_row_version_id, backing_canonical_build_ids_digest,
  event_time, market_available_at, archive_available_at
})
gap_proof_id = H("cross-day-label-gap-proof-v1", {
  offset, gap_id, backing_canonical_build_ids_digest,
  previous_canonical_row_version_id, next_canonical_row_version_id,
  missing_from_event_time, missing_to_event_time, proof_archive_available_at
})
```

Gap proof archive time is max of its two verified boundary archive times;
scope and recomputed gap facts must match section 5, not caller claims.
`offset=-1` is reserved for the anchor row reference. Backing build IDs are
all verified builds containing that identical row/proof. Temporal references
sort by offset; multiple admitted proofs at one offset sort by proof ID.
Rejected archive-future rows use the same row-reference shape but are kept
only in the rejected digest, never consumed. Canonical build IDs seal the
immutable complete build/gap content, not paths or scan order.

These are two distinct sets and domains, never aliases. The per-reference
`backing_canonical_build_ids_digest` is used ONLY in `row_reference_id` and
`gap_proof_id`. The invocation-wide `considered_canonical_build_ids_digest`
is used ONLY in decision/association and any invocation-wide audit identity.
Even when the member IDs happen to coincide, the domain-separated digests
are different; neither may be substituted for the other.

For example, with considered builds A,B,C,D and a selected row backed only
by B,D, the row reference binds `S("cross-day-backing-canonical-builds-v1",
[B,D])`, while the decision binds `S("cross-day-considered-canonical-builds-v1",
[A,B,C,D])`. Adding unrelated considered C to an invocation considering A,B,D
changes decision/association identity but not that row reference. Adding an
additional identical backing build E changes that row reference, and hence
downstream decision/value identities; E also joins the considered set.
The same per-proof rule applies to exact Canonical gap evidence. A build
that does not back the exact admitted row/proof cannot enter its backing set.

### 9.4 Decision

```text
decision_id = H("cross-day-label-decision-v1", {
  schema_version:"cross-day-label-association-v1",
  pit_contract_version:"cross-day-label-pit-v1",
  sample_key, bar_sample_version_id, label_spec_pin_id, schedule_pin_id,
  dataset_as_of, code, interval, adjustment, requested_session, feature_window_close,
  anchor_canonical_row_version_id, anchor_market_calendar_date,
  anchor_event_time, anchor_slot, anchor_row_reference_id,
  required_slots_digest: S("cross-day-label-required-slots-v1", slot_ids by offset),
  considered_canonical_build_ids_digest,
  selected_rows_digest: S("cross-day-label-selected-rows-v1", row_reference_ids by offset),
  rejected_archive_rows_digest: S("cross-day-label-archive-rejected-v1", row_reference_ids by offset),
  absence_proofs_digest: S("cross-day-label-gap-proofs-v1", gap_proof_ids by (offset,ID)),
  status, reason_code, archive_limited, actual_label_end_time
})
```

Required slots retain all required dates/times, even a non-fitting early-close
slot; selected rows mean the actually consumed subset defined in section 6.
Considered build IDs include Feature closure and every supplied Label build,
including proof-only/diagnostic builds; no hidden proof input. Missing anchor
sets its version/reference IDs null, not a fabricated ID. `archive_limited`
is true iff at least one required row was rejected by A, independently of
which reason wins precedence. COMPLETE has reason=null and all required rows.

### 9.5 Sample binding and association content

```text
sample_binding_id = H("cross-day-label-sample-binding-v1", {
  sample_key, bar_sample_version_id, multi_source_sample_version_id, schedule_pin_id,
  decisions_digest: S("cross-day-label-binding-decisions-v1", decision_ids by label_spec_pin_id)
})
association_content_id = H("cross-day-label-association-content-v1", {
  schema_version:"cross-day-label-association-v1",
  pit_contract_version:"cross-day-label-pit-v1", schedule_pin_id,
  label_spec_pins_digest: S("cross-day-label-spec-pins-v1", sorted label_spec_pin_ids),
  considered_canonical_build_ids_digest,
  decisions_digest: S("cross-day-label-decisions-v1", decision_ids by (sample_key,label_spec_pin_id)),
  sample_bindings_digest: S("cross-day-label-bindings-v1", sample_binding_ids by sample_key)
})
```

`multi_source_sample_version_id` is null for L2 bar-only execution, or exactly
the independently verified A3 binding when supplied; L3 multi-source cohort
requires the latter. It is never recalculated with schedule/Label facts.
Zero samples has empty decision/binding sequences but still binds the
explicit schedule, nonempty specs and supplied authority.

### 9.6 Value and values content

```text
value_id = H("cross-day-label-value-v1", {
  execution_contract_version:"cross-day-label-execution-v1",
  sample_key, bar_sample_version_id, multi_source_sample_version_id,
  label_name, label_spec_pin_id, implementation_pin_id, schedule_pin_id, decision_id,
  anchor_canonical_row_version_id,
  consumed_rows_digest: S("cross-day-label-selected-rows-v1", consumed row_reference_ids by offset),
  status, value, reason_code, actual_label_end_time
})
values_content_id = S("cross-day-label-values-v1", value_ids by (sample_key,label_spec_pin_id))
```

The anchor/consumed/status/reason/end fields exactly equal the corresponding
decision, and decision/spec/schedule/implementation linkage is verified before
execution. COMPLETE has finite exact scalar and null reason; INCOMPLETE has
null value and the decision's reason, while retaining the eligible consumed
subset. Selected version or schedule change therefore changes value identity
even when the numeric answer does not. Empty sequence identity is real, not
a null/zero placeholder. No old identity domain is changed.

## 10. Literal Known-Answer Vectors

The six fixture cases below are offline synthetic Canonical/evidence inputs,
not provider/exchange validation. Geometry uses the frozen qualified profiles.
Opaque 64-hex upstream IDs in these encoder fixtures are declared constants,
not instructions to accept unverified runtime data. Runtime canaries must
construct real verified input closures separately.

### 10.1 Complete fixture recipe

These are SIX scenario vectors, 42 scenario digest assertions, 10 supporting
spec/fingerprint digest assertions and one empty-content assertion (53 total).
Each scenario is a separate invocation with one sample and one spec. There
are no implicit dates: the daily-record table is the complete schedule.
`N` expands to TRADING/NORMAL, `E` to TRADING/QUALIFIED_EARLY_CLOSE, and `C`
to CLOSED with three null geometry fields. Coverage endpoints are its first
and last civil date. Date cells become typed `date` values. Convert local
US session times to aware UTC datetimes BEFORE H; do not hash display strings.

Common scalar constants (repeat means literal repetition, not H):

```text
sample_key = "a" repeated 64
bar_sample_version_id = "b" repeated 64
considered_canonical_build_ids = ["c" repeated 64]
each reference's backing_canonical_build_ids = ["c" repeated 64]
anchor_canonical_bar_key = "d" repeated 64
anchor_canonical_row_version_id = "e" repeated 64
multi_source_sample_version_id = null
source_snapshot_id = "1" repeated 64
source_content_hash = "2" repeated 64
coverage_completion_evidence_id = "3" repeated 64
schedule_schema_version = trading-day-schedule-v1
calendar_contract_version = cross-day-us-rth-calendar-contract-v1
normalization_version = trading-day-schedule-normalization-v1
market = US; market_timezone = America/New_York; requested_session = RTH
coverage_complete = true
archive_available_at = 2025-12-31T00:00:00.000000+00:00
dataset_as_of = 2026-01-01T00:00:00.000000+00:00
code = US.AAPL; interval = 5m; adjustment = NONE
archive_limited = false
rejected_archive_rows = []; absence_proofs = []
```

The archive instant above applies to schedule, anchor and every selected row.
Anchor event = first date's open + slot*5 minutes; Feature close and anchor
market availability = anchor event +5 minutes. Its row-reference offset=-1.
At each required offset k, selected row key is integer 100+k formatted as
64-character lowercase hexadecimal with zero padding; row version uses
integer 200+k the same way (offset 0: key ends `64`, version ends `c8`;
offset 1: key ends `65`, version ends `c9`). All reference backing IDs use
the single c*64 build. These fixture sets have equal members but MUST use
their two distinct section 9.3 digest domains. Selected row event is its
slot event, market availability is event +5 minutes. Non-fitting slot has
NO selected row.

All normal opens/closes are local 09:30/16:00. Early close is local 13:00.
Session times in UTC are thus 14:30/21:00 (EST), 13:30/20:00 (EDT), or
14:30/18:00 (the qualified early-close EST dates below). All microseconds
are zero. CLOSED records have no times. Required slots include only the
offsets from the spec. Value is actual float `0.25` for COMPLETE forward,
actual float `0.5` for COMPLETE excursion, null for INCOMPLETE. These follow
anchor.close=80.0, forward target.close=100.0, and excursion high=100.0 then
120.0 (anchor.high=80.0 and point closes=96.0 then 112.0); unused numeric
columns do not enter these identity fixtures directly, their upstream row
IDs stand in for them. No transform is called in the incomplete fixture.

Status=COMPLETE/reason=null except early_close_outside, where status=
INCOMPLETE and reason=ALIGNED_SLOT_OUTSIDE_SESSION. Actual end is last
selected row availability, or null. Binding, association and value payloads
are exactly section 9 using these facts; each per-sample sequence is singleton
except the excursion's two slot/row references. All omitted collections in
this recipe are explicitly the empty collections above, not hidden fields.

Two exact existing LabelSpec fixtures, with requirements
`canonical_schema_versions=("market-bars-canonical-schema-v1",)` and
`source_schema_versions=("10.9-mv-ts2",)`, version `v1`, schema
`market-vault-label-spec-v1`, kind derived LABEL, parameters empty,
output.name=spec.name, float64/nonnullable, FEATURE_CLOSE_ALIGNED,
missing policy INCOMPLETE, and allow=true/SAME_REQUESTED_SESSION_BAR_SLOT:

| Spec | transform_ref | input fields | horizon | observation offsets |
| --- | --- | --- | --- | --- |
| cd_return_1d | market_vault.dataset.label_transforms.forward_return:forward_return | close | TRADING_DAYS/1 | TRADING_DAYS/0/0 |
| cd_mfe_2d | market_vault.dataset.label_transforms.maximum_favorable_excursion:maximum_favorable_excursion | close,high | TRADING_DAYS/2 | TRADING_DAYS/0/1 |

Literal supporting digests, using the base's frozen transform module source
and exactly section 7's fingerprint record:

```text
cd_return_1d.spec_content_id=24a51fc0571178f9ec9427f4efb9a11b94203224858c22685f9001472d1e3d3f
cd_return_1d.spec_pin_id=e6aa62e8bc6eb55b982726a4705563fdf037f47e2ba764e603cf4121ace32d1b
cd_return_1d.implementation_source_sha256=1c898213eedfbfa2055d1d8fe0b69174341d0741b616aa6409581fb012efb705
cd_return_1d.implementation_fingerprint=01baec853ca344d36c3dcdf6db3a7573cc0c2b7c382ea345cacb05e90345a6c1
cd_return_1d.implementation_pin_id=0befd4a9a4d6a1a3b2c47bd13d88d98eedd252dcdc6c88e63035037a9a1aef94
cd_mfe_2d.spec_content_id=01f5e037321de5658f5663ecb5b32f6dcf43e8a65990befd04974a7e6abe569b
cd_mfe_2d.spec_pin_id=d3a2019e74a63eb831367b1de0899dcd3d651940127f0d09b211391cf4ad3394
cd_mfe_2d.implementation_source_sha256=5dc08788468c032a842fb4c978f38f7d73672127e159c7002539b373076dcf93
cd_mfe_2d.implementation_fingerprint=44427fafe75ab0e395f9a277c8b4ec2db42be7887d6e09b70c80495411c16354
cd_mfe_2d.implementation_pin_id=8d0adca923e88533720d96cb4405c7b40a22f35206b7e1acdbc6970f62ea711c
empty_values_content_id=09eaf5af35f95b39ceebc880cec24e1f9c15dfbf5176a9b5c18c4e43cb6b0c41
```

### 10.2 Six scenario known answers

| Scenario | Complete daily records | Slot | Spec | Anchor event -> required events (UTC) | End / value |
| --- | --- | --- | --- | --- | --- |
| normal_forward | 2025-03-03 N; 03-04 N | 1 | cd_return_1d | 03-03 14:35 -> 03-04 14:35 | 03-04 14:40 / 0.25 |
| weekend_forward | 2025-02-07 N; 02-08 C; 02-09 C; 02-10 N | 1 | cd_return_1d | 02-07 14:35 -> 02-10 14:35 | 02-10 14:40 / 0.25 |
| dst_forward | 2025-03-07 N; 03-08 C; 03-09 C; 03-10 N | 1 | cd_return_1d | 03-07 14:35 -> 03-10 13:35 | 03-10 13:40 / 0.25 |
| early_close_fit | 2025-11-26 N; 11-27 C; 11-28 E | 1 | cd_return_1d | 11-26 14:35 -> 11-28 14:35 | 11-28 14:40 / 0.25 |
| early_close_outside | 2025-11-26 N; 11-27 C; 11-28 E | 48 | cd_return_1d | 11-26 18:30 -> 11-28 18:30 (does not fit) | null / null |
| two_day_excursion | 2025-03-03 N; 03-04 N; 03-05 N | 1 | cd_mfe_2d | 03-03 14:35 -> 03-04 14:35, 03-05 14:35 | 03-05 14:40 / 0.5 |

Each abbreviated date above inherits year 2025, not the execution year.
Normal/weekend/DST/early-close fixtures all require offset 0 only; excursion
requires offsets 0,1. Exact literal expected digests:

```text
[normal_forward]
schedule_content_id=67ea16fb43732c78e2788b3ffc110fc312adada93d947a9c3a8037502021db97
schedule_pin_id=f30ca764e588ed71a8c566b5168372b96e9cfd299341153883001d90c9eebf59
decision_id=77803870ab9ea1421d52cc1048fbae5fa6a922e8effb6be6c112c1986d62e8f8
sample_binding_id=a8713202ac7a91caef0271a20d3406d0a4b7a3a3a5478db61c79905a76dcf1b6
association_content_id=e48ce76a7d50260d63b9523a3987e32100ccc197fe75b04bdadbee1f8d0e1496
value_id=e99f98535617ab49d59837f3b3022127ec71ebf64d4cdae344fe875f4170042e
values_content_id=f14a39c92faacf484959f01c787678c3153cc2f07b836973349944fd462ce375

[weekend_forward]
schedule_content_id=bd32dfce1e05f35cdd9640170e702b85935d73514e0e63f5e225dfec71a4746f
schedule_pin_id=c6b7c28974a8782e739604351b14eec8d8c3417f75cccb88ceb75e7294ad4698
decision_id=a95200a8ac494e72d1f4682703b13900f055624eaadd9fdbc8cd0083681ea623
sample_binding_id=83573d2409740e37e749de1d903efd790a61f83b201d19cfda008aa6e4431246
association_content_id=1509cb6490291730fadd83a70203073ecd0f17585b7844074177fb0c552b7849
value_id=821bac62ff8b8ada182957c37e9ac1be41d8a0dee42037c5970adb6713b47fb3
values_content_id=21b017b87b76474b3df882ffc0d0ceb8dc74c285877d6cff7c247d12bee6bfee

[dst_forward]
schedule_content_id=454a7c2d7f5606a4d35ead2e910734ea747803852301a2dd2c4f71f0bf64760a
schedule_pin_id=7396839cea714c5dd74fe78265cf0c3919b342ecd36e71a27210f26c9364d016
decision_id=c38a66980cd52455a94f1826e96b7c1ff7179cb6b4f58f9ae8588f544580297f
sample_binding_id=5c3cd0018fe9b863439621b8a8a8d379ac5c923165a94c6c7c74abcf4807a07b
association_content_id=740167306227bf0bb550ac2ae3b5fa5ebed27cce155ca1a4eb7d74daf3ac27a8
value_id=c22426a36bfe3e684ac8a80912bf4802e940a373af9047154c922744faed24f0
values_content_id=f30a8c6c29ad2a367c79bfc1f136270e014da8ae66941439552e6346c6efba12

[early_close_fit]
schedule_content_id=f3abdf136b1eafb13dfde7c282b52b3f4864fc794b2788b520554cae7f45e55b
schedule_pin_id=53083b15124ecafaaee848bbbb2c313be017789fd5869c69ad5281006ea741be
decision_id=dc563bfb2fa5d46ebd05528240b6b3d388a0e5cbeb0faabc0117c4f0c832223d
sample_binding_id=e72b0974ae1a17d6675ce679659066950ec02920d659dbe2e409d494a3bd636d
association_content_id=3b40666940ef6c946a021cca338d01f35f5c93b8b66764166bd8f7d241d987d5
value_id=67236c30a5b8623c2d26c13c87983f52245defb6c73e5e5cd2abcb0cedf45f32
values_content_id=042e5cbdfd936ddd2e12dcc6c1ce5aafdcfe71cc9f2221b08755acd0ef5ff2d6

[early_close_outside]
schedule_content_id=f3abdf136b1eafb13dfde7c282b52b3f4864fc794b2788b520554cae7f45e55b
schedule_pin_id=53083b15124ecafaaee848bbbb2c313be017789fd5869c69ad5281006ea741be
decision_id=891b2a4cb2217413f19de0f0547d53cd92011eb2cd267c79e4597e612c3c9234
sample_binding_id=23a6b95c65d3e235e9d0de8730cab7f6aa97d014c8855c826eb06a80858a5e77
association_content_id=a16514868565d9292ff26259c9fe70d6419e02cd48960842991e89693a79478c
value_id=a78300c94c2b96146e095a75541323861f180c68a5a2502286b03d8168735a78
values_content_id=35bbaa011e49c573e0af9b4ab3b7b1736e623937b4a283d0d835f6a54e4989cc

[two_day_excursion]
schedule_content_id=8838e4b875dc645d00e5c5c5bce328e8a1d88445aac0edeaa244b56a280d3f9f
schedule_pin_id=eef0dae7db5c40db169faf2b7efb6abc0e1bd32424e210061bbd9f7f67b6b220
decision_id=e1b43ca21246a732277a17ae8c1b2d2b1871d028f26f5d119ae9fcea94c6d695
sample_binding_id=d113ee779d336df4f57eeaa6de2a844bd873eb7514a9e2243d00e9539add04dc
association_content_id=33f61b63bb6dae600e664aa910b01980417f832d6631237f7e609820762fef69
value_id=35667712e0ebefe26c52bb7ce76a569019ac2837b220eb2a60e29529318c6cb2
values_content_id=86f71d44839d550cbb7a8b451232183d51a8f06779c7bf2e94b68d89d642f42a
```

Future tests copy these literal expected values, not generate expected hashes
at test time. The one-off calculator used the existing v1 encoder and stayed
outside the repository under D:. These are design evidence, not an L2 runtime
or verified-artifact implementation.

## 11. Future Dataset and Generator Boundary

L3 requires a separately reviewed TS2-compatible Feature-side authority
before a full bar + Observation + Cross-Day Dataset can be implemented.
The sealed old A4 bar Feature executor/registry cannot directly consume TS2.
The future authority must be parallel/additive, without modifying A4's old
Feature registry, pins, identities, manifests or readers. Its exact design
belongs to L3 design/preflight, not L1 implementation. Without that approved
authority, L3 implementation fails its precondition; no fallback to legacy
`10.9` or widening of the old registry is permitted.

```text
L3_TS2_FEATURE_AUTHORITY_PRECONDITION=true
OLD_A4_FEATURE_REGISTRY_CHANGED=false
```

L3 also requires a NEW `multi-source-cross-day-dataset-id-v1` cohort and
separate manifest/reader discriminator, never truncation into A4's Dataset
ID. Its future exact payload must bind the separately reviewed TS2-compatible
Feature-side authority, unchanged multi_source_sample_version_id semantics,
schedule pin, Cross-Day association, values, implementation pins, sample
audit and existing split facts. This design does not invent an A4
orchestration result with dummy BARS Labels. Keep A3/A4.1 contracts and old
A4 builders/readers untouched; L2's feature-only TS2 PIT remains valid
without executing old bar Feature transforms.

Existing `multi-source-dataset-manifest-v1`, `multi-source-dataset-id-v1` and
`multi-source-dataset-parquet-v1` remain valid. Old readers reject the new
cohort. No artifact rewrite/migration. Physical Cross-Day layout, writer,
reader and destructive authority are not granted here.

The old Sample Generator remains BARS-only. A separate future Cross-Day
entrypoint emits feature-only PIT requests (`label_window=None`) with explicit
schedule and all-TRADING_DAYS specs. For EVERY proposed anchor, coverage must
reach the maximum requested horizon including every intervening civil date.
Insufficient schedule coverage is a configuration/authority failure for the
invocation, never a silently dropped tail or a calendar inferred from bars.

`MoomooCalendarCollector` is acquisition only. `normalize_trading_calendar`
output alone is not VerifiedTradingDaySchedule. No DuckDB/current calendar
state is promoted. All Label assembly/execution is offline with zero provider,
OpenD, network, settings, artifact/spec reads, discovery, current-time or
environment authority; only the section 7 static source-fingerprint read is
allowed at registry construction. No filesystem writes. Relocation of
identical Canonical/schedule artifacts cannot affect IDs: no path, cwd, mtime
or output root participates.

## 12. Future Offline Canaries

These are design obligations, NOT implemented tests in L1. Preserve all
unchanged legacy runtime literal vectors; the rejected L1 candidate's vector
literals are historical only and are superseded by corrected section 10.
The first 58 obligations are retained; additional canaries close the TS2
cohort and distinct build-set identity roles.

1. Old LabelSpec content IDs remain identical for identical old inputs, including old TRADING_DAYS representations; changing a new Cross-Day spec's source requirement to TS2 changes its content ID/pin.
2. Old BARS execution and implementation pins remain unchanged.
3. Old PIT sample keys/versions and association IDs remain unchanged.
4. MINUTES fails before transforms, including zero samples.
5. TRADING_DAYS requires explicit allow=true.
6. Any other boundary rule fails before transforms.
7. Mixed-unit spec sets fail as a whole, with zero transform invocations.
8. Complete schedule contains every civil date inclusive.
9. Missing date fails schedule admission.
10. Duplicate date fails even for identical daily records.
11. Schedule archive bound after A is authority failure; equality is eligible.
12. Missing exact anchor produces MISSING_ANCHOR_ROW, no older substitute or transform.
13. Anchor-slot non-divisibility or invalid anchor session fit fails geometry.
14. DST fixture preserves slot 1 while UTC event time changes by one hour.
15. CLOSED weekend/holiday dates are skipped only from explicit schedule records.
16. Unrepresented date is never treated CLOSED.
17. Forward N selects only offset N-1, not N-th observed date.
18. Missing unneeded intermediate bars do not invalidate a proven forward target.
19. Proven absent forward endpoint yields MISSING_TARGET_ROW; no transform.
20. Excursion consumes one aligned point per required TRADING day, not whole sessions.
21. Excursion missing first point with present endpoint yields INSUFFICIENT_ROWS.
22. Excursion missing interior point with endpoints present yields NON_CONTIGUOUS_TRADING_DAY_ROWS.
23. No interpolation, fill, date skip, nearest or alternative-slot substitution.
24. Qualified early-close slot fitting full nominal interval works.
25. Non-fitting qualified early-close slot yields ALIGNED_SLOT_OUTSIDE_SESSION.
26. Early-close failure never moves the target earlier/later.
27. Unqualified special geometry and listed-day NORMAL misclassification fail closed.
28. Requested-session mismatch fails; no ALL/RTH equivalence assumption.
29. Adjustment other than NONE fails, even if prices look unadjusted.
30. Unsupported interval/market fails before sample execution.
31. Archive-future exact target is unconsumed and ARCHIVE_FUTURE is recorded.
32. Unproved Canonical slot/date coverage fails authority, not INCOMPLETE.
33. Exact archived same-scope internal gap with verified boundaries supports missing-slot INCOMPLETE.
34. Actual end is the last consumed row's market_available_at, including diagnostic subsets.
35. Split uses actual end only; changing a nominal horizon without changed consumption cannot substitute purge time.
36. Each schedule field/proof/clock mutation changes schedule content and pin.
37. Schedule mutation changes association even if chosen numeric rows coincide.
38. Selected row-version mutation changes decision/value/content identity even if value is equal.
39. Reordering builds, specs, requests and schedule input records preserves normalized IDs.
40. Relocation preserves semantic identities; no path/mtime/cwd authority.
41. Schedule never reaches Feature or numeric Label transform inputs.
42. Future Label/schedule-only change leaves multi_source_sample_version_id and Feature values unchanged.
43. A3/A4.1 source-selection and Feature identities remain unchanged.
44. Old A4 Dataset IDs/readers remain unchanged; new cohort is rejected by old readers.
45. Zero provider/network/OpenD calls across generation, assembly and execution.
46. Every literal vector in section 10 matches, including empty values content.
47. Zero samples still rejects unknown transforms, invalid schedule and mismatched evidence.
48. Invalid/unproved target authority fails before a missing-anchor incomplete result.
49. Multiple incomplete causes follow section 6 precedence without dropping proof obligations.
50. Distinct conflicting Canonical versions fail before archive filtering; no timestamp winner.
51. Gap boundaries archived after A cannot prove absence; leading/trailing/EMPTY-only evidence fails.
52. Numeric call counts are one per COMPLETE value and zero per INCOMPLETE value.
53. Unbounded horizons fail finite schedule-capacity admission without huge allocation/arithmetic.
54. Tail-generator schedule deficiency fails the invocation instead of dropping samples.
55. Only static registered module source fingerprint reads are allowed; zero artifact/spec/directory reads or writes.
56. Old BARS ImplementationPins cannot stand in for Cross-Day pins; source/call-contract change changes value identity.
57. Missing/extra/duplicate bindings or forged IDs fail result validation; considered proof-only builds remain identity-bearing.
58. Empty consumed subset has null end; missing anchor consumes none; sample end is max of non-null value ends.
59. Cross-Day admission, spec requirements and implementation fingerprints admit exactly TS2 source schema `10.9-mv-ts2`, including feature-only L2.
60. Legacy `10.9` fails Cross-Day admission before transforms, including zero samples.
61. Old BARS `10.9` Feature/Label registries, executors, pins and identities remain unchanged; no widened supported source schemas.
62. Qualified early-close geometry cannot authorize legacy `10.9` rows/proofs; only the TS2 cohort can use this Cross-Day geometry.
63. L3 refuses implementation without separately reviewed parallel/additive TS2 Feature-side authority; the old A4 Feature registry is not a substitute.
64. Adding unrelated considered C to A,B,D changes decision/association identity while a row backed only by B,D keeps its row_reference_id.
65. Adding identical backing build E to that row changes its row_reference_id and downstream decision/value identities even if numeric value is unchanged.
66. Per-row/per-gap backing sets and invocation considered sets cannot be substituted; equal member sets still yield different domain-separated digests.

DESIGN_CANARY_COUNT=66.

## 13. Phases and Non-Goals

| Phase | Scope | Authority |
| --- | --- | --- |
| L1 | this semantic design freeze only | design PR; no merge authorization |
| L2 | TS2 feature-only PIT, verified logical schedule and Label sidecar/executor; no old bar Feature transforms | not authorized |
| L3 | separately reviewed TS2 Feature authority precondition, separate generator and new Cross-Day Dataset cohort/identity | not authorized |
| L4 | optional immutable schedule artifact/provider acquisition integration | not authorized |

Each phase needs separate authorization after independent post-merge closure
of the preceding phase. No source/tests/scripts/CI/governance-contract/version
change in L1. No provider acquisition, Catalog, CLI/UI, PyPI/TestPyPI,
production/OpenD, QFQ/HFQ/corporate actions, MINUTES, all-session-bars
excursions, custom transforms, ML, backtests, signals or trading.

The historical A1 C:-temp breach, initial A4.2 contract-precondition FAIL,
first PR #165 review FAIL and first PR #166 review FAIL remain historical
facts. They are not relabeled by this design PR. L1 development output is
D:-bound; reading supplied instructions is not development output.

PR #167's initial independent semantic review of
`81b1f5d1ab346a3af063d441dc77a5be370a4a2f` (tree
`b51f938f5699b398399bd5ab984ab19ef2a14ff1`) was FAIL, with blockers
`LEGACY_10_9_SOURCE_SCHEMA_CONFLICTS_WITH_TS2_RTH_AND_EARLY_CLOSE_AUTHORITY`
and `CANONICAL_BUILD_SET_DIGEST_ROLE_AMBIGUITY`. That rejected head's vector
literals and CI run `35118471807` remain historical evidence for that head
only. This narrow correction regenerates the affected vectors for TS2 and
the distinct backing/considered domains; it does not relabel the old review
PASS. New exact-head CI and independent semantic re-review are required.

Validation: diff whitespace, repository hygiene, release checker, destructive
repository inventory (unchanged 5 contracts / 16 exemptions / 42 surfaces).
One docs file should naturally classify docs_fast; classifier is unchanged.
No runtime tests are claimed by this design PR. Natural exact-head CI must
complete successfully before independent review. Do not merge or start L2.
