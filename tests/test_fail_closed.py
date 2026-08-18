"""CLI-level fail-closed contract: every config / git / context failure
converts to tier=full (classify) or POST_MERGE_REUSE=false
(verify-reuse), with the documented exit codes. Proof failure is never a
CI failure; attestation failure is."""

from __future__ import annotations

import json
import re

import pytest

from ci_optimizer.cli import build_parser, cmd_classify, cmd_create_attestation, cmd_verify
from ci_optimizer.git import GitError

from .conftest import CONFIG_TEXT


def make_args(*argv: str):
    return build_parser().parse_args(list(argv))


def write_config(tmp_path, text: str = CONFIG_TEXT, name: str = "ciopt.toml") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class FakeGit:
    def __init__(self, paths: list[str] | None = None, fail: str | None = None):
        self.paths = paths or []
        self.fail = fail

    def resolve_ref(self, ref: str) -> None:
        if self.fail == "resolve":
            raise GitError("git_error", f"unknown ref {ref}")

    def changed_paths(self, base: str, head: str, *, merge_base: bool = True) -> list[str]:
        if self.fail == "diff":
            raise GitError("git_changed_paths_malformed")
        return list(self.paths)


# ---------------------------------------------------------------------------
# classify: malformed / missing config -> tier=full, exit 2.
# ---------------------------------------------------------------------------


def test_classify_malformed_config_fails_closed_to_full(tmp_path, capsys) -> None:
    path = write_config(tmp_path, "schema_version = = 1\n")
    args = make_args("classify", "--config", path, "--mode", "pull_request",
                     "--base", "a" * 40, "--head", "b" * 40)
    rc = cmd_classify(args)
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "full"
    assert out["reason"] == "invalid_config_fail_closed"
    assert out["full_matrix_required"] is True
    assert out["error"]


def test_classify_missing_config_fails_closed(tmp_path, capsys) -> None:
    args = make_args("classify", "--config", str(tmp_path / "missing.toml"),
                     "--mode", "push", "--base", "a" * 40, "--head", "b" * 40)
    assert cmd_classify(args) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "full" and out["reason"] == "invalid_config_fail_closed"


def test_classify_unknown_schema_version_fails_closed(tmp_path, capsys) -> None:
    path = write_config(
        tmp_path, CONFIG_TEXT.replace("schema_version = 1", "schema_version = 2")
    )
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40)
    assert cmd_classify(args) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "full" and out["reason"] == "invalid_config_fail_closed"


# ---------------------------------------------------------------------------
# classify: git / ref resolution failure -> tier=full, exit 2.
# ---------------------------------------------------------------------------


def test_classify_git_failure_fails_closed_to_full(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40)
    rc = cmd_classify(args, git=FakeGit(fail="resolve"))
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "full"
    assert out["reason"] == "classifier_error_fail_closed"


def test_classify_diff_failure_fails_closed(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40)
    assert cmd_classify(args, git=FakeGit(fail="diff")) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "full" and out["reason"] == "classifier_error_fail_closed"


# ---------------------------------------------------------------------------
# classify: valid runs, JSON + env output, deterministic key order.
# ---------------------------------------------------------------------------


def test_classify_json_output_shape_and_key_order(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "pull_request",
                     "--base", "a" * 40, "--head", "b" * 40)
    rc = cmd_classify(args, git=FakeGit(paths=["docs/guide.md"]))
    assert rc == 0
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["tier"] == "docs_fast"
    assert out["reason"] == "all_changes_in_docs_scope"
    assert out["full_matrix_required"] is False
    assert out["changed_files"] == 1
    assert out["files"] == ["docs/guide.md"]
    assert list(out.keys()) == [
        "tier", "reason", "components", "core_changed", "package_changed",
        "unknown_changed", "shared_changed", "independent_only",
        "full_matrix_required", "changed_files", "files",
    ]


def test_classify_json_output_unknown_path_is_full(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40)
    assert cmd_classify(args, git=FakeGit(paths=["tests/new_test.py"])) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tier"] == "full"
    assert out["unknown_changed"] is True


def test_classify_env_output_lines(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40, "--output", "env")
    assert cmd_classify(args, git=FakeGit(paths=["README.md"])) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "tier=package_docs" in lines
    assert "reason=package_doc_changed_in_docs_scope" in lines
    assert "full_matrix_required=false" in lines
    assert lines[-2] == "files:"
    assert lines[-1] == "- README.md"


def test_classify_empty_diff_env_output(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40, "--output", "env")
    assert cmd_classify(args, git=FakeGit(paths=[])) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "tier=full" in lines
    assert "reason=empty_diff" in lines
    assert "full_matrix_required=true" in lines


# ---------------------------------------------------------------------------
# classify: github-env renderer — only valid CI_* assignments, no
# "files:" / "- path" lines (§3 export integration contract).
# ---------------------------------------------------------------------------

_GITHUB_ENV_KEYS = (
    "CI_TIER",
    "CI_TIER_REASON",
    "CI_COMPONENTS",
    "CI_CORE_CHANGED",
    "CI_PACKAGE_CHANGED",
    "CI_UNKNOWN_CHANGED",
    "CI_SHARED_CHANGED",
    "CI_INDEPENDENT_ONLY",
    "CI_FULL_MATRIX_REQUIRED",
    "CI_CHANGED_FILES",
)


def assert_github_env_lines(lines: list[str]) -> None:
    assert len(lines) == 10
    assert [line.split("=", 1)[0] for line in lines] == list(_GITHUB_ENV_KEYS)
    for line in lines:
        # Valid GitHub Actions env assignment: KEY=VALUE, no quoting,
        # no "files:" / "- path" blocks.
        assert re.match(r"^[A-Z0-9_]+=", line), line
        assert not line.startswith("files:")
        assert not line.startswith("- ")


def test_classify_github_env_output_lines(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40, "--output", "github-env")
    assert cmd_classify(args, git=FakeGit(paths=["README.md"])) == 0
    lines = capsys.readouterr().out.splitlines()
    assert_github_env_lines(lines)
    assert lines[0] == "CI_TIER=package_docs"
    assert lines[1] == "CI_TIER_REASON=package_doc_changed_in_docs_scope"
    assert lines[3] == "CI_CORE_CHANGED=false"
    assert lines[4] == "CI_PACKAGE_CHANGED=true"
    assert lines[5] == "CI_UNKNOWN_CHANGED=false"
    assert lines[8] == "CI_FULL_MATRIX_REQUIRED=false"
    assert lines[9] == "CI_CHANGED_FILES=1"


def test_classify_github_env_full_tier(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40, "--output", "github-env")
    assert cmd_classify(args, git=FakeGit(paths=["src/ci_optimizer/cli.py"])) == 0
    lines = capsys.readouterr().out.splitlines()
    assert_github_env_lines(lines)
    assert lines[0] == "CI_TIER=full"
    assert lines[8] == "CI_FULL_MATRIX_REQUIRED=true"


def test_classify_github_env_error_fails_closed(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40, "--output", "github-env")
    assert cmd_classify(args, git=FakeGit(fail="resolve")) == 2
    lines = capsys.readouterr().out.splitlines()
    # Exactly the fail-closed assignment block; safe to append to GITHUB_ENV.
    assert lines == [
        "CI_TIER=full",
        "CI_TIER_REASON=classifier_error_fail_closed",
        "CI_FULL_MATRIX_REQUIRED=true",
    ]


def test_classify_github_env_invalid_config_fails_closed(tmp_path, capsys) -> None:
    path = write_config(tmp_path, "schema_version = = 1\n")
    args = make_args("classify", "--config", path, "--mode", "push",
                     "--base", "a" * 40, "--head", "b" * 40, "--output", "github-env")
    assert cmd_classify(args) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "CI_TIER=full",
        "CI_TIER_REASON=invalid_config_fail_closed",
        "CI_FULL_MATRIX_REQUIRED=true",
    ]


# ---------------------------------------------------------------------------
# verify-reuse: proof failures are verdicts, never CI failures (exit 0).
# ---------------------------------------------------------------------------


def test_verify_reuse_missing_repo_context_is_not_a_ci_failure(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("verify-reuse", "--config", path)
    assert cmd_verify(args, env={}) == 0
    out = capsys.readouterr().out
    assert out.startswith("POST_MERGE_REUSE=false\nreason=missing_repo_context\n")


def test_verify_reuse_missing_token_is_not_a_ci_failure(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("verify-reuse", "--config", path)
    assert cmd_verify(args, env={"GITHUB_REPOSITORY": "example/ci-optimizer"}) == 0
    out = capsys.readouterr().out
    assert out.startswith("POST_MERGE_REUSE=false\nreason=missing_token\n")


def test_verify_reuse_malformed_config_fails_closed(tmp_path, capsys) -> None:
    path = write_config(tmp_path, "not toml at all = =")
    args = make_args("verify-reuse", "--config", path)
    assert cmd_verify(args, env={}) == 0
    out = capsys.readouterr().out
    assert out.startswith("POST_MERGE_REUSE=false\nreason=invalid_config_fail_closed\n")


def test_verify_reuse_disabled_config_verdict(tmp_path, capsys) -> None:
    text = CONFIG_TEXT.replace(
        "enabled = true", "enabled = false"
    )
    path = write_config(tmp_path, text)
    args = make_args("verify-reuse", "--config", path)
    assert cmd_verify(args, env={}) == 0
    out = capsys.readouterr().out
    assert out.startswith("POST_MERGE_REUSE=false\nreason=reuse_disabled\n")


def test_verify_reuse_never_emits_true_on_context_failure(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("verify-reuse", "--config", path)
    cmd_verify(args, env={})
    out = capsys.readouterr().out
    assert "POST_MERGE_REUSE=false" in out
    assert "POST_MERGE_REUSE=true" not in out


# ---------------------------------------------------------------------------
# create-attestation: any failure is a CI failure (exit 1).
# ---------------------------------------------------------------------------


def test_create_attestation_malformed_config_exits_1(tmp_path, capsys) -> None:
    path = write_config(tmp_path, "schema_version = = 1\n")
    args = make_args("create-attestation", "--config", path,
                     str(tmp_path / "out.json"))
    assert cmd_create_attestation(args, env={}) == 1
    out = capsys.readouterr().out
    assert "FULL_CI_ATTESTATION_FAILED reason=invalid_config_fail_closed" in out


def test_create_attestation_missing_run_context_exits_1(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    args = make_args("create-attestation", "--config", path,
                     str(tmp_path / "out.json"))
    assert cmd_create_attestation(args, env={}) == 1
    out = capsys.readouterr().out
    assert "FULL_CI_ATTESTATION_FAILED reason=attestation_missing_run_context" in out


# ---------------------------------------------------------------------------
# main() dispatch.
# ---------------------------------------------------------------------------


def test_main_dispatches_verify_reuse(tmp_path, capsys) -> None:
    path = write_config(tmp_path)
    from ci_optimizer.cli import main

    assert main(["verify-reuse", "--config", path], env={}) == 0
    out = capsys.readouterr().out
    assert out.startswith("POST_MERGE_REUSE=false\nreason=missing_repo_context\n")


def test_main_rejects_unknown_subcommand(tmp_path, capsys) -> None:
    from ci_optimizer.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code == 2
