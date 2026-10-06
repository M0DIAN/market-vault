"""Focused tests for Ridge Final TEST Plan + CLI V1."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from market_vault import cli, ridge_final_cli


UTC = timezone.utc


def _plan():
    return {
        "plan_schema_version": ridge_final_cli.RIDGE_FINAL_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
        "alphas": [10.0, 0.1, 1.0],
    }


def _selection():
    def candidate(letter, alpha, mae, rmse, r2):
        return SimpleNamespace(
            candidate_id=letter * 64,
            alpha=alpha,
            report=SimpleNamespace(
                validation_sample_count=40,
                mae=mae,
                rmse=rmse,
                r2=r2,
            ),
        )

    return SimpleNamespace(
        selection_id="s" * 64,
        candidates=(
            candidate("b", 0.1, 0.04, 0.05, 0.1),
            candidate("c", 1.0, 0.03, 0.04, 0.2),
            candidate("d", 10.0, 0.05, 0.06, None),
        ),
    )


def _final():
    return SimpleNamespace(
        final_test_id="f" * 64,
        model_id="m" * 64,
        walk_forward_id="w" * 64,
        dataset_id="a" * 64,
        label_name="forward_return_5d",
        feature_names=("rsi14", "macd"),
        alpha=1.0,
        test_start_time=datetime(2026, 1, 1, 15, tzinfo=UTC),
        development_candidate_count=140,
        development_purged_count=3,
        development_count=137,
        development_keys_digest="k" * 64,
        test_count=30,
        intercept=0.01,
        coefficients=(0.2, -0.1),
        feature_means=(50.0, 0.0),
        feature_scales=(10.0, 1.0),
        predictions=tuple(range(30)),
        mae=0.025,
        rmse=0.035,
        r2=0.15,
    )


def test_ridge_final_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-final-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    experiment = object()
    walk_forward = object()
    selection = _selection()
    final = _final()
    captured = {}

    def load(path):
        captured["path"] = path
        return verified

    def build(dataset, **kwargs):
        captured["build_dataset"] = dataset
        captured["build_kwargs"] = kwargs
        return experiment

    def walk(value, **kwargs):
        captured["experiment"] = value
        captured["walk_kwargs"] = kwargs
        return walk_forward

    def select(value, **kwargs):
        captured["selection_plan"] = value
        captured["selection_kwargs"] = kwargs
        return selection

    def evaluate(bundle, plan, selected):
        captured["final_bundle"] = bundle
        captured["final_plan"] = plan
        captured["final_selection"] = selected
        return final

    def forbidden_settings(_):
        pytest.fail("research-ridge-final must dispatch before settings load")

    monkeypatch.setattr(
        ridge_final_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(
        ridge_final_cli,
        "build_experiment_dataset",
        build,
    )
    monkeypatch.setattr(
        ridge_final_cli,
        "build_walk_forward_plan",
        walk,
    )
    monkeypatch.setattr(
        ridge_final_cli,
        "select_ridge_alpha",
        select,
    )
    monkeypatch.setattr(
        ridge_final_cli,
        "evaluate_ridge_final_test",
        evaluate,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-ridge-final",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["alpha_selection_version"] == (
        "market-vault-ridge-alpha-selection-v1"
    )
    assert output["final_test_version"] == (
        "market-vault-ridge-final-test-v1"
    )
    assert output["selection_id"] == "s" * 64
    assert output["final_test_id"] == "f" * 64
    assert output["model_id"] == "m" * 64
    assert output["walk_forward_id"] == "w" * 64
    assert output["dataset_id"] == "a" * 64
    assert output["selected_alpha"] == 1.0
    assert output["alpha_candidates"] == [
        {
            "candidate_id": "b" * 64,
            "alpha": 0.1,
            "validation_sample_count": 40,
            "metrics": {"mae": 0.04, "rmse": 0.05, "r2": 0.1},
        },
        {
            "candidate_id": "c" * 64,
            "alpha": 1.0,
            "validation_sample_count": 40,
            "metrics": {"mae": 0.03, "rmse": 0.04, "r2": 0.2},
        },
        {
            "candidate_id": "d" * 64,
            "alpha": 10.0,
            "validation_sample_count": 40,
            "metrics": {"mae": 0.05, "rmse": 0.06, "r2": None},
        },
    ]
    assert output["development"] == {
        "candidate_count": 140,
        "purged_count": 3,
        "retained_count": 137,
        "sample_keys_digest": "k" * 64,
    }
    assert output["test_count"] == 30
    assert output["prediction_count"] == 30
    assert output["model"] == {
        "intercept": 0.01,
        "features": [
            {
                "feature_name": "rsi14",
                "coefficient": 0.2,
                "development_mean": 50.0,
                "development_scale": 10.0,
            },
            {
                "feature_name": "macd",
                "coefficient": -0.1,
                "development_mean": 0.0,
                "development_scale": 1.0,
            },
        ],
    }
    assert output["test_metrics"] == {
        "mae": 0.025,
        "rmse": 0.035,
        "r2": 0.15,
    }

    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["build_dataset"] is verified
    assert captured["build_kwargs"] == {
        "label_field": "forward_return_5d",
        "feature_fields": ("rsi14", "macd"),
    }
    assert captured["experiment"] is experiment
    assert captured["walk_kwargs"] == {
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
    }
    assert captured["selection_plan"] is walk_forward
    assert captured["selection_kwargs"] == {
        "alphas": (0.1, 1.0, 10.0),
    }
    assert captured["final_bundle"] is experiment
    assert captured["final_plan"] is walk_forward
    assert captured["final_selection"] is selection


def test_ridge_final_plan_normalizes_alpha_order():
    payload = _plan()
    plan = ridge_final_cli.parse_ridge_final_plan_bytes(
        json.dumps(payload).encode("utf-8")
    )
    assert plan.alphas == (0.1, 1.0, 10.0)


@pytest.mark.parametrize(
    "alphas,match",
    [
        ([], "at least two"),
        ([1.0], "at least two"),
        ([1.0, 1.0], "unique"),
        ([0.0, 1.0], "strictly positive"),
        ([-1.0, 1.0], "strictly positive"),
        ([True, 1.0], "JSON numbers"),
        ([float("inf"), 1.0], "finite"),
        ("0.1,1.0", "JSON array"),
    ],
)
def test_ridge_final_plan_rejects_invalid_alpha_candidates(alphas, match):
    payload = _plan()
    payload["alphas"] = alphas
    with pytest.raises(ridge_final_cli.RidgeFinalCLIError, match=match):
        ridge_final_cli.parse_ridge_final_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_ridge_final_plan_requires_explicit_unique_features():
    payload = _plan()
    payload["feature_fields"] = []
    with pytest.raises(ridge_final_cli.RidgeFinalCLIError, match="feature_fields"):
        ridge_final_cli.parse_ridge_final_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )

    payload = _plan()
    payload["feature_fields"] = ["rsi14", "rsi14"]
    with pytest.raises(ridge_final_cli.RidgeFinalCLIError, match="duplicates"):
        ridge_final_cli.parse_ridge_final_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_ridge_final_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-ridge-final-plan-v1",'
        b'"plan_schema_version":"market-vault-ridge-final-plan-v1"}'
    )
    with pytest.raises(
        ridge_final_cli.RidgeFinalCLIError,
        match="duplicate JSON key",
    ):
        ridge_final_cli.parse_ridge_final_plan_bytes(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("minimum_train_periods", 0, "minimum_train_periods"),
        ("validation_periods", 0, "validation_periods"),
        ("step_periods", 0, "step_periods"),
        ("step_periods", 10, ">= validation_periods"),
        ("minimum_train_periods", True, "positive integer"),
        ("validation_periods", 1.5, "positive integer"),
    ],
)
def test_ridge_final_plan_rejects_invalid_fold_values(field, value, match):
    payload = _plan()
    payload[field] = value
    with pytest.raises(ridge_final_cli.RidgeFinalCLIError, match=match):
        ridge_final_cli.parse_ridge_final_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_ridge_final_plan_rejects_extra_or_missing_fields():
    extra = _plan() | {"reuse_test": True}
    with pytest.raises(ridge_final_cli.RidgeFinalCLIError):
        ridge_final_cli.parse_ridge_final_plan_bytes(
            json.dumps(extra).encode("utf-8")
        )

    missing = _plan()
    del missing["dataset_build_dir"]
    with pytest.raises(ridge_final_cli.RidgeFinalCLIError):
        ridge_final_cli.parse_ridge_final_plan_bytes(
            json.dumps(missing).encode("utf-8")
        )


def test_ridge_final_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-final-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    def fail(_):
        raise ValueError("not a verified Dataset")

    monkeypatch.setattr(
        ridge_final_cli,
        "load_verified_multi_source_cross_day_dataset",
        fail,
    )

    assert cli.main([
        "research-ridge-final",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        ridge_final_cli.RIDGE_FINAL_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
