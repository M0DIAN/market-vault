"""Focused tests for Walk-Forward Plan + CLI V1."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from market_vault import cli, walk_forward_cli


UTC = timezone.utc


def _plan():
    return {
        "plan_schema_version":
            walk_forward_cli.WALK_FORWARD_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
    }


def _result():
    folds = (
        SimpleNamespace(
            fold_index=0,
            fold_id="c" * 64,
            validation_start_time=datetime(2026, 1, 1, tzinfo=UTC),
            validation_end_time=datetime(2026, 1, 20, tzinfo=UTC),
            train_candidate_count=104,
            purged_train_count=4,
            train=SimpleNamespace(row_count=100),
            validation=SimpleNamespace(row_count=20),
        ),
        SimpleNamespace(
            fold_index=1,
            fold_id="d" * 64,
            validation_start_time=datetime(2026, 1, 21, tzinfo=UTC),
            validation_end_time=datetime(2026, 2, 9, tzinfo=UTC),
            train_candidate_count=123,
            purged_train_count=3,
            train=SimpleNamespace(row_count=120),
            validation=SimpleNamespace(row_count=20),
        ),
    )
    return SimpleNamespace(
        walk_forward_id="b" * 64,
        dataset_id="a" * 64,
        label_name="forward_return_5d",
        feature_names=("rsi14", "macd"),
        minimum_train_periods=100,
        validation_periods=20,
        step_periods=20,
        development_period_count=160,
        development_sample_count=320,
        held_out_test_count=40,
        folds=folds,
    )


def test_walk_forward_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "walk-forward-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    experiment = object()
    captured = {}

    def load(path):
        captured["path"] = path
        return verified

    def build(dataset, **kwargs):
        captured["build_dataset"] = dataset
        captured["build_kwargs"] = kwargs
        return experiment

    def generate(value, **kwargs):
        captured["experiment"] = value
        captured["walk_kwargs"] = kwargs
        return _result()

    def forbidden_settings(_):
        pytest.fail("research-walk-forward must dispatch before settings load")

    monkeypatch.setattr(
        walk_forward_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(
        walk_forward_cli,
        "build_experiment_dataset",
        build,
    )
    monkeypatch.setattr(
        walk_forward_cli,
        "build_walk_forward_plan",
        generate,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-walk-forward",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["walk_forward_version"] == "market-vault-walk-forward-v1"
    assert output["walk_forward_id"] == "b" * 64
    assert output["dataset_id"] == "a" * 64
    assert output["label_name"] == "forward_return_5d"
    assert output["feature_names"] == ["rsi14", "macd"]
    assert output["config"] == {
        "minimum_train_periods": 100,
        "validation_periods": 20,
        "step_periods": 20,
    }
    assert output["development_period_count"] == 160
    assert output["development_sample_count"] == 320
    assert output["held_out_test_count"] == 40
    assert output["fold_count"] == 2
    assert output["folds"][0] == {
        "fold_index": 0,
        "fold_id": "c" * 64,
        "validation_start_time": "2026-01-01T00:00:00+00:00",
        "validation_end_time": "2026-01-20T00:00:00+00:00",
        "train_candidate_count": 104,
        "purged_train_count": 4,
        "train_count": 100,
        "validation_count": 20,
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


def test_walk_forward_plan_requires_explicit_feature_fields():
    payload = _plan()
    payload["feature_fields"] = []
    with pytest.raises(
        walk_forward_cli.WalkForwardCLIError,
        match="feature_fields",
    ):
        walk_forward_cli.parse_walk_forward_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_walk_forward_plan_rejects_duplicate_feature_fields():
    payload = _plan()
    payload["feature_fields"] = ["rsi14", "rsi14"]
    with pytest.raises(
        walk_forward_cli.WalkForwardCLIError,
        match="duplicates",
    ):
        walk_forward_cli.parse_walk_forward_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_walk_forward_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-walk-forward-plan-v1",'
        b'"plan_schema_version":"market-vault-walk-forward-plan-v1"}'
    )
    with pytest.raises(
        walk_forward_cli.WalkForwardCLIError,
        match="duplicate JSON key",
    ):
        walk_forward_cli.parse_walk_forward_plan_bytes(payload)


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
def test_walk_forward_plan_rejects_invalid_values(field, value, match):
    payload = _plan()
    payload[field] = value
    with pytest.raises(
        walk_forward_cli.WalkForwardCLIError,
        match=match,
    ):
        walk_forward_cli.parse_walk_forward_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_walk_forward_plan_rejects_extra_or_missing_fields():
    extra = _plan() | {"shuffle": True}
    with pytest.raises(walk_forward_cli.WalkForwardCLIError):
        walk_forward_cli.parse_walk_forward_plan_bytes(
            json.dumps(extra).encode("utf-8")
        )

    missing = _plan()
    del missing["dataset_build_dir"]
    with pytest.raises(walk_forward_cli.WalkForwardCLIError):
        walk_forward_cli.parse_walk_forward_plan_bytes(
            json.dumps(missing).encode("utf-8")
        )


def test_walk_forward_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "walk-forward-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    def fail(_):
        raise ValueError("not a verified Dataset")

    monkeypatch.setattr(
        walk_forward_cli,
        "load_verified_multi_source_cross_day_dataset",
        fail,
    )

    assert cli.main([
        "research-walk-forward",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        walk_forward_cli.WALK_FORWARD_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
