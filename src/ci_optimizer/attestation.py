"""FULL CI attestation: deterministic, strict, attempt-bound.

The attestation records exactly what a FULL pull_request run tested: the
synthetic PR merge commit, its tree, and the identifiers that bind the
evidence (repository, workflow, run, attempt, PR, base, head, tier).

Strict requirements:
- deterministic JSON: stable key order, UTF-8, newline-terminated
- exact schema: unknown fields are rejected
- size cap on the zip member
- zip extraction safety: exactly one member, no traversal
- run/attempt binding and repository binding
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .git import Git, GitError, SHA_RE

ATTESTATION_SCHEMA_VERSION = 1
ATTESTATION_FILENAME = "ci_full_attestation.json"
ATTESTATION_MAX_BYTES = 64 * 1024  # zip member size cap (fail-closed)

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


def attestation_artifact_name(prefix: str, head_sha: str, run_attempt: int) -> str:
    """Attempt-bound artifact name: <prefix><head_sha>-attempt-<attempt>."""
    return f"{prefix}{head_sha}-attempt-{run_attempt}"


def build_attestation(
    *,
    repository: str,
    workflow: str,
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
        "workflow": workflow,
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


def validate_attestation_fields(
    data: dict, *, workflow: str
) -> tuple[bool, str | None]:
    """Strict attestation schema validation: exact key set, exact types,
    exact literal contract values, well-formed SHA fields."""
    if set(data.keys()) != set(ATTESTATION_FIELD_ORDER):
        return False, "attestation_schema_mismatch"
    if data.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        return False, "attestation_schema_version"
    if data.get("workflow") != workflow:
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


def parse_attestation_zip(data: bytes) -> tuple[dict, str | None]:
    """The attestation artifact zip must contain exactly the attestation
    JSON, small, well-formed."""
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


def validate_attestation(
    data: dict,
    *,
    repository: str,
    workflow: str,
    run: dict,
    pr: dict,
    before_sha: str,
    head_sha: str,
) -> tuple[bool, str | None]:
    """Strict schema validation plus all identifier cross-checks against
    the proven context."""
    ok, reason = validate_attestation_fields(data, workflow=workflow)
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


def create_attestation(
    out_path: str,
    *,
    env: dict[str, str],
    git: Git,
    workflow: str = "CI",
) -> int:
    """Create the FULL attestation from CI environment context, strictly
    validate it, and write deterministic UTF-8 JSON. Any failure exits 1
    so the package job fails (attestation absence must never enable
    reuse)."""
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
        workflow=workflow,
        run_id=run_id,
        run_attempt=run_attempt,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
        tested_merge_sha=tested_merge_sha,
        tested_tree_sha=tested_tree_sha,
    )
    ok, reason = validate_attestation_fields(data, workflow=workflow)
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
