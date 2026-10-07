"""Focused tests for lightweight Ridge Final Evaluation Artifact V1."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json

import pytest

from market_vault.research.ridge_final_evaluation import (
    compare_ridge_final_trading,
)
from market_vault.research.ridge_final_evaluation_artifact import (
    RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION,
    RidgeFinalEvaluationArtifactError,
    load_ridge_final_evaluation_artifact,
    parse_ridge_final_evaluation_report_bytes,
    serialize_ridge_final_evaluation_report,
    write_ridge_final_evaluation_artifact,
)
from test_ridge_final_evaluation import _results


def _report(tmp_path, monkeypatch, *, costs=(10.0, 5.0)):
    _bundle, final, threshold, fixed, selected = _results(
        tmp_path,
        monkeypatch,
        costs=costs,
    )
    return compare_ridge_final_trading(
        final,
        fixed,
        threshold,
        selected,
    )


def test_canonical_bytes_round_trip_revalidates_report_identity(
    tmp_path, monkeypatch
):
    report = _report(tmp_path, monkeypatch)

    first = serialize_ridge_final_evaluation_report(report)
    second = serialize_ridge_final_evaluation_report(report)
    assert first == second
    assert not first.endswith(b"\n")

    root = json.loads(first.decode("utf-8"))
    assert root["artifact_schema_version"] == (
        RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION
    )
    assert root["report_id"] == report.report_id
    assert root["report"]["report_id"] == report.report_id

    loaded = parse_ridge_final_evaluation_report_bytes(first)
    assert loaded == report


def test_explicit_file_write_is_idempotent_only_for_identical_report(
    tmp_path, monkeypatch
):
    report = _report(tmp_path / "first", monkeypatch)
    path = tmp_path / "final-evaluation.json"

    first = write_ridge_final_evaluation_artifact(
        report,
        path=path,
    )
    assert first.created_new_file is True
    assert first.path == path
    assert first.report_id == report.report_id
    assert first.content_sha256 == sha256(path.read_bytes()).hexdigest()
    assert load_ridge_final_evaluation_artifact(path) == report

    second = write_ridge_final_evaluation_artifact(
        report,
        path=path,
    )
    assert second.created_new_file is False
    assert second == replace(first, created_new_file=False)

    other = _report(
        tmp_path / "other",
        monkeypatch,
        costs=(0.0, 0.0),
    )
    assert other.report_id != report.report_id
    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="existing artifact differs",
    ):
        write_ridge_final_evaluation_artifact(
            other,
            path=path,
        )


def test_tampered_report_content_fails_identity_or_delta_validation(
    tmp_path, monkeypatch
):
    report = _report(tmp_path, monkeypatch)
    root = json.loads(
        serialize_ridge_final_evaluation_report(report).decode("utf-8")
    )

    root["report"]["fixed_metrics"]["total_return"] += 1.0
    tampered = json.dumps(
        root,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="report content/identity validation failed",
    ):
        parse_ridge_final_evaluation_report_bytes(tampered)


def test_root_report_id_must_match_revalidated_report(
    tmp_path, monkeypatch
):
    report = _report(tmp_path, monkeypatch)
    root = json.loads(
        serialize_ridge_final_evaluation_report(report).decode("utf-8")
    )
    root["report_id"] = "0" * 64

    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="root report_id differs",
    ):
        parse_ridge_final_evaluation_report_bytes(
            json.dumps(
                root,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )


def test_parser_rejects_duplicate_key_bom_extra_field_and_non_bytes(
    tmp_path, monkeypatch
):
    report = _report(tmp_path, monkeypatch)
    good = serialize_ridge_final_evaluation_report(report)

    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="duplicate JSON key",
    ):
        parse_ridge_final_evaluation_report_bytes(
            b'{"artifact_schema_version":'
            b'"market-vault-ridge-final-evaluation-artifact-v1",'
            b'"report_id":"' + b"a" * 64 + b'",'
            b'"report_id":"' + b"a" * 64 + b'",'
            b'"report":{}}'
        )

    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="must not carry",
    ):
        parse_ridge_final_evaluation_report_bytes(
            b"\xef\xbb\xbf" + good
        )

    root = json.loads(good.decode("utf-8"))
    root["extra"] = True
    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="fields differ",
    ):
        parse_ridge_final_evaluation_report_bytes(
            json.dumps(root).encode("utf-8")
        )

    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="must be bytes",
    ):
        parse_ridge_final_evaluation_report_bytes("not bytes")


def test_file_reader_rejects_tampering_and_non_regular_paths(
    tmp_path, monkeypatch
):
    report = _report(tmp_path / "report", monkeypatch)
    path = tmp_path / "final-evaluation.json"
    write_ridge_final_evaluation_artifact(report, path=path)

    root = json.loads(path.read_text(encoding="utf-8"))
    root["report"]["selected_threshold"] += 1.0
    path.write_text(
        json.dumps(root, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(RidgeFinalEvaluationArtifactError):
        load_ridge_final_evaluation_artifact(path)

    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="regular file",
    ):
        load_ridge_final_evaluation_artifact(tmp_path)


def test_writer_requires_existing_explicit_parent(tmp_path, monkeypatch):
    report = _report(tmp_path / "report", monkeypatch)
    with pytest.raises(
        RidgeFinalEvaluationArtifactError,
        match="existing regular directory",
    ):
        write_ridge_final_evaluation_artifact(
            report,
            path=tmp_path / "missing" / "report.json",
        )
