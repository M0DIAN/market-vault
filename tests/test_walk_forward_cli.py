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
        "initial_train_samples": 100,
        "minimum_retained_train_samples": 90,
        "validation_samples": 20,
        "step_samples": 20,
        "embargo_seconds": 86400,
    }


def _result():
    spec = SimpleNamespace(
        initial_train_samples=100,
        minimum_retained_train_samples=90,
        validation_samples=20,
        step_samples=20,
        embargo_seconds=86400,
    )
    folds = (
        SimpleNamespace(
            fold_index=0,
            validation_start_time=datetime(2026, 1, 1, tzinfo=UTC),
            validation_end_time=datetime(2026, 1, 20, tzinfo=UTC),
            train_count=94,
            validation_count=20,
            purged_count=4,
            embargoed_count=2,
        ),
        SimpleNamespace(
            fold_index=1,
            validation_start_time=datetime(2026, 1, 21, tzinfo=UTC),
            validation_end_time=datetime(2026, 2, 9, tzinfo=UTC),
            train_count=115,
            validation_count=20,
            purged_count=3,
            embargoed_count=2,
        ),
    )
    return SimpleNamespace(
        dataset_id="a" * 64,
        label_name="forward_return_5d",
        feature_names=("rsi14", "macd"),
        source_split="TRAIN",
        source_row_count=150,
        unused_tail_count=10,
        spec=spec,
        fold_count=2,
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

    def generate(value, spec):
        captured["experiment"] = value
        captured["spec"] = spec
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
        "generate_walk_forward_folds",
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
    assert output["dataset_id"] == "a" * 64
    assert output["source_split"] == "TRAIN"
    assert output["fold_count"] == 2
    assert output["folds"][0] == {
        "fold_index": 0,
        "validation_start_time": "2026-01-01T00:00:00+00:00",
        "validation_end_time": "2026-01-20T00:00:00+00:00",
        "train_count": 94,
        "validation_count": 20,
        "purged_count": 4,
        "embargoed_count": 2,
    }

    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["build_dataset"] is verified
    assert captured["build_kwargs"] == {
        "label_field": "forward_return_5d",
        "feature_fields": ("rsi14", "macd"),
    }
    assert captured["experiment"] is experiment
    assert captured["spec"].initial_train_samples == 100
    assert captured["spec"].minimum_retained_train_samples == 90
    assert captured["spec"].validation_samples == 20
    assert captured["spec"].step_samples == 20
    assert captured["spec"].embargo_seconds == 86400


def test_walk_forward_plan_all_features_uses_null():
    payload = _plan()
    payload["feature_fields"] = None
    plan = walk_forward_cli.parse_walk_forward_plan_bytes(
        json.dumps(payload).encode("utf-8")
    )
    assert plan.feature_fields is None


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
        ("initial_train_samples", 0, "initial_train_samples"),
        (
            "minimum_retained_train_samples",
            0,
            "minimum_retained_train_samples",
        ),
        ("validation_samples", 0, "validation_samples"),
        ("step_samples", 0, "step_samples"),
        ("step_samples", 10, ">= validation_samples"),
        ("embargo_seconds", -1, "embargo_seconds"),
        ("initial_train_samples", True, "positive integer"),
        (
            "minimum_retained_train_samples",
            True,
            "positive integer",
        ),
        ("feature_fields", [], "feature_fields"),
        ("feature_fields", ["x", "x"], "duplicates"),
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


def test_walk_forward_plan_rejects_retained_minimum_above_initial():
    payload = _plan()
    payload["minimum_retained_train_samples"] = 101
    with pytest.raises(
        walk_forward_cli.WalkForwardCLIError,
        match="<= initial_train_samples",
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
