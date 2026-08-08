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
