"""Closed in-memory schemas. Parsing proves shape, not source or signer authority."""

import re
from datetime import date, datetime
from types import MappingProxyType

from ._canonical import _decode_base64, _parse_canonical_json
from ._errors import _ScheduleArtifactError, _require
from ._models import _ParsedDocument, _freeze


def _shape(condition, name):
    _require(condition, "INTEGRITY_MISMATCH", "invalid schema value: " + name)


def _date(value, name="date"):
    _shape(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value), name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise _ScheduleArtifactError("INTEGRITY_MISMATCH", name) from exc
    _shape(parsed.isoformat() == value, name)
    return parsed


def _instant(value, name="instant"):
    _shape(type(value) is str and re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00",
        value), name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _ScheduleArtifactError("INTEGRITY_MISMATCH", name) from exc
    _shape(parsed.isoformat(timespec="microseconds") == value, name)
    return parsed


def _digest(value, name="digest"):
    _shape(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), name)


def _text(value, name):
    # Canonical parsing has already enforced NFC, UTF-8 and structured-text safety.
    _shape(type(value) is str and bool(value), name)


def _integer(value, name):
    _shape(type(value) is int and value >= 0, name)


def _literal(expected):
    def validate(value, name):
        _shape(type(value) is type(expected) and value == expected, name)
    return validate


def _enum(*allowed):
    def validate(value, name):
        _shape(type(value) is str and value in allowed, name)
    return validate


def _nullable(validator):
    def validate(value, name):
        if value is not None:
            validator(value, name)
    return validate


def _array(validator):
    def validate(value, name):
        _shape(type(value) is list, name)
        for index, item in enumerate(value):
            validator(item, name + "[" + str(index) + "]")
    return validate


def _record(**fields):
    def validate(value, name):
        _shape(type(value) is dict and value.keys() == fields.keys(), name)
        for field, validator in fields.items():
            validator(value[field], name + "." + field)
    return validate


def _base64(value, name):
    try:
        return _decode_base64(value)
    except (TypeError, ValueError) as exc:
        raise _ScheduleArtifactError("INTEGRITY_MISMATCH", name) from exc


def _signature(value, name):
    _shape(len(_base64(value, name)) == 64, name)


_SCOPE = dict(
    market=_literal("US"), requested_session=_literal("RTH"),
    market_timezone=_literal("America/New_York"),
    coverage_start_date=_date, coverage_end_date=_date,
)
_SOURCE_FIELDS = dict(
    provider_id=_text, source_id=_text, source_contract_id=_text,
    source_contract_version=_text, source_schema_version=_text,
    api_contract_version=_text, origin_locator=_text,
    requested_market=_literal("US"), requested_start_date=_date,
    requested_end_date=_date, requested_code=_literal(None),
    payload_format=_literal("WIRE_BYTES"),
    request_content_hash=_digest, response_content_hash=_digest, acquired_at=_instant,
)
_CUSTODY = _record(
    body=_record(
        receipt_version=_literal("l4-source-custody-receipt-v1"),
        custody_authority_id=_text, key_id=_text,
        signature_algorithm=_literal("Ed25519"), **_SOURCE_FIELDS,
    ),
    signature_base64=_signature,
)
_SOURCE = _record(
    schema_version=_literal("l4-trading-day-source-snapshot-v1"),
    source_snapshot_id=_digest, source_content_hash=_digest,
    content=_record(
        **_SCOPE,
        records=_array(_record(
            source_record_id=_digest,
            evidence=_record(
                **_SOURCE_FIELDS, request_bytes_base64=_base64,
                response_bytes_base64=_base64, custody_receipt=_CUSTODY,
            ),
        )),
    ),
)
_CLAIM = _record(source_record_id=_digest, claim_index=_integer)
_DAILY = dict(
    market_calendar_date=_date, day_status=_enum("TRADING", "CLOSED"),
    session_open=_nullable(_instant), session_close=_nullable(_instant),
    session_profile=_nullable(_enum("NORMAL", "QUALIFIED_EARLY_CLOSE")),
)
_COVERAGE = _record(
    schema_version=_literal("l4-trading-day-coverage-evidence-v1"),
    coverage_completion_evidence_id=_digest,
    content=_record(
        **_SCOPE, source_snapshot_id=_digest,
        completion_rule_version=_literal("l4-explicit-civil-date-completion-v1"),
        calendar_contract_version=_literal("cross-day-us-rth-calendar-contract-v1"),
        closure_finalized_through=_date, closure_knowledge_cutoff=_instant,
        completeness_claims=_array(_CLAIM),
        daily_evidence=_array(_record(
            **_DAILY,
            basis=_enum("REGULAR_SESSION", "QUALIFIED_EARLY_CLOSE", "WEEKEND",
                        "SCHEDULED_HOLIDAY", "TEMPORARY_CLOSURE"),
            status_claims=_array(_CLAIM), closure_claims=_array(_CLAIM),
            geometry_claims=_array(_CLAIM),
        )),
    ),
)
_VERIFICATION = _record(
    body=_record(
        receipt_version=_literal("l4-schedule-verification-receipt-v1"),
        verification_authority_id=_text, verifier_contract_version=_text,
        key_id=_text, signature_algorithm=_literal("Ed25519"),
        source_snapshot_id=_digest, source_content_hash=_digest,
        coverage_completion_evidence_id=_digest,
        schedule_declaration_hash_without_archive=_digest,
        source_validation_times=_array(_record(source_record_id=_digest, verified_at=_instant)),
        coverage_verified_at=_instant, geometry_verified_at=_instant,
        logical_schedule_verified_at=_instant, complete_verified_at=_instant,
    ),
    signature_base64=_signature,
)
_SCHEDULE = _record(
    schedule_schema_version=_literal("trading-day-schedule-v1"), **_SCOPE,
    daily_records=_array(_record(**_DAILY)),
    source_snapshot_id=_digest, source_content_hash=_digest,
    calendar_contract_version=_literal("cross-day-us-rth-calendar-contract-v1"),
    normalization_version=_literal("trading-day-schedule-normalization-v1"),
    coverage_completion_evidence_id=_digest, coverage_complete=_literal(True),
    archive_available_at=_instant,
)
_OUTPUT_ROLES = (
    ("coverage_evidence.json", "COVERAGE_EVIDENCE"),
    ("schedule.json", "SCHEDULE"),
    ("source_snapshot.json", "SOURCE_SNAPSHOT"),
    ("verification_receipt.json", "VERIFICATION_RECEIPT"),
)
_MANIFEST = _record(
    schedule_artifact_id=_digest,
    content=_record(
        manifest_schema_version=_literal("trading-day-schedule-manifest-v1"),
        artifact_schema_version=_literal("trading-day-schedule-artifact-v1"),
        serialization_version=_literal("trading-day-schedule-json-v1"),
        reader_contract_version=_literal("trading-day-schedule-artifact-reader-v1"),
        schedule_content_id=_digest, schedule_pin_id=_digest,
        source_snapshot_id=_digest, source_content_hash=_digest,
        coverage_completion_evidence_id=_digest, **_SCOPE,
        archive_available_at=_instant, daily_record_count=_integer,
        output_files=_array(_record(
            path=_enum(*(name for name, _ in _OUTPUT_ROLES)),
            role=_enum(*(role for _, role in _OUTPUT_ROLES)),
            byte_size=_integer, sha256=_digest,
        )),
    ),
)
_SCHEMAS = MappingProxyType({
    "source_snapshot.json": _SOURCE, "coverage_evidence.json": _COVERAGE,
    "verification_receipt.json": _VERIFICATION, "schedule.json": _SCHEDULE,
    "manifest.json": _MANIFEST,
})


def _parse_document(name, data):
    """Parse one fixed document role, not a filesystem path or trust credential."""
    _shape(type(name) is str and name in _SCHEMAS, "document role")
    try:
        value = _parse_canonical_json(data)
    except (TypeError, ValueError, RecursionError) as exc:
        raise _ScheduleArtifactError("NONCANONICAL_BYTES", name) from exc
    _SCHEMAS[name](value, name)
    return _ParsedDocument(name, data, _freeze(value))
