# Cross-Day Immutable Schedule Artifact and Provider Authority V1

## 1. Status, Base and Decision

DESIGN / PREFLIGHT ONLY. This document proposes physical evidence and reader
contracts; it implements nothing and does not qualify a provider, signer,
acquisition service, publication primitive or platform. Independent semantic
review and a separate implementation work order are required.

```text
BASE_MAIN_SHA=fff087205aeba554c17a308257b5c0057a3dcbbc
BASE_MAIN_TREE=1426642faa9b59ced7697acb22a4b53f2e768d44
PACKAGE_VERSION=0.8.0
L4_MOOMOO_ONLY_AUTHORITY=REJECTED
MOOMOO_ALONE_SUFFICIENT_FOR_CROSS_DAY_COVERAGE_COMPLETE=false
L4_V1_PROVIDER_MODEL=PROVIDER_QUALIFICATION_DEFERRED
L4_RUNTIME_IMPLEMENTATION_AUTHORIZED=false
L4_PROVIDER_PRODUCTION_QUALIFICATION_AUTHORIZED=false
MERGE_AUTHORIZED=false
```

The architectural interfaces below are fixed for review. Production source
profiles and custody/verification signing authorities are deliberately NOT
admitted. Until separately qualified, even a byte-consistent artifact must fail
with SOURCE_CONTRACT_UNQUALIFIED or EVIDENCE_AUTHORITY_UNQUALIFIED. A complete
design is not a claim that the missing calendar evidence exists.

This PR adds this document only. No source, tests, scripts, CI, version,
destructive registry or existing design is changed. Existing historical
L1/L2/L3 review outcomes and failures remain intact.

## 2. Unchanged Logical and Operational Boundaries

Normative existing authorities are [Cross-Day Label V1](cross_day_trading_days_label_v1.md),
[Cross-Day Dataset V1](multi_source_cross_day_dataset_v1.md),
`src/market_vault/cross_day/schedule.py` and
`src/market_vault/cross_day/identity.py` at the base above.

Preserve VerifiedTradingDaySchedule, TradingDayRecord, TradingDaySchedulePin,
schedule_content_id, schedule_pin_id, Label association/value identities and
L3 Dataset ID without modification. L3's five identity domains, 49-field root,
98 fixed digest assertions, artifact layout, reader, writer and two exact
production capability tuples do not change. L4 adds no logical model field.

The existing verify_trading_day_schedule validates a logical declaration,
including digest-shaped references. It explicitly does not authenticate
physical provider evidence. L4 verifies that evidence BEFORE calling it;
L4 must not make L2's pure logical validator acquire or reopen anything.
Existing synthetic logical test schedules stay valid test fixtures, not
production source qualifications.

```text
MoomooCalendarCollector = ACQUISITION_ONLY
normalize_trading_calendar = CURATED_OPERATIONAL_NORMALIZATION_ONLY
trading_calendar_latest = NOT_CROSS_DAY_AUTHORITY
DuckDB current state = NOT_CROSS_DAY_AUTHORITY
DatasetRunManifest = NOT_SCHEDULE_AUTHORITY
```

The current collector converts SDK results to a DataFrame. The operational
normalizer reduces columns and drops duplicate keys with keep-last behavior.
The service records an operational capture timestamp before acquisition and
updates Raw/Curated/Catalog state. These are facts about the existing path,
not L4 evidence rules. Do not repurpose, modify or migrate that v0.3 path.
Do not import its deduplication, capture-clock or latest-view semantics.

Cross-Day assembly, execution, the L3 join and the request generator continue
accepting an explicitly supplied schedule object. They never call OpenD or
Moomoo, query DuckDB/trading_calendar_latest, scan artifact directories, select
latest, or infer from current time. Acquisition precedes offline consumption.

## 3. Provider Limitation and Model Comparison

The official [Moomoo request_trading_days reference](https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-trading-days.html)
was checked on 2026-09-20. It says weekends and holidays are removed, but
"temporary market closed data is not excluded". It also documents date-range
defaults and code taking precedence over market. V1 therefore requires explicit
market US, explicit start/end and no code; neither implicit range nor current
date defaults are permitted. A documentation version label is not a pinned
source contract or operational qualification.

An absent response row is not automatically a negative CLOSED declaration.
A returned row is not automatically TRADING when emergency-closure coverage
is unproven. The algorithm returned=TRADING, missing=CLOSED, complete=true is
forbidden. A response hash cannot repair this epistemic gap.

| Model | Required authority | V1 decision |
| --- | --- | --- |
| A: Moomoo-only | Independently qualified proof that the endpoint covers temporary closures, explicit negative dates and session exceptions, contrary to the current documented limitation | Rejected; no such evidence established |
| B: Moomoo plus separate authority | Authenticated, complete date-status/closure ledger with a finalization boundary, explicit negative assertions, and qualified special-session declarations for the same market/session/scope | Possible future qualification; none admitted here |
| C: independently sealed calendar source | A qualified source that supplies all civil-date statuses, complete emergency/special-session coverage and authenticated possession/verification evidence | Possible future qualification; Moomoo is unnecessary for logical authority |

The selected result is PROVIDER_QUALIFICATION_DEFERRED, not an implicit choice
of a named exchange feed. Public holiday pages, a news search, a library's
calendar, or an undocumented no-results response are not substitutes for a
complete emergency-closure authority. Model B would need a separately reviewed
precedence policy to use a closure source to override a Moomoo returned date;
this V1 proposal instead fails on contradictions. Model C must not quietly
ignore an inconsistent Moomoo snapshot that is included in its evidence set.

## 4. Evidence Chain and Trust Boundary

```text
explicit provider/source acquisition
  -> immutable source snapshot
  -> qualified source-contract verification
  -> per-civil-date coverage-completion evidence
  -> existing qualified session geometry
  -> independently sealed schedule artifact
  -> strict offline artifact reader
  -> existing VerifiedTradingDaySchedule
  -> explicit L2/L3 consumers
```

Every transition needs evidence:

| Transition | Required proof, not a flag |
| --- | --- |
| Acquisition to snapshot | Exact request/response bytes, request-response binding, source identity, authenticated custody receipt, bounded acquisition time |
| Snapshot to parsed authority | Recomputed content/record/bundle IDs, qualified source profile and exact parser version, authenticated origin and receipt signatures |
| Parsed authority to coverage | One justified status per civil date; explicit closure-ledger completeness through the interval, conflict checks and finalization evidence |
| Coverage to geometry | Parsed positive session evidence consistent with the unchanged calendar contract and qualified early dates |
| Verified facts to artifact | Complete verification receipt, unchanged logical validation, closed canonical files, recomputed IDs and physical integrity |
| Artifact to logical schedule | Strict read-only byte/evidence verification and existing logical validators; no caller trust IDs |
| Schedule to L2/L3 | Existing explicit object admission, coverage/geometry/archive gates and schedule pin binding |

Future source profiles must be independently reviewed, immutable reader-owned
contracts, not caller callbacks, config files, Catalog entries or fields in an
artifact that authorize themselves. Each qualified profile must pin: source
identity and exact origin, contract/version, API/schema, request scope mapping,
wire parser and canonical claim order, source authentication method, allowed
signer/key identities, claim meanings, negative-evidence semantics, completeness
and finalization semantics, geometry mapping, clock guarantees and size limits.

This document admits ZERO such profiles or keys. A future runtime cannot
discover-and-trust a contract, self-signed key or SHA-shaped ID from the input.
Any new profile, signer enrollment, revocation handling or provider enum map
requires independent qualification before production admission. No live key
fetch or mutable trust database is allowed in the offline reader.

Custody signatures prove who captured which bytes and when under a qualified
clock/origin policy; they do not prove the calendar claims are true or complete.
Completion verification still needs the actual source declarations below.

## 5. Canonical Physical Encoding and Identity Rules

All JSON files below use C(x): UTF-8 without BOM, sort_keys=True, separators
(',', ':'), ensure_ascii=True, allow_nan=False, and exactly one final LF.
Objects have exactly their listed fields; no optional/unknown keys. Strings
must already be NFC. Dates are YYYY-MM-DD; instants are aware UTC encoded as
YYYY-MM-DDTHH:MM:SS.ffffff+00:00. No implicit conversion, naive timestamp,
sub-microsecond text, float, NaN, infinity, duplicate JSON key or noncanonical
JSON bytes is accepted. Integers are exact integers, never bool; booleans are
exact booleans. Structured text rejects control characters and unsafe text.
Raw payloads use canonical RFC 4648 base64 with padding and no whitespace;
decode/re-encode equality is mandatory, so raw source bytes are not normalized.

Let SHA(b) be lowercase SHA256 hex of exact bytes. Define the L4-only wrapper:

```text
H(domain, payload) = existing dataset.encoding.encode_identity(
    domain, {"canonical_payload_sha256": SHA(C(payload))})
```

This uses the existing scalar identity encoder unchanged. Freeze four new
L4 physical/evidence domains, distinct from every L1/L2/L3 domain:

```text
l4-trading-day-source-record-v1
l4-trading-day-source-snapshot-v1
l4-trading-day-coverage-completion-v1
l4-trading-day-schedule-artifact-v1
```

No filename, absolute path, cwd, mtime, Catalog row ID, directory enumeration
order or read time enters these IDs. Relative member names have fixed artifact
roles, not caller-selected locations. Reacquisition with a different signed
acquisition time is a different snapshot even if response bytes match. Merely
relocating identical source/evidence bytes changes none of these IDs.

These evidence IDs fill only existing schedule reference fields. The new
schedule_artifact_id, manifest hash, file-object IDs and physical file hashes
do NOT enter existing logical schedule or Dataset payloads. Unchanged complete
logical schedules retain identical schedule_content_id, schedule_pin_id, L2
identities and L3 Dataset IDs. Changing an existing source/evidence reference
or archive clock legitimately changes the already-frozen logical identity.

## 6. Immutable Source Snapshot: Exact Evidence, Not Supplied Hashes

Freeze source_snapshot.json as this closed envelope:

```text
schema_version = l4-trading-day-source-snapshot-v1
source_snapshot_id
source_content_hash
content
```

`content` has exactly: market, requested_session, market_timezone,
coverage_start_date, coverage_end_date, records. Scope is US/RTH/
America/New_York; coverage is finite, inclusive and non-reversed. `records` is
a nonempty array sorted by recomputed source_record_id, with no duplicate ID.
Each element is exactly `{source_record_id, evidence}`.

`evidence` has exactly these fields:

```text
provider_id
source_id
source_contract_id
source_contract_version
source_schema_version
api_contract_version
origin_locator
requested_market
requested_start_date
requested_end_date
requested_code
payload_format
request_bytes_base64
request_content_hash
response_bytes_base64
response_content_hash
acquired_at
custody_receipt
```

requested_market=US; requested_code=null; the explicit requested date range
equals this snapshot's coverage. origin_locator is the qualified origin/API
resource, not an artifact path or mutable discovery pointer. A profile must
prove how the request bytes correspond to these declared request fields; a
caller-written market/range label is insufficient. payload_format=WIRE_BYTES
in V1. The response is the complete exact response body, including original
order, duplicates and error envelope, not a selected DataFrame or a JSON
reconstruction that drops information. Error, truncation, unclosed pagination,
unmatched request, unsupported wire/schema or missing bytes cannot qualify.

If an acquisition boundary cannot retain the exact response and request
binding required by its source profile, reject it. A new SDK-typed capture
format needs separate design/qualification; do not silently turn the existing
collector's DataFrame into WIRE_BYTES. Credentials and authorization headers
are never included: retain the domain request/response bodies only; a source
whose domain payload necessarily exposes secrets is not admitted by this V1.

request_content_hash=SHA(decoded request_bytes_base64) and
response_content_hash=SHA(decoded response_bytes_base64). These values are
always recomputed. A successful HTTP/API status alone is not complete coverage.

`custody_receipt` is exactly `{body, signature_base64}`. `body` has exactly:
receipt_version=`l4-source-custody-receipt-v1`, custody_authority_id,
key_id, signature_algorithm=`Ed25519`, provider_id, source_id,
source_contract_id, source_contract_version, source_schema_version,
api_contract_version, origin_locator, requested_market, requested_start_date,
requested_end_date, requested_code, payload_format, request_content_hash,
response_content_hash, acquired_at. All duplicated fields must match evidence.
The signature is 64 decoded bytes over C(body), verified against a separately
qualified reader-owned public key and that key's scope. A supplied key_id is
only a lookup claim, not trust. The custody profile must prove authenticated
origin and bounded clock accuracy; signing an arbitrary caller payload fails
that profile. No custody signer is currently qualified.

acquired_at is the signed conservative upper bound for complete response
possession, not request start or one row's timestamp. If acquisition uncertainty
cannot be bounded conservatively, no snapshot may be admitted.

The identity construction is non-circular:

```text
source_record_id = H("l4-trading-day-source-record-v1", evidence)
source_content_hash = SHA(C(content))
source_snapshot_id = H("l4-trading-day-source-snapshot-v1", {
    "schema_version": "l4-trading-day-source-snapshot-v1",
    "source_content_hash": recomputed source_content_hash
})
```

source_content_hash covers the complete canonical bundle, including all exact
payload hashes/bytes, contract pins, scopes and authenticated acquisition facts;
it is not merely one provider's response hash. Changing any source byte changes
its recomputed record, bundle and artifact IDs, or makes parsing/authentication
fail before admission. The source_snapshot_id cannot be supplied independently
of those bytes. Reader must reject a coordinated rewrite with recalculated
hashes when custody signatures or source-contract verification fail.

Duplicate acquisitions for the same source/contract/request in one bundle are
rejected even if bytes agree or acquisition times differ. No silent deduplication
or latest-wins. Different qualified sources may corroborate but cannot conflict.
The producer selects one explicit immutable bundle before verification; the
reader never searches neighboring snapshots for a preferred answer.

## 7. Coverage Completion and Session Evidence

coverage_evidence.json is exactly:

```text
schema_version = l4-trading-day-coverage-evidence-v1
coverage_completion_evidence_id
content
```

`content` has exactly: market, requested_session, market_timezone,
coverage_start_date, coverage_end_date, source_snapshot_id,
completion_rule_version=`l4-explicit-civil-date-completion-v1`,
calendar_contract_version=`cross-day-us-rth-calendar-contract-v1`,
closure_finalized_through, closure_knowledge_cutoff, completeness_claims,
daily_evidence.

All scope fields equal source content. closure_finalized_through is an explicit
source-proven civil date at least coverage_end_date, NOT an invented date.
closure_knowledge_cutoff is the explicit authority's knowledge instant for a
complete emergency/temporary-closure ledger. The authority must positively
attest that the range is settled through that date as of that cutoff. V1 cannot
claim complete future trading outcomes from a merely prospective holiday list.
The cutoff cannot postdate possession of the source declaration asserting it:
require closure_knowledge_cutoff <= acquired_at for every completeness claim's
source record. A future-dated self-assertion is not observed completeness.
This is evidence-relative historical completeness, not a promise that no later
correction can ever exist. Corrections require a different explicit artifact;
they do not select or mutate an earlier one.

A claim reference is exactly `{source_record_id, claim_index}`: recomputed
record ID and exact nonnegative integer index into the canonical claim sequence
produced by its qualified source parser. Reference arrays sort by that pair,
are nonempty where required, and reject duplicate pairs. Distinct proof sources
are retained, never collapsed. Index validity, claim meaning, source scope,
effective dates and authenticity are verified, not trusted from the reference.

completeness_claims is a nonempty claim-reference array proving the declared
finalization boundary, cutoff and exhaustive coverage of temporary/emergency
closures AND session exceptions. A ledger with no entries is not sufficient
unless its qualified contract and authenticated completeness assertion prove
that absence over this exact interval. An arbitrary statement complete=true
in caller JSON is never such an assertion.

daily_evidence is ordered by market_calendar_date with exactly one entry for
each civil date in the inclusive interval. Its exact entry fields are:

```text
market_calendar_date
day_status
basis
session_open
session_close
session_profile
status_claims
closure_claims
geometry_claims
```

day_status is TRADING or CLOSED. basis is one of REGULAR_SESSION,
QUALIFIED_EARLY_CLOSE, WEEKEND, SCHEDULED_HOLIDAY, TEMPORARY_CLOSURE.
status_claims and closure_claims are nonempty verified reference arrays on
EVERY date. geometry_claims is nonempty for TRADING and exactly [] for CLOSED.
CLOSED has null open/close/profile. TRADING has complete non-null geometry.

Concrete admission requirements by date:

| Situation | Required evidence and response |
| --- | --- |
| Weekend | Positive CLOSED claim or an authenticated complete rule covering this date with all exceptions resolved; weekday arithmetic alone is insufficient |
| Scheduled holiday | Explicit effective holiday/CLOSED authority and complete exception/closure coverage; missing provider row alone is insufficient |
| Temporary/emergency closure | Explicit effective closure declaration plus ledger completeness/finalization; unresolved coverage prevents issuance |
| Normal trading day | Positive TRADING status, exhaustive evidence excluding effective emergency closure and session exception, and positive NORMAL geometry evidence |
| Early/special session | Positive TRADING/session declaration, complete closure/exception evidence, and a mapping within the frozen geometry qualification below |
| Missing provider row | No implicit CLOSED or synthetic filler; require qualified explicit authority for this date or fail the invocation |
| Duplicate/conflicting declarations | Reject duplicate date declarations within a source and conflicting declarations across sources; distinct consistent sources may corroborate one canonical daily entry without deduplication or timestamp selection |

All decoded source claims relevant to scope participate in conflict checking,
not just caller-referenced claims. An unused in-scope contradicting declaration
cannot be hidden by omitting its claim index. Any source declared incomplete,
ambiguous, provisional, errored or unauthorized prevents its use as completion
authority. Consistent Moomoo data may be corroboration only, never the missing
closure/negative proof. If included Moomoo returned status disagrees with the
completion authority, FAIL; there is no override policy in this V1.

Freeze existing geometry only:

```text
market=US; requested_session=RTH; market_timezone=America/New_York
NORMAL: local 09:30-16:00
QUALIFIED_EARLY_CLOSE: local 09:30-13:00
qualified early dates: 2025-11-28, 2025-12-24
```

For TRADING, the two listed dates MUST use QUALIFIED_EARLY_CLOSE; other dates
MUST use NORMAL. A listed date is not automatically TRADING. Neither a provider
TradeDateType nor a bar observation extends the date list or geometry. An
unlisted shortened/extended TRADING session or geometry outside the existing
contract must fail, not be coerced to NORMAL. An explicitly proven full-day
temporary closure is CLOSED with null geometry, not a new session profile.
Provider-enum mappings require
separate exact qualification. Existing timezone/DST conversion and logical
validation remain authoritative; physical timestamps store their UTC instants.

Only after ALL these predicates hold may L4 derive coverage_complete=true.
There is no successfully verified partial schedule result.

```text
coverage_completion_evidence_id = H(
    "l4-trading-day-coverage-completion-v1", content)
```

The content contains the exact source bundle, completeness claims, per-day
authority references, calendar contract, cutoff/finalization and geometry.
Hashing a provider response or a boolean is not an equivalent payload.

## 8. Complete Verification Receipt and Archive Clock

verification_receipt.json is exactly `{body, signature_base64}`. Its body has
exactly: receipt_version=`l4-schedule-verification-receipt-v1`,
verification_authority_id, verifier_contract_version, key_id,
signature_algorithm=`Ed25519`, source_snapshot_id, source_content_hash,
coverage_completion_evidence_id, schedule_declaration_hash_without_archive,
source_validation_times, coverage_verified_at, geometry_verified_at,
logical_schedule_verified_at, complete_verified_at.

source_validation_times is ordered by source_record_id, contains each bundle
record exactly once, and each entry is exactly `{source_record_id, verified_at}`.
Each verified_at is at least that record's acquired_at. The trusted verification
authority must possess every source and completion declaration and actually
execute the qualified evidence/geometry/logical checks. Its signature is over
C(body), with the same fixed signature encoding as custody receipts. Keys and
verifier contracts are separately qualified, never artifact-enrolled.

The receipt's schedule_declaration_hash_without_archive is SHA(C(D)), where D
is the exact section 9 schedule declaration except archive_available_at. This
deliberate exclusion avoids an identity/receipt cycle. Source and coverage
IDs are independently recomputed before receipt verification. The receipt is
not part of their hash payloads. No artifact ID is fed back into D.

All receipt times are authenticated conservative upper bounds from a qualified
clock policy, not caller date strings. Require:

```text
coverage_verified_at >= max(all source verified_at, closure_knowledge_cutoff)
geometry_verified_at >= max(all source verified_at)
logical_schedule_verified_at >= max(coverage_verified_at, geometry_verified_at)
complete_verified_at >= logical_schedule_verified_at

archive_available_at = max(
    all source acquired_at,
    all source verified_at,
    coverage_verified_at,
    geometry_verified_at,
    logical_schedule_verified_at,
    complete_verified_at)
```

complete_verified_at is the signed conservative possession/verification bound
for the entire schedule declaration and all completion evidence. Verification
must actually have completed by that bound, with bounded clock uncertainty;
the signer cannot backdate a claimed verification or copy a request-start time.
The deterministic archive-field derivation and final logical admission must
also have been checked by that verifier. A receipt is signed after these facts
are established. The bound must also cover completion and possession of that
signed receipt: a qualified issuer must finish signing and retaining it no
later than its claimed conservative upper bound. A reserved bound missed by
any final check or signing step cannot be reused or backdated; issuance fails.
This is a bounded-time issuance proof, not a claim that a timestamp proves its
own accuracy. Inability to prove the bound rejects the artifact. No signer,
clock service or receipt-issuance runtime is authorized in this PR.

The reader verifies these bounds and derives the identical archive value; it
does not replace it with file time, earliest row receipt, one source timestamp,
read time or current wall clock. A later-arriving evidence item requires a new
verification receipt, cannot be hidden behind an earlier source clock, and may
change the logical archive gate. With dataset_as_of=A, existing L2/L3 admission
requires archive_available_at <= A, otherwise authority failure. Null A never
authorizes a current-time lookup. Reader rereading or relocating an unchanged
artifact does not advance its archive clock.

## 9. Exact Logical Declaration and Physical Layout

Final directory and exact six-file inventory:

```text
<explicit_output_root>/schedule_artifact_id=<schedule_artifact_id>/
    schedule.json
    source_snapshot.json
    coverage_evidence.json
    verification_receipt.json
    manifest.json
    _SUCCESS
```

No subdirectories, symlinks/reparse points, hard links, extra named data
streams (alternate data streams, ADS), extras, hidden members, case aliases,
partitions, latest/current pointer or L3 Dataset file. The zero-named-stream
requirement of this sentence covers exactly the artifact directory and its six
members; retained ancestry follows the STREAM_POLICY=MEMBER_TREE_ZERO_STREAM
rule in section 10, which never extends that zero-stream requirement to
retained ancestry and never merges the writer's prepublication stream interval
with the reader's separate postcommit interval.
_SUCCESS is an empty regular file. Raw source bytes and receipts are embedded
inside the fixed JSON files, not reopened from external paths or URLs.

schedule.json has exactly the existing logical fields:

```text
schedule_schema_version = trading-day-schedule-v1
market = US
requested_session = RTH
market_timezone = America/New_York
coverage_start_date
coverage_end_date
daily_records
source_snapshot_id
source_content_hash
calendar_contract_version = cross-day-us-rth-calendar-contract-v1
normalization_version = trading-day-schedule-normalization-v1
coverage_completion_evidence_id
coverage_complete = true
archive_available_at
```

daily_records is the ordered array of the five exact TradingDayRecord fields:
market_calendar_date, day_status, session_open, session_close, session_profile.
It must equal the projection of verified daily_evidence, with no duplicate,
omitted or additional dates. The three evidence fields and archive clock are
derived as above. A supplied true value is only a claimed serialized result
and is rejected unless recomputation proves it. No L4 convenience fields are
added to VerifiedTradingDaySchedule or TradingDaySchedulePin.

Freeze these physical versions:

```text
artifact_schema_version = trading-day-schedule-artifact-v1
manifest_schema_version = trading-day-schedule-manifest-v1
serialization_version = trading-day-schedule-json-v1
reader_contract_version = trading-day-schedule-artifact-reader-v1
```

manifest.json is exactly `{schedule_artifact_id, content}`. Manifest `content`
has exactly: manifest_schema_version, artifact_schema_version,
serialization_version, reader_contract_version, schedule_content_id,
schedule_pin_id, source_snapshot_id, source_content_hash,
coverage_completion_evidence_id, market, requested_session, market_timezone,
coverage_start_date, coverage_end_date, archive_available_at,
daily_record_count, output_files.

output_files is ordered by relative path and contains exactly the four JSON
data/evidence files, each record exactly `{path, role, byte_size, sha256}`.
Roles respectively are SCHEDULE, SOURCE_SNAPSHOT, COVERAGE_EVIDENCE and
VERIFICATION_RECEIPT. Paths must equal those literal filenames, not arbitrary
relative paths. Sizes are actual nonnegative byte counts; hashes are exact
file-byte SHA256. Manifest and _SUCCESS are excluded to avoid a hash cycle;
both remain mandatory physical closure checks. No built_at/read timestamp.

```text
schedule_artifact_id = H("l4-trading-day-schedule-artifact-v1", manifest.content)
```

The directory name must match that recomputed ID. Manifest values must match
the verified logical schedule and evidence, not just be mutually consistent
strings. Moving the complete unchanged directory under another safe root
changes no ID, logical value or archive time. Re-encoding otherwise identical
JSON noncanonically fails rather than creating another valid representation.

Before allocation, reject any individual file over 64 MiB, total inventory over
128 MiB, decoded source body over 16 MiB, more than 256 source records, more than
36,600 civil dates, integer overflow or JSON nesting beyond 32 levels. These
are L4 physical-reader limits, not changes to L2's logical model. No streaming
omission, truncation or partial-admission fallback is allowed.

## 10. Strict Offline Reader

Proposed sole physical entrypoint:

```python
load_verified_trading_day_schedule_artifact(build_dir) -> VerifiedTradingDaySchedule
```

build_dir is the explicit final artifact directory, not a search root. No
caller trust IDs, callback, contract override, provider object, current-time
argument, source URL resolver or Catalog setting. The final returned product
is the existing validated logical schedule, not a new subclass or wrapper
requiring new L2/L3 semantics.

Ordered fail-closed verification:

1. Validate path/ancestry without following links or reparse objects; acquire
   stable native identities for root and all six regular, single-link members.
   Reject unsupported filesystem/object/security evidence and all extras. Apply
   the named-stream policy below: the artifact directory and all six members
   must show zero extra named data streams, while every retained ancestor
   stream set above the artifact directory is enumerated and retained as native
   evidence.
2. Read bounded immutable byte copies; record file identities, sizes and SHA256.
   Strictly parse canonical manifest only to obtain its closed inventory claims;
   verify those claims against physical bytes and the empty regular _SUCCESS
   BEFORE parsing source or logical declarations. No manifest field is trusted.
3. Enforce canonical byte equality and exact schemas on all four JSON files.
   Recompute every source body hash, record ID, bundle hash and snapshot ID.
4. Resolve only independently qualified reader-owned source/verifier contracts;
   authenticate custody/verification receipts, origin and time bounds offline.
   Parse complete source bytes with their pinned parser; reject unknown claims.
5. Recompute coverage_completion_evidence_id and prove the exhaustive daily
   partition, finalization/negative evidence, all source consistency and geometry.
   Independently verify receipt claims; a valid signature is not a coverage flag.
6. Derive the exact logical declaration and archive clock. Compare every field
   with schedule.json and receipt declaration hash. Construct TradingDayRecords
   and call the unchanged verify_trading_day_schedule with the full declaration.
   Recompute existing schedule_content_id and schedule_pin_id and compare with
   manifest. No PIT/Label/Feature re-execution and no L2 _facts reconstruction.
7. Recompute artifact ID from physically verified manifest content and verify
   final directory name, scope/count and all repeated bindings.
8. Immediately before returning, recheck ancestry, root/member native object
   identities, exact inventory, bytes/hashes/sizes, manifest and empty _SUCCESS.
   This recheck is the reader's second physical closure and the end of the
   reader/postcommit interval opened by the step-1 first pass; it is not the
   continuation of any writer or prepublication baseline. Recompare every
   retained ancestor named-stream set above the artifact directory with that
   first-pass native evidence and fail PHYSICAL_DRIFT on any addition, removal
   or change made inside this reader interval.
   Same-path identical-byte replacement still fails. Return only the fully
   validated VerifiedTradingDaySchedule; partial results never escape.

### Named-Stream (ADS) Admission Policy: MEMBER_TREE_ZERO_STREAM

```text
STREAM_POLICY=MEMBER_TREE_ZERO_STREAM
```

This reader is the L4.1 owner of the named-stream admission policy. The policy
has exactly three scopes, and no pooled "extra streams" rejection elsewhere in
this document or in the publication contract may be read as widening or
narrowing them:

| Scope | Requirement |
| --- | --- |
| Artifact directory (final, and the writer's staging directory under its own contract) | MUST have zero extra named data streams. Any extra named data stream is rejection. |
| Six fixed artifact members | MUST have zero extra named data streams. Any extra named data stream on a member is rejection. |
| Retained ancestry (every existing ancestor component above the artifact directory, including the native volume root when in scope, that the reader holds or validates) | Stream set MUST be enumerated with native evidence; the exact observed set MUST be retained as physical evidence; any change between the reader's own checkpoints MUST fail second closure as PHYSICAL_DRIFT. An ancestor carrying one or more named data streams is NOT by itself an admission failure. |

Ancestor stream evidence is collected in two separate, mutually independent
intervals, and no single continuous baseline spans them:

- Reader / postcommit interval (this document): after a known commit the reader
  independently reacquires FINAL facts against the explicit final artifact path.
  Its first-pass retained ancestor stream evidence is the reader baseline, and
  the step-8 recheck is the second physical closure that ends the interval. A
  stream-set change observed between those two reader checkpoints fails as
  PHYSICAL_DRIFT.
- Writer / prepublication interval (the publication contract, section 5): first
  retained writer ancestry stream evidence through the immediate prepublication
  revalidation, where a stream-set change fails as PREPUBLICATION_DRIFT.

Neither interval is the other's baseline, and no evidence handoff carries a
writer checkpoint across the commit. The reader's baseline MUST NOT be the
writer's first ancestry stream evidence, and the reader MUST NOT receive the
writer scope, the writer seal, a writer stream tuple or caller physical
evidence; its sole input remains the explicit final artifact path. Drift
observed inside either interval is never tolerated and never re-baselined. The
reader's independent post-commit first-pass acquisition is NOT "re-baselining
detected drift"; it is the beginning of a separate verification interval, and
it cannot launder drift already rejected inside the writer interval.

The artifact directory is the immediate ancestor of the six members, but it is
never tolerated ancestry: it is an artifact-tree object and stays zero-stream.
The ancestry exception applies ONLY above the artifact directory, so no reading
of "ancestor" can move ADS on the artifact directory or on a member into the
tolerated class.

MEMBER_TREE_ZERO_STREAM therefore means zero extra named data streams on the
artifact directory and on the six artifact members. It does NOT mean zero named
data streams on every lexical or native ancestor.

Stream evidence collection is not a zero-stream admission policy. Enumerating an
ancestor's named data streams proves what the host actually presented and lets
that interval's closing checkpoint detect drift against that interval's own
baseline; that evidence MUST NOT be converted into an ancestry-wide zero-stream
admission rule, MUST NOT be replaced by a caller boolean, path string or cached
listing, and MUST NOT be carried across the commit into the reader interval as a
shared baseline. A missing or unreliable native stream fact fails closed exactly
like any other unproved native fact, and a denied or unsupported stream result
is never converted into an empty set; the native no-more-streams outcome is
retained as the empty set it proves.

This exception applies ONLY to retained ancestry. It does not weaken
artifact-directory stream exclusion, six-member stream exclusion, reparse
rejection, path identity, FileIdInfo identity, security/access-boundary checks,
filesystem/volume checks, exact inventory or same-path replacement detection.
Retained ancestry stays subject to native identity, no-reparse, access-boundary,
local filesystem/volume, retained-evidence and two-interval drift-detection
requirements.

Threat-model rationale from the completed G3 review: no demonstrated
path-resolution bypass, replacement-authority bypass, security-descriptor
bypass, inventory bypass, or second-closure bypass when retained ancestor stream
tuples are retained; a zero-stream ancestry rule instead introduces a
demonstrated mutable host dependence, because unrelated host or filesystem
activity on a retained ancestor would make an unchanged, correct artifact
unreadable. Retaining the observed ancestry stream set plus drift detection
preserves every reviewed invariant.

This freeze is DESIGN ONLY. It authorizes no runtime change, qualifies no
platform, and makes no conformance claim about any existing implementation;
bringing an implementation into conformance requires separately authorized
work.

Physical identity/security rules need independently qualified reader platform
support. L3's two qualified writer tuples are not automatically L4 qualification.
The reader has no write, repair, cleanup, rename, delete, quarantine, provider,
network, OpenD or mutable-trust-source authority. Missing or invalid files remain
untouched. Hash verification supplies integrity, not source authenticity.

Proposed failure vocabulary for a future artifact-specific exception:
UNSAFE_PATH, INVENTORY_MISMATCH, NONCANONICAL_BYTES, INTEGRITY_MISMATCH,
SOURCE_CONTRACT_UNQUALIFIED, EVIDENCE_AUTHORITY_UNQUALIFIED,
SOURCE_AUTHENTICATION_FAILED, SOURCE_SCOPE_MISMATCH, SOURCE_CONFLICT,
COVERAGE_INCOMPLETE, SESSION_GEOMETRY_UNQUALIFIED, ARCHIVE_BOUND_INVALID,
LOGICAL_SCHEDULE_MISMATCH, IDENTITY_MISMATCH, PHYSICAL_DRIFT.
These are artifact admission errors, never Label INCOMPLETE or silent row drops.

## 11. Separate Publication Contract Required

YES: a new writer's no-replace publication and invocation-owned staging cleanup
require a separately reviewed destructive operation contract. The existing
[L3 Dataset publication contract](governance/cross_day_dataset_atomic_publication_v1.md)
binds different paths, symbols, inputs and inventory. It grants L4 no authority.
Do not change or call through it to obtain an implicit extension.

Proposed future operation: trading_day_schedule_atomic_publication_v1, contract
version trading-day-schedule-atomic-publication-v1. A later DESIGN-ONLY PR must
add its machine declaration and detailed platform/state/cleanup proof before
any implementation PR. This document and a future approval of its schema are
not that machine-bound authorization.

Proposed exhaustive destructive surface list for that separate review:

| Future file | Future exact symbol | Primitive/count |
| --- | --- | --- |
| src/market_vault/schedule_artifact/materialization.py | _rename_directory_no_replace_windows | os.rename / 1 |
| src/market_vault/schedule_artifact/materialization.py | _remove_tree | shutil.rmtree / 1 |
| src/market_vault/schedule_artifact/materialization.py | _rename_directory_no_replace_linux | direct renameat2(RENAME_NOREPLACE=1) / 1, separately reviewed native boundary |

No other destructive operation is proposed. The future contract must freeze
exclusive sibling staging `.<schedule_artifact_id>.tmp-<32lowerhex>`, root and
member ownership, safe ancestry, same-volume proof, an invocation-private seal,
prepublication revalidation, Windows handle-quiescence/cleanup-rebind safety,
exact no-replace collision semantics, read-only equivalent-winner verification,
postcommit no-rollback and uncertain-publication no-cleanup behavior. Only new
invocation-owned staging can ever be cleanup-eligible. No overwrite, final
deletion, repair, permissions repair, arbitrary staging adoption or sweep.
Reader remains completely outside publication/cleanup authority.

These proposed names/counts are not currently registered. Before implementation,
the later contract must resolve all ownership/state/error details and qualify
actual Windows/Linux primitives for this new artifact. Any different/additional
surface requires separate review. No checker or exemption change is implied.

```text
CURRENT_CONTRACTS=6
CURRENT_EXEMPTIONS=16
CURRENT_PYTHON_DESTRUCTIVE_SURFACES=44
THIS_DESIGN_NEW_RUNTIME_DESTRUCTIVE_SURFACES=0
```

A separately approved new declaration would make 7 contracts; realizing only
the two proposed Python sites would make 46 surfaces, with 16 exemptions and
the native Linux boundary separately audited. These are conditional future
counts, never this PR's inventory or implementation authorization.

## 12. No Circular Authority or Operational Selection

The L3 Dataset artifact's schedule.json is a recorded copy of its already-
authoritative logical schedule. Its L3 reader verifies recorded schedule
closure. It does not thereby become an L4 source snapshot, a provider proof,
a custody receipt, a completion ledger or an L4 schedule artifact. Do not use
Dataset artifact -> schedule authority -> Dataset artifact as a trust chain.
Physical schedule source identity originates strictly upstream of Dataset use.

All disagreement fails: provider dates versus completion declarations,
completion versus session authority, conflicting source claims, duplicate
acquisitions, inconsistent immutable snapshots, scope mismatches and forged
receipt times. No latest wins, Catalog ordering, mtime winner, preferred path,
timestamp winner or repair-in-place. Identical evidence at another location is
the same content, not another vote. Distinct snapshots are explicitly selected
inputs; there is no source discovery API in this design.

After L4 verification, throughout L2/L3 execution:

```text
provider_calls=0
network_calls=0
OpenD_calls=0
current_time_reads=0
mutable_catalog_reads=0
```

Existing sealed implementation-fingerprint reads are unchanged; this statement
does not claim all existing L2/L3 filesystem reads are zero. The L4 reader
reads only the explicit artifact and immutable reader-owned contract logic,
never a provider, settings file, source path, DuckDB or current calendar.

## 13. Future Canaries: Design-Defined, Runtime-Deferred

These are new L4 obligations, NOT rewrites of the historical 80 Dataset
canaries, IR1, or closed L3 evidence. None is reported runtime PASS by this PR.

| ID | Mandatory future assertion |
| --- | --- |
| L4-01 | Identical source/evidence bytes at another path produce identical source/evidence/artifact IDs |
| L4-02 | One source byte change changes recomputed source/artifact identity or fails authentication/parsing; stale hashes never pass |
| L4-03 | One completion-evidence change changes completion/artifact identity or fails verification |
| L4-04 | Missing civil date cannot become CLOSED implicitly |
| L4-05 | Temporary/emergency-closure uncertainty prevents coverage_complete=true |
| L4-06 | Provider row/TradeDateType cannot widen early-close dates or geometry |
| L4-07 | Conflicting included sources fail even when the caller references only one |
| L4-08 | Duplicate daily entries, duplicate date declarations within one source, and duplicate acquisitions fail; separate consistent source proofs remain distinct and no keep-last is used |
| L4-09 | archive_available_at later than dataset_as_of fails existing L2/L3 admission |
| L4-10 | DuckDB/latest/current pointer, Catalog ID, cwd and mtime cannot enter identity or admission |
| L4-11 | Provider unavailable during offline consumption has no effect and causes zero acquisition attempts |
| L4-12 | Complete artifact relocation preserves all semantic IDs and archive time |
| L4-13 | Source snapshot tampering, including coordinated rehashing without authority, fails reader |
| L4-14 | Completion evidence tampering or invented claim index fails reader |
| L4-15 | Manifest tampering, wrong inventory/hash/role/count or mismatched artifact name fails reader |
| L4-16 | Unchanged full logical schedule preserves L3 Dataset IDs and all 98 known-answer literals |
| L4-17 | Old operational collect_trading_calendar behavior remains unchanged |
| L4-18 | Returned Moomoo date alone cannot assert TRADING; absent row alone cannot assert CLOSED |
| L4-19 | Unknown/self-supplied source profile or signing key fails; valid custody signature alone does not prove completeness |
| L4-20 | Late-arriving completion/geometry evidence cannot inherit an earlier source archive clock |
| L4-21 | Receipt forgery, clock-order violation, incomplete finalization or receipt/declaration mismatch fails |
| L4-22 | Exactly two existing early dates, UTC/DST conversion and listed-early-date NORMAL rejection remain unchanged |
| L4-23 | Duplicate keys, BOM, noncanonical JSON/base64, unknown fields, floats and resource-limit excess fail |
| L4-24 | Missing/nonempty/replaced _SUCCESS, reparse/hardlink/extra member or same-byte object replacement fails both physical passes |
| L4-25 | L3 schedule.json alone cannot enter the L4 source/reader authority chain |
| L4-26 | Explicit exact source selection is deterministic; reversing distinct input order does not create a timestamp winner |
| L4-27 | Reader failures cause zero mutation and no source/provider/network/current-time fallback |
| L4-28 | New publication contract precedes any writer implementation; no L3 contract, capability or exemption reuse |
| L4-29 | Extra ADS/named data stream on the artifact directory or on a member fails admission in both physical passes, while an ancestor above the artifact directory carrying a named data stream is admitted only with its exact stream set retained as native evidence; an addition, removal or change of that ancestor stream set inside the reader's own interval, between its first-pass baseline and its second physical closure, fails as PHYSICAL_DRIFT, while the writer's separate prepublication interval fails its own observed change as PREPUBLICATION_DRIFT |

Publication collision/race/crash/quiescence/cleanup/platform canaries must also
be specified by the separate destructive-design PR. Documentation here is not
native qualification evidence for those operations.

## 14. Review Exit and Locks

This phase requires a one-document diff, whitespace/hygiene/release/destructive
gates and completed natural exact-head CI. Its expected inventory remains
6/16/44 and package version remains 0.8.0. CI chooses its own tier; no forced
FULL or reduced tier and no new test files. Existing logical tests may be run
without being changed. No full-runtime claim is made from documentation CI.

Before later production work, independent review must resolve/admit actual
source profiles, trustworthy custody/verification keys and clock guarantees,
complete closure/special-session authority, offline qualification fixtures,
reader platform evidence and a separate publication contract. Merely reviewing
this document does not grant source qualification or runtime authorization.

No Catalog selection API, CLI/UI integration, provider deployment, production
OpenD run, background refresh, scheduled acquisition, QFQ/HFQ, corporate actions,
new markets/session geometry, ML/backtesting/signals/trading or release/tag
mutation. No host restart/shutdown/logoff/sleep/hibernate, feature, BIOS/UEFI,
bcdedit, ACL, network, RDP or firewall change.

```text
SOURCE_CHANGED=false
TESTS_CHANGED=false
SCRIPTS_CHANGED=false
CI_CHANGED=false
VERSION_CHANGED=false
DESTRUCTIVE_REGISTRY_CHANGED=false
L4_RUNTIME_IMPLEMENTATION_AUTHORIZED=false
L4_PROVIDER_PRODUCTION_QUALIFICATION_AUTHORIZED=false
MERGE_AUTHORIZED=false
```

Stop after design commit and natural CI for independent semantic review.
