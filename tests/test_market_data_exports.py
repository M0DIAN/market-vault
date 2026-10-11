"""Offline CSV/verified-Canonical bridges and actual market-data CLI publication.

Every price below is synthetic. Passing these tests establishes the local
comparison/export contract, never the accuracy of a market-data provider.
"""

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json

import pytest

import cross_day_helpers as cd
from market_vault import cli
from market_vault.canonical.reader import load_verified_canonical_build
from market_vault.market_data_exports import snapshot_from_canonical, snapshot_from_csv
from market_vault.quality import market_data_comparison as comparison
from market_vault.storage import atomic_file
from market_vault.storage.atomic_file import AtomicFilePublicationError


BAR_FIELDS = ("start", "end", "open", "high", "low", "close", "volume")
SNAPSHOT_VERSION = "market-vault-market-data-snapshot-v1"


def _utc(value):
    return value.isoformat().replace("+00:00", "Z")


def _metadata(*, day="2025-03-03", interval="5m", count=2, provider="offline-fixture"):
    start = cd.local(day)
    return {
        "source": {
            "provider": provider,
            "version": "fixture-capture-v1",
            "captured_at": "2026-01-03T12:34:56Z",
            "data_kind": "SYNTHETIC",
            "upstream_id": None,
            "upstream_evidence": None,
        },
        "scope": {
            "symbol": "US.AAPL",
            "asset_class": "EQUITY",
            "adjustment": "NONE",
            "session": "RTH",
            "interval": interval,
            "currency": "USD",
            "aggregation": "TRADE_OHLCV",
            "volume_basis": "SHARES",
            "window_start": _utc(start),
            "window_end": _utc(start + timedelta(minutes=int(interval[:-1]) * count)),
        },
    }


def _csv(path, rows=None, *, header=BAR_FIELDS):
    if rows is None:
        rows = [
            ("2025-03-03T14:30:00+00:00", "2025-03-03T14:35:00+00:00", "100", "102", "99", "101", "10"),
            ("2025-03-03T14:35:00+00:00", "2025-03-03T14:40:00+00:00", "101", "103", "100", "102", "0"),
        ]
    path.write_text(",".join(header) + "\n" + "".join(",".join(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _json_file(path, payload):
    # Ordinary external JSON need not already have the exporter's canonical bytes.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _strict_json(data):
    def reject_constant(value):
        pytest.fail(f"Non-JSON numeric token in saved output: {value}")

    return json.loads(data, parse_constant=reject_constant)


def _run(capsys, tmp_path, arguments, *, expected=0):
    missing_settings = tmp_path / "settings-that-do-not-exist.yaml"
    result = cli.main(["--settings", str(missing_settings), *arguments])
    captured = capsys.readouterr()
    assert result == expected, captured.err
    if expected == 0:
        assert not captured.err
        assert captured.out.isascii()
        return _strict_json(captured.out)
    assert not captured.out
    assert captured.err.isascii()
    payload = _strict_json(captured.err)
    assert payload["status"] == "FAILED"
    return payload


def test_csv_converts_fixed_columns_without_changing_metadata_or_inputs(tmp_path):
    csv_path = _csv(tmp_path / "bars.csv")
    original = csv_path.read_bytes()
    metadata = _metadata()
    before = deepcopy(metadata)
    snapshot = snapshot_from_csv(csv_path, metadata)

    assert snapshot["schema_version"] == SNAPSHOT_VERSION
    assert snapshot["source"] == metadata["source"]
    assert snapshot["scope"] == metadata["scope"]
    assert snapshot["origin"] == {"kind": "CSV_EXPORT", "original_csv_sha256": hashlib.sha256(original).hexdigest()}
    assert metadata == before and csv_path.read_bytes() == original
    assert [{key: row[key] for key in BAR_FIELDS} for row in snapshot["bars"]] == [
        {"start": "2025-03-03T14:30:00+00:00", "end": "2025-03-03T14:35:00+00:00",
         "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10},
        {"start": "2025-03-03T14:35:00+00:00", "end": "2025-03-03T14:40:00+00:00",
         "open": 101, "high": 103, "low": 100, "close": 102, "volume": 0},
    ]
    assert comparison.compare_snapshots(snapshot, snapshot)["status"] == "MATCH"


@pytest.mark.parametrize("refusal", ["target_link", "parent_link", "parent_file"])
def test_actual_cli_reports_publication_path_refusals_as_json(tmp_path, capsys, refusal):
    snapshot = snapshot_from_csv(_csv(tmp_path / "bars.csv"), _metadata())
    source = _json_file(tmp_path / "input.json", snapshot)
    original = source.read_bytes()
    parent = tmp_path / "destination"
    output = tmp_path / "report.json"
    try:
        if refusal == "target_link":
            output.symlink_to(source)
        elif refusal == "parent_link":
            parent.mkdir()
            link = tmp_path / "directory-link"
            link.symlink_to(parent, target_is_directory=True)
            output = link / "report.json"
        else:
            parent.write_text("existing non-directory", encoding="utf-8")
            output = parent / "report.json"
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation privilege is unavailable")
        raise

    result = _run(capsys, tmp_path, ["market-data-compare", "--left", str(source),
        "--right", str(source), "--output", str(output)], expected=1)

    assert "publication" in result["error"]
    assert "published" not in result
    assert source.read_bytes() == original
    if refusal == "target_link":
        assert output.is_symlink() and output.readlink() == source
    elif refusal == "parent_link":
        assert output.parent.is_symlink() and not list(parent.iterdir())
    else:
        assert parent.read_text(encoding="utf-8") == "existing non-directory"


def test_csv_keeps_duplicates_bad_numbers_and_naive_timestamps_serializable(tmp_path):
    first = ("2025-03-03T14:30:00+00:00", "2025-03-03T14:35:00+00:00", "100", "102", "99", "101", "10")
    csv_path = _csv(tmp_path / "bad-rows.csv", [
        first,
        first,
        ("2025-03-03T14:35:00", "2025-03-03T14:40:00+00:00", "not-a-price", "103", "100", "102", "0"),
        ("2025-03-03T14:40:00+00:00", "2025-03-03T14:45:00+00:00", "102", "104", "101", "103", "NaN"),
        first[:2],
        (*first, "unexpected"),
    ])
    original = csv_path.read_bytes()
    snapshot = snapshot_from_csv(csv_path, _metadata(count=3))
    rows = snapshot["bars"]

    assert len(rows) == 6
    assert {key: rows[0][key] for key in BAR_FIELDS} == {key: rows[1][key] for key in BAR_FIELDS}
    assert rows[2]["start"] == "2025-03-03T14:35:00"
    assert rows[2]["open"] == "not-a-price"
    assert rows[3]["volume"] == "NaN"
    assert rows[4]["open"] is None and rows[4]["volume"] is None
    assert rows[5]["csv_extra_fields"] == ["unexpected"]
    saved = tmp_path / "bad-rows.json"
    comparison.write_market_data_json(saved, snapshot)
    assert _strict_json(saved.read_bytes())["bars"] == rows
    report = comparison.compare_snapshots(snapshot, snapshot)
    assert report["status"] == "INVALID_INPUT"
    assert report["expected_slots"] == 3
    assert report["market_accuracy_certified"] is False
    assert csv_path.read_bytes() == original


@pytest.mark.parametrize("header", [
    ("timestamp", "end", "open", "high", "low", "close", "volume"),
    (*BAR_FIELDS, "extra"),
    ("start", "start", "open", "high", "low", "close", "volume"),
])
def test_csv_requires_the_fixed_unambiguous_header(tmp_path, header):
    csv_path = _csv(tmp_path / "wrong-header.csv", header=header)
    with pytest.raises(ValueError, match="(?i)header|columns"):
        snapshot_from_csv(csv_path, _metadata())


@pytest.mark.parametrize("mutation", ["missing_capture", "extra_metadata"])
def test_csv_export_requires_explicit_source_capture_and_exact_metadata(tmp_path, mutation):
    metadata = _metadata()
    if mutation == "missing_capture":
        del metadata["source"]["captured_at"]
    else:
        metadata["guessed_timezone"] = "America/New_York"
    with pytest.raises(ValueError):
        snapshot_from_csv(_csv(tmp_path / "bars.csv"), metadata)


def test_actual_csv_export_and_compare_cli_are_stable_exclusive_and_settings_free(tmp_path, capsys):
    left_csv = _csv(tmp_path / "left.csv")
    right_csv = _csv(tmp_path / "right.csv", [
        ("2025-03-03T14:30:00+00:00", "2025-03-03T14:35:00+00:00", "100.25", "102", "99", "101", "10"),
        ("2025-03-03T14:35:00+00:00", "2025-03-03T14:40:00+00:00", "101", "103", "100", "102", "0"),
    ])
    left_meta = _json_file(tmp_path / "left-metadata.json", _metadata(provider="离线供方甲"))
    right_meta = _json_file(tmp_path / "right-metadata.json", _metadata(provider="离线供方乙"))
    original = {path: path.read_bytes() for path in (left_csv, right_csv, left_meta, right_meta)}
    left, left_again, right = (tmp_path / name for name in ("left.json", "left-again.json", "right.json"))
    for csv_path, metadata_path, output in (
        (left_csv, left_meta, left), (left_csv, left_meta, left_again), (right_csv, right_meta, right),
    ):
        result = _run(capsys, tmp_path, ["market-data-snapshot-from-csv", "--csv", str(csv_path),
            "--metadata", str(metadata_path), "--output", str(output)])
        assert result["status"] == "SUCCESS"
        assert _strict_json(output.read_bytes())["schema_version"] == SNAPSHOT_VERSION
    assert left.read_bytes() == left_again.read_bytes()
    original.update({path: path.read_bytes() for path in (left, right)})

    reports = [tmp_path / "comparison.json", tmp_path / "comparison-again.json"]
    for output in reports:
        result = _run(capsys, tmp_path, ["market-data-compare", "--left", str(left), "--right", str(right),
            "--output", str(output)])
        assert result["status"] == "SUCCESS"
        report = _strict_json(output.read_bytes())
        # Successful report publication is distinct from matching market values.
        assert report["status"] == "DIFFERENT"
        assert report["expected_slots"] == 2
        assert report["counts"]["matched"] == report["counts"]["different"] == 1
        assert report["independence"]["status"] == "SYNTHETIC"
        assert report["market_accuracy_certified"] is False
    assert reports[0].read_bytes() == reports[1].read_bytes()
    original[reports[0]] = reports[0].read_bytes()

    _run(capsys, tmp_path, ["market-data-snapshot-from-csv", "--csv", str(left_csv),
        "--metadata", str(left_meta), "--output", str(left)], expected=1)
    _run(capsys, tmp_path, ["market-data-compare", "--left", str(left), "--right", str(right),
        "--output", str(reports[0])], expected=1)
    assert all(path.read_bytes() == content for path, content in original.items())


@pytest.mark.parametrize("day,interval,count", [
    ("2025-03-03", "5m", 78),
    ("2025-11-28", "30m", 7),
])
def test_canonical_export_reads_complete_ts2_window_and_preserves_identity(tmp_path, day, interval, count):
    bars = [cd.bar(day, slot=i, interval=interval, open=100 + i / 100, close=100.005 + i / 100)
            for i in range(count)]
    built = cd.build(tmp_path, bars, interval=interval, dates=[date.fromisoformat(day)])
    metadata = _metadata(day=day, interval=interval, count=count)
    before = deepcopy(metadata)
    snapshot = snapshot_from_canonical(built.build_path, metadata)

    assert snapshot["source"] == metadata["source"]
    assert snapshot["scope"] == metadata["scope"]
    assert metadata == before
    assert snapshot["source"]["data_kind"] == "SYNTHETIC"
    assert snapshot["source"]["captured_at"] != _utc(cd.ARCHIVE)
    assert snapshot["origin"]["kind"] == "CANONICAL_EXPORT"
    assert snapshot["origin"]["canonical_build_id"] == built.canonical_build_id
    assert snapshot["origin"]["canonical_content_id"] == built.canonical_content_id
    assert len(snapshot["bars"]) == count
    assert snapshot["bars"][0]["start"] == metadata["scope"]["window_start"]
    assert snapshot["bars"][-1]["end"] == metadata["scope"]["window_end"]
    for exported, bar in zip(snapshot["bars"], built.bars, strict=True):
        assert exported["start"] == _utc(bar.event_time)
        assert exported["end"] == _utc(bar.event_time + timedelta(minutes=int(interval[:-1])))
        assert all(exported[field] == getattr(bar, field) for field in BAR_FIELDS[2:])
        origin = exported["origin"]
        assert origin["canonical_bar_key"] == bar.canonical_bar_key
        assert origin["canonical_row_version_id"] == bar.canonical_row_version_id
        assert origin["ingestion_run_id"] == bar.ingestion_run_id
        assert origin["physical_snapshot_hash"] == bar.physical_snapshot_hash
        assert origin["logical_source_rows_hash"] == bar.logical_source_rows_hash
        assert origin["source_schema_version"] == bar.source_schema_version
        assert origin["snapshot_file"] == bar.snapshot_file
        assert origin["market_available_at"] == _utc(bar.market_available_at)
        assert origin["archive_available_at"] == _utc(bar.archive_available_at)
    report = comparison.compare_snapshots(snapshot, snapshot)
    assert report["status"] == "MATCH"
    assert report["independence"]["status"] == "SYNTHETIC"
    assert report["market_accuracy_certified"] is False


def test_canonical_cli_uses_explicit_build_and_rechecks_its_disk_state(tmp_path, capsys):
    older = cd.build(tmp_path, [cd.bar(slot=0, open=100.0, source="a")])
    newer = cd.build(tmp_path, [cd.bar(slot=0, open=101.0, source="b")])
    assert older.build_path != newer.build_path
    metadata = _metadata(count=1)
    metadata_path = _json_file(tmp_path / "metadata.json", metadata)
    before = {path: path.read_bytes() for path in (metadata_path, older.build_path / "manifest.json")}
    output = tmp_path / "canonical-export.json"
    result = _run(capsys, tmp_path, ["market-data-snapshot-from-canonical", "--build", str(older.build_path),
        "--metadata", str(metadata_path), "--output", str(output)])
    assert result["status"] == "SUCCESS"
    snapshot = _strict_json(output.read_bytes())
    assert snapshot["origin"]["canonical_build_id"] == older.canonical_build_id
    assert snapshot["bars"][0]["open"] == 100
    assert snapshot["source"]["captured_at"] == metadata["source"]["captured_at"]

    # A previously verified Python object cannot substitute for current disk proof.
    (older.build_path / "_SUCCESS").unlink()
    failed_output = tmp_path / "must-not-exist.json"
    failure = _run(capsys, tmp_path, ["market-data-snapshot-from-canonical", "--build", str(older.build_path),
        "--metadata", str(metadata_path), "--output", str(failed_output)], expected=1)
    assert "_SUCCESS" in failure["error"]
    assert not failed_output.exists()
    assert all(path.read_bytes() == content for path, content in before.items())


def test_canonical_export_never_infers_missing_capture_from_archive(tmp_path):
    built = cd.build(tmp_path, [cd.bar(slot=0)])
    metadata = _metadata(count=1)
    del metadata["source"]["captured_at"]
    with pytest.raises(ValueError):
        snapshot_from_canonical(built.build_path, metadata)


@pytest.mark.parametrize("day,schema,message", [
    ("2025-03-03", "10.9", "10.9-mv-ts2|TS2|ts2|schema"),
    ("2025-07-03", "10.9-mv-ts2", "PROVIDER_UNVERIFIED"),
])
def test_reader_validity_does_not_prove_export_timestamp_qualification(tmp_path, day, schema, message):
    built = cd.build(tmp_path, [cd.bar(day, slot=0, schema=schema)], schema=schema)
    assert load_verified_canonical_build(built.build_path).normalized_request.source_schema_version == schema
    with pytest.raises(ValueError, match=message):
        snapshot_from_canonical(built.build_path, _metadata(day=day, count=1))


def test_cli_keeps_committed_atomic_publication_outcome_in_error_json(tmp_path, capsys, monkeypatch):
    csv_path = _csv(tmp_path / "bars.csv")
    metadata_path = _json_file(tmp_path / "metadata.json", _metadata())
    output = tmp_path / "snapshot.json"

    def fail_publication(path, serialize):
        raise AtomicFilePublicationError("injected boundary failure", path=path,
            temporary_path=tmp_path / "owned-temporary.tmp", published=True)

    monkeypatch.setattr(atomic_file, "_write_file_no_replace", fail_publication)
    failure = _run(capsys, tmp_path, ["market-data-snapshot-from-csv", "--csv", str(csv_path),
        "--metadata", str(metadata_path), "--output", str(output)], expected=1)
    assert failure["published"] is True
