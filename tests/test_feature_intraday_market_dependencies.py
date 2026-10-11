"""Actual Q5 windows, completeness and numerical endpoint evidence.

Fixtures are synthetic Canonical/Q5 artifacts. This mapping neither establishes
independent market accuracy nor recomputes Features, target returns or models.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from market_vault import cli
from market_vault.quality import market_data_comparison as q44
from market_vault.research import intraday_data as q5
from market_vault.research import intraday_market_dependencies as dependencies
from market_vault.research import intraday_market_evidence as market
from test_intraday_data import input_plan
from test_strategy_intraday_market_evidence import (
    DAYS, _data, _item, _plan, _reference, _scope, _write, q5_case,
)


def _observation(report, slot, day=DAYS[0]):
    return next(row for row in report["observations"] if (row["trading_day"], row["slot"]) == (day, slot))


def _count_partitions(report):
    summary = report["summary"]
    assert summary["observation_count"] == len(report["observations"])
    assert summary["observation_count"] == sum(summary["observation_status_counts"].values())
    assert summary["target_record_count"] == sum(summary["target_status_counts"].values())
    assert summary["target_endpoint_count"] == 2 * summary["target_status_counts"]["COMPLETE"]
    assert summary["target_endpoint_count"] == sum(summary["target_endpoint_status_counts"].values())
    assert (summary["target_completeness_support"]["bar_links"] + summary["target_session_end_shortfall"]
            == summary["target_declared_horizon_links"])
    for support in (summary["feature_support"], summary["target_completeness_support"]):
        assert support["bar_links"] == support["local_present_links"] + support["local_missing_links"]
        assert support["bar_links"] == sum(support["comparison_status_counts"].values())
        for counts in support["field_comparison_counts"].values():
            assert sum(counts.values()) == support["bar_links"]
    assert report["market_dependencies_id"] == q5.digest(
        {key: value for key, value in report.items() if key != "market_dependencies_id"})


def test_two_day_hand_oracle_actual_row_ids_and_one_strict_capture(q5_case, tmp_path, monkeypatch):
    paths = [_write(tmp_path / f"{day}.json", _reference(q5_case, scope=_scope(day))) for day in DAYS]
    plan = _plan(*(_item(path, _scope(day)) for path, day in zip(paths, DAYS, strict=True)))
    before = {path: path.read_bytes() for path in (q5_case.path, *paths)}
    original_plan, original = deepcopy(plan), q5_case.as_dict()
    reads, verifies, derivations, references = [], [], [], []
    read, verify, derive, capture = q5._read, q5.verify_intraday_dataset, market._analyze_verified, q44._file_input

    def read_once(path):
        reads.append(path)
        return read(path)

    def verify_once(snapshot):
        verifies.append(snapshot.data_id)
        return verify(snapshot)

    def derive_once(snapshot, normalized):
        derivations.append(snapshot.data_id)
        return derive(snapshot, normalized)

    def capture_once(path):
        references.append(path)
        return capture(path)

    monkeypatch.setattr(q5, "_read", read_once)
    monkeypatch.setattr(q5, "verify_intraday_dataset", verify_once)
    monkeypatch.setattr(market, "_analyze_verified", derive_once)
    monkeypatch.setattr(q44, "_file_input", capture_once)
    report = dependencies.analyze_intraday_market_dependencies(q5_case.path, plan)
    assert reads == [q5_case.path] and verifies == derivations == [q5_case.data_id]
    assert references == [str(path) for path in paths]
    assert report["status"] == "REPORTED" and report["market_evidence"]["status"] == "AVAILABLE"
    assert report["data_id"] == q5_case.data_id and report["market_accuracy_certified"] is False
    assert report["market_evidence_id"] == report["market_evidence"]["market_evidence_id"]
    assert report["market_evidence"]["data"]["source_build_ids"] == original["source_build_ids"]
    summary = report["summary"]
    assert summary["observation_count"] == summary["target_record_count"] == 148
    assert summary["observation_status_counts"] == {"READY": 148, "UNAVAILABLE": 0}
    assert summary["target_status_counts"] == {"COMPLETE": 142, "INCOMPLETE": 6}
    assert summary["target_reason_counts"] == {"SESSION_END": 6, "MISSING_PRICE": 0}
    assert summary["feature_support"]["bar_links"] == 740
    assert summary["target_completeness_support"]["bar_links"] == 432
    assert summary["target_session_end_shortfall"] == 12 and summary["target_declared_horizon_links"] == 444
    assert summary["target_endpoint_count"] == summary["target_endpoint_status_counts"]["MATCH"] == 284
    assert summary["complete_targets_with_endpoint_price_disagreement"] == 0
    assert summary["complete_targets_without_full_endpoint_comparison"] == 0
    prices = report["market_evidence"]["rows"]
    assert len(prices) == 156 and len(report["market_evidence"]["sessions"]) == 2
    for index, (saved, observation, target) in enumerate(zip(
            report["observations"], original["report"]["observations"], original["report"]["targets"], strict=True)):
        assert saved["observation_index"] == index and saved["observation_key"] == observation["observation_key"]
        assert saved["observation_status"] == observation["status"] and saved["observation_reason"] == observation["reason"]
        assert saved["feature_value_ids"] == observation["feature_value_ids"]
        assert saved["target"]["status"] == target["status"] and saved["target"]["reason"] == target["reason"]
        assert saved["target"]["value"] == target["value"]
        assert saved["target"]["actual_label_end_time"] == target["actual_label_end_time"]
        support = saved["feature_support"]
        assert len(support["bar_indices"]) == support["counts"]["bar_links"] == 5
        actual_bars = [prices[i] for i in support["bar_indices"]]
        assert [row["slot"] for row in actual_bars] == list(range(observation["slot"] - 4, observation["slot"] + 1))
        assert q44.parse_utc(actual_bars[0]["start"]) == q44.parse_utc(observation["window_start"])
        assert q44.parse_utc(actual_bars[-1]["end"]) == q44.parse_utc(observation["decision_time"])
        if target["status"] == "COMPLETE":
            for role, field in (("entry", "open"), ("exit", "close")):
                endpoint = saved["target"]["endpoints"][role]
                bar = prices[endpoint["bar_index"]]
                assert endpoint["field"] == field and endpoint["evidence_status"] == "MATCH"
                assert endpoint["row_version_id"] == bar["row_version_id"] == target[role + "_row_version_id"]
                assert bar["trading_day"] == saved["trading_day"]
        else:
            assert saved["target"]["endpoints"] is None
    # Q5 records +00:00; Q46 renders Z. Their actual instants still bind.
    assert original["report"]["observations"][0]["decision_time"].endswith("+00:00")
    assert prices[5]["start"].endswith("Z")
    assert plan == original_plan and q5_case.as_dict() == original
    assert all(path.read_bytes() == content for path, content in before.items())
    _count_partitions(report)


def test_windows_and_completeness_do_not_turn_volume_or_high_into_endpoint_disagreement(q5_case, tmp_path):
    reference = _reference(q5_case)
    reference["bars"][5]["close"] += .5  # Just before the selected Feature support.
    reference["bars"][6]["volume"] += 10
    reference["bars"][11]["volume"] += 10  # Actual entry: only open is a target endpoint.
    reference["bars"][12]["high"] += 1  # Middle target-completeness bar.
    reference["bars"][13]["high"] += 1  # Actual exit: only close is a target endpoint.
    path = _write(tmp_path / "fields.json", reference)
    report = dependencies.analyze_intraday_market_dependencies(q5_case, _plan(_item(path)))
    observation = _observation(report, 10)
    assert observation["feature_support"]["bar_indices"] == [6, 7, 8, 9, 10]
    assert observation["feature_support"]["counts"]["comparison_status_counts"]["DIFFERENT"] == 1
    support = observation["target"]["completeness_support"]
    assert support["bar_indices"] == [11, 12, 13]
    assert support["counts"]["comparison_status_counts"]["DIFFERENT"] == 3
    assert support["counts"]["field_comparison_counts"]["open"]["matched_links"] == 3
    assert support["counts"]["field_comparison_counts"]["close"]["matched_links"] == 3
    assert {endpoint["evidence_status"] for endpoint in observation["target"]["endpoints"].values()} == {"MATCH"}
    assert report["summary"]["complete_targets_with_endpoint_price_disagreement"] == 0
    original = next(row for row in q5_case.as_dict()["report"]["targets"] if row["observation_key"] == observation["observation_key"])
    assert observation["target"]["value"] == original["value"]
    _count_partitions(report)


def test_partial_endpoint_disagreement_and_incomplete_comparison_can_overlap(q5_case, tmp_path):
    scope = _scope(first=11, count=2)
    reference = _reference(q5_case, scope=scope)
    reference["bars"][0]["open"] += .5
    path = _write(tmp_path / "partial.json", reference)
    report = dependencies.analyze_intraday_market_dependencies(q5_case, _plan(_item(path, scope)))
    target = _observation(report, 10)["target"]
    assert target["status"] == "COMPLETE"
    assert target["endpoints"]["entry"]["evidence_status"] == "DIFFERENT"
    assert target["endpoints"]["exit"]["evidence_status"] == "UNASSESSED"
    assert report["market_evidence"]["status"] == "PARTIAL"
    assert report["summary"]["complete_targets_with_endpoint_price_disagreement"] == 1
    assert report["summary"]["complete_targets_without_full_endpoint_comparison"] == 142
    assert report["summary"]["observation_count"] == 148 and len(report["market_evidence"]["rows"]) == 156
    _count_partitions(report)


def test_endpoint_price_changes_can_cancel_in_the_original_target_ratio(q5_case, tmp_path):
    reference = _reference(q5_case)
    for slot in (11, 13):
        for field in ("open", "high", "low", "close"):
            reference["bars"][slot][field] *= 2
    path = _write(tmp_path / "same-ratio.json", reference)
    report = dependencies.analyze_intraday_market_dependencies(q5_case, _plan(_item(path)))
    target = _observation(report, 10)["target"]
    assert {endpoint["evidence_status"] for endpoint in target["endpoints"].values()} == {"DIFFERENT"}
    assert reference["bars"][13]["close"] / reference["bars"][11]["open"] - 1 == pytest.approx(target["value"])
    assert any("does not prove a changed target return" in text for text in report["limitations"])
    assert "external_target" not in target and "target_difference" not in target


def test_original_session_end_priority_and_missing_price_keep_absent_endpoints(tmp_path):
    data = _data(tmp_path / "tail-gap", days=(DAYS[0],), missing=((DAYS[0], 77),))
    report = dependencies.analyze_intraday_market_dependencies(data, _plan())
    missing = _observation(report, 74)["target"]
    short = _observation(report, 75)["target"]
    assert missing["reason"] == "MISSING_PRICE" and missing["completeness_support"]["session_end_shortfall"] == 0
    assert short["reason"] == "SESSION_END" and short["completeness_support"]["session_end_shortfall"] == 1
    assert short["completeness_support"]["bar_indices"] == [76, 77]
    assert short["completeness_support"]["counts"]["local_missing_links"] == 1
    for target in (missing, short):
        assert target["status"] == "INCOMPLETE" and target["endpoints"] is None
        assert target["actual_label_end_time"] is None and target["value"] is None
    assert _observation(report, 77)["observation_status"] == "UNAVAILABLE"
    assert _observation(report, 77)["observation_reason"] == "FEATURE_WINDOW_INCOMPLETE"
    assert _observation(report, 77)["feature_support"]["counts"]["local_missing_links"] == 1
    assert report["summary"]["target_reason_counts"] == {"SESSION_END": 3, "MISSING_PRICE": 1}
    assert report["market_evidence"]["rows"][77]["local_state"] == "MISSING"
    assert report["market_evidence"]["status"] == "UNAVAILABLE"
    _count_partitions(report)


def test_present_q5_support_and_complete_endpoint_can_be_blocked_by_q44(tmp_path):
    data = _data(tmp_path / "admitted", days=(DAYS[0],), inconsistent_ohlc=True)
    reference = _reference(data)
    reference["bars"][0]["high"] = 150
    reference["bars"].append(deepcopy(reference["bars"][5]))
    path = _write(tmp_path / "blocked.json", reference)
    report = dependencies.analyze_intraday_market_dependencies(data, _plan(_item(path)))
    bar = report["market_evidence"]["rows"][0]
    assert bar["local_state"] == "PRESENT" and bar["comparison_local_state"] == "INVALID"
    first = _observation(report, 4)
    counts = first["feature_support"]["counts"]
    assert counts["local_present_links"] == 5 and counts["local_missing_links"] == 0
    assert counts["comparison_status_counts"]["BLOCKED"] == 1
    assert first["target"]["status"] == "COMPLETE"
    assert first["target"]["completeness_support"]["counts"]["local_present_links"] == 3
    assert first["target"]["endpoints"]["entry"]["evidence_status"] == "BLOCKED"
    assert first["target"]["endpoints"]["exit"]["evidence_status"] == "MATCH"
    assert report["market_evidence"]["rows"][5]["local_state"] == "PRESENT"
    _count_partitions(report)


@pytest.mark.parametrize("horizon", [1, None, 2**31 - 1])
def test_horizon_one_disabled_and_huge_remain_bounded_to_each_actual_session(q5_case, horizon, monkeypatch):
    data = q5.build_intraday_dataset({**q5_case.as_dict()["plan"], "target_horizon_bars": horizon})
    verify, calls = dependencies.verify_intraday_dataset, []

    def checked(snapshot):
        calls.append(snapshot.data_id)
        return verify(snapshot)

    monkeypatch.setattr(dependencies, "verify_intraday_dataset", checked)
    report = dependencies.analyze_intraday_market_dependencies(data, _plan())
    assert calls == [data.data_id]
    assert report["sampling"]["target_horizon_bars"] == horizon
    assert report["summary"]["observation_count"] == 148
    assert report["summary"]["feature_support"]["bar_links"] == 740
    assert report["market_evidence"]["summary"]["counts"]["UNASSESSED"] == 156
    if horizon is None:
        assert all(row["target"] is None for row in report["observations"])
        assert report["summary"]["no_target_observation_count"] == 148
        assert report["summary"]["target_record_count"] == report["summary"]["target_endpoint_count"] == 0
    elif horizon == 1:
        assert report["summary"]["target_status_counts"] == {"COMPLETE": 146, "INCOMPLETE": 2}
        assert report["summary"]["target_endpoint_count"] == 292
        first = _observation(report, 4)["target"]
        assert first["endpoints"]["entry"]["bar_index"] == first["endpoints"]["exit"]["bar_index"] == 5
        assert first["endpoints"]["entry"]["field"] == "open" and first["endpoints"]["exit"]["field"] == "close"
    else:
        assert report["summary"]["target_status_counts"] == {"COMPLETE": 0, "INCOMPLETE": 148}
        assert report["summary"]["target_reason_counts"]["SESSION_END"] == 148
        assert report["summary"]["target_completeness_support"]["bar_links"] == 5402
        assert report["summary"]["target_session_end_shortfall"] == 148 * horizon - 5402
        assert _observation(report, 4)["target"]["completeness_support"]["bar_indices"] == list(range(5, 78))
        assert _observation(report, 77)["target"]["completeness_support"]["bar_indices"] == []
        assert _observation(report, 4, DAYS[1])["target"]["completeness_support"]["bar_indices"] == list(range(83, 156))
    _count_partitions(report)


def test_zero_observation_session_retains_market_grid_and_zero_denominators(tmp_path):
    data = q5.build_intraday_dataset(input_plan(tmp_path, interval="30m", preset="CORE_TECHNICAL"))
    report = dependencies.analyze_intraday_market_dependencies(data, _plan())
    assert report["observations"] == [] and len(report["market_evidence"]["rows"]) == 13
    assert len(report["market_evidence"]["sessions"]) == 1
    summary = report["summary"]
    assert summary["observation_count"] == summary["target_record_count"] == summary["no_target_observation_count"] == 0
    assert summary["feature_support"]["bar_links"] == summary["target_completeness_support"]["bar_links"] == 0
    assert summary["target_endpoint_count"] == summary["target_declared_horizon_links"] == 0
    _count_partitions(report)


def test_actual_cli_relative_manifest_strict_q5_exclusive_output_and_recovery(q5_case, tmp_path, capsys, monkeypatch):
    manifest_dir = tmp_path / "plans"
    manifest_dir.mkdir()
    reference = _write(manifest_dir / "reference.json", _reference(q5_case))
    manifest = _write(manifest_dir / "plan.json", _plan(_item(Path("reference.json"))))
    before = {path: path.read_bytes() for path in (q5_case.path, reference, manifest)}
    output, other = tmp_path / "report.json", tmp_path / "again.json"
    monkeypatch.chdir(tmp_path)
    command = ["--settings", str(tmp_path / "absent-settings.yaml"), "research-intraday-market-dependencies",
               "--data", str(q5_case.path), "--manifest", str(manifest), "--output"]
    assert cli.main([*command, str(output)]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert not captured.err and result["status"] == "SUCCESS"
    assert result["report"]["market_evidence"]["references"][0]["snapshot_locator"] == str(reference)
    assert json.loads(output.read_bytes()) == result["report"]
    saved = output.read_bytes()
    assert cli.main([*command, str(output)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED" and output.read_bytes() == saved
    forged = q5_case.as_dict()
    forged["report"]["targets"][0]["entry_row_version_id"] = forged["report"]["prices"][6]["row_version_id"]
    forged["data_id"] = q5._data_identity(forged)
    bad_data, bad_output = tmp_path / "forged.json", tmp_path / "failed.json"
    bad_data.write_bytes(q5.canonical_json(forged))
    assert cli.main(["research-intraday-market-dependencies", "--data", str(bad_data),
                     "--manifest", str(manifest), "--output", str(bad_output)]) == 1
    failed = json.loads(capsys.readouterr().err)
    assert failed["status"] == "FAILED" and "source reconstruction" in failed["error"] and not bad_output.exists()
    assert cli.main([*command, str(other)]) == 0
    assert json.loads(capsys.readouterr().out)["report"] == result["report"] and other.read_bytes() == saved
    assert all(path.read_bytes() == content for path, content in before.items())
