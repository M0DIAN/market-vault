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

Final release-contract pins (phase 3):

- exact minimum read-only permission set (contents/pull-requests/actions,
  read only) in BOTH workflows — no write permissions anywhere
- tier semantics are per-surface: the test job's full-matrix guard MAY
  skip package_docs; the package job's heavy guard MUST NOT (package_docs
  still runs package validation)
- PACKAGE_DOCS_* marker steps make the tier semantics visible in logs
- example configs default control_plane_eligible = [] (opt-in, disabled)
- the template claims NO generic control-plane fast surface
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


def permissions_block(text: str) -> list[str]:
    """The exact lines under the top-level "permissions:" key."""
    _, rest = text.split("permissions:", 1)
    lines: list[str] = []
    for line in rest.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith((" ", "\t")):
            break  # next top-level key
        lines.append(stripped)
    return lines


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


# ---------------------------------------------------------------------------
# §1: exact minimum read-only permission set in BOTH workflows.
# ---------------------------------------------------------------------------


def test_exact_read_only_permission_set_in_both_workflows() -> None:
    for name, text in workflows().items():
        perms = permissions_block(text)
        assert perms == ["contents: read", "pull-requests: read", "actions: read"], (
            f"{name}: expected the exact minimum read-only permission set, "
            f"got {perms!r}"
        )


def test_no_write_permissions_anywhere() -> None:
    for name, text in workflows().items():
        for line in permissions_block(text):
            assert "write" not in line, f"{name}: write permission present"


# ---------------------------------------------------------------------------
# §2: tier semantics are per-surface (package_docs never skips the
# package surface; the test surface may skip it).
# ---------------------------------------------------------------------------


def test_test_job_heavy_guard_may_skip_package_docs() -> None:
    # The full test matrix is unnecessary under a validated package_docs
    # tier: the test job's guard excludes docs_fast AND package_docs.
    for name, text in workflows().items():
        test_job = "\n".join(job_sections(text)["test"])
        assert "env.CI_TIER != 'docs_fast'" in test_job, name
        assert "env.CI_TIER != 'package_docs'" in test_job, name


def test_package_job_heavy_guard_runs_on_package_docs() -> None:
    # package_docs is package-metadata-sensitive (e.g. README): its change
    # MUST still run package validation. Only docs_fast may skip it.
    for name, text in workflows().items():
        package_job = "\n".join(job_sections(text)["package"])
        assert "env.CI_TIER != 'docs_fast'" in package_job, name
        assert "env.CI_TIER != 'package_docs'" not in package_job, (
            f"{name}: package heavy guard must NOT skip package_docs"
        )


def test_package_docs_marker_steps_present() -> None:
    for name, text in workflows().items():
        test_job = "\n".join(job_sections(text)["test"])
        package_job = "\n".join(job_sections(text)["package"])
        assert "PACKAGE_DOCS_TESTS_MAY_SKIP=true" in test_job, name
        assert "PACKAGE_DOCS_PACKAGE_VALIDATION_MUST_RUN=true" in package_job, name
        # Both markers are guarded by the package_docs tier itself.
        assert "env.CI_TIER == 'package_docs'" in test_job, name
        assert "env.CI_TIER == 'package_docs'" in package_job, name


# ---------------------------------------------------------------------------
# §4: control_plane_eligible is OPT-IN — example configs default empty.
# ---------------------------------------------------------------------------


def test_example_configs_default_control_plane_eligible_empty() -> None:
    for path in (
        EXAMPLE_CONFIG,
        ROOT / "examples" / "python-repository" / "ciopt.toml",
    ):
        text = read_text(path)
        assert "control_plane_eligible = []" in text, path
        # The opt-in contract is documented in the config itself.
        assert "OPT-IN" in text, path


def test_template_claims_no_control_plane_fast_surface() -> None:
    # The generic template never claims a validated control-plane subset:
    # control_plane stays FULL until the downstream repo implements and
    # reviews its own conservative surface.
    template = read_text(WORKFLOWS["template"])
    assert "control_plane" not in template
