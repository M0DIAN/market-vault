# Codex phase/risk model routing v1

Status: routing V1 technical gate PASS; activation-ready only for the pinned,
normal-mode client/environment validated by the externally accepted Phase D2.
Automatic routing remains inactive until the reviewed tree is merged and the
formal-main activation checks below pass. Strict parsing remains incompatible;
the bounded external-tooling exception below is not a strict-parsing PASS.
The accepted Phase-C permission failure is retained; its remediation and the
subsequent live boundary evidence are separate checkpoints.
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
when supported by the installed version and report its result separately. A
compatibility failure that prevents project loading, native dispatch, model/effort
observation or required permission enforcement blocks activation. The specific
pre-existing strict-parser failure documented below is a known non-routing tooling
limitation only for the pinned, actually tested normal-mode environment. No other
client/configuration incompatibility inherits that exception.

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
An unknown required live field blocks automatic activation but does not turn an offline test
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

The permission remediation added the missing pre-dispatch parent permission gate
and offline phase-matrix tests without changing role models/defaults, trust, the
client or global configuration. That commit did not run live smokes. Its then-open
live-validation checkpoint was subsequently closed by separately authorized Phase
D2 and the owner's reported external final review: PASS. This does not erase the
Phase-C failure or use the new mv_reviewer role to approve its own feature.

## Accepted Phase-D2 closure and bounded activation policy

The accepted repository exact-head review and Phase-D2 live evidence bind to head
`364237ef09c81652290b31a2a3d3279b90178e7a`, tree
`ebfabf711e1d209a2c015afe99ef880fcf9b3506`, with main
`4279e53df361080f3271e30f8346fb7d80e7a834`. The final policy-only commit changes
this document alone; it does not relabel those historical measurements or their
review as observations of a new head. Recheck the unchanged router/configuration
blobs and exact-head CI, then obtain the final external exact-head review before
owner merge authorization. No merge authorization has been granted.

Pinned tested environment (not a compatibility claim for other installations):

- Windows Desktop-bundled client `0.155.0-alpha.9.2`, executable
  `C:\Users\Administrator\AppData\Local\OpenAI\Codex\bin\247581e40ee272fb\codex.exe`;
  binary SHA256 `bc45017e8239dc150258f69309ced9df6bbcdf5b8e4f346decf780ac0999e226`.
- Exact trusted project root `D:\GitHub\market-vault`; normal-mode `config/read`
  enabled its project layer and resolved `gpt-6-sol / medium`. Project config
  file SHA256 `ae134422850c3375e0a7ac588e4bba6e7786a2db03e86b58ee24a26831e8324b`.
- Unmodified user configuration SHA256
  `e8b1ec88a037e9b85fc3936b662b22a1249bb748d70e7de696a9051bbd9f4ebf`. No full
  configuration, credentials or Computer Use application list is included here.
- Retained external D-drive evidence bundle `PHASE_D2_SANITIZED_EVIDENCE.zip`,
  SHA256 `d41ebc3ca6da87ebdff79154b8ceb186b4bd82c7a47b9d59c2949d4da9f43aff`. Its manifest
  includes native protocol carriers, completed-response telemetry, per-role
  permission probes, negative gates and pre/post frozen-state checks.

Accepted observations:

- The normal-mode project configuration actually loaded; all five native roles
  were dispatched once, serially, with no model/effort override or retry.
- Each `subAgentActivity` explicitly carried both native `agentPath` and runtime
  `agentThreadId`, bound to the exact parent thread/turn and spawn call. The unique
  mapped child completed a tool-free READY turn before its probe was released.
- Completed-response/runtime telemetry verified the model/effort matrix below;
  config metadata, AGENTS instructions and model self-report were not substitutes.
- Actual child runtime sandbox observations preceded task effects. Four own-TEMP
  writes were denied with the sentinel absent. The builder's disposable D-drive
  own-TEMP fixture had collision=false, one CreateNew success, exact readback,
  successful cleanup and final absence. No repository/production writes occurred.
- The wrong-parent read-only-role and builder gates returned HOLD. `remote_write`
  returned HOLD in every supported parent mode; `authority_granted=false` and
  `automatic_remote_write=false`. No real remote write or approval escalation
  occurred; approval requests were zero.
- Fresh-context smoke construction was verified with `fork_turns=none` and a
  distinct native reviewer child. Hidden assembled prompt contents remain
  NOT_VERIFIED. This smoke is not formal independent review or PR approval; the
  existing external reviewer supplied the accepted review independently.

| Native role | Observed runtime model / effort | Observed child sandbox | Own-TEMP result |
| --- | --- | --- | --- |
| mv_inventory | gpt-6-luna / low | read-only | DENIED; absent |
| mv_analyst | gpt-6-sol / medium | read-only | DENIED; absent |
| mv_reasoner | gpt-6-astra / medium | read-only | DENIED; absent |
| mv_reviewer | gpt-6-astra / high | read-only | DENIED; absent |
| mv_builder | gpt-6-sol / medium | workspace-write | SUCCESS; exact readback; cleaned; absent |

Strict startup still fails on the pre-existing Desktop Computer Use
serialization/parser incompatibility involving
`computer_use.windows.always_allowed_app_ids`. That field, Computer Use settings,
client version, trust, provider/auth and permission settings were not modified to
manufacture PASS. Normal-mode loading and the accepted live matrix establish that
this strict-only incompatibility is a KNOWN_EXTERNAL_TOOLING_LIMITATION, not an
automatic-routing activation blocker for this pinned tested environment. Strict
parsing has not passed and remains explicitly false:

```text
STRICT_CONFIG_COMPATIBLE=false
STRICT_CONFIG_REQUIRED_FOR_ROUTING_ACTIVATION=false
STRICT_CONFIG_LIMITATION_CLASS=KNOWN_EXTERNAL_TOOLING_LIMITATION
ROUTING_V1_TECHNICAL_GATE=PASS
AUTOMATIC_ROUTING_ACTIVATION_READY=true
AUTOMATIC_ROUTING_ACTIVATED=false
MERGE_AUTHORIZED=false
```

This is readiness, not activation on formal main. Activation requires the reviewed
tree to be merged under explicit owner authorization, post-merge exact-main
verification under the existing Development Playbook, and a new normal-mode
`config/read` proving the project configuration loaded from that formal main.
The coordinator must reacquire the exact main/tree and loaded-config evidence
before dispatch; record activation only after all those checks pass. A mismatch
or missing required evidence keeps routing inactive. The runtime parent-permission
gate and separate authorization for changing permission mode remain mandatory.

This exception must be revalidated after a material client/configuration or
environment change, including binary/version, project or user configuration,
role assignments, account/provider/model availability, trust, sandbox/approval
policy, or OS sandbox behavior. Do not transfer the D2 PASS or strict exception to
another client, checkout or permission domain. Use a separately authorized bounded
revalidation; until it passes, keep automatic routing inactive. Existing manual
coordination and external independent-review requirements remain available.

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
