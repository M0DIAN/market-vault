"""Independent Q29 screening over real verified data and saved execution evidence.

Dataset publication uses the existing explicit MemoryFS model; these tests do
not qualify native publication or establish corporate-action feed coverage.
"""

from datetime import timedelta
import json

import pytest

import cross_day_helpers as cd
import ts2_feature_helpers as ts
from cross_day_dataset_helpers import fixture
from cross_day_artifact_memory_fs import MemoryFS
from market_vault import cli
from market_vault.cross_day_dataset import join_multi_source_cross_day_dataset, materialize_multi_source_cross_day_dataset_build
from market_vault.research import return_assessment as assessment
from market_vault.research.intraday_data import canonical_json
from market_vault.research.strategy_experiment import StrategyExperiment, load_strategy_experiment, write_strategy_experiment
from market_vault.ts2_feature import execute_ts2_features
from test_cross_day_artifact_publication_state import BUILT_AT
from test_strategy_comparison import verified_workspace_dataset  # noqa: F401
from test_strategy_experiment import experiment_snapshots  # noqa: F401
from test_intraday_research import research_case  # noqa: F401
from test_intraday_experiment import intraday_experiment, signed  # noqa: F401
from test_intraday_final_test import final_case, selection_case  # noqa: F401
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401


def _events(*items):
    return {"schema_version": assessment.RESTRICTION_LIST_VERSION,
            "provenance": "Explicit offline declaration; not an exhaustive action feed", "events": list(items)}


def _instant(clock, *, symbol="US.AAPL", event_id="declared-event"):
    return {"event_id": event_id, "symbol": symbol, "kind": "EFFECTIVE_INSTANT",
            "effective_at": clock, "source": "Offline test restriction"}


def _published(tmp_path, monkeypatch, *, incomplete=False, delayed=False):
    labels = tuple(cd.spec(transform=name, name="label_" + name) for name in (
        "forward_return", "forward_direction", "forward_open_to_close_return",
        "maximum_favorable_excursion", "maximum_adverse_excursion"))
    options = {"label_specs": labels}
    if delayed:
        options["label_bars"] = (cd.bar("2025-03-04", market=cd.local("2025-03-05", 0, 0)),)
    inputs = fixture(tmp_path / "upstream", "B" if incomplete else "A", **options)
    inputs["ts2_features"] = execute_ts2_features(
        inputs["cross_day_association"].feature_builds, inputs["feature_pit"],
        (ts.spec(), ts.spec("candle_body"), ts.spec("rolling_volume_mean")), dataset_as_of=inputs["dataset_as_of"])
    result = join_multi_source_cross_day_dataset(**inputs)
    model = MemoryFS(monkeypatch, tmp_path / "ONLY_IN_MEMORY_NOT_CREATED")
    dataset = materialize_multi_source_cross_day_dataset_build(result, output_root=model.root, built_at=BUILT_AT).verified
    return dataset, model


def test_dataset_actual_consumption_and_availability_are_distinct(tmp_path, monkeypatch):
    dataset, model = _published(tmp_path, monkeypatch, delayed=True)
    before, mutations = model.artifact(dataset.dataset_id), model.mutations
    result = assessment.assess_dataset(dataset.build_path)
    assert (result["coverage_status"], result["screening_status"]) == ("UNKNOWN", "NOT_CHECKED")
    assert result["price_basis"] == "NONE_UNADJUSTED"
    assert result["split_share_adjustment"] == result["cash_dividend_accounting"] == "NOT_APPLIED"
    assert result["window_counts"] == {"FEATURE": 2, "LABEL": 5, "total": 7, "crosses_market_dates": 4}
    assert result["omitted_counts"] == {"observation_features": 1, "volume_only_features": 1}
    by_name = {row["owner_id"].split(":")[1]: row for row in result["windows"]}
    assert by_name["ts2_simple_return"]["start_time"] == "2025-03-03T14:35:00.000000+00:00"
    assert by_name["ts2_candle_body"]["start_time"] == "2025-03-03T14:35:00.000000+00:00"
    assert by_name["ts2_candle_body"]["clock_basis"] == "CONSUMED_BAR_SPAN"
    for name in ("forward_return", "forward_direction", "maximum_favorable_excursion", "maximum_adverse_excursion"):
        row = by_name["label_" + name]
        assert row["start_time"] == "2025-03-03T14:40:00.000000+00:00"
        assert row["end_time"] == "2025-03-04T14:40:00.000000+00:00"
        assert row["crosses_market_dates"]
    execution = by_name["label_forward_open_to_close_return"]
    assert execution["start_time"] == "2025-03-04T14:35:00.000000+00:00"
    assert execution["end_time"] == "2025-03-04T14:40:00.000000+00:00"
    assert not execution["crosses_market_dates"]
    assert all(value.actual_label_end_time == cd.local("2025-03-05", 0, 0) for value in dataset.cross_day_labels.values)
    assert model.artifact(dataset.dataset_id) == before and model.mutations == mutations


def test_declared_overnight_event_does_not_block_next_day_open_to_close(tmp_path, monkeypatch):
    dataset, _ = _published(tmp_path, monkeypatch)
    events = _events(_instant("2025-03-04T09:30:00-05:00"))
    result = assessment.assess_dataset(dataset.build_path, events=events)
    assert result["coverage_status"] == "PARTIAL"
    assert result["screening_status"] == "KNOWN_RESTRICTION_INTERSECTION"
    hit_ids = {hit["window_id"] for hit in result["restriction_matches"]}
    assert len(hit_ids) == 4
    assert all(row["role"] == "LABEL" and row["crosses_market_dates"] for row in result["windows"] if row["window_id"] in hit_ids)
    exact_entry = assessment.assess_dataset(dataset.build_path, events=_events(_instant("2025-03-04T14:35:00Z")))
    assert len(exact_entry["restriction_matches"]) == 4
    exact_exit = assessment.assess_dataset(dataset.build_path, events=_events(_instant("2025-03-04T14:40:00Z")))
    assert len(exact_exit["restriction_matches"]) == 5
    wrong_symbol = assessment.assess_dataset(dataset.build_path, events=_events(_instant("2025-03-04T14:38:00Z", symbol="US.SPY")))
    assert wrong_symbol["screening_status"] == "NO_LISTED_INTERSECTION"


def test_partial_empty_and_conservative_dates_remain_distinct_from_unknown(tmp_path, monkeypatch):
    dataset, _ = _published(tmp_path, monkeypatch)
    empty = assessment.assess_dataset(dataset.build_path, events=_events())
    assert (empty["coverage_status"], empty["screening_status"]) == ("PARTIAL", "NO_LISTED_INTERSECTION")
    assert empty["restriction_list_id"] and not empty["restriction_matches"]
    dated = {"event_id": "date-only", "symbol": "US.AAPL", "kind": "DATE_RESTRICTION",
             "start_date": "2025-03-04", "end_date": "2025-03-04", "source": "No exact effective instant supplied"}
    result = assessment.assess_dataset(dataset.build_path, events=_events(dated))
    assert len(result["restriction_matches"]) == 5
    assert {hit["reason"] for hit in result["restriction_matches"]} == {"CONSERVATIVE_DATE_RESTRICTION_OVERLAP"}
    assert result["window_counts"]["crosses_market_dates"] == 4


def test_incomplete_label_evidence_is_not_executed_price_arithmetic(tmp_path, monkeypatch):
    dataset, _ = _published(tmp_path, monkeypatch, incomplete=True)
    result = assessment.assess_dataset(dataset.build_path, events=_events(_instant("2025-03-04T14:38:00Z")))
    assert result["omitted_counts"]["incomplete_price_labels"] == 5
    assert result["window_counts"] == {"FEATURE": 2, "total": 2, "crosses_market_dates": 0}
    assert result["restriction_matches"] == []


@pytest.mark.parametrize("mutation", ["version", "naive", "duplicate", "extra", "reversed", "symbol"])
def test_restriction_inputs_fail_closed(mutation):
    root = _events(_instant("2025-03-04T14:38:00Z"))
    if mutation == "version":
        root["schema_version"] = "future"
    elif mutation == "naive":
        root["events"][0]["effective_at"] = "2025-03-04T14:38:00"
    elif mutation == "duplicate":
        root["events"] *= 2
    elif mutation == "extra":
        root["coverage_complete"] = True
    elif mutation == "symbol":
        root["events"][0]["symbol"] = "AAPL"
    else:
        root["events"] = [{"event_id": "reversed", "symbol": "US.AAPL", "source": "test", "kind": "DATE_RESTRICTION",
                           "start_date": "2025-03-05", "end_date": "2025-03-04"}]
    with pytest.raises(ValueError):
        assessment.parse_event_restrictions(canonical_json(root))


def test_restriction_identity_normalizes_order_and_offsets():
    one = _instant("2025-03-04T14:38:00Z", event_id="one")
    two = _instant("2025-03-04T09:39:00-05:00", event_id="two")
    parsed = assessment.parse_event_restrictions(canonical_json(_events(two, one)))
    other = assessment.parse_event_restrictions(canonical_json(_events(one, {**two, "effective_at": "2025-03-04T14:39:00+00:00"})))
    assert parsed == other


@pytest.mark.parametrize("mode", ["COMPARISON", "EQUITY", "RISK"])
def test_saved_base_uses_bound_dataset_and_actual_trade_benchmark_windows(experiment_snapshots, verified_workspace_dataset,
                                                                        mode, tmp_path):
    source = experiment_snapshots[mode]
    path = tmp_path / "source.json"
    write_strategy_experiment(source, path=path)
    result = assessment.assess_saved_experiment(path)
    relocated = assessment.assess_saved_experiment(path, source_dataset=verified_workspace_dataset.build_path)
    assert result == relocated
    assert result["source_evidence"] == "VALIDATED_SAVED_RECORDS_NOT_REPLAYED"
    assert result["source_id"] == source.experiment_id
    assert result["dataset_id"] == verified_workspace_dataset.dataset_id
    assert result["window_counts"]["STRATEGY_TRADE"] == sum(len(row["trades"]) for row in source.as_dict()["report"]["results"])
    assert result["window_counts"].get("BENCHMARK_HOLDING", 0) == (1 if mode == "RISK" else 0)
    assert path.read_bytes() == source.content
    event = _events(_instant(result["windows"][0]["end_time"], symbol="US.SPY"))
    assert assessment.assess_saved_experiment(path, events=event)["restriction_matches"]


def test_base_relocated_source_must_match_recorded_identity(experiment_snapshots, tmp_path, monkeypatch):
    path = tmp_path / "source.json"
    write_strategy_experiment(experiment_snapshots["RISK"], path=path)
    different, _ = _published(tmp_path / "different", monkeypatch)
    with pytest.raises(assessment.ReturnAssessmentError, match="Dataset identity differs"):
        assessment.assess_saved_experiment(path, source_dataset=different.build_path)


def test_valid_delayed_comparison_has_an_assessment_only_precision_limit(tmp_path_factory, tmp_path):
    import pandas as pd
    from market_vault.canonical import bars
    from market_vault.strategy_comparison_io import evaluate_comparison_payload, normalized_comparison_plan
    from market_vault.research.strategy_experiment import create_strategy_experiment
    from test_strategy_comparison import _real_config

    original, changed = bars.bar_available_at, []
    def delayed(stamp, *args, **kwargs):
        result = original(stamp, *args, **kwargs)
        if stamp.tz_convert("America/New_York").isoformat().startswith("2026-01-15T15:55:00"):
            changed.append(stamp)
            return result + pd.Timedelta(minutes=1)
        return result
    generator = verified_workspace_dataset.__wrapped__(tmp_path_factory)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(bars, "bar_available_at", delayed)
            dataset = next(generator)
        assert changed  # Only source production was patched; all readers/engines are real.
        config = _real_config()
        plan = normalized_comparison_plan(config, dataset_build_dir=str(dataset.build_path))
        snapshot = create_strategy_experiment(plan=plan,
            report=evaluate_comparison_payload(dataset, config, "COMPARISON"), mode="COMPARISON")
        path = tmp_path / "delayed-comparison.json"
        write_strategy_experiment(snapshot, path=path)
        assert load_strategy_experiment(path).content == snapshot.content
        with pytest.raises(assessment.ReturnAssessmentError) as error:
            assessment.assess_saved_experiment(path)
        assert error.value.reason_code == "UNSUPPORTED_PRICE_CLOCK"
        assert "2026-01-15T21:01:00.000000+00:00" in str(error.value)
        assert "2026-01-15T21:00:00.000000+00:00" in str(error.value)
        assert "validity, Open and Replay behavior are unchanged" in str(error.value)
        assert path.read_bytes() == snapshot.content
    finally:
        generator.close()


def test_saved_intraday_and_test_use_each_actual_holding_only(intraday_experiment, final_case, tmp_path, monkeypatch):
    from market_vault.research import intraday_data, intraday_research
    monkeypatch.setattr(intraday_data, "load_intraday_dataset", lambda *a, **kw: pytest.fail("assessment loaded Q5"))
    monkeypatch.setattr(intraday_research, "run_intraday_execution", lambda *a, **kw: pytest.fail("assessment replayed execution"))
    for index, source in enumerate((intraday_experiment, final_case[1])):
        path = tmp_path / f"source-{index}.json"
        write_strategy_experiment(source, path=path)
        result = assessment.assess_saved_experiment(path)
        assert result["window_counts"]["BENCHMARK_HOLDING"] > 1
        assert result["window_counts"]["crosses_market_dates"] == 0
        assert result["source_kind"] == "SAVED_INTRADAY_EXPERIMENT"
        first = min(result["windows"], key=lambda row: row["start_time"])
        before_entry = _events(_instant(first["start_time"], symbol="US.SPY"))
        assert assessment.assess_saved_experiment(path, events=before_entry)["restriction_matches"] == []
        assert path.read_bytes() == source.content


def test_v2_multi_cost_quadratic_and_frozen_test_share_saved_window_adapter(quadratic_dev_case, tmp_path, monkeypatch):
    from market_vault.research import intraday_final_test as final, intraday_research as research
    from market_vault.research.intraday_experiment import create_intraday_experiment

    plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION,
            "comparison_plan": quadratic_dev_case[1], "strategy_name": "Quadratic",
            "parameter_axes": [{"parameter": "threshold", "values": [-1, 1]}],
            "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = tmp_path / "quadratic.json"
    write_strategy_experiment(source, path=path)
    root = source.as_dict()
    assert root["artifact_schema_version"] == "market-vault-intraday-experiment-v2"
    candidate = root["report"]["groups"][1]["results"][0]
    selection = final.freeze_intraday_candidate(path, expected_experiment_id=source.experiment_id,
        cost_index=1, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    tested = final.create_intraday_test_experiment(selection, final.run_intraday_final_test(selection))
    test_path = tmp_path / "quadratic-test.json"
    write_strategy_experiment(tested, path=test_path)
    assert tested.as_dict()["artifact_schema_version"] == "market-vault-intraday-test-v2"
    monkeypatch.setattr(research, "_fit", lambda *a, **kw: pytest.fail("saved assessment fitted a model"))
    monkeypatch.setattr(research, "run_intraday_execution", lambda *a, **kw: pytest.fail("saved assessment ran an account"))
    result = assessment.assess_saved_experiment(path)
    assert result["window_counts"]["STRATEGY_TRADE"] == sum(
        len(candidate["execution"]["trades"]) for group in root["report"]["groups"] for candidate in group["results"])
    assert result["window_counts"]["BENCHMARK_HOLDING"] == sum(
        len(group["benchmark"]["execution"]["trades"]) for group in root["report"]["groups"])
    assert assessment.assess_saved_experiment(test_path)["window_counts"]["crosses_market_dates"] == 0
    assert path.read_bytes() == source.content and test_path.read_bytes() == tested.content


@pytest.mark.parametrize("mutation", ["trade_time", "row_id", "ledger_time", "hidden_holding", "economic_version"])
def test_saved_hashes_do_not_replace_local_grid_or_economic_evidence(intraday_experiment, tmp_path, mutation):
    root = intraday_experiment.as_dict()
    execution = root["report"]["groups"][0]["results"][1]["execution"]
    if mutation == "trade_time":
        for name in ("signal_time", "entry_time", "exit_time"):
            execution["trades"][0][name] = (assessment._clock(execution["trades"][0][name]) + timedelta(days=3)).isoformat()
    elif mutation == "row_id":
        execution["trades"][0]["entry_row_version_id"] = "0" * 64
    elif mutation == "ledger_time":
        execution["ledger"][0]["timestamp"] = (assessment._clock(execution["ledger"][0]["timestamp"]) + timedelta(minutes=1)).isoformat()
    elif mutation == "hidden_holding":
        execution["ledger"][0]["quantity"] = 1.0
    else:
        root["algorithm_versions"]["execution"] = "historical-execution"
        for group in root["report"]["groups"]:
            for candidate in [*group["results"], group["benchmark"]]:
                candidate["execution"]["version"] = "historical-execution"
    source = StrategyExperiment(signed(root))  # The existing saved reader accepts these records.
    path = tmp_path / "source.json"
    write_strategy_experiment(source, path=path)
    with pytest.raises(assessment.ReturnAssessmentError) as error:
        assessment.assess_saved_experiment(path)
    assert error.value.reason_code == ("UNSUPPORTED_ECONOMIC_VERSION" if mutation == "economic_version" else "CONTRADICTORY_WINDOW_EVIDENCE")
    assert load_strategy_experiment(path).content == source.content


def test_cli_is_deterministic_settings_free_and_restrictions_have_distinct_status(tmp_path, monkeypatch, capsys):
    dataset, _ = _published(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "load_settings", lambda *a: pytest.fail("assessment loaded settings"))
    arguments = ["research-return-assessment", "--dataset", str(dataset.build_path)]
    assert cli.main(arguments) == 0
    first = capsys.readouterr()
    assert first.err == "" and json.loads(first.out)["screening_status"] == "NOT_CHECKED"
    assert cli.main(arguments) == 0
    assert capsys.readouterr().out == first.out
    events = tmp_path / "events.json"
    events.write_bytes(canonical_json(_events(_instant("2025-03-04T14:38:00Z"))))
    assert cli.main([*arguments, "--events", str(events)]) == 2
    hit = capsys.readouterr()
    assert hit.err == "" and json.loads(hit.out)["screening_status"] == "KNOWN_RESTRICTION_INTERSECTION"
    events.write_bytes(b'{"events": [], "events": []}')
    assert cli.main([*arguments, "--events", str(events)]) == 1
    invalid = capsys.readouterr()
    assert invalid.out == "" and json.loads(invalid.err)["status"] == "FAILED"
    assert cli.main([*arguments, "--experiment", "also.json"]) == 1
    assert json.loads(capsys.readouterr().err)["reason_code"] == "INVALID_INPUT"
