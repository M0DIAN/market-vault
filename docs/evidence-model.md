# Evidence model

The post-merge FULL reuse proof is built around one idea: the evidence
that matters is the **tree** that was tested, not the commit that
produced it.

## Synthetic PR merge commit ≠ squash main commit

When you open a pull request, GitHub Actions checks out a **synthetic
merge commit** — `refs/pull/<n>/merge` — produced by merging the PR
head into the current base. When you merge the PR with a squash merge,
`main` receives a **new commit** whose tree happens to be identical to
the PR's merge result.

- the synthetic PR merge commit: created by the merge ref machinery,
  has the base and head as parents, and exists only while the PR is
  open;
- the squash commit on `main`: has exactly one parent (the previous
  `main`), and carries the merge result as its tree.

## Commit SHA equality is NOT expected

Because these are different commits, their SHAs differ by construction.
Requiring commit SHA equality would make reuse structurally
unreachable. The framework never compares commit SHAs between the PR
run and the main push.

## Tree equality is the core proof

What must be identical is the Git tree:

```
git rev-parse <main-sha>^{tree}  ==  attestation.tested_tree_sha
```

`tested_tree_sha` is recorded at attestation time from the synthetic
merge commit (`git rev-parse <GITHUB_SHA>^{tree}` on the PR run). A Git
tree is the byte-exact fingerprint of the file set — identical trees
mean the FULL run validated exactly the files that `main` now contains.
This is what makes reuse sound: the PR FULL evidence covers the exact
content of the merged commit.

## The exact run/attempt/job contract

Tree equality alone is not sufficient; it must be bound to an exact,
verifiable execution:

- **exact run**: a completed, successful `pull_request` run of the
  configured workflow on the exact PR head SHA;
- **exact attempt**: the attempt-bound attestation artifact of that run
  and attempt (name `<prefix><head_sha>-attempt-<attempt>`, matching
  `run_id` / `run_attempt` fields);
- **exact job set**: the run's jobs terminate SUCCESS on exactly the
  configured formal job set — no missing, duplicate, unexpected, or
  non-success job;
- **exact identifiers**: repository, workflow, PR number, base SHA, and
  head SHA all match the context re-derived from git and the API.

Only when every one of these holds — plus the push shape, squash
topology, and control-plane checks — does the verifier emit
`POST_MERGE_REUSE=true`.

## What the attestation records

| field | meaning |
| --- | --- |
| `schema_version` | attestation schema (1) |
| `repository` | `owner/repo` the run belonged to |
| `workflow` | configured CI workflow name |
| `run_id` / `run_attempt` | the exact run that executed the FULL matrix |
| `pr_number` | the pull request |
| `base_sha` / `head_sha` | the PR base and head |
| `tested_merge_sha` | the synthetic merge commit that was tested |
| `tested_tree_sha` | its tree — the reuse proof value |
| `tier` | must be `"full"` |
| `full_matrix_required` | must be `true` |

## Failure modes (all fail closed)

- missing / extra / malformed attestation ⇒ `reuse=false`
- run or attempt mismatch ⇒ `reuse=false`
- tree mismatch ⇒ `reuse=false`
- control-plane mutation in the merged change ⇒ `reuse=false`
- anything unproven ⇒ `reuse=false` ⇒ fresh FULL validation runs
