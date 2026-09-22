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
  implementability is not proved. The helper instead opens its own child
  descriptor relative to its own validated root descriptor (5.8), so no
  descriptor crosses the `sudo` boundary at all.
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
A3D_FIRST_REMEDIATION_ROUND=1
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

### 1.2 Remediation round 2

The second exact-head A3 design review failed the head that round 1 produced,
and that failure is preserved here as well:

```text
SECOND_A3D_REVIEW_FAILED_HEAD=8d791a82b1e482c586a0c8c1f990d722c4b8464e
SECOND_A3D_REVIEW_FAILED_TREE=4dc41e1c878468a04f90be96fcc3120c28f5c72b
SECOND_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
A3D_SECOND_REMEDIATION_ROUND=2
A3D_CURRENT_REMEDIATION_ROUND=2
A3D_HISTORY_ADDITIVE=true
```

History remains additive across both rounds: `777a509...` (first failed head)
then `8d791a8...` (second failed head) then this head. Neither failed head is
rewritten, amended, rebased or force-pushed, and both failure records stay in
this document. Each round is recorded by its own token —
`A3D_FIRST_REMEDIATION_ROUND=1` in 1.1, `A3D_SECOND_REMEDIATION_ROUND=2` and
`A3D_CURRENT_REMEDIATION_ROUND=2` here — so no round fact is stated twice with
two different values.

The second review's three findings are corrected in this document:

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | A fact with no explicit carrier was classified `EXPLICITLY_HANDED_OFF`: the mount namespace row described inherited kernel-carried process state as an explicit handoff, collapsing membership continuity and identity observation into one misclassified row. | 5.5, 5.6, 10.2 |
| 2 | The privileged ownership mutation was not confined to an object the helper had itself acquired and pinned: the root descriptor and the child name were validated, but the mutation target was not pinned as an inode, leaving the privileged `chown` open to symlink substitution and to being applied to a hardlinked child. | 5.8 |
| 3 | The `pull_request` workflow definition was described as "taken from the PR head". That is not the provenance model of the event, and it left the definition actually executed by GitHub unbound to the exact-head definition being independently reviewed. | 6.2, 6.3 |

Finding 1 is a continuity-classification failure, finding 2 is an object-identity
confinement failure, and finding 3 is a workflow-provenance failure. All three
are design-document failures of this contract: no production code is involved in
any of them and none is changed by this remediation.

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

Two further controls are reacquired by the ordinary evidence process after the
privileged helper has exited and before the production call, per 5.8:

```text
CONTROL_post_mutation_st_nlink_eq_1=true
CONTROL_post_mutation_xattr_and_acl_empty=true
```

They are separate measurements, taken after the ownership mutation, because the
pre-mutation preconditions above are established before the privileged action
and therefore cannot witness what the privileged action left behind.

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

The child-object consequence of this rule is frozen in 5.8: the helper opens the
fixed fixture child itself, relative to its own validated root descriptor, and
performs the privileged ownership mutation on the descriptor it opened.

### 5.5 Privileged-boundary model

The fixture spans a privilege boundary and a namespace boundary, so both are
modeled explicitly. Every fact that crosses either boundary is exactly one of
the following three classes, and the classes are mutually exclusive:

- `INHERITED` — the receiving phase holds the state as a kernel-carried property
  of the very process that crossed the boundary. There is no separate carrier
  and no message; the state is not transmitted, it is possessed.
- `INDEPENDENTLY_REACQUIRED` — the receiving phase re-derives the fact from the
  real object with its own observation instead of receiving a value.
- `EXPLICITLY_HANDED_OFF` — the value is transmitted across the boundary by a
  declared carrier, with a declared lifetime and a declared closing checkpoint.

No fourth classification exists, and no fact may be left unclassified. A fact
whose continuity is inheritance MUST NOT be described as an explicit handoff: an
explicit handoff requires a carrier, and inherited process state has none.
`INDEPENDENTLY_REACQUIRED` is therefore also the class for a fact that both
phases must hold but that is never transmitted — for example a value both phases
derive from the same frozen contract text, as 5.1 already states of the third
element of its protocol. Such a fact is classified rather than left unclassified,
and its class says explicitly that no continuity is claimed for it.

Two namespace facts were previously collapsed into a single misclassified row
and are now stated separately:

```text
MOUNT_NAMESPACE_MEMBERSHIP_CONTINUITY=INHERITED
MOUNT_NAMESPACE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED
MOUNT_NAMESPACE_FACT_EXPLICIT_HANDOFF=none
```

`MOUNT_NAMESPACE_MEMBERSHIP_CONTINUITY=INHERITED` means the evidence process and
the helper inherit membership in the already-created private mount namespace
across the declared `fork`/`exec`/`sudo` lifecycle, as a kernel-carried property
of those processes: the `sudo` identity transition changes credentials and does
not change mount namespace membership. `MOUNT_NAMESPACE_IDENTITY_OBSERVATION=
INDEPENDENTLY_REACQUIRED` means each process independently reads its own real
`/proc/self/ns/mnt` identity and reports that value; no process receives another
process's identity, and no identity is inferred from the lifecycle, from a
process name, or from the presence of a `sudo`.

| Fact | Classification | Carrier and lifetime | Closing checkpoint |
| --- | --- | --- | --- |
| Invocation root path | `EXPLICITLY_HANDED_OFF` as an untrusted locator only | `--root` argument, valid for one helper invocation, carrying no authority | helper independently revalidates the root under 5.3 before any mutation |
| Case/action selection | `EXPLICITLY_HANDED_OFF` as a closed enum name only | `--case` argument, valid for one helper invocation | helper rejects any value outside the 5.2 table before any mutation |
| Target uid, target mode, child names | `INDEPENDENTLY_REACQUIRED` | both phases derive them from the same frozen contract text (5.2, 5.8); no value is transmitted and no runtime carrier exists | 4.3 paired controls measure the resulting real state; a caller value can never reach them |
| Helper exit status | `EXPLICITLY_HANDED_OFF` as a non-evidence completion signal only | process status of the helper process, valid for one invocation, carrying no authority | never accepted as evidence; the ordinary process reacquires the state itself |
| Fixture child identity before the ownership mutation | `INDEPENDENTLY_REACQUIRED` by the helper | the descriptor the helper opens for itself relative to its own validated root descriptor (5.8) | pre-mutation child validation passes before the first `chown`/`chmod` |
| Fixture ownership, mode and link state after the ownership action | `INDEPENDENTLY_REACQUIRED` by the ordinary evidence process | ordinary evidence process re-derives them with its own `lstat` and `os.open` | the paired controls of 4.3, including the post-mutation link and attribute reacquisitions, all hold before the production call |
| Mount namespace membership continuity | `INHERITED` | the process's own mount-namespace membership, carried by the kernel across `fork`, `exec` and the `sudo` identity transition within one private namespace; valid until namespace exit | the membership statements of T5, N4 and N5 hold, and the identity equality below is measured |
| Mount namespace identity observation | `INDEPENDENTLY_REACQUIRED` | each process reads its own real `/proc/self/ns/mnt` inode and reports that value | `PRIVATE_EVIDENCE_MNT_NS_ID == PRIVATE_HELPER_MNT_NS_ID` and `PRIVATE_EVIDENCE_MNT_NS_ID != HOST_MNT_NS_ID`, both measured in 10.1 |
| Privileged mount source and target objects | `INDEPENDENTLY_REACQUIRED` by the helper | objects the helper creates exclusively for itself under its validated root in the private namespace (5.9); no caller-created object is ever used, and no object is handed off | a pre-existing object at a role name yields `HELPER_ROOT_REJECTED`, and each object is revalidated against its pinned identity before use |
| Fixture mount state inside the private namespace | `INDEPENDENTLY_REACQUIRED` by each consumer | the real private mount table, read by whichever phase needs the fact; no mount fact is inherited and none is handed off | pre-drift positive admission plus the 10.4 state machine |
| Loop backing device | `INDEPENDENTLY_REACQUIRED` | ordinary evidence process re-reads the real loop state rather than trusting helper output | `LOOP_BACKING_RESIDUE=false` at the end of 10.4 |
| Host mount namespace and host mount table | no fact crosses either boundary: the observer stays outside, the host identity is measured where it is produced, and the private namespace never propagates to the host | real host mount table read by the host observer | host-namespace absence control in 10.3, before and after the run |

The last row declares the absence of a crossing fact and therefore carries no
class; it is not an unclassified fact.

**Round-2 classification audit.** Every row of 5.5, of the 5.6 transition ledger
and of the 10.2 namespace table was re-checked against the three classes above.
The audit changed four classifications and confirmed the rest:

| Location | Previous statement | Audit result | Corrected statement |
| --- | --- | --- | --- |
| 5.5, mount namespace identity | `EXPLICITLY_HANDED_OFF` by inheritance through `fork`, `exec` and `sudo` within one private namespace | `MISCLASSIFIED`: inherited process state has no carrier, so it cannot be an explicit handoff, and the row also collapsed membership continuity with identity observation | split into `MOUNT_NAMESPACE_MEMBERSHIP_CONTINUITY=INHERITED` and `MOUNT_NAMESPACE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED` |
| 5.5, target uid / target mode / child names | `INHERITED` from frozen design constants | `MISCLASSIFIED`: nothing is inherited across the boundary; each phase derives these from the same frozen contract text and no value is transmitted | `INDEPENDENTLY_REACQUIRED` |
| 5.5, helper exit status | `INDEPENDENTLY_REACQUIRED` | `MISCLASSIFIED`: the parent does not re-derive the helper's status, it receives it; the status has a real carrier but is not evidence | `EXPLICITLY_HANDED_OFF` as a non-evidence completion signal |
| 5.5, mounts created inside the private namespace | `INHERITED` within the private namespace only | `MISCLASSIFIED`: a mount is not inherited across a process boundary; each consumer reads the shared namespace's real mount table for itself | `INDEPENDENTLY_REACQUIRED`, with the sharing substrate supplied by the `INHERITED` membership row |
| 5.5 remaining rows | already matched a single class | `CONFIRMED` | unchanged |
| 5.6 T1-T8 | class implicit, transition ledger | `CONFIRMED` or corrected per row; an explicit class column is now frozen | see 5.6 |
| 10.2 N1-N6 | class implicit, namespace table | `CONFIRMED` or corrected per row; an explicit class column is now frozen | see 10.2 |

The helper's own report is not evidence. If the ordinary process cannot
independently reacquire the state the helper claims to have produced, the case
is a `QUALIFICATION_GAP`.

### 5.6 Boundary transition ledger

Each transition across the privilege or namespace boundary carries exactly one
continuity class per crossing fact, plus exactly one authority owner, producer,
carrier, lifetime, consumer and closing checkpoint. A transition with no closing
checkpoint is not frozen here and MUST NOT be implemented.

| # | Transition | Crossing fact and class | Authority owner | Producer | Carrier | Lifetime | Consumer | Closing checkpoint |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | evidence process -> fixture root creation | real root identity, owner and mode: `INDEPENDENTLY_REACQUIRED` by the helper | ordinary runner identity | non-root evidence process | real directory under the runner temporary area | one run attempt | privileged helper (validates) and evidence process (uses) | helper root validation under 5.3 passes before any mutation |
| T2 | evidence process -> helper: case selection | case name: `EXPLICITLY_HANDED_OFF` as a closed enum name | this contract (frozen enum) | non-root evidence process | `--case` argument | one helper invocation | privileged helper | enum membership checked before any mutation |
| T3 | evidence process -> helper: root locator | root path text: `EXPLICITLY_HANDED_OFF` as an untrusted locator | this contract (untrusted input) | non-root evidence process | `--root` argument | one helper invocation | privileged helper | independent revalidation under 5.3 |
| T4 | helper -> filesystem: ownership and mode mutation | real inode metadata: `INDEPENDENTLY_REACQUIRED` by the non-root evidence process | this contract (frozen constants) | privileged fixture helper | real inode metadata, mutated through the helper-pinned child descriptor (5.8) | until cleanup | non-root evidence process | 4.3 paired controls, including the post-mutation reacquisitions, all recorded before the production call |
| T5 | evidence process -> private namespace entry | namespace membership: `INHERITED`; namespace identity: `INDEPENDENTLY_REACQUIRED` by each process | ordinary runner identity | privileged namespace launcher | inherited mount namespace, plus each process's own `/proc/self/ns/mnt` reading | until namespace exit | evidence process and helper | the three identity controls in 10.1 agree |
| T6 | launcher -> private namespace: fixture mount | mount objects and mount state: `INDEPENDENTLY_REACQUIRED` by each consumer; nothing is handed off | this contract | privileged fixture helper | real mount table entry inside the private namespace, and the helper-created source and target objects of 5.9 | until detach and release | non-root evidence process | pre-drift positive admission plus the 10.4 state machine |
| T7 | private namespace -> observer: absence fact | host-table absence: `INDEPENDENTLY_REACQUIRED` by the host observer | this contract | host observer, recorded by the workflow | real mount table read from the host namespace | one run attempt | independent reviewer | host-namespace absence control passes before and after the run |
| T8 | run -> reviewer: evidence publication | recorded run facts including the workflow-provenance facts of 6.3: `EXPLICITLY_HANDED_OFF` through the workflow output carrier | repository design authority | privileged workflow | workflow output bound to head SHA, tree, runner identity and workflow-definition identity | retained as CI evidence | independent reviewer | exact-head binding, workflow-authority equality and residue controls recorded |

T4 is the only transition that changes privilege-owned state, and its authority
owner is this contract rather than the caller. T3 is the only transition that
carries caller-provided text, and it closes at validation, not at use. T5 is the
only transition whose continuity is inheritance, and nothing about it is
handed off.

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

### 5.8 Freeze: privileged child inode confinement

A validated root descriptor is not by itself sufficient authority to mutate a
child of that root. Before the first privileged ownership mutation, and after
5.3 has validated the root, the helper acquires the fixture child itself and
validates that exact object. A child name is never validated and then mutated
through a re-resolved pathname.

Conceptual helper-local acquisition, relative to the helper's own validated root
descriptor:

```text
child_fd = openat(validated_root_fd, FIXTURE_FILE_ROLE, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
```

`O_NOFOLLOW` makes a symlink at the role name an open failure rather than a
redirection, and opening relative to the helper's own descriptor means the
caller's string is never re-resolved. The helper then performs its own `fstat`
on `child_fd` and MUST require, before the first `chown` or `chmod`:

| Required property of the pinned child | Frozen requirement |
| --- | --- |
| object type | regular file (`S_ISREG`): never a directory, device, socket, fifo or symlink |
| link state | `st_nlink == 1` |
| pre-mutation owner | exactly the ordinary runner uid |
| pre-mutation mode | exactly the fixture's approved initial mode `FIXTURE_FILE_INITIAL_MODE=0640`, hence `mode & 0o022 == 0` |
| permission bits | no setuid, setgid or sticky bit set: the helper asserts `S_ISUID`, `S_ISGID` and `S_ISVTX` all clear explicitly, instead of relying on the exact-mode equality alone |
| identity | nonzero `st_dev` and nonzero `st_ino` |
| role scope | the one fixed derived role for the selected case and nothing else; the helper acquires no other child for an ownership action |

A hardlinked child (`st_nlink != 1`) is rejected BEFORE any privileged mutation,
and a symlinked child cannot be opened at all under `O_NOFOLLOW`. Both are hard
refusals with a non-pass outcome, and neither may be repaired by deleting,
replacing or re-creating the object. If the role name does not exist, or exists
as an unexpected object, the helper refuses as well: for the ownership cases the
fixture file is created by the ordinary runner before the helper runs and the
helper never creates it.

The privileged ownership mutation then operates on the pinned child descriptor,
never on a pathname:

```text
fchown(child_fd, derived_target_uid, observed_gid)
fchmod(child_fd, 0o644)
```

The order is frozen: `fchown` first, `fchmod` second. Some filesystems clear
setuid/setgid bits as part of an ownership change, so the frozen `0644` literal
is applied after the ownership change and the resulting mode is exactly the
frozen literal regardless of that kernel behavior. `derived_target_uid` is the
5.2 derivation for the selected case, and `observed_gid` is the `st_gid` the
helper observed on the pinned descriptor; no caller value participates in
either.

```text
OWNERSHIP_MUTATION_TARGET_PINNED_BY_FD=true
OWNERSHIP_MUTATION_FOLLOWS_SYMLINK=false
OWNERSHIP_MUTATION_ACCEPTS_HARDLINK=false
OWNERSHIP_PREMUTATION_NLINK_REQUIRED=1
OWNERSHIP_MUTATION_SYSCALL_TARGET=pinned_child_descriptor
OWNERSHIP_MUTATION_CHOWN_BEFORE_CHMOD=true
HELPER_LOCAL_CHILD_ACQUISITION=true
HELPER_CHILD_ACQUISITION_ORDER=after_root_validation_before_any_mutation
HELPER_CHILD_ACQUISITION_TYPE=regular_file
HELPER_CHILD_ACQUISITION_IDENTITY_NONZERO=true
HELPER_CHILD_ACQUISITION_ROLE_SCOPE=fixed_derived_role_only
HELPER_CHILD_SYMLINK_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_HARDLINK_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_UNEXPECTED_OBJECT_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_MISSING_OUTCOME=HELPER_ROOT_REJECTED
FIXTURE_FILE_INITIAL_MODE=0640
FIXTURE_FILE_INITIAL_MODE_IS_EXACT=true
FIXTURE_FILE_PREMUTATION_OWNER=ordinary_runner_uid
NO_FD_CROSSES_SUDO_BOUNDARY=true
```

`FIXTURE_FILE_INITIAL_MODE=0640` is the approved pre-mutation mode, and it is a
different fact from the frozen post-mutation `FILE_MODE=0644` of 4.1. The
prohibition on `0600` in 4.1 is a requirement on the post-mutation mode that the
case observes, not a statement about the fixture's initial mode, and
`0640 & 0o022 == 0` holds for the initial state exactly as `0644 & 0o022 == 0`
holds for the final state.

`FIXTURE_FILE_ROLE` resolution is case-dependent and frozen as such: for
`own-foreign` and `own-root` the child is created by the ordinary runner before
the helper is invoked, and the helper pins and validates it without creating it;
for `mount-fixture` the child is created by the helper inside the helper's own
freshly created ext4 filesystem after the mount (5.9), and it is then pinned and
validated by the same rule set before any use.

Because no descriptor crosses the `sudo` boundary (5.4), the helper opens this
descriptor itself, after its own root validation, and
`HELPER_ACCEPTS_INHERITED_DESCRIPTOR=false` continues to hold: a caller-supplied
or inherited descriptor is never accepted, and the helper never mutates a
descriptor it did not open itself.

Python expresses the acquisition directly as
`os.open(FIXTURE_FILE_ROLE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)`,
whose underlying operation is `openat` relative to `root_fd`, with
`os.fstat`, `os.fchown` and `os.fchmod` acting on the returned descriptor. No
step of this freeze requires a descriptor to cross the privilege boundary. This
statement is scoped to the declared qualification platform: `dir_fd`-relative
`os.open` and `os.fchown` are Linux facilities, the runner is `ubuntu-latest`
(section 6), and `NO_WINDOWS_QUALIFICATION=true` (section 18) means no other
platform is claimed here. On the declared platform all three descriptor
operations exist and need no dependency beyond the standard library.

The ordinary evidence process does not accept the helper's report of the
mutation. After the helper has exited and before the production call, that
process independently reacquires, from the real object and with no privilege:

```text
POST_HELPER_ST_UID_REACQUIRED=true
POST_HELPER_MODE_REACQUIRED=true
POST_HELPER_REAL_ORDINARY_OPEN_REACQUIRED=true
POST_HELPER_ST_NLINK_REACQUIRED=true
POST_HELPER_XATTR_AND_ACL_REACQUIRED=true
POST_HELPER_REACQUISITION_BEFORE_PRODUCTION_CALL=true
```

Those five reacquisitions are the `CONTROL_*` rows and post-mutation control
rows of 4.3. A missing, failing or unrecorded reacquisition is
`QUALIFICATION_GAP`, never a pass.

### 5.9 Freeze: privileged mount child safety

The mount fixture has the same confinement problem as the ownership fixture and
the same answer: the helper creates the privileged mount's source and target
itself, under its own validated root descriptor in the private namespace, and
treats anything already present at a role name as a refusal rather than as
something to adopt, repair or remove.

`IMAGE_ROLE` and `MOUNTPOINT_ROLE` are fixed derived names from 5.2, never
caller text, and no caller-created symlink or hardlink may become the privileged
mount source or target. The creation semantics are frozen as invariants rather
than as a single syscall list, because the two objects are different kinds of
object and one primitive cannot express both:

- the image object is a regular file the helper creates exclusively, so that any
  pre-existing object at `IMAGE_ROLE` fails creation instead of being opened;
- the mountpoint object is a directory the helper creates exclusively, so that
  any pre-existing object at `MOUNTPOINT_ROLE` — file, symlink or directory —
  fails creation instead of being used;
- both creations are performed relative to the helper's own validated root
  descriptor with no-follow semantics, and neither creation follows a symlink;
- after creation each object is pinned by a descriptor the helper holds, and its
  real `st_dev` and `st_ino` are recorded: the source must be a regular
  single-link file, and the target must be a real directory;
- the loop backing device is acquired by the helper itself and never supplied by
  the caller;
- immediately before the mount, both objects' real identity is re-derived and
  MUST still equal the pinned identity, and the target must still be a directory
  with no symlinked component in the resolution path.

```text
PRIVILEGED_MOUNT_SOURCE_AND_TARGET_CREATED_BY_HELPER=true
PRIVILEGED_MOUNT_PREEXISTING_ROLE_OUTCOME=HELPER_ROOT_REJECTED
PRIVILEGED_MOUNT_SOURCE_ROLE=IMAGE_ROLE
PRIVILEGED_MOUNT_TARGET_ROLE=MOUNTPOINT_ROLE
PRIVILEGED_MOUNT_ROLE_NAMES_DERIVED=true
PRIVILEGED_MOUNT_ACCEPTS_CALLER_PATH=false
PRIVILEGED_MOUNT_ACCEPTS_CALLER_NAME=false
PRIVILEGED_MOUNT_ACCEPTS_CALLER_DEVICE=false
PRIVILEGED_MOUNT_SOURCE_SYMLINK_ALLOWED=false
PRIVILEGED_MOUNT_TARGET_SYMLINK_ALLOWED=false
PRIVILEGED_MOUNT_SOURCE_EXCLUSIVE_CREATE=true
PRIVILEGED_MOUNT_TARGET_EXCLUSIVE_CREATE=true
PRIVILEGED_MOUNT_SOURCE_NLINK_REQUIRED=1
PRIVILEGED_MOUNT_SOURCE_HARDLINK_OUTCOME=HELPER_ROOT_REJECTED
PRIVILEGED_MOUNT_TARGET_IDENTITY_PINNED=true
PRIVILEGED_MOUNT_PINNED_IDENTITY_RECHECKED_BEFORE_USE=true
PRIVILEGED_LOOP_DEVICE_SELECTED_BY_HELPER=true
```

The mount operation itself is a pathname operation: `mount(2)` accepts paths
rather than descriptors and has no descriptor-based form. This contract
therefore freezes the invariant — helper-created objects, exclusive creation,
no caller-created source or target, and identity revalidation — rather than
claiming a descriptor pin for the mount syscall itself. A revalidation failure
is a hard refusal before any privileged effect beyond the creation the helper
already performed.

One consequence is worth stating explicitly, because it constrains how the
implementation may verify the target rather than what it must achieve: once a
filesystem is mounted on the target path, a path-based `stat` of that path
reports the mounted filesystem's root inode rather than the directory the helper
created. The invariant is that the object the helper created is the object its
own mount covers; the implementation may verify that in any way that really
establishes it, for example with a descriptor opened on the target before the
mount, whose identity is unaffected by the covering mount. If the target's
identity cannot be established to still be the helper's own pinned object, the
fixture is a failed construction: the outcome is `QUALIFICATION_GAP` plus a
design finding, cleanup follows 10.4, and it is never a pass.

For `mount-fixture`, `FIXTURE_FILE_ROLE` is created by the helper inside its own
newly created ext4 filesystem after the mount, and it is then pinned by
descriptor and validated under the 5.8 rule set before any use. The ownership
mutation of 5.8 applies only to the `own-foreign` and `own-root` cases; the
mount case performs no ownership mutation, and the mounted file's ownership is
never reported as RQP-L09 evidence.

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
- its checkout MUST bind to the exact PR head SHA being qualified, never to the
  `refs/pull/<PR_NUMBER>/merge` synthetic merge commit the event itself runs
  against, and never to a moving branch tip;
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

- it MUST also record and check the workflow-provenance facts of 6.3, whose
  equality requirement is a precondition of every privileged effect.

### 6.2 Frozen event model

The selected event model is `pull_request`. This is the preferred model because
it names the exact commit under qualification through
`github.event.pull_request.head.sha` while the run holds no base-repository write
trust, unlike `pull_request_target`.

The event's own ref and the code under qualification are two different facts.
On a `pull_request` event the run executes in the context of the synthetic merge
commit rather than in the context of the head object, so `GITHUB_REF` is
`refs/pull/<PR_NUMBER>/merge` and `GITHUB_SHA` names that merge commit. The
workflow definition GitHub executes is therefore the copy of the workflow file
resolved from the event-ref object, which contains the merge of the base and the
head on that path and is not guaranteed to be byte-identical to the head's copy.
An earlier version of this document stated that the workflow definition is
simply "taken from the PR head"; that statement is withdrawn as factually wrong,
and 6.3 replaces it with the actual provenance model plus the equality check
that makes the executed definition provably identical to the exact-head
definition being independently reviewed. The event model itself is unchanged by
this correction: it is still `pull_request` on `base=main`, and no
`pull_request_target`, `workflow_run` or other elevated-context event is
introduced.

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

### 6.3 Frozen pull-request workflow provenance

Two authorities are separated here because they are resolved from different Git
objects and neither implies the other:

- `WORKFLOW_DEFINITION_AUTHORITY` — the workflow file GitHub actually executes
  for the privileged event, resolved from the event-ref object;
- `CODE_UNDER_QUALIFICATION_AUTHORITY` — the repository content the fixture
  qualifies, checked out explicitly at `github.event.pull_request.head.sha`.

```text
PULL_REQUEST_EVENT_REF=refs/pull/<PR_NUMBER>/merge
PULL_REQUEST_EVENT_SHA=synthetic_merge_commit
PRIVILEGED_WORKFLOW_DEFINITION_PATH=.github/workflows/l4_privileged_qualification.yml
WORKFLOW_DEFINITION_AUTHORITY=event_ref_object
CODE_UNDER_QUALIFICATION_AUTHORITY=exact_head_object
PRIVILEGED_WORKFLOW_CHECKOUT_SOURCE=github.event.pull_request.head.sha
WORKFLOW_DEFINITION_AUTHORITY_SEPARATE_FROM_CODE_AUTHORITY=true
```

The privileged run MUST record, from its own real environment and from real Git
objects, every one of:

```text
GITHUB_WORKFLOW_REF
GITHUB_REF
GITHUB_SHA
PR_NUMBER
PR_HEAD_SHA
PR_HEAD_TREE
PRIVILEGED_WORKFLOW_EVENT_REF_BLOB_SHA
PRIVILEGED_WORKFLOW_HEAD_BLOB_SHA
```

`PRIVILEGED_WORKFLOW_EVENT_REF_BLOB_SHA` is the blob identity of
`.github/workflows/l4_privileged_qualification.yml` at the event-ref object named
by `GITHUB_SHA`, and `PRIVILEGED_WORKFLOW_HEAD_BLOB_SHA` is the blob identity of
the same path at `PR_HEAD_SHA`. Both are resolved from authoritative Git objects
— for example `git rev-parse <object>:<path>` against an explicitly fetched
`refs/pull/<PR_NUMBER>/merge` and against the fetched head object, or the
equivalent blob identities read from the repository contents API at those two
commits with the run's read-only token. The checked-out worktree copy is not a
substitute for either, because the worktree holds only the head copy, and
`GITHUB_WORKFLOW_REF` is recorded as corroboration rather than in place of the
blob comparison.

A Git blob identity is a content hash, so equality of those two values is
byte-identity of the workflow definition. Before ANY privileged mutation the run
MUST require:

```text
PRIVILEGED_WORKFLOW_EVENT_REF_BLOB_SHA == PRIVILEGED_WORKFLOW_HEAD_BLOB_SHA
```

If the workflow definition GitHub is executing is not byte-identical to the
exact-head workflow being independently reviewed, the privileged run MUST STOP
privileged fixture execution:

```text
PRIVILEGED_WORKFLOW_AUTHORITY_MISMATCH_OUTCOME=WORKFLOW_AUTHORITY_MISMATCH
PRIVILEGED_WORKFLOW_AUTHORITY_CHECK_ORDER=before_any_privileged_mutation
PRIVILEGED_WORKFLOW_AUTHORITY_CHECK_PRIVILEGE=none
PRIVILEGED_WORKFLOW_MISMATCH_STOPS_PRIVILEGED_EFFECT=true
```

No `sudo`, `unshare`, `mount`, `umount`, `chown`, `chmod`, `mkfs` or `losetup`
may occur after that mismatch. The check itself needs no privilege, so it is
performed before the first privileged step and every privileged step depends on
its result; a run in which any privileged step can execute without that
predecessor does not satisfy this contract. A missing blob identity, an
unresolvable ref, or a malformed value is itself a mismatch and is never treated
as equality.

The same run MUST also bind the code under qualification to the exact head:

```text
CHECKED_OUT_HEAD_EQUALS_PR_HEAD_SHA=true
CHECKED_OUT_HEAD_TREE_EQUALS_PR_HEAD_TREE=true
```

`git rev-parse HEAD` on the checked-out repository MUST equal
`github.event.pull_request.head.sha`. `PR_HEAD_TREE` is derived, never supplied:
it is `git rev-parse HEAD^{tree}` on that proven checked-out head, published as
the run's own output, and the independent reviewer compares the published value
against the tree of the reviewed head SHA. Either failure is
`WORKFLOW_AUTHORITY_MISMATCH` under the same stop rule, because a run that
qualifies a different object than the head under review cannot produce evidence
about that head.

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

Membership continuity and identity observation are separate facts, frozen that
way in 5.5: membership is `INHERITED` across this lifecycle, because the `sudo`
identity transition changes credentials rather than mount namespace membership,
while identity is `INDEPENDENTLY_REACQUIRED` by every process. The equality above
is therefore measured rather than inferred from that inheritance, and a
process that cannot read its own real identity cannot satisfy this contract.

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

Each row names its crossing fact and its single continuity class, alongside the
authority owner, producer, carrier, lifetime, consumer and closing checkpoint
the 5.6 ledger requires.

| # | Transition | Crossing fact and class | Authority owner | Producer | Carrier | Lifetime | Consumer | Closing checkpoint |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N1 | host baseline -> observer | host mount table state: `INDEPENDENTLY_REACQUIRED` by the host observer | this contract | host observer | observed host mount table | one run attempt | independent reviewer | pre-run absence baseline recorded |
| N2 | host -> private namespace creation | namespace membership: `INHERITED`; namespace identity: `INDEPENDENTLY_REACQUIRED` by each process | reviewed privileged identity | privileged namespace launcher | real mount namespace | until namespace exit | evidence process and helper | private namespace identity differs from host identity |
| N3 | propagation state | real propagation flags: `INDEPENDENTLY_REACQUIRED` from the shared namespace object | this contract | privileged namespace launcher | real propagation flags of the private namespace root | until namespace exit | evidence process and helper | propagation is private before any mount mutation |
| N4 | launcher -> evidence process: namespace membership | membership: `INHERITED` across `fork`/`exec`; identity: `INDEPENDENTLY_REACQUIRED` by the evidence process | ordinary runner identity | privileged namespace launcher | inherited mount namespace across `fork`/`exec` | until namespace exit | evidence process | `PRIVATE_EVIDENCE_MNT_NS_ID` measured and equal to the private identity |
| N5 | evidence process -> helper: namespace membership | membership: `INHERITED` across the `sudo` identity transition, which changes credentials and not namespace membership; identity: `INDEPENDENTLY_REACQUIRED` by the helper | reviewed privileged identity | privileged fixture helper | inherited mount namespace across `sudo` | one helper invocation | helper | `PRIVATE_HELPER_MNT_NS_ID` measured and equal to `PRIVATE_EVIDENCE_MNT_NS_ID` |
| N6 | private namespace -> host: absence | host-table absence: `INDEPENDENTLY_REACQUIRED` by the host observer | this contract | host observer | observed host mount table | one run attempt | independent reviewer | post-run absence control recorded |

No row in this table is an explicit handoff. Namespace membership is inherited
and namespace identity is independently reacquired; nothing about the namespace
crosses as a transmitted value.

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
findings these remediations froze: the closed helper argument vector and the
derived constants of 5.1-5.2, the continuity classes and ledgers of 5.5-5.6, the
child-inode confinement facts of 5.8, the privileged mount child-safety facts of
5.9, the three measured namespace identities and namespace classes of 10.1-10.2,
the cleanup state machine and residue controls of 10.4, and the workflow trigger,
permission, exact-head binding and provenance facts of 6.1-6.3, including the
`PRIVILEGED_WORKFLOW_EVENT_REF_BLOB_SHA == PRIVILEGED_WORKFLOW_HEAD_BLOB_SHA`
requirement and the `WORKFLOW_AUTHORITY_MISMATCH` stop rule. A frozen token with
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

The round-1 check was re-run against the round-1 corrected document, in which
the helper protocol (5.1-5.4), the boundary model (5.5-5.6), the process and
namespace topology (10.1-10.2) and the cleanup state machine (10.4) are the
corrected statements. Round 2 re-runs it against this head, in which the
cross-boundary classification (5.5, 5.6, 10.2), the privileged child inode
confinement (5.8), the privileged mount child safety (5.9) and the pull-request
workflow provenance (6.2, 6.3) are the corrected statements. Each result is
claimed only because the document at that head has no
producer/carrier/lifecycle/consumer contradiction:

```text
RQP_L09_FOREIGN_OWNER_IMPLEMENTABILITY=PASS
RQP_L09_ROOT_OWNED_IMPLEMENTABILITY=PASS
RQP_L17_HELD_MOUNT_REPRESENTATION_DRIFT_IMPLEMENTABILITY=PASS
HELPER_PROTOCOL_IMPLEMENTABILITY=PASS
NAMESPACE_LIFECYCLE_IMPLEMENTABILITY=PASS
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS
CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY=PASS
PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS
PRIVILEGED_WORKFLOW_PROVENANCE_IMPLEMENTABILITY=PASS
RQP_L17_L105_MOUNT_ID_CHANGE_IMPLEMENTABILITY=NOT_CONSTRUCTIBLE_WITH_KNOWN_REAL_MECHANISM
A3_CONTRACT_IMPLEMENTABILITY=PASS
```

`A3_CONTRACT_IMPLEMENTABILITY=PASS` is claimed only after the three round-2
results above it are `PASS`, and each of those three is claimed for a stated
reason:

- `CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY=PASS` — every row of 5.5, 5.6 and
  10.2 now carries exactly one of the three classes; the namespace facts are
  split into an `INHERITED` membership fact and an `INDEPENDENTLY_REACQUIRED`
  identity fact, so no inherited state is described as an explicit handoff, and
  no row claims a class without the carrier that class requires. The round-2
  audit table in 5.5 records each reclassification.
- `PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS` — the privileged
  ownership mutation operates on a descriptor the helper opened for itself
  relative to its own validated root descriptor, so the target object is
  confined before the mutation; every required pre-mutation check is an `fstat`
  fact on that descriptor, the mutation is expressible as `os.fchown` and
  `os.fchmod` on it, the acquisition is expressible as
  `os.open(..., dir_fd=...)`, and no descriptor has to cross the `sudo`
  boundary, so no unprovable transport is required.
- `PRIVILEGED_WORKFLOW_PROVENANCE_IMPLEMENTABILITY=PASS` — `GITHUB_REF` and
  `GITHUB_SHA` name the event-ref object; both workflow blob identities are
  resolvable from authoritative Git objects or from the repository contents API
  with the run's read-only token; blob identity equality is byte-identity; and
  the check needs no privilege, so it can precede every privileged step. The
  head binding is expressible as `git rev-parse HEAD` against
  `github.event.pull_request.head.sha`, with `PR_HEAD_TREE` derived from the
  proven checked-out head rather than read from an input the run cannot possess.

The three previously contradictory requirements and the four round-1 remediation
findings resolve as follows:

| Finding | Corrected statement | Why it is now implementable |
| --- | --- | --- |
| helper protocol contradiction: "MUST NOT accept caller-supplied path/uid/mode" versus "root path / child / target uid / mode are explicitly handed off" | 5.1-5.4 | exactly one caller-supplied string may cross, the root locator, and it crosses as untrusted data with no authority; uid, gid, mode and child names are derived from frozen constants inside the helper and never cross at all; the argument vector is a closed enum plus that locator |
| namespace lifecycle asserted rather than produced | 10.1-10.2 | four named roles with declared identities and permitted operations, an ordered lifecycle, and three measured mount namespace identities with the required equality and inequality, so "the helper is in the evidence process's namespace" is an observed fact rather than an assumption about `sudo` |
| unconditional second unmount required after successful `MNT_DETACH` | 10.4 | explicit `ATTACHED` / `DETACHED_BUSY` / `RELEASED` states; the `ATTACHED` failure path keeps the checked ordinary unmount, and the `DETACHED_BUSY` path closes retained descriptors, verifies absence from the private mount table, then releases the loop backing; no unmount is required of a mount point that no longer exists |
| authority preview collapsed "no new authority" into one answer | 1 and 17 | five separate authority facts; privileged execution and CI control-plane change authorities are required by the later implementation phase and granted only there, while public API, registry admission and production change remain not required |

The three round-2 remediation findings resolve as follows:

| Finding | Corrected statement | Why it is now implementable |
| --- | --- | --- |
| inherited namespace state classified as an explicit handoff | 5.5, 5.6, 10.2 | the taxonomy now names the three classes with their carrier requirements, keeps `MOUNT_NAMESPACE_MEMBERSHIP_CONTINUITY=INHERITED` and `MOUNT_NAMESPACE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED` as separate facts, marks `MOUNT_NAMESPACE_FACT_EXPLICIT_HANDOFF=none`, and gives 5.6 and 10.2 an explicit class column so no row is left implicit |
| privileged ownership mutation not confined to a pinned child inode | 5.8 | the helper opens the fixture child itself relative to its own validated root descriptor with `O_NOFOLLOW`, validates regular-file type, `st_nlink == 1`, ordinary-runner pre-mutation owner, exact initial mode `0640`, cleared setuid/setgid/sticky bits and nonzero `st_dev`/`st_ino`, then performs `fchown` and `fchmod` on that descriptor; a symlinked or hardlinked child is a hard refusal before any privileged mutation, and the ordinary process still reacquires the resulting state itself |
| `pull_request` workflow definition described as "taken from the PR head" | 6.2, 6.3 | the event-ref object is frozen as `refs/pull/<PR_NUMBER>/merge` with the synthetic merge commit as `GITHUB_SHA`, the code under qualification is separately bound to `github.event.pull_request.head.sha`, the two workflow blob identities are recorded and required to be equal before any privileged mutation, and a mismatch stops privileged execution as `WORKFLOW_AUTHORITY_MISMATCH` |

| Requirement | Authority owner | Required evidence | Producer | Carrier / holder | Lifetime | Consumer / verifier | Closing checkpoint | Failure outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Helper argument protocol | repository design authority (this contract) | the exact argument vector, the derived uid/mode/child constants, and the rejection of every non-enumerated argument | privileged fixture helper | helper command line (closed enum plus untrusted locator) and the frozen constant table | one helper invocation | independent reviewer; ordinary suite unchanged | argument rejection and root revalidation recorded before any mutation | `HELPER_ARGUMENT_REJECTED`, `HELPER_ROOT_REJECTED` or `QUALIFICATION_GAP` |
| Process and namespace topology | same | the four roles with their real identities, the ordered lifecycle, and three measured mount namespace ids | privileged namespace launcher, evidence process and helper | real mount namespace identity of each running process | one run attempt, retained as CI evidence | independent reviewer | `PRIVATE_EVIDENCE_MNT_NS_ID == PRIVATE_HELPER_MNT_NS_ID` and `PRIVATE_EVIDENCE_MNT_NS_ID != HOST_MNT_NS_ID`, both measured | `QUALIFICATION_GAP` plus a design finding; no mount mutation is attempted |
| Cross-boundary continuity classification | repository design authority (this contract) | every row of 5.5, 5.6 and 10.2 with exactly one class, and the carrier that class requires | this contract for the model; the fixture for the measured facts | the frozen tables of 5.5, 5.6 and 10.2, and the real objects the classified facts describe | this document for the model; one run attempt for the measured facts | independent reviewer | the round-2 audit table in 5.5 and the class columns of 5.6 and 10.2 contain no unclassified or doubly classified row | a class without its required carrier, or an inherited fact described as a handoff, is a design failure and blocks the implementation PR |
| Privileged child inode confinement | same | pre-mutation `fstat` facts on the pinned child, the refusal outcomes, and the post-mutation reacquisitions by the ordinary process | privileged fixture helper for the mutation; non-root evidence process for the reacquisitions | the helper's own child descriptor, and the real inode the ordinary process re-reads afterwards | one helper invocation, then one evidence measurement | independent reviewer; ordinary suite unchanged | child validation recorded before the first `chown`/`chmod`, and the 4.3 post-mutation controls recorded before the production call | `HELPER_ROOT_REJECTED` before mutation, or `QUALIFICATION_GAP` |
| Privileged mount child safety | same | exclusive creation of the image and mountpoint by the helper, the pinned identities, and the pre-use revalidation | privileged fixture helper | helper-created objects under the validated root, each pinned by a descriptor the helper holds | one run attempt | independent reviewer | pre-existing role objects refuse as `HELPER_ROOT_REJECTED`, and both objects match their pinned identity before use | `HELPER_ROOT_REJECTED`, or `QUALIFICATION_GAP` plus a design finding |
| Privileged workflow provenance | same | `GITHUB_WORKFLOW_REF`, `GITHUB_REF`, `GITHUB_SHA`, `PR_NUMBER`, `PR_HEAD_SHA`, `PR_HEAD_TREE` and both workflow blob identities, recorded and compared | privileged workflow, resolving real Git objects with its read-only token | workflow output bound to the run and to the exact objects it resolved | one run attempt, retained as CI evidence | independent reviewer | `PRIVILEGED_WORKFLOW_EVENT_REF_BLOB_SHA == PRIVILEGED_WORKFLOW_HEAD_BLOB_SHA` before any privileged mutation, plus checked-out `HEAD == PR_HEAD_SHA` and derived `PR_HEAD_TREE` | `WORKFLOW_AUTHORITY_MISMATCH`, with no privileged effect afterwards |
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
the privileged mutation target is pinned by a descriptor the helper opened
rather than re-resolved by pathname (5.8), the privileged mount's source and
target are created by the helper rather than adopted from the caller (5.9), the
executed workflow definition is compared against the exact-head definition
instead of being assumed identical to it (6.3), and no writer/reader evidence
handoff exists or is invented.

Two limits are named rather than papered over, and both are named deliberately.
`mount(2)` accepts pathnames and has no descriptor form, so the mount target is
confined by helper-exclusive creation plus pinned-identity revalidation instead
of by a descriptor argument (5.9). The privileged run cannot read the reviewer's
expected tree, so `PR_HEAD_TREE` is derived from the proven checked-out head and
published for the reviewer to compare rather than read from an input (6.3).
Neither is an assumed continuity, and neither is frozen as a requirement the
declared architecture cannot express.

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
| Every crossing fact carries exactly one continuity class | frozen, sections 5.5-5.6 and 10.2 | none added | not applicable | privileged case later; the classes are pinned by the implementation PR |
| Namespace membership is inherited and namespace identity is independently reacquired | frozen, sections 5.5 and 10.1 | none added | no production symbol changes | privileged case later; the two private identities and the host identity are measured |
| The privileged ownership mutation acts on a helper-pinned child descriptor | frozen, section 5.8 | none added | no production symbol changes | privileged case later; the pre-mutation `fstat` facts and the post-mutation reacquisitions are measured |
| Privileged mount source and target are created by the helper and never adopted from the caller | frozen, section 5.9 | none added | no production symbol changes | privileged case later; exclusive creation and the refusal outcomes are pinned by the implementation PR |
| The executed workflow definition equals the exact-head workflow definition | frozen, section 6.3 | the workflow does not exist yet; the equality is a run-time check, not a declaration | not applicable | workflow contract pinned by a checker in the implementation PR |
| Cleanup follows the frozen state machine and ends residue-free | frozen, section 10.4 | none added | no production symbol changes | privileged case later; the four residue controls are measured, not asserted |
| The privileged workflow authority is frozen | frozen, sections 6.1-6.3 | none added; the workflow does not exist yet | not applicable | workflow contract pinned by a checker in the implementation PR |

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
  details. On the helper side, the descriptor-relative acquisition of 5.8 is
  directly expressible in Python: `os.open(name, flags, dir_fd=root_fd)` is
  `openat` against the helper's own validated root descriptor, with `os.fstat`,
  `os.fchown` and `os.fchmod` acting on the returned descriptor, so the pinned
  child model needs no new API, no new dependency and no descriptor transport.
  No new public API is required.
- Can existing evidence and data structures carry all required facts? Yes: the
  retained security tuple, the mount description triple, the retained
  descriptor identity and the real mount table carry every fact the cases
  assert. The workflow-provenance facts of 6.3 are plain strings and Git blob
  identities, carried by the workflow output the manifest already binds to the
  exact head.
- Is new persistent state required? No. The fixture root is invocation-local
  under `RUNNER_TEMP` and is removed by checked cleanup.
- Is a cross-boundary handoff required? Yes, exactly one privilege boundary,
  modeled in 5.5 and 5.6. It is explicit, bounded, revalidated by the ordinary
  process, and carries no authority: only an untrusted root locator and a closed
  case enum are handed off. Every other crossing fact is inherited (namespace
  membership) or independently reacquired, and the privileged ownership
  mutation's target is acquired by the helper itself (5.8) rather than handed
  off. A second, non-process authority boundary — executed workflow definition
  versus code under qualification — is modeled in 6.3 and closed by a
  blob-identity equality check.
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

Neither remediation round adds a further validation class. Each changes one
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

History is additive across both remediation rounds. Each remediated head keeps
the failed head it corrects as its direct parent, so both failures stay in the
branch history rather than being rewritten:

```text
A3D_REMEDIATION_ROUND_1_PARENT=777a509c5d144deaf4c06a432cddb992b86a28b6
A3D_REMEDIATION_ROUND_2_PARENT=8d791a82b1e482c586a0c8c1f990d722c4b8464e
A3D_REMEDIATION_COMMIT_PARENT=8d791a82b1e482c586a0c8c1f990d722c4b8464e
A3D_HISTORY_REWRITTEN=false
A3D_FORCE_PUSH=false
A3D_AMEND_USED=false
A3D_REBASE_USED=false
A3D_RESET_USED=false
```

The push is fast-forward only, and it is performed only after a fresh read of
the remote branch confirms that the remote head still equals
`8d791a82b1e482c586a0c8c1f990d722c4b8464e`. If the remote authority no longer
equals that SHA, the push does not happen and this workstream stops instead.

After the exact-head pull-request CI reaches a terminal conclusion, this
workstream stops and returns for independent review:

- terminal SUCCESS -> report the exact head SHA, head tree, changed-file set,
  contract implementability, PR number and state, and the exact CI run id,
  event, attempt and result, then stop;
- any terminal non-success -> report the actual workflow conclusion, the
  affected job or jobs, and the failing step when available, then stop.

The remediated head requires a fresh independent exact-head review; neither
earlier review's failure is cleared by this document's own claim.

Merge remains unauthorized. Implementation, privileged execution, CI workflow
change, production change and registry admission each remain separately
unauthorized by this document.
