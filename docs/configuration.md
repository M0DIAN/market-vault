# Configuration

One file — `ciopt.toml` by convention — carries every project-specific
assumption. Start from `ciopt.example.toml` in the repository root.
Parsing is strict, deterministic, and fail-closed: no `eval`, no shell
interpolation; a malformed config is an error, and the CLI converts it
to `tier=full` / `reuse=false`.

## Schema version

```toml
schema_version = 1
```

Required and must equal `1`. A future incompatible schema bumps this
value; an unknown version fails closed.

## `[repository]`

| key | default | meaning |
| --- | --- | --- |
| `main_branch` | `"main"` | branch name the post-merge reuse proof applies to (`refs/heads/<main_branch>`) |
| `workflow_name` | `"CI"` | name of the CI workflow (must match the workflow's `name:` and the attestation's `workflow` field) |
| `workflow_path` | `".github/workflows/ci.yml"` | workflow file path used to identify matching runs |

## `[paths]`

| key | default | meaning |
| --- | --- | --- |
| `docs` | `["docs/"]` | docs scope: changes limited to these paths classify `docs_fast` |
| `package_docs` | `["README.md"]` | package-metadata docs: a change limited to these plus `docs` classifies `package_docs` |
| `control_plane` | *required* | control-plane surface: mutating any of these forces FULL (reported as `shared_changed`) |
| `control_plane_eligible` | `[workflow_path, config file]` | the exact fast-eligible subset that may classify `control_plane` |

`control_plane` is required: a conservative default would silently make
control-plane mutations eligible for fast paths, which is never
acceptable. `control_plane_eligible` must be an exact allowlist —
anything outside it (including other control-plane paths) stays FULL.

Rules match exactly or by directory prefix (`"docs/"` matches
`docs/a.md`; `"ciopt.toml"` matches only that file). Trailing slashes
are ignored; there is no substring matching.

## `[components.*]`

```toml
[components.core]
paths = ["src/"]
requires_full = true

[components.package]
paths = ["pyproject.toml", "README.md"]
requires_package = true
```

| key | meaning |
| --- | --- |
| `paths` | non-empty list of path rules for this component |
| `requires_full` | this component's changes always require the full matrix (impact: `core_changed`) |
| `requires_package` | this component's changes are package-sensitive (impact: `package_changed`) |

Component names must match `[a-z0-9_-]+`. Impact is additive metadata
exposed separately from the tier and **never authorizes skipping
validation**: every registered-component change still classifies FULL
until the project registers an explicit validated validation contract.

## `[reuse]`

| key | default | meaning |
| --- | --- | --- |
| `enabled` | `true` | whether the V1 reuse proof is active |
| `required_jobs` | — (required when enabled) | the exact formal job set of the workflow; the PR run must terminate SUCCESS on exactly these jobs |
| `control_plane_paths` | `[paths].control_plane` | merged changes touching any of these deny reuse |
| `artifact_prefix` | `"ci-full-attestation-"` | attestation artifact name prefix (`<prefix><head_sha>-attempt-<run_attempt>`) |

`required_jobs` must be in exact sync with your workflow's job names
(including matrix leg names such as `"test (3.11)"`). A missing,
duplicate, or extra job in the PR run denies reuse.

## Fail-closed behavior

- missing file, unparseable TOML, wrong types ⇒ `ConfigError`
- `schema_version` missing or not `1` ⇒ `ConfigError`
- unknown tables or keys ⇒ `ConfigError` (deterministic: typo'd keys
  never silently change behavior)
- missing `[paths].control_plane` ⇒ `ConfigError`
- `reuse.enabled = true` without `required_jobs` ⇒ `ConfigError`
- `classify` converts any `ConfigError` to `tier=full`,
  `reason=invalid_config_fail_closed`, exit code 2
- `verify-reuse` converts any `ConfigError` to
  `POST_MERGE_REUSE=false`, `reason=invalid_config_fail_closed`
  (never a CI failure — the workflow then runs FULL)
