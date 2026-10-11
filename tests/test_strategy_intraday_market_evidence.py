"""Exact Q5 price binding, external comparison coverage and the actual CLI.

Every market value is synthetic. Source declarations below exercise report
meaning only; no test establishes independent real-market accuracy.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path

import pytest

import cross_day_helpers as cd
from market_vault import cli
from market_vault.quality import market_data_comparison as q44
from market_vault.research import intraday_data as q5
from market_vault.research import intraday_market_evidence as evidence


DAYS = ("2025-03-03", "2025-03-04")
BASIS = {"asset_class": "EQUITY", "currency": "USD", "aggregation": "TRADE_OHLCV", "volume_basis": "SHARES"}


def _source(name="local", kind="SYNTHETIC"):
    return {"provider": name, "version": "observation-v1", "captured_at": "2026-01-03T00:00:00Z",
            "data_kind": kind, "upstream_id": name, "upstream_evidence": f"declared:{name}"}


def _data(parent, *, days=DAYS, missing=(), source="a", inconsistent_ohlc=False):
    parent.mkdir(parents=True, exist_ok=True)
    builds = []
    for day in days:
        bars = [cd.bar(day, slot=slot, open=100 + slot / 100, close=100.005 + slot / 100,
                       high=99.0 if inconsistent_ohlc and slot == 0 else 150.0, source=source)
                for slot in range(78) if (day, slot) not in missing]
        build = cd.build(parent / day, bars, dates=[date.fromisoformat(day)])
        builds.append(str(build.build_path))
    plan = {"plan_schema_version": q5.INTRADAY_PLAN_VERSION, "canonical_build_dirs": builds,
            "schedule": q5.json_values(asdict(cd.schedule(tuple((day, "N") for day in days)))),
            "symbol": "US.AAPL", "interval": "5m", "preset": "LIGHT_TECHNICAL",
            "stride_bars": 1, "target_horizon_bars": 3, "dataset_as_of": cd.AS_OF.isoformat()}
    built = q5.build_intraday_dataset(plan)
    path = q5.write_intraday_dataset(built, path=parent / "q5.json")
    return q5.IntradayDataset(built.content, path)


@pytest.fixture(scope="module")
def q5_case(tmp_path_factory):
    return _data(tmp_path_factory.mktemp("market-evidence-q5"))


@pytest.fixture(scope="module")
def gapped_case(tmp_path_factory):
    return _data(tmp_path_factory.mktemp("market-evidence-gaps"), days=(DAYS[0],),
                 missing=((DAYS[0], 1), (DAYS[0], 2)))


def _scope(day=DAYS[0], first=0, count=78):
    opening = cd.local(day)
    return {"symbol": "US.AAPL", "interval": "5m", "adjustment": "NONE", "session": "RTH", **BASIS,
            "window_start": q44.utc_text(opening + timedelta(minutes=5 * first)),
            "window_end": q44.utc_text(opening + timedelta(minutes=5 * (first + count)))}


def _reference(data, *, scope=None, source=None):
    scope = _scope() if scope is None else scope
    start, end = q44.parse_utc(scope["window_start"]), q44.parse_utc(scope["window_end"])
    bars = [{"start": q44.utc_text(q44.parse_utc(row["event_time"])),
             "end": q44.utc_text(q44.parse_utc(row["available_at"])),
             **{key: row[key] for key in q44.VALUE_FIELDS}}
            for row in data.as_dict()["report"]["prices"] if start <= q44.parse_utc(row["event_time"]) < end]
    return {"schema_version": q44.SNAPSHOT_SCHEMA_VERSION, "scope": scope,
            "source": _source("reference") if source is None else source, "bars": bars}


def _write(path, payload):
    path.write_bytes(q44.json_bytes(payload))
    return path


def _plan(*references, source=None):
    return {"schema_version": evidence.INTRADAY_MARKET_EVIDENCE_PLAN_VERSION,
            "source": _source() if source is None else source, "basis": deepcopy(BASIS),
            "references": list(references)}


def _item(path, scope=None):
    return {"scope": _scope() if scope is None else scope, "snapshot": None if path is None else str(path)}


def _partition(report):
    assert report["summary"]["expected_slots"] == len(report["rows"]) == sum(report["summary"]["counts"].values())
    assert sum(row["summary"]["expected_slots"] for row in report["sessions"]) == len(report["rows"])
    for status in evidence.SLOT_STATUSES:
        assert sum(row["summary"]["counts"][status] for row in report["sessions"]) == report["summary"]["counts"][status]
    assert report["market_accuracy_certified"] is False
    assert report["market_evidence_id"] == q5.digest({key: value for key, value in report.items() if key != "market_evidence_id"})


def test_complete_comparison_binds_actual_q5_rows_all_builds_and_capture_bytes(q5_case, tmp_path, monkeypatch):
    references = [_write(tmp_path / f"{day}.json", _reference(q5_case, scope=_scope(day))) for day in DAYS]
    plan = _plan(*(_item(path, _scope(day)) for path, day in zip(references, DAYS, strict=True)))
    before = {path: path.read_bytes() for path in (q5_case.path, *references)}
    original_plan = deepcopy(plan)
    verify, calls = q5.verify_intraday_dataset, []
    def checked(*args, **kwargs):
        calls.append(1)
        return verify(*args, **kwargs)
    monkeypatch.setattr(q5, "verify_intraday_dataset", checked)
    report = evidence.analyze_intraday_market_evidence(q5_case.path, plan)
    assert calls == [1]
    assert report["status"] == "AVAILABLE" and report["summary"]["counts"]["MATCH"] == 156
    assert report["summary"]["numerical_comparison_coverage"] == {"numerator": 156, "denominator": 156, "ratio": 1}
    root = q5_case.as_dict()
    assert report["data_id"] == root["data_id"] and len(report["data"]["source_build_ids"]) == 2
    assert report["data"]["source_build_ids"] == root["source_build_ids"]
    assert report["data"]["source_evidence"] == "STRICT_Q5_SOURCE_RECONSTRUCTION"
    for saved, actual in zip(report["rows"], root["report"]["prices"], strict=True):
        assert saved["row_version_id"] == actual["row_version_id"]
        assert saved["local_values"] == {field: actual[field] for field in q44.VALUE_FIELDS}
        assert all(value["left"] == actual[field] == value["right"] for field, value in saved["differences"].items())
    for ref, path in zip(report["references"], references, strict=True):
        assert ref["comparison"]["inputs"]["right"]["file_sha256"] == sha256(before[path]).hexdigest()
        assert ref["comparison"]["inputs"]["left"]["origin"]["data_id"] == q5_case.data_id
        assert ref["independence"]["status"] == "SYNTHETIC"
    assert plan == original_plan and all(path.read_bytes() == content for path, content in before.items())
    _partition(report)


def test_no_reference_and_partial_window_keep_every_q5_slot(q5_case, tmp_path):
    absent = evidence.analyze_intraday_market_evidence(q5_case, _plan())
    assert absent["status"] == "UNAVAILABLE" and absent["unavailable_reason"] == "NO_REFERENCE_SNAPSHOTS"
    assert absent["summary"]["counts"]["UNASSESSED"] == 156 and absent["references"] == []
    scope = _scope(first=2, count=6)
    path = _write(tmp_path / "partial.json", _reference(q5_case, scope=scope))
    partial = evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path, scope)))
    assert partial["status"] == "PARTIAL"
    assert partial["summary"]["counts"]["MATCH"] == 6
    assert partial["summary"]["counts"]["UNASSESSED"] == 150
    assert partial["summary"]["reference_declared_slots"] == 6
    assert [row["slot"] for row in partial["rows"] if row["status"] == "MATCH"] == list(range(2, 8))
    assert partial["sessions"][1]["summary"]["counts"]["UNASSESSED"] == 78
    _partition(absent)
    _partition(partial)


def test_differences_gaps_invalid_rows_and_duplicates_remain_distinct(gapped_case, tmp_path):
    ref = _reference(gapped_case)
    # Q5 lacks slots 1 and 2. External slot 1 exists, slot 2 does not, and slot 3
    # is absent only externally. Separate later slots contain bad/duplicate rows.
    first = deepcopy(ref["bars"][0])
    first.update(start=_scope(first=1, count=1)["window_start"], end=_scope(first=1, count=1)["window_end"])
    ref["bars"].append(first)
    by_start = {row["start"]: row for row in ref["bars"]}
    ref["bars"].remove(by_start[_scope(first=3, count=1)["window_start"]])
    ref["bars"].append(deepcopy(by_start[_scope(first=4, count=1)["window_start"]]))
    by_start[_scope(first=5, count=1)["window_start"]]["volume"] = -1
    by_start[_scope(first=6, count=1)["window_start"]]["close"] += .5
    by_start[_scope(first=7, count=1)["window_start"]]["volume"] += 100
    path = _write(tmp_path / "mixed.json", ref)
    report = evidence.analyze_intraday_market_evidence(gapped_case, _plan(_item(path)))
    rows = report["rows"]
    assert [row["status"] for row in rows[:8]] == [
        "MATCH", "RIGHT_ONLY", "BOTH_MISSING", "LEFT_ONLY", "BLOCKED", "BLOCKED", "DIFFERENT", "DIFFERENT"]
    assert rows[1]["row_version_id"] is None and rows[1]["local_values"] is None
    assert rows[4]["reference_state"] == "DUPLICATE" and len(rows[4]["reference_row_indices"]) == 2
    assert rows[5]["reference_state"] == "INVALID"
    assert rows[6]["differences"]["close"]["signed"] == -.5
    assert rows[7]["differences"]["volume"]["signed"] == -100
    assert report["summary"]["local_price_rows"] == 76
    assert report["summary"]["local_missing_slots"] == 2
    assert report["references"][0]["comparison"]["status"] == "INVALID_INPUT"
    assert report["status"] == "PARTIAL"
    _partition(report)


@pytest.mark.parametrize("problem,expected", [("null", "NOT_RUN"), ("missing", "NOT_RUN"), ("json", "INVALID_INPUT")])
def test_absent_or_invalid_file_keeps_declared_window_and_original_evidence(q5_case, tmp_path, problem, expected):
    path = None if problem == "null" else tmp_path / "reference.json"
    if problem == "json":
        path.write_bytes(b'{"source": {}, "source": {}}')
    scope = _scope(first=1, count=3)
    report = evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path, scope)))
    assert report["status"] == "UNAVAILABLE"
    assert report["summary"]["counts"][expected] == 3
    assert report["summary"]["counts"]["UNASSESSED"] == 153
    assert report["references"][0]["comparison"]["status"] == expected
    if problem == "json":
        assert report["references"][0]["comparison"]["inputs"]["right"]["file_sha256"] == sha256(path.read_bytes()).hexdigest()
    _partition(report)


@pytest.mark.parametrize("field,value", [("symbol", "US.SPY"), ("interval", "15m"), ("currency", "JPY"),
                                        ("asset_class", "ETF"), ("aggregation", "OTHER"), ("volume_basis", "LOTS")])
def test_wrong_scope_refuses_before_reference_read(q5_case, tmp_path, monkeypatch, field, value):
    scope = {**_scope(), field: value}
    monkeypatch.setattr(q44, "_file_input", lambda *a, **k: pytest.fail("wrong scope must precede reference I/O"))
    with pytest.raises(ValueError, match="Q5 symbol/interval/economic basis"):
        evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(tmp_path / "unused", scope)))


def test_duplicate_day_outside_day_and_actual_file_scope_do_not_choose_an_implicit_reference(q5_case, tmp_path):
    scope, path = _scope(), tmp_path / "reference.json"
    with pytest.raises(ValueError, match="multiple reference snapshots"):
        evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path), _item(path, _scope(first=4, count=2))))
    with pytest.raises(ValueError, match="outside the Q5 trading sessions"):
        evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path, _scope("2025-03-05"))))
    wrong = _reference(q5_case)
    wrong["scope"]["symbol"] = "US.SPY"
    _write(path, wrong)
    with pytest.raises(ValueError, match="snapshot scope differs.*symbol"):
        evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path, scope)))


@pytest.mark.parametrize("mode,expected", [("synthetic", "SYNTHETIC"), ("unknown", "UNKNOWN"),
                                        ("shared", "SHARED_UPSTREAM"), ("distinct", "CLAIMED_DISTINCT")])
def test_source_declarations_never_certify_market_accuracy(q5_case, tmp_path, mode, expected):
    left, right = _source("local", "OBSERVED"), _source("external", "OBSERVED")
    if mode == "synthetic":
        left["data_kind"] = "SYNTHETIC"
    elif mode == "unknown":
        right["upstream_evidence"] = None
    elif mode == "shared":
        right["upstream_id"] = left["upstream_id"]
    path = _write(tmp_path / "reference.json", _reference(q5_case, source=right))
    report = evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path), source=left))
    assert report["references"][0]["independence"] == {"status": expected, "evidence_scope": "SOURCE_DECLARATIONS_ONLY"}
    assert report["summary"]["independence_counts"][expected] >= 78
    assert report["market_accuracy_certified"] is False
    assert report["references"][0]["comparison"]["market_accuracy_certified"] is False


def test_q5_reconstruction_not_external_origin_establishes_local_row_versions(q5_case, tmp_path):
    reference = _reference(q5_case)
    reference["origin"] = {"data_id": "different-dataset"}
    for row in reference["bars"]:
        row["origin"] = {"canonical_row_version_id": "untrusted-declaration"}
    path = _write(tmp_path / "reference.json", reference)
    first = evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path)))
    assert first["data_id"] == q5_case.data_id
    assert all(row["row_version_id"] != "untrusted-declaration" for row in first["rows"])
    reference["bars"][0]["open"] += 1
    _write(path, reference)
    changed = evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path)))
    assert changed["market_evidence_id"] != first["market_evidence_id"]
    assert changed["references"][0]["comparison"]["inputs"]["right"]["file_sha256"] != first["references"][0]["comparison"]["inputs"]["right"]["file_sha256"]
    assert changed["rows"][0]["differences"]["open"]["within_tolerance"] is False
    # Re-signing caller-owned Q5 bytes is insufficient: the real Canonical
    # reconstruction must still reproduce the actual prices and Features.
    forged = q5_case.as_dict()
    forged["report"]["prices"][0]["open"] += 1
    forged["data_id"] = q5._data_identity(forged)
    with pytest.raises(ValueError, match="source reconstruction"):
        evidence.analyze_intraday_market_evidence(q5.IntradayDataset(q5.canonical_json(forged)), _plan())


def test_explicit_tolerances_change_only_comparison_and_keep_original_values(q5_case, tmp_path):
    reference = _reference(q5_case)
    reference["bars"][0]["close"] += .1
    path = _write(tmp_path / "reference.json", reference)
    exact = evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(path)))
    plan = _plan(_item(path))
    plan["tolerances"] = {"price_absolute": .2, "price_relative": 0, "volume_absolute": 0}
    tolerant = evidence.analyze_intraday_market_evidence(q5_case, plan)
    assert exact["rows"][0]["status"] == "DIFFERENT" and tolerant["rows"][0]["status"] == "MATCH"
    assert exact["rows"][0]["local_values"] == tolerant["rows"][0]["local_values"]
    assert exact["rows"][0]["differences"]["close"]["right"] == tolerant["rows"][0]["differences"]["close"]["right"]
    assert exact["data_id"] == tolerant["data_id"] == q5_case.data_id


def test_full_numeric_coverage_does_not_hide_differences_or_unmapped_invalid_rows(q5_case, tmp_path):
    first = _reference(q5_case)
    first["bars"][0]["close"] += 1
    first["bars"].append({"start": "ambiguous-time", "close": -1})
    left = _write(tmp_path / "first.json", first)
    right = _write(tmp_path / "second.json", _reference(q5_case, scope=_scope(DAYS[1])))
    report = evidence.analyze_intraday_market_evidence(q5_case, _plan(_item(left), _item(right, _scope(DAYS[1]))))
    assert report["status"] == "AVAILABLE"  # Availability is not a quality verdict.
    assert report["summary"]["counts"]["DIFFERENT"] == 1
    assert report["summary"]["input_diagnostics_present"] is True
    assert report["summary"]["reference_status_counts"]["INVALID_INPUT"] == 1
    assert report["references"][0]["comparison"]["inputs"]["right"]["summary"]["invalid_rows"] == 1
    _partition(report)


def test_actual_q5_presence_is_distinct_from_q44_ohlc_validity_even_without_reference(tmp_path):
    data = _data(tmp_path / "local", days=(DAYS[0],), inconsistent_ohlc=True)
    reference = _reference(data)
    reference["bars"][0]["high"] = 150.0
    path = _write(tmp_path / "reference.json", reference)
    report = evidence.analyze_intraday_market_evidence(data.path, _plan(_item(path)))
    row = report["rows"][0]
    assert row["local_state"] == "PRESENT" and row["local_values"]["high"] == 99.0
    assert row["comparison_local_state"] == "INVALID" and row["reference_state"] == "VALID_UNIQUE"
    assert row["status"] == "BLOCKED" and row["differences"] == {}
    assert report["summary"]["local_price_rows"] == 78
    assert report["summary"]["local_missing_slots"] == 0
    assert report["summary"]["numerically_compared_slots"] == 77
    assert report["summary"]["input_diagnostics_present"] is True
    left = report["references"][0]["comparison"]["inputs"]["left"]
    assert left["status"] == "INVALID_INPUT" and left["summary"]["invalid_rows"] == 1
    absent = evidence.analyze_intraday_market_evidence(data.path, _plan(_item(None)))
    assert absent["summary"]["counts"]["NOT_RUN"] == 78
    assert absent["summary"]["input_diagnostics_present"] is True
    assert absent["rows"][0]["local_state"] == "PRESENT"
    assert absent["rows"][0]["comparison_local_state"] == "NOT_RUN"
    assert absent["references"][0]["comparison"]["inputs"]["left"]["status"] == "INVALID_INPUT"
    _partition(report)
    _partition(absent)


def test_actual_cli_relative_references_exclusive_output_and_recovery(q5_case, tmp_path, capsys, monkeypatch):
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    reference = _write(manifest_dir / "reference.json", _reference(q5_case))
    manifest = _write(manifest_dir / "plan.json", _plan(_item(Path("reference.json"))))
    output, other = tmp_path / "report.json", tmp_path / "again.json"
    before = {path: path.read_bytes() for path in (q5_case.path, reference, manifest)}
    monkeypatch.chdir(tmp_path)
    command = ["--settings", str(tmp_path / "no-settings.yaml"), "research-intraday-market-evidence",
               "--data", str(q5_case.path), "--manifest", str(manifest), "--output"]
    assert cli.main([*command, str(output)]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert not captured.err and result["status"] == "SUCCESS" and result["report"]["status"] == "PARTIAL"
    assert result["report"]["references"][0]["snapshot_locator"] == str(reference)
    assert json.loads(output.read_bytes()) == result["report"]
    original_output = output.read_bytes()
    assert cli.main([*command, str(output)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    assert output.read_bytes() == original_output
    assert cli.main([*command, str(other)]) == 0
    assert json.loads(capsys.readouterr().out)["report"] == result["report"]
    assert other.read_bytes() == original_output
    invalid = deepcopy(_plan())
    invalid["basis"]["unexpected"] = True
    bad_manifest = _write(manifest_dir / "bad-plan.json", invalid)
    bad_output = tmp_path / "bad-report.json"
    assert cli.main(["research-intraday-market-evidence", "--data", str(q5_case.path),
                     "--manifest", str(bad_manifest), "--output", str(bad_output)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED" and not bad_output.exists()
    assert all(path.read_bytes() == content for path, content in before.items())
