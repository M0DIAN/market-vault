"""Static L3.3 publication design obligations; no artifact runtime is executed."""

import json
import re

import pytest

from test_destructive_design_gate import (
    ROOT, _commit, _new_repo, _write_json, gate,
)
from test_cross_day_dataset_canary_coverage import CANARIES as L31_CANARIES
from test_cross_day_generator_canaries import CANARIES as L32_CANARIES

OPERATION = "multi_source_cross_day_dataset_atomic_publication_v1"
CONTRACT_PATH = gate.CONTRACT_ROOT / (OPERATION + ".json")
DESIGN_PATH = ROOT / "docs/governance/cross_day_dataset_atomic_publication_v1.md"
SOURCE_PATH = "src/market_vault/cross_day_dataset/materialization.py"

# Source text is analyzed in isolated Git fixtures, never imported or executed.
PLANNED_SOURCE = """import os
import shutil

def _rename_directory_no_replace_windows(staging, final):
    os.rename(staging, final)

def _remove_tree(staging):
    shutil.rmtree(staging)
"""


def contract_data():
    return json.loads((ROOT / CONTRACT_PATH).read_text(encoding="utf-8"))


def design_text():
    return DESIGN_PATH.read_text(encoding="utf-8")


def test_new_contract_exact_realized_bindings_and_inventory():
    value = contract_data()
    contract = gate._validate_contract(value, CONTRACT_PATH.as_posix())
    assert contract.operation_id == OPERATION
    assert {(b.path, symbol, s.kind, s.signal, s.expected_count)
            for b in contract.bindings for symbol in b.symbols for s in b.surfaces} == {
        (SOURCE_PATH, "_rename_directory_no_replace_windows", "destructive_call", "os.rename", 1),
        (SOURCE_PATH, "_remove_tree", "destructive_call", "shutil.rmtree", 1),
    }
    assert all(b.prospective_transition is None for b in contract.bindings)
    snapshot = gate.load_worktree_snapshot(ROOT)
    assert gate.validate_snapshot(snapshot) == []
    assert (len(snapshot.contracts), len(snapshot.exemptions), len(snapshot.findings)) == (6, 16, 44)
    assert (ROOT / SOURCE_PATH).is_file()
    assert {(f.path, f.symbol, f.signal) for f in snapshot.findings
            if f.path.startswith("src/market_vault/cross_day_dataset/")} == {
        (SOURCE_PATH, "_rename_directory_no_replace_windows", "os.rename"),
        (SOURCE_PATH, "_remove_tree", "shutil.rmtree"),
    }


def test_existing_a4_permission_cannot_cover_new_path():
    snapshot = gate.load_worktree_snapshot(ROOT)
    findings, _ = gate._analyze_source(SOURCE_PATH, PLANNED_SOURCE.encode())
    assert len(findings) == 2
    new = snapshot.contracts[OPERATION]
    old = snapshot.contracts["multi_source_dataset_atomic_publication_v1"]
    assert all(new.covers(f) and not old.covers(f) for f in findings)


@pytest.mark.parametrize("planned_first", [False, True])
def test_exact_design_base_required_for_planned_implementation(tmp_path, planned_first):
    repo, initial = _new_repo(tmp_path)
    _write_json(repo / CONTRACT_PATH, contract_data())
    design = _commit(repo, "design only")
    _, errors = gate.validate_pull_request(repo, initial, design)
    assert errors == []
    source = repo / SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_text(PLANNED_SOURCE, encoding="utf-8")
    head = _commit(repo, "synthetic AST only")
    _, errors = gate.validate_pull_request(repo, design if planned_first else initial, head)
    if planned_first:
        assert errors == []
    else:
        assert any("lacks approved BASE contract" in e for e in errors)


@pytest.mark.parametrize("extra", ["os.rename(staging, final)", "os.replace(staging, final)"])
def test_new_contract_rejects_extra_or_different_primitive(extra):
    source = PLANNED_SOURCE.replace("    os.rename(staging, final)",
                                    "    os.rename(staging, final)\n    " + extra)
    snapshot = gate._build_snapshot(
        {SOURCE_PATH: source.encode()},
        {CONTRACT_PATH.as_posix(): json.dumps(contract_data()).encode(),
         gate.EXEMPTIONS_PATH.as_posix(): json.dumps({
             "schema_version": gate.EXEMPTION_SCHEMA_VERSION, "exemptions": [],
         }).encode()},
    )
    assert gate.validate_snapshot(snapshot)


def test_physical_commit_and_verified_success_are_distinct():
    value = contract_data()
    assert value["commit_point"]["before_state"] == "SEALED"
    assert value["commit_point"]["after_state"] == "COMMITTED_UNVERIFIED"
    transitions = {(t["from"], t["to"]) for t in value["state_machine"]["allowed_transitions"]}
    assert ("COMMITTED_UNVERIFIED", "COMMITTED_INVALID") in transitions
    assert ("COMMITTED_UNVERIFIED", "VERIFIED_FINAL") in transitions
    assert ("COMMITTED_UNVERIFIED", "PRIVATE_STAGING") not in transitions
    assert not value["permanent_deletion"]["supported"]


@pytest.mark.parametrize("obligation", [
    "PUBLICATION_CONTRACT_VERSION=multi-source-cross-day-dataset-atomic-publication-v1",
    "dataset_id=<dataset_id>/", ".<dataset_id>.tmp-<nonce>/",
    "_verify_and_seal_staging(owner)", "_publish(owner, seal)",
    "SUBSET", "inventory EQUALITY", "relative_path", "file_role", "byte_size", "SHA256",
    "manifest.dataset_id == owner.dataset_id", "COMMITTED_INVALID",
    "SUPPORTED_AND_QUALIFIED", "UNSUPPORTED_FAIL_CLOSED",
    "renameat2", "RENAME_NOREPLACE", "FileIdInfo", "statx",
    "DATASET_ID_FIELD_COUNT=49", "KNOWN_ANSWER_DIGEST_ASSERTION_COUNT=98",
    "L3_3_CROSS_DAY_ARTIFACT_IMPLEMENTATION_AUTHORIZED=false",
    "L4_IMPLEMENTATION_AUTHORIZED=false", "MERGE_AUTHORIZED=false",
])
def test_normative_document_contains_closed_contract_obligations(obligation):
    assert obligation in design_text()


def test_nine_artifact_canaries_remain_deferred_with_future_mapping():
    expected = {2, 3, 38, 39, 40, 61, 75, 76, 77}
    assert {n for n, phase, _, _ in L31_CANARIES if phase == "L3_3_DEFERRED"} == expected
    assert {n for n, phase, _, _ in L32_CANARIES if phase == "L3_3_DEFERRED"} == expected
    mapped = {int(n) for n in re.findall(r"^\| (\d+) \| L3_3_", design_text(), re.MULTILINE)}
    assert mapped == expected
    assert len(L31_CANARIES) == len(L32_CANARIES) == 80
    assert "L3_3_DESIGN owns only" in design_text()
    assert "L3_3_DEFERRED_CANARIES=9" in design_text()
