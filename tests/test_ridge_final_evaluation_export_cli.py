"""Focused tests for Final Ridge Evaluation Export CLI V1."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_vault import cli, ridge_final_evaluation_export_cli


def _plan():
    return {
        "plan_schema_version": (
            ridge_final_evaluation_export_cli
            .RIDGE_FINAL_EVALUATION_EXPORT_PLAN_SCHEMA_VERSION
        ),
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_open_to_close_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
        "alphas": [10.0, 0.1, 1.0],
        "thresholds": [0.02, -0.01, 0.0],
        "commission_bps": 1.5,
        "slippage_bps": 2.5,
        "artifact_path": "reports/final-evaluation.json",
    }


def test_cli_runs_evaluation_once_and_writes_exact_report(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "export-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    ridge = object()
    threshold = object()
    final = object()
    fixed = object()
    selected = object()
    report = object()
    values = (ridge, threshold, final, fixed, selected, report)
    captured = {"run_calls": 0}

    def run(plan, parent):
        captured["run_calls"] += 1
        captured["evaluation_plan"] = plan
        captured["parent"] = parent
        return values

    def write(value, *, path):
        captured["report"] = value
        captured["artifact_path"] = path
        return SimpleNamespace(
            path=path,
            report_id="q" * 64,
            content_sha256="h" * 64,
            created_new_file=True,
        )

    def base_payload(*items):
        assert items == values
        return {
            "result_schema_version": "base-schema",
            "status": "SUCCESS",
            "report_id": "q" * 64,
            "dataset_id": "a" * 64,
            "delta_semantics": "VALIDATION_SELECTED_MINUS_FIXED_ZERO",
        }

    def forbidden_settings(_):
        pytest.fail(
            "research-ridge-final-evaluation-export must dispatch before settings"
        )

    monkeypatch.setattr(
        ridge_final_evaluation_export_cli,
        "ridge_final_evaluation_run",
        run,
    )
    monkeypatch.setattr(
        ridge_final_evaluation_export_cli,
        "write_ridge_final_evaluation_artifact",
        write,
    )
    monkeypatch.setattr(
        ridge_final_evaluation_export_cli,
        "evaluation_success_payload",
        base_payload,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-ridge-final-evaluation-export",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["result_schema_version"] == (
        ridge_final_evaluation_export_cli
        .RIDGE_FINAL_EVALUATION_EXPORT_CLI_RESULT_SCHEMA_VERSION
    )
    assert output["report_id"] == "q" * 64
    assert output["dataset_id"] == "a" * 64
    assert output["delta_semantics"] == (
        "VALIDATION_SELECTED_MINUS_FIXED_ZERO"
    )
    assert output["artifact"] == {
        "artifact_schema_version": (
            "market-vault-ridge-final-evaluation-artifact-v1"
        ),
        "path": str(tmp_path / "reports/final-evaluation.json"),
        "report_id": "q" * 64,
        "content_sha256": "h" * 64,
        "created_new_file": True,
    }

    assert captured["run_calls"] == 1
    assert captured["parent"] == tmp_path
    assert captured["report"] is report
    assert captured["artifact_path"] == (
        tmp_path / "reports/final-evaluation.json"
    )


def test_plan_reuses_final_evaluation_normalization():
    parsed = (
        ridge_final_evaluation_export_cli
        .parse_ridge_final_evaluation_export_plan_bytes(
            json.dumps(_plan()).encode("utf-8")
        )
    )
    evaluation = parsed.evaluation_plan
    selection = evaluation.selected_final_plan.selection_plan
    assert selection.ridge_plan.dataset_build_dir == (
        "dataset_id=" + "a" * 64
    )
    assert selection.ridge_plan.label_field == (
        "forward_open_to_close_return_5d"
    )
    assert selection.ridge_plan.feature_fields == ("rsi14", "macd")
    assert selection.ridge_plan.alphas == (0.1, 1.0, 10.0)
    assert selection.thresholds == (-0.01, 0.0, 0.02)
    assert selection.commission_bps == 1.5
    assert selection.slippage_bps == 2.5
    assert parsed.artifact_path == "reports/final-evaluation.json"


@pytest.mark.parametrize(
    "extra",
    [
        {"winner": "selected"},
        {"decision": "selected"},
        {"recommendation": "selected"},
        {"test_threshold": 0.0},
        {"final_threshold": 0.0},
        {"test_commission_bps": 1.0},
        {"test_slippage_bps": 1.0},
        {"test_refit": True},
        {"latest": True},
    ],
)
def test_plan_rejects_selection_test_or_discovery_overrides(extra):
    payload = _plan() | extra
    with pytest.raises(
        ridge_final_evaluation_export_cli
        .RidgeFinalEvaluationExportCLIError
    ):
        (
            ridge_final_evaluation_export_cli
            .parse_ridge_final_evaluation_export_plan_bytes(
                json.dumps(payload).encode("utf-8")
            )
        )


def test_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":'
        b'"market-vault-ridge-final-evaluation-export-plan-v1",'
        b'"plan_schema_version":'
        b'"market-vault-ridge-final-evaluation-export-plan-v1"}'
    )
    with pytest.raises(
        ridge_final_evaluation_export_cli
        .RidgeFinalEvaluationExportCLIError,
        match="duplicate JSON key",
    ):
        (
            ridge_final_evaluation_export_cli
            .parse_ridge_final_evaluation_export_plan_bytes(payload)
        )


def test_cli_failure_is_structured(tmp_path, monkeypatch, capsys):
    payload = _plan()
    plan_path = tmp_path / "export-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        ridge_final_evaluation_export_cli,
        "ridge_final_evaluation_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("not a verified Dataset")
        ),
    )

    assert cli.main([
        "research-ridge-final-evaluation-export",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        ridge_final_evaluation_export_cli
        .RIDGE_FINAL_EVALUATION_EXPORT_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
