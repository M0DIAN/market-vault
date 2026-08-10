"""CI post-merge FULL reuse gate (PR #61).

For an eligible push to ``main``, this verifier may authorize the workflow to
reuse the evidence of a successfully completed final PR FULL run instead of
running the FULL matrix again. Reuse is authorized ONLY when every condition
below can be PROVEN; if any proof is missing, ambiguous, stale, malformed,
unreachable, or fails, the verifier prints ``POST_MERGE_REUSE=false`` with a
specific ``reason=`` and the workflow fail-closes to NORMAL FULL validation.
Reuse failure is never itself a CI failure and never skips validation.

Conditions (all must pass):

1. Event shape: ``push`` event on ``refs/heads/main`` with a real non-zero
   ``github.event.before`` and a real ``github.sha``.
2. Commit topology: the new main commit has exactly one parent and that
   parent equals ``github.event.before`` (single-commit squash push; no
   multi-commit push, no merge-commit push, no root commit).
3. Associated PR: exactly one merged PR is associated with the exact new
   main commit (``merge_commit_sha`` == main SHA, ``base.ref`` == main,
   recorded PR base SHA == ``github.event.before``). The PR head SHA is
   captured exactly.
4. Successful exact-head PR CI: a completed, successful ``pull_request``
   workflow run of the same CI workflow on the exact PR head SHA. Pending /
   failed / cancelled / skipped / neutral / timed_out / action_required /
   stale-older-head runs are never accepted.
5. Required job conclusions: the selected run's jobs terminate with SUCCESS
   on exactly the four required surfaces (test (3.11), test (3.14),
   portability-pyarrow24, package). No missing / duplicate / extra / non-
   success job.
6. Attestation: the attempt-bound attestation artifact produced by that
   exact run/attempt is downloaded and strictly schema-validated; its
   repository / run_id / run_attempt / pr_number / base_sha / head_sha /
   tier / full_matrix_required must all match the proven context.
7. TREE EQUIVALENCE (the core safety proof): ``git rev-parse
   <main sha>^{tree}`` must equal the attestation's ``tested_tree_sha``.
   Commit SHA equality is NOT expected (the synthetic PR merge commit and
   the squash commit have different identities); TREE equality is required.
8. Control-plane exclusion: even with tree equivalence, reuse is denied
   when the merged change touches CI / release safety control-plane paths
   (see CONTROL_PLANE_PATHS; rename old+new paths both count). Unknown
   errors resolving changed paths also deny reuse.

The verifier has a separately testable pure verification core (the
``check_*`` / ``select_*`` / ``validate_*`` functions, no I/O) and a thin
read-only GitHub REST API adapter (``GitHubAPI``) plus a minimal ``Git``
wrapper. No ``shell=True``, no ``eval``, no arbitrary command construction,
no writes outside an explicit output path (only ``--create-attestation``
writes anything), no repository / tag / ref mutation.

This module also creates the PR FULL attestation artifact
(``--create-attestation <path>``): deterministic UTF-8 JSON with stable key
ordering, newline-terminated, strictly schema-validated before writing.

The GitHub token is never printed. The token is only ever sent to
``api.github.com``; cross-host redirects (artifact CDN) strip it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Constants (the gate contract).
# ---------------------------------------------------------------------------

ATTESTATION_SCHEMA_VERSION = 1
ATTESTATION_WORKFLOW_NAME = "CI"
ATTESTATION_FILENAME = "ci_full_attestation.json"
ATTESTATION_ARTIFACT_PREFIX = "market-vault-full-ci-attestation-"
ATTESTATION_MAX_BYTES = 64 * 1024  # zip member size cap (fail-closed)

CI_WORKFLOW_NAME = "CI"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
MAIN_REF = "refs/heads/main"
ZERO_SHA = "0" * 40

REQUIRED_JOB_SURFACES = (
    "test (3.11)",
    "test (3.14)",
    "portability-pyarrow24",
    "package",
)

# Control-plane paths: a merged change touching any of these denies reuse
# (normal FULL validation). The release checker and the risk-tier
# classifier are control-plane; the gate contract files themselves are
# control-plane, which intentionally makes this PR's own main-push run
# ineligible for reuse.
CONTROL_PLANE_PATHS = (
    ".github/workflows/",  # directory prefix
    "scripts/ci_post_merge_reuse.py",
    "scripts/ci_risk_tier.py",
    "scripts/audit_pr.py",
    "scripts/check_release.py",
    "ci/components.toml",
    "tests/test_v061_ci_auditability.py",
    "tests/test_ci_post_merge_reuse.py",
)

# The exact attestation field order (deterministic JSON key ordering).
ATTESTATION_FIELD_ORDER = (
    "schema_version",
    "repository",
    "workflow",
    "run_id",
    "run_attempt",
    "pr_number",
    "base_sha",
    "head_sha",
    "tested_merge_sha",
    "tested_tree_sha",
    "tier",
    "full_matrix_required",
)

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

REUSE_OK_REASON = "verified_full_pr_tree_equivalence"

# The exact log block emitted on successful reuse (order fixed; the token is
# never part of it).
REUSE_LOG_KEYS = (
    "pr_number",
    "pr_head_sha",
    "pr_run_id",
    "tested_merge_sha",
    "tested_tree_sha",
    "main_sha",
    "main_tree_sha",
)


# ---------------------------------------------------------------------------
# Verdict.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The verifier's single decision. ``reuse`` is True only when every
    condition is proven; every other outcome is ``reuse=False`` with a
    specific ``reason``."""

    reuse: bool
    reason: str
    pr_number: int | None = None
    pr_head_sha: str | None = None
    pr_run_id: int | None = None
    tested_merge_sha: str | None = None
    tested_tree_sha: str | None = None
    main_sha: str | None = None
    main_tree_sha: str | None = None


def render_verdict(verdict: Verdict) -> str:
    """Render the verdict as the machine-readable log block the workflow
    parses. Newline-terminated; the GitHub token never appears."""
    lines = [
        f"POST_MERGE_REUSE={'true' if verdict.reuse else 'false'}",
        f"reason={verdict.reason}",
    ]
    if verdict.reuse:
        values = {
            "pr_number": verdict.pr_number,
            "pr_head_sha": verdict.pr_head_sha,
            "pr_run_id": verdict.pr_run_id,
            "tested_merge_sha": verdict.tested_merge_sha,
            "tested_tree_sha": verdict.tested_tree_sha,
            "main_sha": verdict.main_sha,
            "main_tree_sha": verdict.main_tree_sha,
        }
        for key in REUSE_LOG_KEYS:
            lines.append(f"{key}={values[key]}")
    return "\n".join(lines) + "\n"


def skip_heavy_validation(post_merge_reuse: str | None) -> bool:
    """The ONLY predicate under which a heavy validation step may skip.

    Anything other than the exact literal ``"true"`` — ``false``, unset,
    empty, ``"TRUE"``, garbage — runs heavy validation. The workflow's
    ``if: env.POST_MERGE_REUSE != 'true'`` guards express exactly this
    predicate; the invariant is regression-tested.
    """
    return post_merge_reuse == "true"


# ---------------------------------------------------------------------------
# Pure verification core (no I/O).
# ---------------------------------------------------------------------------


def check_event_shape(
    event_name: str | None,
    ref: str | None,
    before_sha: str | None,
    main_sha: str | None,
) -> str | None:
    """Condition 1 — event shape. Returns a reason on failure, else None."""
    if event_name != "push":
        return "event_not_push"
    if ref != MAIN_REF:
        return "wrong_ref"
    if not before_sha or not SHA_RE.fullmatch(before_sha) or before_sha == ZERO_SHA:
        return "missing_before"
    if not main_sha or not SHA_RE.fullmatch(main_sha):
        return "missing_main_sha"
    return None


def check_topology(parents: tuple[str, ...], before_sha: str) -> str | None:
    """Condition 2 — commit topology. ``parents`` are the parent SHAs of
    the new main commit (git rev-list --parents -n 1)."""
    if not parents:
        return "topology_root_commit"
    if len(parents) != 1:
        return "topology_not_single_parent"
    if parents[0] != before_sha:
        return "topology_parent_mismatch"
    return None


def _is_merged(pr: dict) -> bool:
    """A PR is merged when it is closed with a merge timestamp. The
    commits/pulls endpoint represents merged PRs with ``merged: null`` but
    ``state: closed`` + ``merged_at`` set, so a strict ``merged == true``
    requirement would make reuse unreachable."""
    if pr.get("merged") is False:
        return False
    return pr.get("state") == "closed" and pr.get("merged_at") is not None


def select_merged_pr(
    prs: list[dict], main_sha: str, before_sha: str
) -> tuple[dict | None, str | None]:
    """Condition 3 — exactly one qualifying merged PR associated with the
    exact new main commit. Returns (pr, None) or (None, reason)."""
    qualifying = []
    seen = {"merged": False, "merge_sha": False, "base_ref": False,
            "base_sha": False, "head_sha": False}
    for pr in prs:
        if not _is_merged(pr):
            continue
        seen["merged"] = True
        if pr.get("merge_commit_sha") != main_sha:
            continue
        seen["merge_sha"] = True
        base = pr.get("base") or {}
        if base.get("ref") != "main":
            continue
        seen["base_ref"] = True
        if base.get("sha") != before_sha:
            continue
        seen["base_sha"] = True
        head = pr.get("head") or {}
        head_sha = head.get("sha")
        if not head_sha or not SHA_RE.fullmatch(head_sha):
            continue
        seen["head_sha"] = True
        qualifying.append(pr)
    if not qualifying:
        # Specific reasons, newest failure shape first, so the CI log
        # explains exactly which association condition was not proven.
        if not prs:
            return None, "no_associated_pr"
        if not seen["merged"]:
            return None, "pr_not_merged"
        if not seen["merge_sha"]:
            return None, "merge_commit_sha_mismatch"
        if not seen["base_ref"]:
            return None, "pr_base_ref_mismatch"
        if not seen["base_sha"]:
            return None, "pr_base_sha_mismatch"
        return None, "pr_missing_head_sha"
    if len(qualifying) > 1:
        return None, "multiple_associated_prs"
    return qualifying[0], None


def select_successful_runs(runs: list[dict], head_sha: str) -> list[dict]:
    """Condition 4 — completed, successful pull_request runs of the same CI
    workflow on the exact PR head SHA, newest-first. Anything queued /
    in_progress / failed / cancelled / skipped / neutral / timed_out /
    action_required / wrong-event / wrong-workflow / wrong-head is
    excluded; an older head is excluded by the exact head_sha filter."""
    def _is_hex_equal(a: str, b: str) -> bool:
        return a.lower() == b.lower()

    candidates = []
    for run in runs:
        if run.get("event") != "pull_request":
            continue
        if run.get("name") != CI_WORKFLOW_NAME:
            continue
        if run.get("path") != CI_WORKFLOW_PATH:
            continue
        if not _is_hex_equal(run.get("head_sha") or "", head_sha):
            continue
        if run.get("status") != "completed":
            continue
        if run.get("conclusion") != "success":
            continue
        candidates.append(run)
    candidates.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return candidates


def check_jobs(jobs: list[dict]) -> tuple[bool, str | None]:
    """Condition 5 — the selected run's jobs must terminate SUCCESS on
    exactly the four required surfaces: no missing job, no duplicate, no
    non-success conclusion, no extra job (fail-closed if the workflow
    surface ever changes without updating this contract)."""
    names = [str(j.get("name") or "") for j in jobs]
    seen = set()
    for name in names:
        if name in seen:
            return False, "jobs_duplicate"
        seen.add(name)
    if set(seen) != set(REQUIRED_JOB_SURFACES):
        missing = set(REQUIRED_JOB_SURFACES) - set(seen)
        extra = set(seen) - set(REQUIRED_JOB_SURFACES)
        if missing:
            return False, "jobs_missing_surface"
        return False, "jobs_unexpected"
    by_name = {str(j.get("name")): j for j in jobs}
    for surface in REQUIRED_JOB_SURFACES:
        job = by_name[surface]
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            return False, "jobs_non_success"
    return True, None


def attestation_artifact_name(head_sha: str, run_attempt: int) -> str:
    return f"{ATTESTATION_ARTIFACT_PREFIX}{head_sha}-attempt-{run_attempt}"


def select_attestation_artifact(
    artifacts: list[dict], run: dict, head_sha: str
) -> tuple[dict | None, str | None]:
    """Condition 6a — the attempt-bound attestation artifact of the
    selected run. Exactly one, not expired, plausibly sized."""
    run_attempt = run.get("run_attempt")
    expected = attestation_artifact_name(head_sha, int(run_attempt) if run_attempt else 0)
    matches = [a for a in artifacts if str(a.get("name") or "") == expected]
    if not matches:
        return None, "attestation_artifact_missing"
    if len(matches) > 1:
        return None, "attestation_artifact_ambiguous"
    artifact = matches[0]
    if artifact.get("expired"):
        return None, "attestation_artifact_expired"
    size = artifact.get("size_in_bytes")
    if size is None or size <= 0 or size > ATTESTATION_MAX_BYTES:
        return None, "attestation_artifact_too_large"
    return artifact, None


def parse_attestation_zip(data: bytes) -> tuple[dict, str | None]:
    """Condition 6b — the attestation artifact zip must contain exactly the
    attestation JSON, small, well-formed."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {}, "attestation_zip_malformed"
    names = zf.namelist()
    if names != [ATTESTATION_FILENAME]:
        return {}, "attestation_zip_malformed"
    info = zf.getinfo(ATTESTATION_FILENAME)
    if info.file_size > ATTESTATION_MAX_BYTES:
        return {}, "attestation_zip_malformed"
    try:
        text = zf.read(ATTESTATION_FILENAME).decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return {}, "attestation_zip_malformed"
    try:
        data_obj = json.loads(text)
    except ValueError:
        return {}, "attestation_json_malformed"
    if not isinstance(data_obj, dict):
        return {}, "attestation_json_malformed"
    return data_obj, None


def validate_attestation_fields(data: dict) -> tuple[bool, str | None]:
    """Strict attestation schema validation: exact key set, exact types,
    exact literal contract values, well-formed SHA fields."""
    if set(data.keys()) != set(ATTESTATION_FIELD_ORDER):
        return False, "attestation_schema_mismatch"
    if data.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        return False, "attestation_schema_version"
    if data.get("workflow") != ATTESTATION_WORKFLOW_NAME:
        return False, "attestation_wrong_workflow"
    if data.get("tier") != "full":
        return False, "attestation_wrong_tier"
    if data.get("full_matrix_required") is not True:
        return False, "attestation_wrong_full_matrix"
    for field_name in ("base_sha", "head_sha", "tested_merge_sha", "tested_tree_sha"):
        value = data.get(field_name)
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            return False, "attestation_bad_sha"
    if not isinstance(data.get("run_id"), int) or data["run_id"] <= 0:
        return False, "attestation_bad_run_id"
    if not isinstance(data.get("run_attempt"), int) or data["run_attempt"] <= 0:
        return False, "attestation_bad_run_attempt"
    if not isinstance(data.get("pr_number"), int) or data["pr_number"] <= 0:
        return False, "attestation_bad_pr_number"
    if not isinstance(data.get("repository"), str) or not data["repository"]:
        return False, "attestation_bad_repository"
    return True, None


def validate_attestation(
    data: dict,
    *,
    repository: str,
    run: dict,
    pr: dict,
    before_sha: str,
    head_sha: str,
) -> tuple[bool, str | None]:
    """Condition 6 — strict schema validation plus all identifier
    cross-checks against the proven context."""
    ok, reason = validate_attestation_fields(data)
    if not ok:
        return False, reason
    if data["repository"] != repository:
        return False, "attestation_wrong_repository"
    if data["run_id"] != run.get("id"):
        return False, "attestation_wrong_run_id"
    if data["run_attempt"] != run.get("run_attempt"):
        return False, "attestation_wrong_run_attempt"
    if data["pr_number"] != pr.get("number"):
        return False, "attestation_wrong_pr"
    if data["base_sha"] != before_sha:
        return False, "attestation_wrong_base"
    if data["head_sha"] != head_sha:
        return False, "attestation_wrong_head"
    return True, None


def check_tree_equivalence(main_tree_sha: str, tested_tree_sha: str) -> bool:
    """Condition 7 — THE core safety proof: the current main tree must be
    byte-for-byte Git-tree-equivalent to the tree the PR FULL run tested."""
    return bool(main_tree_sha) and main_tree_sha == tested_tree_sha


def check_control_plane(changed_paths: list[str]) -> tuple[bool, str | None]:
    """Condition 8 — control-plane exclusion. Any changed path inside
    ``.github/workflows/`` or equal to a listed control-plane file denies
    reuse (rename old+new paths are both included by the Git layer)."""
    for path in changed_paths:
        normalized = path.replace("\\", "/")
        if normalized.startswith(".github/workflows/"):
            return False, "control_plane_changed"
        if normalized in CONTROL_PLANE_PATHS:
            return False, "control_plane_changed"
    return True, None


# ---------------------------------------------------------------------------
# Attestation creation (deterministic JSON, strict validation before write).
# ---------------------------------------------------------------------------


def build_attestation(
    *,
    repository: str,
    run_id: int,
    run_attempt: int,
    pr_number: int,
    base_sha: str,
    head_sha: str,
    tested_merge_sha: str,
    tested_tree_sha: str,
) -> dict:
    """Build the attestation dict in the exact fixed field order."""
    return {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "repository": repository,
        "workflow": ATTESTATION_WORKFLOW_NAME,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "pr_number": pr_number,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "tested_merge_sha": tested_merge_sha,
        "tested_tree_sha": tested_tree_sha,
        "tier": "full",
        "full_matrix_required": True,
    }


def serialize_attestation(data: dict) -> str:
    """Deterministic JSON: stable key ordering, newline-terminated."""
    return json.dumps(data, indent=2, ensure_ascii=True) + "\n"


def create_attestation(out_path: str, *, env: dict[str, str], git: "Git") -> int:
    """Create the PR FULL attestation from CI environment context, strictly
    validate it, and write deterministic UTF-8 JSON. Any failure exits 1 so
    the package job fails (attestation absence must never enable reuse)."""
    try:
        run_id = int(env["GITHUB_RUN_ID"])
        run_attempt = int(env["GITHUB_RUN_ATTEMPT"])
    except (KeyError, ValueError):
        return _create_failed("attestation_missing_run_context")
    repository = env.get("GITHUB_REPOSITORY")
    if not repository:
        return _create_failed("attestation_missing_repository")
    tested_merge_sha = env.get("GITHUB_SHA")
    if not tested_merge_sha or not SHA_RE.fullmatch(tested_merge_sha):
        return _create_failed("attestation_missing_merge_sha")
    event_path = env.get("GITHUB_EVENT_PATH")
    if not event_path:
        return _create_failed("attestation_missing_event")
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _create_failed("attestation_event_unreadable")
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        return _create_failed("attestation_not_pull_request")
    base_sha = (pr.get("base") or {}).get("sha")
    head_sha = (pr.get("head") or {}).get("sha")
    pr_number = pr.get("number")
    if (
        not base_sha
        or not head_sha
        or not isinstance(pr_number, int)
        or not SHA_RE.fullmatch(base_sha)
        or not SHA_RE.fullmatch(head_sha)
    ):
        return _create_failed("attestation_bad_pr_context")
    try:
        tested_tree_sha = git.rev_parse_tree(tested_merge_sha)
    except GitError as exc:
        return _create_failed(exc.reason)
    data = build_attestation(
        repository=repository,
        run_id=run_id,
        run_attempt=run_attempt,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
        tested_merge_sha=tested_merge_sha,
        tested_tree_sha=tested_tree_sha,
    )
    ok, reason = validate_attestation_fields(data)
    if not ok:
        return _create_failed(reason)
    target = Path(out_path)
    target.write_text(serialize_attestation(data), encoding="utf-8", newline="\n")
    print(f"FULL_CI_ATTESTATION_CREATED {target}")
    print(f"tested_tree_sha={tested_tree_sha}")
    return 0


def _create_failed(reason: str) -> int:
    print(f"FULL_CI_ATTESTATION_FAILED reason={reason}")
    return 1


# ---------------------------------------------------------------------------
# GitHub REST API adapter (read-only, thin; the token is never printed).
# ---------------------------------------------------------------------------


class APIError(Exception):
    """A GitHub API failure with a specific fail-closed reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _NoTokenRedirect(urllib.request.HTTPRedirectHandler):
    """Follow GitHub's artifact 302 to the CDN without forwarding the
    Bearer token (the signed CDN URL needs none)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and new.host != req.host:
            new.remove_header("Authorization")
        return new


def _default_urlopen() -> Callable[..., Any]:
    opener = urllib.request.build_opener(_NoTokenRedirect())
    return opener.open


class GitHubAPI:
    """Read-only GitHub REST client (contents: read / pull-requests: read /
    actions: read only). ``urlopen`` is injectable for offline tests."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        urlopen: Callable[..., Any] | None = None,
        timeout: int = 30,
    ):
        self.repository = repository
        self.token = token
        self._urlopen = urlopen if urlopen is not None else _default_urlopen()
        self.timeout = timeout

    # -- low-level ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "market-vault-post-merge-reuse",
        }

    def _get(self, url: str) -> tuple[int, bytes, Any]:
        request = urllib.request.Request(url, headers=self._headers())
        try:
            response = self._urlopen(request, timeout=self.timeout)
            return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers
        except (urllib.error.URLError, TimeoutError):
            raise APIError("network_error")

    def _api_url(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"https://api.github.com{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    @staticmethod
    def _next_page_url(link_header: str) -> str | None:
        for part in link_header.split(","):
            url, _, rel = part.partition(";")
            if 'rel="next"' in rel:
                return url.strip().strip("<>")
        return None

    def _get_list_json(
        self, path: str, params: dict[str, str] | None, key: str | None,
        max_pages: int = 10,
    ) -> list[dict]:
        items: list[dict] = []
        url = self._api_url(path, params)
        for _ in range(max_pages):
            status, body, headers = self._get(url)
            if status == 404:
                raise APIError("api_http_error_404")
            if not 200 <= status < 300:
                raise APIError(f"api_http_error_{status}")
            try:
                data = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise APIError("malformed_api_response")
            if key is None:
                if not isinstance(data, list):
                    raise APIError("malformed_api_response")
                batch = data
            else:
                if not isinstance(data, dict) or not isinstance(data.get(key), list):
                    raise APIError("malformed_api_response")
                batch = data[key]
            items.extend(batch)
            next_url = self._next_page_url(str(headers.get("Link", "")))
            if not next_url:
                return items
            url = next_url
        raise APIError("api_pagination_limit")

    def _download_bytes(self, path: str) -> bytes:
        status, body, _ = self._get(self._api_url(path))
        if status == 404:
            raise APIError("attestation_artifact_download_failed")
        if not 200 <= status < 300:
            raise APIError(f"api_http_error_{status}")
        return body

    # -- queries -----------------------------------------------------------

    def list_pulls_for_commit(self, commit_sha: str) -> list[dict]:
        """GET /repos/{owner}/{repo}/commits/{sha}/pulls (read-only)."""
        return self._get_list_json(
            f"/repos/{self.repository}/commits/{commit_sha}/pulls", None, None
        )

    def list_runs_for_head(self, head_sha: str) -> list[dict]:
        """GET /repos/{owner}/{repo}/actions/runs?event=pull_request&head_sha=…"""
        return self._get_list_json(
            f"/repos/{self.repository}/actions/runs",
            {"event": "pull_request", "head_sha": head_sha, "per_page": "100"},
            "workflow_runs",
        )

    def list_jobs(self, run_id: int) -> list[dict]:
        """GET /repos/{owner}/{repo}/actions/runs/{id}/jobs"""
        return self._get_list_json(
            f"/repos/{self.repository}/actions/runs/{run_id}/jobs",
            {"per_page": "100"},
            "jobs",
        )

    def list_artifacts(self, run_id: int) -> list[dict]:
        """GET /repos/{owner}/{repo}/actions/runs/{id}/artifacts"""
        return self._get_list_json(
            f"/repos/{self.repository}/actions/runs/{run_id}/artifacts",
            {"per_page": "100"},
            "artifacts",
        )

    def download_artifact(self, artifact_id: int) -> bytes:
        """GET /repos/{owner}/{repo}/actions/artifacts/{id}/zip (follows the
        302 to the signed CDN URL without the token)."""
        return self._download_bytes(
            f"/repos/{self.repository}/actions/artifacts/{artifact_id}/zip"
        )


# ---------------------------------------------------------------------------
# Git wrapper (no shell, no mutation).
# ---------------------------------------------------------------------------


class GitError(Exception):
    """A git invocation failure with a specific fail-closed reason."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class Git:
    """Minimal read-only git wrapper. ``runner`` is injectable for tests."""

    def __init__(self, repo_dir: str = ".", runner: Callable[..., Any] | None = None):
        self.repo_dir = repo_dir
        self._run = runner if runner is not None else self._default_run

    @staticmethod
    def _default_run(cmd: list[str]) -> Any:
        return subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )

    def _git(self, *args: str) -> str:
        proc = self._run(["git", "-C", self.repo_dir, *args])
        if proc.returncode != 0:
            raise GitError(
                "git_error", (proc.stderr or proc.stdout or "").strip()
            )
        return proc.stdout

    def rev_list_parents(self, sha: str) -> tuple[str, ...]:
        """``git rev-list --parents -n 1 <sha>`` -> (parent, ...). Verifies
        the parsed commit identity matches the requested SHA."""
        out = self._git("rev-list", "--parents", "-n", "1", sha).strip()
        parts = out.split() if out else []
        if not parts or parts[0] != sha:
            raise GitError("git_commit_mismatch")
        return tuple(parts[1:])

    def rev_parse_tree(self, sha: str) -> str:
        """``git rev-parse <sha>^{tree}`` -> the tree SHA."""
        out = self._git("rev-parse", f"{sha}^{{tree}}").strip()
        if not SHA_RE.fullmatch(out):
            raise GitError("git_tree_failed")
        return out

    def changed_paths(self, base: str, head: str) -> list[str]:
        """``git diff --name-status -M`` over base..head with NUL separators;
        rename (R/C) old+new paths are both returned, so the control-plane
        check treats renames in either direction."""
        out = self._git(
            "diff", "-z", "--name-status", "-M",
            "--diff-filter=AMDR", base, head,
        )
        parts = out.split("\0")
        paths: list[str] = []
        index = 0
        while index < len(parts):
            status = parts[index]
            index += 1
            if not status:
                continue
            if index >= len(parts):
                raise GitError("git_changed_paths_malformed")
            old = parts[index]
            index += 1
            paths.append(old)
            if status.startswith(("R", "C")):
                if index >= len(parts):
                    raise GitError("git_changed_paths_malformed")
                paths.append(parts[index])
                index += 1
        return paths


# ---------------------------------------------------------------------------
# Orchestrator: proves all conditions in order, fail-closed at every step.
# ---------------------------------------------------------------------------


def _verify_run(
    run: dict,
    *,
    pr: dict,
    repository: str,
    before_sha: str,
    head_sha: str,
    main_sha: str,
    api: GitHubAPI,
    git: Git,
) -> tuple[bool, Any]:
    """Verify one candidate run end-to-end (jobs, attestation, tree,
    control-plane). Returns (True, (attestation_data, main_tree_sha)) on
    success, or (False, specific_reason)."""
    jobs = api.list_jobs(run["id"])
    ok, reason = check_jobs(jobs)
    if not ok:
        return False, reason
    artifacts = api.list_artifacts(run["id"])
    artifact, reason = select_attestation_artifact(artifacts, run, head_sha)
    if reason:
        return False, reason
    zip_bytes = api.download_artifact(artifact["id"])
    data, reason = parse_attestation_zip(zip_bytes)
    if reason:
        return False, reason
    ok, reason = validate_attestation(
        data, repository=repository, run=run, pr=pr,
        before_sha=before_sha, head_sha=head_sha,
    )
    if not ok:
        return False, reason
    main_tree = git.rev_parse_tree(main_sha)
    if not check_tree_equivalence(main_tree, data["tested_tree_sha"]):
        return False, "main_tree_mismatch"
    return True, (data, main_tree)


def run_verifier(
    *,
    repository: str,
    event_name: str | None,
    ref: str | None,
    before_sha: str | None,
    main_sha: str | None,
    api: GitHubAPI,
    git: Git,
) -> Verdict:
    """Prove every condition; any failure anywhere yields reuse=False with a
    specific reason. Internal/adapter errors can never produce reuse=True."""
    try:
        reason = check_event_shape(event_name, ref, before_sha, main_sha)
        if reason:
            return Verdict(False, reason)
        assert before_sha is not None and main_sha is not None  # shape-checked
        # Control-plane exclusion is evaluated early (local git, no API):
        # a control-plane merge must not even spend API calls, and must
        # always fall back to normal FULL.
        changed = git.changed_paths(before_sha, main_sha)
        ok, reason = check_control_plane(changed)
        if not ok:
            return Verdict(False, reason)
        parents = git.rev_list_parents(main_sha)
        reason = check_topology(parents, before_sha)
        if reason:
            return Verdict(False, reason)
        prs = api.list_pulls_for_commit(main_sha)
        pr, reason = select_merged_pr(prs, main_sha, before_sha)
        if reason:
            return Verdict(False, reason)
        assert pr is not None
        head_sha = pr["head"]["sha"]
        runs = api.list_runs_for_head(head_sha)
        candidates = select_successful_runs(runs, head_sha)
        if not candidates:
            return Verdict(False, "no_matching_run")
        last_failure = "no_matching_run"
        for run in candidates:
            ok_run, value = _verify_run(
                run, pr=pr, repository=repository, before_sha=before_sha,
                head_sha=head_sha, main_sha=main_sha, api=api, git=git,
            )
            if ok_run:
                data, main_tree = value
                return Verdict(
                    reuse=True,
                    reason=REUSE_OK_REASON,
                    pr_number=pr["number"],
                    pr_head_sha=head_sha,
                    pr_run_id=run["id"],
                    tested_merge_sha=data["tested_merge_sha"],
                    tested_tree_sha=data["tested_tree_sha"],
                    main_sha=main_sha,
                    main_tree_sha=main_tree,
                )
            last_failure = value
        return Verdict(False, last_failure)
    except APIError as exc:
        return Verdict(False, exc.reason)
    except GitError as exc:
        return Verdict(False, exc.reason)
    except Exception:
        # A verifier bug must fail closed to normal FULL, never to skip.
        return Verdict(False, "verifier_internal_error")


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CI post-merge FULL reuse gate (read-only, fail-closed)."
    )
    parser.add_argument(
        "--create-attestation", metavar="PATH",
        help="create the PR FULL attestation JSON at PATH from CI env context",
    )
    parser.add_argument("--repo", help="owner/repo (default $GITHUB_REPOSITORY)")
    parser.add_argument("--event-name", help="event name (default $GITHUB_EVENT_NAME)")
    parser.add_argument("--ref", help="git ref (default $GITHUB_REF)")
    parser.add_argument("--before", help="previous main SHA (default from event file)")
    parser.add_argument("--main-sha", help="pushed main SHA (default $GITHUB_SHA)")
    parser.add_argument("--token-env", default="GITHUB_TOKEN",
                        help="env var holding the token (default GITHUB_TOKEN)")
    return parser.parse_args(argv)


def _print_verdict(verdict: Verdict) -> None:
    sys.stdout.write(render_verdict(verdict))


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    """Entry point. Always exits 0 unless a creation-mode failure requires
    the package job to fail; a proof failure is never a CI failure."""
    env = env if env is not None else os.environ
    args = parse_args(argv)

    if args.create_attestation:
        return create_attestation(args.create_attestation, env=env, git=Git())

    repository = args.repo or env.get("GITHUB_REPOSITORY")
    event_name = args.event_name or env.get("GITHUB_EVENT_NAME")
    ref = args.ref or env.get("GITHUB_REF")
    main_sha = args.main_sha or env.get("GITHUB_SHA")
    token = env.get(args.token_env)

    before_sha = args.before
    if not before_sha:
        event_path = env.get("GITHUB_EVENT_PATH")
        if event_path:
            try:
                event = json.loads(Path(event_path).read_text(encoding="utf-8"))
                before_sha = event.get("before")
            except (OSError, ValueError):
                before_sha = None

    if not repository:
        _print_verdict(Verdict(False, "missing_repo_context"))
        return 0
    if not token:
        _print_verdict(Verdict(False, "missing_token"))
        return 0

    api = GitHubAPI(repository, token)
    git = Git()
    verdict = run_verifier(
        repository=repository,
        event_name=event_name,
        ref=ref,
        before_sha=before_sha,
        main_sha=main_sha,
        api=api,
        git=git,
    )
    _print_verdict(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
