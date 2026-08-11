"""Offline regression tests for the CI post-merge FULL reuse gate.

Tests ``scripts/ci_post_merge_reuse.py`` (PR #61): the pure verification
core, the thin read-only GitHub API adapter (GitHub HTTP is mocked, never
contacted), the git wrapper (faked), the attestation creation contract, and
the fail-safe invariant that ``POST_MERGE_REUSE=false`` can never satisfy
the heavy-step skip predicate.

The suite never makes an internet request and never touches the
MarketVault repository itself (no git fixtures needed).
"""

from __future__ import annotations

import importlib.util
import io
import itertools
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = ROOT / "scripts" / "ci_post_merge_reuse.py"


def _load() -> "module":
    spec = importlib.util.spec_from_file_location("ci_post_merge_reuse", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reuse = _load()

BASE = "a" * 40
HEAD = "b" * 40
MAIN = "c" * 40
TREE = "d" * 40
MERGE = "f" * 40  # the PR run's synthetic merge commit (tested_merge_sha)
REPO = "M0DIAN/market-vault"
RUN_ID = 31352080511
ATTEMPT = 1
PR_NUMBER = 60


# ---------------------------------------------------------------------------
# Factory helpers (fully valid by default; tests override one thing).
# ---------------------------------------------------------------------------


def make_pr(**over: object) -> dict:
    pr = {
        "number": PR_NUMBER,
        "state": "closed",
        "merged_at": "2026-08-10T03:39:55Z",
        "merge_commit_sha": MAIN,
        "base": {"ref": "main", "sha": BASE},
        "head": {"sha": HEAD},
    }
    pr.update(over)
    return pr


def make_run(**over: object) -> dict:
    run = {
        "id": RUN_ID,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_sha": HEAD,
        "run_attempt": ATTEMPT,
        "created_at": "2026-08-10T03:15:13Z",
    }
    run.update(over)
    return run


def make_job(name: str, **over: object) -> dict:
    job = {"name": name, "status": "completed", "conclusion": "success"}
    job.update(over)
    return job


def make_all_jobs() -> list[dict]:
    return [make_job(surface) for surface in reuse.REQUIRED_JOB_SURFACES]


def make_artifact(**over: object) -> dict:
    artifact = {
        "id": 9049399458,
        "name": f"market-vault-full-ci-attestation-{HEAD}-attempt-{ATTEMPT}",
        "size_in_bytes": 600,
        "expired": False,
    }
    artifact.update(over)
    return artifact


def make_attestation(**over: object) -> dict:
    attestation = {
        "schema_version": 1,
        "repository": REPO,
        "workflow": "CI",
        "run_id": RUN_ID,
        "run_attempt": ATTEMPT,
        "pr_number": PR_NUMBER,
        "base_sha": BASE,
        "head_sha": HEAD,
        "tested_merge_sha": MERGE,
        "tested_tree_sha": TREE,
        "tier": "full",
        "full_matrix_required": True,
    }
    attestation.update(over)
    return attestation


def attestation_zip_bytes(data: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            reuse.ATTESTATION_FILENAME,
            json.dumps(data if data is not None else make_attestation()),
        )
    return buf.getvalue()


class FakeGit:
    """Fake read-only git wrapper; defaults to the valid squash shape."""

    def __init__(self, parents: tuple[str, ...] = (BASE,), tree: str = TREE,
                 changed: list[str] | tuple[str, ...] = ()):
        self.parents = list(parents)
        self.tree = tree
        self.changed = list(changed)
        self.calls: list[str] = []

    def rev_list_parents(self, sha: str) -> tuple[str, ...]:
        self.calls.append("rev_list")
        if sha != MAIN:
            raise reuse.GitError("git_commit_mismatch")
        return tuple(self.parents)

    def rev_parse_tree(self, sha: str) -> str:
        self.calls.append("rev_parse_tree")
        if sha != MAIN or not self.tree:
            raise reuse.GitError("git_tree_failed")
        return self.tree

    def changed_paths(self, base: str, head: str) -> list[str]:
        self.calls.append("changed_paths")
        return list(self.changed)


class FakeAPI:
    """Fake read-only GitHub API adapter; every method returns the fully
    valid default context unless overridden, or raises a canned APIError."""

    def __init__(
        self,
        *,
        prs: list[dict] | None = None,
        runs: list[dict] | None = None,
        jobs: list[dict] | None = None,
        artifacts: list[dict] | None = None,
        zip_bytes: bytes | None = None,
        jobs_by_run: dict[int, list[dict]] | None = None,
        artifacts_by_run: dict[int, list[dict]] | None = None,
        fail: str | None = None,
        raise_reason: str = "network_error",
    ):
        self.prs = [make_pr()] if prs is None else prs
        self.runs = [make_run()] if runs is None else runs
        self.jobs = make_all_jobs() if jobs is None else jobs
        self.artifacts = [make_artifact()] if artifacts is None else artifacts
        self.zip_bytes = (
            attestation_zip_bytes() if zip_bytes is None else zip_bytes
        )
        self.jobs_by_run = jobs_by_run
        self.artifacts_by_run = artifacts_by_run
        self.fail = fail
        self.raise_reason = raise_reason
        self.calls: list[str] = []

    def _maybe_fail(self, method: str) -> None:
        self.calls.append(method)
        if self.fail == method:
            raise reuse.APIError(self.raise_reason)

    def list_pulls_for_commit(self, sha: str) -> list[dict]:
        self._maybe_fail("pulls")
        return list(self.prs)

    def list_runs_for_head(self, sha: str) -> list[dict]:
        self._maybe_fail("runs")
        return list(self.runs)

    def list_jobs(self, run_id: int) -> list[dict]:
        self._maybe_fail("jobs")
        if self.jobs_by_run is not None:
            return list(self.jobs_by_run.get(run_id, []))
        return list(self.jobs)

    def list_artifacts(self, run_id: int) -> list[dict]:
        self._maybe_fail("artifacts")
        if self.artifacts_by_run is not None:
            return list(self.artifacts_by_run.get(run_id, []))
        return list(self.artifacts)

    def download_artifact(self, artifact_id: int) -> bytes:
        self._maybe_fail("download")
        return self.zip_bytes


def run_verifier(
    api_kwargs: dict | None = None,
    git_kwargs: dict | None = None,
    **shape: object,
) -> reuse.Verdict:
    """Run the full orchestrator with a fully valid context; override the
    event shape, the API fakes, or the git fakes as needed."""
    event = {
        "repository": REPO,
        "event_name": "push",
        "ref": reuse.MAIN_REF,
        "before_sha": BASE,
        "main_sha": MAIN,
    }
    event.update(shape)
    api = FakeAPI(**(api_kwargs or {}))
    git = FakeGit(**(git_kwargs or {}))
    return reuse.run_verifier(api=api, git=git, **event)


def marker_of(verdict: reuse.Verdict) -> str:
    """The POST_MERGE_REUSE value the workflow would parse from the log."""
    return render_verdict(verdict).splitlines()[0].split("=", 1)[1]


def render_verdict(verdict: reuse.Verdict) -> str:
    return reuse.render_verdict(verdict)


# ---------------------------------------------------------------------------
# Happy path + event shape (conditions 1).
# ---------------------------------------------------------------------------


def test_valid_single_parent_squash_reuse_accepted():
    v = run_verifier()
    assert v.reuse is True
    assert v.reason == reuse.REUSE_OK_REASON
    assert v.pr_number == PR_NUMBER
    assert v.pr_head_sha == HEAD
    assert v.pr_run_id == RUN_ID
    assert v.tested_merge_sha == MERGE
    assert v.tested_tree_sha == TREE
    assert v.main_sha == MAIN
    assert v.main_tree_sha == TREE
    assert marker_of(v) == "true"


def test_event_not_push_rejected():
    v = run_verifier(event_name="pull_request")
    assert v.reuse is False and v.reason == "event_not_push"


def test_wrong_ref_rejected():
    v = run_verifier(ref="refs/heads/feature/x")
    assert v.reuse is False and v.reason == "wrong_ref"


def test_missing_before_rejected():
    v = run_verifier(before_sha=None)
    assert v.reuse is False and v.reason == "missing_before"


def test_zero_before_rejected():
    v = run_verifier(before_sha=reuse.ZERO_SHA)
    assert v.reuse is False and v.reason == "missing_before"


def test_malformed_before_rejected():
    v = run_verifier(before_sha="not-a-sha")
    assert v.reuse is False and v.reason == "missing_before"


def test_missing_main_sha_rejected():
    v = run_verifier(main_sha=None)
    assert v.reuse is False and v.reason == "missing_main_sha"


# ---------------------------------------------------------------------------
# Commit topology (condition 2).
# ---------------------------------------------------------------------------


def test_parent_equals_before_accepted():
    v = run_verifier(git_kwargs={"parents": (BASE,)})
    assert v.reuse is True


def test_parent_mismatch_rejected():
    v = run_verifier(git_kwargs={"parents": (HEAD,)})
    assert v.reuse is False and v.reason == "topology_parent_mismatch"


def test_two_parent_merge_commit_rejected():
    v = run_verifier(git_kwargs={"parents": (BASE, HEAD)})
    assert v.reuse is False and v.reason == "topology_not_single_parent"


def test_root_commit_rejected():
    v = run_verifier(git_kwargs={"parents": ()})
    assert v.reuse is False and v.reason == "topology_root_commit"


# ---------------------------------------------------------------------------
# Associated PR (condition 3).
# ---------------------------------------------------------------------------


def test_exactly_one_merged_pr_accepted():
    v = run_verifier(api_kwargs={"prs": [make_pr()]})
    assert v.reuse is True


def test_zero_pr_rejected():
    v = run_verifier(api_kwargs={"prs": []})
    assert v.reuse is False and v.reason == "no_associated_pr"


def test_multiple_qualifying_prs_rejected():
    v = run_verifier(api_kwargs={"prs": [make_pr(), make_pr()]})
    assert v.reuse is False and v.reason == "multiple_associated_prs"


def test_pr_not_merged_rejected():
    v = run_verifier(
        api_kwargs={"prs": [make_pr(state="open", merged_at=None)]}
    )
    assert v.reuse is False and v.reason == "pr_not_merged"


def test_merge_commit_sha_mismatch_rejected():
    v = run_verifier(api_kwargs={"prs": [make_pr(merge_commit_sha="e" * 40)]})
    assert v.reuse is False and v.reason == "merge_commit_sha_mismatch"


def test_pr_base_ref_mismatch_rejected():
    pr = make_pr()
    pr["base"] = {"ref": "release", "sha": BASE}
    v = run_verifier(api_kwargs={"prs": [pr]})
    assert v.reuse is False and v.reason == "pr_base_ref_mismatch"


def test_pr_base_sha_mismatch_rejected():
    pr = make_pr()
    pr["base"] = {"ref": "main", "sha": "e" * 40}
    v = run_verifier(api_kwargs={"prs": [pr]})
    assert v.reuse is False and v.reason == "pr_base_sha_mismatch"


def test_pr_missing_head_sha_rejected():
    pr = make_pr()
    pr["head"] = {"sha": None}
    v = run_verifier(api_kwargs={"prs": [pr]})
    assert v.reuse is False and v.reason == "pr_missing_head_sha"


# ---------------------------------------------------------------------------
# Successful exact-head run (condition 4).
# ---------------------------------------------------------------------------


def test_successful_exact_head_run_accepted():
    v = run_verifier(api_kwargs={"runs": [make_run()]})
    assert v.reuse is True


@pytest.mark.parametrize(
    "conclusion", ["failure", "cancelled", "skipped", "neutral", "timed_out",
                   "action_required"]
)
def test_non_success_run_conclusion_rejected(conclusion):
    v = run_verifier(api_kwargs={"runs": [make_run(conclusion=conclusion)]})
    assert v.reuse is False and v.reason == "no_matching_run"


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting"])
def test_pending_run_rejected(status):
    v = run_verifier(api_kwargs={"runs": [make_run(status=status)]})
    assert v.reuse is False and v.reason == "no_matching_run"


def test_run_for_other_head_rejected():
    v = run_verifier(api_kwargs={"runs": [make_run(head_sha="e" * 40)]})
    assert v.reuse is False and v.reason == "no_matching_run"


def test_run_wrong_event_rejected():
    v = run_verifier(api_kwargs={"runs": [make_run(event="push")]})
    assert v.reuse is False and v.reason == "no_matching_run"


def test_run_wrong_workflow_name_rejected():
    v = run_verifier(api_kwargs={"runs": [make_run(name="Other")]})
    assert v.reuse is False and v.reason == "no_matching_run"


def test_run_wrong_workflow_path_rejected():
    v = run_verifier(
        api_kwargs={"runs": [make_run(path=".github/workflows/other.yml")]}
    )
    assert v.reuse is False and v.reason == "no_matching_run"


def test_candidates_inspected_newest_first():
    """Newest candidate fails (missing job); older candidate with a
    validating attestation proves the tree -> reuse, reporting the older
    run's id."""
    api = FakeAPI(
        runs=[
            make_run(id=RUN_ID + 1, run_attempt=2, created_at="2026-08-10T04:00:00Z"),
            make_run(id=RUN_ID, run_attempt=1, created_at="2026-08-10T03:00:00Z"),
        ],
        jobs_by_run={
            RUN_ID: make_all_jobs(),
            RUN_ID + 1: [make_job("test (3.11)")],
        },
    )
    v = reuse.run_verifier(
        repository=REPO, event_name="push", ref=reuse.MAIN_REF,
        before_sha=BASE, main_sha=MAIN, api=api, git=FakeGit(),
    )
    assert v.reuse is True
    assert v.pr_run_id == RUN_ID


def test_all_candidates_failing_denies_reuse():
    api = FakeAPI(
        runs=[
            make_run(id=2, run_attempt=2, created_at="2026-08-10T04:00:00Z"),
            make_run(id=1, run_attempt=1, created_at="2026-08-10T03:00:00Z"),
        ],
        jobs_by_run={1: [make_job("test (3.11)")], 2: [make_job("test (3.11)")]},
    )
    v = reuse.run_verifier(
        repository=REPO, event_name="push", ref=reuse.MAIN_REF,
        before_sha=BASE, main_sha=MAIN, api=api, git=FakeGit(),
    )
    assert v.reuse is False and v.reason == "jobs_missing_surface"


# ---------------------------------------------------------------------------
# Required job conclusions (condition 5).
# ---------------------------------------------------------------------------


def test_all_four_required_jobs_accepted():
    v = run_verifier(api_kwargs={"jobs": make_all_jobs()})
    assert v.reuse is True


@pytest.mark.parametrize("surface", reuse.REQUIRED_JOB_SURFACES)
def test_missing_one_job_rejected(surface):
    jobs = [j for j in make_all_jobs() if j["name"] != surface]
    v = run_verifier(api_kwargs={"jobs": jobs})
    assert v.reuse is False and v.reason == "jobs_missing_surface"


@pytest.mark.parametrize(
    "conclusion", ["failure", "cancelled", "timed_out", "skipped", "neutral",
                   "action_required"]
)
@pytest.mark.parametrize("surface", reuse.REQUIRED_JOB_SURFACES)
def test_non_success_job_conclusion_rejected(surface, conclusion):
    jobs = make_all_jobs()
    for job in jobs:
        if job["name"] == surface:
            job["conclusion"] = conclusion
            job["status"] = "completed"
    v = run_verifier(api_kwargs={"jobs": jobs})
    assert v.reuse is False and v.reason == "jobs_non_success"


def test_incomplete_job_status_rejected():
    jobs = make_all_jobs()
    jobs[0]["status"] = "in_progress"
    jobs[0]["conclusion"] = None
    v = run_verifier(api_kwargs={"jobs": jobs})
    assert v.reuse is False and v.reason == "jobs_non_success"


def test_duplicate_required_job_rejected():
    jobs = make_all_jobs() + [make_job("test (3.11)")]
    v = run_verifier(api_kwargs={"jobs": jobs})
    assert v.reuse is False and v.reason == "jobs_duplicate"


def test_extra_job_rejected():
    jobs = make_all_jobs() + [make_job("lint")]
    v = run_verifier(api_kwargs={"jobs": jobs})
    assert v.reuse is False and v.reason == "jobs_unexpected"


# ---------------------------------------------------------------------------
# Attestation artifact (condition 6a).
# ---------------------------------------------------------------------------


def test_artifact_present_accepted():
    v = run_verifier(api_kwargs={"artifacts": [make_artifact()]})
    assert v.reuse is True


def test_artifact_unavailable_rejected():
    v = run_verifier(api_kwargs={"artifacts": []})
    assert v.reuse is False and v.reason == "attestation_artifact_missing"


def test_artifact_wrong_attempt_name_rejected():
    v = run_verifier(
        api_kwargs={"artifacts": [make_artifact(name=f"...-attempt-2")]}
    )
    assert v.reuse is False and v.reason == "attestation_artifact_missing"


def test_artifact_ambiguous_rejected():
    v = run_verifier(api_kwargs={"artifacts": [make_artifact(), make_artifact()]})
    assert v.reuse is False and v.reason == "attestation_artifact_ambiguous"


def test_artifact_expired_rejected():
    v = run_verifier(api_kwargs={"artifacts": [make_artifact(expired=True)]})
    assert v.reuse is False and v.reason == "attestation_artifact_expired"


@pytest.mark.parametrize("size", [0, 65536 + 1, 10_000_000])
def test_artifact_implausible_size_rejected(size):
    v = run_verifier(api_kwargs={"artifacts": [make_artifact(size_in_bytes=size)]})
    assert v.reuse is False and v.reason == "attestation_artifact_too_large"


def test_artifact_download_failure_rejected():
    v = run_verifier(
        api_kwargs={"fail": "download", "raise_reason": "attestation_artifact_download_failed"}
    )
    assert v.reuse is False and v.reason == "attestation_artifact_download_failed"


# ---------------------------------------------------------------------------
# Attestation schema + identifiers (condition 6b/6c).
# ---------------------------------------------------------------------------


def test_malformed_zip_rejected():
    v = run_verifier(api_kwargs={"zip_bytes": b"this is not a zip"})
    assert v.reuse is False and v.reason == "attestation_zip_malformed"


def test_zip_with_extra_member_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other.json", "{}")
        zf.writestr(reuse.ATTESTATION_FILENAME, "{}")
    v = run_verifier(api_kwargs={"zip_bytes": buf.getvalue()})
    assert v.reuse is False and v.reason == "attestation_zip_malformed"


def test_zip_wrong_member_name_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("not_the_attestation.json", "{}")
    v = run_verifier(api_kwargs={"zip_bytes": buf.getvalue()})
    assert v.reuse is False and v.reason == "attestation_zip_malformed"


def test_zip_invalid_json_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(reuse.ATTESTATION_FILENAME, "{not json")
    v = run_verifier(api_kwargs={"zip_bytes": buf.getvalue()})
    assert v.reuse is False and v.reason == "attestation_json_malformed"


def test_zip_non_dict_json_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(reuse.ATTESTATION_FILENAME, "[1, 2]")
    v = run_verifier(api_kwargs={"zip_bytes": buf.getvalue()})
    assert v.reuse is False and v.reason == "attestation_json_malformed"


def test_attestation_missing_field_rejected():
    data = make_attestation()
    del data["base_sha"]
    v = run_verifier(api_kwargs={"zip_bytes": attestation_zip_bytes(data)})
    assert v.reuse is False and v.reason == "attestation_schema_mismatch"


def test_attestation_extra_field_rejected():
    data = make_attestation()
    data["surprise"] = True
    v = run_verifier(api_kwargs={"zip_bytes": attestation_zip_bytes(data)})
    assert v.reuse is False and v.reason == "attestation_schema_mismatch"


def test_attestation_wrong_schema_version_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(schema_version=2))}
    )
    assert v.reuse is False and v.reason == "attestation_schema_version"


def test_attestation_wrong_workflow_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(workflow="Other"))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_workflow"


def test_attestation_wrong_repository_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(repository="other/repo"))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_repository"


def test_attestation_wrong_run_id_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(run_id=RUN_ID + 1))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_run_id"


def test_attestation_wrong_run_attempt_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(run_attempt=2))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_run_attempt"


def test_attestation_wrong_pr_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(pr_number=61))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_pr"


def test_attestation_wrong_base_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(base_sha="e" * 40))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_base"


def test_attestation_wrong_head_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(head_sha="e" * 40))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_head"


def test_attestation_tier_not_full_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(tier="docs_fast"))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_tier"


def test_attestation_full_matrix_required_false_rejected():
    v = run_verifier(
        api_kwargs={"zip_bytes": attestation_zip_bytes(make_attestation(full_matrix_required=False))}
    )
    assert v.reuse is False and v.reason == "attestation_wrong_full_matrix"


@pytest.mark.parametrize(
    "field", ["tested_merge_sha", "tested_tree_sha", "base_sha", "head_sha"]
)
def test_attestation_bad_sha_format_rejected(field):
    data = make_attestation(**{field: "garbage"})
    v = run_verifier(api_kwargs={"zip_bytes": attestation_zip_bytes(data)})
    assert v.reuse is False and v.reason == "attestation_bad_sha"


def test_attestation_bad_run_id_type_rejected():
    data = make_attestation(run_id="31352080511")
    v = run_verifier(api_kwargs={"zip_bytes": attestation_zip_bytes(data)})
    assert v.reuse is False and v.reason == "attestation_bad_run_id"


def test_attestation_bad_pr_number_type_rejected():
    data = make_attestation(pr_number="60")
    v = run_verifier(api_kwargs={"zip_bytes": attestation_zip_bytes(data)})
    assert v.reuse is False and v.reason == "attestation_bad_pr_number"


# ---------------------------------------------------------------------------
# TREE EQUIVALENCE (condition 7 — the core proof).
# ---------------------------------------------------------------------------


def test_main_tree_equals_tested_tree_accepted():
    v = run_verifier(git_kwargs={"tree": TREE})
    assert v.reuse is True


def test_main_tree_differs_from_tested_tree_rejected():
    v = run_verifier(git_kwargs={"tree": "e" * 40})
    assert v.reuse is False and v.reason == "main_tree_mismatch"


# ---------------------------------------------------------------------------
# Control-plane exclusion (condition 8).
# ---------------------------------------------------------------------------

CONTROL_CHANGED_CASES = [
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "scripts/ci_post_merge_reuse.py",
    "scripts/ci_risk_tier.py",
    "scripts/audit_pr.py",
    "scripts/check_release.py",
    "ci/components.toml",
    # P1-1 (PR #75): the Python 3.14 compatibility surface contract
    # (manifest, fail-closed validator, regression surface) is
    # control-plane: a merged change touching it denies reuse so the
    # attestation's "3.14 audited surface" claim is never reused.
    "ci/python314_compatibility_surface.txt",
    "scripts/ci_python314_surface.py",
    "tests/test_python314_compatibility_surface.py",
    "tests/test_v061_ci_auditability.py",
    "tests/test_ci_post_merge_reuse.py",
]


@pytest.mark.parametrize("path", CONTROL_CHANGED_CASES)
def test_control_plane_path_change_forces_full(path):
    v = run_verifier(git_kwargs={"changed": [path]})
    assert v.reuse is False and v.reason == "control_plane_changed"


def test_workflow_path_change_forces_full():
    v = run_verifier(git_kwargs={"changed": [".github/workflows/ci.yml"]})
    assert v.reuse is False and v.reason == "control_plane_changed"


def test_rename_into_control_plane_forces_full():
    v = run_verifier(
        git_kwargs={"changed": ["tests/old_test.py", "tests/test_v061_ci_auditability.py"]}
    )
    assert v.reuse is False and v.reason == "control_plane_changed"


def test_rename_out_of_control_plane_forces_full():
    """Rename old+new paths both count: leaving the control-plane is still a
    control-plane change."""
    v = run_verifier(
        git_kwargs={"changed": ["scripts/check_release.py", "scripts/renamed_checker.py"]}
    )
    assert v.reuse is False and v.reason == "control_plane_changed"


def test_ordinary_src_change_remains_eligible():
    v = run_verifier(
        git_kwargs={"changed": ["src/market_vault/dataset/sample_generation_models.py"]}
    )
    assert v.reuse is True


def test_ordinary_non_control_test_change_remains_eligible():
    v = run_verifier(git_kwargs={"changed": ["tests/test_dataset_catalog_cli.py"]})
    assert v.reuse is True


def test_multiple_changes_with_one_control_path_forces_full():
    v = run_verifier(
        git_kwargs={
            "changed": ["src/market_vault/x.py", ".github/workflows/ci.yml"]
        }
    )
    assert v.reuse is False and v.reason == "control_plane_changed"


def test_control_plane_check_runs_before_any_api_call():
    """The early control-plane gate must deny reuse without spending API
    calls (the common case for this PR itself)."""
    git = FakeGit(changed=["scripts/ci_post_merge_reuse.py"])
    api = FakeAPI(fail="pulls", raise_reason="network_error")
    v = reuse.run_verifier(
        repository=REPO, event_name="push", ref=reuse.MAIN_REF,
        before_sha=BASE, main_sha=MAIN, api=api, git=git,
    )
    assert v.reuse is False and v.reason == "control_plane_changed"
    assert api.calls == []  # control-plane gate consumed no API calls
    assert git.calls == ["changed_paths"]


# ---------------------------------------------------------------------------
# Fail-closed: API / adapter / git failures.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,reason",
    [
        ("pulls", "network_error"),
        ("runs", "network_error"),
        ("jobs", "network_error"),
        ("artifacts", "network_error"),
        ("download", "network_error"),
        ("jobs", "api_http_error_500"),
        ("artifacts", "malformed_api_response"),
    ],
)
def test_api_exception_denies_reuse(method, reason):
    v = run_verifier(api_kwargs={"fail": method, "raise_reason": reason})
    assert v.reuse is False and v.reason == reason


def test_git_error_denies_reuse():
    class BrokenGit(FakeGit):
        def changed_paths(self, base, head):
            raise reuse.GitError("git_changed_paths_malformed")

    v = run_verifier(git_kwargs={})
    # reuse FakeGit via direct call with the broken one
    event = {
        "repository": REPO, "event_name": "push", "ref": reuse.MAIN_REF,
        "before_sha": BASE, "main_sha": MAIN,
    }
    v = reuse.run_verifier(
        api=FakeAPI(), git=BrokenGit(), **event
    )
    assert v.reuse is False and v.reason == "git_changed_paths_malformed"


def test_unknown_changed_paths_denies_reuse():
    class BrokenGit(FakeGit):
        def changed_paths(self, base, head):
            raise reuse.GitError("git_error")

    v = reuse.run_verifier(
        api=FakeAPI(),
        git=BrokenGit(),
        repository=REPO, event_name="push", ref=reuse.MAIN_REF,
        before_sha=BASE, main_sha=MAIN,
    )
    assert v.reuse is False and v.reason == "git_error"


def test_unexpected_verifier_error_fail_closed_never_skips():
    class BrokenGit(FakeGit):
        def rev_list_parents(self, sha):
            raise RuntimeError("boom")

    v = reuse.run_verifier(
        api=FakeAPI(),
        git=BrokenGit(),
        repository=REPO, event_name="push", ref=reuse.MAIN_REF,
        before_sha=BASE, main_sha=MAIN,
    )
    assert v.reuse is False and v.reason == "verifier_internal_error"


# ---------------------------------------------------------------------------
# GitHubAPI adapter with mocked HTTP (no network).
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body


class FakeURLopener:
    """Serves canned (status, body, headers) responses by exact URL."""

    def __init__(self, mapping: dict[str, tuple] | None = None,
                 raise_error: Exception | None = None):
        self.mapping = mapping or {}
        self.raise_error = raise_error
        self.requests: list[str] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request.full_url)
        if self.raise_error is not None:
            raise self.raise_error
        url = request.full_url
        if url not in self.mapping:
            raise urllib.error.URLError(f"no canned response for {url}")
        status, body, headers = self.mapping[url]
        return FakeResponse(status, body, headers)


def api_url(path: str, params: dict[str, str] | None = None) -> str:
    url = f"https://api.github.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def make_api(urlopen: FakeURLopener) -> reuse.GitHubAPI:
    return reuse.GitHubAPI(REPO, "test-token", urlopen=urlopen)


def test_adapter_parses_bare_list_for_commit_pulls():
    opener = FakeURLopener({
        api_url(f"/repos/{REPO}/commits/{MAIN}/pulls"): (200, json.dumps([make_pr()]).encode("utf-8"), {}),
    })
    api = make_api(opener)
    prs = api.list_pulls_for_commit(MAIN)
    assert prs[0]["number"] == PR_NUMBER


def test_adapter_parses_collection_for_runs():
    body = json.dumps({"workflow_runs": [make_run()]}).encode("utf-8")
    opener = FakeURLopener({
        api_url(
            f"/repos/{REPO}/actions/runs",
            {"event": "pull_request", "head_sha": HEAD, "per_page": "100"},
        ): (200, body, {}),
    })
    api = make_api(opener)
    runs = api.list_runs_for_head(HEAD)
    assert runs[0]["id"] == RUN_ID


def test_adapter_http_error_denies_reuse():
    opener = FakeURLopener({
        api_url(f"/repos/{REPO}/commits/{MAIN}/pulls"): (500, b"oops", {}),
    })
    api = make_api(opener)
    with pytest.raises(reuse.APIError) as exc:
        api.list_pulls_for_commit(MAIN)
    assert exc.value.reason == "api_http_error_500"


def test_adapter_404_denies_reuse():
    opener = FakeURLopener({
        api_url(f"/repos/{REPO}/commits/{MAIN}/pulls"): (404, b"", {}),
    })
    api = make_api(opener)
    with pytest.raises(reuse.APIError) as exc:
        api.list_pulls_for_commit(MAIN)
    assert exc.value.reason == "api_http_error_404"


def test_adapter_malformed_json_denies_reuse():
    opener = FakeURLopener({
        api_url(f"/repos/{REPO}/commits/{MAIN}/pulls"): (200, b"<html>not json</html>", {}),
    })
    api = make_api(opener)
    with pytest.raises(reuse.APIError) as exc:
        api.list_pulls_for_commit(MAIN)
    assert exc.value.reason == "malformed_api_response"


def test_adapter_wrong_response_shape_denies_reuse():
    opener = FakeURLopener({
        api_url(
            f"/repos/{REPO}/actions/runs",
            {"event": "pull_request", "head_sha": HEAD, "per_page": "100"},
        ): (200, json.dumps({"not_workflow_runs": []}).encode("utf-8"), {}),
    })
    api = make_api(opener)
    with pytest.raises(reuse.APIError) as exc:
        api.list_runs_for_head(HEAD)
    assert exc.value.reason == "malformed_api_response"


def test_adapter_network_error_denies_reuse():
    opener = FakeURLopener(
        raise_error=urllib.error.URLError("connection refused")
    )
    api = make_api(opener)
    with pytest.raises(reuse.APIError) as exc:
        api.list_pulls_for_commit(MAIN)
    assert exc.value.reason == "network_error"


def test_adapter_downloads_artifact_zip():
    payload = attestation_zip_bytes()
    opener = FakeURLopener({
        api_url(f"/repos/{REPO}/actions/artifacts/9049399458/zip"): (200, payload, {}),
    })
    api = make_api(opener)
    assert api.download_artifact(9049399458) == payload


def test_adapter_follows_pagination_link():
    page1 = json.dumps({"workflow_runs": [make_run(id=1)]}).encode("utf-8")
    page2 = json.dumps({"workflow_runs": [make_run(id=2)]}).encode("utf-8")
    url1 = api_url(
        f"/repos/{REPO}/actions/runs",
        {"event": "pull_request", "head_sha": HEAD, "per_page": "100"},
    )
    url2 = url1 + "&page=2"
    opener = FakeURLopener({
        url1: (200, page1, {"Link": f'<{url2}>; rel="next", <{url1}>; rel="last"'}),
        url2: (200, page2, {}),
    })
    api = make_api(opener)
    runs = api.list_runs_for_head(HEAD)
    assert [r["id"] for r in runs] == [1, 2]


# ---------------------------------------------------------------------------
# Attestation creation contract.
# ---------------------------------------------------------------------------


def fake_create_env(tmp_path: Path, *, event: dict | None = None) -> dict:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            event
            or {
                "ref": "refs/pull/60/merge",
                "pull_request": {
                    "number": PR_NUMBER,
                    "base": {"sha": BASE},
                    "head": {"sha": HEAD},
                },
            }
        ),
        encoding="utf-8",
    )
    return {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_RUN_ID": str(RUN_ID),
        "GITHUB_RUN_ATTEMPT": str(ATTEMPT),
        "GITHUB_SHA": MAIN,
        "GITHUB_EVENT_PATH": str(event_path),
    }


def test_create_attestation_writes_deterministic_json(tmp_path):
    out = tmp_path / "ci_full_attestation.json"
    rc = reuse.create_attestation(
        str(out), env=fake_create_env(tmp_path), git=FakeGit(tree=TREE)
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    data = json.loads(text)
    assert list(data.keys()) == list(reuse.ATTESTATION_FIELD_ORDER)
    assert data["schema_version"] == 1
    assert data["repository"] == REPO
    assert data["workflow"] == "CI"
    assert data["run_id"] == RUN_ID
    assert data["run_attempt"] == ATTEMPT
    assert data["pr_number"] == PR_NUMBER
    assert data["base_sha"] == BASE
    assert data["head_sha"] == HEAD
    assert data["tested_merge_sha"] == MAIN
    assert data["tested_tree_sha"] == TREE
    assert data["tier"] == "full"
    assert data["full_matrix_required"] is True


def test_create_attestation_is_byte_deterministic(tmp_path):
    env = fake_create_env(tmp_path)
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    assert reuse.create_attestation(str(first), env=env, git=FakeGit(tree=TREE)) == 0
    assert reuse.create_attestation(str(second), env=env, git=FakeGit(tree=TREE)) == 0
    assert first.read_bytes() == second.read_bytes()


def test_create_attestation_missing_run_context_fails(tmp_path):
    env = fake_create_env(tmp_path)
    del env["GITHUB_RUN_ID"]
    out = tmp_path / "x.json"
    assert reuse.create_attestation(str(out), env=env, git=FakeGit()) == 1
    assert not out.exists()


def test_create_attestation_non_pr_event_fails(tmp_path):
    env = fake_create_env(tmp_path, event={"ref": "refs/heads/main"})
    out = tmp_path / "x.json"
    assert reuse.create_attestation(str(out), env=env, git=FakeGit()) == 1
    assert not out.exists()


def test_serialize_attestation_is_stable():
    data = make_attestation()
    assert reuse.serialize_attestation(data) == reuse.serialize_attestation(data)
    assert json.loads(reuse.serialize_attestation(data)) == data


# ---------------------------------------------------------------------------
# Verdict rendering + skip predicate (workflow-facing contract).
# ---------------------------------------------------------------------------


def test_render_verdict_true_exact_block():
    v = reuse.Verdict(
        reuse=True, reason=reuse.REUSE_OK_REASON, pr_number=PR_NUMBER,
        pr_head_sha=HEAD, pr_run_id=RUN_ID, tested_merge_sha=MERGE,
        tested_tree_sha=TREE, main_sha=MAIN, main_tree_sha=TREE,
    )
    assert render_verdict(v) == (
        "POST_MERGE_REUSE=true\n"
        "reason=verified_full_pr_tree_equivalence\n"
        f"pr_number={PR_NUMBER}\n"
        f"pr_head_sha={HEAD}\n"
        f"pr_run_id={RUN_ID}\n"
        f"tested_merge_sha={MERGE}\n"
        f"tested_tree_sha={TREE}\n"
        f"main_sha={MAIN}\n"
        f"main_tree_sha={TREE}\n"
    )


def test_render_verdict_false_two_lines():
    assert render_verdict(reuse.Verdict(False, "no_associated_pr")) == (
        "POST_MERGE_REUSE=false\n"
        "reason=no_associated_pr\n"
    )


def test_rendered_verdict_never_contains_token():
    for verdict in (run_verifier(), reuse.Verdict(False, "no_associated_pr")):
        assert "token" not in render_verdict(verdict).lower()


@pytest.mark.parametrize(
    "marker", ["false", "FALSE", "True", "TRUE", "true\n", "", " ", "garbage", "1"]
)
def test_skip_predicate_only_exact_true_skips(marker):
    assert reuse.skip_heavy_validation(marker) is False


def test_skip_predicate_unset_runs_heavy_validation():
    assert reuse.skip_heavy_validation(None) is False


def test_skip_predicate_exact_true_skips():
    assert reuse.skip_heavy_validation("true") is True


# ---------------------------------------------------------------------------
# THE INVARIANT: POST_MERGE_REUSE=false can never satisfy the heavy-step
# skip predicate. Every negative verdict the verifier can produce must map
# to skip_heavy_validation(...) == False; only a proven reuse maps to True.
# ---------------------------------------------------------------------------


def test_invariant_reuse_false_never_satisfies_skip_predicate():
    scenarios = [
        lambda: run_verifier(event_name="pull_request"),
        lambda: run_verifier(ref="refs/heads/feature/x"),
        lambda: run_verifier(before_sha=None),
        lambda: run_verifier(git_kwargs={"parents": ()}),
        lambda: run_verifier(git_kwargs={"parents": (BASE, HEAD)}),
        lambda: run_verifier(git_kwargs={"parents": (HEAD,)}),
        lambda: run_verifier(api_kwargs={"prs": []}),
        lambda: run_verifier(api_kwargs={"prs": [make_pr(), make_pr()]}),
        lambda: run_verifier(api_kwargs={"runs": []}),
        lambda: run_verifier(api_kwargs={"runs": [make_run(status="in_progress")]}),
        lambda: run_verifier(api_kwargs={"runs": [make_run(conclusion="failure")]}),
        lambda: run_verifier(api_kwargs={"jobs": []}),
        lambda: run_verifier(api_kwargs={"artifacts": []}),
        lambda: run_verifier(api_kwargs={"zip_bytes": b"garbage"}),
        lambda: run_verifier(git_kwargs={"tree": "e" * 40}),
        lambda: run_verifier(git_kwargs={"changed": [".github/workflows/ci.yml"]}),
        lambda: run_verifier(api_kwargs={"fail": "runs"}),
        lambda: run_verifier(api_kwargs={"fail": "download"}),
        lambda: run_verifier(),
    ]
    for scenario in scenarios:
        v = scenario()
        marker = marker_of(v)
        assert marker in ("true", "false")
        assert reuse.skip_heavy_validation(marker) == v.reuse, (
            f"scenario produced reuse={v.reuse} reason={v.reason} but "
            f"skip predicate={reuse.skip_heavy_validation(marker)}"
        )


def test_invariant_unset_reuse_state_runs_heavy_validation():
    # The workflow guards use `env.POST_MERGE_REUSE != 'true'`; an unset
    # env var is the empty string, which must never skip.
    assert reuse.skip_heavy_validation(None) is False
    assert reuse.skip_heavy_validation("") is False


# ---------------------------------------------------------------------------
# CLI entry points (offline paths only).
# ---------------------------------------------------------------------------


def test_cli_missing_repo_prints_false(capsys):
    assert reuse.main([], env={}) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("POST_MERGE_REUSE=false\nreason=missing_repo_context\n")


def test_cli_missing_token_prints_false(capsys):
    assert reuse.main(["--repo", REPO], env={}) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("POST_MERGE_REUSE=false\nreason=missing_token\n")


# ---------------------------------------------------------------------------
# V2 foundation: per-surface reuse-plan evidence matrix (PR #65).
#
# FOUNDATION ONLY — these tests pin the pure model, the fail-closed
# decision matrix, and the invariant that identity unproven can never
# produce surface reuse. The foundation is NOT wired into run_verifier():
# the V1 POST_MERGE_REUSE contract tests above are untouched, and the last
# two tests below re-prove that V1 production behavior is unchanged.
# ---------------------------------------------------------------------------


def v2_plan(
    *,
    identity_proven: bool = True,
    identity_reason: str = "verified_tree_identity",
    jobs: list[dict] | None = None,
) -> reuse.ReusePlan:
    return reuse.build_surface_reuse_plan(
        identity_proven=identity_proven,
        identity_reason=identity_reason,
        jobs=[] if jobs is None else jobs,
    )


def v2_jobs(
    *,
    missing: tuple[str, ...] = (),
    statuses: dict[str, str] | None = None,
    conclusions: dict[str, str] | None = None,
    extra: tuple[dict, ...] = (),
) -> list[dict]:
    """Canonical V2 job list; one completed/success job per surface by
    default. ``missing`` selects surfaces (canonical IDs) to omit; the
    status/conclusion maps are keyed by canonical job name."""
    jobs = []
    for surface in reuse.SURFACE_ORDER:
        if surface in missing:
            continue
        name = reuse.SURFACE_JOB_NAMES[surface]
        jobs.append(
            {
                "name": name,
                "status": (statuses or {}).get(name, "completed"),
                "conclusion": (conclusions or {}).get(name, "success"),
            }
        )
    jobs.extend(extra)
    return jobs


def surface_names(plan: reuse.ReusePlan) -> list[str]:
    return [d.surface for d in plan.surfaces]


def test_v2_surface_model_is_canonical_and_maps_to_jobs():
    assert reuse.SURFACE_ORDER == (
        "test-3.11",
        "test-3.14",
        "pyarrow24",
        "package",
    )
    assert reuse.SURFACE_JOB_NAMES == {
        "test-3.11": "test (3.11)",
        "test-3.14": "test (3.14)",
        "pyarrow24": "portability-pyarrow24",
        "package": "package",
    }
    # The V1 four-surface contract is preserved as a separate constant.
    assert reuse.REQUIRED_JOB_SURFACES == tuple(reuse.SURFACE_JOB_NAMES.values())
    assert tuple(reuse.SURFACE_JOB_NAMES[s] for s in reuse.SURFACE_ORDER) == (
        reuse.REQUIRED_JOB_SURFACES
    )


# -- 1. identity false + all jobs success -> no_reuse / 4 RUN -----------


def test_v2_identity_false_all_jobs_success_no_reuse():
    plan = v2_plan(
        identity_proven=False, identity_reason="no_proof", jobs=v2_jobs()
    )
    assert plan.mode == reuse.MODE_NO_REUSE
    assert plan.identity_proven is False
    assert plan.identity_reason == "no_proof"
    assert all(d.reuse is False for d in plan.surfaces)
    assert all(
        d.reason == reuse.GLOBAL_IDENTITY_UNPROVEN_REASON for d in plan.surfaces
    )


# -- 2. identity true + all four success -> full_reuse / 4 REUSE ---------


def test_v2_identity_true_all_success_full_reuse():
    plan = v2_plan(identity_reason="verified_tree_identity", jobs=v2_jobs())
    assert plan.mode == reuse.MODE_FULL_REUSE
    assert plan.identity_proven is True
    assert all(d.reuse is True for d in plan.surfaces)
    assert all(d.reason == reuse.SURFACE_VERIFIED_REASON for d in plan.surfaces)


# -- 3-6. exactly one surface missing -> partial_reuse / only it RUN ----


@pytest.mark.parametrize("surface", reuse.SURFACE_ORDER)
def test_v2_one_missing_surface_partial(surface):
    plan = v2_plan(jobs=v2_jobs(missing=(surface,)))
    assert plan.mode == reuse.MODE_PARTIAL_REUSE
    for decision in plan.surfaces:
        if decision.surface == surface:
            assert decision.reuse is False
            assert decision.reason == reuse.SURFACE_JOB_MISSING_REASON
        else:
            assert decision.reuse is True
            assert decision.reason == reuse.SURFACE_VERIFIED_REASON


# -- 7. every pair of missing surfaces -> partial / those two RUN --------


@pytest.mark.parametrize(
    "pair", [p for p in itertools.combinations(reuse.SURFACE_ORDER, 2)]
)
def test_v2_two_missing_surfaces_partial(pair):
    plan = v2_plan(jobs=v2_jobs(missing=tuple(pair)))
    assert plan.mode == reuse.MODE_PARTIAL_REUSE
    for decision in plan.surfaces:
        expected_reuse = decision.surface not in pair
        assert decision.reuse is expected_reuse
        assert decision.reason == (
            reuse.SURFACE_JOB_MISSING_REASON
            if not expected_reuse
            else reuse.SURFACE_VERIFIED_REASON
        )


# -- 8. three missing -> partial / one REUSE -----------------------------


@pytest.mark.parametrize(
    "triple", [t for t in itertools.combinations(reuse.SURFACE_ORDER, 3)]
)
def test_v2_three_missing_surfaces_partial(triple):
    plan = v2_plan(jobs=v2_jobs(missing=tuple(triple)))
    assert plan.mode == reuse.MODE_PARTIAL_REUSE
    reusable = [d for d in plan.surfaces if d.reuse]
    assert [d.surface for d in reusable] == [
        s for s in reuse.SURFACE_ORDER if s not in triple
    ]
    for decision in plan.surfaces:
        if decision.surface in triple:
            assert decision.reason == reuse.SURFACE_JOB_MISSING_REASON


# -- 9. all four missing -> no_reuse / 4 RUN -----------------------------


def test_v2_all_surfaces_missing_no_reuse():
    plan = v2_plan(jobs=v2_jobs(missing=tuple(reuse.SURFACE_ORDER)))
    assert plan.mode == reuse.MODE_NO_REUSE
    assert all(d.reuse is False for d in plan.surfaces)
    assert all(d.reason == reuse.SURFACE_JOB_MISSING_REASON for d in plan.surfaces)


# -- 10-15. non-success / incomplete per surface -> only it RUN ----------


@pytest.mark.parametrize(
    "conclusion",
    ["failure", "cancelled", "timed_out", "skipped", "neutral", "action_required"],
)
@pytest.mark.parametrize("surface", reuse.SURFACE_ORDER)
def test_v2_non_success_conclusion_partial(surface, conclusion):
    name = reuse.SURFACE_JOB_NAMES[surface]
    plan = v2_plan(
        jobs=v2_jobs(conclusions={name: conclusion})
    )
    assert plan.mode == reuse.MODE_PARTIAL_REUSE
    for decision in plan.surfaces:
        if decision.surface == surface:
            assert decision.reuse is False
            assert decision.reason == reuse.SURFACE_JOB_NON_SUCCESS_REASON
        else:
            assert decision.reuse is True


@pytest.mark.parametrize(
    "status", ["in_progress", "queued", "waiting", "pending", ""]
)
@pytest.mark.parametrize("surface", reuse.SURFACE_ORDER)
def test_v2_incomplete_job_status_partial(surface, status):
    name = reuse.SURFACE_JOB_NAMES[surface]
    plan = v2_plan(
        jobs=v2_jobs(
            statuses={name: status}, conclusions={name: None}
        )
    )
    assert plan.mode == reuse.MODE_PARTIAL_REUSE
    for decision in plan.surfaces:
        if decision.surface == surface:
            assert decision.reuse is False
            assert decision.reason == reuse.SURFACE_JOB_NON_SUCCESS_REASON
        else:
            assert decision.reuse is True


# -- 16-17. duplicate required surface -> no_reuse / 4 RUN ---------------


@pytest.mark.parametrize("surface", ("test-3.11", "package"))
def test_v2_duplicate_required_surface_no_reuse(surface):
    name = reuse.SURFACE_JOB_NAMES[surface]
    jobs = v2_jobs() + [{"name": name, "status": "completed", "conclusion": "success"}]
    plan = v2_plan(jobs=jobs)
    assert plan.mode == reuse.MODE_NO_REUSE
    assert all(d.reuse is False for d in plan.surfaces)
    assert all(d.reason == reuse.JOB_DUPLICATE_CONTRACT_REASON for d in plan.surfaces)


# -- 18. unexpected formal job -> no_reuse / 4 RUN -----------------------


def test_v2_unexpected_job_no_reuse():
    plan = v2_plan(jobs=v2_jobs(extra=({"name": "lint", "status": "completed",
                                        "conclusion": "success"},)))
    assert plan.mode == reuse.MODE_NO_REUSE
    assert all(d.reuse is False for d in plan.surfaces)
    assert all(d.reason == reuse.JOB_UNEXPECTED_CONTRACT_REASON for d in plan.surfaces)


def test_v2_unexpected_job_without_name_no_reuse():
    plan = v2_plan(jobs=v2_jobs(extra=({"status": "completed", "conclusion": "success"},)))
    assert plan.mode == reuse.MODE_NO_REUSE
    assert all(d.reason == reuse.JOB_UNEXPECTED_CONTRACT_REASON for d in plan.surfaces)


# -- 19. shuffled input order -> same plan, canonical output order -------


def test_v2_input_job_order_does_not_matter():
    ordered = v2_plan(jobs=v2_jobs(missing=("package",)))
    shuffled = v2_plan(
        jobs=[
            {"name": reuse.SURFACE_JOB_NAMES["test-3.14"],
             "status": "completed", "conclusion": "success"},
            {"name": reuse.SURFACE_JOB_NAMES["test-3.11"],
             "status": "completed", "conclusion": "success"},
            {"name": reuse.SURFACE_JOB_NAMES["pyarrow24"],
             "status": "completed", "conclusion": "success"},
        ]
    )
    assert surface_names(ordered) == list(reuse.SURFACE_ORDER)
    assert surface_names(shuffled) == list(reuse.SURFACE_ORDER)
    assert shuffled.mode == ordered.mode
    assert [
        (d.surface, d.reuse, d.reason) for d in shuffled.surfaces
    ] == [(d.surface, d.reuse, d.reason) for d in ordered.surfaces]


# -- 20. input jobs are never mutated ------------------------------------


def test_v2_input_jobs_not_mutated():
    jobs = v2_jobs(missing=("package",))
    snapshot = json.dumps(jobs, sort_keys=True)
    v2_plan(jobs=jobs)
    assert json.dumps(jobs, sort_keys=True) == snapshot


# -- 21. identity-false invariant across many job shapes -----------------


@pytest.mark.parametrize(
    "job_shape",
    [
        [],
        v2_jobs(),
        v2_jobs(missing=("package",)),
        v2_jobs(conclusions={reuse.SURFACE_JOB_NAMES["package"]: "failure"}),
        v2_jobs() + [{"name": reuse.SURFACE_JOB_NAMES["package"],
                      "status": "completed", "conclusion": "success"}],
        v2_jobs(extra=({"name": "lint", "status": "completed",
                        "conclusion": "success"},)),
    ],
    ids=["empty", "all_success", "one_missing", "one_failed", "duplicate",
         "unexpected"],
)
def test_v2_identity_false_invariant_no_surface_may_reuse(job_shape):
    plan = v2_plan(identity_proven=False, identity_reason="no_proof",
                   jobs=job_shape)
    assert plan.mode == reuse.MODE_NO_REUSE
    assert all(d.reuse is False for d in plan.surfaces)
    assert all(
        d.reason == reuse.GLOBAL_IDENTITY_UNPROVEN_REASON for d in plan.surfaces
    )


# -- 22-24. mode ⇔ evidence shape ----------------------------------------


def test_v2_full_reuse_only_when_all_four_reusable():
    all_ok = v2_plan(jobs=v2_jobs())
    assert all_ok.mode == reuse.MODE_FULL_REUSE
    for surface in reuse.SURFACE_ORDER:
        name = reuse.SURFACE_JOB_NAMES[surface]
        plan = v2_plan(jobs=v2_jobs(conclusions={name: "failure"}))
        assert plan.mode != reuse.MODE_FULL_REUSE
        assert plan.mode == reuse.MODE_PARTIAL_REUSE


def test_v2_partial_reuse_iff_mix_of_reusable_and_not():
    for surface in reuse.SURFACE_ORDER:
        name = reuse.SURFACE_JOB_NAMES[surface]
        plan = v2_plan(jobs=v2_jobs(missing=(surface,)))
        assert plan.mode == reuse.MODE_PARTIAL_REUSE
        assert any(d.reuse for d in plan.surfaces)
        assert any(not d.reuse for d in plan.surfaces)
    # A single non-reusable surface still yields a mix (the other three
    # remain reusable) → partial.
    name = reuse.SURFACE_JOB_NAMES["test-3.11"]
    plan = v2_plan(jobs=v2_jobs(statuses={name: "in_progress"},
                                conclusions={name: None}))
    assert plan.mode == reuse.MODE_PARTIAL_REUSE


def test_v2_no_reuse_iff_identity_false_or_ambiguous_or_zero_reusable():
    assert v2_plan(identity_proven=False, jobs=v2_jobs()).mode == reuse.MODE_NO_REUSE
    assert v2_plan(
        jobs=v2_jobs() + [{"name": reuse.SURFACE_JOB_NAMES["package"],
                           "status": "completed", "conclusion": "success"}]
    ).mode == reuse.MODE_NO_REUSE
    assert v2_plan(jobs=v2_jobs(extra=({"name": "lint"},))).mode == reuse.MODE_NO_REUSE
    assert v2_plan(jobs=v2_jobs(missing=tuple(reuse.SURFACE_ORDER))).mode == (
        reuse.MODE_NO_REUSE
    )


# -- renderer: deterministic, pinned, never collides with V1 -------------


def test_render_reuse_plan_exact_block():
    plan = v2_plan(
        identity_reason="verified_tree_identity",
        jobs=v2_jobs(missing=("package",)),
    )
    assert reuse.render_reuse_plan(plan) == (
        "POST_MERGE_REUSE_MODE=partial_reuse\n"
        "IDENTITY_PROVEN=true\n"
        "identity_reason=verified_tree_identity\n"
        "REUSE_TEST_311=true\n"
        "REUSE_TEST_314=true\n"
        "REUSE_PYARROW24=true\n"
        "REUSE_PACKAGE=false\n"
        "reason_test_311=verified_job_success\n"
        "reason_test_314=verified_job_success\n"
        "reason_pyarrow24=verified_job_success\n"
        "reason_package=job_missing\n"
    )


def test_render_reuse_plan_newline_terminated_and_deterministic():
    plan = v2_plan(identity_proven=False, identity_reason="no_proof",
                   jobs=v2_jobs())
    first = reuse.render_reuse_plan(plan)
    second = reuse.render_reuse_plan(plan)
    assert first == second
    assert first.endswith("\n")
    assert first.startswith("POST_MERGE_REUSE_MODE=no_reuse\n")


def test_render_reuse_plan_never_collides_with_v1_contract():
    rendered = reuse.render_reuse_plan(
        v2_plan(jobs=v2_jobs(missing=("package",)))
    )
    # V1 ci.yml parses POST_MERGE_REUSE= exactly; the V2 renderer must not
    # emit that key and must not be parseable as a V1 verdict.
    assert "POST_MERGE_REUSE=" not in rendered
    assert rendered.splitlines()[0] == "POST_MERGE_REUSE_MODE=partial_reuse"
    v1 = reuse.render_verdict(
        reuse.Verdict(reuse=True, reason=reuse.REUSE_OK_REASON,
                      pr_number=PR_NUMBER, pr_head_sha=HEAD, pr_run_id=RUN_ID,
                      tested_merge_sha=MERGE, tested_tree_sha=TREE,
                      main_sha=MAIN, main_tree_sha=TREE)
    )
    assert v1 == (
        "POST_MERGE_REUSE=true\n"
        "reason=verified_full_pr_tree_equivalence\n"
        f"pr_number={PR_NUMBER}\n"
        f"pr_head_sha={HEAD}\n"
        f"pr_run_id={RUN_ID}\n"
        f"tested_merge_sha={MERGE}\n"
        f"tested_tree_sha={TREE}\n"
        f"main_sha={MAIN}\n"
        f"main_tree_sha={TREE}\n"
    )


# -- 25-26. V1 production behavior unchanged (foundation is inert) -------


def test_v2_foundation_does_not_change_v1_happy_path():
    v = run_verifier()
    assert v.reuse is True
    assert marker_of(v) == "true"
    assert v.reason == reuse.REUSE_OK_REASON


def test_v2_foundation_does_not_change_v1_missing_job_behavior():
    jobs = [j for j in make_all_jobs() if j["name"] != "package"]
    v = run_verifier(api_kwargs={"jobs": jobs})
    assert v.reuse is False
    assert v.reason == "jobs_missing_surface"
    assert marker_of(v) == "false"
