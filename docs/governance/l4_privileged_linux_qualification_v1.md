# L4 Privileged Linux Qualification Fixture Contract V1

## 1. Design Status and Authority

DESIGN / GOVERNANCE ONLY. This document freezes the design of the privileged
Linux qualification fixture for the L4 trading-day schedule artifact reader. It
implements no runtime, adds no test, changes no workflow, mutates no registry
and qualifies no platform tuple. Everything below describes work that a later,
separately authorized implementation PR must perform.

```text
DESIGN_ONLY=true
IMPLEMENTATION_AUTHORIZED=false
PRIVILEGED_EXECUTION_AUTHORIZED=false
CI_WORKFLOW_CHANGE_AUTHORIZED=false
PRODUCTION_CHANGE_AUTHORIZED=false
REGISTRY_ADMISSION_AUTHORIZED=false
MERGE_AUTHORIZED=false
DESIGN_DOCUMENT_AUTHORIZED=true
```

Requirements and authorizations are separate facts and are never collapsed into
one another. The later A3 implementation phase requires authority this design
does not hold, and requires nothing this design does hold beyond its own text:

```text
NEW_PUBLIC_API_REQUIRED=false
PRIVILEGED_EXECUTION_AUTHORITY_REQUIRED=true
CI_CONTROL_PLANE_CHANGE_AUTHORITY_REQUIRED=true
REGISTRY_ADMISSION_AUTHORITY_REQUIRED_IN_A3=false
PRODUCTION_CHANGE_AUTHORITY_REQUIRED_IN_A3=false
```

`PRIVILEGED_EXECUTION_AUTHORITY_REQUIRED=true` and
`CI_CONTROL_PLANE_CHANGE_AUTHORITY_REQUIRED=true` are requirements of the later
implementation phase, which is separately authorized. They are NOT granted by
this design document: `PRIVILEGED_EXECUTION_AUTHORIZED=false` and
`CI_WORKFLOW_CHANGE_AUTHORIZED=false` above remain the states of this PR, and no
statement in this document may be read as pre-approving either grant.

This design incorporates the corrections recorded by the independent A3
discovery review:

```text
A3_DISCOVERY_INDEPENDENT_REVIEW=PASS_WITH_CORRECTIONS
```

The corrections are normative here, not commentary:

- 0644 mode semantics are stated exactly; the fixture MUST NOT claim that the
  post-chown privileged owner is non-writable, and MUST NOT use 0600.
- The remaining RQP-L17 row is restated as representation drift, not as a
  proven statx mount-id change.
- `L105` remains a defensive fail-closed invariant; its real trigger is not
  known constructible.
- No file-descriptor-passing-via-sudo mechanism is frozen, because its
  implementability is not proved.
- The existing `ci.yml` formal topology is preserved exactly; privileged
  qualification is a separate workflow.

Scope of this PR is exactly one new document:

```text
ADDED_FILE=docs/governance/l4_privileged_linux_qualification_v1.md
FORBIDDEN_CHANGES=src/**,tests/**,scripts/**,.github/**,ci/**,AGENTS.md
EXECUTABLE_PRIVILEGED_CODE=0
```

The design is the predecessor authority for a later implementation PR. That
implementation PR's base commit MUST already contain this document unchanged.
Material redesign of any frozen token requires another design-only review before
implementation; the frozen tokens are not advisory.

### 1.1 Remediation round 1

The first exact-head A3 design review failed the previous head with
`FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE`, and the failure is preserved
here rather than rewritten:

```text
FIRST_A3D_REVIEW_FAILED_HEAD=777a509c5d144deaf4c06a432cddb992b86a28b6
FIRST_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
A3D_REMEDIATION_ROUND=1
```

Its four findings are corrected in this document:

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | The helper protocol contradicted itself: the helper simultaneously had to reject caller-supplied path/uid/mode and to receive the root path, child name, target uid and mode as an explicit handoff. | 5.1-5.4 |
| 2 | The process and namespace topology was asserted rather than frozen: no explicit roles, no ordered lifecycle, and namespace sharing was assumed from `sudo` rather than measured. | 10.1-10.2 |
| 3 | Cleanup required a second unconditional unmount after a successful `MNT_DETACH`, which has no object to act on and is therefore not implementable. | 10.4 |
| 4 | The authority preview collapsed distinct facts into "Is new public API or authority required? No.", hiding the privileged execution and CI control-plane authorities the later implementation phase needs. | 1 and 17 |

`CONTRACT_IMPLEMENTABILITY_FAILURE` is recorded as a design-document failure of
this contract, not as a production defect: no production code was involved, and
none is changed by this remediation.

## 2. Exact Base Record

The checked-in Exact Base procedure
([DEVELOPMENT_PLAYBOOK.md](DEVELOPMENT_PLAYBOOK.md) section 1.1,
[AGENT_HANDOFF.md](AGENT_HANDOFF.md) rule 3) was executed for this PR: switch
`main`, fresh fetch of `origin` with prune and tags, `pull --ff-only`, then
verification of `HEAD`, `origin/main`, tree and tracked worktree state.

```text
BASE_MAIN_SHA=7fc8c1395d01bc4f612291fcdf098703a3866dcd
BASE_MAIN_TREE=bc9ac7c846b271eb48adce1a0343276983e1008c
BASE_HEAD_EQUALS_ORIGIN_MAIN=true
TRACKED_WORKTREE_CLEAN=true
```

Transport record. The HTTPS transport on this host fails with
`schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS
(0x8009030e)`. That failure does not waive the procedure. Remote truth was
established through the reviewed confined SSH transport:

- an environment-local `GIT_SSH` shim stored outside every repository and
  worktree, invoking exactly
  `C:/Windows/System32/OpenSSH/ssh.exe` with
  `-i C:/Users/Administrator/.ssh/marketvault_github_ed25519_v2`,
  `-o IdentitiesOnly=yes`, `-o BatchMode=yes`,
  `-o StrictHostKeyChecking=yes` and
  `-o UserKnownHostsFile=C:/Users/Administrator/.ssh/known_hosts`;
- `GIT_SSH_VARIANT=ssh` in the same environment so the shim is driven as the
  OpenSSH client it wraps;
- a command-local URL rewrite
  `-c url.ssh://git@github.com/.insteadOf=https://github.com/` for the
  `origin` commands
  (`git ... fetch origin --prune --tags` and
  `git ... pull --ff-only origin main`), so `remote.origin.url` is never
  modified;
- no `GIT_SSH_COMMAND`, no `git remote set-url`, no persistent git
  configuration mutation, no host-key relaxation.

Governance note. An earlier discovery invocation reached the same state with
`fetch` plus `merge --ff-only` after transport recovery. That substitution is
NOT promoted into the development procedure. The standing requirement is the
checked-in sequence with real `pull --ff-only` semantics, which is what this PR
executed.

## 3. Frozen Production Surface

This design is a contract about specific existing guards. The following facts
are the entire production surface it binds; no other production behavior is
covered, and none of it is changed.

| Symbol | Location | Frozen behavior |
| --- | --- | --- |
| `_permissions` owner policy | `src/market_vault/schedule_artifact/_linux.py` L109-L118, owner guard at L110 | `_require(data.st_uid in (0, os.geteuid()), "UNSAFE_PATH", "untrusted Linux object owner")` |
| `_permissions` mutation policy | same, L111-L113 | group/world write bits (`st_mode & 0o022`) are rejected unless the object is a sticky directory acting as an ancestor |
| `_permissions` attribute policy | same, L114-L117 | any POSIX ACL or any extended attribute is rejected as unqualified |
| `_mount_id` | same, L53-L60 | real `statx` mount/inode identity; requires the mount-id mask bit, nonzero mount id and nonzero inode, else `PLATFORM_UNQUALIFIED` |
| `_mount_description` | same, L72-L95 | bounded complete mount table, one `-` separator per record, `separator >= 6`, exactly three fields after the separator; `PLATFORM_UNQUALIFIED` detail `held mount missing or ambiguous` when the held mount id matches zero or several records (L84-L85) |
| `_mount_description` ext4/root/device rule | same, L88-L90 | matching record field 2 equals the observed device, field 3 is exactly `/`, the filesystem type is exactly `ext4`, and that device appears in exactly one record of the whole table, else `PLATFORM_UNQUALIFIED` detail `non-ext4 or bind-mount ambiguity` |
| `_mount_description` write policy | same, L93-L94 | `rw` must be present in the mount options and in the super options, and `ro` must be absent from both, else `PLATFORM_UNQUALIFIED` detail `read-only mount` |
| `_ext4_capability` | same, L98-L106 | `fstat(fd)`, first `_mount_id(fd)`, real `/proc/self/mountinfo` read, `_mount_description(...)`, then the L105 drift recheck; returns `("ext4", mount_options, super_options)` |
| `L105` drift invariant | same, L105 | `_require(_mount_id(fd) == before, "UNSAFE_PATH", "mount identity drift")` — a defensive fail-closed invariant |
| `_LinuxObject` | same, L121-L175 | no-follow retained descriptor opened with `O_RDONLY\|O_NOFOLLOW\|O_CLOEXEC\|O_NONBLOCK` (L130), single-link regular files only (L145), retained facts `(identity, filesystem, security, size)` (L141-L147), `recheck()` re-derives and re-opens the same path (L149-L156) |
| `_NativeScope` ancestry binding | `src/market_vault/schedule_artifact/_physical.py` L32-L42 | every retained ancestor from the filesystem root down to the artifact parent must carry an identical filesystem tuple, else `UNSAFE_PATH` detail `ancestry mount/volume transition` (L37-L38); Linux additionally requires the `0xef53` ext4 magic (L41) and computes `mount_description` through `_ext4_capability` (L42) |
| `_NativeScope.recheck` | same, L69-L72 | `_ext4_capability` must reproduce the retained mount description, else `PHYSICAL_DRIFT` detail `mount description changed` |
| L4 capability registry | `src/market_vault/schedule_artifact/_platform.py` L10 | `_QUALIFIED_CAPABILITIES = frozenset()` |
| L4 capability assembly | same, L22-L33 | the ten-field Linux tuple, whose eighth field is the `_ext4_capability` triple and whose ninth field is `l4-schedule-readonly-statx-ext4-v1` |
| L4 admission | same, L37-L40 | exact membership in `_QUALIFIED_CAPABILITIES`, else `PLATFORM_UNQUALIFIED` detail `unqualified exact L4 native capability: ...` |
| Reason vocabulary | `src/market_vault/schedule_artifact/_errors.py` L4-L11 | `UNSAFE_PATH`, `PLATFORM_UNQUALIFIED` and `PHYSICAL_DRIFT` are admitted reason codes |
| Error transport | same, L14-L26 | `_ScheduleArtifactError.reason_code` is an attribute; the message is `reason_code + ": " + detail` |

Existing ordinary evidence surface, which this design extends without editing:

| Surface | Location | Current state |
| --- | --- | --- |
| RQP-L09 case registry | `tests/test_schedule_artifact_native_guards.py` L1351-L1366 | twelve declared cases; `XATTR`, `POSIX_ACL`, `FOREIGN_OWNER`, `ROOT_OWNED` are the conditional gap cases |
| RQP-L09 ownership fixture | same, L1747-L1768 | real `os.chown`, no privilege escalation, kernel refusal recorded verbatim as a gap |
| RQP-L09 foreign/root cases | same, L1772-L1803 | expect `UNSAFE_PATH` / `untrusted Linux object owner` and `held.security[0] == 0` |
| RQP-L17 status | same, L1820-L1871 | `GAP`; read-only feasibility probe, zero mount operations |
| Privilege static guards | same, L2954-L3008 | no sudo/doas/pkexec, no installer, `chown` confined to the ownership helper, feasibility probe stays read-only |
| L4 candidate tuple | `tests/test_schedule_artifact_platform.py` | ten-field literal, temporary enrollment only, production registry asserted empty (L272-L276) |
| Ordinary collection scope | `pyproject.toml` `[tool.pytest.ini_options]` | `testpaths = ["tests"]` with default `python_files = test_*.py` |
| Formal CI topology | `.github/workflows/ci.yml` | exactly three formal jobs: `test`, `portability-pyarrow24`, `package` |

## 4. Freeze: RQP-L09 Foreign-Owner and Root-Owned Cases

```text
RQP_L09_FOREIGN_OWNER_TARGET=_permissions owner-policy rejection
RQP_L09_ROOT_OWNED_TARGET=_permissions literal uid-0 admission with geteuid != 0
FILE_MODE=0644
FILE_CHOWN_ONLY=true
PARENT_DIRECTORY_CHOWN=false
```

### 4.1 Exact mode semantics

`0644` is a literal octal mode (`stat.S_IMODE == 0o644`) and means:

| Class | Bits | Meaning |
| --- | --- | --- |
| owner | `rw` | read and write |
| group | `r` | read only |
| other | `r` | read only |

After the privileged `chown`, the observable consequences are frozen as:

- an ordinary non-root reader can read the object;
- an ordinary reader cannot write the object;
- group and world write bits remain clear;
- the privileged owner may retain owner-write.

That last property is intentional. `0644` does not make the new owner
non-writable, and this contract MUST NOT claim that it does. The decisive guard
for the foreign-owner case is the owner policy at L110, which is exactly what
`0644` isolates: because `0o644 & 0o022 == 0`, the mutation policy at L111-L113
cannot fire, and because the attribute set is empty, the attribute policy at
L114-L117 cannot fire.

`0600` MUST NOT be used. With `0600` owned by another user, an ordinary
non-root reader cannot open the object at all, so the observed failure would be
a read-permission artifact rather than the owner-policy rejection the case
claims; for the root-owned case it would make the required admission
unreachable. `FILE_MODE=0644` is therefore a correctness requirement of both
cases, not a convenience.

### 4.2 Frozen mutation scope

Ownership mutation is confined to the single fixture file:

```text
FILE_CHOWN_ONLY=true
PARENT_DIRECTORY_CHOWN=false
```

The parent directory stays invocation-owned by the ordinary runner. This keeps
ancestor traversal authority with the ordinary process, so a failure can never
be explained by traversal denial, and it keeps the privileged mutation set as
small as the case allows.

The invocation-specific root and fixture parent MUST also be created with group
and world write bits clear (`mode & 0o022 == 0`, for example `0700`), so
ancestor admission goes through the ordinary non-writable path at L111-L113
rather than through the sticky-directory ancestor exception at L112. This
contract neither widens that exception nor depends on it, and no fixture step
may chmod an ancestor to make a case settle.

No fixture step may chown, chmod, ACL, or otherwise repair any object outside
the invocation-specific fixture directory, and no repository, worktree, cache,
runtime-data or pre-existing host path may be touched.

### 4.3 Required paired real controls

Both cases are real-kernel evidence. Before the production call is made, the
future privileged fixture MUST establish and record all of the following real
controls, and MUST record the measured values rather than asserting them from
expectation:

```text
CONTROL_geteuid_ne_target_uid=true
CONTROL_lstat_st_uid_eq_target_uid=true
CONTROL_mode_eq_0644=true
CONTROL_mode_and_0o022_eq_0=true
CONTROL_real_os_open_O_RDONLY_succeeds=true
```

The last control is the attribution guard. `_LinuxObject.__init__` calls
`os.lstat` and `os.open` (L127-L133) *before* `_facts()` reaches the owner
policy, so without a proven successful ordinary `os.open(O_RDONLY)`, a
failure could be an `EACCES` artifact of mode or traversal rather than the
owner-policy rejection under test. The implementation may additionally mirror
the production flag set (`O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK`, L130); the
plain `O_RDONLY` control is the frozen minimum.

Two further real preconditions are required because other production guards sit
on the same path and would otherwise be indistinguishable from the owner
policy:

```text
FIXTURE_REGULAR_SINGLE_LINK_FILE=true      # L145 requires st_nlink == 1
FIXTURE_XATTR_AND_ACL_SET_EMPTY=true       # L114-L117 reject any attribute
```

If either precondition cannot be established, the case outcome is
`QUALIFICATION_GAP`, never a pass and never a product defect.

### 4.4 Frozen case outcomes

FOREIGN_OWNER. The target uid is nonzero and differs from the ordinary
reader's effective uid, so `st_uid in (0, os.geteuid())` is false. Production
MUST fail specifically with:

```text
reason_code=UNSAFE_PATH
detail contains "untrusted Linux object owner"
```

The observation point is `_linux._LinuxObject(path, directory=False)`, which
raises during construction on the path L135 (`_facts()`) -> L146
(`_permissions(...)`) -> L110 (owner guard). A wrong reason code, a wrong
detail, a successful construction, or an `OSError` in place of the contract
error is a failure of the case.

ROOT_OWNED. The target uid is exactly 0 while the ordinary reader's effective
uid is not 0. Production MUST admit the object and the retained security tuple
MUST report the literal root owner:

```text
target_uid=0
ordinary_reader_euid_ne_0=true
production_admits=true
held.security[0] == 0
```

`security` is the retained `(st_uid, st_gid, S_IMODE(st_mode), attributes)` tuple
produced by `_permissions` (L118) and retained by `_LinuxObject._facts()`
(L146); `security[0]` is therefore the literal `st_uid`. The case also proves
that the privileged owner's owner-write bit did not by itself cause a refusal,
which is the mode-semantics correction above.

The relaxed `_ownership_fixture` fallback in the ordinary suite stays exactly
as it is: an ordinary test that cannot chown records a gap. The privileged
fixture does not replace it, does not edit it, and does not convert its gap
into a pass.

## 5. Freeze: Privilege Boundary

The ordinary pytest/evidence process remains non-root. Privilege is used only
by a separately invoked fixed helper, and only for:

- setup ownership mutation (`chown` of the single fixture file);
- cleanup ownership restoration and removal of the invocation-specific fixture
  root;
- the RQP-L17 mount operations that cannot be performed without
  `CAP_SYS_ADMIN`.

No privilege is granted to ordinary pytest, and no fixture case may run its
production call in a privileged process. The production primitive under
qualification is always executed by the non-root evidence process.

A privileged helper MUST:

- operate only beneath one invocation-specific root under the runner temporary
  area, selected by the frozen case table rather than by caller text;
- treat that root path as an untrusted locator and independently revalidate it
  before any mutation;
- derive its target identity, file mode and child names from frozen constants
  and from the selected case name, never from caller input;
- reject a symlinked root or a symlinked path component;
- reject any child name that is not one of its own frozen constants, which
  structurally excludes absolute names, `.`, `..` and multi-component names;
- reject repository and worktree paths;
- reject runtime-data paths (`data/`, `catalog/`, `manifests/`, `reports/` and
  their configured equivalents);
- reject unexpected owner or mode state;
- fail closed on cleanup failure.

The `..`, absolute-name and multi-component rejections are properties of the
frozen derivation rather than separate input checks: because no caller-supplied
child name is ever accepted, no such name can reach the helper in the first
place. They remain required assertions in the implementation, and the helper
MUST additionally assert them against its own derived names.

### 5.1 Frozen helper protocol

This subsection is the single normative statement of the helper's argument
protocol. It supersedes any earlier or looser phrasing in this document: where
another sentence appears to permit the helper to accept a caller-supplied
target identity, target mode, or child name, this subsection governs and the
helper MUST NOT accept it.

The protocol separates three things that an earlier draft conflated:

```text
UNTRUSTED_LOCATOR      the invocation root path (--root)
CASE_ACTION_ENUM       exactly one reviewed case name (--case)
FROZEN_DERIVATION      identity, mode and child name, derived inside the helper
```

Only the first may cross the boundary as caller input, and it crosses as
untrusted data rather than as authority. The second crosses as a closed
enumeration of names. The third never crosses at all.

```text
HELPER_ROOT_BOUNDARY=UNTRUSTED_LOCATOR
HELPER_CASE_SELECTION=CASE_ACTION_ENUM
HELPER_TARGET_IDENTITY_SOURCE=FROZEN_FIXED_CONSTANT
HELPER_FILE_MODE_SOURCE=FROZEN_FIXED_CONSTANT
HELPER_CHILD_NAME_SOURCE=FROZEN_FIXED_CONSTANT
HELPER_ACCEPTS_CALLER_UID=false
HELPER_ACCEPTS_CALLER_GID=false
HELPER_ACCEPTS_CALLER_MODE=false
HELPER_ACCEPTS_CALLER_CHILD_PATH=false
HELPER_ACCEPTS_CALLER_COMMAND=false
HELPER_ACCEPTS_SHELL_FRAGMENT=false
HELPER_ACCEPTS_INHERITED_DESCRIPTOR=false
HELPER_ACCEPTS_ENVIRONMENT_AUTHORITY=false
```

Accepted argument vector, and nothing beyond it:

| Argument | Cardinality | Classification | Validation authority |
| --- | --- | --- | --- |
| `--case=<NAME>` | exactly once, required | `CASE_ACTION_ENUM` | membership in the frozen case table in 5.2; any other value is rejected before any mutation |
| `--root=<PATH>` | exactly once, required | `UNTRUSTED_LOCATOR` | full independent revalidation by the helper under 5.3; the value is data, never authority |

No other argument, switch, environment variable, inherited descriptor, standard
input, shell string, or configuration file may select an action, a target, a
mode, a path, or a scope. Any unrecognized argument is a hard rejection before
any mutation. The helper MUST also refuse to act unless its own effective uid is
the reviewed privileged identity.

```text
HELPER_ARGUMENT_VECTOR_CLOSED=true
HELPER_UNKNOWN_ARGUMENT_OUTCOME=HELPER_ARGUMENT_REJECTED
HELPER_ORDER=reject_arguments_then_validate_root_then_act
```

### 5.2 Frozen derivation, and the qualification gap

The helper derives every privileged effect from the selected case name alone.
Nothing about the caller's environment, working directory, `HOME`, `PATH` or
parent process substitutes for that derivation, and no environment value may
substitute for the caller's `--root` locator either. The one permitted
environment input is the `RUNNER_TEMP` value the caller uses to compose its own
candidate path; that value remains input and never authority, and the helper
still validates the resulting path itself under 5.3.

| `--case` (frozen enum) | Privileged effect | Derived child role | Derived target uid | Derived mode |
| --- | --- | --- | --- | --- |
| `own-foreign` | `chown` the single fixture file to a fixed reviewed foreign uid, then set `0644` | the fixed fixture file under the root (`FIXTURE_FILE_ROLE`) | `FOREIGN_OWNER_TARGET_UID` | `0644` |
| `own-root` | `chown` the single fixture file to uid 0, then set `0644` | the fixed fixture file under the root (`FIXTURE_FILE_ROLE`) | `0` | `0644` |
| `mount-fixture` | create the loop-backed ext4 mount inside the private namespace | the fixed `IMAGE_ROLE`, `MOUNTPOINT_ROLE` and `FIXTURE_FILE_ROLE` under the root | not applicable | not applicable |
| `detach-fixture` | `MNT_DETACH` the fixed fixture mount inside the private namespace | the fixed `MOUNTPOINT_ROLE` under the root | not applicable | not applicable |
| `cleanup` | release the loop backing and remove the fixed fixture objects under the root, following the state machine in 10.4; an ordinary unmount of a still-attached fixture mount is performed only when the observed state is `ATTACHED` | the fixed roles under the root | not applicable | not applicable |

```text
FOREIGN_OWNER_TARGET_UID          = fixed reviewed non-root uid
FOREIGN_OWNER_TARGET_UID_IS_ZERO  = false
ROOT_OWNED_TARGET_UID             = 0
FIXTURE_FILE_CHMOD                = 0644
FIXTURE_FILE_MODE_MASK_CLEAR      = 0o022
FIXTURE_FILE_MODE_IS_EXACT        = true
FIXTURE_FILE_ROLE                 = fixed child name under the invocation root
IMAGE_ROLE                        = fixed child name under the invocation root
MOUNTPOINT_ROLE                   = fixed child name under the invocation root
```

`FOREIGN_OWNER_TARGET_UID` is fixed at implementation time and MUST NOT be a
runtime parameter. Selection rule, which is a requirement and not a preference:

1. the candidate set is the set of uids the host can actually represent that are
   not `0` and not the ordinary runner's effective uid;
2. the implementation selects exactly one member and freezes it as a single
   literal constant in the helper;
3. once frozen, the same literal is used for every invocation and on every run,
   and no invocation, environment value or caller input may change it.

The helper computes this selection itself and MUST NOT read a caller-supplied
substitute for it, including a `SUDO_UID`-style environment value.

```text
FOREIGN_OWNER_TARGET_UID_SELECTION=helper_internal_frozen_literal
FOREIGN_OWNER_TARGET_UID_FROM_CALLER=false
FOREIGN_OWNER_TARGET_UID_FROM_ENVIRONMENT=false
```

If the selected fixed foreign uid equals the ordinary runner's effective uid,
the case is not constructible as designed and the outcome is
`QUALIFICATION_GAP`. This is a required, explicit outcome, not an incidental
one:

```text
FOREIGN_OWNER_UID_EQ_ORDINARY_EUID_OUTCOME=QUALIFICATION_GAP
```

The same outcome applies when the host cannot represent any qualifying uid at
all, and the `ROOT_OWNED` case is likewise `QUALIFICATION_GAP` if the ordinary
runner's effective uid is `0`. A group identity is never caller-supplied either:
the helper leaves `st_gid` as it observed it and reports the observed value.
No fixture step may widen the derived mode, and `FIXTURE_FILE_MODE_IS_EXACT`
forbids any extra permission bit including setuid and setgid.

Both ownership cases derive `0644` on the file only. Neither case may chmod,
chown, or otherwise mutate an ancestor directory: the parent stays
invocation-owned by the ordinary runner per 4.2, and ancestor modes are frozen
at creation rather than repaired by the helper.

```text
HELPER_CHANGES_ANCESTOR_OWNERSHIP=false
HELPER_CHANGES_ANCESTOR_MODE=false
```

### 5.3 Untrusted locator validation

Before its first mutation the helper MUST revalidate `--root` itself, from the
real filesystem, rather than trusting the caller's claim:

- it opens the root with `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` and requires a real
  directory rather than a symlink or a non-directory;
- it requires the root to already exist; the helper never creates its own scope
  from a caller string;
- it requires the root to be invocation-specific and freshly created for this
  run, and requires the observed owner to be the ordinary runner identity with
  `mode & 0o022 == 0`, not a privileged or shared location;
- it resolves and requires the real path to stay beneath the runner temporary
  area, to contain no symlinked component, and to leave the repository,
  worktree, cache, runtime-data and pre-existing host paths untouched;
- it performs every subsequent operation relative to its own validated
  directory descriptor, and never re-resolves the caller's string, so a later
  path substitution cannot redirect the mutation.

An unrecognized argument is rejected before the root is even read; a root that
fails any check is rejected before any mutation. Both are hard refusals with a
distinct non-pass outcome, and neither may be retried with a relaxed check:

```text
HELPER_ROOT_REJECTED=hard_refusal_before_any_mutation
HELPER_ROOT_REVALIDATED_BY_HELPER=true
HELPER_TRUSTS_CALLER_PATH_CLAIM=false
HELPER_ROOT_OWNED_BY_ORDINARY_RUNNER=true
HELPER_CHOWN_TARGET_IS_FIXTURE_FILE_ONLY=true
```

The root stays owned by the ordinary runner, matching 4.2: only the single
fixture file is ever reassigned, and the helper never takes ownership of an
ancestor. A root that is owned by the helper identity, by another user, or by a
shared location is rejected rather than repaired.

Environment state is never authority. `RUNNER_TEMP` may be read as an input
when the *caller* composes its own candidate path, and it may be compared
against the validated root's real location, but no environment value can
authorize an action, widen the derived constants in 5.2, or substitute for the
helper's own validation.

```text
RUNNER_TEMP_IS_INPUT=true
RUNNER_TEMP_IS_AUTHORITY=false
EVERY_PATH_FACT_INDEPENDENTLY_VALIDATED=true
```

### 5.4 No fd-passing requirement

File-descriptor passing across the `sudo` boundary is NOT an accepted
requirement of this contract and MUST NOT be frozen as one. `sudo` commonly
closes nonstandard descriptors, so "the directory descriptor crosses the sudo
boundary" is not currently provable. The implementation may instead reopen the
fixed `RUNNER_TEMP` root safely inside the privileged helper and operate
relative to its own validated descriptor. Either way, the helper revalidates the
root itself; it never trusts inherited state.

### 5.5 Privileged-boundary model

The fixture spans a privilege boundary, so the boundary is modeled explicitly.
Every fact that crosses it is exactly one of the following:
`INHERITED`, `INDEPENDENTLY_REACQUIRED`, or `EXPLICITLY_HANDED_OFF`. No fourth
classification exists, and no fact may be left unclassified.

| Fact | Classification | Carrier and lifetime | Closing checkpoint |
| --- | --- | --- | --- |
| Invocation root path | `EXPLICITLY_HANDED_OFF` as an UNTRUSTED LOCATOR only | `--root` argument, valid for one helper invocation, carrying no authority | helper independently revalidates the root under 5.3 before any mutation |
| Case/action selection | `EXPLICITLY_HANDED_OFF` as a closed enum name only | `--case` argument, valid for one helper invocation | helper rejects any value outside the 5.2 table before any mutation |
| Target uid, target mode, child names | `INHERITED` from frozen design constants, never handed off | compiled-in constants in the helper and in the frozen case table; no runtime carrier | 4.3 paired controls measure the resulting real state; a caller value can never reach them |
| Fixture ownership and mode after the ownership action | `INDEPENDENTLY_REACQUIRED` | ordinary evidence process re-derives them with its own `lstat` and `os.open` | paired controls in 4.3 must all hold before the production call |
| Helper exit status | `INDEPENDENTLY_REACQUIRED` | process status, informational only | never evidence; the ordinary process reacquires the state itself |
| Mount namespace identity | `EXPLICITLY_HANDED_OFF` by inheritance through `fork`, `exec` and `sudo` within one private namespace | namespace id as carried by the namespace itself; valid until namespace exit | the three identity controls in 10.1 are compared before any drift |
| Mounts created inside the private namespace | `INHERITED` within the private namespace only | shared by helper and evidence process; destroyed at namespace exit | explicit checked cleanup under 10.4 before exit; namespace exit is a second boundary, not a substitute |
| Loop backing device | `INDEPENDENTLY_REACQUIRED` | ordinary evidence process re-reads the real loop state rather than trusting helper output | `LOOP_BACKING_RESIDUE=false` at the end of 10.4 |
| Host mount namespace | no fact crosses; the observer stays outside and the private namespace does not propagate to it | real host mount table read by the host observer | host-namespace absence control in 10.3, before and after the run |

The helper's own report is not evidence. If the ordinary process cannot
independently reacquire the state the helper claims to have produced, the case
is a `QUALIFICATION_GAP`.

### 5.6 Boundary transition ledger

Each transition across the privilege or namespace boundary carries exactly one
authority owner, producer, carrier, lifetime, consumer and closing checkpoint.
A transition with no closing checkpoint is not frozen here and MUST NOT be
implemented.

| # | Transition | Authority owner | Producer | Carrier | Lifetime | Consumer | Closing checkpoint |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | evidence process -> fixture root creation | ordinary runner identity | non-root evidence process | real directory under the runner temporary area | one run attempt | privileged helper (validates) and evidence process (uses) | helper root validation under 5.3 passes before any mutation |
| T2 | evidence process -> helper: case selection | this contract (frozen enum) | non-root evidence process | `--case` argument | one helper invocation | privileged helper | enum membership checked before any mutation |
| T3 | evidence process -> helper: root locator | this contract (untrusted input) | non-root evidence process | `--root` argument | one helper invocation | privileged helper | independent revalidation under 5.3 |
| T4 | helper -> filesystem: ownership and mode mutation | this contract (frozen constants) | privileged fixture helper | real inode metadata | until cleanup | non-root evidence process | 4.3 paired controls all recorded before the production call |
| T5 | evidence process -> private namespace entry | ordinary runner identity | privileged namespace launcher | inherited mount namespace | until namespace exit | evidence process and helper | the three identity controls in 10.1 agree |
| T6 | launcher -> private namespace: fixture mount | this contract | privileged fixture helper | real mount table entry inside the private namespace | until detach and release | non-root evidence process | pre-drift positive admission plus the 10.4 state machine |
| T7 | private namespace -> observer: absence fact | this contract | privileged namespace launcher | real mount table read from the host namespace | one run attempt | independent reviewer | host-namespace absence control passes before and after the run |
| T8 | run -> reviewer: evidence publication | repository design authority | privileged workflow | workflow output bound to head SHA and runner identity | retained as CI evidence | independent reviewer | exact-head binding and residue controls recorded |

T4 is the only transition that changes privilege-owned state, and its authority
owner is this contract rather than the caller. T3 is the only transition that
carries caller-provided text, and it closes at validation, not at use.

### 5.7 Failure-origin classification

Every non-pass outcome is classified by origin before it is reported:

| Origin | Meaning for these cases |
| --- | --- |
| `PRODUCT_FAILURE` | the production guard produced the wrong reason, the wrong detail, or the wrong admission after every fixture control held |
| `TEST_FAILURE` | the privileged fixture asserted something it did not measure, or measured the wrong object |
| `ENVIRONMENT_FAILURE` | privilege, capabilities, kernel, tools, filesystem or runner constraints prevented a real fixture |
| `TOOLING_FAILURE` | the helper, shim, workflow or evidence transport malfunctioned without product causality |

An `ENVIRONMENT_FAILURE` or `TOOLING_FAILURE` is never rewritten as a product
defect, and a `PRODUCT_FAILURE` is never excused as an environment artifact.

## 6. Freeze: Privileged CI Architecture

```text
PRIMARY_RUNNER=ubuntu-latest
```

Rationale: the standard GitHub-hosted Ubuntu image runs as a VM and supports
passwordless `sudo`, which is what a real privilege fixture needs.

```text
SELF_HOSTED_REQUIRED=false
SELF_HOSTED_ADOPTION=preflight_demonstrated_fallback_only
```

`SELF_HOSTED_REQUIRED=true` is explicitly NOT frozen. Self-hosted execution is
a fallback only: it may be adopted only if the future implementation preflight
demonstrates that the standard runner cannot construct the required real
fixture, and that finding must be recorded before any self-hosted design is
frozen.

Privileged qualification is a NEW SEPARATE WORKFLOW:

```text
PRIVILEGED_WORKFLOW=.github/workflows/l4_privileged_qualification.yml
```

The existing workflow MUST retain its exact formal topology:

```text
FORMAL_CI_JOBS=test,portability-pyarrow24,package
FOURTH_FORMAL_JOB_AUTHORIZED=false
```

No fourth formal job may be added to `.github/workflows/ci.yml`, and the
privileged workflow is separate control-plane evidence rather than a formal
required check. It MUST NOT be inserted into the ordinary tier logic, and its
existence MUST NOT change any ordinary tier decision. Adding it is a
control-plane change that requires its own authorization, which this design PR
does not grant.

### 6.1 Frozen future workflow authority

The future privileged workflow's own trigger and permissions are frozen here,
so the later implementation PR does not choose its own authority. Every one of
the following is a requirement on that workflow:

- it MUST NOT use `pull_request_target`;
- it MUST NOT use `workflow_run`, or any other event that executes in the base
  repository context with elevated trust;
- it MUST NOT run or reference arbitrary secrets; a run that needs a secret the
  fixture does not require is invalid;
- its `permissions` are minimal and read-only, and a broader permission is
  permitted only where separately justified in the implementation PR;
- its checkout MUST bind to the exact PR head SHA being qualified, never to a
  base-SHA merge result and never to a moving branch tip;
- it MUST print and bind, as its own output, all of:

```text
PR_NUMBER
PR_HEAD_SHA
PR_HEAD_TREE
GITHUB_RUN_ID
GITHUB_RUN_ATTEMPT
RUNNER_IMAGE_IDENTITY
```

Frozen permission and trigger facts:

```text
PRIVILEGED_WORKFLOW_USES_PULL_REQUEST_TARGET=false
PRIVILEGED_WORKFLOW_USES_WORKFLOW_RUN=false
PRIVILEGED_WORKFLOW_ARBITRARY_SECRETS=false
PRIVILEGED_WORKFLOW_PERMISSIONS=read_only_minimal
PRIVILEGED_WORKFLOW_CHECKOUT_BINDS_EXACT_HEAD_SHA=true
PRIVILEGED_WORKFLOW_CHECKS_OUT_MERGE_COMMIT=false
PRIVILEGED_WORKFLOW_PRINTS_HEAD_SHA=true
PRIVILEGED_WORKFLOW_PRINTS_HEAD_TREE=true
PRIVILEGED_WORKFLOW_PRINTS_RUN_ID=true
PRIVILEGED_WORKFLOW_PRINTS_RUN_ATTEMPT=true
PRIVILEGED_WORKFLOW_PRINTS_RUNNER_IDENTITY=true
```

### 6.2 Frozen event model

The selected event model is `pull_request`. This is the preferred model because
it is the only one that gives exact-head authority without granting the run the
base repository's write trust: the workflow definition itself is taken from the
PR head, so a job that the PR intends to add is the job that runs, and
`github.event.pull_request.head.sha` names the exact commit under qualification
while the pull-request ref is only a merge-side view.

```text
PRIVILEGED_WORKFLOW_EVENT=pull_request
PRIVILEGED_WORKFLOW_BASE_BRANCH=main
PRIVILEGED_WORKFLOW_HEAD_BINDING=github.event.pull_request.head.sha
PRIVILEGED_WORKFLOW_PATH_FILTER_REQUIRED=true
PRIVILEGED_WORKFLOW_PATH_FILTER_SCOPE=A3_implementation_and_control_plane_surface
```

A narrow `paths` filter scopes the run to the A3 implementation and
control-plane surface, so unrelated documentation or product PRs do not consume
privileged runner time and no privileged job is reachable from a change that
does not touch the fixture. Candidate surface, frozen as a set of paths whose
exact globs the implementation PR must pin:

| Surface class | Example path |
| --- | --- |
| privileged test file | `tests/privileged_schedule_artifact_qualification.py` |
| privileged helper | `scripts/l4_privileged_fixture.py` |
| the workflow itself | `.github/workflows/l4_privileged_qualification.yml` |
| pinned workflow contract checker | `scripts/check_release.py` |
| this contract | `docs/governance/l4_privileged_linux_qualification_v1.md` |

No other event model is selected. If a later implementation decides that
`pull_request` cannot express a required fact, that decision is a redesign of
this section requiring another design-only review before implementation, and
the replacement model MUST then demonstrate exact-head authority at least as
strongly, that is, it MUST name the exact head commit, MUST NOT execute base
branch code with elevated trust, and MUST NOT require any secret.

Ordinary CI remains separate and cannot be substituted by this run:

```text
ORDINARY_CI_SEPARATE=true
PRIVILEGED_RUN_SUBSTITUTES_ORDINARY_CI=false
ORDINARY_CI_SUBSTITUTES_PRIVILEGED_RUN=false
```

## 7. Freeze: Future Privileged Preflight

Before any mutation, the future implementation workflow MUST prove, from real
observed host state:

| Proof | Required observation |
| --- | --- |
| standard runner | the runner is the standard `ubuntu-latest` VM image, with image identity recorded |
| ordinary privilege | the ordinary evidence process has `euid != 0` |
| passwordless sudo | `sudo -n` succeeds without a prompt or terminal |
| helper privilege | the privileged child really reports `euid == 0` |
| capabilities | the privileged child's `CapEff` contains every capability this exact fixture needs, decoded from the real mask |
| kernel and tools | the required kernel interfaces and utilities exist and their versions are recorded |
| fixture root | the `RUNNER_TEMP` invocation root is usable, invocation-specific, and not a shared or persistent runner path |
| foreign uid | the frozen `FOREIGN_OWNER_TARGET_UID` is representable on the host and differs from the ordinary runner's effective uid, so the 5.2 selection rule is satisfiable |
| isolation | no persistent or shared runner state is targeted by any step |

The fixture's capability requirement is derived from the operations it really
performs: `CAP_CHOWN` for the RQP-L09 ownership mutation, and `CAP_SYS_ADMIN`
for the RQP-L17 private mount namespace, the loop-backed ext4 mount, the
`MNT_DETACH` detach and cleanup. `CAP_DAC_OVERRIDE` MUST NOT be required by the
design: `FILE_MODE=0644` exists precisely so the ordinary reader's access is a
real permissions fact rather than a capability artifact. A preflight that
passes only because a capability was assumed is invalid.

A failed preflight is classified by origin:

- `QUALIFICATION_GAP` when the required real fixture cannot be constructed in
  this environment;
- `ENVIRONMENT_FAILURE` when the environment itself failed to provide a
  documented runner property.

A failed preflight MUST never silently become `PASS`, and must never be
reported as a product failure. No mutation may occur after a failed preflight.

## 8. Freeze: RQP-L17 Row Semantics

The remaining RQP-L17 row is renamed and restated as:

```text
RQP_L17_HELD_MOUNT_REPRESENTATION_DRIFT
```

A3 does NOT prove a statx mount-id change. This contract MUST NOT state that A3
proves `_mount_id(fd)` measurement A != measurement B, and the existing
defensive invariant at L105 is not qualified by A3:

```text
L105_MOUNT_ID_CHANGE_REAL_TRIGGER=NOT_KNOWN_CONSTRUCTIBLE
```

L105 remains a defensive fail-closed invariant whose real trigger is not known
constructible with any reviewed mechanism. It stays in production unchanged and
unqualified; this design neither weakens it nor claims evidence for it.

What A3 does prove is a real topology change in the kernel's mount
representation of a mount that the evidence process still holds. The real
trigger is:

1. Retain a real descriptor to a qualifying ext4 mount, opened by the non-root
   evidence process with no privilege.
2. Before any drift, admit that descriptor once through the production
   primitive, so the positive case is real rather than assumed.
3. Detach that mount from the private namespace with `MNT_DETACH`.
4. Keep the descriptor open; never close it and never reopen by path.
5. Confirm the descriptor is still valid: `fstat` succeeds, the device and
   inode are unchanged, the retained bytes still read back unchanged, and
   `_mount_id(fd)` still returns the same nonzero mount id under `statx`.
6. Confirm from real `/proc/self/mountinfo` that the namespace no longer
   represents that mount: zero records carry the held mount id.
7. Call the production primitive again; `_mount_description` receives the real
   mount table, its `matches` tuple is empty, and the guard at L84-L85 fires.
8. Require exactly:

```text
reason_code=PLATFORM_UNQUALIFIED
detail="held mount missing or ambiguous"
```

`str(exc)` is therefore exactly
`PLATFORM_UNQUALIFIED: held mount missing or ambiguous`.

The paired control in step 2 is mandatory. Without a real positive admission
before the detach, a failure after the detach could be a construction artifact
of the fixture rather than the representation loss this case claims. Steps 5
and 6 are the independent controls that make the failure attributable: they
prove the descriptor is alive and the mount table is the real one, so the only
changed fact is the kernel's representation of the held mount.

```text
RQP_L17_GUARD_DISCRIMINATION_REQUIRED=true
```

Guard discrimination is frozen as well. The case MUST establish which guard
fired. The required failure is L84-L85 (`PLATFORM_UNQUALIFIED`, detail
`held mount missing or ambiguous`). If the observed first failure is instead
L105 (`UNSAFE_PATH`, detail `mount identity drift`), then the kernel changed the
statx mount id across the detach and the observed mechanism differs from the
mechanism frozen here: that outcome is `QUALIFICATION_GAP` plus a design
finding against this document, and it is never a pass and never a product
defect. A case that cannot distinguish the two guards does not prove anything
and MUST NOT be reported as evidence.

## 9. Freeze: RQP-L17 Filesystem Fixture

Bind mounts are NOT accepted as the target ext4 fixture. Before any drift, the
fixture MUST already satisfy the existing production conditions of L88-L94:

```text
root field == "/"                      # record field 3 is exactly b"/"
filesystem type == ext4                # record field separator+1 is exactly b"ext4"
device represented exactly once        # the device appears in exactly one record
rw present                             # "rw" in mount options and in super options
ro absent                              # "ro" in neither option set
```

Those conditions come from production, not from this document. A bind mount
fails them structurally: its `root` field is the bound subdirectory rather than
`/`, and the underlying device then appears in more than one record, which the
exactly-once rule rejects.

Preferred future fixture: one ephemeral ext4 filesystem image, mounted exactly
once inside the private mount namespace. The design may use a sparse regular
image, `mkfs.ext4`, and a loop-backed mount. These operations are permitted
only in the future separately authorized privileged implementation; no such
operation is authorized by this design PR.

Frozen fixture obligations for that implementation:

- the image, the mountpoint, and every helper-visible path live beneath the one
  invocation-specific `RUNNER_TEMP` root;
- the mount table is verified with the production predicate itself, not with a
  hand-written expectation: the retained descriptor must be admitted before the
  drift;
- the exactly-once device rule is verified against the real mount table,
  because runner images may already mount other loop-backed filesystems;
- the retained object is a regular single-link file that the ordinary non-root
  process can open read-only without privilege; its ownership is not RQP-L17
  evidence and must never be reported as RQP-L09 evidence;
- the fixture MUST NOT use the repository filesystem, a worktree, or any
  runtime-data path as the mutable mount fixture;
- any precondition that cannot be met is reported as `QUALIFICATION_GAP`, never
  as a product failure and never as a pass.

## 10. Freeze: Namespace Isolation

```text
RQP_L17_NAMESPACE_ISOLATION_REQUIRED=true
```

All mount and detach operations MUST occur in a private mount namespace.
Before any mutation, mount propagation MUST be made private as appropriate, so
that no event can propagate back to the host namespace. The fixture MUST never
detach or remount the host root filesystem, and MUST never use the repository
filesystem itself as the mutable mount fixture.

### 10.1 Frozen process and namespace topology

Four roles exist, and no other process may perform a privileged or mount
operation. The topology is frozen as a set of roles plus an explicit lifecycle,
not as a set of independent commands that happen to share an environment.

| Role | Runs in | Identity | Permitted operations |
| --- | --- | --- | --- |
| `HOST_OBSERVER` | host mount namespace, outside the private namespace | ordinary runner identity | read the host mount table; record the fixture device and mountpoint absence baseline before and after the run |
| `PRIVILEGED_NAMESPACE_LAUNCHER` | starts in the host mount namespace, then enters a new private mount namespace | reviewed privileged identity via `sudo -n` | create the private mount namespace, make propagation private, establish and report the private namespace identity |
| `NONROOT_EVIDENCE_PROCESS` | inside the private namespace, launched by the launcher | ordinary runner identity, `euid != 0` and `egid` unchanged | execute the production primitive under qualification; retain descriptors; measure and record evidence |
| `PRIVILEGED_FIXTURE_HELPER` | inside the same private namespace, invoked from it | the reviewed privileged identity again, via `sudo -n` | the 5.2 case actions only: fixture ownership mutation, fixture mount setup, `MNT_DETACH` detach, checked cleanup |

Frozen lifecycle, in order:

```text
HOST_OBSERVER                records host mount namespace identity / absence baseline
  -> PRIVILEGED_NAMESPACE_LAUNCHER
       sudo -n
       creates a private mount namespace
       makes propagation private
       establishes namespace identity
  -> NONROOT_EVIDENCE_PROCESS
       launched INSIDE that private namespace
       effective uid/gid = ordinary runner identity
       executes the production primitive
  -> PRIVILEGED_FIXTURE_HELPER
       invoked from INSIDE the same private namespace
       may regain reviewed privilege via sudo
       performs only reviewed setup / detach / cleanup actions
```

```text
HOST_OBSERVER_IN_PRIVATE_NAMESPACE=false
PRIVILEGED_NAMESPACE_LAUNCHER_AUTHORITY=sudo -n only
NONROOT_EVIDENCE_PROCESS_EUID=ordinary_runner_identity
FIXTURE_HELPER_INVOCATION_ORIGIN=inside_the_same_private_namespace
FIXTURE_HELPER_REGAINS_PRIVILEGE=sudo -n only
FIXTURE_HELPER_ACTION_SCOPE=reviewed_setup_detach_cleanup_only
```

The host observer stays OUTSIDE the private namespace for the whole run, and it
is the only role that performs the before/after host-mount absence
observations. A control read from inside the private namespace cannot prove
anything about the host namespace and MUST NOT be reported as that control.

`sudo` is not assumed to preserve the intended namespace. The implementation
MUST observe the actual namespace identity of the evidence process and of the
helper, and MUST compare them against the host identity, before any mount
mutation is trusted:

```text
PRIVATE_EVIDENCE_MNT_NS_ID=
PRIVATE_HELPER_MNT_NS_ID=
HOST_MNT_NS_ID=
PRIVATE_EVIDENCE_MNT_NS_ID == PRIVATE_HELPER_MNT_NS_ID
PRIVATE_EVIDENCE_MNT_NS_ID != HOST_MNT_NS_ID
```

These three identities are read from the real namespace state of the running
processes, not from configuration or intent. The namespace identity is the
inode of the process's own mount namespace as the kernel reports it, so two
processes reporting the same value are provably in the same mount namespace.
Each role reports its own identity from a real read of its own mount namespace
object, and the launcher reports the host identity it observed before entering
the private namespace; the evidence process and the helper report theirs from
inside the private namespace. No identity may be inferred from a process name, a
command line, or the presence of a `sudo` in the lifecycle.

```text
NAMESPACE_IDENTITY_MEASURED=true
NAMESPACE_IDENTITY_SOURCE=/proc/self/ns/mnt inode
NAMESPACE_IDENTITY_ASSUMED_FROM_SUDO=false
PRIVATE_EVIDENCE_HELPER_SAME_NAMESPACE_REQUIRED=true
PRIVATE_NAMESPACE_DIFFERS_FROM_HOST_REQUIRED=true
```

If the two private identities differ, or the private identity equals the host
identity, the mount confining property is not established, no mount mutation may
be attempted, and the outcome is `QUALIFICATION_GAP` with a design finding. A
helper that created the fixture in a namespace the evidence process cannot see
does not satisfy this contract.

### 10.2 Boundary table for namespace state transitions

| # | Transition | Authority owner | Producer | Carrier | Lifetime | Consumer | Closing checkpoint |
| --- | --- | --- | --- | --- | --- | --- | --- |
| N1 | host baseline -> observer | this contract | host observer | observed host mount table | one run attempt | independent reviewer | pre-run absence baseline recorded |
| N2 | host -> private namespace creation | reviewed privileged identity | privileged namespace launcher | real mount namespace | until namespace exit | evidence process and helper | private namespace identity differs from host identity |
| N3 | propagation state | this contract | privileged namespace launcher | real propagation flags of the private namespace root | until namespace exit | evidence process and helper | propagation is private before any mount mutation |
| N4 | launcher -> evidence process: namespace membership | ordinary runner identity | privileged namespace launcher | inherited mount namespace across `fork`/`exec` | until namespace exit | evidence process | `PRIVATE_EVIDENCE_MNT_NS_ID` measured and equal to the private identity |
| N5 | evidence process -> helper: namespace membership | reviewed privileged identity | privileged fixture helper | inherited mount namespace across `sudo` | one helper invocation | helper | `PRIVATE_HELPER_MNT_NS_ID` measured and equal to `PRIVATE_EVIDENCE_MNT_NS_ID` |
| N6 | private namespace -> host: absence | this contract | host observer | observed host mount table | one run attempt | independent reviewer | post-run absence control recorded |

### 10.3 Host-namespace absence control

The workflow MUST record a host-namespace absence control: the fixture's device
and mountpoint MUST never appear in a mount table read from outside the fixture
namespace, before and after the run. That control is what makes "no event
reached the host namespace" an observed fact rather than an assumption, and it
is valid only because the host observer remains outside the private namespace
for the whole run:

```text
HOST_NAMESPACE_ABSENCE_CONTROL_BEFORE=true
HOST_NAMESPACE_ABSENCE_CONTROL_AFTER=true
HOST_NAMESPACE_RESIDUE=false
```

### 10.4 Frozen cleanup state machine

Namespace and process exit is a second cleanup boundary, not a substitute for
explicit checked cleanup. Cleanup is a state machine, and its states are
explicit rather than implied:

```text
MOUNT_STATE=ATTACHED
MOUNT_STATE=DETACHED_BUSY
MOUNT_STATE=RELEASED
```

`ATTACHED` means the fixture mount is present in the private mount table.
`DETACHED_BUSY` means `MNT_DETACH` has succeeded and the mount is no longer
reachable from that table, but the kernel still holds it because a retained
descriptor or a retained reference keeps it busy. `RELEASED` means the detach
completed and every reference the fixture held has been closed, so the held
mount no longer appears in the private mount table and the loop backing is gone.

The legal transitions, and the only ones this contract freezes:

| From | Trigger | To | Required actions |
| --- | --- | --- | --- |
| `ATTACHED` | fixture work completed, `MNT_DETACH` succeeds | `DETACHED_BUSY` | none beyond recording the detach result |
| `ATTACHED` | failure before drift, or detach not attempted | cleanup | checked ordinary fixture unmount, then loop backing release, then removal |
| `DETACHED_BUSY` | retained descriptors closed and the mount table shows zero records for the held mount id | `RELEASED` | close retained descriptors, verify absence from the private mount table, release the loop backing, verify it is gone, remove the image, mountpoint and root |
| any | any residue control still true after the actions above | `CLEANUP_FAILED` | report the state at failure with diagnostics; never retry blindly |

With this state machine, the earlier draft's requirement of a second
unconditional unmount after a successful `MNT_DETACH` is removed. It was not
implementable: after a successful `MNT_DETACH` the mount point no longer appears
in the private mount table, so a further unmount of that path has no object to
act on and cannot be a required step. The required transitions are:

`ATTACHED` -> failure before drift: perform a checked ordinary fixture unmount,
then release the loop backing. The ordinary unmount is required here precisely
because no detach has happened yet.

`DETACHED_BUSY` -> after a successful `MNT_DETACH`:

1. do NOT require another mountpoint unmount;
2. close every retained fixture descriptor, including the evidence process's
   retained mount descriptor and any helper-held descriptor;
3. verify the held mount no longer appears in the private mount table, that is,
   zero records carry the held mount id;
4. allow the kernel to release the detached mount;
5. release the loop backing;
6. verify the loop backing is gone;
7. remove the image, the mountpoint and the invocation-specific root.

```text
CLEANUP_FROM_ATTACHED=checked_unmount_then_release_loop
CLEANUP_FROM_DETACHED_BUSY=close_descriptors_then_verify_then_release_loop
SECOND_UNMOUNT_AFTER_MNT_DETACH_REQUIRED=false
CLEANUP_REQUIRES_ORDER=true
```

The loop backing release is ordered after the retained descriptors are closed,
because a loop device with an open reference is not releasable, and a release
attempt before the close would report a false failure and invite a blind retry.

The final controls are mandatory and are recorded as observed values:

```text
PRIVATE_MOUNT_RESIDUE=false
LOOP_BACKING_RESIDUE=false
FIXTURE_ROOT_RESIDUE=false
HOST_NAMESPACE_RESIDUE=false
```

`PRIVATE_MOUNT_RESIDUE` is measured inside the private namespace, and
`HOST_NAMESPACE_RESIDUE` is measured by the host observer under 10.3. A residue
control that is asserted rather than measured is not a control.

Cleanup failure remains a visible, distinct, non-pass outcome. It is never
suppressed, never retried blindly, and never converted into a pass:

```text
CLEANUP_FAILURE_OUTCOME=CLEANUP_FAILED
CLEANUP_FAILURE_VISIBLE=true
CLEANUP_FAILURE_SUPPRESSED=false
CLEANUP_FAILURE_BLIND_RETRY=false
CLEANUP_FAILED_IS_PASS=false
```

A failed cleanup is never reclassified as `PRODUCT_FAILURE`, and the residual
path, mount id and loop device are recorded as diagnostics only. The state at
the moment of failure is reported together with the outcome, so a reviewer can
distinguish a failure that occurred while `ATTACHED` from one that occurred
while releasing a detached mount.

## 11. Freeze: RQP-L17 Evidence Scope

The frozen scope is precisely:

A3 proves real-kernel fail-closed behavior of `_linux._ext4_capability(fd)` and
its real `_mount_description` path under held-mount representation loss.

A3 does NOT claim an end-to-end loop-mounted `_NativeScope(...)` proof. The
reason is structural: `_NativeScope.__init__` requires every retained ancestry
filesystem identity to match the root object's filesystem tuple
(`_physical.py` L37-L38, `UNSAFE_PATH` detail `ancestry mount/volume
transition`). A nested independent ext4 mount would fail that ancestry
mount/volume transition before the intended RQP-L17 mechanism could be reached,
so an end-to-end scope proof is a different contract with a different fixture.

Any future end-to-end scope proof requires a separate design. This document
does not authorize it, does not sketch it, and must not be cited as if it did.

## 12. Freeze: Future Test Placement and Ordinary-CI Separation

```text
FUTURE_PRIVILEGED_TEST_FILE=tests/privileged_schedule_artifact_qualification.py
```

The filename deliberately does NOT match the repository's normal pytest
auto-discovery pattern. With `testpaths = ["tests"]` and the default
`python_files = test_*.py` in `pyproject.toml`, a bare
`python -m pytest` cannot collect that file.

Frozen consequences:

- normal `python -m pytest` MUST NOT execute privileged fixture tests;
- the future privileged workflow invokes that file explicitly, by path;
- no `test_*.py` module may import the privileged file in a way that executes
  its privileged cases under ordinary collection;
- ordinary FULL semantics are preserved exactly, and ordinary CI is never
  converted into a privileged suite;
- the privileged workflow's own outcome is never a substitute for ordinary CI,
  and ordinary CI is never evidence for the privileged cases.

## 13. Future Implementation Surface

Expected later implementation files, with their expected change class:

| Path | Expected role |
| --- | --- |
| `docs/governance/l4_privileged_linux_qualification_v1.md` | this contract, already on base for the implementation PR |
| `tests/privileged_schedule_artifact_qualification.py` | explicitly invoked privileged qualification cases |
| `scripts/l4_privileged_fixture.py` | the fixed privileged helper (root validation, ownership mutation, mount setup/detach, checked cleanup) |
| `.github/workflows/l4_privileged_qualification.yml` | separate privileged qualification workflow with preflight and evidence publication |
| `scripts/check_release.py` | only as needed to pin and validate the new privileged workflow contract |

```text
FORMAL_CI_FILE_CHANGE_EXPECTED=false       # .github/workflows/ci.yml
PRODUCTION_SRC_CHANGE_EXPECTED=false       # src/**
CHECK_RELEASE_CHANGE_ONLY_FOR_WORKFLOW_PINNING=true
```

`.github/workflows/ci.yml` is EXPECTED UNCHANGED unless the implementation
proves a cross-workflow integration requirement that cannot be expressed
otherwise, and any such change is a separate authorization. Production
`src/**` is EXPECTED UNCHANGED: this design qualifies existing guards and
changes no reader, writer, platform or registry behavior.

Focused tests for the checker and workflow semantics may be added in the
implementation PR where they are needed to pin the new privileged workflow
contract.

The implementation PR MUST also pin, in a checked-in test or checker, the
findings this remediation froze: the closed helper argument vector and the
derived constants of 5.1-5.2, the three measured namespace identities of 10.1,
the cleanup state machine and residue controls of 10.4, and the workflow
trigger, permission and exact-head binding facts of 6.1-6.2. A frozen token with
no pinning check is a token that can silently drift in a later PR.

## 14. Stage Separation and Registry Discipline

A3 privileged evidence closure MUST leave the production registry untouched:

```text
QUALIFIED_CAPABILITIES_AFTER_A3=frozenset()
CANDIDATE_TUPLE_ENROLLMENT=false
```

No candidate tuple may be enrolled by the privileged qualification work. The
L4 Linux tuple stays unadmitted, exactly as `_platform.py` L10 declares it, and
`tests/test_schedule_artifact_platform.py` keeps asserting that the production
registry is empty (L272-L276).

Stage order after A3 evidence closure:

```text
A3 privileged evidence closure
-> independent review of that evidence
-> separate A4 admission workstream
-> registry change only if explicitly authorized
```

The privileged qualification file may report that a real host produced an
admitting capability tuple. That report is review input for A4. It is not
admission: the registry change is a separate, separately authorized
production change with its own exact-tuple evidence and its own review.

## 15. Contract Implementability

These results are design implementability results, NOT qualification evidence.
They state that each frozen requirement can be produced, carried, observed and
consumed by the declared architecture.

The check was re-run against the corrected document, in which the helper
protocol (5.1-5.4), the boundary model (5.5-5.6), the process and namespace
topology (10.1-10.2) and the cleanup state machine (10.4) are the corrected
statements. The result is claimed only because the document now has no
producer/carrier/lifecycle/consumer contradiction:

```text
RQP_L09_FOREIGN_OWNER_IMPLEMENTABILITY=PASS
RQP_L09_ROOT_OWNED_IMPLEMENTABILITY=PASS
RQP_L17_HELD_MOUNT_REPRESENTATION_DRIFT_IMPLEMENTABILITY=PASS
HELPER_PROTOCOL_IMPLEMENTABILITY=PASS
NAMESPACE_LIFECYCLE_IMPLEMENTABILITY=PASS
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS
RQP_L17_L105_MOUNT_ID_CHANGE_IMPLEMENTABILITY=NOT_CONSTRUCTIBLE_WITH_KNOWN_REAL_MECHANISM
A3_CONTRACT_IMPLEMENTABILITY=PASS
```

The three previously contradictory requirements and the four remediation
findings resolve as follows:

| Finding | Corrected statement | Why it is now implementable |
| --- | --- | --- |
| helper protocol contradiction: "MUST NOT accept caller-supplied path/uid/mode" versus "root path / child / target uid / mode are explicitly handed off" | 5.1-5.4 | exactly one caller-supplied string may cross, the root locator, and it crosses as untrusted data with no authority; uid, gid, mode and child names are derived from frozen constants inside the helper and never cross at all; the argument vector is a closed enum plus that locator |
| namespace lifecycle asserted rather than produced | 10.1-10.2 | four named roles with declared identities and permitted operations, an ordered lifecycle, and three measured mount namespace identities with the required equality and inequality, so "the helper is in the evidence process's namespace" is an observed fact rather than an assumption about `sudo` |
| unconditional second unmount required after successful `MNT_DETACH` | 10.4 | explicit `ATTACHED` / `DETACHED_BUSY` / `RELEASED` states; the `ATTACHED` failure path keeps the checked ordinary unmount, and the `DETACHED_BUSY` path closes retained descriptors, verifies absence from the private mount table, then releases the loop backing; no unmount is required of a mount point that no longer exists |
| authority preview collapsed "no new authority" into one answer | 1 and 17 | five separate authority facts; privileged execution and CI control-plane change authorities are required by the later implementation phase and granted only there, while public API, registry admission and production change remain not required |

| Requirement | Authority owner | Required evidence | Producer | Carrier / holder | Lifetime | Consumer / verifier | Closing checkpoint | Failure outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Helper argument protocol | repository design authority (this contract) | the exact argument vector, the derived uid/mode/child constants, and the rejection of every non-enumerated argument | privileged fixture helper | helper command line (closed enum plus untrusted locator) and the frozen constant table | one helper invocation | independent reviewer; ordinary suite unchanged | argument rejection and root revalidation recorded before any mutation | `HELPER_ARGUMENT_REJECTED`, `HELPER_ROOT_REJECTED` or `QUALIFICATION_GAP` |
| Process and namespace topology | same | the four roles with their real identities, the ordered lifecycle, and three measured mount namespace ids | privileged namespace launcher, evidence process and helper | real mount namespace identity of each running process | one run attempt, retained as CI evidence | independent reviewer | `PRIVATE_EVIDENCE_MNT_NS_ID == PRIVATE_HELPER_MNT_NS_ID` and `PRIVATE_EVIDENCE_MNT_NS_ID != HOST_MNT_NS_ID`, both measured | `QUALIFICATION_GAP` plus a design finding; no mount mutation is attempted |
| Cleanup state machine | same | the observed state at cleanup entry or failure, the release order, and the four residue controls | privileged fixture helper plus host observer | real private mount table, real loop state, real host mount table | one run attempt | independent reviewer | `PRIVATE_MOUNT_RESIDUE=false`, `LOOP_BACKING_RESIDUE=false`, `FIXTURE_ROOT_RESIDUE=false`, `HOST_NAMESPACE_RESIDUE=false` | `CLEANUP_FAILED`, always visible and never converted into a pass |
| RQP-L09 FOREIGN_OWNER rejection | same | real foreign-owned file, all five paired controls, exact reason code and detail | privileged helper (setup) plus non-root evidence process (measurement) | captured privileged-workflow run output bound to the exact head and host identity | one run attempt, retained as CI evidence | independent reviewer; ordinary suite unchanged | all controls recorded and the production call observed failing for the owner policy | `QUALIFICATION_GAP` or `PRODUCT_FAILURE`, classified by origin |
| RQP-L09 ROOT_OWNED admission | same | real root-owned file, ordinary `euid != 0`, real open, `held.security[0] == 0` | same | same | same | same | positive admission plus literal `st_uid` observation | `QUALIFICATION_GAP` or `PRODUCT_FAILURE` |
| RQP-L17 representation drift | same | qualifying ext4 mount proof, pre-drift positive admission, post-detach live descriptor, real mount table, exact reason code and detail | privileged helper (mount, detach) plus non-root evidence process (primitive calls) | same | same | same | host-namespace absence control plus explicit checked cleanup recorded | `QUALIFICATION_GAP`, `ENVIRONMENT_FAILURE` or `PRODUCT_FAILURE` |
| RQP-L17 L105 mount-id change | same | a real repeatable trigger for a statx mount-id change on a held descriptor | none known | none | none | independent reviewer records non-constructibility | none; L105 stays defensive and unqualified | `NOT_CONSTRUCTIBLE_WITH_KNOWN_REAL_MECHANISM` |
| Registry admission | repository owner, via a later A4 authorization | exact-tuple evidence from a real qualified host, independently reviewed | future A4 workstream | production `_QUALIFIED_CAPABILITIES` after an authorized change | permanent until superseded by an authorized change | production reader admission path | A4 review and authorization | not attempted in A3; registry stays empty |

No requirement in this document depends on an evidence producer, carrier or
consumer that the declared architecture cannot provide. The places where
continuity could have been assumed are handled explicitly instead: the helper's
exit status is never evidence (5.5), the caller's root string is validated
rather than trusted (5.3), the shared namespace is measured rather than assumed
(10.1), the release order is frozen rather than left to a blind retry (10.4),
and no writer/reader evidence handoff exists or is invented.

## 16. Three-Layer Consistency

| Invariant | HUMAN_CONTRACT (this document) | MACHINE_DECLARATION | RUNTIME | TESTS |
| --- | --- | --- | --- | --- |
| Foreign owner is refused by the owner policy | frozen, section 4.4 | none added; no registry entry exists for this case | `_permissions` L110 unchanged | ordinary gap case today; privileged real case later |
| Root ownership is admitted with a literal `st_uid` of 0 | frozen, section 4.4 | none added | `_permissions` L110 unchanged | ordinary gap case today; privileged real case later |
| Held-mount representation loss fails closed | frozen, sections 8 and 11 | none added | `_mount_description` L84-L85 unchanged | no existing test constructs it; privileged case later |
| L105 stays defensive and unqualified | frozen, section 8 | none | L105 unchanged | unchanged |
| No L4 tuple is admitted | frozen, section 14 | `_QUALIFIED_CAPABILITIES = frozenset()` | `_require_qualified` unchanged | `test_schedule_artifact_platform.py` L272-L276 unchanged |
| Ordinary pytest never runs privileged fixtures | frozen, section 12 | `pyproject.toml` collection scope unchanged | not applicable | privileged file not auto-discovered |
| Formal CI topology is unchanged | frozen, section 6 | `.github/workflows/ci.yml` unchanged | not applicable | unchanged |
| The helper accepts only an enum case and an untrusted root locator | frozen, sections 5.1-5.2 | none added; the enum and the derived constants are helper-internal | no production symbol changes | privileged case later; argument and derivation behavior is pinned by the implementation PR |
| The helper and the evidence process share one measured private namespace | frozen, section 10.1 | none added | no production symbol changes | privileged case later; the three namespace identities are measured at run time |
| Cleanup follows the frozen state machine and ends residue-free | frozen, section 10.4 | none added | no production symbol changes | privileged case later; the four residue controls are measured, not asserted |
| The privileged workflow authority is frozen | frozen, sections 6.1-6.2 | none added; the workflow does not exist yet | not applicable | workflow contract pinned by a checker in the implementation PR |

This design does not claim that any layer is complete. The machine-declaration
layer is deliberately unchanged and empty, the runtime layer is deliberately
unchanged, and the privileged test layer does not yet exist. A green ordinary
suite is not evidence for any case frozen here.

## 17. Future-Implementation Preview

No production code is written by this PR. This is the required lightweight
preview of the later runtime work.

- Modules that will probably need modification: none in `src/**`. The helper
  and the privileged test file are new files under `scripts/` and `tests/`, and
  the workflow is new.
- Can existing APIs express the contract? Yes. The evidence process can import
  the existing private symbols `_linux._LinuxObject`, `_linux._ext4_capability`
  and `_linux._mount_id` exactly as the ordinary native-guard suite already
  does, and the case outcomes are expressed by the existing reason codes and
  details. No new public API is required.
- Can existing evidence and data structures carry all required facts? Yes: the
  retained security tuple, the mount description triple, the retained
  descriptor identity and the real mount table carry every fact the cases
  assert.
- Is new persistent state required? No. The fixture root is invocation-local
  under `RUNNER_TEMP` and is removed by checked cleanup.
- Is a cross-boundary handoff required? Yes, exactly one privilege boundary,
  modeled in 5.5 and 5.6. It is explicit, bounded, revalidated by the ordinary
  process, and carries no authority: only an untrusted root locator and a closed
  case enum cross it.
- Authority facts are separate and are never collapsed into one answer:

```text
NEW_PUBLIC_API_REQUIRED=false
PRIVILEGED_EXECUTION_AUTHORITY_REQUIRED=true
CI_CONTROL_PLANE_CHANGE_AUTHORITY_REQUIRED=true
REGISTRY_ADMISSION_AUTHORITY_REQUIRED_IN_A3=false
PRODUCTION_CHANGE_AUTHORITY_REQUIRED_IN_A3=false
```

  No new public API is required: `_QUALIFIED_CAPABILITIES` remains the only L4
  admission gate and stays empty, and no new symbol becomes part of the public
  surface. Privileged execution authority and CI control-plane change authority
  ARE required, by the future implementation phase rather than by this design,
  and each is separately authorized there; neither is granted here. Registry
  admission and production change authorities are not required in A3 at all.
- Can existing test seams prove the invariant? Yes for the ordinary suite; the
  privileged cases use the same private seams plus real privilege, and their
  evidence is published as workflow output rather than claimed by the ordinary
  suite.

If any of these answers stops being true during implementation, the
implementation PR MUST stop and return here rather than improvising authority.

## 18. Non-Goals

This design PR performs none of the following, and authorizes none of them:

```text
NO_PRIVILEGED_COMMAND=true
NO_SUDO_EXECUTION=true
NO_CHOWN=true
NO_MOUNT=true
NO_UMOUNT=true
NO_UNSHARE=true
NO_MKFS=true
NO_LOSETUP=true
NO_CI_WORKFLOW_MODIFICATION=true
NO_TEST_MODIFICATION=true
NO_PRODUCTION_MODIFICATION=true
NO_REGISTRY_CHANGE=true
NO_TUPLE_ENROLLMENT=true
NO_WINDOWS_QUALIFICATION=true
NO_WRITER_OR_PUBLICATION_QUALIFICATION=true
```

Also out of scope: no workflow file is created or edited, no
`scripts/check_release.py` change, no destructive-operation contract or
exemption change, no version or dependency change, no release, tag, or
publication action, and no host, network, ACL or privilege configuration
change on any machine.

## 19. Validation for This Design PR

Validation is docs-governance scoped only:

- whitespace: `git diff --check` over the exact base-to-head range;
- repository hygiene: `python scripts/check_repo_hygiene.py`;
- destructive-operation design gate: `python scripts/check_destructive_design_gate.py
  --repo . --mode repository` (and the pull-request mode in CI);
- release checker: `python scripts/check_release.py`.

This remediation round adds no further validation class. It changes one
document, so the same four checks apply to the remediated head, and the
prohibitions are unchanged:

```text
NO_FULL_PYTEST=true
NO_SUDO=true
NO_CHOWN=true
NO_MOUNT=true
NO_UNSHARE=true
NO_MKFS=true
NO_LOSETUP=true
```

No FULL local pytest is run merely for this design document, and no privileged
command of any kind is executed by this PR. The ordinary suite is unchanged,
so its existing results remain the ordinary baseline.

```text
FULL_LOCAL_PYTEST_FOR_THIS_PR=false
PRIVILEGED_EXECUTION_FOR_THIS_PR=false
EXPECTED_CI_TIER=docs_fast
```

## 20. Lifecycle and Stop

One design document, one commit, one DRAFT pull request, no amend, no force
push, no merge. The PR body states the design-only flags and this document is
its authority.

Remediation round 1 is additive on the failed first head. The remediated head
keeps the failed head as its direct parent and preserves it in history rather
than rewriting it:

```text
A3D_REMEDIATION_COMMIT_PARENT=777a509c5d144deaf4c06a432cddb992b86a28b6
A3D_HISTORY_REWRITTEN=false
A3D_FORCE_PUSH=false
```

After the exact-head pull-request CI reaches a terminal conclusion, this
workstream stops and returns for independent review:

- terminal SUCCESS -> report the exact head SHA, head tree, changed-file set,
  contract implementability, PR number and state, and the exact CI run id,
  event, attempt and result, then stop;
- any terminal non-success -> report the actual workflow conclusion, the
  affected job or jobs, and the failing step when available, then stop.

The remediated head requires a fresh independent exact-head review; the first
review's failure is not cleared by this document's own claim.

Merge remains unauthorized. Implementation, privileged execution, CI workflow
change, production change and registry admission each remain separately
unauthorized by this document.
