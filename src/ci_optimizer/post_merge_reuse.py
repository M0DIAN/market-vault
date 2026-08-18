"""Post-merge FULL reuse gate (V1).

For an eligible push to the configured main branch, this verifier may
authorize the workflow to reuse the evidence of a successfully completed
final PR FULL run instead of running the FULL matrix again. Reuse is
authorized ONLY when every condition below can be PROVEN; if any proof
is missing, ambiguous, stale, malformed, unreachable, or fails, the
verifier prints ``POST_MERGE_REUSE=false`` with a specific ``reason=``
and the workflow fail-closes to NORMAL FULL validation. Reuse failure is
never itself a CI failure and never skips validation.

Conditions (all must pass):

1. Event shape: ``push`` event on the configured main branch
   (``refs/heads/<main_branch>``) with a real non-zero
   ``github.event.before`` and a real ``github.sha``.
2. Commit topology: the new main commit has exactly one parent and that
   parent equals ``github.event.before`` (single-commit squash push; no
   multi-commit push, no merge-commit push, no root commit).
3. Associated PR: exactly one merged PR is associated with the exact new
   main commit (``merge_commit_sha`` == main SHA, ``base.ref`` ==
   configured main branch, recorded PR base SHA == ``github.event.before``).
   The PR head SHA is captured exactly.
4. Successful exact-head PR CI: a completed, successful ``pull_request``
   workflow run of the configured CI workflow on the exact PR head SHA.
   Pending / failed / cancelled / skipped / neutral / timed_out /
   action_required / stale-older-head runs are never accepted.
5. Required job conclusions: the selected run's jobs terminate with
   SUCCESS on exactly the configured formal job set
   (``[reuse] required_jobs``). No missing / duplicate / unexpected /
   non-success job.
6. Attestation: the attempt-bound attestation artifact produced by that
   exact run/attempt is downloaded and strictly schema-validated; its
   repository / run_id / run_attempt / pr_number / base_sha / head_sha /
   tier / full_matrix_required must all match the proven context.
7. TREE EQUIVALENCE (the core safety proof): ``git rev-parse
   <main sha>^{tree}`` must equal the attestation's ``tested_tree_sha``.
   Commit SHA equality is NOT expected (the synthetic PR merge commit and
   the squash commit have different identities); TREE equality is
   required.
8. Control-plane exclusion: even with tree equivalence, reuse is denied
   when the merged change touches configured control-plane paths
   (``[reuse] control_plane_paths``; rename old+new paths both count).

Critical invariant:

    PROOF FAILURE != CI FAILURE
    reuse=false  =>  fresh validation executes.

``POST_MERGE_REUSE=true`` is emitted only when all proofs succeed.

The verifier has a separately testable pure verification core (the
``check_*`` / ``select_*`` / ``validate_*`` functions, no I/O) and a
thin read-only GitHub REST API adapter. No ``shell=True``, no ``eval``,
no arbitrary command construction, no writes outside an explicit
attestation output path, no repository / tag / ref mutation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .attestation import (
    ATTESTATION_MAX_BYTES,
    attestation_artifact_name,
    parse_attestation_zip,
    validate_attestation,
)
from .github_api import APIError, GitHubAPI
from .git import Git, GitError, SHA_RE
from .policy import Config, rule_matches

ZERO_SHA = "0" * 40

REUSE_OK_REASON = "verified_full_pr_tree_equivalence"

# The exact log block emitted on successful reuse (order fixed; the token
# is never part of it).
REUSE_LOG_KEYS = (
    "pr_number",
    "pr_head_sha",
    "pr_run_id",
    "tested_merge_sha",
    "tested_tree_sha",
    "main_sha",
    "main_tree_sha",
)


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
    *,
    main_ref: str,
) -> str | None:
    """Condition 1 — event shape. Returns a reason on failure, else None."""
    if event_name != "push":
        return "event_not_push"
    if ref != main_ref:
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
    prs: list[dict], main_sha: str, before_sha: str, *, main_branch: str
) -> tuple[dict | None, str | None]:
    """Condition 3 — exactly one qualifying merged PR associated with the
    exact new main commit. Returns (pr, None) or (None, reason)."""
    qualifying = []
    seen = {
        "merged": False,
        "merge_sha": False,
        "base_ref": False,
        "base_sha": False,
        "head_sha": False,
    }
    for pr in prs:
        if not _is_merged(pr):
            continue
        seen["merged"] = True
        if pr.get("merge_commit_sha") != main_sha:
            continue
        seen["merge_sha"] = True
        base = pr.get("base") or {}
        if base.get("ref") != main_branch:
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


def select_successful_runs(
    runs: list[dict],
    head_sha: str,
    *,
    workflow_name: str,
    workflow_path: str,
) -> list[dict]:
    """Condition 4 — completed, successful pull_request runs of the
    configured CI workflow on the exact PR head SHA, newest-first.
    Anything queued / in_progress / failed / cancelled / skipped /
    neutral / timed_out / action_required / wrong-event /
    wrong-workflow / wrong-head is excluded; an older head is excluded by
    the exact head_sha filter."""

    def _is_hex_equal(a: str, b: str) -> bool:
        return a.lower() == b.lower()

    candidates = []
    for run in runs:
        if run.get("event") != "pull_request":
            continue
        if run.get("name") != workflow_name:
            continue
        if run.get("path") != workflow_path:
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


def check_jobs(
    jobs: list[dict], required_jobs: tuple[str, ...]
) -> tuple[bool, str | None]:
    """Condition 5 — the selected run's jobs must terminate SUCCESS on
    exactly the configured formal job set: no missing job, no duplicate,
    no non-success conclusion, no extra job (fail-closed if the workflow
    surface ever changes without updating the config)."""
    names = [str(j.get("name") or "") for j in jobs]
    seen = set()
    for name in names:
        if name in seen:
            return False, "jobs_duplicate"
        seen.add(name)
    if set(seen) != set(required_jobs):
        missing = set(required_jobs) - set(seen)
        extra = set(seen) - set(required_jobs)
        if missing:
            return False, "jobs_missing_surface"
        return False, "jobs_unexpected"
    by_name = {str(j.get("name")): j for j in jobs}
    for surface in required_jobs:
        job = by_name[surface]
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            return False, "jobs_non_success"
    return True, None


def select_attestation_artifact(
    artifacts: list[dict],
    run: dict,
    head_sha: str,
    *,
    prefix: str,
) -> tuple[dict | None, str | None]:
    """Condition 6a — the attempt-bound attestation artifact of the
    selected run. Exactly one, not expired, plausibly sized."""
    run_attempt = run.get("run_attempt")
    expected = attestation_artifact_name(
        prefix, head_sha, int(run_attempt) if run_attempt else 0
    )
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


def check_tree_equivalence(main_tree_sha: str, tested_tree_sha: str) -> bool:
    """Condition 7 — THE core safety proof: the current main tree must be
    byte-for-byte Git-tree-equivalent to the tree the PR FULL run tested."""
    return bool(main_tree_sha) and main_tree_sha == tested_tree_sha


def check_control_plane(
    changed_paths: list[str], control_plane_paths: tuple[str, ...]
) -> tuple[bool, str | None]:
    """Condition 8 — control-plane exclusion. Any changed path inside the
    configured control-plane surface denies reuse (rename old+new paths
    are both included by the git layer)."""
    for path in changed_paths:
        normalized = path.replace("\\", "/")
        if any(rule_matches(rule, normalized) for rule in control_plane_paths):
            return False, "control_plane_changed"
    return True, None


# ---------------------------------------------------------------------------
# Orchestrator: proves all conditions in order, fail-closed at every step.
# ---------------------------------------------------------------------------


def _verify_run(
    run: dict,
    *,
    pr: dict,
    repository: str,
    config: Config,
    before_sha: str,
    head_sha: str,
    main_sha: str,
    api: GitHubAPI,
    git: Git,
) -> tuple[bool, object]:
    """Verify one candidate run end-to-end (jobs, attestation, tree,
    control-plane). Returns (True, (attestation_data, main_tree_sha)) on
    success, or (False, specific_reason)."""
    jobs = api.list_jobs(run["id"])
    ok, reason = check_jobs(jobs, config.required_jobs)
    if not ok:
        return False, reason
    artifacts = api.list_artifacts(run["id"])
    artifact, reason = select_attestation_artifact(
        artifacts, run, head_sha, prefix=config.artifact_prefix
    )
    if reason:
        return False, reason
    zip_bytes = api.download_artifact(artifact["id"])
    data, reason = parse_attestation_zip(zip_bytes)
    if reason:
        return False, reason
    ok, reason = validate_attestation(
        data,
        repository=repository,
        workflow=config.workflow_name,
        run=run,
        pr=pr,
        before_sha=before_sha,
        head_sha=head_sha,
    )
    if not ok:
        return False, reason
    main_tree = git.rev_parse_tree(main_sha)
    if not check_tree_equivalence(main_tree, data["tested_tree_sha"]):
        return False, "main_tree_mismatch"
    return True, (data, main_tree)


def run_verifier(
    *,
    config: Config,
    repository: str,
    event_name: str | None,
    ref: str | None,
    before_sha: str | None,
    main_sha: str | None,
    api: GitHubAPI,
    git: Git,
) -> Verdict:
    """Prove every condition; any failure anywhere yields reuse=False with
    a specific reason. Internal/adapter errors can never produce
    reuse=True."""
    try:
        reason = check_event_shape(
            event_name, ref, before_sha, main_sha, main_ref=config.main_ref
        )
        if reason:
            return Verdict(False, reason)
        assert before_sha is not None and main_sha is not None  # shape-checked
        # Control-plane exclusion is evaluated early (local git, no API):
        # a control-plane merge must not even spend API calls, and must
        # always fall back to normal FULL.
        changed = git.changed_paths(before_sha, main_sha, merge_base=False)
        ok, reason = check_control_plane(changed, config.reuse_control_plane_paths)
        if not ok:
            return Verdict(False, reason)
        parents = git.rev_list_parents(main_sha)
        reason = check_topology(parents, before_sha)
        if reason:
            return Verdict(False, reason)
        prs = api.list_pulls_for_commit(main_sha)
        pr, reason = select_merged_pr(
            prs, main_sha, before_sha, main_branch=config.main_branch
        )
        if reason:
            return Verdict(False, reason)
        assert pr is not None
        head_sha = pr["head"]["sha"]
        runs = api.list_runs_for_head(head_sha)
        candidates = select_successful_runs(
            runs,
            head_sha,
            workflow_name=config.workflow_name,
            workflow_path=config.workflow_path,
        )
        if not candidates:
            return Verdict(False, "no_matching_run")
        last_failure = "no_matching_run"
        for run in candidates:
            ok_run, value = _verify_run(
                run,
                pr=pr,
                repository=repository,
                config=config,
                before_sha=before_sha,
                head_sha=head_sha,
                main_sha=main_sha,
                api=api,
                git=git,
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
