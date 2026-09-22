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

Scope of this PR is exactly one document, and at this head that document is
modified rather than added, because the exact base already contains it:

```text
CHANGED_FILE=docs/governance/l4_privileged_linux_qualification_v1.md
CHANGED_FILE_COUNT=1
ADDED_FILE=none
FORBIDDEN_CHANGES=src/**,tests/**,scripts/**,.github/**,ci/**,AGENTS.md
EXECUTABLE_PRIVILEGED_CODE=0
```

An earlier round introduced this document as
`ADDED_FILE=docs/governance/l4_privileged_linux_qualification_v1.md`. That
remains the history of how the file arrived, and it is not a claim about this
head.

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
A3D_HISTORY_ADDITIVE=true
```

History remains additive across the rounds: `777a509...` (first failed head)
then `8d791a8...` (second failed head) then `80549a2...` (third failed head)
then the round-4 head `3bc6862...` (fourth failed head) then this head. No failed
head is rewritten, amended, rebased or force-pushed,
and every failure record stays in this document. Each round is recorded by its
own token — `A3D_FIRST_REMEDIATION_ROUND=1` in 1.1,
`A3D_SECOND_REMEDIATION_ROUND=2` here, `A3D_THIRD_REMEDIATION_ROUND=3` in 1.3,
`A3D_FOURTH_REMEDIATION_ROUND=4` in 1.4, and `A3D_FIFTH_REMEDIATION_ROUND=5` with
the current-round pointer in 1.5 — so
no round fact is stated twice with two different values. That rule is now
mechanically checkable and checked: the current-round pointer
`A3D_CURRENT_REMEDIATION_ROUND` is stated exactly once in this document, in the
subsection belonging to the current round — 1.5 at this head, 1.4 at the round-4
head —
because a pointer is a fact about the head it describes. Round 3's own record in
1.3 and round 4's in 1.4 keep
the same information under a head-qualified name,
`A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=3` and
`A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=4`, so each earlier round's fact is
preserved
while the bare pointer keeps one unambiguous value, exactly as round 2's
`SECOND_A3D_REVIEW_FAILED_TREE` is history rather than a claim about the current
tree.

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

### 1.3 Remediation round 3

The third exact-head A3 design review failed the head that round 2 produced with
the same failure class, and that failure is preserved here as well:

```text
THIRD_A3D_REVIEW_FAILED_HEAD=80549a22e2770dd6392771207a3d43af4f9a7d84
THIRD_A3D_REVIEW_FAILED_TREE=f08ad03745cf09763fff6269bcde10bd50324cce
THIRD_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
A3D_THIRD_REMEDIATION_ROUND=3
A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=3
A3D_HISTORY_ADDITIVE=true
```

History is additive across all three rounds. No earlier round, head or finding
is deleted or rewritten by this remediation; the round-1 and round-2 records in
1.1 and 1.2 remain in this document exactly as they were, and round 2's frozen
`SECOND_A3D_REVIEW_FAILED_TREE=4dc41e1c878468a04f90be96fcc3120c28f5c72b` is
history rather than a claim about the current tree.

The third review found four requirements that the declared architecture could
not implement as written. Each is corrected here, and no round-2 pass is
reopened except where a credential fact had to be added:

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | The ownership-helper requirement contradicted itself: the contract froze `FILE_CHOWN_ONLY=true` while the frozen helper performs both `fchown` and `fchmod`, and it froze a pre-mutation mode (`0640`) different from the post-mutation mode (`0644`), so a privileged `chmod` was required to reconcile two facts the ordinary process could have established itself. | 4.1, 4.3, 5.2, 5.8 |
| 2 | The foreign target uid was deferred to the implementation PR ("fixed at implementation time", "the implementation selects exactly one member"), so the contract froze no literal and could not be reviewed, simulated or preflighted against a concrete identity. | 5.2 |
| 3 | The ordinary runner's uid and gid crossed into the privileged namespace launcher with no producer, carrier, lifetime, consumer or closing checkpoint, and `SUDO_UID`-style environment values were the only implicit source, so "the launcher launches the non-root evidence process as the ordinary identity" was an assumption about `sudo` rather than a transported fact. | 5.5, 5.6, 10.1, 10.2, 5.10 |
| 4 | "Non-root evidence process" was defined only by `euid != 0`: the process's real `euid`, `egid` and effective capability set were never required to be reacquired, so a process with nonzero `euid` but retained effective capabilities would have satisfied the contract. | 5.5, 5.6, 10.1, 10.2, 5.10 |

Finding 1 is a self-contradictory-mutation failure, findings 2 and 3 are
missing-authority and missing-continuity failures, and finding 4 is an
identity-observation failure. All four are design-document failures of this
contract: no production code is involved in any of them, and none is changed by
this remediation. The capability consequence is corrected with them: because the
helper no longer performs a privileged `chmod`, the truthfully required
privileged capability for the ownership fixture is `CAP_CHOWN` alone, and 7 now
freezes that instead of a capability set that the helper's real operations do
not need.

### 1.4 Remediation round 4

Rounds 1 to 3 were design-review rounds: an independent review of an exact head
failed this contract, and the next head corrected it. Round 4 is not one of
those. Round 4 was triggered by the implementation-preview workstream that
followed the round-3 design, and what that preview exposed is the contradiction
this round corrects.

The failed implementation attempt is preserved as historical evidence. It is not
amended, rewritten, rebased, force-pushed or continued as if the contract had
passed, and this remediation does not build on it:

```text
A3_IMPLEMENTATION_ATTEMPT_1=FAIL
FAILED_IMPLEMENTATION_HEAD=c55000f1d823ee8eb0d093d80f5312fb75a90d50
FAILED_IMPLEMENTATION_HEAD_TREE=d7bfdad9a4eba7362946619c3f1db94ae3332f91
FAILED_IMPLEMENTATION_BASE=cca7805305b0e369b27d7d29ba3611fb9afd7679
FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
A3D_ROUND4_FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
PRODUCT_FAILURE=false
PRIVILEGED_EXECUTION_PERFORMED=false
REMOTE_PUSH_PERFORMED=false
PR_CREATED=false
A3D_FOURTH_REMEDIATION_ROUND=4
A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=4
A3D_HISTORY_ADDITIVE=true
```

The current-round pointer `A3D_CURRENT_REMEDIATION_ROUND` is not stated here: it is
stated exactly once, in 1.5, because it is a fact about the head it describes.
Round 4's own value is preserved above under the head-qualified name
`A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=4`, exactly as round 3's value is
preserved in 1.3.

`PRODUCT_FAILURE=false` is a measured statement rather than a convenience: the
failed attempt changed five implementation files and no production file, ran no
privileged command, was never pushed and produced no pull request, so no
production behavior was involved in the failure and none is changed by this
remediation. `CONTRACT_IMPLEMENTABILITY_FAILURE` is therefore a failure of this
contract's text, not of the production guards it qualifies.

"Never pushed" was verified rather than transcribed, because it bounds what this
remediation may rely on: every remote ref tip was read from the authoritative
remote, and every one of them was tested for ancestry of the failed head:

```text
A3D_ROUND4_FAILED_HEAD_REMOTE_PROBE=ls_remote_all_refs_plus_ancestry_check
A3D_ROUND4_FAILED_HEAD_REMOTE_TIPS_CHECKED=381
A3D_ROUND4_FAILED_HEAD_REMOTE_TIPS_CONTAINING_HEAD=0
A3D_ROUND4_FAILED_HEAD_REMOTE_TIPS_EQUAL_TO_HEAD=0
A3D_ROUND4_FAILED_HEAD_BRANCH_ABSENT_FROM_ORIGIN=true
```

**The contradiction the preview exposed.** 5.8 froze one pinned-child rule set
whose ownership requirement was that the pinned child's pre-mutation owner be
exactly the ordinary runner uid, and 5.9 simultaneously froze that for
`mount-fixture` the `FIXTURE_FILE_ROLE` child is created by the privileged helper
inside its own newly mounted ext4 filesystem after the mount, and that the mount
case performs no ownership mutation. Those facts cannot all hold at once:

- the mount-case file is created by the reviewed privileged identity, so its
  owner is that identity and not the ordinary runner uid;
- satisfying the frozen ownership requirement at the mount site would require a
  privileged ownership mutation (`chown`/`fchown`) that 5.9 forbids for this case
  and that `FILE_CHOWN_ONLY=true` confines to the single ownership fixture;
- satisfying it instead by creating the file as the ordinary runner would
  require a credential mutation inside a process that 5.10 requires to be the
  reviewed privileged identity, which no part of this contract authorizes.

The preview exposed this at exactly the site where it bites: the pinned-child
requirements could be applied to the mount child only by not applying the
ownership requirement — silently narrowing the frozen rule set at the one call
site where it did not fit. A frozen rule set that an implementation must narrow
in order to be implementable is not implementable, and the earlier wording that
the mount child is "validated by the same rule set" (5.8) and "under the 5.8 rule
set" (5.9) is withdrawn by this round.

**Round-4 finding.**

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | 5.8 froze the ownership-case owner predicate (`pre-mutation owner == ordinary runner uid`) as a property of one undivided pinned-child rule set, while 5.9 froze that the mount case's `FIXTURE_FILE_ROLE` is created by the privileged helper after the mount and that the mount case performs no ownership mutation. These facts cannot all hold without introducing an unauthorized ownership or credential mutation. | 5.8, 5.9, 15, 16, 17 |

The correction is a split, not a relaxation: the pinned-child requirements are
now one COMMON STRUCTURAL set that applies to every pinned fixture child, plus a
case-specific ownership predicate — the ordinary-runner predicate for the two
ownership cases, and `st_uid == 0` for the mount case. No common structural
requirement is withdrawn, `FILE_CHOWN_ONLY=true` keeps its meaning, and the mount
case gains no ownership effect.

**Design-level privileged-effect closure, re-run for round 4.** One row per
material effect. "Required authority" names what the effect itself needs; it is
not a claim about what the real `sudo` mask happens to carry, which 7 records
separately from the real mask:

| Effect | Target object | Target binding | Required authority / capability | Preconditions | Postconditions | Cleanup / terminal transition |
| --- | --- | --- | --- | --- | --- | --- |
| `own-foreign` `fchown` | the pinned `FIXTURE_FILE_ROLE` inode | the child descriptor the helper opened for itself relative to its own validated root descriptor (5.8.1) | the reviewed privileged identity, plus `CAP_CHOWN` | the common structural requirements of 5.8.1 hold and `st_uid == ORDINARY_UID` | `st_uid == 65534` and `S_IMODE == 0644`, both re-derived on the same pinned descriptor | ownership change only; objects removed by the 10.4 cleanup state machine |
| `own-root` `fchown` | same | same | same | the common structural requirements of 5.8.1 hold and `st_uid == ORDINARY_UID` | `st_uid == 0` and `S_IMODE == 0644`, both re-derived on the same pinned descriptor | same |
| mount-case fixture file creation | the new regular file at `FIXTURE_FILE_ROLE` inside the helper's own freshly mounted ext4 filesystem | helper-exclusive creation under the helper's own mounted target, then pinned by a descriptor the helper opened itself (5.9) | no `CAP_CHOWN` requirement: creation assigns the creating process's own effective uid to the new file and performs no ownership call | the mount is attached, and a pre-existing object at the role name refuses rather than being adopted | owner `0`, exactly `0644`, single link, no symlink | removed with the fixture objects by the 10.4 cleanup state machine |
| mount-case fixture file ownership mutation | none: this case has no ownership target | not applicable: no ownership call exists in this case | none | not applicable | `st_uid` remains `0`; any ownership change is a fixture-construction failure, never a repair | not applicable: no repair and no retry |
| RQP-L17 mount effects (image creation, `mkfs`, loop acquisition, `mount`, `MNT_DETACH`) — **withdrawn as a grouped row in round 5**: one aggregate `CAP_SYS_ADMIN` row is not one row per material effect, and it named no authority for the namespace, propagation, cleanup-unmount, loop-release and removal effects at all (1.5) | the helper's own `IMAGE_ROLE` and `MOUNTPOINT_ROLE`, the loop backing device, and the private namespace mount table | helper-created objects plus the private mount namespace; `mount(2)` is a pathname operation (5.9) | separately frozen and unchanged: bound to `CAP_SYS_ADMIN` and to the real operations the preflight records (7). This round neither restates nor narrows that set; round 5 replaces this row with one row per effect and derives each authority from that effect's own operation | the 5.9 preconditions and the 5.10 credential validation hold | the private namespace's mount state, with pinned identities revalidated before use | the 10.4 cleanup state machine |

```text
OWN_FOREIGN_FCHOWN_REQUIRED_CAPABILITY=CAP_CHOWN
OWN_ROOT_FCHOWN_REQUIRED_CAPABILITY=CAP_CHOWN
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY=CAP_CHOWN
MOUNT_FIXTURE_FILE_CREATION_REQUIRES_CAP_CHOWN=false
MOUNT_FIXTURE_FILE_CREATION_REQUIRES_OWNERSHIP_MUTATION=false
MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false
MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION_EFFECT=NONE
CAP_FOWNER_REQUIRED=false
CAP_DAC_OVERRIDE_REQUIRED=false
CAP_DAC_OVERRIDE_REQUIRED_SCOPE=ownership_effect_and_mount_case_fixture_file
CAP_DAC_OVERRIDE_REQUIRED_FOR_ANY_REQUIRED_OUTCOME=false
CAP_DAC_OVERRIDE_REQUIRED_FOR_ANY_EVIDENCE=false
RQP_L17_MOUNT_EFFECTS_REMAIN_CAP_SYS_ADMIN_BOUND=true
RQP_L17_MOUNT_EFFECTS_REMAIN_CAP_SYS_ADMIN_BOUND_IS_A_ROUND4_RECORD=true
RQP_L17_MOUNT_EFFECTS_REMAIN_CAP_SYS_ADMIN_BOUND_SUPERSEDED_BY_ROUND5=true
PRIVILEGED_EFFECT_CLOSURE_RERUN_FOR_ROUND=4
ROUND4_EFFECT_TABLE_IS_A_ROUND4_RECORD_NOT_THE_CURRENT_CLOSURE=true
ROUND4_AGGREGATE_MOUNT_ROW_WITHDRAWN_BY_ROUND5=true
CURRENT_PRIVILEGED_EFFECT_CLOSURE=section_1_5
CURRENT_PRIVILEGED_EFFECT_CLOSURE_ROWS=16
CURRENT_PRIVILEGED_EFFECT_CLOSURE_ONE_EFFECT_PER_ROW=true
```

`CAP_FOWNER_REQUIRED=false` and `CAP_DAC_OVERRIDE_REQUIRED=false` are scoped
statements, and the scope is part of them: they are claims about the ownership
effect and about the mount-case fixture file. Nothing in this contract changes a
mode, so no FOWNER-governed attribute is touched anywhere, and no required
outcome may be produced by, attributed to, or proved by an access bypass. They
are NOT claims about the separately frozen RQP-L17 mount prerequisite set of 7,
which stays bound to `CAP_SYS_ADMIN` and to the capabilities the real mount
setup records, and which this round does not restate, widen or narrow.

The closure held in both directions at the round-4 head, over the rows above:
every effect those rows named had a declared authority, and no declared authority
was broader than its effect. The
mount case's fixture file adds an effect — exclusive creation — with no ownership
authority attached to it, and the ownership cases keep exactly the `CAP_CHOWN`
authority that their single `fchown` justifies.

That closure is round 4's, over round 4's four rows, and round 5 re-ran it over
the complete effect set (1.5). Two scoped consequences of the re-run belong
beside these tokens. First, `CAP_DAC_OVERRIDE_REQUIRED=false` remains exactly as
scoped by the paragraph above — no required outcome and no piece of evidence may
rest on an access bypass — while the helper's own file access under the
invocation root is a separate, separately declared access authority that
produces no outcome and no evidence (1.5). Second, deriving each mount effect's
authority from that effect's own operation narrows the `CAP_SYS_ADMIN`
attribution rather than widening it: image creation, `mkfs` and the cleanup
removals are not `CAP_SYS_ADMIN` operations, while the private namespace, the
private propagation, the loop configuration, the mount, the detach and the
unmount remain bound to it (1.5, 7). No capability is added to the fixture's
required set by that narrowing, and the narrower attribution is what makes
`NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true` true rather than asserted.

### 1.5 Remediation round 5

Round 4 was triggered by the implementation-preview workstream rather than by a
failed design review (1.4). Round 5 is a design-review round again: the fourth
exact-head A3 design review failed the head that round 4 produced with the same
failure class, and that failure is preserved here rather than rewritten:

```text
FOURTH_A3D_REVIEW_FAILED_HEAD=3bc6862c869590ee128636e2a9ca5b4ddf9603b2
FOURTH_A3D_REVIEW_FAILED_TREE=f5f118a5468bdc0914cf14c3c8bc6a9a8a74d51e
FOURTH_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
FOURTH_A3D_REVIEW_FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
FOURTH_A3D_REVIEW_BLOCKING_FINDINGS=3
A3D_FIFTH_REMEDIATION_ROUND=5
A3D_CURRENT_REMEDIATION_ROUND=5
A3D_HISTORY_ADDITIVE=true
PRODUCT_FAILURE=false
PRIVILEGED_EXECUTION_PERFORMED=false
```

`PRODUCT_FAILURE=false` is a measured statement rather than a convenience: this
round changes one design document, runs no privileged command, and involves no
production code either in the failure or in the correction. The fourth review's
failure is a failure of this contract's text, not of the production guards it
qualifies.

Round 4's record in 1.4 is not rewritten: it keeps its finding, its four effect
rows and its tokens, and the two statements round 5 supersedes are marked there
rather than deleted. The failed head stays in this branch's history as the direct
parent of this round's commit (20), so no earlier head, finding or round is
amended, rebased, force-pushed or dropped.

The three blocking findings are corrected in this document:

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | `FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=ordinary_nonroot_process` was frozen unscoped in the general 5.8 token block, so it stated the mode provenance of the mount case's `FIXTURE_FILE_ROLE` as an ordinary-process fact even though 5.8.3 freezes that file as created by the helper after the mount. | 5.8, 5.8.3 |
| 2 | `HELPER_CHILD_MISSING_OUTCOME=HELPER_ROOT_REJECTED` was frozen unscoped, assigning a role object that the helper did not create — and for `mount-fixture` cannot find because the helper creates it only after privileged mount effects have already occurred — the same pre-mutation refusal the two ownership cases require. | 5.8.1, 5.8.3 |
| 3 | The round-4 privileged-effect table aggregated image creation, `mkfs`, loop acquisition, `mount` and `MNT_DETACH` into one `CAP_SYS_ADMIN` row, and it enumerated neither the namespace and propagation effects nor the cleanup unmount, loop release and removal effects, so real effects had no declared authority and one declared authority was broader than the effects its row named. | 1.5, 7 |

Finding 1 is a provenance-scope failure, finding 2 is an outcome-scope failure,
and finding 3 is a privileged-effect closure failure. All three are
design-document failures of this contract: no production code is involved in any
of them and none is changed by this remediation.

**Finding 1: mode provenance is scoped; the exact mode is not.** Every case still
requires exactly `0644`, and this round changes no mode fact, introduces no
`chmod` and no `fchmod`, and adds no mode-setting authority. What changes is only
the provenance statement: `0644` is established by the ordinary non-root process
in `own-foreign` and `own-root`, and by the reviewed privileged helper at
creation in `mount-fixture`. The general 5.8 token block and 5.8.3 now carry that
split, and section 4.1 keeps its ownership-case facts unchanged because section 4
is scoped to the RQP-L09 `FOREIGN_OWNER` and `ROOT_OWNED` cases.

```text
FIXTURE_FILE_INITIAL_MODE=0644
FIXTURE_FILE_INITIAL_MODE_IS_EXACT=true
FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=ordinary_nonroot_process
FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=own-foreign,own-root
MOUNT_FIXTURE_FILE_INITIAL_MODE=0644
MOUNT_FIXTURE_FILE_INITIAL_MODE_IS_EXACT=true
MOUNT_FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=reviewed_privileged_helper_at_creation
MOUNT_FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=mount-fixture
MODE_FACT_IS_SINGLE_LITERAL_PER_CASE=true
MODE_ESTABLISHING_MECHANISM=creation_only
CHMOD_INTRODUCED_BY_ROUND5=false
FCHMOD_INTRODUCED_BY_ROUND5=false
MODE_PROVENANCE_SCOPE_SPLIT=true
```

**Finding 2: the missing-child outcome is scoped, and the mount case gets its own
after-creation failure contract.** `HELPER_ROOT_REJECTED` is frozen in 5.3 as a
hard refusal before any mutation. That is exactly true for a role object the
helper must find already present, because refusing it happens before the helper
mutates anything. It cannot be true for the mount case's `FIXTURE_FILE_ROLE`,
which the helper itself creates only after the private namespace, the private
propagation, the image, the `mkfs`, the loop backing and the mount have already
occurred: a child that is missing or non-conforming after that point is a
post-creation fixture failure, not a refusal of a caller-side object, and
labelling it `HELPER_ROOT_REJECTED` would claim a pre-mutation position the
lifecycle does not have.

The pre-existing-object refusals are therefore scoped to the cases where the role
must preexist, and the mount case gets a distinct, origin-classified failure
contract. Neither is a pass, neither is repaired with privilege, and neither is
retried:

```text
HELPER_PREEXISTING_CHILD_REFUSAL_SCOPE=own-foreign,own-root
HELPER_CHILD_SYMLINK_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_SYMLINK_OUTCOME_SCOPE=own-foreign,own-root
HELPER_CHILD_HARDLINK_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_HARDLINK_OUTCOME_SCOPE=own-foreign,own-root
HELPER_CHILD_UNEXPECTED_OBJECT_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_UNEXPECTED_OBJECT_OUTCOME_SCOPE=own-foreign,own-root
HELPER_CHILD_MISSING_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_MISSING_OUTCOME_SCOPE=own-foreign,own-root
MOUNT_CASE_CHILD_MISSING_AFTER_CREATION_IS_HELPER_ROOT_REJECTED=false
MOUNT_CASE_CHILD_NONCONFORMANCE_AFTER_CREATION_IS_HELPER_ROOT_REJECTED=false
MOUNT_CASE_CHILD_MISSING_IS_PASS=false
MOUNT_CASE_CHILD_NONCONFORMANCE_IS_PASS=false
MOUNT_CASE_CHILD_MISSING_IS_EVIDENCE=false
MOUNT_CASE_CHILD_MISSING_OUTCOME=FAILURE_CLASSIFIED_BY_5_7_ORIGIN
MOUNT_CASE_CHILD_MISSING_PRODUCT_FAILURE=false
MOUNT_CASE_CHILD_MISSING_ENVIRONMENT_ORIGIN=ENVIRONMENT_FAILURE_WITH_QUALIFICATION_GAP_OUTCOME
MOUNT_CASE_CHILD_MISSING_TOOLING_ORIGIN=TOOLING_FAILURE
MOUNT_CASE_CHILD_MISSING_TEST_ORIGIN=TEST_FAILURE
MOUNT_CASE_CHILD_MISSING_ORIGIN_DISTINCTIONS_REQUIRED=true
MOUNT_CASE_CHILD_MISSING_REPAIR_WITH_PRIVILEGE=false
MOUNT_CASE_CHILD_MISSING_RETRY=false
MOUNT_CASE_CHILD_MISSING_CLEANUP=consume_10_4_state_machine
```

The three origins are kept distinct because they are produced by different
causes, and collapsing them into one stated cause would report a false cause for
at least two of them:

- `ENVIRONMENT_FAILURE` when the helper's own exclusive creation was refused or
  could not complete because of the filesystem, kernel, mount, loop or runner
  state — for example a refused `O_CREAT|O_EXCL`, a read-only or full freshly
  mounted filesystem, or a mount that did not carry the expected filesystem —
  and the fixture therefore could not be constructed: outcome `QUALIFICATION_GAP`
  with that origin.
- `TOOLING_FAILURE` when the helper's own creation or pinning step malfunctioned
  without product causality — the creation was not attempted, was performed at a
  name other than the frozen derived role, was performed under a `umask` that
  could clear the requested mode, or the pin was opened on a name the helper had
  not created.
- `TEST_FAILURE` when the fixture asserted a presence or an identity it did not
  measure, or measured a different object than the one it created.

`PRODUCT_FAILURE` is excluded structurally rather than by preference: the
production primitive has not run at that point, so no production behavior can
have caused the state and none may be blamed for it.

**Finding 3: the full privileged-effect closure, one row per effect.** The
complete effect set at this head is enumerated below, one material effect per
row, each with its own target object, target-binding mechanism, authority derived
from that effect's own operation, preconditions, postconditions and cleanup or
terminal transition. Effects that produce no privileged mutation are still rows,
because the closure has to hold in both directions: it is not enough for every
effect to have an authority, every declared authority must also correspond to an
actual required effect, and no declared authority may be broader than the effect
that needs it.

| # | Operation or effect | Target object | Target binding mechanism | Required authority or capability | Preconditions | Postconditions | Cleanup or terminal transition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | `own-foreign` `fchown(pinned_child_fd, 65534, observed_gid)`; one ownership call and no mode call | the pinned `FIXTURE_FILE_ROLE` inode created by the ordinary runner inside the invocation root | the child descriptor the helper opened for itself through its own validated root descriptor with `O_RDONLY\|O_NOFOLLOW\|O_CLOEXEC` (5.8.1); the call takes the descriptor, so no pathname is re-resolved and the binding is valid from that open until the descriptor is closed | the reviewed privileged identity plus `CAP_CHOWN` (capabilities(7): "make arbitrary changes to file UIDs and GIDs"); no `CAP_FOWNER` and no access bypass is required by the ownership call itself | 5.3 root validation passed; the 5.8.1 common structural facts hold on the pinned descriptor; the 5.8.2 predicate `st_uid == ORDINARY_UID` holds; the ordinary runner's effective uid is not `65534` (5.2); the helper reaches the child through the declared helper access authority | `st_uid == 65534`, `S_IMODE == 0o644`, `st_nlink == 1` and an empty attribute set, re-derived by the helper on the same descriptor and independently reacquired by the ordinary process before the production call (4.3) | terminal: there is no reverse ownership call and no mode restoration, because no mode was changed; the object is removed by the 10.4 state machine |
| E2 | `own-root` `fchown(pinned_child_fd, 0, observed_gid)`; one ownership call and no mode call | same | same | same | same, with the 5.2 `ROOT_OWNED` precondition that the ordinary runner's effective uid is not `0` | `st_uid == 0`, `S_IMODE == 0o644`, `st_nlink == 1` and an empty attribute set, re-derived and reacquired the same way | same |
| E3 | private mount namespace creation: `unshare(CLONE_NEWNS)` performed by the launcher | the calling process's mount-namespace membership; the kernel creates a new mount-namespace object whose identity is the inode reported at `/proc/self/ns/mnt` | the call acts on the calling process itself and takes no pathname and no caller-supplied target, so the binding is the process identity that performs it, valid for that process and its descendants until namespace exit (10.1) | `CAP_SYS_ADMIN` in the user namespace that owns the current mount namespace (capabilities(7): "employ `CLONE_*` flags that create new namespaces with `clone(2)` and `unshare(2)`") | the launcher runs as the reviewed privileged identity via `sudo -n`; the 5.10.2 credential validation is closed before this effect; the preflight recorded `CAP_SYS_ADMIN` from the real `CapEff` (7) | the launcher is in a new mount namespace whose identity is later measured different from `HOST_MNT_NS_ID`; no host mount-table entry changes | the namespace object is destroyed by the kernel when its last member process exits; no explicit teardown exists and the closing control is the host-namespace absence control (10.3) |
| E4 | mount propagation brought to private inside the new namespace: `mount(NULL, "/", NULL, MS_REC\|MS_PRIVATE, NULL)` | the propagation type of the mounts in the private namespace's mount tree, rooted at that namespace's `/` | the path `/`, resolved by the launcher inside the namespace created by E3 and never in the host namespace; the binding is valid for the launcher's stay in that namespace and the effect is ordered strictly after E3 and before every fixture mount | `CAP_SYS_ADMIN` (mount(2) is in the `CAP_SYS_ADMIN` set of capabilities(7)); umount(2) states the same requirement for the `MS_REC\|MS_PRIVATE` preparation it prescribes | E3 completed and the private namespace identity differs from the host identity; no mount mutation has occurred yet | the real propagation flags of the private namespace are private (10.2 N3), so no later mount or unmount event in it can propagate to the host namespace | propagation is a property of the namespace object and dies with it; no host propagation state is written, and the closing control is the 10.3 absence control |
| E5 | exclusive creation of the fixture image as a regular file at `IMAGE_ROLE` (`O_CREAT\|O_EXCL`, helper-exclusive) | the new regular file at the frozen role `IMAGE_ROLE` under the invocation root | the frozen role name resolved relative to the helper's own validated root descriptor with no-follow semantics; `O_EXCL` makes a pre-existing object a refusal rather than an adoption; the created file is then pinned by the helper's own descriptor and its `st_dev`/`st_ino` recorded (5.9) | no `CAP_SYS_ADMIN`, no `CAP_CHOWN` and no ownership call: creation assigns the creating identity's own uid. The create needs write and search permission on the containing directory, which is owner-only and owned by the ordinary runner, so the reviewed privileged identity performs it through the declared helper access authority rather than through a widened root mode | 5.3 root validation passed; no object exists at `IMAGE_ROLE`; the helper access authority is present in the real `CapEff` recorded by the preflight (7) | exactly one regular single-link file exists at `IMAGE_ROLE`, owned by the creating identity, with recorded `st_dev`/`st_ino`; no pre-existing object was adopted, removed or repaired | removed by E13 under the 10.4 state machine; a refused or failed creation is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy, never a pass |
| E6 | ext4 formatting effect: `mke2fs`/`mkfs.ext4` writes a filesystem into the image | the contents of the image file created by E5 | the image path resolved relative to the validated root descriptor, with the image inode identity re-derived equal to the pinned creation identity immediately before formatting, so the format writes the object the helper created and nothing else | no `CAP_SYS_ADMIN`, no mount, no loop device and no ownership call: this is an ordinary userspace write into a file the helper owns, so the image owner's write permission is the whole file-level requirement, together with the declared helper access authority for reaching it through the invocation root; the tool's presence and version are preflight facts (7) | E5 completed; image identity re-derived equal to the pinned identity; `mke2fs` present and recorded; the image is neither mounted nor loop-bound at formatting time | the image contains an ext4 filesystem; the image inode identity is unchanged by the format; the freshly created filesystem root directory satisfies the E9 preconditions | the formatted image is removed by E13; a formatting failure is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy, never a pass |
| E7 | loop backing acquisition: a free loop device is taken and associated with the image (`LOOP_CTL_GET_FREE` with `LOOP_CONFIGURE`, or `LOOP_SET_FD`/`LOOP_SET_STATUS64`; `losetup --find --show`) | the loop device taken by the helper and its association with the image inode | the device is selected by the helper itself and never supplied by the caller (`PRIVILEGED_LOOP_DEVICE_SELECTED_BY_HELPER=true`); the backing file is bound by the descriptor the helper opens on the image, because the loop configuration ioctls take a file descriptor, so the association is descriptor-mediated and is not re-resolved from the role path; the device name and the backing inode are recorded | `CAP_SYS_ADMIN` for privileged block-device ioctls (capabilities(7)), plus the declared helper access authority for reaching the image and the image owner's own write permission; no ownership capability | E5 and E6 completed; the image identity re-derived equal to the pinned identity; `/dev/loop-control` and the loop device nodes exist and are recorded by the preflight (7); the image is a single-link regular file | exactly one recorded loop device is associated with the image inode, and no second loop device is associated with the same backing file, because losetup(8) documents that a shared backing file can corrupt or overwrite data | released by E12 in the 10.4 order; `LOOP_BACKING_RESIDUE=false` is the closing control; a failed acquisition is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy |
| E8 | mount fixture: `mount(loop_device, MOUNTPOINT_ROLE, "ext4", flags, options)` inside the private namespace | the private namespace's mount table entry, and the ext4 filesystem instance carried by the loop device, covering the helper-created `MOUNTPOINT_ROLE` directory | `mount(2)` is a pathname operation with no descriptor form (5.9), so the target is bound by helper-exclusive creation plus pre-mount identity revalidation: the frozen `MOUNTPOINT_ROLE` resolved relative to the helper's own validated root descriptor, its pinned `st_dev`/`st_ino` re-derived immediately before the call, still a real directory with no symlinked component in its resolution path, with the helper's own loop device as the source and no caller-created source or target ever accepted; the binding window is the interval between that revalidation and the call, inside the private namespace | `CAP_SYS_ADMIN` (capabilities(7) lists mount(2) in that set), plus the declared helper access authority for reaching the target path; no ownership capability | E3 and E4 completed; E5, E6 and E7 completed; target identity re-derived equal to the pinned identity; the device appears in no other private-namespace record (section 9 exactly-once rule); private propagation confirmed private before the mount | exactly one private-namespace record carries the new mount, with root field `/` and filesystem type `ext4`; the evidence process shares the namespace and can reach the mount-case file; the host mount table is unchanged | leaves `ATTACHED` through E10 (`detach-fixture`) or through E11 (failure before drift); the terminal states are the 10.4 `RELEASED` and `CLEANUP_FAILED` |
| E9 | exclusive creation of the mount-case fixture file at the frozen role path `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE` inside the helper's own freshly mounted ext4 filesystem, then pinning it | the new regular file inside the mounted ext4 filesystem: the mount case's `FIXTURE_FILE_ROLE`, which is also the retained object of section 9 | the frozen role path is resolved by the helper itself inside the private namespace after the mount is attached: the mounted target is opened relative to the helper's own validated root descriptor with `O_DIRECTORY\|O_NOFOLLOW\|O_CLOEXEC`, and `FIXTURE_FILE_ROLE` is then created relative to that descriptor with `O_CREAT\|O_EXCL` and no-follow semantics. Both components are frozen derived names, no caller text participates, and a pre-existing object at the name fails the creation instead of being adopted; the created file is pinned by the helper's own descriptor and every later check is an `fstat` on that descriptor | no `CAP_CHOWN`, no `CAP_SYS_ADMIN` and no ownership or mode call: creation assigns the creating identity's own uid, which is the frozen `st_uid == 0` of 5.8.3, and the create itself is authorized by the owner write and search bits of the freshly formatted filesystem's root directory, which the reviewed privileged identity owns; reaching that directory through the invocation root uses the declared helper access authority | E8 completed and the mount attached; the mounted root directory's owner is the reviewed privileged identity with owner write and search set, and its mode grants search to the ordinary identity so that the 5.8.3 ordinary `O_RDONLY` witness can reach the file; the creation-time `umask` cannot clear bits from the requested `0644`; no object exists at the role name | exactly one regular single-link file exists at the frozen role path, owned by uid 0, with `S_IMODE == 0o644`, and the helper's `fstat` facts satisfy the 5.8.1 common structural requirements plus the 5.8.3 `st_uid == 0` predicate | removed with the mounted filesystem's contents when the image is removed by E13; a missing or non-conforming child after creation is a non-pass failure classified by the 5.7 origin taxonomy (5.8.3), never `HELPER_ROOT_REJECTED`, never a pass and never repaired with privilege |
| E10 | `MNT_DETACH` detach: `umount2(MOUNTPOINT_ROLE, MNT_DETACH)` inside the private namespace | the fixture mount in the private namespace's mount table | the frozen `MOUNTPOINT_ROLE` resolved relative to the helper's validated root descriptor inside the private namespace, valid only while that mount is still attached and reachable at that path — the same object the pre-drift positive admission and the section 8 step 5-6 controls reference; no caller path participates | `CAP_SYS_ADMIN` (umount(2): "Appropriate privilege (Linux: the `CAP_SYS_ADMIN` capability) is required to unmount filesystems"), plus the declared helper access authority for reaching the path | the mount state is observed `ATTACHED`; the retained evidence descriptor and the pre-drift positive admission of section 8 step 2 already exist, because the detach is the `detach-fixture` action of 5.2 performed after the positive case | mount state `DETACHED_BUSY`: the mount is immediately disconnected from the private mount table while the unmount completes when the mount ceases to be busy (umount(2) `MNT_DETACH`), so the retained descriptor keeps it alive and a second unmount has no object to act on | advances to `RELEASED` only through E12 to E15 after every retained fixture descriptor is closed and the private mount table shows zero records for the held mount id (10.4); never retried blindly, and `SECOND_UNMOUNT_AFTER_MNT_DETACH_REQUIRED=false` |
| E11 | `ATTACHED`-state ordinary cleanup unmount: `umount2(MOUNTPOINT_ROLE, 0)`, performed only in the observed `ATTACHED` state | the fixture mount in the private namespace, still attached because no successful `MNT_DETACH` occurred | the frozen `MOUNTPOINT_ROLE` resolved relative to the helper's validated root descriptor, valid only while the observed state is `ATTACHED`; the state is measured before the effect and in any other state this effect does not occur at all | `CAP_SYS_ADMIN` (umount(2)), plus the declared helper access authority; no ownership capability | cleanup entered with the observed state `ATTACHED` — failure before drift, or the detach not attempted — and no successful `MNT_DETACH` has occurred | the fixture mount is gone from the private mount table and the loop backing becomes releasable; the state machine advances to release and removal | followed by E12, E13, E14 and E15 in that order; `PRIVATE_MOUNT_RESIDUE=false` is the closing control; a failure is `CLEANUP_FAILED`, visible and never retried blindly |
| E12 | loop backing release: the loop device is detached from the image (`LOOP_CLR_FD`, equivalently `losetup -d`) | the loop device acquired by E7 and its association with the image inode | the device recorded at acquisition, held as helper-internal state and never taken from caller text; the release acts on the recorded device and its real state is re-read afterwards rather than inferred | `CAP_SYS_ADMIN` for privileged block-device ioctls (capabilities(7)); no ownership capability and no ownership call | the observed state is `DETACHED_BUSY`, or the `ATTACHED` path has completed through E11; every retained fixture descriptor is closed, because a loop device with an open reference is not releasable and an early attempt would report a false failure and invite a blind retry (10.4) | no loop device is associated with the image; `LOOP_BACKING_RESIDUE=false`, measured rather than asserted, which also allows for the lazy device destruction losetup(8) documents instead of assuming immediate removal | terminal for the effect; E13 to E15 follow; a failure is `CLEANUP_FAILED` with the residual device recorded as diagnostics |
| E13 | fixture image removal: `unlink(IMAGE_ROLE)` | the image file created by E5 and formatted by E6 | the frozen role name resolved relative to the helper's validated root descriptor with no-follow semantics, with the observed object's `st_dev`/`st_ino` re-derived equal to the pinned creation identity immediately before the removal, so a substituted object is never the removal target | write and search DAC permission on the containing directory — the invocation root — exercised through the declared helper access authority; no `CAP_SYS_ADMIN`, no ownership capability and no ownership call, because removing an object never depends on the removed object's owner | E12 completed and the observed state is `RELEASED`, so no mount and no loop association remains; the observed object is the pinned image inode | the image no longer exists, and the mount case's fixture file, which lives inside the image's filesystem, is removed with it | terminal; `FIXTURE_ROOT_RESIDUE` can become false only after E14 and E15 as well; a failure is `CLEANUP_FAILED` with the residual path recorded as diagnostics |
| E14 | mountpoint removal: `rmdir(MOUNTPOINT_ROLE)`, with no recursive and no forced removal | the mountpoint directory the helper created exclusively during the E8 setup | the frozen role name resolved relative to the validated root descriptor with no-follow semantics, with the observed object re-derived before removal as the helper's own pinned directory identity and still a directory | write and search DAC permission on the invocation root, exercised through the declared helper access authority; no capability beyond it and no ownership call | nothing is mounted at that path — the state is `RELEASED`, or the `ATTACHED` path completed through E11 — and the directory is empty, because the mount case's fixture file lives inside the mounted ext4 filesystem and not in this directory | the mountpoint directory no longer exists and no object outside it was touched | terminal; a failure is `CLEANUP_FAILED` |
| E15 | invocation-root removal: `rmdir` of the invocation-specific root after every fixture object inside it is gone | the invocation root directory created by the ordinary process, owned by it, with group and world bits clear and the sticky bit clear | the same real path the helper validated under 5.3, re-derived; the removal requires the observed directory to be that validated root and to be empty, and it never targets a repository, worktree, cache, runtime-data or pre-existing host path | write and search DAC permission on the root's parent directory (`RUNNER_TEMP`), exercised through the declared helper access authority; no `CAP_SYS_ADMIN` and no ownership capability. `CAP_FOWNER` is neither declared nor needed because the parent is required not to be sticky: removing a directory owned by another identity from a sticky directory would need `CAP_FOWNER` (capabilities(7): "ignore directory sticky bit on file deletion"), so a sticky parent is a preflight failure yielding `QUALIFICATION_GAP` rather than an undeclared authority | E13 and E14 completed and every other fixture object under the root removed; the root is empty; the observed directory is the validated root identity; the parent directory is not sticky, as a preflight fact (7) | `FIXTURE_ROOT_RESIDUE=false`, measured; the fixture leaves no persistent state (17) | terminal; a failure is `CLEANUP_FAILED` with the residual path recorded, never retried blindly and never a pass |
| E16 | cleanup ownership restoration: **withdrawn, no such effect exists** — see the resolution below | not applicable: cleanup has no ownership target | not applicable: no ownership call exists in cleanup, so there is nothing to bind | none: no capability can authorize an ownership call that is never made | not applicable | the ownership set by E1 or E2 is unchanged after the production call and until the object is removed, and the mount case has no ownership state to restore at all | the stale section-5 requirement is removed by this round (5, 10.4); no cleanup row declares an ownership authority |

Authority is derived from each effect's own operation rather than from one
blanket grant, and the documented provenance for every privilege used above is
the Linux `man-pages` text rather than local convention: `capabilities(7)`
(man-pages 6.19, page dated 2026-02-08) for `CAP_CHOWN`, `CAP_DAC_OVERRIDE`,
`CAP_FOWNER` and the `CAP_SYS_ADMIN` entries naming `mount(2)`, `umount(2)`,
`clone(2)`/`unshare(2)` namespace flags and privileged block-device ioctls;
`umount(2)` for the `CAP_SYS_ADMIN` unmount requirement, the `MNT_DETACH`
semantics the `DETACHED_BUSY` state is built on, and the `MS_REC|MS_PRIVATE`
preparation it prescribes; and `losetup(8)` (util-linux 2.43) for the loop device
lifecycle ioctls and the shared-backing-file hazard. Those pages were read for
this round and the claims above are taken from them.

Two consequences of deriving authority this way are stated rather than left
implicit. The helper's own file access under the invocation root — opening the
pinned child, reaching the mount-case role path, opening the image for the loop
configuration, and the cleanup removals — needs a DAC bypass, because the root is
owner-only and owned by the ordinary runner while the helper is not its owner; a
world-traversable root would avoid that bypass but would let an unrelated local
user place objects at the frozen role names, which is exactly the substitution
the confinement rules exist to prevent. That access is declared once, as an
authority that produces no required outcome and no evidence:

```text
INVOCATION_ROOT_MODE_IS_OWNER_ONLY=true
INVOCATION_ROOT_S_IMODE_REQUIRED=0700
INVOCATION_ROOT_GROUP_AND_WORLD_BITS_CLEAR=true
INVOCATION_ROOT_STICKY_BIT_CLEAR=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY=CAP_DAC_OVERRIDE
PRIVILEGED_HELPER_ACCESS_AUTHORITY_REQUIRED=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY_SCOPE=helper_file_access_under_the_validated_invocation_root
PRIVILEGED_HELPER_ACCESS_AUTHORITY_EFFECTS=E1,E2,E5,E6,E7,E9,E13,E14,E15
PRIVILEGED_HELPER_ACCESS_AUTHORITY_PRODUCES_REQUIRED_OUTCOME=false
PRIVILEGED_HELPER_ACCESS_AUTHORITY_PRODUCES_EVIDENCE=false
PRIVILEGED_HELPER_ACCESS_AUTHORITY_AVAILABLE_TO_EVIDENCE_PROCESS=false
PRIVILEGED_HELPER_ACCESS_AUTHORITY_SOURCE=reviewed_privileged_identity_capability_set_recorded_by_preflight
CAP_DAC_OVERRIDE_REQUIRED_FOR_ANY_REQUIRED_OUTCOME=false
CAP_DAC_OVERRIDE_REQUIRED_FOR_ANY_EVIDENCE=false
INVOCATION_ROOT_MODE_WIDENED_TO_AVOID_THE_BYPASS=false
```

The second consequence is that the `CAP_SYS_ADMIN` attribution narrows to the
operations that really are mount, namespace, loop or unmount operations, and that
no other `CAP_SYS_ADMIN` use exists anywhere in the fixture:

```text
CAP_SYS_ADMIN_BOUND_EFFECTS=E3,E4,E7,E8,E10,E11,E12
EFFECTS_WITHOUT_CAP_SYS_ADMIN=E1,E2,E5,E6,E9,E13,E14,E15
CAP_SYS_ADMIN_BOUND_TO_OPERATIONS=mount_namespace_creation,mount_propagation_private,loop_configuration,mount_umount
CAP_SYS_ADMIN_USED_FOR_ANY_OTHER_OPERATION=false
CAP_CHOWN_BOUND_EFFECTS=E1,E2
CAP_DAC_OVERRIDE_BOUND_EFFECTS=E1,E2,E5,E6,E7,E9,E13,E14,E15
CAP_FOWNER_BOUND_EFFECTS=none
CAP_DAC_READ_SEARCH_BOUND_EFFECTS=none
OTHER_CAPABILITY_REQUIRED_BY_ANY_EFFECT=false
```

```text
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
PRIVILEGED_EFFECT_CLOSURE_ROUND=5
PRIVILEGED_EFFECT_CLOSURE_ROWS=16
```

**Cleanup ownership restoration is resolved by removal, not by implementation.**
Section 5 previously listed "cleanup ownership restoration and removal of the
invocation-specific fixture root" among the operations privilege is used for.
Round 5 resolves that stale statement by deleting the ownership half of it,
because the real cleanup architecture never restores ownership and never needs
to:

- the ownership cases leave the fixture file owned by the frozen target uid, and
  cleanup removes that file by unlinking it from a directory the ordinary runner
  owns; a removal depends on the containing directory's write and search bits,
  never on the owner of the object being removed, so no ownership change is
  required to remove a `65534`-owned or `0`-owned file;
- the mount case has no ownership change at any point, so it has no ownership
  state to restore at all;
- restoring the ordinary runner's ownership would be a second privileged
  `fchown`, which 5.8.2 does not freeze, which nothing consumes, and which would
  contradict `FILE_CHOWN_ONLY=true` being a statement about the whole privileged
  effect (4.2) and the frozen cleanup order of 10.4;
- `PARENT_DIRECTORY_CHOWN=false` and `HELPER_CHANGES_ANCESTOR_OWNERSHIP=false`
  already forbid every ancestor ownership change, so the only object a
  restoration could target is the fixture file itself, and nothing needs it.

```text
CLEANUP_OWNERSHIP_RESTORATION_REQUIRED=false
CLEANUP_OWNERSHIP_RESTORATION_EFFECT=NONE
CLEANUP_OWNERSHIP_RESTORATION_RESOLUTION=B_REQUIREMENT_REMOVED_AS_NOT_REQUIRED
CLEANUP_OWNERSHIP_RESTORATION_REASON=removal_depends_on_the_containing_directory_and_not_on_the_removed_object_owner
CLEANUP_SECOND_FCHOWN_REQUIRED=false
CLEANUP_SECOND_FCHOWN_PERFORMED=false
CLEANUP_HELPER_OWNERSHIP_CALLS_AFTER_SETUP=0
CLEANUP_REPAIRS_OWNERSHIP=false
CLEANUP_REMOVED_OBJECT_KEEPS_SETUP_OWNERSHIP_UNTIL_REMOVAL=true
CLEANUP_OWNERSHIP_RESTORATION_HAS_AUTHORITY_ROW=E16
CLEANUP_OWNERSHIP_RESTORATION_HAS_IMPLEMENTATION_ROW=E16
```

That resolution is what keeps the closure honest rather than merely complete:
section 5 no longer declares an operation that no effect row, no authority and no
cleanup step implements, and E16 records the withdrawal instead of leaving a
declared privileged effect with no implementation or authority row.

## 2. Exact Base Record

The checked-in Exact Base procedure
([DEVELOPMENT_PLAYBOOK.md](DEVELOPMENT_PLAYBOOK.md) section 1.1,
[AGENT_HANDOFF.md](AGENT_HANDOFF.md) rule 3) was executed for this PR: switch
`main`, fresh fetch of `origin` with prune and tags, `pull --ff-only`, then
verification of `HEAD`, `origin/main`, tree and tracked worktree state.

It was executed for the round-4 head against exact formal main:

```text
BASE_MAIN_SHA=cca7805305b0e369b27d7d29ba3611fb9afd7679
BASE_MAIN_TREE=00b779f9b9a07e57380a30dd05c6da6342a4a9b3
BASE_HEAD_EQUALS_ORIGIN_MAIN=true
TRACKED_WORKTREE_CLEAN=true
A3D_ROUND4_BASE_IS_EXACT_FORMAL_MAIN=true
A3D_ROUND4_BRANCHES_FROM_FAILED_IMPLEMENTATION_HEAD=false
```

The round-3 record of the same procedure is retained as history and is not a
claim about this head:

```text
ROUND3_BASE_MAIN_SHA=7fc8c1395d01bc4f612291fcdf098703a3866dcd
ROUND3_BASE_MAIN_TREE=bc9ac7c846b271eb48adce1a0343276983e1008c
```

The round-4 branch is built from `cca7805305b0e369b27d7d29ba3611fb9afd7679`
alone. `c55000f1d823ee8eb0d093d80f5312fb75a90d50` is recorded in 1.4 as a failed
implementation attempt and is never this branch's parent or base.

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

The same reviewed transport was re-established for the round-4 head, because the
HTTPS failure is a property of this host rather than of one round:

```text
A3D_ROUND4_TRANSPORT=reviewed_confined_ssh
A3D_ROUND4_TRANSPORT_IS_HTTPS=false
A3D_ROUND4_REMOTE_MAIN_READ_FROM_TRANSPORT=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND4_REMOTE_MAIN_MATCHES_COMMAND_LOCAL_FETCH=true
A3D_ROUND4_REMOTE_WRITE_CHANNEL=reviewed_confined_ssh
```

Round 5 keeps that base and that transport. The HTTPS failure is still a property
of this host rather than of one round, and remote truth for this round was read
from two independent authoritative channels rather than from local refs alone:

```text
A3D_ROUND5_BASE_MAIN_SHA=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND5_BASE_MAIN_TREE=00b779f9b9a07e57380a30dd05c6da6342a4a9b3
A3D_ROUND5_BASE_EQUALS_ORIGIN_MAIN=true
A3D_ROUND5_BRANCH=design/a3d-round4-mount-owner-predicate
A3D_ROUND5_PARENT=FOURTH_A3D_REVIEW_FAILED_HEAD
A3D_ROUND5_HTTPS_TRANSPORT_FAILS=schannel_SEC_E_NO_CREDENTIALS_0x8009030e
TRANSPORT_DEGRADED=true
A3D_ROUND5_REMOTE_TRUTH_CHANNELS=reviewed_confined_ssh_and_authoritative_remote_api
A3D_ROUND5_REMOTE_BRANCH_TIP_AT_PREPUSH=3bc6862c869590ee128636e2a9ca5b4ddf9603b2
A3D_ROUND5_REMOTE_MAIN_AT_PREPUSH=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND5_PREPUSH_ORIGIN_BRANCH_REQUIRED=3bc6862c869590ee128636e2a9ca5b4ddf9603b2
A3D_ROUND5_PREPUSH_ORIGIN_MAIN_REQUIRED=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND5_PUSH_IS_FAST_FORWARD=true
A3D_ROUND5_PUSH_IS_FORCE=false
A3D_ROUND5_PUSH_CREATES_NEW_BRANCH=false
A3D_ROUND5_AMEND_USED=false
A3D_ROUND5_REBASE_USED=false
A3D_ROUND5_REMOTE_WRITE_CHANNEL=reviewed_confined_ssh
```

If either pre-push fact no longer holds when the push is attempted, the push does
not happen and this workstream stops instead of rewriting, rebasing or
force-pushing anything. The remote tip of this branch at that moment must be the
failed round-4 head, and `origin/main` must still be
`cca7805305b0e369b27d7d29ba3611fb9afd7679`, or the fast-forward precondition is
false.

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
FIXTURE_FILE_INITIAL_MODE=0644
FILE_MODE=0644
FILE_CHOWN_ONLY=true
PARENT_DIRECTORY_CHOWN=false
OWNERSHIP_HELPER_CALLS_FCHMOD=false
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY=CAP_CHOWN
OWNERSHIP_MUTATION_REQUIRES_CAP_FOWNER=false
OWNERSHIP_MUTATION_REQUIRES_CAP_DAC_OVERRIDE=false
```

### 4.1 Exact mode semantics

`0644` is a literal octal mode (`stat.S_IMODE == 0o644`) and means:

| Class | Bits | Meaning |
| --- | --- | --- |
| owner | `rw` | read and write |
| group | `r` | read only |
| other | `r` | read only |

The mode is established entirely by ordinary, unprivileged file creation, and it
is established once. The ordinary non-root process creates the fixture file and
freezes its mode at exactly `0644` before the privileged helper is ever invoked:

```text
FIXTURE_FILE_INITIAL_MODE=0644
FIXTURE_FILE_INITIAL_MODE_IS_EXACT=true
FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=ordinary_nonroot_process
FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BEFORE_HELPER=true
```

These are ownership-case facts. Section 4 is scoped to the RQP-L09
`FOREIGN_OWNER` and `ROOT_OWNED` cases, so the ordinary-process provenance above
is a statement about those two cases only; the mount case's `FIXTURE_FILE_ROLE`
has a different provenance and is frozen separately in 5.8.3. The exact-`0644`
requirement itself is common to every case (5.8, 5.8.1).

The initial mode and the post-mutation mode are therefore the same literal, not
two facts that have to be reconciled. An earlier version of this contract froze a
different initial mode (`0640`) and required the privileged helper to `chmod` the
file to `0644` after the ownership change. That requirement is withdrawn: the
privileged mutation is `fchown` only (5.8), the helper MUST NOT call `fchmod` at
all, and no privileged `chmod` may be used to reconcile a mode the ordinary
process can set itself. Because no privileged mode change occurs, the pre- and
post-mutation mode facts are one fact and cannot drift apart.

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
OWNERSHIP_MUTATION_CHOWN_ONLY=true
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY=CAP_CHOWN
OWNERSHIP_HELPER_CALLS_FCHMOD=false
```

`FILE_CHOWN_ONLY=true` is a statement about the whole privileged effect, not
about the syscall name alone: the helper changes ownership and nothing else. It
MUST NOT call `fchmod`, `chmod`, `fchownat` with mode semantics, `setxattr`,
`removexattr`, `setfacl` or any other mutator on the fixture file, and it MUST
NOT repair a mode it did not set. The helper verifies the mode it requires and
fails the fixture when that verification does not hold (5.8); it never fixes it
with privilege.

The parent directory stays invocation-owned by the ordinary runner. This keeps
ancestor traversal authority with the ordinary process, so a failure can never
be explained by traversal denial, and it keeps the privileged mutation set as
small as the case allows.

The invocation-specific root and fixture parent MUST also be created with group
and world write bits clear (`mode & 0o022 == 0`), so
ancestor admission goes through the ordinary non-writable path at L111-L113
rather than through the sticky-directory ancestor exception at L112. This
contract neither widens that exception nor depends on it, and no fixture step
may chmod an ancestor to make a case settle. Round 5 freezes the example as the
literal for the invocation root, for the reason 1.5 gives: the root is created
owner-only (`S_IMODE == 0o700`, group, world and sticky bits clear), so an
unrelated local user cannot traverse it and place objects at the frozen role
names, and the helper reaches those objects through its declared access
authority instead of through a widened root mode.

```text
INVOCATION_ROOT_S_IMODE_REQUIRED=0700
INVOCATION_ROOT_STICKY_BIT_CLEAR=true
INVOCATION_ROOT_MODE_WIDENED_TO_AVOID_THE_BYPASS=false
```

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
CONTROL_initial_mode_eq_0644=true
CONTROL_initial_mode_established_by_ordinary_process=true
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

The two ordinary mode facts are therefore one frozen literal measured twice, by
two different processes: the ordinary process records that it established
`FIXTURE_FILE_INITIAL_MODE=0644` before invoking the helper, and the helper
records that the same literal still holds after its `fchown` (5.8). No
privileged `chmod` sits between them, so an observed `0644` after the ownership
change is the ordinary process's own fact surviving the mutation rather than a
mode the helper imposed.

### 4.4 Frozen case outcomes

FOREIGN_OWNER. The target uid is the frozen literal
`FOREIGN_OWNER_TARGET_UID=65534` of 5.2, which is nonzero and differs from the
ordinary reader's effective uid, so `st_uid in (0, os.geteuid())` is false.
Production MUST fail specifically with:

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

The frozen `65534` literal is the same foreign identity the ordinary RQP-L09
fixture convention already uses: `tests/test_schedule_artifact_native_guards.py`
L1777 selects `65534` as the foreign uid whenever the ordinary process is not
root. This contract freezes that literal for the privileged fixture as well, so
the privileged case and the ordinary gap case describe the same foreign
identity instead of two different ones. The ordinary suite's own fallback
(`1` when `geteuid() == 0`) is NOT adopted here: the privileged case's target uid
is a design-frozen constant, never a runtime selection, and 5.2 forbids any
alternate uid.

## 5. Freeze: Privilege Boundary

The ordinary pytest/evidence process remains non-root. Privilege is used only
by a separately invoked fixed helper, and only for:

- setup ownership mutation (`fchown` of the single fixture file, and nothing
  else: no privileged `chmod` is performed anywhere in the fixture);
- removal of the invocation-specific fixture root and of the fixture objects it
  contains, by the `cleanup` action of 5.2 and the 10.4 state machine. Cleanup
  performs no ownership change at all: the earlier phrase "cleanup ownership
  restoration" is withdrawn by round 5 as a requirement the real cleanup
  architecture does not have (1.5, 10.4), because removing an object depends on
  the containing directory's permissions and never on the removed object's
  owner;
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
HELPER_TARGET_IDENTITY_SOURCE=DESIGN_FROZEN_CONSTANT
HELPER_FILE_MODE_SOURCE=DESIGN_FROZEN_CONSTANT
HELPER_CHILD_NAME_SOURCE=DESIGN_FROZEN_CONSTANT
HELPER_ACCEPTS_CALLER_UID=false
HELPER_ACCEPTS_CALLER_GID=false
HELPER_ACCEPTS_CALLER_MODE=false
HELPER_ACCEPTS_CALLER_CHILD_PATH=false
HELPER_ACCEPTS_CALLER_COMMAND=false
HELPER_ACCEPTS_SHELL_FRAGMENT=false
HELPER_ACCEPTS_INHERITED_DESCRIPTOR=false
HELPER_ACCEPTS_ENVIRONMENT_AUTHORITY=false
HELPER_MUTATION_KIND=fchown_only
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

This closed vector governs the privileged fixture helper. The ordinary
credential handoff of 5.10 is a different protocol with a different receiving
process: `--ordinary-uid` and `--ordinary-gid` are launcher arguments accepted
by `PRIVILEGED_NAMESPACE_LAUNCHER`, never by the helper, and the helper's own
vector remains the two arguments above with no addition. A helper that accepted a
uid or gid argument would violate `HELPER_ACCEPTS_CALLER_UID=false` and
`HELPER_ACCEPTS_CALLER_GID=false` regardless of how the value was produced.

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
| `own-foreign` | `fchown` the single fixture file to the frozen foreign uid `65534`; no mode change | the fixed fixture file under the root (`FIXTURE_FILE_ROLE`) | `FOREIGN_OWNER_TARGET_UID` = `65534` | none: the helper verifies `0644`, it does not set it |
| `own-root` | `fchown` the single fixture file to uid 0; no mode change | the fixed fixture file under the root (`FIXTURE_FILE_ROLE`) | `0` | none: the helper verifies `0644`, it does not set it |
| `mount-fixture` | create the loop-backed ext4 mount inside the private namespace | the fixed `IMAGE_ROLE`, `MOUNTPOINT_ROLE` and `FIXTURE_FILE_ROLE` under the root | not applicable | not applicable |
| `detach-fixture` | `MNT_DETACH` the fixed fixture mount inside the private namespace | the fixed `MOUNTPOINT_ROLE` under the root | not applicable | not applicable |
| `cleanup` | release the loop backing and remove the fixed fixture objects under the root, following the state machine in 10.4; an ordinary unmount of a still-attached fixture mount is performed only when the observed state is `ATTACHED` | the fixed roles under the root | not applicable | not applicable |

```text
FOREIGN_OWNER_TARGET_UID          = 65534
FOREIGN_OWNER_TARGET_UID_IS_ZERO  = false
FOREIGN_OWNER_TARGET_UID_SELECTION = DESIGN_FROZEN_LITERAL
FOREIGN_OWNER_TARGET_UID_FROM_CALLER = false
FOREIGN_OWNER_TARGET_UID_FROM_ENVIRONMENT = false
FOREIGN_OWNER_TARGET_UID_RUNTIME_SUBSTITUTION = false
ROOT_OWNED_TARGET_UID             = 0
FIXTURE_FILE_CHMOD                = none
FIXTURE_FILE_MODE_MASK_CLEAR      = 0o022
FIXTURE_FILE_MODE_IS_EXACT        = true
FIXTURE_FILE_ROLE                 = fixed child name under the invocation root
IMAGE_ROLE                        = fixed child name under the invocation root
MOUNTPOINT_ROLE                   = fixed child name under the invocation root
```

`FOREIGN_OWNER_TARGET_UID` is a design-frozen literal: the value `65534` is
frozen by this document, not chosen by the implementation PR and not selected at
runtime. The implementation transcribes it as a single literal constant in the
helper and MUST NOT derive it, compute it, read it, or substitute for it from any
caller input, environment value, or host property. An earlier version of this
contract deferred the literal to implementation time and described a selection
rule; both are withdrawn, because a contract that freezes no literal cannot be
reviewed or preflighted against a concrete identity.

```text
FOREIGN_OWNER_TARGET_UID_IS_DESIGN_FROZEN=true
FOREIGN_OWNER_TARGET_UID_IMPLEMENTATION_MAY_CHOOSE=false
FOREIGN_OWNER_TARGET_UID_RUNTIME_SELECTION=false
FOREIGN_OWNER_TARGET_UID_ALTERNATE_ON_HOST_MISMATCH=false
```

Two representability requirements are attached to that literal. The ordinary
runner's effective uid MUST NOT be `65534`, and the host MUST be able to
represent uid `65534`; if the ordinary runner's effective uid is `65534`, the
`FOREIGN_OWNER` case is not constructible as designed and its outcome is
`QUALIFICATION_GAP`. No alternate uid may be selected at runtime, and the
implementation MUST NOT fall back to a different foreign identity when the frozen
one is unusable: an unusable frozen literal produces a gap, not a substitution.

```text
FOREIGN_OWNER_ORDINARY_EUID_MUST_DIFFER=true
FOREIGN_OWNER_UID_EQ_ORDINARY_EUID_OUTCOME=QUALIFICATION_GAP
```

The same outcome applies when the host cannot represent uid `65534` at all, and
the `ROOT_OWNED` case is likewise `QUALIFICATION_GAP` if the ordinary runner's
effective uid is `0`. A group identity is never caller-supplied either: the
helper leaves `st_gid` as it observed it and reports the observed value. No
fixture step may widen the frozen mode, and `FIXTURE_FILE_MODE_IS_EXACT`
forbids any extra permission bit including setuid and setgid.

Both ownership cases verify the frozen `0644` on the file only, and neither case
sets it. Neither case may chmod, chown, or otherwise mutate an ancestor
directory: the parent stays invocation-owned by the ordinary runner per 4.2, and
ancestor modes are frozen at creation rather than repaired by the helper.

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
  `mode & 0o022 == 0` and, since round 5, the exact owner-only root mode
  `S_IMODE == 0o700` with the sticky bit clear, not a privileged or shared
  location;
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
HELPER_ROOT_OWNER_ONLY_S_IMODE_REQUIRED=0700
HELPER_ROOT_GROUP_WORLD_WRITE_CLEAR_REQUIRED=true
HELPER_ROOT_STICKY_BIT_CLEAR_REQUIRED=true
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

The ordinary credential facts are split the same way, and for the same reason:
the identity the ordinary runner requested the launcher to become, and the
identity the evidence process really has, are two different facts with two
different classes.

```text
ORDINARY_REQUESTED_UID_GID_CONTINUITY=EXPLICITLY_HANDED_OFF
NONROOT_EVIDENCE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED
NONROOT_EVIDENCE_CAP_EFF_REQUIRED=0
```

The first is a request carried by numeric launcher arguments; the second is a
measurement the evidence process takes of itself. They are never the same fact,
and a contract that treated the requested identity as proof of the observed one
would be assuming exactly the credential continuity it is supposed to establish
(5.10).

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
| Ordinary requested uid and gid (identity handoff to the launcher) | `EXPLICITLY_HANDED_OFF` | fixed numeric launcher arguments `--ordinary-uid` / `--ordinary-gid`, produced by a real measurement of the ordinary process and valid for one launcher invocation; `SUDO_UID`/`SUDO_GID` are corroboration only and never the carrier | launcher validates both values against real filesystem state under 5.10.2 before any credential drop; a failure is `LAUNCHER_CREDENTIAL_REJECTED` with no namespace mutation |
| Actual process identity and effective capabilities inside the evidence process | `INDEPENDENTLY_REACQUIRED` | the evidence process reads its own real `euid`, `egid` and `CapEff` from itself (5.10.3); nothing is received from the launcher and no value is inherited | `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_EUID != 0` and `ACTUAL_CAP_EFF == 0` all hold before the production primitive executes |
| Target uid, target mode, child names | `INDEPENDENTLY_REACQUIRED` | both phases derive them from the same frozen contract text (5.2, 5.8); no value is transmitted and no runtime carrier exists | 4.3 paired controls measure the resulting real state; a caller value can never reach them |
| Helper exit status | `EXPLICITLY_HANDED_OFF` as a non-evidence completion signal only | process status of the helper process, valid for one invocation, carrying no authority | never accepted as evidence; the ordinary process reacquires the state itself |
| Fixture child identity before the ownership mutation | `INDEPENDENTLY_REACQUIRED` by the helper | the descriptor the helper opens for itself relative to its own validated root descriptor (5.8) | pre-mutation child validation passes before the privileged `fchown` |
| Fixture ownership, mode and link state after the ownership action | `INDEPENDENTLY_REACQUIRED` by both the helper, in its required post-mutation `fstat` on the pinned descriptor, and the ordinary evidence process, which measures the real object itself | ordinary evidence process re-derives them with its own `lstat` and `os.open`; the helper's own verification is not evidence for the case (5.8) | the paired controls of 4.3, including the post-mutation link and attribute reacquisitions, all hold before the production call |
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

**Round-3 classification audit.** Round 3 added the ordinary credential
transition and re-checked every credential-adjacent row against the same three
classes. No round-2 classification was reopened; two facts were added and one
row's checkpoint was tightened:

| Location | Previous statement | Audit result | Corrected statement |
| --- | --- | --- | --- |
| 5.5 and 5.6, ordinary runner uid/gid across the launcher boundary | absent: the ordinary identity crossed into the launcher with no class, no producer, no carrier, no consumer and no closing checkpoint | `MISSING`: a crossing fact with no classification and no carrier, which 5.5 forbids | `ORDINARY_REQUESTED_UID_GID_CONTINUITY=EXPLICITLY_HANDED_OFF` with fixed numeric launcher arguments as the carrier and launcher validation (5.10.2) as the closing checkpoint |
| 5.5 and 5.6, evidence-process identity and capabilities | absent: "non-root" was asserted from the launch request rather than classified as a fact | `MISSING`: the observed identity is not the requested identity and needs its own class | `NONROOT_EVIDENCE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED`, with `ACTUAL_CAP_EFF == 0` required before the production call (5.10.3) |
| 5.5, fixture ownership/mode/link state after the ownership action | single consumer: the ordinary evidence process | `NARROWED`: the helper now also takes a required post-mutation `fstat` of its own, and the row named only the ordinary process as consumer | both reacquire the fact independently; the helper's verification is explicitly not case evidence, and only the ordinary process's reacquisition is a control |
| 5.5 and 5.6 remaining rows, 10.2 N1-N6 | already matched a single class | `CONFIRMED` | unchanged |

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
| T4 | helper -> filesystem: ownership mutation | real inode metadata: `INDEPENDENTLY_REACQUIRED` by both the helper (its own required post-mutation `fstat`) and the non-root evidence process (which measures the real object) | this contract (frozen constants) | privileged fixture helper | real inode metadata, mutated by `fchown` only through the helper-pinned child descriptor (5.8); the mode is not mutated at all | until cleanup | non-root evidence process (evidence) and privileged fixture helper (its own verification, not evidence) | 4.3 paired controls, including the post-mutation reacquisitions, all recorded before the production call |
| T5 | evidence process -> private namespace entry | namespace membership: `INHERITED`; namespace identity: `INDEPENDENTLY_REACQUIRED` by each process | ordinary runner identity | privileged namespace launcher | inherited mount namespace, plus each process's own `/proc/self/ns/mnt` reading | until namespace exit | evidence process and helper | the three identity controls in 10.1 agree |
| T6 | launcher -> private namespace: fixture mount | mount objects and mount state: `INDEPENDENTLY_REACQUIRED` by each consumer; nothing is handed off | this contract | privileged fixture helper | real mount table entry inside the private namespace, and the helper-created source and target objects of 5.9 | until detach and release | non-root evidence process | pre-drift positive admission plus the 10.4 state machine |
| T7 | private namespace -> observer: absence fact | host-table absence: `INDEPENDENTLY_REACQUIRED` by the host observer | this contract | host observer, recorded by the workflow | real mount table read from the host namespace | one run attempt | independent reviewer | host-namespace absence control passes before and after the run |
| T8 | run -> reviewer: evidence publication | recorded run facts including the workflow-provenance facts of 6.3: `EXPLICITLY_HANDED_OFF` through the workflow output carrier | repository design authority | privileged workflow | workflow output bound to head SHA, tree, runner identity and workflow-definition identity | retained as CI evidence | independent reviewer | exact-head binding, workflow-authority equality and residue controls recorded |
| T9 | ordinary runner -> launcher: requested identity | requested ordinary uid and gid: `EXPLICITLY_HANDED_OFF` | ordinary runner identity (the measured source) | `HOST_OBSERVER` or the ordinary workflow process, measuring its own real `euid`/`egid` | fixed numeric launcher arguments `--ordinary-uid` / `--ordinary-gid` | one launcher invocation | privileged namespace launcher, which validates them under 5.10.2 | `ORDINARY_UID != 0`, valid numeric ids, and invocation-root `st_uid`/`st_gid` equality all recorded before any credential drop |
| T10 | launcher -> evidence process: actual identity | observed `euid`, `egid` and effective capability mask: `INDEPENDENTLY_REACQUIRED` by the evidence process | ordinary runner identity | non-root evidence process, reading its own real process state | none: the value is not transmitted, it is measured in the process that holds it | the evidence process's lifetime | non-root evidence process itself, recorded as the run's own evidence | `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_EUID != 0` and `ACTUAL_CAP_EFF == 0` all hold before the production primitive executes |

T4 is the only transition that changes privilege-owned state, and its authority
owner is this contract rather than the caller. T3 is the only transition that
carries caller-provided text, and it closes at validation, not at use. T5 is the
only transition whose continuity is inheritance, and nothing about it is
handed off. T9 is the only transition that carries a process identity across the
privilege boundary, and it carries a request rather than a fact: it closes only
when the launcher validates it against the real invocation root, and the fact it
requests is separately reacquired by the receiving process in T10. `SUDO_UID` and
`SUDO_GID` are not the carrier of T9; they are recorded, if at all, as
corroboration under 5.10.1.

### 5.7 Failure-origin classification

Every non-pass outcome is classified by origin before it is reported:

| Origin | Meaning for these cases |
| --- | --- |
| `PRODUCT_FAILURE` | the production guard produced the wrong reason, the wrong detail, or the wrong admission after every fixture control held |
| `TEST_FAILURE` | the privileged fixture asserted something it did not measure, or measured the wrong object; the 5.8 post-mutation verification failing on a mode the fixture itself mis-established is this class |
| `ENVIRONMENT_FAILURE` | privilege, capabilities, kernel, tools, filesystem or runner constraints prevented a real fixture |
| `TOOLING_FAILURE` | the helper, shim, workflow or evidence transport malfunctioned without product causality; an unvalidatable ordinary credential handoff (5.10) is this class when the handoff itself was produced correctly |

A `QUALIFICATION_GAP` is the outcome when the real fixture cannot be constructed
as designed, including an unusable frozen foreign uid (5.2), an ordinary runner
whose identity cannot be handed off or validated (5.10), and a post-mutation
mode that is not the frozen literal on a host that produced it (5.8).

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
caller's string is never re-resolved.

The pinned-child requirements are frozen in two layers, because this contract
pins one role name in three cases and those cases do not share an ownership
history. Round 4 froze the split; the earlier single undivided rule set is
withdrawn, because its ownership requirement was not implementable for the mount
case (1.4).

#### 5.8.1 Common structural requirements

The helper performs its own `fstat` on `child_fd` and MUST require every
requirement in this subsection for every case that pins a `FIXTURE_FILE_ROLE`
child — `own-foreign`, `own-root` and `mount-fixture` alike — before that child
is used, mutated or reported on:

| Required property of the pinned child | Frozen requirement |
| --- | --- |
| object type | regular file (`S_ISREG`): never a directory, device, socket, fifo or symlink |
| link state | `st_nlink == 1`; a hardlinked child is a refusal, never something to adopt |
| exact mode | exactly the frozen initial mode `FIXTURE_FILE_INITIAL_MODE=0644`, hence `mode & 0o022 == 0` |
| group and world write | clear: `st_mode & 0o022 == 0`, so the mutation policy at L111-L113 cannot fire on this child |
| permission bits | no setuid, setgid or sticky bit set: the helper asserts `S_ISUID`, `S_ISGID` and `S_ISVTX` all clear explicitly, instead of relying on the exact-mode equality alone |
| device identity | `st_dev != 0` |
| inode identity | `st_ino != 0` |
| role scope | the frozen derived role names for the selected case and nothing else: `FIXTURE_FILE_ROLE` alone for the two ownership cases, and the frozen role path `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE` for `mount-fixture`, whose child lives inside the helper's own mounted filesystem (5.8.3). Both components are frozen derived names; no caller text selects either |
| symlink | none: a symlink at the role name cannot be opened at all under `O_NOFOLLOW` |
| hardlink | none: `st_nlink != 1` is refused before the child is used |
| acquisition | helper-local descriptor acquisition: the helper opens the descriptor itself, relative to its own validated root descriptor, after its own root validation (5.3) |
| caller input | no caller-supplied child path participates: the role name is derived from the frozen case table of 5.2 and is never accepted from, or re-resolved from, caller text |

```text
COMMON_STRUCTURAL_REQUIREMENTS_SCOPE=own-foreign,own-root,mount-fixture
COMMON_STRUCTURAL_REGULAR_FILE_REQUIRED=true
COMMON_STRUCTURAL_NLINK_REQUIRED=1
COMMON_STRUCTURAL_S_IMODE_REQUIRED=0644
COMMON_STRUCTURAL_GROUP_WORLD_WRITE_CLEAR=true
COMMON_STRUCTURAL_SETUID_SETGID_STICKY_CLEAR=true
COMMON_STRUCTURAL_ST_DEV_NONZERO=true
COMMON_STRUCTURAL_ST_INO_NONZERO=true
COMMON_STRUCTURAL_ROLE=fixed_derived_FIXTURE_FILE_ROLE
COMMON_STRUCTURAL_MOUNT_CASE_ROLE_PATH=MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE
COMMON_STRUCTURAL_MOUNT_CASE_ROLE_PATH_COMPONENTS=frozen_derived_names_only
COMMON_STRUCTURAL_SYMLINK_ALLOWED=false
COMMON_STRUCTURAL_HARDLINK_ALLOWED=false
COMMON_STRUCTURAL_ACQUISITION=helper_local_descriptor
COMMON_STRUCTURAL_CALLER_SUPPLIED_CHILD_PATH_ALLOWED=false
```

A hardlinked child (`st_nlink != 1`) is rejected BEFORE any privileged mutation,
and a symlinked child cannot be opened at all under `O_NOFOLLOW`. Both are hard
refusals with a non-pass outcome, and neither may be repaired by deleting,
replacing or re-creating the object.

The four pre-existing-object refusals — symlink, hardlink, unexpected object and
missing object — are frozen for the two cases whose role object must already
exist when the helper runs, `own-foreign` and `own-root`. For those cases the
refusal really does precede every mutation the helper would otherwise perform, so
`HELPER_ROOT_REJECTED` states their position truthfully. They are NOT the common
outcome for all three cases, and round 4's wording that made them common is
withdrawn: for `mount-fixture` the `FIXTURE_FILE_ROLE` object is created by the
helper itself, after the private namespace, the private propagation, the image,
the `mkfs`, the loop backing and the mount have already occurred, so there is no
pre-existing object to refuse and no pre-mutation position to refuse it from. In
that case a missing or non-conforming pinned child is a distinct post-creation
failure, frozen in 5.8.3, which is never `HELPER_ROOT_REJECTED`, never a pass,
never evidence, and never repaired with privilege.

The common structural requirements of the table above remain common to all three
cases, including the exact `0644` requirement: what is scoped is the provenance
of that mode and the outcome of a pre-existing or absent object, not the mode
itself and not the structural rule set.

#### 5.8.2 Ownership-mutation case requirements

The ownership predicate is the case-specific half of the model, and it applies
to exactly two cases:

```text
OWNERSHIP_PREDICATE_SCOPE=own-foreign,own-root
FIXTURE_FILE_PREMUTATION_OWNER=ordinary_runner_uid
FIXTURE_FILE_PREMUTATION_OWNER_SCOPE=own-foreign,own-root
```

For `own-foreign` and `own-root`, and only for those cases, the fixture file is
created by the ordinary runner before the helper is invoked, and the helper MUST
additionally require, before the privileged mutation:

| Required property of the pinned ownership child | Frozen requirement |
| --- | --- |
| pre-mutation owner | exactly the ordinary runner uid: `st_uid == ORDINARY_UID` |
| mode provenance | exactly `0644`, established by the ordinary non-root process before the helper was invoked (4.1) and never repaired by the helper |

The privileged ownership mutation then operates on the pinned child descriptor,
never on a pathname, and it is exactly one ownership call:

```text
fchown(child_fd, derived_target_uid, observed_gid)
```

In these two ownership cases there is no `fchmod` in the helper, before or after
the `fchown`. `0644` is established by the ordinary non-root process at creation
(4.1), before the helper is invoked, so the helper has no reason to set a mode
and no authority to impose one: `FILE_CHOWN_ONLY=true` in 4.2 means the helper's
entire privileged effect is the ownership change. An earlier version of this
contract froze a `fchmod(child_fd, 0o644)` after the `fchown`, on the reasoning
that a filesystem may clear setuid/setgid bits during an ownership change. That
requirement is withdrawn. It contradicted `FILE_CHOWN_ONLY=true`, it required a
privileged
capability the fixture does not need, and it is unnecessary here: the ordinary
process already established exactly `0644` with all setuid, setgid and sticky
bits clear, and the helper asserts those bits explicitly.

`derived_target_uid` is the 5.2 derivation for the selected case — the frozen
literal `65534` for `own-foreign`, and `0` for `own-root` — and `observed_gid` is
the `st_gid` the helper observed on the pinned descriptor; no caller value
participates in either.

**Required post-mutation verification by the helper (ownership cases).** After
the `fchown`, the helper MUST re-derive the facts from the same pinned descriptor
with its own `fstat(child_fd)` and MUST require:

```text
st_uid == derived_target_uid
S_IMODE(st_mode) == 0o644
```

Both are required. If the mode is not still exactly `0644` after the ownership
change, the fixture construction has failed. The helper MUST NOT repair it with a
privileged `chmod`, MUST NOT retry the `fchown` to obtain a different result, and
MUST NOT report the case as a pass. A failed post-mutation verification is
classified by origin under 5.7: `QUALIFICATION_GAP` when the host filesystem,
kernel or environment produced the unexpected state, and `TEST_FAILURE` when the
fixture asserted or measured something other than what it really did. It is
never a product defect, because no production code has run at that point.

This is what makes `FILE_CHOWN_ONLY=true` truthful rather than aspirational. A
helper that chowns and then chmods would need `CAP_FOWNER` for the mode change
and would be able to mask exactly the failure this verification is meant to
expose; a helper that chowns only verifies the mode it must not own and reports
the truth when it changed.

The helper's own post-mutation verification is not evidence for the case, and it
does not replace the ordinary process's reacquisition below: the helper verifies
what it produced, and the ordinary process independently reacquires what the
object really is.

#### 5.8.3 Mount-case requirements

For `mount-fixture` the pinned child has a different provenance and therefore a
different ownership predicate, frozen explicitly rather than inherited from
5.8.2:

```text
MOUNT_FIXTURE_FILE_CREATED_BY_HELPER=true
MOUNT_FIXTURE_FILE_OWNER_UID=0
MOUNT_FIXTURE_FILE_MODE=0644
MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false
MOUNT_FIXTURE_FILE_OWNERSHIP_PREDICATE=st_uid_eq_0
MOUNT_FIXTURE_FILE_OWNERSHIP_PREDICATE_IS_ORDINARY_UID=false
MOUNT_FIXTURE_FILE_CREATION_IDENTITY=reviewed_privileged_identity
MOUNT_FIXTURE_FILE_COMMON_STRUCTURAL_REQUIREMENTS_APPLIED=true
MOUNT_FIXTURE_FILE_INITIAL_MODE=0644
MOUNT_FIXTURE_FILE_INITIAL_MODE_IS_EXACT=true
MOUNT_FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=reviewed_privileged_helper_at_creation
MOUNT_FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=mount-fixture
MOUNT_FIXTURE_FILE_MODE_ESTABLISHED_BY_ORDINARY_PROCESS=false
MOUNT_FIXTURE_FILE_MODE_ESTABLISHED_BEFORE_HELPER=false
MOUNT_FIXTURE_FILE_MODE_ESTABLISHED_BY_CREATION_ONLY=true
MOUNT_FIXTURE_FILE_CHMOD_USED=false
MOUNT_FIXTURE_FILE_FCHMOD_USED=false
MOUNT_CASE_CHILD_ROLE_PATH=MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE
MOUNT_CASE_CHILD_ACQUISITION_CHAIN=validated_root_descriptor_then_post_mount_mountpoint_descriptor_then_child_descriptor
MOUNT_CASE_CHILD_BINDING_WINDOW=after_mount_attached_before_use
```

The mode provenance is what round 5 scoped here, and it is the only thing that
changed: `0644` is still exact, still established at creation, and still never
produced by a mode-changing call. The ordinary process does not create this file,
does not set its mode and cannot reach it before the mount exists, so no token in
5.8 may state an ordinary-process mode provenance for it.

The child is reached at the frozen role path `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE`,
never as a single child of the invocation root, because the file has to live
inside the helper's own mounted ext4 filesystem for the RQP-L17 admission of 8
and 9 to be reachable at all. The helper opens the mounted target relative to its
own validated root descriptor with `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` after the
mount is attached, and creates and pins `FIXTURE_FILE_ROLE` relative to that
descriptor; both components are frozen derived names, so no caller-supplied child
path participates and the confinement property of 5.8.1 is unchanged.

The helper creates the file inside the newly mounted ext4 filesystem while
running as the reviewed privileged identity, exactly as 5.9 freezes. The created
file therefore belongs to that identity, and creation performs no ownership
call. The helper then pins the file with a descriptor it opened itself and
applies the COMMON STRUCTURAL requirements of 5.8.1 to it.

The creation MUST yield exactly `0644` without a `fchmod`: the helper sets its
creation-time umask so that it cannot clear bits from the requested `0644`. That
is a process setting applied at creation, not a mutation of the file, and it
keeps both `FILE_CHOWN_ONLY=true` and
`MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false` true. A mode that is not exactly
`0644` is a failed fixture construction and is never repaired with privilege.

Two real preconditions make that creation and its one witness possible, and both
are measured rather than assumed. The freshly formatted filesystem's root
directory must be owned by the reviewed privileged identity with its owner write
and search bits set, so that the create is authorized by the directory's own
permissions and needs no capability; and it must grant search to the ordinary
identity, so that the ordinary non-root `O_RDONLY` open of the `0644` root-owned
file — the real DAC witness this subsection requires — can reach the file at all
through `MOUNTPOINT_ROLE`. `mkfs.ext4`'s default root directory satisfies both on
the declared runner, and the preflight records the observed owner and mode (7).
If either fails, the fixture cannot be constructed as designed: the outcome is
`QUALIFICATION_GAP` plus a design finding, never a pass and never a privilege
repair.

```text
MOUNT_CASE_EXT4_ROOT_DIR_OWNER_IS_REVIEWED_PRIVILEGED_IDENTITY_REQUIRED=true
MOUNT_CASE_EXT4_ROOT_DIR_OWNER_WRITE_AND_SEARCH_REQUIRED=true
MOUNT_CASE_EXT4_ROOT_DIR_ORDINARY_SEARCH_ALLOWED_REQUIRED=true
MOUNT_CASE_EXT4_ROOT_DIR_CREATE_NEEDS_NO_CAPABILITY=true
MOUNT_CASE_EXT4_ROOT_DIR_PRECONDITION_FAILURE_OUTCOME=QUALIFICATION_GAP
MOUNT_CASE_EXT4_ROOT_DIR_OWNER_AND_MODE_RECORDED_BY_PREFLIGHT=true
```

**Post-creation failure contract for this case.** Because this child is created
by the helper only after privileged mount effects have already occurred, a child
that is absent or non-conforming after creation cannot be refused before those
effects and MUST NOT be reported as `HELPER_ROOT_REJECTED`. It is a non-pass
fixture failure classified by the 5.7 origin taxonomy, with the origins kept
distinct:

```text
MOUNT_CASE_CHILD_MISSING_AFTER_CREATION_IS_HELPER_ROOT_REJECTED=false
MOUNT_CASE_CHILD_NONCONFORMANCE_AFTER_CREATION_IS_HELPER_ROOT_REJECTED=false
MOUNT_CASE_CHILD_MISSING_IS_PASS=false
MOUNT_CASE_CHILD_NONCONFORMANCE_IS_PASS=false
MOUNT_CASE_CHILD_MISSING_IS_EVIDENCE=false
MOUNT_CASE_CHILD_MISSING_OUTCOME=FAILURE_CLASSIFIED_BY_5_7_ORIGIN
MOUNT_CASE_CHILD_MISSING_PRODUCT_FAILURE=false
MOUNT_CASE_CHILD_MISSING_ENVIRONMENT_ORIGIN=ENVIRONMENT_FAILURE_WITH_QUALIFICATION_GAP_OUTCOME
MOUNT_CASE_CHILD_MISSING_TOOLING_ORIGIN=TOOLING_FAILURE
MOUNT_CASE_CHILD_MISSING_TEST_ORIGIN=TEST_FAILURE
MOUNT_CASE_CHILD_MISSING_ORIGIN_DISTINCTIONS_REQUIRED=true
MOUNT_CASE_CHILD_MISSING_REPAIR_WITH_PRIVILEGE=false
MOUNT_CASE_CHILD_MISSING_RETRY=false
MOUNT_CASE_CHILD_MISSING_CLEANUP=consume_10_4_state_machine
```

An `O_CREAT|O_EXCL` creation refused by the freshly mounted filesystem, a mount
that did not carry the expected filesystem, a mode the creation-time `umask` did
clear, or the file being absent when it is pinned is an environment-origin
failure of fixture construction (`QUALIFICATION_GAP` with `ENVIRONMENT_FAILURE`)
when the filesystem, kernel, mount or runner state produced it; a helper step
that never attempted the creation, used a name other than the frozen derived
role, or pinned a name it did not create is `TOOLING_FAILURE`; and a fixture
assertion about a presence or an identity it did not measure is `TEST_FAILURE`.
Round 4's recommendation to freeze one collapsed after-creation outcome is not
adopted, because one value would report a false cause for at least two of the
three origins. `PRODUCT_FAILURE` is excluded structurally rather than excused:
the production primitive has not run at that point, so no production behavior can
have caused the state and none may be blamed for it.

The helper MUST NOT apply the ownership-case precondition
`st_uid == ORDINARY_UID` to this child. Before use it MUST instead require:

```text
MOUNT_FIXTURE_FILE_ST_UID == 0
```

No `chown` and no `fchown` is permitted for the mount-case file, by any process
and at any point: `MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false` is a prohibition
rather than an observation. An owner other than `0` is a fixture-construction
failure that MUST NOT be repaired with privilege and MUST NOT be reported as a
pass; the correct outcome is `QUALIFICATION_GAP` plus a design finding.

**Why the mount-case owner is `0`.** The production owner policy at L110 admits
`st_uid in (0, os.geteuid())`. The mount-case file is root-owned, and `0` is a
member of that admitted tuple, so the production primitive admits the owner
predicate for a non-root evidence process with no ownership mutation and no
credential mutation introduced to arrange it:

```text
MOUNT_FIXTURE_FILE_OWNER_PREDICATE_ADMITTED_BY_PRODUCTION=true
MOUNT_FIXTURE_FILE_OWNER_PREDICATE_ADMISSION_LITERAL=0
MOUNT_FIXTURE_ROOT_OWNER_IS_RQP_L09_EVIDENCE=false
MOUNT_FIXTURE_ORDINARY_READ_IS_REAL_DAC_WITNESS=true
```

`MOUNT_FIXTURE_ROOT_OWNER_IS_RQP_L09_EVIDENCE=false` is a scope statement about
the evidence this contract claims: the mount case qualifies the RQP-L17
held-mount representation drift of 8 and 11, and no root-owned object in the
mount fixture may be reported as an RQP-L09 ownership case, as ownership
evidence, or as a substitute for the paired controls of 4.3. What the literal
`0` supports is the mount case's admissibility, not an RQP-L09 result. This
subsection does not widen section 11 either: A3 still claims no end-to-end
`_NativeScope` proof for this mount, and the admission fact above is a property
of the fixture's own object rather than a new production proof.

That admission is real rather than assumed only if the ordinary evidence process
really reads the file. The mount case MUST therefore require a real,
unprivileged `O_RDONLY` open of the `0644` root-owned file to succeed before the
positive pre-drift admission of 8 step 2:

- the open is performed by `NONROOT_EVIDENCE_PROCESS`, whose `ACTUAL_EUID != 0`
  and `ACTUAL_CAP_EFF == 0` are reacquired and required first (5.10.3), so a
  privileged read cannot stand in for it and no capability can produce the
  success;
- the read succeeds through the real `0644` DAC bits of a root-owned file, which
  is what `MOUNT_FIXTURE_ORDINARY_READ_IS_REAL_DAC_WITNESS=true` claims; the
  helper's own open of the same file is not that witness (7);
- a failed ordinary open is a fixture-construction and attribution failure —
  `QUALIFICATION_GAP`, never a pass and never a product defect — because the
  production owner policy has not been reached at that point;
- the same requirement already governs the retained object of section 9, which
  the ordinary non-root process must be able to open read-only without
  privilege.

```text
MOUNT_FIXTURE_PRE_DRIFT_ORDINARY_OPEN_REQUIRED=true
MOUNT_FIXTURE_PRE_DRIFT_ORDINARY_OPEN_BEFORE_POSITIVE_ADMISSION=true
MOUNT_FIXTURE_PRE_DRIFT_ORDINARY_OPEN_IS_PRIVILEGED=false
MOUNT_FIXTURE_PRE_DRIFT_ORDINARY_OPEN_FAILURE_OUTCOME=QUALIFICATION_GAP
```

```text
OWNERSHIP_MUTATION_TARGET_PINNED_BY_FD=true
OWNERSHIP_MUTATION_FOLLOWS_SYMLINK=false
OWNERSHIP_MUTATION_ACCEPTS_HARDLINK=false
OWNERSHIP_PREMUTATION_NLINK_REQUIRED=1
OWNERSHIP_MUTATION_SYSCALL_TARGET=pinned_child_descriptor
OWNERSHIP_MUTATION_KIND=fchown_only
OWNERSHIP_HELPER_CALLS_FCHMOD=false
OWNERSHIP_HELPER_CALLS_CHMOD=false
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY=CAP_CHOWN
OWNERSHIP_MUTATION_REQUIRES_CAP_FOWNER=false
OWNERSHIP_MUTATION_REQUIRES_CAP_DAC_OVERRIDE=false
OWNERSHIP_POSTMUTATION_STAT_TARGET=pinned_child_descriptor
OWNERSHIP_POSTMUTATION_ST_UID_EQ_DERIVED_TARGET=true
OWNERSHIP_POSTMUTATION_S_IMODE_REQUIRED=0644
OWNERSHIP_POSTMUTATION_MODE_REPAIR_WITH_PRIVILEGE=false
OWNERSHIP_POSTMUTATION_MODE_FAILURE_OUTCOME=QUALIFICATION_GAP_OR_TEST_FAILURE_BY_ORIGIN
HELPER_LOCAL_CHILD_ACQUISITION=true
HELPER_CHILD_ACQUISITION_ORDER=after_root_validation_before_any_mutation
HELPER_CHILD_ACQUISITION_TYPE=regular_file
HELPER_CHILD_ACQUISITION_IDENTITY_NONZERO=true
HELPER_CHILD_ACQUISITION_ROLE_SCOPE=fixed_derived_role_only
HELPER_CHILD_SYMLINK_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_SYMLINK_OUTCOME_SCOPE=own-foreign,own-root
HELPER_CHILD_HARDLINK_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_HARDLINK_OUTCOME_SCOPE=own-foreign,own-root
HELPER_CHILD_UNEXPECTED_OBJECT_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_UNEXPECTED_OBJECT_OUTCOME_SCOPE=own-foreign,own-root
HELPER_CHILD_MISSING_OUTCOME=HELPER_ROOT_REJECTED
HELPER_CHILD_MISSING_OUTCOME_SCOPE=own-foreign,own-root
HELPER_PREEXISTING_CHILD_REFUSAL_SCOPE=own-foreign,own-root
HELPER_PREEXISTING_CHILD_REFUSAL_IS_COMMON_TO_ALL_CASES=false
FIXTURE_FILE_INITIAL_MODE=0644
FIXTURE_FILE_INITIAL_MODE_IS_EXACT=true
FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=ordinary_nonroot_process
FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=own-foreign,own-root
FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_IS_COMMON_TO_ALL_CASES=false
FIXTURE_FILE_PREMUTATION_OWNER=ordinary_runner_uid
FIXTURE_FILE_PREMUTATION_OWNER_SCOPE=own-foreign,own-root
MOUNT_FIXTURE_FILE_PREMUTATION_OWNER=0
MOUNT_FIXTURE_FILE_PREMUTATION_OWNER_SCOPE=mount-fixture
HELPER_CHILD_REQUIREMENTS_LAYERS=common_structural_plus_case_specific_ownership_predicate
OWNERSHIP_PREDICATE_SCOPE=own-foreign,own-root
MOUNT_FIXTURE_FILE_OWNERSHIP_PREDICATE=st_uid_eq_0
NO_FD_CROSSES_SUDO_BOUNDARY=true
```

`FIXTURE_FILE_INITIAL_MODE=0644` is the approved pre-mutation mode, and it is the
same literal as the frozen `FILE_MODE=0644` of 4.1: there is exactly one mode
fact in these cases, established by the ordinary process before the helper runs
in `own-foreign` and `own-root` (4.1) and established by the helper itself at
creation in `mount-fixture` (5.8.3), and in every case verified — never
`chmod`-ed — by the helper. `0644 & 0o022 == 0` holds for it, so the mutation
policy at L111-L113 cannot fire in either the pre-mutation or the post-mutation
state, and the ownership cases isolate the owner policy at L110 in both states.
The prohibition on `0600` in 4.1 is therefore a requirement on that single mode,
not a comparison between two different modes.

The literal is common to all three cases; only its provenance is scoped.
`FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=own-foreign,own-root` and
`MOUNT_FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=mount-fixture` (5.8.3)
split that provenance so that no token in this block asserts an ordinary-process
creation for a file the helper creates, and round 5 added both scope tokens
without changing the mode, the required exactness, or the verifying process.

`FIXTURE_FILE_ROLE` resolution is case-dependent and frozen as such: for
`own-foreign` and `own-root` the child is created by the ordinary runner before
the helper is invoked, and the helper pins and validates it without creating it;
for `mount-fixture` the child is created by the helper inside the helper's own
freshly created ext4 filesystem after the mount (5.9), and it is then pinned and
validated under the same COMMON STRUCTURAL pinning rules of 5.8.1, plus that
case's own ownership predicate `st_uid == 0` (5.8.3). The mount child is never
validated under the ownership-case owner predicate of 5.8.2, which does not apply
to it, and this is the correction round 4 made: "same rule set" meant one
undivided rule set whose ownership requirement the mount case cannot satisfy.

Because no descriptor crosses the `sudo` boundary (5.4), the helper opens this
descriptor itself, after its own root validation, and
`HELPER_ACCEPTS_INHERITED_DESCRIPTOR=false` continues to hold: a caller-supplied
or inherited descriptor is never accepted, and the helper never mutates a
descriptor it did not open itself.

Python expresses the acquisition directly as
`os.open(FIXTURE_FILE_ROLE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)`,
whose underlying operation is `openat` relative to `root_fd`, with `os.fstat`
acting on the returned descriptor and `os.fchown` acting on it in the two
ownership cases only; `os.fchmod` is not used by the helper at all, because no
mode is ever changed after creation: the ownership cases inherit the ordinary
process's `0644` (4.1) and the mount case sets `0644` at creation (5.8.3). No
step of this freeze requires a descriptor to cross the privilege
boundary. This statement is scoped to the declared qualification platform:
`dir_fd`-relative `os.open` and `os.fchown` are Linux facilities, the runner is
`ubuntu-latest` (section 6), and `NO_WINDOWS_QUALIFICATION=true` (section 18)
means no other platform is claimed here. On the declared platform both descriptor
operations exist and need no dependency beyond the standard library.

The ordinary evidence process does not accept the helper's report of the
ownership mutation, and it does not accept the helper's report of the mount-case
file either. After the helper has exited and before the production call, that
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
rows of 4.3 for the two ownership cases. In the mount case the same discipline
is what 5.8.3 requires: the ordinary process opens the `0644` root-owned
mount-case file itself, with `ACTUAL_CAP_EFF == 0`, before the positive
pre-drift admission of 8. A missing, failing or unrecorded reacquisition is
`QUALIFICATION_GAP`, never a pass. Its independence from the helper's own
`fstat` matters: the helper verifies what it produced or created, the ordinary
process measures what the object is, and the case is evidence only when the
second measurement is the one the contract requires.

### 5.9 Freeze: privileged mount child safety

The mount fixture has the same confinement problem as the ownership fixture and
the same confinement answer: the helper creates the privileged mount's source
and target itself, under its own validated root descriptor in the private
namespace, and treats anything already present at a role name as a refusal
rather than as something to adopt, repair or remove. "The same answer" is about
confinement of helper-created objects; it is not a claim that the two cases share
an ownership predicate, which round 4 corrected (5.8.2, 5.8.3).

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
PRIVILEGED_MOUNT_PREEXISTING_ROLE_REFUSAL_NO_TARGET_MUTATION=true
PRIVILEGED_MOUNT_PREEXISTING_ROLE_REFUSAL_POSITION=before_any_mutation_of_the_refused_role_object
PRIVILEGED_MOUNT_PREEXISTING_ROLE_REFUSAL_REPAIRS_OR_ADOPTS=false
PRIVILEGED_MOUNT_PREEXISTING_ROLE_REFUSAL_CLEANUP=consume_10_4_state_machine
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
newly created ext4 filesystem after the mount, and it is then pinned by a
descriptor the helper opened itself and validated under the same COMMON
STRUCTURAL pinning rules that every pinned fixture child must satisfy (5.8.1),
plus the mount case's own ownership predicate `st_uid == 0` (5.8.3). It is not
validated under the ownership-case owner predicate of 5.8.2, and this case MUST
NOT apply that predicate: round 4 corrected exactly this point (1.4). The
ownership mutation of 5.8.2 applies only to the `own-foreign` and `own-root`
cases; the mount case performs no ownership mutation, and the mounted file's
ownership is never reported as RQP-L09 evidence.

```text
MOUNT_CASE_FIXTURE_CHILD_PINNED_BY_HELPER_DESCRIPTOR=true
MOUNT_CASE_FIXTURE_CHILD_VALIDATED_BY_COMMON_STRUCTURAL_RULES=true
MOUNT_CASE_FIXTURE_CHILD_VALIDATED_BY_ORDINARY_OWNER_PREDICATE=false
MOUNT_CASE_FIXTURE_CHILD_OWNERSHIP_PREDICATE=st_uid_eq_0
MOUNT_CASE_PERFORMS_NO_OWNERSHIP_MUTATION=true
MOUNT_CASE_FIXTURE_FILE_OWNERSHIP_IS_L09_EVIDENCE=false
MOUNT_CASE_FIXTURE_CHILD_ROLE_PATH=MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE
MOUNT_CASE_FIXTURE_CHILD_ROLE_PATH_COMPONENTS_FROZEN=true
MOUNT_CASE_FIXTURE_CHILD_CREATED_AFTER_MOUNT_ATTACHED=true
MOUNT_CASE_FIXTURE_CHILD_PREEXISTING_OBJECT_OUTCOME=CREATION_REFUSED_NOT_ADOPTED
MOUNT_CASE_FIXTURE_CHILD_AFTER_CREATION_FAILURE_OUTCOME=FAILURE_CLASSIFIED_BY_5_7_ORIGIN
MOUNT_CASE_FIXTURE_CHILD_AFTER_CREATION_FAILURE_IS_HELPER_ROOT_REJECTED=false
```

The refusal outcome frozen in 5.9 for a pre-existing object at a helper-created
role is a refusal to adopt, repair or remove that object, positioned before any
mutation of the object it refuses. It is not a claim that the invocation has
performed no privileged effect yet — by the time the helper creates its mount
objects the private namespace and its private propagation already exist — and any
object the helper has already created when such a refusal occurs is removed by
the 10.4 state machine rather than reported as a fixture. For the mount case's
`FIXTURE_FILE_ROLE` the same discipline is expressed differently, because that
object cannot preexist: it is created after the mount, and a missing or
non-conforming child after creation is the origin-classified failure of 5.8.3.

### 5.10 Freeze: ordinary credential handoff and non-root identity reacquisition

The privileged namespace launcher starts as the reviewed privileged identity and
must launch the non-root evidence process as the ordinary runner. It MUST NOT
invent that identity, infer it, or read it from `SUDO_UID`, `SUDO_GID`, `SUDO_*`
state, `LOGNAME`, `USER`, a parent process inspection, or any ambient value. The
ordinary identity is measured where it really is and transported as an explicit,
typed, numeric handoff.

#### 5.10.1 Handoff

Before `sudo` or any namespace creation, `HOST_OBSERVER` or the ordinary
workflow process — a genuinely ordinary, non-root process — measures its own real
effective identity:

```text
ORDINARY_UID=
ORDINARY_GID=
ORDINARY_UID_IS_MEASURED_NOT_ASSUMED=true
```

`ORDINARY_UID` is the ordinary process's real effective uid and `ORDINARY_GID`
its real effective gid, both read from the running process itself. The
representability requirement of 5.2 and the identity requirement of this
subsection are the same requirement:

```text
ORDINARY_UID != 0
ORDINARY_UID_IS_ZERO_OUTCOME=QUALIFICATION_GAP
ORDINARY_GID_IS_VALID_LINUX_GID=true
```

If the ordinary process's effective uid is `0`, no ordinary identity exists to
hand off, the fixture cannot be constructed, and the outcome is
`QUALIFICATION_GAP`: the design MUST NOT launch a synthetic "non-root" process
from a root runner, because that process would not be the ordinary runner whose
identity the cases qualify against.

The two numeric values then cross into `PRIVILEGED_NAMESPACE_LAUNCHER` through a
fixed typed launcher protocol. This is the second explicit handoff in the
fixture, and like the first (5.1) it carries a value the receiving side could not
otherwise obtain and does not carry authority:

```text
ORDINARY_REQUESTED_UID_GID_CONTINUITY=EXPLICITLY_HANDED_OFF
ORDINARY_CREDENTIAL_CARRIER=fixed_numeric_launcher_arguments
ORDINARY_CREDENTIALS_FROM_SUDO_ENVIRONMENT=false
SUDO_UID_SUDO_GID_ARE_AUTHORITY=false
SUDO_UID_SUDO_GID_CORROBORATION_ONLY=true
ORDINARY_CREDENTIALS_FROM_CALLER_TEXT=false
ORDINARY_CREDENTIALS_FROM_PARENT_INSPECTION=false
```

The carrier is two fixed numeric launcher arguments, `--ordinary-uid=<N>` and
`--ordinary-gid=<N>`, valid for exactly one launcher invocation. They are the
requested identity: what the ordinary runner asked the launcher to become. They
are not the observed identity, and this contract does not treat them as one fact
with it.

`SUDO_UID` and `SUDO_GID` may be logged as corroboration of the handoff — they
are useful when a reviewer wants to see that `sudo` agreed with the values the
launcher received — but they MUST NOT be the authority for the handoff, MUST NOT
be the source of `ORDINARY_UID`/`ORDINARY_GID`, and MUST NOT be accepted in place
of the explicit arguments. A launcher that reads its ordinary identity from the
`sudo` environment does not satisfy this contract, because that value is an
artifact of the privilege tool rather than a measurement of the ordinary
process.

#### 5.10.2 Launcher validation before credential drop

The launcher MUST independently validate the handed-off values against real
filesystem state before it drops credentials, and it MUST validate rather than
trust them:

| Required check | Frozen requirement |
| --- | --- |
| nonzero | `ORDINARY_UID != 0`; a zero requested uid is a hard refusal |
| numeric validity | both values are valid numeric Linux ids: decimal, no sign, within the representable uid/gid range of the host |
| root ownership | `st_uid` of the invocation root, as the launcher itself observes it, equals `ORDINARY_UID` |
| expected group relation | `st_gid` of the invocation root equals `ORDINARY_GID`; no other group relation is accepted |
| no substitution | no other source supplies either value |

```text
ORDINARY_INVOCATION_ROOT_OWNER_RELATION=st_uid_eq_ORDINARY_UID
ORDINARY_INVOCATION_ROOT_GROUP_RELATION=st_gid_eq_ORDINARY_GID
ORDINARY_NUMERIC_ID_VALIDATION_LINUX=true
```

The invocation root is created by the ordinary process, so its real owner is the
ordinary identity by construction (4.2, 5.3); comparing the handed-off values
against the root's real `st_uid`/`st_gid` is therefore a real check rather than a
tautology. If any check fails, the launcher refuses and no credential drop
occurs:

```text
ORDINARY_CREDENTIAL_VALIDATED_BY_LAUNCHER=true
ORDINARY_CREDENTIAL_VALIDATION_BEFORE_DROP=true
ORDINARY_CREDENTIAL_INVALID_OUTCOME=LAUNCHER_CREDENTIAL_REJECTED
ORDINARY_CREDENTIAL_ZERO_OUTCOME=LAUNCHER_CREDENTIAL_REJECTED
ORDINARY_ROOT_OWNER_MISMATCH_OUTCOME=LAUNCHER_CREDENTIAL_REJECTED
LAUNCHER_CREDENTIAL_REJECTED_IS_PASS=false
LAUNCHER_CREDENTIAL_REJECTION_BEFORE_NAMESPACE_MUTATION=true
LAUNCHER_ORDINARY_IDENTITY_SOURCE=validated_explicit_handoff
```

A credential rejection is a fixture-construction failure, never a product
defect; no mount mutation may follow it, and cleanup under 10.4 applies to
whatever the launcher had already created.

The launcher then launches `NONROOT_EVIDENCE_PROCESS` using those validated
credentials. That is a request, not a fact about the process that results.

#### 5.10.3 Actual identity and capabilities reacquired inside the evidence process

Inside `NONROOT_EVIDENCE_PROCESS`, the process reacquires its own real identity
and its own real effective capability set, and MUST require all of:

```text
ACTUAL_EUID=
ACTUAL_EGID=
ACTUAL_CAP_EFF=
```

```text
ACTUAL_EUID == ORDINARY_UID
ACTUAL_EGID == ORDINARY_GID
ACTUAL_EUID != 0
ACTUAL_CAP_EFF == 0
```

```text
NONROOT_EVIDENCE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED
NONROOT_EVIDENCE_CAP_EFF_REQUIRED=0
NONROOT_EVIDENCE_CAP_EFF_SOURCE=/proc/self/status CapEff decoded from the real mask
ORDINARY_REQUESTED_UID_GID_IS_NOT_OBSERVED_IDENTITY=true
```

Each of the three values is read from the running evidence process itself, not
received from the launcher and not inferred from the launch request.
`ACTUAL_EUID`, `ACTUAL_EGID` and `ACTUAL_CAP_EFF` are independently
reacquired facts, and they are different facts from the handed-off
`ORDINARY_UID`/`ORDINARY_GID` even when their values agree: agreeing values are
the point of the comparison, and the comparison is only meaningful because the
two sides are measured separately.

The capability requirement is the substantive part of this freeze. Nonzero
`euid` with a nonempty effective capability set is not a nonprivileged process,
and a fixture that admits such a process would attribute to the production
primitive an outcome produced by retained privilege. `ACTUAL_CAP_EFF == 0`
therefore means no effective capability at all: not `CAP_DAC_OVERRIDE`, not
`CAP_DAC_READ_SEARCH`, not `CAP_CHOWN`, not `CAP_SYS_ADMIN`, not
`CAP_FOWNER`, and not any other effective bit, as decoded from the real
`CapEff` mask of the running process.

```text
PRODUCTION_PRIMITIVE_EXECUTES_IN_NONROOT_EVIDENCE_PROCESS=true
PRODUCTION_PRIMITIVE_BEFORE_IDENTITY_CONTROLS=false
NONROOT_EVIDENCE_IDENTITY_MISMATCH_OUTCOME=QUALIFICATION_GAP_OR_FIXTURE_CONSTRUCTION_FAILURE
NONROOT_EVIDENCE_IDENTITY_MISMATCH_IS_EVIDENCE=false
NONROOT_EVIDENCE_CAP_EFF_NONZERO_IS_EVIDENCE=false
```

The production primitive under qualification MUST NOT execute before these
controls pass. A mismatch of `ACTUAL_EUID`, `ACTUAL_EGID` or `ACTUAL_CAP_EFF` is
a `QUALIFICATION_GAP` and a fixture-construction failure, never evidence: the
case cannot conclude anything about production from a process that is not the
ordinary, unprivileged identity the contract requires, and it MUST NOT report a
`PRODUCT_FAILURE` from such a run.

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
| ordinary privilege | the ordinary evidence process has `euid != 0`, and its real `ORDINARY_UID` and `ORDINARY_GID` are measured before `sudo` or namespace creation |
| ordinary capabilities | the evidence process's real `CapEff` is `0`, so "non-root" means unprivileged rather than merely nonzero `euid` |
| passwordless sudo | `sudo -n` succeeds without a prompt or terminal |
| helper privilege | the privileged child really reports `euid == 0` |
| capabilities | the privileged child's `CapEff` contains `CAP_CHOWN` for the ownership fixture and the exact mount-related set including `CAP_SYS_ADMIN` for the RQP-L17 fixture, each decoded from the real mask, with no capability required that the fixture's own operations do not need |
| helper access authority | the privileged child's real `CapEff` contains the declared helper access authority, and the invocation root it must reach is observed as owner-only (`S_IMODE == 0o700`, group, world and sticky bits clear) and owned by the ordinary runner, so that the access authority is required by a measured fact rather than assumed (1.5) |
| kernel and tools | the required kernel interfaces and utilities exist and their versions are recorded |
| fixture root | the `RUNNER_TEMP` invocation root is usable, invocation-specific, and not a shared or persistent runner path; its parent is not sticky, so removal of a directory owned by the ordinary identity needs no `CAP_FOWNER`; and the freshly formatted ext4 root directory is observed with the owner and search facts 5.8.3 requires |
| foreign uid | the design-frozen `FOREIGN_OWNER_TARGET_UID=65534` is representable on the host and the ordinary runner's effective uid is not `65534`, so the 5.2 literal is usable; if it is not, the `FOREIGN_OWNER` outcome is `QUALIFICATION_GAP` and no alternate uid is selected |
| isolation | no persistent or shared runner state is targeted by any step |

The fixture's capability requirement is derived from the operations it really
performs, and it is frozen as an exact set per case rather than as one blanket
grant.

For the RQP-L09 ownership fixture the required privileged-helper capability is
exactly:

```text
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY=CAP_CHOWN
OWNERSHIP_MUTATION_REQUIRES_CAP_FOWNER=false
OWNERSHIP_MUTATION_REQUIRES_CAP_DAC_OVERRIDE=false
OWNERSHIP_FIXTURE_REQUIRED_CAPABILITY_SET=CAP_CHOWN
```

`CAP_CHOWN` is required because the helper performs `fchown` on the pinned child
descriptor in the two ownership cases (5.8.2). `CAP_FOWNER` is NOT required, and
could not be required by an honest contract, because the helper changes no mode,
no ownership of a setuid/setgid object and no other FOWNER-governed attribute:
the zero-argument `fchmod` of the earlier draft is gone (5.8.2), so nothing in
the helper needs FOWNER. `CAP_DAC_OVERRIDE` MUST NOT be required to produce,
attribute or prove any required outcome, and it is not required for the
ownership effect itself or for creating the mount case's fixture file inside the
helper-owned mounted filesystem. It IS the declared authority for the helper's
own file access under the invocation root, which is a separate fact this round
makes explicit rather than implicit (1.5): the root is owner-only and owned by
the ordinary runner while the helper is not its owner, so opening the pinned
child, reaching the mount-case role path, opening the image for the loop
configuration and unlinking the fixture objects all need that access, and a
world-traversable root would let an unrelated local user place objects at the
frozen role names. That access is recorded by the preflight from the real
`CapEff` mask, it produces no outcome and no evidence, and it is unavailable to
the ordinary evidence process, whose `ACTUAL_CAP_EFF == 0` requirement is
unchanged. `FILE_MODE=0644` exists
precisely so the ordinary reader's access is a real permissions fact rather than
a capability artifact: the ordinary non-root process's `os.open(O_RDONLY)`
succeeds through the real `0644` DAC bits, and that success is the 4.3
attribution guard.

The mount case's fixture file adds no ownership capability requirement of its
own, and the closure of 1.5 is what makes that checkable rather than assumed:

```text
MOUNT_FIXTURE_FILE_CREATION_REQUIRES_CAP_CHOWN=false
MOUNT_FIXTURE_FILE_CREATION_REQUIRES_OWNERSHIP_MUTATION=false
MOUNT_FIXTURE_FILE_CREATION_REQUIRES_CAP_SYS_ADMIN=false
MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false
MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION_EFFECT=NONE
MOUNT_FIXTURE_FILE_OWNERSHIP_REQUIRES_CAP_FOWNER=false
MOUNT_FIXTURE_FILE_OWNERSHIP_REQUIRES_CAP_DAC_OVERRIDE=false
MOUNT_FIXTURE_FILE_CREATION_ACCESS_AUTHORITY=PRIVILEGED_HELPER_ACCESS_AUTHORITY
MOUNT_FIXTURE_FILE_CREATION_ACCESS_AUTHORITY_PRODUCES_EVIDENCE=false
```

Creating a file assigns the creating process's own effective uid to it and
performs no ownership call, so the mount case's `st_uid == 0` (5.8.3) is a
property of who the helper already is rather than an authority it exercises; and
because no mode is ever changed after creation, nothing in the mount case needs
FOWNER. `MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION_EFFECT=NONE` is the effect-side
half of the closure: there is no ownership effect in that case for any
capability to authorize.

The helper's own `O_RDONLY` acquisition of the pinned file is not the
attribution guard and is not offered as one. The helper runs as the reviewed
privileged identity, so its read may equally be permitted by its own privilege;
that is why the real DAC witness is the ordinary process's open, which holds no
capability at all. A preflight that passes only because a capability was assumed
is invalid, and a case whose attribution rests on a privileged open rather than
the ordinary one is not evidence.

`sudo`-root may, and on a stock runner will, hold more capabilities than the
fixture needs. Those extra bits are recorded from the real `CapEff` mask for
review and are explicitly not fixture authority:

```text
PRIVILEGED_HELPER_CAP_EFF_RECORDED=true
PRIVILEGED_HELPER_EXTRA_CAPABILITIES_ARE_REQUIRED_AUTHORITY=false
PRIVILEGED_HELPER_CAPABILITY_REQUIREMENT_IS_EXACT_SET=true
CAPABILITY_PREFLIGHT_INVALID_IF_CAPABILITY_ASSUMED=true
```

RQP-L17 separately requires its own exact mount-related capability set, and round
5 derives that set per effect rather than as one blanket grant (1.5):
`CAP_SYS_ADMIN` is required for the private mount namespace creation, the private
propagation, the loop device configuration, the mount, the `MNT_DETACH` detach,
the `ATTACHED`-state ordinary unmount and the loop backing release, and for
nothing else. Image creation, `mkfs`, and the image, mountpoint and
invocation-root removals are not `CAP_SYS_ADMIN` operations at all; they are
file-level operations whose authority is the declared helper access authority
plus the object's own DAC permissions. The two cases' capability sets are
separate facts and neither widens the other.

```text
RQP_L17_REQUIRED_CAPABILITY_SET=CAP_SYS_ADMIN
RQP_L17_CAP_SYS_ADMIN_BOUND_EFFECTS=E3,E4,E7,E8,E10,E11,E12
RQP_L17_EFFECTS_WITHOUT_CAP_SYS_ADMIN=E5,E6,E13,E14,E15
RQP_L17_CAP_SYS_ADMIN_BROADER_THAN_ITS_EFFECTS=false
RQP_L17_PREFLIGHT_RECORDS_ACCESS_AUTHORITY_FROM_REAL_CAP_EFF=true
RQP_L17_PREFLIGHT_ASSERTS_NO_CAPABILITY_THE_OPERATIONS_DO_NOT_NEED=true
```

A failed preflight is classified by origin:

- `QUALIFICATION_GAP` when the required real fixture cannot be constructed in
  this environment;
- `LAUNCHER_CREDENTIAL_REJECTED` when the ordinary credential handoff of 5.10
  cannot be validated, which is also a fixture-construction failure and occurs
  before any namespace mutation;
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
| `HOST_OBSERVER` | host mount namespace, outside the private namespace | ordinary runner identity | read the host mount table; record the fixture device and mountpoint absence baseline before and after the run; measure and hand off its own real `ORDINARY_UID`/`ORDINARY_GID` (5.10.1) |
| `PRIVILEGED_NAMESPACE_LAUNCHER` | starts in the host mount namespace, then enters a new private mount namespace | reviewed privileged identity via `sudo -n` | validate the handed-off ordinary uid/gid against real filesystem state (5.10.2); create the private mount namespace; make propagation private; establish and report the private namespace identity; launch the evidence process with the validated ordinary credentials |
| `NONROOT_EVIDENCE_PROCESS` | inside the private namespace, launched by the launcher | ordinary runner identity, `euid != 0`, `egid` unchanged, and `CapEff == 0`; all three independently reacquired by the process itself (5.10.3) | reacquire its own identity and capability mask before anything else; execute the production primitive under qualification; retain descriptors; measure and record evidence |
| `PRIVILEGED_FIXTURE_HELPER` | inside the same private namespace, invoked from it | the reviewed privileged identity again, via `sudo -n` | the 5.2 case actions only: fixture ownership mutation by `fchown`, fixture mount setup, `MNT_DETACH` detach, checked cleanup |

Frozen lifecycle, in order:

```text
HOST_OBSERVER                records host mount namespace identity / absence baseline
                             measures its own real ORDINARY_UID / ORDINARY_GID
  -> PRIVILEGED_NAMESPACE_LAUNCHER
       sudo -n
       validates ORDINARY_UID != 0, numeric validity, and invocation-root
         st_uid == ORDINARY_UID / st_gid == ORDINARY_GID against real state
       refuses as LAUNCHER_CREDENTIAL_REJECTED before any namespace mutation
         if any credential check fails
       creates a private mount namespace
       makes propagation private
       establishes namespace identity
  -> NONROOT_EVIDENCE_PROCESS
       launched INSIDE that private namespace
       with the validated ordinary credentials
       reacquires ACTUAL_EUID / ACTUAL_EGID / ACTUAL_CAP_EFF from itself
       requires ACTUAL_EUID == ORDINARY_UID, ACTUAL_EGID == ORDINARY_GID,
         ACTUAL_EUID != 0, ACTUAL_CAP_EFF == 0
       executes the production primitive only after those controls pass
  -> PRIVILEGED_FIXTURE_HELPER
       invoked from INSIDE the same private namespace
       may regain reviewed privilege via sudo
       performs only reviewed setup / detach / cleanup actions
```

```text
HOST_OBSERVER_IN_PRIVATE_NAMESPACE=false
PRIVILEGED_NAMESPACE_LAUNCHER_AUTHORITY=sudo -n only
PRIVILEGED_NAMESPACE_LAUNCHER_ORDINARY_IDENTITY_INPUT=validated_explicit_handoff
PRIVILEGED_NAMESPACE_LAUNCHER_CREDENTIAL_VALIDATION_BEFORE_DROP=true
NONROOT_EVIDENCE_PROCESS_EUID=ordinary_runner_identity
NONROOT_EVIDENCE_PROCESS_IDENTITY_IS_REACQUIRED=true
NONROOT_EVIDENCE_PROCESS_CAP_EFF_REQUIRED=0
FIXTURE_HELPER_INVOCATION_ORIGIN=inside_the_same_private_namespace
FIXTURE_HELPER_REGAINS_PRIVILEGE=sudo -n only
FIXTURE_HELPER_ACTION_SCOPE=reviewed_setup_detach_cleanup_only
NONROOT_EVIDENCE_PROCESS_LAUNCH_IS_A_REQUEST_NOT_A_FACT=true
```

The host observer stays OUTSIDE the private namespace for the whole run, and it
is the only role that performs the before/after host-mount absence
observations. A control read from inside the private namespace cannot prove
anything about the host namespace and MUST NOT be reported as that control.

The launcher does not know the ordinary identity by itself and MUST NOT invent
it. It receives `ORDINARY_UID` and `ORDINARY_GID` as an explicit typed handoff
from the host observer (5.10.1), validates them against the real invocation root
before dropping credentials (5.10.2), and refuses as
`LAUNCHER_CREDENTIAL_REJECTED` when they do not hold up. `SUDO_UID` and
`SUDO_GID` are corroboration only: the launcher MUST NOT read its ordinary
identity from the `sudo` environment, from `SUDO_*` state, or from any
assumption that the invocation root's owner is "whatever the caller was".

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

The evidence process's identity and capabilities are measured with the same
discipline, and are required before the production primitive executes:

```text
NONROOT_EVIDENCE_PROCESS_IDENTITY_MEASURED=true
NONROOT_EVIDENCE_PROCESS_IDENTITY_SOURCE=own real process state
NONROOT_EVIDENCE_PROCESS_CAP_EFF_SOURCE=/proc/self/status CapEff decoded from the real mask
NONROOT_EVIDENCE_IDENTITY_ASSUMED_FROM_LAUNCH_REQUEST=false
NONROOT_EVIDENCE_IDENTITY_ASSUMED_FROM_SUDO=false
NONROOT_EVIDENCE_PROCESS_EUID_NONZERO_IS_NOT_SUFFICIENT=true
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
| N4 | launcher -> evidence process: namespace membership, requested credentials, actual identity | namespace membership: `INHERITED` across `fork`/`exec`; requested ordinary uid/gid: `EXPLICITLY_HANDED_OFF` to the launcher and validated before the drop; actual identity and capabilities: `INDEPENDENTLY_REACQUIRED` by the evidence process | ordinary runner identity | privileged namespace launcher | inherited mount namespace across `fork`/`exec`, fixed numeric credential arguments, and the evidence process's own real process state | until namespace exit | evidence process | `PRIVATE_EVIDENCE_MNT_NS_ID` measured and equal to the private identity, and `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_EUID != 0`, `ACTUAL_CAP_EFF == 0` all recorded before the production call |
| N5 | evidence process -> helper: namespace membership | membership: `INHERITED` across the `sudo` identity transition, which changes credentials and not namespace membership; identity: `INDEPENDENTLY_REACQUIRED` by the helper | reviewed privileged identity | privileged fixture helper | inherited mount namespace across `sudo` | one helper invocation | helper | `PRIVATE_HELPER_MNT_NS_ID` measured and equal to `PRIVATE_EVIDENCE_MNT_NS_ID` |
| N6 | private namespace -> host: absence | host-table absence: `INDEPENDENTLY_REACQUIRED` by the host observer | this contract | host observer | observed host mount table | one run attempt | independent reviewer | post-run absence control recorded |

No row in this table is an unclassified fact. Namespace membership is inherited;
namespace identity and the evidence process's own identity and capabilities are
independently reacquired; and exactly one row, N4, carries an explicit handoff —
the requested ordinary uid and gid — which is a request rather than an observed
fact and closes at the launcher's validation (5.10.2) before any credential drop.
The two credential facts are never collapsed into one: the requested identity is
handed off, the observed identity is reacquired, and the run records both so the
reviewer can compare them.

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

Cleanup restores no ownership, and the earlier section-5 phrase "cleanup
ownership restoration" is withdrawn by round 5 as a requirement this state
machine does not have (1.5). Removal is bound to the containing directory's
permissions and never to the removed object's owner, so unlinking a
`65534`-owned or `0`-owned fixture file needs no ownership change; the mount case
has no ownership change to reverse; and a reverse `fchown` would be an
undeclared second ownership call, contradicting the single-call mutation of 5.8.2
and `FILE_CHOWN_ONLY=true` as a statement about the whole privileged effect
(4.2). No cleanup step below performs an ownership call:

```text
CLEANUP_OWNERSHIP_RESTORATION_REQUIRED=false
CLEANUP_OWNERSHIP_RESTORATION_EFFECT=NONE
CLEANUP_SECOND_FCHOWN_PERFORMED=false
CLEANUP_HELPER_OWNERSHIP_CALLS_AFTER_SETUP=0
CLEANUP_REPAIRS_OWNERSHIP=false
CLEANUP_REMOVED_OBJECT_KEEPS_SETUP_OWNERSHIP_UNTIL_REMOVAL=true
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
child-inode confinement facts of 5.8, including the round-4 split into the common
structural requirements of 5.8.1 and the case-specific ownership predicates of
5.8.2 and 5.8.3 — `st_uid == ORDINARY_UID` for the two ownership cases and
`st_uid == 0` with `MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false` for the mount
case — the privileged mount child-safety facts of
5.9, the three measured namespace identities and namespace classes of 10.1-10.2,
the cleanup state machine and residue controls of 10.4, and the workflow trigger,
permission, exact-head binding and provenance facts of 6.1-6.3, including the
`PRIVILEGED_WORKFLOW_EVENT_REF_BLOB_SHA == PRIVILEGED_WORKFLOW_HEAD_BLOB_SHA`
requirement and the `WORKFLOW_AUTHORITY_MISMATCH` stop rule. The round-5 facts
are pinned the same way: the mode-provenance scope tokens of 5.8 and 5.8.3 with
the exact-`0644` requirement still common, the four `..._OUTCOME_SCOPE` tokens of
5.8.1 and the mount case's after-creation origin tokens of 5.8.3, the sixteen
effect rows of 1.5 with their declared authorities and the three
bidirectional-closure tokens, and the cleanup no-ownership-restoration tokens of
5 and 10.4. A frozen token with
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
corrected statements. Round 2 re-ran it against the round-2 head, in which the
cross-boundary classification (5.5, 5.6, 10.2), the privileged child inode
confinement (5.8), the privileged mount child safety (5.9) and the pull-request
workflow provenance (6.2, 6.3) are the corrected statements. Round 3 re-ran it
against the round-3 head, in which the ownership capability model (4.1, 4.2,
5.8, 7), the foreign uid authority (5.2), the ordinary credential handoff and
the non-root evidence identity (5.5, 5.6, 5.10, 10.1, 10.2) are the corrected
statements. Round 4 re-ran it against the round-4 head, in which the pinned-child
model (5.8.1-5.8.3, 5.9, 7) is the corrected statement: the common structural
requirements and the case-specific ownership predicates are now separate facts,
and the mount case's `st_uid == 0` predicate replaces the ownership predicate
that the helper-created mount child cannot satisfy. Round 5 re-runs it against
this head, in which the mode-provenance scope (5.8, 5.8.3), the child-object
outcome scope (5.8.1, 5.8.3, 5.9), the per-effect privileged closure and its
declared access authority (1.5, 7), and the cleanup ownership-resolution (5,
10.4) are the corrected statements. Each result is claimed only
because the document at that head has no
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
OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY=PASS
ORDINARY_CREDENTIAL_HANDOFF_IMPLEMENTABILITY=PASS
NONROOT_EVIDENCE_IDENTITY_IMPLEMENTABILITY=PASS
FOREIGN_UID_AUTHORITY_IMPLEMENTABILITY=PASS
RQP_L17_L105_MOUNT_ID_CHANGE_IMPLEMENTABILITY=NOT_CONSTRUCTIBLE_WITH_KNOWN_REAL_MECHANISM
A3_CONTRACT_IMPLEMENTABILITY=PASS
```

Round 4 re-evaluated the six results the corrected pinned-child model touches,
and claims `PASS` for them only because the corrected owner predicates are
mutually implementable: the ownership cases require `st_uid == ORDINARY_UID`
before their `fchown`, while the mount case requires `st_uid == 0` and performs
no ownership mutation, so neither predicate is applied to the other case's
object, and no case needs an ownership or credential mutation in order to be
constructed.

```text
ROUND4_RE_EVALUATED_RESULTS=RQP_L09_FOREIGN_OWNER_IMPLEMENTABILITY,RQP_L09_ROOT_OWNED_IMPLEMENTABILITY,RQP_L17_HELD_MOUNT_REPRESENTATION_DRIFT_IMPLEMENTABILITY,OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
OWNERSHIP_CASE_OWNER_PREDICATE=st_uid_eq_ORDINARY_UID
MOUNT_CASE_OWNER_PREDICATE=st_uid_eq_0
CASE_OWNER_PREDICATES_ARE_MUTUALLY_IMPLEMENTABLE=true
CASE_OWNER_PREDICATES_ARE_INTERCHANGEABLE=false
MOUNT_FIXTURE_FILE_CREATION_EFFECT_IMPLEMENTABILITY=PASS
MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION_EFFECT=NONE
MOUNT_FIXTURE_ORDINARY_READ_WITNESS_IMPLEMENTABILITY=PASS
PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY_SCOPE=own-foreign,own-root,mount-fixture
```

Round 5 re-evaluated the five results the three blocking findings touch. Each is
`PASS` only because the corrected statements have no producer, carrier, consumer
or authority gap left open, and each is claimed for its own stated reason:

```text
ROUND5_RE_EVALUATED_RESULTS=PRIVILEGED_EFFECT_AUTHORITY_CLOSURE,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY,CLEANUP_STATE_MACHINE_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE_ROWS=16
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS
OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY=PASS
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS
A3_CONTRACT_IMPLEMENTABILITY=PASS
MODE_PROVENANCE_SCOPE_CLOSED=true
MOUNT_CHILD_MISSING_OUTCOME_CLOSED=true
CLEANUP_OWNERSHIP_RESTORATION_RESOLVED=true
BLOCKING_FINDINGS_CLOSED=3
BLOCKING_FINDINGS_OPEN=0
```

- `PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS` — all sixteen material effects have
  one row each in 1.5, with a target object, a target-binding mechanism, an
  authority derived from that effect's own operation, preconditions,
  postconditions and a cleanup or terminal transition. The closure holds in both
  directions: every effect has a declared authority, and every declared authority
  is bound to effects that really need it, so no capability is granted for
  nothing and no effect is left unauthorized. The authority facts are decidable
  before implementation: `CAP_CHOWN` is bound to E1 and E2, `CAP_SYS_ADMIN` to
  E3, E4, E7, E8, E10, E11 and E12, the declared access authority to the nine
  effects that touch objects under the invocation root, and `CAP_FOWNER`,
  `CAP_DAC_READ_SEARCH` and every other capability to none, because no effect
  needs them. The `mkfs` and image-creation effects are the clearest case of the
  derivation mattering: they are ordinary file writes and creates, and grouping
  them under `CAP_SYS_ADMIN` would have declared an authority no operation of
  theirs exercises.
- `PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS` (re-evaluated) — for
  every case that pins a `FIXTURE_FILE_ROLE` child the helper opens the
  descriptor itself, and the round-5 scoping keeps that true at all three call
  sites: the two ownership cases bind a child that must preexist and refuse a
  missing, symlinked, hardlinked or unexpected object before mutating anything,
  while the mount case binds its own created child at the frozen role path
  `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE` and classifies absence or non-conformance
  after creation by origin instead of claiming a pre-mutation refusal it cannot
  have. No case is left with a requirement it cannot satisfy, and no case
  borrows the other's outcome.
- `OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY=PASS` (re-evaluated) — the helper
  performs exactly one privileged mutation per ownership case on a descriptor it
  opened itself, so `CAP_CHOWN` is the whole ownership requirement; the
  mode-provenance split of 1.5 removes the last unscoped mode fact without
  introducing a mode-changing call; and the helper's access to the object it
  mutates is now a declared access authority rather than an implicit assumption,
  which produces no ownership outcome, no evidence, and no capability the
  ownership effect itself needs.
- `CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS` (re-evaluated) — the state
  machine's transitions are all real operations with declared authorities: the
  `ATTACHED` path through the ordinary unmount, the `DETACHED_BUSY` path through
  descriptor closure, verification and loop release, then removal of the image,
  the mountpoint and the root. `SECOND_UNMOUNT_AFTER_MNT_DETACH_REQUIRED=false`
  stays implementable because `MNT_DETACH` disconnects the mount from the table
  immediately, and the withdrawal of the ownership-restoration requirement
  removes the one step that had no effect row, no consumer and no place in the
  frozen order.
- `A3_CONTRACT_IMPLEMENTABILITY=PASS` is claimed only after the round-5
  re-evaluation above and every earlier result it depends on are `PASS`, and only
  because each of the three blocking findings is closed at this head by a
  statement that names its owner, its producer, its carrier, its consumer and its
  closing point: the mode-provenance scope (1.5, 5.8, 5.8.3), the child-object
  outcome scope (1.5, 5.8.1, 5.8.3, 5.9), and the per-effect privileged closure
  with its declared access authority (1.5, 7).

The three blocking findings are closed as follows:

| Blocking finding | Corrected statement at this head | Why it is now implementable |
| --- | --- | --- |
| mode-provenance token unscoped in the general 5.8 block | `FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=own-foreign,own-root` in 5.8 and `MOUNT_FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=reviewed_privileged_helper_at_creation` with `..._SCOPE=mount-fixture` in 5.8.3 (1.5) | the mode literal and its exactness are unchanged and still common to all three cases; only the provenance is scoped, so no token claims an ordinary-process creation for a helper-created file, and no `chmod`/`fchmod` is introduced |
| child-missing outcome unscoped, and therefore false for the helper-created mount case | the four pre-existing-object refusals are scoped to `own-foreign,own-root`, and the mount case gets an after-creation failure contract with `MOUNT_CASE_CHILD_MISSING_AFTER_CREATION_IS_HELPER_ROOT_REJECTED=false`, `MOUNT_CASE_CHILD_MISSING_IS_PASS=false` and an origin split that keeps `ENVIRONMENT_FAILURE`, `TOOLING_FAILURE` and `TEST_FAILURE` distinct (1.5, 5.8.1, 5.8.3) | the refusal outcomes are only claimed where the role must preexist, the mount case's failure is classified by the origin that really produced it instead of one collapsed value, and the production primitive has not run at that point, so `PRODUCT_FAILURE` is structurally excluded rather than excused |
| privileged-effect table grouped distinct effects and left effects unauthorized | one row per material effect, sixteen rows, each with target, binding, authority, preconditions, postconditions and cleanup transition, plus the three bidirectional-closure tokens (1.5) | every effect's authority follows from the operation it performs, no effect is left undeclared, no declared authority is unused or broader than its effects, and the two authorities the round-4 table did not name — the mount-case creation authority and the helper's declared access authority — are now frozen rather than assumed |

`A3_CONTRACT_IMPLEMENTABILITY=PASS` is claimed only after the four round-3
results and the three round-2 results above it are `PASS`, and only after the
round-4 re-evaluation confirms that the corrected owner predicates are mutually
implementable and the round-5 re-evaluation (below) confirms that all sixteen
privileged effects have a declared authority and that no declared authority is
broader than its effects. Each of those seven is claimed for a stated reason:

- `OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY=PASS` — the helper performs
  exactly one privileged mutation per ownership case, `fchown(child_fd,
  derived_target_uid, observed_gid)` on a descriptor it opened itself, so
  `CAP_CHOWN` is the whole ownership capability requirement; no mode is changed
  by the helper, so `CAP_FOWNER` is not required, and no access check is bypassed
  to obtain a required outcome, so `CAP_DAC_OVERRIDE` is not required for those
  effects. `0644` is established by the ordinary process before the helper runs
  in the ownership cases (4.1) and at creation in the mount case (5.8.3), and the
  helper's post-`fchown` `fstat` on the same pinned descriptor observes `st_uid
  == derived_target_uid` and `S_IMODE == 0644` and fails the fixture construction
  rather than repairing the mode. Round 4 added the mount case to this model and
  closed it from both sides (1.4): the mount-case fixture file is created with no
  ownership call and no `CAP_CHOWN` requirement, its ownership mutation is `NONE`
  rather than merely unused, and `st_uid == 0` follows from the creating identity
  instead of being produced by privilege. Every frozen requirement names an
  operation the standard library can perform on the declared platform, and no
  requirement needs a capability the helper's real operations do not use.
- `ORDINARY_CREDENTIAL_HANDOFF_IMPLEMENTABILITY=PASS` — the ordinary identity is
  measured by a running ordinary process, so the producer exists; it is carried
  by two fixed numeric launcher arguments, so the carrier exists; the launcher
  validates `ORDINARY_UID != 0`, numeric validity and the invocation root's real
  `st_uid`/`st_gid` before any credential drop, so the consumer and the closing
  checkpoint exist; and `SUDO_UID`/`SUDO_GID` are demoted to corroboration, so
  no requirement rests on a value the fixture cannot authoritatively obtain.
- `NONROOT_EVIDENCE_IDENTITY_IMPLEMENTABILITY=PASS` — `euid`, `egid` and
  `CapEff` are all readable by a process from itself (`os.geteuid`, `os.getegid`
  and the real `/proc/self/status` mask on the declared Linux platform), so the
  evidence process can produce and consume the fact with no carrier and no
  privileged help; the required comparisons are exact equalities and a zero mask,
  so the check is decidable; and a mismatch is classified as a fixture failure
  before the production call rather than as evidence.
- `FOREIGN_UID_AUTHORITY_IMPLEMENTABILITY=PASS` — a single design-frozen literal
  (`65534`) is available to both the contract reviewer and the implementation, so
  the target identity is reviewable and preflightable without an
  implementation-time choice; the implementation needs only to transcribe it;
  the ordinary runner's non-`65534` requirement is measurable before any
  mutation; and the unusable-literal case terminates in `QUALIFICATION_GAP`
  rather than in an unreviewed substitution.
- `CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY=PASS` — every row of 5.5, 5.6 and
  10.2 carries exactly one of the three classes; the namespace facts are
  split into an `INHERITED` membership fact and an `INDEPENDENTLY_REACQUIRED`
  identity fact; the ordinary credential facts are split the same way into an
  `EXPLICITLY_HANDED_OFF` request and an `INDEPENDENTLY_REACQUIRED`
  observation; so no inherited state is described as an explicit handoff, no
  requested value is described as an observed one, and no row claims a class
  without the carrier that class requires. The round-2 and round-3 audit tables
  in 5.5 record each reclassification and addition.
- `PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS` — for every case
  that pins a `FIXTURE_FILE_ROLE` child, the helper opens the descriptor itself
  relative to its own validated root descriptor, so the target object is confined
  before it is used or mutated; every required check is an `fstat` fact on that
  descriptor, the acquisition is expressible as `os.open(..., dir_fd=...)`, and
  no descriptor has to cross the `sudo` boundary, so no unprovable transport is
  required. In the two ownership cases the mutation is expressible as
  `os.fchown` on that descriptor and the verification as a second `os.fstat` on
  it; in the mount case the same pinned descriptor carries the `st_uid == 0`
  predicate and no mutation at all is expressible on it, because none is
  permitted. Round 4 split the requirements into the COMMON STRUCTURAL set
  (5.8.1) and the case-specific ownership predicates (5.8.2, 5.8.3), so the rule
  set is now implementable at all three call sites instead of only at two.
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
| privileged ownership mutation not confined to a pinned child inode | 5.8 (the ownership cases; the mount case's own child is governed by the case-specific predicate of 5.8.3, added in round 4) | the helper opens the fixture child itself relative to its own validated root descriptor with `O_NOFOLLOW`, validates regular-file type, `st_nlink == 1`, ordinary-runner pre-mutation owner, exact initial mode `0644`, cleared setuid/setgid/sticky bits and nonzero `st_dev`/`st_ino`, then performs `fchown` on that descriptor and re-derives `st_uid` and `S_IMODE` from the same descriptor; a symlinked or hardlinked child is a hard refusal before any privileged mutation, and the ordinary process still reacquires the resulting state itself |
| `pull_request` workflow definition described as "taken from the PR head" | 6.2, 6.3 | the event-ref object is frozen as `refs/pull/<PR_NUMBER>/merge` with the synthetic merge commit as `GITHUB_SHA`, the code under qualification is separately bound to `github.event.pull_request.head.sha`, the two workflow blob identities are recorded and required to be equal before any privileged mutation, and a mismatch stops privileged execution as `WORKFLOW_AUTHORITY_MISMATCH` |

The four round-3 remediation findings resolve as follows:

| Finding | Corrected statement | Why it is now implementable |
| --- | --- | --- |
| `FILE_CHOWN_ONLY=true` contradicted by a helper that `fchown`s and then `fchmod`s, with a pre-mutation mode (`0640`) different from the post-mutation mode (`0644`) | 4.1, 4.2, 5.8 | one mode fact exists: the ordinary non-root process creates the fixture file at exactly `0644` before the helper is invoked, the helper performs `fchown` only, and the helper's required post-`fchown` `fstat` observes `S_IMODE == 0644` and `st_uid == derived_target_uid` on the same pinned descriptor. A mode that is not `0644` fails the fixture construction and is classified by origin; it is never repaired with a privileged `chmod`. The privileged mutation set is now exactly what `FILE_CHOWN_ONLY=true` claims |
| foreign target uid deferred to implementation time, with a selection rule instead of a literal | 5.2 | `FOREIGN_OWNER_TARGET_UID=65534` is frozen by this document, matching the existing ordinary RQP-L09 fixture convention, with `FOREIGN_OWNER_TARGET_UID_SELECTION=DESIGN_FROZEN_LITERAL` and no runtime substitution. The implementation transcribes one literal; the ordinary runner's non-`65534` requirement is a measurable precondition; and an unusable literal terminates in `QUALIFICATION_GAP` rather than a different uid |
| the ordinary runner's uid/gid crossed into the launcher with no producer, carrier, lifetime, consumer or closing checkpoint, and `SUDO_*` was the only implicit source | 5.5, 5.6, 10.1, 10.2, 5.10.1-5.10.2 | the ordinary process measures its own real `ORDINARY_UID`/`ORDINARY_GID` before `sudo`; the values cross as fixed numeric launcher arguments (`ORDINARY_REQUESTED_UID_GID_CONTINUITY=EXPLICITLY_HANDED_OFF`); the launcher validates `ORDINARY_UID != 0`, numeric validity and the invocation root's real `st_uid`/`st_gid` before the credential drop, refusing as `LAUNCHER_CREDENTIAL_REJECTED` with no namespace mutation; and `SUDO_UID`/`SUDO_GID` are corroboration only, never authority |
| "non-root evidence process" defined only by `euid != 0`, so retained effective capabilities satisfied it | 5.5, 5.6, 10.1, 10.2, 5.10.3 | the evidence process independently reacquires `ACTUAL_EUID`, `ACTUAL_EGID` and `ACTUAL_CAP_EFF` from itself and MUST require `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_EUID != 0` and `ACTUAL_CAP_EFF == 0` before the production primitive executes. A mismatch is a fixture-construction failure and `QUALIFICATION_GAP`, never evidence, and a nonzero effective capability mask is explicitly not a nonprivileged process |

The round-4 finding resolves as follows:

| Finding | Corrected statement | Why it is now implementable |
| --- | --- | --- |
| one undivided pinned-child rule set whose ownership requirement was `pre-mutation owner == ordinary runner uid`, applied also to a mount child that 5.9 freezes as helper-created and never ownership-mutated | 5.8.1-5.8.3, 5.9 | the requirements are now two layers with one owner each: the COMMON STRUCTURAL set (5.8.1) applies to `own-foreign`, `own-root` and `mount-fixture`, and the ownership predicate is explicit per case — `st_uid == ORDINARY_UID` before the `fchown` in 5.8.2, and `st_uid == 0` with `MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false` in 5.8.3. The helper-created mount child is therefore validated by rules it can satisfy, the ownership cases keep the predicate their case requires, and neither case acquires an ownership or credential mutation in order to satisfy the other's predicate |

| Requirement | Authority owner | Required evidence | Producer | Carrier / holder | Lifetime | Consumer / verifier | Closing checkpoint | Failure outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Helper argument protocol | repository design authority (this contract) | the exact argument vector, the derived uid/mode/child constants, and the rejection of every non-enumerated argument | privileged fixture helper | helper command line (closed enum plus untrusted locator) and the frozen constant table | one helper invocation | independent reviewer; ordinary suite unchanged | argument rejection and root revalidation recorded before any mutation | `HELPER_ARGUMENT_REJECTED`, `HELPER_ROOT_REJECTED` or `QUALIFICATION_GAP` |
| Process and namespace topology | same | the four roles with their real identities, the ordered lifecycle, and three measured mount namespace ids | privileged namespace launcher, evidence process and helper | real mount namespace identity of each running process | one run attempt, retained as CI evidence | independent reviewer | `PRIVATE_EVIDENCE_MNT_NS_ID == PRIVATE_HELPER_MNT_NS_ID` and `PRIVATE_EVIDENCE_MNT_NS_ID != HOST_MNT_NS_ID`, both measured | `QUALIFICATION_GAP` plus a design finding; no mount mutation is attempted |
| Cross-boundary continuity classification | repository design authority (this contract) | every row of 5.5, 5.6 and 10.2 with exactly one class, and the carrier that class requires | this contract for the model; the fixture for the measured facts | the frozen tables of 5.5, 5.6 and 10.2, and the real objects the classified facts describe | this document for the model; one run attempt for the measured facts | independent reviewer | the round-2 audit table in 5.5 and the class columns of 5.6 and 10.2 contain no unclassified or doubly classified row | a class without its required carrier, or an inherited fact described as a handoff, is a design failure and blocks the implementation PR |
| Privileged child inode confinement | same | pre-mutation `fstat` facts on the pinned child for that child's own case requirement set, the refusal outcomes, the helper's own post-`fchown` `fstat` in the ownership cases, and the post-mutation reacquisitions by the ordinary process | privileged fixture helper for the mutation and its own verification; non-root evidence process for the reacquisitions | the helper's own child descriptor, and the real inode the ordinary process re-reads afterwards | one helper invocation, then one evidence measurement | independent reviewer; ordinary suite unchanged | child validation recorded before the `fchown` in the ownership cases and before use in the mount case, and the 4.3 post-mutation controls recorded before the production call | `HELPER_ROOT_REJECTED` before mutation in `own-foreign` and `own-root`, where the role must preexist; `QUALIFICATION_GAP` with a 5.7 origin for a missing or non-conforming mount-case child after the helper's own creation (5.8.3); never a pass in either case |
| Ownership capability model | same | the exact privileged mutation performed per case, the capability set the helper really used, and the ordinary reader's real `O_RDONLY` success through `0644` | privileged fixture helper for the mutation and its capability record; non-root evidence process for the real open control | the helper's recorded `CapEff` and the ordinary process's own open result | one run attempt, retained as CI evidence | independent reviewer | `OWNERSHIP_MUTATION_REQUIRED_CAPABILITY=CAP_CHOWN` for the two ownership cases, `MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false` with `MOUNT_FIXTURE_FILE_CREATION_REQUIRES_CAP_CHOWN=false` for the mount case (1.4), no `CAP_FOWNER` and no `CAP_DAC_OVERRIDE` requirement for these effects, and `CONTROL_real_os_open_O_RDONLY_succeeds=true` recorded | `QUALIFICATION_GAP` or `ENVIRONMENT_FAILURE`; a capability-granted pass is not a pass |
| Ordinary credential handoff | same | the measured `ORDINARY_UID`/`ORDINARY_GID`, the launcher arguments that carried them, and the launcher's validation against the real invocation root | `HOST_OBSERVER` or the ordinary workflow process for the measurement; privileged namespace launcher for the validation | fixed numeric launcher arguments, plus the real invocation root's `st_uid`/`st_gid` | one launcher invocation | privileged namespace launcher; independent reviewer for the recorded values | `ORDINARY_UID != 0`, valid numeric ids, and invocation-root `st_uid`/`st_gid` equality recorded before any credential drop | `LAUNCHER_CREDENTIAL_REJECTED` or `QUALIFICATION_GAP`, with no namespace mutation |
| Non-root evidence identity | same | `ACTUAL_EUID`, `ACTUAL_EGID` and the decoded `ACTUAL_CAP_EFF` of the running evidence process | non-root evidence process, from its own real process state | none: the facts are measured in the process that holds them and recorded as run output | the evidence process's lifetime, recorded in the run attempt | independent reviewer; the production primitive depends on the result | the four required equalities hold before the production primitive executes | `QUALIFICATION_GAP` and a fixture-construction failure; never evidence and never a product defect |
| Foreign uid authority | same | the frozen literal, the ordinary runner's effective uid, and the host's representability of `65534` | this contract for the literal; the preflight for the host facts | the frozen constant table and the real preflight observations | this document for the literal; one run attempt for the observations | independent reviewer | `FOREIGN_OWNER_TARGET_UID=65534`, ordinary `euid != 65534`, and no runtime substitution recorded | `QUALIFICATION_GAP`; no alternate uid is selected |
| Privileged mount child safety | same | exclusive creation of the image and mountpoint by the helper, the pinned identities, and the pre-use revalidation | privileged fixture helper | helper-created objects under the validated root, each pinned by a descriptor the helper holds | one run attempt | independent reviewer | pre-existing role objects refuse as `HELPER_ROOT_REJECTED`, and both objects match their pinned identity before use | `HELPER_ROOT_REJECTED`, or `QUALIFICATION_GAP` plus a design finding |
| Mount-case child ownership predicate | same | the `fstat` facts on the helper-pinned mount-case child, the recorded `st_uid`, the absence of any ownership call, and the ordinary process's real `O_RDONLY` open of the `0644` root-owned file | privileged fixture helper for the creation, the pinning and the `st_uid == 0` check; non-root evidence process for the ordinary open | the helper's own child descriptor, and the real inode the ordinary process opens | one helper invocation, then one evidence measurement | independent reviewer; the RQP-L17 positive pre-drift admission depends on the ordinary open | `MOUNT_FIXTURE_FILE_ST_UID == 0` with no ownership mutation, and the ordinary `O_RDONLY` open recorded before the positive pre-drift admission | `QUALIFICATION_GAP` plus a design finding; never a pass and never RQP-L09 evidence |
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
rather than re-resolved by pathname (5.8), the ownership predicate is stated per
case rather than assumed shared across cases whose provenance differs
(5.8.1-5.8.3), the mount case's root-owned child is admitted by production
rather than chowned into admissibility (5.8.3), the privileged mount's source
and target are created by the helper rather than adopted from the caller (5.9), the
executed workflow definition is compared against the exact-head definition
instead of being assumed identical to it (6.3), the ordinary identity is
measured and handed off rather than read from the privilege tool's environment
(5.10.1-5.10.2), and the evidence process reacquires its own identity and
effective capabilities rather than inheriting the launch request's claim
(5.10.3). No writer/reader evidence handoff exists or is invented.

Two limits are named rather than papered over, and both are named deliberately.
`mount(2)` accepts pathnames and has no descriptor form, so the mount target is
confined by helper-exclusive creation plus pinned-identity revalidation instead
of by a descriptor argument (5.9). The privileged run cannot read the reviewer's
expected tree, so `PR_HEAD_TREE` is derived from the proven checked-out head and
published for the reviewer to compare rather than read from an input (6.3).
Neither is an assumed continuity, and neither is frozen as a requirement the
declared architecture cannot express.

Two platform facts are likewise stated rather than assumed, because the round-3
credential requirements rest on them. The capability mask is read from the
process's own `/proc/self/status` `CapEff` field, which is a real
kernel-provided value on the declared Linux runner and needs no privilege to
read; and the identity of a launched process is a request until that process
reports its own real `euid`, `egid` and capability mask, which is exactly why
5.10.3 reacquires them instead of trusting the launch. Neither is a capability
artifact and neither is unavailable on the declared platform.

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
| The helper changes ownership only in the ownership cases, never mode anywhere | frozen, sections 4.1-4.2 and 5.8.2-5.8.3 | none added | no production symbol changes | privileged case later; `fchmod` is absent from the helper, the mount case performs no ownership call, and the post-`fchown` `fstat` is recorded |
| The ownership cases require `CAP_CHOWN` alone, and the mount case's fixture file requires no ownership capability at all | frozen, sections 5.8.2-5.8.3, 7 and 1.4 | none added | no production symbol changes | privileged case later; the helper's real `CapEff`, the absence of an ownership call in the mount case, and the ordinary process's real `O_RDONLY` success are all recorded |
| The pinned child's ownership predicate is case-specific: `st_uid == ORDINARY_UID` for the ownership cases, `st_uid == 0` and no ownership mutation for the mount case | frozen, sections 5.8.1-5.8.3 and 5.9 | none added; the role name and the predicates are helper-internal | no production symbol changes | privileged case later; each case's own predicate is asserted on the helper-pinned descriptor, and the common structural requirements are shared, not the ownership predicate |
| The foreign target uid is the design-frozen literal `65534` | frozen, sections 4.4 and 5.2 | none added; the literal is helper-internal | no production symbol changes | privileged case later; the literal, the ordinary `euid != 65534` precondition and the no-substitution rule are pinned |
| The ordinary uid/gid is explicitly handed off and validated before any credential drop | frozen, sections 5.5-5.6, 5.10.1-5.10.2 and 10.1 | none added | no production symbol changes | privileged case later; the handoff arguments and the launcher's root-ownership validation are recorded |
| The evidence process reacquires its own identity and requires `CapEff == 0` | frozen, sections 5.5-5.6, 5.10.3 and 10.1 | none added | no production symbol changes | privileged case later; `ACTUAL_EUID`, `ACTUAL_EGID` and the decoded `ACTUAL_CAP_EFF` are measured before the production call |
| The privileged ownership mutation acts on a helper-pinned child descriptor, and the mount case's child is pinned the same way without a mutation | frozen, sections 5.8.1-5.8.3 | none added | no production symbol changes | privileged case later; the case-appropriate `fstat` facts, the post-`fchown` `fstat` in the ownership cases and the post-mutation reacquisitions are measured |
| The mount-case fixture file is helper-created, root-owned and never ownership-mutated | frozen, sections 5.8.3 and 5.9 | none added | no production symbol changes | privileged case later; `st_uid == 0`, the absence of any ownership call, and the ordinary process's real `O_RDONLY` open before the positive pre-drift admission are measured |
| Mount fixture file ownership is not RQP-L09 evidence and the ordinary read is the real DAC witness | frozen, sections 5.8.3, 9 and 11 | none added | no production symbol changes | privileged case later; `MOUNT_FIXTURE_ROOT_OWNER_IS_RQP_L09_EVIDENCE=false` and `MOUNT_FIXTURE_ORDINARY_READ_IS_REAL_DAC_WITNESS=true` are pinned, and the mount case reports no L09 result |
| Privileged mount source and target are created by the helper and never adopted from the caller | frozen, section 5.9 | none added | no production symbol changes | privileged case later; exclusive creation and the refusal outcomes are pinned by the implementation PR |
| The executed workflow definition equals the exact-head workflow definition | frozen, section 6.3 | the workflow does not exist yet; the equality is a run-time check, not a declaration | not applicable | workflow contract pinned by a checker in the implementation PR |
| Cleanup follows the frozen state machine and ends residue-free | frozen, section 10.4 | none added | no production symbol changes | privileged case later; the four residue controls are measured, not asserted |
| The privileged workflow authority is frozen | frozen, sections 6.1-6.3 | none added; the workflow does not exist yet | not applicable | workflow contract pinned by a checker in the implementation PR |
| Every privileged or destructive effect has exactly one closure row with its own declared authority | frozen, section 1.5 | none added; the effect table and the authority names are design facts | no production symbol changes | privileged case later; the preflight records the real `CapEff` and the declared authorities are compared against the effects actually performed |
| Every case's `0644` requirement is common, while its mode provenance is case-scoped | frozen, sections 4.1, 5.8 and 5.8.3 | none added | no production symbol changes | privileged case later; the ordinary process records the mode it established in the ownership cases and the helper records the mode it created in the mount case, with `fchmod` absent everywhere |
| A missing or non-conforming pinned child is classified by origin, and is a pre-mutation refusal only where the role must preexist | frozen, sections 5.7, 5.8.1, 5.8.3 and 5.9 | none added | no production symbol changes | privileged case later; the two ownership cases record a refusal before the `fchown`, and the mount case records its after-creation failure with the origin that produced it |
| Cleanup restores no ownership | frozen, sections 5, 10.4 and 1.5 | none added | no production symbol changes | privileged case later; the cleanup path performs no ownership call, and the removed objects keep the ownership the setup gave them until they are removed |

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
  details. On the helper side, the descriptor-relative acquisition of 5.8.1 is
  directly expressible in Python: `os.open(name, flags, dir_fd=root_fd)` is
  `openat` against the helper's own validated root descriptor, with `os.fstat`
  acting on the returned descriptor and `os.fchown` acting on it in the two
  ownership cases only; `os.fchmod` is not used, because no mode is changed after
  creation, so the pinned child model needs no new API, no new dependency, no
  descriptor transport and no capability beyond `CAP_CHOWN` for the ownership
  effects. The mount case is expressible in the same standard library: the helper
  creates the file inside its own freshly mounted filesystem with
  `O_CREAT|O_EXCL` and mode `0644` under a creation-time umask that cannot clear
  those bits, opens it again with `O_RDONLY|O_NOFOLLOW|O_CLOEXEC` to pin it, and
  requires `st_uid == 0` from `os.fstat` on that pinned descriptor, while the
  ordinary process's own `O_RDONLY` open of the same file is the read witness.
  No ownership call and no mode call appears in that case at all. The credential
  model is
  expressible with the standard library alone as well: the ordinary process
  measures itself with `os.geteuid`/`os.getegid`, the launcher passes on two
  integers, and the evidence process reads `os.geteuid`, `os.getegid` and the
  real `CapEff` mask from `/proc/self/status`. No new public API is required.
- Can existing evidence and data structures carry all required facts? Yes: the
  retained security tuple, the mount description triple, the retained
  descriptor identity and the real mount table carry every fact the cases
  assert. The mount case's facts are carried by the same structures: the pinned
  mount-case descriptor's `fstat` facts for the structural requirements and the
  `st_uid == 0` predicate, the ordinary process's own open result for the DAC
  witness, and the retained descriptor of section 9 for the RQP-L17 admission.
  The workflow-provenance facts of 6.3 are plain strings and Git blob
  identities, carried by the workflow output the manifest already binds to the
  exact head.
- Is new persistent state required? No. The fixture root is invocation-local
  under `RUNNER_TEMP` and is removed by checked cleanup.
- Is a cross-boundary handoff required? Yes, one privilege boundary, modeled in
  5.5 and 5.6. It is explicit, bounded, revalidated by the receiving side, and
  carries no authority. Three facts cross it. An untrusted root locator and a
  closed case enum are handed off to the helper (5.1-5.3). The ordinary runner's
  uid and gid are handed off to the launcher as fixed numeric arguments and
  validated there against the real invocation root before the credential drop
  (5.10.1-5.10.2). Every other crossing fact is inherited (namespace membership)
  or independently reacquired — including the evidence process's own `euid`,
  `egid` and effective capability mask (5.10.3) — and the privileged ownership
  mutation's target is acquired by the helper itself (5.8) rather than handed
  off, as is the mount case's fixture child (5.8.1, 5.8.3). A second,
  non-process authority boundary — executed workflow definition
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

The round-4 preview result is that the corrected pinned-child model maps to an
implementation without an unauthorized effect:

```text
ROUND4_PREVIEW_PINNED_CHILD_MODEL_IMPLEMENTABLE=true
ROUND4_PREVIEW_MOUNT_CASE_REQUIRES_OWNERSHIP_MUTATION=false
ROUND4_PREVIEW_MOUNT_CASE_REQUIRES_CREDENTIAL_MUTATION=false
ROUND4_PREVIEW_MOUNT_CASE_OWNERSHIP_PREDICATE_SOURCE=pinned_descriptor_fstat
ROUND4_PREVIEW_NEW_AUTHORITY_REQUIRED=false
ROUND4_PREVIEW_NEW_PERSISTENT_STATE_REQUIRED=false
ROUND4_PREVIEW_STOPS_IMPLEMENTATION_CONTRACT=true
```

`ROUND4_PREVIEW_STOPS_IMPLEMENTATION_CONTRACT=true` records what the failed
attempt demonstrated: a pinned-child model that an implementation must narrow at
a call site is a contract that stops the implementation, rather than a contract
the implementation may interpret. The corrected model needs neither an ownership
mutation nor a credential mutation to place the mount-case child under a rule
set it can satisfy, so the stop condition is not reachable through the case that
produced it. A preview is feasibility evidence, not implementation
authorization: `A3_IMPLEMENTATION_AUTHORIZED=false` in 1 is unchanged by this
subsection.

The round-5 preview question is whether the per-effect closure of 1.5 maps onto
operations the declared architecture can really perform. It does, and each
effect's authority is bounded by what its own operation needs: namespace creation
and private propagation are `unshare`/`mount` operations with
`CAP_SYS_ADMIN`; image creation is `os.open(..., O_CREAT|O_EXCL)`; formatting is
the `mke2fs` tool writing the file the helper owns; loop acquisition and release
are the documented loop ioctls; the mount and both unmount forms are `mount(2)`
and `umount2(2)`; and the three removals are `unlink`/`rmdir` on objects whose
containing directories the helper can reach. None of them needs a new public API,
a new dependency, a descriptor across the `sudo` boundary, or a capability the
operation does not exercise, and the one access authority the fixture does need —
reaching objects under an owner-only invocation root — is declared, recorded from
the real capability mask, and produces no outcome and no evidence.

```text
ROUND5_PREVIEW_PRIVILEGED_EFFECT_CLOSURE_IMPLEMENTABLE=true
ROUND5_PREVIEW_EFFECTS_WITH_DECLARED_AUTHORITY=16
ROUND5_PREVIEW_EFFECTS_WITHOUT_DECLARED_AUTHORITY=0
ROUND5_PREVIEW_DECLARED_AUTHORITIES_WITHOUT_REQUIRED_EFFECT=0
ROUND5_PREVIEW_NEW_PUBLIC_API_REQUIRED=false
ROUND5_PREVIEW_NEW_DEPENDENCY_REQUIRED=false
ROUND5_PREVIEW_NEW_AUTHORITY_REQUIRED=false
ROUND5_PREVIEW_ACCESS_AUTHORITY_PRODUCES_EVIDENCE=false
ROUND5_PREVIEW_MODE_CHANGE_REQUIRED=false
ROUND5_PREVIEW_CLEANUP_OWNERSHIP_CALL_REQUIRED=false
```

`ROUND5_PREVIEW_NEW_AUTHORITY_REQUIRED=false` is scoped to this design: it means
the closure adds no authority beyond the fixture's real operations and the
preflight's recorded capability set. Privileged execution authority and CI
control-plane change authority remain required by the later implementation phase,
exactly as the authority facts above state.

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
- release checker: `python scripts/check_release.py`;
- CI tier classifier:
  `python scripts/ci_risk_tier.py --mode pull_request --base <base> --head <head>`,
  which must continue to report the docs-only tier for this one-document change.

No remediation round adds a further validation class. Each changes one document,
so the same checks apply to the remediated head, and the prohibitions are
unchanged:

```text
NO_FULL_PYTEST=true
NO_SUDO=true
NO_CHOWN=true
NO_CHMOD_REQUIRING_PRIVILEGE=true
NO_MOUNT=true
NO_UMOUNT=true
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

Round 5 adds no validation class either. It changes the same one document, so the
same five checks apply to the remediated head, and the round-5 effect rows add no
executable surface to validate locally: the effects they enumerate are the
fixture's future privileged operations, which this PR neither implements nor
runs.

```text
ROUND5_VALIDATION_SCOPE=docs_governance_only
ROUND5_VALIDATION_CLASSES=git_diff_check,repo_hygiene,destructive_design_gate,release_check,ci_risk_tier
ROUND5_PRIVILEGED_EXECUTION_PERFORMED=false
ROUND5_IMPLEMENTATION_FILES_CHANGED=0
ROUND5_CHANGED_FILE_COUNT=1
```

## 20. Lifecycle and Stop

One design document, one commit, one DRAFT pull request, no amend, no force
push, no merge. The PR body states the design-only flags and this document is
its authority.

History is additive across all three design-review remediation rounds. Each of
those remediated heads keeps the failed head it corrects as its direct parent, so
every failure stays in the branch history rather than being rewritten:

```text
A3D_REMEDIATION_ROUND_1_PARENT=777a509c5d144deaf4c06a432cddb992b86a28b6
A3D_REMEDIATION_ROUND_2_PARENT=8d791a82b1e482c586a0c8c1f990d722c4b8464e
A3D_REMEDIATION_ROUND_3_PARENT=80549a22e2770dd6392771207a3d43af4f9a7d84
A3D_REMEDIATION_ROUND_3_COMMIT_PARENT=80549a22e2770dd6392771207a3d43af4f9a7d84
A3D_HISTORY_REWRITTEN=false
A3D_FORCE_PUSH=false
A3D_AMEND_USED=false
A3D_REBASE_USED=false
A3D_RESET_USED=false
```

Round 4 preserves history differently, and the difference is stated rather than
smoothed over. Its trigger was not a failed design review, so there is no failed
design head for it to parent; instead it corrects the failed implementation
attempt recorded in 1.4, and that attempt was never pushed. Round 4 therefore
uses a new one-commit branch built directly on exact formal main, and it does not
parent, contain or continue the failed implementation head:

```text
A3D_REMEDIATION_ROUND_4=4
A3D_REMEDIATION_ROUND_4_PARENT=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_REMEDIATION_ROUND_4_PARENT_IS_EXACT_FORMAL_MAIN=true
A3D_REMEDIATION_ROUND_4_BRANCH=design/a3d-round4-mount-owner-predicate
A3D_REMEDIATION_ROUND_4_COMMIT_COUNT=1
A3D_ROUND4_CONTAINS_FAILED_IMPLEMENTATION_HEAD=false
A3D_ROUND4_PARENTS_FAILED_IMPLEMENTATION_HEAD=false
A3D_ROUND4_REWRITES_FAILED_IMPLEMENTATION_HEAD=false
FAILED_IMPLEMENTATION_HEAD_REACHABLE_ON_ORIGIN=false
A3D_HISTORY_PRESERVED_BY_RECORD=true
A3D_HISTORY_REWRITTEN=false
```

The round-3 fast-forward precondition applies to the round-3 branch, not to this
one, because this branch is new rather than a continuation of it. The round-4
push creates the remote branch, and it happens only after a fresh read of the
remote repository confirms both of:

```text
A3D_ROUND4_PREPUSH_ORIGIN_MAIN_REQUIRED=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND4_PREPUSH_BRANCH_ABSENT_ON_ORIGIN_REQUIRED=true
A3D_ROUND4_PUSH_IS_NEW_BRANCH=true
A3D_ROUND4_PUSH_FORCE=false
```

If `origin/main` no longer equals that SHA, or the round-4 branch already exists
on `origin`, the push does not happen and this workstream stops instead of
rewriting, rebasing or force-pushing anything.

Round 5 preserves history the way rounds 1 to 3 do, because its trigger is an
independent review failure of an exact head. It adds exactly one commit whose
direct parent is that failed head, pushes it as a normal fast-forward onto the
branch that already carries it, and never rewrites, replaces or drops it:

```text
A3D_REMEDIATION_ROUND_5=5
A3D_REMEDIATION_ROUND_5_PARENT=3bc6862c869590ee128636e2a9ca5b4ddf9603b2
A3D_REMEDIATION_ROUND_5_PARENT_IS_FAILED_FOURTH_REVIEW_HEAD=true
A3D_REMEDIATION_ROUND_5_BRANCH=design/a3d-round4-mount-owner-predicate
A3D_REMEDIATION_ROUND_5_COMMIT_COUNT=1
A3D_REMEDIATION_COMMIT_PARENT=3bc6862c869590ee128636e2a9ca5b4ddf9603b2
A3D_ROUND5_CONTAINS_FAILED_FOURTH_REVIEW_HEAD=true
A3D_ROUND5_PARENTS_FAILED_FOURTH_REVIEW_HEAD=true
A3D_ROUND5_REWRITES_FAILED_FOURTH_REVIEW_HEAD=false
A3D_ROUND5_PUSH_IS_FAST_FORWARD=true
A3D_ROUND5_PUSH_IS_NEW_BRANCH=false
A3D_ROUND5_PUSH_FORCE=false
A3D_HISTORY_PRESERVED_BY_RECORD=true
A3D_HISTORY_REWRITTEN=false
```

The unscoped `A3D_REMEDIATION_COMMIT_PARENT` above is round 5's own commit parent
and names the failed fourth-review head, which is what makes the failed head
auditable from the branch tip. Rounds 1 to 3 keep their own parents under their
own names; the round-3 value that this token held before round 5 is preserved
above as `A3D_REMEDIATION_ROUND_3_COMMIT_PARENT`, so correcting the bare pointer
does not erase the round-3 fact.

After the exact-head pull-request CI reaches a terminal conclusion, this
workstream stops and returns for independent review:

- terminal SUCCESS -> report the exact head SHA, head tree, changed-file set,
  contract implementability, PR number and state, and the exact CI run id,
  event, attempt and result, then stop;
- any terminal non-success -> report the actual workflow conclusion, the
  affected job or jobs, and the failing step when available, then stop.

The remediated head requires a fresh independent exact-head review; no earlier
review's failure is cleared by this document's own claim.

Merge remains unauthorized. Implementation, privileged execution, CI workflow
change, production change and registry admission each remain separately
unauthorized by this document.
