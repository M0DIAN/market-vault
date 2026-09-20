"""Pure consistency checks only; no source parsing, signature authentication or admission."""

from ..cross_day.identity import schedule_pin_id
from ..cross_day.schedule import TradingDayRecord, verify_trading_day_schedule
from ._canonical import _canonical_json, _decode_base64
from ._errors import _ScheduleArtifactError, _require
from ._identity import _identity, _sha256
from ._models import _MAX_CIVIL_DATES, _MAX_SOURCE_RECORDS, _SemanticFacts, _thaw
from ._schema import _OUTPUT_ROLES, _date, _instant, _parse_document


_SCOPE_FIELDS = (
    "market", "requested_session", "market_timezone",
    "coverage_start_date", "coverage_end_date",
)
_DAILY_FIELDS = (
    "market_calendar_date", "day_status", "session_open", "session_close", "session_profile",
)
_EVIDENCE_IDS = (
    "source_snapshot_id", "source_content_hash", "coverage_completion_evidence_id",
)
# Reacquisition time, response and custody signer never choose a winning acquisition.
_ACQUISITION_BOUNDARY = (
    "provider_id", "source_id", "source_contract_id", "source_contract_version",
    "source_schema_version", "api_contract_version", "origin_locator",
    "requested_market", "requested_start_date", "requested_end_date", "requested_code",
    "payload_format",
)


def _same_fields(actual, expected, fields, reason):
    for field in fields:
        _require(actual[field] == expected[field], reason, "mismatched " + field)


def _range(content):
    start = _date(content["coverage_start_date"])
    end = _date(content["coverage_end_date"])
    count = end.toordinal() - start.toordinal() + 1
    _require(1 <= count <= _MAX_CIVIL_DATES, "COVERAGE_INCOMPLETE", "invalid civil-date count")
    return start, count


def _source(snapshot):
    content = snapshot["content"]
    _range(content)
    records = content["records"]
    _require(1 <= len(records) <= _MAX_SOURCE_RECORDS,
             "SOURCE_CONFLICT", "invalid source-record count")
    ids, boundaries, acquired = [], set(), {}
    for record in records:
        evidence = record["evidence"]
        _require(
            evidence["requested_start_date"] == content["coverage_start_date"]
            and evidence["requested_end_date"] == content["coverage_end_date"],
            "SOURCE_SCOPE_MISMATCH", "request range differs from snapshot",
        )
        for body_name in ("request", "response"):
            raw = _decode_base64(evidence[body_name + "_bytes_base64"])
            _require(_sha256(raw) == evidence[body_name + "_content_hash"],
                     "INTEGRITY_MISMATCH", body_name + " bytes/hash mismatch")
        receipt_body = evidence["custody_receipt"]["body"]
        _same_fields(receipt_body, evidence,
                     tuple(field for field in evidence
                           if field not in ("request_bytes_base64", "response_bytes_base64",
                                            "custody_receipt")),
                     "SOURCE_SCOPE_MISMATCH")
        record_id = _identity("l4-trading-day-source-record-v1", evidence)
        _require(record_id == record["source_record_id"], "IDENTITY_MISMATCH", "source record")
        boundary = tuple(evidence[field] for field in _ACQUISITION_BOUNDARY)
        _require(boundary not in boundaries, "SOURCE_CONFLICT", "duplicate acquisition")
        boundaries.add(boundary)
        ids.append(record_id)
        acquired[record_id] = _instant(evidence["acquired_at"])
    _require(ids == sorted(set(ids)), "SOURCE_CONFLICT", "source IDs must be ordered and unique")
    content_hash = _sha256(_canonical_json(content))
    _require(snapshot["source_content_hash"] == content_hash,
             "IDENTITY_MISMATCH", "source content hash")
    snapshot_id = _identity("l4-trading-day-source-snapshot-v1", {
        "schema_version": snapshot["schema_version"], "source_content_hash": content_hash,
    })
    _require(snapshot["source_snapshot_id"] == snapshot_id, "IDENTITY_MISMATCH", "snapshot ID")
    return acquired


def _claims(references, acquired, *, nonempty):
    pairs = [(ref["source_record_id"], ref["claim_index"]) for ref in references]
    _require(not nonempty or bool(pairs), "COVERAGE_INCOMPLETE", "missing claim reference")
    _require(pairs == sorted(set(pairs)), "SOURCE_CONFLICT", "claim order/duplicate")
    _require(all(record_id in acquired for record_id, _ in pairs),
             "SOURCE_CONFLICT", "unknown source reference")
    # Claim meaning and parser-relative upper bounds require qualified source profiles.


def _logical_day(day):
    declaration = {field: day[field] for field in _DAILY_FIELDS}
    declaration["market_calendar_date"] = _date(declaration["market_calendar_date"])
    for field in ("session_open", "session_close"):
        if declaration[field] is not None:
            declaration[field] = _instant(declaration[field])
    try:
        return TradingDayRecord(**declaration)
    except ValueError as exc:
        raise _ScheduleArtifactError("SESSION_GEOMETRY_UNQUALIFIED", "logical geometry") from exc


def _coverage(coverage, snapshot, acquired):
    content = coverage["content"]
    _same_fields(content, snapshot["content"], _SCOPE_FIELDS, "SOURCE_SCOPE_MISMATCH")
    _require(content["source_snapshot_id"] == snapshot["source_snapshot_id"],
             "IDENTITY_MISMATCH", "coverage snapshot")
    start, count = _range(content)
    _require(_date(content["closure_finalized_through"]) >= _date(content["coverage_end_date"]),
             "COVERAGE_INCOMPLETE", "closure finalization before coverage end")
    cutoff = _instant(content["closure_knowledge_cutoff"])
    _claims(content["completeness_claims"], acquired, nonempty=True)
    _require(all(cutoff <= acquired[ref["source_record_id"]]
                 for ref in content["completeness_claims"]),
             "ARCHIVE_BOUND_INVALID", "completeness cutoff after acquisition")
    days = content["daily_evidence"]
    _require(len(days) == count, "COVERAGE_INCOMPLETE", "civil-date count mismatch")
    for offset, day in enumerate(days):
        _require(_date(day["market_calendar_date"]).toordinal() == start.toordinal() + offset,
                 "COVERAGE_INCOMPLETE", "missing, duplicate or unordered civil date")
        _claims(day["status_claims"], acquired, nonempty=True)
        _claims(day["closure_claims"], acquired, nonempty=True)
        trading = day["day_status"] == "TRADING"
        _claims(day["geometry_claims"], acquired, nonempty=trading)
        if not trading:
            _require(not day["geometry_claims"], "SESSION_GEOMETRY_UNQUALIFIED",
                     "CLOSED geometry claims")
            _require(day["basis"] in ("WEEKEND", "SCHEDULED_HOLIDAY", "TEMPORARY_CLOSURE"),
                     "SESSION_GEOMETRY_UNQUALIFIED", "CLOSED basis")
        logical = _logical_day(day)
        if trading:
            basis = ("REGULAR_SESSION" if logical.session_profile == "NORMAL"
                     else "QUALIFIED_EARLY_CLOSE")
            _require(day["basis"] == basis, "SESSION_GEOMETRY_UNQUALIFIED", "TRADING basis")
    coverage_id = _identity("l4-trading-day-coverage-completion-v1", content)
    _require(coverage_id == coverage["coverage_completion_evidence_id"],
             "IDENTITY_MISMATCH", "coverage ID")


def _archive(receipt, acquired, cutoff, evidence_ids):
    body = receipt["body"]
    _same_fields(body, evidence_ids, _EVIDENCE_IDS, "IDENTITY_MISMATCH")
    validations = body["source_validation_times"]
    _require([entry["source_record_id"] for entry in validations] == sorted(acquired),
             "ARCHIVE_BOUND_INVALID", "source validation list must cover each source once in order")
    verified = [_instant(entry["verified_at"]) for entry in validations]
    _require(all(stamp >= acquired[entry["source_record_id"]]
                 for entry, stamp in zip(validations, verified)),
             "ARCHIVE_BOUND_INVALID", "verification before acquisition")
    coverage_at = _instant(body["coverage_verified_at"])
    geometry_at = _instant(body["geometry_verified_at"])
    logical_at = _instant(body["logical_schedule_verified_at"])
    complete_at = _instant(body["complete_verified_at"])
    _require(coverage_at >= max(*verified, cutoff), "ARCHIVE_BOUND_INVALID", "coverage clock")
    _require(geometry_at >= max(verified), "ARCHIVE_BOUND_INVALID", "geometry clock")
    _require(logical_at >= max(coverage_at, geometry_at), "ARCHIVE_BOUND_INVALID", "logical clock")
    _require(complete_at >= logical_at, "ARCHIVE_BOUND_INVALID", "complete clock")
    return max(*acquired.values(), *verified, coverage_at, geometry_at, logical_at, complete_at)


def _schedule(schedule, snapshot, coverage, receipt, evidence_ids, archive):
    _same_fields(schedule, snapshot["content"], _SCOPE_FIELDS, "SOURCE_SCOPE_MISMATCH")
    _same_fields(schedule, evidence_ids, _EVIDENCE_IDS, "IDENTITY_MISMATCH")
    projection = [{field: day[field] for field in _DAILY_FIELDS}
                  for day in coverage["content"]["daily_evidence"]]
    _require(schedule["daily_records"] == projection,
             "LOGICAL_SCHEDULE_MISMATCH", "daily projection")
    _require(_instant(schedule["archive_available_at"]) == archive,
             "ARCHIVE_BOUND_INVALID", "derived archive clock")
    declaration = {key: value for key, value in schedule.items() if key != "archive_available_at"}
    declaration_hash = _sha256(_canonical_json(declaration))
    _require(declaration_hash == receipt["body"]["schedule_declaration_hash_without_archive"],
             "IDENTITY_MISMATCH", "schedule declaration hash")
    logical = dict(schedule)
    logical["coverage_start_date"] = _date(logical["coverage_start_date"])
    logical["coverage_end_date"] = _date(logical["coverage_end_date"])
    logical["archive_available_at"] = archive
    logical["daily_records"] = tuple(_logical_day(day) for day in schedule["daily_records"])
    try:
        checked = verify_trading_day_schedule(**logical)
        content_id, pin_id = checked.schedule_content_id, schedule_pin_id(checked.pin)
    except ValueError as exc:
        raise _ScheduleArtifactError("LOGICAL_SCHEDULE_MISMATCH", "logical declaration") from exc
    return declaration_hash, content_id, pin_id


def _manifest(manifest, supplied, schedule, evidence_ids, content_id, pin_id):
    content = manifest["content"]
    _same_fields(content, schedule, _SCOPE_FIELDS + ("archive_available_at",),
                 "LOGICAL_SCHEDULE_MISMATCH")
    _same_fields(content, evidence_ids, _EVIDENCE_IDS, "IDENTITY_MISMATCH")
    _require(content["schedule_content_id"] == content_id and content["schedule_pin_id"] == pin_id,
             "IDENTITY_MISMATCH", "logical schedule IDs")
    _require(content["daily_record_count"] == len(schedule["daily_records"]),
             "LOGICAL_SCHEDULE_MISMATCH", "daily count")
    outputs = content["output_files"]
    _require(tuple((item["path"], item["role"]) for item in outputs) == _OUTPUT_ROLES,
             "INTEGRITY_MISMATCH", "closed output inventory/order/roles")
    for item in outputs:
        raw = supplied[item["path"]]
        _require(item["byte_size"] == len(raw) and item["sha256"] == _sha256(raw),
                 "INTEGRITY_MISMATCH", "member bytes: " + item["path"])
    artifact_id = _identity("l4-trading-day-schedule-artifact-v1", content)
    _require(manifest["schedule_artifact_id"] == artifact_id, "IDENTITY_MISMATCH", "artifact ID")
    return artifact_id


def _validate_artifact_structure(*, source_snapshot_bytes, coverage_evidence_bytes,
                                 verification_receipt_bytes, schedule_bytes, manifest_bytes):
    """Return detached consistency facts, NEVER authenticated schedule authority.

    Receipts are only shape/clock checked; source claims and claim-index upper
    bounds require unavailable qualified parsers. No trust resolver is bypassed
    to implement an admission API, and no logical schedule escapes this function.
    """
    supplied = {
        "source_snapshot.json": source_snapshot_bytes,
        "coverage_evidence.json": coverage_evidence_bytes,
        "verification_receipt.json": verification_receipt_bytes,
        "schedule.json": schedule_bytes, "manifest.json": manifest_bytes,
    }
    documents = tuple(_parse_document(name, data) for name, data in supplied.items())
    source, coverage, receipt, schedule, manifest = (
        _thaw(document.value) for document in documents
    )
    acquired = _source(source)
    _coverage(coverage, source, acquired)
    evidence_ids = {
        "source_snapshot_id": source["source_snapshot_id"],
        "source_content_hash": source["source_content_hash"],
        "coverage_completion_evidence_id": coverage["coverage_completion_evidence_id"],
    }
    archive = _archive(receipt, acquired, _instant(coverage["content"]["closure_knowledge_cutoff"]),
                       evidence_ids)
    declaration_hash, content_id, pin_id = _schedule(
        schedule, source, coverage, receipt, evidence_ids, archive,
    )
    artifact_id = _manifest(manifest, supplied, schedule, evidence_ids, content_id, pin_id)
    return _SemanticFacts(
        documents, source["source_snapshot_id"], source["source_content_hash"],
        coverage["coverage_completion_evidence_id"], declaration_hash,
        content_id, pin_id, artifact_id, archive,
    )
