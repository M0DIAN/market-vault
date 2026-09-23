# Codex phase/risk model routing v1

Status: repository integration for independent review; automatic routing is inactive.
Runtime integration is IMPLEMENTED_NOT_WIRED on the probed Windows installation.
This is a development-agent workflow, not MarketVault runtime functionality.
It refines existing gates; it does not replace AGENTS.md or grant new authority.

## Mechanism and limits

The primary Codex session normally stays on GPT-6 Sol / medium. At a phase boundary
it supplies a structured task to `scripts/codex_model_router.py`, reads the JSON
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

| Role | Model / effort | Intended use | Expected default sandbox |
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
7. Keep the role inside an open phase; no downgrade until its checkpoint closes.
   New evidence may require stopping the child and starting an upgraded role with
   an explicit handoff. Never change a model mid-tool-call or retry hidden writes.

Trivial editorial work does not inherit an eight-phase mandatory ceremony. Do not
add independent reviews to every extraction, nor call a model repeatedly just to
wait for CI. Run approved deterministic checks with the existing runner, and pass
only terminal results or relevant failure excerpts to a model. Test execution may
write caches and fixtures; `validation_readback` is log reading, not authorization
to run tests in a supposedly read-only sandbox.

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

Custom-agent sandbox entries are DEFAULTS, not hard caps. Local Codex can reapply
parent-turn live permission overrides to children. Before execution check the
actual effective permission policy. An Astra selection grants no extra write or
network permission. Do not set danger-full-access, never-approval, global trust,
new writable roots, credentials or policy bypass flags to make routing work.

One spawned child at a time is the v1 concurrency setting. The coordinator must
not edit while a builder is active. The setting alone does not prevent the primary
session or other processes from writing: verify the operational single-writer rule.

The mv_reviewer role is review ASSISTANCE. A different model or name alone is not
independence. For formal review use a distinct process/session that did not author
the change, does not inherit the implementation transcript and reacquires exact
objects. If the UI/client cannot prove clean review context, use the existing
external reviewer; never label an inherited implementation thread independent.
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
CI whitelist to reduce validation effort. Use existing D-only Windows FULL entry
points when the actual classifier requires them.

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

## Local integration observation (2026-09-23)

The installed client reports `codex-cli 0.155.0-alpha.9.2`. Its normal app-server
`model/list` returns `gpt-6-luna`, `gpt-6-sol`, and `gpt-6-astra` with the required
low/medium/high effort choices. This proves catalog availability, not inference.

`config/read` with the source repository as cwd recognizes the project layer but
returns a `disabledReason`: the project is not trusted. The merged effective
configuration therefore retains the existing user Astra/xhigh default and has no
active project agents settings. A no-turn ephemeral `thread/start` confirms
Astra/xhigh, on-request approvals, the user reviewer, and a read-only permission
profile with network disabled. No model turn or role smoke was submitted.

Strict startup separately fails on a pre-existing user configuration field,
`computer_use.windows.always_allowed_app_ids`. Normal startup reports that field
as ignored. Neither observation authorizes editing the user's global settings.
Project trust, permissions, provider and authentication were not changed.

Consequently PROJECT_CONFIG_LOADED=false; LIVE_ROLE_DISPATCH_VERIFIED,
EFFECTIVE_PERMISSIONS_VERIFIED (role boundaries), and
REVIEW_CONTEXT_ISOLATION_VERIFIED remain NOT_VERIFIED. Reading AGENTS.md in the
ephemeral session is not evidence of role/config activation. The initial role
smoke budget remains unused (0/5); its builder fixture must stay outside all
repositories on the approved D drive. When the owner separately resolves the
environment, rerun these gates in a new coordinator before any activation claim.
Keep ordinary manually selected Sol available as the fallback workflow; this
probe did not change the active session or user default to Sol.

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
