"""Deterministic text-level contract tests for BOTH workflow files: the
framework self-CI (.github/workflows/ci.yml) and the downstream template
(templates/github-actions/ci.yml). No YAML parsing — the pins inspect the
exact bytes so a regression in any fail-closed guard is caught.

The pins (§10 of the export integration contract):

- fetch-depth: 0 on every checkout; preferred action majors (@v6/@v7)
- event-aware classifier invocation (PR -> base/head/pull_request mode,
  push -> before/sha/push mode); never a hardcoded --mode pull_request
- --output github-env only (no raw classifier env/json dump into GITHUB_ENV)
- classifier fail-closed wrapper (classifier_error_fail_closed)
- V1 reuse proof before every heavy surface, in every formal job
- heavy surfaces guarded by the exact literal env.POST_MERGE_REUSE != 'true'
- verifier crash fallback (verifier_crash_fail_closed)
- no invalid "| default(" expression; hardcoded attestation artifact name
  matching config artifact_prefix
- no unqualified PyPI install claim
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WORKFLOWS: dict[str, Path] = {
    "self-ci": ROOT / ".github" / "workflows" / "ci.yml",
    "template": ROOT / "templates" / "github-actions" / "ci.yml",
}
EXAMPLE_CONFIG = ROOT / "ciopt.example.toml"

# Top-level job keys are the only 2-space-indented scalar keys in either
# workflow ("on:", "permissions:", "jobs:" sit at column 0).
_JOB_HEADER = re.compile(r"^  [a-z][a-z0-9_-]*:$")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def job_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    in_jobs = False
    for line in text.splitlines():
        if line == "jobs:":
            in_jobs = True
            continue
        # Trigger keys ("push:" / "pull_request:" under "on:") also sit at
        # 2-space indent, but only the keys after "jobs:" are jobs.
        if in_jobs and _JOB_HEADER.match(line):
            current = line.strip()[:-1]
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def workflows() -> dict[str, str]:
    return {name: read_text(path) for name, path in WORKFLOWS.items()}


# ---------------------------------------------------------------------------
# §1: checkout contract and action majors.
# ---------------------------------------------------------------------------


def test_every_checkout_fetch_depth_zero() -> None:
    for name, text in workflows().items():
        assert text.count("actions/checkout@v6") >= 1, name
        assert text.count("fetch-depth: 0") >= text.count("actions/checkout@v6"), name
        assert "fetch-depth: 0" in text, name


def test_preferred_action_majors_only() -> None:
    for name, text in workflows().items():
        assert "actions/checkout@v6" in text, name
        assert "actions/setup-python@v6" in text, name
        assert "actions/upload-artifact@v7" in text, name
        for stale in ("checkout@v4", "checkout@v5",
                      "setup-python@v4", "setup-python@v5",
                      "upload-artifact@v4", "upload-artifact@v5",
                      "upload-artifact@v6"):
            assert stale not in text, f"{name} still pins {stale}"


# ---------------------------------------------------------------------------
# §2: event-aware classification.
# ---------------------------------------------------------------------------


def test_classifier_is_event_aware() -> None:
    for name, text in workflows().items():
        assert "github.event.pull_request && 'pull_request' || 'push'" in text, name
        assert "github.event.pull_request.base.sha" in text, name
        assert "github.event.pull_request.head.sha" in text, name
        assert "github.event.before" in text, name
        # The classifier is invoked with the exact resolved MODE/BASE/HEAD;
        # never a hardcoded pull_request mode.
        assert '--mode "$CI_EVENT"' in text, name
        assert "--mode pull_request" not in text, name


# ---------------------------------------------------------------------------
# §3: github-env output contract.
# ---------------------------------------------------------------------------


def test_classifier_uses_github_env_output_only() -> None:
    for name, text in workflows().items():
        assert "--output github-env" in text, name
        # No raw classifier dump (json or env renderer) into GITHUB_ENV.
        assert "--output env" not in text, name
        assert "--output json" not in text, name
        assert "classify.env" in text, name
        assert 'cat classify.env >> "$GITHUB_ENV"' in text, name


def test_classifier_fail_closed_wrapper_exports_full() -> None:
    for name, text in workflows().items():
        assert 'echo "CI_TIER=full"' in text, name
        assert 'echo "CI_TIER_REASON=classifier_error_fail_closed"' in text, name
        assert 'echo "CI_FULL_MATRIX_REQUIRED=true"' in text, name


# ---------------------------------------------------------------------------
# §5/§4: per-job V1 reuse proof BEFORE heavy validation.
# ---------------------------------------------------------------------------


def test_every_job_has_proof_before_heavy_and_exact_literal_guard() -> None:
    for name, text in workflows().items():
        for job, lines in job_sections(text).items():
            joined = "\n".join(lines)
            assert "verify-reuse" in joined, f"{name}: {job} missing V1 proof"
            assert "POST_MERGE_REUSE != 'true'" in joined, f"{name}: {job} heavy guard"
            proof_at = joined.index("verify-reuse")
            guard_at = joined.index("POST_MERGE_REUSE != 'true'")
            assert proof_at < guard_at, (
                f"{name}: {job} must prove reuse BEFORE heavy validation"
            )
            # Marker steps (if present) come after the guarded heavy surface.
            if "POST_MERGE_REUSE == 'true'" in joined:
                assert joined.index("POST_MERGE_REUSE == 'true'") > guard_at, name


def test_heavy_guard_uses_exact_literal_in_every_job() -> None:
    for name, text in workflows().items():
        for job, lines in job_sections(text).items():
            joined = "\n".join(lines)
            assert "env.POST_MERGE_REUSE != 'true'" in joined, f"{name}: {job}"


# ---------------------------------------------------------------------------
# §7: verifier crash fail-close.
# ---------------------------------------------------------------------------


def test_verifier_crash_fail_closed_wrapper() -> None:
    for name, text in workflows().items():
        assert 'echo "POST_MERGE_REUSE=false"' in text, name
        assert 'echo "reason=verifier_crash_fail_closed"' in text, name
        assert "verify-reuse --config ciopt.toml > reuse.env 2>&1" in text, name
        assert 'cat reuse.env >> "$GITHUB_ENV"' in text, name


# ---------------------------------------------------------------------------
# §8: artifact naming — no invalid expression, hardcoded, matches prefix.
# ---------------------------------------------------------------------------


def test_no_invalid_default_expression_in_workflows() -> None:
    for name, text in workflows().items():
        assert "| default(" not in text, name
        assert "vars.CI_ATTESTATION_PREFIX" not in text, name


def test_attestation_artifact_name_matches_default_prefix() -> None:
    hardcoded = (
        "ci-full-attestation-${{ github.event.pull_request.head.sha }}"
        "-attempt-${{ github.run_attempt }}"
    )
    for name, text in workflows().items():
        assert hardcoded in text, name
    cfg = read_text(EXAMPLE_CONFIG)
    assert 'artifact_prefix = "ci-full-attestation-"' in cfg


# ---------------------------------------------------------------------------
# §9: no unqualified PyPI install claim.
# ---------------------------------------------------------------------------


def test_no_unqualified_pypi_install_in_workflows() -> None:
    for name, text in workflows().items():
        assert "pip install ci-optimization-framework" not in text, name


def test_template_pins_framework_from_git_source() -> None:
    template = read_text(WORKFLOWS["template"])
    assert "git+https://github.com/<OWNER>/<FRAMEWORK_REPO>.git@<TAG>" in template


# ---------------------------------------------------------------------------
# Self-CI specifics (§11).
# ---------------------------------------------------------------------------


def test_self_ci_jobs_and_gates() -> None:
    self_ci = read_text(WORKFLOWS["self-ci"])
    jobs = job_sections(self_ci)
    assert set(jobs) == {"test", "package"}
    assert "python -m compileall -q src tests" in self_ci
    assert "python -m pytest -q" in self_ci
    # Self-CI installs the framework itself (editable dev), not from PyPI.
    assert 'python -m pip install -e ".[dev]"' in self_ci
