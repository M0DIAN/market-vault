from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_destructive_design_gate.py"
SPEC = importlib.util.spec_from_file_location("check_destructive_design_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _base_contract() -> dict:
    return json.loads(
        (
            ROOT
            / "docs"
            / "governance"
            / "destructive_operations"
            / "safe_purge_v01.json"
        ).read_text(encoding="utf-8")
    )


def _planned_contract(
    *,
    operation_id: str = "planned_remove_v01",
    path: str = "src/market_vault/example.py",
    symbol: str = "dangerous",
) -> dict:
    value = _base_contract()
    value["operation_id"] = operation_id
    value["identity"] = {
        "name": "Planned remove operation",
        "purpose": "Test-only planned destructive operation contract.",
    }
    value["implementation_bindings"] = [
        {
            "path": path,
            "symbols": [symbol],
            "role": "MUTATION_OWNER",
            "allowed_surface_kinds": [
                "destructive_call",
                "destructive_public_name",
                "destructive_sql",
            ],
            "rationale": "Exact planned implementation boundary for the test fixture.",
        }
    ]
    return value


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _empty_exemptions() -> dict:
    return {
        "schema_version": gate.EXEMPTION_SCHEMA_VERSION,
        "exemptions": [],
    }


def _validate(value: dict):
    return gate._validate_contract(value, "contract.json")


def test_valid_approved_contract_passes():
    contract = _validate(_base_contract())
    assert contract.operation_id == "safe_purge_v01"


def test_missing_required_section_fails():
    value = _base_contract()
    del value["idempotence"]
    with pytest.raises(gate.GateError, match="missing=.*idempotence"):
        _validate(value)


def test_duplicate_operation_id_fails():
    contract = _json_bytes(_base_contract())
    governance = {
        gate.EXEMPTIONS_PATH.as_posix(): _json_bytes(_empty_exemptions()),
        f"{gate.CONTRACT_ROOT}/one.json": contract,
        f"{gate.CONTRACT_ROOT}/two.json": contract,
    }
    with pytest.raises(gate.GateError, match="duplicate operation_id"):
        gate._build_snapshot({}, governance)


def test_contract_filename_must_match_operation_id():
    governance = {
        gate.EXEMPTIONS_PATH.as_posix(): _json_bytes(_empty_exemptions()),
        f"{gate.CONTRACT_ROOT}/wrong_name.json": _json_bytes(_base_contract()),
    }
    with pytest.raises(gate.GateError, match="must use canonical path"):
        gate._build_snapshot({}, governance)


def test_unknown_schema_version_fails():
    value = _base_contract()
    value["schema_version"] = "future-v99"
    with pytest.raises(gate.GateError, match="unknown schema_version"):
        _validate(value)


def test_unknown_binding_role_fails():
    value = _base_contract()
    value["implementation_bindings"][0]["role"] = "MAGIC"
    with pytest.raises(gate.GateError, match="role is unknown"):
        _validate(value)


def test_wildcard_contract_symbol_fails():
    value = _base_contract()
    value["implementation_bindings"][0]["symbols"] = ["purge_*"]
    with pytest.raises(gate.GateError, match="exact symbols"):
        _validate(value)


def test_transition_to_unknown_state_fails():
    value = _base_contract()
    value["state_machine"]["allowed_transitions"][0]["to"] = "MISSING"
    with pytest.raises(gate.GateError, match="transition references unknown state"):
        _validate(value)


def test_missing_durable_commit_point_fails():
    value = _base_contract()
    del value["commit_point"]["durable_authority"]
    with pytest.raises(gate.GateError, match="commit_point fields mismatch"):
        _validate(value)


def test_missing_crash_recovery_semantics_fails():
    value = _base_contract()
    del value["crash_semantics"]["post_commit"]
    with pytest.raises(gate.GateError, match="crash_semantics fields mismatch"):
        _validate(value)


def test_bare_na_without_rationale_fails():
    value = _base_contract()
    value["rollback_recovery"]["non_restorable"] = ["N/A"]
    with pytest.raises(gate.GateError, match="bare N/A"):
        _validate(value)


def test_structured_not_applicable_with_rationale_passes():
    value = _base_contract()
    value["stale_plan_ui"]["invalidation_triggers"] = {
        "applicable": False,
        "rationale": "This planned operation has no UI surface.",
    }
    _validate(value)


def test_wildcard_exemption_fails():
    value = _empty_exemptions()
    value["exemptions"] = [
        {
            "exemption_id": "bad_wildcard",
            "path": "src/market_vault/*.py",
            "symbol": "cleanup",
            "kind": "destructive_call",
            "signal": "path.unlink",
            "fingerprint": "0" * 64,
            "expected_count": 1,
            "rationale": "This must be rejected despite having a rationale.",
        }
    ]
    with pytest.raises(gate.GateError, match="wildcard"):
        gate._validate_exemptions(value, "exemptions.json")


def test_over_broad_exemption_fails():
    value = _empty_exemptions()
    value["exemptions"] = [
        {
            "exemption_id": "bad_directory",
            "path": "src/market_vault/dataset",
            "symbol": "cleanup",
            "kind": "destructive_call",
            "signal": "path.unlink",
            "fingerprint": "0" * 64,
            "expected_count": 1,
            "rationale": "A directory cannot be an exemption boundary.",
        }
    ]
    with pytest.raises(gate.GateError, match="exact Python file"):
        gate._validate_exemptions(value, "exemptions.json")


def test_windows_reparse_policy_cannot_be_omitted_for_path_mutation():
    value = _base_contract()
    del value["path_safety"]["windows_reparse_policy"]
    with pytest.raises(gate.GateError, match="path_safety fields mismatch"):
        _validate(value)


def test_existing_safe_purge_contract_and_inventory_validate():
    snapshot = gate.load_worktree_snapshot(ROOT)
    assert gate.validate_snapshot(snapshot) == []
    assert set(snapshot.contracts) == {"safe_purge_v01"}
    assert len(snapshot.exemptions) == 19
    assert len(snapshot.findings) == 37
    purge_findings = [
        finding
        for finding in snapshot.findings
        if snapshot.contracts["safe_purge_v01"].covers(finding)
    ]
    assert purge_findings


def test_known_infrastructure_exemption_is_exactly_bound():
    snapshot = gate.load_worktree_snapshot(ROOT)
    exemption = next(
        item
        for item in snapshot.exemptions
        if item.exemption_id == "report_failed_temp_cleanup"
    )
    matches = [finding for finding in snapshot.findings if exemption.covers(finding)]
    assert len(matches) == exemption.expected_count == 1
    assert matches[0].symbol == "write_json_report_atomic"


def test_new_destructive_logic_beside_exemption_is_not_automatically_exempt():
    source = b"from pathlib import Path\n\ndef cleanup(path: Path):\n    path.unlink()\n    path.unlink()\n"
    findings, _ = gate._analyze_source("src/market_vault/example.py", source)
    matching = [item for item in findings if item.kind == "destructive_call"]
    assert len(matching) == 2
    exemption = {
        "schema_version": gate.EXEMPTION_SCHEMA_VERSION,
        "exemptions": [
            {
                "exemption_id": "one_exact_cleanup",
                "path": "src/market_vault/example.py",
                "symbol": "cleanup",
                "kind": matching[0].kind,
                "signal": matching[0].signal,
                "fingerprint": matching[0].fingerprint,
                "expected_count": 1,
                "rationale": "Only the one reviewed call is exempt.",
            }
        ],
    }
    snapshot = gate._build_snapshot(
        {"src/market_vault/example.py": source},
        {gate.EXEMPTIONS_PATH.as_posix(): _json_bytes(exemption)},
    )
    errors = gate.validate_snapshot(snapshot)
    assert any("expected exactly 1" in error and "found 2" in error for error in errors)


def test_checker_parse_failure_fails_closed():
    with pytest.raises(gate.GateError, match="AST parse failed"):
        gate._analyze_source("src/market_vault/broken.py", b"def broken(:\n")


def test_checker_unexpected_runtime_failure_returns_nonzero(monkeypatch, capsys):
    def fail(_repo):
        raise RuntimeError("simulated runtime fault")

    monkeypatch.setattr(gate, "load_worktree_snapshot", fail)
    assert gate.main(["--repo", str(ROOT), "--mode", "repository"]) == 1
    captured = capsys.readouterr()
    assert "DESTRUCTIVE_DESIGN_GATE_ERROR" in captured.err
    assert "simulated runtime fault" in captured.err
    assert "Traceback" not in captured.err


def test_path_replace_is_detected_but_text_replace_is_not():
    source = b'''from pathlib import Path

def publish(target_path: Path, text: str):
    text.replace("a", "b")
    target_path.replace(Path("final"))
'''
    findings, _ = gate._analyze_source("src/market_vault/example.py", source)
    calls = [finding for finding in findings if finding.kind == "destructive_call"]
    assert [(finding.symbol, finding.signal) for finding in calls] == [
        ("publish", "path.replace")
    ]


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Gate Test",
        "GIT_AUTHOR_EMAIL": "gate@example.invalid",
        "GIT_COMMITTER_NAME": "Gate Test",
        "GIT_COMMITTER_EMAIL": "gate@example.invalid",
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _new_repo(tmp_path: Path, *, source: str = "") -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "src" / "market_vault").mkdir(parents=True)
    if source:
        (repo / "src" / "market_vault" / "example.py").write_text(
            source, encoding="utf-8", newline="\n"
        )
    _write_json(repo / gate.EXEMPTIONS_PATH.as_posix(), _empty_exemptions())
    _git(repo, "init", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_new_destructive_primitive_without_base_contract_fails(tmp_path):
    repo, base = _new_repo(tmp_path, source="def operate():\n    return None\n")
    (repo / "src" / "market_vault" / "example.py").write_text(
        "import os\n\ndef operate():\n    os.remove('runtime.db')\n",
        encoding="utf-8",
        newline="\n",
    )
    head = _commit(repo, "implementation")
    _, errors = gate.validate_pull_request(repo, base, head)
    assert any("lacks approved BASE contract" in error for error in errors)


def test_new_destructive_public_operation_without_base_contract_fails(tmp_path):
    repo, base = _new_repo(tmp_path)
    (repo / "src" / "market_vault" / "example.py").write_text(
        "def restore_runtime():\n    return None\n", encoding="utf-8", newline="\n"
    )
    head = _commit(repo, "implementation")
    _, errors = gate.validate_pull_request(repo, base, head)
    assert any("lacks approved BASE contract" in error for error in errors)


def test_contract_added_only_in_head_with_implementation_fails(tmp_path):
    repo, base = _new_repo(tmp_path, source="def dangerous():\n    return None\n")
    _write_json(
        repo / gate.CONTRACT_ROOT.as_posix() / "planned_remove_v01.json",
        _planned_contract(),
    )
    (repo / "src" / "market_vault" / "example.py").write_text(
        "import os\n\ndef dangerous():\n    os.remove('runtime.db')\n",
        encoding="utf-8",
        newline="\n",
    )
    head = _commit(repo, "contract and implementation")
    _, errors = gate.validate_pull_request(repo, base, head)
    assert any("lacks approved BASE contract" in error for error in errors)


def test_contract_changed_with_destructive_implementation_fails(tmp_path):
    repo, _ = _new_repo(tmp_path, source="def dangerous():\n    return None\n")
    contract_path = repo / gate.CONTRACT_ROOT.as_posix() / "planned_remove_v01.json"
    value = _planned_contract()
    _write_json(contract_path, value)
    base = _commit(repo, "approved design")
    value["identity"]["purpose"] = "Materially redesigned during implementation."
    _write_json(contract_path, value)
    (repo / "src" / "market_vault" / "example.py").write_text(
        "import os\n\ndef dangerous():\n    os.remove('runtime.db')\n",
        encoding="utf-8",
        newline="\n",
    )
    head = _commit(repo, "redesign and implementation")
    _, errors = gate.validate_pull_request(repo, base, head)
    assert any("contract changed together" in error for error in errors)


def test_approved_matching_contract_already_in_base_passes(tmp_path):
    repo, _ = _new_repo(tmp_path, source="def dangerous():\n    return None\n")
    _write_json(
        repo / gate.CONTRACT_ROOT.as_posix() / "planned_remove_v01.json",
        _planned_contract(),
    )
    base = _commit(repo, "approved design")
    (repo / "src" / "market_vault" / "example.py").write_text(
        "import os\n\ndef dangerous():\n    os.remove('runtime.db')\n",
        encoding="utf-8",
        newline="\n",
    )
    head = _commit(repo, "implementation")
    _, errors = gate.validate_pull_request(repo, base, head)
    assert errors == []


def test_design_only_contract_with_future_path_passes(tmp_path):
    repo, base = _new_repo(tmp_path)
    _write_json(
        repo / gate.CONTRACT_ROOT.as_posix() / "planned_remove_v01.json",
        _planned_contract(
            path="src/market_vault/future_remove.py", symbol="remove_snapshot"
        ),
    )
    head = _commit(repo, "design only")
    snapshot, errors = gate.validate_pull_request(repo, base, head)
    assert errors == []
    assert "planned_remove_v01" in snapshot.contracts


def test_registry_bootstrap_without_base_registry_passes_only_for_design(tmp_path):
    repo = tmp_path / "bootstrap"
    (repo / "src" / "market_vault").mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / "src" / "market_vault" / "example.py").write_text(
        "def ordinary():\n    return None\n", encoding="utf-8", newline="\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base without gate")
    base = _git(repo, "rev-parse", "HEAD")
    _write_json(repo / gate.EXEMPTIONS_PATH.as_posix(), _empty_exemptions())
    _write_json(
        repo / gate.CONTRACT_ROOT.as_posix() / "planned_remove_v01.json",
        _planned_contract(
            path="src/market_vault/future_remove.py", symbol="remove_snapshot"
        ),
    )
    head = _commit(repo, "bootstrap design gate")
    _, errors = gate.validate_pull_request(repo, base, head)
    assert errors == []


def test_workflow_runs_gate_for_pull_requests_and_repository_pushes():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Check destructive-operation design gate" in workflow
    assert "--mode pull_request" in workflow
    assert 'github.event.pull_request.base.sha' in workflow
    assert 'github.event.pull_request.head.sha' in workflow
    assert "--mode repository" in workflow
