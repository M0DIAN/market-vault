"""Q75 explicit saved-history behavior. All source research prices are synthetic."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.quality.market_data_comparison import write_market_data_json
from market_vault.research import intraday_history as history
from market_vault.research.intraday_data import digest
from market_vault.research.strategy_experiment import StrategyExperiment, canonical_json, write_strategy_experiment
from test_intraday_final_test import final_case, selection_case  # noqa: F401
from test_intraday_experiment import intraday_experiment  # noqa: F401
from test_intraday_research import research_case  # noqa: F401


@pytest.fixture(scope="module")
def history_case(selection_case, final_case, tmp_path_factory):
    parent = tmp_path_factory.mktemp("q75-history")
    selection = parent / "selection.json"
    tested = parent / "test.json"
    write_strategy_experiment(selection_case[1], path=selection)
    write_strategy_experiment(final_case[1], path=tested)
    return selection, tested


def declaration(path, *, purpose="PLAN_ONLY", days=None):
    return {"schema_version": history.DECLARATION_VERSION,
            "expected_experiment_id": json.loads(path.read_bytes())["experiment_id"],
            "recorded_at": "2026-10-13T03:30:00Z", "purpose": purpose,
            "observed_days": [] if days is None else days, "code_commit": None, "notes": "Retrospective test declaration"}


def test_actual_saved_entries_do_not_read_data_fit_or_test_and_preserve_inputs(history_case, tmp_path, monkeypatch):
    from market_vault.research import intraday_research, intraday_final_test
    selection, tested = history_case
    before = {p: p.read_bytes() for p in history_case}
    def forbidden(*args, **kwargs):
        pytest.fail("history performed Q5 I/O, model fitting or TEST execution")
    monkeypatch.setattr(intraday_research, "load_intraday_dataset", forbidden)
    monkeypatch.setattr(intraday_research, "_fit", forbidden)
    monkeypatch.setattr(intraday_final_test, "load_intraday_dataset", forbidden)
    monkeypatch.setattr(intraday_final_test, "run_intraday_final_test", forbidden)
    empty = history.analyze_intraday_test_history(selection, [])
    assert empty["status"] == "NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY"
    assert empty["independence_certified"] is False and empty["external_history_coverage"] == "UNKNOWN"
    declared = declaration(selection)
    event = history.create_intraday_history_event(selection, declared)
    assert event["source"]["data_id"] == json.loads(before[selection])["dataset_id"]
    assert event["source"]["recipe_set_id"] == digest(event["source"]["recipes"])
    assert event["declaration"] == declared and event["declaration"]["code_commit"] is None
    event_path = write_market_data_json(tmp_path / "planned.json", event)
    planned = history.analyze_intraday_test_history(selection, [event_path])
    assert planned["status"] == empty["status"] and planned["matches"][0]["recorded_use_overlap_days"] == []
    # A saved TEST cannot be presented as unseen even with no supplied history.
    already_tested = history.analyze_intraday_test_history(tested, [])
    assert already_tested["status"] == "KNOWN_EXPOSURE"
    assert already_tested["own_recorded_test_days"] == event["source"]["context"]["split"]["TEST"]
    test_event = history.create_intraday_history_event(tested, declaration(tested))
    test_path = write_market_data_json(tmp_path / "tested.json", test_event)
    assessed = history.analyze_intraday_test_history(selection, [test_path])
    assert assessed["status"] == "KNOWN_EXPOSURE" and len(assessed["known_exposure_days"]) == 6
    assert assessed["matches"][0]["declared_exposure_overlap_days"] == []
    assert assessed["matches"][0]["recorded_use_overlap_days"] == assessed["known_exposure_days"]
    assert all(p.read_bytes() == b for p, b in before.items())
    assert history.create_intraday_history_event(selection, declared) == event


def test_overlap_unknown_and_renaming_never_reset_recorded_exposure(history_case, tmp_path):
    selection, _ = history_case
    root = json.loads(selection.read_bytes())
    day = root["report"]["context"]["split"]["TEST"][0]
    inspected = history.create_intraday_history_event(selection, declaration(selection, purpose="INSPECT", days=[day]))
    inspected_path = write_market_data_json(tmp_path / "inspection.json", inspected)
    unknown = history.create_intraday_history_event(selection, declaration(selection, purpose="UNKNOWN"))
    unknown_path = write_market_data_json(tmp_path / "unknown.json", unknown)
    result = history.analyze_intraday_test_history(selection, [unknown_path])
    assert result["status"] == "UNKNOWN_RECORDED_EXPOSURE" and len(result["unknown_exposure_days"]) == 6
    # A metadata rename creates a different source ID, but does not reset the
    # same economic dates. Copying the event also does not inflate its weight.
    root["name"] = "Renamed candidate"
    root["experiment_id"] = digest({k: v for k, v in root.items() if k != "experiment_id"})
    renamed = tmp_path / "different-name.json"
    write_strategy_experiment(StrategyExperiment(canonical_json(root)), path=renamed)
    relocated = tmp_path / "relocated-event.json"
    relocated.write_bytes(inspected_path.read_bytes())
    result = history.analyze_intraday_test_history(renamed, [inspected_path, relocated, unknown_path])
    assert result["status"] == "KNOWN_EXPOSURE" and result["known_exposure_days"] == [day]
    assert result["input_count"] == 3 and result["unique_event_count"] == 2 and result["duplicate_event_count"] == 1
    assert result["matches"][0]["source_experiment_id"] != result["proposed_source"]["experiment_id"]
    assert len(result["unknown_exposure_days"]) == 6
    assert result["history_assessment_id"] == digest({k: v for k, v in result.items() if k != "history_assessment_id"})
    # A declared observation of DEV dates does not overlap the original TEST.
    previous_day = root["report"]["context"]["split"]["TRAIN"][0]
    older = history.create_intraday_history_event(selection, declaration(selection, purpose="TUNE", days=[previous_day]))
    older_path = write_market_data_json(tmp_path / "disjoint.json", older)
    assert history.analyze_intraday_test_history(selection, [older_path])["status"] == "NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY"


def test_relabeling_bar_interval_data_id_and_split_keeps_economic_overlap(history_case, tmp_path):
    selection, _ = history_case
    event = history.create_intraday_history_event(selection, declaration(selection))
    target = event["source"]["context"]["split"]["TEST"][0]
    # Imported declared history in which today's proposed TEST date previously
    # belonged to DEV. Its independent source metadata uses another data ID and
    # interval; these do not make the same symbol/day independent.
    source = event["source"]
    source["data_id"] = "a" * 64
    source["context"]["interval"] = "1m"
    source["context"]["split"]["VALIDATION"].append(source["context"]["split"]["TEST"].pop(0))
    event["event_id"] = digest({k: v for k, v in event.items() if k != "event_id"})
    path = write_market_data_json(tmp_path / "imported.json", history.validate_intraday_history_event(event))
    result = history.analyze_intraday_test_history(selection, [path])
    assert result["status"] == "KNOWN_EXPOSURE" and result["known_exposure_days"] == [target]
    # These are explicit imported metadata declarations, not replayed provenance.
    source["context"]["symbol"] = "US.AAPL"
    event["event_id"] = digest({k: v for k, v in event.items() if k != "event_id"})
    other = write_market_data_json(tmp_path / "other-symbol.json", event)
    other_result = history.analyze_intraday_test_history(selection, [other])
    assert other_result["status"] == "NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY"
    assert other_result["matches"][0]["same_symbol"] is False
    assert other_result["external_history_coverage"] == "UNKNOWN"


def test_malformed_or_stale_history_fails_not_silently_omitted(history_case, tmp_path):
    selection, _ = history_case
    base = declaration(selection)
    for change in ({"expected_experiment_id": "0" * 64}, {"code_commit": "latest"},
                   {"purpose": "INSPECT"}, {"recorded_at": "no-timezone"},
                   {"purpose": "TUNE", "observed_days": ["2020-01-02"]}):
        with pytest.raises(ValueError):
            history.create_intraday_history_event(selection, {**base, **change})
    event = history.create_intraday_history_event(selection, base)
    broken = deepcopy(event)
    broken["declaration"]["notes"] = "changed without an updated identity"
    path = write_market_data_json(tmp_path / "broken.json", broken)
    with pytest.raises(ValueError, match="event_id"):
        history.analyze_intraday_test_history(selection, [path])
    broken = deepcopy(event)
    broken["source"]["recipe_set_id"] = "b" * 64
    broken["event_id"] = digest({k: v for k, v in broken.items() if k != "event_id"})
    with pytest.raises(ValueError, match="recipe set identity"):
        history.validate_intraday_history_event(broken)
    with pytest.raises(ValueError, match="explicit file list"):
        history.analyze_intraday_test_history(selection, str(tmp_path))


def test_module_cli_creates_once_and_reports_overlap_exit_two(history_case, tmp_path, capsys):
    selection, tested = history_case
    declared = write_market_data_json(tmp_path / "declaration.json", declaration(tested))
    event_path = tmp_path / "event.json"
    command = ["record", "--experiment", str(tested), "--declaration", str(declared), "--output", str(event_path)]
    assert history.main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RECORDED"
    before = event_path.read_bytes()
    assert history.main(command) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED" and event_path.read_bytes() == before
    output = tmp_path / "assessment.json"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    process = subprocess.run([sys.executable, "-m", "market_vault.research.intraday_history", "assess",
                              "--experiment", str(selection), "--event", str(event_path), "--output", str(output)],
                             capture_output=True, text=True, timeout=90, env=env, cwd=tmp_path)
    assert process.returncode == 2, process.stderr
    envelope = json.loads(process.stdout)
    assert envelope["status"] == "KNOWN_EXPOSURE"
    assert json.loads(output.read_bytes()) == envelope["report"]
    assert event_path.read_bytes() == before
