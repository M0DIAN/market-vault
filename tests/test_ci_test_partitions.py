"""Coverage, plan and failure propagation for the 3.11 CI partitions."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci_test_partitions.py"
spec = importlib.util.spec_from_file_location("ci_test_partitions", SCRIPT)
partitions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(partitions)
release_spec = importlib.util.spec_from_file_location("partition_release_checker", ROOT / "scripts/check_release.py")
release_checker = importlib.util.module_from_spec(release_spec)
sys.modules[release_spec.name] = release_checker
release_spec.loader.exec_module(release_checker)


def tiny_repo(tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    manifest = "schema_version = 1\n"
    for name in partitions.PARTITION_NAMES:
        filename = f"test_{name}_example.py"
        (tmp_path / "tests" / filename).write_text("def test_example():\n    assert True\n")
        manifest += f'\n[partitions.{name}]\nfiles = []\nprefixes = ["test_{name}_"]\n'
    (tmp_path / partitions.REGISTRY_REL).write_text(manifest)
    return tmp_path


def test_current_registry_covers_every_discovered_test_exactly_once():
    resolved = partitions.load_partitions(ROOT)
    files = [path for group in resolved.values() for path in group]
    expected = {
        path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    }
    assert set(files) == expected
    assert len(files) == len(expected)
    assert "tests/test_intraday_final_test.py" in resolved["intraday_final"]
    assert "tests/test_desktop_intraday_research.py" in resolved["intraday_research"]


def test_new_test_in_known_domain_is_included_including_subdirectories(tmp_path):
    repo = tiny_repo(tmp_path)
    (repo / "tests/nested").mkdir()
    (repo / "tests/nested/test_data_new.py").write_text("def test_new(): pass\n")
    assert "tests/nested/test_data_new.py" in partitions.load_partitions(repo)["data"]


@pytest.mark.parametrize("filename", ["test_unassigned.py", "unassigned_test.py"])
def test_unknown_tests_are_not_silently_omitted(tmp_path, filename):
    repo = tiny_repo(tmp_path)
    (repo / "tests" / filename).write_text("def test_new(): pass\n")
    with pytest.raises(ValueError, match="exactly one owner"):
        partitions.load_partitions(repo)


def test_overlapping_prefixes_fail(tmp_path):
    repo = tiny_repo(tmp_path)
    path = repo / partitions.REGISTRY_REL
    path.write_text(path.read_text().replace('prefixes = ["test_strategy_"]',
                                            'prefixes = ["test_strategy_", "test_data_"]'))
    with pytest.raises(ValueError, match="exactly one owner"):
        partitions.load_partitions(repo)


def test_explicit_file_ownership_overrides_broad_gui_prefix(tmp_path):
    repo = tiny_repo(tmp_path)
    path = repo / partitions.REGISTRY_REL
    path.write_text(path.read_text().replace('[partitions.intraday_final]\nfiles = []',
        '[partitions.intraday_final]\nfiles = ["test_data_example.py"]'))
    (repo / "tests/test_data_another.py").write_text("def test_other(): pass\n")
    assert "tests/test_data_example.py" in partitions.load_partitions(repo)["intraday_final"]


@pytest.mark.parametrize("failure", ["stale", "duplicate", "empty", "discovery"])
def test_invalid_registry_or_discovery_fails(tmp_path, failure):
    repo = tiny_repo(tmp_path)
    path = repo / partitions.REGISTRY_REL
    text = path.read_text()
    if failure == "stale":
        text = text.replace("files = []", 'files = ["test_missing.py"]', 1)
    elif failure == "duplicate":
        text = text.replace("files = []", 'files = ["test_data_example.py"]', 2)
    elif failure == "empty":
        (repo / "tests/test_data_example.py").unlink()
    else:
        (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["other"]\n')
    path.write_text(text)
    with pytest.raises(ValueError):
        partitions.load_partitions(repo)


@pytest.mark.parametrize("tier,reuse,fmr", [
    ("", "", ""), ("unknown", "false", "true"),
    ("docs_fast", "false", "true"), ("full", "true", "false"),
    ("research_fast", "true", "false"), ("full", "invalid", "true"),
])
def test_incomplete_decisions_fall_back_to_full(tier, reuse, fmr):
    assert partitions.execution_plan(tier, reuse, fmr) == {
        "tier": "full", "reuse": "false", "full_matrix_required": "true", "run_partitions": "true"
    }


@pytest.mark.parametrize("tier", sorted(partitions.FAST_TIERS))
def test_existing_fast_tiers_skip_only_the_full_partitions(tier):
    assert partitions.execution_plan(tier, "", "false")["run_partitions"] == "false"
    partitions.verify_results("success", "skipped", tier, "false", "false")


def test_verified_full_reuse_retains_planned_skip():
    assert partitions.execution_plan("full", "true", "true")["run_partitions"] == "false"
    partitions.verify_results("success", "skipped", "full", "true", "true")


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", "neutral"])
def test_full_cannot_pass_with_a_missing_or_unsuccessful_partition(result):
    with pytest.raises(ValueError, match="partition result"):
        partitions.verify_results("success", result, "full", "false", "true")


@pytest.mark.parametrize("result", ["failure", "cancelled", "success", ""])
def test_fast_path_does_not_hide_unexpected_partition_results(result):
    with pytest.raises(ValueError, match="partition result"):
        partitions.verify_results("success", result, "docs_fast", "false", "false")


def test_plan_failure_and_inconsistent_outputs_cannot_pass():
    with pytest.raises(ValueError, match="plan did not succeed"):
        partitions.verify_results("failure", "skipped", "full", "false", "true")
    with pytest.raises(ValueError, match="incomplete or inconsistent"):
        partitions.verify_results("success", "success", "", "", "")
    partitions.verify_results("success", "success", "full", "false", "true")


def test_runner_really_runs_only_owned_files_and_propagates_failure(tmp_path):
    repo = tiny_repo(tmp_path)
    (repo / "tests/test_data_example.py").write_text("def test_owned_failure():\n    assert False\n")
    (repo / "tests/test_strategy_example.py").write_text("raise RuntimeError('UNSELECTED_FILE_IMPORTED')\n")
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    run = subprocess.run([sys.executable, str(SCRIPT), "run", "--repo", str(repo),
                          "--partition", "data"], env=env, text=True, capture_output=True)
    assert run.returncode == 1, run.stdout + run.stderr
    assert "test_owned_failure" in run.stdout
    assert "1 failed" in run.stdout
    assert "UNSELECTED_FILE_IMPORTED" not in run.stdout + run.stderr


@pytest.mark.parametrize("addopts", ["--collect-only", "-k passing", "--ignore=tests/test_data_example.py"])
def test_runner_rejects_inherited_options_that_can_omit_tests(tmp_path, addopts):
    repo = tiny_repo(tmp_path)
    (repo / "tests/test_data_example.py").write_text("def test_failure():\n    assert False\n")
    env = dict(os.environ, PYTEST_ADDOPTS=addopts)
    run = subprocess.run([sys.executable, str(SCRIPT), "run", "--repo", str(repo),
                          "--partition", "data"], env=env, text=True, capture_output=True)
    assert run.returncode == 1
    assert "PYTEST_ADDOPTS must be empty" in run.stderr


@pytest.mark.parametrize("old,new,diagnostic", [
    ("        partition: [data, dataset_features, strategy, intraday_research, intraday_final, app_ops]",
     "        partition: [data, dataset_features, strategy, intraday_research, intraday_final, app_ops]\n"
     "        exclude:\n          - partition: intraday_final", "cannot include or exclude"),
    ("  package:\n", "  package:\n    if: always()\n", "package must keep its exact job condition"),
    ("  package:\n", "  package:\n    if: false\n", "package must keep its exact job condition"),
    ("    " + release_checker.CI_PACKAGE_JOB_GUARD + "\n", "", "package must keep its exact job condition"),
    (" && needs.test.result == 'success'", "", "package must keep its exact job condition"),
    ("      - name: Export execution plan\n", "      - name: Export execution plan\n"
     "        env:\n          POST_MERGE_REUSE: true\n", "cannot override execution decisions"),
    ("      - name: Run offline tests\n", "      - name: Run offline tests\n"
     "        env:\n          CI_PARTITIONS_RESULT: success\n", "cannot override execution decisions"),
    ("        run: python scripts/ci_test_partitions.py verify\n",
     "        run: echo success\n", "must run"),
    ("    if: ${{ always() && !cancelled() }}\n", "", "test must keep its exact job condition"),
    ("      fail-fast: false\n", "      fail-fast: false\n    continue-on-error: true\n", "cannot ignore failures"),
])
def test_workflow_mutations_cannot_omit_partitions_or_forge_success(tmp_path, old, new, diagnostic):
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert old in workflow
    target = tmp_path / ".github/workflows/ci.yml"
    target.parent.mkdir(parents=True)
    target.write_text(workflow.replace(old, new, 1))
    for relative in ("ci/test_partitions.toml", "scripts/ci_test_partitions.py"):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text((ROOT / relative).read_text())
    failures = release_checker.check_ci_partitions(tmp_path)
    assert any(diagnostic in failure for failure in failures), failures


def test_current_workflow_partition_contract_is_valid():
    assert release_checker.check_ci_partitions(ROOT) == []


def test_plan_cli_exports_the_exact_normalized_plan(tmp_path):
    output = tmp_path / "github-output"
    env = dict(os.environ, GITHUB_OUTPUT=str(output), CI_TIER="full",
               CI_FULL_MATRIX_REQUIRED="true", POST_MERGE_REUSE="false")
    run = subprocess.run([sys.executable, str(SCRIPT), "plan"], env=env,
                         text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    assert output.read_text() == run.stdout
    assert "run_partitions=true\n" in run.stdout
