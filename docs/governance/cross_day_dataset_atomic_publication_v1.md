# Cross-Day Dataset Destructive Publication Contract V1

## 1. Status and Frozen Authority

DESIGN ONLY. Independent destructive-authority review, authorized merge,
exact-main closure and a separate runtime work order are all required before
implementation. This candidate does not approve itself or qualify a platform.

BASE_MAIN_SHA=ef624dc6f2fa44bbf09191a175a76e56a992753c
BASE_MAIN_TREE=6df0546b9e7f00ecdbd0e55a148b868bf2180b51

PUBLICATION_CONTRACT_VERSION=multi-source-cross-day-dataset-atomic-publication-v1
OPERATION_ID=multi_source_cross_day_dataset_atomic_publication_v1

The JSON contract at
[destructive_operations/multi_source_cross_day_dataset_atomic_publication_v1.json](destructive_operations/multi_source_cross_day_dataset_atomic_publication_v1.json)
is the machine-bound declaration. Its APPROVED schema value is the repository's
only admitted contract enum, not evidence of independent approval of this PR.
The unchanged declaration must exist in the future implementation PR BASE.
This document supplies its normative detailed predicates; neither declaration
may be materially changed beside implementation. On disagreement fail closed
and obtain a separate design correction.

[Cross-Day Dataset design](../multi_source_cross_day_dataset_v1.md), especially
sections 19-23, remains the logical, serialization, reader and layout authority.
No alteration to the five identity domains, 49-field Dataset ID, 32-field audit,
98 fixed digests, matrix schema, completion, split, L3.1 join or L3.2 generator.
Old Dataset, A1-A4, L2 and TS2 authorities remain sealed. A4's contract owns only
its exact multi_source/materialization.py symbols, not this new package.

## 2. Operation and Exact Mutation Scope

The future internal operation has two bounded actions: publish one verified
directory without replacement, and remove only current-invocation uncommitted
staging. Reader calls have no mutation authority.

The caller supplies a pre-existing absolute output_root, an actual issued
MultiSourceCrossDayDatasetResult and explicit built_at metadata. The future
writer fully validates those inputs before mutation. It never creates,
repairs, chmods, deletes or owns output_root or its ancestors. The root must be
a dedicated artifact-output directory, not a filesystem root, repository,
source evidence directory, existing artifact, or directory within an artifact.
Acquisition/settings/Catalog/current-time inference is forbidden.

Freeze exactly these sibling names (ID is lowercase 64-hex):

```text
<output_root>/
  .<dataset_id>.tmp-<nonce>/
  dataset_id=<dataset_id>/
```

nonce is 32 lowercase hex characters from 16 cryptographically random bytes.
It is neither caller-controlled nor time-based and is never logical identity.
Exclusive mkdir must succeed for that exact name. Collision is a failure;
no adoption, existence-tolerant mkdir or collision cleanup. A later invocation
uses a new nonce. No search for old staging and no sweep of siblings.

Only exclusive creation of the staging directory, its whitelisted
subdirectories and new files is permitted before publication. No truncating an
existing file, hard-link creation, source-file move, arbitrary copy tree,
permission repair or external write is permitted. Handles opened for writes
must be closed before final private verification.

### Exact Future Destructive Bindings

| Future path | Exact symbol | Gate kind / signal / count |
| --- | --- | --- |
| src/market_vault/cross_day_dataset/materialization.py | _rename_directory_no_replace_windows | destructive_call / os.rename / 1 |
| src/market_vault/cross_day_dataset/materialization.py | _remove_tree | destructive_call / shutil.rmtree / 1 |

Linux's sole native publication boundary is
materialization.py::_rename_directory_no_replace_linux: one direct, bounded
renameat2 call with RENAME_NOREPLACE, reached only through the same sealed
publication path. The current AST checker does not inventory that native call.
It is explicitly part of this operation's semantic authority, not an exemption
or an uncounted license for other native mutation. Future source review and
static tests must enforce the one named wrapper, one call site, constant flag,
fixed arguments and no alternate native dispatch. No implementation exists here.

Expected inventory: before 5 contracts / 16 exemptions / 42 findings;
this PR 6 / 16 / 42; eventual two realized Python findings 6 / 16 / 44.
That last count is an implementation expectation, not today's inventory.
No checker change, exemption, prospective_transition, wildcard binding or
reuse of A4 bindings is permitted. Another signal/symbol/count requires a
separate prior design approval.

## 3. Safe Paths and Ownership

Validate lexical syntax before traversal: absolute canonical native root only;
no empty/dot/dot-dot components, drive-relative paths, NUL/control characters,
ambiguous trailing dots/spaces, device names, UNC/network roots or extended
device namespace aliases. Windows allows only the single drive colon in its
absolute root prefix; every other colon (including ADS) is rejected.
Canonical artifact members use the frozen relative POSIX spelling, never
backslashes, drive syntax, absolute paths or path escapes.

Inspect every existing component with lstat/reparse-aware checks before
following it, including ancestors above output_root. resolve() alone is not
proof. Require exact directory types for ancestors and declared subdirectories,
and exact regular-file types for members. Reject links, junctions, all Windows
FILE_ATTRIBUTE_REPARSE_POINT objects (even non-escaping ones), device files,
sockets, FIFOs, mount transitions below the output root and unknown types.
Require single-link regular files; reject extra Windows named streams rather
than overlooking non-inventory data. All inspections fail closed on denial.

Retain an invocation-private ownership record, not a caller token:
validated root path and root object identity, ancestor identities, filesystem
identity, exact staging name/path/object identity, exact final sibling/name,
dataset_id, exclusive-creation success, and each created member's path/type/
object identity as creation completes. Creation failure before ownership is
captured grants no deletion authority. No serialization or caller-authored
ownership record is accepted.

Before every mutation revalidate the relevant ancestry, root and owned objects;
before recursive removal validate the whole extant private subtree. Other
writers may only create their own staging and compete for an absent final.
Require locally controlled root/ancestors and private staging access controls
that exclude untrusted mutation; creation uses restrictive owner-only access.
Do not change pre-existing permissions to obtain this property. Permission/
ACL drift, unverifiable exclusive control or inability to prevent traversal
substitution means refusal, not a best-effort check.

This is not protection against a hostile kernel, administrator, or process
already holding equivalent owner credentials. A content scan is not an atomic
lock against such an actor. Supported operation requires the stated access
boundary for the scan-to-rename interval; prepublication checks do not pretend
to remove that limit. Cooperative concurrent writers never access each
other's staging. Tests inject drift before the last check and prove refusal;
they do not claim unrestricted adversarial concurrency is solved.

## 4. Object and Filesystem Evidence

Linux: retain no-follow directory/file descriptors while capturing fstat
(st_dev, st_ino, exact type); compare path lstat to those held objects. Root,
staging and every member must have the same st_dev, and mount identity must
also match (statx mount ID) so bind mounts cannot masquerade as same-placement
proof. Rename source/destination are single names relative to the same held
output-root directory descriptor. Require a qualified local filesystem and
stable identities; EXDEV or any proof failure is fatal.

Windows: retain no-follow/reparse-aware handles and compare
GetFileInformationByHandleEx(FileIdInfo): VolumeSerialNumber plus full 128-bit
FileId, with FileAttributeTagInfo/type and final handle path cross-checks.
Use the root's volume GUID identity plus serial, not drive letter alone.
Root/staging/members and final parent must share that volume; an existing
final is separately checked read-only. A missing target has no file identity:
prove its parent is the very same retained root. Missing/zero/unstable identity,
reparse traversal, remote volume or cross-volume path is unsupported.

mtime, ctime, size alone, lexical prefix checks and a successful resolve are
never object or filesystem proofs. Reuse of a path or same inode number after
handle loss is not ownership; inability to retain reliable evidence fails.
See [Microsoft FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info)
for the handle identity pair. The stricter volume/mount/access checks above
are requirements of this contract.

## 5. Closed Inventory and Private Seal

The final name is exactly dataset_id=<ID>. Freeze the existing layout:

```text
dataset.parquet
feature_pit.json
canonical_evidence.json
ts2_features.json
observation_pit.json
observation_evidence.json
observation_features.json
cross_day_association.json
cross_day_values.json
schedule.json
sample_audit.json
split.json
build_report.json
specs/ts2/<dataset-spec-pin-id>.yaml
specs/observation/<existing-feature-pin-id>.yaml
specs/cross_day/<dataset-spec-pin-id>.yaml
specs/split.yaml
manifest.json
_SUCCESS
```

Expected file set derives from the verified result's exact specs and the
frozen section-20 whitelist, not from arbitrary manifest paths. Directory set
is exactly specs plus the parent directories of the expected spec files;
empty family directories absent when no such files exist. Reject every extra
file, hidden child, extra directory, alternate case spelling, stream or alias.
Roles/versions/content IDs/row counts and bytes follow frozen sections 19-20.
manifest.json and _SUCCESS stay outside manifest.output_files (no recursion)
but are mandatory members of the seal. EMPTY still has an exact-schema
zero-row dataset.parquet and all required provenance.

Only _verify_and_seal_staging(owner) may issue _PublicationSeal, after complete
private verification including _SUCCESS. No public constructor, replace/
deserialization path, caller hash, skip-validation option or borrowed seal
establishes authority. Bind the seal to that invocation's owner by private
issuance context and single-use publication state.

The immutable seal contains dataset_id, exact root/staging/final path binding,
ancestor/root/staging object and filesystem identities, exact sorted typed
inventory (files AND directories), and, for every file, relative_path,
file_role, object identity, byte_size and exact SHA256. Capture directory
identities too. Include every spec, sidecar and matrix file. Retain exact
manifest bytes and SHA256; require strict typed manifest reconstruction of
manifest.dataset_id == owner.dataset_id. _SUCCESS must be an empty regular file,
byte_size=0 and SHA256 of empty bytes. No omitted evidence/report member.

Seal facts must describe the bytes admitted by the final private verifier,
not a later unchecked reread. The verifier retains its complete admitted
physical facts, then capture compares against that exact inventory/object/
content snapshot; drift between verification and seal issuance fails. Seal
capture cannot launder changed bytes as newly trusted authority.

## 6. Commit Order and Immediate Revalidation

Exact future order; no upstream numerical execution or selector rerun:

1. Validate explicit issued result, built_at, root/safety/platform capability.
   If final already exists, take section 9's read-only path without staging.
2. Exclusively create the one sibling staging and capture ownership.
3. Exclusively write matrix, recorded sidecars and canonical spec files.
4. Write canonical manifest last among content files; close all write handles.
5. Perform full private artifact verification without _SUCCESS; require exact
   inventory for this phase, logical closure and manifest owner binding.
6. Exclusively create exact empty _SUCCESS; close its handle.
7. Perform full final private verification with _SUCCESS and staging-name
   exception only. Do not weaken any other reader/recorded closure rule.
8. Issue private seal from the admitted physical facts as in section 5.
9. Immediately revalidate safety, exact target binding and ALL seal facts.
10. Attempt one true atomic same-filesystem no-replace directory publication.
11. Verify final through the sole new verified reader, including its final
    physical closure pass and comparison with the requested logical authority.
12. Return success only after step 11; mark created_new_build accordingly.

_publish(owner, seal) is the only path to the primitive. It requires a genuine,
matching, unconsumed seal; a cleanup ownership record alone is insufficient.
Step 9 repeats safe ancestry, root/staging/directory/file object identity,
filesystem/volume/mount identity, exact inventory EQUALITY, every size and
SHA256, exact manifest bytes and reconstructed ID, and empty _SUCCESS.
Recheck final state immediately. No callback, await, write, permission change,
new data preparation or other caller hook occurs between this check and
primitive entry. Any drift fails BEFORE the primitive (call count zero).

If a safe final appeared, skip primitive and verify read-only. If it appears
after the check, the primitive must refuse replacement. A missing expected
member is a publication failure even though cleanup can admit partial state.

## 7. Two Distinct Authorities: Cleanup and Publication

_check_owner is a cleanup/ownership predicate for partial PRIVATE_STAGING.
Its inventory may be a SUBSET of expected final inventory, never a superset.
All extant entries must also be current-invocation-created objects from the
ownership ledger with safe types/ancestry and unchanged object identities.
Missing files or owned files with invalid content do not alone prohibit cleanup.
Substituted file/root objects, unexpected children, links or uncertain control
do prohibit it. No complete manifest, empty marker or publication seal is
required to clean a legitimately partial write.

_remove_tree is private, accepts only still-validated owner authority and
uses one shutil.rmtree occurrence. It has no raw caller-path API, no retry
callback that chmods/unlinks protected data, and no ignored errors. Revalidate
immediately before removal with a qualified traversal-safe implementation
under the protected namespace. On denied/partial cleanup retain the original
error plus CLEANUP_REFUSED detail and residue location; do not widen scope.

After successful rename, revoke staging cleanup authority BEFORE invoking the
final reader. Never cleanup by checking only that the old path happens to
exist: another object may now occupy it. No final deletion, rollback, repair,
quarantine, manifest regeneration or marker regeneration is allowed.

## 8. Platform Primitives and Qualification

Linux requires renameat2(root_fd, staging_name, root_fd, final_name,
RENAME_NOREPLACE), flag value 1 only. No RENAME_EXCHANGE/WHITEOUT, plain
rename/renameat, copy+delete or fallback. EEXIST is destination-exists; ENOTEMPTY
may be treated likewise only with fresh safe final existence proof. ENOSYS,
EINVAL, ENOTSUP/EOPNOTSUPP, missing symbol or unsupported filesystem fails
closed. EXDEV is a same-filesystem failure; permissions and other errors never
become an overwrite retry. This matches the
[Linux renameat2 contract](https://man7.org/linux/man-pages/man2/rename.2.html);
filesystem support is a separate required capability.

Windows requires exactly os.rename(staging, final) only inside the bound
Windows helper, with a qualified CPython build using non-replacing semantics.
No os.replace, MoveFileEx replacement/copy flags, delayed reboot move or
shutil.move. [Python documents destination-exists refusal on Windows](https://docs.python.org/3/library/os.html#os.rename).
Actual empty AND nonempty directory refusal is mandatory evidence, not an
inference from success on absent destinations. FileExistsError maps to
destination-exists. Any ambiguous Windows error is not assumed a race success:
inspect safely read-only; otherwise fail without mutation or fallback.
The [MoveFileEx flags](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)
must be audited in the selected CPython primitive implementation; replacement
and copy flags are forbidden.

Qualification is exact (OS build/kernel, CPU architecture, Python build,
filesystem type/version/options, local-volume configuration, identity APIs,
ACL/permission policy). A documented API, mocked call or older A4 result is
not qualification of this new path. No tuple is qualified by this design PR.

| Platform candidate | SUPPORTED_AND_QUALIFIED only after | UNSUPPORTED_FAIL_CLOSED |
| --- | --- | --- |
| Windows 11 / Server 2022+, local NTFS, CPython 3.11/3.14 | Exact tested tuple; actual new-wrapper destination/race tests; reliable FileIdInfo + volume and reparse checks; restrictive ACL qualification | Other or untested tuples, FAT/exFAT/ReFS/network/UNC, missing stable IDs, unsafe ACL, unsupported runtime |
| Linux, local ext4, CPython 3.11/3.14 | Exact tested kernel/libc/filesystem tuple; actual renameat2 flag=1; root-fd/mount/type checks; protected private permissions | Untested tuples, network/NFS/CIFS, overlay/FUSE/bind-mount ambiguity, missing primitive/statx/identity/control proof |
| All other platforms | None in v1 | Always unsupported |

These are closed candidate families, not minimum-version promises. The future
runtime PR must record tuples/evidence and encode an explicit admitted
capability policy; unknown environments fail closed. Broadening families or
switching primitive requires prior independent design review.

For EACH accepted tuple require real absent-target success, empty destination
refusal, nonempty destination refusal, simultaneous identical/conflicting
writers, corrupt race winner immutability, root/staging/member substitution,
same-size mutation, deletion, marker/manifest drift, reparse/link refusal,
cross-device refusal, permission/cleanup refusal and postcommit reader failure.
Tests must assert bytes and object identities of existing destinations and
unrelated siblings survive. Run Linux tests on actual Linux, Windows tests on
actual Windows; mocks supplement failure branches but cannot qualify a tuple.
Evidence must include exact-head natural CI and native platform run logs.

## 9. Existing Final, Races and Retry

Existing final before staging: inspect safely read-only; fully verify with
the frozen new reader and externally pin to the requested dataset_id,
identity_input, recorded logical component facts, schema/content and specs.
Equality is logical artifact authority, not equality of new built_at or
serializer bytes. Existing bytes must independently match their own manifest.
Physical-only differences never justify rewriting. Equivalent returns
created_new_build=false; conflicting/corrupt/symlink/partial final fails
untouched and creates no staging.

Race loser follows the same rule for the winner. No-replace is exclusion
authority, not final.exists(). Cleanup of the loser's own staging is separate
and must succeed or produce a reported cleanup refusal; never claim the
winner is cleanup-owned. Concurrent equivalent writers may have one newly
created result and one verified existing result, with no overwrite.
Conflicting writers cannot overwrite or repair the winner.

Retry is a NEW invocation starting with final verification. It gains no
authority over prior staging, including residue with the same dataset_id,
nonce-looking name, owner process ID or _SUCCESS. No automatic scanning or GC.

## 10. State and Error Contract

Physical publication and successful verified return are distinct:

| State | Authority / permitted next state |
| --- | --- |
| PREFLIGHT | No owned staging; PRIVATE_STAGING, EXISTING_EQUIVALENT or FAILED_PRECOMMIT |
| PRIVATE_STAGING | Owned partial content; SEALED or FAILED_PRECOMMIT |
| SEALED | Exact privately verified immutable snapshot; COMMITTED_UNVERIFIED, EXISTING_EQUIVALENT, FAILED_PRECOMMIT or PUBLICATION_UNCERTAIN |
| COMMITTED_UNVERIFIED | Rename succeeded; VERIFIED_FINAL or COMMITTED_INVALID only, NEVER cleanup |
| VERIFIED_FINAL | Terminal newly created verified success |
| EXISTING_EQUIVALENT | Terminal verified existing success |
| FAILED_PRECOMMIT | Terminal failed invocation; cleanup only if ownership remains provable |
| COMMITTED_INVALID | Terminal postcommit failure; final left untouched |
| PUBLICATION_UNCERTAIN | Terminal ambiguous primitive interruption; no cleanup; read-only recovery only |

The mutation commit point is successful no-replace rename, not _SUCCESS and
not reader return. No trusted final result is issued before successful final
verification. COMMITTED_INVALID does not undo the physical commit.

Freeze the future artifact error envelope as
MultiSourceCrossDayArtifactError(reason_code, publication_state, cause),
with cause preserving the original exception; optional cleanup failure is
secondary detail, never replacement of the first failure. Reason codes:
INPUT_AUTHORITY, UNSAFE_PATH, OWNERSHIP_UNPROVEN, PLATFORM_UNQUALIFIED,
FILESYSTEM_MISMATCH, INVENTORY_MISMATCH, CONTENT_MISMATCH,
MANIFEST_BINDING, SUCCESS_MARKER, SEAL_AUTHORITY, EXISTING_FINAL_INVALID,
PUBLICATION_FAILED, CLEANUP_REFUSED, FINAL_VERIFICATION_FAILED,
ARTIFACT_DECODE, ARTIFACT_AUTHORITY.
These are artifact failures, not new Feature/Label statuses or Dataset ID
fields. Destination-exists is internal control flow followed by verification.
Unexpected programming errors are not hidden by a broad decoding catch.

On ambiguous interruption during primitive entry, never infer non-commit
from an exception alone and never delete final; report uncertain publication
with PUBLICATION_FAILED and publication_state=PUBLICATION_UNCERTAIN; revoke
cleanup authority and preserve evidence. Recovery starts read-only.
Atomic visibility is not a universal power-loss durability guarantee. The
platform qualification must describe its persistence limits; after restart
strict verification, never repair, decides whether an artifact is usable.

## 11. Concrete Threat and Crash Responses

| Threat / interruption | Required response / evidence |
| --- | --- |
| Symlink | Reject before traversal or mutation, preserve target |
| Junction / reparse | Reject all tags, including inside-root redirection |
| Output-root replacement | Identity/ancestry failure; no publication or cleanup through replacement |
| Staging-root replacement | Ownership failure; leave substituted object and residue |
| Same-path file replacement after hash | Object mismatch despite same bytes; zero rename calls; cleanup refused |
| Added hidden/unlisted file or directory | Exact inventory failure; zero rename; no broad cleanup |
| Same-size byte mutation | SHA256/verified-snapshot mismatch; zero rename; owned safe cleanup only |
| Manifest mutation | Exact bytes/hash and Dataset binding fail; zero rename |
| _SUCCESS mutation | Nonempty, replaced, missing or wrong type fails; zero rename |
| Cross-filesystem staging | Device/volume/mount proof or EXDEV fails; no copy fallback |
| Pre-existing final | Read-only equivalence or failure; no staging creation |
| Racing final creator | No-replace refusal; read-only verification of winner |
| Permission / ACL changes | Fail safety/operation; no permission repair; uncertain cleanup refused |
| Crash before manifest | Non-authoritative partial staging; retry never adopts/deletes it |
| Crash after manifest | Still private, no trusted final; same residue policy |
| Crash after _SUCCESS | Marker does not publish; same residue policy |
| Crash immediately before publication | Sealed private residue is not a final artifact |
| Crash immediately after publication | No rollback; next invocation verifies final read-only |
| Final verification failure | COMMITTED_INVALID, FINAL_VERIFICATION_FAILED; final untouched |
| Leftover owned staging in live invocation | Remove only if current ownership checks still pass |
| Leftover unowned staging | Never adopt, inspect for adoption, sweep or delete |
| Concurrent identical writers | One publication; loser verifies winner; private cleanup only |
| Concurrent conflicting writers | Never replace winner; loser fails after read-only verification |
| Forged/reused seal | SEAL_AUTHORITY; zero primitive calls |
| Changed permissions during cleanup | Report residue; never retry with widened deletion privileges |

Future fault injection must reach the interval AFTER final private verification
and BEFORE _publish. Mutate/remove each member class, including specs,
association/evidence/report files, not just matrix. Assert zero primitive
calls, final absent unless an independent winner exists, unrelated children
unchanged. Inject replacement between verification and seal capture as well.

## 12. Reader and Logical Identity Separation

The future sole reader remains load_verified_multi_source_cross_day_dataset.
Its exact recorded validation and final second-pass physical closure from
the frozen design are unchanged. It never invokes upstream selectors,
executors or L2 _facts, and never regenerates a manifest/marker, repairs,
cleans, renames, deletes or quarantines anything. No public trusted sealed
upstream result is manufactured by deserialization.

Physical hashes, file identity, output_root, cwd, mtime, built_at, manifest
bytes and the publication seal are artifact verification facts only.
DATASET_ID_DOMAIN=multi-source-cross-day-dataset-id-v1
NEW_IDENTITY_DOMAIN_COUNT=5
DATASET_ID_FIELD_COUNT=49
KNOWN_ANSWER_VECTOR_COUNT=8
KNOWN_ANSWER_DIGEST_ASSERTION_COUNT=98
No sixth logical domain or physical-fact Dataset payload field is introduced.

## 13. Governance Tests and Future Canary Mapping

Static declaration tests must assert exact bindings, contract schema,
dormant source absence, no new runtime finding, unchanged exemptions,
seal/cleanup distinction and separate design-BASE requirement. Synthetic AST
fixtures are analyzed only; no destructive operation is executed by these
design tests. The checker cannot prove filesystem semantics or native calls:
future runtime fault injection, platform qualification and independent review
remain mandatory. Passing this design's tests is not runtime approval.

Historical L3.1 and L3.2 canary tables remain unchanged. All 80 remain accounted:
58 L3.1 runtime, 6 preserved upstream, 5 L3.2 runtime, 9 L3.3 deferred,
2 boundary. The existing canary 68 statement about its original design having
no live contract is historical, not rewritten by this later contract PR.

| Existing canary | Future ownership | Required evidence; still deferred now |
| --- | --- | --- |
| 2 | L3_3_READER | Old readers reject new discriminator |
| 3 | L3_3_READER | New reader rejects all old discriminators |
| 38 | L3_3_RUNTIME + L3_3_READER | Relocation preserves logical identity and full proof multiplicity |
| 39 | L3_3_RUNTIME + L3_3_READER | built_at changes only physical metadata |
| 40 | L3_3_RUNTIME + L3_3_READER | output_root does not change Dataset ID |
| 61 | L3_3_READER | No upstream execution/selection/provider on read |
| 75 | L3_3_READER + L3_3_PLATFORM_QUALIFICATION | Final pass rejects object and byte substitution |
| 76 | L3_3_RUNTIME + L3_3_PLATFORM_QUALIFICATION | Partial cleanup != seal authority; invalid seal zero rename |
| 77 | L3_3_RUNTIME + L3_3_READER | Exact zero-row Parquet schema and scope completion |

L3_3_DESIGN owns only the present contract/static consistency obligations,
not runtime canary PASS. New publication threat/qualification tests supplement
these nine without renumbering or enlarging the existing 80-canary list.
L3_3_DEFERRED_CANARIES=9
DESIGN_CANARY_COUNT=80

## 14. Implementation Gate and Locks

Before a future runtime PR: independent approval and merged/closed exact
contract BASE; separate owner implementation authorization; no contract/
checker/exemption change beside implementation. Produce exact AST inventory,
platform-qualified no-replace tests, seal mutation tests, partial cleanup tests,
races, read-only reader TOCTOU tests, 98 unchanged Dataset known answers and
unchanged upstream regressions. Exact-head natural CI determines its own tier.

L3_3_DESTRUCTIVE_PUBLICATION_CONTRACT_DESIGN_AUTHORIZED=true
L3_3_CROSS_DAY_ARTIFACT_IMPLEMENTATION_STARTED=false
L3_3_CROSS_DAY_ARTIFACT_IMPLEMENTATION_AUTHORIZED=false
L4_IMPLEMENTATION_STARTED=false
L4_IMPLEMENTATION_AUTHORIZED=false
MERGE_AUTHORIZED=false
VERSION_CHANGED=false
VERSION=0.8.0

No writer, reader, manifest parser, syscall wrapper, cleanup implementation,
Catalog/CLI/provider/OpenD/network acquisition, production operation, tag,
release, package publication or deployment in this PR.
