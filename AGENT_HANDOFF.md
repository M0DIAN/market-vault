# MarketVault Agent Handoff

The execution contract for Claude Code and Codex agents working on
MarketVault. Agents follow this contract in place of receiving the full
gate specification inside every prompt. The playbooks it references are
[DEVELOPMENT_PLAYBOOK.md](DEVELOPMENT_PLAYBOOK.md) and
[RELEASE_PLAYBOOK.md](RELEASE_PLAYBOOK.md).

## 1. Execution contract

1. **Agent is executor; independent reviewer remains separate.** The
   agent implements and verifies. An independent reviewer — a human or a
   separate review process, never the same agent instance — approves.
2. **Never treat the agent's own report as independent verification.**
   The agent's "I checked it" is not the review gate. The independent
   review gate (development playbook 1.8) is satisfied only by a
   reviewer other than the authoring agent.
3. **Exact base SHA must be checked before work.** Run the exact-base
   procedure (development playbook 1.1): switch to `main`, fetch,
   fast-forward, verify `HEAD == origin/main == <base SHA>`, verify a
   clean worktree. If the check fails, stop and report.
4. **Scope expansion requires stopping, not silently adding work.**
   If the work reveals that the frozen scope is wrong or incomplete,
   stop and report the needed expansion. Do not fold it in.
5. **STOP BEFORE MERGE unless explicitly authorized.** The agent never
   merges its own PR without explicit merge authorization.
6. **Never move / recreate release tags without explicit release
   instruction.** No tag creation, deletion, movement, or recreation
   outside an explicit release task.
7. **Never amend / rebase / force-push protected release history
   without explicit authorization.** Release commits, tags, and the
   formal release records are immutable (release playbook 2).

## 2. Final-reporting rule: wait for CI to reach a terminal state

This is the most important reporting rule.

If a task triggers GitHub CI, the agent MUST wait for the CI associated
with the exact final head SHA to reach a terminal state.

The agent MUST NOT output the final acceptance / completion report while
CI is:

- queued
- waiting
- pending
- in_progress

Only after the CI for the exact final head SHA reaches a terminal state:

- **SUCCESS** — report `READY FOR INDEPENDENT REVIEW` (with the compact
  final-report fields below).
- **FAILURE** — report `FAILED`, naming the failing job and failing
  step.

If the task subsequently merges and triggers main CI, apply the SAME
rule to the exact merge / main commit before reporting `COMPLETE`.

Do not drip-feed "CI pending" as a final report. Interim progress
messages are fine; the final report is emitted only at a terminal CI
state.

## 3. Compact standard final-report fields

Every final report contains exactly these fields, in this order:

| Field | Content |
|---|---|
| base SHA | the exact base SHA verified before work |
| final head SHA | the pushed head SHA whose CI was evaluated |
| changed files | the exact changed-file list |
| local checks | the local verification performed and its results |
| CI run ID | the GitHub Actions run ID for the final head |
| CI job conclusions | every job's conclusion (SUCCESS / FAILURE) |
| diff / scope result | diff stat and confirmation the changed-file list matches the frozen scope |
| working-tree state | clean or the exact remaining changes |
| mutation / immutability declaration | explicit confirmation that no product / version / dependency / API / CLI / schema / workflow / release mutation occurred, when that is true |
| stop state | the current stop point (for example "STOP BEFORE MERGE", "READY FOR INDEPENDENT REVIEW") |

## 4. Reporting vocabulary

- `READY FOR INDEPENDENT REVIEW` — final-head CI terminal SUCCESS, all
  local and scope checks done; the independent reviewer is the next gate.
- `FAILED` — final-head CI terminal FAILURE; report the failing job and
  step.
- `COMPLETE` — reserved for post-merge tasks whose exact merge / main
  commit CI is terminal SUCCESS.
- `STOP BEFORE MERGE` — the explicit stop state; merge requires separate
  authorization (contract rule 5).

## 5. Protocol violations

The following are protocol violations and must be reported as such:

- Working from an unverified base.
- Silent scope expansion.
- Reporting acceptance while CI is queued / waiting / pending /
  in_progress.
- Treating an agent's own report as the independent review.
- Moving, recreating, amending, or force-pushing release history without
  explicit authorization.
