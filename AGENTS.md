# Repository Guidelines

## Authority and Agent Role

Codex is the default primary implementation and development agent for
MarketVault. These rules are tool-agnostic and apply equally to any other
agent or contributor. Repository code, checked-in contracts, tests, and
governance documents outrank conversational memory or prior reports. Read the
relevant source and contracts before changing behavior.

The repository owner retains product and release authority. An independent
reviewer provides architecture, merge, and release audit; the implementing
agent's own report is not independent approval. See
`docs/AGENT_GOVERNANCE.md` and `docs/governance/`.

## DeepSeek Harness Review Protocol

This section binds the DeepSeek Harness agent when it inspects, reviews, or
implements work here. It supplements the authority rules above and in
`docs/AGENT_GOVERNANCE.md`; it does not replace or weaken them. Codex remains
the default primary implementation and development agent.

Apply these gates by materiality: a trivial editorial change does not inherit
the ceremony required of a contract, authority, evidence, or lifecycle change.

### Work-Order Authority First

Before implementation, inspect the active work order, phase locks, explicit
authorizations, and non-goals. Technical usefulness does not override an
explicit `IMPLEMENTATION_AUTHORIZED=false`. Implementation, production, and
merge/release authorities are separate grants; holding one never implies
another. Existing unauthorized work in progress inherits no approval merely
because it exists.

### Read-Only Discovery First

For non-trivial work, begin read-only: relevant source, tests, contracts, ADRs
under `docs/adr`, governance, current Git/worktree state, and active work-order
authority. Do not modify existing dirty-worktree content during discovery; the
clean-worktree gate before branching in the Required Development Flow below is
unaffected.

### Findings Are Hypotheses

Findings are not an automatic repair list. Every material finding needs concrete
evidence: source location, call graph, contract text, test behavior, or an
executable probe. Before a finding becomes a repair item, actively attempt to
disprove it and classify it `CONFIRMED`, `DOWNGRADED`, `RETRACTED`, or
`NEEDS_DESIGN_DECISION`. Retraction is preferable to preserving a weak finding.

Do not conflate an observed implementation fact, an unfinished implementation
gap, a reachable production defect, a test coverage gap, intentional fail-closed
behavior, contract ambiguity, and a design decision. Private-helper behavior is
not automatically a public-API defect.

### Complete Call Graph, Executable Probes

Absence of a check from one layer does not prove absence from the system; trace
the complete intended and implemented call graph before declaring an enforcement
requirement missing.

Do not reason by mental arithmetic about bitmasks and flags, hashes and
identities, byte sizes, offsets, binary layouts, encoding lengths, timestamps
and time windows, or numeric boundaries. Use an executable probe and record its
input, computed result, and assertion. A correct conclusion does not excuse
incorrect intermediate arithmetic.

### Evidence Convergence and Completion Gates

After adversarial self-review, stop broadening the search for findings and
reduce what remains to concrete completion gates. For unfinished work,
distinguish `IMPLEMENTED_AND_WIRED`, `IMPLEMENTED_NOT_WIRED`, and
`NOT_IMPLEMENTED`, and do not describe unreachable unfinished implementation as
a production vulnerability merely because it is incomplete.

Before modifying code, define the exact files expected to change, the exact
invariant being introduced or restored, the required tests, and explicit
non-goals; prefer the smallest change that makes the invariant structural. Once
implementation is authorized, stay inside the accepted gates: no opportunistic
cleanup, unrelated refactor, silent taxonomy expansion, test weakening, or
conversion of failures into skips.

### Contract Implementability

When a material `MUST`, `MUST NOT`, `REQUIRE`, or `FAIL IF` requirement is
introduced, identify, where applicable: the authority owner; the evidence or
input required; the evidence producer; the evidence carrier or holder; the
evidence lifetime; the evidence consumer or verifier; the closing or recheck
point; and the failure outcome or reason.

A contract must not freeze a requirement that the declared architecture cannot
possess, transport, observe, or prove. State the result as
`CONTRACT_IMPLEMENTABILITY=PASS|FAIL`. If required evidence has no authorized
producer, carrier, or consumer path, the result is
`CONTRACT_IMPLEMENTABILITY=FAIL`; do not paper over the absence with assumed
continuity.

### Privileged Effect and Authority Closure

For any design or implementation involving privileged or destructive effects,
enumerate each material effect before approval, one row per effect: operation or
effect; target object; target-binding mechanism; required authority, privilege,
or capability; preconditions; postconditions; and cleanup or terminal
transition. Target binding is part of the effect row: name the mechanism that
binds the effect to that exact target and the window in which the binding is
valid, without requiring one fixed mechanism where a platform or operation has
no descriptor-targeted API.

Require closure in both directions: every privileged or destructive effect has
an explicitly declared authority, and every declared authority or capability
corresponds to an actual required effect. An undeclared effect, or an unused or
broader required authority than the effects justify, is a failure.

Values that determine the scope of a privileged effect — target uid or gid,
privilege or capability, target role, authority source — must be frozen by the
reviewed design or explicitly produced through a reviewed boundary mechanism.
They must not be left as "implementation selects ...", unless the design makes
that selection algorithm itself the reviewed authority and can prove its bounded
result.

### Cross-Boundary State Continuity

When an invariant spans a lifecycle or authority boundary, require an explicit
boundary model before freezing the design. Boundaries include
writer -> publication -> reader, process A -> restart -> process B,
capture -> materialization, acquisition -> offline consumption,
first pass -> second pass, and PR head -> squash-main result.

Classify every relevant fact crossing a boundary as exactly one of `INHERITED`,
`INDEPENDENTLY_REACQUIRED`, or `EXPLICITLY_HANDED_OFF`. State per phase the
baseline owner, the state or evidence carrier, its lifetime, the closing
checkpoint, the boundary, and the relationship to the next phase.

If continuity is required but neither inheritance nor an explicit handoff
exists, the design is invalid. Do not use "rebaseline" wording to hide a
genuinely independent new interval.

Publication-time carrier audit. Every material boundary-crossing fact must
appear in the same audit row as its class, so that class and evidence semantics
are checkable together:

- `INHERITED`: the state is carried by lifecycle, process, or object continuity;
  the row MUST NOT claim an explicit handoff carrier.
- `EXPLICITLY_HANDED_OFF`: the row MUST name exactly one explicit carrier and
  that carrier's lifetime.
- `INDEPENDENTLY_REACQUIRED`: the row MUST name the independent observation or
  re-read that produces the fact.

A fact that does not cross the boundary must be stated as not crossing rather
than forced into a crossing class; no fourth crossing class is added. If a row's
prose or declared carrier contradicts its class, the result is
`CONTRACT_IMPLEMENTABILITY=FAIL`.

### Contract-to-Implementation Preview

Before merging a design or contract PR that requires later runtime work, perform
a lightweight future-implementation preview. Write no production code. Answer:
which modules will probably need modification; whether existing APIs can express
the contract; whether existing evidence and data structures can carry all
required facts; whether new persistent state is required; whether a
cross-boundary handoff is required; whether new public API or authority is
required; and whether existing test seams can prove the invariant.

If the frozen contract cannot be mapped to a plausible implementation without
violating existing architecture or authority, stop the contract PR. A preview is
feasibility evidence, not implementation authorization.

### Three-Layer Consistency

Where relevant, recommend an invariant matrix across `HUMAN_CONTRACT`,
`MACHINE_DECLARATION`, `RUNTIME`, and `TESTS`, classifying each important
invariant per layer. Never describe the system as complete because only the
contract layer, or only the runtime layer, is complete.

### Machine-Contract Semantic Diff

When a structured governance artifact such as JSON changes, do not rely on
textual Git diff alone. Where material, establish semantic evidence such as
`KEY_SET_CHANGED`, `TYPE_CHANGED`, `ARRAY_LENGTH_CHANGED`,
`SEMANTIC_VALUE_CHANGED`, and `ORDER_CHANGED`, and distinguish an inserted array
item from replacement of later array items.

### Test Proof and Independent Review

A green test is not sufficient evidence by itself. For security, filesystem,
identity, parser, fail-closed, or governance invariants, verify that the test
passes or fails for the intended reason rather than because an unrelated earlier
guard fired.

A Harness session that implemented a change must not approve its own work;
independent review follows the rules above and
`docs/governance/DEVELOPMENT_PLAYBOOK.md`. High-risk changes require independent
read-only review before merge, including artifact identity, filesystem or native
evidence, PIT semantics, destructive behavior, publication, cryptography,
CI/control-plane behavior, and security boundaries.

### Evidence Provenance and Atomicity

Do not hand-transcribe important identifiers when the authoritative producer can
supply them. Derive Git SHAs, run IDs, hashes, and tree IDs from authoritative
output, validate expected syntax or length where useful, and bind related checks
to that exact identifier.

If one command in a supposedly atomic evidence block fails, returns malformed
data, or addresses the wrong object, the block must not retain PASS conclusions
from sibling commands unless those claims are explicitly independent and
re-established. Avoid mixed output where an HTTP or API failure is printed
beside unrelated PASS-looking fields.

For a material claim about an external control plane — CI provider or event
semantics, workflow execution provenance, OS or kernel privilege behavior,
external registry or service authority — require, before freezing the claim,
either `DOCUMENTED` provenance (authoritative documentation plus the exact
applicability, version, and context it was read for) or `PROBED` provenance (an
executable or object-level probe with its input and observed result). Where
authorities differ, model them separately; for CI or control-plane work do not
collapse event authority, workflow-definition authority, and code-under-test
authority when they resolve from different objects. A material
external-control-plane claim with neither documented nor probed provenance fails
evidence convergence.

### Lossless Structured Verification

Do not verify a structured or multiline object through a lossy text round trip.
A tool or shell transformation that can collapse line breaks, encoding, JSON
structure, markdown table boundaries, or whitespace significant to the check
must not be the sole verification evidence. Prefer the authoritative API object,
occurrence counts, semantic parsing, whole-object invariant checks, and an exact
or explicitly justified normalized diff. A malformed intermediate representation
must fail the evidence block rather than produce PASS-looking partial output.

### Failure-Origin Classification

Before treating a failed command or test as product evidence, classify its
origin as `PRODUCT_FAILURE`, `TEST_FAILURE`, `ENVIRONMENT_FAILURE`, or
`TOOLING_FAILURE`. Do not infer a product defect from sandbox ACL behavior,
pytest temp-root restrictions, TLS or Schannel failures, unavailable
credentials, shell quoting or globbing errors, or connector permission limits
until the failure path establishes product causality. Do not convert genuine
product failures into environment excuses.

### Degraded Transport

If the preferred Git transport is unavailable or untrustworthy, do not silently
fall back to potentially stale local refs. Classify `TRANSPORT_DEGRADED=true`,
use another authenticated authoritative read channel when permitted, and
disclose which channel established remote truth. Local refs may corroborate but
do not replace fresh remote truth when the work order requires freshness.
Transport degradation alone is not a repository defect.

This rule does not itself waive, relax, or replace the mandatory Exact Base
procedure defined by `docs/governance/DEVELOPMENT_PLAYBOOK.md` section 1.1 and
`docs/governance/AGENT_HANDOFF.md` rule 3:

- another authenticated authoritative read channel may establish remote truth
  only when the applicable authority permits that use;
- alternate read transport does not by itself grant permission to bypass a
  checked-in Git baseline procedure;
- if the mandatory Exact Base procedure cannot be completed, STOP before
  branching unless checked-in governance separately defines an equivalent
  fallback.

Do not treat an alternate read channel, including an API read path, as an
implicit substitute for that procedure.

### Remote Write Verification

A GitHub metadata write, including a PR body, an issue body or comment, release
metadata, or an equivalent review object, is not proven by a successful write
acknowledgement alone. Required sequence: write -> re-fetch the authoritative
remote final object -> verify whole-object invariants -> PASS. Do not verify
only the edited region, and do not infer that untouched portions remained
correct without checking the final remote object when those portions
participate in the gate.

### Post-Remediation Metadata Sync

After any remediation or follow-up commit that changes a previously reviewed PR
head, treat descriptive PR metadata as derived state. Before Ready or merge
authorization, synchronize and verify as applicable: base SHA, head SHA, head
tree, commit count, changed-file set, stated statistics, current policy or
contract wording, validation and test claims, the exact CI run and attempt,
remaining blockers, non-goals, authority locks, and lifecycle or stage
instructions. Require `PR_BODY_TRUTH == CURRENT_HEAD_TRUTH`. A technically
correct tree with materially stale review metadata does not pass the final PR
gate.

### Post-Remediation Agent Improvement Review

After a workstream requires remediation and technical closure passes, perform a
separate Agent Improvement Retrospective; do not expand the just-closed feature
PR to carry agent-governance changes. Report at minimum:

```text
AGENT_IMPROVEMENT_REVIEW=
ROOT_CAUSE=
MISSED_SIGNAL=
REASONING_FAILURE_CLASS=
COULD_HAVE_BEEN_PREVENTED_BY=
GENERALIZABLE=
PROPOSED_AGENT_RULE=
PROPOSED_WORKFLOW_CHANGE=
PROPOSED_TEST_OR_PROBE_RULE=
AGENTS_MD_CHANGE_RECOMMENDED=
PRIORITY=
```

Only reusable, executable, and verifiable lessons are promoted into mandatory
governance. One-off accidents may remain retrospective notes; repeated or
high-impact patterns are candidates for formal promotion.

### Exact-Head PR Review

Before merge authorization, verify the exact PR head SHA, exact tree, exact base
SHA, exact changed-file set, exact-head CI run and attempt, and the independent
review result. Green CI alone is not merge approval, and repository-owner merge
authority is unchanged.

### Unchanged Authority and Gates

These refinements grant no new authority and create no second governance flow;
they refine the flow below. Codex remains the default primary implementation and
development agent. The repository owner retains product, release, and merge
authority, and Harness holds no automatic merge authority. The clean-worktree
gate, the independent-review requirement, the exact-head review requirement, and
every destructive-operation rule are unchanged. Never force-push or rewrite
`main`.

### Standard Harness Flow

This refines the Required Development Flow below; it does not replace it.

```text
read-only discovery -> adversarial self-review -> evidence convergence
-> completion gates -> lifecycle / authority model when applicable
-> privileged-effect / carrier audit when applicable
-> contract implementability -> implementation preview when applicable
-> minimal patch plan -> narrow implementation -> validation
-> commit / Draft PR -> exact-head PR CI -> independent review
-> remediation / revalidation if required -> metadata synchronization
-> final exact-head review -> owner merge authorization -> squash merge
-> natural main CI -> post-merge closure
-> Agent Improvement Retrospective when remediation occurred
```

If remediation changes the head, independent review applies to the new exact
head after the required revalidation and CI.

Harness holds no automatic merge authority.

## Required Development Flow

Use this normal path:

```text
current origin/main -> feature branch -> inspect -> implement -> tests
-> local validation -> PR -> PR CI/review -> squash merge
-> exact main SHA -> post-merge CI verification
```

Never develop directly on `main`. Verify the exact current `origin/main` SHA
and a clean worktree before branching. Keep changes within the declared scope,
use feature branches and pull requests for writes, and stop before merge unless
the repository owner explicitly authorizes it. Squash merge is the default.
Never force-push or rewrite `main` history.

Important Git and CI claims must identify the exact SHA. CI evidence must also
identify the relevant run attempt when the repository contract binds evidence
to an attempt. Green PR CI does not prove a merged change healthy: verify CI for
the exact resulting `main` SHA after merge. Derive the current CI tier and
fail-closed behavior from `scripts/ci_risk_tier.py`,
`scripts/ci_post_merge_reuse.py`, `.github/workflows/ci.yml`, and their tests;
do not rely on a copied summary. If validation scope cannot be proven safe,
fail closed.

## Project Structure

Python code lives in `src/market_vault`; tests are in `tests`; settings
templates are in `config`; operational and CI helpers are in `scripts`.
Formal data, Dataset, point-in-time, CLI, and storage contracts live in
`docs/contracts`. Development and release rules live in `docs/governance`.
Runtime output belongs under ignored paths such as `data`, `catalog`,
`manifests`, and `reports`.

## Implementation and Validation

Use Python 3.11+ conventions already present in the repository: four-space
indentation, snake_case functions and variables, PascalCase classes, type
hints on public interfaces, and focused tests named `test_*.py`. Keep tests
offline unless a task explicitly requires live integration. Do not weaken,
skip, delete, or dilute tests, assertions, contracts, or validation merely to
obtain a green result.

Run checks appropriate to the changed surface and the repository's actual CI
classifier. Typical local checks include:

```powershell
python -m pytest tests/<focused-test-file>.py
./scripts/verify_full.ps1
python scripts/check_repo_hygiene.py
python scripts/check_release.py
git diff --check
```

On Windows, `scripts/verify_full.ps1` is the canonical local FULL test entry
point. Do not run FULL pytest with `--basetemp` inside a MarketVault repository
or any registered Git worktree. The wrapper proves an external temporary path
safe and checks disk capacity before pytest starts; see the Development
Playbook for its override and cleanup contract.

Do not manually force a reduced CI tier. Inspect the full diff and changed-file
scope before committing. PRs must state behavior and contract impact, tests
run, and any remaining live validation.

## Contract and Security Boundaries

Do not silently change schema, storage layout, data or point-in-time semantics,
compatibility guarantees, CLI behavior, CI architecture, or release process.
Make such impact explicit in the PR and obtain the required review visibility.
Keep OpenD SDK imports and tests compatible with the repository's offline
design unless a task explicitly changes that contract.

Before implementing a new operation that can delete, quarantine, restore over,
replace, incompatibly migrate, or otherwise make persistent runtime state
unavailable, stop and prepare a separate design-only PR under
`docs/governance/destructive_operations/`. The approved contract must already
exist in the implementation PR's base commit; adding or materially changing it
beside the implementation fails the repository gate. Follow
`docs/governance/DESTRUCTIVE_OPERATIONS.md`. Prompt text and developer intent
are not substitutes for the checked-in contract and CI gate.

Never commit or expose credentials, tokens, passwords, account details,
OpenD session details, or generated market data. Do not track `.env`, local
databases, Parquet output, caches, virtual environments, or runtime data
directories. Never move, delete, or recreate formal tags, and never create or
mutate GitHub Releases or their assets without explicit repository-owner
authorization.

## Codex Phase/Risk Model Routing

This optional workflow requires local verification and refines the development flow and
authority boundaries. It does not replace them. See
`docs/governance/codex_model_routing_v1.md`.

After capability and activation checks pass, keep the primary coordinator on the
verified Sol default and use `scripts/codex_model_router.py` for material phase
routing. First derive a structured task from the work order and real evidence;
do not classify by file extension or command length alone. Invoke the helper with
`--task <outside-repository-json>` and optional `--state <prior-phase-state>`.
Treat exit 2/INVALID_INPUT or exit 3/HOLD as a stop, not permission to guess a role.
A DISPATCH_REQUEST is a selection, not proof that the requested model ran.
Model/effort routing is automatic; permission escalation is NOT automatic.
Before each dispatch supply `effective_parent_sandbox` and a current
`permission_evidence_reference` bound to the parent session/turn. Native children
inherit/reapply the parent turn's live permission mode: role-local `sandbox_mode`
is a desired/default setting, not sufficient enforcement proof. Read-only roles
require a read-only parent; mv_builder requires a workspace-write parent plus the
existing scoped authorization. A mismatch, danger-full-access, unknown mode or
missing evidence returns HOLD. Treat `required_parent_sandbox` as the prerequisite;
the input claim and role default do not verify the effective runtime boundary.
Switching the parent permission mode is a separate explicit workflow action under
existing authorization, never a router action or implicit response to HOLD.
Reacquire current permission evidence after any session/turn or permission change;
verify the child's effective runtime policy before task effects and stop on drift.

Dispatch the named custom agent in `.codex/agents/`, wait for its result, close its
thread, and verify the checkpoint before dispatching another. Do not create
parallel writers or recursively delegate. Keep the same role inside an open phase;
if escalation is required, stop the old child and hand off explicitly. Model, role,
reasoning effort and effective sandbox must be recorded from runtime evidence,
not from a model's self-description. Unknown observations remain unknown.

Only mv_builder may carry out the owner's scoped implementation grant, and the
coordinator must not write while that builder is active. Running tests that write
files uses existing separately approved test/scratch rules, not mv_inventory's
read-only log-reading role. Mechanical checks and CI waits should use approved
existing scripts rather than repeated model turns.

Authentication, sandbox, environment and quota failures do not trigger blind
model escalation. Do not change account, provider, origin, project trust, network
or permission settings to bypass failures. Final audit assistance does not grant
merge authority, and merely changing models or forking the implementation thread
does not satisfy independent review. Retain the existing external exact-head gate.

For this routing feature's own implementation/review, do not bootstrap approval
from its unreviewed instructions. Use the previously approved workflow and stop
for external independent review. Before live activation, inspect actual local
client capability/configuration; the presence of these files alone is not activation.

## Codex Route Visibility V1.1

For the activated MarketVault routing workflow, show the user one concise status
notice only at a real native-child dispatch, its return, or a material router
HOLD. See `docs/governance/codex_route_visibility_v1_1.md`. These notices do
not alter V1 routing decisions, permissions, checkpoints, or authority.

After obtaining a valid `DISPATCH_REQUEST` and confirming the selected native
child is about to be spawned, emit exactly one visible progress message:
`◆ ROUTE  <phase> → <role> | <friendly-model> · <effort> | <required-parent-sandbox>`.
Take phase, role, requested_model, requested_effort, and
required_parent_sandbox only from that router output. Map `gpt-6-luna` to
`GPT-6 Luna`, `gpt-6-sol` to `GPT-6 Sol`, and `gpt-6-astra` to `GPT-6 Astra`.
If a required value is missing or unmapped, stop rather than invent a notice or
spawn. This is a requested route, never runtime-model verification or authority.
For `stop_child_then_escalate_at_checkpoint`, wait until the old child has
actually stopped and its checkpoint is processed before showing the new ROUTE
notice immediately ahead of the new spawn. Contemplating a model, deterministic
commands, and repeated tool calls do not produce ROUTE notices.

After the child completes and its checkpoint is processed, emit exactly one
visible return notice for that dispatch: `↩ RETURN <role> | completed |
checkpoint passed`, or `↩ RETURN <role> | completed | checkpoint unresolved`
when the checkpoint is not established. A child execution failure uses
`↩ RETURN <role> | failed | <short stable failure-class>`. For mv_reviewer,
use `↩ RETURN mv_reviewer | completed | advisory only` unless a separately
valid external-review checkpoint exists. Its own output never grants formal
independent approval. An observed runtime model/effort may be appended only
when independently evidenced by runtime telemetry, not role defaults,
requested values, model self-description, or the notice itself.

For router `HOLD` on a material routed phase, show exactly one visible
`■ HOLD <phase> | <short stable human-readable reason>` and spawn no child.
Translate the decisive router reason using the V1.1 governance mapping;
`remote_write` reads `separate authorized executor required`. Do not silently
escalate permission, retry with broader sandbox, or treat HOLD as a route.
Notices never include task JSON, permission-evidence references, prompts,
credentials, hidden reasoning, full reason-code arrays, or long error logs.
Do not show these notices for shell commands, search, hashes, tests, CI waits,
or every tool call.
