"""Focused tests for Feature Research Plan + CLI V1."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from market_vault import cli, feature_research_cli


def _plan():
    return {
        "plan_schema_version":
            feature_research_cli.FEATURE_RESEARCH_PLAN_SCHEMA_VERSION,
        "dataset_build_dir": "dataset_id=" + "a" * 64,
        "label_field": "forward_return_5d",
        "feature_fields": ["rsi14", "macd"],
        "split": "TRAIN",
        "quantile_count": 5,
    }


def _report():
    return SimpleNamespace(
        dataset_id="a" * 64,
        split="TRAIN",
        label_name="forward_return_5d",
        quantile_count=5,
        metrics=(
            SimpleNamespace(
                feature_name="rsi14",
                sample_count=100,
                feature_mean=50.0,
                feature_std=10.0,
                pearson_ic=0.12,
                rank_ic=0.15,
                bottom_count=20,
                top_count=20,
                bottom_label_mean=-0.01,
                top_label_mean=0.02,
                top_bottom_spread=0.03,
            ),
            SimpleNamespace(
                feature_name="macd",
                sample_count=100,
                feature_mean=0.1,
                feature_std=1.2,
                pearson_ic=-0.05,
                rank_ic=-0.04,
                bottom_count=20,
                top_count=20,
                bottom_label_mean=0.01,
                top_label_mean=0.0,
                top_bottom_spread=-0.01,
            ),
        ),
    )


def test_feature_report_cli_is_settings_independent_and_explicit(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "feature-report-plan.json"
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

    def analyze(value, **kwargs):
        captured["analyze_bundle"] = value
        captured["analyze_kwargs"] = kwargs
        return _report()

    def forbidden_settings(_):
        pytest.fail("research-feature-report must dispatch before settings load")

    monkeypatch.setattr(
        feature_research_cli,
        "load_verified_multi_source_cross_day_dataset",
        load,
    )
    monkeypatch.setattr(feature_research_cli, "build_ml_dataset", build)
    monkeypatch.setattr(feature_research_cli, "analyze_features", analyze)
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-feature-report",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["feature_research_version"] == (
        "market-vault-feature-research-v1"
    )
    assert output["dataset_id"] == "a" * 64
    assert output["split"] == "TRAIN"
    assert output["label_name"] == "forward_return_5d"
    assert output["quantile_count"] == 5
    assert [item["feature_name"] for item in output["metrics"]] == [
        "rsi14",
        "macd",
    ]
    assert output["metrics"][0]["rank_ic"] == 0.15
    assert output["metrics"][0]["top_bottom_spread"] == 0.03

    assert captured["path"] == tmp_path / payload["dataset_build_dir"]
    assert captured["build_dataset"] is verified
    assert captured["build_kwargs"] == {
        "label_field": "forward_return_5d",
        "feature_fields": ("rsi14", "macd"),
    }
    assert captured["analyze_bundle"] is bundle
    assert captured["analyze_kwargs"] == {
        "split": "TRAIN",
        "feature_names": ("rsi14", "macd"),
        "quantile_count": 5,
    }


def test_feature_report_plan_all_features_uses_null(tmp_path, monkeypatch):
    payload = _plan()
    payload["feature_fields"] = None
    plan = feature_research_cli.parse_feature_research_plan_bytes(
        json.dumps(payload).encode("utf-8")
    )
    assert plan.feature_fields is None


def test_feature_report_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-feature-research-plan-v1",'
        b'"plan_schema_version":"market-vault-feature-research-plan-v1"}'
    )
    with pytest.raises(
        feature_research_cli.FeatureResearchCLIError,
        match="duplicate JSON key",
    ):
        feature_research_cli.parse_feature_research_plan_bytes(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("split", "ALL", "TRAIN, VALIDATION, or TEST"),
        ("quantile_count", True, "quantile_count"),
        ("quantile_count", 1, "quantile_count"),
        ("quantile_count", 11, "quantile_count"),
        ("feature_fields", [], "feature_fields"),
        ("feature_fields", ["x", "x"], "must be unique"),
    ],
)
def test_feature_report_plan_rejects_invalid_values(field, value, match):
    payload = _plan()
    payload[field] = value
    with pytest.raises(
        feature_research_cli.FeatureResearchCLIError,
        match=match,
    ):
        feature_research_cli.parse_feature_research_plan_bytes(
            json.dumps(payload).encode("utf-8")
        )


def test_feature_report_plan_rejects_extra_or_missing_fields():
    extra = _plan() | {"shuffle": True}
    with pytest.raises(feature_research_cli.FeatureResearchCLIError):
        feature_research_cli.parse_feature_research_plan_bytes(
            json.dumps(extra).encode("utf-8")
        )

    missing = _plan()
    del missing["dataset_build_dir"]
    with pytest.raises(feature_research_cli.FeatureResearchCLIError):
        feature_research_cli.parse_feature_research_plan_bytes(
            json.dumps(missing).encode("utf-8")
        )


def test_feature_report_cli_failure_is_structured(
    tmp_path, monkeypatch, capsys
):
    payload = _plan()
    plan_path = tmp_path / "feature-report-plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    def fail(_):
        raise ValueError("not a verified Dataset")

    monkeypatch.setattr(
        feature_research_cli,
        "load_verified_multi_source_cross_day_dataset",
        fail,
    )

    assert cli.main([
        "research-feature-report",
        "--plan",
        str(plan_path),
    ]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["status"] == "FAILED"
    assert output["result_schema_version"] == (
        feature_research_cli.FEATURE_RESEARCH_CLI_RESULT_SCHEMA_VERSION
    )
    assert "not a verified Dataset" in output["error"]
