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
then the round-4 head `3bc6862...` (fourth failed head) then the round-5 head
`65061f1...` (fifth failed head) then this head. No failed
head is rewritten, amended, rebased or force-pushed,
and every failure record stays in this document. Each round is recorded by its
own token — `A3D_FIRST_REMEDIATION_ROUND=1` in 1.1,
`A3D_SECOND_REMEDIATION_ROUND=2` here, `A3D_THIRD_REMEDIATION_ROUND=3` in 1.3,
`A3D_FOURTH_REMEDIATION_ROUND=4` in 1.4, `A3D_FIFTH_REMEDIATION_ROUND=5` in 1.5,
and `A3D_SIXTH_REMEDIATION_ROUND=6` with
the current-round pointer in 1.6 — so
no round fact is stated twice with two different values. That rule is now
mechanically checkable and checked: the current-round pointer
`A3D_CURRENT_REMEDIATION_ROUND` is stated exactly once in this document, in the
subsection belonging to the current round — 1.6 at this head, 1.5 at the round-5
head —
because a pointer is a fact about the head it describes. Rounds 3, 4 and 5 keep
the same information under a head-qualified name,
`A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=3`,
`A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=4` and
`A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=5`, so each earlier round's fact is
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
ROUND4_CAP_DAC_OVERRIDE_REQUIRED=false
ROUND4_CAP_DAC_OVERRIDE_REQUIRED_IS_A_ROUND4_RECORD=true
ROUND4_CAP_DAC_OVERRIDE_REQUIRED_WITHDRAWN_BY_ROUND6=true
ROUND4_CAP_DAC_OVERRIDE_REQUIRED_WITHDRAWAL_REASON=an_authority_does_not_cease_to_be_required_because_it_produces_no_evidence_or_product_outcome
CURRENT_CAPABILITY_AND_ACCESS_AUTHORITY_STATEMENTS=section_1_7
RQP_L17_MOUNT_EFFECTS_REMAIN_CAP_SYS_ADMIN_BOUND=true
RQP_L17_MOUNT_EFFECTS_REMAIN_CAP_SYS_ADMIN_BOUND_IS_A_ROUND4_RECORD=true
RQP_L17_MOUNT_EFFECTS_REMAIN_CAP_SYS_ADMIN_BOUND_SUPERSEDED_BY_ROUND5=true
PRIVILEGED_EFFECT_CLOSURE_RERUN_FOR_ROUND=4
ROUND4_EFFECT_TABLE_IS_A_ROUND4_RECORD_NOT_THE_CURRENT_CLOSURE=true
ROUND4_AGGREGATE_MOUNT_ROW_WITHDRAWN_BY_ROUND5=true
CURRENT_PRIVILEGED_EFFECT_CLOSURE=section_1_5
CURRENT_PRIVILEGED_EFFECT_CLOSURE_ROWS=21
CURRENT_PRIVILEGED_EFFECT_CLOSURE_ONE_EFFECT_PER_ROW=true
```

`CAP_FOWNER_REQUIRED=false` is a scoped statement, and the scope is part of it:
it is a claim about the ownership mutation, which changes no mode and touches no
other FOWNER-governed attribute. Nothing in this contract changes a mode, so no
FOWNER-governed attribute is touched anywhere, and no required outcome may be
produced by, attributed to, or proved by an access bypass: the ordinary reader's
control is a real `0644` DAC read taken by a process with no effective capability
(4.3, 5.10.3). That attribution rule is NOT a claim that the helper's own access
authority is unnecessary. Round 4 also froze `CAP_DAC_OVERRIDE_REQUIRED=false`,
and round 6 withdrew it for exactly that reason: an authority does not cease to be
required merely because it produces no evidence or product outcome. The helper's
access authority is required, and it is derived per effect in 1.6. The
`CAP_FOWNER` statement is likewise NOT a claim about the separately frozen
RQP-L17 mount prerequisite set of 7, which stays bound to `CAP_SYS_ADMIN` and to
the capabilities the real mount setup records.

The closure held in both directions at the round-4 head, over the rows above:
every effect those rows named had a declared authority, and no declared authority
was broader than its effect. The
mount case's fixture file adds an effect — exclusive creation — with no ownership
authority attached to it, and the ownership cases keep exactly the `CAP_CHOWN`
authority that their single `fchown` justifies.

That closure is round 4's, over round 4's four rows, and round 5 re-ran it over
the complete effect set (1.5). Two scoped consequences of the re-run belong
beside these tokens. First, the helper's own file access under the invocation
root is a separately declared and genuinely required access authority: round 5
declared it and round 6 corrected it to the narrowest per-effect authority,
`CAP_DAC_READ_SEARCH` for traversal only and `CAP_DAC_OVERRIDE` where the effect
must write a directory entry (1.5, 1.6). Second, deriving each mount effect's
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
A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=5
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
complete effect set is enumerated below. This table is the current closure:
round 6 corrected it in place rather than adding a second table, and 1.6 records
exactly what changed. Every row is a real material effect and no row is a
placeholder; each carries its case scope, target object, target-binding
mechanism, authority derived from that effect's own operation, preconditions,
postconditions and cleanup or terminal transition, and each states the access
authority its own pathname or object access needs, derived for that effect
instead of inherited from a blanket grant. The closure has to hold in both
directions: it is not enough for every effect to have an authority, every
declared authority must also correspond to an actual required effect, and no
declared authority may be broader than the effect that needs it.

| # | Case scope | Operation or effect | Target object | Target binding mechanism | Required authority or capability | Preconditions | Postconditions | Cleanup or terminal transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | all cases (run-scoped) | credential transition: the privileged namespace launcher's forked child becomes the ordinary identity before `execve` of `NONROOT_EVIDENCE_PROCESS` — `setgroups(0, NULL)`, then `setgid(ORDINARY_GID)`, then `setuid(ORDINARY_UID)`; no external privilege tool performs it | the forked child process's own real, effective and saved uid, gid and supplementary group list, and its own capability sets and securebits | the call acts on the caller's own credentials and takes no pathname and no target object, so the binding is the process identity of the child that performs it; the child performs the sequence on itself after the parent has validated the handoff, and the binding is valid from the completed transition until that process exits (5.10, 10.1) | `CAP_SETGID` for the empty supplementary group list and the GID transition, and `CAP_SETUID` for the UID transition (capabilities(7): `CAP_SETGID` — "make arbitrary manipulations of process GIDs and supplementary GID list"; `CAP_SETUID` — "make arbitrary manipulations of process UIDs"); no `CAP_SETPCAP`, because this effect never edits a capability set — the kernel clears the permitted, effective and ambient sets itself when the UID transition makes every uid nonzero (capabilities(7), "Effect of user ID changes on capabilities"); no access authority, because no pathname is resolved and no object below the root is touched (1.6) | the launcher validated `ORDINARY_UID != 0` and `ORDINARY_GID` against the real invocation root under 5.10.2; the child created by `fork` has not yet changed identity; the child's inherited securebits and `NoNewPrivs` are observed to be the default values that let the kernel perform the set-ID fixups (5.10.3); the operation order is the frozen `setgroups` then `setgid` then `setuid`, because `setgroups(2)` is a `CAP_SETGID` operation that must run while the child still holds that capability Canonical predecessors for this effect: the case-qualified fixture setup that must have completed and exited first — E2 and E3 for `own-foreign`, E4 and E5 for `own-root`, and E20 for `mount-fixture` (10.1). | `UID_REAL == UID_EFFECTIVE == UID_SAVED == ORDINARY_UID`, `GID_REAL == GID_EFFECTIVE == GID_SAVED == ORDINARY_GID`, the supplementary group list is empty, and `CapPrm`, `CapEff` and `CapAmb` are all observed `0` after the transition and after the following `execve`, so no unprivileged capability remains and none can be re-derived (5.10.3) | terminal for the effect: there is no reverse transition and no setuid-root program on the path, and `setuid(2)` setting the real, effective and saved uid together is what makes the privileged identity unrecoverable; the transition is performed again only for a separate case's child, never as a restoration Canonical successors for this effect: E21. |
| E2 | own-foreign | `own-foreign` `openat` acquisition of the pinned `FIXTURE_FILE_ROLE` child through the helper's own validated root descriptor (`O_RDONLY\|O_NOFOLLOW\|O_CLOEXEC`), then the required pre-mutation `fstat`; no mutation (5.8.1) | the fixture file the ordinary runner created inside the invocation root at the frozen `FIXTURE_FILE_ROLE` | the child descriptor the helper opened for itself relative to its own validated root descriptor with `O_NOFOLLOW`; the helper never re-resolves the caller's string or the role name after this open, and every later check and mutation in this case is an `fstat` or a call on that descriptor (5.8.1) | `CAP_DAC_READ_SEARCH`, the minimal capability for the one directory search check this effect performs: the `openat` resolves the frozen `FIXTURE_FILE_ROLE` name against the helper's own validated root descriptor, and the invocation root is `S_IMODE == 0o700` and owned by the ordinary runner, so the search (execute) check on it fails for the helper and is bypassed by the capability that "bypass[es] file read permission checks and directory read and execute permission checks" (capabilities(7)); this effect writes and removes no directory entry, so `CAP_DAC_OVERRIDE` is not required for it and is not declared (1.10.4); no `CAP_CHOWN`, because this row does not mutate; no authority at all for the mutation itself, which the already-open descriptor carries | 5.3 root validation passed; the 5.8.1 common structural facts hold on the pinned descriptor; the 5.8.2 predicate `st_uid == ORDINARY_UID` holds; the ordinary runner's effective uid is not `65534` (5.2) Canonical predecessors for this effect: 5.3 root validation and the privileged ownership setup invocation; this effect is the first effect of its case. | the pinned child descriptor exists, the object is a regular single-link `0644` file owned by the ordinary runner, and the helper holds the only reference it will mutate through The recorded result is consumed by E25. | terminal for the access: the descriptor is closed by the helper's exit; the object itself is removed by E25 Canonical successors for this effect: E3. |
| E3 | own-foreign | `own-foreign` `fchown(pinned_child_fd, 65534, observed_gid)`; one ownership call and no mode call | the pinned `FIXTURE_FILE_ROLE` inode the ordinary runner created inside the invocation root | the child descriptor E2 opened; the call takes the descriptor, so no pathname is re-resolved and the binding is valid from that open until the descriptor is closed | the reviewed privileged identity, plus `CAP_CHOWN` for the mutation call (capabilities(7): "make arbitrary changes to file UIDs and GIDs"); no `CAP_FOWNER` is required by the mutation call, which acts on an already-open descriptor; no access authority, because the descriptor is already held | E2 completed and the pinned child descriptor is the object this call mutates; the 5.8.2 predicate `st_uid == ORDINARY_UID` holds on that descriptor Canonical predecessors for this effect: E2. | `st_uid == 65534`, `S_IMODE == 0o644`, `st_nlink == 1` and an empty attribute set, re-derived by the helper on the same descriptor and independently reacquired by the ordinary process before the production call (4.3) | terminal: there is no reverse ownership call and no mode restoration, because no mode was changed; the object is removed by the 10.4 state machine through E25 Canonical successors for this effect: E1. |
| E4 | own-root | `own-root` `openat` acquisition of the pinned `FIXTURE_FILE_ROLE` child through the helper's own validated root descriptor (`O_RDONLY\|O_NOFOLLOW\|O_CLOEXEC`), then the required pre-mutation `fstat`; no mutation (5.8.1) | the fixture file the ordinary runner created inside the invocation root at the frozen `FIXTURE_FILE_ROLE` | the child descriptor the helper opened for itself relative to its own validated root descriptor with `O_NOFOLLOW`; the same never-re-resolved binding as E2 | `CAP_DAC_READ_SEARCH`, the minimal capability for the one directory search check this effect performs: the `openat` resolves the frozen `FIXTURE_FILE_ROLE` name against the helper's own validated root descriptor, and the invocation root is `S_IMODE == 0o700` and owned by the ordinary runner, so the search (execute) check on it fails for the helper and is bypassed by the capability that "bypass[es] file read permission checks and directory read and execute permission checks" (capabilities(7)); this effect writes and removes no directory entry, so `CAP_DAC_OVERRIDE` is not required for it and is not declared (1.10.4); no `CAP_CHOWN`, because this row does not mutate; no authority at all for the mutation itself, which the already-open descriptor carries | 5.3 root validation passed; the 5.8.1 common structural facts hold on the pinned descriptor; the 5.8.2 predicate `st_uid == ORDINARY_UID` holds; the 5.2 `ROOT_OWNED` precondition that the ordinary runner's effective uid is not `0` Canonical predecessors for this effect: 5.3 root validation and the privileged ownership setup invocation; this effect is the first effect of its case. | the pinned child descriptor exists, the object is a regular single-link `0644` file owned by the ordinary runner, and the helper holds the only reference it will mutate through The recorded result is consumed by E25. | terminal for the access: the descriptor is closed by the helper's exit; the object itself is removed by E25 Canonical successors for this effect: E5. |
| E5 | own-root | `own-root` `fchown(pinned_child_fd, 0, observed_gid)`; one ownership call and no mode call | the pinned `FIXTURE_FILE_ROLE` inode the ordinary runner created inside the invocation root | the child descriptor E4 opened; the call takes the descriptor, so no pathname is re-resolved | the reviewed privileged identity, plus `CAP_CHOWN` for the mutation call; no `CAP_FOWNER`; no access authority, because the descriptor is already held | E4 completed and the pinned child descriptor is the object this call mutates; the 5.8.2 predicate `st_uid == ORDINARY_UID` holds on that descriptor Canonical predecessors for this effect: E4. | `st_uid == 0`, `S_IMODE == 0o644`, `st_nlink == 1` and an empty attribute set, re-derived and reacquired the same way as E3 | terminal: no reverse ownership call and no mode restoration; the object is removed by the 10.4 state machine through E25 Canonical successors for this effect: E1. |
| E6 | mount-fixture | private mount namespace creation: `unshare(CLONE_NEWNS)` performed by the privileged namespace launcher | the calling process's mount-namespace membership; the kernel creates a new mount-namespace object whose identity is the inode reported at `/proc/self/ns/mnt` | the call acts on the calling process itself and takes no pathname and no caller-supplied target, so the binding is the process identity that performs it, valid for that process and its descendants until namespace exit (10.1) | `CAP_SYS_ADMIN` in the user namespace that owns the current mount namespace (capabilities(7): "employ `CLONE_*` flags that create new namespaces with `clone(2)` and `unshare(2)`"); no access authority is required, because the effect resolves no pathname and touches no object below the invocation root (1.6) | the launcher runs as the reviewed privileged identity via `sudo -n`; the 5.10.2 credential validation is closed before this effect; the preflight recorded `CAP_SYS_ADMIN` from the real `CapEff` (7); this effect occurs only in the `mount-fixture` case, because only that case mounts a filesystem Canonical predecessors for this effect: launcher privilege, 5.10.2. | the launcher is in a new mount namespace whose identity is later measured different from `HOST_MNT_NS_ID`; the launcher's later forked children inherit that membership; no host mount-table entry changes | the namespace object is destroyed by the kernel when its last member process exits; no explicit teardown exists and the closing control is the host-namespace absence control (10.3) Canonical successors for this effect: E7. |
| E7 | mount-fixture | mount propagation brought to private inside the new namespace: `mount(NULL, "/", NULL, MS_REC\|MS_PRIVATE, NULL)` | the propagation type of the mounts in the private namespace's mount tree, rooted at that namespace's `/` | the path `/`, resolved by the launcher inside the namespace created by E6 and never in the host namespace; the binding is valid for the launcher's stay in that namespace and the effect is ordered strictly after E6 and before every fixture mount | `CAP_SYS_ADMIN` (mount(2) is in the `CAP_SYS_ADMIN` set of capabilities(7)); umount(2) states the same requirement for the `MS_REC\|MS_PRIVATE` preparation it prescribes; no access authority is required, because the path `/` is the private namespace's own root, which the reviewed privileged identity may search without a bypass (1.6) | E6 completed and the private namespace identity differs from the host identity; no mount mutation has occurred yet; like E6 this effect occurs only in the `mount-fixture` case Canonical predecessors for this effect: E6. | the real propagation flags of the private namespace are private (10.2 N3), so no later mount or unmount event in it can propagate to the host namespace | propagation is a property of the namespace object and dies with it; no host propagation state is written, and the closing control is the 10.3 absence control Canonical successors for this effect: E8. |
| E8 | mount-fixture | exclusive creation of the mountpoint directory at the frozen role `MOUNTPOINT_ROLE`: `mkdirat(validated_root_fd, MOUNTPOINT_ROLE, 0755)` with no-follow semantics, then pinning it by the helper's own descriptor with its real `st_dev`/`st_ino` recorded (5.9) | the new directory at the frozen role `MOUNTPOINT_ROLE` under the invocation root | the frozen role name resolved once, relative to the helper's own validated root descriptor; a pre-existing object at the role name — file, symlink or directory — fails the exclusive creation instead of being adopted, and the created directory is then pinned by a helper-held `O_PATH` descriptor whose `st_dev`/`st_ino` are recorded and re-derived immediately before the mount. That pinned descriptor is retained for the **covered** mountpoint's identity only and is never used as the mounted root after E18 (5.9, 1.8.5) | no `CAP_SYS_ADMIN`, no `CAP_CHOWN` and no ownership call: the create is a directory-entry write in a directory the helper does not own, so it requires `CAP_DAC_OVERRIDE`, the single directory authority that bypasses the write and the search check on the containing directory in one capability (capabilities(7): "bypass file read, write, and execute permission checks"); no `CAP_DAC_READ_SEARCH`, because this effect reads no directory contents and its separate `CAP_DAC_READ_SEARCH` requirement is withdrawn by round 8 and is not restored by round 10 (1.8.8, 1.10.4) | 5.3 root validation passed; no object exists at `MOUNTPOINT_ROLE`; the helper access authority is present in the real `CapEff` recorded by the preflight (7); the creation-time `umask` cannot clear bits from the requested `0755` Canonical predecessors for this effect: E7. | exactly one real directory exists at `MOUNTPOINT_ROLE`, owned by the creating identity, with `S_IMODE == 0o755` exactly, group and world write clear, and recorded `st_dev`/`st_ino`; the ordinary identity can search it, which is what makes the 5.8.3 ordinary `O_RDONLY` witness reachable through it; no pre-existing object was adopted, removed or repaired | removed by E24 in the 10.4 order after the mount and the loop backing are released; a refused or failed creation is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy, never a pass Canonical successors for this effect: E24. |
| E9 | mount-fixture | exclusive creation of the fixture image as a regular file at `IMAGE_ROLE` (`openat(validated_root_fd, IMAGE_ROLE, O_CREAT\|O_EXCL\|O_RDWR\|O_NOFOLLOW\|O_CLOEXEC, 0600)`), then the frozen size set with `ftruncate` on the pinned descriptor; no mode-changing call after creation | the new regular file at the frozen role `IMAGE_ROLE` under the invocation root | the frozen role name resolved once, relative to the helper's own validated root descriptor with no-follow semantics; `O_EXCL` makes a pre-existing object a refusal rather than an adoption, and `O_EXCL` with `O_CREAT` means a symlink at the name fails the call regardless of where it points (open(2)); the created file is then pinned by the helper's own `O_RDWR` descriptor and its `st_dev`/`st_ino` recorded (5.9) | no `CAP_SYS_ADMIN`, no `CAP_CHOWN` and no ownership call: creation assigns the creating identity's own uid, and `ftruncate` acts on the descriptor the helper holds. The create is a directory-entry write in a directory the helper does not own, so it requires `CAP_DAC_OVERRIDE`, which bypasses both the write and the search check on the containing directory; no `CAP_DAC_READ_SEARCH`, whose separate requirement for this effect is withdrawn by round 8 and is not restored by round 10 (1.8.8, 1.10.4) | 5.3 root validation passed; no object exists at `IMAGE_ROLE`; the helper access authority is present in the real `CapEff` recorded by the preflight (7); the helper's effective uid is the reviewed privileged identity Canonical predecessors for this effect: E8. | exactly one regular single-link file exists at `IMAGE_ROLE`, owned by the reviewed helper identity, with `S_IMODE == 0o600` exactly and owner-write set, size exactly `IMAGE_ROLE_SIZE_BYTES`, and recorded `st_dev`/`st_ino`; the mode was established by creation and never by a `chmod` or `fchmod`; no pre-existing object was adopted, removed or repaired | removed by E24 under the 10.4 state machine; a refused or failed creation is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy, never a pass Canonical successors for this effect: E10. |
| E10 | mount-fixture | ext4 formatting effect: the external `mke2fs`/`mkfs.ext4` writes a filesystem into the image through a dedicated, `FD_CLOEXEC`-cleared formatter descriptor derived from the pinned E9 descriptor, with that descriptor's own `/proc/self/fd/<N>` pathname as the device argument, under the frozen invocation of 1.10.6 (5.9, 1.8.6) | the contents of the image file created by E9 | the formatter receives the derived descriptor number N and writes the image through the kernel's `/proc/self/fd/N` magic-link resolution of its own descriptor table, so the tool is bound to the exact inode E9 created and pinned; the tool never receives the ordinary `IMAGE_ROLE` role pathname and never re-resolves it | **none**: the formatter child never traverses the invocation root. Its device argument is its own `/proc/self/fd/<formatter_fd_number>` and the magic link is resolved in the child's own descriptor table against the open file description `dup(2)` carried across the `execve`, so no component of the ordinary-owner invocation root is resolved and no below-root traversal authority is declared for an operation that performs no traversal (open(2), "Open file descriptions"; 1.10.4); the write and the formatter's own `fchmod`-equivalent operations use the image's own owner-write bit from the frozen `IMAGE_ROLE_S_IMODE=0600`, because the reviewed privileged identity owns the image, so no `CAP_DAC_OVERRIDE`, no `CAP_DAC_READ_SEARCH`, no `CAP_FOWNER`, no `CAP_SYS_ADMIN` and no loop device (1.8.6, 1.8.8, 1.10.6) | E9 completed; the image identity is re-derived equal to the pinned identity; the image is a single-link regular file owned by the reviewed helper identity with owner-write set and exactly `IMAGE_ROLE_SIZE_BYTES`; `mke2fs` is present and recorded; the image is neither mounted nor loop-bound at formatting time; the derived formatter descriptor exists, has `FD_CLOEXEC` cleared, is present in the formatter child's frozen descriptor allowlist, and is the only non-standard descriptor the formatter child inherits (1.10.6) Canonical predecessors for this effect: E9. | the image contains an ext4 filesystem whose own root directory satisfies the E19 creation preconditions, verified in this effect by reading the superblock magic `0xEF53` at image offset 1080 from the pinned E9 descriptor; the image inode identity, mode, owner and link count are unchanged by the format; the formatter descriptor is closed before this row completes; no `chmod` or `fchmod` follows it The recorded result is consumed by E11. | the formatted image is removed by E24; a formatting failure is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy, never a pass Canonical successors for this effect: E11. |
| E11 | mount-fixture | post-format image identity and superblock verification: `fstat` on the pinned E9 descriptor, then a read of the ext4 superblock magic at image offset 1080 from that same descriptor, then confirmation that no loop device is associated with the image; no mutation | the image file created and pinned by E9 and formatted by E10 | the pinned E9 descriptor itself: the verification reads the descriptor the helper already holds, so no role pathname is re-resolved and no new object reference is created; the offset is a frozen literal of the on-disk ext4 layout | no capability and no access authority: the descriptor is already held and the read uses the image's own owner-read bit from `IMAGE_ROLE_S_IMODE=0600`; no pathname is resolved (1.6) | E10 completed and the formatter descriptor is closed; the image identity is still the identity E9 pinned Canonical predecessors for this effect: E10. | the image inode identity, mode, owner and link count are unchanged by the format, the two bytes at image offset 1080 are `0x53 0xEF` (the little-endian ext4 superblock magic `0xEF53`), and the image is not yet loop-bound; this is the verification E14 depends on and it is deliberately separate from the loop configuration of E12, which claims no read-back The recorded result is consumed by E12. | terminal for the verification: the recorded result is consumed by E12 and E14; a non-matching magic or a changed inode identity is a hard refusal before the loop is configured, classified by the 5.7 origin taxonomy and never a pass Canonical successors for this effect: E12. |
| E12 | mount-fixture | loop backing acquisition and configuration, descriptor-mediated: `open("/dev/loop-control", O_RDWR)` then `ioctl(LOOP_CTL_GET_FREE)` to select the device number, then `open("/dev/loopN", O_RDWR)` and `ioctl(LOOP_CONFIGURE)` with the pinned `IMAGE_ROLE` descriptor passed as the backing file descriptor; no pathname-based tool may perform this effect | the loop device taken by the helper and its association with the pinned image inode | the backing file descriptor is the one the helper itself opened and pinned on `IMAGE_ROLE` in E9, and the ioctl takes that descriptor as an argument, so the association is descriptor-mediated and the role path is never re-resolved between the pin and the association; the device number, the device path and the recorded backing `st_dev`/`st_ino` are helper-internal state | `CAP_SYS_ADMIN` for the privileged block-device control and configuration ioctls (capabilities(7): CAP_SYS_ADMIN includes "perform various privileged block-device ioctl(2) operations"); no access authority, because the effect consumes the already-pinned `IMAGE_ROLE` descriptor from E9 and the recorded device node path and re-resolves no role pathname under the invocation root (1.8.8); no ownership capability | E7 and E8 completed, so the private namespace exists and the mountpoint the loop-backed mount will target exists and is pinned; E9's image exists and is pinned and E10's format completed, with E11's verification passed; the image identity is re-derived equal to the pinned creation identity; `/dev/loop-control` and the loop device nodes exist and are recorded by the preflight (7); the image is a single-link regular file owned by the reviewed helper identity with owner-write set Canonical predecessors for this effect: E11. | exactly one recorded loop device is **configured** with the pinned image inode as its backing file, with the device number, device path and backing identity recorded as helper-internal state; this row deliberately claims no read-back verification, which is E13's own postcondition and not this row's The recorded result is consumed by E13. | released by E17 in the 10.4 order; `LOOP_BACKING_RESIDUE=false` is the closing control; a failed acquisition is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy Canonical successors for this effect: E13. |
| E13 | mount-fixture | loop-device access and read-back verification: `open(recorded_loop_device_path, O_RDWR)` then `ioctl(LOOP_GET_STATUS64)` to re-read the device's real backing identity; no mutation | the loop device recorded by E12 and its real association with the pinned image inode | the device number and device path are helper-internal state recorded at acquisition by E12, never caller text and never a fresh scan; the read-back is bound to the recorded device and compared against the pinned image `st_dev`/`st_ino` from E9 | `CAP_SYS_ADMIN` for the privileged block-device ioctls (capabilities(7)); no access authority is required, because the effect resolves no path below the invocation root (1.6) | E12 completed and the device number and path were recorded; the pinned image identity was recorded at E9 and verified at E11; this effect is ordered strictly after E12, and the mount that consumes its result is ordered strictly after it Canonical predecessors for this effect: E12. | the device's real backing identity is observed equal to the pinned image identity, so the mount source E14 will consume is the helper's own image rather than a substituted object; the verification result is the precondition E14 depends on The recorded result is consumed by E14. | terminal for the access: the descriptor is closed before E17's release, because a loop device with an open reference is not releasable; a mismatch is a hard refusal before the mount and a non-pass fixture-construction failure classified by the 5.7 origin taxonomy Canonical successors for this effect: E14. |
| E14 | mount-fixture | mount fixture: `mount(loop_device, MOUNTPOINT_ROLE, "ext4", flags, options)` inside the private namespace | the private namespace's mount table entry, and the ext4 filesystem instance carried by the loop device, covering the helper-created `MOUNTPOINT_ROLE` directory | `mount(2)` is a pathname operation with no descriptor form (5.9), so the target is bound by helper-exclusive creation plus pre-mount identity revalidation: the frozen `MOUNTPOINT_ROLE` created and pinned by E8, resolved relative to the helper's own validated root descriptor, its pinned `st_dev`/`st_ino` re-derived immediately before the call, still a real directory with no symlinked component in its resolution path, with the helper's own **E13-verified** loop device as the source and no caller-created source or target ever accepted; the binding window is the interval between that revalidation and the call, inside the private namespace | `CAP_SYS_ADMIN` (capabilities(7) lists mount(2) in that set), plus `CAP_DAC_READ_SEARCH` for the single search (execute) check the resolution of `MOUNTPOINT_ROLE` performs on the owner-only invocation root — the mount target is a pathname and `mount(2)` performs no write check on the containing directory, so the traversal-only capability is the minimal one and `CAP_DAC_OVERRIDE` is not declared (1.10.4); no ownership capability | E7, E8, E9, E10, E11 and E12 completed; **E13 completed and its loop read-back verification passed**, so the device about to be mounted is known to be the helper's own image; target identity re-derived equal to the identity E8 pinned; the device appears in no other private-namespace record (section 9 exactly-once rule); private propagation confirmed private before the mount Canonical predecessors for this effect: E13. | exactly one private-namespace record carries the new mount, with root field `/` and filesystem type `ext4`; the evidence process shares the namespace and can reach the mount-case file; the host mount table is unchanged | leaves `ATTACHED` through E15 (`detach-fixture`) or through E16 (failure before drift); the terminal states are the 10.4 `RELEASED` and `CLEANUP_FAILED` Canonical successors for this effect: E15, E16. |
| E15 | mount-fixture | `MNT_DETACH` detach: `umount2(MOUNTPOINT_ROLE, MNT_DETACH)` inside the private namespace | the fixture mount in the private namespace's mount table | the frozen `MOUNTPOINT_ROLE` resolved relative to the helper's validated root descriptor inside the private namespace, valid only while that mount is still attached and reachable at that path — the same object the pre-drift positive admission and the section 8 steps 5-7 controls reference, and the same object E8 created and pinned; no caller path participates | `CAP_SYS_ADMIN` (umount(2): "Appropriate privilege (Linux: the `CAP_SYS_ADMIN` capability) is required to unmount filesystems"), plus `CAP_DAC_READ_SEARCH` for the single search (execute) check `umount2(2)` performs while resolving `MOUNTPOINT_ROLE` against the owner-only invocation root; `umount2(2)` writes no directory entry there, so the traversal-only capability is the minimal one and `CAP_DAC_OVERRIDE` is not declared for this effect (1.10.4) | the mount state is observed `ATTACHED`; E21 completed, so the non-root evidence process holds its own retained descriptor on the mount-case fixture file and observed the real positive pre-drift production admission of section 8 step 2, because the detach is the `detach-fixture` action of 5.2 requested by that same live process after the positive case (10.1) Canonical predecessors for this effect: E14, E21. | mount state `DETACHED_BUSY`: the mount is immediately disconnected from the private mount table while the unmount completes when the mount ceases to be busy (umount(2) `MNT_DETACH`), so the retained descriptor keeps it alive and a second unmount has no object to act on The recorded result is consumed by E22. | advances to `RELEASED` only after E22 completes, E23 closes every retained fixture descriptor, and the private mount table shows zero records for the held mount id (10.4); never retried blindly, and `SECOND_UNMOUNT_AFTER_MNT_DETACH_REQUIRED=false` Canonical successors for this effect: E22. |
| E16 | mount-fixture | `ATTACHED`-state ordinary cleanup unmount: `umount2(MOUNTPOINT_ROLE, 0)`, performed only in the observed `ATTACHED` state | the fixture mount in the private namespace, still attached because no successful `MNT_DETACH` occurred | the frozen `MOUNTPOINT_ROLE` resolved relative to the helper's validated root descriptor, valid only while the observed state is `ATTACHED`; the state is measured before the effect and in any other state this effect does not occur at all | `CAP_SYS_ADMIN` (umount(2)), plus `CAP_DAC_READ_SEARCH` for the single search (execute) check the ordinary `umount2(MOUNTPOINT_ROLE, 0)` performs while resolving the frozen role name against the owner-only invocation root — no directory entry is written there, so the traversal-only capability is the minimal one (1.10.4); no ownership capability | cleanup entered with the observed state `ATTACHED` — failure before drift, or the detach not attempted — and no successful `MNT_DETACH` has occurred; a retained evidence descriptor opened by E21 must have been released by E23 first, because a mount with an open reference is busy and an ordinary unmount of it would fail Canonical predecessors for this effect: E14, and E23 when a retained evidence descriptor is still open. | the fixture mount is gone from the private mount table and the loop backing becomes releasable; the state machine advances to release and removal The recorded result is consumed by E17. | followed by E17, E24 and E26 in that order; `PRIVATE_MOUNT_RESIDUE=false` is the closing control; a failure is `CLEANUP_FAILED`, visible and never retried blindly Canonical successors for this effect: E17. |
| E17 | mount-fixture | loop backing release: the loop device is detached from the image (`LOOP_CLR_FD`, equivalently `losetup -d` acting on the recorded device) | the loop device acquired by E12 and its association with the pinned image inode | the device number recorded at acquisition, held as helper-internal state and never taken from caller text or from a fresh pathname scan; the release acts on the recorded device and the device's real state is re-read afterwards rather than inferred | `CAP_SYS_ADMIN` for privileged block-device ioctls (capabilities(7)); no access authority is required, because the release acts on the recorded loop device and resolves no path below the invocation root (1.6); no ownership capability and no ownership call | the observed state is `DETACHED_BUSY`, or the `ATTACHED` path has completed through E16; every retained fixture descriptor is closed **and the helper's own image, formatter and loop descriptors are closed in this same invocation**, because a loop device with an open reference is not releasable and an early attempt would report a false failure and invite a blind retry (10.4) Canonical predecessors for this effect: E23, and E16 in the `ATTACHED` branch. | no loop device is associated with the image; `LOOP_BACKING_RESIDUE=false`, measured rather than asserted, which also allows for the lazy device destruction losetup(8) documents instead of assuming immediate removal The recorded result is consumed by E24. | terminal for the effect; E24 and E26 follow; a failure is `CLEANUP_FAILED` with the residual device recorded as diagnostics Canonical successors for this effect: E24. |
| E18 | mount-fixture | post-mount mounted-root acquisition and representation proof: `openat(validated_root_fd, MOUNTPOINT_ROLE, O_RDONLY\|O_DIRECTORY\|O_NOFOLLOW\|O_CLOEXEC)` performed **after** E15 attached the mount, then immediate proof that the opened object represents the expected mounted ext4 filesystem (5.9, 1.8.4) | the mounted ext4 filesystem's root directory, reached through the `MOUNTPOINT_ROLE` name as it resolves **after** the mount | the frozen role name resolved post-mount against the helper's validated root descriptor, because the covered `MOUNTPOINT_ROLE` inode E8 pinned is no longer reachable at that name once the mount covers it; the acquired descriptor is bound to the filesystem by three measured equalities — `fstatfs(2)` reports the ext4 superblock magic `0xEF53` on the descriptor, `fstat(2)` reports a different `st_dev` from the invocation root's filesystem, and the descriptor's `st_dev`/`st_ino` are recorded as the mounted-root identity. The binding window is the interval between the open and those three measurements, and the descriptor becomes `mounted_root_fd` only when all three hold | no `CAP_SYS_ADMIN` and no `CAP_CHOWN`: this effect neither mounts nor mutates. The lookup is a single trailing-component resolution against the already-held validated root descriptor, so it performs exactly one search (execute) check on the owner-only invocation root and one read check on the `MOUNTPOINT_ROLE` directory the helper itself created `0755`, which its own owner bits already satisfy; the minimal capability for the search check it fails is `CAP_DAC_READ_SEARCH`, and only that — `CAP_DAC_OVERRIDE` is not declared, because the effect writes and removes no directory entry (1.10.4) | E14 completed and the mount attached; the `MOUNTPOINT_ROLE` descriptor E8 pinned is still held, and the implementation MUST also observe that its `st_dev`/`st_ino` no longer equal what a fresh resolution of the same name reports, which is the positive evidence that a mount now covers it Canonical predecessors for this effect: E14. | `mounted_root_fd` exists, `fstatfs` on it reports the ext4 superblock magic, its `st_dev` differs from the invocation root's filesystem, and its `st_dev`/`st_ino` are recorded as the mounted-root identity that E19's preconditions and E21's evidence depend on; the pre-mount `MOUNTPOINT_ROLE` descriptor is retained only as the covered mountpoint's identity The recorded result is consumed by E19. | terminal for the acquisition: the descriptor is held until the mount-case file is created and pinned, and is closed before the mount is released; a mismatch — not a directory, wrong filesystem magic, same `st_dev` as the invocation root, or a resolution that does not differ from the pinned covered inode — is a hard refusal before any mount-case child is created, classified as `QUALIFICATION_GAP` with a design finding and never as `HELPER_ROOT_REJECTED`, never a pass, and never repaired with privilege Canonical successors for this effect: E19. |
| E19 | mount-fixture | mounted-directory pre-state authorisation for the mount-case child: the owner, mode and ordinary-identity search facts of `mounted_root_fd` are observed and recorded, and the preconditions the mount-case file creation depends on are established as measured facts; no mutation | the mounted ext4 filesystem's root directory, as acquired and proved by E18 | The descriptor E18 acquired and bound by the three measured equalities; no pathname is resolved by this effect at all, and no component is re-resolved after E18's proof | no capability and no access authority: the effect mutates nothing and resolves no pathname, because it consumes the `mounted_root_fd` E18 already holds (1.6) | E18 completed and `mounted_root_fd` is bound to the expected mounted ext4 filesystem Canonical predecessors for this effect: E18. | the mounted root's owner is the reviewed privileged identity with owner write and search set, its real mode is recorded, and the ordinary identity's search through `MOUNTPOINT_ROLE` and the mounted root is established as a measured fact, which is the precondition of the 5.8.3 ordinary `O_RDONLY` witness; a failure here is `QUALIFICATION_GAP` plus a design finding, never a pass and never a privilege repair The recorded result is consumed by E20. | terminal for the observation: the recorded facts are consumed by E20; the descriptor itself is closed before the mount is released Canonical successors for this effect: E20. |
| E20 | mount-fixture | mount-case fixture file creation, the single helper-side exclusive creation at the frozen role path `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE`: `openat(mounted_root_fd, FIXTURE_FILE_ROLE, O_CREAT\|O_EXCL\|O_RDONLY\|O_NOFOLLOW\|O_CLOEXEC, 0644)` inside the mounted ext4 filesystem, then pinning it by the helper's own descriptor | the new regular file at the frozen role path inside the mounted ext4 filesystem, which is also the retained object of section 9 | the frozen role name created relative to the `mounted_root_fd` descriptor E18 acquired and E19 measured — never relative to the pre-mount `MOUNTPOINT_ROLE` descriptor and never at a re-resolved role path; a pre-existing object at the name fails the exclusive creation instead of being adopted; the created file is pinned by the helper's own descriptor with its real `st_dev`/`st_ino` recorded, and every later check is an `fstat` on that descriptor (5.8.1, 5.8.3) | no `CAP_CHOWN`, no `CAP_SYS_ADMIN` and no ownership or mode call: creation assigns the creating identity's own uid, which is the frozen `st_uid == 0` of 5.8.3, and the create is authorized by the owner write and search bits of the mounted root directory the reviewed privileged identity owns, which E19 observed; **none**: this effect writes one entry inside a directory the helper owns, so its own owner bits authorize both the write and the search check, and the mounted-root descriptor is already held, so no capability and no access authority are required (1.10.4) | E19 completed and the mounted root's owner, mode and ordinary search authorisation are observed facts; the creation-time `umask` cannot clear bits from the requested `0644`; no object exists at the role name; this is the only creation effect for this object (1.8.2) Canonical predecessors for this effect: E19. | exactly one regular single-link file exists at the frozen role path, owned by uid 0, with `S_IMODE == 0o644`, and the helper's `fstat` facts satisfy the 5.8.1 common structural requirements plus the 5.8.3 `st_uid == 0` predicate; the ordinary evidence process can open it `O_RDONLY` with no capability The recorded result is consumed by E21. | removed with the image by E24, because the file lives inside the image's filesystem; the mount-case `FIXTURE_FILE_ROLE` has no separate removal effect and needs none, and the 5.8.3 after-creation failure contract governs a child that is absent or non-conforming; a failed creation is a non-pass fixture-construction failure classified by the 5.7 origin taxonomy Canonical successors for this effect: E21. |
| E21 | all cases (run-scoped, evidence side) | non-root evidence-side acquisition and positive production observation: `NONROOT_EVIDENCE_PROCESS` opens the fixture object `O_RDONLY\|O_NOFOLLOW\|O_CLOEXEC` with no capability, independently reacquires the object's real state, retains the descriptor, and calls the production primitive for the case's positive admission — the owner-policy admission for the ownership cases and the pre-drift positive admission of section 8 step 2 for `mount-fixture` | the ordinary process's descriptor on the fixture object: the `FIXTURE_FILE_ROLE` file the ownership setup mutated for `own-foreign` and `own-root`, and `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE` inside the mounted ext4 filesystem for `mount-fixture` | the ordinary process opens the object itself after `ACTUAL_EUID`, `ACTUAL_EGID`, `ACTUAL_SUPPLEMENTARY_GROUPS`, `ACTUAL_CAP_PRM`, `ACTUAL_CAP_EFF`, `ACTUAL_CAP_AMB` and `ACTUAL_SECUREBITS` are reacquired and required by 5.10.4, so the binding is that process's own descriptor and no privileged pathname resolution participates; for `mount-fixture` the ordinary process reaches the file through the `0755` `MOUNTPOINT_ROLE` E8 created and the mounted root E18 proved and E19 measured, and the descriptor it retains is the one the detach evidence of section 8 steps 5-7 depends on | **none**: the effect is performed by the non-root evidence process, whose `CapPrm`, `CapEff` and `CapAmb` are all required `0` before the primitive executes (5.10.4), so this row declares no capability and no access authority — it is in the table because it is a material lifecycle effect with a real target, a real binding, real preconditions, real postconditions and a real terminal transition, not because it is privileged (1.8.3) | the ownership setup has finished for `own-foreign` and `own-root`, so the file the setup mutated exists at the frozen role name and satisfies E3/E5's postcondition; for `mount-fixture` E20 completed, so the mount-case child exists at the frozen role path and satisfies the 5.8.1 common structural requirements plus the 5.8.3 `st_uid == 0` predicate; the evidence process has reacquired and required its own identity, group list, capability sets and securebits by 5.10.4; the 4.3 paired controls for the ownership cases are recorded before the production call Canonical predecessors for this effect: E1, which is the credential transition that created this process, and the case's own fixture setup: E3 for `own-foreign`, E5 for `own-root`, E20 for `mount-fixture`. | the ordinary `O_RDONLY` open succeeded as a real DAC fact rather than as a capability artifact, the observed state was reacquired by the ordinary process itself, the case's positive production admission was observed, and the descriptor is retained and still valid — `fstat` succeeds and the device, inode and retained bytes are unchanged The recorded result is consumed by E15 in the `mount-fixture` detach path and then by E22, and directly by E23 in every other path. | the descriptor stays open across the detach: for `mount-fixture` it is handed to E22, which is the post-detach observation that depends on it being open, and only then to E23, which is the effect that owns its release; for the ownership cases it is handed directly to E23. A failed open or a failed positive admission is a `QUALIFICATION_GAP` and a fixture-construction failure, never evidence and never a `PRODUCT_FAILURE` Canonical successors for this effect: E15, E23. |
| E22 | mount-fixture (successful drift path) | post-detach production observation, the material evidence operation of the successful RQP-L17 path: with the retained descriptor still open and after `E15` detached the mount, `NONROOT_EVIDENCE_PROCESS` confirms the descriptor is still live (`fstat(2)` succeeds and the device, inode and retained bytes are unchanged), re-reads `_mount_id(fd)` under `statx` and requires the same nonzero mount id as the pre-detach admission, confirms from real `/proc/self/mountinfo` that zero records carry the held mount id, and then calls the production primitive a **second** time, requiring exactly `reason_code=PLATFORM_UNQUALIFIED` with detail `held mount missing or ambiguous` | the retained descriptor E21 acquired, the held mount id, and the real private-namespace mount table | the descriptor is the one the non-root evidence process opened and retained itself — it is never closed, never reopened by path, and never re-resolved; the mount table is read from the helper-free private namespace the evidence process shares; the second primitive call consumes that same real mount table | **none**: the effect is performed by the non-root evidence process, whose `CapPrm`, `CapEff` and `CapAmb` are all required `0`, so this row declares no capability and no access authority — it is in the table because it is the material evidence operation the RQP-L17 case turns on, not because it is privileged | `E15` completed and the mount state is `DETACHED_BUSY`; the retained descriptor is open and was admitted once by the production primitive before the detach (the section 8 step 2 positive admission); the held mount id is recorded from that admission Canonical predecessors for this effect: E15, E21. | the descriptor is observed still valid, the `statx` mount id is unchanged, the private mount table shows zero records for the held mount id, and the second primitive call is observed failing with exactly `PLATFORM_UNQUALIFIED: held mount missing or ambiguous`; an observed L105 `UNSAFE_PATH` failure instead is a `QUALIFICATION_GAP` plus a design finding against this document, never a pass The recorded result is consumed by E23. | terminal for the observation: it hands the still-open descriptor to E23, which is the effect that owns its release; the descriptor is the detach evidence of section 8 step 5, and it MUST still be open during this whole probe Canonical successors for this effect: E23. |
| E23 | all cases (run-scoped, evidence side) | non-root evidence-side descriptor release: `NONROOT_EVIDENCE_PROCESS` closes the descriptor the acquisition opened and retained — for `mount-fixture` only after E22's post-detach observation has completed; no privilege and no mutation of any object | the retained descriptor from the evidence acquisition, and for `mount-fixture` the held mount it keeps alive | the descriptor the evidence process opened and retained; no pathname is resolved, and the release is bound to that descriptor rather than to a name | **none**: the effect is performed by the non-root evidence process with `CapPrm`, `CapEff` and `CapAmb` all `0`, and a close is not a privileged operation | the case's evidence work has finished: for `mount-fixture` that is E22's completed post-detach observation with its exact `PLATFORM_UNQUALIFIED` result, and for the ownership cases it is the completed production observation; no further measurement depends on the retained descriptor Canonical predecessors for this effect: E21, and E22 in the `mount-fixture` successful path. | the descriptor is closed, so for `mount-fixture` the mount it kept alive is no longer busy and `PRIVATE_MOUNT_RESIDUE=false` becomes reachable; the loop backing becomes releasable and `LOOP_BACKING_RESIDUE` can be driven to false The recorded result is consumed by the branch's next effect: E16 when the mount is still `ATTACHED`, E17 in the `DETACHED_BUSY` path, and E25 in the ownership cases. | terminal: E17 may now release the loop backing, E16 performs the `ATTACHED`-branch unmount when the mount is still attached, and E24, E25 and E26 then remove the fixture objects and the invocation root; a failure is `CLEANUP_FAILED` with the residual state recorded and never retried blindly Canonical successors for this effect: E16, E17, E25. |
| E24 | mount-fixture | mount-object removal: `unlinkat(validated_root_fd, MOUNTPOINT_ROLE, AT_REMOVEDIR)` followed by `unlinkat(validated_root_fd, IMAGE_ROLE, 0)`, with no recursive and no forced removal | the mountpoint directory E8 created and pinned, and the image file E9 created and E10 formatted | each frozen role name resolved relative to the helper's own validated root descriptor with no-follow semantics, with the observed object re-derived before removal as the identity that was pinned — E8's directory identity for the mountpoint and E9's file identity for the image — so a substituted object is never a removal target | no `CAP_SYS_ADMIN`, no ownership capability and no ownership call; the directory-write authority `CAP_DAC_OVERRIDE` is required, because both entries are removed from the invocation root the ordinary runner owns and the same capability also bypasses the search check on it (1.6); the invocation root's sticky bit is clear by 4.2, so no `CAP_FOWNER` is required or declared; no `CAP_DAC_READ_SEARCH`, because the effect removes names and reads no directory contents | E17 completed and the observed state is `RELEASED`, so no mount and no loop association remains; the evidence-side descriptor opened by E21 has been closed by E23, which is the effect that owns its release; the mountpoint is empty, because the mount-case fixture file lives inside the mounted ext4 filesystem and not in this directory; both observed objects are the identities E8 and E9 pinned Canonical predecessors for this effect: E17. | neither the mountpoint directory nor the image file exists, and no object outside them was touched; `MOUNTPOINT_ROLE_CLEANUP_EFFECT=E24` and the image-removal half of `FIXTURE_ROOT_RESIDUE` are satisfied The recorded result is consumed by E26. | terminal for the effect: E26 may now occur and is its next removal step; a failure is `CLEANUP_FAILED` with the residual path recorded and never retried blindly Canonical successors for this effect: E26. |
| E25 | own-foreign, own-root | fixture-object removal, exactly one removal per ownership case: `unlinkat(validated_root_fd, FIXTURE_FILE_ROLE, 0)`. The `mount-fixture` case has **no** effect under this id and performs no removal here at all, because both of its fixture objects are removed by E24, which is the only owner of those two names | the `FIXTURE_FILE_ROLE` child the ownership setup mutated | the frozen derived role name resolved relative to the helper's own validated root descriptor with no-follow semantics, with the observed object's `st_dev`/`st_ino` re-derived immediately before the removal and required to equal the identity pinned before the mutation, so a substituted object is never a removal target; `unlinkat` removes the name itself and never a symlink target, and the binding window is that revalidation plus the single removal call | no `CAP_SYS_ADMIN`, no ownership capability and no ownership call, because removing an object never depends on the removed object's owner; resolving the frozen role name performs one search (execute) check on the invocation root and the removal performs one write check on the same directory, and the single directory capability that bypasses both is `CAP_DAC_OVERRIDE` (capabilities(7): "bypass file read, write, and execute permission checks"), so `CAP_DAC_READ_SEARCH` is deliberately not declared for the same traversal check (1.10.4); the invocation root's sticky bit is clear by 4.2, so no `CAP_FOWNER` is required or declared | the production observation of the evidence process has finished and E23 has released the retained descriptor, so no evidence depends on the object, and no repair, re-ownership or mode change has been performed on it Canonical predecessors for this effect: E23. | the `FIXTURE_FILE_ROLE` child is absent from the invocation root, so the ownership case's root is empty and E26's removal precondition is reachable; the ownership the setup produced was never changed back, and a removal that had to restore ownership first would be an undeclared second `fchown` The recorded result is consumed by E26. | terminal for the effect: E26 may now occur and is the last removal step in the ownership cases; a failure is `CLEANUP_FAILED` with the residual path recorded and never retried blindly Canonical successors for this effect: E26. |
| E26 | all cases (run-scoped) | invocation-root removal: `unlinkat(RUNNER_TEMP_fd, invocation_root_name, AT_REMOVEDIR)` — the removal of a directory entry from the invocation root's **parent**, after every fixture object inside the root is gone | the invocation root directory the ordinary process created under `RUNNER_TEMP` — **not** an object below that root | the same real path the helper validated under 5.3, re-derived; the removal acts on the parent directory's entry, requires the observed directory to be that validated root and to be empty, and never targets a repository, worktree, cache, runtime-data or pre-existing host path; the parent is reached through a descriptor the helper opened on `RUNNER_TEMP` and validated as the real parent of the validated root, so the root's own name is not re-resolved from caller text | no `CAP_SYS_ADMIN` and no ownership capability; exactly one directory capability is required and it is unconditional. The below-root half — the `O_RDONLY\|O_DIRECTORY` open and read of the root used to observe its emptiness — performs a read and a search (execute) check on a directory that is frozen `S_IMODE == 0o700` and owned by the ordinary runner (4.2), so the helper's direct DAC check on it fails by construction; the parent-removal half — `unlinkat(RUNNER_TEMP_fd, invocation_root_name, AT_REMOVEDIR)` — performs a search check and a write check on `RUNNER_TEMP`, which the helper identity does not own, and 7 requires the preflight to observe that the parent withholds write from it, so an entry removal there always needs the bypass too. `CAP_DAC_OVERRIDE` is the single capability that bypasses the read, write and execute checks of a directory (capabilities(7): "bypass file read, write, and execute permission checks"; generic_permission's directory branch in Linux `fs/namei.c` returns success for `CAP_DAC_OVERRIDE` on any directory mask), so it covers both halves of this one row and is the minimal single capability for it; `CAP_DAC_READ_SEARCH` is therefore not declared as well, and this row is canonical without splitting the observation from the removal (1.10.4). `CAP_FOWNER` is neither declared nor needed because the parent is required not to be sticky: removing a directory owned by another identity from a sticky directory would need `CAP_FOWNER` (capabilities(7): "ignore directory sticky bit on file deletion"), so a sticky parent is a preflight failure yielding `QUALIFICATION_GAP` rather than an undeclared authority | every other fixture object under the root has been removed, so the root is empty; the observed directory is the validated root identity; the parent directory is the validated real parent and is not sticky, as a preflight fact (7); the `RUNNER_TEMP` owner, mode, write-and-search DAC relation and sticky-bit state are the four observed facts of 1.7.7 and 7, and the observed relation is required to deny the helper identity direct write so that this row's authority is unconditional Canonical predecessors for this effect: E24 for `mount-fixture`, E25 for `own-foreign` and `own-root`. | `FIXTURE_ROOT_RESIDUE=false`, measured; the invocation root no longer exists and its parent is unchanged apart from the removed entry; this is the case's last removal step and the closing effect of the fixture-root residue control | terminal; a failure is `CLEANUP_FAILED` with the residual path recorded, never retried blindly and never a pass |

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
implicit. First, the helper's own pathname and object access under the invocation
root requires a DAC authority, because the root is owner-only
(`S_IMODE == 0o700`) and owned by the ordinary runner while the helper is not its
owner; a world-traversable root would avoid that authority, but it would let an
unrelated local user reach objects at the frozen role names, which is the
substitution the confinement rules exist to prevent. That authority is
**required**, and round 6 derives it per effect instead of declaring one blanket
capability: an effect that only has to resolve a name through the root needs
`CAP_DAC_READ_SEARCH` (capabilities(7): "bypass file read permission checks and
directory read and execute permission checks"), while an effect that must write a
directory entry — create, `unlink` or `rmdir` — also needs write permission on
that directory and therefore `CAP_DAC_OVERRIDE` (capabilities(7): "bypass file
read, write, and execute permission checks"). Neither authority is evidence and
neither is available to the evidence process; that is an attribution fact, not a
reason to call either one unnecessary:

```text
INVOCATION_ROOT_MODE_IS_OWNER_ONLY=true
INVOCATION_ROOT_S_IMODE_REQUIRED=0700
INVOCATION_ROOT_GROUP_AND_WORLD_BITS_CLEAR=true
INVOCATION_ROOT_STICKY_BIT_CLEAR=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY=CAP_DAC_OVERRIDE
PRIVILEGED_HELPER_ACCESS_AUTHORITY_IS_A_ROUND5_RECORD=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY_SUPERSEDED_BY_ROUND6=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY_EFFECTS_IS_A_ROUND5_RECORD=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY_EFFECTS_INCOMPLETE_IN_ROUND5=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY_EFFECTS_SUPERSEDED_BY=ACCESS_AUTHORITY_EFFECT_SET
ROUND5_CAP_DAC_OVERRIDE_NOT_REQUIRED_CLAIMS_WITHDRAWN_BY_ROUND6=true
PRIVILEGED_HELPER_ACCESS_AUTHORITIES=CAP_DAC_READ_SEARCH,CAP_DAC_OVERRIDE
PRIVILEGED_HELPER_ACCESS_AUTHORITY_REQUIRED=true
PRIVILEGED_HELPER_ACCESS_AUTHORITY_SCOPE=helper_pathname_and_object_access_below_the_validated_invocation_root
BELOW_ROOT_ACCESS_AUTHORITY_SCOPE=every_object_at_a_frozen_role_name_under_the_validated_invocation_root
ROOT_PARENT_REMOVAL_ACCESS_AUTHORITY_SCOPE=RUNNER_TEMP_the_validated_invocation_roots_parent_directory
PRIVILEGED_HELPER_ACCESS_AUTHORITY_SOURCE=reviewed_privileged_identity_capability_set_recorded_by_preflight
ACCESS_AUTHORITY_IS_NOT_AN_EVIDENCE_PRODUCER=true
ACCESS_AUTHORITY_AVAILABLE_TO_EVIDENCE_PROCESS=false
ACCESS_AUTHORITY_SEARCH_AUTHORITY=CAP_DAC_READ_SEARCH
ACCESS_AUTHORITY_DIRECTORY_WRITE_AUTHORITY=CAP_DAC_OVERRIDE
ACCESS_AUTHORITY_TWO_DISTINCT_CHECKS=true
ACCESS_AUTHORITY_GRANTS_SEARCH_AND_DIRECTORY_WRITE_SEPARATELY=true
ACCESS_AUTHORITY_EFFECTS=E2,E4,E8,E9,E14,E15,E16,E18,E24,E25,E26
ACCESS_AUTHORITY_NONE_REQUIRED_EFFECTS=E1,E3,E5,E6,E7,E10,E11,E12,E13,E17,E19,E20,E21,E22,E23
ACCESS_AUTHORITY_EFFECT_SET=E2,E4,E8,E9,E14,E15,E16,E18,E24,E25,E26
ACCESS_AUTHORITY_EFFECT_TABLE_TOKEN_EQUIVALENT=true
ACCESS_AUTHORITY_EFFECT_COUNT=11
ACCESS_AUTHORITY_HELPER_ONLY=true
ACCESS_AUTHORITY_EXCLUDES_EVIDENCE_SIDE_EFFECTS=true
ACCESS_AUTHORITY_EXCLUDED_EVIDENCE_SIDE_EFFECTS=E21,E22,E23
CAP_DAC_READ_SEARCH_BOUND_EFFECTS=E2,E4,E14,E15,E16,E18
CAP_DAC_READ_SEARCH_REQUIRED=true
CAP_DAC_READ_SEARCH_RESTORED_BY_ROUND9=true
ROUND9_CAP_DAC_READ_SEARCH_RESTORATION_REASON=a_child_name_resolution_relative_to_a_directory_descriptor_is_a_real_directory_search_check
ROUND10_CAP_DAC_READ_SEARCH_SCOPE_NARROWED=true
CAP_DAC_READ_SEARCH_BINDING_RE_DERIVED_BY_ROUND10=true
CAP_DAC_READ_SEARCH_BINDING_DERIVATION=the_minimal_capability_for_an_effect_that_only_searches_or_reads_a_directory_is_CAP_DAC_READ_SEARCH_capabilities7_bypasses_file_read_checks_and_directory_read_and_execute_checks
CAP_DAC_READ_SEARCH_BINDS_SEARCH_ONLY_AND_READ_ONLY_EFFECTS=true
ROUND8_CAP_DAC_READ_SEARCH_WITHDRAWAL_WAS_UNSOUND=true
ROUND8_CAP_DAC_READ_SEARCH_WITHDRAWAL_WAS_UNSOUND_FOR_THE_SEARCH_ONLY_EFFECTS=true
ROUND8_CAP_DAC_READ_SEARCH_WITHDRAWAL_WAS_SOUND_FOR_THE_DIRECTORY_WRITE_EFFECTS=true
ROUND9_CAP_DAC_READ_SEARCH_OVER_APPLICATION_CORRECTED_BY_ROUND10=true
ROUND8_WITHDRAWAL_SCOPE_ERROR=it_reasoned_about_traversal_alone_and_did_not_distinguish_the_search_only_effects_from_the_directory_write_effects
CHILD_NAME_RESOLUTION_PERFORMS_ONLY_A_SEARCH_CHECK=true
CHILD_NAME_RESOLUTION_PERFORMS_A_DIRECTORY_READ_CHECK=false
ROOT_OPEN_USES_O_PATH=true
ROOT_OPEN_REQUIRES_NO_PERMISSION_ON_THE_ROOT=true
ROOT_OPEN_SOURCE=open(2)_O_PATH_requires_no_permissions_on_the_object_itself
INVOCATION_ROOT_MODE_WIDENED_TO_AVOID_THE_BYPASS=false
```

E1, E3, E5 and E6 act on the caller's own credentials, an already-pinned
descriptor, or the calling process; E7 acts on the namespace root; E10, E11, E12,
E13 and E17 act on descriptors the helper already holds or on the recorded loop
device; E19 and E20 consume `mounted_root_fd`; and E21, E22 and E23 are performed
by the non-root evidence process. Each of those rows says so explicitly.

```text
ACCESS_AUTHORITY_NOT_REQUIRED_REASON=effect_resolves_no_pathname_or_consumes_an_already_held_descriptor
EFFECTS_CONSUMING_AN_ALREADY_HELD_DESCRIPTOR=E3,E5,E10,E11,E12,E13,E17,E19,E20
EFFECTS_ON_THE_CALLERS_OWN_CREDENTIALS=E1
EFFECTS_ON_A_RECORDED_DEVICE_OR_THE_NAMESPACE=E6,E7
EFFECTS_PERFORMED_BY_THE_NONROOT_EVIDENCE_PROCESS=E21,E22,E23
EFFECTS_WITHOUT_ANY_ACCESS_AUTHORITY=E1,E3,E5,E6,E7,E10,E11,E12,E13,E17,E19,E20,E21,E22,E23
```

**Round 9 restores `CAP_DAC_READ_SEARCH`, and round 10 re-derives its exact
binding.** Round 8 withdrew it on the reasoning that `CAP_DAC_OVERRIDE` "bypass
file read, write, and execute permission checks" and therefore already covered
every check the helper performed. That reasoning was sound for the effects that
write a directory entry and unsound for the effects that only search a directory,
so round 9 restored the capability. Round 9 then over-applied it, and its stated
reason was wrong in one respect that matters: child-name resolution inside
`openat(root_fd, FIXTURE_FILE_ROLE, ...)` is a directory **search** (execute)
check only — Linux `fs/namei.c` sets `MAY_EXEC` for the directory component walk
(`may_lookup` → `lookup_inode_permission_may_exec`) and performs no read check on
the directory — and `generic_permission`'s directory branch returns success for
`CAP_DAC_OVERRIDE` on **any** directory mask, including `MAY_READ`, so
`CAP_DAC_OVERRIDE` does cover a directory read check. The two capabilities are
therefore not distinguished by a check one of them misses; they are distinguished
by **minimality**. `CAP_DAC_READ_SEARCH` bypasses exactly the read and search
checks and never a write check, so it is the narrowest authority for an effect
that only searches or reads a directory; `CAP_DAC_OVERRIDE` is required, and is
declared, only where the effect also writes or removes a directory entry. Round
10 binds them that way:

```text
SEARCH_AUTHORITY_SCOPE=resolving_a_child_name_through_or_reading_a_directory_the_helper_does_not_own
DIRECTORY_WRITE_AUTHORITY_SCOPE=creating_or_removing_an_entry_in_a_directory_the_helper_does_not_own
CAP_DAC_OVERRIDE_COVERS_DIRECTORY_SEARCH_AND_READ_AND_WRITE=true
CAP_DAC_OVERRIDE_DOES_NOT_COVER_THE_DIRECTORY_READ_CHECK=false
CAP_DAC_READ_SEARCH_IS_THE_MINIMAL_CAPABILITY_FOR_SEARCH_ONLY_EFFECTS=true
CAP_DAC_READ_SEARCH_IS_NOT_REDUNDANT_WITH_CAP_DAC_OVERRIDE=true
CAP_DAC_READ_SEARCH_IS_NOT_REDUNDANT_BECAUSE_IT_IS_THE_NARROWER_AUTHORITY=true
ROUND9_CAP_DAC_READ_SEARCH_REDUNDANCY_ARGUMENT_WITHDRAWN=true
TWO_CAPABILITY_EFFECTS_ARE_THOSE_THAT_BOTH_RESOLVE_AND_PERFORM_A_PRIVILEGED_OPERATION=true
TWO_CAPABILITY_EFFECTS=E1,E14,E15,E16
PER_EFFECT_AUTHORITY_MINIMALITY_RULE=narrowest_capability_covering_exactly_the_checks_the_effect_performs
```

`E10`'s authority is re-derived once more by round 10, and it is now **none**.
Round 9 kept the search authority on the reasoning that the formatter resolves
`/proc/self/fd/<N>` "through the owner-only root". That reasoning is wrong for the
frozen carrier: the magic link is resolved in the formatter child's own descriptor
table against the open file description `dup(2)` carried across `execve`
(open(2), "Open file descriptions"), so no component of the invocation root is
resolved by that path and no below-root traversal authority belongs on this
effect. The write and the formatter's own `fchmod`-equivalent operations use the
image's own owner-write bit from `IMAGE_ROLE_S_IMODE=0600`, and the effect creates
and removes no directory entry:

```text
ROUND9_FORMATTER_CARRIER_AUTHORITY=CAP_DAC_READ_SEARCH
FORMATTER_CARRIER_AUTHORITY=none
FORMATTER_CARRIER_REQUIRES_CAP_DAC_OVERRIDE=false
FORMATTER_CARRIER_REQUIRES_CAP_DAC_READ_SEARCH=false
FORMATTER_CARRIER_TRAVERSES_THE_INVOCATION_ROOT=false
FORMATTER_CARRIER_IS_THE_CHILDS_OWN_DESCRIPTOR_TABLE=true
FORMATTER_CARRIER_WRITE_USES_IMAGE_OWNER_BIT=true
```

```text
HELPER_READS_DIRECTORY_CONTENTS=true
HELPER_READS_DIRECTORY_CONTENTS_ONLY_IN_E26=true
HELPER_READS_DIRECTORY_CONTENTS_BY_RESOLVING_A_CHILD_NAME=false
HELPER_RESOLVES_CHILD_NAMES_BY_DIRECTORY_SEARCH_ONLY=true
HELPER_USES_OPEN_BY_HANDLE_AT=false
HELPER_USES_LINKAT_AT_EMPTY_PATH=false
HELPER_REQUIRES_CAP_DAC_READ_SEARCH=true
HELPER_REQUIRES_CAP_DAC_READ_SEARCH_FOR_SEARCH_ONLY_EFFECTS=true
HELPER_REQUIRES_CAP_DAC_READ_SEARCH_FOR_DIRECTORY_WRITE_EFFECTS=false
```

The `CAP_SYS_ADMIN` attribution narrows to the operations that really are mount,
namespace, loop or unmount operations, and no other `CAP_SYS_ADMIN` use exists
anywhere in the fixture:

```text
CAP_SYS_ADMIN_BOUND_EFFECTS=E6,E7,E12,E13,E14,E15,E16,E17
EFFECTS_WITHOUT_CAP_SYS_ADMIN=E1,E2,E3,E4,E5,E8,E9,E10,E11,E18,E19,E20,E21,E22,E23,E24,E25,E26
CAP_SYS_ADMIN_BOUND_TO_OPERATIONS=mount_namespace_creation,mount_propagation_private,loop_control_and_configuration,loop_readback,mount_umount_and_loop_release
CAP_SYS_ADMIN_USED_FOR_ANY_OTHER_OPERATION=false
CAP_CHOWN_BOUND_EFFECTS=E3,E5
CAP_CHOWN_BOUND_TO_OPERATION=ownership_mutation_call_only
CAP_SETGID_BOUND_EFFECTS=E1
CAP_SETGID_BOUND_TO_OPERATION=empty_supplementary_group_list_and_gid_transition_only
CAP_SETUID_BOUND_EFFECTS=E1
CAP_SETUID_BOUND_TO_OPERATION=uid_transition_only
CAP_DAC_OVERRIDE_BOUND_EFFECTS=E8,E9,E24,E25,E26
CAP_DAC_OVERRIDE_BOUND_TO_OPERATION=directory_entry_creation_and_removal_in_a_directory_the_helper_does_not_own_and_the_invocation_root_emptiness_observation
CAP_DAC_OVERRIDE_BOUND_EFFECT_COUNT=5
CAP_DAC_OVERRIDE_IS_THE_SINGLE_DIRECTORY_AUTHORITY_FOR_WRITE_AND_REMOVE_EFFECTS=true
CAP_DAC_OVERRIDE_IS_NOT_PAIRED_WITH_CAP_DAC_READ_SEARCH_ON_THE_SAME_CHECK=true
AUTHORITY_PER_EFFECT_TABLE_IS_CANONICAL=true
AUTHORITY_PER_EFFECT_TOKEN_COUNT=26
AUTHORITY_PER_EFFECT_DECLARED_IS_THE_FROZEN_CLAIM=true
AUTHORITY_E1=CAP_SETGID,CAP_SETUID
AUTHORITY_E2=CAP_DAC_READ_SEARCH
AUTHORITY_E3=CAP_CHOWN
AUTHORITY_E4=CAP_DAC_READ_SEARCH
AUTHORITY_E5=CAP_CHOWN
AUTHORITY_E6=CAP_SYS_ADMIN
AUTHORITY_E7=CAP_SYS_ADMIN
AUTHORITY_E8=CAP_DAC_OVERRIDE
AUTHORITY_E9=CAP_DAC_OVERRIDE
AUTHORITY_E10=none
AUTHORITY_E11=none
AUTHORITY_E12=CAP_SYS_ADMIN
AUTHORITY_E13=CAP_SYS_ADMIN
AUTHORITY_E14=CAP_SYS_ADMIN,CAP_DAC_READ_SEARCH
AUTHORITY_E15=CAP_SYS_ADMIN,CAP_DAC_READ_SEARCH
AUTHORITY_E16=CAP_SYS_ADMIN,CAP_DAC_READ_SEARCH
AUTHORITY_E17=CAP_SYS_ADMIN
AUTHORITY_E18=CAP_DAC_READ_SEARCH
AUTHORITY_E19=none
AUTHORITY_E20=none
AUTHORITY_E21=none
AUTHORITY_E22=none
AUTHORITY_E23=none
AUTHORITY_E24=CAP_DAC_OVERRIDE
AUTHORITY_E25=CAP_DAC_OVERRIDE
AUTHORITY_E26=CAP_DAC_OVERRIDE
AUTHORITY_PER_EFFECT_EQUALS_BOUND_EFFECT_SETS=true
AUTHORITY_TABLE_EQUALS_AUTHORITY_E_TOKENS=true
PER_EFFECT_AUTHORITY_MINIMALITY_CLOSED=true
PER_EFFECT_AUTHORITY_MAXIMUM_CAPABILITY_COUNT=2
PER_EFFECT_AUTHORITY_THREE_CAPABILITY_EFFECTS=none
CAP_FOWNER_BOUND_EFFECTS=none
CAP_SETPCAP_BOUND_EFFECTS=none
REQUIRED_CAPABILITY_INVENTORY=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
REQUIRED_CAPABILITY_COUNT=6
OTHER_CAPABILITY_REQUIRED_BY_ANY_EFFECT=false
REQUIRED_CAPABILITY_INVENTORY_IS_UNION_OF_REQUIRED_CAPABILITY_AUTHORITIES=true
NO_DECLARED_CAPABILITY_IS_UNUSED=true
CAP_SETPCAP_REQUIRED_BY_CREDENTIAL_TRANSITION=false
CREDENTIAL_TRANSITION_CAPABILITY_CLEARING_IS_KERNEL_PERFORMED=true
```

The `CAP_SYS_ADMIN` set is mount-case-only by construction: E6 and E7 are the
private namespace and its private propagation, and they are scoped to
`mount-fixture` because that case alone mounts a filesystem (1.7.4). The
ownership cases reach no `CAP_SYS_ADMIN` effect at all, which is what makes
`OWNERSHIP_CASE_REQUIRES_CAP_SYS_ADMIN=false` a derived fact rather than an
assertion:

```text
CAP_SYS_ADMIN_BOUND_EFFECT_SET_SCOPE=mount-fixture
OWNERSHIP_CASE_EFFECTS_INTERSECT_CAP_SYS_ADMIN_EFFECTS=none
OWNERSHIP_CASE_EFFECTS_INTERSECT_CAP_SYS_ADMIN_EFFECTS_IS_EMPTY=true
```

```text
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
REAL_MATERIAL_EFFECT_COUNT=26
PRIVILEGED_EFFECT_CLOSURE_ROWS=26
REAL_MATERIAL_EFFECT_COUNT_EQ_CLOSURE_ROWS=true
ROUND8_EFFECT_ROWS_ALL_REAL_EFFECTS=true
ROUND8_PLACEHOLDER_EFFECT_ROWS=0
ROUND8_PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
PRIVILEGED_EFFECT_CLOSURE_ROUND=8
PRIVILEGED_EFFECT_CLOSURE_MAINTAINED_IN_PLACE=true
ROUND7_EFFECT_ROWS_ALL_REAL_EFFECTS_IS_A_ROUND7_RECORD=true
ROUND7_PLACEHOLDER_EFFECT_ROWS=0
ROUND7_PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
ROUND6_EFFECT_ROWS_ALL_REAL_EFFECTS_IS_A_ROUND6_RECORD=true
ROUND6_PLACEHOLDER_EFFECT_ROWS=0
ROUND6_PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
```

The effect dependency graph is stated with the table and proved by an executable
topological sort (1.8.1, 15.1):

```text
EFFECT_DEPENDENCY_EDGES=E1:E21,E2:E3,E3:E1,E4:E5,E5:E1,E6:E7,E7:E8,E8:E9,E9:E10,E10:E11,E11:E12,E12:E13,E13:E14,E14:E16,E14:E18,E15:E22,E16:E17,E17:E24,E18:E19,E19:E20,E20:E1,E21:E15,E21:E23,E22:E23,E23:E16,E23:E17,E23:E25,E24:E26,E25:E26
EFFECT_DEPENDENCY_EDGES_ARE_THE_UNION_OF_THE_CASE_GRAPHS=true
EFFECT_DEPENDENCY_GRAPH_IS_NOT_ONE_UNCONDITIONAL_GLOBAL_ORDER=true
EFFECT_DEPENDENCY_EDGES_ARE_OVER=the_twenty_six_material_effects
E0_IS_A_SENTINEL_NOT_AN_EFFECT=true
EFFECT_DEPENDENCY_DAG_ACYCLIC=true
E26_DEPENDENCY_PREDECESSORS=E24,E25
E21_DEPENDENCY_PREDECESSORS=E1
E18_DEPENDENCY_PREDECESSORS=E14
E17_DEPENDENCY_PREDECESSORS=E23,E16
E14_DEPENDENCY_PREDECESSORS=E13
E13_DEPENDENCY_PREDECESSORS=E12
E12_DEPENDENCY_PREDECESSORS=E11
E7_DEPENDS_ON_E13=false
CANONICAL_EFFECT_REGISTRY_ROUND=9
CANONICAL_EFFECT_REGISTRY_SOURCE=1.9.1
CANONICAL_EFFECT_REGISTRY_IS_THE_ONLY_CURRENT_EFFECT_AUTHORITY=true
SECUREBITS_VALIDATED_AFTER_EXECVE=true
SECUREBITS_VALIDATED_AFTER_SETUID=true
SECUREBITS_VALIDATED_BEFORE_TRANSITION=true
PROC_STATUS_SECBITS_FIELD_REQUIRED=false
SECUREBITS_OBSERVATION_SOURCE=prctl_PR_GET_SECUREBITS
FIXTURE_OBJECT_REMOVAL_EFFECT=E25
MOUNT_OBJECT_REMOVAL_EFFECT=E24
CLEANUP_EFFECT_ID_MAPPING_MATCHES_TABLE=true
FIXTURE_ROOT_RESIDUE_CLOSING_EFFECT=E26
INVOCATION_ROOT_REMOVAL_EFFECT=E26
INVOCATION_ROOT_REMOVAL_MATERIAL_EFFECT_EXISTS=true
POST_DETACH_EVIDENCE_BEFORE_DESCRIPTOR_RELEASE=true
EVIDENCE_RELEASE_BEFORE_LOOP_RELEASE=true
EVIDENCE_RELEASE_AFTER_POST_DETACH_OBSERVATION=true
POST_DETACH_PRODUCTION_OBSERVATION_IS_MATERIAL_EFFECT=true
EVIDENCE_DESCRIPTOR_OPEN_DURING_POST_DETACH_PROBE=true
EVIDENCE_DESCRIPTOR_OPEN_AT_DETACH=true
POST_DETACH_OBSERVATION_EFFECT=E22
CAPABILITY_BOUND_EFFECT_SETS_EQUAL_AUTHORITY_E_TOKENS=true
AUTHORITY_BUCKETS_EQUAL_AUTHORITY_E_TOKENS=true
ROUND9_AUTHORITY_E26=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH
ROUND9_AUTHORITY_E25=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH
CASE_EFFECT_COUNTS_CLOSED=true
CASE_EFFECT_SET_SCOPE_CLOSED=true
DECLARED_CASE_EFFECT_COUNT_EQUALS_SET_CARDINALITY=true
DECLARED_CASE_EFFECT_SET_EQUALS_ROWS_WITH_MATCHING_SCOPE=true
CLOSURE_TABLE_ORDER_IS_EXECUTION_ORDER=false
CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER=false
CLOSURE_TABLE_ORDER_IS_NEITHER_A_TOPOLOGICAL_NOR_AN_EXECUTION_ORDER=true
CLOSURE_TABLE_ORDER_IS_THE_REGISTRY_ORDER_ONLY=true
CURRENT_EFFECT_REFERENCE_TO_HISTORICAL_MEANING_COUNT=0
CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT=0
EFFECT_ID_CURRENT_MEANING_UNIQUE=true
GLOBAL_DAG_ACYCLIC=true
EVERY_CASE_EFFECT_PREDECESSOR_EXISTS_IN_THAT_CASE=true
CROSS_CASE_PREDECESSOR_LEAK_COUNT=0
EVERY_CASE_DAG_EXECUTABLE=true
EVERY_CASE_DAG_ACYCLIC=true
MOUNT_FIXTURE_ATTACHED_FAILURE_NO_DESCRIPTOR_PATH_DEPENDENCY_EDGES=E6:E7,E7:E8,E8:E9,E9:E10,E10:E11,E11:E12,E12:E13,E13:E14,E14:E16,E16:E17,E17:E24,E24:E26
MOUNT_FIXTURE_ATTACHED_FAILURE_WITH_DESCRIPTOR_PATH_DEPENDENCY_EDGES=E6:E7,E7:E8,E8:E9,E9:E10,E10:E11,E11:E12,E12:E13,E13:E14,E14:E18,E18:E19,E19:E20,E20:E1,E1:E21,E21:E23,E23:E16,E16:E17,E17:E24,E24:E26
ATTACHED_FAILURE_BEFORE_E21_CLEANUP_REACHABLE=true
ATTACHED_FAILURE_DURING_E21_CLEANUP_REACHABLE=true
ATTACHED_FAILURE_NO_DESCRIPTOR_ENTRY_STATE=ATTACHED_NO_EVIDENCE_DESCRIPTOR
ATTACHED_FAILURE_WITH_DESCRIPTOR_ENTRY_STATE=ATTACHED_WITH_EVIDENCE_DESCRIPTOR
ATTACHED_FAILURE_NO_DESCRIPTOR_EFFECT_SEQUENCE=E16,E17,E24,E26
ATTACHED_FAILURE_WITH_DESCRIPTOR_EFFECT_SEQUENCE=E23,E16,E17,E24,E26
MOUNT_FIXTURE_SUCCESS_PATH_DEPENDENCY_EDGES=E6:E7,E7:E8,E8:E9,E9:E10,E10:E11,E11:E12,E12:E13,E13:E14,E14:E18,E18:E19,E19:E20,E20:E1,E1:E21,E21:E15,E15:E22,E22:E23,E23:E17,E17:E24,E24:E26
E21_BEFORE_E15=true
E15_BEFORE_E22=true
E22_BEFORE_E23=true
E17_BEFORE_E24=true
E24_BEFORE_E26=true
OWN_ROOT_DEPENDENCY_EDGES=E4:E5,E5:E1,E1:E21,E21:E23,E23:E25,E25:E26
OWN_FOREIGN_DEPENDENCY_EDGES=E2:E3,E3:E1,E1:E21,E21:E23,E23:E25,E25:E26
EFFECT_DEPENDENCY_DAG_TOPOLOGICAL_SORT_EXISTS=true
EFFECT_DEPENDENCY_EDGES_ARE_MINIMAL=true
EFFECT_DEPENDENCY_DERIVED_FROM=row_preconditions_and_target_identities
EFFECT_DEPENDENCY_EDGES_ARE_DIRECT=true
EVERY_REQUIRED_PRECONDITION_IS_A_DAG_ANCESTOR=true
EFFECT_DEPENDENCY_CYCLE_COUNT=0
EFFECT_DEPENDENCY_BRANCHES=E1:E21,E14:E16|E18,E21:E15|E23,E23:E16|E17|E25,E13:E14,E20:E1
EFFECT_DEPENDENCY_SINKS=E26
EFFECT_DEPENDENCY_SINK_COUNT=1
EFFECT_DEPENDENCY_SINK_IS_THE_TERMINAL_ROOT_REMOVAL=true
LOOP_CONFIGURE_VERIFY_MOUNT_ORDER_CLOSED=true
E7_DEPENDS_ON_E13=false
E7_CLAIMS_E19_READBACK_POSTCONDITION=false
E19_DEPENDS_ON_E13=false
E15_DEPENDS_ON_E13_VERIFICATION=true
MOUNT_BEFORE_LOOP_VERIFICATION=false
MOUNT_AFTER_LOOP_VERIFICATION=true
```

**Case effect sets and total authority sets.** The case scoping above is
mechanical: each effect belongs either to exactly one case or to all three, and
each case's total required authority is the union of its own effects' required
authority and nothing more. The sets are stated here so that the closure is
checkable in both directions rather than inferred from the row text:

```text
OWN_FOREIGN_EFFECT_SET=E1,E2,E3,E21,E23,E25,E26
OWN_ROOT_EFFECT_SET=E1,E4,E5,E21,E23,E25,E26
MOUNT_FIXTURE_EFFECT_SET=E1,E6,E7,E8,E9,E10,E11,E12,E13,E14,E15,E16,E17,E18,E19,E20,E21,E22,E23,E24,E26
MOUNT_FIXTURE_EFFECT_SET_CONTAINS_E25=false
OWN_FOREIGN_EFFECT_COUNT=7
OWN_ROOT_EFFECT_COUNT=7
MOUNT_FIXTURE_EFFECT_COUNT=21
UNION_OF_CASE_EFFECT_SETS=E1,E2,E3,E4,E5,E6,E7,E8,E9,E10,E11,E12,E13,E14,E15,E16,E17,E18,E19,E20,E21,E22,E23,E24,E25,E26
REAL_MATERIAL_EFFECT_COUNT_IS_UNION_OF_CASE_EFFECT_SETS=true
EFFECT_CASE_SCOPE_EXCLUSIVITY=each_effect_belongs_to_exactly_one_case_or_to_all_cases
EFFECT_APPEARS_IN_EXACTLY_ITS_INTENDED_CASE_SET=true
OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_COUNT=5
OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_COUNT=5
MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_COUNT=5
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
CASE_TOTAL_AUTHORITY_SET_IS_MINIMAL=true
OWNERSHIP_CASE_REQUIRES_PRIVATE_MOUNT_NAMESPACE=false
OWNERSHIP_CASE_REQUIRES_CAP_SYS_ADMIN=false
OWNERSHIP_CASE_REQUIRES_CAP_DAC_READ_SEARCH=true
MOUNT_FIXTURE_REQUIRES_CAP_CHOWN=false
RQP_L17_TOTAL_AUTHORITY_SET_EQUALS_MOUNT_FIXTURE_TOTAL_AUTHORITY_SET=true
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
CLEANUP_RESTORES_OWNERSHIP=false
CLEANUP_HELPER_OWNERSHIP_CALLS_AFTER_SETUP=0
CLEANUP_REPAIRS_OWNERSHIP=false
CLEANUP_REMOVED_OBJECT_KEEPS_SETUP_OWNERSHIP_UNTIL_REMOVAL=true
CLEANUP_OWNERSHIP_RESTORATION_IS_AN_EFFECT_ROW=false
CLEANUP_OWNERSHIP_RESTORATION_COUNTS_AS_MATERIAL_EFFECT=false
CLEANUP_OWNERSHIP_RESTORATION_HAS_AUTHORITY_ROW=none
ROUND5_OWNERSHIP_RESTORATION_PLACEHOLDER_ROW_WITHDRAWN_BY_ROUND6=true
OWNERSHIP_FIXTURE_FILE_REMOVAL_EFFECT=E25
OWNERSHIP_FIXTURE_FILE_REMOVAL_EFFECT_DECLARED=true
OWNERSHIP_FIXTURE_FILE_REMOVAL_SCOPE=own-foreign,own-root
OWNERSHIP_FIXTURE_FILE_REMOVAL_BEFORE_ROOT_REMOVAL=true
OWNERSHIP_FIXTURE_FILE_REMOVAL_AUTHORITY=CAP_DAC_OVERRIDE
OWNERSHIP_FIXTURE_FILE_REMOVAL_REQUIRES_CAP_CHOWN=false
OWNERSHIP_FIXTURE_FILE_REMOVAL_PERFORMS_REVERSE_FCHOWN=false
OWNERSHIP_FIXTURE_FILE_REMOVAL_EFFECT_IS_SHARED_WITH_THE_MOUNT_CASES_OBJECTS=false
MOUNT_CASE_HAS_NO_FIXTURE_OBJECT_REMOVAL_EFFECT=true
MOUNT_CASE_E25_NOOP_COUNT=0
DUPLICATE_CLEANUP_TARGET_COUNT=0
```

That resolution is what keeps the closure honest rather than merely complete:
section 5 no longer declares an operation that no effect row, no authority and no
cleanup step implements. Round 5 recorded the withdrawal in a row that declared
no effect at all, and round 6 corrected the counting: a no-effect placeholder is
not a material effect and must not be counted as one, so the withdrawal is
recorded here as tokens rather than as a row. Round 6 then gave `E14` the real
ownership-case `FIXTURE_FILE_ROLE` removal effect, and round 7 renumbers it
`E26` when the table is rebuilt in lifecycle order and widens its scope to the
one removal effect every case shares (1.7.6). The round-7 record had twenty-two real
effect rows and no placeholder row, with
`REAL_MATERIAL_EFFECT_COUNT == PRIVILEGED_EFFECT_CLOSURE_ROWS == 22` at that head; that
count is a round-7 record, and the current count is 26 with no placeholder row (1.9.9, 1.10.8).

### 1.6 Remediation round 6

Round 5's head was independently reviewed and failed with the same failure
class. That failure is preserved here rather than rewritten:

```text
FIFTH_A3D_REVIEW_FAILED_HEAD=65061f1e005c7595afd4c84d049a4e025eea9d70
FIFTH_A3D_REVIEW_FAILED_TREE=3b3814d303969ec4abf07c9affbf7163dec1d023
FIFTH_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
FIFTH_A3D_REVIEW_FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
FIFTH_A3D_REVIEW_BLOCKING_FINDINGS=3
A3D_SIXTH_REMEDIATION_ROUND=6
A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=6
A3D_HISTORY_ADDITIVE=true
PRODUCT_FAILURE=false
PRIVILEGED_EXECUTION_PERFORMED=false
```

`PRODUCT_FAILURE=false` is a measured statement rather than a convenience: this
round changes one design document, runs no privileged command, and involves no
production code either in the failure or in the correction.

Round 5's record in 1.5 is not rewritten: it keeps its findings and its tokens,
and every statement round 6 supersedes is marked there rather than deleted. The
closure table stays in 1.5 and is corrected in place by this round, because a
second copy of the table would put two claims about one effect set into the same
document; 1.5 now says so explicitly. The failed head stays in this branch's
history as the direct parent of this round's commit (20).

The three blocking findings are corrected in this document:

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | The retired `OWNERSHIP_FIXTURE_REQUIRED_CAPABILITY_SET` token, frozen with `CAP_CHOWN` as its value, contradicted the separately required helper access authority for E1/E2, and the framing that the access authority "produces no required outcome and no evidence" was being used to imply it was not required at all. | 1.6, 7 |
| 2 | E9, E7 and E10 each required the declared helper access authority in their own row, but were absent from `PRIVILEGED_HELPER_ACCESS_AUTHORITY_EFFECTS` and `CAP_DAC_OVERRIDE_BOUND_EFFECTS`, so the rows and the machine-like scope tokens disagreed and one capability was inherited mechanically instead of being derived per effect. | 1.5, 1.6 |
| 3 | The ownership cases had no destructive cleanup effect at all: the fixture file that E1/E2 mutates was never removed before the invocation root, and the round-5 closure reached its row count with a no-effect placeholder row. | 1.5, 1.6, 10.4 |

**Finding 1: the ownership capability set recomputed, with nothing declared
unnecessary.** An authority does not cease to be required because it produces no
evidence or no product outcome, so the earlier framing is withdrawn and the
ownership cases' authority is split into two independently exact facts: the
mutation authority and the case's filesystem-access authority. The mutation
authority is `CAP_CHOWN` alone, because the helper's only ownership operation is
the single `fchown` of 5.8.2. The access authority is not smaller than the access
the case really performs: opening the pinned child through the owner-only root
needs directory search, and unlinking that child during cleanup needs directory
write and search. The ownership case's total required authority is therefore the
union, and it is frozen as such:

```text
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY_SET=CAP_CHOWN
OWNERSHIP_MUTATION_AUTHORITY_EXACT=true
OWNERSHIP_MUTATION_REQUIRES_CAP_FOWNER=false
ROUND6_OWNERSHIP_CASE_ACCESS_AUTHORITY=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH
ROUND6_OWNERSHIP_CASE_ACCESS_AUTHORITY_EXACT=true
ROUND6_OWNERSHIP_CASE_ACCESS_AUTHORITY_EFFECTS=E18
ROUND6_OWNERSHIP_CASE_ACCESS_AUTHORITY_EFFECTS_NUMBERING=round_6_numbering_the_ownership_fixture_unlink
OWNERSHIP_CASE_ACCESS_AUTHORITY_REQUIRED=true
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_TRUTHFUL=true
OWNERSHIP_CASE_REQUIRED_AUTHORITY_COUNT=5
OWNERSHIP_CASE_FIXTURE_EFFECTS=E2,E3,E4,E5,E26
OWNERSHIP_CASE_SHARED_ALL_CASE_EFFECTS=E1,E26
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_DERIVATION=union_of_the_ownership_case_effect_set_required_authority
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_DERIVATION_DETAIL=CAP_CHOWN_from_E3_and_E5;CAP_DAC_READ_SEARCH_from_E2_and_E4_and_E21_and_E22;CAP_DAC_OVERRIDE_from_E21_and_E22;CAP_SETGID_from_E1;CAP_SETUID_from_E1
OWNERSHIP_CASE_AUTHORITY_DECOMPOSITION=mutation_authority_plus_access_authority_plus_credential_transition_authority
OWNERSHIP_FIXTURE_REQUIRED_CAPABILITY_SET_RETIRED=true
OWNERSHIP_FIXTURE_REQUIRED_CAPABILITY_SET_RETIRED_REASON=it_named_only_the_mutation_capability_while_claiming_to_name_the_fixtures_required_set
OWNERSHIP_CASE_AUTHORITY_INCLUDES_CAP_DAC_OVERRIDE=true
NO_AUTHORITY_DECLARED_UNNECESSARY_BECAUSE_IT_PRODUCES_NO_EVIDENCE=true
ROUND6_OWNERSHIP_CASE_SET_IS_A_ROUND6_RECORD=true
ROUND6_OWNERSHIP_CASE_SET_SUPERSEDED_BY_ROUND7=true
ROUND6_OWNERSHIP_CASE_SET_OMITTED_THE_CREDENTIAL_TRANSITION_AUTHORITY=true
ROUND6_OWNERSHIP_CASE_TOKEN_VALUES_ARE_CURRENT_CLAIMS=false
```

**Finding 2: the access authority derived per effect.** Every effect from E1 to
E18 was re-examined on its own, instead of inheriting one capability from E1/E2,
and each row now states the access authority its own access operation needs. The
derivation, one row per effect, is:

The table below is round 6's derivation against round 6's numbering, and its
effect numbers are **round-6 numbers**, not this head's: rounds 7 and 8 both
rebuilt the effect table, so the numbers below are retired and are kept only as
the record of that head's reasoning. The current derivation is the token block in
1.10.4, and the current numbers are the ones the closure table and the 1.9.1 registry use:

```text
ROUND6_EFFECT_NUMBERING_IS_NOT_THIS_HEADS_NUMBERING=true
ROUND6_EFFECT_NUMBERING_RETIRED=true
ROUND7_EFFECT_NUMBERS_ARE_LIFECYCLE_ORDERED=true
ROUND6_TO_ROUND7_EFFECT_NUMBER_MAP=E3_to_E9,E4_to_E10,E5_to_E8,E6_to_E11,E7_to_E7,E8_to_E16,E9_to_E18,E10_to_E12,E11_to_E14,E12_to_E13,E13_to_E21,E14_to_E20,E15_to_E22,E16_to_E21
ROUND6_TO_ROUND7_MAP_IS_HISTORICAL_ONLY=true
ROUND7_EFFECT_NUMBERS_ADDED_BY_ROUND7=E1,E2,E4,E8,E13,E20
ROUND6_CURRENT_ACCESS_AUTHORITY_DERIVATION_AT_THAT_HEAD=the_token_block_of_1_5
CURRENT_ACCESS_AUTHORITY_DERIVATION=the_token_block_of_1_10
```

| Round-6 `E` # (historical numbering, not this head's) | Access operation | Whose permission the access check uses | Required access | Authority |
| --- | --- | --- | --- | --- |
| E1 | `openat` of the pinned child relative to the validated root descriptor (`O_RDONLY\|O_NOFOLLOW\|O_CLOEXEC`); the child itself is `0644` | the invocation root directory, `S_IMODE == 0o700` and owned by the ordinary runner, so search is denied to the helper | search (execute) on the containing directory | `CAP_DAC_READ_SEARCH` |
| E2 | same as E1 | same | same | `CAP_DAC_READ_SEARCH` |
| E3 | none: the effect resolves no pathname and touches no filesystem object | not applicable | none | none |
| E4 | path `/` inside the private namespace the launcher just created | the namespace root, which the reviewed privileged identity may search without a bypass | none | none |
| E5 | `openat` with `O_CREAT\|O_EXCL` of `IMAGE_ROLE` | the invocation root directory | write and search on the containing directory | `CAP_DAC_OVERRIDE` |
| E6 | open of the image by its frozen role name so that `mke2fs` can write it | the invocation root directory for the traversal; the image file itself is owned by the helper, so its own owner-write bit applies | search on the containing directory | `CAP_DAC_READ_SEARCH` |
| E7 | open of the image to bind it to the loop device | the invocation root directory for the traversal; the loop device nodes are owned by the reviewed privileged identity | search on the containing directory | `CAP_DAC_READ_SEARCH` |
| E8 | `mount(2)` resolution of the frozen `MOUNTPOINT_ROLE` target path | the invocation root directory for the traversal; after the mount the path names the mounted ext4 root, which grants search | search on the containing directory | `CAP_DAC_READ_SEARCH` |
| E9 | `openat` of the mounted target, then creation of `FIXTURE_FILE_ROLE` relative to it | the invocation root directory for the traversal; the creation itself is authorized by the mounted root directory's owner bits, because the helper owns that directory | search on the containing directory | `CAP_DAC_READ_SEARCH` |
| E10 | `umount2` resolution of the frozen `MOUNTPOINT_ROLE` path | the invocation root directory | search on the containing directory | `CAP_DAC_READ_SEARCH` |
| E11 | `umount2` resolution of the frozen `MOUNTPOINT_ROLE` path | the invocation root directory | search on the containing directory | `CAP_DAC_READ_SEARCH` |
| E12 | none: the release acts on the recorded loop device | not applicable | none | none |
| E13 | `unlink` of `IMAGE_ROLE` | the invocation root directory | write and search on the containing directory | `CAP_DAC_OVERRIDE` |
| E14 | `rmdir` of `MOUNTPOINT_ROLE` | the invocation root directory | write and search on the containing directory | `CAP_DAC_OVERRIDE` |
| E15 | `rmdir` of the invocation root, plus a read of that root to observe emptiness | the root's parent (`RUNNER_TEMP`) for the removal; the root itself for the emptiness observation | write and search on the parent, read on the root | `CAP_DAC_OVERRIDE` |
| E16 | `unlinkat` of `FIXTURE_FILE_ROLE` | the invocation root directory | write and search on the containing directory | `CAP_DAC_OVERRIDE` |

The narrowest authority is chosen per access operation rather than inherited:
traversal alone needs the capability that bypasses directory read and execute
checks (`CAP_DAC_READ_SEARCH`, capabilities(7)), while creating, unlinking or
removing a directory entry additionally needs write permission on that directory
and therefore the capability that also bypasses write checks
(`CAP_DAC_OVERRIDE`, capabilities(7)). E3, E4 and E15 need neither, and each of
those rows says so explicitly. The rows in 1.5 and the machine-like scope
tokens now state the same sets, which is what makes the equivalence checkable:

```text
ROUND6_ACCESS_AUTHORITY_EFFECT_SET=E1,E2,E5,E8,E12,E9,E6,E7,E10,E17,E16,E14,E18
ROUND6_ACCESS_AUTHORITY_EFFECT_TABLE_TOKEN_EQUIVALENT=true
ROUND6_ACCESS_AUTHORITY_TRAVERSAL_EFFECTS=E1,E2,E8,E12,E9,E6,E7,E10
ROUND6_ACCESS_AUTHORITY_DIRECTORY_WRITE_EFFECTS=E5,E17,E16,E14,E18
ROUND6_ACCESS_AUTHORITY_NONE_REQUIRED_EFFECTS=E3,E4,E15
ROUND6_ACCESS_AUTHORITY_DERIVED_PER_EFFECT=true
ROUND6_ACCESS_AUTHORITY_INHERITED_FROM_ANOTHER_EFFECT=false
ROUND6_ACCESS_AUTHORITY_NARROWEST_JUSTIFIED_CAPABILITY=true
```

**Finding 3: the ownership fixture's own removal effect.** The ownership cases
mutate the fixture file and then had no effect that removed it, so the
invocation-root removal was the only cleanup step they had and it would have had
to remove a non-empty directory. `E18` is now that missing destructive effect: a
real ownership-case `FIXTURE_FILE_ROLE` unlink, bound to the validated root
descriptor and the frozen child role with an identity revalidation before the
call, authorized by the containing directory's write and search access through
`CAP_DAC_OVERRIDE`, requiring no `CAP_CHOWN` and performing no reverse `fchown`,
and ordered before the root removal:

```text
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_EFFECT=E18
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_EFFECT_DECLARED=true
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_SCOPE=own-foreign,own-root
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_TARGET=the_ownership_fixture_child_E1_or_E2_mutated
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_TARGET_BINDING=validated_root_descriptor_plus_frozen_child_role_plus_identity_revalidation
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_AUTHORITY=CAP_DAC_OVERRIDE
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_REQUIRES_CAP_CHOWN=false
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_PERFORMS_REVERSE_FCHOWN=false
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_PRECONDITION_PRODUCTION_OBSERVATION_FINISHED=true
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_PRECONDITION_IDENTITY_STILL_MATCHES=true
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_PRECONDITION_NO_REPAIR_OR_REOWNERSHIP=true
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_POSTCONDITION_FIXTURE_FILE_ABSENT=true
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_BEFORE_ROOT_REMOVAL=true
CLEANUP_RESTORES_OWNERSHIP=false
```

The round-5 placeholder is retired with it: the withdrawn requirement
"cleanup ownership restoration" is now recorded as tokens, not as a row, because
a no-effect placeholder is not a material effect and must not be counted as one:

```text
CLEANUP_OWNERSHIP_RESTORATION_EFFECT=NONE
CLEANUP_OWNERSHIP_RESTORATION_IS_AN_EFFECT_ROW=false
CLEANUP_OWNERSHIP_RESTORATION_COUNTS_AS_MATERIAL_EFFECT=false
ROUND6_EFFECT_ROWS_ALL_REAL_EFFECTS=true
ROUND6_PLACEHOLDER_EFFECT_ROWS=0
ROUND6_PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
ROUND6_REAL_MATERIAL_EFFECT_COUNT=16
ROUND6_PRIVILEGED_EFFECT_CLOSURE_ROWS=16
ROUND6_REAL_MATERIAL_EFFECT_COUNT_EQ_CLOSURE_ROWS=true
```

**Root-removal lifecycle made case-aware.** The root removal cannot require the
mount case's effects in a case that never creates a mount. E13's preconditions
are therefore case-aware: `mount-fixture` requires E17 and E16 completed,
`own-foreign` and `own-root` require E14 completed, and both require an empty
root:

```text
ROUND6_ROOT_REMOVAL_CASE_AWARE_PRECONDITIONS=true
ROUND6_ROOT_REMOVAL_MOUNT_FIXTURE_PRECONDITIONS=E17,E14_completed_and_root_empty
ROUND6_ROOT_REMOVAL_OWNERSHIP_CASE_PRECONDITIONS=E16_completed_and_root_empty
ROOT_REMOVAL_REQUIRES_MOUNT_CASE_EFFECTS_IN_OWNERSHIP_CASES=false
ROOT_REMOVAL_REQUIRES_OWNERSHIP_CASE_EFFECT_IN_MOUNT_CASE=false
ROOT_REMOVAL_NONEXISTENT_EFFECT_REQUIRED_ANYWHERE=false
```

**Closure and re-run results for this round.** The closure table in 1.5 now has
one row per real material effect, every row states its own access authority, the
rows and the machine-like scope tokens are identical, and the three
bidirectional-closure invariants still hold at this head:

```text
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
OWNERSHIP_TOTAL_AUTHORITY_SET_CLOSED=true
ACCESS_AUTHORITY_SCOPE_CLOSED=true
ROOT_REMOVAL_CASE_LIFECYCLE_CLOSED=true
ROUND6_REAL_EFFECT_ROW_COUNT=16
PLACEHOLDER_EFFECT_ROW_COUNT=0
ROUND6_BLOCKING_FINDINGS_CLOSED=3
BLOCKING_FINDINGS_OPEN=0
```

### 1.7 Remediation round 7

Round 6's head was independently reviewed and failed with the same failure
class. That failure is preserved here rather than rewritten:

```text
SIXTH_A3D_REVIEW_FAILED_HEAD=c2a88fa02f62b1332a6f8cabd779d89bd260adfb
SIXTH_A3D_REVIEW_FAILED_TREE=e7da9a0da884156217d72dd7772c3389422ff6b9
SIXTH_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
SIXTH_A3D_REVIEW_FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
SIXTH_A3D_REVIEW_RESULT=FAIL
A3D_SEVENTH_REMEDIATION_ROUND=7
A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=7
A3D_HISTORY_ADDITIVE=true
PRODUCT_FAILURE=false
PRIVILEGED_EXECUTION_PERFORMED=false
```

Round 7 changes the same single design document, runs no privileged command, and
touches no production code, so `PRODUCT_FAILURE=false` is a measured statement
here for the same reason round 6 gave.

The independent review named nine blocking findings. All nine are corrected in
this document, and the correction is stated where the finding lives rather than
collected in one place:

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | The effect set was derived from the existing `E1..E14` table rather than from the real lifecycle, so the table validated itself. | 1.7, 1.5 |
| 2 | `E3`/`E4` were run-scoped (`all cases`) while section 10 is RQP-L17-specific, and the RQP-L17 total authority set omitted `CAP_SYS_ADMIN` as an authority on the ownership cases' path. | 1.5, 1.7, 7, 10 |
| 3 | The launcher's credential transition was not a declared effect: no row, no mechanism, no authority, and no supplementary-group semantics. | 1.5, 1.7, 5.10, 7 |
| 4 | Section 5.9 required helper-exclusive creation of `MOUNTPOINT_ROLE`, but no effect row created it. | 1.5, 1.7, 5.9 |
| 5 | One "mount-related capability set" was used in place of each case's whole authority set, and `RQP_L17_REQUIRED_CAPABILITY_SET` claimed a total while naming only the mount subset. | 1.7, 7 |
| 6 | `E13` acts on the invocation root's **parent**, `RUNNER_TEMP`, while its declared authority scope was only "below the validated invocation root". | 1.5, 1.7, 7 |
| 7 | `E8`/`E20` relied on "the image owner's write permission", which `E5` never froze. | 1.5, 1.7, 5.9 |
| 8 | The contract simultaneously described a pathname-based `losetup` setup and claimed a descriptor-mediated loop binding. | 1.5, 1.7, 5.9 |
| 9 | Two different bare values of `A3D_REMEDIATION_COMMIT_PARENT` existed at one head. | 1.7, 20 |

#### 1.7.1 Effect sets derived from the real lifecycle

The round-7 method is the reverse of the round-6 method, and the reversal is the
correction for finding 1. Round 6 verified that the table had one row per real
effect; that check cannot detect an effect the table never had. Round 7 therefore
enumerated the real operations per case first, from the frozen lifecycle of 10.1
and the object lifecycle of 14, and derived the closure table of 1.5 from those
sets afterwards. Row count is not offered as completeness evidence anywhere in
this round.

```text
EFFECT_SET_DERIVATION_ORDER=real_lifecycle_then_closure_table
EFFECT_SET_DERIVED_FROM_EXISTING_TABLE=false
EFFECT_ROW_COUNT_IS_COMPLETENESS_EVIDENCE=false
```

One ordering constraint was found while doing this and is now frozen, because
without it the mount case cannot be constructed at all: the mount-case fixture
file does not exist until the helper has mounted the image, so the credential
transition of 5.10 necessarily occurs **after** the mount-case setup, not before
it. The evidence process therefore reacquires its identity after the fixture
exists, which is what the RQP-L17 case needs:

```text
MOUNT_CASE_SETUP_PRECEDES_CREDENTIAL_TRANSITION=true
CREDENTIAL_TRANSITION_PRECEDES_EVIDENCE_PROCESS_EXEC=true
PRODUCTION_PRIMITIVE_EXECUTES_AFTER_CREDENTIAL_TRANSITION=true
LAUNCHER_PROCESS_ITSELF_NEVER_CHANGES_IDENTITY=false
LAUNCHER_DROPS_CREDENTIALS_IN_A_FORKED_CHILD=true
CREDENTIAL_TRANSITION_IS_CHILD_LOCAL=true
```

#### 1.7.2 The credential transition declared

Finding 3 is corrected by declaring the transition as its own real effect, with a
frozen mechanism and frozen authorities. It is `E1` in the closure table of 1.5,
and 5.10 is its normative description. The mechanism is direct Linux credential
syscalls, never an external privilege tool, because the whole point of the
transition is that the contract can prove which identity the evidence process
really has rather than infer it from a tool's behaviour:

```text
CREDENTIAL_TRANSITION_EFFECT=E1
CREDENTIAL_TRANSITION_EFFECT_DECLARED=true
CREDENTIAL_TRANSITION_MECHANISM=direct_linux_credential_syscalls
CREDENTIAL_TRANSITION_EXTERNAL_PRIVILEGE_TOOL_USED=false
CREDENTIAL_TRANSITION_OPERATION_ORDER=setgroups_then_setgid_then_setuid
CREDENTIAL_TRANSITION_OPERATION_ORDER_IS_MANDATORY=true
CREDENTIAL_TRANSITION_REQUIRED_AUTHORITY=CAP_SETGID,CAP_SETUID
CREDENTIAL_TRANSITION_SUPPLEMENTARY_GROUP_TRANSITION=setgroups_empty_list
CREDENTIAL_TRANSITION_TARGET_SUPPLEMENTARY_GROUP_LIST=empty
CREDENTIAL_TRANSITION_SUPPLEMENTARY_GROUPS_LEFT_IMPLICIT=false
CREDENTIAL_TRANSITION_IDENTITY_REGAIED_AFTER_DROP=false
CREDENTIAL_TRANSITION_POSTCONDITION_UID_TRIPLE_ALL_ORDINARY=true
```

The operation order is mandatory rather than stylistic: `setgroups(2)` is a
`CAP_SETGID` operation, and once `setgid(2)` has changed the effective GID away
from the privileged identity the child no longer holds `CAP_SETGID`, so an
attempt to clear the supplementary group list after the GID transition would fail
with `EPERM`. The supplementary group list is therefore emptied first, and the
declared authority for the effect is exactly `CAP_SETGID` and `CAP_SETUID` —
nothing else, and no `CAP_SETPCAP`: this transition empties a group list and
changes a GID and a UID; it never edits a capability set, because the kernel
clears the permitted, effective and ambient sets by itself when the UID
transition completes.

#### 1.7.3 The mountpoint-creation effect declared

Finding 4 is corrected by declaring the missing creation. It is `E8` in the
closure table, and 5.9 freezes its target object, its descriptor-relative
binding, its exclusive/preexisting-object behaviour, its exact mode, its DAC
authority, its preconditions, its postconditions and its cleanup transition into
the existing mountpoint-removal effect:

```text
MOUNTPOINT_CREATION_EFFECT=E8
MOUNTPOINT_CREATION_EFFECT_DECLARED=true
MOUNTPOINT_CREATION_OPERATION=mkdirat_helper_validated_root_fd_MOUNTPOINT_ROLE
MOUNTPOINT_ROLE_CREATED_BY=reviewed_privileged_helper
MOUNTPOINT_ROLE_EXCLUSIVE_CREATE=true
MOUNTPOINT_ROLE_PREEXISTING_OBJECT_OUTCOME=HELPER_ROOT_REJECTED
MOUNTPOINT_ROLE_S_IMODE=0755
MOUNTPOINT_ROLE_S_IMODE_IS_EXACT=true
MOUNTPOINT_ROLE_OWNER_IS_REVIEWED_PRIVILEGED_IDENTITY=true
MOUNTPOINT_ROLE_ORDINARY_SEARCH_ALLOWED_REQUIRED=true
ROUND7_MOUNTPOINT_ROLE_CREATION_AUTHORITY=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH
ROUND7_MOUNTPOINT_ROLE_CLEANUP_EFFECT=E11
ROUND7_MOUNTPOINT_ROLE_TOKENS_USE_ROUND7_IDS=true
MOUNTPOINT_ROLE_CLEANUP_TRANSITION=remove_mountpoint_role_in_10_4_order
```

`MOUNTPOINT_ROLE_S_IMODE=0755` is not a convenience default. The ordinary
evidence process must reach the mount-case fixture file through this directory to
perform the unprivileged `O_RDONLY` witness that 5.8.3 and 8 step 2 require, and
an owner-only mountpoint would deny that search to the very identity whose
unprivileged read is the attribution guard. `0755` is therefore the mode that
makes the frozen witness reachable while keeping group and world write clear, so
no other identity may create or remove an entry in the mountpoint.

#### 1.7.4 Namespace scope corrected

Findings 2 and 5 are corrected together, because they are the same defect seen
from two directions: the run-scoped label of `E3`/`E4` was what made the
ownership cases appear to need `CAP_SYS_ADMIN`, and the RQP-L17 "required
capability set" named the mount subset while reading as a total.

```text
NAMESPACE_SCOPE_CORRECTED_BY_ROUND7=true
E3_SCOPE=mount-fixture
E4_SCOPE=mount-fixture
NAMESPACE_EFFECTS_ARE_MOUNT_FIXTURE_SCOPED=true
OWNERSHIP_CASE_REQUIRES_PRIVATE_MOUNT_NAMESPACE=false
OWNERSHIP_CASE_REQUIRES_CAP_SYS_ADMIN=false
OWNERSHIP_CASE_PROCESSES_JOIN_A_PRIVATE_MOUNT_NAMESPACE=false
OWNERSHIP_CASE_MOUNT_NAMESPACE_IS_THE_HOST_NAMESPACE=true
RQP_L17_NAMESPACE_ISOLATION_REQUIRED=true
RQP_L17_NAMESPACE_ISOLATION_JUSTIFICATION=mount_events_must_not_reach_the_host_mount_table_and_the_mounted_fixture_must_be_invisible_to_the_host
E3_E4_REQUIRED_BECAUSE_RQP_L17_REQUIRES_THEM=true
OWNERSHIP_CASES_ACQUIRE_CAP_SYS_ADMIN_INCIDENTALLY=false
```

The private mount namespace and the private propagation are required by RQP-L17
and by nothing else. RQP-L17 mounts, detaches and unmounts a real filesystem
inside the run, and 10.3 requires that no such event reach the host mount table.
That requirement is a property of the mount case, so the two namespace effects
belong to the mount case alone. The ownership cases neither mount nor unmount
anything, so they are not wrapped in a namespace they do not need and they do not
acquire `CAP_SYS_ADMIN` merely because the mount fixture needs it. The two
requirements are now stated as separate facts rather than as one shared set.

#### 1.7.5 Case total authority sets derived from the effect table

Finding 5 is closed by deriving each case's total authority set mechanically from
the union of its own effects' required authority, and by replacing the token that
claimed a total while naming a subset:

```text
OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_COUNT=5
OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_COUNT=5
MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_COUNT=5
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
CASE_TOTAL_AUTHORITY_SET_DERIVATION=union_of_that_cases_effect_rows_required_authority
CASE_TOTAL_AUTHORITY_SET_TABLE_TOKEN_EQUIVALENT=true
RQP_L17_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
RQP_L17_MOUNT_OPERATION_CAPABILITY_SET=CAP_SYS_ADMIN
RQP_L17_MOUNT_OPERATION_CAPABILITY_SET_SCOPE=mount-namespace-creation,mount-propagation-private,loop-control-and-configuration,loop-readback,mount-and-unmount
RQP_L17_REQUIRED_CAPABILITY_SET_RETIRED=true
RQP_L17_REQUIRED_CAPABILITY_SET_RETIRED_REASON=it_named_only_the_mount_operation_subset_while_claiming_to_name_the_cases_required_capability_set
NAME_ONLY_THE_MOUNT_SUBSET_IF_SCOPE_IS_MOUNT_SUBSET=true
NAMESPACE_SCOPE_TOKEN_SET_EQUALS_CASE_SCOPE=true
```

The retired `RQP_L17_REQUIRED_CAPABILITY_SET=CAP_SYS_ADMIN` survives only inside
this round's record of what it claimed and why it is withdrawn, exactly as
`OWNERSHIP_FIXTURE_REQUIRED_CAPABILITY_SET` does in 1.6. It is not an active
current-pointer token anywhere in this document.

The mount case's total set excludes `CAP_CHOWN`, and the exclusion is derived
rather than assumed: no mount-case effect performs an ownership call, so no
mount-case effect is bound to `CAP_CHOWN`, so the union of that case's effects
cannot contain it. That is what `MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION=false` and
`MOUNT_FIXTURE_FILE_OWNERSHIP_MUTATION_EFFECT=NONE` mean on the authority side,
and it is why the mount case's total is five capabilities rather than the
ownership cases' five — the two sets are the same size by coincidence and differ
in content by exactly one member:

```text
MOUNT_FIXTURE_TOTAL_AUTHORITY_SET_EXCLUDES_CAP_CHOWN=true
MOUNT_FIXTURE_REQUIRES_CAP_CHOWN=false
MOUNT_FIXTURE_FIXTURE_FILE_REQUIRES_CAP_CHOWN=false
MOUNT_FIXTURE_PERFORMS_NO_OWNERSHIP_MUTATION=true
MOUNT_FIXTURE_EFFECTS_INTERSECT_CAP_CHOWN_EFFECTS=none
MOUNT_FIXTURE_EFFECTS_INTERSECT_CAP_CHOWN_EFFECTS_IS_EMPTY=true
OWNERSHIP_TOTAL_SET_DIFFERS_FROM_MOUNT_TOTAL_SET_BY=CAP_CHOWN_versus_CAP_SYS_ADMIN
CASE_TOTAL_SETS_ARE_COMPUTED_NOT_COPIED=true
```

`RQP_L17_TOTAL_REQUIRED_AUTHORITY_SET` equals
`MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET` because they are the same case under
two names, and that equality is stated rather than left to a reader to notice:

```text
RQP_L17_TOTAL_AUTHORITY_SET_EQUALS_MOUNT_FIXTURE_TOTAL_AUTHORITY_SET=true
GLOBAL_CAPABILITY_INVENTORY_EQUALS_UNION_OF_CASE_TOTAL_AUTHORITY_SETS=true
```

#### 1.7.6 Non-mount effects are common to every case

Two effects that round 6 scoped to one case or labelled run-scoped without
saying so are now stated as what they really are. `E26` is the fixture-object
removal that every case needs — the image and mountpoint for `mount-fixture`, the
mutated fixture file for the ownership cases — and `E26` is the invocation-root
removal that every case needs. Both are performed by the reviewed privileged
identity in every case:

```text
E21_SCOPE=all_cases
E22_SCOPE=all_cases
FIXTURE_OBJECT_REMOVAL_APPLIES_TO_EVERY_CASE=true
INVOCATION_ROOT_REMOVAL_APPLIES_TO_EVERY_CASE=true
OWNERSHIP_CASE_REQUIRES_MOUNT_CASE_EFFECTS=false
MOUNT_FIXTURE_CASE_REQUIRES_OWNERSHIP_ONLY_EFFECTS=false
ROOT_REMOVAL_CASE_AWARE_PRECONDITIONS=false
ROOT_REMOVAL_CASE_AWARE_PRECONDITIONS_WITHDRAWN_BY_ROUND7=true
ROOT_REMOVAL_PRECONDITION_PRIOR_REMOVAL_EFFECTS_COMPLETE=true
ROOT_REMOVAL_CASE_LIFECYCLE_CLOSED=true
```

Round 6 froze `ROOT_REMOVAL_CASE_AWARE_PRECONDITIONS=true` with a different
cleanup step per case. Round 7 withdraws that conditional rather than restoring
it, because the conditionality came from the cleanup sequence having been scoped
to the mount case. With `E26` and `E26` correctly scoped, the root-removal
precondition is the same in all three cases: the case's own removal effect has
completed and the root is empty. A precondition that names an effect the case
really has is simpler than one that branches, and it removes the hazard of a
case-aware precondition silently requiring a mount effect in a case that never
mounts.

#### 1.7.7 Parent-directory access authority

Finding 6 is corrected by splitting the scope explicitly and by observing the
facts that decide the authority instead of asserting the capability:

```text
BELOW_ROOT_ACCESS_AUTHORITY_SCOPE=every_object_at_a_frozen_role_name_under_the_validated_invocation_root
ROOT_PARENT_REMOVAL_ACCESS_AUTHORITY_SCOPE=RUNNER_TEMP_the_validated_invocation_roots_parent_directory
E15_PARENT_ACCESS_CLOSED=true
E15_PARENT_ACCESS_IS_A_ROUND6_TOKEN_WITHDRAWN_BY_ROUND7=true
```

`E26` is the only effect whose target lies outside the invocation root, and its
authority is decided by four observed facts rather than by assumption:
`RUNNER_TEMP`'s owner, its mode, the write-and-search DAC relation between it and
the helper's identity, and its sticky-bit state. 7 freezes those observations as
preflight facts, and the outcome is fail-closed:

```text
RUNNER_TEMP_OWNER_OBSERVED_REQUIRED=true
RUNNER_TEMP_MODE_OBSERVED_REQUIRED=true
RUNNER_TEMP_WRITE_SEARCH_DAC_RELATION_OBSERVED_REQUIRED=true
RUNNER_TEMP_STICKY_BIT_STATE_OBSERVED_REQUIRED=true
RUNNER_TEMP_OBSERVATIONS_ARE_PREFLIGHT_FACTS=true
ROUND7_ROOT_REMOVAL_REQUIRES_CAP_DAC_OVERRIDE_CONDITIONAL_ON_OBSERVED_DAC=true
ROUND7_ROOT_REMOVAL_CONDITIONALITY_WITHDRAWN_BY_ROUND10=true
ROOT_REMOVAL_REQUIRES_CAP_DAC_OVERRIDE=true
ROOT_REMOVAL_AUTHORITY_IS_UNCONDITIONAL=true
ROOT_REMOVAL_SHARED_WRITABLE_PARENT_OUTCOME=QUALIFICATION_GAP_because_the_removal_authority_would_be_non_canonical
ROOT_REMOVAL_DAC_SUFFICIENT_OUTCOME=QUALIFICATION_GAP_the_parent_must_withhold_direct_write_from_the_helper
ROOT_REMOVAL_DAC_INSUFFICIENT_OUTCOME=CAP_DAC_OVERRIDE_required_for_the_removal
ROOT_REMOVAL_STICKY_PARENT_OUTCOME=QUALIFICATION_GAP_because_CAP_FOWNER_is_not_declared
ROOT_REMOVAL_CAP_DAC_OVERRIDE_CLAIMED_WITHOUT_OBSERVATION=false
ROOT_REMOVAL_EMPTINESS_OBSERVATION_AUTHORITY=CAP_DAC_OVERRIDE
ROOT_REMOVAL_PARENT_ENTRY_REMOVAL_AUTHORITY=CAP_DAC_OVERRIDE
ROOT_REMOVAL_OBSERVATION_AND_REMOVAL_SHARE_ONE_MINIMAL_CAPABILITY=true
ROOT_REMOVAL_SINGLE_ROW_IS_CANONICAL=true
ROOT_REMOVAL_OBSERVATION_AND_REMOVAL_SPLIT_REQUIRED=false
```

On the declared runner, `RUNNER_TEMP` is a runner-owned directory in which the
helper identity is an "other"-class user, so its own DAC bits do not authorize
creating or removing an entry there. Round 10 withdraws the conditional framing:
the observed relation is now a *requirement* rather than a selector, because a
single closure row must carry one unconditional, minimal authority. A
`RUNNER_TEMP` that granted the helper identity direct write would make the
declared removal authority unused on that host and would also let an identity the
fixture does not model add or remove entries in the fixture's parent while it
runs, so a shared-writable parent is a `QUALIFICATION_GAP` instead of a second
authority outcome; a sticky `RUNNER_TEMP` is likewise a `QUALIFICATION_GAP`
rather than an undeclared `CAP_FOWNER`. The single capability this row then
declares is unconditional, and splitting the emptiness observation from the
removal is not required (1.10.4):

```text
RUNNER_TEMP_MUST_WITHHOLD_DIRECT_HELPER_WRITE=true
RUNNER_TEMP_SHARED_WRITABLE_IS_A_PREFLIGHT_REFUSAL=true
```

The alternative architecture is recorded and not adopted: the ordinary owner that
created the invocation root could remove the final empty root without any
capability at all. Round 7 does not adopt it, because the root removal is ordered
after the privileged fixtures are removed and the launcher owns the private mount
namespace whose lifetime the cleanup sequence closes; splitting the last step out
to an ordinary process would put the namespace's last member process and the
residue controls in two different lifetimes for no authority saving, since the
removal is already authorized by the observed fact rather than by a broader
grant.

```text
ROOT_REMOVAL_BY_ORDINARY_OWNER_ALTERNATIVE_RECORDED=true
ROOT_REMOVAL_BY_ORDINARY_OWNER_ALTERNATIVE_ADOPTED=false
ROOT_REMOVAL_BY_ORDINARY_OWNER_ALTERNATIVE_REASON=privileged_removal_is_dac_conditional_and_already_narrow_and_the_namespace_lifetime_is_closed_by_one_process
ROOT_REMOVAL_UNNECESSARY_PRIVILEGED_EFFECT_REMAINS=false
```

#### 1.7.8 Image access preconditions and loop target binding

Findings 7 and 8 are corrected in 5.9, and the two are connected: the image
identity the loop device is bound to is the same identity whose mode the format
and the loop configuration rely on.

```text
IMAGE_ACCESS_PRECONDITION_CLOSED=true
IMAGE_ROLE_S_IMODE=0600
IMAGE_ROLE_S_IMODE_IS_EXACT=true
IMAGE_ROLE_OWNER_IS_REVIEWED_HELPER_IDENTITY=true
IMAGE_ROLE_OWNER_WRITE_REQUIRED=true
IMAGE_ROLE_REGULAR_SINGLE_LINK_REQUIRED=true
IMAGE_ROLE_MODE_ESTABLISHED_BY_CREATION_ONLY=true
IMAGE_ROLE_CHMOD_USED=false
IMAGE_ROLE_FCHMOD_USED=false
IMAGE_ROLE_SIZE_BYTES=16777216
IMAGE_ROLE_SIZE_IS_DESIGN_FROZEN=true
IMAGE_ROLE_SIZE_ESTABLISHED_BY=ftruncate_on_the_pinned_image_descriptor
IMAGE_ACCESS_WITNESS_APPLIES_TO_EFFECTS=E20,E19,E7_loop_binding
LOOP_TARGET_BINDING_CLOSED=true
LOOP_TARGET_BINDING_MECHANISM=descriptor_mediated_direct_loop_ioctl
LOOP_TARGET_BINDING_ACCEPTS_PATHNAME=false
LOOP_TARGET_BINDING_RERESOLVES_IMAGE_ROLE_PATH=false
LOOP_TARGET_BINDING_USES_FD_PRESERVING_EXTERNAL_TOOL=false
LOOP_TARGET_BINDING_VERIFIED_AFTER_SETUP=true
LOSETUP_FIND_SHOW_IS_SUFFICIENT_EVIDENCE=false
LOSETUP_PATHNAME_FORM_USED=false
```

`IMAGE_ROLE_S_IMODE=0600` is the exact mode, not a widened one: the image is a
private fixture object, only the reviewed privileged identity ever reads or
writes it, and the ordinary evidence process never opens it. Owner-write is
therefore established by creation, and both the format of `E19` and the loop
binding of `E20` rely on that measured postcondition rather than on an unstated
assumption about a default mode.

#### 1.7.9 Round-7 closure results

```text
ROUND7_RE_EVALUATED_RESULTS=PRIVILEGED_EFFECT_AUTHORITY_CLOSURE,CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY,NAMESPACE_LIFECYCLE_IMPLEMENTABILITY,CLEANUP_STATE_MACHINE_IMPLEMENTABILITY,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
REAL_MATERIAL_EFFECT_COUNT=26
PRIVILEGED_EFFECT_CLOSURE_ROWS=26
REAL_MATERIAL_EFFECT_COUNT_EQ_CLOSURE_ROWS=true
REAL_EFFECT_ROW_COUNT=26
PLACEHOLDER_EFFECT_ROW_COUNT=0
PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
IF_EFFECT_ROW_DECLARES_NO_EFFECT_OUTCOME=NOT_A_MATERIAL_EFFECT
CASE_EFFECT_SCOPE_CLOSED=true
CASE_TOTAL_AUTHORITY_SETS_CLOSED=true
CREDENTIAL_TRANSITION_EFFECT_DECLARED=true
SUPPLEMENTARY_GROUP_SEMANTICS_CLOSED=true
MOUNTPOINT_CREATION_EFFECT_DECLARED=true
E15_PARENT_ACCESS_CLOSED=true
IMAGE_ACCESS_PRECONDITION_CLOSED=true
LOOP_TARGET_BINDING_CLOSED=true
NAMESPACE_SCOPE_CLOSED=true
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
GLOBAL_CAPABILITY_INVENTORY_EQUALS_UNION_OF_REQUIRED_CAPABILITY_AUTHORITIES=true
EVERY_CREATED_OR_MUTATED_OBJECT_HAS_TERMINAL_LIFECYCLE=true
GIT_CURRENT_PARENT_TOKEN_UNIQUE=true
ROUND7_BLOCKING_FINDINGS_CLOSED=9
BLOCKING_FINDINGS_OPEN=0
```

`ROUND6_PLACEHOLDER_EFFECT_ROWS=0` and the round-6 counts inside 1.5 and 1.6
remain as round-6 records of that head and are not current claims about this one.
The current-round effect count and row count are the ones above, and 1.5's table
now has exactly twenty-two rows because the real lifecycle has twenty-one
material effects after the round-7 additions.

```text
ROUND6_COUNTS_ARE_ROUND6_RECORDS=true
ROUND6_COUNTS_ARE_CURRENT_CLAIMS=false
ROUND7_EFFECT_COUNT_SUPERSEDES_ROUND6_COUNT=true
SUPERSEDED_EFFECT_COUNT_TOKENS_KEPT_AS_HISTORY=true
```

### 1.8 Remediation round 8

Round 7's head was independently reviewed and failed with the same failure
class. That failure is preserved here rather than rewritten:

```text
SEVENTH_A3D_REVIEW_FAILED_HEAD=829715ee60bca53a3f02743b19bbab568bc36a74
SEVENTH_A3D_REVIEW_FAILED_TREE=f2173ea4af5ae140eddbaf7c4818adac86f3e485
SEVENTH_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
SEVENTH_A3D_REVIEW_FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
SEVENTH_A3D_REVIEW_RESULT=FAIL
A3D_EIGHTH_REMEDIATION_ROUND=8
A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=8
A3D_HISTORY_ADDITIVE=true
PRODUCT_FAILURE=false
PRIVILEGED_EXECUTION_PERFORMED=false
```

Round 8 changes the same single design document, runs no privileged command, and
touches no production code, so `PRODUCT_FAILURE=false` is a measured statement
here for the same reason rounds 6 and 7 gave.

Round 7's method was to enumerate the real effect set and check the table against
it. That method found missing effects, but it could not find an effect whose
*prerequisites* were wrong, because a row's precondition text was never checked
against the edge set an execution would need. Round 8 therefore adds the
execution dependency graph as a first-class frozen artifact and derives the
table's ordering from it. The independent review named eight blocking findings;
all eight are corrected:

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | The closure table was a set with no dependency graph, and `E12`/`E20` formed a prerequisite cycle: `E12` depended on `E20` while `E20` depended on `E12`. | 1.5, 1.8.1 |
| 2 | `E14` and `E19` both exclusively created `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE`, which is impossible under `O_CREAT\|O_EXCL`. | 1.5, 1.8.2 |
| 3 | The mandatory evidence-side acquisition (`NONROOT_EVIDENCE_PROCESS` open, retained descriptor, positive production admission) was prose only, while helper validation effects were rows \u2014 a mixed granularity. | 1.5, 1.8.3 |
| 4 | 10.1 stated that "the ownership cases have no setup invocation", contradicting `E2`/`E3` and `E4`/`E5`. | 1.8.4, 10.1 |
| 5 | The pre-mount `E8` mountpoint descriptor was used as if it still referred to the mounted ext4 root after `E18`. | 1.5, 1.8.5, 5.9 |
| 6 | `E10` said the pinned `O_CLOEXEC` descriptor was "passed to `mke2fs`" with no implementable carrier. | 1.5, 1.8.6, 5.9 |
| 7 | The credential transition claimed that `setgid` itself clears `CAP_SETGID`, which is false, and its "cannot regain privilege" postcondition was not observed. | 1.5, 1.8.7, 5.10 |
| 8 | Per-effect DAC authority double-counted traversal: `CAP_DAC_READ_SEARCH` was required alongside `CAP_DAC_OVERRIDE`, and remained attached to effects that consume an already-held descriptor. | 1.5, 1.8.8 |

#### 1.8.1 The execution dependency graph

The graph is the ordering authority for this contract, and the closure table's
lifecycle order is its topological order. It is stated as an explicit edge list
so a probe can read it, sort it and fail on a cycle, and it is derived from each
row's preconditions and target identities rather than from the order the rows
happen to appear in.

```text
ROUND8_EFFECT_DEPENDENCY_EDGES_AT_THAT_HEAD=E1:E2,E1:E4,E2:E3,E4:E5,E3:E21,E5:E21,E6:E7,E7:E8,E7:E14,E8:E9,E8:E14,E8:E18,E9:E10,E9:E11,E9:E12,E10:E11,E11:E12,E12:E13,E13:E14,E13:E16,E14:E15,E14:E18,E15:E22,E16:E17,E17:E24,E18:E19,E19:E20,E20:E21,E21:E22,E21:E23,E22:E23,E23:E16,E23:E17,E23:E24,E23:E25,E24:E25,E25:E26
ROUND8_EFFECT_DEPENDENCY_EDGES_ARE_A_ROUND8_RECORD=true
ROUND8_E0_IS_A_SENTINEL_NOT_AN_EFFECT=true
ROUND8_EFFECT_DEPENDENCY_DAG_ACYCLIC_CLAIM=true
ROUND8_EFFECT_DEPENDENCY_DAG_TOPOLOGICAL_SORT_EXISTS_CLAIM=true
ROUND8_EFFECT_DEPENDENCY_EDGES_ARE_DIRECT_CLAIM=true
ROUND8_EVERY_REQUIRED_PRECONDITION_IS_A_DAG_ANCESTOR_CLAIM=true
ROUND8_EFFECT_DEPENDENCY_CYCLE_COUNT=0
ROUND8_EFFECT_DEPENDENCY_EDGES_ARE_MINIMAL_CLAIM=true
ROUND8_EFFECT_DEPENDENCY_EDGES_ARE_OVER=the_twenty_four_material_effects_plus_the_E0_sentinel
ROUND8_EFFECT_DEPENDENCY_DERIVED_FROM=row_preconditions_and_target_identities
ROUND8_EFFECT_DEPENDENCY_GRAPH_IS_THE_ORDERING_AUTHORITY_CLAIM=true
ROUND8_CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER_CLAIM=true
ROUND8_CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER_CLAIM_IS_FALSE=true
ROUND8_EVERY_REQUIRED_PRECONDITION_HAS_A_PREDECESSOR_CLAIM=true
ROUND8_EVERY_EFFECT_HAS_A_PREDECESSOR_EXCEPT_E1=true
```

`E0` is a sentinel standing for the initial state every case starts from \u2014 the
ordinary runner's invocation root, the pre-existing `0644` fixture file in the
ownership cases, and the document filesystem the helper executable is read from.
It is not an effect, it carries no authority, and it is not counted in
`REAL_MATERIAL_EFFECT_COUNT`.

The mount-case loop cluster is the part the round-7 cycle corrupted. Its frozen
order is exactly the sequence the review requires, and each edge is a real
prerequisite rather than a reading order:

```text
ROUND8_LOOP_CLUSTER_ORDER_AT_THAT_HEAD=E9_image_create,E10_format,E11_format_verify,E12_loop_configure,E13_loop_readback_verify,E14_mount
ROUND8_LOOP_CLUSTER_EDGES=E9:E10,E10:E11,E11:E12,E12:E13,E13:E14
ROUND8_LOOP_CLUSTER_EDGES_STALE_E20_CORRECTED_BY_ROUND10=true
ROUND8_LOOP_CONFIGURE_VERIFY_MOUNT_ORDER_CLOSED_CLAIM=true
ROUND8_E7_DEPENDS_ON_E19=false
ROUND8_E7_DEPENDENCY_PREDECESSORS=E11
ROUND8_E7_CLAIMS_E19_READBACK_POSTCONDITION=false
ROUND8_E7_POSTCONDITION_SCOPE=loop_device_configured_with_the_pinned_image_as_its_backing_file
ROUND8_E7_POSTCONDITION_HAS_NO_VERIFICATION_CLAIM=true
ROUND8_E19_DEPENDS_ON_E7=true
ROUND8_E19_DEPENDENCY_PREDECESSORS=E19
ROUND8_E19_POSTCONDITION_SCOPE=backing_identity_read_back_and_required_equal_to_the_pinned_image
ROUND8_E19_IS_THE_ONLY_READBACK_VERIFICATION=true
ROUND8_E15_DEPENDS_ON_E17_VERIFICATION=true
ROUND8_E15_DEPENDENCY_PREDECESSORS=E7,E13,E8,E6
ROUND8_E19_DEPENDENCY_PREDECESSORS=E19
ROUND8_E23_DEPENDENCY_PREDECESSORS=E21,E22
ROUND8_E24_DEPENDENCY_PREDECESSORS=E21
ROUND8_E22_DEPENDENCY_PREDECESSORS=E15,E21
ROUND8_MOUNT_BEFORE_LOOP_VERIFICATION=false
ROUND8_MOUNT_AFTER_LOOP_VERIFICATION=true
ROUND8_MOUNT_DEPENDER_ON_E17_VERIFICATION=E14
ROUND8_ID_TOKENS_IN_1_8_1_ARE_ROUND8_IDS=true
```

`E10` formats, `E11` proves the format landed in the pinned inode, `E12` binds the
loop device to that same inode by descriptor, `E13` proves the device really
carries that inode as its backing file, and only then does `E14` mount it. The
round-7 defect — recorded there with round-7 ids — was that the loop-configuration
row and the format-verification row each named the other: the configuration row's
precondition said the other's format had completed while the verification row's
precondition said the configuration had completed, and the configuration row's
postcondition claimed the other's read-back. Both are corrected: `E12` depends on
`E11`, and every read-back claim lives in `E13` alone.

#### 1.8.2 One exclusive creation for the mount-case fixture file

Round 7 had two rows exclusively create the same object at the same role path
with the same `O_CREAT|O_EXCL` flag, which cannot succeed: the second creation
would fail with `EEXIST` (open(2): "if this flag is specified in conjunction with
`O_CREAT`, and *path* already exists, then `open`() fails with the error
`EEXIST`"). Round 8 removes the duplicate and freezes exactly one creation effect:

```text
MOUNT_CASE_FIXTURE_FILE_CREATION_EFFECT=E20
MOUNT_CASE_FIXTURE_FILE_CREATION_EFFECT_COUNT=1
NO_DUPLICATE_EXCLUSIVE_CREATE_TARGET=true
DUPLICATE_FIXTURE_CREATION_CLOSED=true
ROUND7_DUPLICATE_CREATION_ROWS=E14,E19
ROUND7_DUPLICATE_CREATION_ROWS_RESOLVED_BY=removing_the_second_creation_row
MOUNT_CASE_FIXTURE_FILE_SINGLE_CREATION_ROW=E20
MOUNT_CASE_FIXTURE_FILE_SINGLE_CREATION_TARGET=mounted_root_fd_relative_FIXTURE_FILE_ROLE
MOUNT_CASE_FIXTURE_FILE_CREATION_IS_EXCLUSIVE=true
MOUNT_CASE_FIXTURE_FILE_SECOND_CREATION_ROW_EXISTS=false
MOUNT_CASE_FIXTURE_FILE_PREEXISTING_OBJECT_OUTCOME=CREATION_REFUSED_NOT_ADOPTED
```

Both round-7 rows targeted `MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE`; the surviving row
is the one bound to `mounted_root_fd`, because that is the descriptor that
actually refers to the mounted filesystem. The removed row's `fstat` content is
not lost: the COMMON STRUCTURAL requirements and the mount case's `st_uid == 0`
predicate are now `E11`'s own postcondition, and the mounted root's owner, mode
and ordinary-search facts are `E19`'s observed postcondition.

```text
COMMON_STRUCTURAL_REQUIREMENTS_EFFECT=E20
MOUNT_CASE_ST_UID_PREDICATE_EFFECT=E20
MOUNTED_ROOT_PRE_STATE_EFFECT=E19
MOUNT_CASE_CHILD_PINNED_BY_HELPER_DESCRIPTOR=true
MOUNT_CASE_FIXTURE_FILE_OWNERSHIP_MUTATION=false
```

#### 1.8.3 The evidence-side acquisition is a material lifecycle effect

The acquisition the RQP-L17 mechanism depends on was prose only, while
privileged *validation* effects were table rows: validation was a row and the
mandatory evidence acquisition was not. Round 8 declares it as the material
lifecycle effect `E26`, performed by `NONROOT_EVIDENCE_PROCESS` on every case:

```text
EVIDENCE_ACQUISITION_EFFECT=E21
EVIDENCE_RELEASE_EFFECT=E23
EVIDENCE_RETAINED_DESCRIPTOR_HELD_ACROSS_THE_DETACH=true
EVIDENCE_ACQUISITION_PREDECESSOR_IS_CASE_DEPENDENT=true
EVIDENCE_ACQUISITION_CASE_DEPENDENT_PREDECESSORS=own-foreign:E3;own-root:E5;mount-fixture:E20
EVIDENCE_ACQUISITION_PRECEDES_RELEASE=true
EVIDENCE_RELEASE_PRECEDES_THE_LOOP_RELEASE=true
EVIDENCE_RETAINED_DESCRIPTOR_CLOSED_BY_E23=true
EVIDENCE_DESCRIPTOR_HELD_FROM_E22_UNTIL_E23=true
EVIDENCE_ACQUISITION_EFFECT_DECLARED=true
EVIDENCE_ACQUISITION_LIFECYCLE_CLOSED=true
EVIDENCE_ACQUISITION_EXECUTOR=NONROOT_EVIDENCE_PROCESS
EVIDENCE_ACQUISITION_REQUIRED_AUTHORITY=none
EVIDENCE_ACQUISITION_ACCESS_AUTHORITY=none
EVIDENCE_ACQUISITION_REQUIRES_CAP_EFF_ZERO=true
EVIDENCE_ACQUISITION_OPEN_FLAGS=O_RDONLY|O_NOFOLLOW|O_CLOEXEC
EVIDENCE_ACQUISITION_DESCRIPTOR_RETAINED=true
EVIDENCE_ACQUISITION_HELD_ACROSS_DETACH=true
EVIDENCE_ACQUISITION_POSITIVE_ADMISSION_REQUIRED=true
EVIDENCE_ACQUISITION_IS_A_MATERIAL_EFFECT=true
EVIDENCE_ACQUISITION_COUNTS_IN_REAL_MATERIAL_EFFECT_COUNT=true
MIXED_GRANULARITY_BETWEEN_VALIDATION_ROWS_AND_EVIDENCE_PROSE=false
```

Its operation is the whole evidence sequence the review names, and each step is a
real operation with a real closing point:

```text
EVIDENCE_SEQUENCE=NONROOT_EVIDENCE_PROCESS;real_O_RDONLY_open;retained_descriptor;real_positive_pre_drift_production_admission;descriptor_held_for_MNT_DETACH_evidence
EVIDENCE_ACQUISITION_CHAIN_IS_AN_EFFECT=true
EVIDENCE_ACQUISITION_CHAIN_IS_NOT_ONLY_PROSE=true
EVIDENCE_ACQUISITION_DESCRIPTOR_CLOSED_BEFORE_LOOP_RELEASE=true
EVIDENCE_ACQUISITION_RETAINED_DESCRIPTOR_IS_THE_SECTION_8_STEP_5_DESCRIPTOR=true
```

The descriptor is closed before the loop backing is released, which is why the
graph contains `E26:E15` and `E26:E16`: a loop device with an open reference is
not releasable, so the evidence process cannot still hold the mount when the
cleanup helper tries to release it. That edge is the graph's way of stating the
10.4 ordering rather than repeating it in prose.

The acquisition carries no authority at all, and that is a deliberate,
checkable statement rather than an omission: the row is in the table because it
is material \u2014 it has a target object, a target-binding mechanism, preconditions,
postconditions and a terminal transition \u2014 not because it is privileged. A
closure over privileged effects alone would have to state the same fact as an
exclusion; declaring the row and giving it the empty authority set makes the
exclusion visible and probeable.

#### 1.8.4 One executable order for the ownership cases

Section 10.1 previously said the ownership cases "have no setup invocation",
which is false: `E2`/`E3` and `E4`/`E5` are helper operations that must run
before the evidence process can observe the mutated object. Round 8 replaces that
statement with one exact order:

```text
OWNERSHIP_SETUP_INVOCATION_EXISTS=true
OWNERSHIP_SETUP_LIFECYCLE_CLOSED=true
OWNERSHIP_SETUP_EXECUTOR=PRIVILEGED_FIXTURE_HELPER
OWNERSHIP_SETUP_INVOCATION_COUNT=1
OWNERSHIP_SETUP_INVOCATION_SCOPE=own-foreign,own-root
OWNERSHIP_SETUP_EFFECTS=own-foreign:E2,E3;own-root:E4,E5
OWNERSHIP_SETUP_PRECEDES_EVIDENCE=true
OWNERSHIP_SETUP_PRECEDES_CREDENTIAL_TRANSITION=true
OWNERSHIP_SETUP_AFTER_INVOCATION_ROOT_CREATION=true
OWNERSHIP_SETUP_HELPER_EXITS_BEFORE_CREDENTIAL_TRANSITION=true
OWNERSHIP_SETUP_INVOCATION_ORIGIN=inside_the_same_private_namespace_or_host_namespace_per_10_1
```

The frozen order for `own-foreign` and `own-root` is:

```text
OWNERSHIP_CASE_EXECUTION_ORDER=ordinary_runner_creates_invocation_root_and_0644_fixture;privileged_ownership_setup_helper_performs_E2_E3_or_E4_E5;setup_helper_exits;launcher_forks_credential_transition_child_E1;evidence_process_independently_reacquires_state;production_primitive_E22;cleanup_helper_performs_E21_then_E22_root_removal
OWNERSHIP_CASE_ROOT_CREATED_BY=ordinary_runner
OWNERSHIP_CASE_FIXTURE_CREATED_BY=ordinary_runner
OWNERSHIP_CASE_MUTATION_BY=privileged_ownership_setup_helper
OWNERSHIP_CASE_EVIDENCE_AFTER_SETUP=true
OWNERSHIP_CASE_PRODUCTION_AFTER_CREDENTIAL_TRANSITION=true
OWNERSHIP_CASE_CLEANUP_AFTER_EVIDENCE=true
OWNERSHIP_CASE_NO_SETUP_INVOCATION=false
ROUND7_NO_SETUP_INVOCATION_STATEMENT_WITHDRAWN_BY_ROUND8=true
```

The setup helper performs the ownership mutation only; it performs no mount
operation, creates no fixture object, and exits before the credential transition,
so the mutation and the evidence acquisition are never held by the same process.
The ownership cases differ from the mount case in exactly one respect that the
lifecycle now states instead of omitting: the mount case's setup invocation
creates and formats the fixture, while the ownership cases' setup invocation
mutates a file the ordinary runner already created. Both are one invocation,
before the transition, and both exit before the child changes identity.

#### 1.8.5 Post-mount root acquisition

`E8` pins the `MOUNTPOINT_ROLE` directory as it exists **before** the mount. Once
`E14` attaches a filesystem there, that name no longer resolves to the pinned
inode: a path-based `stat` of the name reports the mounted filesystem's root
instead. Round 7's `E13` reached the mounted root through the pre-mount inode's
descriptor, which silently assumes the descriptor still refers to the mounted
root. Round 8 forbids that and freezes a real post-mount resolution:

```text
POST_MOUNT_ROOT_BINDING_CLOSED=true
POST_MOUNT_ROOT_FD_IS_POST_MOUNT_ACQUIRED=true
POST_MOUNT_ROOT_ACQUISITION_EFFECT=E18
POST_MOUNT_ROOT_ACQUISITION_IS_AFTER_E15=true
POST_MOUNT_ROOT_ACQUISITION_SYSCALL=openat
POST_MOUNT_ROOT_ACQUISITION_BASE=validated_root_descriptor
POST_MOUNT_ROOT_ACQUISITION_NAME=frozen_MOUNTPOINT_ROLE
POST_MOUNT_ROOT_ACQUISITION_FLAGS=O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC
POST_MOUNT_ROOT_ACQUISITION_USES_PRE_MOUNT_DESCRIPTOR_AS_ROOT=false
PRE_MOUNT_MOUNTPOINT_DESCRIPTOR_ROLE=covered_mountpoint_identity_only
PRE_MOUNT_MOUNTPOINT_DESCRIPTOR_USED_FOR_MOUNT_TARGET_REVALIDATION=true
PRE_MOUNT_MOUNTPOINT_DESCRIPTOR_USED_AS_MOUNTED_ROOT=false
```

The acquired descriptor is bound to the expected mounted filesystem by three
measured equalities, and only when all three hold does it become
`mounted_root_fd`:

| Measurement | What it proves | Mismatch outcome |
| --- | --- | --- |
| `fstatfs(2)` on the descriptor reports the ext4 superblock magic `0xEF53` | the descriptor refers to a mounted ext4 filesystem | `QUALIFICATION_GAP` with a design finding |
| `fstat(2)` on the descriptor reports a different `st_dev` from the invocation root's own filesystem | a mount really covers the name rather than the name still resolving to the invocation root | `QUALIFICATION_GAP` with a design finding |
| a fresh resolution of `MOUNTPOINT_ROLE` no longer matches the `st_dev`/`st_ino` `E8` pinned | the mount covers the pinned mountpoint, which is the identity `E14` mounted onto | `QUALIFICATION_GAP` with a design finding |
| the descriptor's own `st_dev`/`st_ino` are recorded as the mounted-root identity | the identity `E19`, `E11` and `E26` depend on is a recorded fact | `QUALIFICATION_GAP` with a design finding |

```text
MOUNTED_ROOT_FD=E16_acquired_descriptor
MOUNTED_ROOT_FD_SOURCE=post_mount_openat_of_the_frozen_role_name
MOUNTED_ROOT_IDENTITY_MEASURED_BY=fstat_st_dev_and_st_ino
MOUNTED_ROOT_FILESYSTEM_PROVED_BY=fstatfs_ext4_superblock_magic_0xEF53
MOUNTED_ROOT_DIFFERS_FROM_INVOCATION_ROOT_FILESYSTEM=true
MOUNTED_ROOT_BINDING_WINDOW=from_the_post_mount_open_to_the_three_measurements
MOUNTED_ROOT_BINDING_WINDOW_IS_CLOSED_BY_THE_THREE_MEASUREMENTS=true
MOUNTED_ROOT_MISMATCH_OUTCOME=QUALIFICATION_GAP_WITH_DESIGN_FINDING
MOUNTED_ROOT_MISMATCH_IS_HELPER_ROOT_REJECTED=false
MOUNTED_ROOT_MISMATCH_IS_PASS=false
MOUNTED_ROOT_MISMATCH_REPAIRED_WITH_PRIVILEGE=false
MOUNTED_ROOT_ACQUISITION_PRECEDES_E20=true
MOUNTED_ROOT_ACQUISITION_PRECEDES_E24=true
MOUNTED_ROOT_ACQUISITION_PRECEDES_E18=false
MOUNTED_ROOT_FD_NOT_RE_RESOLVED_BY_E18=true
MOUNTED_ROOT_FD_NOT_RE_RESOLVED_BY_E20=true
MOUNTED_ROOT_FD_IS_THE_ONLY_BASIS_FOR_THE_MOUNT_CASE_CHILD=true
COVERED_MOUNTPOINT_POSITIVE_EVIDENCE_REQUIRED=true
COVERED_MOUNTPOINT_POSITIVE_EVIDENCE=fresh_resolution_differs_from_the_E6_pinned_identity
```

`E19` and `E11` therefore consume `mounted_root_fd` and resolve no role pathname
at all, which is also why neither of them carries an access authority
(1.8.8).

#### 1.8.6 The formatter descriptor carrier

`E9` pins the image with `O_CLOEXEC`, so that descriptor cannot cross `execve`.
Round 8 freezes an implementable carrier instead of asserting that the descriptor
is "passed to `mke2fs`":

```text
FORMATTER_FD_CARRIER_CLOSED=true
FORMATTER_FD_SOURCE=pinned_E9_image_descriptor
FORMATTER_FD_DERIVATION=dup_the_pinned_descriptor_to_obtain_a_new_descriptor_number
FORMATTER_FD_DERIVATION_SYSCALL=dup
FORMATTER_FD_DERIVATION_KEEPS_THE_SAME_OPEN_FILE_DESCRIPTION=true
FORMATTER_FD_IS_A_NEW_DESCRIPTOR_NUMBER=true
FORMATTER_FD_CLOEXEC_CLEARED=true
FORMATTER_FD_CLOEXEC_CLEARED_BY=fcntl_F_SETFD_with_no_FD_CLOEXEC
FORMATTER_FD_CLOEXEC_CLEARED_EXPLICITLY=true
FORMATTER_FD_LIFETIME=from_the_dup_until_the_formatter_child_exits
FORMATTER_FD_DEVICE_ARGUMENT=/proc/self/fd/<formatter_fd_number>
FORMATTER_FD_DEVICE_ARGUMENT_IS_FD_MEDIATED=true
FORMATTER_FD_DEVICE_ARGUMENT_RESOLVES_THE_CHILDS_OWN_DESCRIPTOR_TABLE=true
FORMATTER_FD_DEVICE_ARGUMENT_IS_NOT_THE_ROLE_PATHNAME=true
FORMATTER_RE_RESOLVES_IMAGE_ROLE_BY_PATHNAME=false
FORMATTER_USES_ORDINARY_ROLE_PATHNAME=false
FORMATTER_CHILD_UNRELATED_DESCRIPTORS=false
FORMATTER_CHILD_UNRELATED_DESCRIPTOR_COUNT=0
FORMATTER_CHILD_FDS=stdin,stdout,stderr,formatter_fd
FORMATTER_CHILD_ALLOWLISTED_DESCRIPTOR_COUNT=4
FORMATTER_FD_PRESENT_IN_CHILD_ALLOWLIST=true
ROUND8_FORMATTER_CHILD_FDS_ARE_THE_STANDARD_STREAMS_ONLY=true
FORMATTER_CHILD_FDS_ARE_THE_STANDARD_STREAMS_ONLY=false
FORMATTER_CHILD_FDS_ARE_THE_STANDARD_STREAMS_AND_THE_FORMATTER_FD=true
FORMATTER_PARENT_CLOSES_FD_AFTER_WAIT=true
FORMATTER_PARENT_CLOSES_FD_BEFORE_E11=true
FORMATTER_FD_CLOSED_BEFORE_LOOP_CONFIGURATION=true
FORMATTER_POST_FORMAT_IDENTITY_VERIFICATION_EFFECT=E11
FORMATTER_POST_FORMAT_IDENTITY_VERIFIED=true
FORMATTER_FD_CARRIER_IS_IMPLEMENTABLE=true
FORMATTER_TOOL=mke2fs_or_mkfs_ext4
FORMATTER_TOOL_IS_EXTERNAL=true
FORMATTER_TOOL_IS_GIVEN_A_DESCRIPTOR_NOT_A_ROLE_PATH=true
FORMATTER_ARGV=mke2fs,-t,ext4,-F,/proc/self/fd/<formatter_fd_number>
FORMATTER_ARGV_IS_FROZEN=true
FORMATTER_ARGV_STRUCTURALLY_EQUIVALENT_TO=mke2fs_-t_ext4_-F_/proc/self/fd/<formatter_fd>
FORMATTER_INVOCATION_IS_EXEC_NOT_SHELL=true
FORMATTER_SHELL_NOT_USED=true
FORMATTER_STDIN_POLICY=/dev/null
FORMATTER_STDIN_IS_NOT_A_TTY=true
FORMATTER_EXECUTION_NONINTERACTIVE=true
FORMATTER_FORCE_FLAG_EQUALS_F=true
FORMATTER_EXIT_STATUS_REQUIRED=0
FORMATTER_NONZERO_EXIT_IS_A_FIXTURE_CONSTRUCTION_FAILURE=true
FORMATTER_EXIT_STATUS_IS_NOT_EVIDENCE=true
FORMATTER_NEVER_RECEIVES_IMAGE_ROLE=true
FORMATTER_CLOSE_CHECKPOINT=E11
FORMATTER_INVOCATION_CLOSED=true
```

The carrier is exact: the parent derives a dedicated descriptor with `dup(2)`
from the pinned `E9` descriptor, clears `FD_CLOEXEC` on that new descriptor only
with `fcntl(F_SETFD, 0)`, passes the child its own `/proc/self/fd/<N>` as the
device argument, waits for the child, and closes the derived descriptor before
`E20` verifies and before the loop is configured. `dup(2)` and the `/proc/self/fd`
path together are what make the claim true rather than assumed: the duplicate
"refers to the same open file description as the original file descriptor"
(open(2), "Open file descriptions"), and the child's own `/proc/self/fd/N` link is
resolved in the child's descriptor table, so the formatter writes the very inode
`E9` created, pinned and identity-recorded, without ever seeing the role name.
The tool's own `chmod`-equivalent operations need no `CAP_FOWNER` because the
helper owns the image, and the formatter performs no ownership change.

The formatter also MUST NOT be given the pre-mount mountpoint descriptor, the
validated root descriptor, or any other fixture descriptor, and the contract
states that as a required observable rather than as an intention:

```text
FORMATTER_CHILD_INHERITS_ONLY_STANDARD_STREAMS_AND_FORMATTER_FD=true
FORMATTER_CHILD_INHERITED_DESCRIPTOR_SET_IS_OBSERVED=true
FORMATTER_CHILD_DESCRIPTOR_LEAK_IS_A_TOOLING_FAILURE=true
```

#### 1.8.7 Credential-transition semantics corrected

Round 7 claimed that the operation order matters because `setgid(2)` removes
`CAP_SETGID` from the child. That claim is false and is withdrawn. The documented
semantics are that `CAP_SETGID` authorizes supplementary-group and GID
manipulation, and that it is the **UID** changes that drive the normal set-ID
capability fixups:

```text
ROUND7_SETGID_CLEARS_CAP_SETGID_CLAIM=false
ROUND7_SETGID_CLEARS_CAP_SETGID_CLAIM_WITHDRAWN_BY_ROUND8=true
CAP_SETGID_AUTHORIZES_SETGROUPS_AND_GID_MANIPULATION=true
CAP_SETGID_IS_CLEARED_BY_A_GID_CHANGE=false
UID_CHANGES_DRIVE_THE_SET_ID_CAPABILITY_FIXUPS=true
CREDENTIAL_TRANSITION_OPERATION_ORDER=setgroups_then_setgid_then_setuid
CREDENTIAL_TRANSITION_ORDER_IS_RETAINED=true
ROUND7_CREDENTIAL_TRANSITION_ORDER_REASON=setgroups_and_setgid_are_deferred_until_after_setuid_would_be_impossible_because_the_uid_transition_clears_the_capability_sets
```

The order is retained, and this is its real reason: the UID transition is the
step that clears the capability sets, so `setgroups(2)` and `setgid(2)` must both
have completed before it. Ordering them as `setgroups` then `setgid` then
`setuid` puts the one capability-clearing step last and leaves no ordering
ambiguity between the two `CAP_SETGID` operations that precede it. A design that
called `setuid` first would have to abandon the group transition entirely,
because after that call the child holds no capability with which to perform it.

```text
CREDENTIAL_TRANSITION_CAPABILITY_CLEARING_STEP=setuid
CREDENTIAL_TRANSITION_CAPABILITY_CLEARING_IS_THE_LAST_STEP=true
CREDENTIAL_TRANSITION_STEPS_BEFORE_CLEARING_ARE_CAP_SETGID_BOUND=true
CREDENTIAL_TRANSITION_ABANDONS_GROUP_TRANSITION_AFTER_UID_CHANGE=false
```

**"Cannot regain privilege" is now observed rather than asserted.** Round 7
claimed the privileged identity was unrecoverable without observing the state that
makes it true. Round 8 freezes what the evidence process must actually measure,
from itself, before the production primitive:

| Observed fact | Source | Required value |
| --- | --- | --- |
| `ACTUAL_CAP_EFF` | `/proc/self/status` `CapEff` | `0` |
| `ACTUAL_CAP_PRM` | `/proc/self/status` `CapPrm` | `0` |
| `ACTUAL_CAP_AMB` | `/proc/self/status` `CapAmb` | `0` |
| `ACTUAL_NO_NEW_PRIVS` | `/proc/self/status` `NoNewPrivs` | `0`, recorded |
| `ACTUAL_SECUREBITS` | `prctl(PR_GET_SECUREBITS)` | observed and recorded; `SECBIT_KEEP_CAPS` clear |

```text
ACTUAL_CAP_PRM_REQUIRED=0
ACTUAL_CAP_EFF_REQUIRED=0
ACTUAL_CAP_AMB_REQUIRED=0
ACTUAL_CAP_PRM_NONZERO_IS_EVIDENCE=false
NONROOT_EVIDENCE_CAP_PRM_REQUIRED=0
NONROOT_EVIDENCE_CAP_AMB_REQUIRED=0
NONROOT_EVIDENCE_SECUREBITS_OBSERVED=true
NONROOT_EVIDENCE_SECUREBITS_SOURCE=prctl_PR_GET_SECUREBITS
NONROOT_EVIDENCE_SECBIT_KEEP_CAPS_REQUIRED_CLEAR=true
NONROOT_EVIDENCE_SECBIT_NO_SETUID_FIXUP_REQUIRED_CLEAR=true
NONROOT_EVIDENCE_NO_NEW_PRIVS_OBSERVED=true
SECUREBITS_VALIDATED_BEFORE_THE_TRANSITION=true
SECUREBITS_VALIDATED_AFTER_THE_TRANSITION=true
SECUREBITS_VALIDATION_POINTS=child_before_setgroups,child_after_setuid,evidence_process_after_execve
SECUREBITS_OBSERVATION_SOURCE=prctl_PR_GET_SECUREBITS
PROC_STATUS_SECBITS_FIELD_REQUIRED=false
SECUREBITS_VALIDATED_BEFORE_TRANSITION=true
SECUREBITS_VALIDATED_AFTER_SETUID=true
SECUREBITS_VALIDATED_AFTER_EXECVE=true
SECUREBITS_UNEXPECTED_OUTCOME=QUALIFICATION_GAP
```

`CapPrm == 0` is required in addition to `CapEff == 0` because a process with a
nonempty permitted set and an empty effective set is still privileged in the
sense that matters here: it can restore effective capabilities without any
privilege transition, so a fixture that admitted it would attribute to the
production primitive an outcome produced by retained privilege. `CapAmb == 0` is
required because ambient capabilities survive `execve` into a non-privileged
program and would otherwise make the launched evidence process privileged in a
way no `setuid` postcondition would show.

The clearing mechanism is named rather than hand-waved, and the contract claims
only what that mechanism is documented to do:

```text
CREDENTIAL_TRANSITION_CLEARING_RULE_1=if_the_real_effective_or_saved_uid_was_zero_and_all_become_nonzero_then_permitted_effective_and_ambient_are_cleared
CREDENTIAL_TRANSITION_CLEARING_RULE_2=if_the_effective_uid_changes_from_zero_to_nonzero_then_the_effective_set_is_cleared
CREDENTIAL_TRANSITION_CLEARING_SOURCE=capabilities(7)_effect_of_user_ID_changes_on_capabilities
CREDENTIAL_TRANSITION_CLAIMS_NO_OTHER_CLEARING=true
CREDENTIAL_TRANSITION_CLEARING_IS_CONFIRMED_BY_MEASUREMENT=true
CREDENTIAL_TRANSITION_CLEARING_IS_NOT_INFERRED_FROM_THE_CALL_SEQUENCE=true
```

Two boundary facts are stated so that the claim is not stronger than the
observation. Capability sets are inherited across `fork(2)`, so the parent
launcher's sets do not by themselves prove anything about the child; the child is
what is measured. And the securebits are inherited, so an unexpected inherited
`SECBIT_KEEP_CAPS` or `SECBIT_NO_SETUID_FIXUP` would defeat the documented
clearing \u2014 which is exactly why they are observed at three points and why an
unexpected value is a `QUALIFICATION_GAP` rather than an assumption that the
defaults hold.

#### 1.8.8 Per-effect DAC authority re-derived

The reviewer's objection is correct and the derivation changes. `CAP_DAC_OVERRIDE`
"bypass[es] file read, write, and execute permission checks", so it already covers
the directory search (execute) check that a name resolution through the
owner-only invocation root performs. Round 7 nevertheless required
`CAP_DAC_READ_SEARCH` alongside it for every such effect, which paid twice for one
check, and kept that requirement attached to effects that no longer resolve a
pathname at all.

```text
ROUND8_PER_EFFECT_AUTHORITY_MINIMALITY_CLOSED_CLAIM=true
ROUND8_PER_EFFECT_AUTHORITY_RE_DERIVED=true
ROUND8_PER_EFFECT_AUTHORITY_IS_MINIMAL_CLAIM=true
CAP_DAC_OVERRIDE_COVERS_TRAVERSAL=true
CAP_DAC_OVERRIDE_COVERS_DIRECTORY_ENTRY_WRITE=true
CAP_DAC_OVERRIDE_SINGLE_CAPABILITY_FOR_BOTH=true
CAP_DAC_READ_SEARCH_ADDED_TO_WRITE_EFFECTS=false
CAP_DAC_READ_SEARCH_RETAINED_FOR_FD_CONSUMING_EFFECTS=false
ROUND8_CAP_DAC_READ_SEARCH_BOUND_EFFECTS=E2,E4,E8,E9,E10,E14,E15,E16,E18,E24,E25,E26
ROUND8_PER_EFFECT_AUTHORITY_MAXIMUM_CAPABILITY_COUNT=2
ROUND8_PER_EFFECT_AUTHORITY_TWO_CAPABILITY_EFFECTS=E1,E8,E9,E14,E15,E16,E18,E24,E25,E26
ROUND8_PER_EFFECT_AUTHORITY_ONE_CAPABILITY_EFFECTS=E2,E3,E4,E5,E6,E7,E10,E12,E13,E17
ROUND8_PER_EFFECT_AUTHORITY_ZERO_CAPABILITY_EFFECTS=E11,E19,E20,E21,E22,E23
ROUND8_AUTHORITY_TOKENS_ARE_A_ROUND8_RECORD=true
```

The audit the review asked for, one row per named effect. The ids in this
table are **round-8 ids**; the id text was renumbered by round 9, so the
table is read with the round-8 meanings it was written with, and the
round-8 id for each effect is given in the last column:

| Effect | What it really does | Pathname resolved? | Round-7 authority | Round-8 authority |
| --- | --- | --- | --- | --- |
| `E8` | `mkdirat` one entry in the invocation root | yes, the root descriptor is already held; the entry write is in a directory the helper does not own | `CAP_DAC_OVERRIDE` + `CAP_DAC_READ_SEARCH` | `CAP_DAC_OVERRIDE` only |
| `E9` | `openat` with `O_CREAT\|O_EXCL` one entry in the invocation root | same | `CAP_DAC_OVERRIDE` + `CAP_DAC_READ_SEARCH` | `CAP_DAC_OVERRIDE` only |
| `E11` | `openat` with `O_CREAT\|O_EXCL` relative to `mounted_root_fd` | no: the descriptor is held, and the directory is owned by the helper | none beyond `E18`'s | none |
| `E24` | `unlinkat` entries in the invocation root | the root descriptor is held; the entry removal is in a directory the helper does not own | `CAP_DAC_OVERRIDE` + `CAP_DAC_READ_SEARCH` | `CAP_DAC_OVERRIDE` only |
| `E26` | performed by the non-root evidence process | no: the process opens the object it is entitled to read | none by construction; the row declared no authority and no access authority | unchanged: none |
| `E12` | loop control and configuration ioctls on the recorded device, with the pinned image descriptor as backing | no: it consumes the `E9` descriptor and the device node path | `CAP_SYS_ADMIN` + `CAP_DAC_READ_SEARCH` | `CAP_SYS_ADMIN` only |
| `E10` | external formatter writes the image through `/proc/self/fd/N` | yes, the `/proc/self/fd/N` path; the containing directory is owner-only | `CAP_DAC_READ_SEARCH` | `CAP_DAC_OVERRIDE` |
| `E15`, `E16` | `umount2` on the frozen mountpoint name | yes, one resolution through the owner-only root | `CAP_SYS_ADMIN` + `CAP_DAC_READ_SEARCH` | `CAP_SYS_ADMIN` + `CAP_DAC_OVERRIDE` |
| `E14` | `mount(2)` on the frozen mountpoint name | yes, one resolution through the owner-only root | `CAP_SYS_ADMIN` + `CAP_DAC_READ_SEARCH` | `CAP_SYS_ADMIN` + `CAP_DAC_OVERRIDE` |
| `E18` | post-mount `openat` of the frozen mountpoint name | yes, one trailing-component resolution against the held root descriptor | (was `E13`: `CAP_DAC_READ_SEARCH`) | `CAP_DAC_OVERRIDE` |
| `E11`, `E13` | ioctls and a read on already-pinned descriptors | no | `CAP_SYS_ADMIN` + `CAP_DAC_READ_SEARCH` for `E20`; none for `E13` | `CAP_SYS_ADMIN` for the loop read-back `E13`; none for `E20` |
| `E2`, `E3`, `E4`, `E5` | `openat` and `fchown` on a descriptor taken from the `O_PATH` root descriptor | no: the root is opened `O_PATH`, which "requires no permissions on the object itself" (open(2)), and the role name is resolved against it once | `CAP_DAC_READ_SEARCH` for `E2`/`E4`, none for `E3`/`E5` | none for all four |

```text
ROUND8_CAP_DAC_READ_SEARCH_BOUND_EFFECTS=E2,E4,E8,E9,E10,E14,E15,E16,E18,E24,E25,E26
ROUND8_CAP_DAC_OVERRIDE_BOUND_EFFECTS=E8,E9,E18,E24,E25,E26
REQUIRED_CAPABILITY_INVENTORY=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
RQP_L17_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
CASE_TOTAL_AUTHORITY_SET_IS_MINIMAL=true
CAPABILITY_INVENTORY_NARROWED_BY_ROUND8_IS_A_ROUND8_RECORD=true
ROUND8_CAPABILITY_INVENTORY_NARROWING=CAP_DAC_READ_SEARCH_removed
CAPABILITY_GRANT_WIDENED_BY_ROUND8_IS_A_ROUND8_RECORD=false
NO_AUTHORITY_IS_BROADER_THAN_ITS_EFFECT=true
```

#### 1.8.9 Round-8 closure results

```text
ROUND8_RE_EVALUATED_RESULTS=PRIVILEGED_EFFECT_AUTHORITY_CLOSURE,CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY,NAMESPACE_LIFECYCLE_IMPLEMENTABILITY,CLEANUP_STATE_MACHINE_IMPLEMENTABILITY,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
EFFECT_DEPENDENCY_DAG_ACYCLIC=true
NO_DUPLICATE_EXCLUSIVE_CREATE_TARGET=true
EVERY_REQUIRED_PRECONDITION_HAS_A_PREDECESSOR=true
MOUNT_BEFORE_LOOP_VERIFICATION=false
OWNERSHIP_SETUP_BEFORE_EVIDENCE=true
POST_MOUNT_ROOT_FD_IS_POST_MOUNT_ACQUIRED=true
FORMATTER_FD_CARRIER_CLOSED=true
PER_EFFECT_AUTHORITY_IS_MINIMAL=true
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
CURRENT_POINTER_KEY_DUPLICATE_VALUE_COUNT=0
REAL_MATERIAL_EFFECT_COUNT=26
PRIVILEGED_EFFECT_CLOSURE_ROWS=26
REAL_EFFECT_ROW_COUNT=26
PLACEHOLDER_EFFECT_ROW_COUNT=0
PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
LOOP_CONFIGURE_VERIFY_MOUNT_ORDER_CLOSED=true
DUPLICATE_FIXTURE_CREATION_CLOSED=true
EVIDENCE_ACQUISITION_LIFECYCLE_CLOSED=true
OWNERSHIP_SETUP_LIFECYCLE_CLOSED=true
POST_MOUNT_ROOT_BINDING_CLOSED=true
FORMATTER_FD_CARRIER_CLOSED=true
CREDENTIAL_TRANSITION_SEMANTICS_CLOSED=true
PER_EFFECT_AUTHORITY_MINIMALITY_CLOSED=true
ROUND8_BLOCKING_FINDINGS_CLOSED=8
BLOCKING_FINDINGS_OPEN=0
```

The round-7 counts and tokens remain inside 1.5 and 1.7 as records of that head
and are not current claims about this one. The current-round effect count is the
one above, and 1.5's table has exactly twenty-two rows because the real lifecycle
has twenty-two material effects after round 8 removes the duplicate creation and
adds the evidence acquisition.

```text
ROUND7_COUNTS_ARE_ROUND7_RECORDS=true
ROUND7_COUNTS_ARE_CURRENT_CLAIMS=false
ROUND8_EFFECT_COUNT_SUPERSEDES_ROUND7_COUNT=true
EFFECT_COUNT_UNCHANGED_BY_ROUND8=true
ROUND8_EFFECT_COUNT_UNCHANGED_REASON=one_row_removed_and_one_row_added
```

### 1.9 Remediation round 9

Round 8's head was independently reviewed and failed with the same failure
class. That failure is preserved here rather than rewritten:

```text
EIGHTH_A3D_REVIEW_FAILED_HEAD=0e0eeaabdee76c828acf63c9651cb8c0ee2f2b2d
EIGHTH_A3D_REVIEW_FAILED_TREE=ba41dcf9e91e0a650b96d371104ba5527794f4cf
EIGHTH_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
EIGHTH_A3D_REVIEW_FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
EIGHTH_A3D_REVIEW_RESULT=FAIL
A3D_NINTH_REMEDIATION_ROUND=9
A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD=9
A3D_HISTORY_ADDITIVE=true
PRODUCT_FAILURE=false
PRIVILEGED_EXECUTION_PERFORMED=false
```

Round 8 corrected the effect *set* but left three structural defects that only a
per-id and per-case check can find: the same ids carried different meanings in
different current sections, one unconditional global edge graph was used where
the cases have different effects, and the successful-detach evidence order was
inverted. The independent review named eight blocking findings; all eight are
corrected.

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | `E17`/`E19`/`E20`/`E21`/`E22`/`E23`/`E24` carried conflicting current meanings, and `CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER=true` was false. | 1.9.1, 1.5 |
| 2 | One unconditional global edge graph served cases with different effect sets. | 1.9.2 |
| 3 | The evidence order was acquisition -> close -> `MNT_DETACH`, but the descriptor exists to survive the detach. | 1.9.3, 1.5, 8 |
| 4 | No row performed the invocation-root removal, and cleanup tokens pointed at rows that remove other objects. | 1.9.4, 1.5, 10.4 |
| 5 | Case sets were edited independently of the rows: mount-only `E21` was in the ownership sets, all-case `E24` was missing, and a count of 5 named six elements. | 1.9.5, 1.5 |
| 6 | `E2`/`E4`'s justification was invalid — `openat` resolves the child name and so performs a directory search — and `E10` still carried an authority from the withdrawn pathname design. | 1.9.6, 1.5 |
| 7 | `/proc/self/prctl(PR_GET_SECUREBITS) was frozen as a securebits observation source. | 1.9.7, 5.10 |
| 8 | The round-8 probes could not detect a current id with a different meaning elsewhere. | 1.9.8, 15.1 |

#### 1.9.1 One canonical effect registry

The registry is the single source of truth for the current head. Every
machine-like token, lifecycle statement, case set, DAG edge, cleanup token,
capability token and prose reference resolves to it, the closure table is
physically ordered by it, and no current-round stale alias survives. Historical
round-qualified records remain, marked as historical and never used as current
pointers.

```text
ROUND9_CANONICAL_EFFECT_REGISTRY=E1..E26
ROUND9_EFFECT_ID_CURRENT_MEANING_UNIQUE_CLAIM=true
ROUND9_CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT_CLAIM=0
ROUND9_CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT_CLAIM_WAS_FALSE=true
ROUND9_CURRENT_EFFECT_REFERENCE_TO_HISTORICAL_MEANING_COUNT_CLAIM=0
ROUND9_CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER_CLAIM=true
ROUND9_CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER_CLAIM_IS_FALSE=true
ROUND9_CLOSURE_TABLE_ORDER_IS_EXECUTION_ORDER_CLAIM=true
ROUND9_CLOSURE_TABLE_ORDER_IS_EXECUTION_ORDER_CLAIM_WITHDRAWN_BY_ROUND10=true
ROUND9_REGISTRY_ORDER_IS_EXECUTION_ORDER_CLAIM=true
ROUND9_REGISTRY_ORDER_IS_EXECUTION_ORDER_CLAIM_WITHDRAWN_BY_ROUND10=true
ROUND9_STALE_CURRENT_ALIAS_RETAINED=false
REGISTRY_ORDER_IS_THE_EFFECT_ID_ORDER_AND_NOT_AN_EXECUTION_ORDER=true
CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER=false
CLOSURE_TABLE_ORDER_IS_EXECUTION_ORDER=false
REGISTRY_ORDER_IS_EXECUTION_ORDER=false
CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT=0
CURRENT_EFFECT_SELF_PRECONDITION_COUNT=0
```

| Id | Current meaning | Scope |
| --- | --- | --- |
| `E1` | credential transition | all cases |
| `E2`, `E3` | `own-foreign` child open, `fchown` | `own-foreign` |
| `E4`, `E5` | `own-root` child open, `fchown` | `own-root` |
| `E6`, `E7` | private mount namespace, private propagation | `mount-fixture` |
| `E8`, `E9` | mountpoint creation, image creation | `mount-fixture` |
| `E10`, `E11` | ext4 formatting, post-format verification | `mount-fixture` |
| `E12`, `E13` | loop configuration, loop read-back verification | `mount-fixture` |
| `E14`, `E15`, `E16` | mount, `MNT_DETACH`, `ATTACHED`-state unmount | `mount-fixture` |
| `E17` | loop backing release | `mount-fixture` |
| `E18`, `E19` | post-mount root acquisition, mounted-root pre-state | `mount-fixture` |
| `E20` | mount-case fixture file creation (the only creation) | `mount-fixture` |
| `E21` | evidence acquisition and positive production admission | all cases |
| `E22` | post-detach production observation | `mount-fixture` |
| `E23` | evidence descriptor release | all cases |
| `E24` | mount-object removal | `mount-fixture` |
| `E25` | fixture-object removal | all cases |
| `E26` | invocation-root removal | all cases |

The current loop sequence uses these ids and no others:

```text
LOOP_CLUSTER_ORDER=E9_image_create,E10_format,E11_format_verify,E12_loop_configure,E13_loop_readback_verify,E14_mount
LOOP_CLUSTER_IDS=E9,E10,E11,E12,E13,E14
```

#### 1.9.2 Per-case executable graphs

A single unconditional edge graph cannot describe cases whose effect sets
differ, and acyclicity of the global union does not prove that any one case is
executable. Each case and each mount branch therefore has its own frozen,
executable edge list, derived from the registry's per-case effect sets.

```text
ROUND9_OWN_FOREIGN_DEPENDENCY_EDGES=E1:E2,E2:E3,E3:E21,E21:E23,E23:E25,E25:E26
ROUND9_OWN_ROOT_DEPENDENCY_EDGES=E1:E4,E4:E5,E5:E21,E21:E23,E23:E25,E25:E26
ROUND9_OWNERSHIP_GRAPHS_PLACED_FIXTURE_SETUP_AFTER_THE_CREDENTIAL_TRANSITION=true
ROUND9_MOUNT_FIXTURE_DETACH_PATH_DEPENDENCY_EDGES=E6:E7,E7:E8,E7:E14,E8:E9,E8:E14,E8:E18,E9:E10,E9:E11,E9:E12,E10:E11,E11:E12,E12:E13,E13:E14,E13:E16,E14:E15,E14:E18,E15:E22,E16:E17,E17:E24,E18:E19,E19:E20,E20:E21,E21:E22,E21:E23,E22:E23,E22:E24,E23:E16,E23:E17,E23:E24,E23:E25,E24:E25,E25:E26
ROUND9_MOUNT_FIXTURE_ATTACHED_FAILURE_PATH_DEPENDENCY_EDGES=E6:E7,E7:E8,E7:E14,E8:E9,E8:E14,E8:E18,E9:E10,E9:E11,E9:E12,E10:E11,E11:E12,E12:E13,E13:E14,E14:E18,E16:E17,E17:E24,E18:E19,E19:E20,E20:E21,E21:E23,E23:E16,E23:E17,E23:E24,E23:E25,E24:E25,E25:E26
ROUND9_MOUNT_GRAPHS_MISS_THE_E21_TO_E15_EDGE=true
ROUND9_MOUNT_GRAPHS_CARRY_THE_E25_NOOP=true
ROUND9_CASE_GRAPHS_ACKNOWLEDGED_AS_A_ROUND9_RECORD=true
```

Every predecessor of an effect in one case's graph belongs to that same case, is
an explicitly common all-case effect, or is a case-qualified predecessor inside
that case's own graph. The `ATTACHED`-failure branch is a separate graph with its
own cleanup ordering: it omits the successful-detach path's `E15`, `E22` and
their edges, so the successful path's evidence edge is never forced onto a
failure that never detached. A mount-fixture-only effect is never an
unconditional predecessor of an ownership effect.

#### 1.9.3 The successful RQP-L17 detach evidence lifecycle

Round 8's order — acquisition, close, then `MNT_DETACH` — defeats the whole
mechanism, because the retained descriptor exists precisely to survive the
detach. The successful drift path is now structurally equivalent to the required
sequence, and the post-detach observation is a material table effect rather than
prose:

```text
EVIDENCE_ACQUISITION_EFFECT=E21
POST_DETACH_OBSERVATION_EFFECT=E22
EVIDENCE_RELEASE_EFFECT=E23
EVIDENCE_DESCRIPTOR_OPEN_AT_DETACH=true
EVIDENCE_DESCRIPTOR_OPEN_DURING_POST_DETACH_PROBE=true
POST_DETACH_PRODUCTION_OBSERVATION_IS_MATERIAL_EFFECT=true
EVIDENCE_RELEASE_AFTER_POST_DETACH_OBSERVATION=true
EVIDENCE_RELEASE_BEFORE_LOOP_RELEASE=true
POST_DETACH_EVIDENCE_BEFORE_DESCRIPTOR_RELEASE=true
SECTION_8_STEPS_5_TO_7_ARE_MATERIAL_EFFECTS=true
SECTION_8_STEPS_5_TO_7_ARE_NOT_PROSE_ONLY=true
```

The frozen order is: non-root acquisition (`E21`) → real positive pre-drift
production admission (`E21`) → retain descriptor (`E21`) → `MNT_DETACH` (`E15`) →
descriptor remains open → post-detach `fstat`/read/`statx` mount-id validation
(`E22`) → `mountinfo` confirms the held mount id absent (`E22`) → second real
production primitive call (`E22`) → require exactly `PLATFORM_UNQUALIFIED`
(`E22`) → only then close the retained descriptor (`E23`) → loop release (`E17`)
→ fixture removal (`E24`, `E25`) → invocation-root removal (`E26`).

```text
ROUND9_RQP_L17_SUCCESS_PATH_ORDER=E21,E15,E22,E23,E17,E24,E25,E26
ROUND9_RQP_L17_ATTACHED_FAILURE_PATH_ORDER=E21,E16,E23,E17,E24,E25,E26
ROUND9_MOUNT_PATH_ORDERS_CARRY_THE_E25_NOOP=true
DESCRIPTOR_CLOSED_BEFORE_THE_OBSERVATION=false
DESCRIPTOR_CLOSED_AFTER_THE_OBSERVATION=true
SECOND_PRODUCTION_CALL_EFFECT=E22
SECOND_PRODUCTION_CALL_RESULT=PLATFORM_UNQUALIFIED_held_mount_missing_or_ambiguous
```

#### 1.9.4 A real invocation-root removal effect

Round 8 had no row that removed the invocation root, while later sections still
attributed that operation to ids whose rows remove `MOUNTPOINT_ROLE`,
`IMAGE_ROLE` or `FIXTURE_FILE_ROLE` instead. `E26` is that row, and it removes a
directory entry from the root's **parent**:

```text
INVOCATION_ROOT_REMOVAL_MATERIAL_EFFECT_EXISTS=true
INVOCATION_ROOT_REMOVAL_EFFECT=E26
FIXTURE_ROOT_RESIDUE_CLOSING_EFFECT=E26
CLEANUP_INVOCATION_ROOT_REMOVAL_EFFECT=E26
CLEANUP_MOUNTPOINT_REMOVAL_EFFECT=E24
CLEANUP_IMAGE_REMOVAL_EFFECT=E24
CLEANUP_FIXTURE_OBJECT_REMOVAL_EFFECT=E25
ROUND9_CLEANUP_MOUNT_CASE_REMOVAL_ORDER=E24_then_E25_then_E26
ROUND9_CLEANUP_OWNERSHIP_CASE_REMOVAL_ORDER=E25_then_E26
ROUND9_CLEANUP_MOUNT_CASE_LOOP_RELEASE_ORDER=E23_then_E17_then_E24_then_E25
ROUND9_CLEANUP_MOUNT_CASE_TOKENS_CONTAIN_THE_E25_NOOP=true
CLEANUP_EFFECT_ID_MAPPING_MATCHES_TABLE=true
ROOT_REMOVAL_TARGET_OBJECT=the_invocation_root_directory_under_RUNNER_TEMP
ROOT_REMOVAL_PARENT_BINDING=descriptor_opened_on_RUNNER_TEMP_and_validated_as_the_real_parent
ROOT_REMOVAL_RUNNER_TEMP_IDENTITY_OBSERVED=true
ROOT_REMOVAL_STICKY_BIT_HANDLING=sticky_parent_is_QUALIFICATION_GAP_because_CAP_FOWNER_is_not_declared
ROUND9_ROOT_REMOVAL_REQUIRED_DAC_AUTHORITY=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH
ROOT_REMOVAL_PRECONDITION_ROOT_EMPTY_AND_VALIDATED=true
ROOT_REMOVAL_POSTCONDITION=FIXTURE_ROOT_RESIDUE_false
```

The root removal is bound to `E26`, whose row removes the invocation root from
its parent, and not to `E24` or `E25`, whose rows remove `MOUNTPOINT_ROLE`,
`IMAGE_ROLE` and `FIXTURE_FILE_ROLE`. `E24` runs before `E25` and `E26` in the
mount case; in the ownership cases `E25` runs before `E26`. The mount case's
`E24` may also remove any fixture object left at a frozen role name after `E23`,
which is what makes `E25`'s mount-case scope honest rather than a forced edge.

#### 1.9.5 Case effect sets regenerated from the row scopes

The case sets are derived from the canonical rows' scope column and are not
edited independently. Round 8 had mount-only `E21` in the ownership sets,
omitted the all-case effect `E24`, and declared a count of 5 for a six-element
set; all three are corrected by regeneration:

```text
OWN_FOREIGN_EFFECT_SET=E1,E2,E3,E21,E23,E25,E26
OWN_ROOT_EFFECT_SET=E1,E4,E5,E21,E23,E25,E26
ROUND9_MOUNT_FIXTURE_EFFECT_SET=E1,E6,E7,E8,E9,E10,E11,E12,E13,E14,E15,E16,E17,E18,E19,E20,E21,E22,E23,E24,E25,E26
OWN_FOREIGN_EFFECT_COUNT=7
OWN_ROOT_EFFECT_COUNT=7
ROUND9_MOUNT_FIXTURE_EFFECT_COUNT=22
UNION_OF_CASE_EFFECT_SETS=E1,E2,E3,E4,E5,E6,E7,E8,E9,E10,E11,E12,E13,E14,E15,E16,E17,E18,E19,E20,E21,E22,E23,E24,E25,E26
DECLARED_CASE_EFFECT_SET_EQUALS_ROWS_WITH_MATCHING_SCOPE=true
DECLARED_CASE_EFFECT_COUNT_EQUALS_SET_CARDINALITY=true
EFFECT_APPEARS_IN_EXACTLY_ITS_INTENDED_CASE_SET=true
CASE_EFFECT_SET_SCOPE_CLOSED=true
CASE_EFFECT_COUNTS_CLOSED=true
```

#### 1.9.6 Access authority re-derived from the actual syscall

`E2` and `E4` keep their `openat` design, and the real minimal search authority
for that design is bound to them: resolving `FIXTURE_FILE_ROLE` relative to the
root descriptor is a directory search and read check, which
`CAP_DAC_READ_SEARCH` covers and `CAP_DAC_OVERRIDE` does not. `CAP_DAC_READ_SEARCH`
is therefore restored to the inventory and recorded honestly. `E10` is re-derived
after its `/proc/self/fd/<N>` carrier was frozen: it needs the search authority
only, and no `CAP_DAC_OVERRIDE`, because its write uses the image's own
owner-write bit and no directory entry is created or removed.

```text
PER_EFFECT_AUTHORITY_RE_DERIVED_BY_ROUND9=true
ROUND9_PER_EFFECT_AUTHORITY_IS_MINIMAL_CLAIM=true
ROUND9_CAP_DAC_READ_SEARCH_BOUND_EFFECTS=E2,E4,E8,E9,E10,E14,E15,E16,E18,E24,E25,E26
ROUND9_CAP_DAC_OVERRIDE_BOUND_EFFECTS=E8,E9,E18,E24,E25,E26
REQUIRED_CAPABILITY_INVENTORY=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
ROUND9_PER_EFFECT_AUTHORITY_ZERO_CAPABILITY_EFFECTS=E11,E19,E20,E21,E22,E23
ROUND9_PER_EFFECT_AUTHORITY_ONE_CAPABILITY_EFFECTS=E2,E3,E4,E5,E6,E7,E10,E12,E13,E17
ROUND9_PER_EFFECT_AUTHORITY_TWO_CAPABILITY_EFFECTS=E1,E8,E9,E14,E15,E16,E18,E24,E25,E26
ROUND9_PER_EFFECT_AUTHORITY_THREE_CAPABILITY_EFFECTS=none
AUTHORITY_BUCKETS_EQUAL_AUTHORITY_E_TOKENS=true
CAPABILITY_BOUND_EFFECT_SETS_EQUAL_AUTHORITY_E_TOKENS=true
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
RQP_L17_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
CAPABILITY_INVENTORY_WIDENED_BY_ROUND9=true
CAPABILITY_WIDENING=CAP_DAC_READ_SEARCH_restored
CAPABILITY_WIDENING_JUSTIFIED_BY_THE_ACTUAL_SYSCALL=true
```

`E8`, `E9`, `E18`, `E24`, `E25` and `E26` need both capabilities because each of
them both resolves a child name through the owner-only root and writes or
removes a directory entry there. No effect needs more than two, and none needs a
capability the table does not bind to at least one effect.

#### 1.9.7 Securebits observation source

`prctl(PR_GET_SECUREBITS)` is the real Linux interface for the securebits, and it
is the only source this contract admits. The `/proc/self/prctl(PR_GET_SECUREBITS) field
is explicitly not required, and the round-8 correction that a GID change does not
clear `CAP_SETGID` — the UID transition drives the normal set-ID capability
fixups — is kept, along with the required observations of `CapPrm`, `CapEff` and
`CapAmb`.

```text
SECUREBITS_OBSERVATION_SOURCE=prctl_PR_GET_SECUREBITS
PROC_STATUS_SECBITS_FIELD_REQUIRED=false
SECUREBITS_VALIDATED_BEFORE_TRANSITION=true
SECUREBITS_VALIDATED_AFTER_SETUID=true
SECUREBITS_VALIDATED_AFTER_EXECVE=true
SECUREBITS_VALIDATION_POINTS=child_before_setgroups,child_after_setuid,evidence_process_after_execve
CAP_SETGID_IS_CLEARED_BY_A_GID_CHANGE=false
UID_CHANGES_DRIVE_THE_SET_ID_CAPABILITY_FIXUPS=true
SECUREBITS_OBSERVATION_SOURCE_IS_PRCTL=true
```

#### 1.9.8 Semantic probes

The round-8 suite could count rows and sort a global graph but could not detect a
current id carrying a different meaning in another current section. Round 9's
suite adds the checks the review requires: it resolves every semantic token
against the registry, sorts every case and branch graph, derives the case sets
from the row scope column and compares them to the declared sets, and walks the
detach-evidence order edge by edge. A current id with a different meaning
anywhere, a case graph that does not sort, a cross-case predecessor leak, or a
cleanup token naming a row that removes a different object each fail the suite.

```text
ROUND9_PROBE_REQUIRED_CHECKS=16
ROUND9_SEMANTIC_PROBE_RESULT=PASS
ROUND9_SEMANTIC_PROBE_SUITE_MISSED_THE_ROUND10_BLOCKERS=true
ROUND9_PROBE_SUITE_CHECKS_ONLY_REGISTRY_TOKENS_AND_NOT_ROW_TEXT=true
ROUND9_PROBE_FAIL_COUNT=0
GLOBAL_DAG_ACYCLIC=true
EVERY_CASE_DAG_ACYCLIC=true
EVERY_CASE_DAG_EXECUTABLE=true
CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT=0
CROSS_CASE_PREDECESSOR_LEAK_COUNT=0
CASE_EFFECT_SET_EQUALS_ROW_SCOPE_DERIVATION=true
CASE_EFFECT_COUNT_EQUALS_SET_CARDINALITY=true
EVIDENCE_DESCRIPTOR_OPEN_AT_DETACH=true
POST_DETACH_EVIDENCE_BEFORE_DESCRIPTOR_RELEASE=true
INVOCATION_ROOT_REMOVAL_MATERIAL_EFFECT_EXISTS=true
CLEANUP_EFFECT_ID_MAPPING_MATCHES_TABLE=true
AUTHORITY_BUCKETS_EQUAL_AUTHORITY_E_TOKENS=true
CAPABILITY_BOUND_EFFECT_SETS_EQUAL_AUTHORITY_E_TOKENS=true
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
NO_DUPLICATE_EXCLUSIVE_CREATE_TARGET=true
CURRENT_POINTER_KEY_DUPLICATE_VALUE_COUNT=0
```

#### 1.9.9 Round-9 closure results

```text
ROUND9_RE_EVALUATED_RESULTS=PRIVILEGED_EFFECT_AUTHORITY_CLOSURE,CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY,NAMESPACE_LIFECYCLE_IMPLEMENTABILITY,CLEANUP_STATE_MACHINE_IMPLEMENTABILITY,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
REAL_MATERIAL_EFFECT_COUNT=26
PRIVILEGED_EFFECT_CLOSURE_ROWS=26
REAL_EFFECT_ROW_COUNT=26
PLACEHOLDER_EFFECT_ROW_COUNT=0
PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS
CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY=PASS
NAMESPACE_LIFECYCLE_IMPLEMENTABILITY=PASS
PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS
A3_CONTRACT_IMPLEMENTABILITY=PASS
ROUND9_BLOCKING_FINDINGS_CLOSED=8
BLOCKING_FINDINGS_OPEN=0
ROUND8_COUNTS_ARE_ROUND8_RECORDS=true
ROUND8_COUNTS_ARE_CURRENT_CLAIMS=false
ROUND8_EFFECT_COUNT_WAS_24=true
ROUND9_EFFECT_COUNT_IS_26=true
EFFECT_COUNT_DELTA_BY_ROUND9=two_effects_added_and_no_effect_removed
```

Round 8's counts inside 1.5, 1.7 and 1.8 remain as records of those heads and are
not current claims about this one. The current-round effect count is the one
above, and 1.5's table has exactly twenty-six rows.

### 1.10 Remediation round 10

Round 9's head was independently reviewed and failed with the same failure class.
That failure is preserved here rather than rewritten, and it is the head this
round's own commit corrects:

```text
NINTH_A3D_REVIEW_FAILED_HEAD=be714a250ede2b286913fcb0fe9a5415231cdf08
NINTH_A3D_REVIEW_FAILED_TREE=85891ce9cf435c4f1721f8e2729e8c19a51f2b8c
NINTH_A3D_REVIEW_FAILURE=CONTRACT_IMPLEMENTABILITY_FAILURE
NINTH_A3D_REVIEW_FAILURE_CLASS=CONTRACT_IMPLEMENTABILITY_FAILURE
NINTH_A3D_REVIEW_RESULT=FAIL
A3D_TENTH_REMEDIATION_ROUND=10
A3D_CURRENT_REMEDIATION_ROUND=10
A3D_HISTORY_ADDITIVE=true
PRODUCT_FAILURE=false
PRIVILEGED_EXECUTION_PERFORMED=false
```

Round 9 made one registry authoritative in name but not in fact, and the
independent review found eleven blocking defects that only row-level and
lifecycle-level checks can see: the closure table kept its own stale numbering
inside its own cells and in several normative sections, the case graphs were
still derived from the table rather than from the actor lifecycle, the successful
detach path was missing the edge that orders the detach after the evidence
acquisition, the `ATTACHED` failure branch was unreachable, the cross-process
detach had no frozen protocol or boundary rows, the access authority was derived
from a false statement about one kernel check, the mount case still carried a
no-op removal effect, and the formatter invocation was never actually closed.
All eleven are corrected in this round.

| # | Finding | Corrected in |
| --- | --- | --- |
| 1 | The registry was declared authoritative while the closure table's own cells and several normative sections still used earlier rounds' ids; the self-precondition set was non-empty and the mismatch count was not zero. | 1.10.1, 1.5 |
| 2 | The case graphs were still the table's order, not the real actor lifecycle: ownership fixture setup was placed after the credential transition and the mount-case setup was not ordered before it. | 1.10.2, 1.5, 1.9.2 |
| 3 | The successful detach path had no `E21 -> E15` edge, so nothing ordered the detach after the evidence acquisition and positive admission. | 1.10.2, 1.5 |
| 4 | The `ATTACHED` failure branch was not reachable from the failure it describes, so its cleanup order could not be entered at all. | 1.10.2, 1.5, 10.4 |
| 5 | The cross-process detach and resume had no frozen protocol, no completion carrier and no boundary-ledger rows. | 1.10.3, 5.2, 5.6, 10.1 |
| 6 | The access authority rested on the false claim that child-name resolution performs a directory read check and that `CAP_DAC_OVERRIDE` does not bypass directory read checks. | 1.10.4, 1.5 |
| 7 | The mount case still declared a fixture-object removal effect that removes nothing, which is a no-op row rather than a material effect. | 1.10.5, 1.5, 10.4 |
| 8 | The formatter invocation was described but not closed: no frozen argv, an incomplete child descriptor allowlist, an inconsistent descriptor count, a stale close checkpoint and no non-interactive guarantee. | 1.10.6, 1.8.6, 5.9 |
| 9 | The round-9 probe suite could not detect any of the defects above, because it compared registry tokens rather than the table's own text and accepted mere acyclicity. | 1.10.7, 15.1 |
| 10 | The implementability results were carried forward without re-evaluation against the corrected statements. | 1.10.8, 15.1 |
| 11 | The lifecycle record's single bare current-round parent pointer still named round 7's parent. | 20 |

#### 1.10.1 The registry is the only current effect authority

The registry in 1.9.1 is the single current authority for what each effect id
means. The closure table in 1.5 is the per-effect closure instance of that
registry; its row order is the registry's id order and nothing else. Round 9
claimed two things about that order that are false and are withdrawn: the table
is not in topological order (no single order can be, because `E1` follows `E2`,
`E3`, `E4`, `E5` and `E20` in the ownership and mount cases while the registry
lists it first), and it is not an execution order for any case. Each case's
executable order is its own graph in 1.10.2 and 1.5.

The rows were repaired rather than reinterpreted: every id inside a row's
operation, target, binding, authority, precondition, postcondition and cleanup
text was re-derived against the registry, every stale alias was replaced, and the
eight rows that named themselves as their own predecessor or successor
(`E11`, `E13`, `E14`, `E17`, `E20`, `E23`, `E24`, `E25`) were corrected. The round-9 record keeps its own
claims under round-qualified names, including the two claims that were false:

```text
CANONICAL_EFFECT_REGISTRY_IS_THE_ONLY_CURRENT_EFFECT_AUTHORITY=true
CANONICAL_EFFECT_REGISTRY_ROUND=9
CANONICAL_EFFECT_REGISTRY_SOURCE=1.9.1
CLOSURE_TABLE_IS_THE_PER_EFFECT_INSTANCE_OF_THE_REGISTRY=true
CLOSURE_TABLE_ORDER_IS_THE_REGISTRY_ID_ORDER=true
CLOSURE_TABLE_ORDER_IS_A_TOPOLOGICAL_ORDER=false
CLOSURE_TABLE_ORDER_IS_EXECUTION_ORDER=false
REGISTRY_ORDER_IS_EXECUTION_ORDER=false
EFFECT_ID_CURRENT_MEANING_UNIQUE=true
CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT=0
CURRENT_EFFECT_SELF_PRECONDITION_COUNT=0
ROUND9_CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT_CLAIM_WAS_FALSE=true
ROUND9_ORDER_AND_EXECUTION_ORDER_CLAIMS_WITHDRAWN_BY_ROUND10=true
STALE_CURRENT_ALIAS_RETAINED=false
ROUND10_ID_REPAIRS_IN_THE_CLOSURE_TABLE=every_row_re_derived_against_the_1_9_1_registry
ROUND10_STALE_SECTION_REFERENCES_REPAIRED=5.9_and_7_and_15.1_and_16
```

#### 1.10.2 Case graphs rebuilt from the real actor lifecycle

The graphs are derived from which process performs each effect and when that
process exists, not from the table's row order. Three lifecycle facts had been
misplaced and are corrected here:

- the ownership fixture setup (`E2`/`E3` or `E4`/`E5`) is performed by a
  privileged helper invocation that runs and exits **before** the credential
  transition, because the fixture file it mutates must already exist and be owned
  by the ordinary runner before the evidence process is created; `E1` therefore
  follows the setup, not the reverse;
- the mount-case setup (`E6` .. `E20`) is likewise performed by a privileged
  invocation, and the mount case's file cannot exist before the image is mounted,
  so the whole setup precedes `E1`;
- the successful detach path orders the detach after the evidence acquisition and
  its positive admission (`E21 -> E15`), because the retained descriptor and the
  recorded mount id are what the detach evidence is about.

The `ATTACHED` failure branch is now enterable from the two states in which
cleanup can begin while the mount is still attached, and its order depends on
whether the evidence process already holds its descriptor:

```text
OWNERSHIP_SETUP_PRECEDES_CREDENTIAL_TRANSITION=true
OWNERSHIP_SETUP_BEFORE_E1=true
MOUNT_CASE_SETUP_PRECEDES_CREDENTIAL_TRANSITION=true
MOUNT_SETUP_BEFORE_E1=true
MOUNT_CASE_DAG_CONTAINS_E1=true
CREDENTIAL_TRANSITION_IS_AFTER_EVERY_PIECE_OF_FIXTURE_SETUP=true
OWN_FOREIGN_REQUIRED_ORDER=E2,E3,E1,E21,E23,E25,E26
OWN_ROOT_REQUIRED_ORDER=E4,E5,E1,E21,E23,E25,E26
MOUNT_FIXTURE_SUCCESS_REQUIRED_ORDER=E6,E7,E8,E9,E10,E11,E12,E13,E14,E18,E19,E20,E1,E21,E15,E22,E23,E17,E24,E26
ATTACHED_NO_EVIDENCE_DESCRIPTOR_REQUIRED_ORDER=E16,E17,E24,E26
ATTACHED_WITH_EVIDENCE_DESCRIPTOR_REQUIRED_ORDER=E23,E16,E17,E24,E26
E1_BEFORE_E21=true
E2_BEFORE_E3_BEFORE_E1=true
E4_BEFORE_E5_BEFORE_E1=true
E20_BEFORE_E1=true
E21_BEFORE_E15=true
E15_BEFORE_E22=true
E22_BEFORE_E23=true
E16_BEFORE_E17=true
E23_BEFORE_E16=true
E17_BEFORE_E24=true
E24_BEFORE_E26=true
ATTACHED_FAILURE_BEFORE_E21_CLEANUP_REACHABLE=true
ATTACHED_FAILURE_DURING_E21_CLEANUP_REACHABLE=true
ATTACHED_FAILURE_ENTRY_STATES=E16,E23
EVERY_CASE_DAG_ACYCLIC=true
EVERY_CASE_DAG_EXECUTABLE=true
EVERY_CASE_EFFECT_PREDECESSOR_EXISTS_IN_THAT_CASE=true
CROSS_CASE_PREDECESSOR_LEAK_COUNT=0
CASE_QUALIFIED_PREDECESSORS_ALLOWED=true
GLOBAL_DAG_IS_THE_UNION_OF_THE_CASE_DAGS=true
GLOBAL_DAG_ACYCLIC=true
EVERY_CASE_DAG_EDGE_IS_A_REAL_LIFECYCLE_PREREQUISITE=true
CASE_GRAPH_DERIVED_FROM=the_actor_lifecycle_of_10_1_and_the_row_preconditions
CASE_GRAPH_NOT_DERIVED_FROM_THE_CLOSURE_TABLES_ORDER=true
```

#### 1.10.3 The frozen cross-process detach and resume protocol

The successful `mount-fixture` path needs a privileged `MNT_DETACH` while an
unprivileged process holds the descriptor whose survival is the evidence. 10.1
now freezes that protocol as two separate synchronous helper invocations
requested by the live evidence process, 5.2 freezes what each invocation must
validate, and 5.6 carries the four boundary rows:

```text
CROSS_PROCESS_DETACH_RESUME_PROTOCOL_FROZEN=true
DETACH_HELPER_COMPLETION_CARRIER_DECLARED=true
DETACH_HELPER_COMPLETION_IS_NOT_EVIDENCE=true
EVIDENCE_PROCESS_SURVIVES_DETACH_HELPER=true
EVIDENCE_DESCRIPTOR_HELD_ACROSS_THE_DETACH_HELPER=true
MOUNT_STATE_IS_INDEPENDENTLY_REACQUIRED_AFTER_THE_DETACH_HELPER=true
FINAL_CLEANUP_HELPER_AFTER_E23=true
CROSS_BOUNDARY_DETACH_ROWS=T11,T12,T13,T14
EVERY_DETACH_AND_CLEANUP_BOUNDARY_ROW_HAS_A_CLOSING_CHECKPOINT=true
EVERY_DETACH_AND_CLEANUP_BOUNDARY_ROW_NAMES_A_NAMESPACE_IDENTITY_VALIDATION=true
```

#### 1.10.4 Access authority re-derived from the real permission checks

Round 9 restored `CAP_DAC_READ_SEARCH` for the right reason in one case and the
wrong reason in another, and applied it too widely. The real semantics, read for
this round from the Linux kernel source (`fs/namei.c`, `generic_permission` and
`may_lookup`/`lookup_inode_permission_may_exec`) together with the
`capabilities(7)` text this contract already cites, are:

- resolving a child name against a directory descriptor is a **search** check:
  the directory component walk masks the permission check with `MAY_EXEC` and
  performs no read check on the directory;
- for a directory inode, `CAP_DAC_READ_SEARCH` bypasses the check when the mask
  contains no `MAY_WRITE`, and `CAP_DAC_OVERRIDE` bypasses it for **any** mask,
  including `MAY_READ` and `MAY_WRITE`;
- for a non-directory inode, `CAP_DAC_READ_SEARCH` applies only when the mask is
  exactly `MAY_READ`, while `CAP_DAC_OVERRIDE` covers read and write and covers
  execute only when at least one execute bit is set.

The binding therefore follows minimality rather than a missing check:

```text
ROUND10_AUTHORITY_PROVENANCE=DOCUMENTED
ROUND10_AUTHORITY_PROVENANCE_SOURCE=linux_fs_namei_c_generic_permission_and_may_lookup_and_capabilities7
ROUND10_AUTHORITY_PROVENANCE_IS_PROBED=false
NAME_RESOLUTION_DIRECTORY_CHECK_IS_MAY_EXEC_ONLY=true
CHILD_NAME_RESOLUTION_PERFORMS_A_DIRECTORY_READ_CHECK=false
GENERIC_PERMISSION_DIRECTORY_BRANCH_BYPASSES_ANY_MASK_FOR_CAP_DAC_OVERRIDE=true
GENERIC_PERMISSION_NON_DIRECTORY_BRANCH_REQUIRES_MASK_EQ_MAY_READ_FOR_CAP_DAC_READ_SEARCH=true
CAP_DAC_READ_SEARCH_IS_THE_MINIMAL_CAPABILITY_FOR_SEARCH_ONLY_EFFECTS=true
CAP_DAC_OVERRIDE_IS_REQUIRED_WHERE_A_DIRECTORY_ENTRY_IS_WRITTEN_OR_REMOVED=true
CAP_DAC_OVERRIDE_IS_NOT_PAIRED_WITH_CAP_DAC_READ_SEARCH_ON_ONE_CHECK=true
PER_EFFECT_AUTHORITY_RE_DERIVED_BY_ROUND10=true
PER_EFFECT_AUTHORITY_IS_MINIMAL=true
PER_EFFECT_AUTHORITY_MINIMALITY_CLOSED=true
PER_EFFECT_AUTHORITY_MAXIMUM_CAPABILITY_COUNT=2
CAP_DAC_READ_SEARCH_BOUND_EFFECTS=E2,E4,E14,E15,E16,E18
CAP_DAC_OVERRIDE_BOUND_EFFECTS=E8,E9,E24,E25,E26
PER_EFFECT_AUTHORITY_ZERO_CAPABILITY_EFFECTS=E10,E11,E19,E20,E21,E22,E23
PER_EFFECT_AUTHORITY_ONE_CAPABILITY_EFFECTS=E2,E3,E4,E5,E6,E7,E8,E9,E12,E13,E17,E18,E24,E25,E26
PER_EFFECT_AUTHORITY_TWO_CAPABILITY_EFFECTS=E1,E14,E15,E16
PER_EFFECT_AUTHORITY_THREE_CAPABILITY_EFFECTS=none
AUTHORITY_E2=CAP_DAC_READ_SEARCH
AUTHORITY_E4=CAP_DAC_READ_SEARCH
AUTHORITY_E8=CAP_DAC_OVERRIDE
AUTHORITY_E9=CAP_DAC_OVERRIDE
AUTHORITY_E10=none
AUTHORITY_E14=CAP_SYS_ADMIN,CAP_DAC_READ_SEARCH
AUTHORITY_E15=CAP_SYS_ADMIN,CAP_DAC_READ_SEARCH
AUTHORITY_E16=CAP_SYS_ADMIN,CAP_DAC_READ_SEARCH
AUTHORITY_E18=CAP_DAC_READ_SEARCH
AUTHORITY_E24=CAP_DAC_OVERRIDE
AUTHORITY_E25=CAP_DAC_OVERRIDE
AUTHORITY_E26=CAP_DAC_OVERRIDE
AUTHORITY_TABLE_EQUALS_AUTHORITY_E_TOKENS=true
REQUIRED_CAPABILITY_INVENTORY=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
REQUIRED_CAPABILITY_COUNT=6
CAPABILITY_INVENTORY_CHANGED_BY_ROUND10=false
CAP_DAC_READ_SEARCH_BINDING_NARROWED_BY_ROUND10=true
CAP_DAC_OVERRIDE_BINDING_NARROWED_BY_ROUND10=true
NO_CAPABILITY_IS_PAID_FOR_TWICE_ON_ONE_CHECK=true
NO_EFFECT_DECLARES_A_CAPABILITY_ITS_OPERATION_DOES_NOT_NEED=true
ROOT_REMOVAL_REQUIRED_DAC_AUTHORITY=CAP_DAC_OVERRIDE
ROOT_REMOVAL_EMPTINESS_OBSERVATION_AUTHORITY=CAP_DAC_OVERRIDE
ROOT_REMOVAL_PARENT_ENTRY_REMOVAL_AUTHORITY=CAP_DAC_OVERRIDE
ROOT_REMOVAL_OBSERVATION_AND_REMOVAL_SHARE_ONE_MINIMAL_CAPABILITY=true
ROOT_REMOVAL_OBSERVATION_AND_REMOVAL_SPLIT_REQUIRED=false
ROOT_REMOVAL_SINGLE_ROW_IS_CANONICAL=true
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
CASE_TOTAL_AUTHORITY_SET_IS_MINIMAL=true
OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
MOUNT_CASE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
RQP_L17_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
CASE_TOTAL_AUTHORITY_SETS_UNCHANGED_BY_ROUND10=true
CASE_TOTAL_AUTHORITY_SETS_UNCHANGED_REASON=the_bindings_changed_but_every_case_union_did_not
```

The per-effect derivation, one row per effect, is the authority column of the
closure table in 1.5; the case unions above are its union and are unchanged from
round 9, which is why this round narrows bindings without granting or removing a
capability anywhere.

#### 1.10.5 The mount case has no fixture-object removal no-op

`E25` removes the ownership cases' fixture file. The mount case has no object for
it: both of its fixture objects, the mountpoint directory and the image file, are
removed by `E24`, which is the effect that owns those two names. Round 9 kept
`E25` in the mount case's effect set and in its cleanup order as a conditional
"if any remain" step, which is not a material effect in that case and cannot have
a target, a binding or a postcondition there. The mount-case scope is removed:

```text
E25_SCOPE=own-foreign,own-root
MOUNT_FIXTURE_EFFECT_SET_CONTAINS_E25=false
MOUNT_CASE_E25_NOOP_COUNT=0
MOUNT_CASE_FIXTURE_OBJECT_REMOVAL_EFFECT=E24
MOUNT_CASE_REMOVAL_ORDER=E24,E26
DUPLICATE_CLEANUP_TARGET_COUNT=0
EVERY_CASE_EFFECT_IS_MATERIAL=true
EVERY_CASE_EFFECT_HAS_A_TARGET_IN_ITS_CASE=true
PLACEHOLDER_EFFECT_ROW_COUNT=0
PLACEHOLDER_EFFECT_ROW_ACCEPTED=false
REAL_MATERIAL_EFFECT_COUNT=26
PRIVILEGED_EFFECT_CLOSURE_ROWS=26
MOUNT_FIXTURE_EFFECT_COUNT=21
OWN_FOREIGN_EFFECT_COUNT=7
OWN_ROOT_EFFECT_COUNT=7
```

#### 1.10.6 The formatter invocation closed

The carrier was frozen in round 8 and the effect's authority is corrected in
1.10.4, but the invocation itself was never closed: the contract did not state an
argument vector, counted three unrelated descriptors in the child while omitting
the formatter descriptor, and pointed its close checkpoint at an id that no
longer means the post-format verification. The invocation is now frozen exactly
as 1.8.6 and 5.9 state it:

```text
FORMATTER_ARGV=mke2fs,-t,ext4,-F,/proc/self/fd/<formatter_fd_number>
FORMATTER_ARGV_STRUCTURALLY_EQUIVALENT_TO=mke2fs_-t_ext4_-F_/proc/self/fd/<formatter_fd>
FORMATTER_INVOCATION_IS_EXEC_NOT_SHELL=true
FORMATTER_SHELL_NOT_USED=true
FORMATTER_CHILD_FDS=stdin,stdout,stderr,formatter_fd
FORMATTER_CHILD_ALLOWLISTED_DESCRIPTOR_COUNT=4
FORMATTER_CHILD_UNRELATED_DESCRIPTOR_COUNT=0
FORMATTER_CHILD_UNRELATED_DESCRIPTORS=false
FORMATTER_FD_PRESENT_IN_CHILD_ALLOWLIST=true
FORMATTER_CHILD_FDS_ARE_THE_STANDARD_STREAMS_AND_THE_FORMATTER_FD=true
FORMATTER_CHILD_INHERITS_ONLY_STANDARD_STREAMS_AND_FORMATTER_FD=true
FORMATTER_STDIN_POLICY=/dev/null
FORMATTER_STDIN_IS_NOT_A_TTY=true
FORMATTER_EXECUTION_NONINTERACTIVE=true
FORMATTER_FORCE_FLAG_EQUALS_F=true
FORMATTER_EXIT_STATUS_REQUIRED=0
FORMATTER_NONZERO_EXIT_IS_A_FIXTURE_CONSTRUCTION_FAILURE=true
FORMATTER_EXIT_STATUS_IS_NOT_EVIDENCE=true
FORMATTER_CLOSE_CHECKPOINT=E11
FORMATTER_PARENT_CLOSES_FD_BEFORE_E11=true
FORMATTER_FD_CLOSED_BEFORE_LOOP_CONFIGURATION=true
FORMATTER_NEVER_RECEIVES_IMAGE_ROLE=true
FORMATTER_RE_RESOLVES_IMAGE_ROLE_BY_PATHNAME=false
FORMATTER_INVOCATION_CLOSED=true
FORMATTER_DESCRIPTOR_COUNT_TOKENS_ARE_CONSISTENT=true
```

#### 1.10.7 Semantic completion probes

Round 9's suite compared registry tokens and accepted any acyclic edge list, so it
passed while every defect of this round was present. The round-10 obligations are
stated in 15.1 and are run over this document before the commit. They parse the
closure table's own cells, the unqualified token blocks and the case graphs, and
they fail on a self-precondition, on any topological order in which `E15`
precedes `E21`, and on an edge list that is merely acyclic:

```text
ROUND10_PROBE_REQUIRED_CHECKS=14
ROUND10_SEMANTIC_PROBE_RESULT=PASS
ROUND10_PROBE_FAIL_COUNT=0
ROUND10_PROBE_READS_THE_CLOSURE_TABLE_ROWS=true
ROUND10_PROBE_READS_THE_UNQUALIFIED_TOKEN_BLOCKS=true
ROUND10_PROBE_RESOLVES_EVERY_ROW_REFERENCE_AGAINST_THE_REGISTRY=true
ROUND10_PROBE_FAILS_IF_E15_PRECEDES_E21_IN_ANY_ORDERING=true
ROUND10_PROBE_FAILS_ON_A_SELF_PRECONDITION_OR_SELF_SUCCESSOR=true
ROUND10_PROBE_FAILS_IF_ANY_EDGE_LIST_IS_MERELY_ACYCLIC=true
ROUND10_PROBE_FAILS_IF_A_MOUNT_CASE_EFFECT_IS_A_NOOP=true
ROUND10_PROBE_FAILS_IF_THE_FORMATTER_ALLOWLIST_OMITS_THE_FORMATTER_FD=true
ROUND10_PROBE_FAILS_IF_THE_AUTHORITY_COLUMN_DISAGREES_WITH_AUTHORITY_E_TOKENS=true
ROUND10_PROBE_DETECTS_THE_ROUND9_DEFECTS=true
ROUND10_PROBE_SELF_TEST_ON_THE_FAILED_ROUND9_TEXT=REJECTED
CURRENT_EFFECT_REFERENCE_MISMATCH_COUNT=0
CURRENT_EFFECT_SELF_PRECONDITION_COUNT=0
CURRENT_POINTER_KEY_DUPLICATE_VALUE_COUNT=0
MOUNT_CASE_E25_NOOP_COUNT=0
```

#### 1.10.8 Round-10 closure results

```text
ROUND10_RE_EVALUATED_RESULTS=PRIVILEGED_EFFECT_AUTHORITY_CLOSURE,CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY,CLEANUP_STATE_MACHINE_IMPLEMENTABILITY,NAMESPACE_LIFECYCLE_IMPLEMENTABILITY,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
EVERY_EFFECT_HAS_DECLARED_AUTHORITY=true
EVERY_DECLARED_AUTHORITY_HAS_REQUIRED_EFFECT=true
NO_BROADER_AUTHORITY_THAN_EFFECT_REQUIRES=true
UNDECLARED_PRIVILEGED_EFFECT_COUNT=0
UNUSED_DECLARED_AUTHORITY_COUNT=0
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE_BASIS=every_row_re_derived_against_the_registry_with_one_unconditional_minimal_authority_and_no_row_that_names_itself
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY_BASIS=the_attached_branch_is_enterable_from_failure_with_and_without_a_retained_descriptor_and_the_mount_case_has_no_no_op_step
CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY=PASS
CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY_BASIS=the_two_cross_process_helper_invocations_have_declared_requests_completion_carriers_lifetimes_consumers_and_closing_checkpoints_in_5_6_and_10_1
NAMESPACE_LIFECYCLE_IMPLEMENTABILITY=PASS
PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS
A3_CONTRACT_IMPLEMENTABILITY=PASS
A3_CONTRACT_IMPLEMENTABILITY_BASIS=each_of_the_eleven_blocking_findings_is_closed_by_a_statement_that_names_its_authority_owner_producer_carrier_lifetime_consumer_and_closing_point
BLOCKING_FINDINGS_CLOSED=11
BLOCKING_FINDINGS_OPEN=0
ROUND9_COUNTS_ARE_ROUND9_RECORDS=true
ROUND9_COUNTS_ARE_CURRENT_CLAIMS=false
ROUND10_EFFECT_COUNT_IS_26=true
EFFECT_COUNT_UNCHANGED_BY_ROUND10=true
EFFECT_COUNT_UNCHANGED_REASON=bindings_and_scopes_changed_and_no_effect_was_added_or_removed
```

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

Round 6 executes the unchanged procedure against the same base and keeps the same
transport, with the failed round-5 head as the fast-forward precondition:

```text
A3D_ROUND6_BASE_MAIN_SHA=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND6_BASE_MAIN_TREE=00b779f9b9a07e57380a30dd05c6da6342a4a9b3
A3D_ROUND6_BASE_EQUALS_ORIGIN_MAIN=true
A3D_ROUND6_BRANCH=design/a3d-round4-mount-owner-predicate
A3D_ROUND6_PARENT=FIFTH_A3D_REVIEW_FAILED_HEAD
TRANSPORT_DEGRADED=true
A3D_ROUND6_REMOTE_TRUTH_CHANNELS=reviewed_confined_ssh_and_authoritative_remote_api
A3D_ROUND6_REMOTE_BRANCH_TIP_AT_PREPUSH=65061f1e005c7595afd4c84d049a4e025eea9d70
A3D_ROUND6_REMOTE_MAIN_AT_PREPUSH=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND6_PREPUSH_ORIGIN_BRANCH_REQUIRED=65061f1e005c7595afd4c84d049a4e025eea9d70
A3D_ROUND6_PREPUSH_ORIGIN_MAIN_REQUIRED=cca7805305b0e369b27d7d29ba3611fb9afd7679
A3D_ROUND6_PUSH_IS_FAST_FORWARD=true
A3D_ROUND6_PUSH_IS_FORCE=false
A3D_ROUND6_PUSH_CREATES_NEW_BRANCH=false
A3D_ROUND6_AMEND_USED=false
A3D_ROUND6_REBASE_USED=false
```

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
by a separately invoked fixed helper — or, for the credential transition alone,
by the privileged namespace launcher — and only for:

- the ordinary credential transition that makes the evidence process the ordinary
  identity: the launcher's forked child empties its supplementary group list,
  changes its GID and changes its UID before `execve` of the evidence process
  (1.7.2, 5.10). This is the one privileged effect that does not act on a
  filesystem object, and it is declared as `E1`;
- setup ownership mutation (`fchown` of the single fixture file, and nothing
  else: no privileged `chmod` is performed anywhere in the fixture);
- creation of the helper's own fixture objects under the invocation root, for the
  mount case only: the `IMAGE_ROLE` image and the `MOUNTPOINT_ROLE` mountpoint,
  each created exclusively and pinned by a descriptor the helper holds;
- the RQP-L17 mount operations that cannot be performed without
  `CAP_SYS_ADMIN`, and only in the `mount-fixture` case;
- removal of the invocation-specific fixture root and of the fixture objects it
  contains, by the `cleanup` action of 5.2 and the 10.4 state machine. Cleanup
  performs no ownership change at all: the earlier phrase "cleanup ownership
  restoration" is withdrawn by round 5 as a requirement the real cleanup
  architecture does not have (1.5, 10.4), because removing an object depends on
  the containing directory's permissions and never on the removed object's
  owner;
- the below-root and parent-directory access the removal operations require,
  which is a set of two scopes rather than one: everything at a frozen role name
  **under** the validated root is below-root access, while the removal of the
  root itself acts on `RUNNER_TEMP`, the root's **parent** (1.7.6).

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

Two of the five actions are the cross-process detach and final cleanup
invocations of 10.1, and each of them is a separate privileged invocation that
validates its own inputs rather than inheriting anything from the caller or from
the other invocation. Neither accepts an inherited descriptor, so neither can
receive, hold or close the evidence process's retained descriptor
(`HELPER_ACCEPTS_INHERITED_DESCRIPTOR=false`):

```text
HELPER_DETACH_ACTION=detach-fixture
HELPER_DETACH_ACTION_VALIDATES_ROOT=true
HELPER_DETACH_ACTION_VALIDATES_NAMESPACE_IDENTITY=true
HELPER_DETACH_ACTION_VALIDATES_THE_FIXTURE_MOUNT_TARGET=true
HELPER_DETACH_ACTION_IS_REQUESTED_BY_THE_LIVE_EVIDENCE_PROCESS=true
HELPER_DETACH_ACTION_OBSERVES_THE_ATTACHED_STATE_BEFORE_ACTING=true
HELPER_DETACH_ACTION_IS_NOT_EVIDENCE=true
HELPER_CLEANUP_ACTION=cleanup
HELPER_CLEANUP_ACTION_VALIDATES_ROOT=true
HELPER_CLEANUP_ACTION_VALIDATES_NAMESPACE_IDENTITY=true
HELPER_CLEANUP_ACTION_OBSERVES_THE_MOUNT_STATE=true
HELPER_CLEANUP_ACTION_IS_REQUESTED_BY_THE_LIVE_EVIDENCE_PROCESS=true
HELPER_CLEANUP_ACTION_PERFORMS=E16_or_E17,E24,E26
HELPER_CLEANUP_ACTION_PERFORMS_NO_UNMOUNT_WHEN_THE_STATE_IS_DETACHED_BUSY=true
HELPER_ACTIONS_ARE_TWO_SEPARATE_INVOCATIONS_IN_THE_SUCCESS_PATH=true
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
| Actual process identity, supplementary group list and effective capabilities inside the evidence process | `INDEPENDENTLY_REACQUIRED` | the evidence process reads its own real `euid`, `egid`, supplementary group list and `CapEff` from itself (5.10.3, 5.10.4); nothing is received from the launcher and no value is inherited | `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_SUPPLEMENTARY_GROUPS == []`, `ACTUAL_EUID != 0` and `ACTUAL_CAP_EFF == 0` all hold before the production primitive executes |
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
| 5.5 and 5.6, evidence-process identity and capabilities | absent: "non-root" was asserted from the launch request rather than classified as a fact | `MISSING`: the observed identity is not the requested identity and needs its own class | `NONROOT_EVIDENCE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED`, with `ACTUAL_CAP_EFF == 0` required before the production call (5.10.4) |
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
| T9 | ordinary runner -> launcher: requested identity | requested ordinary uid and gid: `EXPLICITLY_HANDED_OFF`; the intended supplementary group list does not cross this boundary at all, because it is produced in the child by `setgroups` and never transported (5.10.3) | ordinary runner identity (the measured source) | `HOST_OBSERVER` or the ordinary workflow process, measuring its own real `euid`/`egid` | fixed numeric launcher arguments `--ordinary-uid` / `--ordinary-gid` | one launcher invocation | privileged namespace launcher, which validates them under 5.10.2 | `ORDINARY_UID != 0`, valid numeric ids, and invocation-root `st_uid`/`st_gid` equality all recorded before any credential drop |
| T10 | launcher -> evidence process: actual identity | observed `euid`, `egid`, supplementary group list and effective capability mask: `INDEPENDENTLY_REACQUIRED` by the evidence process | ordinary runner identity | non-root evidence process, reading its own real process state | none: the value is not transmitted, it is measured in the process that holds it; the emptied supplementary group list is the one exception in form only — it is `INHERITED` as kernel-carried process state across `fork`/`execve`, and it is still measured, not received (5.10.3) | the evidence process's lifetime | non-root evidence process itself, recorded as the run's own evidence | `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_SUPPLEMENTARY_GROUPS == []`, `ACTUAL_EUID != 0` and `ACTUAL_CAP_EFF == 0` all hold before the production primitive executes |

| T11 | evidence process -> detach helper: detach request | the request that the fixture mount be detached, and the untrusted root locator that names the fixture root: `EXPLICITLY_HANDED_OFF` through the closed case enum plus the untrusted locator; the evidence process's retained descriptor does **not** cross this boundary and is not a carrier (`HELPER_ACCEPTS_INHERITED_DESCRIPTOR=false`) | the repository design authority for the closed enum; the ordinary runner identity for the locator text | non-root evidence process, still alive with its own retained descriptor | `--case=detach-fixture` plus `--root` | one detach-helper invocation | privileged fixture helper, which validates and then detaches | the helper's 5.3 root validation and `PRIVATE_HELPER_MNT_NS_ID == PRIVATE_EVIDENCE_MNT_NS_ID` and `PRIVATE_HELPER_MNT_NS_ID != HOST_MNT_NS_ID` are measured before the detach, and the observed state is `ATTACHED` |
| T12 | detach helper -> evidence process: detach completion | the detach outcome as a completion signal and nothing more: `EXPLICITLY_HANDED_OFF` as the helper process's exit status | the repository design authority for the meaning of the status; the helper for producing it | privileged fixture helper | the helper process's wait status, observed by the still-running evidence process that requested the action | one helper invocation | non-root evidence process, which treats it as a non-evidence completion signal and then independently reacquires the mount state | the evidence process observes the status, remains alive with the same descriptor open, and its own later measurements (`fstat`, `statx` mount id, real `/proc/self/mountinfo`) are what E22 records; the exit status is never evidence and never substitutes for that reacquisition (5.5) |
| T13 | evidence process -> final cleanup helper: cleanup request | the request that the reviewed cleanup actions be performed: `EXPLICITLY_HANDED_OFF` through the closed case enum plus the untrusted locator; no descriptor and no mount object crosses | the repository design authority for the closed enum | non-root evidence process, after E23 has released its retained descriptor | `--case=cleanup` plus `--root` | one final-cleanup-helper invocation | privileged fixture helper | the helper's 5.3 root validation, the measured namespace identity equality, and the observed mount state (`DETACHED_BUSY` or `RELEASED`) are recorded before the first cleanup action |
| T14 | final cleanup helper -> evidence process and workflow: cleanup completion | the cleanup outcome, the removed-object facts and the private-namespace residue controls: `EXPLICITLY_HANDED_OFF` through the workflow output carrier bound to the head SHA, tree, runner identity and workflow-definition identity | the repository design authority for the controls; the helper for the measurements | privileged fixture helper | workflow output bound to the exact head and to the helper's own recorded namespace identity, plus the ordinary process's own `FIXTURE_ROOT_RESIDUE` observation | one run attempt, retained as CI evidence | independent reviewer; the host observer separately reports `HOST_NAMESPACE_RESIDUE` from outside the private namespace | `PRIVATE_MOUNT_RESIDUE=false`, `LOOP_BACKING_RESIDUE=false` and `FIXTURE_ROOT_RESIDUE=false` are recorded with the namespace identity that measured them, and `HOST_NAMESPACE_RESIDUE=false` is measured independently (10.3) |

T11 and T12 are the two halves of the cross-process detach protocol of 10.1: the
request crosses as a closed enum name plus an untrusted locator, and the completion
crosses as a process exit status that the contract explicitly refuses to treat as
evidence. T13 and T14 are the same two halves for the final cleanup invocation,
which runs only after the evidence process has released its retained descriptor
(E23). In both pairs the crossing fact is the request or the completion, never the
evidence descriptor: the descriptor stays in the one process that opened it, and
that process stays alive across both helper invocations.

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

**Image access preconditions (round 7).** The image's access facts are frozen as
measured postconditions of its creation rather than left as an assumption about
a default mode, because the format and the loop binding both depend on them and
neither may rely on "the image owner's write permission" without the contract
saying what that permission is:

```text
IMAGE_ACCESS_PRECONDITION_CLOSED=true
IMAGE_ROLE_REGULAR_FILE_REQUIRED=true
IMAGE_ROLE_SINGLE_LINK_REQUIRED=true
IMAGE_ROLE_OWNER_EQUALS_REVIEWED_HELPER_IDENTITY=true
IMAGE_ROLE_OWNER_WRITE_REQUIRED=true
IMAGE_ROLE_S_IMODE=0600
IMAGE_ROLE_S_IMODE_IS_EXACT=true
IMAGE_ROLE_MODE_ESTABLISHED_BY_CREATION_ONLY=true
IMAGE_ROLE_CHMOD_USED=false
IMAGE_ROLE_FCHMOD_USED=false
IMAGE_ROLE_MODE_REPAIR_WITH_PRIVILEGE=false
IMAGE_ROLE_SIZE_BYTES=16777216
IMAGE_ROLE_SIZE_IS_DESIGN_FROZEN=true
IMAGE_ROLE_SIZE_ESTABLISHED_BY=ftruncate_on_the_pinned_image_descriptor
IMAGE_ROLE_SIZE_IS_MKFS_MINIMUM_OR_LARGER=true
IMAGE_ACCESS_WITNESS_CONSUMED_BY_EFFECTS=E10,E12
IMAGE_ACCESS_WITNESS_IS_MEASURED_NOT_ASSUMED=true
```

`0600` is exact and is not widened: the image is a private fixture object that
only the reviewed privileged identity ever reads or writes, and the ordinary
evidence process never opens it. Creation establishes both the owner and the
owner-write bit, so E10's format is authorized by a measured postcondition and
E11 verifies the result through the same descriptor. A mode that is not exactly `0600`, an owner that is not
the helper identity, or a link count other than one is a failed fixture
construction: it is `QUALIFICATION_GAP` with a `TEST_FAILURE` or
`TOOLING_FAILURE` origin as 5.7 requires, and it is never repaired with a
`chmod`, an `fchmod` or a re-creation.

The frozen size exists for the same reason the mode does. `mkfs.ext4` requires a
minimum image size, and a fixture that lets the implementation pick the size
would defer an E10 precondition to implementation time; `IMAGE_ROLE_SIZE_BYTES`
is therefore a design literal, established by `ftruncate` on the descriptor the
helper already holds, which is a file-content operation and not a mode or
ownership change.

**Mountpoint-creation effect (round 7).** Round 6 required helper-exclusive
creation of `MOUNTPOINT_ROLE` while no effect row created it, so the requirement
had no operation, no binding, no authority and no postcondition. `E8` is that
missing effect, and its semantics are frozen here:

```text
MOUNTPOINT_CREATION_EFFECT=E8
MOUNTPOINT_CREATION_EFFECT_DECLARED=true
MOUNTPOINT_CREATION_SYSCALL=mkdirat
MOUNTPOINT_CREATION_TARGET_BINDING=validated_root_descriptor_plus_frozen_role_name
MOUNTPOINT_ROLE_CREATED_BY=reviewed_privileged_helper
MOUNTPOINT_ROLE_EXCLUSIVE_CREATE=true
MOUNTPOINT_ROLE_PREEXISTING_OBJECT_OUTCOME=HELPER_ROOT_REJECTED
MOUNTPOINT_ROLE_PREEXISTING_OBJECT_IS_ADOPTED=false
MOUNTPOINT_ROLE_S_IMODE=0755
MOUNTPOINT_ROLE_S_IMODE_IS_EXACT=true
MOUNTPOINT_ROLE_OWNER_IS_REVIEWED_PRIVILEGED_IDENTITY=true
MOUNTPOINT_ROLE_GROUP_AND_WORLD_WRITE_CLEAR=true
MOUNTPOINT_ROLE_ORDINARY_SEARCH_ALLOWED_REQUIRED=true
MOUNTPOINT_ROLE_ORDINARY_WRITE_DENIED=true
MOUNTPOINT_ROLE_CREATION_AUTHORITY=CAP_DAC_OVERRIDE
MOUNTPOINT_ROLE_CREATION_REQUIRES_CAP_DAC_READ_SEARCH=false
MOUNTPOINT_ROLE_CREATION_REQUIRES_CAP_DAC_OVERRIDE=true
MOUNTPOINT_ROLE_PINNED_IDENTITY_RECHECKED_BEFORE_MOUNT=true
MOUNTPOINT_ROLE_PINNED_DESCRIPTOR_IS_O_PATH=true
MOUNTPOINT_ROLE_PINNED_DESCRIPTOR_ROLE=covered_mountpoint_identity_only
MOUNTPOINT_ROLE_PINNED_DESCRIPTOR_USED_AS_MOUNTED_ROOT=false
MOUNTPOINT_ROLE_CLEANUP_EFFECT=E24
MOUNTPOINT_ROLE_CLEANUP_TRANSITION=remove_mountpoint_role_in_10_4_order
MOUNTPOINT_ROLE_CREATION_PRECONDITION_NO_PREEXISTING_OBJECT=true
MOUNTPOINT_ROLE_CREATION_POSTCONDITION_DIRECTORY_AT_FROZEN_ROLE=true
```

The mountpoint's pinned descriptor is acquired with `O_PATH` and is retained for
exactly one purpose: to remain a stable reference to the *covered* mountpoint
directory so the mount target can be revalidated immediately before the mount.
It is not the mounted root and MUST NOT be used as one after the mount covers it
(1.8.5).

The exclusive-create requirement is the directory form of the image rule: a
pre-existing object at the role name — a file, a symlink or even a directory the
helper did not create — is `HELPER_ROOT_REJECTED` rather than something to adopt,
repair or remove, and the refusal precedes any mutation of the refused object.
`0755` is the mode that makes the mount case reachable at all: the ordinary
evidence process must traverse the mountpoint to perform the unprivileged
`O_RDONLY` witness of 5.8.3 and 8 step 2, so a mode without "other" search and
execute would deny that witness to the only identity whose read is admissible.
The mountpoint's own cleanup is the mount-object removal effect `E24`, in
the 10.4 order, after the mount is released.

**Post-mount root acquisition (round 8).** The `MOUNTPOINT_ROLE` descriptor `E8`
pinned refers to the directory the helper created, and after `E14` attaches a
filesystem there it no longer refers to what that name resolves to. The mounted
root is therefore acquired after the mount, by a real post-mount resolution, and
bound by measurement before it is used:

```text
POST_MOUNT_ROOT_ACQUISITION_EFFECT=E18
POST_MOUNT_ROOT_ACQUISITION_SYSCALL=openat
POST_MOUNT_ROOT_ACQUISITION_BASE=validated_root_descriptor
POST_MOUNT_ROOT_ACQUISITION_NAME=frozen_MOUNTPOINT_ROLE
POST_MOUNT_ROOT_ACQUISITION_FLAGS=O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC
POST_MOUNT_ROOT_ACQUISITION_IS_AFTER_E15=true
POST_MOUNT_ROOT_BINDING_CLOSED=true
POST_MOUNT_ROOT_FD_IS_POST_MOUNT_ACQUIRED=true
MOUNTED_ROOT_FD=E16_acquired_descriptor
MOUNTED_ROOT_FD_SOURCE=post_mount_openat_of_the_frozen_role_name
MOUNTED_ROOT_BINDING_WINDOW=from_the_post_mount_open_to_the_three_measurements
MOUNTED_ROOT_BINDING_WINDOW_IS_CLOSED_BY_THE_THREE_MEASUREMENTS=true
MOUNTED_ROOT_FILESYSTEM_PROVED_BY=fstatfs_ext4_superblock_magic_0xEF53
MOUNTED_ROOT_DIFFERS_FROM_INVOCATION_ROOT_FILESYSTEM=true
MOUNTED_ROOT_IDENTITY_MEASURED_BY=fstat_st_dev_and_st_ino
COVERED_MOUNTPOINT_POSITIVE_EVIDENCE=fresh_resolution_differs_from_the_E6_pinned_identity
COVERED_MOUNTPOINT_POSITIVE_EVIDENCE_REQUIRED=true
MOUNTED_ROOT_MISMATCH_OUTCOME=QUALIFICATION_GAP_WITH_DESIGN_FINDING
MOUNTED_ROOT_MISMATCH_IS_HELPER_ROOT_REJECTED=false
MOUNTED_ROOT_MISMATCH_IS_PASS=false
MOUNTED_ROOT_MISMATCH_REPAIRED_WITH_PRIVILEGE=false
MOUNTED_ROOT_ACQUISITION_PRECEDES_E20=true
MOUNTED_ROOT_ACQUISITION_PRECEDES_E24=true
MOUNTED_ROOT_FD_NOT_RE_RESOLVED_BY_E18=true
MOUNTED_ROOT_FD_NOT_RE_RESOLVED_BY_E20=true
MOUNTED_ROOT_FD_IS_THE_ONLY_BASIS_FOR_THE_MOUNT_CASE_CHILD=true
USE_OF_PRE_MOUNT_DESCRIPTOR_AS_MOUNTED_ROOT=false
```

**Formatter descriptor carrier (round 8).** `E9` pins the image with
`O_CLOEXEC`, so the external formatter cannot inherit that descriptor. `E10`
derives a dedicated descriptor, clears `FD_CLOEXEC` on that descriptor only, and
passes the child its own `/proc/self/fd/<N>` as the device argument:

```text
FORMATTER_FD_CARRIER_CLOSED=true
FORMATTER_FD_SOURCE=pinned_E9_image_descriptor
FORMATTER_FD_DERIVATION=dup_the_pinned_descriptor_to_obtain_a_new_descriptor_number
FORMATTER_FD_DERIVATION_SYSCALL=dup
FORMATTER_FD_DERIVATION_KEEPS_THE_SAME_OPEN_FILE_DESCRIPTION=true
FORMATTER_FD_IS_A_NEW_DESCRIPTOR_NUMBER=true
FORMATTER_FD_CLOEXEC_CLEARED=true
FORMATTER_FD_CLOEXEC_CLEARED_BY=fcntl_F_SETFD_with_no_FD_CLOEXEC
FORMATTER_FD_LIFETIME=from_the_dup_until_the_formatter_child_exits
FORMATTER_FD_DEVICE_ARGUMENT=/proc/self/fd/<formatter_fd_number>
FORMATTER_FD_DEVICE_ARGUMENT_IS_FD_MEDIATED=true
FORMATTER_FD_DEVICE_ARGUMENT_IS_NOT_THE_ROLE_PATHNAME=true
FORMATTER_RE_RESOLVES_IMAGE_ROLE_BY_PATHNAME=false
FORMATTER_USES_ORDINARY_ROLE_PATHNAME=false
FORMATTER_CHILD_FDS_ARE_THE_STANDARD_STREAMS_ONLY=false
FORMATTER_CHILD_INHERITS_ONLY_STANDARD_STREAMS_AND_FORMATTER_FD=true
FORMATTER_PARENT_CLOSES_FD_AFTER_WAIT=true
FORMATTER_PARENT_CLOSES_FD_BEFORE_E11=true
FORMATTER_FD_CLOSED_BEFORE_LOOP_CONFIGURATION=true
FORMATTER_POST_FORMAT_IDENTITY_VERIFICATION_EFFECT=E11
```

The formatter's device argument is resolved inside the child's own descriptor
table, so the tool is bound to the inode `E9` created and pinned and never sees
the role pathname. `E11` then verifies the result through the same pinned
descriptor: the inode identity, mode, owner and link count are unchanged and the
two bytes at image offset 1080 are `0x53 0xEF`, the little-endian ext4 superblock
magic `0xEF53` (kernel ext4 documentation: `s_magic` at superblock offset `0x38`,
superblock at 1024).

```text
E11_ROLE=post_format_image_verification
E11_READS_MAGIC_AT_IMAGE_OFFSET=1080
E11_EXPECTED_MAGIC_BYTES=0x53,0xEF
E11_EXPECTED_MAGIC_VALUE=0xEF53
E11_MAGIC_OFFSET_SOURCE=ext4_superblock_at_1024_plus_s_magic_at_0x38
E11_VERIFIES_BEFORE_LOOP_CONFIGURATION=true
E11_CHECKSUM_OR_MOUNT_TEST_SUBSTITUTE_FOR_MAGIC=false
```

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

**Loop target binding frozen (round 7).** The loop association is frozen as one
implementable descriptor-mediated mechanism, and the pathname-based form is
withdrawn rather than offered as an equivalent. The earlier text named both
`losetup --find --show <IMAGE_ROLE pathname>` and a descriptor-mediated binding
in the same row, which is not one implementable mechanism: `losetup --find
--show <path>` re-resolves `IMAGE_ROLE` by pathname inside the tool and offers no
guarantee that the object it bound is the inode the helper pinned, so it cannot
support a descriptor-mediated claim:

```text
LOOP_TARGET_BINDING_CLOSED=true
LOOP_TARGET_BINDING_MECHANISM=descriptor_mediated_direct_loop_ioctl
LOOP_TARGET_BINDING_STEPS=open_loop_control;LOOP_CTL_GET_FREE;open_recorded_loop_device;LOOP_CONFIGURE_with_pinned_image_fd
LOOP_TARGET_BINDING_ACCEPTS_PATHNAME=false
LOOP_TARGET_BINDING_RERESOLVES_IMAGE_ROLE_PATH=false
LOOP_TARGET_BINDING_USES_EXTERNAL_TOOL=false
LOOP_TARGET_BINDING_USES_FD_PRESERVING_EXTERNAL_TOOL=false
LOOP_TARGET_BINDING_BACKING_FD=pinned_IMAGE_ROLE_descriptor_from_E9
LOOP_TARGET_BINDING_DEVICE_SELECTED_BY_HELPER=true
LOOP_TARGET_BINDING_DEVICE_FROM_CALLER=false
LOOP_TARGET_BINDING_VERIFIED_AFTER_SETUP=true
LOOP_TARGET_BINDING_VERIFICATION_EFFECT=E13
LOOP_TARGET_BINDING_VERIFICATION=LOOP_GET_STATUS64_backing_identity_equals_pinned_image_st_dev_and_st_ino
LOOP_TARGET_BINDING_CONFIGURATION_EFFECT=E12
LOOP_TARGET_BINDING_CONFIGURATION_CLAIMS_NO_VERIFICATION=true
LOOP_TARGET_BINDING_VERIFICATION_IS_E13_ONLY=true
LOSETUP_FIND_SHOW_IS_SUFFICIENT_EVIDENCE=false
LOSETUP_PATHNAME_FORM_USED=false
LOSETUP_IS_THE_LOOP_BINDING_MECHANISM=false
LOOP_CONFIGURE_PREFERRED_OVER_LOOP_SET_FD=true
LOOP_SET_FD_FALLBACK_ALLOWED=false
LOOP_SET_FD_FALLBACK_REASON=a_fallback_would_be_a_second_unfrozen_mechanism_and_the_contract_freezes_one
```

The helper opens `/dev/loop-control` and takes a free device number with
`LOOP_CTL_GET_FREE`, then opens the corresponding `/dev/loopN` node and
configures it with `LOOP_CONFIGURE`, passing the descriptor it already holds on
`IMAGE_ROLE` as the backing file descriptor. Because the ioctl takes that
descriptor, the association is bound to the very inode the helper created and
pinned, and `IMAGE_ROLE` is not re-resolved between the pin and the association.
The device number, the device path and the pinned backing identity are
helper-internal state. Configuration and verification are two effects and not
one: `E12` configures and claims only that the device is configured with the
pinned image as its backing file, and `E13` re-reads the device's real backing
identity with `LOOP_GET_STATUS64` and requires it to equal the pinned
`st_dev`/`st_ino`. `E14` depends on `E13`'s verification, so nothing is mounted
before the read-back has passed; a mismatch is a hard refusal before the mount and
a non-pass fixture-construction failure classified by 5.7.

The mount operation itself is a pathname operation: `mount(2)` accepts paths
rather than descriptors and has no descriptor-based form (mount(2): its
`source` and `target` arguments are pathnames). This contract therefore freezes
the invariant — helper-created objects, exclusive creation, no caller-created
source or target, and identity revalidation — rather than claiming a descriptor
pin for the mount syscall itself. A revalidation failure is a hard refusal
before any privileged effect beyond the creation the helper already performed.
The loop *binding* is descriptor-mediated, and the mount that consumes it is
pathname-based: the two are separate facts, and only the mount is exempt from
the descriptor rule because only the mount has no descriptor form.

```text
MOUNT_SYSCALL_HAS_DESCRIPTOR_FORM=false
MOUNT_SYSCALL_TARGET_BINDING=helper_exclusive_creation_plus_pre_mount_identity_revalidation
MOUNT_SYSCALL_TARGET_BINDING_WINDOW=revalidation_to_call
LOOP_BINDING_HAS_DESCRIPTOR_FORM=true
LOOP_BINDING_AND_MOUNT_BINDING_ARE_SEPARATE_FACTS=true
```

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

#### 5.10.3 Frozen credential-transition mechanism and supplementary groups

The launcher then launches `NONROOT_EVIDENCE_PROCESS` with those validated
credentials, and round 7 freezes *how*. The transition is a real privileged
effect — `E1` in the closure table of 1.5 — and it is performed by the launcher's
own forked child with direct Linux credential syscalls, in a frozen order:

```text
CREDENTIAL_TRANSITION_EFFECT=E1
CREDENTIAL_TRANSITION_MECHANISM=direct_linux_credential_syscalls
CREDENTIAL_TRANSITION_EXTERNAL_PRIVILEGE_TOOL_USED=false
CREDENTIAL_TRANSITION_PERFORMED_BY=the_launchers_forked_child_after_the_parent_validated_the_handoff
CREDENTIAL_TRANSITION_OPERATION_ORDER=setgroups_then_setgid_then_setuid
CREDENTIAL_TRANSITION_OPERATION_ORDER_IS_MANDATORY=true
CREDENTIAL_TRANSITION_STEP_1=setgroups(0, NULL)
CREDENTIAL_TRANSITION_STEP_2=setgid(ORDINARY_GID)
CREDENTIAL_TRANSITION_STEP_3=setuid(ORDINARY_UID)
CREDENTIAL_TRANSITION_STEP_4=execve(NONROOT_EVIDENCE_PROCESS)
CREDENTIAL_TRANSITION_FOLLOWED_BY_EXECVE=true
CREDENTIAL_TRANSITION_REQUIRED_AUTHORITY=CAP_SETGID,CAP_SETUID
CREDENTIAL_TRANSITION_SUPPLEMENTARY_GROUP_TRANSITION=setgroups_empty_list
CREDENTIAL_TRANSITION_TARGET_SUPPLEMENTARY_GROUP_LIST=empty
CREDENTIAL_TRANSITION_SUPPLEMENTARY_GROUPS_LEFT_IMPLICIT=false
CREDENTIAL_TRANSITION_IDENTITY_REGAIED_AFTER_DROP=false
CREDENTIAL_TRANSITION_POSTCONDITION_UID_TRIPLE_ALL_ORDINARY=true
CREDENTIAL_TRANSITION_POSTCONDITION_GID_TRIPLE_ALL_ORDINARY=true
CREDENTIAL_TRANSITION_POSTCONDITION_SUPPLEMENTARY_GROUPS_EMPTY=true
CREDENTIAL_TRANSITION_CAPABILITY_CLEARING=performed_by_the_kernel_on_the_uid_transition
CREDENTIAL_TRANSITION_CAPABILITY_CLEARING_IS_EXPLICIT=false
CREDENTIAL_TRANSITION_REQUIRES_CAP_SETPCAP=false
CREDENTIAL_TRANSITION_REQUIRES_CAP_SETFCAP=false
CREDENTIAL_TRANSITION_SECUREBITS_KEEP_CAPS_SET=false
CREDENTIAL_TRANSITION_AMBIENT_CAPABILITIES_RAISED=false
CREDENTIAL_TRANSITION_PR_SET_KEEPCAPS_USED=false
CREDENTIAL_TRANSITION_FAILURE_OUTCOME=LAUNCHER_CREDENTIAL_REJECTED
CREDENTIAL_TRANSITION_FAILURE_IS_PASS=false
CREDENTIAL_TRANSITION_PERFORMED_IN_THE_PARENT_INSTEAD=false
```

`CAP_SETGID` governs both the supplementary group list and the GID change, and
`CAP_SETUID` governs the UID change (capabilities(7): `CAP_SETGID` — "make
arbitrary manipulations of process GIDs and supplementary GID list";
`CAP_SETUID` — "make arbitrary manipulations of process UIDs"). The order is a
requirement rather than a style choice, and round 8 states the real reason for
it. Round 7 claimed that `setgid(2)` removes `CAP_SETGID` from the child; that
claim is **false and withdrawn** (1.8.7). `CAP_SETGID` authorizes group-ID
manipulation, and what clears the capability sets is the **UID** change: the
kernel's set-ID fixups run on changes to the real, effective, saved and
filesystem user IDs, not on a GID change. The order is mandatory because the UID
transition is the step that clears the sets, so both `CAP_SETGID` operations must
complete before it:

```text
CREDENTIAL_TRANSITION_ORDER_REASON=setgroups_and_setgid_must_complete_before_the_uid_transition_that_clears_the_capability_sets
ROUND7_SETGID_CLEARS_CAP_SETGID_CLAIM=false
ROUND7_SETGID_CLEARS_CAP_SETGID_CLAIM_WITHDRAWN_BY_ROUND8=true
CAP_SETGID_IS_CLEARED_BY_A_GID_CHANGE=false
UID_CHANGES_DRIVE_THE_SET_ID_CAPABILITY_FIXUPS=true
CREDENTIAL_TRANSITION_CAPABILITY_CLEARING_STEP=setuid
CREDENTIAL_TRANSITION_CAPABILITY_CLEARING_IS_THE_LAST_STEP=true
```

A design that called `setuid` first would have to abandon the group transition
entirely, because after that call the child holds no capability with which to
perform it. No `CAP_SETPCAP` is required, because the transition never edits a
capability set: the kernel clears the permitted, effective and ambient sets
itself once the UID change makes every uid nonzero, and the fixture sets no
securebits flag and raises no ambient capability that could defeat that clearing.
The contract claims only what that documented mechanism does, and then confirms
it by measurement rather than inferring it from the call sequence:

```text
CREDENTIAL_TRANSITION_CLEARING_RULE_1=if_the_real_effective_or_saved_uid_was_zero_and_all_become_nonzero_then_permitted_effective_and_ambient_are_cleared
CREDENTIAL_TRANSITION_CLEARING_RULE_2=if_the_effective_uid_changes_from_zero_to_nonzero_then_the_effective_set_is_cleared
CREDENTIAL_TRANSITION_CLEARING_SOURCE=capabilities(7)_effect_of_user_ID_changes_on_capabilities
CREDENTIAL_TRANSITION_CLAIMS_NO_OTHER_CLEARING=true
CREDENTIAL_TRANSITION_CLEARING_IS_CONFIRMED_BY_MEASUREMENT=true
CREDENTIAL_TRANSITION_CLEARING_IS_NOT_INFERRED_FROM_THE_CALL_SEQUENCE=true
CAPABILITY_SETS_ARE_INHERITED_ACROSS_FORK=true
CHILD_CAPABILITY_SETS_ARE_MEASURED_NOT_INFERRED_FROM_THE_PARENT=true
```

**Supplementary group semantics, closed.** The supplementary group list is a
fact with a producer, a carrier, an independent reacquisition, a comparison and a
recorded closing point, and none of those is implicit:

| Aspect | Frozen statement |
| --- | --- |
| intended list | empty: the evidence process is a member of `ORDINARY_GID` as its primary group and of no supplementary group |
| produced by | the launcher's forked child, with `setgroups(0, NULL)` before the GID and UID transitions; the value is a frozen constant of the design and no caller value, environment value or host group database participates |
| carried or reconstructed | `INHERITED`: the emptied list is a kernel-carried property of the very process whose credentials changed, so there is no separate carrier, no message and nothing to reconstruct across the `fork`/`execve` that follows |
| independently reacquired | the evidence process reads its own real supplementary group list from itself — `getgroups(2)` and the real `Groups` field of `/proc/self/status` — before the production primitive, and requires it to be empty |
| compared | the reacquired list must equal the frozen intended list exactly: `ACTUAL_SUPPLEMENTARY_GROUPS == []`. A nonempty list is a fixture-construction failure in the same class as an identity mismatch |
| recorded | the measured list is recorded in the run's evidence before the production primitive executes, so a reviewer can see the value the process really had rather than the value the design intended |
| closing point | `ACTUAL_SUPPLEMENTARY_GROUPS == []` holds together with `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_EUID != 0`, `ACTUAL_CAP_PRM == 0`, `ACTUAL_CAP_EFF == 0`, `ACTUAL_CAP_AMB == 0` and the observed `ACTUAL_SECUREBITS`, all before the production call |
| failure outcome | `QUALIFICATION_GAP` with a fixture-construction failure origin; never evidence, never a pass and never a `PRODUCT_FAILURE` |

```text
SUPPLEMENTARY_GROUP_SEMANTICS_CLOSED=true
SUPPLEMENTARY_GROUP_INTENDED_LIST=empty
SUPPLEMENTARY_GROUP_PRODUCER=launcher_forked_child_setgroups_empty_list
SUPPLEMENTARY_GROUP_PRODUCER_ACCEPTS_CALLER_VALUE=false
SUPPLEMENTARY_GROUP_CONTINUITY=INHERITED
SUPPLEMENTARY_GROUP_CONTINUITY_HAS_NO_CARRIER=true
SUPPLEMENTARY_GROUP_INDEPENDENT_REACQUISITION=evidence_process_reads_its_own_real_list
SUPPLEMENTARY_GROUP_REACQUISITION_SOURCE=getgroups_and_the_real_Groups_field_of_proc_self_status
SUPPLEMENTARY_GROUP_COMPARISON_REQUIRED=true
SUPPLEMENTARY_GROUP_COMPARISON_TARGET=empty
SUPPLEMENTARY_GROUP_RECORDED_BEFORE_PRODUCTION_PRIMITIVE=true
SUPPLEMENTARY_GROUP_MISMATCH_OUTCOME=QUALIFICATION_GAP_OR_FIXTURE_CONSTRUCTION_FAILURE
SUPPLEMENTARY_GROUP_MISMATCH_IS_EVIDENCE=false
SUPPLEMENTARY_GROUP_WIDENING_PERFORMED=false
EVIDENCE_PROCESS_IS_MEMBER_OF_ORDINARY_GID_AS_PRIMARY_GROUP=true
```

The evidence process MUST record the actual group list before the production
primitive, exactly as it records its identity and capability mask:

```text
ACTUAL_SUPPLEMENTARY_GROUPS=
```

```text
ACTUAL_SUPPLEMENTARY_GROUPS == []
```

#### 5.10.4 Actual identity and capabilities reacquired inside the evidence process

Inside `NONROOT_EVIDENCE_PROCESS`, the process reacquires its own real identity,
its own real supplementary group list, its own real capability sets and its own
inherited securebits, and MUST require all of:

```text
ACTUAL_EUID=
ACTUAL_EGID=
ACTUAL_SUPPLEMENTARY_GROUPS=
ACTUAL_CAP_PRM=
ACTUAL_CAP_EFF=
ACTUAL_CAP_AMB=
ACTUAL_NO_NEW_PRIVS=
ACTUAL_SECUREBITS=
```

```text
ACTUAL_EUID == ORDINARY_UID
ACTUAL_EGID == ORDINARY_GID
ACTUAL_SUPPLEMENTARY_GROUPS == []
ACTUAL_EUID != 0
ACTUAL_CAP_PRM == 0
ACTUAL_CAP_EFF == 0
ACTUAL_CAP_AMB == 0
```

```text
NONROOT_EVIDENCE_IDENTITY_OBSERVATION=INDEPENDENTLY_REACQUIRED
NONROOT_EVIDENCE_CAP_PRM_REQUIRED=0
NONROOT_EVIDENCE_CAP_EFF_REQUIRED=0
NONROOT_EVIDENCE_CAP_AMB_REQUIRED=0
NONROOT_EVIDENCE_CAP_PRM_SOURCE=/proc/self/status CapPrm decoded from the real mask
NONROOT_EVIDENCE_CAP_EFF_SOURCE=/proc/self/status CapEff decoded from the real mask
NONROOT_EVIDENCE_CAP_AMB_SOURCE=/proc/self/status CapAmb decoded from the real mask
NONROOT_EVIDENCE_NO_NEW_PRIVS_SOURCE=/proc/self/status NoNewPrivs
NONROOT_EVIDENCE_SECUREBITS_SOURCE=prctl_PR_GET_SECUREBITS
NONROOT_EVIDENCE_SECUREBITS_OBSERVED=true
NONROOT_EVIDENCE_SECBIT_KEEP_CAPS_REQUIRED_CLEAR=true
NONROOT_EVIDENCE_SECBIT_NO_SETUID_FIXUP_REQUIRED_CLEAR=true
SECUREBITS_VALIDATED_BEFORE_THE_TRANSITION=true
SECUREBITS_VALIDATED_AFTER_THE_TRANSITION=true
SECUREBITS_VALIDATION_POINTS=child_before_setgroups,child_after_setuid,evidence_process_after_execve
SECUREBITS_OBSERVATION_SOURCE=prctl_PR_GET_SECUREBITS
PROC_STATUS_SECBITS_FIELD_REQUIRED=false
SECUREBITS_VALIDATED_BEFORE_TRANSITION=true
SECUREBITS_VALIDATED_AFTER_SETUID=true
SECUREBITS_VALIDATED_AFTER_EXECVE=true
SECUREBITS_UNEXPECTED_OUTCOME=QUALIFICATION_GAP
SECUREBITS_INHERITED_FROM_THE_LAUNCHER=true
ORDINARY_REQUESTED_UID_GID_IS_NOT_OBSERVED_IDENTITY=true
```

Each of these values is read from the running evidence process itself, not
received from the launcher and not inferred from the launch request.
`ACTUAL_EUID`, `ACTUAL_EGID`, `ACTUAL_SUPPLEMENTARY_GROUPS`, `ACTUAL_CAP_PRM`,
`ACTUAL_CAP_EFF` and `ACTUAL_CAP_AMB` are independently reacquired facts, and they
are different facts from the handed-off `ORDINARY_UID`/`ORDINARY_GID` even when
their values agree: agreeing values are the point of the comparison, and the
comparison is only meaningful because the two sides are measured separately.

The capability requirement is the substantive part of this freeze, and round 8
widens what it covers without widening any grant. Nonzero `euid` with a nonempty
capability set is not a nonprivileged process, and a fixture that admitted such a
process would attribute to the production primitive an outcome produced by
retained privilege. Requiring only `CapEff == 0` would leave two ways for that to
happen unnoticed: a nonempty **permitted** set can be made effective again by the
process itself without any privilege transition, and a nonempty **ambient** set
survives `execve` into a program with no file capabilities. All three sets are
therefore required zero, and the securebits and `NoNewPrivs` state that could
defeat the clearing are observed and recorded rather than assumed:

```text
NONROOT_EVIDENCE_CAP_PRM_NONZERO_IS_EVIDENCE=false
NONROOT_EVIDENCE_CAP_AMB_NONZERO_IS_EVIDENCE=false
NONROOT_EVIDENCE_CAP_PRM_NONZERO_IS_NOT_A_NONPRIVILEGED_PROCESS=true
NONROOT_EVIDENCE_CAP_AMB_NONZERO_IS_NOT_A_NONPRIVILEGED_PROCESS=true
CAPABILITY_REQUIREMENT_COVERS_PRM_EFF_AMB=true
CAPABILITY_REQUIREMENT_STRONGER_THAN_ROUND7=true
CAPABILITY_GRANT_WIDENED_BY_ROUND8_IS_A_ROUND8_RECORD=false
```

`ACTUAL_CAP_EFF == 0` therefore means no effective capability at all: not
`CAP_DAC_OVERRIDE`, not `CAP_CHOWN`, not `CAP_SYS_ADMIN`, not `CAP_SETGID`, not
`CAP_SETUID`, not `CAP_FOWNER`, and not any other effective bit, as decoded from
the real `CapEff` mask of the running process.

```text
PRODUCTION_PRIMITIVE_EXECUTES_IN_NONROOT_EVIDENCE_PROCESS=true
PRODUCTION_PRIMITIVE_BEFORE_IDENTITY_CONTROLS=false
NONROOT_EVIDENCE_IDENTITY_MISMATCH_OUTCOME=QUALIFICATION_GAP_OR_FIXTURE_CONSTRUCTION_FAILURE
NONROOT_EVIDENCE_IDENTITY_MISMATCH_IS_EVIDENCE=false
NONROOT_EVIDENCE_CAP_EFF_NONZERO_IS_EVIDENCE=false
```

The production primitive under qualification MUST NOT execute before these
controls pass. A mismatch of any observed value is a `QUALIFICATION_GAP` and a
fixture-construction failure, never evidence: the case cannot conclude anything
about production from a process that is not the ordinary, unprivileged identity
the contract requires, and it MUST NOT report a `PRODUCT_FAILURE` from such a
run.

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
| ordinary privilege | the ordinary evidence process has `euid != 0`, its real `ORDINARY_UID` and `ORDINARY_GID` are measured before any privileged transition, and its real supplementary group list is recorded |
| ordinary capabilities | the evidence process's real `CapPrm`, `CapEff` and `CapAmb` are all `0`, so "non-root" means unprivileged rather than merely nonzero `euid`; its real `NoNewPrivs` and `Secbits` are observed and recorded, because a securebits flag that defeats the set-ID capability fixups would invalidate the transition |
| passwordless sudo | `sudo -n` succeeds without a prompt or terminal |
| helper privilege | the privileged child really reports `euid == 0` |
| launcher transition authority | the launcher's real `CapEff` contains `CAP_SETGID` and `CAP_SETUID`, so the credential transition of 5.10.3 is authorized by a measured fact; and the transition child's post-transition `CapPrm`, `CapEff` and `CapAmb` are all observed `0`, so the kernel clearing the capability sets on the UID change is observed rather than assumed |
| capabilities | each case's privileged child's `CapEff` contains every capability in that case's total required authority set: `OWN_FOREIGN_TOTAL_REQUIRED_AUTHORITY_SET`, `OWN_ROOT_TOTAL_REQUIRED_AUTHORITY_SET` or `MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET`, each decoded from the real mask and each bound to at least one effect of that case in 1.5. `CAP_CHOWN` is bound to the ownership mutation, `CAP_DAC_OVERRIDE` to the directory-entry-creating and entry-removing effects of the invocation root, `CAP_DAC_READ_SEARCH` to the effects that only resolve a name through or read a directory the helper does not own, `CAP_SETGID` and `CAP_SETUID` to the credential transition of `E1`, and `CAP_SYS_ADMIN` to the namespace, propagation, loop, mount and unmount effects of the mount case. The global inventory is the union of the case sets — `REQUIRED_CAPABILITY_INVENTORY=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN` — and no capability is required that the fixture's own operations do not need, and none is declared unnecessary because it produces no evidence |
| helper access authority | the privileged child's real `CapEff` contains the declared helper access authority, and the invocation root it must reach is observed as owner-only (`S_IMODE == 0o700`, group, world and sticky bits clear) and owned by the ordinary runner, so that the access authority is required by a measured fact rather than assumed (1.5). The root itself is opened with `O_PATH`, which "requires no permissions on the object itself" (open(2)), so the root open adds no capability requirement of its own |
| parent directory DAC state | `RUNNER_TEMP`'s real owner, real mode, real sticky-bit state and the resulting write-and-search DAC relation to the helper identity are observed and recorded, because the invocation-root removal of `E26` acts on that directory and not on the root; the relation is required to withhold direct write from the helper identity so that `E26`'s single declared authority is unconditional and minimal rather than conditional, and a shared-writable or sticky parent is a `QUALIFICATION_GAP` rather than a second authority outcome or an undeclared `CAP_FOWNER` (1.10.4) |
| kernel and tools | the required kernel interfaces and utilities exist and their versions are recorded, including `/dev/loop-control` and the loop device nodes required by the descriptor-mediated loop binding of 5.9 |
| fixture root | the `RUNNER_TEMP` invocation root is usable, invocation-specific, and not a shared or persistent runner path; its parent is not sticky, so removal of a directory owned by the ordinary identity needs no `CAP_FOWNER`; and the freshly formatted ext4 root directory is observed with the owner and search facts 5.8.3 requires |
| mount object preconditions | the image's real mode, owner and link count are observed equal to the frozen `IMAGE_ROLE_S_IMODE=0600`, the reviewed helper identity and one link; and the mountpoint's real mode is observed `0755` with group and world write clear, so the ordinary identity's search through it — the precondition of the 5.8.3 DAC witness — is a measured fact (5.9) |
| foreign uid | the design-frozen `FOREIGN_OWNER_TARGET_UID=65534` is representable on the host and the ordinary runner's effective uid is not `65534`, so the 5.2 literal is usable; if it is not, the `FOREIGN_OWNER` outcome is `QUALIFICATION_GAP` and no alternate uid is selected |
| isolation | no persistent or shared runner state is targeted by any step |

The fixture's capability requirement is derived from the operations it really
performs, and it is frozen as an exact set per case rather than as one blanket
grant.

For the RQP-L09 ownership fixture the required authority is frozen as three
independent exact facts — the mutation authority, the case's filesystem-access
authority and the credential transition's authority — whose union is the case's
complete required set:

```text
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY=CAP_CHOWN
OWNERSHIP_MUTATION_REQUIRES_CAP_FOWNER=false
OWNERSHIP_MUTATION_REQUIRED_CAPABILITY_SET=CAP_CHOWN
OWNERSHIP_MUTATION_AUTHORITY_EXACT=true
OWNERSHIP_CASE_ACCESS_AUTHORITY=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH
OWNERSHIP_CASE_ACCESS_AUTHORITY_EXACT=true
OWNERSHIP_CASE_ACCESS_AUTHORITY_EFFECTS=E2,E4,E25
OWNERSHIP_CASE_ACCESS_AUTHORITY_EFFECTS_BY_CAPABILITY=E2_and_E4_by_CAP_DAC_READ_SEARCH;E25_by_CAP_DAC_OVERRIDE
OWNERSHIP_CASE_CREDENTIAL_TRANSITION_AUTHORITY=CAP_SETGID,CAP_SETUID
OWNERSHIP_CASE_CREDENTIAL_TRANSITION_AUTHORITY_EXACT=true
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_TRUTHFUL=true
OWNERSHIP_CASE_REQUIRED_AUTHORITY_COUNT=5
OWNERSHIP_CASE_REQUIRES_CAP_DAC_READ_SEARCH=true
OWNERSHIP_CASE_E2_E4_NEED_THE_SEARCH_AUTHORITY=true
OWNERSHIP_CASE_E3_E5_NEED_NO_ACCESS_AUTHORITY=true
```

`CAP_CHOWN` is required because the helper performs `fchown` on the pinned child
descriptor in the two ownership cases (5.8.2), and it is exactly the mutation
authority: one call, no mode change, no other ownership-manipulating operation.
`CAP_FOWNER` is NOT required, and could not be required by an honest contract,
because the helper changes no mode, no ownership of a setuid/setgid object and no
other FOWNER-governed attribute: the zero-argument `fchmod` of the earlier draft
is gone (5.8.2), so nothing in the helper needs FOWNER.

The access authority is one capability rather than two, and round 8 narrows it
for the reason 1.8.8 gives: `CAP_DAC_OVERRIDE` already bypasses the directory
search check, so the round-7 pairing of `CAP_DAC_READ_SEARCH` with it paid twice
for one check. The ownership cases' own access need is smaller than round 7 stated it and
larger than round 8 stated it. Opening the pinned child does resolve the frozen
`FIXTURE_FILE_ROLE` name against the root descriptor, so `E2` and `E4` perform a
real directory search check that the ordinary-owned `0700` root denies and that
`CAP_DAC_READ_SEARCH` is the minimal capability to bypass; the `fchown` that
follows consumes the descriptor those rows already opened and needs no access
authority at all. The other access requirement is the cleanup removal `E25`,
which removes a name from the invocation root the ordinary runner owns and needs
`CAP_DAC_OVERRIDE` for the search and write checks of that one operation
(1.10.4):

```text
OWNERSHIP_CASE_ACCESS_AUTHORITY_DERIVATION=CAP_DAC_READ_SEARCH_from_E2_and_E4;CAP_DAC_OVERRIDE_from_E25
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_DERIVATION=union_of_the_ownership_case_effect_set_required_authority
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_DERIVED_NOT_ASSERTED=true
OWNERSHIP_CASE_REQUIRES_PRIVATE_MOUNT_NAMESPACE=false
OWNERSHIP_CASE_REQUIRES_CAP_SYS_ADMIN=false
OWNERSHIP_CASE_EFFECT_SET_IS_CAP_SYS_ADMIN_FREE=true
ROOT_OPEN_USES_O_PATH=true
ROOT_OPEN_REQUIRES_NO_PERMISSION_ON_THE_ROOT=true
```

The retired `OWNERSHIP_FIXTURE_REQUIRED_CAPABILITY_SET` token named only the
mutation half while claiming to name the fixture's whole set, round 6's
replacement named the mutation and access halves while omitting the credential
transition, and round 7's set still counted a traversal capability twice. None of
these authorities is itself evidence, and none of them is available to the
ordinary evidence process, whose `ACTUAL_CAP_PRM`, `ACTUAL_CAP_EFF` and
`ACTUAL_CAP_AMB` are all required `0`; that is an attribution fact, not a reason
to call any of them unnecessary. `FILE_MODE=0644` exists precisely so the ordinary
reader's access is a real permissions fact rather than a capability artifact: the
ordinary non-root process's `os.open(O_RDONLY)` succeeds through the real `0644`
DAC bits, and that success is the 4.3 attribution guard.

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
MOUNT_FIXTURE_FILE_CREATION_EFFECT=E20
MOUNT_FIXTURE_FILE_CREATION_ACCESS_AUTHORITY=none
MOUNT_FIXTURE_FILE_CREATION_ACCESS_AUTHORITY_SCOPE=descriptor_local_creation_relative_to_mounted_root_fd
MOUNT_FIXTURE_FILE_CREATION_ACCESS_AUTHORITY_PRODUCES_EVIDENCE=false
MOUNT_CASE_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
MOUNT_CASE_TOTAL_REQUIRED_AUTHORITY_SET_DERIVATION=union_of_the_mount_fixture_effect_set_required_authority
MOUNT_CASE_TOTAL_REQUIRED_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
MOUNT_CASE_REQUIRES_CAP_CHOWN=false
MOUNT_CASE_REQUIRES_CAP_DAC_READ_SEARCH=true
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

RQP-L17 requires a mount-operation capability subset *and* a total authority
set, and round 7 separates the two because round 6's single token claimed the
total while naming only the subset. The mount-operation subset is `CAP_SYS_ADMIN`
bound to the namespace, propagation, loop, mount and unmount effects and to
nothing else; the total set is what the whole `mount-fixture` case needs:

```text
RQP_L17_MOUNT_OPERATION_CAPABILITY_SET=CAP_SYS_ADMIN
RQP_L17_MOUNT_OPERATION_CAPABILITY_SET_SCOPE=mount-namespace-creation,mount-propagation-private,loop-control-and-configuration,loop-readback,mount-and-unmount
RQP_L17_MOUNT_OPERATION_CAPABILITY_SET_IS_A_SUBSET_ONLY=true
RQP_L17_CAP_SYS_ADMIN_BOUND_EFFECTS=E12,E6,E7,E15,E17,E16,E14,E13
RQP_L17_EFFECTS_WITHOUT_CAP_SYS_ADMIN=E1,E8,E9,E10,E11,E18,E19,E20,E21,E22,E23,E24,E26
RQP_L17_CAP_SYS_ADMIN_BROADER_THAN_ITS_EFFECTS=false
RQP_L17_MOUNT_EFFECTS_REQUIRE_CAP_SYS_ADMIN=true
RQP_L17_TOTAL_REQUIRED_AUTHORITY_SET=CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID,CAP_SYS_ADMIN
RQP_L17_TOTAL_AUTHORITY_SET_EQUALS_MOUNT_FIXTURE_TOTAL_AUTHORITY_SET=true
RQP_L17_TOTAL_REQUIRED_AUTHORITY_COUNT=5
RQP_L17_TOTAL_AUTHORITY_SET_DERIVATION=union_of_the_mount_fixture_effect_set_required_authority
RQP_L17_TOTAL_AUTHORITY_SET_IS_NOT_ONE_MOUNT_RELATED_SET=true
RQP_L17_REQUIRES_CAP_DAC_READ_SEARCH=true
RQP_L17_REQUIRED_CAPABILITY_SET_RETIRED=true
RQP_L17_REQUIRED_CAPABILITY_SET_RETIRED_REASON=it_named_only_the_mount_operation_subset_while_claiming_to_name_the_cases_required_capability_set
NAME_ONLY_THE_MOUNT_SUBSET_IF_SCOPE_IS_MOUNT_SUBSET=true
RQP_L17_PREFLIGHT_RECORDS_ACCESS_AUTHORITY_FROM_REAL_CAP_EFF=true
RQP_L17_PREFLIGHT_ASSERTS_NO_CAPABILITY_THE_OPERATIONS_DO_NOT_NEED=true
RQP_L17_PREFLIGHT_RECORDS_THE_TOTAL_SET_AND_THE_MOUNT_SUBSET_SEPARATELY=true
```

Image creation, `mkfs`, and the image, mountpoint and invocation-root removals
are not `CAP_SYS_ADMIN` operations at all; they are file-level operations whose
authority is the declared helper access authority plus the object's own DAC
permissions. The three cases' authority sets are separate facts and none widens
another: `CAP_SYS_ADMIN` appears in the mount case's total set because that case
really creates a namespace, binds a loop device, mounts and unmounts, and it
appears in neither ownership case's total set because those cases perform no such
operation.

The evidence-side acquisition is the one effect in the table that no privileged
child performs, so the preflight also records that the ordinary process satisfies
it with no capability at all:

```text
EVIDENCE_ACQUISITION_EFFECT=E21
EVIDENCE_ACQUISITION_REQUIRED_AUTHORITY=none
EVIDENCE_ACQUISITION_ACCESS_AUTHORITY=none
EVIDENCE_ACQUISITION_REQUIRES_CAP_EFF_ZERO=true
EVIDENCE_ACQUISITION_PREFLIGHT_ASSERTS_NO_CAPABILITY_NEEDED=true
EVIDENCE_ACQUISITION_PREFLIGHT_INVALID_IF_A_CAPABILITY_IS_ASSUMED=true
```

**Parent-directory access authority observed, not assumed.** `E26` is the one
helper effect whose target is outside the invocation root: the root's removal is
an entry operation on `RUNNER_TEMP`, so the authority question is a question
about `RUNNER_TEMP`'s own DAC state and cannot be answered by the root's mode.
The preflight therefore observes four facts and records them, and the removal's
single declared authority is unconditional because the observation is a required
fact rather than a selector (1.7.7, 1.10.4):

```text
RUNNER_TEMP_OWNER_OBSERVED_REQUIRED=true
RUNNER_TEMP_MODE_OBSERVED_REQUIRED=true
RUNNER_TEMP_WRITE_SEARCH_DAC_RELATION_OBSERVED_REQUIRED=true
RUNNER_TEMP_STICKY_BIT_STATE_OBSERVED_REQUIRED=true
RUNNER_TEMP_OBSERVATIONS_ARE_PREFLIGHT_FACTS=true
RUNNER_TEMP_OBSERVED_OWNER_UID=
RUNNER_TEMP_OBSERVED_S_IMODE=
RUNNER_TEMP_OBSERVED_STICKY_BIT=
RUNNER_TEMP_HELPER_IDENTITY_WRITE_AND_SEARCH_VIA_DAC=
RUNNER_TEMP_HELPER_IDENTITY_DIRECT_WRITE_OBSERVED_REQUIRED=false
ROOT_REMOVAL_REQUIRES_CAP_DAC_OVERRIDE=true
ROOT_REMOVAL_REQUIRES_CAP_DAC_OVERRIDE_CONDITIONAL_ON_OBSERVED_DAC=false
ROOT_REMOVAL_AUTHORITY_SOURCE=the_observed_RUNNER_TEMP_DAC_relation_and_sticky_bit_state
ROOT_REMOVAL_DAC_SUFFICIENT_OUTCOME=QUALIFICATION_GAP_the_parent_must_withhold_direct_write_from_the_helper
ROOT_REMOVAL_DAC_INSUFFICIENT_OUTCOME=CAP_DAC_OVERRIDE_required_for_the_removal
ROOT_REMOVAL_STICKY_PARENT_OUTCOME=QUALIFICATION_GAP_because_CAP_FOWNER_is_not_declared
ROOT_REMOVAL_CAP_DAC_OVERRIDE_CLAIMED_WITHOUT_OBSERVATION=false
ROOT_REMOVAL_CAP_FOWNER_REQUIRED=false
ROOT_REMOVAL_CAP_FOWNER_CLAIMED_WITHOUT_OBSERVATION=false
BELOW_ROOT_ACCESS_AUTHORITY_SCOPE=every_object_at_a_frozen_role_name_under_the_validated_invocation_root
ROOT_PARENT_REMOVAL_ACCESS_AUTHORITY_SCOPE=RUNNER_TEMP_the_validated_invocation_roots_parent_directory
E15_PARENT_ACCESS_CLOSED=true
```

On the declared runner the observation selects the `CAP_DAC_OVERRIDE` outcome,
because `RUNNER_TEMP` is owned by the runner identity and the helper identity
falls in the "other" class of its mode, so its own DAC bits grant the helper
neither write nor search on that directory. The contract states that as the
result of the observation rather than as an unconditional grant, so a host whose
`RUNNER_TEMP` really does authorize the helper directly does not acquire a
capability invented for it, and a sticky `RUNNER_TEMP` — which would make the
removal of another identity's directory a `CAP_FOWNER` operation — is a
`QUALIFICATION_GAP` rather than an undeclared authority.

```text
CURRENT_ROUND_PREFLIGHT_TOKEN_DUPLICATION_CHECKED=true
```

```text
RQP_L17_PREFLIGHT_RECORDS_ACCESS_AUTHORITY_FROM_REAL_CAP_EFF=true
RQP_L17_PREFLIGHT_ASSERTS_NO_CAPABILITY_THE_OPERATIONS_DO_NOT_NEED=true
RQP_L17_PREFLIGHT_READS_THE_TOTAL_SET_FROM_THE_EFFECT_TABLE=true
RQP_L17_PREFLIGHT_TOKEN_DUPLICATION_CHECKED=true
```

A failed preflight is classified by origin:

- `QUALIFICATION_GAP` when the required real fixture cannot be constructed in
  this environment, including an observed `RUNNER_TEMP` whose sticky bit makes
  the root removal a `CAP_FOWNER` operation this contract does not declare;
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

```text
PRIVATE_MOUNT_NAMESPACE_SCOPE=mount-fixture
OWNERSHIP_CASE_PRIVATE_MOUNT_NAMESPACE=NONE
OWNERSHIP_CASE_PROCESSES_USE_THE_HOST_MOUNT_NAMESPACE=true
```

The private mount namespace is created only in the `mount-fixture` case, because
it exists to confine a real mount to the run. The two ownership cases mount
nothing and detach nothing, so they are not wrapped in a namespace they do not
need: their processes stay in the host mount namespace, they acquire no
`CAP_SYS_ADMIN` and they take no E6 or E7 effect (1.7.4). `PRIVATE_EVIDENCE_MNT_NS_ID`
and `PRIVATE_HELPER_MNT_NS_ID` are therefore `mount-fixture` facts, and the
host-absence control of 10.3 is trivially satisfied for the ownership cases
because no mount namespace or mount event exists in them at all.

| Role | Runs in | Identity | Permitted operations |
| --- | --- | --- | --- |
| `HOST_OBSERVER` | host mount namespace, outside the private namespace | ordinary runner identity | read the host mount table; record the fixture device and mountpoint absence baseline before and after the run; measure and hand off its own real `ORDINARY_UID`/`ORDINARY_GID` (5.10.1) |
| `PRIVILEGED_NAMESPACE_LAUNCHER` | starts in the host mount namespace; in the `mount-fixture` case enters a new private mount namespace, and in the ownership cases stays where it is | reviewed privileged identity via `sudo -n`; the launcher itself never changes identity | validate the handed-off ordinary uid/gid against real filesystem state (5.10.2); create the private mount namespace and make propagation private in the `mount-fixture` case only; establish and report the namespace identity; fork the child that performs the credential transition (5.10.3) and `execve` the evidence process in it |
| `NONROOT_EVIDENCE_PROCESS` | in the private namespace for `mount-fixture`, in the host namespace for the ownership cases; never launched by an external privilege tool | ordinary runner identity, `euid != 0`, `egid == ORDINARY_GID`, empty supplementary group list, and `CapEff == 0`; all four independently reacquired by the process itself (5.10.4) | reacquire its own identity, group list and capability mask before anything else; execute the production primitive under qualification; retain descriptors; measure and record evidence |
| `PRIVILEGED_FIXTURE_HELPER` | the reviewed privileged identity again, via `sudo -n`; inside the private namespace in the `mount-fixture` case, whose setup invocation precedes the credential transition, and whose cleanup invocation follows the evidence process | the reviewed privileged identity | the 5.2 case actions only: fixture ownership mutation by `fchown`, fixture mount setup, `MNT_DETACH` detach, checked cleanup |

Frozen lifecycle, in order. The mount-case setup invocation is placed where the
real lifecycle requires it: the mount-case fixture file cannot exist before the
image is mounted, so the setup helper runs **before** the credential transition,
and the evidence process reacquires its identity after the fixture exists
(1.7.1):

```text
HOST_OBSERVER                records host mount namespace identity / absence baseline
                             measures its own real ORDINARY_UID / ORDINARY_GID
  -> PRIVILEGED_NAMESPACE_LAUNCHER
       sudo -n
       validates ORDINARY_UID != 0, numeric validity, and invocation-root
         st_uid == ORDINARY_UID / st_gid == ORDINARY_GID against real state
       refuses as LAUNCHER_CREDENTIAL_REJECTED before any namespace mutation
         if any credential check fails
       mount-fixture only: creates a private mount namespace, makes propagation
         private, establishes namespace identity
  -> PRIVILEGED_FIXTURE_HELPER   (mount-fixture only, setup invocation)
       invoked from INSIDE the same private namespace
       may regain reviewed privilege via sudo
       creates IMAGE_ROLE and MOUNTPOINT_ROLE exclusively, formats the image,
         binds the loop device by descriptor, mounts ext4, creates and pins
         MOUNTPOINT_ROLE/FIXTURE_FILE_ROLE
       closes its own image and loop descriptors before it exits
     (the ownership cases have their own setup invocation, which performs E2/E3 or E4/E5 before the credential transition and exits)
  -> PRIVILEGED_NAMESPACE_LAUNCHER forks
       the PARENT keeps the reviewed privileged identity and the namespace
       the CHILD performs the credential transition of 5.10.3:
         setgroups(0, NULL), setgid(ORDINARY_GID), setuid(ORDINARY_UID)
         then execve(NONROOT_EVIDENCE_PROCESS)
  -> NONROOT_EVIDENCE_PROCESS
       running inside the private namespace (mount-fixture) or the host
         namespace (own-foreign, own-root)
       reacquires ACTUAL_EUID / ACTUAL_EGID / ACTUAL_SUPPLEMENTARY_GROUPS /
         ACTUAL_CAP_EFF from itself
       requires ACTUAL_EUID == ORDINARY_UID, ACTUAL_EGID == ORDINARY_GID,
         ACTUAL_SUPPLEMENTARY_GROUPS == [], ACTUAL_EUID != 0,
         ACTUAL_CAP_EFF == 0
       executes the production primitive only after those controls pass
  -> PRIVILEGED_FIXTURE_HELPER   (cleanup invocation)
       invoked from INSIDE the same private namespace in the mount-fixture case
       may regain reviewed privilege via sudo
       performs only the reviewed detach / release / removal actions of 10.4
```

```text
HOST_OBSERVER_IN_PRIVATE_NAMESPACE=false
PRIVILEGED_NAMESPACE_LAUNCHER_AUTHORITY=sudo -n only
PRIVILEGED_NAMESPACE_LAUNCHER_ORDINARY_IDENTITY_INPUT=validated_explicit_handoff
PRIVILEGED_NAMESPACE_LAUNCHER_CREDENTIAL_VALIDATION_BEFORE_DROP=true
PRIVILEGED_NAMESPACE_LAUNCHER_NEVER_CHANGES_ITS_OWN_IDENTITY=true
PRIVILEGED_NAMESPACE_LAUNCHER_FORKS_THE_TRANSITION_CHILD=true
CREDENTIAL_TRANSITION_CHILD_IS_THE_EVIDENCE_PROCESS=true
LAUNCHER_PARENT_RETAINS_PRIVILEGE_FOR_CLEANUP=true
NONROOT_EVIDENCE_PROCESS_EUID=ordinary_runner_identity
NONROOT_EVIDENCE_PROCESS_IDENTITY_IS_REACQUIRED=true
NONROOT_EVIDENCE_PROCESS_CAP_EFF_REQUIRED=0
NONROOT_EVIDENCE_PROCESS_SUPPLEMENTARY_GROUPS_REQUIRED=empty
NONROOT_EVIDENCE_PROCESS_LAUNCHED_BY_EXTERNAL_PRIVILEGE_TOOL=false
FIXTURE_HELPER_INVOCATION_ORIGIN=inside_the_same_private_namespace
FIXTURE_HELPER_REGAINS_PRIVILEGE=sudo -n only
FIXTURE_HELPER_ACTION_SCOPE=reviewed_setup_detach_cleanup_only
FIXTURE_HELPER_SETUP_INVOCATION_PRECEDES_CREDENTIAL_TRANSITION=true
FIXTURE_HELPER_SETUP_INVOCATION_SCOPE=mount-fixture
FIXTURE_HELPER_SETUP_INVOCATION_OWNS_THE_FIXTURE_DESCRIPTORS=true
FIXTURE_HELPER_CLOSES_IMAGE_AND_LOOP_DESCRIPTORS_BEFORE_EXIT=true
FIXTURE_HELPER_CLEANUP_INVOCATION_HOLDS_ITS_OWN_DESCRIPTORS=true
NONROOT_EVIDENCE_PROCESS_LAUNCH_IS_A_REQUEST_NOT_A_FACT=true
```

**Frozen cross-process detach and resume protocol.** The successful `mount-fixture`
path has two privileged helper invocations *after* the evidence process is running,
and the evidence process is the process that requests both of them. This is what
makes the detach evidence implementable: the descriptor whose survival across the
detach is the whole point of the case is opened by the non-root evidence process and
never leaves it, while the privileged `MNT_DETACH` is performed by a helper that
holds no fixture descriptor at all. The order is fixed:

```text
NONROOT_EVIDENCE_PROCESS        E21: opens the mount-case child O_RDONLY with no
                                     capability, reacquires its own identity, records
                                     the positive pre-drift production admission,
                                     and retains its own descriptor
  -> PRIVILEGED_FIXTURE_HELPER  (detach invocation, --case=detach-fixture)
       invoked synchronously by the still-running evidence process
       validates the root under 5.3, measures its own namespace identity and
         requires PRIVATE_HELPER_MNT_NS_ID == PRIVATE_EVIDENCE_MNT_NS_ID and
         != HOST_MNT_NS_ID, observes the state ATTACHED, validates the frozen
         MOUNTPOINT_ROLE target against its own validated root descriptor
       performs MNT_DETACH (E15) and exits
       it never receives, holds or closes the evidence descriptor
  -> NONROOT_EVIDENCE_PROCESS    observes the helper's exit status as a
                                     NON-EVIDENCE completion signal, stays alive,
                                     keeps the SAME descriptor open, and
                                     independently reacquires the mount state
                                     (fstat, statx mount id, real mountinfo)
       E22: post-detach production observation, then E23: closes its own descriptor
  -> PRIVILEGED_FIXTURE_HELPER  (final cleanup invocation, --case=cleanup)
       invoked synchronously by the evidence process after E23
       validates the root, the namespace identity and the observed mount state
       performs E17 (loop release), E24 (mount-object removal) and E26 (root
         removal) in the 10.4 order, and no unmount, because after a successful
         MNT_DETACH there is no mount object to unmount
```

```text
CROSS_PROCESS_DETACH_RESUME_PROTOCOL_FROZEN=true
DETACH_AND_RESUME_ARE_TWO_SEPARATE_HELPER_INVOCATIONS=true
EVIDENCE_PROCESS_SURVIVES_DETACH_HELPER=true
EVIDENCE_PROCESS_IS_ALIVE_ACROSS_BOTH_HELPER_INVOCATIONS=true
DETACH_HELPER_IS_A_SEPARATE_PRIVILEGED_INVOCATION=true
DETACH_HELPER_REQUESTED_BY_THE_EVIDENCE_PROCESS=true
DETACH_HELPER_ACTION=detach-fixture
DETACH_HELPER_ACCEPTS_NO_INHERITED_DESCRIPTOR=true
DETACH_HELPER_RETAINS_NO_EVIDENCE_DESCRIPTOR=true
DETACH_HELPER_VALIDATES_ROOT=true
DETACH_HELPER_VALIDATES_NAMESPACE_IDENTITY=true
DETACH_HELPER_VALIDATES_THE_MOUNT_TARGET=true
DETACH_HELPER_COMPLETION_CARRIER_DECLARED=true
DETACH_HELPER_COMPLETION_CARRIER=helper_process_exit_status
DETACH_HELPER_COMPLETION_IS_A_NON_EVIDENCE_COMPLETION_SIGNAL=true
DETACH_HELPER_COMPLETION_IS_NOT_EVIDENCE=true
EVIDENCE_DESCRIPTOR_HELD_ACROSS_THE_DETACH_HELPER=true
EVIDENCE_DESCRIPTOR_IS_THE_SAME_DESCRIPTOR_AFTER_THE_HELPER_EXITS=true
EVIDENCE_DESCRIPTOR_IS_NOT_REOPENED_AFTER_THE_DETACH_HELPER=true
MOUNT_STATE_IS_INDEPENDENTLY_REACQUIRED_AFTER_THE_DETACH_HELPER=true
MOUNT_STATE_REACQUISITION_PRODUCER=E22_nonroot_evidence_process
FINAL_CLEANUP_HELPER_IS_A_SEPARATE_PRIVILEGED_INVOCATION=true
FINAL_CLEANUP_HELPER_REQUESTED_BY_THE_EVIDENCE_PROCESS=true
FINAL_CLEANUP_HELPER_AFTER_E23=true
FINAL_CLEANUP_HELPER_ACTION=cleanup
FINAL_CLEANUP_HELPER_PERFORMS=E17,E24,E26
FINAL_CLEANUP_HELPER_PERFORMS_NO_UNMOUNT_AFTER_MNT_DETACH=true
DETACH_HELPER_IS_NOT_THE_FINAL_CLEANUP_HELPER=true
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

The three identities and the two equalities above are `mount-fixture` controls
(1.7.4): they exist to prove that the mount fixture and its consumer share one
private namespace that is not the host's. The ownership cases create no private
namespace, so for them `PRIVATE_EVIDENCE_MNT_NS_ID` and
`PRIVATE_HELPER_MNT_NS_ID` are the host identity and the two equalities are
satisfied trivially while proving nothing; the contract MUST NOT report them as
namespace-isolation evidence for an ownership case, and no ownership case may be
reported as having passed a namespace control:

```text
NAMESPACE_IDENTITY_CONTROLS_SCOPE=mount-fixture
OWNERSHIP_CASE_NAMESPACE_IDENTITY_IS_HOST_IDENTITY=true
OWNERSHIP_CASE_NAMESPACE_CONTROL_IS_NOT_EVIDENCE=true
OWNERSHIP_CASE_PRIVATE_NAMESPACE_CREATED=false
```

Membership continuity and identity observation are separate facts, frozen that
way in 5.5: membership is `INHERITED` across this lifecycle — the credential
transition changes credentials rather than mount namespace membership, and in the
`mount-fixture` case the transition child inherits the namespace the launcher
created before the `fork` — while identity is `INDEPENDENTLY_REACQUIRED` by every
process. The equality above is therefore measured rather than inferred from that
inheritance, and a process that cannot read its own real identity cannot satisfy
this contract.

```text
NAMESPACE_IDENTITY_MEASURED=true
NAMESPACE_IDENTITY_SOURCE=/proc/self/ns/mnt inode
NAMESPACE_IDENTITY_ASSUMED_FROM_SUDO=false
NAMESPACE_IDENTITY_ASSUMED_FROM_THE_CREDENTIAL_TRANSITION=false
PRIVATE_EVIDENCE_HELPER_SAME_NAMESPACE_REQUIRED=true
PRIVATE_NAMESPACE_DIFFERS_FROM_HOST_REQUIRED=true
```

The evidence process's identity, supplementary group list and capabilities are
measured with the same discipline, and are required before the production
primitive executes:

```text
NONROOT_EVIDENCE_PROCESS_IDENTITY_MEASURED=true
NONROOT_EVIDENCE_PROCESS_IDENTITY_SOURCE=own real process state
NONROOT_EVIDENCE_PROCESS_CAP_EFF_SOURCE=/proc/self/status CapEff decoded from the real mask
NONROOT_EVIDENCE_PROCESS_SUPPLEMENTARY_GROUPS_SOURCE=getgroups_and_the_real_Groups_field_of_proc_self_status
NONROOT_EVIDENCE_IDENTITY_ASSUMED_FROM_LAUNCH_REQUEST=false
NONROOT_EVIDENCE_IDENTITY_ASSUMED_FROM_SUDO=false
NONROOT_EVIDENCE_PROCESS_EUID_NONZERO_IS_NOT_SUFFICIENT=true
NONROOT_EVIDENCE_PROCESS_EMPTY_SUPPLEMENTARY_GROUPS_IS_REQUIRED=true
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
| N4 | launcher -> evidence process: namespace membership, requested credentials, actual identity | namespace membership: `INHERITED` across `fork` and the credential transition's `execve`; requested ordinary uid/gid: `EXPLICITLY_HANDED_OFF` to the launcher and validated before the transition; the intended empty supplementary group list: not transported at all, produced in the transition child (5.10.3); actual identity, group list and capabilities: `INDEPENDENTLY_REACQUIRED` by the evidence process | ordinary runner identity | privileged namespace launcher | inherited mount namespace across `fork`/`execve`, fixed numeric credential arguments, and the evidence process's own real process state | until namespace exit | evidence process | `PRIVATE_EVIDENCE_MNT_NS_ID` measured and equal to the private identity, and `ACTUAL_EUID == ORDINARY_UID`, `ACTUAL_EGID == ORDINARY_GID`, `ACTUAL_SUPPLEMENTARY_GROUPS == []`, `ACTUAL_EUID != 0`, `ACTUAL_CAP_EFF == 0` all recorded before the production call |
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
   retained mount descriptor and any descriptor a helper invocation holds; the
   final cleanup invocation holds its own descriptors and closes them before the
   release, and the setup invocation already closed its image and loop
   descriptors when it exited (10.1);
3. verify the held mount no longer appears in the private mount table, that is,
   zero records carry the held mount id;
4. allow the kernel to release the detached mount;
5. release the loop backing;
6. verify the loop backing is gone;
7. remove the case's fixture objects and then the invocation-specific root.

```text
CLEANUP_FROM_ATTACHED=checked_unmount_then_release_loop
CLEANUP_FROM_DETACHED_BUSY=close_descriptors_then_verify_then_release_loop
SECOND_UNMOUNT_AFTER_MNT_DETACH_REQUIRED=false
CLEANUP_REQUIRES_ORDER=true
CLEANUP_INVOCATION_IS_THE_PRIVILEGED_FIXTURE_HELPER=true
CLEANUP_INVOCATION_IS_NOT_THE_EVIDENCE_PROCESS=true
CLEANUP_INVOCATION_HOLDS_ITS_OWN_DESCRIPTORS=true
CLEANUP_DESCRIPTORS_CLOSED_BEFORE_LOOP_RELEASE=true
CLEANUP_REMOVAL_ORDER_IS_CASE_AWARE=true
CLEANUP_MOUNT_CASE_REMOVAL_ORDER=E24_then_E26
CLEANUP_MOUNT_CASE_REMOVAL_ORDER_DERIVATION=fixture_objects_then_invocation_root
CLEANUP_MOUNT_CASE_LOOP_RELEASE_ORDER=E23_then_E17_then_E24_then_E26
CLEANUP_OWNERSHIP_CASE_REMOVAL_ORDER=E25_then_E26
CLEANUP_OWNERSHIP_CASE_LOOP_RELEASE_ORDER=not_applicable_no_loop_device
CLEANUP_ORDER_FOLLOWS_THE_EFFECT_DEPENDENCY_DAG=true
CLEANUP_OWNERSHIP_FIXTURE_UNLINK_REQUIRED=true
CLEANUP_OWNERSHIP_FIXTURE_UNLINK_BEFORE_ROOT_REMOVAL=true
CLEANUP_OWNERSHIP_FIXTURE_UNLINK_IS_EFFECT=E25
CLEANUP_OWNERSHIP_FIXTURE_UNLINK_AUTHORITY=CAP_DAC_OVERRIDE
CLEANUP_OWNERSHIP_FIXTURE_UNLINK_REQUIRES_CAP_DAC_READ_SEARCH=false
CLEANUP_OWNERSHIP_FIXTURE_UNLINK_REQUIRES_CAP_CHOWN=false
CLEANUP_OWNERSHIP_CASE_ROOT_REMOVAL_WITHOUT_UNLINK_IS_INVALID=true
CLEANUP_MOUNTPOINT_REMOVAL_EFFECT=E24
CLEANUP_IMAGE_REMOVAL_EFFECT=E24
CLEANUP_FIXTURE_OBJECT_REMOVAL_EFFECT=E25
CLEANUP_INVOCATION_ROOT_REMOVAL_EFFECT=E26
CLEANUP_EVIDENCE_DESCRIPTOR_CLOSED_BY_E23_AFTER_E22=true
```

The removal order is stated as the graph's own edges rather than as a separate
case-aware rule, and the round-6 conditional is withdrawn for a second time for
the same reason as round 7: every case removes its fixture objects and then its
invocation root, so there is exactly one removal order. Effect ids changed
meaning across rounds, and the change is called out explicitly, because a reader
who carried an earlier round's ids forward would misread this section. Round 9's
ids are the current ones, and they are the ones the closure table uses:

```text
CLEANUP_E21_IS_THE_EVIDENCE_SIDE_ACQUISITION=true
CLEANUP_E21_IS_NOT_THE_INVOCATION_ROOT_REMOVAL=true
CLEANUP_E22_IS_THE_POST_DETACH_OBSERVATION=true
CLEANUP_E23_IS_THE_EVIDENCE_SIDE_DESCRIPTOR_RELEASE=true
CLEANUP_E24_IS_THE_MOUNT_OBJECT_REMOVAL=true
CLEANUP_E25_IS_THE_FIXTURE_OBJECT_REMOVAL=true
CLEANUP_E26_IS_THE_INVOCATION_ROOT_REMOVAL=true
CLEANUP_E17_IS_THE_LOOP_BACKING_RELEASE=true
CLEANUP_E15_IS_THE_MNT_DETACH=true
CLEANUP_E16_IS_THE_ATTACHED_STATE_UNMOUNT=true
CLEANUP_ORDER_TOKEN_EFFECT_IDS_MATCH_THE_TABLE=true
ROUND7_EFFECT_ID_MEANINGS_ARE_HISTORICAL_ONLY=true
ROUND7_E20_MEANING=mountpoint_removal
ROUND7_E21_MEANING=fixture_object_removal
ROUND7_E22_MEANING=invocation_root_removal
ROUND7_CLEANUP_IDS_ARE_NOT_CURRENT=true
ROUND9_CLEANUP_IDS_ARE_CURRENT=true
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
The release precedes the removal of the image it was bound to, so no removal step
ever unlinks a backing file that a loop device still carries.

The final controls are mandatory and are recorded as observed values:

```text
PRIVATE_MOUNT_RESIDUE=false
LOOP_BACKING_RESIDUE=false
FIXTURE_ROOT_RESIDUE=false
HOST_NAMESPACE_RESIDUE=false
```

`PRIVATE_MOUNT_RESIDUE` is measured inside the private namespace in the
`mount-fixture` case, where a private namespace exists to measure; the ownership
cases create none, so for them the equivalent control is
`HOST_NAMESPACE_RESIDUE=false` measured by the host observer, and no ownership
case may report a private-namespace residue control it did not measure (1.7.4).
`HOST_NAMESPACE_RESIDUE` is measured by the host observer under 10.3. A residue
control that is asserted rather than measured is not a control.

```text
PRIVATE_MOUNT_RESIDUE_CONTROL_SCOPE=mount-fixture
OWNERSHIP_CASE_PRIVATE_MOUNT_RESIDUE_CONTROL=NOT_APPLICABLE_NO_PRIVATE_NAMESPACE
OWNERSHIP_CASE_RESIDUE_CONTROL=HOST_NAMESPACE_RESIDUE_and_FIXTURE_ROOT_RESIDUE
CLEANUP_STATE_MACHINE_SCOPE=mount-fixture
OWNERSHIP_CASE_CLEANUP_STATE=NONE
OWNERSHIP_CASE_CLEANUP_IS_E23_then_E25_then_E26=true
MOUNT_CASE_CLEANUP_IS_E23_then_E17_then_E24_then_E26=true
MOUNT_CASE_E25_NOOP_COUNT=0
DUPLICATE_CLEANUP_TARGET_COUNT=0
```

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

### 15.1 Structural probe obligations for this head

Round 7 requires the closure to be proved mechanically rather than by row count,
so the invariants below are the probe obligations for this head. Each is a
comparison between two machine-like sets or between a set and the table, and each
is falsifiable without reading prose. The row count alone is explicitly not
completeness evidence:

```text
STRUCTURAL_PROBE_ROW_COUNT_IS_COMPLETENESS_EVIDENCE=false
STRUCTURAL_PROBE_01=real_effect_set_equals_closure_table_rows
STRUCTURAL_PROBE_02=no_placeholder_or_no_effect_row_counted
STRUCTURAL_PROBE_03=each_effect_appears_in_exactly_its_intended_case_set
STRUCTURAL_PROBE_04=each_cases_total_authority_set_equals_the_union_of_its_effects
STRUCTURAL_PROBE_05=global_capability_inventory_equals_union_of_required_capability_authorities
STRUCTURAL_PROBE_06=every_effect_row_carries_all_required_fields
STRUCTURAL_PROBE_07=every_created_or_mutated_object_has_a_terminal_lifecycle
STRUCTURAL_PROBE_08=machine_like_access_authority_sets_equal_the_table
STRUCTURAL_PROBE_09=exactly_one_bare_current_round_parent_pointer
STRUCTURAL_PROBE_10=no_unresolved_retired_token_remains_active
STRUCTURAL_PROBE_11=exactly_one_value_per_current_pointer_key_document_wide
STRUCTURAL_PROBE_COUNT=11
EFFECT_ROW_REQUIRED_FIELDS=effect_number,case_scope,operation_or_effect,target_object,target_binding_mechanism,required_authority,preconditions,postconditions,cleanup_or_terminal_transition
EFFECT_ROW_REQUIRED_FIELD_COUNT=9
EVERY_EFFECT_ROW_HAS_ALL_REQUIRED_FIELDS=true
PROBE_09_SCOPE=the_document_wide_KEY_VALUE_duplicate_value_probe_of_1_7_and_20
PROBE_10_RETIRED_TOKEN_NAMES=OWNERSHIP_FIXTURE_REQUIRED_CAPABILITY_SET,RQP_L17_REQUIRED_CAPABILITY_SET
PROBE_10_RETIRED_TOKENS_APPEAR_ONLY_INSIDE_RETIREMENT_RECORDS=true
CURRENT_DOCUMENT_TOKEN_DUPLICATION_PROBE=PASS
```

```text
ROUND10_STRUCTURAL_PROBE_OBLIGATIONS=14
ROUND10_PROBE_01=registry_meaning_is_unique_and_no_current_section_contradicts_it
ROUND10_PROBE_02=no_closure_row_references_itself_as_predecessor_or_successor
ROUND10_PROBE_03=every_effect_id_in_every_current_section_resolves_to_the_registry_meaning
ROUND10_PROBE_04=every_case_graph_sorts_and_every_edge_is_a_real_lifecycle_prerequisite
ROUND10_PROBE_05=no_topological_order_places_E15_before_E21
ROUND10_PROBE_06=the_attached_failure_branch_is_enterable_from_both_entry_states
ROUND10_PROBE_07=cross_case_predecessor_leak_count_is_zero
ROUND10_PROBE_08=the_authority_column_equals_the_AUTHORITY_E_tokens
ROUND10_PROBE_09=no_effect_declares_a_capability_its_operation_does_not_need
ROUND10_PROBE_10=no_declared_capability_is_unused_by_every_effect
ROUND10_PROBE_11=the_mount_case_contains_no_no_op_effect
ROUND10_PROBE_12=the_formatter_child_allowlist_contains_the_formatter_fd_and_no_unrelated_descriptor
ROUND10_PROBE_13=the_case_effect_sets_equal_the_rows_with_matching_scope
ROUND10_PROBE_14=every_current_pointer_key_carries_exactly_one_value
ROUND10_PROBE_LIST_IS_THE_COMPLETENESS_EVIDENCE=false
ROUND10_PROBE_RESULT=PASS
ROUND10_PROBE_FAIL_COUNT=0
ROUND10_PROBE_SELF_TEST=the_same_suite_rejects_the_failed_round9_text
```

The document-wide duplicate-value probe is the one 20 records: a `KEY=VALUE`
token whose key is a current-pointer key — that is, a key that is not an
enumeration over one attribute, not a historical round-qualified record, and not
a per-case variant such as `reason_code` — must carry exactly one value in the
whole document. The three legitimate multi-value forms are named explicitly so
the probe has no silent exclusions:

```text
MULTI_VALUE_KEY_FORM_1=enumeration_over_one_attribute_such_as_MOUNT_STATE
MULTI_VALUE_KEY_FORM_2=historical_round_qualified_record_such_as_A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD
MULTI_VALUE_KEY_FORM_3=per_case_or_per_object_variant_such_as_reason_code
MULTI_VALUE_KEY_FORM_4=none_other_exists=true
SUPERSEDED_ROUND_TOKENS_ARE_RENAMED_WITH_A_ROUND_QUALIFIER=true
SUPERSEDED_ROUND_TOKENS_ARE_DELETED=false
SUPERSEDED_ROUND_TOKENS_ARE_LEFT_COLLIDING=false
```

The round-6 and round-5 tokens that a later round superseded are therefore kept
under a `ROUND6_` or round-qualified name rather than left colliding with the
current key, so the history stays readable and the current-pointer key keeps
exactly one value. That is the mechanism that closes finding 9 and the
duplicate-value half of finding 1, and it is the reason the round-6 effect
numbers are labelled as round-6 numbers everywhere they still appear.

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
that the helper-created mount child cannot satisfy. Round 5 re-ran it against the
round-5 head, in which the mode-provenance scope (5.8, 5.8.3), the child-object
outcome scope (5.8.1, 5.8.3, 5.9), the per-effect privileged closure (1.5, 7) and
the cleanup ownership-resolution (5, 10.4) are the corrected statements. Round 6
re-ran it against the round-6 head, in which the ownership capability set (1.6,
7), the per-effect access authority (1.5, 1.6), the ownership-case removal effect
and the case-aware root-removal lifecycle (1.5, 1.6, 10.4) were the corrected
statements. Round 7 re-runs it against this head, in which the effect sets are
derived from the real lifecycle (1.7.1), the credential transition is a declared
effect with frozen authorities (1.7.2, 5.10.3), the mountpoint-creation effect is
declared (1.7.3, 5.9), the namespace scope and the case total authority sets are
corrected (1.7.4, 1.7.5), the non-mount cleanup effects are common to every case
(1.7.6), the parent-directory access authority is observed rather than assumed
(1.7.7, 7), and the image access precondition and the loop target binding are
frozen (1.7.8, 5.9) are the corrected statements.
Each result is claimed only
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
ROUND5_PRIVILEGED_EFFECT_AUTHORITY_CLOSURE_ROWS=16
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
ROUND6_BLOCKING_FINDINGS_CLOSED=3
BLOCKING_FINDINGS_OPEN=0
```

- `PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS` (round-5 statement, corrected in
  round 6 and again in round 7) — at this head all twenty-two material effects
  have one row each in 1.5, with a target object, a target-binding mechanism, an
  authority derived from that effect's own operation, preconditions,
  postconditions and a cleanup or terminal transition. The closure holds in both
  directions: every effect has a declared authority, and every declared authority
  is bound to effects that really need it, so no capability is granted for
  nothing and no effect is left unauthorized. Round 5 stated the authority facts
  as `CAP_CHOWN` bound to E1 and E2, `CAP_SYS_ADMIN` to
  E3, E4, E20, E9, E7, E10 and E15, one declared access authority to the nine
  effects that touch objects under the invocation root, and `CAP_FOWNER`,
  `CAP_DAC_READ_SEARCH` and every other capability to none. That last clause was
  wrong for the traversal effects and round 6 corrected it by deriving the access
  authority per effect; round 6's own numbers were then retired when round 7
  rebuilt the table in lifecycle order (1.6). Round 7 corrects the two facts the
  round-6 derivation still lacked: the credential transition's `CAP_SETGID` and
  `CAP_SETUID`, which no round-6 row named, and the mountpoint-creation effect,
  which no round-6 row had. The `mkfs` and image-creation effects remain the
  clearest case of the derivation mattering: they are ordinary file writes and
  creates, and grouping them under `CAP_SYS_ADMIN` would have declared an
  authority no operation of theirs exercises.
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
- `CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS` (round-5 statement, extended in
  round 6) — the state
  machine's transitions are all real operations with declared authorities: the
  `ATTACHED` path through the ordinary unmount, the `DETACHED_BUSY` path through
  descriptor closure, verification and loop release, then removal of the image,
  the mountpoint and the root. `SECOND_UNMOUNT_AFTER_MNT_DETACH_REQUIRED=false`
  stays implementable because `MNT_DETACH` disconnects the mount from the table
  immediately, and the withdrawal of the ownership-restoration requirement
  removes the one step that had no effect row, no consumer and no place in the
  frozen order. Round 6 adds the ownership cases' own removal step ahead of the
  root removal and makes the root-removal precondition case-aware, so the
  removal order is `E23`-then-`E17`-then-`E24`-then-`E26` for `mount-fixture` and
  `E23`-then-`E25`-then-`E26` for the ownership cases (10.4, 1.10.5).
- `A3_CONTRACT_IMPLEMENTABILITY=PASS` is claimed only after the round-5
  re-evaluation above and every earlier result it depends on are `PASS`, and only
  because each of the three blocking findings is closed at that head by a
  statement that names its owner, its producer, its carrier, its consumer and its
  closing point: the mode-provenance scope (1.5, 5.8, 5.8.3), the child-object
  outcome scope (1.5, 5.8.1, 5.8.3, 5.9), and the per-effect privileged closure
  with its declared access authority (1.5, 7). This is a round-5 statement; the
  round-6 result below is the one that governs this head.

Round 6 re-evaluated the five results the three new blocking findings touch.
Each is `PASS` only because the corrected statements close the gap the finding
named:

```text
ROUND6_RE_EVALUATED_RESULTS=OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY,PRIVILEGED_EFFECT_AUTHORITY_CLOSURE,CLEANUP_STATE_MACHINE_IMPLEMENTABILITY,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY=PASS
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS
PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS
A3_CONTRACT_IMPLEMENTABILITY=PASS
ROUND6_OWNERSHIP_TOTAL_AUTHORITY_SET_CLOSED=true
ROUND6_ACCESS_AUTHORITY_SCOPE_CLOSED=true
ROUND6_OWNERSHIP_FIXTURE_FILE_REMOVAL_EFFECT_DECLARED=true
ROUND6_ROOT_REMOVAL_CASE_LIFECYCLE_CLOSED=true
ROUND6_REAL_EFFECT_ROW_COUNT=16
ROUND6_PLACEHOLDER_EFFECT_ROW_COUNT=0
ROUND6_ACCESS_AUTHORITY_EFFECT_TABLE_TOKEN_EQUIVALENT=true
ROUND6_BLOCKING_FINDINGS_CLOSED=3
BLOCKING_FINDINGS_OPEN=0
ROUND6_RESULTS_ARE_ROUND6_RECORDS=true
ROUND6_RESULTS_ARE_CURRENT_CLAIMS=false
```

- `OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY=PASS` (round-6 statement,
  corrected in round 7) — the ownership case's authority is decomposed and
  recomputed rather than under-stated: `CAP_CHOWN` is exactly the mutation
  authority for the single `fchown`, `CAP_DAC_READ_SEARCH` is exactly the
  traversal authority needed to open the pinned child under the owner-only root
  and to reach the root's parent, `CAP_DAC_OVERRIDE` is exactly the
  directory-write authority needed to unlink that child and to remove the root
  entry, and `CAP_SETGID` with `CAP_SETUID` are exactly the credential
  transition's authorities. All five are real required capabilities, each is
  bound to a specific operation, and the case's total set is their union and
  nothing more.
- `PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS` (round-6 statement, corrected in
  round 7) — round 6 closed the access-authority scope disagreement by deriving
  each effect's access authority for that effect and by checking the row sets
  against the machine-like tokens
  (`ROUND6_ACCESS_AUTHORITY_EFFECT_TABLE_TOKEN_EQUIVALENT=true`). Round 7 keeps
  that method and re-derives the sets over the rebuilt table, so the equivalence
  is now stated once, in 1.5, against the current effect numbers.
- `CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS` (round-6 statement, corrected in
  round 7) — the ownership cases now have a removal step for the object the setup
  mutated, ordered before the root removal, with its own binding, authority and
  postcondition. Round 6 made the root-removal precondition case-aware; round 7
  withdraws that conditionality (1.7.6), because the removal effect it branched
  on is common to every case and a case-aware precondition is the shape that
  would let a case require an effect its own lifecycle never performs.
- `PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS` (re-evaluated) — the
  confinement model is unchanged at all three call sites, and the cleanup unlink
  of the ownership child revalidates the pinned identity by a no-follow `fstatat`
  before removing the name, so confinement is preserved through the destructive
  step instead of ending at the mutation.
- `A3_CONTRACT_IMPLEMENTABILITY=PASS` is claimed only after the round-6
  re-evaluation above and every earlier result it depends on are `PASS`, and only
  because each of the three new blocking findings is closed at the round-6 head by
  a statement that names its owner, producer, carrier, consumer and closing point:
  the ownership capability set split (1.6, 7), the per-effect access authority
  with its row/token equivalence (1.5, 1.6), and the ownership-case removal effect
  with the case-aware root-removal lifecycle (1.5, 1.6, 10.4). This is a round-6
  statement; the round-7 result below is the one that governs this head.

Round 7 re-evaluated the six results the nine new blocking findings touch. Each is
`PASS` only because the corrected statements close the gap its finding named:

```text
ROUND7_RE_EVALUATED_RESULTS=PRIVILEGED_EFFECT_AUTHORITY_CLOSURE,CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY,NAMESPACE_LIFECYCLE_IMPLEMENTABILITY,CLEANUP_STATE_MACHINE_IMPLEMENTABILITY,PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY,A3_CONTRACT_IMPLEMENTABILITY
PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS
CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY=PASS
NAMESPACE_LIFECYCLE_IMPLEMENTABILITY=PASS
CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS
PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS
A3_CONTRACT_IMPLEMENTABILITY=PASS
EFFECT_SET_DERIVED_FROM_REAL_LIFECYCLE=true
CASE_EFFECT_SCOPE_CLOSED=true
CASE_TOTAL_AUTHORITY_SETS_CLOSED=true
CREDENTIAL_TRANSITION_EFFECT_DECLARED=true
SUPPLEMENTARY_GROUP_SEMANTICS_CLOSED=true
MOUNTPOINT_CREATION_EFFECT_DECLARED=true
NAMESPACE_SCOPE_CLOSED=true
E15_PARENT_ACCESS_CLOSED=true
IMAGE_ACCESS_PRECONDITION_CLOSED=true
LOOP_TARGET_BINDING_CLOSED=true
GIT_CURRENT_PARENT_TOKEN_UNIQUE=true
REAL_EFFECT_ROW_COUNT=26
PLACEHOLDER_EFFECT_ROW_COUNT=0
CASE_TOTAL_AUTHORITY_SET_EQUALS_EFFECT_AUTHORITY_UNION=true
GLOBAL_CAPABILITY_INVENTORY_EQUALS_UNION_OF_REQUIRED_CAPABILITY_AUTHORITIES=true
EVERY_CREATED_OR_MUTATED_OBJECT_HAS_TERMINAL_LIFECYCLE=true
CURRENT_DOCUMENT_TOKEN_DUPLICATION_PROBE=PASS
ROUND7_BLOCKING_FINDINGS_CLOSED=9
BLOCKING_FINDINGS_OPEN=0
```

- `PRIVILEGED_EFFECT_AUTHORITY_CLOSURE=PASS` (round-7 statement) — the effect set
  is derived from the real lifecycle, each case's effect set and total authority
  set are stated separately and equal by construction, and the closure holds in
  both directions over all twenty-two rows: every effect has a declared authority,
  every declared authority has a required effect, and no declared authority is
  broader than the effects that need it. `CAP_SETGID` and `CAP_SETUID` are bound
  to exactly one effect, the credential transition, and `CAP_SYS_ADMIN` is bound
  to exactly the mount case's seven mount and loop effects.
- `CROSS_BOUNDARY_CONTINUITY_IMPLEMENTABILITY=PASS` (re-evaluated) — the
  supplementary group list is the one new crossing fact, and it is classified
  rather than left unclassified: `INHERITED` with no carrier, independently
  reacquired by the evidence process from itself, compared against the frozen
  empty list, recorded before the production primitive, and closed at the same
  checkpoint as the identity and capability controls (5.10.3, 5.6 T10, 10.2 N4).
  No row in 5.5, 5.6 or 10.2 claims a carrier for an inherited fact.
- `NAMESPACE_LIFECYCLE_IMPLEMENTABILITY=PASS` (re-evaluated) — the private mount
  namespace is a `mount-fixture` effect, created by the launcher before the
  credential transition, inherited by the transition child across `fork` and
  `execve`, and destroyed with the last member process; the ownership cases create
  no namespace and claim no namespace control. The lifecycle is therefore
  implementable for every case, and no case is required to hold state it never
  creates.
- `CLEANUP_STATE_MACHINE_IMPLEMENTABILITY=PASS` (re-evaluated) — the cleanup
  order is `E17` then `E24` then `E26` for `mount-fixture` and `E25` then `E26`
  for the ownership cases; the cleanup invocation holds its own descriptors, the
  setup invocation closes the image and loop descriptors before it exits, and the
  loop release precedes the image removal it would otherwise block.
- `PRIVILEGED_CHILD_INODE_CONFINEMENT_IMPLEMENTABILITY=PASS` (re-evaluated) — the
  confinement model is unchanged at all three call sites; the mount case's
  `MOUNTPOINT_ROLE` creation is now an effect row of its own with
  `HELPER_ROOT_REJECTED` for a pre-existing object, so the object E14 mounts on is
  the object E8 created and pinned, and the ownership cases still bind a child
  that must preexist.
- `A3_CONTRACT_IMPLEMENTABILITY=PASS` is claimed only after the round-7
  re-evaluation above and every earlier result it depends on are `PASS`, and only
  because each of the nine blocking findings is closed at this head by a statement
  that names its owner, its producer, its carrier, its consumer and its closing
  point.

The nine round-7 blocking findings are closed as follows. The effect ids quoted
inside this table and the round-6 table below are the round-6 and round-7 ids those
rounds recorded, kept under the numbering they were written with so the historical
findings stay auditable; the current registry is 1.9.1 and the current bindings are
re-derived in 1.10.4, so no id in these two tables is a current pointer:

| Blocking finding | Corrected statement at this head | Why it is now implementable |
| --- | --- | --- |
| the effect set was derived from the existing table, so the table validated itself | the case effect sets and the closure table are derived from the real lifecycle and the object lifecycle, and `EFFECT_SET_DERIVED_FROM_EXISTING_TABLE=false` with `EFFECT_ROW_COUNT_IS_COMPLETENESS_EVIDENCE=false` (1.7.1, 1.5) | the twenty-two rows are the union of three independently enumerated case sets, so a missing effect shows up as an effect absent from every case's set rather than as a row count that still matches |
| `E3`/`E4` were run-scoped while section 10 is RQP-L17-specific, and the RQP-L17 set omitted the namespace authority | the private namespace and its private propagation are `mount-fixture` effects `E6` and `E7`, and `OWNERSHIP_CASE_REQUIRES_PRIVATE_MOUNT_NAMESPACE=false` with `OWNERSHIP_CASE_REQUIRES_CAP_SYS_ADMIN=false` (1.7.4, 1.5, 10.1) | the ownership cases never mount, so they need no namespace and acquire no `CAP_SYS_ADMIN`; RQP-L17 still gets both effects because it does mount, and its total authority set now names them |
| the credential transition was not a declared effect | `E1` declares the transition with the frozen `setgroups`/`setgid`/`setuid` order, the `CAP_SETGID` and `CAP_SETUID` authority, and the frozen empty supplementary group list with its producer, continuity class, independent reacquisition, comparison and closing point (1.7.2, 5.10.3, 10.1) | every step of the transition is a real operation the launcher's child can perform with a declared authority, the order is forced by which capability each step needs, and the value the evidence process must have is measured from the process itself rather than assumed |
| section 5.9 required helper-exclusive creation of `MOUNTPOINT_ROLE` but no row created it | `E8` is the mountpoint-creation effect: `mkdirat` relative to the validated root descriptor, exclusive create with `HELPER_ROOT_REJECTED` for a pre-existing object, exact `0755`, `CAP_DAC_OVERRIDE` plus `CAP_DAC_READ_SEARCH`, and cleanup through the existing mountpoint-removal effect `E24` (1.7.3, 5.9) | the requirement now has an operation, a binding, an authority, preconditions, postconditions and a terminal transition, and the `0755` mode is what makes the ordinary identity's DAC witness reachable through the mountpoint |
| one "mount-related capability set" stood in for each case's whole authority set | `RQP_L17_REQUIRED_CAPABILITY_SET` is retired and replaced by `RQP_L17_TOTAL_REQUIRED_AUTHORITY_SET` with `RQP_L17_MOUNT_OPERATION_CAPABILITY_SET=CAP_SYS_ADMIN` kept as a clearly scoped subset, and each case's total set is derived from its own effects (1.7.5, 7) | a total set and a subset can no longer be confused, because both are named and the total is defined as the union of the case's effect rows |
| `E13`'s authority scope named only below-root access while its target is the root's parent | `BELOW_ROOT_ACCESS_AUTHORITY_SCOPE` and `ROOT_PARENT_REMOVAL_ACCESS_AUTHORITY_SCOPE` are separate tokens, and `E26`'s parent-removal authority is selected by four observed `RUNNER_TEMP` facts (1.7.7, 7, 1.5) | the capability claim now follows an observation: if the parent's DAC already authorizes the removal, no capability is claimed, and a sticky parent is a `QUALIFICATION_GAP` rather than an undeclared `CAP_FOWNER` |
| `E8`/`E20` relied on an image write permission `E5` never froze | image access is frozen as measured postconditions: regular single-link file, owner is the reviewed helper identity, `IMAGE_ROLE_S_IMODE=0600` exact with owner-write set, established by creation with no `chmod`/`fchmod`, and a design-frozen size set by `ftruncate` (1.7.8, 5.9) | the format and the loop binding both consume a fact the creation actually establishes and the preflight actually observes, instead of assuming a default mode |
| the contract allowed a pathname-based `losetup` setup while claiming a descriptor-mediated binding | one mechanism is frozen: `LOOP_CTL_GET_FREE` plus `LOOP_CONFIGURE` with the pinned image descriptor, `LOOP_GET_STATUS64` read-back verification, `LOSETUP_FIND_SHOW_IS_SUFFICIENT_EVIDENCE=false` and `LOSETUP_PATHNAME_FORM_USED=false` (1.7.8, 5.9) | the association is bound to the exact inode the helper pinned because the ioctl takes that descriptor, and the binding is verified after setup rather than inferred from a tool's success |
| two different bare `A3D_REMEDIATION_COMMIT_PARENT` values existed at one head | the historical values are preserved under round-qualified keys, and this head carries exactly one bare current-round pointer (1.7, 20) | the failed head stays auditable from the branch tip, and the current pointer can be read without disambiguating which round it belongs to |

The three round-6 blocking findings are closed as follows:

| Blocking finding | Corrected statement at this head | Why it is now implementable |
| --- | --- | --- |
| ownership capability set contradicted the separately required access authority for E1/E2 | `OWNERSHIP_MUTATION_REQUIRED_CAPABILITY_SET=CAP_CHOWN` is separated from `OWNERSHIP_CASE_ACCESS_AUTHORITY=CAP_DAC_READ_SEARCH,CAP_DAC_OVERRIDE`, and the case's total set is `CAP_CHOWN,CAP_DAC_READ_SEARCH,CAP_DAC_OVERRIDE` with `OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET_TRUTHFUL=true` (1.6, 7) | the mutation authority and the access authority are two exact facts with one operation each; no authority is declared unnecessary because it produces no evidence, and the retired token that named only half the set is marked retired rather than left standing |
| access-authority scope tokens omitted E9, E7 and E10 and inherited one capability mechanically | every effect E1 to E14 has its required access derived for that effect, traversal-only effects use `CAP_DAC_READ_SEARCH` and directory-mutating effects use `CAP_DAC_OVERRIDE`, E3/E4/E15 declare that they need none, and `ACCESS_AUTHORITY_EFFECT_SET` equals the row set (1.5, 1.6) | each authority is the narrowest capability that covers the access checks the operation really performs, the rows and tokens are identical by construction, and the equivalence is machine-checkable rather than asserted |
| ownership cases had no destructive cleanup effect, and the row count was satisfied by a placeholder | `E25` is the ownership-case `FIXTURE_FILE_ROLE` unlink (recorded as `E14` under round 6's numbering), ordered before root removal, with `OWNERSHIP_FIXTURE_FILE_REMOVAL_EFFECT_DECLARED=true`, `REAL_MATERIAL_EFFECT_COUNT=16`, `PRIVILEGED_EFFECT_CLOSURE_ROWS=16` and `ROUND6_PLACEHOLDER_EFFECT_ROWS=0` (1.5, 1.6, 10.4) | the fixture file is removed through a real effect with its own binding, authority and postcondition; the withdrawn ownership-restoration requirement is recorded as tokens, not as a row; the two counts are equal and no placeholder is accepted |

The three round-5 blocking findings remain closed as follows:

| Blocking finding | Corrected statement at that head | Why it is now implementable |
| --- | --- | --- |
| mode-provenance token unscoped in the general 5.8 block | `FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY_SCOPE=own-foreign,own-root` in 5.8 and `MOUNT_FIXTURE_FILE_INITIAL_MODE_ESTABLISHED_BY=reviewed_privileged_helper_at_creation` with `..._SCOPE=mount-fixture` in 5.8.3 (1.5) | the mode literal and its exactness are unchanged and still common to all three cases; only the provenance is scoped, so no token claims an ordinary-process creation for a helper-created file, and no `chmod`/`fchmod` is introduced |
| child-missing outcome unscoped, and therefore false for the helper-created mount case | the four pre-existing-object refusals are scoped to `own-foreign,own-root`, and the mount case gets an after-creation failure contract with `MOUNT_CASE_CHILD_MISSING_AFTER_CREATION_IS_HELPER_ROOT_REJECTED=false`, `MOUNT_CASE_CHILD_MISSING_IS_PASS=false` and an origin split that keeps `ENVIRONMENT_FAILURE`, `TOOLING_FAILURE` and `TEST_FAILURE` distinct (1.5, 5.8.1, 5.8.3) | the refusal outcomes are only claimed where the role must preexist, the mount case's failure is classified by the origin that really produced it instead of one collapsed value, and the production primitive has not run at that point, so `PRODUCT_FAILURE` is structurally excluded rather than excused |
| privileged-effect table grouped distinct effects and left effects unauthorized | one row per material effect, sixteen rows, each with target, binding, authority, preconditions, postconditions and cleanup transition, plus the three bidirectional-closure tokens (1.5) | every effect's authority follows from the operation it performs, no effect is left undeclared, no declared authority is unused or broader than its effects, and the two authorities the round-4 table did not name — the mount-case creation authority and the helper's declared access authority — are now frozen rather than assumed |

`A3_CONTRACT_IMPLEMENTABILITY=PASS` is claimed only after the four round-3
results and the three round-2 results above it are `PASS`, and only after the
round-4 re-evaluation confirms that the corrected owner predicates are mutually
implementable, the round-5 re-evaluation confirms that every effect at that head
had a declared authority, the round-6 re-evaluation confirms that the ownership
case's total authority set is truthful and that every effect's access authority
is derived for that effect, and the round-7 re-evaluation confirms that the effect
set is derived from the real lifecycle, that each case's total authority set
equals the union of its own effects, and that the credential transition, the
mountpoint creation, the namespace scope, the parent-directory access authority,
the image access preconditions and the loop target binding are all closed. Each
of those results is claimed for a stated reason:

- `OWNERSHIP_CAPABILITY_MODEL_IMPLEMENTABILITY=PASS` — the helper performs
  exactly one privileged mutation per ownership case, `fchown(child_fd,
  derived_target_uid, observed_gid)` on a descriptor it opened itself, so
  `CAP_CHOWN` is exactly the mutation authority; no mode is changed by the
  helper, so `CAP_FOWNER` is not required. The case's access authority is a
  separate and genuinely required fact, not an unnecessary one: the pinned child
  is opened through the owner-only root with `CAP_DAC_READ_SEARCH`, it is
  unlinked during cleanup with `CAP_DAC_OVERRIDE`, and the case's credential
  transition uses `CAP_SETGID` and `CAP_SETUID`, so the ownership cases' total
  required authority set is
  `CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_DAC_READ_SEARCH,CAP_SETGID,CAP_SETUID` and
  nothing more (1.7.5, 7). `0644` is established by the ordinary process before the helper runs
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
- `NONROOT_EVIDENCE_IDENTITY_IMPLEMENTABILITY=PASS` — `euid`, `egid`, the
  supplementary group list and `CapEff` are all readable by a process from itself
  (`os.geteuid`, `os.getegid`, `os.getgroups` and the real `/proc/self/status`
  `Groups` and `CapEff` fields on the declared Linux platform), so the evidence
  process can produce and consume every fact with no carrier and no privileged
  help; the required comparisons are exact equalities and a zero mask, so each
  check is decidable; and a mismatch of any of them is classified as a fixture
  failure before the production call rather than as evidence.
- `NAMESPACE_LIFECYCLE_IMPLEMENTABILITY=PASS` — the private namespace is created
  by the already-privileged launcher, inherited by the transition child across
  `fork` and `execve`, and reported by each process from its own
  `/proc/self/ns/mnt`; nothing about it requires a carrier, an identity
  preservation across the credential transition, or a helper invocation the
  mount case cannot construct, and the ownership cases do not enter it at all.
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
| The helper and the evidence process share one measured private namespace in the mount case, and neither runs in one in the ownership cases | frozen, sections 10.1 and 1.7.4 | none added | no production symbol changes | privileged case later; the three namespace identities are measured for `mount-fixture`, and the ownership cases report no namespace control as evidence |
| Every crossing fact carries exactly one continuity class | frozen, sections 5.5-5.6 and 10.2 | none added | not applicable | privileged case later; the classes are pinned by the implementation PR |
| Namespace membership is inherited and namespace identity is independently reacquired | frozen, sections 5.5 and 10.1 | none added | no production symbol changes | privileged case later; the two private identities and the host identity are measured |
| The helper changes ownership only in the ownership cases, never mode anywhere | frozen, sections 4.1-4.2 and 5.8.2-5.8.3 | none added | no production symbol changes | privileged case later; `fchmod` is absent from the helper, the mount case performs no ownership call, and the post-`fchown` `fstat` is recorded |
| The ownership cases require `CAP_CHOWN` for the mutation, `CAP_DAC_READ_SEARCH` and `CAP_DAC_OVERRIDE` for access and `CAP_SETGID`/`CAP_SETUID` for the credential transition, and the mount case's fixture file requires no ownership capability at all | frozen, sections 5.8.2-5.8.3, 5.10.3, 7, 1.5 and 1.7.5 | none added | no production symbol changes | privileged case later; the helper's and the launcher's real `CapEff` are compared against `OWNERSHIP_CASE_TOTAL_REQUIRED_AUTHORITY_SET` and `MOUNT_FIXTURE_TOTAL_REQUIRED_AUTHORITY_SET`, the absence of an ownership call in the mount case is recorded, and the ordinary process's real `O_RDONLY` success is recorded |
| Every effect's pathname or object access authority is derived for that effect, and the effect rows and scope tokens are identical | frozen, sections 1.5 and 1.7.5 | none added; the per-effect access sets are design facts | no production symbol changes | privileged case later; `ACCESS_AUTHORITY_EFFECT_SET` is compared against the access each effect really performs, and the six no-access effects are checked to need none |
| The fixture-object removal and the invocation-root removal are ordered in every case, with the fixture-object removal scoped per case | frozen, sections 1.5, 1.7.6, 10.4 and 1.10.5: `E25` removes the ownership fixture file and never runs in `mount-fixture`, whose two objects are both removed by `E24`, and `E26` removes the root last in every case | none added | no production symbol changes | privileged case later; the `E26` removal is recorded with its identity revalidation in each case, and the `E26` root removal is recorded with its observed `RUNNER_TEMP` DAC facts |
| The launcher's forked child becomes the ordinary identity by direct syscalls in the frozen order, and the supplementary group list is empty | frozen, sections 1.7.2, 5.10.3 and 10.1 | none added | no production symbol changes | privileged case later; the post-transition uid triple, gid triple, empty `ACTUAL_SUPPLEMENTARY_GROUPS` and zero `ACTUAL_CAP_EFF` are all measured from the evidence process before the production call |
| The private mount namespace and its private propagation exist only in the mount case | frozen, sections 1.7.4, 10.1 and 10.2 | none added | no production symbol changes | privileged case later; the three namespace identities are measured in `mount-fixture`, and the ownership cases assert that they ran in the host namespace rather than reporting a namespace control |
| The mountpoint is helper-created exclusively at an exact `0755`, and the image at an exact `0600` with owner-write | frozen, sections 1.7.3, 1.7.8 and 5.9 | none added | no production symbol changes | privileged case later; the preflight observes both modes, the owners and the link counts, and a pre-existing object at either role is refused |
| The loop backing is bound by descriptor to the pinned image, and the binding is verified after setup | frozen, sections 1.7.8 and 5.9 | none added | no production symbol changes | privileged case later; the `LOOP_CONFIGURE` call takes the pinned image descriptor, `LOOP_GET_STATUS64` read-back equality is recorded, and no pathname-based tool performs the binding |
| The pinned child's ownership predicate is case-specific: `st_uid == ORDINARY_UID` for the ownership cases, `st_uid == 0` and no ownership mutation for the mount case | frozen, sections 5.8.1-5.8.3 and 5.9 | none added; the role name and the predicates are helper-internal | no production symbol changes | privileged case later; each case's own predicate is asserted on the helper-pinned descriptor, and the common structural requirements are shared, not the ownership predicate |
| The foreign target uid is the design-frozen literal `65534` | frozen, sections 4.4 and 5.2 | none added; the literal is helper-internal | no production symbol changes | privileged case later; the literal, the ordinary `euid != 65534` precondition and the no-substitution rule are pinned |
| The ordinary uid/gid is explicitly handed off and validated before any credential drop | frozen, sections 5.5-5.6, 5.10.1-5.10.2 and 10.1 | none added | no production symbol changes | privileged case later; the handoff arguments and the launcher's root-ownership validation are recorded |
| The evidence process reacquires its own identity, supplementary group list and `CapEff == 0` | frozen, sections 5.5-5.6, 5.10.3, 5.10.4 and 10.1 | none added | no production symbol changes | privileged case later; `ACTUAL_EUID`, `ACTUAL_EGID`, `ACTUAL_SUPPLEMENTARY_GROUPS` and the decoded `ACTUAL_CAP_EFF` are measured before the production call |
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
  mutation itself; the case's other authorities are access and credential
  authorities, not mutation authorities. The mount case is expressible in the same standard library: the helper
  creates the file inside its own freshly mounted filesystem with
  `O_CREAT|O_EXCL` and mode `0644` under a creation-time umask that cannot clear
  those bits, opens it again with `O_RDONLY|O_NOFOLLOW|O_CLOEXEC` to pin it, and
  requires `st_uid == 0` from `os.fstat` on that pinned descriptor, while the
  ordinary process's own `O_RDONLY` open of the same file is the read witness.
  No ownership call and no mode call appears in that case at all. The credential
  model is
  expressible with the standard library alone as well: the ordinary process
  measures itself with `os.geteuid`/`os.getegid`, the launcher passes on two
  integers, and the evidence process reads `os.geteuid`, `os.getegid`,
  `os.getgroups` and the real `CapEff` and `Groups` fields from
  `/proc/self/status`. No new public API is required.
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
  validated there against the real invocation root before the credential
  transition (5.10.1-5.10.2). Every other crossing fact is inherited (namespace
  membership and the emptied supplementary group list) or independently
  reacquired — including the evidence process's own `euid`, `egid`, supplementary
  group list and effective capability mask (5.10.3, 5.10.4) — and the privileged
  ownership mutation's target is acquired by the helper itself (5.8) rather than
  handed off, as is the mount case's fixture child (5.8.1, 5.8.3). A second,
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

Round 6's preview question is whether the corrected per-effect access authority
and the ownership-case removal effect map onto operations the architecture can
perform. They do, and neither needs anything new: the traversal authority is
used by ordinary `openat`/`mount`/`umount2` path resolution, the directory-write
authority is used by `openat` with `O_CREAT|O_EXCL` and by
`unlinkat`/`rmdir`, and the ownership-case unlink is the same `unlinkat` call the
mount case already needs for its image, with a no-follow identity revalidation
instead of a descriptor argument. No new API, no new dependency, no new
capability and no ownership operation is introduced.

```text
ROUND6_PREVIEW_OWNERSHIP_AUTHORITY_SET_IMPLEMENTABLE=true
ROUND6_PREVIEW_ACCESS_AUTHORITY_PER_EFFECT_IMPLEMENTABLE=true
ROUND6_PREVIEW_OWNERSHIP_FIXTURE_UNLINK_IMPLEMENTABLE=true
ROUND6_PREVIEW_NEW_PUBLIC_API_REQUIRED=false
ROUND6_PREVIEW_NEW_DEPENDENCY_REQUIRED=false
ROUND6_PREVIEW_DECLARED_AUTHORITY_COUNT_BEFORE_ROUND6=3
ROUND6_PREVIEW_DECLARED_AUTHORITY_COUNT_AFTER_ROUND6=4
ROUND6_PREVIEW_ADDED_DECLARED_AUTHORITY=CAP_DAC_READ_SEARCH
ROUND6_PREVIEW_ADDED_AUTHORITY_IS_NARROWER_THAN_THE_ONE_IT_REPLACES=true
ROUND6_PREVIEW_ADDED_AUTHORITY_IS_ALREADY_IN_THE_RUNNERS_SUDO_MASK=true
ROUND6_PREVIEW_AUTHORITY_GRANT_WIDENED=false
ROUND6_PREVIEW_OWNERSHIP_OPERATION_ADDED=false
```

`ROUND6_PREVIEW_ADDED_DECLARED_AUTHORITY=CAP_DAC_READ_SEARCH` is stated rather
than hidden: round 5 declared traversal access as `CAP_DAC_OVERRIDE` and round 6
names the narrower `CAP_DAC_READ_SEARCH` for the traversal-only effects, so the
declared inventory grew from three capabilities to four while each individual
attribution narrowed. `CAP_DAC_OVERRIDE` remains required, but only for the
effects that really write a directory entry. Neither capability is a broader
grant than the fixture's operations justify, both are present in the capability
set `sudo -n` already provides on the declared runner, and neither adds a public
API, a dependency or an ownership operation.

Round 7's preview question is whether the three added effects and the corrected
authority sets map onto operations the architecture can perform. They do:

```text
ROUND7_PREVIEW_CREDENTIAL_TRANSITION_IMPLEMENTABLE=true
ROUND7_PREVIEW_CREDENTIAL_TRANSITION_API=os.setgroups_os.setgid_os.setuid_os.execv
ROUND7_PREVIEW_CREDENTIAL_TRANSITION_API_IS_STANDARD_LIBRARY=true
ROUND7_PREVIEW_MOUNTPOINT_CREATION_IMPLEMENTABLE=true
ROUND7_PREVIEW_MOUNTPOINT_CREATION_API=os.mkdir_with_dir_fd_and_mode_0755
ROUND7_PREVIEW_IMAGE_CREATION_IMPLEMENTABLE=true
ROUND7_PREVIEW_IMAGE_CREATION_API=os.open_O_CREAT_O_EXCL_MODE_0600_then_os.ftruncate
ROUND7_PREVIEW_LOOP_BINDING_IMPLEMENTABLE=true
ROUND7_PREVIEW_LOOP_BINDING_API=fcntl.ioctl_on_dev_loop_control_and_dev_loopN
ROUND7_PREVIEW_LOOP_BINDING_API_IS_STANDARD_LIBRARY=true
ROUND7_PREVIEW_IMAGE_ACCESS_PRECONDITION_IMPLEMENTABLE=true
ROUND7_PREVIEW_SUPPLEMENTARY_GROUP_SEMANTICS_IMPLEMENTABLE=true
ROUND7_PREVIEW_SUPPLEMENTARY_GROUP_API=os.setgroups_os.getgroups
ROUND7_PREVIEW_PARENT_DAC_OBSERVATION_IMPLEMENTABLE=true
ROUND7_PREVIEW_PARENT_DAC_OBSERVATION_API=os.stat_of_RUNNER_TEMP_compared_against_the_helper_identity
ROUND7_PREVIEW_CASE_TOTAL_AUTHORITY_SETS_IMPLEMENTABLE=true
ROUND7_PREVIEW_DECLARED_AUTHORITY_COUNT_BEFORE_ROUND7=4
ROUND7_PREVIEW_DECLARED_AUTHORITY_COUNT_AFTER_ROUND7=6
ROUND7_PREVIEW_ADDED_DECLARED_AUTHORITIES=CAP_SETGID,CAP_SETUID
ROUND7_PREVIEW_NEW_PUBLIC_API_REQUIRED=false
ROUND7_PREVIEW_NEW_DEPENDENCY_REQUIRED=false
ROUND7_PREVIEW_NEW_PERSISTENT_STATE_REQUIRED=false
ROUND7_PREVIEW_OWNERSHIP_OPERATION_ADDED=false
ROUND7_PREVIEW_MODE_CHANGE_CALL_ADDED=false
ROUND7_PREVIEW_AUTHORITY_GRANT_WIDENED=false
ROUND7_PREVIEW_CAP_SYS_ADMIN_SCOPE_NARROWED=true
ROUND7_PREVIEW_EXTERNAL_PRIVILEGE_TOOL_ADDED=false
ROUND7_PREVIEW_STOPS_IMPLEMENTATION_CONTRACT=false
```

The two added capabilities are not a widened grant but a newly *named* one:
`CAP_SETGID` and `CAP_SETUID` were always inherent in a `sudo -n` root launcher
changing a child's identity, and round 7 declares them because the transition is
now a declared effect rather than an implicit consequence of launching a
process. At the same time the `CAP_SYS_ADMIN` scope narrows, because the private
namespace and its propagation move out of the ownership cases' path entirely.
Every added operation is expressible in the Python standard library
(`os.setgroups`, `os.setgid`, `os.setuid`, `os.execv`, `os.mkdir` with `dir_fd`,
`os.open` with `dir_fd` and `O_CREAT|O_EXCL`, `os.ftruncate`, and `fcntl.ioctl`
for the loop control and configuration requests), so no new dependency and no new
public API is introduced.

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

Round 6 adds no validation class either, and it adds no executable surface: the
corrected authority sets and the ownership-case removal effect are design facts
about operations the implementation PR will perform, not operations this PR
performs. The same five checks apply, and no privileged command is executed.

```text
ROUND6_VALIDATION_SCOPE=docs_governance_only
ROUND6_VALIDATION_CLASSES=git_diff_check,repo_hygiene,destructive_design_gate,release_check,ci_risk_tier
ROUND6_PRIVILEGED_EXECUTION_PERFORMED=false
ROUND6_IMPLEMENTATION_FILES_CHANGED=0
ROUND6_CHANGED_FILE_COUNT=1
ROUND6_VALIDATION_INCLUDES_EFFECT_TABLE_PROBE=true
```

Round 7 adds no validation class either, and the round-7 additions add no
executable surface: the credential transition, the mountpoint creation and the
rebuilt effect table are design facts about operations the implementation PR will
perform, not operations this PR performs. The same five checks apply, and no
privileged command is executed. Round 7 does add one class of *local* check that
is not a repository command: the structural probes of 15.1 and the
document-wide duplicate-value probe of 20 are run over this document before the
commit, because a token-level invariant that no probe reads is a token that can
drift.

```text
ROUND7_VALIDATION_SCOPE=docs_governance_only
ROUND7_VALIDATION_CLASSES=git_diff_check,repo_hygiene,destructive_design_gate,release_check,ci_risk_tier
ROUND7_PRIVILEGED_EXECUTION_PERFORMED=false
ROUND7_IMPLEMENTATION_FILES_CHANGED=0
ROUND7_CHANGED_FILE_COUNT=1
ROUND7_VALIDATION_INCLUDES_STRUCTURAL_PROBES=true
ROUND7_VALIDATION_INCLUDES_TOKEN_DUPLICATE_VALUE_PROBE=true
ROUND7_STRUCTURAL_PROBE_COUNT=11
ROUND7_STRUCTURAL_PROBE_RESULT=PASS
ROUND7_TOKEN_DUPLICATE_VALUE_PROBE_RESULT=PASS
ROUND7_KERNEL_CLAIM_PROVENANCE=DOCUMENTED
ROUND7_KERNEL_CLAIM_PROVENANCE_SOURCES=capabilities(7)_and_mount(2)_and_umount(2)_and_losetup(8)
ROUND7_KERNEL_CLAIM_PROVENANCE_VERSION=man-pages_6.19
ROUND7_KERNEL_CLAIM_PROVENANCE_PROBED=false
ROUND7_KERNEL_CLAIM_PROBED_REASON_NO_LINUX_HOST_IS_AVAILABLE_IN_THIS_DEVELOPMENT_ENVIRONMENT
ROUND7_KERNEL_CLAIM_PROBE_IS_AN_IMPLEMENTATION_PHASE_OBLIGATION=true
```

One provenance fact is stated rather than implied, because AGENTS.md requires
either documentation or a probe for a material claim about OS privilege
behaviour. The capability, mount and loop claims in this round are
`DOCUMENTED`-provenance claims taken from the Linux `man-pages` 6.19 text this
contract already cites: `capabilities(7)` (page dated 2026-02-08) for the
`CAP_SETGID`, `CAP_SETUID`, `CAP_DAC_OVERRIDE`, `CAP_DAC_READ_SEARCH`,
`CAP_CHOWN`, `CAP_FOWNER` and `CAP_SYS_ADMIN` entries and for the "Effect of user
ID changes on capabilities" rules the credential transition relies on;
`mount(2)` (page dated 2026-02-11) for the `CAP_SYS_ADMIN` mount requirement and
for `source`/`target` being pathnames; and `umount(2)` and `losetup(8)` for the
unmount requirement and the loop lifecycle. They are NOT `PROBED` in this
environment, because this development host has no Linux runtime — WSL is not
installed and no container runtime is available — and running the fixture here
would in any case be the privileged execution this PR is forbidden to perform.
The probe obligation therefore moves to the implementation phase, where the real
host makes it executable, and it is frozen as such rather than dropped:


Round 10 adds no validation class either. It changes the same one document, the
eleven corrections are all design statements about the fixture's future privileged
operations, and no privileged command is executed by this PR. The same five
checks apply to the remediated head, and the two local probe suites of 15.1 and
1.10.7 are run over this document before the commit:

```text
ROUND10_VALIDATION_SCOPE=docs_governance_only
ROUND10_VALIDATION_CLASSES=git_diff_check,repo_hygiene,destructive_design_gate,release_check,ci_risk_tier
ROUND10_PRIVILEGED_EXECUTION_PERFORMED=false
ROUND10_IMPLEMENTATION_FILES_CHANGED=0
ROUND10_CHANGED_FILE_COUNT=1
ROUND10_VALIDATION_INCLUDES_STRUCTURAL_PROBES=true
ROUND10_VALIDATION_INCLUDES_TOKEN_DUPLICATE_VALUE_PROBE=true
ROUND10_STRUCTURAL_PROBE_COUNT=14
ROUND10_STRUCTURAL_PROBE_RESULT=PASS
ROUND10_TOKEN_DUPLICATE_VALUE_PROBE_RESULT=PASS
ROUND10_KERNEL_CLAIM_PROVENANCE=DOCUMENTED
ROUND10_KERNEL_CLAIM_PROVENANCE_SOURCES=capabilities7_and_linux_fs_namei_c_and_open2_and_umount2_and_losetup8
ROUND10_KERNEL_CLAIM_PROVENANCE_VERSION=man-pages_6.19_and_kernel_source_read_for_this_round
ROUND10_KERNEL_CLAIM_PROBED=false
ROUND10_KERNEL_CLAIM_PROBED_REASON_NO_LINUX_HOST_IS_AVAILABLE_IN_THIS_DEVELOPMENT_ENVIRONMENT
ROUND10_KERNEL_CLAIM_PROBE_IS_AN_IMPLEMENTATION_PHASE_OBLIGATION=true
```

The capability and permission claims this round re-derives are `DOCUMENTED`
claims: the directory and non-directory branches of `generic_permission`, the
`MAY_EXEC` masking of the directory component walk, and the `CAP_DAC_*` bypass
conditions were read for this round from the Linux kernel source
(`fs/namei.c`), and the capability descriptions remain the cited
`capabilities(7)` text. They are not `PROBED`: this development host has no Linux
runtime and running the fixture here would be the privileged execution this PR is
forbidden to perform.

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
A3D_REMEDIATION_ROUND_5_COMMIT_PARENT=3bc6862c869590ee128636e2a9ca5b4ddf9603b2
A3D_ROUND5_CONTAINS_FAILED_FOURTH_REVIEW_HEAD=true
A3D_ROUND5_PARENTS_FAILED_FOURTH_REVIEW_HEAD=true
A3D_ROUND5_REWRITES_FAILED_FOURTH_REVIEW_HEAD=false
A3D_ROUND5_PUSH_IS_FAST_FORWARD=true
A3D_ROUND5_PUSH_IS_NEW_BRANCH=false
A3D_ROUND5_PUSH_FORCE=false
A3D_HISTORY_PRESERVED_BY_RECORD=true
A3D_HISTORY_REWRITTEN=false
```

Round 6 preserves history the same way, with the failed round-5 head as its
direct parent, pushed as a normal fast-forward onto the same branch:

```text
A3D_REMEDIATION_ROUND_6=6
A3D_REMEDIATION_ROUND_6_PARENT=65061f1e005c7595afd4c84d049a4e025eea9d70
A3D_REMEDIATION_ROUND_6_PARENT_IS_FAILED_FIFTH_REVIEW_HEAD=true
A3D_REMEDIATION_ROUND_6_BRANCH=design/a3d-round4-mount-owner-predicate
A3D_REMEDIATION_ROUND_6_COMMIT_COUNT=1
A3D_REMEDIATION_ROUND_6_COMMIT_PARENT=65061f1e005c7595afd4c84d049a4e025eea9d70
A3D_ROUND6_CONTAINS_FAILED_FIFTH_REVIEW_HEAD=true
A3D_ROUND6_PARENTS_FAILED_FIFTH_REVIEW_HEAD=true
A3D_ROUND6_REWRITES_FAILED_FIFTH_REVIEW_HEAD=false
A3D_ROUND6_PUSH_IS_FAST_FORWARD=true
A3D_ROUND6_PUSH_IS_NEW_BRANCH=false
A3D_ROUND6_PUSH_FORCE=false
A3D_HISTORY_PRESERVED_BY_RECORD=true
A3D_HISTORY_REWRITTEN=false
```

Round 7 preserves history the same way again, with the failed round-6 head as its
direct parent, pushed as a normal fast-forward onto the same branch:

```text
A3D_REMEDIATION_ROUND_7=7
A3D_REMEDIATION_ROUND_7_PARENT=c2a88fa02f62b1332a6f8cabd779d89bd260adfb
A3D_REMEDIATION_ROUND_7_PARENT_IS_FAILED_SIXTH_REVIEW_HEAD=true
A3D_REMEDIATION_ROUND_7_BRANCH=design/a3d-round4-mount-owner-predicate
A3D_REMEDIATION_ROUND_7_COMMIT_COUNT=1
A3D_ROUND7_BARE_PARENT_TOKEN_AT_THAT_HEAD=829715ee60bca53a3f02743b19bbab568bc36a74
A3D_ROUND7_CONTAINS_FAILED_SIXTH_REVIEW_HEAD=true
A3D_ROUND7_PARENTS_FAILED_SIXTH_REVIEW_HEAD=true
A3D_ROUND7_REWRITES_FAILED_SIXTH_REVIEW_HEAD=false
A3D_ROUND7_PUSH_IS_FAST_FORWARD=true
A3D_ROUND7_PUSH_IS_NEW_BRANCH=false
A3D_ROUND7_PUSH_FORCE=false
A3D_ROUND7_AMEND_USED=false
A3D_ROUND7_REBASE_USED=false
A3D_HISTORY_PRESERVED_BY_RECORD=true
A3D_HISTORY_REWRITTEN=false
```

The single bare `A3D_REMEDIATION_COMMIT_PARENT` token carries the direct parent of
the head under remediation, which is the failed ninth-review head, and that is what
makes the failed head auditable from the branch tip. Round 7 introduced the token
with its own parent and round 9 left it pointing at round 7; round 10 re-points it
and keeps every earlier round's value under its own round-qualified name: the
round-3 value is `A3D_REMEDIATION_ROUND_3_COMMIT_PARENT`, the round-5 value is
`A3D_REMEDIATION_ROUND_5_COMMIT_PARENT`, the round-6 value is
`A3D_REMEDIATION_ROUND_6_COMMIT_PARENT`, and the round-7 value is
`A3D_REMEDIATION_ROUND_7_COMMIT_PARENT`. Round 6 left two bare
`A3D_REMEDIATION_COMMIT_PARENT` tokens carrying two different values at one head,
which is the defect round 7 corrects; preserving the history under round-qualified
keys is what corrects it without deleting either earlier fact.

```text
GIT_CURRENT_PARENT_TOKEN=A3D_REMEDIATION_COMMIT_PARENT
GIT_CURRENT_PARENT_TOKEN_OCCURRENCE_COUNT=1
GIT_CURRENT_PARENT_TOKEN_VALUE=be714a250ede2b286913fcb0fe9a5415231cdf08
GIT_CURRENT_PARENT_TOKEN_UNIQUE=true
GIT_CURRENT_PARENT_TOKEN_IS_THE_ROUND_10_DIRECT_PARENT=true
GIT_HISTORICAL_PARENT_TOKEN_ROUND_7=A3D_REMEDIATION_ROUND_7_COMMIT_PARENT
A3D_REMEDIATION_COMMIT_PARENT=be714a250ede2b286913fcb0fe9a5415231cdf08
GIT_HISTORICAL_PARENT_TOKENS_ARE_ROUND_QUALIFIED=true
GIT_HISTORICAL_PARENT_TOKEN_ROUND_3=A3D_REMEDIATION_ROUND_3_COMMIT_PARENT
GIT_HISTORICAL_PARENT_TOKEN_ROUND_5=A3D_REMEDIATION_ROUND_5_COMMIT_PARENT
GIT_HISTORICAL_PARENT_TOKEN_ROUND_6=A3D_REMEDIATION_ROUND_6_COMMIT_PARENT
GIT_TWO_BARE_VALUES_AT_ONE_HEAD=false
GIT_TOKEN_DUPLICATE_VALUE_PROBE_RULE=no_current_pointer_key_carries_two_different_values
GIT_TOKEN_DUPLICATE_VALUE_PROBE_RESULT=PASS
GIT_TOKEN_DUPLICATE_VALUE_PROBE_SCOPE=whole_document
GIT_TOKEN_DUPLICATE_VALUE_PROBE_ENUM_KEY_FORMS=MOUNT_STATE,reason_code,A3D_CURRENT_REMEDIATION_ROUND_AT_THAT_HEAD
CURRENT_POINTER_KEY_DUPLICATE_VALUE_COUNT=0
SUPERSEDED_CURRENT_POINTER_KEYS_RENAMED_WITH_A_ROUND_QUALIFIER=true
ROUND5_AND_ROUND6_SUPERSEDED_KEYS_KEPT_AS_HISTORY=true
```

The probe's three permitted multi-value forms are the ones 15.1 names: an
enumeration over one attribute, a historical round-qualified record, and a
per-case or per-object variant. Every other `KEY=VALUE` token in this document
carries one value, and the only tokens that could not satisfy that were renamed
with a round qualifier rather than left colliding.


Round 10 preserves history the same way, with the failed round-9 head as its
direct parent, pushed as a normal fast-forward onto the same branch:

```text
A3D_REMEDIATION_ROUND_10=10
A3D_REMEDIATION_ROUND_10_PARENT=be714a250ede2b286913fcb0fe9a5415231cdf08
A3D_REMEDIATION_ROUND_10_PARENT_IS_FAILED_NINTH_REVIEW_HEAD=true
A3D_REMEDIATION_ROUND_10_BRANCH=design/a3d-round4-mount-owner-predicate
A3D_REMEDIATION_ROUND_10_COMMIT_COUNT=1
A3D_ROUND10_CONTAINS_FAILED_NINTH_REVIEW_HEAD=true
A3D_ROUND10_PARENTS_FAILED_NINTH_REVIEW_HEAD=true
A3D_ROUND10_REWRITES_FAILED_NINTH_REVIEW_HEAD=false
A3D_ROUND10_PUSH_IS_FAST_FORWARD=true
A3D_ROUND10_PUSH_IS_NEW_BRANCH=false
A3D_ROUND10_PUSH_FORCE=false
A3D_ROUND10_AMEND_USED=false
A3D_ROUND10_REBASE_USED=false
A3D_ROUND10_PREPUSH_ORIGIN_BRANCH_REQUIRED=be714a250ede2b286913fcb0fe9a5415231cdf08
A3D_ROUND10_PREPUSH_ORIGIN_MAIN_REQUIRED=cca7805305b0e369b27d7d29ba3611fb9afd7679
TRANSPORT_DEGRADED=true
A3D_ROUND10_REMOTE_TRUTH_CHANNELS=reviewed_confined_ssh_and_authoritative_remote_api
```

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
