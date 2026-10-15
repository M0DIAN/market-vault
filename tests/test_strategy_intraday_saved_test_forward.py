"""Q82 existing final fixtures and public saved TEST forward round trips.

These synthetic observations prove software behavior, not live market capture.
Fixture definitions are reused with session scope; no fresh research per case.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.quality.market_data_comparison import write_market_data_json
from market_vault.research import intraday_forward_reconciliation as forward
from market_vault.research import intraday_final_test as final
from market_vault.research.intraday_data import digest
from market_vault.research.strategy_experiment import StrategyExperiment, write_strategy_experiment
from test_intraday_final_test import (  # noqa: F401
    bind, sign_test, freeze_source, final_case, selection_case, intraday_experiment, research_case,
)
from test_strategy_intraday_forward_reconciliation import observed
from test_strategy_intraday_ml_final import ml_final_case, inner_case, quadratic_dev_case  # noqa: F401
from test_strategy_intraday_threshold_final import threshold_final_case, threshold_case  # noqa: F401
from test_strategy_intraday_joint_final import joint_final_case, joint_case, joint_quadratic_case  # noqa: F401


def assert_saved_test_forward(snapshot, tmp_path, monkeypatch, *, require_actions=True):
    """Q82 contract, shared by existing final fixtures without another fit."""
    from market_vault.research import intraday_final_test as final
    from market_vault.research import intraday_research as research
    root = snapshot.as_dict()
    before = snapshot.content
    path = write_strategy_experiment(snapshot, path=tmp_path / "saved-test.json").path
    execution = root["report"]["execution"]
    transactions = execution["transactions"]
    if require_actions:
        assert transactions, "this case must distinguish the actual TEST account"
    declaration = {"source": {"provider": "synthetic-saved-test-fixture", "version": "1",
        "captured_at": "2026-10-15T00:00:00Z", "data_kind": "SYNTHETIC",
        "upstream_id": None, "upstream_evidence": None}, "reference_clock_id": "capture",
        "policy": {"max_quote_age_ms": 10, "max_adverse_quote_bps": None}}
    declared = deepcopy(declaration)
    blocked = lambda *a, **kw: pytest.fail("saved TEST reconciliation read Q5, fitted or executed")
    with monkeypatch.context() as patch:
        for module, name in ((final, "load_intraday_dataset"), (final, "load_strategy_experiment"),
                (final, "run_intraday_final_test"), (final, "run_intraday_execution"),
                (final, "fit_quadratic_rows"), (research, "load_intraday_dataset"),
                (research, "_fit"), (research, "_evaluate_intraday_research"), (research, "run_intraday_execution")):
            patch.setattr(module, name, blocked)
        template = forward.create_intraday_forward_template(path, declaration)
        assert template["schema_version"] == forward.TEST_OBSERVATIONS_VERSION
        assert {key: template["expected_" + key] for key in
                ("experiment_id", "execution_id", "selection_id", "final_test_id")} == {
            "experiment_id": root["experiment_id"], "execution_id": execution["execution_id"],
            "selection_id": root["report"]["selection_id"], "final_test_id": root["report"]["final_test_id"]}
        keys = [(row["trading_day"], row["slot"], row["side"]) for row in transactions]
        assert [(row["trading_day"], row["slot"], row["side"]) for row in template["records"]] == keys
        assert all(row["action_ready_at"] is row["quote"] is row["paper_fill"] is None
                   for row in template["records"])
        split = root["report"]["context"]["split"]
        assert all(row["trading_day"] in split["TEST"] and row["trading_day"] not in split["VALIDATION"]
                   for row in template["records"])
        empty = forward.analyze_intraday_forward_reconciliation(path, template)
        assert empty["version"] == forward.TEST_RECONCILIATION_VERSION
        assert empty["status"] == ("NOT_MEASURED" if transactions else "NO_REFERENCE_ACTIONS")
        assert empty["summary"]["matched_record_count"] == len(transactions)
        assert empty["summary"]["missing_record_count"] == empty["summary"]["measured_quote_count"] == 0
        assert empty["source"]["selection_experiment_id"] == root["plan"]["selection"]["experiment_id"]
        assert empty["source"]["strategy"] == root["plan"]["selection"]["report"]["candidate"]["strategy"]
        assert empty["source"]["evaluation_scope"] == "FROZEN_SINGLE_CANDIDATE_TEST"
        assert empty["source"]["algorithm_versions"] == root["algorithm_versions"]
        assert empty["source"]["environment"] == root["environment"]
        assert empty["forward_capture_verified"] is empty["fills_verified"] is False
        measured = {**template, "records": [observed(row["reference"]) for row in empty["rows"]]}
        result = forward.analyze_intraday_forward_reconciliation(path, measured)
        assert result["status"] == ("RECONCILED" if transactions else "NO_REFERENCE_ACTIONS")
        assert result["summary"]["measured_quote_count"] == len(transactions)
        assert result["summary"]["reference_action_count"] == len(transactions)
        assert result["summary"]["quote_policy_exceeded_count"] == 0
        for key in ("expected_experiment_id", "expected_execution_id", "expected_final_test_id", "expected_selection_id"):
            with pytest.raises(ValueError, match="identity differs"):
                forward.analyze_intraday_forward_reconciliation(path, {**template, key: "0" * 64})
        with pytest.raises(ValueError, match="does not accept"):
            forward.create_intraday_forward_template(path, declaration, cost_index=0, candidate_index=0)
    assert snapshot.content == before == path.read_bytes()
    assert declaration == declared
    return path, template, result


def assert_saved_test_forward_cli(path, template, tmp_path):
    """One real installed/module round trip; other final cases reuse the API."""
    inputs = write_market_data_json(tmp_path / "declaration.json", {
        key: template[key] for key in ("source", "reference_clock_id", "policy")})
    before = path.read_bytes(), inputs.read_bytes()
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    cli = Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault")
    assert cli.is_file(), "the installed public entry must exist"
    reports = []
    for root in (False, True):
        command = ([str(cli), "--settings", str(tmp_path / "missing-settings.yaml"),
                    "research-intraday-forward-reconciliation"] if root else
                   [sys.executable, "-m", "market_vault.research.intraday_forward_reconciliation"])
        def call(arguments):
            return subprocess.run(command + ["--experiment", str(path)] + arguments, cwd=tmp_path,
                                  env=env, capture_output=True, text=True, timeout=90)
        output = tmp_path / f"template-{root}.json"
        args = ["--template-declaration", str(inputs), "--output", str(output)]
        exported = call(args)
        assert exported.returncode == 0, exported.stderr
        assert json.loads(exported.stdout)["status"] == "TEMPLATE_CREATED"
        assert json.loads(output.read_text()) == template
        content = output.read_bytes()
        assert call(args).returncode == 1 and output.read_bytes() == content
        for name, batch_value, expected, status in (
                ("unmeasured", template, 2, "NOT_MEASURED"),
                ("measured", {**template, "records": [observed(row["reference"]) for row in
                    forward.analyze_intraday_forward_reconciliation(path, template)["rows"]]}, 0, "RECONCILED"),
                ("wrong", {**template, "expected_final_test_id": "0" * 64}, 1, "FAILED")):
            observations = write_market_data_json(tmp_path / f"{name}-{root}-input.json", batch_value)
            target = tmp_path / f"{name}-{root}-report.json"
            completed = call(["--observations", str(observations), "--output", str(target)])
            assert completed.returncode == expected, completed.stderr
            payload = json.loads(completed.stderr if expected == 1 else completed.stdout)
            assert payload["version"] == forward.TEST_RECONCILIATION_VERSION
            assert payload["status"] == status
            if expected == 1:
                assert not target.exists()
            else:
                assert json.loads(target.read_text()) == payload["report"]
                reports.append(payload["report"])
    assert reports[:2] == reports[2:]
    assert (path.read_bytes(), inputs.read_bytes()) == before


def test_saved_test_forward_v3_exact_account_and_offline_cli(final_case, selection_case, tmp_path, monkeypatch):
    from market_vault.research import intraday_forward_reconciliation as forward
    # Relocate only this disposable saved snapshot's input locators, resealing
    # the existing identities without creating or executing another TEST.
    root = final_case[1].as_dict()
    selection = root["plan"]["selection"]
    selection["plan"]["source_experiment"]["path"] = str(tmp_path / "absent-dev.json")
    selection["report"]["context"]["intraday_data_path"] = str(tmp_path / "absent-q5.json")
    selection["report"]["plan_sha256"] = digest(selection["plan"])
    bind(selection["report"], "selection_id")
    bind(selection, "experiment_id")
    report = root["report"]
    report["selection_experiment_id"] = selection["experiment_id"]
    report["selection_id"] = report["context"]["selection_id"] = selection["report"]["selection_id"]
    snapshot = StrategyExperiment(sign_test(root))
    path, template, result = assert_saved_test_forward(snapshot, tmp_path, monkeypatch)
    assert not (tmp_path / "absent-dev.json").exists() and not (tmp_path / "absent-q5.json").exists()
    assert result["source"]["execution_id"] != root["report"]["benchmark"]["execution"]["execution_id"]
    partial = {**template, "records": [result["rows"][0]["observation"]]}
    value = forward.analyze_intraday_forward_reconciliation(path, partial)
    assert value["status"] == "PARTIAL" and value["summary"]["measured_quote_count"] == 1
    assert value["summary"]["missing_record_count"] == len(template["records"]) - 1
    complete = {**template, "records": [row["observation"] for row in result["rows"]],
                "policy": {**template["policy"], "max_adverse_quote_bps": 0}}
    exceeded = forward.analyze_intraday_forward_reconciliation(path, complete)
    assert exceeded["status"] == "RECONCILED"
    assert exceeded["summary"]["quote_policy_exceeded_count"] == len(template["records"])
    # The same envelope cannot be paired with a selection-only file or DEV.
    selection_path = write_strategy_experiment(selection_case[1], path=tmp_path / "selection-only.json").path
    for unsupported in (selection_path, selection_case[0]):
        with pytest.raises(ValueError, match="saved frozen-candidate TEST"):
            forward.analyze_intraday_forward_reconciliation(unsupported, template)
    assert_saved_test_forward_cli(path, template, tmp_path)


@pytest.mark.parametrize("fixture,name", [("ml_final_case", "fixed"), ("ml_final_case", "inner"),
    ("threshold_final_case", None), ("joint_final_case", "ridge"), ("joint_final_case", "quadratic")])
def test_saved_selected_test_forward_v3_uses_frozen_test_not_dev(request, tmp_path, monkeypatch, fixture, name):
    value = request.getfixturevalue(fixture)
    snapshot = (value[name].tested if fixture == "joint_final_case" else
                value[1] if fixture == "threshold_final_case" else value[1][name])
    assert_saved_test_forward(snapshot, tmp_path, monkeypatch)


def test_saved_flat_test_forward_retains_no_reference_actions(intraday_experiment, tmp_path, monkeypatch):
    selection = freeze_source(intraday_experiment, tmp_path / "source.json", index=0)
    report = final.run_intraday_final_test(selection)
    assert report["execution"]["transactions"] == []
    snapshot = final.create_intraday_test_experiment(selection, report)
    _, template, result = assert_saved_test_forward(snapshot, tmp_path, monkeypatch, require_actions=False)
    assert template["records"] == [] and result["status"] == "NO_REFERENCE_ACTIONS"
