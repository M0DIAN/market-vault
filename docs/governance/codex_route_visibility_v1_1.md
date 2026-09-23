# Codex route visibility V1.1

This change makes material MarketVault routing observable to the user. It
changes coordinator display behavior in `AGENTS.md`; V1 remains authoritative
for selection, authorization, permissions, checkpoints, and remote-write HOLD.
The deterministic router, project configuration, role definitions, and product
code are unchanged. V1.1 visibility is proposed on this feature branch and is
not active on formal main until reviewed and merged.

```text
ROUTE_VISIBILITY_VERSION=1.1
ROUTING_POLICY_VERSION=1.1.0
ROUTING_DECISION_LOGIC_CHANGED=false
PERMISSION_LOGIC_CHANGED=false
MODEL_ASSIGNMENTS_CHANGED=false
```

## Visible events

After a valid `DISPATCH_REQUEST`, when the coordinator is about to spawn the
selected native child, emit exactly one user-visible progress message:

```text
◆ ROUTE  <phase> → <role> | <friendly-model> · <effort> | <required-parent-sandbox>
```

Use only router-output `phase`, `role`, `requested_model`, `requested_effort`,
and `required_parent_sandbox`. Display `gpt-6-luna` as `GPT-6 Luna`,
`gpt-6-sol` as `GPT-6 Sol`, and `gpt-6-astra` as `GPT-6 Astra`. Missing or
unmapped fields stop the dispatch; never guess from AGENTS prose, role names,
or TOML. A ROUTE notice is a selected/requested route and grants no authority.
It does not assert that the selected runtime model or permission took effect.

After the native child has completed and the checkpoint has been processed,
emit exactly one return for that dispatch:

```text
↩ RETURN <role> | completed | checkpoint passed
↩ RETURN <role> | completed | checkpoint unresolved
↩ RETURN <role> | failed | <short stable failure-class>
```

Use `checkpoint passed` only after the actual checkpoint passes. If the child
finishes but checkpoint evidence is absent or inconclusive, use `checkpoint
unresolved`. Execution failure uses a short stable class such as
`execution-error`, `timeout`, or `permission-mismatch`; details belong in the
normal evidence report, not the notice. For `mv_reviewer`, a completed smoke or
review assistance returns `↩ RETURN mv_reviewer | completed | advisory only`
unless a separately valid **external** review checkpoint exists. The native
reviewer role cannot approve its own feature or supply formal independent
approval merely by completing.

When the router returns `HOLD` for a material routed phase, emit one visible
`■ HOLD <phase> | <short stable human-readable reason>` and spawn no child.
Use the decisive reason from the router result, not a model's explanation.
Examples and stable translations:

| Router reason | Visible reason |
| --- | --- |
| `READONLY_ROLE_REQUIRES_READONLY_PARENT` | read-only role requires read-only parent |
| `BUILDER_REQUIRES_WORKSPACE_WRITE_PARENT` | builder requires workspace-write parent |
| `CURRENT_PARENT_PERMISSION_EVIDENCE_REQUIRED` | current parent permission evidence required |
| `REQUIRED_MODEL_UNAVAILABLE_NO_SILENT_FALLBACK` | required model unavailable; no fallback |
| `USE_SEPARATELY_AUTHORIZED_EXECUTOR_AND_EXACT_OBJECT_RECHECK` | separate authorized executor required |
| `SCOPE_NOT_FROZEN` | scope not frozen |
| `EXPLICIT_SCOPED_WRITE_AUTHORIZATION_REQUIRED` | scoped write authorization required |
| `PATH_OUTSIDE_APPROVED_SCOPE` | path outside approved scope |
| `ASTRA_READONLY_PLAN_REVIEW_REQUIRED_BEFORE_WRITING` | read-only plan review required before writing |
| `STOP_REPEATED_PATCHING_AND_REOPEN_REASONING_CHECKPOINT` | repeated patching stopped; reopen reasoning checkpoint |
| `PHASE_ATTEMPT_BUDGET_EXHAUSTED` | phase attempt limit reached |
| `PREVIOUS_PHASE_CHECKPOINT_STILL_OPEN` | previous phase checkpoint still open |
| `FIX_ENVIRONMENT_OR_ACCESS_NOT_MODEL:<kind>` | fix <kind> access or environment before routing |

For `remote_write`, display `■ HOLD remote_write | separate authorized executor
required`. For an unknown or ambiguous reason, stop and report `routing hold;
reason unresolved` without printing the full reason-code array or launching a
child. A HOLD notice does not request permission escalation.

When the router returns `transition=stop_child_then_escalate_at_checkpoint`,
the previous child must stop and its checkpoint be processed first. Show the
new ROUTE line only immediately before the new child actually spawns. Do not
print a ROUTE line for a contemplated model, repeated deterministic commands,
or a transition that stops before dispatch.

Only native dispatch, its return, and a material HOLD produce these notices.
Ordinary shell commands, grep/search, deterministic hashes, local Python checks,
CI polling, and individual tool calls do not. One dispatch has one ROUTE and
one RETURN. A HOLD has one HOLD and zero child spawns. Neither duplicates nor
silent dispatches are acceptable.

## Requested and observed values

The ROUTE line describes `requested_model` and `requested_effort` from the
router. An optional RETURN annotation such as `observed GPT-6 Astra · medium`
is permitted only when independently observed in completed-response or other
runtime telemetry. If unavailable, omit it. Never infer an observed model from
the agent name, role TOML, requested value, model self-description, or an AGENTS
instruction. Effective permissions remain governed by V1's live parent and
child checks; the display line is not permission evidence.

No notice exposes chain of thought, hidden reasoning, the full routing task
JSON, prompts, permission-evidence references, credentials, or long error logs.
The normal handoff report retains detailed evidence outside these short notices.

## Validation and rollback

Validate the exact branch head with repository checks and the actual CI
classifier. In a fresh, bounded read-only session, verify one mechanical
`mv_inventory` dispatch and return, one wrong-parent `HOLD` with zero native
children, and one adversarial-review `mv_reasoner` dispatch and return. Do not
repeat the full D2 permission matrix solely for display behavior. The external
independent exact-head reviewer remains the final review authority.

Rollback removes only this document and the `Codex Route Visibility V1.1`
instructions from `AGENTS.md` through a reviewed narrow change. It does not
alter V1 router behavior, role models, trust, permissions, or project config.
