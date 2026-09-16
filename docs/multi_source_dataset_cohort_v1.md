# Multi-Source Dataset Cohort V1

Status: design candidate; independent architecture and governance review pending.
This document freezes future interfaces, not an implemented or merged cohort.

## 1. Authority, Scope, And Delivery

DESIGN_BASE_MAIN_SHA=52432d1ac46ef49dbee4c8402e6f3992dbb14497
DESIGN_BASE_MAIN_TREE=0c010b759807562ba1cfd56b35ddd95078756105
VERSION=0.8.0
A4_IMPLEMENTATION_AUTHORIZED=false
MERGE_AUTHORIZED=false

Read this alongside [the multi-source authority design](multi_source_feature_framework_v1.md),
[A3](observation_pit_sidecar_v1.md), and the exact-base implementations in
observation/pit_models.py, observation/pit_identity.py, dataset/specs.py,
dataset/content.py, dataset/identity.py, dataset/orchestration_models.py and
dataset/artifact_serialization.py. References to existing algorithms below
mean those frozen base contracts, not mutable "latest supported" behavior.

Implementation requires three sequential, separately authorized PRs:

| Phase | Sole runtime scope |
| --- | --- |
| A4.1 | Observation FeatureSpec and Observation Feature executor |
| A4.2 | Pure in-memory Multi-Source Dataset orchestration and identity |
| A4.3 | Immutable Multi-Source Dataset materializer and verified reader |

Each phase needs exact-head FULL CI, independent review, authorized merge and
exact-main closure before authorization of the next. Design merge does not
authorize any implementation. Do not combine or parallelize these phases.

The parallel future package is market_vault.multi_source. Old Dataset and
Observation packages must not import it back. Importing frozen authorities
from the new package is permitted; circular authority is not. Do not widen
dataset.models, dataset.identity, dataset.manifest, dataset.reader or
dataset.feature_execution to accept this cohort.

Frozen invariants:

~~~text
CANONICAL_PIT_CHANGED=false
PIT_ASSOCIATION_V1_CHANGED=false
PIT_SAMPLE_KEY_CHANGED=false
PIT_SAMPLE_VERSION_ID_CHANGED=false
A1_IDENTITY_CHANGED=false
A2_ARTIFACT_CHANGED=false
A2_READER_CHANGED=false
A3_CONTRACT_CHANGED=false
EXISTING_FEATURE_SPEC_V1_CHANGED=false
EXISTING_LABEL_SPEC_V1_CHANGED=false
EXISTING_DATASET_MANIFEST_V1_CHANGED=false
EXISTING_DATASET_ID_CHANGED=false
EXISTING_DATASET_READER_CHANGED=false
~~~

Old bar executors, materializer, Catalog and identity-bearing artifacts remain
unchanged. Old FeatureSpec content IDs, Dataset IDs/schema IDs, canonical
manifest bytes, reader vectors, A1 vectors and A3 vectors stay identical.
No existing artifact rewrite or migration is required.

No providers, Catalog integration, CLI, UI, mixed sample-generation plan,
network, OpenD, production operation, live source acquisition, custom
transforms or implicit forward fill are authorized. No formal release asset
is built, published or replaced by this design.

## 2. Frozen Versions And Encoding

| Constant | Exact value |
| --- | --- |
| OBSERVATION_FEATURE_SPEC_SCHEMA_VERSION | observation-feature-spec-v1 |
| OBSERVATION_FEATURE_SPEC_CONTENT_ID_VERSION | observation-feature-spec-content-v1 |
| OBSERVATION_FEATURE_SPEC_ARTIFACT_VERSION | observation-feature-spec-yaml-v1 |
| OBSERVATION_FEATURE_EXECUTION_CONTRACT_VERSION | observation-feature-execution-v1 |
| OBSERVATION_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION | observation-feature-transform-call-v1 |
| MULTI_SOURCE_DATASET_ORCHESTRATION_CONTRACT_VERSION | multi-source-dataset-orchestration-v1 |
| MULTI_SOURCE_DATASET_MANIFEST_SCHEMA_VERSION | multi-source-dataset-manifest-v1 |
| MULTI_SOURCE_DATASET_ID_VERSION | multi-source-dataset-id-v1 |
| MULTI_SOURCE_DATASET_SERIALIZATION_FORMAT_VERSION | multi-source-dataset-parquet-v1 |
| MULTI_SOURCE_OBSERVATION_EVIDENCE_CONTENT_ID_VERSION | multi-source-observation-evidence-v1 |
| MULTI_SOURCE_DATASET_MATERIALIZER_VERSION | multi-source-dataset-materializer-v1 |
| MULTI_SOURCE_DATASET_READER_CONTRACT_VERSION | multi-source-dataset-reader-v1 |
| MULTI_SOURCE_DATASET_BUILD_REPORT_VERSION | multi-source-dataset-build-report-v1 |

No reuse of the old dataset-id or manifest-v1 domain as the new cohort ID.
DatasetField, DatasetSchema and the existing logical schema/content functions
are reused unchanged: a schema describes ordered logical fields, not a cohort
dispatcher. Cohort separation is explicit in the new Dataset ID and manifest.

Normative notation:

- H(domain, fields) is frozen dataset.encoding.encode_identity, encoding
  version v1: sorted keys, tagged scalar values, UTF-8/NFC, distinct bool/int,
  UTC microseconds, binary64 big-endian float encoding, finite floats only,
  negative zero normalized. It is not a hash of JSON or Python repr.
- R(x) is an exact named-field record; derived fields are included only where
  an explicit payload below requires them. Nested objects never enter H raw.
- S(domain, ids) = H(domain, {count: len(ids), members: concat(ids)}).
  Every member is validated lowercase 64-hex; order is specified at each use.
  Empty sequence has count=0 and members=""; duplicates are not silently lost.
- J(payload) is UTF-8 JSON, sort_keys=true, separators=(",", ":"),
  ensure_ascii=true, allow_nan=false, exactly one trailing LF, no BOM.
  Typed instants render UTC ISO-8601 with six fractional digits and Z; dates
  use YYYY-MM-DD. Numeric JSON scalars retain int versus float; -0.0 becomes
  0.0. JSON is physical serialization, not the identity encoder.

All logical text follows the owning frozen model's safety/normalization.
Naive instants, bool-as-int, non-finite floats, unsafe text, duplicate
normalized names and unsupported types fail closed before hashing.

## 3. Observation FeatureSpec

ObservationFeatureSpec has exactly these semantic fields:

~~~text
spec_schema_version, name, version, output, source_spec, transform_ref,
parameters, kind
~~~

kind is derived/fixed FEATURE. Schema version is observation-feature-spec-v1.
Name and version use the frozen FeatureSpec name/version grammar (lowercase
identifier and v-positive-integer respectively). Output is DatasetField with
exact fields name, logical_type, nullable; name equals spec.name,
logical_type is int64 or float64, nullable is false. No text, bool, date,
timestamp, JSON, embedding or image output.

source_spec is one complete normalized A3 ObservationSourceSpec, not a second
file, version range or SpecVersionRequirements. Its exact serialized fields:

~~~text
provider_id, source_kind, observation_name, dimensions,
entity_binding, entity_id, code_entity_map, input_field_names, value_schema_id,
provider_contract_version, provider_contract_content_id,
normalization_version, normalization_content_id,
known_at_authority_policy_version, known_at_authority_policy_content_id,
alignment, exact_target_binding, max_age_us, missing_policy
~~~

Dimensions are objects with exactly name, logical_type, value, ordered by
normalized dimension name. They preserve A1 ObservationDimension types
(string/int64/float64), never inferred from Python values or converted to text.
code_entity_map is a list of objects {code, entity_id}, in normalized code
order. input_field_names is a nonempty ordered list of distinct names; that
order is semantic, not sorted. All other field types, conditional nulls,
entity binding, source scope and policy rules are exactly A3's.

parameters is a normalized tuple of existing SpecParameter semantics:
{name, value}, sorted by name, with no duplicate normalized names. Serialization
uses a mapping from names to exact bool/int64/float64/string/null values.
Both V1 registrations require this mapping to be empty. General parameter
syntax is not permission to execute an unsupported parameter or transform.

### 3.1 Strict YAML And Canonical Artifact

parse_observation_feature_spec accepts one UTF-8 YAML mapping (bytes decoding
must be strict); reject unknown/missing fields at every level, duplicate keys
including normalized duplicates, non-string keys, merge keys, anchors,
aliases, explicit/custom tags, unsafe scalars, multiple documents and type
coercion. Use the strict event/node validation pattern of dataset.specs, not
unrestricted object construction. Only safe primitive YAML scalar/list/map
nodes are legal; timestamp-like text is not a substitute for a typed numeric
dimension. SourceSpec is explicitly constructed and normalized by A3.

The exact YAML top-level field set equals the eight semantic fields above.
kind must be present as FEATURE in serialized input; callers cannot vary the
derived model field. transform_ref is a string, not a nested transform object.
Do not guess the spec family from kind=FEATURE; schema is decisive.

serialize_observation_feature_spec uses J of the normalized eight-field
record, including the exact nested records above. Canonical JSON syntax is
valid YAML, matching the existing package's spec-artifact pattern. The stored
.yaml bytes must equal reserialization exactly. Input YAML comments, key
order and CRLF do not affect semantic identity; noncanonical stored bytes
are rejected by the materialized-cohort reader even if semantically equal.
Artifact version is carried in manifest spec-file facts, not an extra YAML key.

### 3.2 Spec Identity And A3 Linkage

observation_feature_spec_content_id(spec) is H under
observation-feature-spec-content-v1 with exactly:

~~~text
spec_schema_version, kind, name, spec_version=spec.version,
output_name, output_logical_type, output_nullable,
observation_source_spec_id=A3.observation_source_spec_id(source_spec),
transform_ref, parameter_count,
parameter_0000_name, parameter_0000_value, ... (ascending name order)
~~~

Indices are zero-based decimal with minimum width four, as in existing specs.
The A3 source ID binds the entire embedded source record, including dimension
logical types, ordered input fields and exact policies. YAML artifacts must
reconstruct that record, not replace it with an opaque caller-authored hash.

observation_feature_spec_pin(spec) returns the existing
SpecPin(FEATURE, name, version, content_id). Its A3 feature_spec_pin_id is
computed by the unchanged A3 function. There is no new SpecPin kind and no
reinterpretation of a bar FeatureSpec.

Derive ObservationPITFeatureBinding(pin, spec.source_spec) exclusively from
the parsed spec. Require exact equality with the trusted A3 result's binding
set, including feature_spec_pin_id and observation_source_spec_id. Reject
missing, extra, duplicate or conflicting bindings before any transform.

## 4. Separate Built-In Registry

V1 contains exactly:

| transform_ref | input arity/types | output | parameters | implementation version |
| --- | --- | --- | --- | --- |
| market_vault.multi_source.feature_transforms:identity_float64 | 1 / (float64,) | float64 | empty | v1 |
| market_vault.multi_source.feature_transforms:identity_int64 | 1 / (int64,) | int64 | empty | v1 |

Both return exactly the one declared field with no coercion, reject bool,
preserve signed int64 bounds and int/float separation, normalize float -0.0,
and reject NaN/infinity. No ratio, difference, rolling, aggregation,
cross-provider or provider-specific transform. Future registration requires
separate review, not caller configuration.

Each immutable registration binds transform_ref, implementation_version,
implementation_content_sha256, transform_call_contract_version, input_arity,
exact input logical types, exact output type, parameter schema and supported
Observation schema contract (observation-schema-v1).

Static imports and a built-in exact registry are the only resolution route.
No dynamic import, eval, entrypoints, plugin fallback, provider dispatch or
caller-supplied registry. Registry preflight runs even on zero samples and
even when every A3 decision is EXCLUDED.

Fingerprint payload is frozen separately under
observation-feature-implementation-v1:

~~~text
transform_ref, implementation_version,
implementation_source_sha256,
transform_call_contract_version, observation_schema_version,
input_arity, input_0000_logical_type, ...,
output_logical_type, parameter_count=0
~~~

implementation_source_sha256 is SHA-256 of strict UTF-8 implementation module
source with CRLF/CR normalized to LF, no absolute paths or mtimes. The module
must contain the complete numeric implementation and its validation helpers;
no unpinned external behavior may affect the result. Binding imported pure
frozen scalar contracts requires naming them in the call-contract review.
Fingerprint resolution occurs at static registry construction, never via
filesystem access inside execute_observation_features. Moving installation
paths cannot change fingerprints. A module byte change changes both pins.

ImplementationPin is reused with name=transform_ref, version=v1,
content_sha256=the above fingerprint (never null). Old bar transform
fingerprints are untouched. Conflicting (name, version) pins fail; identical
pins deduplicate. No fabricated PIT/splitter/orchestration pseudo-pin.

## 5. Observation Feature Execution

Future pure entry:

~~~text
execute_observation_features(
    pit_result: ObservationPITAssemblyResult,
    observation_builds: tuple[VerifiedObservationBuild, ...],
    feature_specs: tuple[ObservationFeatureSpec, ...],
)
~~~

No paths, settings, clock, network or provider callbacks. Admit the exact
trusted A3 result type and exact A2 verified build types; normalize copies
without modifying them. Public trust-me/from-unverified/skip-validation
constructors are not allowed.

Recheck A3 binding/decision/sample identity closure using frozen algorithms.
The supplied verified build set must cover every A3 evidence BuildPin;
reconstruct each pin's content/schema/coverage/created_at/provenance and
snapshot facts from the verified object. Unmatched, missing, conflicting or
extra build proof declarations fail rather than changing A3 provenance.
No PIT winner selection is rerun. Multiple exact captures follow A3's
existing representative selection; executor ordering is never a new choice.

For each COMPLETE decision, re-resolve selected_observation_version_id from
the exact selected_observation_build_id representative. Verify membership,
recomputed version/key, selected source snapshot, known-at authority,
event/known/archive clocks, source scope, all exact contracts and
value_schema_id against the decision, binding and verified build.
An ID without its typed verified row is insufficient.

Require value_status=VALUE and non-null values. Resolve each declared input
field against the exact ordered ObservationValueSchema. Reject missing or
duplicate fields and schema/type mismatches. Preserve SourceSpec input order.
Never infer types, coerce scalars, search backward or substitute another row.

ObservationFeatureTransformInput has exactly:

~~~text
field_names, field_logical_types, values, parameters
~~~

These are deeply immutable tuples: declared names in SourceSpec order, their
selected schema types, corresponding values from one selected row, parameters
in name order. No rows/window abstraction, paths, clocks, source/provider
objects or callbacks. The call-contract and registration must agree on every
input and output type.

ObservationFeatureValueResult has exactly these logical fields:

~~~text
sample_key, multi_source_sample_version_id, feature_name, spec_pin,
implementation_pin, decision_id, status, value, reason_code,
consumed_observation_version_id
~~~

COMPLETE requires a COMPLETE A3 decision, VALUE row, exact-type finite
non-null scalar, reason_code=null, and consumed version equal to the selected
version. Transform or admission error fails the execution; it is not an
EXCLUDED missing value.

EXCLUDED requires an EXCLUDED A3 decision; no transform call, value=null,
reason_code exactly decision.reason, consumed_observation_version_id=null.
STALE/NOT_REPORTED/WITHDRAWN selected references remain in A3 provenance but
are not consumed values. No PARTIAL status.

ObservationFeatureSampleResult fields are sample_key,
multi_source_sample_version_id, status, values. One value per normalized
Observation spec in stable (kind, name, version, content_sha256) SpecPin order.
Sample COMPLETE iff every value is COMPLETE; otherwise EXCLUDED.
ObservationFeatureExecutionResult fields are samples, feature_spec_pins,
implementation_pins, execution_contract_version. Samples sort by sample_key;
exactly one per A3 sample binding. All result constructors reverify cardinality,
cross-references and derived status; they do not accept arbitrary trusted data.

Freeze value provenance identity H(observation-feature-value-v1, fields)
with exactly sample_key, multi_source_sample_version_id, feature_name,
feature_spec_pin_id, implementation_pin_id, decision_id, status, value,
reason_code, consumed_observation_version_id. feature_spec_pin_id is the
unchanged A3 pin ID; implementation_pin_id is
H(dataset-implementation, R(implementation_pin)). This identity is
bound, for COMPLETE and EXCLUDED values, through a sorted sequence
S(observation-feature-values-v1, value IDs in (sample_key, feature_spec_pin_id)
order). Call this observation_feature_values_content_id. This logical digest,
unlike the physical file SHA, enters the new Dataset ID.

## 6. Pure Multi-Source Orchestration

Inputs: explicit tuples of VerifiedCanonicalBuild, VerifiedObservationBuild,
PITSampleRequest, bar FeatureSpec, ObservationFeatureSpec, LabelSpec; one
ChronologicalSplitSpec, DatasetScope and explicit dataset_as_of (aware instant
or null). V1 is SUPERVISED, with nonempty verified Canonical and Observation
build sets and nonempty spec sets for each Feature family and Labels.
Zero sample requests are legal; no implicit sample generation.

Scope/request binding is the frozen Canonical rule: code, anchor date,
interval, adjustment and requested session agree; duplicate sample keys fail.
Normalize every input, reject conflicts and validate registry/spec contracts
before returning an EMPTY result.

Exact execution order, once each:

1. Normalize all specs and registry contracts.
2. Validate scope/request binding.
3. Existing Canonical PIT assembly.
4. Derive A3 bindings from ObservationFeatureSpecs.
5. A3 Observation PIT assembly.
6. Existing bar Feature executor.
7. Observation Feature executor.
8. Existing bar Label executor.
9. Cross-verify every sample/spec/provenance binding.
10. Derive multi-source sample eligibility.
11. Construct split samples.
12. Existing chronological split.
13. Derive completion.
14. Derive final logical rows.
15. Derive schema and logical content.
16. Construct MultiSourceDatasetIdentityInput.
17. Compute multi_source_dataset_id.

Do not call the old orchestrator (which would execute upstream stages again).
A4.2-owned orchestration, identity, evidence, audit and result code performs
no filesystem access. The complete pipeline may inherit only the frozen
built-in bar Feature/Label registry implementation-source fingerprint reads
defined in 6.2; this is not a general read-only filesystem allowance.
No plan/settings/latest/current-time/provider access. A3 keeps
T=feature_window_close and A=dataset_as_of; revision-before-alignment,
event_time cross-key ordering, exact/latest-effective modes, freshness after
selection and no backward search remain unchanged. Preserve A3's conservative
proof clock and extended [selected.event_time,T] stale-candidate coverage;
missing policy cannot downgrade unproved authority.

Matrix eligibility is all bar Features COMPLETE AND all Observation Features
COMPLETE. Any exclusion removes the entire sample from matrix rows, not from
A3 decision/evidence/sample-binding artifacts or Feature outcome artifacts.
Incomplete Labels retain the existing Feature-complete audit row with null
values for incomplete individual Labels; use the existing aggregate Label
status/end time. Do not turn Label incompleteness into Feature exclusion.

Keep sample_key equal to the old bar logical key. The matrix's
sample_version_id is exactly A3 multi_source_sample_version_id. The original
bar sample_version_id stays unchanged in bar associations and sample bindings.

Split inputs are existing ChronologicalSplitSample objects with sample_key,
sample_version_id=multi_source_sample_version_id, feature_window_close,
actual_label_end_time and label_status. The latter two come from the
same-key existing Label result, never nominal horizon inference. Observation
clocks do not become split boundaries. Preserve date geometry, purge and
INCOMPLETE policies; assigned/purged/excluded split status does not alter
computation completion.

CompletionSummary is structurally reused over scope.symbols x trade_dates:
no request is MISSING / NO_SAMPLE_REQUEST; any Feature-family exclusion or
Label incompleteness is INCOMPLETE with exactly
MULTI_SOURCE_FEATURE_EXCLUDED, LABEL_INCOMPLETE, or
MULTI_SOURCE_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE; otherwise COMPLETE with
null reason. Detailed Observation reasons stay in A3, never Canonical gaps.

### 6.1 Matrix Schema And Row Order

Columns, in exact order (N=non-nullable, Y=nullable):

| Column | Logical type | Nullable |
| --- | --- | --- |
| code | string | N |
| sample_key | string | N |
| sample_version_id | string | N |
| feature_window_close | timestamp_us_utc | N |
| actual_label_end_time | timestamp_us_utc | Y |
| label_status | string | N |
| dataset_as_of (only when cutoff is non-null) | timestamp_us_utc | N |
| bar Feature outputs in old stable SpecPin order | declared type | N |
| Observation Feature outputs in Observation SpecPin order | int64/float64 | N |
| Label outputs in old stable SpecPin order | declared type | Y |
| feature_window_close_date | date32 | N |
| nominal_split | string | Y |
| final_split | string | Y |
| assignment_status | string | N |
| reason_code | string | Y |
| purge_boundary | timestamp_us_utc | Y |

All output names across both Feature families and Labels must be unique and
must avoid every reserved fixed field (including dataset_as_of when absent).
No union schema or inferred nullability. Rows sort by (code,
feature_window_close, sample_key); no duplicate sample key. Reuse
dataset_schema_id and logical_dataset_content_id exactly on this derived
DatasetSchema and exact rows, after stricter Observation scalar validation.
Logical row multiplicity/order rules remain those frozen functions.

### 6.2 Inherited Registry Source-Read Boundary

At the clarification base `7aad267917c0e5fbbe7134aae1324cbcf813aa63`
(tree `0ddd7d102db5639d78db64228a30b28b40ec82b2`), the existing Dataset
Feature and Label executors construct their built-in registries internally.
Those frozen registries derive implementation fingerprints through
`dataset.transform_models._module_source_sha256(...)` calling
`inspect.getsource(module)`. The sole allowed inherited read class is
`INHERITED_REGISTRY_SOURCE_READ`: read-only access to the source of an
already-loaded, statically registered built-in implementation module, only
to derive its existing normalized source SHA/fingerprint for immutable
`TransformRegistration` / `ImplementationPin` facts. No dynamic module
discovery, caller-supplied precomputed registry or caller-authored pin bypass
is authorized.

This is a closed-world allowance for existing behavior, not permission for
new filesystem access. It does not authorize A4.2-owned file reads or writes,
nor direct or indirect new access to Canonical, Observation or Dataset
artifact files; Feature, Observation Feature, Label or split spec files;
sample-generation plans; manifests; Catalog files; settings files;
environment-derived data authority; latest/current pointers; directory scans
or filesystem inventory; mtime or cwd-derived authority. Network, providers,
OpenD and current time remain forbidden. All Dataset inputs remain explicit,
already-verified in-memory objects. Any filesystem access outside the exact
inherited registry fingerprint behavior is a contract violation.

~~~text
INHERITED_REGISTRY_SOURCE_READ_ONLY=true
INHERITED_REGISTRY_SOURCE_READ_MUTATION=false
INHERITED_REGISTRY_SOURCE_READ_IS_DATA_AUTHORITY=false
INHERITED_REGISTRY_SOURCE_READ_IS_PIT_AUTHORITY=false
INHERITED_REGISTRY_SOURCE_READ_IS_PROVIDER_AUTHORITY=false
INHERITED_REGISTRY_SOURCE_PATH_IDENTITY_BOUND=false
INHERITED_REGISTRY_SOURCE_MTIME_IDENTITY_BOUND=false
INHERITED_REGISTRY_SOURCE_CWD_IDENTITY_BOUND=false
~~~

Only normalized implementation source content affects the already-existing
implementation fingerprint, exactly under the frozen old executor contract.
Source location, path, mtime and cwd are not identity-bearing. Relocating
byte-identical verified Canonical/Observation artifacts still cannot change
`multi_source_dataset_id`.

"Pure Multi-Source Orchestration" means no hidden market/data/provider
authority, no filesystem-backed Dataset input, no mutable external state
used as Dataset input or mutated by orchestration, and deterministic output
from explicit verified inputs plus the frozen implementation fingerprints
of statically registered transforms. The inherited source read is
implementation attestation, not Dataset input or a PIT/provider authority.

The exact once-per-layer execution order in section 6 remains unchanged.
Do not replace or modify the existing Feature/Label executors, registries,
implementation fingerprint/ImplementationPin semantics, Feature/Label value
identities or old Dataset ID. A1, A2, A3 and A4.1 remain unchanged, including
the already-reviewed A4.1 Observation registry fingerprint behavior. This
clarification exists because A4.2 must compose the frozen legacy bar
executors rather than replace them; it does not authorize implementation.

## 7. Complete Evidence And New Dataset Identity

### 7.1 Observation Evidence

observation_evidence_content_id is defined under
multi-source-observation-evidence-v1 over complete A3
ObservationDecisionEvidence, including excluded decisions and every
considered proof, not only selected builds.

For each evidence item, pair each BuildPin with its corresponding Coverage;
recompute A1 coverage_id and require equality to pin.coverage_id. Normalize
the pairs by recomputed observation_build_pin_id. Duplicate pair IDs,
unpaired coverage, conflicting pin facts or missing evidence fail closed.
Do not independently sort coverages and accidentally change the pairing.

~~~text
pair_id = H("multi-source-observation-proof-v1", {
  observation_build_pin_id: A3.observation_build_pin_id(pin),
  coverage_id: A1.observation_coverage_id(coverage)
})
item_id = H("multi-source-observation-evidence-item-v1", {
  sample_key, feature_spec_pin_id,
  proofs_digest: S("multi-source-observation-proofs-v1", ordered pair_ids)
})
observation_evidence_content_id =
  S("multi-source-observation-evidence-v1", item_ids ordered by
    (sample_key, feature_spec_pin_id))
~~~

The exact distinct BuildPin IDs (not just observation_build_id), all coverage
IDs and evidence identity are also explicit in the manifest/identity input.
The same build may have different per-decision selected-version facts.
coverage_proof_available_at is A2 created_at and remains identity-bearing
here through A3 BuildPin, unlike this Dataset's non-identity built_at.
No hidden proof input, discarded unused declared proof or path-based identity.

Retain the A3 bar_association_content_id, observation_association_content_id,
sample_binding_content_id and combined_association_content_id exactly.
The combined ID input is the unchanged A3 H payload:

~~~text
H("multi-source-association-content-v1", {
  bar_association_content_id, bar_association_schema_id,
  bar_association_schema_version: "pit-association-schema-v1",
  observation_association_content_id,
  observation_association_schema_version: "observation-association-v1",
  sample_binding_content_id,
  sample_binding_schema_version: "observation-sample-binding-v1",
  multi_source_pit_contract_version: "multi-source-pit-v1"
})
~~~

### 7.2 Sample Audit Closure

A self-contained reader cannot recover a zero-bar/excluded request from a
hash, nor rerun upstream transforms to discover bar exclusion or Label timing.
Therefore the manifest carries an identity-bound sample_audit, distinct from
the non-identity build report. It contains exactly one item per original
request, sorted by sample_key, with these fields:

~~~text
sample_key, request, bar_sample_version_id, dataset_as_of,
considered_canonical_build_ids, feature_canonical_row_version_ids,
label_canonical_row_version_ids, bar_feature_status, bar_feature_values,
label_status, actual_label_end_time, label_values
~~~

request is the exact PITSampleRequest record: code, interval, adjustment,
requested_session, anchor_market_calendar_date, feature_window_start,
feature_window_close, label_window_start, label_window_close; the optional
Label boundaries are null together. The two ordered
row-version sequences and sorted considered IDs reconstruct the frozen bar
version and must agree with bar association positions and Canonical pins.

bar_feature_values records each old Feature outcome in stable spec order,
with exact fields feature_name, spec_pin, implementation_pin, status, value,
reason_code, consumed_canonical_row_version_ids. label_values records
label_name, spec_pin, implementation_pin, status, value, reason_code,
anchor_canonical_row_version_id, consumed_label_canonical_row_version_ids,
actual_label_end_time. These are the full frozen ValueResult shapes, not
truncated output-only projections. Pin records use the existing shapes;
values retain their declared scalar types. Status/reason/null rules stay
those of the existing executors. Consumed versions must belong to the exact
sample/role association subset, with the Label anchor bound to its Feature
association. Per-Label actual end equals the last consumed Label row's
market_available_at when present. Sample bar_feature_status and label_status
are derived from all values; actual_label_end_time is the maximum non-null
per-Label end, or null if all ends are null. This is recorded computation
provenance, not proof of transform recomputation.

Define F(prefix, value): recursively flatten a validated exact-schema record
into scalar fields. Object keys are traversed sorted, nested names separated
by ".", lists emit "<prefix>.count" and "<prefix>.0000", etc.; record keys
cannot contain "." and array indices have minimum width four. A null object
emits just its prefix=null; an empty object emits "<prefix>.count"=0.
Values are typed before flattening, so timestamps remain timestamps for H.
No user-defined mapping keys occur here except normalized parameter names.

sample_audit_content_id = H("multi-source-sample-audit-v1",
F("samples", sample_audit)). This also binds outcomes for samples absent from
the matrix. It supplies explicit audit inputs for completion/split checks;
build_report never supplies missing authority.

### 7.3 Identity Input And Exact Encoder

MultiSourceDatasetIdentityInput is separate, not a DatasetIdentityInput
subclass. It validates SUPERVISED kind, exact schema/content, scope/cutoff,
Canonical coverage of every pinned row version, spec family/name uniqueness,
implementation conflicts, completion and Canonical gap references using
equivalent frozen rules. It additionally closes all A3/A4 references.

Its exact fields are the following H payload fields plus schema,
sample_audit and complete observation_evidence (normalized typed objects).
The latter objects must reproduce their supplied digests, not bypass them.
For this formula D_scope, D_build, D_spec, D_impl, D_completion and D_gap
mean the unchanged scalar digests in dataset.identity at the design base.
Reuse their payloads without modifying old functions or domains.

multi_source_dataset_id = H("multi-source-dataset-id-v1", {

~~~text
dataset_kind,
scope: D_scope(scope),
dataset_as_of,
dataset_schema_id,
logical_dataset_content_id,
canonical_builds: join_RS(sorted(D_build(pin))),
canonical_row_version_ids: join_RS(sorted(distinct row IDs)),
bar_feature_specs: join_RS(sorted(D_spec(pin))),
observation_feature_specs: join_RS(sorted(D_spec(pin))),
label_specs: join_RS(sorted(D_spec(pin))),
split_spec: D_spec(split pin),
implementations: join_RS(sorted(D_impl(pin))),
completion: D_completion(completion),
gap_references: join_RS(sorted(D_gap(ref))),
manifest_schema_version: "multi-source-dataset-manifest-v1",
serialization_format: "parquet",
serialization_format_version: "multi-source-dataset-parquet-v1",
bar_association_schema_id,
bar_association_content_id,
observation_association_schema_version: "observation-association-v1",
observation_association_content_id,
sample_binding_schema_version: "observation-sample-binding-v1",
sample_binding_content_id,
combined_association_content_id,
multi_source_pit_contract_version: "multi-source-pit-v1",
observation_evidence_content_id,
observation_build_pin_ids: join_RS(sorted(distinct full BuildPin IDs)),
observation_coverage_ids: join_RS(sorted(distinct coverage IDs)),
observation_feature_values_content_id,
sample_audit_content_id,
observation_feature_execution_contract_version: "observation-feature-execution-v1",
multi_source_dataset_orchestration_contract_version: "multi-source-dataset-orchestration-v1"
~~~

}). join_RS joins validated 64-hex members with U+001E; empty is "". Reject
duplicate semantic inputs before hashing except explicitly identical shared
implementation pins and the defined distinct aggregate proof-ID sets.
Never call old dataset_id with extra fields.

Changing any declared Observation spec, decision, selected version,
considered proof, coverage proof clock, implementation fingerprint, combined
association, logical outcome/audit or matrix content changes the new ID.
Input order, relocated identical verified sources, path, this build's
built_at, physical file size/hash, Parquet compression and build report do not.

## 8. Physical Cohort

Exact final layout; no other file, latest/current pointer or optional sidecar:

~~~text
<output_root>/<multi_source_dataset_id>/
  dataset.parquet
  associations/bar.parquet
  associations/observation.parquet
  associations/sample_bindings.parquet
  associations/observation_feature_values.parquet
  associations/observation_evidence.json
  feature_specs/bar/<content_sha256>.yaml
  feature_specs/observation/<content_sha256>.yaml
  label_specs/<content_sha256>.yaml
  split_spec.yaml
  build_report.json
  manifest.json
  _SUCCESS
~~~

One spec artifact per exact pin, filenames use its lowercase semantic content
hash, not unsafe names or input indices. Bar Feature/Label/Split artifacts
use the unchanged canonical serializers. Observation spec artifacts use 3.1.
File listings must equal the derived whitelist, including exact directories.

### 8.1 Association Schemas

In the tables, string=pa.string(), int64=pa.int64(), float64=pa.float64(),
bool=pa.bool_(), timestamp_us_utc=pa.timestamp("us", tz="UTC"),
date32=pa.date32(). N means nullable=false, Y nullable=true. No type inference,
schema widening, nested union values or column reordering is allowed.

bar.parquet preserves the exact old association columns and row values:

| Column | Type | Nullable |
| --- | --- | --- |
| sample_key | string | N |
| sample_version_id | string | N |
| role | string | N |
| position | int64 | N |
| canonical_build_id | string | N |
| canonical_bar_key | string | N |
| canonical_row_version_id | string | N |
| code | string | N |
| event_time | timestamp_us_utc | N |
| market_available_at | timestamp_us_utc | N |
| archive_available_at | timestamp_us_utc | N |

Sort by (sample_key, role, position); positions are contiguous from zero per
sample/role. Recompute existing pit_association_schema_id and
pit_association_content_id, without changing the bar sample version.

observation.parquet encodes exactly the A3 ObservationPITDecision fields:

| Column | Type | Nullable |
| --- | --- | --- |
| sample_key | string | N |
| bar_sample_version_id | string | N |
| feature_spec_pin_id | string | N |
| observation_source_spec_id | string | N |
| T | timestamp_us_utc | N |
| A | timestamp_us_utc | Y |
| considered_observation_builds_digest | string | N |
| status | string | N |
| reason | string | Y |
| archive_limited | bool | N |
| selected_observation_key | string | Y |
| selected_observation_version_id | string | Y |
| selected_observation_build_id | string | Y |
| selected_source_snapshot_id | string | Y |
| selected_known_at_authority_id | string | Y |
| selected_event_time | timestamp_us_utc | Y |
| selected_known_at | timestamp_us_utc | Y |
| selected_archive_available_at | timestamp_us_utc | Y |
| scoped_version_count | int64 | N |
| future_known_excluded_count | int64 | N |
| archive_future_excluded_count | int64 | N |
| eligible_key_count | int64 | N |
| alignment_candidate_count | int64 | N |

Sort by (sample_key, feature_spec_pin_id); one exact decision per sample/spec.
All eight selected fields obey A3's all-null/all-present rule, including
selected-but-excluded reasons. Counts/status/clock rules remain A3's.

sample_bindings.parquet has four non-nullable string columns, in order:
sample_key, bar_sample_version_id, observation_binding_id,
multi_source_sample_version_id. Sort by sample_key; exact A3 rows, one per
request even when excluded. Recompute bindings and all A3 content IDs.

observation_feature_values.parquet has this exact order:

| Column | Type | Nullable |
| --- | --- | --- |
| sample_key | string | N |
| multi_source_sample_version_id | string | N |
| feature_name | string | N |
| feature_spec_pin_id | string | N |
| implementation_name | string | N |
| implementation_version | string | N |
| implementation_content_sha256 | string | N |
| decision_id | string | N |
| status | string | N |
| output_logical_type | string | N |
| value_int64 | int64 | Y |
| value_float64 | float64 | Y |
| reason_code | string | Y |
| consumed_observation_version_id | string | Y |

Sort by (sample_key, feature_spec_pin_id). Resolve full SpecPin through
manifest/spec artifacts. COMPLETE has exactly one populated value column
matching declared output type; the other is null. EXCLUDED has both null.
The two-slot encoding preserves types without coercing int64 into float64.
Reconstruct logical ValueResult and its identity, including full
implementation pin. No extra value row or missing excluded row is legal.

### 8.2 Arrow Metadata And Physical Facts

All five Parquet files use exact schema/nullability and no field metadata.
Required schema metadata keys (UTF-8 keys/values), with no other application
keys, are market_vault.multi_source_dataset_id,
market_vault.serialization_format_version,
market_vault.materializer_version, market_vault.file_role,
market_vault.logical_schema_id, market_vault.logical_content_id,
market_vault.row_order. Matrix uses existing schema/content IDs; bar uses
existing association IDs; A3 tables use their exact schema version string in
logical_schema_id and their A3 content ID; Feature values use
observation-feature-value-v1 and observation_feature_values_content_id.
These labels are explicitly typed contracts, not alternate A3 schema hashes.

file_role is respectively MATRIX, BAR_ASSOCIATION, OBSERVATION_ASSOCIATION,
SAMPLE_BINDING, OBSERVATION_FEATURE_VALUES. row_order is respectively
CODE_FEATURE_CLOSE_SAMPLE_KEY, SAMPLE_ROLE_POSITION,
SAMPLE_FEATURE_SPEC_PIN_ID, SAMPLE_KEY, SAMPLE_FEATURE_SPEC_PIN_ID.
Arrow's serialized schema footer is interpreted as encoding metadata, not a
new logical field. Reject unexpected semantic metadata.

Parquet writer settings: zstd, use_dictionary=false, write_statistics=true,
coerce_timestamps=us, allow_truncated_timestamps=false, version=2.6,
data_page_version=2.0. These freeze supported serialization policy, not
cross-library byte equality. EMPTY matrix and empty associations are legal
zero-row files with their exact schemas.

OutputFile fields are exactly relative_path, file_role, byte_size, sha256,
row_count, content_role, content_id, artifact_version. row_count is a
nonnegative int for Parquet, null for JSON/YAML. Hashes are lowercase 64-hex;
paths must be exact safe whitelist members. content_role states the verified
logical authority; spec content IDs differ from their physical SHA.

The manifest lists every file except itself and _SUCCESS; neither is
recursively hashed. _SUCCESS is exactly an empty regular file. Manifest
canonical bytes and marker are verified directly, including a second pass.
No output SHA, size or built_at enters logical Dataset identity.

### 8.3 Exact Observation Evidence JSON

Top-level fields: schema_version="multi-source-observation-evidence-v1",
items. Each item: sample_key, feature_spec_pin_id, proofs. Each proof:
observation_build_pin_id, build_pin, coverage. Lists use the order in 7.1.

build_pin is the exact A3 record: observation_build_id,
observation_content_id, observation_schema_version, coverage_id,
coverage_proof_available_at, status, authority_evidence_ids,
provider_contracts, normalizations, source_snapshots,
selected_observation_version_ids. Contract pairs have version, content_id.
Hash tuples sort, contracts sort by (version, content_id), snapshots sort by
source_snapshot_id. No source file path or URL.

Snapshot fields: source_snapshot_id, source_content_sha256, provider_id,
source_kind, provider_contract_version, provider_contract_content_id,
normalized_request_id, acquisition_receipt_id,
acquisition_receipt_content_id, completed_possession_at.

Coverage fields: scope, provider_contract, effective_start, effective_end,
knowledge_start, knowledge_end, normalized_request_id,
request_completion_evidence_id, request_pages_complete, missing_semantics,
missing_semantics_content_id, revision_inventory_content_id,
revision_inventory_complete. Scope fields: provider_id, source_kind,
entity_id, observation_name, dimensions (exact typed triples).

J serialization is mandatory. Reject unknown/missing/duplicate JSON fields.
Reconstruct exact typed A1/A3 objects; recompute coverage ID, BuildPin IDs,
considered digest per decision and evidence content ID. Cross-check source
scope/policies, snapshot pins, archive proof clock, selected membership and
all referenced authorities. No caller-authored evidence path is trusted.

### 8.4 Separate Manifest And Build Report

MultiSourceDatasetManifest has exactly the following top-level fields:

~~~text
manifest_schema_version, dataset_id, dataset_kind, status, built_at,
scope, dataset_as_of, schema, dataset_schema_id, logical_dataset_content_id,
logical_row_count, row_order,
canonical_builds, canonical_row_version_ids,
bar_feature_specs, observation_feature_specs, label_specs, split_spec,
implementations, completion, gap_references,
bar_association_schema_id, bar_association_content_id,
bar_association_schema_version,
observation_association_schema_version, observation_association_content_id,
sample_binding_schema_version, sample_binding_content_id,
combined_association_content_id, multi_source_pit_contract_version,
observation_evidence_content_id, observation_build_pin_ids,
observation_coverage_ids, observation_feature_values_content_id,
sample_audit, sample_audit_content_id,
observation_feature_execution_contract_version,
multi_source_dataset_orchestration_contract_version,
materializer_version, serialization_format, serialization_format_version,
reader_contract_version, spec_artifact_versions, output_files
~~~

Unchanged nested Dataset shapes use the exact named JSON records of
dataset.manifest at the design base: schema, scope, CanonicalBuildPin with
SourceSnapshotPin children, SpecPin, ImplementationPin, CompletionSummary
with entries, GapReference. Their field sets and scalar parsers are normative;
no optional extension of the OLD manifest is made. Only the new top-level
schema dispatch accepts this record.

spec_artifact_versions has exact keys bar_feature, observation_feature,
label, split; values respectively market-vault-feature-spec-v1,
observation-feature-spec-yaml-v1, market-vault-label-spec-v1 and
market-vault-chronological-split-spec-v1. Bar/Label/Split values identify
their unchanged canonical artifact contracts, not new version claims.

Output file roles beyond the five Parquet roles are OBSERVATION_EVIDENCE,
BAR_FEATURE_SPEC, OBSERVATION_FEATURE_SPEC, LABEL_SPEC, SPLIT_SPEC,
BUILD_REPORT. content_role equals file_role. Exact content/version binding:

| file_role | content_id | artifact_version |
| --- | --- | --- |
| MATRIX | logical_dataset_content_id | multi-source-dataset-parquet-v1 |
| BAR_ASSOCIATION | bar_association_content_id | multi-source-dataset-parquet-v1 |
| OBSERVATION_ASSOCIATION | observation_association_content_id | multi-source-dataset-parquet-v1 |
| SAMPLE_BINDING | sample_binding_content_id | multi-source-dataset-parquet-v1 |
| OBSERVATION_FEATURE_VALUES | observation_feature_values_content_id | multi-source-dataset-parquet-v1 |
| OBSERVATION_EVIDENCE | observation_evidence_content_id | multi-source-observation-evidence-v1 |
| BAR_FEATURE_SPEC | that SpecPin.content_sha256 | market-vault-feature-spec-v1 |
| OBSERVATION_FEATURE_SPEC | that SpecPin.content_sha256 | observation-feature-spec-yaml-v1 |
| LABEL_SPEC | that SpecPin.content_sha256 | market-vault-label-spec-v1 |
| SPLIT_SPEC | split SpecPin.content_sha256 | market-vault-chronological-split-spec-v1 |
| BUILD_REPORT | null | multi-source-dataset-build-report-v1 |

Only BUILD_REPORT has null content_id. Physical fact rows sort by relative_path.

Manifest uses J; identity-bearing fields reconstruct the exact input in 7.3.
status is EMPTY iff logical_row_count=0, otherwise COMPLETE; completion is
independent. built_at is explicit aware UTC microsecond metadata, never
current-time default or proof clock. Paths and bytes do not affect IDs.

Build report exact fields: report_version, built_at, dataset_id, status,
sample_count, matrix_row_count, feature_excluded_sample_count,
label_incomplete_sample_count, observation_complete_value_count,
observation_excluded_value_count, split_assigned_count, split_purged_count,
split_excluded_count, completion. report_version is
multi-source-dataset-build-report-v1; J serialization. Every count/summary
must equal reconstructed manifest/matrix/association/spec facts.
The report supplies no missing proof, winner, Feature value or authority.

## 9. Sole New Verified Reader

Future load_verified_multi_source_dataset(build_dir) is separate from
load_verified_dataset. Old reader rejects this manifest as unsupported.
New reader rejects old manifest; no best-effort dispatch.

Explicit path only, read-only, no settings/latest/parent scanning, no writes,
repair, current time, upstream Canonical/Observation reload, PIT execution,
transform execution or provider calls. It validates recorded artifact
integrity/provenance, not re-acquisition of economic truth.

Before trust:

1. Inspect every path component for symlink/junction/reparse, escapes,
   unverifiable types and root substitution. A resolved in-root link is
   still forbidden. Reject unsafe member syntax (absolute, dot/dot-dot,
   empty, backslash, drive or ADS colon).
2. Require exact manifest version, canonical bytes/field sets, final directory
   name, inventory and empty regular _SUCCESS.
3. Verify every file size/SHA, metadata, exact schema/nullability, order and
   row count. Strict UTF-8/YAML/JSON; all documented Unicode/Arrow decoding
   failures become the new dedicated artifact error with cause preserved.
4. Parse specs and recompute both families' pins. Rebuild bindings from
   Observation specs; no unverified SourceSpec shortcut.
5. Verify bar associations with old schema/content algorithms and sample
   audit's recomputed sample keys/versions, positions and Canonical pins.
6. Reconstruct A3 decisions, sample bindings and evidence. Recompute every
   decision, binding, multi-source sample, considered-build and component/
   combined content ID; cross-check selected/evidence/cutoff facts.
   This is recorded identity/structural closure, not a second PIT selector.
7. Reconstruct every Observation Feature result; verify spec, decision,
   implementation and consumed-version linkage, exact types and reasons.
   EXCLUDED decisions have no consumed value even when selected fields exist.
8. Recompute Feature-family eligibility from all recorded outcomes and require
   exact matrix sample equality, not just absence of Observation exclusions.
   Match COMPLETE Feature values and Label null/value facts exactly to rows.
9. Reconstruct split inputs from eligible sample audit, substitute only A3
   multi-source sample versions and verify the unchanged split algorithm's
   facts. Recompute completion and cross-check the non-authoritative report.
10. Recompute logical schema/content, evidence, audit and new Dataset ID.
11. Before constructing a deeply immutable verified result, revalidate root
    object identity and exact inventory AND reread manifest, marker and all
    committed files. Require identical bytes or SHA+size to the initially
    verified bytes. Inventory equality alone cannot prove content stability.

No broad exception catch hiding programming errors; already dedicated errors
remain unwrapped. A reader failure never triggers final-directory cleanup.
No supported skip_validation, trust_me or from_unverified entry.

EMPTY due to exclusion retains Canonical pins, all Observation proof pins,
all component associations, sample bindings, Feature outcomes, specs,
implementations, sample audit and completion. It is not zero provenance.

## 10. Future Atomic Publication Contract

The companion [operation contract](governance/destructive_operations/multi_source_dataset_atomic_publication_v1.json)
must be merged unchanged in the later A4.3 implementation BASE. It does not
authorize implementation in this PR. No checker/exemption change and no reuse
of the historical Dataset exemption. Exactly two planned AST surfaces:

| Path | Symbol | Role | Kind / signal / count |
| --- | --- | --- | --- |
| src/market_vault/multi_source/materialization.py | _rename_directory_no_replace_windows | MUTATION_OWNER | destructive_call / os.rename / 1 |
| src/market_vault/multi_source/materialization.py | _remove_tree | SUPPORTING | destructive_call / shutil.rmtree / 1 |

No prospective_transition; future symbols are absent at this BASE.
Windows uses true no-replace os.rename only in the bound helper; destination
exists maps explicitly. Linux uses narrowly bounded renameat2(RENAME_NOREPLACE);
EEXIST/ENOTEMPTY means destination exists. Missing primitive,
EINVAL/ENOSYS/ENOTSUP/EOPNOTSUPP, unsupported platform/filesystem and other
errors fail closed. Never ordinary overwriting POSIX rename, os.replace,
Path.replace/rename, shutil.move, unlink/rmdir or delete-then-rename.

Materialization has explicit result, output_root and built_at inputs.
Staging is .<multi_source_dataset_id>.tmp-<random>, an exclusively created
sibling of the final ID directory. Own only that invocation's uncommitted
staging, with path/object identity and safe root/final binding retained and
revalidated before publication/cleanup. Never adopt/delete pre-existing
staging, existing finals or other artifacts. On uncertain ownership leave
residue and fail; never broaden cleanup or sweep orphans.

Write all artifacts, privately verify them, write _SUCCESS last, verify it,
revalidate ownership and same-filesystem ancestry, then atomically publish
NO-REPLACE. Marker inside staging is not a commit. Only successful publication
crosses PRIVATE_STAGING to COMMITTED; final still requires strict reader
verification. No partial visible final.

Existing final before staging is read/verify only: equivalent succeeds
without staging; corrupt/conflicting fails. An exists() precheck is not the
race boundary. On a concurrent winner, no-replace refuses, strict verification
decides equivalence and only owned staging may be cleaned. Never change the
winner. After commit no rollback deletion, repair, rewrite or movement.
Crashes can leave non-authoritative staging; post-commit finals stay immutable.
Permanent user-data deletion, Catalog cascades and production cleanup are
unsupported. See JSON for complete state/path/recovery contract.

## 11. Required Future Offline Canaries

These 58 canaries are obligations for the relevant runtime phase, not tests
claimed to execute in this docs PR. Additional assertions may extend a canary
without replacing it. All old A1/A2/A3 and old-cohort vectors remain.

1. Observation spec embeds the full typed SourceSpec.
2. YAML reorder, comments and CRLF preserve semantic spec ID.
3. Any semantic SourceSpec field change changes Observation Feature SpecPin.
4. A3 binding mismatch fails before transform.
5. Exact selected version is re-resolved from the verified representative.
6. Wrong value_schema_id fails.
7. Wrong or duplicate input field fails.
8. float64 identity transform returns the exact finite scalar.
9. int64 identity transform returns the exact bounded integer.
10. Implicit int/float coercion and bool acceptance fail.
11. EXCLUDED A3 decision never calls a transform.
12. STALE/NOT_REPORTED/WITHDRAWN keep provenance but consume no value.
13. Implementation fingerprint change changes the new Dataset ID.
14. Arbitrary transform reference fails registry preflight.
15. Zero samples still validate every spec, binding and registry contract.
16. Old bar sample_key survives the new cohort unchanged.
17. Matrix sample_version_id equals multi_source_sample_version_id.
18. Bar sample_version_id remains unchanged in sample-binding proof.
19. Observation exclusion removes the sample from the matrix.
20. Excluded sample remains in A3 artifacts and all considered evidence.
21. Label INCOMPLETE retains the eligible Feature-complete audit row.
22. Bar Feature exclusion still removes the sample.
23. Bar/Observation Feature output-name collision fails.
24. Observation/Label or reserved-field name collision fails.
25. Changing an unused but declared considered Observation proof changes ID.
26. Changing coverage_proof_available_at changes Dataset ID.
27. Changing an A3 decision changes Dataset ID.
28. Changing Observation spec changes Dataset ID.
29. Build/spec input order cannot change Dataset ID.
30. Relocated identical verified upstream artifacts preserve Dataset ID.
31. EMPTY matrix retains every upstream evidence identity and audit outcome.
32. Old Dataset/Feature/schema/manifest/A1/A3 vectors stay unchanged.
33. Old Dataset reader rejects the new manifest.
34. New reader rejects old manifest without a future explicit dispatcher.
35. Matrix tamper fails, including same-inventory mutation between read passes.
36. Bar association tamper fails.
37. A3 observation association tamper fails.
38. Sample-binding tamper fails.
39. Observation Feature value-sidecar tamper fails.
40. Observation evidence tamper or lost pin/coverage pairing fails.
41. Extra unlisted artifact fails.
42. Missing artifact or _SUCCESS alone fails.
43. Manifest identity mismatch or second-pass byte mutation fails.
44. Spec artifact/pin or noncanonical stored-spec mismatch fails.
45. Output hash/size, schema/nullability or metadata mismatch fails.
46. An excluded sample illegally present in matrix fails.
47. COMPLETE Observation value without exact selected-version linkage fails.
48. Reader performs no upstream reload, PIT, transform or provider calls.
49. Actual Windows existing destination, even empty, is never replaced.
50. Linux RENAME_NOREPLACE refuses an existing destination unchanged.
51. Unsupported no-replace capability fails closed, without fallback.
52. Race winner is never overwritten, deleted, repaired or moved.
53. Failure cleanup removes only current invocation-owned staging.
54. Pre-existing or substituted staging is never adopted or removed.
55. Committed final is never repaired, replaced or deleted after failure.
56. Crash staging residue is non-authoritative and not swept.
57. Reparse/symlink/junction, including non-escaping links, fails closed.
58. Unrelated output-root children and all upstream artifacts stay untouched.

### 11.1 Separate Implementation-Boundary Canary

`A42_INHERITED_REGISTRY_SOURCE_READ_BOUNDARY` is an additional named
implementation-boundary obligation for the later A4.2 tests, not a new
product-semantic canary. The existing product canaries keep their numbering
and `DESIGN_CANARY_COUNT=58`.

Prove that an orchestration invocation introduces no filesystem access
except the exact inherited built-in registry implementation-source
fingerprint reads in 6.2. Distinguish the allowed frozen source-read call
path and already-loaded static implementation targets from all forbidden
A4.2-owned reads and all artifact/spec/plan/settings/directory access.
Reject unrelated read targets or any broadened read authority; verify that
no write or new data authority is introduced. Do not monkeypatch all file
reads indiscriminately and then incorrectly expect the unchanged legacy
executors to succeed. Preserve the exactly-once execution assertions and
relocation/identity assertions alongside this boundary check.

## 12. Future Fixed-Vector Payloads

This section fixes encoder inputs, not fabricated known-answer hashes or
claims of existing implementation. A4.1/A4.2/A4.3 must add literal expected
digests/canonical bytes from these payloads, independently reviewed. Never
regenerate old vectors. Encoder-only vectors using synthetic hash tokens
are explicitly not valid upstream artifacts or bypasses of admission.

Let Z be 64 "0" characters, O be 64 "1" characters, P be 64 "2"
characters and Q be 64 "3" characters; all are literal lowercase strings,
not variables supplied by runtime users. Let U=2026-01-02T00:00:00.000000Z.
H, S, J, F and frozen Dataset digest helpers mean exactly sections 2 and 7.

### 12.1 Spec And Pin

Source vector S0 is the exact SourceSpec record:

~~~json
{
  "provider_id":"offline","source_kind":"series","observation_name":"rate",
  "dimensions":[{"name":"tenor","logical_type":"int64","value":10}],
  "entity_binding":"EXACT_ENTITY","entity_id":"US","code_entity_map":[],
  "input_field_names":["value"],"value_schema_id":"<Z>",
  "provider_contract_version":"v1","provider_contract_content_id":"<O>",
  "normalization_version":"v1","normalization_content_id":"<P>",
  "known_at_authority_policy_version":"v1",
  "known_at_authority_policy_content_id":"<Q>",
  "alignment":"LATEST_EFFECTIVE_AT_OR_BEFORE","exact_target_binding":null,
  "max_age_us":1000000,"missing_policy":"EXCLUDE_SAMPLE"
}
~~~

Angle-bracket tokens in this section are expanded to the literal strings
defined above before typed construction, never stored as placeholders.
Spec V0 has schema observation-feature-spec-v1, kind FEATURE, name
obs_rate, version v1, output {name:obs_rate, logical_type:float64,
nullable:false}, source_spec=S0, transform_ref=
market_vault.multi_source.feature_transforms:identity_float64, parameters={}.

Freeze H's exact fields from 3.2 for V0 (parameter_count=0 and no indexed
parameter fields), then SpecPin(FEATURE,obs_rate,v1,that hash), then A3
feature_spec_pin_id of that exact pin. Canonical YAML vector is J(V0).
Countervectors: dimension type/value (int64,10) versus (float64,10.0);
comments/key-order/CRLF versus canonical bytes; int64-output identity variant.

### 12.2 Implementation And Feature Value

Implementation vector is H(observation-feature-implementation-v1, {
transform_ref: the float64 ref above, implementation_version:v1,
implementation_source_sha256: SHA256 of UTF-8 "fixture-module-v1\n",
transform_call_contract_version:observation-feature-transform-call-v1,
observation_schema_version:observation-schema-v1, input_arity:1,
input_0000_logical_type:float64, output_logical_type:float64,
parameter_count:0 }). This synthetic source is an encoder fixture, not the
registered production implementation or an importable transform.
Its ImplementationPin is (ref,v1,fingerprint).

Feature value vector uses sample_key=Z, multi_source_sample_version_id=O,
feature_name=obs_rate, the derived V0 SpecPin and fixture ImplementationPin,
decision_id=P, status=COMPLETE, value=1.25 (float64), reason_code=null,
consumed_observation_version_id=Q. Apply the exact value payload in section 5.
Paired EXCLUDED vector changes status to EXCLUDED, value=null,
reason_code=STALE, consumed version=null. Do not reuse selected ID as consumed.

### 12.3 Evidence And Association

Coverage C0: scope {provider_id:offline, source_kind:series, entity_id:US,
observation_name:rate, dimensions:S0.dimensions}; provider_contract=(v1,O);
effective_start=effective_end=knowledge_start=knowledge_end=U;
normalized_request_id=Z; request_completion_evidence_id=P;
request_pages_complete=true; missing_semantics=EXPLICIT_EMPTY;
missing_semantics_content_id=Q; revision_inventory_content_id=O;
revision_inventory_complete=true.

Snapshot N0: source_snapshot_id=Z, source_content_sha256=O,
provider_id=offline, source_kind=series, provider_contract_version=v1,
provider_contract_content_id=O, normalized_request_id=Z,
acquisition_receipt_id=receipt-1, acquisition_receipt_content_id=P,
completed_possession_at=U.

BuildPin B0: observation_build_id=Z, observation_content_id=O,
observation_schema_version=observation-schema-v1,
coverage_id=A1.observation_coverage_id(C0), coverage_proof_available_at=U,
status=EMPTY, authority_evidence_ids=[Q], provider_contracts=[(v1,O)],
normalizations=[(v1,P)], source_snapshots=[N0],
selected_observation_version_ids=[].

Evidence item: sample_key=Z, feature_spec_pin_id=A3.feature_spec_pin_id(V0
pin), paired build_pins=[B0], coverages=[C0]. Apply every pair/item/sequence
payload in 7.1. Include empty-sequence and two-item reverse-order vectors.
These test complete pin encoding without pretending Z is a verified build.

Combined-association vector uses the exact 7.1 A3 payload with
bar_association_content_id=Z, bar_association_schema_id=O,
observation_association_content_id=P, sample_binding_content_id=Q.
No new combined-ID algorithm or A3 expected-hash regeneration.

### 12.4 Matrix Schema, Content And Dataset ID

Matrix vector schema is 6.1 without dataset_as_of, bar output
bar_return:float64/N, Observation output obs_rate:float64/N,
Label output label_return:float64/Y. No other variable output columns.
Use the existing DatasetSchema version and dataset_schema_id.

One row, in that schema: code=US.TEST, sample_key=Z, sample_version_id=O,
feature_window_close=U, actual_label_end_time=null, label_status=INCOMPLETE,
bar_return=0.5, obs_rate=1.25, label_return=null,
feature_window_close_date=2026-01-02, nominal_split=TRAIN, final_split=null,
assignment_status=EXCLUDED, reason_code=INCOMPLETE_LABEL, purge_boundary=null.
Compute logical_dataset_content_id of this exact row and of zero rows.
This is a logical-encoder fixture; full split admission uses separate valid
fixtures in the runtime canaries, not assumed validity of a machine reason.

Dataset-ID encoder vector: use the exact 7.3 scalar payload with
dataset_kind=SUPERVISED, scope=Z, dataset_as_of=null,
dataset_schema_id and logical_dataset_content_id from this matrix;
canonical_builds=O, canonical_row_version_ids=P, bar_feature_specs=Q,
observation_feature_specs=D_spec(V0 pin), label_specs=Z, split_spec=O,
implementations=D_impl(fixture implementation pin), completion=P,
gap_references="", bar_association_schema_id=O,
bar_association_content_id=Z, observation_association_content_id=P,
sample_binding_content_id=Q, combined_association_content_id=12.3 result,
observation_evidence_content_id=12.3 result,
observation_build_pin_ids=A3.observation_build_pin_id(B0),
observation_coverage_ids=A1.observation_coverage_id(C0),
observation_feature_values_content_id=S(observation-feature-values-v1,
[12.2 COMPLETE value ID]), sample_audit_content_id=
H(multi-source-sample-audit-v1,F("samples",[])).
All remaining version/format fields are exactly the constants in 7.3.
Synthetic prehashed scalar fixtures test encoding only; the public identity
constructor must still reject inconsistent provenance.

### 12.5 Manifest Canonical Bytes

Serialization fixture M0 uses exactly the 8.4 top-level fields, dataset_id
from 12.4, dataset_kind=SUPERVISED, status=COMPLETE, built_at=U,
scope={symbols:["US.TEST"],trade_dates:["2026-01-02"],adjustment:"NONE",
interval:"1m",requested_session:"RTH"}, dataset_as_of=null, schema=12.4
DatasetSchema's exact old manifest record, row_order=
CODE_FEATURE_CLOSE_SAMPLE_KEY, logical_row_count=1, schema/content IDs=12.4.

canonical_builds=[], canonical_row_version_ids=[], bar_feature_specs=[],
observation_feature_specs=[R(V0 pin)], label_specs=[], split_spec=null,
implementations=[R(fixture implementation pin)],
completion={complete_count:0,incomplete_count:0,missing_count:0,entries:[]},
gap_references=[], sample_audit=[], output_files=[].
Association/evidence/value/audit IDs and distinct proof-ID lists use the
12.3/12.4 values. All schema/contract/materializer/reader/serialization
versions and spec_artifact_versions are exactly 8.4; split artifact schema
is the frozen chronological split schema at the design base.

J(M0) is the fixed canonical serialization input: sorted keys, compact
separators, ASCII escapes, UTC instants, LF. M0 deliberately lacks valid
artifact provenance and must fail public verified-reader admission; canonical
encoding is tested separately from authority validation. A4.3 must also
freeze a COMPLETE and an exclusion-EMPTY end-to-end manifest from valid
offline runtime fixtures after all preceding phase vectors have been reviewed.

## 13. Submission Gates And Stop

The original design PR changed exactly this document and the new operation JSON.
Run diff --check, repository hygiene, release checker and destructive
repository inventory with D:-bound environment/output roots. Future exact
symbols may be absent; that is the checker's supported steady-binding model.
After commit run PR-mode destructive gate against the exact design BASE.

Natural exact-head CI chooses its tier; docs_fast is expected, not forced.
All required jobs and the actually executed destructive design gate must
succeed. No runtime tests, source/CI/checker/exemption/version edits or package
release builds are part of this design submission. Stop before merge for
independent architecture and governance review.

### 13.1 A4.2 Precondition Clarification History

The initial A4.2 implementation attempt stopped before modifying repository
files because its blanket no-filesystem statement conflicted with the
required frozen bar executors' implementation-source fingerprint reads.
Preserve that attempt's result without relabeling it:

~~~text
MULTI_SOURCE_CORE_A4_2_DATASET_ORCHESTRATION_IDENTITY=FAIL
FAILURE_CLASS=CONTRACT_PRECONDITION_CONFLICT
FAIL_REASON=FROZEN_BAR_EXECUTORS_REQUIRE_SOURCE_FILE_READS
CHANGED_FILE_COUNT=0
COMMIT_CREATED=false
PUSH_PERFORMED=false
PR_CREATED=false
A4_2_C_DRIVE_DEVELOPMENT_USED=false
~~~

The selected resolution is a separate design-only correction, limited to
this document, defining the narrow inherited registry source-read allowance
in 6.2. It is not a source/test/registry/executor/CI/governance-contract or
version change. Run D:-bound diff, repository hygiene, release checker and
destructive repository gates, then natural exact-head PR CI (docs_fast is
expected, never forced). Independent narrow contract review is required.
`A4_2_IMPLEMENTATION_AUTHORIZED=false`,
`A4_3_IMPLEMENTATION_AUTHORIZED=false`, and `MERGE_AUTHORIZED=false` remain
in effect for this correction. No A4.2 implementation resumes here.
