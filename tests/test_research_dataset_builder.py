"""Focused composition tests for Research Dataset Builder V1."""

from datetime import date, timedelta
from pathlib import Path

import market_vault

import cross_day_helpers as cd
from cross_day_dataset_helpers import fixture
from market_vault.cross_day_dataset import CrossDayAnchor, join_multi_source_cross_day_dataset
from market_vault import research_dataset as research


def _kwargs(tmp_path):
    existing = fixture(tmp_path / "upstream", slots=(0, 1, 2))
    association = existing["cross_day_association"]
    return existing, dict(
        feature_builds=association.feature_builds,
        label_builds=association.label_builds,
        observation_builds=existing["observation_builds"],
        schedule=existing["schedule"],
        scope=existing["scope"],
        split_spec=existing["split_spec"],
        anchors=(CrossDayAnchor("US.AAPL", date(2025, 3, 3), 2),),
        ts2_feature_specs=existing["ts2_features"].feature_specs,
        observation_feature_specs=existing["observation_feature_specs"],
        label_specs=association.label_specs,
        feature_window_bars=3,
        dataset_as_of=existing["dataset_as_of"],
        output_root=tmp_path / "research",
        built_at=cd.AS_OF + timedelta(days=2),
    )


def test_builder_composes_existing_pipeline_without_redefining_authority(tmp_path, monkeypatch):
    existing, kwargs = _kwargs(tmp_path)
    expected = join_multi_source_cross_day_dataset(**existing)
    captured = {}
    sentinel = object()

    def materialize(result, *, output_root, built_at):
        captured["result"] = result
        captured["output_root"] = output_root
        captured["built_at"] = built_at
        return sentinel

    monkeypatch.setattr(
        research,
        "materialize_multi_source_cross_day_dataset_build",
        materialize,
    )

    assert research.build_research_dataset(**kwargs) is sentinel
    actual = captured["result"]
    assert actual.dataset_id == expected.dataset_id
    assert actual.schema == expected.schema
    assert actual.rows == expected.rows
    assert actual.sample_audit == expected.sample_audit
    assert actual.completion == expected.completion
    assert actual.split_result == expected.split_result
    assert captured["output_root"] == kwargs["output_root"]
    assert captured["built_at"] == kwargs["built_at"]


def test_source_mode_keeps_exact_caller_output_root(tmp_path):
    requested = tmp_path / "research" / "cross_day"
    assert research._production_materialization_output_root(requested) == requested


def test_frozen_windows_research_output_root_contract_is_direct_volume_child():
    source = Path(research.__file__).read_text(encoding="utf-8")
    assert 'Path(root.anchor) / "MarketVault-Research" / "cross_day"' in source
    assert 'os.name != "nt"' in source
    assert 'getattr(sys, "frozen", False)' in source


def test_top_level_lazy_export_points_to_builder():
    assert market_vault.build_research_dataset is research.build_research_dataset
