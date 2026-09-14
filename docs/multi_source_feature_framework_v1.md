# Multi-Source Feature Framework V1

## 1. Scope and Governance

```text
DESIGN_ONLY=true
DESIGN_APPROVAL_REQUIRES_INDEPENDENT_REVIEW=true
DESIGN_DOCUMENT_SELF_APPROVAL=false
IMPLEMENTATION_REQUIRES_POST_MERGE_AUTHORIZATION=true
BASE_MAIN_SHA=7be596e8ba7731a4870a21fde09ccc3dc2190fd7
BASE_MAIN_TREE=e4d789e0009ffcd39933c6b33d710525276eb3c6
SELECTED_AUTHORITY_MODEL=MODEL_B
RUNTIME_IMPLEMENTED=false
PROVIDER_IMPLEMENTED=false
VERSION=0.8.0
```

[ADR 0004](adr/0004-multi-source-feature-authority.md) selects parallel,
immutable non-bar observation authority, preserving Canonical Market Bars.
Sections describing new types/versions are future normative design, not
claims about exported Python APIs. This document alone grants no implementation,
merge, provider collection or release authority. Approval is established by
independent review and merge; implementation requires separate authorization.

V1 augments **Canonical-anchored samples** with numeric non-bar Features.
Observation-only sample generation, non-bar Labels, arbitrary transforms,
dynamic plugins, text/embeddings/LLM execution, REST, ML, backtesting, signals,
trading and live capture are outside this PR. No source, tests, database,
version-bearing files or old contracts change. The sealed v0.8 release stays
immutable. No provider API was called to prepare this repository audit.

## 2. Current Authorities

All source findings below refer to the exact base above. Links identify
repository files; symbols/sections identify the inspected behavior. Historical
contract status paragraphs are point-in-time records, not the current feature
inventory. The actual base source decides current support.

| Authority | Verified current behavior and consequence |
| --- | --- |
| [ADR 0001](adr/0001-canonical-ml-dataset-boundary.md), decisions 1-6 | Canonical is the materialized market-bar authority; business keys are separate from row versions. Dataset exports are never authoritative inputs to other Dataset builds. ADR 0004 extends only the non-bar exclusivity boundary. |
| [PIT assembler](../src/market_vault/dataset/pit.py), `assemble_point_in_time_samples`, `_reconcile_rows`, `_select`, `_association_rows` | Input items must be `VerifiedCanonicalBuild`. Conflicting candidates for one bar key fail; no newest-build winner. Association columns explicitly bind `canonical_build_id`, `canonical_bar_key`, `canonical_row_version_id`. Market/archive equality is allowed. |
| [PIT models](../src/market_vault/dataset/pit_models.py), `PITObservationWindow`, `PITSampleRequest`, `PITSample` | Event windows are half-open `[start, close)`. Instants normalize to UTC microseconds. `adjustment != NONE` fails. Feature/Label row-version tuples and considered build IDs remain bar-specific. |
| [PIT identity](../src/market_vault/dataset/pit_identity.py), `pit_sample_key`, `pit_sample_version_id` | Key binds request dimensions and windows, not specs, paths or as-of. Version binds key, as-of, ordered Feature/Label versions, considered builds and PIT versions. These are not generic observation IDs. |
| [Feature contract](contracts/built_in_feature_execution.md), sections 7, 12-18; [executor](../src/market_vault/dataset/feature_execution.py), `_CANONICAL_INPUT_FIELDS`, `_validate_row`, `_trailing_window`, `_bar_input_row` | Consumable value fields are exactly `open`, `high`, `low`, `close`, `volume`; registrations select subsets in declared order. Provenance must match PIT. Trailing rows must be contiguous at the nominal interval and on the anchor market date; missingness excludes or fails, never fills. |
| [Feature models](../src/market_vault/dataset/feature_models.py), `FeatureTransformInput`; [registry](../src/market_vault/dataset/feature_registry.py), `built_in_feature_registrations` | Input carries field names, tuple rows of finite floats and sorted parameters. The input model alone validates shape, not OHLCV membership; the executor enforces membership. Eight fixed built-ins, non-nullable float64 outputs, source support exactly `("10.9",)` at this base. TS2 normalization support elsewhere does not automatically expand this registry. |
| [Label contract](contracts/built_in_label_execution.md), sections 4, 6-8, 17-24 | Four built-ins, BARS-only, exact future-row/anchor checks, actual consumed end for purging. MINUTES, TRADING_DAYS and cross-day execution fail closed. A spec's ability to express a unit does not implement it. |
| [Sample generation core](../src/market_vault/dataset/sample_generation_core.py), `generate_sample_requests`, `_preflight_feature_coverage`, `_contiguous_segments`; [models](../src/market_vault/dataset/sample_generation_models.py), `SampleGenerationRule` | Explicit paths use formal readers/spec loaders and registry preflight. Requests come from verified Canonical bar segments; BARS coverage, `VERIFIED_CANONICAL_BARS`, `FEATURE_WINDOW_CLOSE`, cross-day `REJECT`. The core reads local artifacts but performs no Dataset execution. |
| [Dataset models](../src/market_vault/dataset/models.py), `SourceSnapshotPin`, `CanonicalBuildPin`, `SpecPin`, `ImplementationPin`, `DatasetIdentityInput` | Source pins require market request date/session and run/hash provenance. Build pins are explicitly Canonical. SpecPin kinds are FEATURE/LABEL/SPLIT; ImplementationPin identifies transforms. None is a generic observation authority merely because its name sounds reusable. |
| [Dataset identity](../src/market_vault/dataset/identity.py), `dataset_id`; [manifest](../src/market_vault/dataset/manifest.py), `validate_dataset_manifest`; [orchestration](../src/market_vault/dataset/orchestration.py), `_orchestrate` | Identity binds scope, as-of, row/schema content, Canonical pins, specs, implementations, completion, gaps and versions. Manifest v1 rejects unknown fields/versions. Orchestration has no independent observation-pin or observation-association input. |
| [Dataset reader](../src/market_vault/dataset/reader.py); [Catalog identity](../src/market_vault/dataset/dataset_catalog_identity.py), `catalog_dataset_content_id`, `dataset_catalog_content_id`; [snapshot identity](../src/market_vault/dataset/dataset_catalog_snapshot_identity.py), `dataset_catalog_snapshot_id` | Reader verifies exported artifacts rather than rebuilding them. Catalog hashes verified Dataset facts including dataset_id; snapshot identity additionally binds serialized snapshot facts. Paths are descriptive, not a second Dataset loader or upstream identity. Richer observation facts need explicit future reader/cohort support. |
| [Options collector](../src/market_vault/collectors/moomoo_options.py), `MoomooOptionCollector`; [normalization](../src/market_vault/normalization/options.py) | Existing option-chain and volatility endpoints, copying provider frames; normalization produces contract/volatility rows with capture/run metadata. No generic publication/revision proof. See section 13. |
| [Service](../src/market_vault/service.py), `collect_option_chain`, `collect_option_volatility`, `_finish_dataset_run`; [Parquet store](../src/market_vault/storage/parquet_store.py), option writers; [Catalog](../src/market_vault/storage/catalog.py), `record_dataset_run`, option view refreshers | Stores Raw/Curated per request/run and records status/quality. Latest views use capture/run order, not PIT visibility. Persistence and run provenance are reusable; those views are not historical Feature authority. |
| [Adjusted-price PIT policy](adjusted_price_pit_as_of_policy_v1.md), sections 7-11 | Market/publication knowledge is independent of archive time. Current `MODEL_C_NONE_ONLY` remains mandatory. Generic observations do not qualify QFQ/HFQ, revisions of factors, or corporate-action authority. |

```text
CURRENT_PIT_SOURCE_AUTHORITY=VerifiedCanonicalBuild
CURRENT_FEATURE_INPUT_SURFACE=open,high,low,close,volume
CURRENT_OPTIONS_FIRST_CLASS_PIT_FEATURE_SOURCE=false
CANONICAL_MARKET_BAR_KEY_CHANGED=false
CANONICAL_ROW_VERSION_ID_CHANGED=false
EXISTING_CANONICAL_ARTIFACT_REWRITE_REQUIRED=false
EXISTING_DATASET_ARTIFACT_REWRITE_REQUIRED=false
QFQ_PIT_ALLOWED=false
HFQ_PIT_ALLOWED=false
```

## 3. Authority and Offline Boundaries

The ADR compares universal Canonical, parallel observation authority and
Canonical subtypes and selects MODEL_B. The minimum new data authority is an
immutable `VerifiedObservationBuild` produced by one formal observation reader.
Its normalized observations are derived from sealed source snapshots and
content-pinned provider authority, not from a Dataset, mutable latest view,
filename, response row count or cached Feature value.

```text
separately authorized collection/import
  -> immutable source snapshot + acquisition evidence
  -> deterministic normalization + formal observation verification
  -> VerifiedObservationBuild (explicit, pinned local inputs)
  -> observation PIT sidecar + unchanged Canonical PIT
  -> registered numeric Features + existing bar Labels
  -> new-cohort immutable derived Dataset

DATASET_BUILD_NETWORK_ACCESS=false
DATASET_BUILD_OPEND_ACCESS=false
NO_IMPLICIT_FORWARD_FILL=true
NO_IMPLICIT_INTERPOLATION=true
NO_IMPLICIT_BACKFILL=true
NO_SILENT_PROVIDER_FALLBACK=true
```

The artifact-loading boundary may read explicitly supplied local artifacts;
PIT selection and transforms operate purely on verified in-memory objects.
Neither boundary may refresh/download a missing input, inspect current
settings, infer cwd/latest paths, consult current time, or connect to a
provider. No database or new DuckDB table is required. Catalog indexing is
downstream, not source trust. Snapshot ingestion/materialization must receive
its own narrowly reviewed safe-path/atomic-commit contract before implementation;
this design grants no delete, quarantine, replacement or repair operation.

## 4. Observation Schema and Identities

### 4.1 Encoding and Value Scope

Use the repository's typed, domain-separated deterministic identity encoding
for scalar fields; encode ordered records as digests of typed named fields,
then ordered sequences of fixed-width digests. Do not hash arbitrary JSON,
Python repr, dict insertion order or unescaped delimiter-joined free text.
All identity versions have separate domains. Hashes are lowercase 64-hex.
Strings are NFC, nonempty, no controls or surrounding whitespace; identifiers
are provider-contract-defined exact tokens, not universal case folding.
Named dimensions are unique and sorted by name. Field order is schema order.
Paths and mutable URLs are descriptive references only, never logical keys.

Instants are timezone-aware and normalized to integer UTC microseconds; naive,
ambiguous or unrepresentable instants fail. Date/period sources need an explicit
provider-contract mapping to an effective instant/period, including timezone
and granularity. A mapped midnight is only an effective-time convention,
never proof of publication. No generic core default guesses this mapping.

V1 payloads are a finite scalar or a flat, finite numeric field tuple, with a
fixed schema of named `int64`/`float64` fields and explicit units/scales.
Scalar means one named field, not a second encoding. Reject bool as numeric,
NaN, infinity, nested arbitrary objects and undeclared columns. Normalize
negative zero; decimal-to-float conversion/rounding must be pinned by the
normalizer and schema, not inferred by Feature code. No text value, embedding,
arbitrary JSON, image or LLM result enters Feature execution. Identity labels
and provenance references may be strings; they are not text Features.

```text
TEXT_FEATURE_EXECUTION_IN_V1=false
```

### 4.2 Minimum Normalized Record

R = required; C = conditionally required; O = optional descriptive metadata.
K = logical key; V = observation version; P = PIT selection/verification;
D = Dataset identity through version/pins/decisions. A `V` field propagates to
D even if two different versions happen to produce equal numeric Features.
All fields are immutable; optional semantic fields use explicit typed null.

| Field | Meaning and normalized representation | Need | K | V | P | D |
| --- | --- | --- | --- | --- | --- | --- |
| `provider_id` | Exact registered provider namespace; an aggregator is not silently the original publisher. | R | yes | via K | exact scope | yes |
| `source_kind` | Registered information family, e.g. positioning or yield observations, independent of transport/URL. | R | yes | via K | exact scope | yes |
| `entity_id` | Namespaced economic entity/instrument/market identity; no display-name matching. | R | yes | via K | exact binding | yes |
| `observation_name` | Contract-defined series/measure identity, not an arbitrary output column alias. | R | yes | via K | exact scope | yes |
| `dimensions` | Sorted typed name/value pairs for report type, tenor, market/contract, units convention etc.; complete set declared by provider contract. | R, empty only if declared | yes | via K | exact scope | yes |
| `event_time` | Effective instant, or effective period end; UTC microseconds under declared granularity convention. | R | yes | via K | alignment/freshness | yes |
| `event_period_start` | Effective interval start; UTC microseconds with `start < event_time`, null for point observations. | C | yes | via K | scope validation | yes |
| `value_schema_id` | Hash of ordered field names, numeric types, units and scale/representation contract. | R | no | yes | type authority | yes |
| `values` | Numeric tuple in schema order; absent only for explicit NOT_REPORTED/WITHDRAWN status. | C | no | yes | selected input | yes |
| `value_status` | VALUE, NOT_REPORTED, or WITHDRAWN; never a fabricated zero/null VALUE. | R | no | yes | absence/retraction | yes |
| `known_at` | This revision's proved public-knowledge instant or explicitly qualified conservative usable bound. UTC microseconds. Also the sole `revision_known_at`; no competing second clock. | R | no | yes | inclusive cutoff | yes |
| `known_at_authority_id` | Hash of exact authority method, version and immutable evidence proving this bound for this record/revision. | R | no | yes | authority gate | yes |
| `archive_available_at` | Earliest proved local possession of all immutable evidence needed for this version, not request start or build time. UTC microseconds. | R | no | yes | inclusive archive cutoff | yes |
| `source_snapshot_id` | Acquisition-specific immutable snapshot seal, as defined below. | R | no | yes | evidence binding | yes |
| `source_content_sha256` | SHA-256 of exact source bytes, or a deterministic ordered file inventory digest for multi-file responses. | R | no | yes | integrity | yes |
| `provider_contract_version` | Exact supported provider contract version; no ranges/latest. | R | no | yes | schema/semantics gate | yes |
| `provider_contract_content_id` | Seal of the versioned contract including entity/event/value/revision/coverage semantics. | R | no | yes | authority gate | yes |
| `normalization_version` | Exact supported deterministic normalizer version. | R | no | yes | reader gate | yes |
| `normalization_content_id` | Fingerprint of the normalizer implementation and conversion rules. | R | no | yes | integrity | yes |
| `revision_id` | Exact provider revision identity or contract-derived evidence identity; not capture order. Required even for the initial vintage. | R | no | yes | revision reconciliation | yes |
| `supersedes_revision_id` | Proven predecessor for the same logical key; null only for a proved initial revision. | C | no | yes | supersession | yes |
| `observation_key` | Recomputed logical business identity. | R, derived | result | yes | grouping | yes |
| `observation_version_id` | Recomputed complete version identity. | R, derived | no | result | exact association | yes |
| `source_locator` | Original URI, local path or human citation, stored outside identity-bearing record as descriptive metadata. | O | no | no | never dereferenced by PIT | no |

An entity remapping or unit convention that changes what the measure means
requires a new logical token/dimension. It cannot masquerade as merely a new
normalizer. `value_schema_id` also prevents changing scale/type under an old
version. A record with unproven known_at cannot enter this verified schema;
the source snapshot may retain it as raw evidence, but Dataset admission fails.

### 4.3 Exact Identity Payloads

`OBSERVATION_KEY` uses domain `observation-key-v1` and exactly:
provider_id, source_kind, entity_id, observation_name, sorted dimensions,
event_time, event_period_start. No values, versions, clocks of knowledge/capture,
paths or URLs enter K. Equivalent timezone representations yield the same K.

`OBSERVATION_VERSION_ID` uses domain `observation-version-v1` and exactly:
K, value_schema_id, values, value_status, known_at, known_at_authority_id,
archive_available_at, source_snapshot_id, source_content_sha256,
provider_contract_version/content_id, normalization_version/content_id,
revision_id, supersedes_revision_id. Supersession points to revision identity,
not an acquisition-specific observation version: repeated captures must not
fork the economic revision chain. These fields are verified, not caller hints.

`source_snapshot_id` uses domain `observation-source-snapshot-v1`: exact
provider/source contract identity, normalized request identity (series, scope,
filters and pagination contract), source_content_sha256, immutable acquisition
receipt ID/content hash and receipt's completed-possession instant. Credentials,
tokens, mutable transport addresses and output paths are excluded. Different
acquisitions can share content bytes but have different snapshot IDs; neither
retrieval time nor snapshot ID establishes public known_at. An inventory hash
binds sorted relative member names, sizes and byte hashes; duplicate names or
incomplete pagination fails. Reordering provider rows may change physical bytes
and snapshot IDs; it does not change normalized logical keys or value content.

An observation build binds its exact snapshot set, authority evidence set,
observation schema and normalizer fingerprints, normalized row-content hash
and coverage proof. Row-content hash sorts by (K, observation_version_id);
conflicting duplicate version IDs fail. `observation_build_id` hashes those
facts under `observation-build-v1`. Materialization path and build wall time
are non-identity metadata. Output byte hashes still verify physical integrity;
cross-PyArrow byte identity is not promised.

The verified reader checks seals, declared file inventory, path containment,
no symlink/junction/reparse traversal, schemas, counts, all IDs, authority
references, revision consistency and coverage completeness before constructing
`VerifiedObservationBuild`. `_SUCCESS` alone or a user-constructed object is not
a second trust path. The future implementation must have one reader and one
normalization authority, not one per consumer. Copying byte-identical sealed
evidence with its original proved receipt preserves archive time; importing
unsealed historic files today cannot backdate possession.

## 5. Three Clocks and Known-At Authority

Let T be the sample's existing `feature_window_close`, A its explicit optional
`dataset_as_of`, and v an observation version. After authority validation:

```text
visible(v, T, A) =
    v.known_at <= T
    AND (A is null OR v.archive_available_at <= A)
```

Both boundaries are **inclusive**. Event time is not a substitute for either
clock. V1 effective observations additionally require `event_time <= T`;
future-effective announcements/forecasts need a later separately versioned
alignment contract. This effective-time restriction does not change existing
bar PIT's `[feature_window_start, feature_window_close)` membership.

A null A means market-knowledge reconstruction using explicitly pinned local
evidence; it does **not** claim MarketVault already held it at T. A present A
means both independent clock predicates apply; never replace them with one
minimum cutoff. Even with null A, archive time and its evidence remain required
and identity-bearing. Known-future and archive-future candidates are excluded
with separate diagnostics; a result falsely associating one fails verification.

```text
KNOWN_AT_AUTHORITY_REQUIRED=true
UNKNOWN_KNOWN_AT_FAILS_CLOSED=true
```

Provider contracts must bind the origin of known_at and revision_known_at:

| Method | Required proof and restriction |
| --- | --- |
| Exact publisher timestamp | Immutable evidence ties the exact value/vintage to an actual public release instant and timezone. A database update timestamp is not automatically publication. |
| Publication schedule | Versioned official schedule plus exact-date release evidence, delay/holiday/embargo rules and timestamp precision. A recurring expected time alone does not prove actual publication; an unproved exception fails. |
| API observation timestamp | Exact field semantics must prove when this version was publicly knowable, not merely the historical period or query-server time. Capture the binding evidence. |
| Conservative capture bound | Allowed only by an explicit qualified provider policy proving the public response contained this exact version by a completed retrieval instant. Use that instant or a later proved bound, never request start; no visibility before it. It is a conservative usable time, not a claimed original publication timestamp. No generic fallback. |

Date-only publication cannot be assigned an invented intraday instant. A
provider may qualify a conservative later bound with timezone/date and actual
release evidence; otherwise it is unproven and fails. Internal review/capture
of a document today is not evidence that a revised historic value was known
yesterday. Future qualification must archive the content of the authority,
not just its mutable URL.

`archive_available_at` is the maximum of proved local possession times of the
source bytes and all record-specific publication/revision evidence needed to
justify v. An independently provable older receipt may be preserved; absence
of such proof uses the later ingestion completion or fails, never filesystem
mtime. Normalization build time is not added merely because deterministic
normalization runs later. The Dataset's authority pins disclose the precise
evidence used and its possession provenance.

Illustrative canary, **not an assertion of a qualified current CFTC schedule**:
positions effective Tuesday, published Friday at a proved instant, archived
later. Wednesday T cannot see them; the following Monday T can see them only
after the Friday publication, subject to freshness and archive cutoff. If A
precedes capture, Monday still excludes them. Missing actual publication
evidence fails the qualification gate rather than assuming Friday.

## 6. Revisions and Coverage

Group versions by K. Each provider contract must prove an initial revision
and an unambiguous acyclic supersession chain, with strictly increasing known_at
for successive revisions in V1. Same-instant conflicting revisions or an unknown
predecessor fail; lexicographic revision IDs do not break semantic ties.
Superseded evidence remains immutable. WITHDRAWN is an explicit revision which
removes usability after its known_at, never permission to resurrect a prior
value. A provider that cannot prove historical vintages cannot qualify current
returned old-date values as original historic versions.

After visibility filtering, select the unique terminal eligible revision per
K under that chain. A newer but not-yet-known revision never overwrites an
older eligible one. Archive reconstruction similarly restricts evidence to A.
If a visible correction/withdrawal is known in the eligible evidence but its
required payload or chain is missing, FAIL BUILD; do not fall back to an older
value. If only an older complete vintage was archived by A, the reconstruction
may use it and must be labeled archive-limited, not an exhaustive statement of
all public knowledge at T.

A revision changes the historically visible version of the **same K**. Its
later known_at is a visibility clock for that revision, not an ordering
authority between distinct effective observations. Correcting an old event
does not make it the newest effective observation; cross-K alignment uses
event_time as specified in section 7.2.

Repeated captures of one revision may have different observation versions.
They must agree on values, schema, known_at authority and revision relation
under the declared provider/normalizer contract. Disagreement fails before
winner selection. For identical revision facts only, use the eligible evidence
instance with smallest (archive_available_at, source_snapshot_id,
observation_version_id) as deterministic provenance representative. This is
not authority to pick among conflicting economic values. Pin every considered
build so changing the declared reconstruction evidence changes Dataset identity.

Each observation build carries a content-identified coverage proof: exact
provider/entity/measure/dimension scope; effective-time range; knowledge-vintage
coverage; request/page completion evidence; explicit missing/not-reported
semantics; and revision inventory completeness within that scope. No row-count
or min/max-date inference substitutes for coverage. The build plan names an
exact finite set of such builds sufficient to prove each requested selection
domain. Overlapping evidence must reconcile under the same authority; holes
or unproven revision inventories FAIL BUILD. A genuinely empty, proved complete
domain may produce absence. No snapshot file at all is not an empty domain.

## 7. Feature Source Declaration and Alignment

### 7.1 Declaration Choice

Select a **new observation FeatureSpec cohort**, with an embedded immutable
`ObservationSourceSpec`. Do not change existing FeatureSpec v1, add provider
arguments to old transforms, or encode providers in free-form parameters.
No separately loaded SourceSpec file is needed in V1: its full normalized
content belongs in the Feature spec hash and stored spec artifact.

Minimum declaration (all explicit and identity-bearing):

- existing spec-style name, version, output, exact registered transform_ref
  and parameters, under `observation-feature-spec-v1`;
- provider_id, source_kind, observation_name, complete fixed dimensions;
- entity binding: EXACT_ENTITY with one namespaced entity_id, or
  SAMPLE_CODE with a pinned finite code-to-entity map and mapping content ID;
  unknown/multiple mapping fails, no symbol guessing;
- ordered input field names and value_schema_id;
- exact provider contract version/content ID, normalizer version/content ID
  and allowed known-at authority method/version/content definition;
- alignment enum; EXACT_EVENT_TIME additionally declares its target binding;
- finite positive integer max_age_us, freshness clock EVENT_TIME, elapsed-UTC
  duration semantics, and missing_policy EXCLUDE_SAMPLE or FAIL (no default).

Snapshot IDs belong in the build's input pins, not the reusable FeatureSpec.
The spec pins authority *rules*; selected versions also pin record-specific
authority *evidence*. Provider-specific names never become generic-core enum
branches. A Treasury series code from an aggregator must identify that provider;
`DGS10` must not be assumed to be a direct Treasury field without qualification.

### 7.2 Deterministic Selection

For each sample and observation Feature, validate declaration and supplied
coverage first. Reconcile revisions as in section 6, then apply the following:

| Alignment | V1 meaning |
| --- | --- |
| EXACT_EVENT_TIME | Target is explicitly either T or the existing sample's Feature-window start, expressed as a UTC instant. Require `event_time == target` and exactly one logical key in the exact declared source scope after revision selection. No rounding to a day or nearest point. Period sources must match their declared effective-end convention exactly. |
| LATEST_EFFECTIVE_AT_OR_BEFORE | Among scoped logical observations with an eligible revision and event_time <= T, choose the unique observation with greatest event_time. Distinct logical keys tied at that greatest event_time without authority proving uniqueness cause FAIL BUILD. known_at controls revision visibility, never cross-K ordering. |

The exact latest-effective sequence is:

1. Validate the source declaration and complete coverage for this sample and
   Feature before selecting any value.
2. Group versions by OBSERVATION_KEY within the exact declared source scope.
3. Resolve the unique eligible revision per K under section 6, requiring
   `known_at <= T` and, when `dataset_as_of = A`,
   `archive_available_at <= A`. Keys without an eligible revision do not
   enter cross-K alignment; malformed or ambiguous authority still fails.
4. Restrict those logical observations to `event_time <= T`.
5. Select the unique logical observation with greatest event_time. Revision
   known_at, capture time, input order and lexicographic IDs never break a
   cross-K tie. If two distinct keys share that greatest event_time and the
   authority cannot prove a unique observation, FAIL BUILD.
6. Apply staleness to that selected observation using
   `age_us = T - selected.event_time`. Never search backward for another
   observation merely because this latest-effective observation is stale.

Unknown alignment fails preflight even for zero samples. These two modes are
the complete V1 set; calendars, rolling observation windows and as-of joins
with implicit tolerances are deferred. All selected rows must satisfy the
independent archive predicate. A future Feature asking for the most recently
published event may need a separately named and versioned
`LATEST_PUBLICATION_AT_OR_BEFORE` contract. That mode is deferred, not supported
in V1, and is not an alias for generic latest-value selection.

Illustrative offline fixture (UTC instants, not provider time authority):

| Key | event_time | Eligible revision known_at |
| --- | --- | --- |
| K_old | 2026-03-01T00:00:00Z | 2026-09-11T09:00:00Z (correction) |
| K_new | 2026-09-10T00:00:00Z | 2026-09-10T18:00:00Z (initial revision) |

At `T = 2026-09-11T10:00:00Z`, with complete revision/coverage proof and
archive eligibility for both, LATEST_EFFECTIVE_AT_OR_BEFORE selects K_new.
The correction is the authoritative visible version when using K_old, but
its later publication does not displace K_new. Freshness is then evaluated
for K_new under the declared limit.

No candidate after filtering produces an explicit missing outcome. Multiple
unresolved candidates produce a build error. Each Feature uses exactly one
logical observation's finite numeric tuple in V1. A Dataset can contain many
Features from many sources; provider pre-aggregation or cross-provider joining
does not become a hidden alternate selection authority.

### 7.3 Freshness and Missingness

Apply freshness **after** alignment selection:

```text
age_us = T - selected.event_time
fresh = 0 <= age_us <= max_age_us
```

Effective time/period end is used so a correction to a six-month-old fact does
not reset its economic age merely because it was republished today. It updates
that fact's revision but does not outrank a newer effective observation merely
because its known_at is later. max_age_us must be finite and positive in both
modes. Equality is allowed. Durations are elapsed UTC microseconds, not
business/trading days; DST/weekends do not stretch them. Source-specific
calendars are not implicit V1 freshness policies. A future change of clock,
limit or calendar semantics changes the spec identity.

| Situation | V1 outcome |
| --- | --- |
| Proved complete scope but no observation existed/was published by T | EXCLUDED Feature and whole sample under EXCLUDE_SAMPLE; FAIL BUILD under FAIL. |
| Only future-known or archive-future versions; no eligible value | Same explicit policy outcome, with separate FUTURE_KNOWN / ARCHIVE_FUTURE diagnostics; never use the future version. |
| Explicit NOT_REPORTED or eligible WITHDRAWN revision | Same policy outcome; no zero/previous-value substitution. |
| Selected observation stale | Same policy outcome with STALE; do not search backward for a replacement. |
| Incomplete snapshot, missing pinned archive, coverage hole or unproved inventory | FAIL BUILD regardless of missing_policy. |
| Unknown known_at, malformed authority, schema drift, tamper/hash mismatch | FAIL BUILD regardless of missing_policy. |
| Conflicting duplicate facts, revision ambiguity, unresolved alignment tie | FAIL BUILD regardless of missing_policy. |

An excluded Feature is a typed outcome with no value, not a nullable output
column silently emitted into training. Any excluded required Feature excludes
the whole sample from the output matrix; preserve its decision/provenance in
the sidecar. Other independently selected Feature decisions may still be
recorded for audit. A configuration/authority failure fails the entire build,
not merely the affected source. "Graceful isolation" means explicit diagnostics
and reusable independent evidence, not best-effort substitution.

## 8. Pins and Association Choice

### 8.1 Pin Reuse

| Existing type | Decision |
| --- | --- |
| SourceSnapshotPin | Keep for bars. Its mandatory request date/session and ingestion-run semantics do not describe general publications. Add `ObservationSnapshotPin` with the snapshot/byte seal, acquisition receipt, provider contract and coverage identity. No fake session/date values. |
| CanonicalBuildPin | Keep for bars. Add `ObservationBuildPin` containing build/content/schema IDs, exact provider/normalizer authority IDs, exact snapshot pins, coverage ID and selected observation-version set (possibly empty for exclusion). |
| ImplementationPin | Reuse for registered observation transforms with non-null exact fingerprints. Provider/normalizer authority uses its own explicit content fields, not a transform pin with unrelated meaning. |
| SpecPin | Reuse kind FEATURE for observation Feature specs; content hash binds the new spec schema and embedded source. Do not invent kind SOURCE, which v1 rejects. LABEL/SPLIT pins unchanged. |

Pins are reconstructed from verified objects, not accepted as caller-authored
proof. Exact bidirectional coverage is required: no selected version lacking
a source pin and no unexplained selected-version pin. All considered builds
and coverage proofs are pinned, including valid domains yielding no row.

### 8.2 PIT Alternatives

| Model | Effect |
| --- | --- |
| A: replace association v1 with generic v2 | Coherent unified schema but forces bar-only producers/consumers through a wider change; old rows need parallel legacy interpretation. Not selected. |
| B: retain Canonical association plus observation sidecar | Preserves old bar selection/identities; explicitly binds two authorities in a new Dataset cohort. Smallest localized change. Selected. |
| C: unified typed source references | Extensible, but requires general typed dispatch throughout PIT/Feature/reader logic now. More abstraction than V1 needs. Not selected. |

```text
MULTI_SOURCE_PIT_BINDING_MODEL=MODEL_B_OBSERVATION_SIDECAR
PIT_ASSOCIATION_V1_ARTIFACTS_REMAIN_VALID=true
```

Retain the existing `PITSample` and `pit-association-schema-v1` content and
bar `sample_version_id` unchanged, named `bar_sample_version_id` when referenced
by the new envelope. Never put observation IDs into a canonical row-version
column. One new `observation-association-v1` decision row per
(sample_key, observation Feature SpecPin) records:

- sample_key, bar_sample_version_id, Feature SpecPin digest and resolved
  source declaration digest;
- T, A, exact considered ObservationBuildPin/coverage digest;
- COMPLETE/EXCLUDED status and fixed reason (or null for COMPLETE);
- selected observation key/version/build/snapshot/authority IDs, known_at,
  archive_available_at and event_time when a candidate was selected;
- empty selected reference for genuine absence; the rejected candidate
  reference for STALE/NOT_REPORTED/WITHDRAWN, explicitly not a consumed value.

Deterministic row ordering is (sample_key, Feature SpecPin stable identity).
Row set/cardinality, clocks, reasons and the exact selected/consumed references
must re-verify against the supplied authorities, not only match byte hashes.
No observation Label role is allowed. Reader validation is offline and does
not rerun transforms or collect anything; any required proof artifacts must be
explicitly pinned local inputs or sealed files, never rediscovered via a URL.

For each sample, hash its decision rows under `observation-binding-v1`.
Compute the new envelope version **after** those rows:

```text
multi_source_sample_version_id = H(
  domain = multi-source-sample-version-v1,
  sample_key,
  bar_sample_version_id,
  observation_binding_id,
  observation_association_schema_version,
  multi_source_pit_contract_version
)
```

Decision rows deliberately do not contain this derived version: no circular
hash. A separate sample-binding table maps sample_key, bar_sample_version_id,
observation_binding_id to multi_source_sample_version_id. New-cohort matrix
rows use the latter as sample_version_id; v1 rows keep their old version.
The bar executor continues to receive the unchanged bar PIT result; the new
orchestrator performs an explicit verified binding join, never mutating it.

`association_content_id` remains the existing bar association ID in v1.
New-cohort manifests record it as `bar_association_content_id`, plus
`observation_association_content_id` and sample-binding table content ID.
The new combined `association_content_id` is a domain-separated hash of those
three IDs and their schema/contract versions. It binds excluded samples too.
Exact empty sidecars have a real schema-bound content hash, not a placeholder.

## 9. Feature Execution Coexistence

| Input model | Evaluation |
| --- | --- |
| A: generalize FeatureTransformInput | Risks reinterpreting `rows` and Canonical field/window contracts and changing old transform fingerprints. Reject for V1. |
| B: separate bar and observation inputs | Keep the existing name/class `FeatureTransformInput` as the bar input (no forced rename). New `ObservationFeatureTransformInput` is a separate frozen numeric-only input. Selected. |
| C: provider pre-aggregation | Useful future normalized measures, but cannot replace generic publication/revision selection; hides lineage and risks encoding Features as source facts. Not the Feature execution authority. |

The new input carries ordered field names/types, one selected numeric value
tuple, and sorted typed parameters. It carries no paths, clocks to consult,
provider callbacks or live objects. The executor proves times and provenance
first and exposes only declared values. Registry entries are built-in exact
references with supported observation schema/value contract, output type,
parameter contract and pinned implementation fingerprint. No arbitrary YAML
module import, caller registry injection, eval or runtime provider dispatch.

Existing eight OHLCV transforms, FeatureSpec hashes and ImplementationPins
must remain byte/semantically unchanged. In particular, extracting or renaming
their modules just for this architecture could change fingerprints and is not
required. Observation executor output is a non-null finite scalar float64 or
int64 declared by its registration/spec; no implicit int/float conversion to
mask drift. Structured observation inputs do not imply structured output columns.

Sample anchors and bar Label horizons remain Canonical-driven. The mixed-cohort
orchestrator accepts both spec families explicitly. It retains bar-window
preflight for bar specs; it must not pass observation specs through today's
BARS-only `generate_sample_requests` preflight. A new mixed-plan version pins
all specs and observation builds, while using the same bar anchor geometry.
Old plans run unchanged. Changing observation freshness does not secretly
change stride anchors; it affects explicit Feature/sample exclusions instead.

## 10. Dataset Identity and Version Cohorts

### 10.1 Identity Propagation

Keep `sample_key` exactly the existing logical request identity. Features were
never part of that key; comparing the same anchor across feature sets remains
possible. Do not add provider or capture timestamps to it.

| Change | Observation/spec binding | sample_key | New sample_version_id / association | Manifest / dataset_id | Dataset Catalog |
| --- | --- | --- | --- | --- | --- |
| provider, source kind, entity, measure, dimensions | K and source-spec hash change. | unchanged for same request | decision/binding/version change | source/spec pins and combined association change ID | changed dataset_id changes entry and catalog identities |
| snapshot bytes or declared snapshot set | snapshot/build pins and V change | unchanged | considered-build binding changes, even if value equal | pins always change ID, including EMPTY output | new Dataset facts, never update old snapshot |
| known_at rule/evidence or timestamp | source rule/spec and/or V change | unchanged | eligibility/decision/version change | authority seals and association enter ID | new facts/content/snapshot IDs |
| revision/value/status/supersession | V changes, K preserved | unchanged | selected/exclusion decisions change | V/pins/content change ID | new facts/content/snapshot IDs |
| alignment/target/entity mapping | spec hash changes | unchanged unless request itself changes | declaration/binding/version change even if same value | Feature SpecPin and association change ID | new facts/content/snapshot IDs |
| freshness clock/limit/missing policy | spec hash changes | unchanged | decision binding changes, even if still fresh | same propagation | same propagation |
| provider/normalizer version or fingerprint | rule/spec/pins/V change | unchanged | binding/version change | exact contracts/pins change ID | same propagation |
| equivalent TZ notation, input/provider order, relocated sealed files | normalized meanings/pins identical | unchanged | unchanged | unchanged | logical identities unchanged; descriptive snapshot metadata may differ |

Alignment mode is identity-bearing. Changing LATEST_EFFECTIVE_AT_OR_BEFORE to
a future LATEST_PUBLICATION_AT_OR_BEFORE changes the Observation FeatureSpec
identity and therefore Dataset identity, even if a particular sample happens
to select the same value. This design correction changes no existing artifact
identity and does not reinterpret any old cohort.

Every declared considered observation build enters identity, not only those
producing a value. This prevents an all-excluded/EMPTY Dataset from losing its
evidence boundary. Changing an unrelated, undeclared provider artifact has no
effect and is never discovered. Physical reserialization of normalized output
alone is not a new logical Dataset identity; exact source-byte replacement is.

### 10.2 Cohort Contract

Reserve these **future design names**, not current runtime constants:

| Cohort | Required implementation boundary |
| --- | --- |
| observation-schema-v1 / observation-build-v1 | New normalized authority/reader, exact supported provider and normalizer contracts. |
| observation-feature-spec-v1 / observation-feature-execution-v1 | New spec serialization/hash and separate input/executor; keep bar FeatureSpec v1 path untouched. |
| observation-association-v1 / multi-source-pit-v1 | New decision sidecar and binding table; retain Canonical association v1. |
| multi-source-dataset-manifest-v1 / multi-source-dataset-id-v1 | New strict Dataset manifest/identity domain and schema dispatch, not an extra optional field in old v1. |
| multi-source-sample-generation-plan-v1 | Explicit mixed-spec/pin plan when generation is requested; old plan/rule/IDs unchanged. |
| multi-source-dataset-catalog-entry-v1 / multi-source-dataset-catalog-snapshot-v1 | Explicit richer facts and mixed legacy/new entry dispatch; old catalog snapshots/algorithms unchanged. |

New Dataset identity hashes all existing normalized Dataset identity inputs
under the new domain **plus** considered ObservationBuildPins, authority and
coverage pins, the combined association_content_id, multi-source spec/plan
contract versions and executor fingerprints. Manifest includes those fields
directly, the three component association IDs/schemas, the explicit clock mode,
and physical output file hashes. Existing scope stays bar-anchored. Old
completion/gap meanings are not overloaded to mean observation coverage.
Sample decisions provide the latter. A present dataset_as_of or explicit null
is bound; no environment-selected default.

New materialized Datasets contain the bar association, observation decisions
and sample binding artifacts in a versioned whitelist, plus the normal matrix,
specs, manifest, report and success marker. They pin exact observation proofs
needed for offline verification; locators alone never satisfy a reader.
Manifest validation recomputes identity and association hashes even for EMPTY
matrices. The new reader independently checks proof/association consistency,
not just matrix values. Old v0.8 readers correctly reject the unknown new
manifest; future readers must retain the existing v1 reader unchanged and
dispatch explicitly. No unknown-schema best effort.

Catalog integration must project the new pins and association IDs from the
verified new manifest into the new entry facts; it must not truncate them to
old Canonical-only facts. Entry content hashes bind new dataset_id and new
facts, catalog content binds sorted typed entry digests, and snapshot identity
binds the new contract/version and entry snapshot records. Old entry digests
are reused unchanged in a mixed snapshot's typed envelope; an old snapshot
is never rewritten. Catalog remains downstream and never feeds its identity
back into dataset_id. Full wire-format/test vectors for these new artifacts
are a prerequisite of the separately reviewed core implementation; the field
and dependency decisions here are not permission to accept them in v0.8.

## 11. Compatibility and Migration

No change occurs to runtime artifacts in this design PR. Classifications below
describe the future implementation selected here, not existing capability.

| Surface | Classification | Exact effect |
| --- | --- | --- |
| Canonical Market Bar artifacts | UNCHANGED | Old schema, values, files, clocks, verified reader and no-repair rules preserved. |
| Canonical build IDs | UNCHANGED | No observation field enters their encoders. |
| canonical_bar_key | UNCHANGED | Same market-event dimensions. |
| canonical_row_version_id | UNCHANGED | Same bar/provenance algorithm, not reused for observations. |
| PIT association v1 | UNCHANGED + ADDITIVE | Existing rows/IDs remain valid; observation sidecar belongs only to new Dataset cohort. |
| FeatureSpecs | UNCHANGED + NEW_VERSIONED_COHORT | Old bar specs/hashes unchanged; separately versioned observation specs. |
| LabelSpecs | UNCHANGED | Existing units/boundaries and fail-closed execution preserved. |
| Dataset manifests | NEW_VERSIONED_COHORT | New explicit observation/association fields; old strict v1 persists. |
| Dataset IDs | UNCHANGED for old inputs; NEW_VERSIONED_COHORT for mixed inputs | Separate hash domain binds all new evidence; no old recomputation drift. |
| Dataset readers | ADDITIVE | Explicit dispatch; new reader supports old artifacts; old binaries reject new cohort. |
| Dataset Catalog | NEW_VERSIONED_COHORT | Richer typed entry/snapshot facts for new/mixed snapshots, old IDs/snapshots untouched. |
| Existing v0.8 artifacts | UNCHANGED | No migration, regeneration or requalification by assertion. |
| Options Raw/Curated artifacts | UNCHANGED | Optional future explicit sealed import/adapter; no rewrite or automatic PIT admission. |
| DuckDB Catalog schema | UNCHANGED | Core V1 needs immutable file authorities, not a new operational table. Later indexing needs separate scope. |
| ArtifactClient | UNCHANGED existing four methods | No new convenience/API method is frozen here; future reader support must preserve signatures, lazy imports and exact entry selection. |

`MIGRATION_REQUIRED=false` and `REWRITE_REQUIRED=false` for all existing
artifacts. Supporting new cohorts requires upgraded code, which is not an
artifact migration. Old builds without observation specs continue to use old
identity algorithms by default, not a new-cohort wrapper with empty fields.

## 12. Failure and Security Contract

Unknown provider, provider contract, normalizer, known-at authority, value
schema, alignment or artifact cohort: FAIL BUILD before transforms, including
zero-sample builds. Missing sealed input, tamper, hash mismatch, incomplete
pagination, unproved scope coverage, conflicting duplicates, cycle/ambiguous
revision, malformed time/identity, provider schema drift: FAIL BUILD. No
fallback provider, snapshot, schema, row or value is chosen to obtain success.

Future-known/archive-future, genuine absence and stale observations have only
the explicit exclusion/fail policy in section 7. The verifier rejects an
associated illegal future value even if diagnostics claim it was excluded.
All returned complete Features must have exact pin-to-row coverage. A copied
digest without evidence is not authority. Authority URLs are citations, never
instructions to the build; no secrets or live credentials belong in snapshots
used as checked-in fixtures. No operation rewrites source history or destroys
superseded vintages. Source isolation never weakens fail-closed provenance.

## 13. Existing Moomoo Options and Adapter Gap

The audited collector exposes chain static fields and volatility requests.
`select_option_volatility_period` maps requested dates to bounded period enums;
the service's as_of_date chooses the request period, **not a historic publication
vintage**. No existing parameter implements the three-clock predicate.

Both option service functions create captured_at before network requests and
reuse it across a batch. `_finish_dataset_run` records finished_at after
storage/quality work. These are useful operational facts, but captured_at alone
is neither a completed-possession receipt nor known_at. A future adapter must
prove archival completion from immutable evidence, not blindly copy that column.

Raw paths are option_chain/capture_date or option_volatility_daily/start/end
partitions; Curated equivalents retain run-based filenames. `_dataset_key`
is a truncated request/run hash, **not a content hash or observation version**.
`to_parquet` writes the frame; these option writers do not construct the new
content-sealed snapshot/reader contract. `record_dataset_run` stores run status,
parameters, file paths, counts, quality and config hash in dataset_ingestion_runs;
it replaces the record for a run ID. This mutable operational catalog is not an
immutable observation authority.

Normalization accepts provider aliases, numeric/date coercion and nulls;
contracts deduplicate by (option_code, captured_at, source), volatility by
(option_code, trade_date, source), using `keep="last"`. Those convenience rules
are not the proposed conflict/revision proof. Raw responses are the candidate
evidence for a future deterministic adapter, not automatically qualified
Curated winners. The volatility `analysis` string is outside numeric V1.

Latest option views rank capture time/run ID (and volatility falls back to run
ID when captured_at is absent); they do not reconstruct publicly known vintages.
The new adapter must not use these views as PIT source selection.

| Reusable foundation | Missing authority before Options admission |
| --- | --- |
| Existing endpoints and Raw captures | Exact endpoint/field/entity contract, knowability and historical availability limits; no reconstruction of unavailable historic Greeks/quotes/IV. |
| Run parameters, status, quality and finished_at | Sealed acquisition/coverage proof; completed capture and original public known_at distinguished. |
| Retained Parquet files | Full byte inventory hashes, stable snapshot IDs and verified observation reader. |
| Static/volatility field mappings | Pinned strict deterministic numeric normalization, no silently coerced invalid values or last-row conflict resolution. |
| Multiple captures | Proven revision/evidence equivalence rules; repeated capture is not a revision chronology. |
| Catalog browsing | New observation pins, PIT decisions and Feature source declarations; no mutable latest authority. |

```text
MOOMOO_OPTIONS_ADAPTER_PHASE=PHASE_PROVIDER_3
EXISTING_OPTIONS_AUTOMATICALLY_PIT_QUALIFIED=false
```

## 14. Future Implementation and Provider Gates

Each phase requires separate authorization and independent review. No provider
version, source URL, series token or real publication schedule is qualified by
the examples in this design.

1. **Core contract implementation:** freeze serialized schemas/test vectors for
   the new cohorts; implement deterministic observation models, identities,
   safe immutable snapshots and the sole verified reader using offline
   fixtures. Implement the one revision/alignment authority, sidecar binding,
   new Feature cohort and offline new Dataset reader/identity path. Preserve
   v0.8 golden IDs. No new provider collection or live experiment implied.
2. **PHASE_PROVIDER_1 = US Treasury:** recommended first structured numeric
   canary, conditional on proof below. Source selection must distinguish the
   official Treasury series from an aggregator's codes/data. Simple numeric
   shape does not make publication time straightforward by assumption.
3. **PHASE_PROVIDER_2 = CFTC COT:** recommended delayed-publication/revision
   canary. Prove effective date differs from actual publication and archive.
4. **PHASE_PROVIDER_3 = Moomoo Options adapter:** adapt independently qualified
   existing evidence after the generic boundary works, retaining all gaps and
   historical availability limits above.
5. **Later candidates:** SEC filings/amendments, macro releases/revisions,
   flows; news/text only after a separate value/transform design. This is
   implementation ordering, not permanent product exclusion or release scope.

### Treasury Activation Checklist

- Seal authoritative source and exact series/field/units/entity contract;
  prove timezone and effective date/period representation.
- Prove actual release/known-at semantics and precision for every admitted
  vintage, including revisions and any date-only conservative bound.
- Preserve original historical numeric representation; pin conversion,
  missing/non-business-day and not-reported semantics. Do not fabricate a
  holiday observation or forward-fill daily rows.
- Capture a complete source response/page inventory and immutable receipt,
  hash it, normalize deterministically, verify with the sole reader, and bind
  archive/authority evidence. Historical vintage completeness must be proved.
- Offline PIT canary: before publication excluded, equality included, after
  publication included only within max age, and A-before-capture excluded.
  A latest-value Feature selects the latest effective observation whose
  revision is legally visible. Include the old-event late-revision canary,
  plus stale, missing and tampered-snapshot cases.
- Prove Dataset build/verification makes no provider call; activation remains
  blocked if any known-at or revision requirement cannot be proved.

### CFTC Activation Checklist

- Seal report type, effective/report date, market/contract identity,
  dimensions, units, exact fields and normalization rules; no ambiguous
  display-name mapping or mixed report series.
- Prove actual publication known_at/timezone, delays/holidays and
  corrections/retractions with revision identity and historical vintages.
- Seal response inventories, possession evidence, snapshot/content IDs and
  source-contract/normalizer fingerprints; verify completeness independently
  of the presence of a few expected dates.
- Offline illustrative delayed-publication canary: Tuesday effective,
  Friday publication; Wednesday invisible, next Monday potentially visible
  when freshness/archive permit. A before capture excludes Monday; no archive
  relaxation can make Wednesday see Friday knowledge.
- Later correction must not enter a pre-correction sample; a visible withdrawal
  must not restore the prior value. A later correction to an older report
  updates that report's visible revision but does not replace a newer effective
  report in a latest-effective Feature. Unknown release times remain fail-closed.

Cross-Day / TRADING_DAYS Labels remain separate. Long-term composition is
multi-source Feature authority plus separately qualified Label horizon authority
feeding strict PIT assembly. Neither Treasury onboarding nor this framework
implements cross-day, TRADING_DAYS or MINUTES labels. Adjusted prices remain
`MODEL_C_NONE_ONLY`; generic provider admission is not corporate-action PIT
enablement. No new ArtifactClient method, CLI command or database is required
to approve this architecture.

## 15. Future Offline Test Contract

These are mandatory future tests, not tests implemented/run by this docs PR.

| Surface | Required proof |
| --- | --- |
| Logical identity | Equivalent UTC representations, dimension order and input order preserve keys; different provider/entity/measure/event/dimension changes K; paths/URLs do not. |
| Version identity | Value, clocks, authority, revision, snapshot, provider/normalizer fingerprints change V, including equal-valued but differently proved revisions. |
| Evidence integrity | Snapshot substitution, duplicate inventory members, missing/tampered bytes, incomplete pages, unsafe paths/reparse points and forged verified input fail. |
| Publication | Exactly T included; T+1 microsecond excluded; event date alone never proves known_at; unknown method/version fails; date-only ambiguity fails; qualified capture fallback never appears before completed capture. |
| Archive | Exactly A included; A+1 microsecond excluded; null A means explicit market-only reconstruction, not historic possession; no backdating imported files. |
| Revisions | Pre/post revision cutoffs, superseded retention, withdrawals, missing predecessor, same-time conflicts and visible correction without payload; repeated equivalent captures deterministic, conflict never first/last-wins. |
| Alignment | Exact event equality; latest-effective selects greatest eligible event_time after per-K revision visibility; no hidden nearest/rounding; unresolved distinct-key greatest-event_time tie fails; unknown/deferred publication modes fail even with zero samples. |
| Freshness | max_age equality passes; one microsecond beyond excludes/fails; finite positive limit required; old-event correction does not reset age; no retry with an older candidate. |
| Missingness | Proved absence versus incomplete/missing evidence; EXCLUDE_SAMPLE versus FAIL; no emitted null Feature/zero, no source fallback, interpolation or synthetic backfill. |
| Associations | Exact one decision per sample/spec, coverage of excluded samples, no extra/missing pins, no cycle in binding hashes; bar association v1 remains unchanged. |
| Mixed Features | Bar + qualified Treasury fixture; bar + delayed CFTC fixture; source/spec/build order independence; observation values never enter bar transforms, Labels or anchor-generation windows. |
| Old contracts | Read old PIT v1/Canonical/Dataset/Catalog artifacts; preserve golden keys, row versions, FeatureSpecs, implementation pins and dataset_id; old readers reject new schemas. |
| New Dataset | All-excluded/EMPTY and equal-value cases still bind source/policy evidence; sidecar substitution fails verification; mixed catalog hashes bind richer facts without changing old snapshots. |
| Offline/security | Reader only touches supplied local artifacts; PIT/executors touch no filesystem, network, OpenD, settings or current time; provider/code loading cannot be invoked from specs. |
| Existing guards | BARS/Label/cross-day boundaries, QFQ/HFQ refusal and current ArtifactClient four-method surface unchanged. |

Mandatory cross-K revision canary:

```text
OLD_EVENT_LATE_REVISION_DOES_NOT_DISPLACE_NEWER_EFFECTIVE_OBSERVATION
```

Construct complete immutable evidence for old K with event_time=t0, an initial
revision known before t1, and a correction known at t3; new K has event_time=t2
and an initial revision known at t2_publication. Require
`t0 < t1 < t2 <= T` and `t2_publication < t3 <= T`, with both revisions archive
eligible and the new observation within its declared max age.
LATEST_EFFECTIVE_AT_OR_BEFORE must select new K. Independently verify that the
visible correction remains the authoritative version of old K when old K is
selected by an EXACT_EVENT_TIME query with Feature-window-start target=t0 and
a finite max_age allowing old K, without winning the cross-K alignment.
Repeat with reversed input/key/version order; the result must not change.

## 16. Inspiration, Non-Goals and Review Closure

External Digital Oracle discussion is inspiration only for independent sources,
provider separation, time-horizon awareness and explicit source isolation.
No code or contracts are copied. MarketVault does not assume all public
information is contained in price. Any source becomes a historical Feature
input only when knowability can be independently and deterministically proved.

This PR changes exactly this file and ADR 0004. It implements no provider,
PIT/Feature/spec/manifest/identity runtime, schema, CLI, REST, news ingestion or
database migration. It performs no collection, external provider API request,
OpenD operation, production mutation, version bump or release mutation.
Repository Git/PR/CI operations are development evidence, not provider access.

Submission validation is docs-appropriate: whitespace, repository hygiene,
release checker and the natural exact-head CI tier selected by the repository.
No local FULL run or forced FULL CI is required for two design docs. A passing
design/CI report is not provider qualification or independent design approval.
Stop after opening the PR and exact-head CI closure for architecture review.
