# Trading-Day Schedule Artifact Atomic Publication Contract V1

## 1. Design Status and Authority

DESIGN / GOVERNANCE ONLY. No runtime is implemented or authorized by this PR.
No platform tuple, source/provider profile, custody/signing key, verification
key or clock service is qualified here. Independent semantic/destructive review,
authorized merge and exact-main closure must precede a separate implementation
work order. Same-PR implementation is forbidden.

```text
BASE_MAIN_SHA=b7724d83b614c2fb594d67e448cf0125e5620257
BASE_MAIN_TREE=3a84449a255f50d3ec63f3b51ae7ac27d7828857
PACKAGE_VERSION=0.8.0
OPERATION_ID=trading_day_schedule_atomic_publication_v1
PUBLICATION_CONTRACT_VERSION=trading-day-schedule-atomic-publication-v1
```

The companion [machine contract](destructive_operations/trading_day_schedule_atomic_publication_v1.json)
uses schema_version=market-vault-destructive-operation-v1 and
approval.status=APPROVED, the existing schema's only admitted approval enum.
That enum is a design declaration, not independent approval of this candidate
or permission to execute it. This unchanged contract and this normative
companion must exist on BASE before any implementation PR. Disagreement between
them is a STOP, not a choice of the more permissive text. Material redesign
requires another design-only review before implementation.

[L4.1 schedule artifact/provider design](../cross_day_schedule_artifact_provider_v1.md)
remains the semantic, identity, canonical-byte, six-file layout and strict-reader
authority. Preserve its source snapshots, evidence, receipts, archive clock and
all existing VerifiedTradingDaySchedule/TradingDayRecord/TradingDaySchedulePin
fields and identities. Preserve L2/L3 values, Dataset IDs and all L3 runtime,
publication contracts and capability tables.

L4_MOOMOO_ONLY_AUTHORITY=REJECTED.
L4_V1_PROVIDER_MODEL=PROVIDER_QUALIFICATION_DEFERRED.
Publication integrity cannot qualify provider truth, coverage completeness,
session geometry, source profiles, signing/verifier keys or clock guarantees.
Until those independent prerequisites are admitted, production input admission
fails even if physical publication would be possible.

## 2. Exact Future Bindings and Inventory

Only the following two Python destructive surfaces are declared:

| Future path | Exact symbol | Role | Kind / signal / count |
| --- | --- | --- | --- |
| src/market_vault/schedule_artifact/materialization.py | _rename_directory_no_replace_windows | MUTATION_OWNER | destructive_call / os.rename / 1 |
| src/market_vault/schedule_artifact/materialization.py | _remove_tree | SUPPORTING | destructive_call / shutil.rmtree / 1 |

The separate native boundary is exactly
src/market_vault/schedule_artifact/materialization.py::_rename_directory_no_replace_linux,
with one direct call:

```text
renameat2(root_fd, staging_name, root_fd, final_name, RENAME_NOREPLACE=1)
```

The current Python AST inventory does not detect that native call. There is
no fake machine surface or exemption for it. Future source review and native
evidence must independently prove one call site, flag 1, retained root_fd,
single relative names and no alternate dispatch or fallback. No other native
mutation is covered.

```text
BASE_CONTRACT_COUNT=6
BASE_EXEMPTION_COUNT=16
BASE_DESTRUCTIVE_SURFACE_COUNT=44
DESIGN_CONTRACT_COUNT=7
DESIGN_EXEMPTION_COUNT=16
DESIGN_DESTRUCTIVE_SURFACE_COUNT=44
NEW_RUNTIME_DESTRUCTIVE_SURFACES=0
FUTURE_EXPECTED_PYTHON_SURFACE_COUNT=46
```

46 is conditional on later realizing these two new Python sites, not this
PR's inventory. No checker, exemption, wildcard, prospective transition or
existing contract is changed. The L3 multi_source_cross_day_dataset_atomic_publication_v1
contract does not cover this package, artifact or operation; calling through
L3 code to borrow its authority is forbidden.

## 3. Three Independent Authorities

| Authority | Establishment | What it permits |
| --- | --- | --- |
| INPUT / ARTIFACT AUTHORITY | Full L4.1 source-contract, receipt, completion, geometry, archive, logical and physical-content validation of exact requested facts | Determine immutable canonical artifact bytes and recomputed schedule_artifact_id; no mutation or cleanup authority by itself |
| PRIVATE STAGING OWNERSHIP | Exclusive creation by this invocation plus retained native object/access evidence | Bounded writes to owned new members and, while uncommitted, one proven cleanup attempt; never publication by itself |
| PUBLICATION SEAL | Complete private staging verification of exactly the bytes/objects captured in the seal | At most one no-replace publication attempt for that owner and destination; no arbitrary-path cleanup |

A plain logical VerifiedTradingDaySchedule, caller hashes, boolean, serialized
owner/seal or path existence is insufficient input/ownership/publication proof.
Future input integration must derive private immutable working bytes/facts
from actual L4.1 verification. Caller mutation after capture cannot enter
artifact content. This contract adds no public logical fields or trust API.

The future materializer owns this operation. The read-only reader, provider,
Catalog, CLI, settings and user-supplied callbacks cannot invoke its mutation
or enroll ownership. Private ownership and seal instances are invocation-local,
non-transferable and non-serializable as authority. Direct construction,
copy/replace, foreign-owner, stale, replayed or caller-supplied seals fail.

## 4. Scope, Paths and Exclusive Creation

The caller supplies an explicit, already-existing safe absolute output_root.
It is a dedicated artifact-output directory, not a volume root, repository,
source-evidence directory, existing artifact or directory within an artifact.
The writer cannot create, repair, chmod, take ownership of, or delete it or its
ancestors. Input and read-only root/platform admission precede mutation.

Freeze exactly:

```text
<output_root>/
    .<schedule_artifact_id>.tmp-<nonce>/
    schedule_artifact_id=<schedule_artifact_id>/
```

schedule_artifact_id is exactly 64 lowercase hex, recomputed under L4.1, not
caller trust. nonce is independently generated 16 cryptographically random
bytes rendered as 32 lowercase hex. No timestamp/caller nonce. Staging and final
are immediate siblings on the same independently qualified local filesystem.
Exclusive staging creation must succeed; a collision fails without adoption,
cleanup or a retry loop. New invocations use new ownership and nonces.

Only creation of that private staging directory and exclusive new regular
members is permitted before commit. Do not truncate an existing object, copy
an arbitrary tree, move source evidence, create hard links or adjust existing
permissions. Windows private protected DACL and Linux restrictive access must
be supplied at creation, not repaired after exposure. Failure before capturing
reliable ownership leaves residue without granting deletion authority.

Reject relative/drive-relative paths, empty/dot/dot-dot components, NUL/control
characters, trailing-dot/space aliases, Windows device names, UNC/network or
extended-namespace caller paths, ADS/extra colons and any root escape. Native
volume-GUID evidence is not caller permission to supply a namespace alias.
No latest/current discovery or directory search selects a target.

## 5. Native Ancestry, Object and Security Evidence

Every existing component of output_root, staging and final is checked using
no-follow/reparse-aware native evidence. resolve() and lexical containment
alone are insufficient. Ancestors/staging/final must be exact directories;
members must be exact single-link regular files. Reject all symlinks,
junctions, Windows reparse tags, device/FIFO/socket/unknown types, extra streams,
hard links, mount/volume transitions and ambiguous or unsafe writable ancestry.
An absent final is proved relative to its held parent, not by a cached exists().

Linux evidence includes retained no-follow descriptors, fstat device/inode/type,
native link count, access-control evidence and statx mount identity. Validate
the ancestry chain and require a single local filesystem/mount binding through
output_root, staging, every member and final parent. Same device number alone
does not prove absence of a bind-mount transition. Keep descriptors through
renameat2; Windows handle-quiescence rules never apply to Linux.

Windows evidence includes retained reparse-aware handles, FileIdInfo volume
serial and full 128-bit FileId, FileAttributeTagInfo, FileStandardInfo link/type
proof, named-stream checks, native security descriptors and volume GUID/local
filesystem evidence. Cross-check held-handle paths and native volume APIs.
DirEntry.stat().st_nlink is not Windows link authority. A missing or unreliable
native fact fails closed. No mtime/size-only or drive-letter-only authority.

Access checks distinguish protected output/member objects, ordinary ancestors
and an actual native volume-root ancestor. Protected objects reject all
untrusted mutation grants, including write/append/EA/attributes, DELETE,
FILE_DELETE_CHILD, WRITE_DAC, WRITE_OWNER, GENERIC_WRITE and GENERIC_ALL.
Ordinary ancestors reject child-delete, DELETE, security-owner changes and
other authority that can replace/traverse into the protected chain. They do
not inherit a volume-root exception.

For a native volume-root exception, the held directory itself must be proved
the exact GUID-relative root of the same local volume using
GetVolumePathNameW, GetVolumeNameForVolumeMountPointW,
GetFinalPathNameByHandleW and stable FileIdInfo. A caller boolean or a C:\ string
does not classify it. Only there may root DELETE, write/append, write-EA and
write-attributes bits be tolerated when they grant no deletion/replacement or
security mutation of the separately protected child. FILE_DELETE_CHILD,
WRITE_DAC, WRITE_OWNER, GENERIC_ALL and raw GENERIC_WRITE still fail. All actual
reparse objects fail. This is a future L4 qualification obligation, not reuse
of L3's two admitted tuples or a claim that today's host is qualified.

Capture an invocation-private ledger covering root/ancestors, volume/mount,
staging root, final-name binding and each created member's identity, security,
filesystem and exact type. Hold original evidence, including identities for
objects whose handles may later be deliberately quiesced. Reopening a path is
not sameness proof. Access controls must exclude untrusted mutation throughout
the check-to-primitive interval; cooperating writers use only their own staging.
Hostile kernel/administrator/equivalent-owner credentials are outside this
access-boundary guarantee. A hash scan alone is not a concurrency lock.

## 6. Existing Final and Closed Inventory

Before any staging creation, inspect the exact final target read-only:

- Absent with safe parent: continue to exclusive staging.
- Present and fully verified equivalent: return EXISTING_EQUIVALENT with
  created_new_build=false; no staging or rewrite.
- Present but corrupt/conflicting/incomplete/unsafe: FAILED_PRECOMMIT; leave it
  untouched and do not create staging.

Equivalent means the strict L4 reader proves the artifact ID, complete physical
integrity, exact source/evidence/receipt bindings, schedule_content_id,
schedule_pin_id, scope/date range/archive clock and exact requested logical
authority. Every canonical member must agree with the requested immutable
facts. Unlike a mutable operational view, a different acquisition/receipt or
artifact identity cannot be treated as a timestamp winner. No repair,
quarantine, overwrite, final deletion or permission change is permitted.

The final and complete staged artifact contain exactly six files, no children
directories:

```text
schedule.json
source_snapshot.json
coverage_evidence.json
verification_receipt.json
manifest.json
_SUCCESS
```

No extras, hidden children, streams, case aliases or subsets at publication.
_SUCCESS is a single-link regular file of exactly zero bytes. All JSON and
manifest rules, canonical bytes, source/evidence/signature/completion checks,
resource bounds and logical schedule validation remain exactly L4.1. The seal
covers all six members, including manifest and marker despite their exclusion
from manifest.output_files. Paths and native object IDs never enter logical
schedule/source/artifact content identities.

## 7. Seal and Preparation Order

Only complete private staging verification may issue a private immutable
single-use publication seal. Bind at least:

- owner/invocation and schedule_artifact_id;
- exact root/staging/final names and held root/ancestor/staging identities;
- filesystem/volume/mount and security/type evidence;
- exact sorted six-file inventory, roles, member identities, sizes and SHA256;
- exact manifest bytes/hash and exact empty _SUCCESS bytes/hash;
- source_snapshot_id/source_content_hash, coverage_completion_evidence_id;
- schedule_content_id, schedule_pin_id and exact verification-receipt bytes/hash
  plus the verified signature/contract/declaration bindings from L4.1.

The seal captures the verifier's admitted physical facts, not an unchecked
later reread. Drift between private verification and seal construction fails.
Only the current owner may use that exact issued seal; at most one primitive
attempt may consume it. A failed attempt never permits resealing/retrying in
the same invocation. Ownership alone cannot reach the primitive.

Exact order:

1. Validate explicit immutable input facts, root/platform/ancestry and final;
   finish existing-final admission before any staging mutation.
2. Exclusively create sibling private staging and capture its ownership.
3. Exclusively write the four data/evidence JSON files, then manifest.json;
   capture each object and close content-write handles.
4. Fully verify private staging without marker: exactly those five members,
   all L4.1 semantic and physical checks, with only staging-name/absent-marker
   differences from final verification.
5. Exclusively create empty _SUCCESS and close its write handle.
6. Fully verify all six members and issue the private seal from admitted facts.
7. Immediately revalidate every seal/safety fact and the target state.
8. If final appeared, take the read-only winner path without quiescence.
   Otherwise Windows alone checked-closes descendants, retaining staging root
   and scope handles, and immediately enters the single no-replace primitive.
9. Success is COMMITTED_UNVERIFIED; irrevocably revoke staging cleanup authority.
10. Invoke the strict final reader, including fresh final-path evidence, its
    second physical closure and comparison with requested authority.
11. Only successful final verification returns VERIFIED_FINAL.

No provider/network/current-time call, callback, await, sleep, serialization,
permission change or content write occurs between final revalidation and the
primitive. The protected namespace, not an arbitrary time limit, bounds this
interval. Marker creation, a manifest and a seal are NOT commit points.

## 8. Complete State Machine

States are invocation-local to this L4 operation; similarly spelled L3 states
convey no authority here. Initial state is PREFLIGHT. Terminal states are
VERIFIED_FINAL, EXISTING_EQUIVALENT, FAILED_PRECOMMIT, COMMITTED_INVALID and
PUBLICATION_UNCERTAIN. Every transition is classified below.

| Code | State |
| --- | --- |
| P | PREFLIGHT |
| W | PRIVATE_STAGING |
| S | SEALED |
| C | COMMITTED_UNVERIFIED |
| V | VERIFIED_FINAL |
| E | EXISTING_EQUIVALENT |
| F | FAILED_PRECOMMIT |
| I | COMMITTED_INVALID |
| U | PUBLICATION_UNCERTAIN |

Rows are FROM, columns TO. A means allowed only under the predicates below;
X means forbidden. This matrix enumerates all 81 ordered pairs (11 A, 70 X).
The JSON lists the identical 11 allowed and all 70 forbidden pairs explicitly.
Remaining in a state during private bookkeeping is not a self-transition.

| FROM / TO | P | W | S | C | V | E | F | I | U |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P | X | A | X | X | X | A | A | X | X |
| W | X | X | A | X | X | X | A | X | X |
| S | X | X | X | A | X | A | A | X | A |
| C | X | X | X | X | A | X | X | A | X |
| V | X | X | X | X | X | X | X | X | X |
| E | X | X | X | X | X | X | X | X | X |
| F | X | X | X | X | X | X | X | X | X |
| I | X | X | X | X | X | X | X | X | X |
| U | X | X | X | X | X | X | X | X | X |

| Allowed pair | Necessary condition |
| --- | --- |
| P -> W | Inputs/root/platform safe, final absent, exclusive staging created with ownership |
| P -> E | Existing equivalent fully verified read-only, no staging |
| P -> F | Preflight/refused existing final or creation/ownership-capture failure; only proven newly owned residue is cleanup eligible |
| W -> S | Complete six-file private verification and issued seal |
| W -> F | Preparation fails; at most one current-owned partial staging cleanup |
| S -> C | One qualified no-replace primitive positively reports success; revoke cleanup |
| S -> E | Late-existing/race winner fully verified equivalent AND own staging cleanup succeeds |
| S -> F | Seal drift, partial quiescence failure, known noncommit failure or invalid winner; only proven uncommitted cleanup, otherwise report residue |
| S -> U | Primitive outcome ambiguous, including interruption across the success-return/state-recording boundary; revoke cleanup without probing destructively |
| C -> V | Strict final reader plus second closure and requested-authority comparison succeed |
| C -> I | Final verification/return preparation fails after known commit; preserve final |

All other jumps, terminal retries, resets, resealing and rollback are forbidden.
Private windows_descendants_quiesced and cleanup_attempted flags are not public
states or authority. A one-shot pending cleanup may finish while reporting
FAILED_PRECOMMIT without changing that terminal state. Retrying the operation
always means a new invocation beginning at P with read-only final admission.

## 9. Windows Quiescence and No-Replace Publication

Exactly one os.rename(staging, final) call site is permitted, only inside the
bound Windows helper and on an independently exact-tuple-qualified platform.
Native tests must prove existing empty and nonempty destinations are refused.
No os.replace, Path.replace, Path.rename, shutil.move, alternate MoveFileEx
wrapper, copy/delete, delete/rename, retry-overwrite or reboot-delayed move.

After full seal revalidation and a fresh absent-final proof, while SEALED:

- Preserve all scope/output-root/ancestor handles and the staging-root handle.
- Mark the owner as quiescence-started before the first close; checked-close
  every retained descendant (all six member files and any redundant descendant
  handle). Do not retain unnoticed write/verification handles into this tree.
- Require each handle valid; CloseHandle must succeed before marking it closed.
- A failed close, including a partial sequence, makes primitive count zero.
- Successful quiescence goes immediately to os.rename, with no user hook.

The open staging-root handle retains FileIdInfo/volume/security/non-reparse
authority. Closing that root to make rename succeed is forbidden. On successful
rename, never reacquire the old staging descendants; the final reader must
acquire independent final-path evidence.

Only the exact, independently qualified destination-exists error mapping may
prove a race noncommit (native ERROR_FILE_EXISTS=80 or
ERROR_ALREADY_EXISTS=183 when the exact primitive reports it). Do not interpret
generic AccessDenied/WinError 5 or path errors as collision or cleanup authority.
All other ambiguous primitive exceptions, including interrupted completion,
yield PUBLICATION_FAILED / PUBLICATION_UNCERTAIN. No rebind, rmtree, rollback,
final mutation or destructive recovery probe. Read-only recovery is allowed.

## 10. Windows Cleanup-Evidence Rebind

Rebind is Windows-only, private, non-enrolling and non-publishing. Eligibility:
genuine current invocation; SEALED or FAILED_PRECOMMIT; deliberate full/partial
quiescence; current seal; staging root still open and unchanged; known noncommit;
no uncertain/successful publication and no prior cleanup attempt.

For a destination race, verify the winner read-only first (valid equivalent or
invalid). Partial-close failure has no winner prerequisite because rename was
never entered. Then:

1. Recheck held scope/ancestors/staging root and their security/volume binding.
2. For each closed descendant, reopen via native scope.member(old.path,
   directory=old.directory). Require exact original identity, filesystem,
   security and type plus fresh recheck, single-link and no-reparse/stream proof.
   Still-open descendants are rechecked against the same original record.
3. Build replacement handles in a temporary local collection. Do not replace
   owner ledger entries incrementally or rebaseline original facts.
4. Require complete exact six-file inventory and the original binding; a
   missing/replaced/extra member, security drift or proof failure refuses all.
5. Only when EVERY record matches, install the replacements together; require
   owner binding == original seal binding and run normal complete owner check
   again before declaring cleanup authority restored.

On failure, close provisional handles, preserve originals/baseline and residue,
report CLEANUP_REFUSED; never call rmtree. Identical bytes at a different FileId
are not the original object. No ACL/chmod repair. Path existence cannot restore
authority. Successful rebind restores cleanup only, never seal reuse or another
publication attempt. Linux retains descriptors and does not use this process.

## 11. One-Shot Cleanup and Race Outcomes

The sole recursive destructive primitive is one shutil.rmtree(owner.path)
call site in _remove_tree. It accepts genuine private ownership, never a raw
caller path. Only current-invocation, uncommitted, still-proven staging qualifies.
_remove_tree must perform required Windows rebind BEFORE its normal owner check.

Before rmtree revalidate ancestry/root, staging identity and security, same
filesystem, every owned member and exact extant inventory. A preparation failure
may have fewer than six files only if the actual inventory equals the current
exclusive-creation ledger. Missing already-owned objects or unowned extras fail;
partial creation is not arbitrary-subset cleanup. Content completeness/seal
issuance is not required for cleanup before sealing, but ownership always is.

Set cleanup_attempted=true before the destructive attempt and never retry.
Where native handles must be closed for removal, finish ownership validation
first, checked-close only own staging/member handles, retain scope protection
and immediately enter rmtree with no hook or write. Close failure refuses
removal. Do not ignore errors, supply chmod/onerror repair or retry after partial
removal. Record residual paths only as diagnostics, never new cleanup authority.

A known race loser may return EXISTING_EQUIVALENT / created_new_build=false
only after BOTH strict winner equivalence and its own successful cleanup.
Invalid/conflicting winner stays untouched; own cleanup still requires the same
proof. Rebind/cleanup failure reports FAILED_PRECOMMIT with CLEANUP_REFUSED or
CLEANUP_FAILED and residue, preserving the original error/winner result. Never
report idempotent success while suppressing an unowned or unremoved residue.

No adoption/sweep of historical staging, parent/final deletion, quarantine,
permission escalation or security repair. permanent_deletion.supported=false:
owned private precommit cleanup is internal failure handling, not a facility
to delete committed artifacts or existing user assets.

## 12. Linux Native Boundary

Use exactly one direct renameat2(root_fd, staging_name, root_fd, final_name,
RENAME_NOREPLACE=1) inside the bound native helper. root_fd is the retained
output-root descriptor; both names are single validated sibling components.
No pathname fallback, absolute native target, ordinary rename/renameat,
RENAME_EXCHANGE/WHITEOUT, copy/delete or alternate syscall dispatch.

| Exact outcome | Required handling |
| --- | --- |
| Success | C; irrevocably revoke staging cleanup before final reader |
| EEXIST | Known destination collision; winner read-only verification, then only owned loser cleanup |
| ENOTEMPTY | Collision only after fresh safe final-object proof; without it, fail closed without assuming a winner |
| EXDEV | Known noncommit filesystem mismatch; fail, never copy; cleanup only if all original ownership/filesystem proofs still pass |
| ENOSYS/EINVAL/ENOTSUP/EOPNOTSUPP or missing symbol | Unsupported platform; no alternative primitive; at most proven precommit cleanup |
| Other demonstrated noncommit native errno | Fail without fallback; cleanup still needs complete ownership proof |
| Interrupted/unclassifiable outcome | U; no cleanup or destructive recovery |

Known errno classification is allowed only from a definite syscall failure,
not an exception after the physical operation may have completed. Permission
failures are not a reason to change permissions. Keep all Linux retained object
descriptors through publication; no Windows-style quiescence.

## 13. Final Verification, Crash and Retry

The only physical commit point is successful qualified atomic no-replace
directory publication. _SUCCESS, manifest and seal do not commit. Record C and
revoke cleanup immediately; interruption across the primitive/state boundary
is U if success cannot be positively established. Physical visibility does
not promise universal power-loss persistence; exact platform qualification
must state durability limits. Restart always requires full read-only checks.

After known commit, invoke the strict L4 reader against FINAL, not the old
staging path. It reacquires physical identities, checks all six files and full
L4.1 semantics, then repeats its second ancestry/inventory/object/byte closure.
Compare artifact/source/evidence/receipt/schedule IDs and requested authority.
Only this produces V / created_new_build=true. Reader failure is
FINAL_VERIFICATION_FAILED / COMMITTED_INVALID; final remains untouched.

| Crash/fault checkpoint | Required behavior |
| --- | --- |
| Before staging | No owned tree; no cleanup target |
| During member writes | Only exact current ledger may permit one cleanup attempt; lost invocation leaves unadoptable residue |
| After four data/evidence files | No published authority; same current-owned partial cleanup rule |
| After manifest | Still private; five-file verification is not publication authority |
| After _SUCCESS | Six-file marker is not commit; complete verification still required |
| After seal | Still private; seal cannot authorize retry or future-invocation cleanup |
| Immediately before primitive, including partial quiescence | If known not entered, only ownership/rebind-proven cleanup; never infer noncommit from pathname alone |
| During primitive ambiguity | U; no rebind/removal; read-only inspection only |
| Immediately after successful primitive | C when success known, otherwise U; no rollback in either case |
| During final verification | Known commit remains immutable; failure I; process loss returns no verified success |

A new invocation after any crash/retry checks final first. Valid equivalent
returns read-only; invalid/conflicting/unsafe fails untouched. No regeneration
of marker/manifest, rewriting, relocation or permission changes. New invocation
never adopts/deletes prior residue, even when names, IDs or process metadata
appear familiar. No same-invocation second rename or cleanup retry.

## 14. Independent Platform Qualification and Failure Envelope

No L4 platform is qualified here. L3's two production native tuples do not
authorize L4 reader, writer, cleanup or primitive use. Future acceptance needs
exact-code, exact-tuple, real native evidence, independently reviewed before
admission; mocks, family names, version ranges and environment bypasses are
not qualification. Record OS/build/kernel, CPU, Python, native API/libc,
filesystem/options, volume/mount and security-policy evidence. Unknown or
unprovable tuples are UNSUPPORTED_FAIL_CLOSED.

Windows qualification must demonstrate FileIdInfo, native single-link/stream
proof, protected ancestry/root classification, checked descendant quiescence
with staging root retained, real no-replace collision/race behavior, exact
cleanup rebind and final-reader closure. Linux independently needs retained-fd
and statx evidence, actual flag-1 syscall/collision/errno behavior and the same
full writer/reader invariants. No inferred cross-platform qualification.

Future failure reporting must retain reason, publication state, original cause
and any secondary cleanup error/residue. Freeze boundary reasons:
INPUT_AUTHORITY, PLATFORM_UNQUALIFIED, UNSAFE_PATH, FILESYSTEM_MISMATCH,
INVENTORY_MISMATCH, OWNERSHIP_MISMATCH, SEAL_INVALID, PREPUBLICATION_DRIFT,
QUIESCENCE_FAILED, EXISTING_FINAL_INVALID, PUBLICATION_FAILED,
FINAL_VERIFICATION_FAILED, CLEANUP_REFUSED, CLEANUP_FAILED. Preserve specific
L4.1 reader reasons as causes; do not translate failures into schedule statuses,
source truth, Label INCOMPLETE or successful partial artifacts. No plan/UI
confirmation substitutes for fresh input/owner/seal validation.

## 15. Future Implementation Canaries

All are DESIGN-DEFINED / RUNTIME-DEFERRED. This PR claims none as native PASS.
They supplement, not rewrite, L4.1 or historical L3 canaries/results.

| ID | Required future evidence |
| --- | --- |
| SP-01 | Absent-target complete publication, strict final reader and second closure succeed |
| SP-02 | Existing equivalent returns without staging/writes; exact requested authority checked |
| SP-03 | Existing corrupt/conflicting/unsafe final fails untouched without staging |
| SP-04 | Simultaneous equivalent full creators: one winner, verified loser, proven loser cleanup |
| SP-05 | Simultaneous conflicting creators preserve winner; no overwrite or hidden residue |
| SP-06 | Real Windows existing empty/nonempty destinations refused unchanged |
| SP-07 | Linux EEXIST and ENOTEMPTY safe-proof classification, EXDEV and unsupported errnos have no fallback |
| SP-08 | Symlink/junction/all reparse objects rejected throughout ancestry and membership |
| SP-09 | Real native hard-link rejection; no Windows DirEntry link-count authority |
| SP-10 | ADS/named stream and path alias rejection |
| SP-11 | Mount/bind-mount/volume transition and unsafe access rejected |
| SP-12 | Staging-root substitution refuses publication and cleanup |
| SP-13 | Identical-byte member replacement detected by native identity |
| SP-14 | Security drift refuses publication/rebind/cleanup; no permission repair |
| SP-15 | Extra or hidden/case-aliased member refuses seal/publication/cleanup |
| SP-16 | Missing member refuses seal/publication; cleanup requires exact owned partial-creation ledger |
| SP-17 | Manifest tamper, same-size source/evidence/receipt change and hash drift fail |
| SP-18 | _SUCCESS missing/nonempty/replaced fails; marker alone never authorizes commit |
| SP-19 | Checked-close failure gives zero rename calls, including failure after some closes |
| SP-20 | Partial Windows quiescence rebind matches all original records and safely cleans |
| SP-21 | Partial rebind identity/security/filesystem/type mismatch leaves residue without rmtree |
| SP-22 | Race-loser rebind is all-or-nothing; winner unchanged; success requires own cleanup |
| SP-23 | Ambiguous committed interruption yields U, no rebind/rmtree/final mutation |
| SP-24 | Crash after successful primitive never rolls back; read-only retry |
| SP-25 | Final reader failure preserves final and reports I |
| SP-26 | Relocation changes no artifact/source/evidence/logical schedule identity |
| SP-27 | Zero provider/network/OpenD/current-time/mutable-Catalog fallback |
| SP-28 | Foreign/forged/reused/copied seals and raw-path cleanup inputs rejected |
| SP-29 | Exactly one os.rename, one rmtree, one flag-1 native call site; unchanged BASE contract required |
| SP-30 | One-shot partial cleanup failure reports residue; no retry/ignore/chmod/sweep |
| SP-31 | All 81 state pairs enforced; no reseal, terminal restart or authority transfer |
| SP-32 | Independently qualified L4 exact tuples only; L3 admission and mocks insufficient |
| SP-33 | Snapshot capture/seal drift and caller mutation cannot enter artifact bytes |
| SP-34 | Unqualified source/keys/clock/completion fail input admission despite physical capability |
| SP-35 | Every crash checkpoint in section 13 preserves ownership/commit distinction |

Future tests must distinguish real native evidence from fault injection and
cannot turn skipped/unknown-platform cases into qualification. An implementation
PR must not weaken tests/checker/contracts to obtain any PASS.

## 16. Validation, Exclusions and Stop

Only this Markdown and its companion JSON are added. Run diff --check,
repository hygiene, release checker and destructive gate in repository and
exact-base pull-request modes. Expected version 0.8.0 and inventory 7/16/44.
Natural exact-head CI chooses its tier; no forced FULL or runtime-suite claim.
One normal design commit, one DRAFT PR, no amend, force push or merge.

No src/tests/scripts/.github/version/checker/exemption or L3 modification.
No schedule reader/writer, provider capture, key registry, production source
profile, OpenD/provider run, Catalog/CLI integration, migration, repair or
release/deployment. No host restart/shutdown/logoff/sleep/hibernate, feature,
BIOS/UEFI/bcdedit, ACL, network, RDP or firewall change.

```text
L4_RUNTIME_IMPLEMENTATION_AUTHORIZED=false
L4_PROVIDER_PRODUCTION_QUALIFICATION_AUTHORIZED=false
MERGE_AUTHORIZED=false
```

Stop after natural CI for independent semantic/destructive review. Only a
separate later work order may authorize implementation from an exact BASE
already containing the independently approved unchanged contract.
