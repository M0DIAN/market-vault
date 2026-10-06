"""Focused tests for Ridge Regression Plan + CLI V1."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from market_vault import cli, ridge_cli


def _plan():
    return {
        "plan_schema_version": ridge_cli.RIDGE_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
        "alpha": 1.5,
    }


def _result():
    folds = (
        SimpleNamespace(
            fold_index=0,
            fold_id="c" * 64,
            train_count=100,
            validation_count=20,
            alpha=1.5,
            intercept=0.01,
            coefficients=(0.2, -0.1),
            feature_means=(50.0, 0.0),
            feature_scales=(10.0, 1.0),
            mae=0.03,
            rmse=0.04,
            r2=0.25,
        ),
        SimpleNamespace(
            fold_index=1,
            fold_id="d" * 64,
            train_count=120,
            validation_count=20,
            alpha=1.5,
            intercept=0.02,
            coefficients=(0.15, -0.05),
            feature_means=(52.0, 0.1),
            feature_scales=(9.0, 1.1),
            mae=0.02,
            rmse=0.03,
            r2=None,
        ),
    )
    return SimpleNamespace(
        walk_forward_id="b" * 64,
        dataset_id="a" * 64,
        feature_names=("rsi14", "macd"),
        label_name="forward_return_5d",
        alpha=1.5,
        folds=folds,
        validation_sample_count=40,
        mae=0.025,
        rmse=0.035,
        r2=0.2,
    )


def test_ridge_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    experiment = object()
    walk_forward = object()
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

    def evaluate(value, **kwargs):
        captured["walk_forward"] = value
        captured["ridge_kwargs"] = kwargs
        return _result()

    def forbidden_settings(_):
        pytest.fail("research-ridge must dispatch before settings load")

    monkeypatch.setattr(
        ridge_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(ridge_cli, "build_experiment_dataset", build)
    monkeypatch.setattr(ridge_cli, "build_walk_forward_plan", walk)
    monkeypatch.setattr(ridge_cli, "evaluate_ridge_baseline", evaluate)
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-ridge",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["ridge_version"] == "market-vault-ridge-baseline-v1"
    assert output["walk_forward_id"] == "b" * 64
    assert output["dataset_id"] == "a" * 64
    assert output["label_name"] == "forward_return_5d"
    assert output["feature_names"] == ["rsi14", "macd"]
    assert output["alpha"] == 1.5
    assert output["validation_sample_count"] == 40
    assert output["metrics"] == {
        "mae": 0.025,
        "rmse": 0.035,
        "r2": 0.2,
    }
    assert output["fold_count"] == 2
    assert output["folds"][0] == {
        "fold_index": 0,
        "fold_id": "c" * 64,
        "train_count": 100,
        "validation_count": 20,
        "alpha": 1.5,
        "intercept": 0.01,
        "features": [
            {
                "feature_name": "rsi14",
                "coefficient": 0.2,
                "train_mean": 50.0,
                "train_scale": 10.0,
            },
            {
                "feature_name": "macd",
                "coefficient": -0.1,
                "train_mean": 0.0,
                "train_scale": 1.0,
            },
        ],
        "metrics": {
            "mae": 0.03,
            "rmse": 0.04,
            "r2": 0.25,
        },
    }
    assert output["folds"][1]["metrics"]["r2"] is None

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
    assert captured["walk_forward"] is walk_forward
    assert captured["ridge_kwargs"] == {"alpha": 1.5}


def test_ridge_plan_requires_explicit_feature_fields():
    payload = _plan()
    payload["feature_fields"] = []
    with pytest.raises(ridge_cli.RidgeCLIError, match="feature_fields"):
        ridge_cli.parse_ridge_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_ridge_plan_rejects_duplicate_feature_fields():
    payload = _plan()
    payload["feature_fields"] = ["rsi14", "rsi14"]
    with pytest.raises(ridge_cli.RidgeCLIError, match="duplicates"):
        ridge_cli.parse_ridge_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_ridge_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-ridge-plan-v1",'
        b'"plan_schema_version":"market-vault-ridge-plan-v1"}'
    )
    with pytest.raises(
        ridge_cli.RidgeCLIError,
        match="duplicate JSON key",
    ):
        ridge_cli.parse_ridge_plan_bytes(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("minimum_train_periods", 0, "minimum_train_periods"),
        ("validation_periods", 0, "validation_periods"),
        ("step_periods", 0, "step_periods"),
        ("step_periods", 10, ">= validation_periods"),
        ("minimum_train_periods", True, "positive integer"),
        ("validation_periods", 1.5, "positive integer"),
        ("alpha", 0, "strictly positive"),
        ("alpha", -1, "strictly positive"),
        ("alpha", True, "JSON number"),
        ("alpha", float("inf"), "finite"),
    ],
)
def test_ridge_plan_rejects_invalid_values(field, value, match):
    payload = _plan()
    payload[field] = value
    with pytest.raises(ridge_cli.RidgeCLIError, match=match):
        ridge_cli.parse_ridge_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_ridge_plan_rejects_extra_or_missing_fields():
    extra = _plan() | {"alpha_grid": [0.1, 1.0, 10.0]}
    with pytest.raises(ridge_cli.RidgeCLIError):
        ridge_cli.parse_ridge_plan_bytes(
            json.dumps(extra).encode("utf-8")
        )

    missing = _plan()
    del missing["dataset_build_dir"]
    with pytest.raises(ridge_cli.RidgeCLIError):
        ridge_cli.parse_ridge_plan_bytes(
            json.dumps(missing).encode("utf-8")
        )


def test_ridge_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "ridge-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    def fail(_):
        raise ValueError("not a verified Dataset")

    monkeypatch.setattr(
        ridge_cli,
        "load_verified_multi_source_cross_day_dataset",
        fail,
    )

    assert cli.main([
        "research-ridge",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        ridge_cli.RIDGE_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
