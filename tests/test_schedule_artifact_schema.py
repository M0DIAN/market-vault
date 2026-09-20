"""Closed schema regressions with synthetic, explicitly unauthenticated receipts."""

import base64
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
import hashlib
import json
from zoneinfo import ZoneInfo

import pytest

from market_vault.cross_day.identity import schedule_pin_id
from market_vault.cross_day.schedule import TradingDayRecord, verify_trading_day_schedule
from market_vault.dataset.encoding import encode_identity
from market_vault.schedule_artifact._errors import _ScheduleArtifactError
from market_vault.schedule_artifact._models import _thaw
from market_vault.schedule_artifact._schema import _date, _digest, _instant, _parse_document
from market_vault.schedule_artifact._semantics import _validate_artifact_structure


def _c(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _h(domain, value):
    return encode_identity(domain, {"canonical_payload_sha256": _sha(_c(value))})


def _b64(raw):
    return base64.b64encode(raw).decode("ascii")


def _stamp(hour, minute=0):
    return f"2025-12-01T{hour:02}:{minute:02}:00.000000+00:00"


def _seal_source(source):
    for record in source["content"]["records"]:
        record["source_record_id"] = _h("l4-trading-day-source-record-v1", record["evidence"])
    source["content"]["records"].sort(key=lambda item: item["source_record_id"])
    source["source_content_hash"] = _sha(_c(source["content"]))
    source["source_snapshot_id"] = _h("l4-trading-day-source-snapshot-v1", {
        "schema_version": source["schema_version"],
        "source_content_hash": source["source_content_hash"],
    })


def _bundle(start="2025-11-28", count=3):
    """Independent fixture encoder; no new schema/semantic/hash helpers build expectations."""
    first = date.fromisoformat(start)
    end = (first + timedelta(days=count - 1)).isoformat()
    scope = dict(market="US", requested_session="RTH", market_timezone="America/New_York",
                 coverage_start_date=start, coverage_end_date=end)
    records = []
    for index in range(2):
        common = dict(
            provider_id="fixture-provider", source_id="source-" + str(index),
            source_contract_id="fixture-contract", source_contract_version="v1",
            source_schema_version="v1", api_contract_version="v1",
            origin_locator="https://fixture.invalid/calendar",
            requested_market="US", requested_start_date=start, requested_end_date=end,
            requested_code=None, payload_format="WIRE_BYTES",
            request_content_hash=_sha(b"request"), response_content_hash=_sha(b"response"),
            acquired_at=_stamp(10, index),
        )
        body = dict(receipt_version="l4-source-custody-receipt-v1",
                    custody_authority_id="UNQUALIFIED", key_id="UNQUALIFIED",
                    signature_algorithm="Ed25519", **common)
        evidence = dict(
            **common, request_bytes_base64=_b64(b"request"), response_bytes_base64=_b64(b"response"),
            custody_receipt=dict(body=body, signature_base64=_b64(bytes(64))),
        )
        records.append(dict(source_record_id="0" * 64, evidence=evidence))
    source = dict(schema_version="l4-trading-day-source-snapshot-v1",
                  source_snapshot_id="0" * 64, source_content_hash="0" * 64,
                  content=dict(**scope, records=records))
    _seal_source(source)
    claims = [dict(source_record_id=record["source_record_id"], claim_index=0)
              for record in source["content"]["records"]]
    days = []
    for offset in range(count):
        day = first + timedelta(days=offset)
        early = day.isoformat() in ("2025-11-28", "2025-12-24")
        opened = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        closed = opened.replace(hour=13 if early else 16, minute=0)
        # Fixture conversion only; production uses the unchanged logical geometry validator.
        utc = ZoneInfo("UTC")
        trading = offset == 0
        days.append(dict(
            market_calendar_date=day.isoformat(), day_status="TRADING" if trading else "CLOSED",
            basis=("QUALIFIED_EARLY_CLOSE" if early else "REGULAR_SESSION") if trading else "WEEKEND",
            session_open=opened.astimezone(utc).isoformat(timespec="microseconds") if trading else None,
            session_close=closed.astimezone(utc).isoformat(timespec="microseconds") if trading else None,
            session_profile=("QUALIFIED_EARLY_CLOSE" if early else "NORMAL") if trading else None,
            status_claims=deepcopy(claims), closure_claims=deepcopy(claims),
            geometry_claims=deepcopy(claims) if trading else [],
        ))
    coverage_content = dict(
        **scope, source_snapshot_id=source["source_snapshot_id"],
        completion_rule_version="l4-explicit-civil-date-completion-v1",
        calendar_contract_version="cross-day-us-rth-calendar-contract-v1",
        closure_finalized_through=end, closure_knowledge_cutoff=_stamp(9),
        completeness_claims=claims, daily_evidence=days,
    )
    coverage = dict(schema_version="l4-trading-day-coverage-evidence-v1",
                    coverage_completion_evidence_id=_h(
                        "l4-trading-day-coverage-completion-v1", coverage_content),
                    content=coverage_content)
    evidence_ids = dict(source_snapshot_id=source["source_snapshot_id"],
                        source_content_hash=source["source_content_hash"],
                        coverage_completion_evidence_id=coverage["coverage_completion_evidence_id"])
    schedule = dict(
        schedule_schema_version="trading-day-schedule-v1", **scope,
        daily_records=[{key: day[key] for key in (
            "market_calendar_date", "day_status", "session_open", "session_close", "session_profile",
        )} for day in days],
        **evidence_ids, calendar_contract_version="cross-day-us-rth-calendar-contract-v1",
        normalization_version="trading-day-schedule-normalization-v1", coverage_complete=True,
        archive_available_at=_stamp(15),
    )
    declaration = {key: value for key, value in schedule.items() if key != "archive_available_at"}
    receipt = dict(
        body=dict(
            receipt_version="l4-schedule-verification-receipt-v1",
            verification_authority_id="UNQUALIFIED", verifier_contract_version="v1",
            key_id="UNQUALIFIED", signature_algorithm="Ed25519", **evidence_ids,
            schedule_declaration_hash_without_archive=_sha(_c(declaration)),
            source_validation_times=[dict(source_record_id=record["source_record_id"],
                                          verified_at=_stamp(11, index))
                                     for index, record in enumerate(source["content"]["records"])],
            coverage_verified_at=_stamp(12), geometry_verified_at=_stamp(13),
            logical_schedule_verified_at=_stamp(14), complete_verified_at=_stamp(15),
        ),
        signature_base64=_b64(bytes(64)),
    )
    logical_fields = dict(schedule)
    logical_fields.update(
        coverage_start_date=first, coverage_end_date=date.fromisoformat(end),
        archive_available_at=datetime.fromisoformat(schedule["archive_available_at"]),
        daily_records=tuple(TradingDayRecord(
            date.fromisoformat(day["market_calendar_date"]), day["day_status"],
            datetime.fromisoformat(day["session_open"]) if day["session_open"] else None,
            datetime.fromisoformat(day["session_close"]) if day["session_close"] else None,
            day["session_profile"],
        ) for day in schedule["daily_records"]),
    )
    logical = verify_trading_day_schedule(**logical_fields)
    bundle = {"source_snapshot.json": source, "coverage_evidence.json": coverage,
              "verification_receipt.json": receipt, "schedule.json": schedule}
    manifest_content = dict(
        manifest_schema_version="trading-day-schedule-manifest-v1",
        artifact_schema_version="trading-day-schedule-artifact-v1",
        serialization_version="trading-day-schedule-json-v1",
        reader_contract_version="trading-day-schedule-artifact-reader-v1",
        schedule_content_id=logical.schedule_content_id, schedule_pin_id=schedule_pin_id(logical.pin),
        **evidence_ids, **scope, archive_available_at=schedule["archive_available_at"],
        daily_record_count=count, output_files=[
            dict(path=name, role=role, byte_size=len(_c(bundle[name])), sha256=_sha(_c(bundle[name])))
            for name, role in (
                ("coverage_evidence.json", "COVERAGE_EVIDENCE"), ("schedule.json", "SCHEDULE"),
                ("source_snapshot.json", "SOURCE_SNAPSHOT"),
                ("verification_receipt.json", "VERIFICATION_RECEIPT"),
            )
        ],
    )
    bundle["manifest.json"] = dict(
        schedule_artifact_id=_h("l4-trading-day-schedule-artifact-v1", manifest_content),
        content=manifest_content,
    )
    return bundle


def _validate(bundle):
    return _validate_artifact_structure(
        source_snapshot_bytes=_c(bundle["source_snapshot.json"]),
        coverage_evidence_bytes=_c(bundle["coverage_evidence.json"]),
        verification_receipt_bytes=_c(bundle["verification_receipt.json"]),
        schedule_bytes=_c(bundle["schedule.json"]), manifest_bytes=_c(bundle["manifest.json"]),
    )


def _at(root, keys):
    for key in keys:
        root = root[key]
    return root


def _nodes(value, prefix=()):
    if isinstance(value, dict):
        yield prefix, value
        for key, item in value.items():
            yield from _nodes(item, prefix + (key,))
    elif isinstance(value, list):
        # One representative of each nested record schema suffices for exhaustive field checks.
        if value:
            yield from _nodes(value[0], prefix + (0,))


_FIXTURE = _bundle()
_OBJECTS = [(name, keys) for name, value in _FIXTURE.items() for keys, _ in _nodes(value)]
_FIELDS = [(name, keys, field) for name, value in _FIXTURE.items()
           for keys, obj in _nodes(value) for field in obj]


@pytest.mark.parametrize("name", tuple(_FIXTURE))
def test_each_closed_document_parses_into_deeply_immutable_detached_model(name):
    value = deepcopy(_FIXTURE[name])
    raw = _c(value)
    parsed = _parse_document(name, raw)
    assert parsed.canonical_bytes == raw and _thaw(parsed.value) == value
    with pytest.raises(TypeError):
        parsed.value["unknown"] = 1
    with pytest.raises(FrozenInstanceError):
        parsed.name = "other"
    nested = (parsed.value["daily_records"][0] if name == "schedule.json"
              else next(item for item in parsed.value.values() if type(item) is type(parsed.value)))
    with pytest.raises(TypeError):
        nested["unknown"] = 1
    value.clear()
    detached_copy = _thaw(parsed.value)
    detached_copy.clear()
    assert _thaw(parsed.value) == _FIXTURE[name]


@pytest.mark.parametrize("name,keys", _OBJECTS)
@pytest.mark.parametrize("fault", ["unknown", "wrong_type"])
def test_every_object_level_rejects_extra_keys_and_non_object_types(name, keys, fault):
    value = deepcopy(_FIXTURE[name])
    if fault == "unknown":
        _at(value, keys)["unknown"] = None
    elif not keys:
        value = []
    else:
        _at(value, keys[:-1])[keys[-1]] = []
    with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
        _parse_document(name, _c(value))


@pytest.mark.parametrize("name,keys,field", _FIELDS)
def test_every_required_field_at_every_object_level_rejects_omission(name, keys, field):
    value = deepcopy(_FIXTURE[name])
    del _at(value, keys)[field]
    with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
        _parse_document(name, _c(value))


@pytest.mark.parametrize("text", ["2025-1-01", "2025-01-1", "2025-02-29", "0000-01-01",
                                 "2025-01-01Z", "2025-01-01T00:00:00", "20250101", None, True])
def test_date_rejects_noncanonical_or_invalid_civil_text(text):
    with pytest.raises(_ScheduleArtifactError):
        _date(text)


@pytest.mark.parametrize("text", [
    "2025-01-01T00:00:00.000000Z", "2025-01-01T00:00:00.000000-00:00",
    "2025-01-01T01:00:00.000000+01:00", "2025-01-01T00:00:00",
    "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00.00000+00:00",
    "2025-01-01T00:00:00.0000000+00:00", "2025-01-01 00:00:00.000000+00:00",
    "2025-02-29T00:00:00.000000+00:00", "2025-01-01T24:00:00.000000+00:00", 0,
])
def test_instant_rejects_equivalent_spelling_non_utc_and_invalid_dates(text):
    with pytest.raises(_ScheduleArtifactError):
        _instant(text)


@pytest.mark.parametrize("text", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, 0, True, None])
def test_digest_requires_exact_lowercase_64_hex(text):
    with pytest.raises(_ScheduleArtifactError):
        _digest(text)


def test_scalar_roundtrips_include_leap_date_and_year_one():
    assert _date("2024-02-29").isoformat() == "2024-02-29"
    assert _date("0001-01-01").isoformat() == "0001-01-01"
    assert _instant("0001-01-01T00:00:00.000000+00:00").year == 1


@pytest.mark.parametrize("name", tuple(_FIXTURE))
@pytest.mark.parametrize("mutation", [
    lambda raw: b"\xef\xbb\xbf" + raw, lambda raw: b" " + raw,
    lambda raw: raw[:-1], lambda raw: raw + b"\n", lambda raw: raw + b"\xff",
    lambda raw: b'{"duplicate":0,"duplicate":1}\n', lambda raw: bytearray(raw),
])
def test_document_parser_never_bypasses_canonical_parser(name, mutation):
    with pytest.raises(_ScheduleArtifactError, match="NONCANONICAL_BYTES"):
        _parse_document(name, mutation(_c(_FIXTURE[name])))


@pytest.mark.parametrize("name,keys,bad", [
    ("source_snapshot.json", ("schema_version",), "v2"),
    ("source_snapshot.json", ("content", "market"), "HK"),
    ("source_snapshot.json", ("content", "requested_session"), "ALL"),
    ("source_snapshot.json", ("content", "market_timezone"), "UTC"),
    ("source_snapshot.json", ("content", "records"), {}),
    ("source_snapshot.json", ("content", "records", 0, "evidence", "provider_id"), ""),
    ("source_snapshot.json", ("content", "records", 0, "evidence", "requested_market"), "HK"),
    ("source_snapshot.json", ("content", "records", 0, "evidence", "requested_code"), "AAPL"),
    ("source_snapshot.json", ("content", "records", 0, "evidence", "payload_format"), "DATAFRAME"),
    ("coverage_evidence.json", ("schema_version",), "v2"),
    ("coverage_evidence.json", ("content", "completion_rule_version"), "v2"),
    ("coverage_evidence.json", ("content", "calendar_contract_version"), "v2"),
    ("coverage_evidence.json", ("content", "daily_evidence", 0, "day_status"), "UNKNOWN"),
    ("coverage_evidence.json", ("content", "daily_evidence", 0, "basis"), "PROVIDER_ENUM"),
    ("coverage_evidence.json", ("content", "daily_evidence", 0, "session_profile"), "EXTENDED"),
    ("coverage_evidence.json", ("content", "completeness_claims", 0, "claim_index"), True),
    ("coverage_evidence.json", ("content", "completeness_claims", 0, "claim_index"), -1),
    ("coverage_evidence.json", ("content", "completeness_claims"), {}),
    ("verification_receipt.json", ("body", "receipt_version"), "v2"),
    ("verification_receipt.json", ("body", "signature_algorithm"), "RSA"),
    ("verification_receipt.json", ("body", "source_validation_times"), {}),
    ("schedule.json", ("schedule_schema_version",), "v2"),
    ("schedule.json", ("normalization_version",), "v2"),
    ("schedule.json", ("calendar_contract_version",), "v2"),
    ("schedule.json", ("coverage_complete",), 1),
    ("schedule.json", ("coverage_complete",), False),
    ("schedule.json", ("daily_records",), {}),
    ("manifest.json", ("content", "manifest_schema_version"), "v2"),
    ("manifest.json", ("content", "artifact_schema_version"), "v2"),
    ("manifest.json", ("content", "serialization_version"), "v2"),
    ("manifest.json", ("content", "reader_contract_version"), "v2"),
    ("manifest.json", ("content", "daily_record_count"), True),
    ("manifest.json", ("content", "output_files", 0, "byte_size"), True),
    ("manifest.json", ("content", "output_files", 0, "byte_size"), -1),
    ("manifest.json", ("content", "output_files", 0, "path"), "manifest.json"),
    ("manifest.json", ("content", "output_files", 0, "path"), "_SUCCESS"),
    ("manifest.json", ("content", "output_files", 0, "path"), "../schedule.json"),
    ("manifest.json", ("content", "output_files", 0, "role"), "UNKNOWN"),
])
def test_nested_types_literals_scope_and_bool_int_are_strict(name, keys, bad):
    value = deepcopy(_FIXTURE[name])
    _at(value, keys[:-1])[keys[-1]] = bad
    with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
        _parse_document(name, _c(value))


@pytest.mark.parametrize("custody", [False, True])
@pytest.mark.parametrize("signature", [_b64(bytes(63)), _b64(bytes(65)), "AA", "AA==\n", "_/8="])
def test_receipt_signature_shape_is_strict_but_not_authenticated(custody, signature):
    name = "source_snapshot.json" if custody else "verification_receipt.json"
    value = deepcopy(_FIXTURE[name])
    receipt = value["content"]["records"][0]["evidence"]["custody_receipt"] if custody else value
    receipt["signature_base64"] = signature
    with pytest.raises(_ScheduleArtifactError):
        _parse_document(name, _c(value))
