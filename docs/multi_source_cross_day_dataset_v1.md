# Multi-Source Cross-Day Dataset V1

## 1. Status and Base Authority

DESIGN / PREFLIGHT ONLY. Candidate for independent semantic review, not
implementation, merge, production, or destructive-operation authorization.

```text
BASE_MAIN_SHA=b907524b59c827157540aff85324afafdc264c5e
BASE_MAIN_TREE=40f391945cd3a0ec58d65942d2f718b20144bad7
SELECTED_ARCHITECTURE=PARALLEL_MULTI_SOURCE_CROSS_DAY_DATASET_COHORT
VERSION=0.8.0
```

All references to existing source records, helpers, algorithms and field sets
in this document are pinned to BASE_MAIN_SHA above, not to future HEAD. The
normative upstream designs are `cross_day_trading_days_label_v1.md`,
`cross_day_ts2_feature_authority_v1.md`, `observation_pit_sidecar_v1.md`, and
`multi_source_dataset_cohort_v1.md`. L1, L2, TS2 Feature, and A1-A4 are sealed.
This document resolves the previously deferred Dataset join; it does not
retroactively mark an upstream deferred implementation canary implemented.

## 2. Architecture and Versions

The future package is `market_vault.cross_day_dataset`, parallel to both
`market_vault.dataset` and `market_vault.multi_source`. Old authorities must
not import it back. It joins supplied verified facts, performs one unchanged
chronological split, derives a new matrix/audit/identity, and returns one
deeply immutable result. There is no hidden sample generation.

| Contract | Frozen value |
| --- | --- |
| Dataset ID | `multi-source-cross-day-dataset-id-v1` |
| Orchestration | `multi-source-cross-day-dataset-orchestration-v1` |
| Manifest | `multi-source-cross-day-dataset-manifest-v1` |
| Serialization | `multi-source-cross-day-dataset-parquet-v1` |
| Materializer | `multi-source-cross-day-dataset-materializer-v1` |
| Reader | `multi-source-cross-day-dataset-reader-v1` |
| Build report | `multi-source-cross-day-build-report-v1` |
| Sample audit | `multi-source-cross-day-sample-audit-v1` |
| Generator | `multi-source-cross-day-sample-generator-v1` |

Serialization format is `parquet`; this version also defines the JSON
sidecars in section 20. Writer/reader/report versions are physical validation
contracts, not additional Dataset ID fields. The manifest and serialization
versions DO enter Dataset ID. No package version bump is authorized.

## 3. Sealed Authorities and Admission

| Authority | Admission |
| --- | --- |
| Canonical | `market-bars-canonical-schema-v1`, source **only** `10.9-mv-ts2` |
| Scope | `DatasetScope`, nonempty symbols/dates, US.* / RTH / NONE, interval 1m, 5m, 15m, 30m or 60m |
| Feature PIT | exact `PITAssemblyResult`, all requests feature-only; both Label window fields null and all Label selections/gaps/counts empty/zero |
| TS2 Features | exact issued `TS2FeatureExecutionResult`, all eight actual registry pins |
| Observation PIT | exact issued `ObservationPITAssemblyResult`; real A3 binding mandatory |
| Observation Features | exact `ObservationFeatureExecutionResult` and full `ObservationFeatureSpec` records |
| Cross-Day Labels | exact `CrossDayLabelAssemblyResult` and `CrossDayLabelExecutionResult`, TRADING_DAYS / SAME_REQUESTED_SESSION_BAR_SLOT |
| Schedule | exact `VerifiedTradingDaySchedule`, US/RTH/America/New_York, complete civil-date inventory |
| Split | exact `ChronologicalSplitSpec`, unchanged algorithm and fixed policies |
| Cutoff | explicit aware UTC-microsecond `datetime` or explicit null; no default |

Each of the TS2 Feature, Observation Feature and Cross-Day Label spec families
must be nonempty, including zero-sample invocations. This is a new cohort
admission rule, not a change to TS2's legal zero-spec result. Zero requests
are legal. Scope still must be nonempty; no empty Cartesian scope loophole.
Unknown, mixed or legacy Canonical source schemas fail, including unused
supplied builds. Adjustment remains NONE; MINUTES Labels remain disabled.

Old BARS Feature/Label registry authority remains 10.9 only. No old Feature
executor, old Label executor, A4 orchestrator, old Sample Generator, or old
Dataset reader/writer is used as this cohort's authority. Existing Dataset,
multi-source-dataset-id-v1, multi-source-dataset-manifest-v1 and
multi-source-dataset-parquet-v1 keep their exact meaning: ZERO migration,
rewriting or re-identification. Old readers reject the new discriminator;
the new reader rejects old discriminators. No dispatcher is authorized.

## 4. Exact Future Inputs and Result

```python
join_multi_source_cross_day_dataset(
    *,
    feature_pit: PITAssemblyResult,
    ts2_features: TS2FeatureExecutionResult,
    observation_pit: ObservationPITAssemblyResult,
    observation_builds: tuple[VerifiedObservationBuild, ...],
    observation_feature_specs: tuple[ObservationFeatureSpec, ...],
    observation_features: ObservationFeatureExecutionResult,
    cross_day_association: CrossDayLabelAssemblyResult,
    cross_day_labels: CrossDayLabelExecutionResult,
    schedule: VerifiedTradingDaySchedule,
    scope: DatasetScope,
    split_spec: ChronologicalSplitSpec,
    dataset_as_of: datetime | None,
) -> MultiSourceCrossDayDatasetResult
```

Existing types come respectively from dataset.pit_models, ts2_feature.models,
observation.pit_models, observation.artifact_models, multi_source.feature_spec_models,
multi_source.feature_models, cross_day.assembly, cross_day.execution,
cross_day.schedule, dataset.models and dataset.split_models. No ID-only
alternative or path overload exists. Feature and Label specs are taken from
their complete supplied results. Canonical evidence is taken from the
association's explicit `feature_builds` and `label_builds` tuples of
`VerifiedCanonicalBuild`; a second caller-selected Canonical boundary is not
accepted. Observation evidence is supplied separately because A3 does not
store full A2 rows/snapshots.

Exact result fields are: `identity_input`, `dataset_id`, `scope`,
`dataset_as_of`, `schema`, `rows`, `sample_audit`, `completion`, `split_result`,
`feature_pit`, `ts2_features`, `observation_pit`, `observation_builds`,
`observation_feature_specs`, `observation_features`, `cross_day_association`,
`cross_day_labels`, `schedule`, `status`. Rows are tuples of exact scalars in
schema order; all collections are detached immutable tuples/records. Status
is COMPLETE iff row count > 0, otherwise EMPTY; it does not claim Label or
scope completion. No PARTIAL result escapes an authority failure.

The join is the sole live-result issuer. Direct construction,
dataclasses.replace, caller tokens, source hashes, callbacks, registries or
ImplementationPins cannot issue a trusted result. Invocation-private context
binds the admitted input records, real registries, structural comparisons,
split output and derived matrix/audit/identity. Deserialized records are NOT
live TS2/A3 issuance tokens. The future reader issues its own separate
`VerifiedMultiSourceCrossDayDataset`, never a forged upstream result.

`MultiSourceCrossDayDatasetIdentityInput` is a pure typed declaration, not a
trust entrypoint. Exact fields: `scope`, `dataset_as_of`, `schema`, `rows`,
`canonical_builds`, `canonical_build_pins`, `gap_references`, `feature_pit`,
`ts2_features`, `observation_pit`, `observation_builds`,
`observation_input_proofs`, `observation_feature_specs`,
`observation_features`, `cross_day_association`, `cross_day_labels`, `schedule`,
`split_result`, `sample_audit`, `completion`. These contain the full logical
records or validated recorded projections described here, not opaque hashes.
Its identity function validates closure and derives section 17; it cannot
grant runtime issuance authority or run any upstream computation.

canonical_builds is the complete union of logical Canonical projections;
observation_builds is the complete A2 logical projection sequence. The pin/proof
fields are recomputed assertions of these records, not substitutes for them.

## 5. Exact Join Closure and Order

The following order is normative; no stage repairs, reselects or executes an
upstream result. Normalize input container ordering only after rejecting
duplicate semantic inputs. Normalize instants with the existing encoder.

1. Check exact input types, explicit cutoff, nonempty spec families and scope.
2. Validate complete nested specs, output contracts, cross-family names and
   fixed registration/fingerprint bindings, including unused TS2 registrations.
3. Verify schedule content/pin and its archive gate; compare all schedule copies.
4. Validate every Canonical build, normalized request, row ID, source pin,
   content/build ID and internal gap/boundary proof. Reconcile across the union
   BEFORE clock filtering. Same key with conflicting logical facts fails;
   identical rows with additional backing builds retain all backing IDs.
5. Reverify recorded feature-only PIT requests, sample keys/versions, source
   and build pins, selected-row membership/order, associations and diagnostics.
   No PIT selection, winner search, or new PIT requests occur here.
6. Validate the TS2 result and bind it to that exact PIT/evidence/cutoff.
7. Validate complete A2 logical evidence and the A3 recorded closure; verify
   every full proof pin/coverage pair and every selected version reference.
8. Bind Observation Feature specs/results to A3 and their real static pins.
9. Structurally verify the recorded L2 association, exact selected/rejected
   references and gap proofs, schedule geometry and recorded decision reasons.
10. Validate recorded L2 values/pins against those decisions without formulas.
11. Enforce the exact sample and cross-layer equality rules below.
12. Derive audit pre-split facts and Feature eligibility for every request.
13. Invoke `assign_chronological_splits` exactly once on eligible samples only.
14. Derive exact schema, matrix, completed audit and scope completion summary.
15. Recompute all component/content IDs and section 17 Dataset ID; issue once.

There is a nonempty or empty exact common sample-key set K across PIT samples,
A3 sample_bindings, TS2 samples, Observation Feature samples, L2 sample_bindings
and L2 execution.samples. Reject duplicates before set comparison. For K,
exact sample-key -> bar-version mapping equals PIT. TS2 samples and L2
decisions/values/bindings must agree with this mapping. A3, Observation Feature
and L2 values/bindings must agree on each non-null A3 multi-source version.
No missing/extra sample or decision/value is tolerated, even when excluded.
Cross-products are exactly K x the normalized owning spec family.

All Feature association schema/content IDs equal PIT's, including A3's
bar_association_schema_id/content_id and TS2's feature_association fields.
L2's embedded feature_pit must be logically equal to the supplied PIT,
not just SHA-shaped. Its embedded observation_pit equals supplied A3.
L2 execution.association equals the supplied association in all logical fields.
All equality excludes only explicitly non-authoritative paths/physical
manifest metadata, never clocks, rows, proof pins, scope or source identities.

For every sample compare request code, interval, adjustment, requested_session,
anchor_market_calendar_date, feature_window_start/close, cutoff and bar version.
Records without a field must link to its owning PIT request by sample/version;
do not invent an implicit value. L2 decisions explicitly repeat code, interval,
adjustment, requested_session, anchor date and Feature close; compare all.
TS2 values repeat Feature close and cutoff. A3 T equals Feature close and A
equals cutoff. Every PIT sample and L2 association cutoff equals the argument.
The scope's symbol/date Cartesian product contains every requested sample;
interval/session/adjustment are exact. Missing product cells become completion
MISSING, not silently dropped scope.

Feature Canonical build IDs are exactly the TS2 considered set and the L2
feature_builds set. They equal PIT's full explicit build-pin boundary,
including its zero-sample boundary. A PIT per-sample considered set retains
its frozen meaning and need not include unrelated builds. Label/proof builds
are an independent explicit set; L2 considered set is exactly their union
with Feature builds. Duplicate build IDs within a supplied tuple fail; overlap
between Feature/Label roles is legal only for identical full logical builds.
Conflicts fail before availability checks. No globally latest build authority.

Dataset scope.trade_dates names anchor dates, not a truncation boundary for
future Label/proof evidence. Label and diagnostic build dates may extend beyond
it (as vector H does); all build symbols must still be within scope.symbols,
with exact interval/RTH/NONE/TS2 authority. Reject unrelated symbol/session/
interval input rather than silently excluding it from considered identity.

## 6. A3 Binding and Observation Proof Multiplicity

There is no bar-only fallback in this cohort. Recompute existing A3 decision,
Observation binding, multi_source_sample_version_id, sample-binding content,
Observation association content and combined association content identities
using their unchanged payloads; compare all assertions. Copy the verified
multi-source version into the matrix, audit and L2 correspondence checks.
Schedule, TS2 values, Labels and Dataset facts never enter its calculation.

Use the pure A4.1 `verify_execution_inputs` rules for recorded A3 closure, not
`assemble_observation_pit_sidecar`. A proof match key is the COMPLETE
`observation_build_pin_id(replace(pin, selected_observation_version_ids=()))`.
Matching by observation_build_id alone is forbidden. Independently verify
selected membership, full pin ID, coverage ID, snapshot/provider/normalizer/
known-at-authority linkage and exact SourceSpec scope, including typed
dimensions. Preserve every `(BuildPin, Coverage)` pair. Duplicate identical
pair IDs fail within an evidence item; same logical build at distinct
coverage_proof_available_at clocks is valid and remains two proofs.

For every decision, evidence includes exactly the admitted input proofs for
its SourceSpec-bound entity scope, not a selected subset. Coverage freshness,
knowledge-through-T, revision completeness, archive gate and stale extension
retain A3 semantics. Verify recorded selected provenance, membership and
structural proof obligations; do not choose another revision/effective row.
Evidence items are unique `(sample_key, feature_spec_pin_id)`.

Zero samples require an explicit exception to the *invocation of* the A4.1
helper, not a change to its sealed behavior: it rejects unmatched builds when
there are no decisions. For K empty, verify its empty A3/spec closure with an
empty represented-build tuple. Separately admit EVERY supplied A2 build,
require it to match at least one exact embedded SourceSpec, validate its
provider/normalization/policy/coverage, and retain its complete unselected
input proof. Do not pass extra proofs into a helper then weaken that helper.
For K nonempty, each input proof must be represented in applicable evidence;
unmatched extra proofs fail. Input full proof IDs, evidence full selected pin
IDs, and coverage IDs are separately bound in Dataset identity even for K empty.

## 7. TS2 Feature Binding

Only the actual issued TS2 result is accepted by the live join. Recompute its
ten frozen identities and check real fixed registrations/source fingerprints,
spec pins, all eight ImplementationPins, sample/value cardinality and status.
Do not call execute_ts2_features or reconstruct via the sealed result constructor.
The Dataset join separately verifies the complete ordered PIT Feature selection
as upstream PIT authority. For each TS2 Feature value, recorded candidate IDs
must equal exactly the LAST min(N, selected_count) positions of that complete
selection, preserving PIT order, under the owning frozen TS2 registration/spec
window contract. Full selection and candidate rows are distinct facts: every
selected row still requires complete validation; candidates are a spec-specific
trailing projection, not a replacement for that full authority boundary.
Never require candidate == full selection when selected_count > N. They may
be equal only when selected_count <= N.

If selected_count < N, candidates contain all selected positions and the value
is EXCLUDED / INSUFFICIENT_ROWS with empty consumed IDs. Otherwise candidates
contain exactly the trailing N positions: a contiguous tail is COMPLETE with
consumed IDs equal to candidates; a noncontiguous tail is EXCLUDED /
NON_CONTIGUOUS_ROWS with empty consumed IDs. The join performs no new window
selection or TS2 execution; it checks the frozen result against the already
verified full PIT selection, without searching for another window.
Insufficient/noncontiguous reason semantics,
bounded huge-N handling, finite actual float output and negative-zero rules
remain TS2's. No formula is run to validate a supplied numeric result.

Normative non-identity examples (R0/R1/R2 denote selected PIT positions, not
new identity constants):

- A: full PIT selection (R0, R1, R2), window_bars=2, with a valid contiguous
  tail and otherwise admitted facts. Candidates and COMPLETE consumed IDs
  are (R1, R2). Dataset verification must PASS; requiring candidates to equal
  (R0, R1, R2) is forbidden.
- B: full PIT selection (R0,), window_bars=2. Candidates are (R0,), status
  EXCLUDED, reason INSUFFICIENT_ROWS, consumed IDs (). This valid excluded
  result retains the full PIT selection separately.

All selected Feature rows must be in the exact request window/date/scope,
market_available_at <= Feature close and (A null or archive_available_at <= A).
Clock equality is valid. A selected future row is an authority failure, not
EXCLUDED. Check full Canonical/source/provenance closure before clocks. No
fallback to old 10.9 Feature registry/executor or fabricated legacy pins.

## 8. Observation Feature Binding

Derive each ObservationPITFeatureBinding only from the full supplied
ObservationFeatureSpec. Compare exact A3 feature pin ID and SourceSpec ID.
The A4.1 result's own spec/value/pin tuples retain their sealed semantic
(kind, name, version, content_sha256) order. Its content identity separately
sorts by existing A3 `feature_spec_pin_id`, whose domain is
observation-feature-spec-pin-v1, NOT dataset-spec. The new matrix explicitly
uses that A3 pin-ID order for Observation columns; do not rewrite the supplied
result's tuple order. Revalidate the
unchanged two-entry Observation registry, exact used ImplementationPins and
scalar types. Match every value's sample/version, decision_id, status, reason,
consumed_observation_version_id and schema/field extraction to A3/A2 facts.
COMPLETE consumes exactly its A3 selected version; EXCLUDED consumes none and
has null value. STALE/NOT_REPORTED/WITHDRAWN selected references remain A3
evidence, not Feature consumption. Recompute all existing Observation Feature
value and values-content IDs, including excluded outcomes. No executor call.

## 9. Cross-Day Label Binding Without Reassembly

L2's current `replace(CrossDayLabelAssemblyResult)` invokes `_facts`, and its
execution validator rebuilds that association. Those entrypoints are NOT
permitted in this join or reader. Future parallel recorded-closure validators
must compare supplied facts without calling `_facts`, assembly, PIT selection,
or execution. This is an explicit implementation gate; modifying L2 to make
validation easier is forbidden.

Verify the exact existing L2 scalar records and IDs: slot, row reference,
gap proof, decision, sample binding, association and value. For each already
recorded required slot, verify D(k), session-relative anchor slot, exact date,
UTC event and qualified early-close fit against supplied schedule. Each slot
has exactly its recorded eligible row, archive-rejected row, out-of-session
status or exact archived internal gap proof. Verify membership, offsets,
backing sets and boundary rows against full Canonical evidence. Contradictory
rows/proofs fail; do not search for replacements. Check recorded initial
anchor against exact selected Feature slot. Check all L2 incompleteness
precedence, archive_limited, required-slot cardinalities and retained evidence.
This checks a supplied proof, not a fresh winner selection or reassembly.

Recompute `cross-day-backing-canonical-builds-v1` ONLY from exact row/proof
backing builds; use it in row_reference_id/gap_proof_id. Recompute
`cross-day-considered-canonical-builds-v1` from the invocation union; use it
in decisions/association. An unrelated considered build changes the latter,
not a selected row's reference. An identical additional backing build changes
the row reference too. Neither set substitutes for the other.

Cross-Day Label rows have NO market_available_at <= Feature close rule and
NO nominal-horizon/session-close market cutoff. Existing Canonical row
invariants still hold; consumption with A requires archive_available_at <= A.
Decision actual_label_end_time is the last actually consumed row's verified
market_available_at, or null for no consumption, exactly as L2 records it.
Each value equals its decision's reference/status/reason/end facts, with exact
real L2 ImplementationPin and output scalar type. Numeric values are verified
as recorded outcomes, not recalculated formulas.

## 10. Schedule Binding

Recompute the complete `VerifiedTradingDaySchedule` content ID and pin ID.
Require exact normalized daily-record sequence, one record per civil date
inclusive of coverage bounds, explicit CLOSED records, verified normal or
qualified-early-close sessions and correct timezone/DST geometry. Compare the
explicit schedule to both L2 copies, every binding/decision/value schedule
pin, and root identity. If A is non-null, schedule.archive_available_at <= A.
No timezone/calendar/provider lookup may supply missing trading-day records.
The installed explicit timezone rules perform conversion only, not calendar
acquisition. Schedule-only changes leave A3 and TS2 facts untouched.

## 11. Matrix Eligibility and Label Aggregation

For each original sample, `matrix_eligible = (ts2_sample.status == COMPLETE
and observation_sample.status == COMPLETE)`. Exactly those samples appear
in the matrix, even if the chronological split later marks them EXCLUDED or
PURGED. A training consumer must use final_split/assignment_status; physical
matrix presence alone is not training admission. Every requested sample,
including both Feature exclusions, remains in audit and all component facts.

Label sample status is COMPLETE iff ALL requested Label values are COMPLETE,
otherwise INCOMPLETE. Each incomplete output projects to null regardless of
the LabelSpec's non-null logical transform output contract. Aggregate
actual_label_end_time is max of all non-null per-Label actual ends, including
partially consumed incomplete Labels, or null when none consumed. Nonempty
Label family prevents vacuous COMPLETE with no actual end. Compare the exact
L2 aggregate sample result; never infer a nominal horizon end.

## 12. Exact Logical Matrix Schema

Use unchanged `DatasetField` / `DatasetSchema` / dataset_schema_id and
logical_dataset_content_id encoders, not runtime dtype inference. Exact order:

| Position/group | Name | Logical type | Nullable |
| --- | --- | --- | --- |
| 1 | code | string | false |
| 2 | sample_key | string | false |
| 3 | sample_version_id | string | false |
| 4 | feature_window_close | timestamp_us_utc | false |
| 5 | actual_label_end_time | timestamp_us_utc | true |
| 6 | label_status | string | false |
| 7, iff A non-null | dataset_as_of | timestamp_us_utc | false |
| next | TS2 outputs by dataset-spec pin ID | float64 | false |
| next | Observation outputs by existing Feature pin ID | int64 or float64 | false |
| next | Cross-Day outputs by dataset-spec pin ID | int64 or float64 | true |
| next | feature_window_close_date | date32 | false |
| next | nominal_split | string | true |
| next | final_split | string | true |
| next | assignment_status | string | false |
| next | reason_code | string | true |
| last | purge_boundary | timestamp_us_utc | true |

Output names equal owning spec names. Apply existing safe normalized name
semantics before comparison. Reject duplicate names across all three families,
even if types/values coincide. All fixed names above are reserved even when
conditionally absent; also reserve `bar_sample_version_id`,
`multi_source_sample_version_id`, `dataset_id`, `status`, `built_at`, and
`schedule_pin_id`. No numeric/string/bool coercion. IEEE finite float64 and
signed int64 only; normalize -0.0. No inferred nullable Feature column.

Rows sort by (code, feature_window_close, sample_key). sample_key is unique;
matrix sample_version_id is exactly the non-null A3 multi-source version.
The bar version stays separately in audit/PIT, never replaces it. The exact
schema is present even for zero rows. No output column depends on observed
status, except the explicitly cutoff-controlled dataset_as_of column.

## 13. Split Semantics

Exactly one call to unchanged `assign_chronological_splits(samples, split_spec)`
for the eligible sample set, even if empty. Each ChronologicalSplitSample is
(sample_key, A3 multi-source version, Feature close, exact L2 aggregate status,
exact L2 aggregate actual end). The split uses its explicit timezone and
Feature-close date, actual-end purge boundaries, incomplete_label_policy=EXCLUDE
and out_of_range_policy=EXCLUDE. Existing equality/boundary rules are unchanged.
Observation clocks, schedule coverage end and nominal TRADING_DAYS horizon
are never purge boundaries. Retain all assignments, including excluded/purged,
and their schema/content/result IDs. No assignment exists for a Feature-excluded
sample; its split audit fields are all null, not a fabricated split exclusion.

## 14. New Completion Summary

One entry for every (symbol, scope.trade_date), sorted by (code, trade_date).
Exact entry fields are `code`, `trade_date`, `status`, `reason_code`.
No requests in a cell: MISSING / NO_SAMPLE_REQUEST. Otherwise aggregate flags
t = any TS2 EXCLUDED, o = any Observation EXCLUDED, l = any Label INCOMPLETE
over ALL its requests, including Feature-ineligible ones. Priority:

| Condition | Status | Reason |
| --- | --- | --- |
| (t or o) and l | INCOMPLETE | FEATURE_EXCLUDED_AND_CROSS_DAY_LABEL_INCOMPLETE |
| t and o | INCOMPLETE | TS2_AND_OBSERVATION_FEATURE_EXCLUDED |
| t | INCOMPLETE | TS2_FEATURE_EXCLUDED |
| o | INCOMPLETE | OBSERVATION_FEATURE_EXCLUDED |
| l | INCOMPLETE | CROSS_DAY_LABEL_INCOMPLETE |
| none | COMPLETE | null |

Flags may arise in different samples of a cell. Split purge/out-of-range
does not change Feature/Label completion. Exact summary fields are
`complete_count`, `incomplete_count`, `missing_count`, `entries`; counts must
equal the entries. This new vocabulary never reinterprets old CompletionSummary
reason strings. All upstream detailed reasons remain in their owning records.

## 15. Exact Sample Audit

One record per PIT request, including empty Feature selections and matrix
exclusions, sorted by sample_key. This is a new audit record, not an old A4
record with substituted Feature authority. Exact scalar field set:

```text
sample_key bar_sample_version_id multi_source_sample_version_id
code interval adjustment requested_session anchor_market_calendar_date
feature_window_start feature_window_close dataset_as_of
feature_association_schema_id feature_association_content_id
ts2_sample_id ts2_values_content_id observation_binding_id
observation_values_content_id cross_day_sample_binding_id
cross_day_values_content_id schedule_pin_id
ts2_feature_status observation_feature_status label_status
actual_label_end_time matrix_eligible matrix_present
split_feature_window_close_date split_nominal_split split_final_split
split_assignment_status split_reason_code split_purge_boundary
```

Identity fields are lowercase 64-hex; scope/status fields are safe strings;
anchor/split close dates are date32; instants UTC microseconds; matrix flags
actual bools. A and actual end may be null. All six split fields are null
iff ineligible; eligible split nullability is exactly section 12. Other
fields are non-null. Reconstruct the exact PIT request with null Label
window from scope/window fields and verify its sample_key. Recompute the
bar version from full PIT selection/cutoff/considered evidence, not from
audit alone. `matrix_present == matrix_eligible == actual matrix membership`.

ts2_sample_id and per-sample values content are sealed TS2 identities.
observation_values_content_id is existing observation-feature-values-v1 over
this sample's values in Feature pin order. Cross-Day values content is the
existing cross-day-label-values-v1 over this sample's Label pin order.
The A3 binding and L2 binding IDs anchor full decisions/proofs in sidecars.
Thus the audit does not redundantly duplicate numeric values or whole rows.
Its referenced sidecars are mandatory; IDs alone cannot replace missing facts.
Split fields exactly project the corresponding assignment. Build reports
cannot supply missing audit or proof. Empty audit uses the real empty Q digest.

## 16. Exact New Identity Domains

H(domain, scalar_mapping) is the unchanged dataset.encoding.encode_identity
v1, including typed scalars, NFC, UTC microseconds and finite binary64.
There is NO JSON/repr hashing for logical identities. Dates are date values,
not text; times are aware datetime values. Hashes are lowercase 64-hex.

Exactly FIVE new identity domains are introduced:

| Domain | Exact payload |
| --- | --- |
| multi-source-cross-day-sequence-v1 | `{role, count, members}` as Q below |
| multi-source-cross-day-sample-audit-v1 | all and only section 15 scalar fields |
| multi-source-cross-day-completion-entry-v1 | `{code, trade_date, status, reason_code}` |
| multi-source-cross-day-completion-v1 | `{complete_count, incomplete_count, missing_count, entries_digest}` |
| multi-source-cross-day-dataset-id-v1 | exact section 17 payload |

Q(role, IDs) has count = number of normalized members, members = concatenated
fixed-width hex IDs with NO separator. Roles are a closed enum in section 17
plus COMPLETION_ENTRIES and SAMPLE_AUDIT. No caller-chosen new role. Ordinary
set roles sort unique IDs. Duplicates in explicit input objects fail admission;
deduplication is only for derived unions/repeated references to the SAME
identical authority. Ordered roles are explicitly identified below; never
lexically reorder their digest members instead of the owning record keys.

COMPLETION_ENTRIES is completion-entry IDs in (code, trade_date) order.
SAMPLE_AUDIT is audit IDs in sample_key order. Summary.entries_digest is
Q(COMPLETION_ENTRIES); sample_audit_content_id is Q(SAMPLE_AUDIT).
No separate sample replacement identity, Dataset-derived A3 identity, or
generator identity is introduced. Existing schema/content, scope, spec,
implementation, PIT, A3, proof-pair, Observation Feature, L2 and split domains
are reused ONLY with their exact existing record semantics.

## 17. Exact Dataset ID Payload

The following table lists ALL 49 scalar fields. It is a closed field set.
No implicit dataclass reflection, extra runtime field or hidden input may
change it. DatasetID = H(multi-source-cross-day-dataset-id-v1, this mapping).
Q labels below are exact role strings. Existing *_digest helpers refer to
dataset.identity at BASE; existing component identities refer to their owning
modules. IdentityInput carries full records; these hashes are derived, not
caller admission substitutes.

| Field | Exact value/derivation |
| --- | --- |
| dataset_kind | SUPERVISED |
| source_schema_version | 10.9-mv-ts2 |
| scope_id | existing _scope_digest(scope) |
| dataset_as_of | normalized explicit A or null |
| dataset_schema_id | exact section 12 schema identity |
| logical_dataset_content_id | unchanged content encoder over exact matrix |
| canonical_build_pins_digest | Q(CANONICAL_BUILD_PINS, _build_pin_digest of union Feature/Label full Canonical pins) |
| feature_canonical_builds_digest | existing ts2-feature-considered-builds-v1 over TS2's exact set |
| cross_day_considered_canonical_builds_digest | existing cross-day-considered-canonical-builds-v1 over L2's union |
| canonical_row_versions_digest | Q(CANONICAL_ROW_VERSIONS, ALL row versions in union Canonical pins) |
| gap_references_digest | Q(GAP_REFERENCES, _gap_reference_digest for each union build, including zero-gap references) |
| ts2_spec_pins_digest | Q(TS2_SPEC_PINS, _spec_digest of TS2 specs) |
| observation_spec_pins_digest | Q(OBSERVATION_SPEC_PINS, _spec_digest of Observation specs) |
| cross_day_spec_pins_digest | Q(CROSS_DAY_SPEC_PINS, _spec_digest of L2 specs) |
| ts2_registry_pins_digest | Q(TS2_REGISTRY_PINS, _implementation_digest of ALL eight TS2 pins) |
| observation_implementation_pins_digest | Q(OBSERVATION_IMPLEMENTATION_PINS, _implementation_digest of exact used A4.1 pins) |
| cross_day_implementation_pins_digest | Q(CROSS_DAY_IMPLEMENTATION_PINS, _implementation_digest of exact used L2 pins) |
| split_spec_pin_id | _spec_digest(chronological_split_spec_pin(split_spec)) |
| split_result_id | unchanged chronological split result ID |
| completion_content_id | section 16 summary ID |
| feature_association_schema_id | PIT association_schema_id |
| feature_association_content_id | PIT association_content_id |
| observation_association_content_id | A3 observation_association_content_id |
| observation_sample_binding_content_id | A3 sample_binding_content_id |
| combined_association_content_id | A3 combined_association_content_id |
| observation_evidence_content_id | unchanged multi-source-observation-evidence-v1 over complete paired A3 evidence |
| observation_input_proofs_digest | Q(OBSERVATION_INPUT_PROOFS, full A2-derived BuildPin IDs with empty selected membership for ALL supplied inputs) |
| observation_build_pin_ids_digest | Q(OBSERVATION_BUILDPIN_IDS, full selected-membership BuildPin IDs from ALL A3 evidence) |
| observation_coverage_ids_digest | Q(OBSERVATION_COVERAGE_IDS, recomputed coverage IDs from ALL supplied inputs) |
| multi_source_sample_versions_digest | Q(MULTI_SOURCE_SAMPLE_VERSIONS, A3 versions in sample_key order); ordered role |
| ts2_execution_id | exact TS2 execution_id |
| ts2_values_content_id | exact TS2 values_content_id, including EXCLUDED |
| observation_values_content_id | exact Observation Feature global values content, including EXCLUDED |
| schedule_pin_id | existing trading-day-schedule-pin-v1 |
| cross_day_association_content_id | exact L2 association_content_id |
| cross_day_sample_bindings_digest | Q(CROSS_DAY_SAMPLE_BINDINGS, L2 binding IDs in sample_key order); ordered role |
| cross_day_decisions_digest | Q(CROSS_DAY_DECISIONS, L2 decision IDs in (sample_key, Label pin ID) order); ordered role |
| cross_day_values_content_id | exact L2 global values content ID |
| sample_audit_content_id | Q(SAMPLE_AUDIT), ordered role |
| manifest_schema_version | multi-source-cross-day-dataset-manifest-v1 |
| serialization_format | parquet |
| serialization_format_version | multi-source-cross-day-dataset-parquet-v1 |
| orchestration_contract_version | multi-source-cross-day-dataset-orchestration-v1 |
| sample_audit_contract_version | multi-source-cross-day-sample-audit-v1 |
| ts2_feature_execution_contract_version | ts2-feature-execution-v1 |
| observation_feature_execution_contract_version | observation-feature-execution-v1 |
| multi_source_pit_contract_version | multi-source-pit-v1 |
| cross_day_association_schema_version | cross-day-label-association-v1 |
| cross_day_execution_contract_version | cross-day-label-execution-v1 |

Changing a second physical Observation proof changes input/evidence pin
digests even if logical build ID and actual Feature values are unchanged.
No manifest recursion: dataset_id itself is not a payload field. Source
content fingerprints enter through real ImplementationPins. Source path,
mtime, cwd, output_root, built_at, JSON/Parquet byte hashes and report bytes
do NOT enter this payload. Root ID depends on logical bytes only through
existing typed content encoders, never serializer layout.

## 18. Separate Future Generator

```python
generate_cross_day_feature_requests(
    *, scope: DatasetScope,
    anchors: tuple[CrossDayAnchor, ...],
    feature_window_bars: int,
    schedule: VerifiedTradingDaySchedule,
    label_specs: tuple[LabelSpec, ...],
    dataset_as_of: datetime | None,
) -> tuple[PITSampleRequest, ...]
```

CrossDayAnchor exact fields: `code: str`, `market_calendar_date: date`,
`anchor_slot: int`. Actual int64 slots >= 0; no bool/coercion. Anchors are
explicit proposals, not discovered from bars or missing dates. Reject
duplicate (normalized code, date, slot), out-of-scope anchors, CLOSED anchor
days, non-fitting full nominal anchor bars or Feature windows crossing session
open/date. feature_window_bars is actual int64 >= 1, <= anchor_slot+1 for each
anchor; check counts before multiplication/range allocation. Scope admission
is section 3. Validate all static contracts even for no anchors.

For nominal interval delta, anchor event = explicit day's session_open +
anchor_slot * delta, Feature close = event + delta, Feature start = close -
feature_window_bars * delta. Emit unchanged PITSampleRequest with both
label_window_start and label_window_close null. Sort by existing sample_key.
No new sample ID, no PIT execution, no transform, no old generator call.

For EVERY proposed anchor, verify schedule has every civil-date record
through D(max requested horizon), considering ALL LabelSpecs. Count future
TRADING records before allocating horizon-sized structures. Missing coverage
fails the WHOLE invocation, never drops tail anchors. A qualified future early
close with a non-fitting same slot remains a legal proposal: L2 later records
ALIGNED_SLOT_OUTSIDE_SESSION, with no earlier-slot substitution. CLOSED days
come only from explicit schedule records, never bar absence. No bars input,
provider acquisition, current calendar, network or OpenD exists here.

Generator and join are separate future PRs. Join accepts explicit facts
without running generator; identity does not include a hidden generation
step. Audit covers every explicit PIT request. Proving that a caller intended
additional unsupplied anchors requires the separate generator proposal input;
join does not claim to infer unexpressed sampling intent.

## 19. New Manifest Schema

Exact top-level fields, no extras/missing fields:

```text
manifest_schema_version dataset_id identity status built_at logical_row_count
schema scope completion row_order materializer_version reader_contract_version
build_report_contract_version spec_artifact_versions output_files
```

`identity` is exactly section 17's 49-field scalar mapping, timestamps encoded
by section 20; each field is an assertion derived from sidecars. `schema`
contains only `{fields:[{name,logical_type,nullable},...]}`; scope contains
exact DatasetScope fields; completion is section 14's complete record.
These three repeat facts only for inspection and MUST agree with identity and
audit. row_order is `CODE_FEATURE_CLOSE_SAMPLE_KEY`. Manifest discriminator
and writer/reader/report version constants are exactly section 2. Status is
COMPLETE iff logical_row_count > 0 else EMPTY. A missing/zero-row Parquet is
not interchangeable: EMPTY requires legal zero-row exact schema Parquet.

`spec_artifact_versions` exact keys/values:
`ts2_feature=market-vault-feature-spec-v1`,
`observation_feature=observation-feature-spec-yaml-v1`,
`cross_day_label=market-vault-label-spec-v1`,
`split=market-vault-chronological-split-spec-v1`.

Each output_files record has exactly `relative_path`, `file_role`,
`artifact_version`, `row_count`, `byte_size`, `sha256`, `content_role`,
`content_id`. Nonnegative actual int counts/sizes; sha/content IDs lowercase
64-hex. Sort records by relative_path, reject duplicates. Exact whitelist
is section 20. Matrix content_id is logical content; authority/spec IDs are
as mapped there. Output facts bind bytes for verification, not Dataset ID.
manifest.json and _SUCCESS are not output_files entries, avoiding recursion.
built_at is explicit aware UTC microsecond metadata, at least all represented
evidence acquisition/proof clocks, never a selection clock or logical identity.
Writer/reader output paths and upstream descriptive paths are not identity.

## 20. Physical Layout and Exact Recorded Projections

Future layout is `output_root/dataset_id=<dataset_id>/` with exactly:

| Relative path | file_role; content_role; content_id | row_count |
| --- | --- | --- |
| dataset.parquet | MATRIX; MATRIX; logical_dataset_content_id | matrix count |
| feature_pit.json | FEATURE_PIT; FEATURE_PIT; feature_association_content_id | K |
| canonical_evidence.json | CANONICAL_EVIDENCE; CANONICAL_EVIDENCE; canonical_build_pins_digest | union build count |
| ts2_features.json | TS2_FEATURES; TS2_FEATURES; ts2_execution_id | TS2 value count |
| observation_pit.json | OBSERVATION_PIT; OBSERVATION_PIT; combined_association_content_id | A3 decision count |
| observation_evidence.json | OBSERVATION_EVIDENCE; OBSERVATION_EVIDENCE; observation_input_proofs_digest | full input proof count |
| observation_features.json | OBSERVATION_FEATURES; OBSERVATION_FEATURES; observation_values_content_id | Observation value count |
| cross_day_association.json | CROSS_DAY_ASSOCIATION; CROSS_DAY_ASSOCIATION; cross_day_association_content_id | L2 decision count |
| cross_day_values.json | CROSS_DAY_VALUES; CROSS_DAY_VALUES; cross_day_values_content_id | L2 value count |
| schedule.json | SCHEDULE; SCHEDULE; schedule_pin_id | daily-record count |
| sample_audit.json | SAMPLE_AUDIT; SAMPLE_AUDIT; sample_audit_content_id | K |
| split.json | SPLIT; SPLIT; split_result_id | eligible count |
| build_report.json | BUILD_REPORT; NON_AUTHORITATIVE; dataset_id | 1 |
| specs/ts2/<dataset-spec-pin-id>.yaml | TS2_SPEC; SPEC; spec content_sha256 | 1 |
| specs/observation/<existing-feature-pin-id>.yaml | OBSERVATION_SPEC; SPEC; spec content_sha256 | 1 |
| specs/cross_day/<dataset-spec-pin-id>.yaml | CROSS_DAY_SPEC; SPEC; spec content_sha256 | 1 |
| specs/split.yaml | SPLIT_SPEC; SPEC; split spec content_sha256 | 1 |
| manifest.json | manifest, not output_files | n/a |
| _SUCCESS | exact empty regular file, not output_files | n/a |

artifact_version is section 2 serialization version for matrix and fact
sidecars; build report uses its report version; specs use section 19's own
artifact versions. There is exactly one Parquet file. No partition inference,
latest/current/active pointer, detached optional evidence or external artifact
dependency. No duplicate numeric representation: TS2/A4.1/L2 values own their
numbers, audit references those values, and matrix is their verified projection.

For all fact JSON use deterministic UTF-8, sort_keys=True, compact separators,
ensure_ascii=True, allow_nan=False, trailing newline. Reject duplicate keys,
BOM, invalid UTF-8, unknown/missing fields, unsafe text, non-finite scalars and
noncanonical bytes. Native bool/int/float remain distinct; UTC timestamp strings
use `YYYY-MM-DDTHH:MM:SS.ffffffZ`, dates `YYYY-MM-DD`. Parse by declared field
types, not string inference. Tuples become arrays; objects use exact named
fields. Each file is `{artifact_version, records}`; records is an array, even
for one singleton. No Python class/module tags or dynamic imports.

Projection field sets are fixed by these explicitly named BASE dataclasses,
recursively over their declared fields; derived properties are not stored
unless listed below. Future fields added upstream are NOT automatically
allowed. The L3.3 implementation must contain literal schema tables for these
BASE sets, with tests preventing reflection-based widening:

- feature_pit: one PITAssemblyResult, including full PITSample/request/
  diagnostics, build pins, selected union, association schema/rows/IDs. Rows
  preserve position ordering; samples are in sample_key order.
- canonical_evidence: one record per logical build in build ID order, containing
  ALL VerifiedCanonicalBuild fields except build_path and manifest_payload.
  In nested CanonicalBar/CanonicalSourceRef omit snapshot_file only. Restore
  neither paths nor physical manifests; validate semantic request, source,
  resolution/content/build IDs, bars, gap ranges and gap boundaries directly.
- ts2_features: one complete TS2FeatureExecutionResult field projection,
  recursively including specs, all eight pins and samples/values, plus
  `implementation_source_hashes` as sorted `{transform_ref,source_sha256}`
  assertions for all eight real registrations. Never instantiate a sealed
  TS2 result from these records; use private recorded projections.
- observation_pit: one full ObservationPITAssemblyResult field projection,
  including bindings, decisions, paired evidence and sample bindings. It
  repeats full A3 BuildPins for their decision-specific selected membership.
- observation_evidence: records `{identity_input, source_snapshots, created_at}`.
  identity_input is the exact A1 ObservationBuildIdentityInput record reconstructed
  from the verified A2 object, including all rows/coverage/contracts. Full input
  proof clocks survive relocation. Sort by full unselected BuildPin ID, not
  logical observation_build_id. No A2 physical manifest, path or Parquet bytes.
- observation_features: one full ObservationFeatureExecutionResult projection.
  Full specs are in spec files; IDs/pins/results must bind them exactly.
- cross_day_association: one exact record `{feature_build_ids,label_build_ids,
  dataset_as_of,decisions,sample_bindings}`. Full PIT/A3/schedule/specs are in
  their own files; these IDs identify role subsets of canonical_evidence, not
  replacement proof authority. Decisions/bindings use full BASE L2 record
  fields. This projection deliberately avoids the reassembling L2 constructor.
- cross_day_values: one exact record `{implementation_pins,
  implementation_source_hashes,values}` using L2 BASE shapes. Its association
  is the preceding sidecar, not a recursively duplicated object.
- schedule: one full VerifiedTradingDaySchedule field projection. Recompute
  pin from content; do not accept a pin without daily records.
- sample_audit: section 15 records, sorted by sample_key.
- split: one full ChronologicalSplitResult projection, including spec/pin,
  assignments/schema/rows/IDs/diagnostics; validate immutable recorded facts.
- build_report: one exact record `{report_contract_version,dataset_id,
  requested_sample_count,matrix_row_count,feature_excluded_sample_count,
  label_incomplete_sample_count,complete_scope_count,incomplete_scope_count,
  missing_scope_count}`. It is deterministic derivable metadata only, never
  reader authority; missing proof cannot be repaired from this report.

Spec bytes use their existing canonical in-memory serializers, no path-based
loading in the pure join. Persist no caller-authored implementation-source
files. Parquet uses exact Arrow mappings: string->string, int64->int64,
float64->float64, timestamp_us_utc->timestamp(us,UTC), date32->date32; field
order/nullability exactly section 12, schema/field metadata empty. Require
exact schema, no inferred pandas index or extra field. Compression zstd,
writer format 2.6, data_page_version 1.0, dictionary false, statistics true,
row_group_size 65536. Serializer/library byte differences are physical facts,
not logical ID changes. The future writer must fail if exact logical types
cannot be represented without coercion.

## 21. Separate Verified Reader and Trust Limit

Future sole path entry: `load_verified_multi_source_cross_day_dataset(build_dir)`.
It returns deeply immutable VerifiedMultiSourceCrossDayDataset with dataset_id,
identity_input, schema, rows, sample_audit, completion, split_result, all verified
recorded component projections, manifest payload, and descriptive build_path.
No skip_validation/trust_me/from_unverified, latest search, repair or old-reader
dispatch. Exact directory name and exact manifest discriminator are mandatory.

Reader validates safe components, strict inventory and every file fact;
parses exact typed projections/specs; validates fixed registries/pins; recomputes
Canonical/A1/PIT/A3/TS2/A4.1/L2/schedule component identities and structural
closure under sections 5-10; reconstructs audit/matrix eligibility and checks
recorded split rules, counts, schema/content and new Dataset ID. It does not
construct upstream live results, call upstream assembly/selection/executors,
acquire schedules, or run formulas. Pure unchanged split validation is legal;
no new split policy. Validate excluded samples too. A4.1/L2 scalar outputs are
recorded outcomes, not a claim that this reader reran their formulas.

Crucial scope: this is integrity/identity/structural verification of a recorded
artifact, not an external signature, provider truth proof, or independent
mathematical proof of transform execution. A caller who forges a wholly new,
internally consistent artifact and its ID is outside a content-hash authenticity
claim. Consumers expecting a specific Dataset must compare its externally
pinned Dataset ID. A live join starts from issued/verified upstream authorities;
deserialization must not manufacture upstream issuance. No build report or
matching caller hashes can substitute for any mandatory structural fact.

Before issuing the verified object, perform a final physical closure pass:
same root object, exact inventory, safe ancestry/components, same file objects,
manifest byte equality, every committed file size+SHA256 equality, and still
empty regular _SUCCESS. Same-path byte or object mutation fails; inventory
equality alone is insufficient. Unicode/Arrow/documented decoding failures
map to a dedicated artifact error with original cause, no broad programming-
error suppression. Reader is read-only and never rolls back a final build.

Inspect path components with lstat/reparse-aware checks before traversal;
resolve() alone is insufficient. Artifact members use canonical relative
POSIX paths only: reject absolute paths, empty/dot/dot-dot components,
backslashes, drive syntax, ADS colons, symlinks, junctions, Windows reparse
points, root escape or unverifiable file types. Check exact regular-file and
directory types at both passes, with no unlisted children at any depth.
Neither _SUCCESS alone nor a matching filename establishes authority.

## 22. Future Publication and I/O Boundary

This PR introduces ZERO destructive authority and no operation contract.
Future L3.3 must first obtain a separately reviewed exact-base atomic/no-replace
contract with narrowly bound destructive surfaces. The dormant A4 contract is
not permission for a new path. Missing approved base contract stops that phase.

Future semantics: exclusive invocation-owned sibling staging; prove exact root,
staging filesystem identity, safe ancestry and same filesystem. Partial-write
cleanup ownership is separate from publication authority. Write data/specs,
manifest, full private verification, then empty _SUCCESS and final verification.
Issue private seal binding dataset_id, exact inventory, file object identities,
byte sizes and SHA256. Immediately before no-replace publication, revalidate all
seal facts. Never ordinary overwriting POSIX rename, delete-then-rename or repair.
Windows no-replace and Linux renameat2(RENAME_NOREPLACE) must be separately
qualified; unsupported platforms fail closed. Existing/race final is strictly
verified; equivalent returns existing, corrupt fails untouched. No arbitrary
staging adoption/sweep or postcommit rollback deletion. This paragraph designs
behavior only; it is not the future machine-enforced destructive contract.

Pure join/generator own code performs zero filesystem reads/writes. Registry
validation is bounded to already reviewed source acquisitions: eight static
TS2 modules and four static Cross-Day Label modules via their frozen mechanisms;
Observation's sealed two-entry registry uses its existing import-time source
fingerprint, not new per-call discovery. All modules are loaded before the
invocation boundary. No old BARS registry needs to run. No dynamic imports,
caller source hashes, arbitrary file reads, artifact reopening, spec/manifest/
plan/settings/Catalog lookup, directory scan, cwd/environment authority,
current time, network, provider or OpenD. Fingerprint reads bind content only,
not source path/mtime/cwd. Future artifact reader additionally has its explicit
closed artifact read boundary. No general read-only filesystem allowance.

## 23. Failure Vocabulary

Future `MultiSourceCrossDayDatasetError` has exact reason_code enum below;
preserve documented wrapped causes. First failing stage in section 5 decides
the code, and no partial trusted result escapes. Upstream outcome reasons are
not Dataset authority codes.

| Code | Meaning |
| --- | --- |
| INPUT_TYPE | wrong concrete type, missing explicit argument or malformed container |
| SCOPE | unsupported source/scope or request outside declared scope |
| DUPLICATE_INPUT | repeated semantic input/sample/spec/proof object |
| PIT_BINDING | recorded PIT request/selection/pins/association inconsistency |
| A3_BINDING | null/missing/extra/conflicting A3 version, decision or complete proof |
| TS2_FEATURE_BINDING | TS2 result/PIT/window/provenance mismatch |
| OBSERVATION_FEATURE_BINDING | A4.1 value/spec/selected A3 version mismatch |
| CROSS_DAY_BINDING | L2 association/value/reference/decision mismatch |
| SCHEDULE_BINDING | schedule content/pin/geometry/coverage mismatch |
| CLOCK_AUTHORITY | inconsistent explicit cutoffs or selected clock violation |
| SPEC_CONTRACT | unsupported/malformed spec family, shape or output collision |
| IMPLEMENTATION_BINDING | fixed registration/source fingerprint/pin failure |
| MATRIX_ELIGIBILITY | matrix membership/projection differs from owning outcomes |
| SPLIT_BINDING | wrong split input/assignment/status/end/spec/content |
| IDENTITY_AUTHORITY | recorded schema/content/component/new Dataset ID mismatch |
| RESULT_AUTHORITY | unsupported issuance, mutation or malformed final result |

Canonical source-scope mismatch is SCOPE; Canonical conflicting candidates,
bad row/build identities or gaps are PIT_BINDING at stage 4. Generator uses
these same preflight categories where applicable; insufficient future schedule
is SCHEDULE_BINDING, not a Label incomplete outcome. Artifact parsing/path/
inventory/publication errors belong to separate future reader/materializer
errors and never become Feature/Label statuses.

## 24. Offline Literal Known-Answer Vectors

Vector recipes and literal expected values follow below. They exercise new
identities using existing BASE upstream authorities. No production/provider
qualification is inferred from synthetic fixtures. One-off calculators remain
outside the repository on D:. Future tests must copy literal expectations;
they must not regenerate expected hashes at test time.

### 24.1 Reproducible Fixture Recipe

There are EIGHT vector groups A-H (H has two subcases), with 98
literal digest assertions. These include all five new domains, empty and
two-member cases for all seventeen Q roles, and real upstream order invariance.
They do not modify L1/L2's 53 assertions or TS2's 49 assertions.

The complete fixture primitives are the existing BASE test helpers
`tests/cross_day_helpers.py` (cd), `tests/ts2_feature_helpers.py` (ts),
`tests/test_observation_models.py` (om),
`tests/test_observation_pit_models.py` (op), and
`tests/test_multi_source_feature_execution.py:spec` (obs_spec). Their exact
BASE definitions/defaults are part of this recipe; no future mutable helper
defaults may change a vector. They are synthetic authority fixtures, not
mocked trust tokens. Canonical/A2 builds are materialized/read only in an
external D: calculator workspace to obtain genuine verified upstream inputs.

Common fixture, with all helper arguments not overridden retaining BASE defaults:

- scope = DatasetScope(("US.AAPL",), (date(2025,3,3),), "NONE", "5m", "RTH").
- A = 2026-01-01T00:00:00.000000Z. Feature close T =
  2025-03-03T14:40:00.000000Z, Feature start = 14:30Z.
- Feature build = cd.build over (cd.bar(slot=0),
  cd.bar(slot=1, close=125.0)); source schema 10.9-mv-ts2.
  PIT = cd.pit((Feature build,)), unchanged one feature-only request.
- TS2 specs = (ts.spec(n=2),), namely ts2_simple_return.
- Observation specs = (obs_spec(),), namely obs_rate / float64 / max_age_us=10.
- Observation snapshot = om.sample_snapshot(completed_possession_at=T-1 second).
  Row = om.sample_observation(event_time=T-5us, known_at=T-4us,
  archive_available_at=T-3us, source_snapshot_id=recomputed snapshot ID).
  All other economic/schema/provenance facts are the exact om fixture:
  fixture-provider, fixture-series, fixture:entity, rate, typed tenor/variant
  dimensions, values (4.25,12), initial-1, full known-at/provider/normalizer pins.
- Call op.artifacts.__wrapped__(D_fixture_root) to obtain its factory.
  Supply that row and snapshot; effective/knowledge coverage [T-1day,T+1day],
  created_at=T+300us. Both completeness flags and all op evidence pins remain
  exact defaults. The factory's integer clock offsets are measured from om.T;
  negative offsets are intentional for this 2025 fixture.
- A3 = assemble_observation_pit_sidecar(PIT, (Observation build,),
  exact observation_feature_binding per spec).
  Observation Feature result = execute_observation_features(A3, represented
  Observation builds, specs). TS2 result = execute_ts2_features((Feature build,),
  PIT, TS2 specs, dataset_as_of=A).
- Label build = cd.build over (cd.bar("2025-03-04", close=150.0),).
  Label specs = (cd.spec(),), namely cd_return_1d.
  Schedule = cd.schedule(): normal sessions on March 3 and 4, every civil
  date explicitly present, archive_available_at=2025-12-31T00:00:00Z.
- L2 = assemble_cross_day_labels(PIT, (Feature build,), (Label build,),
  schedule, Label specs, dataset_as_of=A, observation_pit=A3), then existing
  execute_cross_day_labels. These calls generate the fixture BEFORE a future
  Dataset join. They are not permitted calls inside that join.
- Split spec exact fields: schema market-vault-chronological-split-spec-v1;
  name cd_chrono; version v1; boundary_timezone America/New_York;
  train_end_date=2025-03-04; validation_end_date=2025-03-05;
  test_end_date=2025-03-06; assignment_rule FEATURE_WINDOW_CLOSE_DATE;
  purge_rule ACTUAL_LABEL_END; incomplete_label_policy EXCLUDE;
  out_of_range_policy EXCLUDE.
- Normalize full component records per sections 5-17. Canonical pins contain
  all rows/source snapshots, with GapReference for every build even if count=0.
  Calculate split only for Feature-eligible samples, then exact schema/rows,
  audit, completion and 49-field Dataset payload. No caller-supplied opaque
  hashes are needed to compute any new Dataset digest.

Scenario overrides (all other inputs unchanged):

| Group | Override | Matrix rows; outcome |
| --- | --- | --- |
| A | common fixture | 1; all families COMPLETE |
| B | Label row archive_available_at=A+1 day | 1; Label INCOMPLETE/ARCHIVE_FUTURE, null value/end, split EXCLUDED |
| C | ts.spec(n=3) | 0; TS2 INSUFFICIENT_ROWS, audit retained |
| D | obs_spec(max_age_us=1) | 0; Observation STALE with fully continuous extended coverage |
| E | cd.pit(..., requests=()) | 0; nonempty scope/specs/input proofs remain; A3 has no decisions |
| F | add ts.spec("candle_body"), obs_spec("int64", name="obs_count"), cd.spec(transform="forward_direction", name="cd_direction_1d") | 1; three families each have two outputs |
| G | schedule archive_available_at decreases by 1us | 1; schedule/L2/Dataset identities change, A3 and TS2 do not |
| H_considered | add Label/proof build cd.build((cd.bar("2025-03-05", close=150.0),)) | 1; unrelated considered authority changes, selected reference unchanged |
| H_backing | add build containing the IDENTICAL March 4 Label row, but materialization request dates=(March 4,March 5) | 1; additional identical backing build changes selected reference |

For E, A3 preflight still sees the explicit Observation build; existing A4.1
execution receives the empty represented-build tuple, as required by its
sealed zero-decision boundary. The new Dataset input-proof digest still binds
the separately supplied full Observation input. No sample audit record exists,
so E has no audit_id; its audit CONTENT ID is a real empty Q, not null.

F.reversed_dataset_id reruns the real upstream path with all three spec input
tuples reversed. H_backing.reversed_dataset_id reverses the Label-build tuple.
The expected IDs are equal to the normal runs. This is not merely dictionary
key reorder. G and both H variants preserve the literal A TS2 execution ID and
A3 combined association ID below. Their Feature values remain equal to A.
H_considered's selected row reference equals A; H_backing's differs.

Q role vectors are scalar-encoder tests, not substitute admitted upstream
objects. `empty` means IDs=(); `two` means IDs=("a"*64,"b"*64) in that order.
For set roles the normalized order is the same; for ordered roles the two
members represent already sorted owner records. IDs are literal repeated hex,
not hashes of letters. These are distinct from the scenario-level Q values.

### 24.2 Frozen Expected Digests

Copy these literal expectations into future tests. Dates/times in the recipe
must be encoded as typed scalars, not JSON strings. Source path/serializer
bytes never enter an expected identity.

```text
A.dataset_id=2f5355e7cc30ab7a984f9ff959b10e8d8b949e89e453b0e43c0d88a6a36f06c8
A.sample_audit_content_id=05141d26027d39234fd8d3fa63ef7ca88db1770088750880d61a02bb47d7fa84
A.completion_content_id=c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7
A.logical_dataset_content_id=d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da
A.completion_entry_id=5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379
A.audit_id=bb473bdc63666c47f90176f5b079e4052c64c2396952fe7a81090327f87f8b87
B.dataset_id=7bb8903e54e7c3203deb9c1d2bf63cef16202ed5b2807c9c20a6eb4ed0c7f1af
B.sample_audit_content_id=3d67dd7cd8ef2bfb8a355d2a1def438fc4cf144d54db2f9b4e475c18d69547f7
B.completion_content_id=6c6dcfabb4a8c32bbbdb6be0c1a8831e25e6ebb2e2886a9063bfc74521510d67
B.logical_dataset_content_id=c04f288a1ed7124ecc8720e07fb57eced3dbcbd4e4161d684d12eeaaaec11cd4
B.completion_entry_id=e95e19f95ff8113112b397e3aa3b8fb51258e26cda5b5a5151a337a6254f3d76
B.audit_id=a7f37ef7284048d5f0a2e45053c1433578bc99b8db5bc3795aa6f9e01f5a0c8c
C.dataset_id=b0223c6eac1186590ea3a967b35780b3e043e8dbf4f46bee976c728bffff4bc8
C.sample_audit_content_id=93160daf0413839e49acb5f543445e5eaef4d376b9aa579e238806cd64cb7f27
C.completion_content_id=88e72332af570ec7f2dea8a5c2051b75b91650b4a862185450c731b36fe0da84
C.logical_dataset_content_id=cbd1556a06c724f3c11e0d9b9c72689114e6cc6906d0c3a648cdc69b92bf7b25
C.completion_entry_id=ada02cf8ae2ab180d9c64d003235ec91c6c24c9af2bb23ea253138d5715092cd
C.audit_id=bbe96e12455a6fc5c6ee61194430b5c8ea50be1272d510278fa0861ca30b9707
D.dataset_id=047f51f7ccb41ed97e7b682cd2432dc135921fead1904e6028e24faf60344ce6
D.sample_audit_content_id=1c9fd5710c9209594185de348a27fa1e69a27670c9d6086f248e91aa806912bd
D.completion_content_id=d4289b1ae8462a9951431802303f06595271ac61c953e9f9db0dc783064a9b5b
D.logical_dataset_content_id=cbd1556a06c724f3c11e0d9b9c72689114e6cc6906d0c3a648cdc69b92bf7b25
D.completion_entry_id=85225f05d4f81f4909f312fc3a41a3554ef293e88d53e468d26ef4cf29f8813e
D.audit_id=79beef4e9b5dd57ae972d0905c49f0899b9f66cd886266ddd220b0a83677487c
E.dataset_id=dcdd12857a9278d6c1008e70b9ec0b8a0bb4b16f8afb0d7173c2ef5cbd9f191f
E.sample_audit_content_id=4d40e8649193ec70a93870c726053db8951176d5c83488da6736370afbf96ab3
E.completion_content_id=3d32a36f77055ef3378d019bdbaaf02d7c9df7726db5c29502daa2696273065f
E.logical_dataset_content_id=cbd1556a06c724f3c11e0d9b9c72689114e6cc6906d0c3a648cdc69b92bf7b25
E.completion_entry_id=54ea47c41449b97ff38e204415e8b3bf22431c5c948231f6e08e9c997d1185f1
F.dataset_id=1d20617d872c9d93c924435e9f3bfb7226a381e9f834cd9e70e7c2abc69cd802
F.sample_audit_content_id=a0d1362ebd277b1a4e5778b8cabf36fbd63ac60ce895bf59f1c9f0ef47e4f0dd
F.completion_content_id=c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7
F.logical_dataset_content_id=d8306f69619ff0697ec80f193108a7d459fda109bc5886938e4c6298b9357180
F.completion_entry_id=5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379
F.audit_id=fa9c1821167340b2f206d83e2a5ba45bc46334b0fad1d546a65b70e8c0ff7e2b
G.dataset_id=07da04ab3ccdca4cdf42a60e0e828d197d3047370148d994a789753116ab02d9
G.sample_audit_content_id=011d6c7c1c1370723a148ee208c2df1dcb1ae64715d2180c404d3d1c72bd9414
G.completion_content_id=c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7
G.logical_dataset_content_id=d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da
G.completion_entry_id=5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379
G.audit_id=a9515d8999c184b39d7224e42f55d8f59b25bd573db55e90ef84cd5419f67ba5
H_considered.dataset_id=5900736e6a44db736497d74ebcfd3db32f3cf336d45fb90bdda7d6ae0fb61111
H_considered.sample_audit_content_id=ed6e8b4caaaf8152527394c693edf677b24e29e11f7a95d76414d9ca9db2c029
H_considered.completion_content_id=c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7
H_considered.logical_dataset_content_id=d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da
H_considered.completion_entry_id=5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379
H_considered.audit_id=9db8326863cb9f78c8ad9dd2b2d8477a611a6d2ffa57c4efe8434e6e57695bd5
H_backing.dataset_id=36c731b512ca8c5a75cdb0ef11b2cab4f4e5eaff74f1669a819a9fbb87228b9e
H_backing.sample_audit_content_id=aab2ac1c6b8dda8c0d20300136a14732f6474214a00a17bb634ecb0615f39f99
H_backing.completion_content_id=c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7
H_backing.logical_dataset_content_id=d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da
H_backing.completion_entry_id=5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379
H_backing.audit_id=af8e0e889479ec1bd914b8bb2c65422e78fe977425c7006bb8bc07e27ac9c597
A.selected_row_reference_id=6644f2c9764231d1b737825d912b80d8f795f8241d606a81d2e2de377be8f1b1
A.considered_builds_digest=c67791675c4f93de16c179a996e4d01a05a7879ce7a10f4ea049ced9a25272a3
H_considered.selected_row_reference_id=6644f2c9764231d1b737825d912b80d8f795f8241d606a81d2e2de377be8f1b1
H_considered.considered_builds_digest=4b2ecd5785215f00990d7d3a51a5ea36279e9f436553799eb73e0de3077493c1
H_backing.selected_row_reference_id=d47f063f57238fc079c839a7340cb88a44d290d42432cd2f015796e6ee44dc0d
H_backing.considered_builds_digest=8979a802da972f53387078fc4b2e72607830f20652bd9c838b03d09a75adebce
A.ts2_execution_id=a9bacbdcfa334a544b32ff906d0698f571c0e1b8ef17bf6a7c603dfbc5d0bf74
A.a3_combined_association_content_id=b2128bf1daf366e4bc1583e60778bfcbf90973152d363f29da6a82cbaf2370a1
A.multi_source_sample_version_id=c2f13818c6c7938d0d93fdba114dfb0f440afc9f8fac1e3f4bebaaa91587548a
F.reversed_dataset_id=1d20617d872c9d93c924435e9f3bfb7226a381e9f834cd9e70e7c2abc69cd802
H_backing.reversed_dataset_id=36c731b512ca8c5a75cdb0ef11b2cab4f4e5eaff74f1669a819a9fbb87228b9e
Q.CANONICAL_BUILD_PINS.empty=f92877ca8dc1c8cb00653ae93a170b30db8842372f924b896909693017b41dbb
Q.CANONICAL_BUILD_PINS.two=f3f24d0301f03436a47aa5661347d199ac9d3d500047b191b267d765ebb843f5
Q.CANONICAL_ROW_VERSIONS.empty=4d312df170f3da112040ffd72cc464e7095e47b02c5e42092f60e2a1a040481a
Q.CANONICAL_ROW_VERSIONS.two=d4f8c22588c8f36bb8bc04a2f75aea3d2074ca30b14fb91a7a6cb6ceb0647971
Q.COMPLETION_ENTRIES.empty=0e1100eaadbadbe35dfbc1799304893f09666af8311cb287146cb01770f545b6
Q.COMPLETION_ENTRIES.two=d0c1b86f0ba3d9eded95b3ef471823aa275523f22b5b47f42c96c901fba94bac
Q.CROSS_DAY_DECISIONS.empty=a342a47a93784dfa115a41626ceb8b07e3a5e1931061ecf0f857f4f2689a11f7
Q.CROSS_DAY_DECISIONS.two=833d38205e848d374ef58e105d18be64c8b2446d2c1ed43a93288216662d5b01
Q.CROSS_DAY_IMPLEMENTATION_PINS.empty=a7a1f179bef1d39c1fddcb115ca47bc97df23a51c296d4be48aa57b0b4e72c8c
Q.CROSS_DAY_IMPLEMENTATION_PINS.two=cd4400e2e21e401e9344ba7e699d61aa39e59ed8064d9c4fb0c776d78f95d4d1
Q.CROSS_DAY_SAMPLE_BINDINGS.empty=9a170a4312b71159fe3d399684e6df2b255274760ca9eca3507e2d210359192d
Q.CROSS_DAY_SAMPLE_BINDINGS.two=d0127b591d05bdc8e97483f2887e14ec732353a71f7fe5098fcdfb2cb4375669
Q.CROSS_DAY_SPEC_PINS.empty=8bd3acc4d89f06911fa81f406ac5ab32e7abaf2408538f5134f79fd99d773df7
Q.CROSS_DAY_SPEC_PINS.two=4549ef8b16607e5dfd442aa7fd7f930ca8a18fef24b9dec1f4712dab74389ed7
Q.GAP_REFERENCES.empty=46e056f39d099675057ce5b330bbd513a412602e155f4fc58f69f9d503448079
Q.GAP_REFERENCES.two=84267b5c48bdb85759f62deb3df884595803e5701a6ffc18e4b592a63cfbeb96
Q.MULTI_SOURCE_SAMPLE_VERSIONS.empty=905093f9f420b3b80525479e7f273512a72be7ec0b6110e576147abd556ba209
Q.MULTI_SOURCE_SAMPLE_VERSIONS.two=665022bf4d8d86f7458abe7710851c6cdd279cc4122ca7d19096353cf7d04e6d
Q.OBSERVATION_BUILDPIN_IDS.empty=6488e8fcfd4d90ffe02cda0084720a268fe3ceedc15b90a7f0b902f9e6e52bb4
Q.OBSERVATION_BUILDPIN_IDS.two=a4cbd53398063be5d0d53df51ff81449c71bacff3af9f7c1bdc17626026ec380
Q.OBSERVATION_COVERAGE_IDS.empty=1d930d5cb2d881e10290aea6337b34caaf62c2f74e37af60ea2ff162c8c99ddc
Q.OBSERVATION_COVERAGE_IDS.two=ca1b4105860ae31fd45be4a01810eea24a2c97d8ae27a8e1810fd0c445399673
Q.OBSERVATION_IMPLEMENTATION_PINS.empty=f978e1cc9f04c1bf2ace7f0d805078d63558a70c7f0ec905bc0e1577ec120efa
Q.OBSERVATION_IMPLEMENTATION_PINS.two=58075738ea2f8a09400e2582ce6b0dfe3b60438ba99ac2b2dc69ac2fd379ea60
Q.OBSERVATION_INPUT_PROOFS.empty=65a8b8d4848470ec2fc9ace812a6c838f0922118f4cf62c00706093f120b6d5e
Q.OBSERVATION_INPUT_PROOFS.two=9681f508260ea64e29447bbcba58d557ced945eea16eb4a78ded95b39d6eb16e
Q.OBSERVATION_SPEC_PINS.empty=50fe9740b97c4f91a722044b60ebcfb859c1dbe3c8eae03b1801d9e6938f280c
Q.OBSERVATION_SPEC_PINS.two=d08e0b770b9bdb80a2336196123852288bf6362a9c86c49b494dac5353e6c680
Q.SAMPLE_AUDIT.empty=4d40e8649193ec70a93870c726053db8951176d5c83488da6736370afbf96ab3
Q.SAMPLE_AUDIT.two=5cc34532d7b000e5e38bee5d0b76f810542e6c16f2b3a2cc4e2f76372c5b3368
Q.TS2_REGISTRY_PINS.empty=7206c5228de5c5a362cd71271d6037c97a9bb8a4dbe158064460c91618f8c88a
Q.TS2_REGISTRY_PINS.two=c8427951944bd6f327b04974d3d7f19572b95c17e1d6596062e0ecc49d06ff69
Q.TS2_SPEC_PINS.empty=43e7dcdff66fbfa191abc7214efae4f0477796d42bff93a120ec840556722a02
Q.TS2_SPEC_PINS.two=fe3e0ba8c269c26e2dfdc4ccba7a3348d319e3e32c779ef3aad098385bc48704
```

```text
KNOWN_ANSWER_VECTOR_COUNT=8
KNOWN_ANSWER_DIGEST_ASSERTION_COUNT=98
```

## 25. Future Design Canaries

All canaries are future obligations, not claims that Dataset runtime exists.

1. Old Dataset cohort IDs and runtime stay unchanged.
2. Old readers reject the new manifest discriminator.
3. New reader rejects every old cohort discriminator.
4. Null A3 multi-source sample version fails, never bar-only fallback.
5. A3 sample-key mismatch fails.
6. A3 bar-version mismatch fails.
7. L2 multi-source sample version mismatch fails.
8. Missing/extra A3 binding fails exact set equality.
9. Missing/extra TS2 Feature sample fails.
10. Missing/extra Observation Feature sample fails.
11. Missing/extra L2 binding/execution sample fails.
12. Feature association schema/content mismatch fails.
13. Any dataset_as_of mismatch fails.
14. Any schedule pin/copy mismatch fails.
15. Schedule/Label mutation cannot alter A3 identity.
16. Observation-only mutation cannot alter TS2 identity.
17. TS2 execution/value identity mutation changes Dataset ID.
18. Observation Feature identity mutation changes Dataset ID.
19. Cross-Day association mutation changes Dataset ID.
20. Cross-Day values mutation changes Dataset ID.
21. Schedule pin mutation changes Dataset ID.
22. L2 real implementation pin mutation changes Dataset ID.
23. Unused considered Label/proof evidence stays identity-bearing.
24. Backing and considered L2 digest domains cannot substitute.
25. TS2 EXCLUDED removes matrix row.
26. Observation Feature EXCLUDED removes matrix row.
27. Excluded sample remains in audit.
28. Excluded sample remains in all component evidence/facts.
29. L2 INCOMPLETE retains a Feature-eligible matrix row.
30. Incomplete Label value is null, never fabricated.
31. Aggregate actual end uses exact L2 per-Label ends, including partial consumption.
32. Nominal horizon cannot replace actual end.
33. Matrix sample_version_id equals non-null A3 version.
34. Original bar version remains separately unchanged.
35. Split uses exact joined status/end, including purge equality.
36. Observation clocks cannot change split boundaries.
37. Reordering caller input/spec/build tuples leaves identity unchanged.
38. Relocation of all upstream and output artifacts leaves logical identity unchanged.
39. built_at mutation alone cannot change Dataset ID.
40. output_root mutation alone cannot change Dataset ID.
41. Dataset ID binds the exact sealed TS2 execution contract. Validate the
    complete ordered PIT Feature selection separately; each TS2 value's
    candidate sequence is exactly its frozen trailing min(N, selected_count)
    projection in PIT order, never widened to the full selection when
    selected_count > N.
42. Dataset ID binds all eight actual TS2 registry pins, not just used pins.
43. Dataset ID binds complete A3 associations/proofs, not only selected rows.
44. Dataset ID binds COMPLETE and EXCLUDED Observation values.
45. Dataset ID binds exact L2 association/value/schedule closure.
46. Zero samples retain explicit scope/spec/registry/input-proof identities.
47. Zero matrix rows with requested exclusions retain nonempty provenance.
48. Cross-Feature-family output collision fails.
49. Label/reserved-field name collision fails, including conditional cutoff column.
50. Duplicate sample key fails before normalization.
51. Join never reruns PIT selection.
52. Join never reruns A3 selection.
53. Join never invokes TS2 Feature execution.
54. Join never invokes Observation Feature execution.
55. Join never invokes L2 assembly/execution or constructor-based reassembly.
56. Generator emits feature-only requests with null Label window fields.
57. Insufficient schedule coverage fails the entire generator, including tail anchors.
58. Generator never infers CLOSED from missing bars.
59. Generator never invokes provider/OpenD/network.
60. Pure join has no artifact/spec/plan/settings/Catalog/directory reads or writes.
61. Reader never runs upstream transforms/selection/providers.
62. A1-A4 identities stay unchanged.
63. Existing L1/L2 53 fixed digest assertions remain unchanged.
64. Existing L1/L2 66 canaries remain unchanged.
65. Existing TS2 49 assertions remain unchanged.
66. Existing TS2 48-canary accounting remains unchanged.
67. No L4 implementation is introduced.
68. This design introduces no destructive runtime surface or live contract.
69. Same logical Observation build with two distinct physical proof clocks retains both and changes Dataset ID.
70. Duplicate identical complete Observation proof pairs fail.
71. Zero samples validate and bind unmatched-to-no-decision input proofs without weakening A4.1's sealed helper.
72. Legacy/mixed Canonical schemas fail even in unused supplied evidence.
73. Conflicting Canonical candidates fail before market/archive filtering.
74. Direct live-result construction and coordinated fake implementation assertions fail.
75. New reader detects same-path byte/object mutation in its final physical pass.
76. Partial-staging cleanup is not publication authority; invalid seal never reaches rename.
77. Zero-row Parquet has exact schema, and nonempty scope completion still covers every cell.
78. Incomplete/purged split assignments remain matrix rows with nontraining status; Feature-ineligible samples have no assignment.
79. Generator huge horizon/window fails boundedly; qualified future early-close misfit is left to L2 without substitution.
80. Every new identity domain and ordered role has literal vectors, including empty sequences.

DESIGN_CANARY_COUNT=80

## 26. Future Phase Gates

L3.1: pure join, recorded-closure validators, identity, schema/audit/completion
and split integration. Separate additive package; no generator or artifacts.
L3.2: separate explicit Cross-Day generator, after L3.1 reviewed/main closure.
L3.3: separate artifact writer/reader after L3.2 closure and a separately
reviewed approved-base destructive design contract. A standalone contract PR
must precede writer implementation; this design does not supply it.

Each phase needs explicit owner authorization, exact-base branch, natural
exact-head CI, independent runtime/semantic review, authorized merge and exact
main post-merge closure before the next phase. No phase is authorized here.
L3.1 can test explicit already verified facts without L3.2 generation.

## 27. Non-Goals and Locks

No runtime implementation, old authority edits, test/CI/classifier changes,
version/tag/release/package publication, migration, Catalog/CLI, provider,
calendar acquisition, Moomoo/OpenD, schedule persistence or live operation.
In particular no current-time or environment-derived Dataset authority.

```text
L3_CROSS_DAY_DATASET_DESIGN_PREFLIGHT_AUTHORIZED=true
L3_CROSS_DAY_DATASET_IMPLEMENTATION_STARTED=false
L3_CROSS_DAY_DATASET_IMPLEMENTATION_AUTHORIZED=false
L3_CROSS_DAY_GENERATOR_IMPLEMENTATION_STARTED=false
L3_CROSS_DAY_GENERATOR_IMPLEMENTATION_AUTHORIZED=false
L3_CROSS_DAY_ARTIFACT_IMPLEMENTATION_STARTED=false
L3_CROSS_DAY_ARTIFACT_IMPLEMENTATION_AUTHORIZED=false
L4_IMPLEMENTATION_STARTED=false
L4_IMPLEMENTATION_AUTHORIZED=false
NEW_DESTRUCTIVE_SURFACE_COUNT=0
MERGE_AUTHORIZED=false
PRODUCTION_OPERATION_PERFORMED=false
PRODUCTION_OPEND_USED=false
NETWORK_PROVIDER_CALL_PERFORMED=false
VERSION_CHANGED=false
VERSION=0.8.0
```
