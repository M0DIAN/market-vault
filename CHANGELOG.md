# Changelog

All notable changes to the CI Optimization Framework are recorded here.

## [0.1.0] — 2026-08-18

Initial standalone release of the CI Optimization Framework.

**Provenance.** This version was extracted and generalized from the
production CI governance and optimization system developed for
MarketVault. Source extraction baseline:
[M0DIAN/market-vault](https://github.com/M0DIAN/market-vault) at
`99840349bdab4f0dc56a420bc66a1556750d1878`.

### Stable (production-proven contracts carried forward)

- Risk-tier classification (`docs_fast` / `package_docs` /
  `control_plane` / `full`), fully config-driven via `ciopt.toml`
  (schema version 1), fail-closed on unknown / unset / malformed input.
- Component impact model (`[components.*]`): additive metadata exposed
  separately from the tier; component impact alone never authorizes
  skipping validation.
- Exact-tree post-merge FULL reuse V1: the 8-condition proof contract
  (event shape, squash topology, exact associated PR, exact successful
  head run, exact configured formal job set, attempt-bound attestation,
  tree equivalence, control-plane exclusion) with the invariant
  `PROOF FAILURE != CI FAILURE`.
- Attempt-bound FULL attestation: deterministic JSON, stable key order,
  UTF-8, newline-terminated, exact schema, size caps, zip extraction
  safety, repository and run/attempt binding.
- Read-only GitHub REST adapter with minimal permissions
  (`contents: read`, `pull-requests: read`, `actions: read`); token
  never logged, stripped on cross-host redirect.
- Fail-closed GitHub Actions integration: a heavy surface may skip
  only when EITHER (1) that exact surface is explicitly unnecessary
  under a validated tier contract (`docs_fast` may skip any heavy
  surface; `package_docs` may skip the core matrix but must still run
  package validation; `control_plane` is OPT-IN and disabled by
  default), OR (2) `POST_MERGE_REUSE` is the exact literal `"true"`.
  Anything else runs.

### Not supported in v0.1.0

- Partial (per-surface) reuse V2
- PR-head reuse
- Generic test-impact-analysis claims
- Merge strategies outside the configured squash topology

See [docs/non-goals.md](docs/non-goals.md).
