from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_full


RUN_ID = "run-20260823T000000Z-abcdef123456"
ENOUGH_SPACE = 20 * verify_full.GIB


def disk_with(free: int):
    return lambda _path: SimpleNamespace(free=free)


def make_preflight(
    tmp_path: Path,
    *,
    free: int = ENOUGH_SPACE,
    repo_name: str = "repo",
) -> verify_full.ValidationPreflight:
    repo = tmp_path / repo_name
    repo.mkdir()
    parent = tmp_path / "external-temp"
    return verify_full.build_preflight(
        repo_root=repo,
        temp_parent=parent,
        worktrees=(repo,),
        run_id=RUN_ID,
        python_executable="python.exe",
        disk_usage=disk_with(free),
    )


def test_repo_internal_pytest_cache_basetemp_is_refused(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    candidate = repo / ".pytest_cache" / "full"
    with pytest.raises(verify_full.ValidationSafetyError, match="inside.*worktree"):
        verify_full.assert_outside_worktrees(candidate, repo, (repo,))


def test_nested_registered_worktree_temp_is_refused(tmp_path):
    repo = tmp_path / "repo"
    other = tmp_path / "another-worktree"
    repo.mkdir()
    other.mkdir()
    candidate = other / "temp"
    with pytest.raises(verify_full.ValidationSafetyError, match="another-worktree"):
        verify_full.assert_outside_worktrees(candidate, repo, (repo, other))


def test_exact_worktree_root_is_refused(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(verify_full.ValidationSafetyError, match="inside.*worktree"):
        verify_full.assert_outside_worktrees(repo, repo, (repo,))


def test_safe_external_path_with_spaces_and_non_ascii_is_accepted(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    candidate = tmp_path / "safe temp" / "验证" / RUN_ID
    resolved = verify_full.assert_outside_worktrees(candidate, repo, (repo,))
    assert resolved == candidate.resolve()


def test_explicit_override_cannot_bypass_worktree_safety(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(verify_full.ValidationSafetyError, match="inside.*worktree"):
        verify_full.choose_temp_parent(
            repo_root=repo,
            worktrees=(repo,),
            run_id=RUN_ID,
            explicit=str(repo / ".pytest_cache" / "full"),
            env={},
        )


def test_low_free_space_refuses_before_pytest_or_directory_creation(tmp_path):
    preflight = make_preflight(tmp_path, free=verify_full.MINIMUM_FREE_BYTES - 1)
    launched = False
    output: list[str] = []

    def unexpected_run(*_args, **_kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("pytest must not launch")

    with pytest.raises(verify_full.ValidationSafetyError, match="insufficient free space"):
        verify_full.execute_validation(
            preflight, emit=output.append, run_process=unexpected_run
        )
    assert not launched
    assert not preflight.temp_parent.exists()
    assert f"required_bytes={verify_full.MINIMUM_FREE_BYTES}" in output
    assert f"available_bytes={verify_full.MINIMUM_FREE_BYTES - 1}" in output


@pytest.mark.parametrize("pytest_exit", [0, 7])
def test_pytest_exit_code_is_preserved_and_preflight_prints_before_mutation(
    tmp_path, pytest_exit
):
    preflight = make_preflight(tmp_path)
    output: list[str] = []
    launched = False

    def emit(line: str):
        if not launched:
            assert not preflight.temp_parent.exists()
        output.append(line)

    def fake_run(command, *, cwd, env, check):
        nonlocal launched
        launched = True
        assert command == list(preflight.command)
        assert command[3:5] == ["-p", "no:cacheprovider"]
        assert cwd == preflight.repo_root
        assert env["PYTHONUTF8"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert "PYTEST_ADDOPTS" not in env
        assert check is False
        return SimpleNamespace(returncode=pytest_exit)

    result = verify_full.execute_validation(
        preflight, emit=emit, run_process=fake_run
    )
    assert result == pytest_exit
    assert not preflight.run_dir.exists()
    assert any(line.startswith("pytest_command=") for line in output)


def test_cleanup_removes_only_exact_run_owned_directory(tmp_path):
    preflight = make_preflight(tmp_path)
    preflight.temp_parent.mkdir(parents=True)
    sibling = preflight.temp_parent / "shared-sentinel.txt"
    sibling.write_text("retain", encoding="utf-8")
    cleanup_calls: list[Path] = []

    def cleanup(path: Path):
        cleanup_calls.append(path)
        shutil.rmtree(path)

    result = verify_full.execute_validation(
        preflight,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
        cleanup=cleanup,
    )
    assert result == 0
    assert cleanup_calls == [preflight.run_dir]
    assert sibling.read_text(encoding="utf-8") == "retain"
    assert preflight.temp_parent.is_dir()


def test_cleanup_failure_reports_retained_exact_path_without_broadening(tmp_path):
    preflight = make_preflight(tmp_path)
    output: list[str] = []
    cleanup_calls: list[Path] = []

    def locked_cleanup(path: Path):
        cleanup_calls.append(path)
        raise PermissionError("simulated Windows ACL lock")

    result = verify_full.execute_validation(
        preflight,
        emit=output.append,
        run_process=lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
        cleanup=locked_cleanup,
    )
    assert result == 0
    assert cleanup_calls == [preflight.run_dir]
    assert preflight.run_dir.is_dir()
    assert any(
        line
        == (
            f"cleanup_status=RETAINED path={preflight.run_dir} "
            "error=simulated Windows ACL lock"
        )
        for line in output
    )


def test_worktree_porcelain_parser_uses_nul_delimited_authoritative_paths(tmp_path):
    first = tmp_path / "repo with spaces"
    second = tmp_path / "另一个-worktree"
    payload = (
        f"worktree {first}\0HEAD aaa\0branch refs/heads/main\0\0"
        f"worktree {second}\0HEAD bbb\0detached\0\0"
    ).encode("utf-8")
    assert verify_full.parse_worktree_porcelain(payload) == (first, second)


def test_wrapper_sets_utf8_and_delegates_to_canonical_helper():
    repo_root = Path(__file__).resolve().parents[1]
    wrapper = (repo_root / "scripts" / "verify_full.ps1").read_text(
        encoding="utf-8"
    )
    assert '$env:PYTHONUTF8 = "1"' in wrapper
    assert '$env:PYTHONIOENCODING = "utf-8"' in wrapper
    assert '"verify_full.py"' in wrapper
    assert "exit $validationExitCode" in wrapper
