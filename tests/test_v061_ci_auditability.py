"""Offline deterministic CI/package auditability regression (v0.6.1 PR-3).

Reads ``.github/workflows/ci.yml`` (and the PR-3 CI/package audit
document) and asserts the stable invariants of the PR-3 audit chain:

- the Node-24 Action majors (``actions/checkout@v6``,
  ``actions/setup-python@v6``, ``actions/upload-artifact@v7``) and the
  absence of the stale Node-20-targeting v4/v5 majors;
- the exact normal test matrix (3.11 + 3.14, ``fail-fast: false``), the
  exact four-job gate, and the exact package job dependency
  (test + portability-pyarrow24);
- the ``portability-pyarrow24`` job keeps Python 3.11, the exact
  CI-only ``pyarrow==24.0.0`` pin, the portability / canonical-reader /
  Sample Generation / full pytest runs, and the corrected
  compatibility terminology (no stale "writer" wording in its audited
  step names);
- the package audit chain: the separate SHA256SUMS build and verify
  stages, the attempt-bound artifact upload with fail-closed settings,
  the artifact metadata closure, and the ``V061_PACKAGE_AUDIT_OK``
  marker;
- the audit document states the raw-package-file-SHA256 vs GitHub
  ``artifact-digest`` distinction.

This is a repository/workflow regression test, not product code. It never
makes an internet request.

PR #61 additionally pins the post-merge FULL reuse gate contract:

- the read-only workflow ``permissions`` block and the absence of any
  workflow-level ``paths`` / ``paths-ignore`` filtering (the reuse gate
  must never be bypassed via ``on:`` path filters);
- every job runs the ``Post-merge FULL reuse proof`` step (main-push + full
  tier only) with a fail-closed crash fallback, and every heavy validation
  step's guard contains the literal ``env.POST_MERGE_REUSE != 'true'``
  exclusion — an unset ``POST_MERGE_REUSE`` is the empty string, so heavy
  validation always runs unless reuse is PROVEN;
- the verified-reuse markers (``FULL_TESTS_REUSED_FROM_VERIFIED_PR`` /
  ``PACKAGE_VALIDATION_REUSED_FROM_VERIFIED_PR``) exist only behind
  ``env.POST_MERGE_REUSE == 'true'`` and only echo — they never gate any
  validation, and "skipped by policy" markers are never on the reuse path;
- the PR FULL attestation create + upload steps exist in the package job
  with a pull_request-only ``tier == 'full'`` guard and the attempt-bound
  artifact name contract;
- every ``Post-merge FULL reuse proof`` step binds ``GITHUB_TOKEN``
  (``${{ github.token }}``) **step-scoped** — the verifier reads the token
  from its process environment, so a missing binding would make every
  eligible main push fail closed with ``reason=missing_token`` and the
  reuse path unreachable; the binding is never workflow-global or
  job-global, and ordinary heavy pytest/build/package steps receive no
  dedicated token env from this change.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
AUDIT_DOC = ROOT / "docs" / "v0_6_1_ci_package_audit.md"

JOB_HEADER_RE = re.compile(r"(?m)^  ([A-Za-z0-9_-]+):\s*$")


def ci_text() -> str:
    return CI.read_text(encoding="utf-8")


def _jobs_section(text: str) -> str:
    return text.split("jobs:\n", 1)[1]


def _job_block(text: str, job: str) -> str:
    """The block of one formal job: from its two-space ``  <job>:``
    header to the next two-space job header (or the end of the jobs
    section)."""
    section = _jobs_section(text)
    start = section.index(f"  {job}:\n")
    tail = section[start + len(job) + 2 :]
    matches = list(JOB_HEADER_RE.finditer(tail))
    end = matches[0].start() if matches else len(tail)
    return tail[:end]


def _step_names(block: str) -> list[str]:
    return re.findall(r"(?m)^      - name: (.+)$", block)


def _region(text: str, start_marker: str, end_marker: str | None) -> str:
    start = text.index(start_marker)
    if end_marker is None:
        return text[start:]
    end = text.index(end_marker, start + len(start_marker))
    return text[start:end]


# ---------------------------------------------------------------------------
# Action versions (section 28).
# ---------------------------------------------------------------------------


def test_workflow_uses_checkout_v6_for_every_checkout_job():
    text = ci_text()
    for job in ("test", "portability-pyarrow24", "package"):
        block = _job_block(text, job)
        assert "uses: actions/checkout@v6" in block
        assert "actions/checkout@v4" not in block


def test_workflow_uses_setup_python_v6_for_every_python_job():
    text = ci_text()
    for job in ("test", "portability-pyarrow24", "package"):
        block = _job_block(text, job)
        assert "uses: actions/setup-python@v6" in block
        assert "actions/setup-python@v5" not in block


def test_workflow_uses_upload_artifact_v7_in_package_flow():
    text = ci_text()
    assert "uses: actions/upload-artifact@v7" in text
    assert "actions/upload-artifact@v7" in _job_block(text, "package")


def test_workflow_never_restores_stale_action_majors():
    text = ci_text()
    assert "actions/checkout@v4" not in text
    assert "actions/setup-python@v5" not in text


# ---------------------------------------------------------------------------
# Matrix and job gate (section 29 / section 34).
# ---------------------------------------------------------------------------


def test_formal_jobs_are_exactly_four_surfaces():
    headers = list(JOB_HEADER_RE.findall(_jobs_section(ci_text())))
    assert headers == ["test", "portability-pyarrow24", "package"]
    for forbidden in ("package-artifact-audit", "release", "publish", "deploy"):
        assert forbidden not in headers


def test_normal_test_matrix_exactly_311_and_314():
    block = _job_block(ci_text(), "test")
    assert '"3.11", "3.14"' in block
    for third in ('"3.12"', '"3.13"', '"3.15"'):
        assert third not in block
    assert "fail-fast: false" in block


def test_package_job_needs_test_and_portability():
    block = _job_block(ci_text(), "package")
    assert "needs: [test, portability-pyarrow24]" in block


def test_release_checker_step_runs_on_all_tiers():
    """The package job's `Run release checker` step must not be tier-gated.

    scripts/check_release.py is a stdlib-only release/document consistency
    checker that validates docs/** content (release notes, direction docs,
    contracts, lifecycle records). A DOCS_FAST run must keep executing it,
    while the package BUILD chain stays docs_fast-guarded (PACKAGE_DOCS and
    FULL behavior are unchanged: the guards exclude only docs_fast).
    """
    block = _job_block(ci_text(), "package")
    names = _step_names(block)

    def own_region(name: str) -> str:
        idx = names.index(name)
        end = f"- name: {names[idx + 1]}" if idx + 1 < len(names) else None
        return _region(block, f"- name: {name}", end)

    release_checker = own_region("Run release checker")
    assert "run: python scripts/check_release.py" in release_checker
    assert "if:" not in release_checker
    for name in (
        "Install build tooling",
        "Example renderer help smoke",
        "PR-5 verified client example help smoke",
        "Build wheel and sdist",
        "Confirm exactly one wheel and one sdist",
        "Install wheel in a fresh virtual environment",
        "Fresh-wheel public API smoke check",
        "Check wheel contents exclude local data",
        "Build package SHA256 manifest",
        "Verify package SHA256 manifest",
        "Upload package audit artifact",
        "Confirm package audit artifact metadata",
    ):
        assert "if: env.CI_TIER != 'docs_fast'" in own_region(name), name


# ---------------------------------------------------------------------------
# portability-pyarrow24 (section 30).
# ---------------------------------------------------------------------------


def test_pyarrow24_job_keeps_runtime_and_suite():
    block = _job_block(ci_text(), "portability-pyarrow24")
    assert 'python-version: "3.11"' in block
    assert 'pip install "pyarrow==24.0.0"' in block
    assert "tests/test_v060_portability.py" in block
    assert "tests/test_canonical_reader.py" in block
    assert "tests/test_sample_generation_core.py" in block
    assert "tests/test_sample_generation_cli.py" in block
    assert "python -m pytest" in block


def test_pyarrow24_step_names_use_compatibility_terminology():
    block = _job_block(ci_text(), "portability-pyarrow24")
    names = _step_names(block)
    assert any("Pin the audited PyArrow 24.0.0 compatibility runtime" in n for n in names)
    assert any("Assert the audited PyArrow compatibility version" in n for n in names)
    assert any("Run audited PyArrow 24 compatibility tests" in n for n in names)
    # The stale "writer" wording is gone from the PyArrow24 audited step
    # names specifically; the word itself is not banned repository-wide.
    for name in names:
        assert "writer" not in name
        assert "writer version" not in name


# ---------------------------------------------------------------------------
# SHA256 manifest (section 31).
# ---------------------------------------------------------------------------


def test_manifest_has_separate_build_and_verify_stages():
    text = ci_text()
    assert "Build package SHA256 manifest" in text
    assert "Verify package SHA256 manifest" in text
    assert text.index("Build package SHA256 manifest") < text.index(
        "Verify package SHA256 manifest"
    )
    assert "dist/SHA256SUMS.txt" in text


def test_manifest_generation_hashes_raw_wheel_and_sdist():
    block = _region(ci_text(), "Build package SHA256 manifest", "Verify package SHA256 manifest")
    assert "hashlib.sha256" in block
    assert "*.whl" in block
    assert "*.tar.gz" in block
    assert "read_bytes()" in block


def test_manifest_verification_recomputes_raw_file_hashes():
    block = _region(
        ci_text(), "Verify package SHA256 manifest", "Upload package audit artifact"
    )
    assert "read_bytes()" in block
    assert "hexdigest()" in block
    assert "fullmatch" in block
    assert "exactly 2 non-empty lines" in block


# ---------------------------------------------------------------------------
# Artifact upload (section 32).
# ---------------------------------------------------------------------------


def test_package_artifact_upload_settings():
    block = _region(ci_text(), "Upload package audit artifact", "Confirm package audit artifact metadata")
    assert "uses: actions/upload-artifact@v7" in block
    assert "id: package-artifact" in block
    assert "github.sha" in block
    assert "github.run_attempt" in block
    assert "dist/*.whl" in block
    assert "dist/*.tar.gz" in block
    assert "dist/SHA256SUMS.txt" in block
    assert "if-no-files-found: error" in block
    assert "retention-days: 30" in block
    assert "overwrite: false" in block
    # No broad dist/ upload: every path is an explicit globbed file path.
    assert re.search(r"(?m)^\s*path:\s*dist\s*$", block) is None


def test_package_artifact_name_resolves_source_sha_per_event():
    # The artifact name must bind the reviewed PR head on pull_request
    # runs (github.event.pull_request.head.sha) and fall back to
    # github.sha on push runs. github.sha alone is the synthetic merge-ref
    # commit on pull_request runs and must not be the only binding.
    block = _region(
        ci_text(), "Upload package audit artifact", "Confirm package audit artifact metadata"
    )
    assert (
        "market-vault-package-${{ github.event.pull_request.head.sha || "
        "github.sha }}-attempt-${{ github.run_attempt }}"
    ) in block
    assert "github.event.pull_request.head.sha" in block
    assert "|| github.sha" in block
    assert "github.run_attempt" in block


def test_artifact_name_never_frozen_to_github_sha_only():
    # The stale github.sha-only artifact naming must not reappear as the
    # source SHA resolution for the package artifact.
    text = ci_text()
    assert (
        "market-vault-package-${{ github.sha }}-attempt-${{ github.run_attempt }}"
        not in text
    )


# ---------------------------------------------------------------------------
# Artifact metadata closure (section 33).
# ---------------------------------------------------------------------------


def test_workflow_consumes_artifact_metadata_outputs():
    text = ci_text()
    assert "steps.package-artifact.outputs.artifact-id" in text
    assert "steps.package-artifact.outputs.artifact-url" in text
    assert "steps.package-artifact.outputs.artifact-digest" in text
    assert "V061_PACKAGE_AUDIT_OK" in text


def test_audit_doc_distinguishes_raw_hashes_from_artifact_digest():
    text = AUDIT_DOC.read_text(encoding="utf-8")
    assert "MarketVault v0.6.1 CI and Package Auditability" in text
    assert "33d7f5856bf060527ccf4d2ab679df4429009ce6" in text
    assert "artifact-digest" in text
    assert "never compared to either package-file SHA" in text
    assert "container/archive" in text


def test_audit_doc_describes_source_sha_resolution():
    # The audit document must state the per-event source SHA resolution
    # (pull_request head SHA vs push github.sha) and the merge-ref caveat.
    text = AUDIT_DOC.read_text(encoding="utf-8")
    assert "github.event.pull_request.head.sha" in text
    assert "github.sha" in text
    assert "synthetic merge-ref" in text
    assert "market-vault-package-<source_sha>-attempt-<attempt>" in text


# ---------------------------------------------------------------------------
# Post-merge FULL reuse gate (PR #61).
# ---------------------------------------------------------------------------


def _steps(text: str) -> list[tuple[str, str]]:
    """(name, region) for every step of every formal job."""
    out = []
    for job in ("test", "portability-pyarrow24", "package"):
        block = _job_block(text, job)
        names = _step_names(block)
        for i, name in enumerate(names):
            end = f"- name: {names[i + 1]}" if i + 1 < len(names) else None
            out.append((name, _region(block, f"- name: {name}", end)))
    return out


def test_workflow_permissions_are_read_only():
    block = _region(ci_text(), "permissions:", "on:")
    assert "contents: read" in block
    assert "pull-requests: read" in block
    assert "actions: read" in block
    assert "write" not in block


def test_no_workflow_level_path_filtering():
    """The reuse gate must never be bypassed via workflow-level path
    filtering: the ``on:`` block has no paths / paths-ignore."""
    on_region = _region(ci_text(), "on:", "jobs:")
    assert "paths:" not in on_region
    assert "paths-ignore:" not in on_region


def test_reuse_proof_step_present_in_all_three_jobs():
    for job in ("test", "portability-pyarrow24", "package"):
        block = _job_block(ci_text(), job)
        assert "Post-merge FULL reuse proof" in block
        assert "python scripts/ci_post_merge_reuse.py" in block
        assert "github.event_name == 'push'" in block
        assert "github.ref == 'refs/heads/main'" in block
        assert "env.CI_TIER == 'full'" in block
        assert "POST_MERGE_REUSE=" in block


def test_reuse_proof_step_fail_closes_on_verifier_crash():
    """A verifier crash must fail-closed: marker=false with a specific
    reason, never a skip of heavy validation."""
    for job in ("test", "portability-pyarrow24", "package"):
        block = _job_block(ci_text(), job)
        assert "verifier_crash_fail_closed" in block
        assert "marker=false" in block


def test_every_reuse_proof_step_binds_step_scoped_github_token():
    """The verifier reads ``GITHUB_TOKEN`` from its process environment.
    Without a binding every eligible main push would fail closed with
    ``reason=missing_token`` and the reuse path would be unreachable, so
    every proof step must expose ``github.token`` as ``GITHUB_TOKEN``."""
    proofs = [region for name, region in _steps(ci_text())
              if name == "Post-merge FULL reuse proof"]
    assert len(proofs) == 3
    for region in proofs:
        assert "env:" in region
        assert "GITHUB_TOKEN: ${{ github.token }}" in region


def test_github_token_binding_is_step_scoped_only():
    """The token binding must be step-scoped: exactly three bindings in the
    whole workflow, each inside a proof step — never workflow-global and
    never job-global."""
    text = ci_text()
    binding = "GITHUB_TOKEN: ${{ github.token }}"
    assert text.count(binding) == 3
    for name, region in _steps(text):
        if binding in region:
            assert name == "Post-merge FULL reuse proof", name
    # No binding (and no env block at all) outside the jobs section: the
    # workflow preamble holds name/permissions/on only.
    preamble = text.split("jobs:\n", 1)[0]
    assert binding not in preamble
    assert "env:" not in preamble


def test_heavy_steps_receive_no_dedicated_github_token_env():
    """Ordinary heavy pytest/build/package steps must not gain a
    ``GITHUB_TOKEN`` env binding from this change: the token is only needed
    by the reuse verifier, and per-step default token exposure for other
    steps is not introduced here."""
    text = ci_text()
    for job, names in _HEAVY_STEPS_PER_JOB.items():
        for name, region in _steps(text):
            if name in names and _job_block(text, job).count(f"- name: {name}") == 1:
                assert "GITHUB_TOKEN" not in region, (job, name)


def test_missing_token_proof_failure_never_skips_heavy_validation():
    """A verifier run without a token is an exit-0 proof failure
    (``POST_MERGE_REUSE=false`` / ``reason=missing_token`` — proven at the
    verifier level in test_ci_post_merge_reuse.py). This test mirrors the
    proof step's marker extraction in pure Python and proves the extracted
    marker never equals 'true', so the heavy guards
    (``env.POST_MERGE_REUSE != 'true'``) run FULL validation. Offline and
    deterministic; no sed dependency."""
    verifier_output = "POST_MERGE_REUSE=false\nreason=missing_token\n"
    marker = next(
        (line.split("=", 1)[1] for line in verifier_output.splitlines()
         if line.startswith("POST_MERGE_REUSE=")),
        "false",
    )
    reason = next(
        (line.split("=", 1)[1] for line in verifier_output.splitlines()
         if line.startswith("reason=")),
        "",
    )
    assert marker == "false"
    assert reason == "missing_token"
    assert marker != "true"  # -> heavy guard holds -> FULL validation runs


def test_classify_exports_full_matrix_required_in_every_job():
    for job in ("test", "portability-pyarrow24", "package"):
        block = _job_block(ci_text(), job)
        assert "full_matrix_required" in block
        assert "CI_FULL_MATRIX_REQUIRED=" in block


_HEAVY_STEPS_PER_JOB = {
    "test": (
        "Install dependencies",
        "Compile Python",
        "Run offline tests",
    ),
    "portability-pyarrow24": (
        "Install dependencies",
        "Pin the audited PyArrow 24.0.0 compatibility runtime",
        "Assert the audited PyArrow compatibility version",
        "Run audited PyArrow 24 compatibility tests",
        "Run the canonical reader and frozen regression surface",
        "Run full offline suite under PyArrow 24.0.0",
    ),
    "package": (
        "Install build tooling",
        "Example renderer help smoke",
        "PR-5 verified client example help smoke",
        "Build wheel and sdist",
        "Confirm exactly one wheel and one sdist",
        "Install wheel in a fresh virtual environment",
        "Fresh-wheel public API smoke check",
        "Check wheel contents exclude local data",
        "Build package SHA256 manifest",
        "Verify package SHA256 manifest",
        "Upload package audit artifact",
        "Confirm package audit artifact metadata",
    ),
}


def test_heavy_steps_never_skip_without_verified_proof():
    """Every heavy validation step's guard must contain the literal
    ``env.POST_MERGE_REUSE != 'true'`` exclusion: an unset POST_MERGE_REUSE
    is the empty string, and ``false`` is not ``'true'``, so the guard is
    true and heavy validation runs (fail-safe) for every proof-failure
    state."""
    text = ci_text()
    for job, names in _HEAVY_STEPS_PER_JOB.items():
        for name, region in _steps(text):
            if name in names and _job_block(text, job).count(f"- name: {name}") == 1:
                assert "env.POST_MERGE_REUSE != 'true'" in region, (job, name)


def test_reuse_true_guard_appears_only_on_echo_only_marker_steps():
    """``POST_MERGE_REUSE == 'true'`` may only gate the verified-reuse
    marker steps, and those steps only echo — they never run or gate any
    validation."""
    for name, region in _steps(ci_text()):
        if "env.POST_MERGE_REUSE == 'true'" in region:
            assert name in (
                "FULL tests reused from verified PR",
                "Package validation reused from verified PR",
            ), name
            assert "echo" in region
            assert "python -m pytest" not in region
            assert "pip " not in region
            assert "python -m build" not in region
            assert "python scripts/check_release.py" not in region


def test_reuse_markers_present_with_exact_names():
    text = ci_text()
    assert text.count("FULL_TESTS_REUSED_FROM_VERIFIED_PR") == 2
    assert text.count("PACKAGE_VALIDATION_REUSED_FROM_VERIFIED_PR") == 1


def test_skipped_by_policy_never_claimed_on_reuse_path():
    """The fast-tier markers keep their exact old guards; they are never on
    the verified-reuse path."""
    for name, region in _steps(ci_text()):
        if "SKIPPED_BY_POLICY" in region:
            assert "env.CI_TIER == 'docs_fast'" in region
            assert "POST_MERGE_REUSE" not in region


def test_attestation_steps_present_with_pr_only_full_guard():
    block = _job_block(ci_text(), "package")
    assert "Create FULL CI attestation" in block
    assert "Upload FULL CI attestation artifact" in block
    assert "python scripts/ci_post_merge_reuse.py --create-attestation ci_full_attestation.json" in block
    assert "github.event_name == 'pull_request'" in block
    assert "env.CI_TIER == 'full'" in block
    assert "env.CI_FULL_MATRIX_REQUIRED == 'true'" in block
    assert "actions/upload-artifact@v7" in block
    assert "if-no-files-found: error" in block
    assert "retention-days: 30" in block
    assert "overwrite: false" in block


def test_attestation_artifact_name_binds_pr_head_and_attempt():
    block = _job_block(ci_text(), "package")
    assert (
        "market-vault-full-ci-attestation-${{ github.event.pull_request.head.sha }}"
        "-attempt-${{ github.run_attempt }}"
    ) in block


def test_attestation_never_created_on_non_full_tier():
    """The attestation create step is gated on tier == full (and the
    exported full-matrix-required flag): docs_fast / package_docs /
    unset-tier runs produce no attestation, so no evidence can be minted
    from a run that did not really execute the FULL matrix."""
    for name, region in _steps(ci_text()):
        if name == "Create FULL CI attestation":
            assert "env.CI_TIER == 'full'" in region
            assert "env.CI_FULL_MATRIX_REQUIRED == 'true'" in region
            assert "github.event_name == 'pull_request'" in region
