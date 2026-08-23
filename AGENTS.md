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

Never commit or expose credentials, tokens, passwords, account details,
OpenD session details, or generated market data. Do not track `.env`, local
databases, Parquet output, caches, virtual environments, or runtime data
directories. Never move, delete, or recreate formal tags, and never create or
mutate GitHub Releases or their assets without explicit repository-owner
authorization.
