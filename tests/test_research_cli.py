"""Focused tests for Research Build Plan + CLI V1."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cross_day_helpers as cd
from cross_day_dataset_helpers import fixture
from market_vault import cli
from market_vault.cross_day_dataset import join_multi_source_cross_day_dataset
from market_vault.multi_source.feature_specs import (
    serialize_observation_feature_spec,
)
from market_vault import research_cli


def _generic_spec_payload(spec):
    payload = {
        "spec_schema_version": spec.spec_schema_version,
        "kind": spec.kind,
        "name": spec.name,
        "version": spec.version,
        "output": {
            "name": spec.output.name,
            "logical_type": spec.output.logical_type,
            "nullable": spec.output.nullable,
        },
        "inputs": {
            "canonical_fields": list(spec.input_canonical_fields),
        },
        "transform": {"ref": spec.transform_ref},
        "parameters": {p.name: p.value for p in spec.parameters},
        "requirements": {
            "canonical_schema_versions": list(
                spec.requirements.canonical_schema_versions
            ),
            "source_schema_versions": list(
                spec.requirements.source_schema_versions
            ),
        },
    }
    if spec.kind == "LABEL":
        payload.update({
            "observation_window": {
                "unit": spec.observation_window.unit,
                "start_offset": spec.observation_window.start_offset,
                "end_offset": spec.observation_window.end_offset,
            },
            "horizon": {
                "unit": spec.horizon.unit,
                "value": spec.horizon.value,
            },
            "alignment_rule": spec.alignment_rule,
            "missing_data_policy": spec.missing_data_policy,
            "cross_trading_day": {
                "allow": spec.cross_trading_day.allow,
                "boundary_rule": spec.cross_trading_day.boundary_rule,
            },
        })
    return payload


def _schedule_payload(schedule):
    return {
        "schedule_schema_version": schedule.schedule_schema_version,
        "market": schedule.market,
        "requested_session": schedule.requested_session,
        "market_timezone": schedule.market_timezone,
        "coverage_start_date": schedule.coverage_start_date.isoformat(),
        "coverage_end_date": schedule.coverage_end_date.isoformat(),
        "daily_records": [
            {
                "market_calendar_date": record.market_calendar_date.isoformat(),
                "day_status": record.day_status,
                "session_open": (
                    None
                    if record.session_open is None
                    else record.session_open.isoformat()
                ),
                "session_close": (
                    None
                    if record.session_close is None
                    else record.session_close.isoformat()
                ),
                "session_profile": record.session_profile,
            }
            for record in schedule.daily_records
        ],
        "source_snapshot_id": schedule.source_snapshot_id,
        "source_content_hash": schedule.source_content_hash,
        "calendar_contract_version": schedule.calendar_contract_version,
        "normalization_version": schedule.normalization_version,
        "coverage_completion_evidence_id": (
            schedule.coverage_completion_evidence_id
        ),
        "coverage_complete": schedule.coverage_complete,
        "archive_available_at": schedule.archive_available_at.isoformat(),
    }


def _scope_payload(scope):
    return {
        "symbols": list(scope.symbols),
        "trade_dates": [d.isoformat() for d in scope.trade_dates],
        "interval": scope.interval,
        "adjustment": scope.adjustment,
        "requested_session": scope.requested_session,
    }


def _split_payload(split):
    return {
        "spec_schema_version": split.spec_schema_version,
        "name": split.name,
        "version": split.version,
        "boundary_timezone": split.boundary_timezone,
        "train_end_date": split.train_end_date.isoformat(),
        "validation_end_date": split.validation_end_date.isoformat(),
        "test_end_date": split.test_end_date.isoformat(),
        "assignment_rule": split.assignment_rule,
        "purge_rule": split.purge_rule,
        "incomplete_label_policy": split.incomplete_label_policy,
        "out_of_range_policy": split.out_of_range_policy,
    }


def _write_plan(tmp_path):
    existing = fixture(tmp_path / "upstream", slots=(0, 1, 2))
    association = existing["cross_day_association"]

    ts2_file = tmp_path / "ts2.json"
    ts2_file.write_text(
        json.dumps(_generic_spec_payload(existing["ts2_features"].feature_specs[0])),
        encoding="utf-8",
    )
    observation_file = tmp_path / "observation.json"
    observation_file.write_bytes(
        serialize_observation_feature_spec(
            existing["observation_feature_specs"][0]
        )
    )
    label_file = tmp_path / "label.json"
    label_file.write_text(
        json.dumps(_generic_spec_payload(association.label_specs[0])),
        encoding="utf-8",
    )

    plan = {
        "plan_schema_version": research_cli.RESEARCH_BUILD_PLAN_SCHEMA_VERSION,
        "feature_build_dirs": [
            str(build.build_path) for build in association.feature_builds
        ],
        "label_build_dirs": [
            str(build.build_path) for build in association.label_builds
        ],
        "observation_build_dirs": [
            str(build.build_dir) for build in existing["observation_builds"]
        ],
        "ts2_feature_spec_files": [str(ts2_file)],
        "observation_feature_spec_files": [str(observation_file)],
        "label_spec_files": [str(label_file)],
        "schedule": _schedule_payload(existing["schedule"]),
        "scope": _scope_payload(existing["scope"]),
        "split_spec": _split_payload(existing["split_spec"]),
        "anchors": [{
            "code": "US.AAPL",
            "market_calendar_date": "2025-03-03",
            "anchor_slot": 2,
        }],
        "feature_window_bars": 3,
        "dataset_as_of": existing["dataset_as_of"].isoformat(),
        "output_root": str(tmp_path / "research-output"),
        "built_at": (cd.AS_OF.replace(day=3)).isoformat(),
    }
    plan_path = tmp_path / "research-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return existing, plan, plan_path


def _fake_materialization(existing, build_path):
    logical = join_multi_source_cross_day_dataset(**existing)
    verified = SimpleNamespace(
        dataset_id=logical.dataset_id,
        status=logical.status,
        build_path=build_path,
        rows=logical.rows,
        ts2_features=logical.ts2_features,
        observation_features=logical.observation_features,
        cross_day_labels=logical.cross_day_labels,
        split_result=logical.split_result,
        completion=logical.completion,
    )
    return SimpleNamespace(verified=verified, created_new_build=True)


def test_research_build_cli_loads_explicit_plan_and_skips_settings(
    tmp_path, monkeypatch, capsys
):
    existing, plan, plan_path = _write_plan(tmp_path)
    captured = {}

    def build(**kwargs):
        captured.update(kwargs)
        return _fake_materialization(
            existing,
            Path(plan["output_root"]) / "dataset_id=fake",
        )

    def forbidden_settings(_):
        pytest.fail("research-build must dispatch before settings load")

    monkeypatch.setattr(research_cli, "build_research_dataset", build)
    monkeypatch.setattr(cli, "load_settings", forbidden_settings)

    assert cli.main([
        "--settings",
        str(tmp_path / "missing-settings.yaml"),
        "research-build",
        "--plan",
        str(plan_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SUCCESS"
    assert output["dataset_id"] == (
        join_multi_source_cross_day_dataset(**existing).dataset_id
    )
    assert output["row_count"] == 1
    assert output["feature_count"] == 2
    assert output["label_count"] == 1
    assert output["created_new_build"] is True
    assert set(output["split_counts"]) == {
        "TRAIN", "VALIDATION", "TEST", "PURGED", "EXCLUDED"
    }

    assert tuple(b.canonical_build_id for b in captured["feature_builds"]) == (
        tuple(
            b.canonical_build_id
            for b in existing["cross_day_association"].feature_builds
        )
    )
    assert tuple(b.canonical_build_id for b in captured["label_builds"]) == (
        tuple(
            b.canonical_build_id
            for b in existing["cross_day_association"].label_builds
        )
    )
    assert tuple(
        b.observation_build_id for b in captured["observation_builds"]
    ) == tuple(
        b.observation_build_id for b in existing["observation_builds"]
    )
    assert captured["schedule"] == existing["schedule"]
    assert captured["scope"] == existing["scope"]
    assert captured["split_spec"] == existing["split_spec"]
    assert captured["feature_window_bars"] == 3
    assert captured["dataset_as_of"] == existing["dataset_as_of"]
    assert captured["output_root"] == Path(plan["output_root"])
    assert len(captured["ts2_feature_specs"]) == 1
    assert len(captured["observation_feature_specs"]) == 1
    assert len(captured["label_specs"]) == 1


def test_research_plan_rejects_duplicate_json_key():
    payload = (
        b'{"plan_schema_version":"market-vault-research-build-plan-v1",'
        b'"plan_schema_version":"market-vault-research-build-plan-v1"}'
    )
    with pytest.raises(research_cli.ResearchCLIError, match="duplicate JSON key"):
        research_cli.parse_research_plan_bytes(payload)


def test_research_plan_rejects_no_feature_specs(tmp_path):
    _, plan, _ = _write_plan(tmp_path)
    plan["ts2_feature_spec_files"] = []
    plan["observation_feature_spec_files"] = []
    with pytest.raises(
        research_cli.ResearchCLIError,
        match="at least one TS2 or Observation Feature spec",
    ):
        research_cli.parse_research_plan_bytes(
            json.dumps(plan).encode("utf-8")
        )
