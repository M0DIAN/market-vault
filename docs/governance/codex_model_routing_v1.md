# Codex phase/risk model routing v1

Status: repository integration for independent review; automatic routing is inactive.
Activation remains blocked by runtime permission evidence and strict-config compatibility.
The router permission gate below remediates the accepted Phase-C workflow failure;
offline PASS is not proof of a live read-only boundary.
This is a development-agent workflow, not MarketVault runtime functionality.
It refines existing gates; it does not replace AGENTS.md or grant new authority.

## Mechanism and limits

The primary Codex session normally stays on GPT-6 Sol / medium. At a phase boundary
it supplies a structured task, including current effective parent permissions and
an evidence reference, to `scripts/codex_model_router.py`, reads the JSON
routing decision, dispatches a named project custom agent, waits for completion,
and independently verifies the checkpoint before advancing. It does not need to
change the primary session's UI model on every command.

The Python helper is a deterministic decision component, NOT a daemon, runtime
hook, launcher, sandbox, credential manager or natural-language intent classifier.
Codex does not automatically execute it merely because the file exists. The
coordinator integration in AGENTS.md is needed and must be exercised in a real
session. Configuration presence, TOML validity, a DISPATCH_REQUEST result and a
model's self-reported identity are each insufficient proof of actual dispatch.

The coordinator initially classifies the phase/risk from the work order, relevant
source and actual changed-path set. Input flags are claims linked to that evidence,
not self-authenticating authority. Unknown risk is not a reason to choose Luna.
A malicious or mistaken caller can misclassify work: the policy helper is not a
security boundary. Existing sandbox, approvals, owner authority and independent
review remain the enforcement mechanisms.

## Role allocation (policy choices, not benchmark claims)

| Role | Model / effort | Intended use | Desired role sandbox default |
| --- | --- | --- | --- |
| mv_inventory | gpt-6-luna / low | Bounded extraction and validation-log readback | read-only |
| mv_analyst | gpt-6-sol / medium | Normal discovery and narrow patch planning | read-only |
| mv_builder | gpt-6-sol / medium | One writer implementing a scoped approved plan | workspace-write |
| mv_reasoner | gpt-6-astra / medium | Risk analysis, adversarial review and evidence convergence | read-only |
| mv_reviewer | gpt-6-astra / high | Fresh exact-head review assistance | read-only |

Use the actual available-model catalog and supported effort options from the local
client/account, not a remembered catalog. No new API key, account, proxy or provider
is required by this design. Do not silently fall back if a required role's model
is unavailable. Fix access/configuration or obtain an explicit revised work order.

## Selection and phase continuity

1. Authentication, sandbox, environment and quota errors HOLD: a larger model is
   not a fix for missing permission or missing input. Phase attempts above three HOLD.
2. Remote writes HOLD for a separately owner-authorized executor and exact-object
   recheck. No routing result approves commit/push/Ready/merge/release/deploy.
3. Final exact-head and publication gates use a fresh read-only review role.
4. Adversarial review and evidence convergence use the reasoner. High complexity,
   ambiguity, declared risk, sensitive changed paths or two failed reasoning/test
   attempts raise read-only analysis to the reasoner.
5. An implementation requires a real authorization reference, frozen exact paths,
   and a completed risk-plan review when risk is high. Only the builder writes.
   Repeated patch failures stop writing and reopen analysis, rather than upgrading
   a writer's privileges. A reviewed hard plan can be implemented by Sol.
6. Only explicitly bounded, low-risk mechanical work qualifies for Luna. Broader
   discovery is not mechanical merely because its first command is a search.
7. After final role selection (including sticky state), require the parent sandbox
   to be exactly read-only for inventory/analyst/reasoner/reviewer, or exactly
   workspace-write for builder. A mismatch returns HOLD; danger-full-access and
   unknown never satisfy either gate. Matching permissions also require a nonblank
   evidence reference. No dispatch state is emitted on HOLD.
8. Keep the role inside an open phase; no downgrade until its checkpoint closes.
   New evidence may require stopping the child and starting an upgraded role with
   an explicit handoff. Never change a model mid-tool-call or retry hidden writes.

Trivial editorial work does not inherit an eight-phase mandatory ceremony. Do not
add independent reviews to every extraction, nor call a model repeatedly just to
wait for CI. Run approved deterministic checks with the existing runner, and pass
only terminal results or relevant failure excerpts to a model. Test execution may
write caches and fixtures; `validation_readback` is log reading, not authorization
to run tests in a supposedly read-only sandbox.

## Parent permission input/output contract

Policy version 1.1.0 keeps the strict `schema_version=1` task envelope and adds two
mandatory fields. Older task JSON without them is INVALID_INPUT (exit 2); there is
no inferred permission mode or compatibility default. All existing fields remain
required. Add these fields to the coordinator's task object, for example:

```json
{
  "effective_parent_sandbox": "read-only",
  "permission_evidence_reference": "runtime-evidence:parent-session-7/turn-3"
}
```

This fragment is not a complete CLI input. `effective_parent_sandbox` is a closed
enum: `read-only`, `workspace-write`, `danger-full-access`, `unknown`. The reference
is a bounded string pointing to evidence, not credentials or raw configuration.
A blank reference is accepted as missing evidence and returns HOLD before dispatch.

The coordinator produces the current effective parent observation from runtime
metadata and applicable permission-boundary evidence, and carries it with the
parent session/turn identity in the referenced record. The router consumes the
claim before every dispatch; it cannot authenticate that record or establish an
OS security boundary. The record is valid only for the observed session/turn and
permission configuration. Reacquire it after any change; do not use cached role
defaults, requested permissions, AGENTS prose or model self-report as its source.
Before task effects, the coordinator verifies the child's actual runtime policy
against the required mode and stops on unknown or mismatched observations.

Outputs keep these distinct:

- `requested_sandbox`: the desired role-local default, retained for compatibility.
- `required_parent_sandbox`: the policy prerequisite for the selected role.
- `effective_parent_sandbox` / `permission_evidence_reference`: echoed coordinator
  claims, not independently verified observations from this Python helper.
- `runtime_permissions_verified=false`: the helper never attests live enforcement.

Mismatches return `READONLY_ROLE_REQUIRES_READONLY_PARENT` or
`BUILDER_REQUIRES_WORKSPACE_WRITE_PARENT`. Missing evidence with a matching mode
returns `CURRENT_PARENT_PERMISSION_EVIDENCE_REQUIRED`. HOLD uses exit 3 and has no
`next_state`; the coordinator must stop instead of launching the selected role.
Other guards may HOLD earlier (including missing authority/models and exhausted
attempts). `remote_write` always holds regardless of sandbox. Selection grants
neither authority nor automatic remote writes.

## Handoff and observable evidence

Every material handoff includes task ID, phase, active work-order reference,
exact base/head/tree where relevant, allowed paths, non-goals, confirmed findings,
retracted findings, input evidence locations/digests and the closing checkpoint.
The recipient rereads necessary source and Git objects. Do not copy the whole
conversation merely to transfer a few facts.

Use the existing crossing classes: identifiers supplied in the handoff are
EXPLICITLY_HANDED_OFF through that handoff record; fresh Git/file/CI observations
are INDEPENDENTLY_REACQUIRED. A new thread's prior reasoning is not INHERITED.
The handoff is valid only for its bound objects and phase. A head/tree change
invalidates downstream evidence and requires the existing recheck, not an old PASS.

Record requested model/effort separately from observed runtime model/effort and
the metadata source. Also record effective permissions, thread ID, role-config
hash, outcome, failure origin, elapsed time and usage when actually exposed.
Unexposed usage/model data stays unknown. No secret, auth token or full sensitive
prompt belongs in routing logs; logs and smoke-test fixtures stay in approved
D-drive scratch outside every repository/worktree.

## Permission and review boundaries

Model/effort routing is automatic when the coordinator consumes the policy;
permission escalation is NOT automatic. Native child agents inherit/reapply the
parent turn's live permission mode. Role-local `sandbox_mode` values are desired
defaults, non-authoritative when a live parent override exists, and insufficient
enforcement proof. The coordinator must supply current effective parent sandbox
evidence before dispatch. A mismatch returns HOLD even when the role TOML says
read-only. The accepted Phase-C own-TEMP write success under workspace-write is a
permission-boundary failure, not a read-only success.

Switching the parent permission mode is a separate explicit workflow action under
existing authorization. The router neither changes that mode nor requests broader
permissions to clear HOLD. An Astra selection grants no extra write or network
permission. Do not set danger-full-access, never-approval, global trust, new
writable roots, credentials or policy bypass flags to make routing work.

One spawned child at a time is the v1 concurrency setting. The coordinator must
not edit while a builder is active. The setting alone does not prevent the primary
session or other processes from writing: verify the operational single-writer rule.

The mv_reviewer role is review ASSISTANCE. A different model or name alone is not
independence. Formal independent review still uses the existing external reviewer
in a distinct process/session that did not author the change, does not inherit the
implementation transcript and reacquires exact objects. Never label an inherited
implementation thread independent.
The new routing implementation/configuration must itself be reviewed under the
existing workflow, not self-approved by its newly written reviewer instructions.

## Installation and activation gates

Create a new feature branch from the verified current main after the PR #195 merge
closure. Never append routing work to PR #195 or edit its frozen Linux contract.
Read existing `.codex/config.toml`, `.codex/agents/`, user configuration and managed
requirements without printing secrets. Merge changes; do not replace unrelated
settings, duplicate existing roles or edit global authentication/permissions.

Use the current documented standalone custom-agent TOML schema only when the
installed client actually supports it. Do not load both standalone roles and legacy
role declarations for the same name. Project settings must really load for the
trusted project; do not silently change project trust. Check strict config parsing
when supported by the installed version. A client incompatibility is a TOOLING or
ENVIRONMENT failure and leaves activation blocked.

Offline gate: focused tests, TOML parsing and role/model consistency, negative
cases, Python syntax, repository hygiene and existing CI tier classifier. Do not
assume docs_fast: this change includes scripts/tests/agent config. Never broaden the
CI whitelist to reduce validation effort. Follow the Development Playbook's local
validation levels and natural exact-head CI requirement. If local FULL is run,
use the existing D-only Windows FULL entry point.

Live gate: at most five bounded smoke-role calls for initial activation, one per
role. Use normal account credentials and a disposable D-drive fixture for the
builder (not product code). Observe loaded role, requested/actual model, effective
sandbox, one-child concurrency, fresh-context behavior and the rule that remote
writes return HOLD. When testing permission denial, use only a disposable sentinel
whose mutation is harmless and authorized; never probe denial against production
files. Do not claim enforcement without an actual observation.

Report separately: OFFLINE_POLICY_TESTS, CLIENT_CONFIG_LOAD, MODEL_CATALOG,
LIVE_ROLE_DISPATCH, EFFECTIVE_PERMISSIONS, REVIEW_CONTEXT_ISOLATION and ACTIVATION.
An unknown live field blocks automatic activation but does not turn an offline test
into FAIL or PASS for an unrelated claim.

## Local integration evidence and remediation (2026-09-23)

The accepted failed head is `ba2b6226d470e8f2b4e11087e424087765169200`, tree
`a873663bd050b340a9976f5d5c24e9e315eb6f86`. Earlier initial-integration observations
of an untrusted project were superseded by owner-authorized Phase B: normal
`config/read` loaded the exact trusted project and resolved Sol/medium. The client
was `codex-cli 0.155.0-alpha.9.2`; its catalog exposed Luna/low, Sol/medium and
Astra/medium/high. Catalog availability and configuration loading are distinct
from completed inference.

Phase C established that mv_inventory requested `gpt-6-luna / low / read-only`
but actually ran `gpt-6-luna / low / workspace-write`. Its harmless own-TEMP write
succeeded with no approval escalation. This is the accepted
`AGENT_WORKFLOW_IMPLEMENTABILITY_FAILURE`, blocker
`PARENT_RUNTIME_SANDBOX_OVERRIDES_ROLE_READONLY_DEFAULT_WITHOUT_ROUTER_GATE`.
The evidence is retained; declaring read-only in TOML did not enforce it.

The remediation adds the missing pre-dispatch parent permission gate and offline
phase-matrix tests. It changes no role model/default, trust, client or global
configuration. It does not rerun live role smokes or retroactively validate role
boundaries. Post-remediation live permissions and dispatch enforcement remain
NOT_VERIFIED until separately authorized runtime validation and external review.

Strict startup still has the known incompatibility with the existing user field
`computer_use.windows.always_allowed_app_ids`; this remediation does not edit it.
`STRICT_CONFIG_COMPATIBLE=false`, `AUTOMATIC_ROUTING_ACTIVATED=false`, and
`MERGE_AUTHORIZED=false` remain in force. Ordinary manually selected coordination
and the existing independent-review workflow remain available.

## Rollback and evaluation

Before integration retain exact original bytes of existing touched configuration
outside the repository. Rollback is a reviewed narrow revert/restoration of just
this feature's files/hunks, not `git reset --hard`, wholesale replacement, branch
rewrite, credential cleanup or deleting a scratch parent. Stop routing first;
return to the manually selected Sol workflow and existing review gates.

Pilot before expanding. Compare representative tasks against fixed-Sol runs on
matched inputs/checkpoints. Measure time to accepted completion, total observable
usage including coordinator/handoffs/retries, first-review acceptance, rework and
routing errors. Do not freeze an unmeasured savings percentage or model-use ratio.

## Official interface references (checked 2026-09-23)

- Models: https://developers.openai.com/codex/models
- Custom subagents and live permission overrides: https://developers.openai.com/codex/subagents
- Project config/trust/precedence: https://developers.openai.com/codex/config-basic
- Configuration keys: https://developers.openai.com/codex/config-reference
- CLI flags and strict config: https://developers.openai.com/codex/cli/reference
- Available model catalog and thread APIs: https://developers.openai.com/codex/app-server

These references document interfaces, not a guarantee that this Windows installation
has loaded the candidate, that this account exposes every model, or that the router
saves a particular amount of usage. Keep documented capability distinct from probe evidence.
