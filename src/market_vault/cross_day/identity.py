"""Frozen L1 scalar payloads; typed authority admission lives above encoding."""

from ..dataset.encoding import encode_identity
from ..dataset.specs import feature_label_spec_pin
from ._validation import digest_set, record, sha256

CROSS_DAY_LABEL_ASSOCIATION_SCHEMA_VERSION = "cross-day-label-association-v1"
CROSS_DAY_LABEL_PIT_CONTRACT_VERSION = "cross-day-label-pit-v1"


def sequence_id(domain, members):
    members = tuple(sha256(v, "sequence member") for v in members)
    return encode_identity(domain, {"count": len(members), "members": "".join(members)})


def backing_canonical_build_ids_digest(build_ids):
    return sequence_id("cross-day-backing-canonical-builds-v1", digest_set(build_ids, "backing builds"))


def considered_canonical_build_ids_digest(build_ids):
    return sequence_id("cross-day-considered-canonical-builds-v1", digest_set(build_ids, "considered builds"))


def schedule_content_id(schedule):
    payload = record(schedule)
    days = payload.pop("daily_records")
    payload["daily_records_digest"] = sequence_id("trading-day-schedule-dates-v1", (
        encode_identity("trading-day-schedule-date-v1", record(d)) for d in days))
    return encode_identity("trading-day-schedule-content-v1", payload)


def schedule_pin_id(pin):
    return encode_identity("trading-day-schedule-pin-v1", record(pin))


def label_spec_pin_id(spec):
    return encode_identity("dataset-spec", record(feature_label_spec_pin(spec)))


def implementation_pin_id(pin):
    return encode_identity("dataset-implementation", record(pin))


def slot_id(slot):
    return encode_identity("cross-day-label-slot-v1", record(slot))


def row_reference_id(row):
    payload = record(row)
    payload["backing_canonical_build_ids_digest"] = backing_canonical_build_ids_digest(
        payload.pop("backing_canonical_build_ids"))
    return encode_identity("cross-day-label-row-v1", payload)


def gap_proof_id(proof):
    payload = record(proof)
    payload["backing_canonical_build_ids_digest"] = backing_canonical_build_ids_digest(
        payload.pop("backing_canonical_build_ids"))
    return encode_identity("cross-day-label-gap-proof-v1", payload)


def selected_rows_digest(rows):
    return sequence_id("cross-day-label-selected-rows-v1", (row_reference_id(r) for r in rows))


def decision_payload(decision):
    payload = record(decision)
    anchor = payload.pop("anchor")
    payload.update(schema_version=CROSS_DAY_LABEL_ASSOCIATION_SCHEMA_VERSION,
                   pit_contract_version=CROSS_DAY_LABEL_PIT_CONTRACT_VERSION,
                   anchor_canonical_row_version_id=None if anchor is None else anchor.canonical_row_version_id,
                   anchor_row_reference_id=None if anchor is None else row_reference_id(anchor),
                   required_slots_digest=sequence_id("cross-day-label-required-slots-v1", (
                       slot_id(s) for s in payload.pop("required_slots"))),
                   considered_canonical_build_ids_digest=considered_canonical_build_ids_digest(
                       payload.pop("considered_canonical_build_ids")),
                   selected_rows_digest=selected_rows_digest(payload.pop("selected_rows")),
                   rejected_archive_rows_digest=sequence_id("cross-day-label-archive-rejected-v1", (
                       row_reference_id(r) for r in payload.pop("rejected_archive_rows"))),
                   absence_proofs_digest=sequence_id("cross-day-label-gap-proofs-v1", (
                       gap_proof_id(p) for p in payload.pop("absence_proofs"))))
    return payload


def decision_id(decision):
    return encode_identity("cross-day-label-decision-v1", decision_payload(decision))


def sample_binding_id(binding):
    payload = record(binding)
    payload["decisions_digest"] = sequence_id("cross-day-label-binding-decisions-v1", payload.pop("decision_ids"))
    return encode_identity("cross-day-label-sample-binding-v1", payload)


def association_content_id(schedule_pin, specs, builds, decisions, bindings):
    return encode_identity("cross-day-label-association-content-v1", dict(
        schema_version=CROSS_DAY_LABEL_ASSOCIATION_SCHEMA_VERSION,
        pit_contract_version=CROSS_DAY_LABEL_PIT_CONTRACT_VERSION,
        schedule_pin_id=schedule_pin_id(schedule_pin),
        label_spec_pins_digest=sequence_id("cross-day-label-spec-pins-v1", sorted(label_spec_pin_id(s) for s in specs)),
        considered_canonical_build_ids_digest=considered_canonical_build_ids_digest(builds),
        decisions_digest=sequence_id("cross-day-label-decisions-v1", (decision_id(d) for d in decisions)),
        sample_bindings_digest=sequence_id("cross-day-label-bindings-v1", (sample_binding_id(b) for b in bindings))))


def value_id(value):
    payload = record(value)
    spec_pin = payload.pop("spec_pin")
    payload.update(execution_contract_version="cross-day-label-execution-v1",
                   label_spec_pin_id=encode_identity("dataset-spec", record(spec_pin)),
                   implementation_pin_id=implementation_pin_id(payload.pop("implementation_pin")),
                   consumed_rows_digest=selected_rows_digest(payload.pop("consumed_rows")))
    return encode_identity("cross-day-label-value-v1", payload)


def values_content_id(values):
    return sequence_id("cross-day-label-values-v1", (value_id(v) for v in values))
