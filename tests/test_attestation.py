"""Offline tests for the FULL attestation contract: deterministic JSON,
exact schema, strict validation, zip safety, and creation from CI
environment context."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from ci_optimizer.attestation import (
    ATTESTATION_FIELD_ORDER,
    ATTESTATION_FILENAME,
    ATTESTATION_MAX_BYTES,
    attestation_artifact_name,
    build_attestation,
    create_attestation,
    parse_attestation_zip,
    serialize_attestation,
    validate_attestation,
    validate_attestation_fields,
)
from ci_optimizer.git import GitError

from .conftest import ATTEMPT, BASE, HEAD, MAIN, MERGE, PREFIX, PR_NUMBER, REPO, RUN_ID, TREE


def make_attestation(**over: object) -> dict:
    data = build_attestation(
        repository=REPO,
        workflow="CI",
        run_id=RUN_ID,
        run_attempt=ATTEMPT,
        pr_number=PR_NUMBER,
        base_sha=BASE,
        head_sha=HEAD,
        tested_merge_sha=MERGE,
        tested_tree_sha=TREE,
    )
    data.update(over)
    return data


def attestation_zip_bytes(data: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            ATTESTATION_FILENAME,
            json.dumps(data if data is not None else make_attestation()),
        )
    return buf.getvalue()


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
    }
    run.update(over)
    return run


def make_pr(**over: object) -> dict:
    pr = {"number": PR_NUMBER, "base": {"sha": BASE}, "head": {"sha": HEAD}}
    pr.update(over)
    return pr


class FakeGit:
    def __init__(self, tree: str = TREE):
        self.tree = tree

    def rev_parse_tree(self, sha: str) -> str:
        if sha != MAIN or not self.tree:
            raise GitError("git_tree_failed")
        return self.tree


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


# ---------------------------------------------------------------------------
# Naming, building, serializing.
# ---------------------------------------------------------------------------


def test_artifact_name_is_attempt_bound() -> None:
    assert attestation_artifact_name(PREFIX, HEAD, ATTEMPT) == (
        f"{PREFIX}{HEAD}-attempt-{ATTEMPT}"
    )
    assert attestation_artifact_name(PREFIX, HEAD, 2) != (
        attestation_artifact_name(PREFIX, HEAD, 1)
    )


def test_build_attestation_fixed_field_order() -> None:
    data = build_attestation(
        repository=REPO, workflow="CI", run_id=RUN_ID, run_attempt=ATTEMPT,
        pr_number=PR_NUMBER, base_sha=BASE, head_sha=HEAD,
        tested_merge_sha=MERGE, tested_tree_sha=TREE,
    )
    assert list(data.keys()) == list(ATTESTATION_FIELD_ORDER)
    assert data["tier"] == "full"
    assert data["full_matrix_required"] is True


def test_serialize_attestation_deterministic_newline_terminated() -> None:
    first = serialize_attestation(make_attestation())
    second = serialize_attestation(make_attestation())
    assert first == second
    assert first.endswith("\n")
    assert json.loads(first) == make_attestation()


# ---------------------------------------------------------------------------
# Strict schema validation.
# ---------------------------------------------------------------------------


def test_valid_attestation_passes_fields() -> None:
    ok, reason = validate_attestation_fields(make_attestation(), workflow="CI")
    assert ok is True
    assert reason is None


def test_missing_field_rejected() -> None:
    data = make_attestation()
    del data["base_sha"]
    ok, reason = validate_attestation_fields(data, workflow="CI")
    assert ok is False and reason == "attestation_schema_mismatch"


def test_extra_field_rejected() -> None:
    data = make_attestation()
    data["surprise"] = True
    ok, reason = validate_attestation_fields(data, workflow="CI")
    assert ok is False and reason == "attestation_schema_mismatch"


def test_wrong_schema_version_rejected() -> None:
    ok, reason = validate_attestation_fields(make_attestation(schema_version=2), workflow="CI")
    assert ok is False and reason == "attestation_schema_version"


def test_wrong_workflow_rejected() -> None:
    ok, reason = validate_attestation_fields(make_attestation(workflow="Other"), workflow="CI")
    assert ok is False and reason == "attestation_wrong_workflow"


def test_tier_not_full_rejected() -> None:
    ok, reason = validate_attestation_fields(make_attestation(tier="docs_fast"), workflow="CI")
    assert ok is False and reason == "attestation_wrong_tier"


def test_full_matrix_required_false_rejected() -> None:
    data = make_attestation(full_matrix_required=False)
    ok, reason = validate_attestation_fields(data, workflow="CI")
    assert ok is False and reason == "attestation_wrong_full_matrix"


@pytest.mark.parametrize(
    "field", ["base_sha", "head_sha", "tested_merge_sha", "tested_tree_sha"]
)
def test_bad_sha_format_rejected(field: str) -> None:
    data = make_attestation(**{field: "garbage"})
    ok, reason = validate_attestation_fields(data, workflow="CI")
    assert ok is False and reason == "attestation_bad_sha"


@pytest.mark.parametrize(
    "field", ["run_id", "run_attempt", "pr_number"]
)
def test_bad_int_type_rejected(field: str) -> None:
    data = make_attestation(**{field: "60"})
    ok, reason = validate_attestation_fields(data, workflow="CI")
    assert ok is False and reason == f"attestation_bad_{field}"


def test_empty_repository_rejected() -> None:
    ok, reason = validate_attestation_fields(make_attestation(repository=""), workflow="CI")
    assert ok is False and reason == "attestation_bad_repository"


def test_non_int_identifier_rejected() -> None:
    ok, reason = validate_attestation_fields(make_attestation(run_id=0), workflow="CI")
    assert ok is False and reason == "attestation_bad_run_id"


# ---------------------------------------------------------------------------
# Zip parsing (extraction safety + size cap).
# ---------------------------------------------------------------------------


def test_parse_valid_zip() -> None:
    data, reason = parse_attestation_zip(attestation_zip_bytes())
    assert reason is None
    assert data["head_sha"] == HEAD


@pytest.mark.parametrize(
    "raw", [b"this is not a zip", b"", b"\x00\x01\x02"]
)
def test_malformed_zip_rejected(raw: bytes) -> None:
    data, reason = parse_attestation_zip(raw)
    assert reason == "attestation_zip_malformed"


def test_zip_with_extra_member_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other.json", "{}")
        zf.writestr(ATTESTATION_FILENAME, "{}")
    data, reason = parse_attestation_zip(buf.getvalue())
    assert reason == "attestation_zip_malformed"


def test_zip_wrong_member_name_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("not_the_attestation.json", "{}")
    data, reason = parse_attestation_zip(buf.getvalue())
    assert reason == "attestation_zip_malformed"


def test_zip_oversize_member_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(ATTESTATION_FILENAME, "x" * (ATTESTATION_MAX_BYTES + 1))
    data, reason = parse_attestation_zip(buf.getvalue())
    assert reason == "attestation_zip_malformed"


def test_zip_invalid_json_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(ATTESTATION_FILENAME, "{not json")
    data, reason = parse_attestation_zip(buf.getvalue())
    assert reason == "attestation_json_malformed"


def test_zip_non_dict_json_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(ATTESTATION_FILENAME, "[1, 2]")
    data, reason = parse_attestation_zip(buf.getvalue())
    assert reason == "attestation_json_malformed"


# ---------------------------------------------------------------------------
# Identifier cross-checks against the proven context.
# ---------------------------------------------------------------------------


def context(**over: object) -> dict:
    ctx = {
        "repository": REPO,
        "workflow": "CI",
        "run": make_run(),
        "pr": make_pr(),
        "before_sha": BASE,
        "head_sha": HEAD,
    }
    ctx.update(over)
    return ctx


def test_valid_attestation_passes_identifier_cross_checks() -> None:
    ok, reason = validate_attestation(make_attestation(), **context())
    assert ok is True and reason is None


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("repository", "other/repo", "attestation_wrong_repository"),
        ("run_id", RUN_ID + 1, "attestation_wrong_run_id"),
        ("run_attempt", ATTEMPT + 1, "attestation_wrong_run_attempt"),
        ("pr_number", PR_NUMBER + 1, "attestation_wrong_pr"),
        ("base_sha", "e" * 40, "attestation_wrong_base"),
        ("head_sha", "e" * 40, "attestation_wrong_head"),
    ],
)
def test_identifier_mismatch_rejected(field: str, value: object, reason: str) -> None:
    data = make_attestation(**{field: value})
    ok, got = validate_attestation(data, **context())
    assert ok is False and got == reason


def test_run_context_mismatch_rejected() -> None:
    ok, got = validate_attestation(
        make_attestation(),
        **context(run=make_run(id=RUN_ID + 1, run_attempt=ATTEMPT)),
    )
    assert ok is False and got == "attestation_wrong_run_id"


# ---------------------------------------------------------------------------
# Creation from CI environment context.
# ---------------------------------------------------------------------------


def test_create_attestation_writes_deterministic_json(tmp_path) -> None:
    out = tmp_path / "ci_full_attestation.json"
    rc = create_attestation(str(out), env=fake_create_env(tmp_path), git=FakeGit())
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    data = json.loads(text)
    assert list(data.keys()) == list(ATTESTATION_FIELD_ORDER)
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


def test_create_attestation_is_byte_deterministic(tmp_path) -> None:
    env = fake_create_env(tmp_path)
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    assert create_attestation(str(first), env=env, git=FakeGit()) == 0
    assert create_attestation(str(second), env=env, git=FakeGit()) == 0
    assert first.read_bytes() == second.read_bytes()


def test_create_attestation_missing_run_context_fails(tmp_path) -> None:
    env = fake_create_env(tmp_path)
    del env["GITHUB_RUN_ID"]
    out = tmp_path / "x.json"
    assert create_attestation(str(out), env=env, git=FakeGit()) == 1
    assert not out.exists()


def test_create_attestation_missing_repository_fails(tmp_path) -> None:
    env = fake_create_env(tmp_path)
    del env["GITHUB_REPOSITORY"]
    out = tmp_path / "x.json"
    assert create_attestation(str(out), env=env, git=FakeGit()) == 1
    assert not out.exists()


def test_create_attestation_non_pr_event_fails(tmp_path) -> None:
    env = fake_create_env(tmp_path, event={"ref": "refs/heads/main"})
    out = tmp_path / "x.json"
    assert create_attestation(str(out), env=env, git=FakeGit()) == 1
    assert not out.exists()


def test_create_attestation_missing_event_file_fails(tmp_path) -> None:
    env = fake_create_env(tmp_path)
    del env["GITHUB_EVENT_PATH"]
    out = tmp_path / "x.json"
    assert create_attestation(str(out), env=env, git=FakeGit()) == 1
    assert not out.exists()


def test_create_attestation_git_failure_fails(tmp_path) -> None:
    out = tmp_path / "x.json"
    assert create_attestation(str(out), env=fake_create_env(tmp_path), git=FakeGit(tree="")) == 1
    assert not out.exists()
