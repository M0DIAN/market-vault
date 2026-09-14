# ADR 0004: Multi-Source Feature Authority

- Decision scope: post-v0.8 design; no runtime or provider implementation.
- Deciders: MarketVault maintainers, through independent PR review.
- Audited base: `7be596e8ba7731a4870a21fde09ccc3dc2190fd7`.
- Audited tree: `e4d789e0009ffcd39933c6b33d710525276eb3c6`.
- Detailed contract: [Multi-Source Feature Framework V1](../multi_source_feature_framework_v1.md).

```text
DESIGN_ONLY=true
DESIGN_APPROVAL_REQUIRES_INDEPENDENT_REVIEW=true
DESIGN_DOCUMENT_SELF_APPROVAL=false
IMPLEMENTATION_REQUIRES_POST_MERGE_AUTHORIZATION=true
RUNTIME_IMPLEMENTED=false
PROVIDER_IMPLEMENTED=false
VERSION=0.8.0
```

This record states the architecture selected for review. Approval and later
implementation authority come from independent PR review, merge evidence and
separate post-merge authorization, not from this document alone.

## Context

Current PIT accepts `VerifiedCanonicalBuild` and binds samples to Canonical
market-bar keys and row versions. Built-in Features consume only the allowed
OHLCV field projection over trailing contiguous Canonical rows. Options have
collection, normalization, Parquet and run provenance, but not a verified
historical publication/revision authority. The framework's
[source audit](../multi_source_feature_framework_v1.md#2-current-authorities)
identifies the exact implementations and their limitations.

An old event date is not proof that a value was publicly knowable on that
date. A later capture is not proof of the original publication time. A
revision of an old observation must not silently replace its historically
visible value. These are authority boundaries, not generic join options.

## Alternatives

| Criterion | MODEL_A: universalize Canonical bars | MODEL_B: parallel observation authority | MODEL_C: source-specific Canonical subtypes |
| --- | --- | --- | --- |
| ADR 0001 | Replaces the bar-centered source model broadly. | Extends exclusivity only for post-v0.8 non-bar inputs. | Extends Canonical to heterogeneous subtypes. |
| `canonical_bar_key` | Must generalize its fixed market-event tuple or retain a legacy branch. | Unchanged; non-bars have a separate observation key. | Legacy key can survive, but subtype-specific keys and dispatch are required. |
| `canonical_row_version_id` | Universal revisions require a new meaning/cohort. | Unchanged; observation versions carry publication and revision authority. | Separate subtype version algorithms behind the common name. |
| Existing Dataset IDs | Preservation needs explicit legacy encoding and readers. | Exact old encoders remain; only new multi-source builds use a new cohort. | Preservation needs typed identity dispatch throughout Dataset contracts. |
| PITSample / association | Replace or version the bar-shaped association. | Retain bar PIT; attach a separately verified observation sidecar. | Generic typed references must be introduced across PIT. |
| Migration | Broad migration pressure; rewrite avoided only by dual support. | No old-artifact migration or rewrite. | Dual legacy/subtype support, no necessary rewrite but a wider upgrade. |
| Providers | Uniform surface, many irrelevant bar fields or a large union. | Provider contracts normalize into one non-bar schema. | Each new source risks another subtype and reader. |
| Revisions | Bar conflict semantics must split from generic version selection. | Independent explicit revision chains; no bar conflict-rule change. | Per-subtype policies plus a common selector must be kept consistent. |
| v0.8 preservation | Possible with substantial legacy machinery. | Direct: old schemas and algorithms remain authoritative for old builds. | Possible with explicit legacy dispatch, not automatic. |
| Complexity | High blast radius for a first provider. | Smallest independent authority with a deliberate new Dataset cohort. | More registries, polymorphism and cross-subtype validation. |
| Fail closed | Risk of treating bar and non-bar clocks as interchangeable. | Unknown publication/revision authority fails before selection. | Unknown subtype fails; consistency across subtype authorities is harder. |

## Decision

Select **MODEL_B**. Preserve Canonical Market Bars. Add a parallel immutable,
normalized observation authority for non-bar information, derived only from
explicit immutable source evidence through a versioned provider contract and
verified reader. Do not turn stored Features or exported Datasets into source
authorities. No provider-specific table, database service, live lookup or
arbitrary transform mechanism is required by this decision.

```text
SELECTED_AUTHORITY_MODEL=MODEL_B
CANONICAL_MARKET_BAR_CONTRACT_CHANGED=false
CANONICAL_MARKET_BAR_KEY_CHANGED=false
CANONICAL_ROW_VERSION_ID_CHANGED=false
EXISTING_CANONICAL_ARTIFACT_REWRITE_REQUIRED=false
EXISTING_DATASET_ARTIFACT_REWRITE_REQUIRED=false
PIT_ASSOCIATION_V1_ARTIFACTS_REMAIN_VALID=true
```

1. Separate event/effective time, public-known time and archive time. Every
   used observation has a content-pinned known-at authority. Visibility is
   inclusive at the Feature cutoff and, when specified, archive-as-of cutoff.
2. Separate logical observation keys from immutable observation versions.
   Revisions are explicit, ordered by proven knowledge and supersession, never
   by retrieval order, filesystem mtime or today's returned value.
3. Select PIT association **MODEL_B (sidecar)**: retain Canonical association
   v1 with its original sample-version meanings; add observation decisions
   and multi-source sample-version bindings in a new cohort. Never reinterpret
   an old association row or attach an unbound, optional sidecar to v1.
4. Put the provider/entity/observation/field and alignment/freshness declaration
   in a new versioned observation FeatureSpec with an embedded typed source
   declaration. Transform registration declares compatible input contracts,
   not which provider to silently select. Existing FeatureSpecs remain valid.
5. Select Feature input **MODEL_B (separate inputs)**: keep the current
   `FeatureTransformInput` and built-ins unchanged; a separate numeric
   `ObservationFeatureTransformInput` receives only proved selected values.
   No fake OHLCV row, implicit fill, or provider call inside a transform.
6. Require finite identity-bearing staleness limits, deterministic missing
   outcomes and explicit revision tie rejection. Provider failure is never
   disguised as ordinary historical unavailability.
7. Use a new multi-source Dataset manifest/identity/reader cohort. Old builds
   still verify under old rules and retain their IDs. Catalog integration
   explicitly versions the richer facts rather than silently dropping pins.
8. Keep builds offline. Separately authorized collection precedes immutable
   snapshot verification. No current provider, including Options, is
   automatically qualified by this design.

## Relationship to Earlier Decisions

[ADR 0001](0001-canonical-ml-dataset-boundary.md) decision 1's statement that
Canonical is the only new materialized source-of-truth layer is extended for
the future non-bar cohort: a verified observation layer becomes an additional
Dataset input authority. Decision 5's Canonical-only Dataset input list gains
observation pins in that new cohort. Its decisions 2-4 remain authoritative
for Canonical bar identity, bar clocks and logical determinism. Its remaining
spec, leakage, no-repair, adjustment and split boundaries remain in force.
This is not a retrospective reinterpretation of v0.4-v0.8 artifacts.

[ADR 0002](0002-deterministic-dataset-builder-boundary.md) repeats the
Canonical-only boundary in its context and decisions 1-2. The same narrowly
scoped extension applies there for future multi-source builds; explicit pins,
offline execution, built-in-only transform resolution, immutable derived
Datasets and verified readers remain requirements. Its v1 materialization
whitelist is not widened in place: new files require the new cohort.
Neither earlier ADR is edited by this PR.

The [adjusted-price policy](../adjusted_price_pit_as_of_policy_v1.md) is not
superseded. `MODEL_C_NONE_ONLY` remains enforced for PIT; QFQ/HFQ enablement
and corporate-action qualification are separate. Generic observation clocks
do not themselves qualify adjustment factors.

## Consequences and Sequence

This preserves all v0.8 immutable inputs and outputs, at the cost of one new
observation authority and explicit Dataset cohort dispatch. New readers must
support old cohorts; old readers may fail closed on new ones. No old artifact
rewrite, storage migration or automatic catalog mutation is part of V1.

Implement the core identity/reader/PIT/Feature boundary only after approval.
Then qualify Treasury first, CFTC second, and an adapter for existing Moomoo
Options third. These are ordered candidates, not declarations of existing
provider safety. Treasury is a useful structured numeric canary only if its
known-at evidence can be proved. CFTC tests delayed publication and revision
knowledge. SEC, macro, flows and text remain future candidates; numeric-only
V1 does not authorize text execution.

Cross-Day / TRADING_DAYS Label authority remains an independent workstream.
It may later combine with multi-source Features in strict PIT assembly;
neither workstream is a prerequisite for implementing the other's provider
boundary. No v0.9 scope or release is declared here.

## Acceptance

The detailed framework freezes clock, identity, alignment, revision, exclusion
and compatibility rules plus future offline tests. No runtime implementation,
provider request, OpenD operation, version change, formal tag/release mutation
or production operation occurs in this design PR. Independent architecture
review is required before this decision can authorize follow-on planning.
