# Cross-Day TS2 Feature Authority v1

## 1. Status and Authority

```text
PHASE=L3_DESIGN_PREFLIGHT
BASE_MAIN_SHA=aae9a137e99d067fbfef321d5098d4757552c968
BASE_MAIN_TREE=10b29e2e3c3f7f93e3cf5c5f803361c318bd1392
SELECTED_ARCHITECTURE=PARALLEL_TS2_FEATURE_AUTHORITY
TS2_SOURCE_SCHEMA=10.9-mv-ts2
LEGACY_10_9_ADMITTED=false
VERSION=0.8.0
L3_IMPLEMENTATION_AUTHORIZED=false
L4_IMPLEMENTATION_AUTHORIZED=false
MERGE_AUTHORIZED=false
```

This is a candidate design for independent review, not implemented runtime
or implementation authorization. It closes the Feature-side design questions
required by [L1 section 11](cross_day_trading_days_label_v1.md#11-future-dataset-and-generator-boundary).
L1 and corrected L2 are sealed on the stated base. Their six vectors, 53
digest assertions and 66 canaries remain unchanged. The rejected first L2
review remains FAIL; this document does not relabel that historical result.

Future code belongs in a new parallel `market_vault.ts2_feature` package.
It may import the explicitly identified sealed pure models, validation and
formula functions below; old authorities must not import the new package.
No runtime file is created by this PR.

The old `dataset.feature_registry` and `dataset.feature_execution` remain
`10.9` BARS authority. Neither can execute this TS2 cohort. No widening,
fallback, rebinding of old registrations, or mutation of old ImplementationPins
is allowed. Old Label execution, Sample Generator, PIT v1, A1-A4 and L2 are
unchanged. Identical old inputs must retain every old identity.

## 2. Entry and Admission Table

The sole future execution entry is:

```python
execute_ts2_features(
    builds: tuple[VerifiedCanonicalBuild, ...],
    pit_result: PITAssemblyResult,
    feature_specs: tuple[FeatureSpec, ...],
    *, dataset_as_of: datetime | None,
) -> TS2FeatureExecutionResult
```

All arguments are explicit and in memory. Exact existing types are required,
not subclasses or duck-typed replacements. Reconstruct/validate typed
contents rather than accepting SHA-shaped assertions. No path overload,
loader, plan, settings, registry parameter, callbacks, schedule, LabelSpec,
Observation build or A3 result is an executor argument.

| Input | Exact admission | Failure |
| --- | --- | --- |
| Canonical builds | Exact `VerifiedCanonicalBuild` tuple, source `10.9-mv-ts2`, Canonical `market-bars-canonical-schema-v1` | `SOURCE_COHORT` / `CANONICAL_AUTHORITY` |
| Scope | `US.` instruments; interval exactly `1m`, `5m`, `15m`, `30m`, or `60m`; requested and actual session `RTH`; adjustment `NONE` | `SCOPE` |
| Legacy/mixed schema | `10.9`, mixed TS2/legacy and unknown schema rejected, including unused supplied builds | `SOURCE_COHORT` |
| Feature PIT | Exact feature-only PIT v1; every request has `label_window=None`, every Label selected-row tuple empty | `PIT_AUTHORITY` |
| Archive cutoff | Explicit null or aware UTC-microsecond datetime; every sample's `dataset_as_of` equals this value | `CLOCK_AUTHORITY` |
| FeatureSpec | Existing `market-vault-feature-spec-v1`; fixed FEATURE kind, existing canonical normalization | `SPEC_CONTRACT` |
| Requirements | Exactly `canonical_schema_versions=("market-bars-canonical-schema-v1",)` and `source_schema_versions=("10.9-mv-ts2",)` | `SOURCE_COHORT` |
| Output | Name equals spec name, `float64`, `nullable=false` | `SPEC_CONTRACT` |
| Transform and inputs | Exact reference and exact ordered fields in section 3; no alias/discovery | `REGISTRY_AUTHORITY` / `SPEC_CONTRACT` |
| Parameters | Exact declared set; actual int, not bool/float, bounded signed int64; no defaults/coercion | `SPEC_CONTRACT` |
| Duplicate semantic input | Duplicate build ID, duplicate normalized feature name (even another version), duplicate pin, conflicting evidence rejected | `DUPLICATE_INPUT` / `CANONICAL_CONFLICT` |

Two identical rows in different admitted Canonical builds may reconcile;
two supplied Canonical objects with the same build ID are duplicate input.
This is the frozen Canonical rule, not a new restriction on A3 Observation
physical proofs. A3 same-logical-build/distinct-complete-BuildPin semantics
remain unchanged.

Empty build/spec tuples are legal only with the exact PIT evidence closure.
No sample can resolve a selected version from an absent build. No implicit
default build or spec is inserted. Input tuple order is not authority.

## 3. Closed Registry and Formula Catalog

```text
TS2_FEATURE_REGISTRY_CONTRACT_VERSION=ts2-feature-registry-v1
TS2_FEATURE_EXECUTION_CONTRACT_VERSION=ts2-feature-execution-v1
TS2_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION=ts2-feature-transform-call-v1
TS2_FEATURE_IMPLEMENTATION_FINGERPRINT_VERSION=ts2-feature-implementation-v1
```

Exactly eight new immutable registrations, sorted by exact `transform_ref`,
bind the existing pure functions. For short name `x` in this table, the
exact reference is `market_vault.dataset.feature_transforms.x:x` and the
callable is that already-loaded module's exact attribute `x`. These are
function references, not permission to call the old registry or executor.

| x | Ordered fields | Required N / parameters | Formula and domain |
| --- | --- | --- | --- |
| `simple_return` | `close` | `window_bars >= 2` | last/first - 1; first nonzero |
| `log_return` | `close` | `window_bars >= 2` | log(last/first); both endpoints and finite ratio strictly positive |
| `rolling_mean` | `close` | `window_bars >= 1` | `math.fsum(values)/N` |
| `rolling_std` | `close` | `window_bars >= 2` | population std: fsum mean, fsum squared deviations/N, sqrt; ddof=0 |
| `rolling_volume_mean` | `volume` | `window_bars >= 1` | `math.fsum(values)/N` |
| `volume_ratio` | `volume` | `window_bars >= 2` | last / mean of preceding N-1; preceding mean strictly positive |
| `candle_range` | `high,low` | fixed N=1; no parameters | high - low |
| `candle_body` | `open,close` | fixed N=1; no parameters | close - open |

Every parameterized registration has only `window_bars`, nonnullable int64,
upper bound `9223372036854775807`; lower bound is the table value. No
lookforward, TRADING_DAYS or MINUTES window exists here. N is a row count,
not N returns; N=2 return spans one bar interval. No rounding, rescaling,
clamping, imputation or adjustment is added. Arithmetic errors, non-finite
output and formula-domain errors fail the entire invocation, not EXCLUDED.

Reuse the exact sealed `dataset.feature_models.FeatureTransformInput`
transport: `(field_names, rows, parameters)` with immutable tuples, ordered
finite actual-float scalars, and existing `SpecParameter` records. Its old
transport contract `market-vault-feature-transform-call-v1` is unchanged.
The new call contract governs TS2 admission before this transport is created;
it does not reinterpret or extend the old input class. No paths, row objects,
clocks, builds, provider objects, labels or scheduling callbacks reach a
formula. Type conversion is forbidden, including int volume to float.

Every callable must be a plain module-level, synchronous non-generator
function, one positional argument, no defaults, closure, lambda, partial,
decorator dispatch or alternate callable. Output must be actual finite
float; int/bool are rejected. Normalize negative zero to positive zero.

Resolve only the eight fixed registrations. No caller registry, arbitrary
callback, dynamic import, eval, entrypoints, discovery, alias or fallback.
Preflight all eight even with zero samples/specs. Never construct the old
`TransformRegistry` to obtain TS2 pins; its fingerprint is a different authority.

## 4. Fingerprint and Source Read Boundary

Registry construction has the ONLY filesystem allowance in this Feature
pipeline: `inspect.getsource(module)` for the eight already-loaded, statically
registered formula modules in section 3, solely for implementation-content
fingerprints. Validate module identity and exact function attribute first.
Do not discover/import a module from a caller string. Reuse the sealed
`dataset.transform_models._normalize_source_text` normalization semantics:

1. CRLF and CR become LF; do not strip individual source lines.
2. Reject NUL, C0 except LF/tab, DEL and C1; reject empty normalized source.
3. Remove leading/trailing blank lines and leave exactly one trailing LF.
4. SHA256 the resulting UTF-8 source bytes. Do not NFC-normalize Python source.

Unavailable/uninspectable source or wrong callable binding fails closed;
no cached guessed hash, bytecode fallback or caller-supplied source hash.
Within an invocation take one source snapshot per registration and retain
it only in the private issuance context. No caller context injection.

Source path, mtime, cwd, environment, module installation root and file
metadata are NOT identity. Source code content is. A relocated installed
wheel with identical source must produce identical pins. The eight modules
are self-contained formula implementations at BASE; their sealed input
transport is bound by its contract version. No old source is changed here.

Using H from section 9, fingerprint is H(`ts2-feature-implementation-v1`, F).
F is this exact flat field set; no unknown fields or hidden display metadata:

```text
registry_contract_version = ts2-feature-registry-v1
execution_contract_version = ts2-feature-execution-v1
transform_call_contract_version = ts2-feature-transform-call-v1
input_transport_contract_version = market-vault-feature-transform-call-v1
transform_ref = section 3 exact reference
kind = FEATURE
implementation_version = v1
implementation_source_sha256 = normalized module source SHA256
canonical_schema_version = market-bars-canonical-schema-v1
source_schema_version = 10.9-mv-ts2
requested_session = RTH
adjustment = NONE
market = US
input_count = number of ordered input fields
input_0000, input_0001, ... = ordered field names (only existing indices)
output_arity = 1
output_logical_type = float64
output_nullable = false
parameter_count = 0 or 1
lookback_source = FIXED or PARAMETER
lookback_unit = BARS
lookback_value = 1 for FIXED; null for PARAMETER
lookback_parameter_name = null for FIXED; window_bars for PARAMETER
lookforward_source = NONE
boundary_policy = SAME_MARKET_CALENDAR_DATE
missing_policy = EXCLUDE_SAMPLE
```

Only when parameter_count=1, additionally include all and only:

```text
parameter_0000_name = window_bars
parameter_0000_value_type = int64
parameter_0000_nullable = false
parameter_0000_lower_bound = section 3 lower bound
parameter_0000_upper_bound = 9223372036854775807
```

An actual spec parameter VALUE belongs to the spec pin, not F. Use existing
`ImplementationPin(name=transform_ref, version="v1", content_sha256=fingerprint)`.
The record's ID remains H(`dataset-implementation`, exact pin record).
There is no pseudo pin or reuse of an old `transform-implementation-v1` pin.

All executor, evidence admission, identities and result assembly outside
this bounded registry construction perform ZERO filesystem access. No
artifact/spec/plan/manifest/settings/Catalog reads, directory scans, writes,
latest/current discovery, provider/network/OpenD or current-time authority.
Tests must allow only these inherited-style static source reads, not blanket
allow all reads or disable the required source check. Source acquisition
failure cannot be downgraded because no values would be calculated.

## 5. Canonical and Feature PIT Closure

Before any transform, validate the whole explicit input boundary, including
unused supplied rows/builds and every sample, not just a requested tail:

1. Reconstruct typed Canonical request/row/source records and all existing
   Canonical bar keys, row version IDs, content IDs, gap contents, build IDs,
   selected-version membership and source snapshot provenance. Verify
   status/count and exact request/row/schema scope. Preserve Canonical clock,
   market-date and builder invariants; paths are not logical authority.
2. Reconcile every supplied candidate BEFORE market/archive filtering.
   Same version with conflicting logical/provenance facts fails. Different
   versions for the same Canonical bar key with conflicting comparison
   records fail too; no latest build, timestamp, revision or order winner.
   Identical admitted rows retain ALL their backing build IDs.
3. Recompute PIT requests, `pit_sample_key`, bar `sample_version_id`, fixed
   association schema/content, selected-row union, association rows,
   build/source pins and gap references. Require exactly one expected
   CanonicalBuildPin per supplied build. Per-sample and invocation considered
   build sets must exactly equal the supplied builds. Missing/extra pins,
   duplicate sample keys or selected rows fail.
4. Re-resolve every selected version from that evidence. Feature positions
   must agree with strictly increasing unique event times and exact request
   scope/date. No Label positions, unknown side or unbound association row.
5. Verify selected rows' clocks under section 6. For every admitted spec,
   validate its declared input fields on ALL selected Feature rows as actual
   finite float64, before window insufficiency/exclusion is considered.
   Freeze a deep immutable snapshot of the verified Feature PIT and specs;
   never mutate caller data.

At BASE, the sealed pure validations in `cross_day._authority.admit_builds`,
`reconcile`, `admit_feature_pit`, `observation._pit_validation.admit_bar` and
`dataset.execution_provenance` provide this TS2/Feature-only admission path.
Future code may call those unchanged pure validators. They are not permission
to invoke Cross-Day Label assembly/execution or old Feature execution. All
listed invariants are mandatory even if helper composition changes internally
under a separately reviewed implementation. No PIT winner-selection rerun:
verification reconstructs claims from the SAME selected IDs, never calls
`assemble_pit` to replace them or selects new rows from the builds.

Verified input objects originate at existing readers outside this pipeline.
Their logical revalidation is not artifact I/O or a replacement reader.
Do not reopen their paths, infer missing facts, repair evidence or relax
validation after a failure. Gap references remain considered PIT evidence;
no synthetic bars or negative coverage proofs are manufactured.

## 6. Clocks, Windows and Exclusion

For each sample, T is exactly `request.feature_window_close`. A is the
explicit invocation `dataset_as_of`; null means no archive cutoff, never
"now". Every sample must carry the same A, including validation before any
transform. Normalize aware datetimes to UTC microseconds by the sealed
encoder/model rules; naive instants fail.

Every selected Feature row must satisfy:

```text
feature_window_start <= event_time < T
market_available_at <= T
A is null OR archive_available_at <= A
market_calendar_date == anchor_market_calendar_date
code / interval / adjustment / requested_session == request scope
```

Equality at market and archive cutoffs is admitted. A future-clock SELECTED
row is an authority failure, never silently filtered or warm-up EXCLUDED.
Unselected candidates can be future-clock rows but are still checked for
conflicts and build closure first. No schedule or future Label clock enters
Feature admission. Unlike L2 Label rows, Feature rows always obey market<=T.

After complete evidence admission, N is the section 3 count. Candidate rows
are the last min(N, count) selected Feature positions, in their existing
order. If count<N: EXCLUDED/INSUFFICIENT_ROWS. Otherwise require each adjacent
candidate event-time delta equals the exact interval. A gap gives
EXCLUDED/NON_CONTIGUOUS_ROWS. Never backtrack to an earlier contiguous window,
fill a gap, cross a date, resample or borrow Label rows. A date mismatch was
already a hard scope failure, not an exclusion escape hatch.

The last selected row need not end exactly at T. This v1 computes a trailing
selected-row Feature, not an assertion that no later unobserved row exists;
there is no added freshness threshold. An internal gap outside that trailing
window remains PIT provenance but does not invalidate an otherwise complete
tail. Existing PIT diagnostics are not a new completeness/winner algorithm.

RTH normal and qualified early-close data share TS2 Canonical authority.
Use the verified row instants/date and actual interval differences, not a
hard-coded 16:00 close or inferred calendar. No cross-day Feature window;
DST cannot make a Feature window borrow rows from another market date.

N is bounded signed int64. Compare N with the finite selected-row count
BEFORE slicing or arithmetic. Insufficient huge N returns the normal
exclusion without allocating N elements, iterating an N-sized range, or
calculating T-N*interval. All work is bounded by actual supplied input size.
Datetime/size arithmetic overflow fails; no implicit clipping. There is no
Feature horizon enumeration and no calendar acquisition.

COMPLETE: call exactly one registered formula exactly once with exactly N
candidate rows. Revalidate declared input fields as actual finite float64;
no numeric coercion. Record candidate and consumed versions identically.
EXCLUDED: zero calls, value=null, consumed versions=(); retain candidate
versions as examined provenance. Only the two exclusion reasons above exist.
Any malformed numeric input, wrong schema or formula-domain failure is a
hard error, not missing data. No PARTIAL and no removal of excluded samples.

## 7. Immutable Result Authority

Choose a sealed result pattern, NOT a public caller-authored aggregate:
`execute_ts2_features` is the sole issuer of `TS2FeatureExecutionResult` and
its nested `TS2FeatureSampleResult` / `TS2FeatureValueResult` objects. Direct
construction and dataclass replacement of an issued object must reject.
No public `from_unverified`, `skip_validation`, result import/deserialization,
caller registry, source hashes or implementation pins are authority inputs.
Identity helpers are pure calculators, not trusted-result factories.

The issuer's private, invocation-scoped context is created only after all
admission and fixed-registry checks. It is not returned or accepted from
callers. It binds exact normalized input closure, actual fixed registration
pins, calls and outcomes; it cannot issue a result for alternative values
or inputs. Result construction validates against this context and actual
fixed registrations, not mutually agreeing caller assertions. Formula
execution occurs once, not again in constructor validation. Untrusted
coordinated fake source/fingerprint/ImplementationPin/value pins must not
reach a trusted result. Python reflection/process-memory tampering is not
a serialization or supported construction API.

All collections are tuples and nested records immutable; no mutable dict,
list or caller alias survives. Unknown fields, bad types, NaN/Inf, unsafe
text, duplicate normalized names/pins, incorrect order/cardinality, wrong
status/reason/consumption, identity mismatch and wrong fixed pins fail.
Use finite actual float scalars and canonical UTC/NFC normalization.

Exact value record fields (IDs are derived read-only properties, not inputs):

```text
sample_key, bar_sample_version_id, feature_name
spec_pin: SpecPin, implementation_pin: ImplementationPin
feature_window_close, dataset_as_of
considered_canonical_build_ids: tuple[str, ...]
candidate_canonical_row_version_ids: tuple[str, ...]
consumed_canonical_row_version_ids: tuple[str, ...]
status: COMPLETE|EXCLUDED, value: float|null, reason_code: str|null
```

Exact sample record: `sample_key, bar_sample_version_id, values, status`.
Exactly one per Feature PIT sample, sorted by sample_key; values exactly one
per spec sorted by SpecPin ID. Status COMPLETE iff all values COMPLETE,
otherwise EXCLUDED. Zero values makes an existing sample COMPLETE.

Exact execution record:

```text
execution_contract_version, registry_contract_version
feature_association_content_id, feature_association_schema_id, dataset_as_of
considered_canonical_build_ids
feature_specs: tuple[FeatureSpec, ...]
feature_spec_pins: tuple[SpecPin, ...]
registry_implementation_pins: tuple[ImplementationPin, ...]
samples: tuple[TS2FeatureSampleResult, ...]
status: EMPTY|COMPLETE|EXCLUDED
```

Specs and spec pins are one-to-one, sorted by SpecPin ID. Registry pins are
ALL EIGHT fixed pins sorted by ImplementationPin ID, not just used transforms.
Multiple specs sharing one implementation do not duplicate that registry
pin. Execution is EMPTY iff no samples; otherwise COMPLETE iff all samples
COMPLETE, else EXCLUDED. Counts and section 9 IDs are derived properties.
No paths, current time, schedule, Label facts or A3 ID are fields.

Zero samples still validates all eight registrations/source fingerprints,
every supplied spec, complete build/PIT closure and explicit A. Unknown
transform fails with zero samples. Zero specs also validates registry and
PIT/evidence, retains every sample with zero values and invokes no formula.
When both are zero, execution is EMPTY and all provenance remains bound.

## 8. Failure Vocabulary and Atomic Return

Future public error: `TS2FeatureError` with stable `reason_code`. No partial
trusted result is returned after any failure. Fixed reasons:

| Reason | Boundary |
| --- | --- |
| `SOURCE_COHORT` | wrong Canonical/source schema, including spec requirement |
| `SCOPE` | unsupported instrument/interval/session/adjustment/date |
| `DUPLICATE_INPUT` | duplicate semantic build/spec/sample/pin input |
| `CANONICAL_AUTHORITY` | invalid typed Canonical provenance/content/ID/gap closure |
| `CANONICAL_CONFLICT` | conflicting candidates before any clock filtering |
| `PIT_AUTHORITY` | malformed/forged Feature PIT or pin/association/sample linkage |
| `CLOCK_AUTHORITY` | naive/invalid A/T, A mismatch or inadmissible selected row |
| `SPEC_CONTRACT` | wrong field order, output, parameters, bounds or spec type |
| `REGISTRY_AUTHORITY` | unknown ref, wrong static callable/metadata or injected authority |
| `SOURCE_FINGERPRINT` | fixed module source acquisition/normalization failure |
| `TRANSFORM_DOMAIN` | arithmetic/domain error from the exact callable |
| `TRANSFORM_OUTPUT` | non-float or non-finite output |
| `RESULT_AUTHORITY` | illegal result construction or mismatched issued facts |

Preflight order is input shape/spec normalization, full fixed registry and
spec compatibility, whole-build admission/conflict reconciliation, PIT and
clock closure, then all window plans, formula calls and sealed return.
Never call a formula before all samples' authority checks succeed.
For simultaneous authority failures in one category, examine canonical
sorted inputs, not caller order. Preserve causes when wrapping documented
validation/source/ArithmeticError failures; do not use `except Exception`
or conceal programming errors. Exclusion reasons are value outcomes, not
this authority-failure vocabulary.

## 9. Exact Identity Encoding and Payloads

H(domain, fields) is exactly the existing
`market_vault.dataset.encoding.encode_identity` at BASE, encoding version v1.
Keys are sorted; scalar tags distinguish null/bool/int/float/text/date/time;
strings NFC, float binary64 big-endian hex, -0.0 normalized, aware time UTC
microseconds. The encoded preimage is `v1|domain|` followed by sorted
`key:encode_scalar(value)` joined by U+001F. No JSON substitute or Python repr.
Reject unsafe text before encoding. Every field set below is exact.

S(domain, members) = H(domain, `{count: len(members), members: concat(members)}`).
Members are validated 64-character lowercase hex digests; concatenation has
unambiguous fixed width. Empty means count=0 and members="". Sort only where
specified; ordered row/value/sample sequences cannot be arbitrarily sorted
by their resulting hash. Reject duplicate semantic input before forming sets.

Existing spec content IDs use `feature_label_spec_content_id` unchanged.
Existing `feature_label_spec_pin(spec)` yields the existing SpecPin; its ID
is H(`dataset-spec`, `{kind,name,version,content_sha256}`). Existing
ImplementationPin ID is H(`dataset-implementation`, `{name,version,content_sha256}`).
Do not create a TS2 FeatureSpec schema or change old spec hashing.

The TEN new digest domains and uses are:

| Domain | Exact payload or members |
| --- | --- |
| `ts2-feature-implementation-v1` | F in section 4 |
| `ts2-feature-considered-builds-v1` | S of sorted unique complete supplied Canonical build IDs |
| `ts2-feature-input-rows-v1` | S of row version IDs in selected/candidate/consumed position order |
| `ts2-feature-spec-pins-v1` | S of all spec pin IDs, sorted by pin ID |
| `ts2-feature-implementation-pins-v1` | S of all eight actual registry pin IDs, sorted by pin ID |
| `ts2-feature-value-v1` | V below |
| `ts2-feature-values-v1` | S of value IDs ordered by (sample_key, spec_pin_id) |
| `ts2-feature-sample-v1` | Q below |
| `ts2-feature-samples-v1` | S of sample IDs ordered by sample_key |
| `ts2-feature-execution-v1` | E below |

V has exactly:

```text
execution_contract_version
sample_key, bar_sample_version_id, feature_name
feature_spec_pin_id, implementation_pin_id
feature_window_close, dataset_as_of
considered_canonical_build_ids_digest
candidate_row_version_ids_digest, consumed_row_version_ids_digest
status, value, reason_code
```

The two row digests use the same ordered-row domain but distinct named
payload roles. EXCLUDED consumed digest is the actual empty sequence digest,
not null; COMPLETE consumption exactly equals candidates. Q is exactly:

```text
sample_key, bar_sample_version_id, status, values_content_id
```

Q's values_content_id contains just that sample's values. Execution's
values_content_id contains ALL values, including EXCLUDED. E is exactly:

```text
execution_contract_version, registry_contract_version
feature_association_content_id, feature_association_schema_id, dataset_as_of
considered_canonical_build_ids_digest
feature_spec_pins_digest, registry_implementation_pins_digest
sample_count, feature_count, status
values_content_id, samples_content_id
```

The Feature association IDs are the verified upstream PIT v1 values.
Build IDs bind complete Canonical content/provenance even if row-version IDs
alone would not encode numerical payloads. No hash substitutes for admission.
Additional considered Feature evidence changes V/E even if numerical value
is unchanged; it must first be consistently represented in the supplied PIT.
Unused registry source changes alter the full registry digest/E but not an
unaffected transform's V. This full-catalog empty-case binding is deliberate.

There is no new bar sample ID, A3 ID, Cross-Day Label ID or Dataset ID here.

## 10. Offline Known-Answer Vectors

These are encoding/fingerprint known answers, not fake VerifiedCanonicalBuild
objects to admit at runtime. Opaque upstream IDs below are synthetic digest
inputs ONLY to pure identity helpers. Real runtime canaries must obtain them
from verified builds and actual Feature-only PIT. Copy these literal expected
hashes into future tests; never compute expected values using the code under
test. Existing L1/L2 expected values are not regenerated.

There are SIX vector groups, 49 literal digest assertions, covering every
new domain: (1) registry; (2) spec/sequence primitives; (3) COMPLETE;
(4) EXCLUDED; (5) zero samples; (6) zero specs. Eight raw source hash checks
are included in the 49. Source comes from the exact BASE formula modules
and section 4 normalization. Remaining scalar inputs are entirely specified
below, so the vectors are independently reproducible with the existing encoder.

### 10.1 Registry

For each of the eight section 3 registrations construct F literally as
section 4 specifies, with these source hashes. Hash F, then its exact
ImplementationPin record. Source names below are section 3 short names.

```text
candle_body.source_sha256=818beb25bcae1773e64d27ddc9d53d4e7926d43ffc5a6477191602e02aea22ca
candle_body.fingerprint=f7052b2e5cb8b2698e95e0a7fc3535635c39a2f292423122ea3ad9d1fde565f8
candle_body.implementation_pin_id=4a9b5e89687fcac6edbbd02e87912c85c64799836af3010ad9297332012217dd
candle_range.source_sha256=dd9811e764ca4a8b5a2d82335dbcaa88ed6c7a9f4a498544ba63104f49dbf4b0
candle_range.fingerprint=fd85a80f628d7ecec2f396644c29d48094f3e3cec2375afc1706b94371f466a8
candle_range.implementation_pin_id=5b85ed91231955b7f0b5ecaa9f3d584210c9e28cd36d2dff0ae19ef3d0a0b687
log_return.source_sha256=4a1d6e4295ad33824020259c4653b74b087176ee5f40d2097f2a1aae7532e3fa
log_return.fingerprint=3fbdad819ee7d51a995474c94aba16e2333e611778b794c5246885fed66b69f2
log_return.implementation_pin_id=f938e63f485766459c6b378da97615fdbe5913b8f59cfe5ab734b39b55b0b60f
rolling_mean.source_sha256=97ee08de1d84e66bf362cd85c6f21aa15b09e5a2289fb5918476eb90bae8633f
rolling_mean.fingerprint=b1eafd9fd110ab5307bec4d6940a0c16a1eb21c108c38c5eb10c718b61bfafbc
rolling_mean.implementation_pin_id=f14cef9547f49b28a0b66b7ed41e82454cb7bfb43ad433681f641e02c0d4fb08
rolling_std.source_sha256=c5b1b4cd5d4a4eff35f3b05b754e41e9ac68968df47bb4f3af03fe711e41d830
rolling_std.fingerprint=1fa2edafb36ed62c1ed74567f7bfed87a60f46d3dc4bac7b8d98f5d35c584822
rolling_std.implementation_pin_id=bfcf14f5814a4efabc5737132413a0fb61194ada32720417cf23f48b8b680145
rolling_volume_mean.source_sha256=617bdd2685cf7485f89336241a2a3b4e6818c006c051ce775b8b6a607c1e81af
rolling_volume_mean.fingerprint=46ece8f194e40253f2ee527837b4c9be04c6791be5ae34507cf36397aeb14fa0
rolling_volume_mean.implementation_pin_id=d053c4ae596074cafb41ee53d7743712758fbbee3e232af09ffeb7f124c45491
simple_return.source_sha256=41345d65d910b01012a909b136dfb8681e33feb55d6b663628e301d3f0bcce32
simple_return.fingerprint=984589ae4cfe3471d72e1cf0438105dcd29360979ef89eb062a3d5c177c1c70e
simple_return.implementation_pin_id=55d3885db5b6eccdea45f2ad0baa41d170884c63bcb1bdf2f5bdd9f24f763782
volume_ratio.source_sha256=3a10650c63f2acf64912ad6bd2959ec0ba14f84f09cbfaa40f023f84e74ac919
volume_ratio.fingerprint=9dbad62831815638ba82d51608c9efc99b6131332c1b1c03d3670c2108c0da46
volume_ratio.implementation_pin_id=435f28696559ca2204997e76260403228a65cf6c150109bcf04afab6d5281d3b
```

### 10.2 Spec and Sequences

Exact FeatureSpec: schema=`market-vault-feature-spec-v1`, name=`ts2_return`,
version=`v1`, output=`DatasetField("ts2_return","float64",false)`,
input_canonical_fields=("close",), transform_ref is section 3 simple_return,
parameters=(SpecParameter("window_bars",2),), requirements are exactly the
section 2 canonical and TS2 tuples. Kind is derived FEATURE. Use existing
spec content/pin algorithms, then section 9 sequences.

For notation only, B1="1" repeated 64 times, B2="2" repeated 64 times;
R1="3" repeated 64 times, R2="4" repeated 64 times. Considered sequence
is (B1,B2); input sequence is (R1,R2). Spec sequence contains the one spec
pin; registry sequence contains all eight pin IDs, sorted, from 10.1.

```text
spec_content_id=73dc26da80653a4959ff8a8f733cda416235f19e404fc6f995327d94fa387a40
spec_pin_id=908e88052dabd17e6efd045a1e8af5ebe4f5b97560fb7bbb193918ac3c0ee600
spec_pins_digest=b57a6f8a51d1e65780d44a980bfb7f86262a85b6dae6cbff9895cc80af95356c
registry_pins_digest=2f59d9a2d8b01316f46d97ad084b924ae6b97fbee40506c114c31b982f2fbd5f
considered_builds_digest=ee9387846c20f93cb412b1ad8a6bf586f15dbe721eac2847407581a180d501ec
input_rows_digest=e74426c75d468d6b851c6099950e4f284b09397b7bab9af11b80f284e63f4965
empty.ts2-feature-considered-builds-v1=a208644d37cfbf0cfd3afd066ea2cbe6a2c93b4be8167bdbd725a2e3ed3a4340
empty.ts2-feature-input-rows-v1=8fd862f5fd4d753d0fc7ffb490f799f0d3232e31f91f8fde2e8c17575975d3da
empty.ts2-feature-spec-pins-v1=c2f913489fa2030d0e9ac6440e6c34ed3932f93bacdd7c0d9f2052d8b3caee0e
empty.ts2-feature-values-v1=14abd339a978e6be2dc75f032ac8aca36b70b90cc33d8258662fb15a680a9e7e
empty.ts2-feature-samples-v1=db9e774d9acf4aba198070e96acd55e85a5bf6bc76aea2bc9180128986d1b389
```

### 10.3 COMPLETE

All remaining cases use sample_key="5"*64, bar_sample_version_id="6"*64,
feature_association_content_id="7"*64, feature_association_schema_id="8"*64,
T=aware `2026-01-05T14:32:00+00:00`, A=aware `2026-01-06T22:00:00+00:00`.
Use UTC datetime values, not strings in H. Execution/registry versions are
section 3 constants. V uses the 10.2 spec pin, simple_return implementation
pin, feature_name=`ts2_return`, considered digest from 10.2, candidates and
consumed=(R1,R2), status=COMPLETE, actual float value=0.25, reason_code=null.
This formula value can be produced by closes 100.0,125.0. Q has this one
value, status COMPLETE. E has this one sample, one feature, status COMPLETE,
and the corresponding full values/samples digests and full registry digest.

```text
complete.value_id=73d10788fec5259e94b3494172b32cf716042d84f83f60415426c3e9d70f8e6f
complete.values_content_id=5fd7745f3d1699d2313753d26b8de05f4fee82f85ca4d090aa875bafb7713f43
complete.sample_id=b869236fbc5bae51803d1a6d6210d3c620e6b448d5536e0b15ea5abcfd06d9f2
complete.samples_content_id=3c0060e325ebf0cbfe4edb7f3d95b206838c0cc946ef5fed66019259a430809b
complete.execution_id=b29d49174d4ebcac5ead385dc94e98c3400066b90f24928889a3d7d8b3af798e
```

### 10.4 EXCLUDED

Use 10.3 inputs except candidates=(R1,), consumed=(), V value=null,
reason_code=INSUFFICIENT_ROWS; V/Q/E status=EXCLUDED. Recompute every dependent
digest; sample_count=1 and feature_count=1 remain. One candidate cannot meet
window_bars=2. No formula executes.

```text
excluded.value_id=070b2c1665a469a2c454d8fac2e837246fb543c1e32df9c9c60ff76df4de9823
excluded.values_content_id=a8207e7a3eb557a17c7ea0103b47dee7f2715e808e17d13a3a9625a3edaf01d5
excluded.sample_id=c868cae29df9b5c94e013475ef93cabf15ab878c8d61eeace9dc4d45f19288db
excluded.samples_content_id=04cd1c4a69a663781c23db5925d3c5e397e31192e073340a78e2594d252310ae
excluded.execution_id=afb4da567c49a0ff073b8901952c8e4d8ec33efcd87b828886c636fb57333ef9
```

### 10.5 Zero Samples

E uses 10.3 context and one spec, but sample_count=0, status=EMPTY,
values_content_id=empty values digest and samples_content_id=empty samples
digest. Considered builds, explicit A, spec and registry digests remain.
These synthetic association IDs are opaque identity-helper inputs, not a
claim that an actual empty PIT can reuse a nonempty PIT's content ID.

```text
zero_samples.execution_id=eedfdac0687b129851023361fad9fdc8e8add3d0851fe25df6f98f9b78f4077c
```

### 10.6 Zero Specs

Use 10.3 one sample with zero values and status COMPLETE. Q uses the empty
values digest. E has feature_count=0, empty spec-pins and values digests,
that Q in its sample digest, sample_count=1, status COMPLETE. Preserve other
10.3 context, including all eight registry pins.

```text
zero_specs.sample_id=fa873cbb61d1ac0d277dc84a325aa67547bae4d74e758a379613c15239963d9a
zero_specs.samples_content_id=5d2595b6454d0e2f228b999c4229c0827934fafefcf5247d7a43a9928ea893e2
zero_specs.execution_id=437f0a8f954bc13bee9f756ea960dc6e2c3654b315f16c72b0586eae2698ec2e
```

## 11. A3, L2 and Future Dataset Integration

This Feature executor accepts only Feature PIT, verified Canonical builds
and specs. It neither consumes nor generates an optional A3 identity.
Existing A3 and L2 may independently share the EXACT SAME Feature-only PIT.
Future Dataset integration must verify equal Feature association schema and
content and exact sample-key/bar-sample-version sets across all supplied
results before joining. It must not rerun Feature PIT, A3 selection or L2
assembly to paper over a mismatch.

If A3 is supplied, future integration requires its sealed independently
verified `ObservationPITAssemblyResult`, exact sample correspondence and
existing A3 identity closure. COPY its `multi_source_sample_version_id`;
never derive one from this Feature result, schedule, Label outcome or Dataset
facts. L2 must carry that SAME optional A3 value or null for bar-only usage.
Missing/extra/conflicting optional A3 links fail, not silently downgraded to
null. This join requirement is not a new A3 verifier implementation here.

Schedule-only/Label-only changes, holding the Feature input boundary fixed,
cannot change any TS2 Feature identity or upstream PIT/A3 identity. They may
change L2 association/values as designed. Observation-only evidence changes
may change A3 but cannot change these bar Feature values/identities. L2's
market clock (no market<=T label cutoff), actual_label_end_time, backing vs
considered domains, schedule completeness and all 53 literals stay sealed.

Future separately reviewed Cross-Day Dataset identity must bind this exact
TS2 execution contract, execution_id, values_content_id, spec pins and real
registry implementation pins, along with the unchanged upstream identities,
L2 and Observation facts required by L1 section 11. It must retain excluded
sample provenance even when matrix admission excludes a Feature sample.
No new Dataset ID payload, completion/split algorithm, generator, matrix,
manifest, reader or orchestration is designed or implemented by this PR.
Do not shoehorn this result into A4's old Feature result or Dataset cohort.

## 12. Future Semantic Canaries

These 48 obligations are design-only, NOT claims of implemented tests.
They add to, not replace or reclassify, the existing 66 L1/L2 canaries.

1. New authority rejects legacy 10.9, including a zero-sample invocation.
2. Real verified TS2 RTH/NONE builds and Feature-only PIT execute successfully.
3. Old Feature registry stays exactly 10.9-only and rejects TS2 requirements.
4. All old Feature/BARS Label pin and identity vectors remain unchanged.
5. Instrumented old Feature/Label executors and registries are never invoked.
6. Mixed/unknown schemas, adjusted bars, non-US or non-RTH scopes fail.
7. Selected market_available_at>T fails before transform; equality passes.
8. Selected archive_available_at>A fails; equality passes; null A uses no clock.
9. Naive A/T and mismatched PIT/sample A fail, including empty-case context.
10. Conflict before clocks: a conflicting archive-future candidate still fails.
11. Same-version content/provenance conflict and conflicting same-key versions fail.
12. Identical cross-build rows retain all backing builds; duplicate build input fails.
13. Missing/extra Canonical pins, source pins, selected membership or association rows fail.
14. Sample/request/bar-version/association ID tampering fails without PIT reselection.
15. Input build/spec order changes neither values nor identities nor result ordering.
16. Relocation changes no ID and causes no artifact path access.
17. Registry has exactly eight immutable entries; unknown refs and callbacks fail.
18. Missing/uninspectable source or mismatched module attribute fails closed.
19. Source CRLF/LF and outer blank lines normalize equally; actual code change changes pin.
20. Source path/mtime/cwd never enters fingerprint or execution identity.
21. Joint fake source hash, fingerprint, pin and value cannot construct an issued result.
22. Direct aggregate/nested construction, dataclass replacement and bypass flags are rejected.
23. Deep immutability prevents caller mutation/aliasing after issuance.
24. Exact input field order/output/parameter contract; wrong/duplicate names fail.
25. Bool/int/float coercion, NaN/Inf, malformed volume and non-float output fail.
26. Huge valid window count excludes in bounded work; out-of-int64/overflow fails.
27. Insufficient rows excludes, records candidates, consumes none and invokes no formula.
28. Noncontiguous tail excludes; no older-window substitution or gap filling.
29. Gap outside valid tail remains evidence without excluding that tail.
30. Cross-date selected row fails; DST never crosses the anchor date.
31. TS2 qualified early-close rows work without schedule/provider or nominal-close inference.
32. Exactly N trailing selected positions, one formula call per COMPLETE value.
33. Return/log/volume-ratio domain errors fail; rolling std uses population ddof=0.
34. All eight actual formulas agree with frozen pure functions; -0.0 normalizes.
35. Zero samples still verifies all registry/spec/source/PIT evidence; unknown ref fails.
36. Zero specs retains each sample COMPLETE, full registry pins and no transform calls.
37. Both zero returns deterministic EMPTY with real empty digests, no fabricated pins.
38. COMPLETE and EXCLUDED values both participate in values/sample/execution IDs.
39. Extra considered evidence changes context identities only after exact PIT re-binding.
40. All 49 literal assertions in section 10 match; no runtime expected-hash generation.
41. Optional A3 binding remains bit-identical under schedule/Label-only mutation.
42. TS2 Feature identity is unchanged by schedule/Label and Observation-only mutations.
43. Future join rejects mismatched PIT/A3/L2 sample/version sets; no replacement identity.
44. Fixed registry source change alters implementation/result identity, including empty cases.
45. I/O canary observes only eight authorized source acquisitions, zero artifact/spec/plan/settings/directory reads or writes.
46. No current-time/env/network/provider/OpenD authority or callable side channel.
47. Old A1-A4, L2 optional binding, 53 digest assertions and 66 canaries remain unchanged.
48. No Dataset/generator/materialization/reader/Catalog/CLI/L4 implementation or destructive surface is introduced.

## 13. Phase Locks and Review Evidence

```text
KNOWN_ANSWER_VECTOR_COUNT=6
KNOWN_ANSWER_DIGEST_ASSERTION_COUNT=49
DESIGN_CANARY_COUNT=48
L3_TS2_FEATURE_AUTHORITY_PRECONDITION=true
OLD_FEATURE_REGISTRY_CHANGED=false
OLD_FEATURE_EXECUTOR_CHANGED=false
OLD_FEATURE_PINS_CHANGED=false
PIT_V1_CHANGED=false
A3_CHANGED=false
A4_CHANGED=false
L2_CHANGED=false
NEW_DESTRUCTIVE_SURFACE_COUNT=0
L3_IMPLEMENTATION_STARTED=false
L3_IMPLEMENTATION_AUTHORIZED=false
L4_IMPLEMENTATION_STARTED=false
L4_IMPLEMENTATION_AUTHORIZED=false
PROVIDER_IMPLEMENTATION_AUTHORIZED=false
CATALOG_INTEGRATION_AUTHORIZED=false
CLI_INTEGRATION_AUTHORIZED=false
PRODUCTION_OPERATION_AUTHORIZED=false
OPEND_AUTHORIZED=false
NETWORK_PROVIDER_CALL_AUTHORIZED=false
MERGE_AUTHORIZED=false
```

Design validation: diff check, repository hygiene, release checker,
destructive repository gate and current document/governance regressions.
Expected destructive baseline remains contracts=5, exemptions=16, surfaces=42.
Only this document changes. Existing tests, contracts, checker, exemptions,
CI control plane, version and sealed release assets remain untouched.

All one-off vector calculations/temp/cache/log output are D:-bound outside
the repository. Natural exact-head PR CI is required; do not force its tier.
Design review approval, merge authorization, Feature runtime implementation
authorization and future Cross-Day Dataset authorization are separate gates.
Stop after this PR for independent TS2 Feature-authority semantic review.
