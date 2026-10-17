from __future__ import annotations

import json

import pytest

from market_vault.moomoo_simulation_evidence import build_evidence, export_evidence
from market_vault.moomoo_simulation_orders import BuyIntent, PaperJournal
from market_vault.moomoo_simulation_observations import summarize, wall_elapsed
from test_strategy_moomoo_qualifier import broker, run, submit_args

ID = "0123456789abcdef0123456789abcdef"
T0 = "2026-10-16T15:00:00+00:00"
T1 = "2026-10-16T15:00:02+00:00"
T2 = "2026-10-16T15:01:00+00:00"


def fresh(journal, **changes):
    row = dict(order_id="local-only-id", order_status="CANCELLED_PART", dealt_qty="0.4",
               dealt_avg_price="499", updated_time="2026-10-16 11:01:00", recorded_at_utc=T2)
    journal.append("ORDER_OBSERVATION", ID, **{**row, **changes})


def start(path):
    journal = PaperJournal.create(path, 123456789)
    journal.reserve(BuyIntent(ID, "US.SPY", "500.00"))
    journal.append("SUBMISSION_CALL", ID, recorded_at_utc=T0)
    return journal


def test_export_counts_all_intentions_and_uses_cumulative_fill_once(tmp_path):
    path, output = tmp_path / "p.sqlite", tmp_path / "out.json"
    with start(path) as journal:
        journal.append("SUBMISSION_RECEIPT", ID, order_id="local-only-id", recorded_at_utc=T1)
        fresh(journal)
        fresh(journal)
    before = path.read_bytes()
    report = export_evidence(path, output)
    summary = report["observation_summary"]
    assert summary["intention_count"] == 1 and summary["outcome_counts"]["OBSERVED_TERMINAL"] == 1
    item = summary["intentions"][0]
    assert item["recorded_query_count"] == 2
    assert item["last_observation"]["cumulative_qty"] == "0.4"
    assert item["last_observation"]["fill_minus_owner_limit_usd"] == "-1.00"
    assert item["call_to_receipt_wall"] == {"seconds": 2.0, "reason": None}
    assert item["call_to_first_query_wall"]["seconds"] == 60
    assert summary["market_slippage_bps"] is summary["broker_latency_ms"] is None
    assert summary["cost_calibration"] == summary["strategy_forward_validation"] == "NOT_PERFORMED"
    assert not summary["new_orders_authorized"] and path.read_bytes() == before
    text = json.dumps(report)
    assert ID not in text and "local-only-id" not in text and "123456789" not in text


def test_ack_is_not_fresh_fill_and_unknown_can_be_resolved_by_later_query(tmp_path):
    path = tmp_path / "p.sqlite"
    with start(path) as journal:
        journal.append("SUBMISSION_ACK", ID, order_id="local-only-id", order_status="FILLED_ALL",
                       dealt_qty=1, dealt_avg_price=499)
        journal.append("SUBMISSION_UNKNOWN", ID, error_type="TimeoutError")
        report = build_evidence(path)["observation_summary"]
        assert report["outcome_counts"]["UNRESOLVED"] == 1 and report["observed_outcome_fraction"] == 0
        assert report["intentions"][0]["last_observation"] is None
        fresh(journal, order_status="FILLED_ALL", dealt_qty=1)
        report = build_evidence(path)["observation_summary"]
        assert report["outcome_counts"]["OBSERVED_TERMINAL"] == 1
        assert report["intentions"][0]["had_submission_unknown"]


@pytest.mark.parametrize("kind", ["ORDER_QUERY_FAILED", "CANCEL_ACK", "UNRECOGNIZED_EVENT"])
def test_later_failure_or_cancel_ack_does_not_reuse_old_outcome_as_current(tmp_path, kind):
    path = tmp_path / "p.sqlite"
    with start(path) as journal:
        fresh(journal, order_status="FILLED_PART")
        journal.append(kind, ID, order_id="local-only-id")
    item = build_evidence(path)["observation_summary"]["intentions"][0]
    assert item["outcome_as_of_record"] == "UNRESOLVED"
    assert item["last_observation"]["cumulative_qty"] == "0.4"  # retained as historical only


@pytest.mark.parametrize("change", [{"dealt_qty": "0.3"}, {"order_id": "another-id"},
                                     {"dealt_avg_price": "500"}, {"updated_time": ""}])
def test_contradictory_or_missing_observation_cannot_produce_fill_metric(tmp_path, change):
    path = tmp_path / "p.sqlite"
    with start(path) as journal:
        fresh(journal)
        fresh(journal, **change)
    item = build_evidence(path)["observation_summary"]["intentions"][0]
    assert item["outcome_as_of_record"] == "UNRESOLVED"
    assert item["last_observation"] is None
    assert item["reason"] == "INCOMPLETE_OR_CONFLICTING_ORDER_EVIDENCE"


def test_no_intention_and_missing_or_bad_clock_are_not_zero_measurements(tmp_path):
    path = tmp_path / "p.sqlite"
    with PaperJournal.create(path, 200):
        pass
    summary = build_evidence(path)["observation_summary"]
    assert summary["intention_count"] == 0 and summary["observed_outcome_fraction"] is None
    assert sum(summary["outcome_counts"].values()) == 0
    left = {"seq": 1, "recorded_at_utc": T1}
    for right in (None, {"seq": 2, "recorded_at_utc": T0},
                  {"seq": 2, "recorded_at_utc": "2026-10-16T15:00:05"}):
        assert wall_elapsed(left, right)["seconds"] is None


def test_unmatched_action_is_retained_and_does_not_claim_a_completed_check(tmp_path):
    path = tmp_path / "p.sqlite"
    with start(path) as journal:
        journal.append("RECONCILIATION", None, result="OBSERVATIONS_MATCH")
        journal.append("QUALIFICATION_START", None, action="check", runtime={}, started_at_utc=T0)
        fresh(journal)
    report = build_evidence(path)
    summary = report["observation_summary"]
    assert summary["incomplete_action_count"] == 1
    assert summary["last_reconciliation"]["subsequent_activity_recorded"]
    assert summary["actions"][0]["elapsed_ms"] is None
    assert summary["outcome_counts"]["UNRESOLVED"] == 1
    assert summarize(report) == summary  # summary does not consume itself


def test_s5_actual_entry_automatically_includes_summary_and_historical_reconciliation(broker, tmp_path):
    code, prepared = run(tmp_path, "prepare")
    assert code == 0 and prepared["evidence"]["observation_summary"]["intention_count"] == 0
    code, submitted = run(tmp_path, "submit", extra=submit_args())
    assert code == 0
    summary = submitted["evidence"]["observation_summary"]
    assert summary["outcome_counts"]["UNRESOLVED"] == 1  # ACK only, no fresh query
    assert summary["last_reconciliation"]["subsequent_activity_recorded"]
    broker.rows[0].update(order_status="FILLED_ALL", dealt_qty=1, dealt_avg_price=499,
                          updated_time="2026-10-16 11:01:00")
    broker.positions, broker.cash = [dict(code="US.SPY", qty=1, position_side="LONG")], "9501.00"
    code, checked = run(tmp_path, "check")
    assert code == 0
    summary = checked["evidence"]["observation_summary"]
    assert summary["outcome_counts"]["OBSERVED_TERMINAL"] == 1
    assert summary["last_reconciliation"]["result"] == "OBSERVATIONS_MATCH"
    assert not summary["last_reconciliation"]["subsequent_activity_recorded"]
    assert len(summary["actions"]) == 3 and summary["incomplete_action_count"] == 0
    assert all(float(a["elapsed_ms"]) >= 0 for a in summary["actions"])
    assert broker.calls.count("place") == 1  # report building adds no broker action


def test_explicit_not_sent_is_distinct_from_unknown_reservation(tmp_path):
    path = tmp_path / "p.sqlite"
    with PaperJournal.create(path, 200) as journal:
        journal.reserve(BuyIntent(ID, "US.SPY", "500.00"))
        assert build_evidence(path)["observation_summary"]["outcome_counts"]["UNRESOLVED"] == 1
        journal.append("SUBMISSION_NOT_SENT", ID)
        assert build_evidence(path)["observation_summary"]["outcome_counts"]["NOT_SENT"] == 1


def test_summary_provenance_changes_when_only_summary_source_changes(tmp_path, monkeypatch):
    from pathlib import Path
    from market_vault import moomoo_simulation_observations as observed_code

    path = tmp_path / "p.sqlite"
    with PaperJournal.create(path, 200):
        pass
    first = build_evidence(path)
    source = Path(observed_code.__file__)
    copy = tmp_path / "summary_copy.py"
    copy.write_bytes(source.read_bytes() + b"\n# isolated source-version change\n")
    monkeypatch.setattr(observed_code, "__file__", str(copy))
    second = build_evidence(path)
    assert first["exporter_sha256"] == second["exporter_sha256"]
    first_sources = first.get("observation_summary_source_sha256_lf", {})
    second_sources = second.get("observation_summary_source_sha256_lf", {})
    assert first_sources.get("moomoo_simulation_observations.py") != second_sources.get("moomoo_simulation_observations.py")
    assert set(first_sources) == {"moomoo_simulation_observations.py", "moomoo_simulation_orders.py",
                                  "moomoo_simulation_recovery.py"}


def test_normal_offline_stop_marks_activity_after_last_reconciliation(broker, tmp_path):
    assert run(tmp_path, "prepare")[0] == 0
    before = len(broker.contexts)
    code, stopped = run(tmp_path, "stop")
    assert code == 0 and len(broker.contexts) == before
    assert stopped["evidence"]["stopped"]
    summary = stopped["evidence"]["observation_summary"]
    assert summary["last_reconciliation"]["subsequent_activity_recorded"]
    assert summary["last_reconciliation"]["basis"] == "HISTORICAL_NONATOMIC_COMPARISON_ONLY"
