"""Q77/Q78: saved procedure history and selected-account acceptance entries.

Keep shared study fixtures in this module to avoid rebuilding them per action.
All observations are synthetic software evidence, not verified market capture.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.quality.market_data_comparison import write_market_data_json
from market_vault.research import intraday_history as history
from market_vault.research import intraday_forward_reconciliation as forward
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import digest
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_inner_selection import inner_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401
from test_strategy_intraday_joint_selection import joint_case  # noqa: F401
from test_strategy_intraday_forward_reconciliation import observed


ROOT = Path(__file__).resolve().parents[1]


def declaration(path, *, purpose="PLAN_ONLY", days=None):
    return {"schema_version": history.DECLARATION_VERSION,
            "expected_experiment_id": json.loads(path.read_bytes())["experiment_id"],
            "recorded_at": "2026-10-15T02:10:00Z", "purpose": purpose,
            "observed_days": [] if days is None else days, "code_commit": None,
            "notes": "Synthetic retrospective procedure declaration, not preregistration"}


@pytest.mark.parametrize("fixture_name,family_count", [("inner_case", 6), ("threshold_case", 4), ("joint_case", 24)])
def test_actual_offline_procedure_entry_keeps_source_and_complete_declared_family(
        request, fixture_name, family_count, monkeypatch):
    case = request.getfixturevalue(fixture_name)
    source, study, path = case[1], case[4], case[5]
    before = path.read_bytes()
    calls, loader = [], history.load_strategy_experiment
    def loaded(*args, **kwargs):
        calls.append(args[0])
        return loader(*args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("history read Q5, fitted or replayed a selection procedure")
    monkeypatch.setattr(history, "load_strategy_experiment", loaded)
    monkeypatch.setattr(research, "load_intraday_dataset", forbidden)
    monkeypatch.setattr(research, "_fit", forbidden)
    for module in (inner, threshold, joint):
        monkeypatch.setattr(module, "_evaluate", forbidden)
    event = history.create_intraday_history_event(path, declaration(path))
    assert calls == [path] and path.read_bytes() == before
    assert event["schema_version"] == history.PROCEDURE_EVENT_VERSION
    captured, original = event["source"], source.as_dict()
    assert captured["experiment_id"] == study.experiment_id
    assert captured["artifact_schema_version"] == study.as_dict()["artifact_schema_version"]
    assert captured["plan_id"] == digest(study.as_dict()["plan"])
    assert captured["context"]["split"] == original["report"]["context"]["split"]
    prefix = [{"strategy": candidate["strategy"], "execution_policy": group["execution_policy"]}
              for group in original["report"]["groups"] for candidate in group["results"]]
    selected = case[3]
    group = original["report"]["groups"][selected["cost_index"]]
    reference = group["results"][selected["candidate_index"]]["strategy"]
    models = [{"kind": kind, "alpha": alpha} for kind in ("RIDGE", "QUADRATIC_RIDGE") for alpha in (.1, 1., 10.)]
    members = ([{"threshold": t} for t in (0., .0005, .001, .002)] if family_count == 4 else
               models if family_count == 6 else [{**model, "threshold": t} for model in models for t in (0., .0005, .001, .002)])
    expected = [{"strategy": {**reference, **member}, "execution_policy": group["execution_policy"]} for member in members]
    assert captured["recipes"] == prefix + expected
    assert len(captured["recipes"]) == len(prefix) + family_count
    assert captured["recipe_set_id"] == digest(prefix + expected)
    assert history.validate_intraday_history_event(deepcopy(event)) == event


def test_mixed_legacy_and_procedure_history_uses_economic_dates_and_keeps_old_versions(inner_case, tmp_path):
    source_path, procedure_path = inner_case[2], inner_case[5]
    legacy = history.create_intraday_history_event(source_path, declaration(source_path))
    assert legacy["schema_version"] == history.EVENT_VERSION
    old = history.analyze_intraday_test_history(source_path, [])
    assert old["version"] == history.ASSESSMENT_VERSION
    day = legacy["source"]["context"]["split"]["TEST"][0]
    event = history.create_intraday_history_event(procedure_path, declaration(procedure_path, purpose="INSPECT", days=[day]))
    first = write_market_data_json(tmp_path / "procedure.json", event)
    copied = write_market_data_json(tmp_path / "renamed.json", event)
    old_path = write_market_data_json(tmp_path / "legacy.json", legacy)
    result = history.analyze_intraday_test_history(source_path, [old_path, first, copied])
    assert result["version"] == history.PROCEDURE_ASSESSMENT_VERSION
    assert result["status"] == "KNOWN_EXPOSURE" and result["known_exposure_days"] == [day]
    assert (result["input_count"], result["unique_event_count"], result["duplicate_event_count"]) == (3, 2, 1)
    assert result["independence_certified"] is False and result["external_history_coverage"] == "UNKNOWN"
    proposed = history.analyze_intraday_test_history(procedure_path, [])
    assert proposed["version"] == history.PROCEDURE_ASSESSMENT_VERSION
    assert proposed["status"] == "NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY"
    unknown = history.create_intraday_history_event(procedure_path, declaration(procedure_path, purpose="UNKNOWN"))
    unknown_path = write_market_data_json(tmp_path / "unknown.json", unknown)
    assert history.analyze_intraday_test_history(source_path, [unknown_path])["status"] == "UNKNOWN_RECORDED_EXPOSURE"


def test_unavailable_procedure_records_declared_family_without_claiming_fits(quadratic_dev_case, tmp_path):
    plan = deepcopy(quadratic_dev_case[1])
    plan["walk_forward"]["minimum_train_days"] = 14
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    source_path = write_strategy_experiment(source, path=tmp_path / "source.json").path
    reference = source.as_dict()["report"]["groups"][0]["results"][0]
    study = inner.run_intraday_inner_selection(source_path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=reference["candidate_id"])
    assert study.as_dict()["report"]["status"] == "UNAVAILABLE"
    assert study.as_dict()["report"]["selected_account"] is None
    path = write_strategy_experiment(study, path=tmp_path / "unavailable.json").path
    event = history.create_intraday_history_event(path, declaration(path))
    assert len(event["source"]["recipes"]) == 7  # One original recipe plus the declared six; not seven fits.
    assert history._recorded_use_days(event["source"]) == (
        event["source"]["context"]["split"]["TRAIN"] + event["source"]["context"]["split"]["VALIDATION"])
    with pytest.raises(ValueError, match="AVAILABLE selected procedure account"):
        forward.analyze_intraday_forward_reconciliation(path, procedure_observations(study.as_dict()))


def test_procedure_event_downgrade_and_rehashed_recipe_mismatch_fail(threshold_case):
    path = threshold_case[5]
    event = history.create_intraday_history_event(path, declaration(path))
    event["schema_version"] = history.EVENT_VERSION
    event["event_id"] = digest({k: v for k, v in event.items() if k != "event_id"})
    with pytest.raises(ValueError, match="version differs"):
        history.validate_intraday_history_event(event)
    event["schema_version"] = history.PROCEDURE_EVENT_VERSION
    event["source"]["recipes"].pop()
    event["event_id"] = digest({k: v for k, v in event.items() if k != "event_id"})
    with pytest.raises(ValueError, match="recipe set identity"):
        history.validate_intraday_history_event(event)


def test_actual_module_cli_emits_v2_and_preserves_exclusive_publication(threshold_case, tmp_path):
    path = threshold_case[5]
    declared = write_market_data_json(tmp_path / "declaration.json", declaration(path))
    output = tmp_path / "event.json"
    command = [sys.executable, "-m", "market_vault.research.intraday_history", "record",
               "--experiment", str(path), "--declaration", str(declared), "--output", str(output)]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(command, env=env, cwd=tmp_path, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"] == payload["report"]["schema_version"] == history.PROCEDURE_EVENT_VERSION
    before = output.read_bytes()
    result = subprocess.run(command, env=env, cwd=tmp_path, text=True, capture_output=True, timeout=90)
    assert result.returncode == 1 and output.read_bytes() == before
    assert json.loads(result.stderr)["status"] == "FAILED"


def procedure_observations(root, records=None):
    account = root["report"]["selected_account"]
    return {"schema_version": forward.PROCEDURE_OBSERVATIONS_VERSION,
            "expected_experiment_id": root["experiment_id"],
            "expected_execution_id": "0" * 64 if account is None else account["execution"]["execution_id"],
            "source": {"provider": "synthetic-procedure-fixture", "version": "1",
                       "captured_at": "2026-10-15T02:50:00Z", "data_kind": "SYNTHETIC",
                       "upstream_id": None, "upstream_evidence": None},
            "reference_clock_id": "capture", "policy": {"max_quote_age_ms": 10, "max_adverse_quote_bps": None},
            "records": [] if records is None else records}


@pytest.mark.parametrize("fixture_name,kind,applied", [
    ("inner_case", "INNER_MODEL_SELECTION", "refit"),
    ("threshold_case", "ECONOMIC_THRESHOLD_SELECTION", "application"),
    ("joint_case", "JOINT_ECONOMIC_SELECTION", "refit"),
])
def test_saved_selected_account_reconciliation_binds_actual_execution_not_fixed_reference(
        request, fixture_name, kind, applied, monkeypatch):
    case = request.getfixturevalue(fixture_name)
    root, path = case[4].as_dict(), case[5]
    report = root["report"]
    execution = report["selected_account"]["execution"]
    source = report["source_experiment"]
    symbol = source["report"]["context"]["symbol"]
    selected = root["plan"]["selection"]
    fixed = source["report"]["groups"][selected["cost_index"]]["results"][selected["candidate_index"]]
    rows = forward._reference_rows(execution, symbol)
    observations = procedure_observations(root, [observed(row) for row in rows])
    original, source_bytes = deepcopy(observations), path.read_bytes()
    loads, accounts = [], []
    loader, references = forward.load_strategy_experiment, forward._reference_rows
    def load(*args, **kwargs):
        loads.append(args[0])
        return loader(*args, **kwargs)
    def captured(account, symbol):
        accounts.append(account)
        return references(account, symbol)
    def forbidden(*args, **kwargs):
        pytest.fail("saved reconciliation reconstructed Q5, fitted or replayed a procedure")
    monkeypatch.setattr(forward, "load_strategy_experiment", load)
    monkeypatch.setattr(forward, "_reference_rows", captured)
    monkeypatch.setattr(research, "load_intraday_dataset", forbidden)
    monkeypatch.setattr(research, "_fit", forbidden)
    for module in (inner, threshold, joint):
        monkeypatch.setattr(module, "_evaluate", forbidden)
    result = forward.analyze_intraday_forward_reconciliation(path, observations)
    assert loads == [path] and accounts == [execution]
    assert path.read_bytes() == source_bytes and observations == original
    assert result["version"] == forward.PROCEDURE_RECONCILIATION_VERSION
    assert result["source"]["procedure_kind"] == kind
    assert result["source"]["experiment_id"] == root["experiment_id"]
    assert result["source"]["source_experiment_id"] == source["experiment_id"]
    assert result["source"]["execution_id"] == execution["execution_id"]
    assert result["source"]["fixed_reference"] == {
        **selected, "strategy": fixed["strategy"], "execution_id": fixed["execution"]["execution_id"]}
    assert result["source"]["outer_fold_recipes"] == [
        {"fold_id": row["fold_id"], "strategy": row[applied]["strategy"]} for row in report["outer_folds"]]
    assert "strategy" not in result["source"] and "candidate_id" not in result["source"]
    assert result["source"]["execution_policy"] == execution["policy"]
    assert result["status"] == ("RECONCILED" if rows else "NO_REFERENCE_ACTIONS")
    assert result["summary"]["reference_action_count"] == len(execution["transactions"])
    assert result["summary"]["matched_record_count"] == len(execution["transactions"])
    assert [(row["reference"]["trading_day"], row["reference"]["slot"], row["reference"]["side"])
            for row in result["rows"]] == [(tx["trading_day"], tx["slot"], tx["side"]) for tx in execution["transactions"]]
    for row, tx in zip(result["rows"], execution["transactions"], strict=True):
        assert row["reference"]["raw_open"] == tx["raw_open"]
        assert row["reference"]["modeled_fill_price"] == tx["fill_price"]
        spread = .03 if tx["side"] == "BUY" else .02
        assert row["metrics"]["quote_adverse_bps"]["value"] == pytest.approx(spread / tx["raw_open"] * 10000)
        assert row["metrics"]["paper_fill_adverse_bps"]["value"] == pytest.approx(.04 / tx["raw_open"] * 10000)
        assert row["metrics"]["quote_age_ms"]["value"] == 10
    assert result["forward_capture_verified"] is False and result["fills_verified"] is False
    assert result["reconciliation_id"] == digest({key: value for key, value in result.items() if key != "reconciliation_id"})
    for key in ("expected_experiment_id", "expected_execution_id"):
        with pytest.raises(ValueError, match="identity differs"):
            forward.analyze_intraday_forward_reconciliation(path, {**observations, key: "0" * 64})
    assert accounts == [execution]  # Wrong identities fail before reference extraction.


def test_procedure_partial_evidence_retains_selected_population_denominators(inner_case):
    root, path = inner_case[4].as_dict(), inner_case[5]
    execution = root["report"]["selected_account"]["execution"]
    rows = forward._reference_rows(execution, root["report"]["source_experiment"]["report"]["context"]["symbol"])
    assert len(rows) > 2
    first = observed(rows[0])
    unmatched = {**observed(rows[1]), "symbol": "US.AAPL"}
    batch = procedure_observations(root, [first, unmatched])
    result = forward.analyze_intraday_forward_reconciliation(path, batch)
    assert result["status"] == "PARTIAL"
    assert result["summary"] == {"reference_action_count": len(rows), "supplied_record_count": 2,
                                 "matched_record_count": 1, "unmatched_record_count": 1,
                                 "missing_record_count": len(rows) - 1, "measured_quote_count": 1,
                                 "quote_policy_exceeded_count": 0}
    assert result["unmatched_records"] == [unmatched]
    assert result["statistics"]["quote_adverse_bps"]["available_count"] == 1
    assert result["statistics"]["quote_adverse_bps"]["unavailable_count"] == len(rows) - 1
    assert all(row["metrics"]["quote_adverse_bps"]["value"] is None for row in result["rows"][1:])
    with pytest.raises(ValueError):
        forward.normalize_forward_observations({**batch, "expected_candidate_id": "0" * 64})
    with pytest.raises(ValueError, match="ordinary saved Q7"):
        forward.analyze_intraday_forward_reconciliation(path, {
            **{k: v for k, v in batch.items() if k != "expected_execution_id"},
            "schema_version": forward.OBSERVATIONS_VERSION, "cost_index": 0, "candidate_index": 0,
            "expected_candidate_id": "0" * 64})


def test_available_flat_procedure_is_not_unavailable_or_an_ordinary_v2_source(quadratic_dev_case, tmp_path):
    source, source_path = quadratic_dev_case[3], quadratic_dev_case[4]
    candidate = source.as_dict()["report"]["groups"][0]["results"][2]
    assert candidate["strategy"]["threshold"] == 1 and candidate["execution"]["metrics"]["trade_count"] == 0
    study = inner.run_intraday_inner_selection(source_path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=2, expected_candidate_id=candidate["candidate_id"])
    root = study.as_dict()
    assert root["report"]["status"] == "AVAILABLE"
    assert root["report"]["selected_account"]["execution"]["transactions"] == []
    path = write_strategy_experiment(study, path=tmp_path / "flat-procedure.json").path
    result = forward.analyze_intraday_forward_reconciliation(path, procedure_observations(root))
    assert result["status"] == "NO_REFERENCE_ACTIONS" and result["rows"] == []
    assert all(value["available_count"] == 0 and value["mean"] is None for value in result["statistics"].values())
    assert result["source"]["outer_fold_recipes"]
    with pytest.raises(ValueError, match="saved Q25/Q31/Q36"):
        forward.analyze_intraday_forward_reconciliation(source_path, {
            **procedure_observations(root), "expected_experiment_id": source.experiment_id})


def test_actual_procedure_forward_module_cli_v2_identity_and_exclusive_output(inner_case, tmp_path):
    root, path = inner_case[4].as_dict(), inner_case[5]
    rows = forward._reference_rows(root["report"]["selected_account"]["execution"],
                                   root["report"]["source_experiment"]["report"]["context"]["symbol"])
    assert rows
    batch = procedure_observations(root, [observed(row) for row in rows])
    observations = write_market_data_json(tmp_path / "observations.json", batch)
    output = tmp_path / "reconciliation.json"
    command = [sys.executable, "-m", "market_vault.research.intraday_forward_reconciliation",
               "--experiment", str(path), "--observations", str(observations), "--output", str(output)]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(command, env=env, cwd=tmp_path, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"] == payload["report"]["version"] == forward.PROCEDURE_RECONCILIATION_VERSION
    original = output.read_bytes()
    result = subprocess.run(command, env=env, cwd=tmp_path, text=True, capture_output=True, timeout=90)
    assert result.returncode == 1 and output.read_bytes() == original
    assert json.loads(result.stderr)["status"] == "FAILED"
    invalid = write_market_data_json(tmp_path / "wrong-account.json", {**batch, "expected_execution_id": "0" * 64})
    command[command.index("--observations") + 1] = str(invalid)
    missing = tmp_path / "not-published.json"
    command[-1] = str(missing)
    result = subprocess.run(command, env=env, cwd=tmp_path, text=True, capture_output=True, timeout=90)
    assert result.returncode == 1 and not missing.exists()
    assert json.loads(result.stderr)["version"] == forward.PROCEDURE_RECONCILIATION_VERSION
    assert "execution identity differs" in json.loads(result.stderr)["error"]
