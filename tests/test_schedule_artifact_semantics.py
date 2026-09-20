"""Cross-document consistency is independent of (unavailable) production authentication."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from market_vault.schedule_artifact import _models
from market_vault.schedule_artifact._errors import _ScheduleArtifactError
from market_vault.schedule_artifact._semantics import _validate_artifact_structure
from test_schedule_artifact_schema import (
    _at, _b64, _bundle, _c, _h, _seal_source, _sha, _stamp, _validate,
)


@pytest.mark.parametrize("start", ["2025-11-28", "2025-12-24", "2025-07-01", "2025-11-26"])
def test_complete_structure_reuses_logical_normal_early_close_and_dst_geometry(start):
    bundle = _bundle(start, 1)
    facts = _validate(bundle)
    source = bundle["source_snapshot.json"]
    manifest = bundle["manifest.json"]
    assert facts.source_snapshot_id == source["source_snapshot_id"]
    assert facts.source_content_hash == source["source_content_hash"]
    assert facts.coverage_completion_evidence_id == bundle["coverage_evidence.json"]["coverage_completion_evidence_id"]
    assert facts.schedule_content_id == manifest["content"]["schedule_content_id"]
    assert facts.schedule_pin_id == manifest["content"]["schedule_pin_id"]
    assert facts.schedule_artifact_id == manifest["schedule_artifact_id"]
    assert facts.archive_available_at == datetime.fromisoformat(_stamp(15))
    assert len(facts.documents) == 5
    assert not hasattr(facts, "schedule")
    with pytest.raises(FrozenInstanceError):
        facts.schedule_content_id = "0" * 64
    with pytest.raises(TypeError):
        facts.documents[0].value["content"]["records"][0]["evidence"]["provider_id"] = "mutated"
    bundle.clear()
    assert facts.schedule_artifact_id == manifest["schedule_artifact_id"]


@pytest.mark.parametrize("name,keys,bad,reason,detail", [
    ("source_snapshot.json", ("content", "records", 0, "evidence", "request_bytes_base64"),
     _b64(b"forged"), "INTEGRITY_MISMATCH", "request bytes/hash"),
    ("source_snapshot.json", ("content", "records", 0, "evidence", "response_bytes_base64"),
     _b64(b"forged"), "INTEGRITY_MISMATCH", "response bytes/hash"),
    ("source_snapshot.json", ("content", "records", 0, "evidence", "request_content_hash"),
     "0" * 64, "INTEGRITY_MISMATCH", "request bytes/hash"),
    ("source_snapshot.json", ("content", "records", 0, "evidence", "response_content_hash"),
     "0" * 64, "INTEGRITY_MISMATCH", "response bytes/hash"),
    ("source_snapshot.json", ("content", "records", 0, "source_record_id"),
     "0" * 64, "IDENTITY_MISMATCH", "source record"),
    ("source_snapshot.json", ("source_content_hash",), "0" * 64, "IDENTITY_MISMATCH", "source content"),
    ("source_snapshot.json", ("source_snapshot_id",), "0" * 64, "IDENTITY_MISMATCH", "snapshot ID"),
    ("coverage_evidence.json", ("coverage_completion_evidence_id",),
     "0" * 64, "IDENTITY_MISMATCH", "coverage ID"),
    ("coverage_evidence.json", ("content", "source_snapshot_id"),
     "0" * 64, "IDENTITY_MISMATCH", "coverage snapshot"),
    ("verification_receipt.json", ("body", "schedule_declaration_hash_without_archive"),
     "0" * 64, "IDENTITY_MISMATCH", "schedule declaration hash"),
    ("manifest.json", ("content", "schedule_content_id"),
     "0" * 64, "IDENTITY_MISMATCH", "logical schedule IDs"),
    ("manifest.json", ("content", "schedule_pin_id"),
     "0" * 64, "IDENTITY_MISMATCH", "logical schedule IDs"),
    ("manifest.json", ("content", "output_files", 0, "sha256"),
     "0" * 64, "INTEGRITY_MISMATCH", "member bytes"),
    ("manifest.json", ("schedule_artifact_id",), "0" * 64, "IDENTITY_MISMATCH", "artifact ID"),
])
def test_each_identity_and_hash_tamper_fails_at_its_own_boundary(name, keys, bad, reason, detail):
    bundle = _bundle()
    _at(bundle[name], keys[:-1])[keys[-1]] = bad
    with pytest.raises(_ScheduleArtifactError, match=detail) as caught:
        _validate(bundle)
    assert caught.value.reason_code == reason


@pytest.mark.parametrize("field", [
    "provider_id", "source_id", "source_contract_id", "source_contract_version",
    "source_schema_version", "api_contract_version", "origin_locator",
    "request_content_hash", "response_content_hash", "acquired_at",
    "requested_start_date", "requested_end_date",
])
def test_custody_every_duplicated_variable_field_is_bound(field):
    bundle = _bundle()
    body = bundle["source_snapshot.json"]["content"]["records"][0]["evidence"]["custody_receipt"]["body"]
    body[field] = ("0" * 64 if field.endswith("_hash") else _stamp(8) if field == "acquired_at"
                   else "2025-01-01" if field.endswith("_date") else "different")
    with pytest.raises(_ScheduleArtifactError, match="mismatched " + field) as caught:
        _validate(bundle)
    assert caught.value.reason_code == "SOURCE_SCOPE_MISMATCH"


@pytest.mark.parametrize("variation", ["identical", "clock", "request", "response"])
def test_duplicate_declared_acquisition_rejected_even_with_distinct_clock_or_bytes(variation):
    bundle = _bundle()
    source = bundle["source_snapshot.json"]
    duplicate = deepcopy(source["content"]["records"][0])
    if variation == "clock":
        duplicate["evidence"]["acquired_at"] = _stamp(10, 2)
        duplicate["evidence"]["custody_receipt"]["body"]["acquired_at"] = _stamp(10, 2)
    elif variation in ("request", "response"):
        duplicate["evidence"][variation + "_bytes_base64"] = _b64(b"different wire body")
        digest = _sha(b"different wire body")
        duplicate["evidence"][variation + "_content_hash"] = digest
        duplicate["evidence"]["custody_receipt"]["body"][variation + "_content_hash"] = digest
    source["content"]["records"].append(duplicate)
    _seal_source(source)
    with pytest.raises(_ScheduleArtifactError, match="duplicate acquisition"):
        _validate(bundle)


@pytest.mark.parametrize("fault", ["empty", "over_limit", "order", "scope"])
def test_source_count_order_and_request_scope(fault):
    bundle = _bundle()
    content = bundle["source_snapshot.json"]["content"]
    if fault == "empty":
        content["records"] = []
    elif fault == "over_limit":
        content["records"] *= 129
    elif fault == "order":
        content["records"].reverse()
    else:
        content["records"][0]["evidence"]["requested_start_date"] = "2025-01-01"
    expected = {"empty": "source-record count", "over_limit": "source-record count",
                "order": "ordered and unique", "scope": "request range"}
    with pytest.raises(_ScheduleArtifactError, match=expected[fault]):
        _validate(bundle)


@pytest.mark.parametrize("fault", [
    "reversed", "range_over_limit", "list_over_limit", "missing", "duplicate", "order",
    "empty_completeness", "duplicate_claim", "unsorted_claim", "unknown_claim",
    "finalization", "cutoff", "scope",
])
def test_coverage_range_order_refs_finalization_and_completeness(fault):
    bundle = _bundle()
    source = bundle["source_snapshot.json"]["content"]
    content = bundle["coverage_evidence.json"]["content"]
    expected = "COVERAGE_INCOMPLETE"
    if fault == "reversed":
        source["coverage_start_date"] = "2025-12-01"
    elif fault == "range_over_limit":
        source["coverage_end_date"] = "2126-02-13"
    elif fault == "list_over_limit":
        content["daily_evidence"] = [content["daily_evidence"][0]] * 36_601
    elif fault == "missing":
        content["daily_evidence"].pop()
    elif fault == "duplicate":
        content["daily_evidence"][1] = deepcopy(content["daily_evidence"][0])
    elif fault == "order":
        content["daily_evidence"].reverse()
    elif fault == "empty_completeness":
        content["completeness_claims"] = []
    elif fault == "duplicate_claim":
        content["completeness_claims"].append(deepcopy(content["completeness_claims"][0]))
        expected = "SOURCE_CONFLICT"
    elif fault == "unsorted_claim":
        content["completeness_claims"].reverse()
        expected = "SOURCE_CONFLICT"
    elif fault == "unknown_claim":
        content["completeness_claims"] = [dict(source_record_id="0" * 64, claim_index=0)]
        expected = "SOURCE_CONFLICT"
    elif fault == "finalization":
        content["closure_finalized_through"] = "2025-11-29"
    elif fault == "cutoff":
        content["closure_knowledge_cutoff"] = _stamp(10, 1)
        expected = "ARCHIVE_BOUND_INVALID"
    else:
        content["coverage_end_date"] = "2025-11-29"
        expected = "SOURCE_SCOPE_MISMATCH"
    with pytest.raises(_ScheduleArtifactError) as caught:
        _validate(bundle)
    assert caught.value.reason_code == expected


@pytest.mark.parametrize("index,field,value,reason", [
    (0, "session_open", None, "SESSION_GEOMETRY_UNQUALIFIED"),
    (0, "session_close", None, "SESSION_GEOMETRY_UNQUALIFIED"),
    (0, "session_profile", "NORMAL", "SESSION_GEOMETRY_UNQUALIFIED"),
    (0, "basis", "REGULAR_SESSION", "SESSION_GEOMETRY_UNQUALIFIED"),
    (0, "session_open", "2025-11-28T09:30:00.000000+00:00", "SESSION_GEOMETRY_UNQUALIFIED"),
    (0, "session_close", "2025-11-28T21:00:00.000000+00:00", "SESSION_GEOMETRY_UNQUALIFIED"),
    (0, "status_claims", [], "COVERAGE_INCOMPLETE"),
    (0, "closure_claims", [], "COVERAGE_INCOMPLETE"),
    (0, "geometry_claims", [], "COVERAGE_INCOMPLETE"),
    (1, "status_claims", [], "COVERAGE_INCOMPLETE"),
    (1, "closure_claims", [], "COVERAGE_INCOMPLETE"),
    (1, "session_profile", "NORMAL", "SESSION_GEOMETRY_UNQUALIFIED"),
    (1, "session_open", "2025-11-29T14:30:00.000000+00:00", "SESSION_GEOMETRY_UNQUALIFIED"),
    (1, "basis", "REGULAR_SESSION", "SESSION_GEOMETRY_UNQUALIFIED"),
])
def test_daily_status_basis_geometry_and_required_claims(index, field, value, reason):
    bundle = _bundle()
    bundle["coverage_evidence.json"]["content"]["daily_evidence"][index][field] = value
    with pytest.raises(_ScheduleArtifactError) as caught:
        _validate(bundle)
    assert caught.value.reason_code == reason


def test_closed_geometry_claims_and_normal_day_early_profile_rejected():
    bundle = _bundle()
    days = bundle["coverage_evidence.json"]["content"]["daily_evidence"]
    days[1]["geometry_claims"] = deepcopy(days[1]["status_claims"])
    with pytest.raises(_ScheduleArtifactError, match="CLOSED geometry claims"):
        _validate(bundle)
    bundle = _bundle("2025-11-26", 1)
    bundle["coverage_evidence.json"]["content"]["daily_evidence"][0]["session_profile"] = "QUALIFIED_EARLY_CLOSE"
    with pytest.raises(_ScheduleArtifactError, match="SESSION_GEOMETRY_UNQUALIFIED"):
        _validate(bundle)


@pytest.mark.parametrize("fault", [
    "missing", "duplicate", "extra", "order", "before_acquired",
    "coverage", "geometry", "logical", "complete", "archive",
])
def test_receipt_list_and_every_clock_relation(fault):
    bundle = _bundle()
    body = bundle["verification_receipt.json"]["body"]
    entries = body["source_validation_times"]
    if fault == "missing":
        entries.pop()
    elif fault == "duplicate":
        entries[1] = deepcopy(entries[0])
    elif fault == "extra":
        entries.append(dict(source_record_id="f" * 64, verified_at=_stamp(11)))
    elif fault == "order":
        entries.reverse()
    elif fault == "before_acquired":
        entries[0]["verified_at"] = _stamp(9)
    elif fault == "coverage":
        body["coverage_verified_at"] = _stamp(11)
    elif fault == "geometry":
        body["geometry_verified_at"] = _stamp(11)
    elif fault == "logical":
        body["logical_schedule_verified_at"] = _stamp(12)
    elif fault == "complete":
        body["complete_verified_at"] = _stamp(13)
    else:
        bundle["schedule.json"]["archive_available_at"] = _stamp(14)
    with pytest.raises(_ScheduleArtifactError) as caught:
        _validate(bundle)
    assert caught.value.reason_code == "ARCHIVE_BOUND_INVALID"


@pytest.mark.parametrize("fault", ["omission", "addition", "duplicate", "order", "value"])
def test_schedule_daily_projection_must_match_exactly(fault):
    bundle = _bundle()
    days = bundle["schedule.json"]["daily_records"]
    if fault == "omission":
        days.pop()
    elif fault == "addition":
        days.append(deepcopy(days[-1]))
    elif fault == "duplicate":
        days[1] = deepcopy(days[0])
    elif fault == "order":
        days.reverse()
    else:
        days[1]["day_status"] = "TRADING"
    with pytest.raises(_ScheduleArtifactError, match="daily projection"):
        _validate(bundle)


@pytest.mark.parametrize("name,prefix", [
    ("verification_receipt.json", ("body",)), ("schedule.json", ()),
    ("manifest.json", ("content",)),
])
@pytest.mark.parametrize("field", [
    "source_snapshot_id", "source_content_hash", "coverage_completion_evidence_id",
])
def test_each_repeated_evidence_identity_is_bound(name, prefix, field):
    bundle = _bundle()
    _at(bundle[name], prefix)[field] = "0" * 64
    with pytest.raises(_ScheduleArtifactError, match="mismatched " + field) as caught:
        _validate(bundle)
    assert caught.value.reason_code == "IDENTITY_MISMATCH"


@pytest.mark.parametrize("fault", ["role", "order", "missing", "extra", "size", "count", "archive", "scope"])
def test_manifest_closed_inventory_sizes_and_repeated_facts(fault):
    bundle = _bundle()
    content = bundle["manifest.json"]["content"]
    outputs = content["output_files"]
    reason = "INTEGRITY_MISMATCH"
    if fault == "role":
        outputs[0]["role"] = "SCHEDULE"
    elif fault == "order":
        outputs.reverse()
    elif fault == "missing":
        outputs.pop()
    elif fault == "extra":
        outputs.append(deepcopy(outputs[0]))
    elif fault == "size":
        outputs[0]["byte_size"] += 1
    elif fault == "count":
        content["daily_record_count"] = 2
        reason = "LOGICAL_SCHEDULE_MISMATCH"
    elif fault == "archive":
        content["archive_available_at"] = _stamp(16)
        reason = "LOGICAL_SCHEDULE_MISMATCH"
    else:
        content["coverage_end_date"] = "2025-11-29"
        reason = "LOGICAL_SCHEDULE_MISMATCH"
    with pytest.raises(_ScheduleArtifactError) as caught:
        _validate(bundle)
    assert caught.value.reason_code == reason


def test_hashes_cover_custody_signature_bytes_but_do_not_authenticate_them():
    bundle = _bundle()
    evidence = bundle["source_snapshot.json"]["content"]["records"][0]["evidence"]
    evidence["custody_receipt"]["signature_base64"] = _b64(b"X" * 64)
    with pytest.raises(_ScheduleArtifactError, match="source record"):
        _validate(bundle)


def test_uninterpreted_claim_index_has_no_invented_upper_bound_or_authority():
    bundle = _bundle()
    coverage = bundle["coverage_evidence.json"]
    coverage["content"]["completeness_claims"][0]["claim_index"] = 10 ** 100
    coverage["coverage_completion_evidence_id"] = _h(
        "l4-trading-day-coverage-completion-v1", coverage["content"])
    coverage_id = coverage["coverage_completion_evidence_id"]
    schedule = bundle["schedule.json"]
    schedule["coverage_completion_evidence_id"] = coverage_id
    body = bundle["verification_receipt.json"]["body"]
    body["coverage_completion_evidence_id"] = coverage_id
    body["schedule_declaration_hash_without_archive"] = _sha(_c({
        key: value for key, value in schedule.items() if key != "archive_available_at"
    }))
    # Pure checks must reach the manifest rather than pretend to resolve source claims.
    with pytest.raises(_ScheduleArtifactError, match="mismatched coverage_completion_evidence_id"):
        _validate(bundle)


def test_semantic_limits_present_preallocation_reader_limits_deferred():
    assert _models._MAX_SOURCE_RECORDS == 256
    assert _models._MAX_CIVIL_DATES == 36_600
    assert _models._MAX_FILE_BYTES == 64 * 1024 * 1024
    assert _models._MAX_INVENTORY_BYTES == 128 * 1024 * 1024
    assert _models._MAX_SOURCE_BODY_BYTES == 16 * 1024 * 1024
    assert _models._MAX_JSON_NESTING == 32
    # This API accepts existing bytes; it makes no before-allocation reader claim.
    import inspect
    assert tuple(inspect.signature(_validate_artifact_structure).parameters) == (
        "source_snapshot_bytes", "coverage_evidence_bytes", "verification_receipt_bytes",
        "schedule_bytes", "manifest_bytes",
    )
