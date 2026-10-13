"""Q74 policy judgment through verified Canonical data and the real CLI.

All prices are synthetic. OBSERVED/distinct declarations below test declaration
handling only; no test demonstrates independently observed market agreement.
"""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from market_vault import cli
from market_vault.quality import market_data_comparison as q44
from market_vault.research import intraday_data as q5
from market_vault.research import intraday_data_acceptance as acceptance
from test_strategy_intraday_market_evidence import (
    DAYS, _data, _item, _plan, _reference, _scope, _source, _write,
)


@pytest.fixture(scope="module")
def acceptance_data(tmp_path_factory):
    return _data(tmp_path_factory.mktemp("q74-data"))


def policy(**changes):
    return {"schema_version": acceptance.INTRADAY_DATA_ACCEPTANCE_POLICY_VERSION, **changes}


def references(data, parent, *, kind="OBSERVED"):
    paths = [_write(parent / f"ref-{day}.json", _reference(data, scope=_scope(day),
                    source=_source("reference", kind))) for day in DAYS]
    manifest = _plan(*(_item(path, _scope(day)) for day, path in zip(DAYS, paths, strict=True)),
                     source=_source("local", "OBSERVED"))
    return manifest, paths


def test_actual_source_verified_once_and_all_support_retained(acceptance_data, tmp_path, monkeypatch):
    manifest, paths = references(acceptance_data, tmp_path)
    before = {p: p.read_bytes() for p in (acceptance_data.path, *paths)}
    manifest_before, policy_input = deepcopy(manifest), policy()
    checked, calls = q5.verify_intraday_dataset, []
    def verify(*args, **kwargs):
        calls.append(1)
        return checked(*args, **kwargs)
    monkeypatch.setattr(q5, "verify_intraday_dataset", verify)
    result = acceptance.analyze_intraday_data_acceptance(acceptance_data.path, manifest, policy_input)
    assert calls == [1]
    assert result["status"] == "POLICY_SATISFIED"
    assert result["rejections"] == result["evidence_gaps"] == []
    assert result["policy"]["tolerances"] == q44.normalize_tolerances()
    assert result["policy"]["require_declared_distinct_observed"] is True
    assert result["summary"]["counts"]["MATCH"] == result["summary"]["expected_slots"] == 156
    support = result["dependencies"]
    assert support["summary"]["feature_support"]["bar_links"] == 740
    assert support["summary"]["target_endpoint_count"] == 284
    assert result["market_dependencies_id"] == support["market_dependencies_id"]
    assert result["market_evidence_id"] == support["market_evidence"]["market_evidence_id"]
    assert result["source_assurance"]["independence_verified"] is False
    assert result["source_assurance"]["independence_counts"]["CLAIMED_DISTINCT"] == 156
    assert result["market_accuracy_certified"] is False
    for recorded, actual in zip(support["market_evidence"]["references"], paths, strict=True):
        assert recorded["comparison"]["inputs"]["right"]["file_sha256"] == sha256(before[actual]).hexdigest()
    assert all(p.read_bytes() == b for p, b in before.items())
    assert manifest == manifest_before and policy_input == policy()
    assert result["acceptance_id"] == q5.digest({k: v for k, v in result.items() if k != "acceptance_id"})
    assert acceptance.analyze_intraday_data_acceptance(acceptance_data.path, manifest, policy_input) == result
    assert calls == [1, 1]  # A new action verifies again, rather than trusting a saved verdict.


def test_missing_and_partial_evidence_keep_the_full_denominator(acceptance_data, tmp_path):
    manifest = _plan(source=_source("local", "OBSERVED"))
    absent = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    assert absent["status"] == "NEEDS_EVIDENCE" and absent["rejections"] == []
    assert absent["summary"]["counts"]["UNASSESSED"] == 156
    assert absent["evidence_gaps"] == [{"reason": "INCOMPLETE_NUMERICAL_COVERAGE", "count": 156}]
    scope = _scope(first=2, count=6)
    path = _write(tmp_path / "partial.json", _reference(acceptance_data, scope=scope,
                                                       source=_source("reference", "OBSERVED")))
    manifest["references"] = [_item(path, scope)]
    partial = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    assert partial["status"] == "NEEDS_EVIDENCE"
    assert partial["summary"]["counts"]["MATCH"] == 6
    assert partial["summary"]["expected_slots"] == sum(partial["summary"]["counts"].values()) == 156
    assert partial["evidence_gaps"] == [{"reason": "INCOMPLETE_NUMERICAL_COVERAGE", "count": 150}]


@pytest.mark.parametrize("case,reason,compared", [
    ("different", "NUMERICAL_DISAGREEMENT", 156),
    ("unkeyed", "INVALID_REFERENCE_INPUT", 156),
    ("duplicate", "INVALID_REFERENCE_INPUT", 155),
])
def test_full_or_almost_full_comparison_is_not_policy_success(acceptance_data, tmp_path, case, reason, compared):
    manifest, paths = references(acceptance_data, tmp_path)
    payload = q44.read_json_file(paths[0])
    if case == "different":
        payload["bars"][0]["close"] += 1
    elif case == "unkeyed":
        payload["bars"].append({"start": "not-a-grid-key"})
    else:
        payload["bars"].append(deepcopy(payload["bars"][0]))
    _write(paths[0], payload)
    result = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    assert result["status"] == "REJECTED"
    assert [item["reason"] for item in result["rejections"]] == [reason]
    assert result["summary"]["numerically_compared_slots"] == compared
    if case == "unkeyed":
        assert result["dependencies"]["market_evidence"]["status"] == "AVAILABLE"
        assert result["summary"]["counts"]["MATCH"] == 156
        assert result["summary"]["input_diagnostics_present"] is True
    if case == "duplicate":
        assert result["summary"]["counts"]["BLOCKED"] == 1
        assert result["evidence_gaps"] == [{"reason": "INCOMPLETE_NUMERICAL_COVERAGE", "count": 1}]


def test_invalid_and_missing_local_prices_rejected_without_references(tmp_path):
    invalid = _data(tmp_path / "invalid", days=(DAYS[0],), inconsistent_ohlc=True)
    missing = _data(tmp_path / "missing", days=(DAYS[0],), missing=((DAYS[0], 2),))
    manifest = _plan(source=_source("local", "OBSERVED"))
    bad = acceptance.analyze_intraday_data_acceptance(invalid, manifest, policy())
    gap = acceptance.analyze_intraday_data_acceptance(missing, manifest, policy())
    assert bad["status"] == gap["status"] == "REJECTED"
    assert bad["rejections"] == [{"reason": "INVALID_LOCAL_INPUT", "trading_days": [DAYS[0]]}]
    assert bad["local_inspections"][0]["inspection"]["summary"]["invalid_rows"] == 1
    assert bad["summary"]["counts"]["UNASSESSED"] == 78
    assert gap["rejections"] == [{"reason": "MISSING_REQUIRED_LOCAL_PRICES", "count": 1}]
    assert gap["evidence_gaps"] == [{"reason": "INCOMPLETE_NUMERICAL_COVERAGE", "count": 78}]


def test_declarations_are_separate_and_explicit_policy_changes_are_bound(acceptance_data, tmp_path):
    manifest, paths = references(acceptance_data, tmp_path, kind="SYNTHETIC")
    rejected = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    assert rejected["status"] == "REJECTED"
    assert {item["reason"] for item in rejected["rejections"]} == {"SYNTHETIC_REFERENCE_SOURCE"}
    numeric = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest,
                                                        policy(require_declared_distinct_observed=False))
    assert numeric["status"] == "POLICY_SATISFIED"
    assert numeric["policy_id"] != rejected["policy_id"]
    assert numeric["source_assurance"]["independence_verified"] is False
    for path in paths:
        payload = q44.read_json_file(path)
        payload["source"] = _source("local", "OBSERVED")
        _write(path, payload)
    shared = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    assert shared["status"] == "REJECTED"
    assert {item["reason"] for item in shared["rejections"]} == {"SHARED_DECLARED_UPSTREAM"}
    for path in paths:
        payload = q44.read_json_file(path)
        payload["source"]["upstream_id"] = None
        _write(path, payload)
    unknown = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    assert unknown["status"] == "NEEDS_EVIDENCE" and unknown["rejections"] == []
    assert {item["reason"] for item in unknown["evidence_gaps"]} == {"DISTINCT_OBSERVED_SOURCE_DECLARATION_MISSING"}
    assert len({item["acceptance_id"] for item in (rejected, numeric, shared, unknown)}) == 4


def test_config_mismatch_fails_and_changed_reference_bytes_change_identity(acceptance_data, tmp_path):
    manifest, paths = references(acceptance_data, tmp_path)
    original = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    paths[0].write_bytes(paths[0].read_bytes() + b"\n")
    changed = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy())
    assert original["status"] == changed["status"] == "POLICY_SATISFIED"
    assert original["acceptance_id"] != changed["acceptance_id"]
    tolerances = {"price_absolute": 0.01, "price_relative": 0, "volume_absolute": 0}
    with pytest.raises(ValueError, match="tolerances differ"):
        acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy(tolerances=tolerances))
    manifest["tolerances"] = tolerances
    explicit = acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy(tolerances=tolerances))
    assert explicit["status"] == "POLICY_SATISFIED" and explicit["policy_id"] != original["policy_id"]
    manifest["references"][0]["scope"]["currency"] = "JPY"
    with pytest.raises(ValueError, match="economic basis"):
        acceptance.analyze_intraday_data_acceptance(acceptance_data, manifest, policy(tolerances=tolerances))
    for malformed in (policy(scope="INTERSECTION"), policy(require_declared_distinct_observed=1),
                      policy(extra="ignore"), policy(tolerances={**tolerances, "price_absolute": -1})):
        with pytest.raises(ValueError):
            acceptance.normalize_intraday_acceptance_policy(malformed)
    corrupt = acceptance_data.as_dict()
    corrupt["data_id"] = "0" * 64
    bad_path = _write(tmp_path / "corrupt-q5.json", corrupt)
    with pytest.raises(ValueError):
        acceptance.analyze_intraday_data_acceptance(bad_path, _plan(), policy())


def test_actual_cli_publishes_nonpass_without_confusing_it_with_success(acceptance_data, tmp_path, capsys):
    manifest = _write(tmp_path / "manifest.json", _plan(source=_source("local", "OBSERVED")))
    rules = _write(tmp_path / "policy.json", policy())
    before = {p: p.read_bytes() for p in (manifest, rules, acceptance_data.path)}
    output = tmp_path / "acceptance.json"
    command = ["research-intraday-market-evidence", "--data", str(acceptance_data.path),
               "--manifest", str(manifest), "--output", str(output), "--policy", str(rules)]
    assert cli.main(command) == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "NEEDS_EVIDENCE"
    assert envelope["result_schema_version"] == acceptance.INTRADAY_DATA_ACCEPTANCE_VERSION
    assert q44.read_json_file(output) == envelope["report"]
    encoded = output.read_bytes()
    assert cli.main(command) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    assert output.read_bytes() == encoded
    good_manifest, _ = references(acceptance_data, tmp_path)
    _write(manifest, good_manifest)
    good_output = tmp_path / "accepted.json"
    good_command = [*command]
    good_command[good_command.index(str(output))] = str(good_output)
    assert cli.main(good_command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "POLICY_SATISFIED"
    # Old report generation still returns SUCCESS/0 with absent evidence.
    manifest.write_bytes(before[manifest])
    legacy_output = tmp_path / "legacy.json"
    legacy = command[:-2]
    legacy[legacy.index(str(output))] = str(legacy_output)
    assert cli.main(legacy) == 0
    legacy_result = json.loads(capsys.readouterr().out)
    assert legacy_result["status"] == "SUCCESS" and legacy_result["report"]["status"] == "UNAVAILABLE"
    assert all(p.read_bytes() == b for p, b in before.items())
