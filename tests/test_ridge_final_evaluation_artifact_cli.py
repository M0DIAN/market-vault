"""Focused tests for Final Ridge Evaluation Artifact CLI V1."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_ridge_final_evaluation_cli as base
from market_vault import (
    cli,
    ridge_final_evaluation_artifact_cli as artifact_cli,
)
from market_vault.research.ridge_final_evaluation_artifact import (
    RidgeFinalEvaluationArtifactError,
)


def _plan():
    payload = base._plan()
    payload["plan_schema_version"] = (
        artifact_cli
        .RIDGE_FINAL_EVALUATION_ARTIFACT_PLAN_SCHEMA_VERSION
    )
    payload["artifact_path"] = "artifacts/final-evaluation.json"
    return payload


def _values():
    return (
        base._ridge_selection(),
        base._threshold_selection(),
        base._final(),
        base._fixed_trading(),
        base._selected_trading(),
        base._report(),
    )


def test_cli_runs_frozen_evaluation_once_then_writes_exact_artifact(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "artifact-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    values = _values()
    captured = {"pipeline_calls": 0, "writer_calls": 0}

    def run_evaluation(plan, parent):
        captured["pipeline_calls"] += 1
        captured["evaluation_plan"] = plan
        captured["parent"] = parent
        return values

    def write(report, *, path):
        captured["writer_calls"] += 1
        captured["report"] = report
        captured["artifact_path"] = path
        return SimpleNamespace(
            path=path,
            report_id=report.report_id,
            content_sha256="d" * 64,
            created_new_file=True,
        )

    def forbidden_settings(_):
        pytest.fail(
            "research-ridge-final-evaluation-artifact must dispatch "
            "before settings load"
        )

    monkeypatch.setattr(
        artifact_cli,
        "_run_evaluation_plan",
        run_evaluation,
    )
    monkeypatch.setattr(
        artifact_cli,
        "write_ridge_final_evaluation_artifact",
        write,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-ridge-final-evaluation-artifact",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["result_schema_version"] == (
        artifact_cli
        .RIDGE_FINAL_EVALUATION_ARTIFACT_CLI_RESULT_SCHEMA_VERSION
    )
    assert output["report_id"] == "q" * 64
    assert output["final_test_id"] == "f" * 64
    assert output["model_id"] == "m" * 64
    assert output["delta_semantics"] == (
        "VALIDATION_SELECTED_MINUS_FIXED_ZERO"
    )
    assert output["artifact"] == {
        "artifact_schema_version": (
            "market-vault-ridge-final-evaluation-artifact-v1"
        ),
        "path": str(tmp_path / "artifacts" / "final-evaluation.json"),
        "report_id": "q" * 64,
        "content_sha256": "d" * 64,
        "created_new_file": True,
    }

    assert captured["pipeline_calls"] == 1
    assert captured["writer_calls"] == 1
    assert captured["parent"] == tmp_path
    assert captured["report"] is values[-1]
    assert captured["artifact_path"] == (
        tmp_path / "artifacts" / "final-evaluation.json"
    )

    evaluation_plan = captured["evaluation_plan"]
    selection = evaluation_plan.selected_final_plan.selection_plan
    assert selection.ridge_plan.dataset_build_dir == (
        payload["dataset_build_dir"]
    )
    assert selection.ridge_plan.feature_fields == ("rsi14", "macd")
    assert selection.ridge_plan.alphas == (0.1, 1.0, 10.0)
    assert selection.thresholds == (-0.01, 0.0, 0.02)


def test_plan_reuses_final_evaluation_normalization():
    parsed = artifact_cli.parse_ridge_final_evaluation_artifact_plan_bytes(
        json.dumps(_plan()).encode("utf-8")
    )
    assert parsed.artifact_path == "artifacts/final-evaluation.json"
    selection = parsed.evaluation_plan.selected_final_plan.selection_plan
    assert selection.ridge_plan.feature_fields == ("rsi14", "macd")
    assert selection.ridge_plan.alphas == (0.1, 1.0, 10.0)
    assert selection.thresholds == (-0.01, 0.0, 0.02)
    assert selection.commission_bps == 1.5
    assert selection.slippage_bps == 2.5


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_path": ""},
        {"winner": "selected"},
        {"decision": "selected"},
        {"recommendation": "selected"},
        {"test_threshold": 0.0},
        {"final_threshold": 0.0},
        {"test_refit": True},
    ],
)
def test_plan_rejects_invalid_or_selection_stage_fields(change):
    payload = _plan()
    payload.update(change)
    with pytest.raises(
        artifact_cli.RidgeFinalEvaluationArtifactCLIError
    ):
        artifact_cli.parse_ridge_final_evaluation_artifact_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":'
        b'"market-vault-ridge-final-evaluation-artifact-plan-v1",'
        b'"plan_schema_version":'
        b'"market-vault-ridge-final-evaluation-artifact-plan-v1"}'
    )
    with pytest.raises(
        artifact_cli.RidgeFinalEvaluationArtifactCLIError,
        match="duplicate JSON key",
    ):
        artifact_cli.parse_ridge_final_evaluation_artifact_plan_bytes(
            payload
        )


def test_cli_writer_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "artifact-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        artifact_cli,
        "_run_evaluation_plan",
        lambda plan, parent: _values(),
    )
    monkeypatch.setattr(
        artifact_cli,
        "write_ridge_final_evaluation_artifact",
        lambda report, *, path: (_ for _ in ()).throw(
            RidgeFinalEvaluationArtifactError("existing artifact differs")
        ),
    )

    assert cli.main([
        "research-ridge-final-evaluation-artifact",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        artifact_cli
        .RIDGE_FINAL_EVALUATION_ARTIFACT_CLI_RESULT_SCHEMA_VERSION
    )
    assert "existing artifact differs" in output["error"]


def test_cli_rejects_writer_report_id_mismatch(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "artifact-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        artifact_cli,
        "_run_evaluation_plan",
        lambda plan, parent: _values(),
    )
    monkeypatch.setattr(
        artifact_cli,
        "write_ridge_final_evaluation_artifact",
        lambda report, *, path: SimpleNamespace(
            path=Path(path),
            report_id="e" * 64,
            content_sha256="d" * 64,
            created_new_file=False,
        ),
    )

    assert cli.main([
        "research-ridge-final-evaluation-artifact",
        "--plan",
        str(plan_path),
    ]) == 1

    output = json.loads(capsys.readouterr().err)
    assert output["status"] == "FAILED"
    assert "different report_id" in output["error"]
