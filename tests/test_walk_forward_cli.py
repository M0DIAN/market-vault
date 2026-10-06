"""Focused tests for Purged Walk-Forward Plan + CLI V1."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from market_vault import cli, walk_forward_cli
from market_vault.research.walk_forward import (
    PURGED_WALK_FORWARD_VERSION,
)


UTC = timezone.utc


def _plan():
    return {
        "plan_schema_version":
            walk_forward_cli.WALK_FORWARD_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_return_5d",
        "feature_fields": ["f1", "f2"],
        "initial_train_samples": 100,
        "validation_samples": 20,
        "step_samples": 20,
    }


def _result():
    spec = SimpleNamespace(
        initial_train_samples=100,
        validation_samples=20,
        step_samples=20,
    )
    train = SimpleNamespace(row_count=95)
    validation = SimpleNamespace(row_count=20)
    fold = SimpleNamespace(
        fold_index=0,
        validation_start_time=datetime(2026, 1, 1, tzinfo=UTC),
        validation_end_time=datetime(2026, 1, 20, tzinfo=UTC),
        train_candidate_count=100,
        train=train,
        validation=validation,
        purged_count=5,
    )
    return SimpleNamespace(
        dataset_id="a" * 64,
        feature_names=("f1", "f2"),
        label_name="forward_return_5d",
        label_logical_type="float64",
        spec=spec,
        source_train_count=120,
        source_validation_count=40,
        source_test_count=30,
        unused_tail_count=0,
        fold_count=1,
        folds=(fold,),
    )


def test_walk_forward_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "walk-forward.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    experiment = object()
    captured = {}

    def load(path):
        captured["path"] = path
        return verified

    def build_exp(dataset, **kwargs):
        captured["verified"] = dataset
        captured["experiment_kwargs"] = kwargs
        return experiment

    def build_walk(value, **kwargs):
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
        build_exp,
    )
    monkeypatch.setattr(
        walk_forward_cli,
        "build_purged_walk_forward",
        build_walk,
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
    assert output == {
        "result_schema_version":
            walk_forward_cli.WALK_FORWARD_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "walk_forward_version": PURGED_WALK_FORWARD_VERSION,
        "dataset_id": "a" * 64,
        "feature_names": ["f1", "f2"],
        "label_name": "forward_return_5d",
        "label_logical_type": "float64",
        "spec": {
            "initial_train_samples": 100,
            "validation_samples": 20,
            "step_samples": 20,
        },
        "source_counts": {
            "train": 120,
            "validation": 40,
            "test": 30,
        },
        "unused_tail_count": 0,
        "fold_count": 1,
        "folds": [{
            "fold_index": 0,
            "validation_start_time": "2026-01-01T00:00:00+00:00",
            "validation_end_time": "2026-01-20T00:00:00+00:00",
            "train_candidate_count": 100,
            "train_count": 95,
            "purged_count": 5,
            "validation_count": 20,
        }],
    }

    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["verified"] is verified
    assert captured["experiment_kwargs"] == {
        "label_field": "forward_return_5d",
        "feature_fields": ("f1", "f2"),
    }
    assert captured["experiment"] is experiment
    assert captured["walk_kwargs"] == {
        "initial_train_samples": 100,
        "validation_samples": 20,
        "step_samples": 20,
    }


def test_walk_forward_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-purged-walk-forward-plan-v1",'
        b'"plan_schema_version":"market-vault-purged-walk-forward-plan-v1"}'
    )
    with pytest.raises(
        walk_forward_cli.WalkForwardCLIError,
        match="duplicate JSON key",
    ):
        walk_forward_cli.parse_walk_forward_plan_bytes(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("feature_fields", [], "must not be empty"),
        ("feature_fields", "f1", "JSON array"),
        ("initial_train_samples", 0, "positive integer"),
        ("validation_samples", True, "positive integer"),
        ("step_samples", -1, "positive integer"),
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


def test_walk_forward_plan_accepts_null_feature_subset():
    payload = _plan()
    payload["feature_fields"] = None
    parsed = walk_forward_cli.parse_walk_forward_plan_bytes(
        json.dumps(payload).encode("utf-8")
    )
    assert parsed.feature_fields is None


def test_walk_forward_plan_rejects_extra_field():
    payload = _plan() | {"embargo_seconds": 60}
    with pytest.raises(walk_forward_cli.WalkForwardCLIError):
        walk_forward_cli.parse_walk_forward_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_walk_forward_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "walk-forward.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        walk_forward_cli,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: (_ for _ in ()).throw(
            ValueError("not a verified Dataset")
        ),
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
