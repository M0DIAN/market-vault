# Observation PIT Sidecar V1

Status: pre-implementation semantic freeze candidate; independent architecture
review required. This document authorizes no runtime implementation or merge.

```text
WORKSTREAM=MULTI_SOURCE_CORE_A3_OBSERVATION_PIT_SEMANTIC_FREEZE
MODE=DESIGN_ONLY
BASE_MAIN_SHA=304cc6df319505029468e918dc4f6b99c2155f63
BASE_MAIN_TREE=fb4f9d874b757a00da0d43f8b72ea7c7134a5102
VERSION=0.8.0
SELECTED_AUTHORITY_MODEL=MODEL_B
A3_IMPLEMENTATION_AUTHORIZED=false
A4_IMPLEMENTATION_AUTHORIZED=false
PROVIDER_IMPLEMENTATION_AUTHORIZED=false
```

## 1. Authority and Scope

This is the implementation-level A3 specialization of the accepted
[Multi-Source Feature Framework V1](multi_source_feature_framework_v1.md),
especially its clocks, coverage, alignment and MODEL_B sidecar decisions.
It does not replace the framework, the
[Canonical PIT contract](contracts/point_in_time_sample_assembly.md), A1
Observation identities, or the A2 immutable artifact and verified reader.
All runtime requirements below describe a future separately authorized A3.

The existing bar PIT result remains an independent authority. Observation
decisions are a parallel, pure in-memory sidecar. No observation ID is put
into a Canonical row-version field. A3 binds source declarations to Feature
pins, but neither executes Features nor creates a new Dataset cohort.

The baseline code authorities are `dataset/pit_models.py`, `dataset/models.py`
(`SpecPin`), `dataset/encoding.py`, `observation/models.py`,
`observation/identity.py`, and the A2 verified reader. All paths in this
paragraph are relative to `src/market_vault/`. Their current identity and
validation behavior is preserved, not redefined by an alternate serializer.

## 2. Input and Trust Boundary

Future A3 consumes only an existing `PITAssemblyResult`, explicitly supplied
`VerifiedObservationBuild` objects, and immutable
`ObservationPITFeatureBinding` declarations. It must not accept artifact
paths, `ObservationBuildIdentityInput`, unverified rows, caller-authored pins,
provider objects, or a validation-bypass option. A2 loading happens before A3.

Validate declarations even when the bar result has zero samples. Validate
the carried bar association schema/content and consistency of sample
references under the existing bar authority; do not change or recompute bar
selection using Observation rules. Duplicate sample keys, inconsistent bar
versions for a key, or conflicting bindings for a Feature pin fail assembly.
Identical duplicate bindings may collapse; two different SourceSpec IDs for
one Feature pin must fail. Input order is never authority.

Considered builds for a decision are all explicitly supplied builds with the
exact resolved source scope, including overlaps and EMPTY builds. A matching
scope with a wrong contract, schema or authority is an error, not a build to
filter away. Builds for other explicitly declared scopes are routed only to
those scopes; an input build matching no declared scope fails admission.
SAMPLE_CODE's complete finite map defines its declared entity scopes even
with zero samples. There is no implicit latest-build choice or path discovery.

A3 is pure in-memory after loading: no `open`, `Path.read_*`, `Path.write_*`,
`mkdir`, rename, remove, `rmtree`, scanning, cwd, settings, environment lookup,
current time, network, OpenD or provider callback. No destructive-operation
contract is needed for this computation. A3 does not reopen the A2 publication
contract or gain cleanup authority.

## 3. Source and Feature Declarations

### 3.1 ObservationSourceSpec

The SourceSpec is a deeply immutable in-memory declaration, not a separately
loaded spec file. Its exact field set is:

| Field | V1 type and constraint |
| --- | --- |
| provider_id, source_kind, observation_name | Exact A1 text tokens. |
| dimensions | Tuple of exact A1 ObservationDimension coordinates: name, logical_type, value; unique normalized names, sorted by normalized name. |
| entity_binding | Exactly EXACT_ENTITY or SAMPLE_CODE. |
| entity_id | Exact A1 entity token for EXACT_ENTITY; typed null otherwise. |
| code_entity_map | Complete finite nonempty map for SAMPLE_CODE; empty otherwise. |
| input_field_names | Nonempty ordered tuple of distinct exact value-schema field names. |
| value_schema_id | Exact A1 value-schema SHA-256 identity. |
| provider_contract_version, provider_contract_content_id | Exact contract pin. |
| normalization_version, normalization_content_id | Exact normalizer pin. |
| known_at_authority_policy_version, known_at_authority_policy_content_id | Exact reusable authority-policy pin. |
| alignment | EXACT_EVENT_TIME or LATEST_EFFECTIVE_AT_OR_BEFORE only. |
| exact_target_binding | FEATURE_WINDOW_CLOSE or FEATURE_WINDOW_START for EXACT_EVENT_TIME; typed null for LATEST_EFFECTIVE_AT_OR_BEFORE. |
| max_age_us | Exact positive integer, not bool, float, null, NaN or infinity. |
| missing_policy | EXCLUDE_SAMPLE or FAIL; no default. |

Use existing A1 NFC/text validation, including unsafe-text rejection and no
surrounding whitespace; do not lowercase provider/entity tokens. Hashes are
lowercase 64-hex. All instants are aware, normalized by the existing UTC
microsecond rule, with no floating-point epoch conversion. Durations are
elapsed UTC microseconds, not calendar/trading days. An unrepresentable
`T - max_age_us` fails configuration; it is not clipped or rounded.

Dimensions preserve the full normalized A1 ObservationDimension semantics,
including the explicit logical_type and its typed value. Supported logical
types and value validation remain exactly A1's: at this base, string, int64
and float64 with their existing text, numeric, bool-rejection and finite-value
rules. Do not infer logical_type from a Python value, coerce a numeric dimension
to text, or otherwise change A1 normalization. Permuting dimension input order
does not change the normalized tuple or SourceSpec identity.

Code keys use exactly `PITSample.request.code` normalization: reject unsafe
text before stripping, then NFC, strip and uppercase. Duplicate normalized
keys fail even if the entities agree. Sort the complete mapping by normalized
code; multiple codes may explicitly name the same entity. Unknown sample code
or multiple bindings for a code fail. No ticker guessing, symbol-prefix
inference, locale collation or lookup outside the supplied map is permitted.

### 3.2 Strict V1 Admission

For a decision, scope is exactly `(provider_id, source_kind, resolved entity_id,
observation_name, dimensions)`, not a partial match. Compare the exact normalized
ObservationDimension tuple, including name, logical_type and typed value,
against ObservationCoverage.scope and row scope. A dimension logical-type
mismatch fails admission, even when values have the same printed form or
compare numerically equal in Python; it also changes observation_source_spec_id.
Every considered build must have that coverage scope and the exact declared coverage provider
contract. Its provider pins must include that exact contract. Its normalizer
pins must include the exact declared normalizer and cannot conflict at that
version. Extra unused pins remain provenance, never alternate normalizers.

All scoped rows, including clock-ineligible rows, must use exactly the declared
provider contract, normalization version/content ID and value_schema_id.
Validate ordered input_field_names against the reconstructed value schema;
do not infer a new schema from numeric values. In an EMPTY build the schema ID
and field names remain declared pins, not a claim of numeric row verification.
No drifted row may be silently removed to make a decision possible.

A1 `known_at_authority_id` remains record-specific immutable evidence. The
SourceSpec's authority-policy pin names a reusable policy, not that record.
Every considered build must pin the policy content ID in
`authority_evidence_ids`, as well as the A1-required row evidence. The exact
provider contract content ID is the semantic authority linking the contract
to its accepted known-at method. Pin presence does not invent or independently
qualify a provider policy. Unknown/unqualified authority fails; no generic
capture-time fallback is introduced.

### 3.3 ObservationPITFeatureBinding

One binding is an existing `SpecPin(kind=FEATURE)` plus one normalized
ObservationSourceSpec. The SpecPin fields remain `kind`, `name`, `version`,
`content_sha256`; LABEL, SPLIT and a new SOURCE kind are not accepted here.
Its stable A3 identity hashes all four normalized fields, not name alone.

A3 validates pin shape/kind, SourceSpec and PIT authority. It does **not**
verify that FeatureSpec bytes embed that SourceSpec; A4 must establish that
link before execution. A3 binds both identities so A4 cannot silently replace
either. Changing alignment, the complete entity map, field order, policy,
freshness or missing policy changes the SourceSpec identity. A future
publication-order mode needs a separately versioned contract and a changed
Observation FeatureSpec identity, hence changed new-cohort Dataset identity.

## 4. Three Independent Clocks

For each existing bar sample:

```text
T = sample.request.feature_window_close
A = sample.dataset_as_of
market_visible = known_at <= T
archive_visible = (A is null) OR (archive_available_at <= A)
eligible = market_visible AND archive_visible
effective_admissible = event_time <= T
```

All comparisons are inclusive. EXACT_EVENT_TIME may bind its target to the
feature-window start, but visibility and age still use T, not the target.
The bar window remains half-open under its existing contract; this does not
make the Observation instant or coverage bounds half-open.

Never substitute `min(T,A)` or use capture order, filesystem mtime,
build.created_at, input order, lexical revision ID, snapshot ID, version ID or
build ID as economic-selection authority. `known_at` controls visibility and
revision eligibility, not ordering across distinct economic observations.

## 5. Coverage Proof Before Selection

### 5.1 Conservative Archive Availability

A1 ObservationCoverage has no archive clock. Without changing A1 or A2:

```text
coverage_proof_available_at = VerifiedObservationBuild.created_at
COVERAGE_PROOF_AVAILABILITY_MODEL=VERIFIED_BUILD_CREATED_AT_CONSERVATIVE_BOUND
```

This is **not** a claimed earliest possession time of provider evidence. It is
the conservative proved upper bound at which the exact coverage declaration,
revision-inventory claim and pinned evidence IDs existed in this verified
artifact. For A non-null, a proof is usable only if this bound is `<= A`.
This may reject a historically reconstructible case. It must not backdate a
proof to a row or snapshot possession time.

This rule gates only completeness, revision-inventory and absence proof.
It does not replace any row's archive_available_at, choose an economic
revision, or make the physical build timestamp part of A1 build identity.
A late-created build remains pinned and may supply row facts/diagnostics;
its proof is unavailable at A. Independently eligible coverage must prove the
decision domain and revision completeness. Without that proof, fail even if
some supplied row looks usable. An unavailable proof is not by itself a
row-level ARCHIVE_FUTURE outcome.

### 5.2 Minimum Required Domain

| Alignment | Minimum required effective-time domain |
| --- | --- |
| EXACT_EVENT_TIME | Closed singleton [target, target]. |
| LATEST_EFFECTIVE_AT_OR_BEFORE | Closed interval [T - max_age_us, T]. |

For LATEST this is the fresh-usability domain. It proves whether a fresh usable
observation can exist, not that an older supplied row is the latest effective
observation. Selecting an older row requires the additional continuous domain
in 5.3. The proof eligibility and interval-combination rules below apply to
both the minimum domain and any required extension.

Both A1 coverage flags must be true: `request_pages_complete` and
`revision_inventory_complete`. Each used proof must have
`knowledge_start <= T <= knowledge_end`, the exact scope/provider contract,
and archive eligibility under 5.1. In particular `knowledge_end >= T` is
mandatory; a future-only knowledge interval cannot prove absence at T.
Its knowledge interval must contain each row/revision it contributes. Retain
and check the full pinned coverage declaration and evidence; no count, row
minimum, row maximum or newer row substitutes for revision-history proof.

Combine only exact-scope/exact-contract effective intervals. Clip them to the
required domain, sort by `(effective_start, effective_end, coverage_id,
coverage_proof_available_at, observation_build_id)` for proof bookkeeping,
and require full coverage with no microsecond gap. On the discrete UTC
microsecond axis, adjacent closed intervals with next_start <= previous_end
+ 1 microsecond are continuous. The first and last required instants must be
covered. Sorting proofs is not choosing observations. All qualifying proofs
are retained; do not choose an input-order-dependent minimal cover.

Revision completeness through T must be established for each contributing
key, including supplied older keys that might be selected as STALE. Reconcile
the union of supplied chains against the complete inventories. A claim of
completeness cannot hide a missing predecessor, fork or conflicting revision.
Every contributing row remains within its containing build's declared
effective and knowledge ranges as required by A1/A2. A late proof cannot fill
a hole in archive-eligible knowledge/absence authority. Failure to prove
completeness through T is an authority failure, never FUTURE_KNOWN or normal
missingness.

### 5.3 Older History and EMPTY Builds

Distinguish **FRESH-USABILITY PROOF** from
**EXACT STALE-CANDIDATE PROVENANCE PROOF**. Neither claims global all-history
completeness. For LATEST_EFFECTIVE_AT_OR_BEFORE:

1. First prove the normal closed fresh domain `[T - max_age_us, T]`.
2. After revision reconciliation and the existing visibility/effective gates,
   identify the tentative unique greatest supplied eligible candidate. If its
   event_time is `>= T - max_age_us`, no older-domain extension is required.
3. If its event_time is `< T - max_age_us`, it is not yet a proved latest
   selection. Before recording selected references, eligible coverage proofs
   must establish continuous effective-time coverage over
   `[tentative.event_time, T]`. Equivalently, extend the already proved fresh
   domain with `[tentative.event_time, T - max_age_us]`, without a missing
   microsecond. Use the same exact scope/provider contract, complete revision
   inventory, knowledge-through-T and coverage-proof archive gates as in 5.2.
4. Only after this extension proves the candidate is actually latest may it
   become selected; then apply value status and freshness. For VALUE under
   EXCLUDE_SAMPLE, emit EXCLUDED/STALE and preserve all eight selected fields
   in section 9. FAIL still fails assembly. Existing NOT_REPORTED/WITHDRAWN
   precedence remains unchanged; it cannot bypass proof of a latest selection.

The proved stale-selection domain is therefore `[selected.event_time, T]`.
If the tentative greatest supplied eligible candidate is older than the fresh
domain but the extension cannot be proved, **FAIL AUTHORITY**: fail the entire assembly regardless of
missing_policy. Do not silently select it, ignore it, emit STALE with unproved
references, or relabel the result NO_ELIGIBLE_OBSERVATION. Proving only that
row's own point/revision plus the fresh domain is insufficient. No backward
search or alternate older-candidate substitution repairs the proof failure.

All extension proofs must come from the explicitly considered verified builds.
Their ObservationBuildPins remain in considered_observation_builds_digest,
including coverage-only builds; there is no hidden proof input or
input-order-dependent proof selection.

Normative example: let integer microsecond coordinates denote offsets from
one fixed aware UTC instant, with `T=100us` and `max_age_us=10us`. Complete
coverage `[90,100]` contains no rows. A supplied eligible VALUE at event 50 has
its own point/revision proved, but instants 51 through 89 are uncovered. The
outcome is FAIL AUTHORITY, not event 50 / STALE: an unproved event at 80 could
exist. In the paired positive case, continuous eligible coverage `[50,100]`
and complete revision inventories establish no later eligible observation.
Select event 50, then emit STALE under EXCLUDE_SAMPLE, retaining selected
references with no backward search.

If the fresh domain is fully proved, no eligible candidate exists there and
no older candidate is supplied, NO_ELIGIBLE_OBSERVATION remains allowed under
the existing no-candidate rules. It means no usable eligible candidate was
established by the exact proved decision-relevant domain, not that the series
never existed. Unproved older history cannot make that sample usable, but this
limited usability fact cannot justify selecting any particular stale row.

EMPTY is admissible only as a verified complete declaration with the same
proof-clock gate. An EMPTY proof created after A cannot prove historical
absence. If it is the only proof of a required interval, fail assembly.

## 6. Revision Reconciliation

Reconcile across **all** considered verified builds, not one winner build.
A2 structural validation remains necessary but is not sufficient for a union.

1. Collapse identical observation_version_id occurrences with identical full
   typed A1 row facts. Retain the sorted set of containing logical build IDs
   and every distinct physical-proof pin. Same ID with different facts fails.
2. Group by observation_key, then economic revision_id. Repeated captures may
   differ only in the A1/A2 capture facts: archive_available_at,
   source_snapshot_id, source_content_sha256 and derived version ID. Value
   schema/values/status, known_at/authority, contracts, normalization and
   revision relation must agree. Conflict fails before clock filtering.
3. Reconcile one connected non-forking chain with one initial revision, no
   missing/self predecessor, no cycle, and strictly increasing successor
   known_at. Never order revisions lexically. Apply these structural checks
   to the union before discarding future captures.
4. Filter captures by known_at <= T, then archive_available_at <= A if A
   exists. A revision is eligible if at least one of its captures is eligible.
5. Select the unique terminal eligible economic revision for each key: no
   other eligible revision is its descendant in the reconciled full chain.
   Chain reachability is retained even across an ineligible intermediate
   revision. No eligible revision means no candidate for this key; multiple
   terminal eligible revisions or unproved reachability fail.
6. Within that revision only, choose the eligible provenance capture by
   ascending `(archive_available_at, source_snapshot_id,
   observation_version_id)`.

A future-known correction leaves the older market-visible revision eligible;
an archive-future correction leaves the older archive-eligible revision
eligible. A visible WITHDRAWN is still the terminal revision, not permission
to resurrect its predecessor.

For a selected version in multiple builds, the singular
`selected_observation_build_id` is the lexically smallest containing logical
build ID. This is provenance representation only. It cannot affect revision
choice, effective alignment, age, status or missingness. All considered pins
remain recorded, including duplicates of a logical build with distinct proof
availability. Adding identical-version provenance can change provenance
digests without changing the economic decision.

## 7. Alignment, Status and Missingness

### 7.1 Fixed Selection Order

LATEST_EFFECTIVE_AT_OR_BEFORE executes exactly:

1. Validate source declaration.
2. Validate coverage authority.
3. Group by observation_key.
4. Reconcile revision chains.
5. Apply known_at <= T.
6. Apply archive_available_at <= A when A exists.
7. Choose one eligible economic revision per key, with its capture provenance.
8. Restrict to event_time <= T.
9. Select the unique key with greatest event_time.
10. Apply value status.
11. Apply freshness.

At step 9, an older tentative candidate cannot become the selected latest
observation until the extended coverage proof in 5.3 succeeds. This is a
selection-authority check before status/freshness, not backward substitution
or a change to revision-before-alignment or event-time ordering.

Distinct keys tied at the greatest event_time fail assembly, even if values
agree. No ID or input-order tie-break is allowed. A correction of K_old at a
later known_at does not displace K_new with a greater event_time. The
correction is authoritative only when using K_old.

EXACT_EVENT_TIME uses the same validation/reconciliation/clock gates. Its
target is exactly T for FEATURE_WINDOW_CLOSE or exactly
`sample.request.feature_window_start` for FEATURE_WINDOW_START. After choosing
eligible revisions, retain only event_time == target (also event_time <= T).
One distinct key is required; zero yields explicit missingness, more than one
fails. No rounding or day matching.

The V1 mode set is exactly EXACT_EVENT_TIME and
LATEST_EFFECTIVE_AT_OR_BEFORE. Reject LATEST_PUBLICATION_AT_OR_BEFORE, nearest,
floor-day, calendar-asof, tolerance, forward fill, backfill and interpolation.
Unknown modes fail even with zero samples. A separately named publication
policy remains a future contract, not a synonym for latest effective.

### 7.2 Freshness and Selected-Candidate Outcomes

```text
age_us = T - selected.event_time
fresh = 0 <= age_us <= max_age_us
```

Calculate exact elapsed integer microseconds after selection. Equality is
fresh. Corrections do not reset economic age. Do not search backward after a
stale, NOT_REPORTED or WITHDRAWN selection, or substitute zeros/interpolation.

The selected-candidate reason precedence is exactly WITHDRAWN, NOT_REPORTED,
STALE, then COMPLETE (reason typed null). VALUE is consumable by future A4
only when fresh and all authority/schema gates pass. WITHDRAWN and
NOT_REPORTED never supply values. This precedence is diagnostic, not a
different selection algorithm.

### 7.3 No-Candidate Reasons and Policies

The exact exclusion vocabulary is FUTURE_KNOWN, ARCHIVE_FUTURE,
NO_ELIGIBLE_OBSERVATION, NOT_REPORTED, WITHDRAWN and STALE.

For a genuinely empty alignment candidate set, use this deterministic rule
after all authority checks pass:

1. If A exists and removing only the row archive filter would leave at least
   one market-visible aligned candidate, use ARCHIVE_FUTURE.
2. Otherwise, if a supplied scoped capture with known_at > T satisfies the
   effective alignment predicate, use FUTURE_KNOWN.
3. Otherwise use NO_ELIGIBLE_OBSERVATION.

The effective predicate is event_time == target for EXACT and event_time <= T
for LATEST. Future-effective rows alone cannot cause FUTURE_KNOWN. These are
diagnostic existence probes over supplied facts, not permission to consume a
future revision, to relax coverage-proof gates, or to choose a winner among
clock-ineligible keys. ARCHIVE_FUTURE takes precedence when both populations
exist. Neither reason substitutes for unproved coverage.

Under EXCLUDE_SAMPLE, any non-COMPLETE decision has status EXCLUDED. One
excluded required Feature excludes that sample from a future A4 matrix, but
A3 still evaluates and records all independent Feature decisions. Under FAIL,
any such outcome fails the whole assembly; no partial trusted sidecar is
returned. Configuration/authority failures always fail assembly under either
policy, including holes, unknown authority, schema drift, malformed pins,
tamper, wrong contract, revision ambiguity or eligible alignment ties.

### 7.4 archive_limited

Every decision has an identity-bearing exact bool. It is false when A is null.
With A present it is true for ARCHIVE_FUTURE. For a selected candidate it is
true if the market-only reconciliation (known_at gate retained, row archive
gate removed) demonstrates either:

- an aligned key with a greater event_time than the actual latest-effective
  selection; or
- a later chain revision of the actually selected key that was unavailable
  solely under A.

The first condition applies to LATEST; EXACT has one fixed target and uses the
second condition. This detects selection of older effective/revision evidence,
not merely the presence of some irrelevant archived-future row. Unrelated
older keys or identical-revision extra captures alone do not set the flag.
An archive-ineligible distinct key at the same event_time does not itself
mean older evidence was selected; it remains a counted excluded fact, not a
lexical tie-break. The probe returns facts/sets, never chooses a counterfactual
winner or fails on a tie that is absent from the actually eligible set.
Unavailable coverage proofs remain unavailable during the probe.

## 8. Provenance Pins

Pins are reconstructed only from VerifiedObservationBuild, never accepted as
caller-authored proof. Relocation does not affect them. All sets below are
canonical sorted sets; reject conflicting duplicate identities.

### 8.1 ObservationSnapshotPin

The exact field set is source_snapshot_id, source_content_sha256, provider_id,
source_kind, provider_contract_version, provider_contract_content_id,
normalized_request_id, acquisition_receipt_id, acquisition_receipt_content_id,
and completed_possession_at. IDs and instants use their A1 types. No path or
URL. Reconstruct the ID from the verified snapshot, including its A1 members;
the ID binds those members without flattening or inventing bar-session fields.
Coverage identity is bound by the enclosing ObservationBuildPin, not a fake
snapshot date or an independently mutable coverage claim.

### 8.2 ObservationBuildPin

The exact field set is:

```text
observation_build_id
observation_content_id
observation_schema_version
coverage_id
coverage_proof_available_at
status
authority_evidence_ids
provider_contracts
normalizations
source_snapshots
selected_observation_version_ids
```

`status` is the verified A2 COMPLETE/EMPTY status, not decision status.
`source_snapshots` is the exact tuple of ObservationSnapshotPins sorted by
source_snapshot_id. Contract tuples are sorted by (version, content_id);
authority IDs and selected version IDs are sorted lexically. Coverage's exact
A1 identity includes its closed ranges and evidence pins. The assembly keeps
the verified coverage object with the pin so coverage can be checked, not
merely a claimed digest.

Pins are per decision. selected_observation_version_ids is empty for genuine
no-candidate outcomes; otherwise it includes the selected version in every
containing build, even for STALE/NOT_REPORTED/WITHDRAWN. All other considered
builds have empty selected sets. This supports exact bidirectional membership
checking while the row carries only one representative build ID.

Pin all selected, overlapping, EMPTY and coverage-only builds, including all
proofs used by the extended stale-selection domain, and late-created
builds considered for row facts. Do not deduplicate solely by logical build ID:
same observation_build_id with different coverage_proof_available_at gives
different A3 pins. Only identical complete pins collapse. Sort by the complete
pin digest. This ensures physically different proof bounds cannot silently
share provenance without changing A1 observation_build_id.

## 9. Decision Sidecar and Diagnostics

```text
OBSERVATION_ASSOCIATION_SCHEMA_VERSION=observation-association-v1
```

One row exists for every `(sample_key, feature_spec_pin_id)` pair in the
validated samples x bindings product. Order by those two fields. No early
omission of excluded Features. Empty products have a real schema-bound content
identity. The ordered exact field/type list is:

| Fields in order | Type |
| --- | --- |
| sample_key, bar_sample_version_id | Existing bar identity strings. |
| feature_spec_pin_id, observation_source_spec_id | SHA-256 strings. |
| T | UTC microsecond instant. |
| A | Nullable UTC microsecond instant. |
| considered_observation_builds_digest | SHA-256 string. |
| status | COMPLETE or EXCLUDED. |
| reason | Nullable fixed exclusion enum. |
| archive_limited | Exact bool. |
| selected_observation_key, selected_observation_version_id, selected_observation_build_id, selected_source_snapshot_id, selected_known_at_authority_id | Nullable SHA-256 strings. |
| selected_event_time, selected_known_at, selected_archive_available_at | Nullable UTC microsecond instants. |
| scoped_version_count, future_known_excluded_count, archive_future_excluded_count, eligible_key_count, alignment_candidate_count | Nonnegative exact integers, not bool. |

All selected fields are null together for genuine no-candidate outcomes.
Selected-but-rejected outcomes retain all selected references and instants.
COMPLETE requires a fresh VALUE with legal authority, exact schema and
reason=null. No PARTIAL status and no numeric Feature output are allowed.

Count populations are frozen per decision after cross-build identical-version
collapse and strict admission:

- scoped_version_count: all distinct supplied versions in the exact scope,
  before either clock filter or effective alignment.
- future_known_excluded_count: those versions with known_at > T.
- archive_future_excluded_count: those with known_at <= T and A non-null and
  archive_available_at > A. Zero when A is null; no double counting with the
  preceding population.
- eligible_key_count: keys with a unique terminal eligible revision after
  both clocks, before effective alignment.
- alignment_candidate_count: distinct eligible keys satisfying the effective
  predicate, before latest-max selection, value status or freshness.

Counts include supplied future-effective/older history according to these
definitions; they do not prove global completeness. No free-form diagnostic
string participates in the trusted result. Failures are not fabricated rows.

## 10. Frozen Identity Encoding

### 10.1 Scalars, Records and Sequences

`H(domain, fields)` means the existing `dataset.encoding.encode_identity`
with that exact prefix and named, typed scalar fields. Preserve its typed
null/bool/int/string/UTC-microsecond distinction and sorted field keys. No
Python repr, JSON serialization, delimiter-joined arbitrary text, float
timestamps or untyped null sentinels are allowed.

For ordered SHA-256 members define
`S(domain, members) = H(domain, {count: len(members), members: concatenated
fixed-width lowercase 64-hex members})`. This is the existing A1-style
count/fixed-width sequence model, not a new A1 algorithm. Lists of strings or
records must first hash each typed member in its own domain. Order-bearing
lists retain order; sets sort as specified. Empty sequences are valid where
the shape permits them. Omitted fields and typed null are not interchangeable.

Freeze these public domains:

```text
OBSERVATION_SOURCE_SPEC_ID_VERSION=observation-source-spec-v1
OBSERVATION_FEATURE_SPEC_PIN_ID_VERSION=observation-feature-spec-pin-v1
OBSERVATION_BINDING_ID_VERSION=observation-binding-v1
MULTI_SOURCE_SAMPLE_VERSION_ID_VERSION=multi-source-sample-version-v1
MULTI_SOURCE_PIT_CONTRACT_VERSION=multi-source-pit-v1
OBSERVATION_SAMPLE_BINDING_SCHEMA_VERSION=observation-sample-binding-v1
OBSERVATION_SAMPLE_BINDING_CONTENT_ID_VERSION=observation-sample-binding-content-v1
OBSERVATION_ASSOCIATION_CONTENT_ID_VERSION=observation-association-content-v1
```

### 10.2 Source and Pin Payloads

The following table freezes the auxiliary record/sequence domains. Record
fields are exact as named; references to earlier shapes mean all fields of
that shape, replacing only the listed nested collections with their digests.

| Identity | Domain and payload |
| --- | --- |
| Dimension item | H(observation-source-dimension-v1, {name, logical_type, value}); dimension sequence S(observation-source-dimensions-v1, normalized-name-ordered item IDs). |
| Code mapping item | H(observation-entity-map-entry-v1, {code, entity_id}); complete map S(observation-entity-map-v1, code-ordered item IDs). |
| Input field item | H(observation-input-field-v1, {name}); field sequence S(observation-input-fields-v1, declaration-ordered item IDs). |
| observation_source_spec_id | H(observation-source-spec-v1, all 3.1 scalar fields, replacing dimensions/code_entity_map/input_field_names by dimensions_digest/code_entity_map_content_id/input_field_names_digest respectively). |
| feature_spec_pin_id | H(observation-feature-spec-pin-v1, {kind, name, version, content_sha256}). |
| Snapshot pin | H(observation-snapshot-pin-v1, all ten fields from 8.1); sequence S(observation-snapshot-pins-v1, source_snapshot_id-ordered pin IDs). |
| Contract pin | H(observation-provenance-contract-pin-v1, {version, content_id}). |
| Provider pins | S(observation-provider-pins-v1, (version, content_id)-ordered contract pin IDs). |
| Normalizer pins | S(observation-normalizer-pins-v1, (version, content_id)-ordered contract pin IDs). |
| Authority IDs | S(observation-authority-pins-v1, sorted authority_evidence_ids). |
| Selected versions | S(observation-selected-versions-v1, sorted selected_observation_version_ids). |
| Build pin | H(observation-build-pin-v1, 8.2 scalar fields, replacing authority_evidence_ids/provider_contracts/normalizations/source_snapshots/selected_observation_version_ids by authority_evidence_ids_digest/provider_contracts_digest/normalizations_digest/source_snapshots_digest/selected_observation_version_ids_digest respectively). |
| considered_observation_builds_digest | S(observation-considered-builds-v1, sorted distinct complete build-pin IDs). |

These domains do not reuse observation_key, observation_version_id or any
other A1 identity domain. In particular, the separate A3
observation-source-dimension-v1 binds the explicit logical_type and typed value;
A1 observation-dimension-v1 remains unchanged. SourceSpec's exact-target typed
null and empty map for EXACT_ENTITY are included, not omitted. The complete map is bound, not
only the entity resolved for the current sample.

### 10.3 Decision and Table Content

A decision ID is `H(observation-decision-v1, all exact fields in section 9)`.
All five counts, archive_limited, clocks, excluded status/reason and complete
pin digest participate. For each sample:

```text
observation_binding_id = S(
    observation-binding-v1,
    decision IDs ordered by feature_spec_pin_id for this sample
)
```

"Complete decision rows" means the entire records, including EXCLUDED rows,
not just rows whose status is COMPLETE. A sample with no bindings gets the
real empty-sequence binding ID. Compute afterward:

```text
multi_source_sample_version_id = H(
    multi-source-sample-version-v1,
    {
        sample_key,
        bar_sample_version_id,
        observation_binding_id,
        observation_association_schema_version: observation-association-v1,
        multi_source_pit_contract_version: multi-source-pit-v1
    }
)
```

Do not change PITSample.sample_key or PITSample.sample_version_id; the latter
is bar_sample_version_id in this envelope. Decision rows do not contain the
new multi_source_sample_version_id. There is no circular hash.

The sample-binding table's exact ordered fields are sample_key,
bar_sample_version_id, observation_binding_id, multi_source_sample_version_id,
all non-null identity strings. One row per existing sample, ordered by
sample_key, under schema observation-sample-binding-v1. Hash each row with
H(observation-sample-binding-row-v1, all four fields). Its content ID is:

```text
H(observation-sample-binding-content-v1, {
    schema_version: observation-sample-binding-v1,
    rows_digest: S(observation-sample-binding-rows-v1, ordered row IDs)
})
```

The sidecar content ID is:

```text
H(observation-association-content-v1, {
    schema_version: observation-association-v1,
    multi_source_pit_contract_version: multi-source-pit-v1,
    rows_digest: S(observation-association-rows-v1, ordered decision IDs)
})
```

The fixed schema versions bind the exact ordered field/type/nullability
definitions above; a future shape change requires a new version, not extra
unhashed fields. A3 constructs deeply immutable rows/tables and verifies
cardinality, references, pin membership and recomputed decisions, not only
claimed hashes. There is no table file materialization in A3.

For future combination, freeze H(multi-source-association-content-v1, fields):
bar_association_content_id, bar_association_schema_id (both from the unchanged
PITAssemblyResult), bar_association_schema_version=pit-association-schema-v1,
observation_association_content_id,
observation_association_schema_version=observation-association-v1,
sample_binding_content_id,
sample_binding_schema_version=observation-sample-binding-v1,
multi_source_pit_contract_version=multi-source-pit-v1. This new combined ID
never overwrites the old bar association_content_id or an existing artifact.

## 11. Required Future Offline Canaries

These are design requirements, not claims that A3 tests or runtime exist.
Unless a row says otherwise, fixtures provide exact authority/schema,
complete decision-domain and revision-inventory proofs eligible at A, valid
chains and missing_policy=EXCLUDE_SAMPLE. Any older selected LATEST candidate
also has the continuous extension required by 5.3 unless the canary explicitly
tests its absence. "Fail" means whole-assembly failure
with no partial trusted result. Equality tests use exact UTC microseconds.

| # | Canary | Required outcome |
| --- | --- | --- |
| 1 | Exact event-time match at declared start or close target. | The unique eligible key is selected; fresh VALUE is COMPLETE. Visibility still uses T. |
| 2 | Exact event-time zero candidates with proved target coverage. | EXCLUDED with the 7.3 no-candidate reason; absent clock-blocked facts gives NO_ELIGIBLE_OBSERVATION and null selected fields. |
| 3 | Two eligible distinct keys at exact target. | Fail, even if values agree. |
| 4 | Ordinary latest-effective observations. | Unique greatest event_time wins, not greatest known_at. |
| 5 | OLD_EVENT_LATE_REVISION_DOES_NOT_DISPLACE_NEWER_EFFECTIVE_OBSERVATION: old event t0, newer event t2, old correction known t3 later than new publication, t0 < t2 <= T and t3 <= T. | New key wins cross-key alignment; correction remains authoritative for old key only. |
| 6 | Future-known successor correction. | Older eligible revision remains selected; no future revision consumption. |
| 7 | Market-visible successor has archive_available_at > A. | Older archive-eligible revision remains selected; archive_limited=true. An independently eligible proof must cover completeness through T. |
| 8 | Equivalent repeated captures. | Select ascending archive/snapshot/version representative among eligible captures, never between economic revisions. |
| 9 | Latest supplied eligible VALUE is older than T - max_age_us; continuous eligible coverage [candidate.event_time, T] proves it is truly latest. | After extended proof, select then EXCLUDED/STALE; preserve references and never search backward. |
| 10 | Latest newer key is NOT_REPORTED. | EXCLUDED/NOT_REPORTED; do not substitute older VALUE. |
| 11 | Terminal eligible revision is WITHDRAWN. | EXCLUDED/WITHDRAWN; no predecessor resurrection, including if stale. |
| 12 | Distinct eligible keys tie at greatest event_time. | Fail, with no lexical winner. |
| 13 | archive_available_at == A. | Row eligible; archive equality alone does not exclude. |
| 14 | known_at == T. | Market-visible. |
| 15 | age_us == max_age_us. | Fresh; VALUE may be COMPLETE. |
| 16 | One-microsecond uncovered instant in required coverage. | Fail regardless of rows or missing policy. Adjacent closed ranges without a missing instant may combine. |
| 17 | Sole needed coverage proof created after A. | Fail as unavailable archive proof, not an ordinary missing reason. |
| 18 | Sole EMPTY proof created after A. | Cannot prove historical absence; fail. |
| 19 | Complete fresh-domain coverage, no eligible candidate and no supplied older/clock-blocked candidate. | NO_ELIGIBLE_OBSERVATION; do not assert all-history nonexistence. |
| 20 | Permute considered build inputs. | Same decisions, counts, pins and all A3 identities. |
| 21 | Same identical version in additional considered builds. | Same economic choice; singular provenance is smallest containing build ID; all pins retained, provenance digest may change. |
| 22 | Same version ID with conflicting typed facts. | Fail before visibility filtering. |
| 23 | Permute Feature pin/SourceSpec binding inputs. | Same row order and identities; conflicting duplicate Feature pin bindings fail. |
| 24 | One required Feature excluded, another COMPLETE. | Record both decisions; future A4 excludes sample. With FAIL policy, no partial trusted sidecar. |
| 25 | Unknown alignment, zero samples. | Fail declaration validation. |
| 26 | Same logical build ID, different verified created_at. | Distinct proof pins and considered digest; never silently deduplicate by build ID. |
| 27 | coverage_proof_available_at == A. | Proof archive gate allows equality; row clocks still independently required. |
| 28 | Complete effective range but knowledge_end < T. | Fail revision-completeness authority, not FUTURE_KNOWN. |
| 29 | Cross-build fork/missing predecessor or conflicting repeated economic revision. | Fail even if the conflicting row is clock-ineligible. |
| 30 | Unknown sample code, duplicate normalized map code, wrong policy pin, normalizer or schema. | Fail; no inference or silent filtering. |
| 31 | Both future-known and market-visible archive-future aligned populations, no actual candidate. | ARCHIVE_FUTURE; disjoint clock counts; null selected references. |
| 32 | Only future-effective rows. | They cannot cause FUTURE_KNOWN or become candidates at T. |
| 33 | Change only missing policy, max age, field order or unused map entry. | SourceSpec and dependent identities change. |
| 34 | Add duplicate identical physical-proof input, or relocate a verified artifact. | Canonical pin deduplication/location independence leaves A3 result unchanged. |
| 35 | Unavailable proof accompanies separately proved archive-eligible row facts. | Do not substitute build.created_at for row archive visibility; unavailable proof cannot fill coverage holes. |
| 36 | archive-future correction of an older key while a newer effective key wins unchanged. | archive_limited=false unless the selected decision itself uses older evidence under 7.4. |
| 37 | EMPTY proof has knowledge_start > T although knowledge_end >= T. | Fail: a future-only knowledge interval cannot establish completeness or absence at T. |
| 38 | Same normalized dimension name with different explicit logical_type, e.g. int64 value 1 versus float64 value 1.0. | Different observation_source_spec_id; exact typed dimension scope mismatch fails admission. No Python numeric-equality shortcut. |
| 39 | Typed numeric dimension, e.g. int64 value 1, versus string value "1". | Numeric value stays numeric with its declared logical_type; no conversion to text. Distinct SourceSpec identities and scopes. |
| 40 | Permute dimension input order with unchanged exact typed coordinates. | Same normalized name-sorted tuple and observation_source_spec_id. |
| 41 | T=100us, max_age_us=10us; no fresh rows; complete [90,100] plus only the supplied eligible event-50 point/revision proof, with 51..89 uncovered. | FAIL AUTHORITY regardless of missing_policy; not event 50 / STALE and not NO_ELIGIBLE_OBSERVATION. An event at 80 has not been excluded by proof. |
| 42 | Paired case: T=100us, max_age_us=10us, eligible VALUE at 50, continuous eligible [50,100] proof with no later eligible observation. | Select event 50 only after extended proof, then EXCLUDED/STALE; preserve all selected references, pin every used proof, no backward search. |

## 12. Unchanged Contracts and Deferred Work

```text
CANONICAL_PIT_CHANGED=false
PIT_ASSOCIATION_V1_CHANGED=false
PIT_SAMPLE_KEY_CHANGED=false
PIT_SAMPLE_VERSION_ID_CHANGED=false
A1_IDENTITY_CHANGED=false
A2_ARTIFACT_FORMAT_CHANGED=false
A2_READER_CHANGED=false
EXISTING_DATASET_IDENTITY_CHANGED=false
EXISTING_FEATURE_SPEC_V1_CHANGED=false
PIT_ASSOCIATION_V1_ARTIFACTS_REMAIN_VALID=true
NO_IMPLICIT_FORWARD_FILL=true
TEXT_FEATURE_EXECUTION_IN_V1=false
OBSERVATION_FEATURE_EXECUTION_IMPLEMENTED=false
MULTI_SOURCE_DATASET_COHORT_IMPLEMENTED=false
PROVIDER_IMPLEMENTED=false
CATALOG_INTEGRATION=false
```

A1 frozen vectors and A2 physical versions/reader trust entry point remain
unchanged. There is no artifact migration or rewrite. The three-clock model,
record authority, revision identities, MODEL_B and separate future
ObservationFeatureTransformInput remain the framework's decisions.

No A3 runtime, A4 Feature execution, Dataset manifest/reader v2, Dataset cohort,
Catalog integration, Treasury, CFTC, Moomoo Options, SEC, network acquisition,
OpenD or production operation is in this PR. Future provider ordering remains
Treasury, then CFTC, then Options, subject to separate qualification and
authorization. No provider is qualified by this document. Version stays 0.8.0.

## 13. Design Validation and Review Gate

Only this new document changes. Local design validation is `git diff --check`,
repository hygiene and the release checker, with all temporary/log output on
D:. No runtime tests or code changes are authorized for this freeze. Natural
PR CI should classify the docs-only diff as docs_fast; do not force a tier or
weaken a repository-required gate. Capture exact-head CI evidence in the PR.

Commit and PR publication do not approve implementation or merge. Stop for
independent architecture review; a later owner authorization is required for
A3 implementation, and A4/provider work remains separate.
