"""Focused tests for Feature Stability Plan + CLI V1."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from market_vault import cli, feature_stability_cli


def _plan():
    return {
        "plan_schema_version":
            feature_stability_cli.FEATURE_STABILITY_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "quantile_count": 5,
    }


def _metric(name, sign):
    return SimpleNamespace(
        feature_name=name,
        train_sample_count=100,
        validation_sample_count=40,
        test_sample_count=40,
        train_pearson_ic=0.12 * sign,
        validation_pearson_ic=0.08 * sign,
        test_pearson_ic=0.10 * sign,
        pearson_available_count=3,
        pearson_sign_consistent=True,
        pearson_range=0.04,
        train_rank_ic=0.15 * sign,
        validation_rank_ic=0.11 * sign,
        test_rank_ic=0.13 * sign,
        rank_available_count=3,
        rank_sign_consistent=True,
        rank_range=0.04,
        train_top_bottom_spread=0.03 * sign,
        validation_top_bottom_spread=0.02 * sign,
        test_top_bottom_spread=0.025 * sign,
        spread_available_count=3,
        spread_sign_consistent=True,
        spread_range=0.01,
    )


def _report():
    return SimpleNamespace(
        dataset_id="a" * 64,
        label_name="forward_return_5d",
        quantile_count=5,
        metrics=(
            _metric("rsi14", 1.0),
            _metric("macd", -1.0),
        ),
    )


def test_feature_stability_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "feature-stability-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    verified = object()
    bundle = object()
    captured = {}

    def load(path):
        captured["path"] = path
        return verified

    def build(dataset, **kwargs):
        captured["build_dataset"] = dataset
        captured["build_kwargs"] = kwargs
        return bundle

    def compare(value, **kwargs):
        captured["compare_bundle"] = value
        captured["compare_kwargs"] = kwargs
        return _report()

    def forbidden_settings(_):
        pytest.fail("research-feature-stability must dispatch before settings load")

    monkeypatch.setattr(
        feature_stability_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(feature_stability_cli, "build_ml_dataset", build)
    monkeypatch.setattr(
        feature_stability_cli,
        "compare_feature_stability",
        compare,
    )
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-feature-stability",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["feature_stability_version"] == (
        "market-vault-feature-stability-v1"
    )
    assert output["dataset_id"] == "a" * 64
    assert output["label_name"] == "forward_return_5d"
    assert output["quantile_count"] == 5
    assert [item["feature_name"] for item in output["metrics"]] == [
        "rsi14",
        "macd",
    ]
    first = output["metrics"][0]
    assert first["sample_counts"] == {
        "TRAIN": 100,
        "VALIDATION": 40,
        "TEST": 40,
    }
    assert first["rank_ic"]["sign_consistent"] is True
    assert first["rank_ic"]["range"] == 0.04
    assert first["top_bottom_spread"]["TEST"] == 0.025

    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["build_dataset"] is verified
    assert captured["build_kwargs"] == {
        "label_field": "forward_return_5d",
        "feature_fields": ("rsi14", "macd"),
    }
    assert captured["compare_bundle"] is bundle
    assert captured["compare_kwargs"] == {
        "feature_names": ("rsi14", "macd"),
        "quantile_count": 5,
    }


def test_feature_stability_plan_all_features_uses_null():
    payload = _plan()
    payload["feature_fields"] = None
    plan = feature_stability_cli.parse_feature_stability_plan_bytes(
        json.dumps(payload).encode("utf-8")
    )
    assert plan.feature_fields is None


def test_feature_stability_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-feature-stability-plan-v1",'
        b'"plan_schema_version":"market-vault-feature-stability-plan-v1"}'
    )
    with pytest.raises(
        feature_stability_cli.FeatureStabilityCLIError,
        match="duplicate JSON key",
    ):
        feature_stability_cli.parse_feature_stability_plan_bytes(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("quantile_count", True, "quantile_count"),
        ("quantile_count", 1, "quantile_count"),
        ("quantile_count", 11, "quantile_count"),
        ("feature_fields", [], "feature_fields"),
        ("feature_fields", ["x", "x"], "duplicates"),
    ],
)
def test_feature_stability_plan_rejects_invalid_values(field, value, match):
    payload = _plan()
    payload[field] = value
    with pytest.raises(
        feature_stability_cli.FeatureStabilityCLIError,
        match=match,
    ):
        feature_stability_cli.parse_feature_stability_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_feature_stability_plan_rejects_extra_or_missing_fields():
    extra = _plan() | {"rank_features": True}
    with pytest.raises(feature_stability_cli.FeatureStabilityCLIError):
        feature_stability_cli.parse_feature_stability_plan_bytes(
            json.dumps(extra).encode("utf-8")
        )

    missing = _plan()
    del missing["dataset_build_dir"]
    with pytest.raises(feature_stability_cli.FeatureStabilityCLIError):
        feature_stability_cli.parse_feature_stability_plan_bytes(
            json.dumps(missing).encode("utf-8")
        )


def test_feature_stability_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "feature-stability-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    def fail(_):
        raise ValueError("not a verified Dataset")

    monkeypatch.setattr(
        feature_stability_cli,
        "load_verified_multi_source_cross_day_dataset",
        fail,
    )

    assert cli.main([
        "research-feature-stability",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        feature_stability_cli.FEATURE_STABILITY_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
