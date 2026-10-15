"""Q76 actual saved-account/CLI checks and independent small clock/price oracles.

All market prices and observations here are synthetic. They prove calculations
and boundary behavior, not observed market accuracy or obtainable fills.
"""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.quality.market_data_comparison import utc_text, write_market_data_json
from market_vault.research import intraday_forward_reconciliation as forward
from market_vault.research.intraday_data import digest
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_intraday_experiment import intraday_experiment  # noqa: F401
from test_intraday_research import research_case  # noqa: F401


def stamp(time, ms=0, clock="capture"):
    return {"timestamp": utc_text(datetime.fromisoformat(time.replace("Z", "+00:00")) + timedelta(milliseconds=ms)),
            "clock_id": clock}


def observed(reference):
    time = reference["reference_open_time"]
    return {**{key: reference[key] for key in ("symbol", "trading_day", "slot", "side")},
            "action_ready_at": stamp(time, 20),
            "quote": {"bid": reference["raw_open"] - .02, "ask": reference["raw_open"] + .03,
                      "observed_at": stamp(time, 40), "received_at": stamp(time, 50)},
            "paper_fill": {"price": reference["raw_open"] + (.04 if reference["side"] == "BUY" else -.04),
                           "filled_at": stamp(time, 45)}}


def batch(root, *, index=1, complete=False):
    candidate = root["report"]["groups"][0]["results"][index]
    references = forward._reference_rows(candidate["execution"], root["report"]["context"]["symbol"])
    return {"schema_version": forward.OBSERVATIONS_VERSION, "expected_experiment_id": root["experiment_id"],
            "cost_index": 0, "candidate_index": index, "expected_candidate_id": candidate["candidate_id"],
            "source": {"provider": "synthetic-unit-fixture", "version": "1", "captured_at": "2026-10-15T00:00:00Z",
                       "data_kind": "SYNTHETIC", "upstream_id": None, "upstream_evidence": None},
            "reference_clock_id": "capture", "policy": {"max_quote_age_ms": 10, "max_adverse_quote_bps": None},
            "records": [observed(row) for row in references] if complete else []}


def reference(side="BUY"):
    return {"symbol": "US.SPY", "trading_day": "2025-03-03", "slot": 5, "side": side,
            "reference_open_time": "2025-03-03T14:55:00Z", "raw_open": 100.0, "modeled_fill_price": 100.05}


def test_hand_computable_bid_ask_side_cost_and_clock_separation():
    settings = {"reference_clock_id": "capture", "policy": {"max_quote_age_ms": 10, "max_adverse_quote_bps": 2.5}}
    for side, expected in (("BUY", 3), ("SELL", 2)):
        ref = reference(side)
        row = forward._reconcile(ref, observed(ref), settings)
        assert row["quote_status"] == "MEASURED"
        assert row["metrics"]["quote_adverse_bps"]["value"] == pytest.approx(expected)
        assert row["metrics"]["paper_fill_adverse_bps"]["value"] == pytest.approx(4)
        assert row["quote_policy_exceeded"] is (side == "BUY")
        assert {key: row["metrics"][key]["value"] for key in forward._METRICS if key.endswith("_ms")} == {
            "reference_to_ready_ms": 20, "ready_to_quote_ms": 30, "quote_age_ms": 10, "ready_to_paper_fill_ms": 25}
        assert row["reference"]["modeled_fill_price"] == 100.05  # Not the price denominator; costs not applied again.
    assert forward._bps(99, 100, "BUY")["value"] == -100
    assert forward._bps(101, 100, "SELL")["value"] == -100


def test_missing_stale_crossed_and_unrelated_clocks_do_not_turn_into_zero():
    ref = reference()
    settings = {"reference_clock_id": "capture", "policy": {"max_quote_age_ms": 10, "max_adverse_quote_bps": 3}}
    missing = forward._reconcile(ref, None, settings)
    assert missing["quote_status"] == "NO_OBSERVATION"
    assert all(item["value"] is None for item in missing["metrics"].values())
    for change, reason in (("stale", "STALE_QUOTE"), ("crossed", "CROSSED_QUOTE"),
                           ("partial", "MISSING_BID_ASK"), ("clock", "QUOTE_CLOCK_UNRESOLVED"),
                           ("absent", "NO_QUOTE")):
        row = observed(ref)
        if change == "stale":
            row["quote"]["received_at"] = stamp(ref["reference_open_time"], 50.001)
        elif change == "crossed":
            row["quote"]["bid"] = 101
        elif change == "partial":
            row["quote"]["ask"] = None
        elif change == "clock":
            row["quote"]["observed_at"]["clock_id"] = "unrelated-feed"
        else:
            row["quote"] = None
        result = forward._reconcile(ref, row, settings)
        assert result["quote_status"] == reason and result["quote_policy_exceeded"] is None
        assert result["metrics"]["quote_adverse_bps"]["value"] is None
        assert result["metrics"]["paper_fill_adverse_bps"]["value"] == pytest.approx(4)
    result = forward._reconcile(ref, observed(ref), {**settings, "reference_clock_id": None})
    assert result["quote_status"] == "REFERENCE_CLOCK_UNRESOLVED"
    assert result["metrics"]["reference_to_ready_ms"]["value"] is None
    assert result["metrics"]["ready_to_quote_ms"]["value"] == 30
    assert result["metrics"]["paper_fill_adverse_bps"]["value"] is None
    with pytest.raises(ValueError, match="same-clock ordering"):
        forward._elapsed(stamp(ref["reference_open_time"], 5), stamp(ref["reference_open_time"], 4))


@pytest.fixture(scope="module")
def forward_case(intraday_experiment, tmp_path_factory):
    path = tmp_path_factory.mktemp("q76-saved") / "development.json"
    write_strategy_experiment(intraday_experiment, path=path)
    return path, intraday_experiment.as_dict()


def test_public_entry_verifies_saved_source_once_without_q5_fit_or_execution(forward_case, monkeypatch):
    from market_vault.research import intraday_research
    path, root = forward_case
    source_before, original = path.read_bytes(), batch(root, complete=True)
    saved, calls = forward.load_strategy_experiment, []
    def load(*args, **kwargs):
        calls.append(1)
        return saved(*args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("reconciliation reconstructed Q5, fitted or re-executed")
    monkeypatch.setattr(forward, "load_strategy_experiment", load)
    monkeypatch.setattr(intraday_research, "load_intraday_dataset", forbidden)
    monkeypatch.setattr(intraday_research, "_fit", forbidden)
    monkeypatch.setattr(intraday_research, "run_intraday_execution", forbidden)
    frozen = deepcopy(original)
    report = forward.analyze_intraday_forward_reconciliation(path, original)
    assert report["status"] == "RECONCILED" and calls == [1]
    transactions = root["report"]["groups"][0]["results"][1]["execution"]["transactions"]
    count = len(transactions)
    assert count > 0 and report["summary"]["reference_action_count"] == count
    assert report["summary"]["measured_quote_count"] == count
    assert all(row["metrics"]["ready_to_quote_ms"]["value"] == 30 for row in report["rows"])
    assert all(row["reference"]["signal_bar_end_time"] is None for row in report["rows"]
               if row["reference"]["reason"] in ("EOD", "MAX_HOLD"))
    for row, tx in zip(report["rows"], transactions, strict=True):
        assert row["reference"]["raw_open"] == tx["raw_open"]
        assert row["reference"]["side"] == tx["side"]
    assert report["fills_verified"] is report["forward_capture_verified"] is False
    assert report["reconciliation_id"] == digest({k: v for k, v in report.items() if k != "reconciliation_id"})
    assert original == frozen and path.read_bytes() == source_before
    assert forward.analyze_intraday_forward_reconciliation(path, original) == report and calls == [1, 1]


def test_partial_unmatched_empty_and_flat_keep_all_reference_denominators(forward_case):
    path, root = forward_case
    complete = batch(root, complete=True)
    empty = forward.analyze_intraday_forward_reconciliation(path, batch(root))
    count = empty["summary"]["reference_action_count"]
    assert empty["status"] == "NOT_MEASURED" and empty["summary"]["missing_record_count"] == count
    assert empty["statistics"]["quote_adverse_bps"]["mean"] is None
    partial = deepcopy(complete)
    partial["records"] = partial["records"][:1]
    other = deepcopy(partial["records"][0])
    other["symbol"] = "US.AAPL"
    partial["records"].append(other)
    result = forward.analyze_intraday_forward_reconciliation(path, partial)
    assert result["status"] == "PARTIAL"
    assert result["summary"] == {"reference_action_count": count, "supplied_record_count": 2,
                                 "matched_record_count": 1, "unmatched_record_count": 1,
                                 "missing_record_count": count - 1, "measured_quote_count": 1,
                                 "quote_policy_exceeded_count": 0}
    assert result["unmatched_records"] == [other]
    assert result["statistics"]["quote_adverse_bps"]["available_count"] == 1
    assert result["statistics"]["quote_adverse_bps"]["unavailable_count"] == count - 1
    flat = forward.analyze_intraday_forward_reconciliation(path, batch(root, index=0))
    assert flat["status"] == "NO_REFERENCE_ACTIONS" and flat["rows"] == []
    changed = deepcopy(partial)
    changed["policy"]["max_adverse_quote_bps"] = 0
    judged = forward.analyze_intraday_forward_reconciliation(path, changed)
    assert judged["summary"]["quote_policy_exceeded_count"] == 1
    assert judged["policy_id"] != result["policy_id"] and judged["reconciliation_id"] != result["reconciliation_id"]


def test_bad_id_duplicate_numeric_and_clock_inputs_fail_not_silently_disappear(forward_case):
    path, root = forward_case
    original = batch(root, complete=True)
    for field in ("expected_experiment_id", "expected_candidate_id"):
        with pytest.raises(ValueError, match="identity differs"):
            forward.analyze_intraday_forward_reconciliation(path, {**original, field: "0" * 64})
    with pytest.raises(ValueError, match="outside the saved"):
        forward.analyze_intraday_forward_reconciliation(path, {**original, "candidate_index": 999})
    duplicate = deepcopy(original)
    duplicate["records"].append(deepcopy(duplicate["records"][0]))
    with pytest.raises(ValueError, match="duplicate forward action"):
        forward.normalize_forward_observations(duplicate)
    for invalid in (True, float("inf"), -1):
        broken = deepcopy(original)
        broken["policy"]["max_quote_age_ms"] = invalid
        with pytest.raises(ValueError):
            forward.normalize_forward_observations(broken)
    broken = deepcopy(original)
    broken["records"][0]["quote"]["bid"] = 0
    with pytest.raises(ValueError, match="positive"):
        forward.normalize_forward_observations(broken)
    broken = deepcopy(original)
    broken["records"][0]["quote"]["received_at"] = broken["records"][0]["action_ready_at"]
    with pytest.raises(ValueError, match="same-clock ordering"):
        forward.normalize_forward_observations(broken)


def test_rehashed_transaction_reference_is_not_a_price_authority(forward_case, tmp_path):
    from market_vault.research.strategy_experiment import load_strategy_experiment
    from test_intraday_experiment import signed
    _, root = forward_case
    for field in ("raw_open", "fill_price", "exit_reason", "ledger_observation_key"):
        changed = deepcopy(root)
        candidate = changed["report"]["groups"][0]["results"][1]
        execution = candidate["execution"]
        if field == "exit_reason":
            execution["trades"][0]["exit_reason"] = "TARGET_FLAT"
        elif field == "ledger_observation_key":
            tx = execution["transactions"][0]
            point = next(row for row in execution["ledger"] if row["phase"] == "OPEN"
                         and (row["trading_day"], row["slot"]) == (tx["trading_day"], tx["slot"]))
            point["observation_key"] = "0" * 64
        else:
            execution["transactions"][0][field] += 1
        path = tmp_path / (field + ".json")
        path.write_bytes(signed(changed))
        admitted = load_strategy_experiment(path).as_dict()  # Existing grammar/hash Open is not replay.
        observations = batch(root)
        observations["expected_experiment_id"] = admitted["experiment_id"]
        observations["expected_candidate_id"] = admitted["report"]["groups"][0]["results"][1]["candidate_id"]
        before = path.read_bytes()
        with pytest.raises(ValueError, match="OPEN grid or trade endpoint"):
            forward.analyze_intraday_forward_reconciliation(path, observations)
        assert path.read_bytes() == before


def test_microsecond_quote_age_equality_through_the_public_entry(forward_case):
    path, root = forward_case
    observations = batch(root, complete=True)
    observations["records"] = observations["records"][:1]
    row = observations["records"][0]
    quote_time = row["quote"]["observed_at"]["timestamp"]
    row["quote"]["received_at"] = stamp(quote_time, .009)
    observations["policy"]["max_quote_age_ms"] = .009
    equal = forward.analyze_intraday_forward_reconciliation(path, observations)
    assert equal["rows"][0]["metrics"]["quote_age_ms"]["value"] == .009
    assert equal["rows"][0]["quote_status"] == "MEASURED"
    assert equal["summary"]["measured_quote_count"] == 1
    observations["policy"]["max_quote_age_ms"] = .008
    stale = forward.analyze_intraday_forward_reconciliation(path, observations)
    assert stale["rows"][0]["quote_status"] == "STALE_QUOTE"
    assert stale["summary"]["measured_quote_count"] == 0
    assert stale["summary"]["reference_action_count"] == equal["summary"]["reference_action_count"]


def test_real_module_cli_nonpass_publication_is_exclusive(forward_case, tmp_path, capsys):
    path, root = forward_case
    observation_file = write_market_data_json(tmp_path / "observations.json", batch(root))
    before = observation_file.read_bytes()
    output = tmp_path / "reconciliation.json"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    command = ["--experiment", str(path), "--observations", str(observation_file), "--output", str(output)]
    process = subprocess.run([sys.executable, "-m", "market_vault.research.intraday_forward_reconciliation", *command],
                             capture_output=True, text=True, timeout=90, env=env, cwd=tmp_path)
    assert process.returncode == 2, process.stderr
    envelope = json.loads(process.stdout)
    assert envelope["status"] == "NOT_MEASURED" and json.loads(output.read_bytes()) == envelope["report"]
    encoded = output.read_bytes()
    assert forward.main(command) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    assert output.read_bytes() == encoded and observation_file.read_bytes() == before
    full_file = write_market_data_json(tmp_path / "complete.json", batch(root, complete=True))
    assert forward.main(["--experiment", str(path), "--observations", str(full_file),
                         "--output", str(tmp_path / "complete-result.json")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RECONCILED"
