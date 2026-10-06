"""Focused tests for Feature Selection Plan + CLI V1."""

from __future__ import annotations

import json

import pytest

from market_vault import cli, feature_selection_cli
from market_vault.research.feature_selection import (
    FEATURE_SELECTION_VERSION,
    REASON_RANK_IC_SIGN_MISMATCH,
    FeatureSelectionDecision,
    FeatureSelectionPolicy,
    FeatureSelectionReport,
)


def _policy():
    return {
        "minimum_train_samples": 30,
        "minimum_validation_samples": 20,
        "minimum_abs_train_rank_ic": 0.02,
        "minimum_abs_validation_rank_ic": 0.01,
        "maximum_rank_ic_drift": 0.05,
        "require_same_sign": True,
    }


def _plan():
    return {
        "plan_schema_version":
            feature_selection_cli.FEATURE_SELECTION_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_return_5d",
        "feature_fields": ["stable", "flip"],
        "quantile_count": 5,
        "policy": _policy(),
    }


def _report():
    policy = FeatureSelectionPolicy(
        30,
        20,
        0.02,
        0.01,
        0.05,
        True,
    )
    stable = FeatureSelectionDecision(
        "stable",
        True,
        (),
        100,
        50,
        0.08,
        0.07,
        0.01,
        True,
    )
    flip = FeatureSelectionDecision(
        "flip",
        False,
        (REASON_RANK_IC_SIGN_MISMATCH,),
        100,
        50,
        0.05,
        -0.04,
        0.09,
        False,
    )
    return FeatureSelectionReport(
        FEATURE_SELECTION_VERSION,
        "a" * 64,
        "forward_return_5d",
        5,
        policy,
        (stable, flip),
        ("stable",),
    )


def test_feature_selection_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "feature-selection.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    bundle = object()
    captured = {}

    def load(path):
        captured["path"] = path
        return verified

    def build(dataset, **kwargs):
        captured["dataset"] = dataset
        captured["build_kwargs"] = kwargs
        return bundle

    def select(value, **kwargs):
        captured["bundle"] = value
        captured["select_kwargs"] = kwargs
        return _report()

    def forbidden_settings(_):
        pytest.fail("research-feature-select must dispatch before settings load")

    monkeypatch.setattr(
        feature_selection_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(
        feature_selection_cli,
        "build_ml_dataset",
        build,
    )
    monkeypatch.setattr(
        feature_selection_cli,
        "select_features",
        select,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-feature-select",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["feature_selection_version"] == FEATURE_SELECTION_VERSION
    assert output["dataset_id"] == "a" * 64
    assert output["label_name"] == "forward_return_5d"
    assert output["selected_features"] == ["stable"]
    assert output["policy"] == _policy()
    assert output["decisions"] == [
        {
            "feature_name": "stable",
            "selected": True,
            "reason_codes": [],
            "train_sample_count": 100,
            "validation_sample_count": 50,
            "train_rank_ic": 0.08,
            "validation_rank_ic": 0.07,
            "rank_ic_drift": 0.01,
            "rank_ic_sign_consistent": True,
        },
        {
            "feature_name": "flip",
            "selected": False,
            "reason_codes": [REASON_RANK_IC_SIGN_MISMATCH],
            "train_sample_count": 100,
            "validation_sample_count": 50,
            "train_rank_ic": 0.05,
            "validation_rank_ic": -0.04,
            "rank_ic_drift": 0.09,
            "rank_ic_sign_consistent": False,
        },
    ]

    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["dataset"] is verified
    assert captured["build_kwargs"] == {
        "label_field": "forward_return_5d",
        "feature_fields": ("stable", "flip"),
    }
    assert captured["bundle"] is bundle
    assert captured["select_kwargs"]["feature_names"] == (
        "stable",
        "flip",
    )
    assert captured["select_kwargs"]["quantile_count"] == 5
    policy = captured["select_kwargs"]["policy"]
    assert policy == _report().policy


def test_feature_selection_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-feature-selection-plan-v1",'
        b'"plan_schema_version":"market-vault-feature-selection-plan-v1"}'
    )
    with pytest.raises(
        feature_selection_cli.FeatureSelectionCLIError,
        match="duplicate JSON key",
    ):
        feature_selection_cli.parse_feature_selection_plan_bytes(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("quantile_count", 1, "quantile_count"),
        ("feature_fields", [], "non-empty"),
        ("feature_fields", "stable", "JSON array"),
    ],
)
def test_feature_selection_plan_rejects_invalid_top_level_values(
    field, value, match
):
    payload = _plan()
    payload[field] = value
    with pytest.raises(
        feature_selection_cli.FeatureSelectionCLIError,
        match=match,
    ):
        feature_selection_cli.parse_feature_selection_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("minimum_train_samples", True, "non-negative integer"),
        ("minimum_validation_samples", -1, "non-negative integer"),
        ("minimum_abs_train_rank_ic", 1.1, "within"),
        ("minimum_abs_validation_rank_ic", float("nan"), "within"),
        ("maximum_rank_ic_drift", 2.1, "within"),
        ("require_same_sign", 1, "boolean"),
    ],
)
def test_feature_selection_plan_rejects_invalid_policy(
    field, value, match
):
    payload = _plan()
    payload["policy"][field] = value
    with pytest.raises(
        feature_selection_cli.FeatureSelectionCLIError,
        match=match,
    ):
        feature_selection_cli.parse_feature_selection_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_feature_selection_plan_accepts_null_feature_subset():
    payload = _plan()
    payload["feature_fields"] = None
    parsed = feature_selection_cli.parse_feature_selection_plan_bytes(
        json.dumps(payload).encode("utf-8")
    )
    assert parsed.feature_fields is None


def test_feature_selection_plan_rejects_extra_policy_field():
    payload = _plan()
    payload["policy"]["score"] = 0.5
    with pytest.raises(feature_selection_cli.FeatureSelectionCLIError):
        feature_selection_cli.parse_feature_selection_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_feature_selection_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "feature-selection.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        feature_selection_cli,
        "load_verified_multi_source_cross_day_dataset",
        lambda path: (_ for _ in ()).throw(
            ValueError("not a verified Dataset")
        ),
    )

    assert cli.main([
        "research-feature-select",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        feature_selection_cli.FEATURE_SELECTION_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
