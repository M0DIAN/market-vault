"""Q77: saved procedure history preserves declared families and TEST overlap."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.quality.market_data_comparison import write_market_data_json
from market_vault.research import intraday_history as history
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
