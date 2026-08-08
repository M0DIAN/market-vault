# MarketVault v0.6.1 CI and Package Auditability

Baseline:
33d7f5856bf060527ccf4d2ab679df4429009ce6

Package:
0.6.0

Stage:
v0.6.1 PR-3

Purpose:
CI/package auditability + maintenance hardening

PR-3 is strictly CI/package auditability plus maintenance hardening. No
product capability is added; no production source file changes; identity,
schema, contract, CLI, artifact format, dependencies, and the package
version are all unchanged.

## A. Normal CI matrix

The normal test matrix stays exactly Python 3.11 + 3.14 with
`fail-fast: false`. No third normal Python version is added and no matrix
reshaping is done.

## B. portability-pyarrow24

The `portability-pyarrow24` job stays: Python 3.11, the exact CI-only pin
`pyarrow==24.0.0`, the portability tests (`tests/test_v060_portability.py`),
the canonical reader regression, the Sample Generation frozen regression,
and the full offline pytest suite. The PyArrow runtime pin is CI-only and
never a project/runtime dependency change (`pyarrow>=16` stays unchanged).

## C. "writer" terminology correction

The stale PyArrow24 CI step wording "audited PyArrow 24.0.0 writer" /
"audited writer version" was corrected to compatibility-runtime
terminology: "Pin the audited PyArrow 24.0.0 compatibility runtime" /
"Assert the audited PyArrow compatibility version" / "Run audited PyArrow
24 compatibility tests". PyArrow is a compatibility runtime under audit,
not a writer in this repository; no command or test logic changed.

## D. GitHub Actions runtime

All Actions were moved off the stale Node-20-targeting majors:

- `actions/checkout@v6` (Node 24 runtime)
- `actions/setup-python@v6` (Node 24 runtime)
- `actions/upload-artifact@v7` (package artifact retention, Node-24-capable)

No compatibility environment variable (such as
`ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION`) is added and no warning is
suppressed: the stale runtime cause is removed, not hidden. The jobs keep
`runs-on: ubuntu-latest`; the observed GitHub-hosted runner (2.336.0) is
already newer than the Node-24 Action minimum, and no runner image is
pinned.

## E. Package audit chain

The package job keeps every existing validation gate (release checker,
example renderer help, `python -m build`, `twine check`, exactly one wheel
and one sdist, fresh-venv wheel install, the 9 formal help smokes, module /
metadata version, public API smoke, Catalog command-set smoke, wheel
contents hygiene). The audit chain then runs:

```text
build
→ twine
→ fresh wheel validation
→ wheel hygiene
→ SHA256SUMS.txt
→ local manifest verification
→ workflow artifact upload
→ artifact metadata/digest
→ later independent download
→ SHA256SUMS verification
```

The workflow artifact is retained only after all package validations
succeed, so a retained artifact always passed every package gate. The
package CI log must close the loop with the `V061_PACKAGE_AUDIT_OK`
marker after the artifact metadata is confirmed.

## F. Raw package file hashes vs GitHub artifact-digest

`SHA256SUMS.txt` records the SHA256 of the RAW wheel and RAW sdist bytes.
The `actions/upload-artifact` `artifact-digest` output is the digest of the
GitHub workflow artifact container/archive. These are different audit
layers: `artifact-digest` is never called a wheel hash, an sdist hash, or a
release asset hash, and it is never compared to either package-file SHA.

## G. Artifact naming

```text
market-vault-package-<commit>-attempt-<attempt>
```

i.e. `market-vault-package-${{ github.sha }}-attempt-${{ github.run_attempt }}`.
The name binds the source commit and the run attempt, so a rerun gets a
distinct attempt-bound artifact name instead of replacing a previous
artifact.

## H. Retention

Workflow artifacts are retained for 30 days (`retention-days: 30`).

## I. Overwrite

Artifact upload uses `overwrite: false`; no overwrite/replacement workflow
exists.

## Unchanged matrix

```text
production behavior unchanged
identity unchanged
schema unchanged
formal contracts unchanged
CLI unchanged
dependencies unchanged
version stays 0.6.0
runtime pyarrow remains >=16
no release publication
```

The retained PR-3 workflow artifact is a CI audit artifact — not a GitHub
Release asset, not a PyPI artifact, and not formal v0.6.1 release bytes.
Formal release assets must come from the exact future v0.6.1 release
commit after PR-4.
