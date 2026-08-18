# CI Optimization Framework

Conservative, fail-closed CI optimization: deterministic risk-tier
classification of change ranges and exact-tree post-merge FULL reuse for
GitHub Actions. Runtime is Python 3.11+ stdlib-only, with a single
strict configuration file (`ciopt.toml`).

> **Provenance.** This framework was extracted and generalized from the
> production CI governance and optimization system developed for
> MarketVault. Source extraction baseline:
> [M0DIAN/market-vault](https://github.com/M0DIAN/market-vault) at
> `99840349bdab4f0dc56a420bc66a1556750d1878`. The extraction carries
> forward only the production-proven, fail-closed V1 contracts.

## Problem

CI often reruns expensive validation even when the risk profile does not
require it. A documentation-only change reruns the same hours of tests
as a change to core code, and every merge to `main` reruns the entire
FULL matrix that the merged pull request already validated.

## Framework strategy

```
CHANGE
  ↓
RISK CLASSIFIER
  ├─ docs_fast
  ├─ package_docs
  ├─ control_plane
  └─ full

For FULL PR:

RUN FULL
  ↓
CREATE ATTESTATION

After squash merge:

PROVE SAME TESTED TREE
  ↓
YES → reuse PR FULL evidence
NO  → run FULL again
```

The classifier maps a change range to one of four stable tiers:

| tier | meaning |
| --- | --- |
| `docs_fast` | every changed path is inside the configured docs scope (validated generic fast path) |
| `package_docs` | every changed path is docs or a package-doc file (e.g. README), and a package-doc file changed — core tests may skip, package validation MUST still run |
| `control_plane` | OPT-IN, disabled by default: every changed path is inside the exact configured control-plane eligible subset — a downstream-specific conservative validation surface |
| `full` | everything else — including empty diffs, unknown paths, and any failure to classify |

**Component impact is exposed separately from the tier and never
authorizes skip.** A registered `[components.*]` surface may report
`independent_only=true`, but the tier stays `full` unless an explicit
validated validation contract exists.

**The tiers are per-surface, not a single switch.** A tier authorizes a
skip only for the surface whose validation is unnecessary under that
tier's contract: `docs_fast` may skip both the core matrix and package
validation; `package_docs` may skip the core matrix but MUST still run
package validation (a package-doc change such as README is package
metadata); `control_plane` is never claimed by the generic template —
the framework does not auto-provide a validated control-plane subset.

## Security principle

> Cannot prove safe optimization
> ⇒ do more work.
>
> Never:
> cannot prove
> ⇒ skip work.

The framework fails closed everywhere. Unknown / unset / malformed
config, unknown paths, empty diffs, unresolvable refs, git or network
failures, missing or stale evidence — every one of them lands on
`full` / `reuse=false`, and the workflow runs normal FULL validation.

Post-merge FULL reuse (V1) is authorized **only** when every proof
holds: exact push shape, one-parent squash topology, exactly one
associated merged PR with exact base/head identity, a completed
successful `pull_request` run of the configured workflow on the exact
head SHA, a job set that terminates SUCCESS on exactly the configured
formal jobs (no missing/duplicate/extra), an attempt-bound attestation
matching every identifier, **tree equivalence** between the current
`main` tree and the tree the PR run tested, and no control-plane
mutation. Anything else ⇒ `POST_MERGE_REUSE=false` ⇒ fresh FULL.

**Proof failure is never a CI failure.** `reuse=false` just means the
workflow runs the validation itself.

## Installation

**v0.1.0 is not published to PyPI.** Install it from source.

For local framework development, install the checkout in editable mode
with the dev extras:

```console
python -m pip install -e ".[dev]"
```

Downstream repositories pin the framework source with a git install.
Replace `<OWNER>/<FRAMEWORK_REPO>` and `<TAG>` with the final values:

```console
python -m pip install \
  "git+https://github.com/<OWNER>/<FRAMEWORK_REPO>.git@<TAG>"
```

`ci-opt` is the CLI; `python -m ci_optimizer` works too. Copy
`ciopt.example.toml` to `ciopt.toml` in your repository root and adapt
it (see [docs/configuration.md](docs/configuration.md)).

```console
ci-opt classify --config ciopt.toml \
  --mode pull_request --base <BASE_SHA> --head <HEAD_SHA>
```

`classify` prints JSON by default; `--output env` emits production
key=value lines; `--output github-env` emits only valid GitHub Actions
environment assignments (`CI_TIER`, `CI_TIER_REASON`, `CI_COMPONENTS`,
`CI_CORE_CHANGED`, `CI_PACKAGE_CHANGED`, `CI_UNKNOWN_CHANGED`,
`CI_SHARED_CHANGED`, `CI_INDEPENDENT_ONLY`, `CI_FULL_MATRIX_REQUIRED`,
`CI_CHANGED_FILES`) — the renderer used by the workflow templates.

## Adoption path

The framework is designed to be adopted gradually. **Strongly
discouraged: enabling all optimizations at once.**

1. **Phase 1 — classification only / observe.** Add the classifier to
   your workflow and log `CI_TIER` for every run. Nothing is skipped yet.
2. **Phase 2 — enable safe tiers per surface.** Once the observed
   classifications match your expectations, guard each heavy step with
   its own tier: `docs_fast` may skip any heavy surface; `package_docs`
   may skip the core test matrix but must still run package validation.
   `control_plane` stays disabled (empty `control_plane_eligible`):
   activate it only after implementing and reviewing a dedicated
   conservative control-plane validation surface, populating the
   eligible list, gating the FULL surfaces, and shadow-observing first.
3. **Phase 3 — enable post-merge FULL reuse.** Only after phases 1–2 are
   stable, add the attestation creation step and the post-merge reuse
   proof.

See [docs/adoption.md](docs/adoption.md) for the full guide.

## Documentation

- [docs/architecture.md](docs/architecture.md) — classifier boundary,
  config, evidence producer/consumer, GitHub API, workflow guards,
  exact-tree model
- [docs/configuration.md](docs/configuration.md) — full config schema
  reference
- [docs/security-model.md](docs/security-model.md) — trust boundary and
  attack/failure cases
- [docs/evidence-model.md](docs/evidence-model.md) — why tree equality,
  not commit equality, is the core proof
- [docs/adoption.md](docs/adoption.md) — staged adoption guide
- [docs/non-goals.md](docs/non-goals.md) — what v0.1.0 explicitly does
  not support
- [templates/github-actions/ci.yml](templates/github-actions/ci.yml) —
  downstream workflow template
- [examples/python-repository/](examples/python-repository/) — example
  config for a Python repository

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 M0DIAN.
