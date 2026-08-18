# Non-goals

v0.1.0 is deliberately narrow. It carries forward only the
production-proven, fail-closed V1 contracts. The following are
explicitly **not supported** in v0.1.0:

- **Per-surface partial reuse is not supported in v0.1.0.** The V1
  contract is all-or-nothing: either the entire FULL evidence of a
  verified PR run is reused, or the FULL matrix runs. There is no
  middle ground where some surfaces are reused and others run.
- **PR-head reuse is not supported in v0.1.0.** The evidence model
  requires the exact push shape, squash topology, and tree equivalence
  on the configured main branch. Reusing evidence of a PR head without
  the merged-tree proof is outside the model.
- **No generic test-impact-analysis claim.** The framework classifies
  paths against an explicit, conservative config contract. It does not
  claim to predict which tests are affected by a change, and it never
  uses such a prediction to skip validation.
- **No guarantee for merge strategies outside the configured/proven
  topology.** The reuse proof assumes the single-commit squash push
  topology (one-parent commit whose parent is the push's `before`).
  Rebase merges, merge commits, multi-commit pushes, fast-forward
  pushes of already-tested commits, and other strategies are not proven
  by V1 and simply run FULL.

Project-specific compatibility surfaces (e.g. pinned dependency
versions, platform-specific test surfaces, packaging contracts) are not
part of the framework. They should be integrated as downstream
commands and jobs in the consuming repository's own workflow, guarded
by the framework's tier and reuse markers.

The framework also does not:

- run or manage tests (it only classifies and proves);
- publish packages or create releases;
- grant any write permission to GitHub API tokens;
- make network requests from the classifier (it is offline by design).
