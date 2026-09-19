"""Closed typed physical projections, without reconstructing upstream live results.

These tables freeze the declared BASE fields. Names are internal codec selectors,
never class tags in artifact bytes. No upstream constructor or reflection is used.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from struct import unpack
from types import MappingProxyType
from zoneinfo import ZoneInfo

from ._artifact_encoding import (
    _text, canonical_json, decode_date, decode_json, decode_timestamp,
    exact_fields, timestamp_text,
)
from .artifact_models import SERIALIZATION_FORMAT_VERSION, _require


# ?T is nullable, *T is a tuple, (A,B) is a fixed pair. Scalars are exact.
_DECLARATIONS = {
    "DatasetScope": "symbols:*str trade_dates:*date adjustment:str interval:str requested_session:str",
    "DatasetSchema": "fields:*DatasetField",
    "DatasetField": "name:str logical_type:str nullable:bool",
    "VerifiedCanonicalBuild": (
        "canonical_build_id:str canonical_content_id:str resolution_content_id:str gap_content_id:str "
        "canonical_builder_version:str canonical_schema_version:str materializer_version:str "
        "gap_policy_version:str status:str normalized_request:VerifiedCanonicalRequest bars:*CanonicalBar "
        "canonical_row_version_ids:*str source_snapshot_provenance:*CanonicalSourceRef "
        "gap_ranges:*GapRange gap_boundaries:*GapBoundaryBars gap_count:int"
    ),
    "VerifiedCanonicalRequest": (
        "symbols:*str trade_dates:*date interval:str requested_session:str adjustment:str source_schema_version:str"
    ),
    "CanonicalBar": (
        "canonical_bar_key:str canonical_row_version_id:str dataset_kind:str code:str interval:str adjustment:str "
        "event_time:datetime market_available_at:datetime archive_available_at:datetime open:float high:float "
        "low:float close:float volume:number extra_fields:*(str,float) ingestion_run_id:str "
        "physical_snapshot_hash:str logical_source_rows_hash:str source_schema_version:str "
        "canonical_builder_version:str requested_trade_date:date requested_session:str "
        "market_calendar_date:?date session:str"
    ),
    "CanonicalSourceRef": (
        "ingestion_run_id:str physical_snapshot_hash:str logical_source_rows_hash:str source_schema_version:str "
        "requested_trade_date:date requested_session:str"
    ),
    "CanonicalBuildPin": (
        "canonical_build_id:str canonical_content_id:str canonical_builder_version:str canonical_schema_version:str "
        "materializer_version:str gap_policy_version:str gap_content_id:str status:str "
        "canonical_row_version_ids:*str source_snapshots:*SourceSnapshotPin"
    ),
    "SourceSnapshotPin": (
        "ingestion_run_id:str physical_snapshot_hash:str logical_source_rows_hash:str source_schema_version:str "
        "requested_trade_date:date requested_session:str"
    ),
    "GapReference": "canonical_build_id:str gap_content_id:str gap_range_count:int",
    "GapRange": (
        "gap_id:str gap_policy_version:str dataset_kind:str code:str interval:str adjustment:str "
        "market_calendar_date:date session:str previous_event_time:datetime next_event_time:datetime "
        "missing_from_event_time:datetime missing_to_event_time:datetime missing_bar_count:int"
    ),
    "GapBoundaryBars": (
        "gap_id:str previous_archive_available_at:datetime next_market_available_at:datetime "
        "next_archive_available_at:datetime"
    ),
    "PITAssemblyResult": (
        "samples:*PITSample canonical_build_pins:*CanonicalBuildPin canonical_row_version_ids:*str "
        "gap_references:*GapReference association_schema:DatasetSchema association_rows:*PITAssociationRow "
        "association_schema_id:str association_content_id:str diagnostics:PITAssemblyDiagnostics"
    ),
    "PITSample": (
        "sample_key:str sample_version_id:str request:PITSampleRequest dataset_as_of:?datetime "
        "feature_canonical_row_version_ids:*str label_canonical_row_version_ids:*str "
        "considered_canonical_build_ids:*str diagnostics:PITDiagnostics"
    ),
    "PITSampleRequest": (
        "code:str interval:str adjustment:str requested_session:str anchor_market_calendar_date:date "
        "feature_window_start:datetime feature_window_close:datetime label_window_start:?datetime "
        "label_window_close:?datetime"
    ),
    "PITDiagnostics": (
        "feature_candidate_count:int feature_selected_count:int feature_market_future_excluded_count:int "
        "feature_archive_future_excluded_count:int label_candidate_count:int label_selected_count:int "
        "label_market_future_excluded_count:int label_archive_future_excluded_count:int "
        "known_feature_gap_ids:*str known_label_gap_ids:*str empty_observation_window:bool"
    ),
    "PITAssemblyDiagnostics": (
        "sample_count:int total_feature_rows:int total_label_rows:int feature_market_future_excluded_count:int "
        "feature_archive_future_excluded_count:int label_market_future_excluded_count:int "
        "label_archive_future_excluded_count:int considered_canonical_build_ids:*str"
    ),
    "PITAssociationRow": (
        "sample_key:str sample_version_id:str role:str position:int canonical_build_id:str "
        "canonical_bar_key:str canonical_row_version_id:str code:str event_time:datetime "
        "market_available_at:datetime archive_available_at:datetime"
    ),
    "TS2FeatureExecutionResult": (
        "execution_contract_version:str registry_contract_version:str feature_association_content_id:str "
        "feature_association_schema_id:str dataset_as_of:?datetime considered_canonical_build_ids:*str "
        "feature_specs:*FeatureSpec feature_spec_pins:*SpecPin registry_implementation_pins:*ImplementationPin "
        "samples:*TS2FeatureSampleResult status:str"
    ),
    "FeatureSpec": (
        "spec_schema_version:str name:str version:str output:DatasetField input_canonical_fields:*str "
        "transform_ref:str parameters:*SpecParameter requirements:SpecVersionRequirements kind:str"
    ),
    "SpecParameter": "name:str value:parameter",
    "SpecVersionRequirements": "canonical_schema_versions:*str source_schema_versions:*str",
    "SpecPin": "kind:str name:str version:str content_sha256:str",
    "ImplementationPin": "name:str version:str content_sha256:?str",
    "TS2FeatureSampleResult": "sample_key:str bar_sample_version_id:str values:*TS2FeatureValueResult status:str",
    "TS2FeatureValueResult": (
        "sample_key:str bar_sample_version_id:str feature_name:str spec_pin:SpecPin implementation_pin:ImplementationPin "
        "feature_window_close:datetime dataset_as_of:?datetime considered_canonical_build_ids:*str "
        "candidate_canonical_row_version_ids:*str consumed_canonical_row_version_ids:*str "
        "status:str value:?float reason_code:?str"
    ),
    "ObservationPITAssemblyResult": (
        "decisions:*ObservationPITDecision evidence:*ObservationDecisionEvidence sample_bindings:*ObservationSampleBinding "
        "bindings:*ObservationPITFeatureBinding observation_association_content_id:str sample_binding_content_id:str "
        "combined_association_content_id:str bar_association_content_id:str bar_association_schema_id:str"
    ),
    "ObservationPITDecision": (
        "sample_key:str bar_sample_version_id:str feature_spec_pin_id:str observation_source_spec_id:str "
        "T:datetime A:?datetime considered_observation_builds_digest:str status:str reason:?str archive_limited:bool "
        "selected_observation_key:?str selected_observation_version_id:?str selected_observation_build_id:?str "
        "selected_source_snapshot_id:?str selected_known_at_authority_id:?str selected_event_time:?datetime "
        "selected_known_at:?datetime selected_archive_available_at:?datetime scoped_version_count:int "
        "future_known_excluded_count:int archive_future_excluded_count:int eligible_key_count:int alignment_candidate_count:int"
    ),
    "ObservationDecisionEvidence": (
        "sample_key:str feature_spec_pin_id:str build_pins:*ObservationBuildPin coverages:*ObservationCoverage"
    ),
    "ObservationBuildPin": (
        "observation_build_id:str observation_content_id:str observation_schema_version:str coverage_id:str "
        "coverage_proof_available_at:datetime status:str authority_evidence_ids:*str "
        "provider_contracts:*ObservationContractPin normalizations:*ObservationContractPin "
        "source_snapshots:*ObservationSnapshotPin selected_observation_version_ids:*str"
    ),
    "ObservationContractPin": "version:str content_id:str",
    "ObservationSnapshotPin": (
        "source_snapshot_id:str source_content_sha256:str provider_id:str source_kind:str provider_contract_version:str "
        "provider_contract_content_id:str normalized_request_id:str acquisition_receipt_id:str "
        "acquisition_receipt_content_id:str completed_possession_at:datetime"
    ),
    "ObservationCoverage": (
        "scope:ObservationScope provider_contract:ObservationContractPin effective_start:datetime effective_end:datetime "
        "knowledge_start:datetime knowledge_end:datetime normalized_request_id:str request_completion_evidence_id:str "
        "request_pages_complete:bool missing_semantics:str missing_semantics_content_id:str "
        "revision_inventory_content_id:str revision_inventory_complete:bool"
    ),
    "ObservationScope": "provider_id:str source_kind:str entity_id:str observation_name:str dimensions:*ObservationDimension",
    "ObservationDimension": "name:str logical_type:str value:dimension",
    "ObservationSampleBinding": (
        "sample_key:str bar_sample_version_id:str observation_binding_id:str multi_source_sample_version_id:str"
    ),
    "ObservationPITFeatureBinding": (
        "feature_spec_pin:SpecPin source_spec:ObservationSourceSpec feature_spec_pin_id:str observation_source_spec_id:str"
    ),
    "ObservationSourceSpec": (
        "provider_id:str source_kind:str observation_name:str dimensions:*ObservationDimension entity_binding:str "
        "entity_id:?str code_entity_map:*(str,str) input_field_names:*str value_schema_id:str provider_contract_version:str "
        "provider_contract_content_id:str normalization_version:str normalization_content_id:str "
        "known_at_authority_policy_version:str known_at_authority_policy_content_id:str alignment:str "
        "exact_target_binding:?str max_age_us:int missing_policy:str"
    ),
    "ObservationBuildIdentityInput": (
        "rows:*Observation source_snapshot_ids:*str authority_evidence_ids:*str provider_contracts:*ObservationContractPin "
        "normalizations:*ObservationContractPin coverage:ObservationCoverage schema_version:str"
    ),
    "ObservationEvidence": (
        "identity_input:ObservationBuildIdentityInput source_snapshots:*ObservationSourceSnapshotInput created_at:datetime"
    ),
    "Observation": (
        "provider_id:str source_kind:str entity_id:str observation_name:str dimensions:*ObservationDimension "
        "event_time:datetime event_period_start:?datetime value_schema:ObservationValueSchema values:?*number "
        "value_status:str known_at:datetime known_at_authority_id:str archive_available_at:datetime "
        "source_snapshot_id:str source_content_sha256:str provider_contract_version:str provider_contract_content_id:str "
        "normalization_version:str normalization_content_id:str revision_id:str supersedes_revision_id:?str "
        "value_schema_id:str observation_key:str observation_version_id:str"
    ),
    "ObservationValueSchema": "fields:*ObservationValueField",
    "ObservationValueField": "name:str logical_type:str unit:str representation:str",
    "ObservationSourceSnapshotInput": (
        "provider_id:str source_kind:str provider_contract:ObservationContractPin normalized_request_id:str "
        "source_content_sha256:str acquisition_receipt_id:str acquisition_receipt_content_id:str "
        "completed_possession_at:datetime members:*ObservationSnapshotMember"
    ),
    "ObservationSnapshotMember": "relative_name:str byte_size:int sha256:str",
    "ObservationFeatureSpec": (
        "spec_schema_version:str name:str version:str output:DatasetField source_spec:ObservationSourceSpec "
        "transform_ref:str parameters:*SpecParameter kind:str"
    ),
    "ObservationFeatureExecutionResult": (
        "samples:*ObservationFeatureSampleResult feature_spec_pins:*SpecPin implementation_pins:*ImplementationPin "
        "execution_contract_version:str"
    ),
    "ObservationFeatureSampleResult": (
        "sample_key:str multi_source_sample_version_id:str status:str values:*ObservationFeatureValueResult"
    ),
    "ObservationFeatureValueResult": (
        "sample_key:str multi_source_sample_version_id:str feature_name:str spec_pin:SpecPin "
        "implementation_pin:ImplementationPin decision_id:str status:str value:?number reason_code:?str "
        "consumed_observation_version_id:?str"
    ),
    "CrossDayAssociation": (
        "feature_build_ids:*str label_build_ids:*str dataset_as_of:?datetime decisions:*CrossDayLabelDecision "
        "sample_bindings:*CrossDayLabelSampleBinding"
    ),
    "VerifiedTradingDaySchedule": (
        "schedule_schema_version:str market:str requested_session:str market_timezone:str coverage_start_date:date "
        "coverage_end_date:date daily_records:*TradingDayRecord source_snapshot_id:str source_content_hash:str "
        "calendar_contract_version:str normalization_version:str coverage_completion_evidence_id:str "
        "coverage_complete:bool archive_available_at:datetime"
    ),
    "TradingDayRecord": (
        "market_calendar_date:date day_status:str session_open:?datetime session_close:?datetime session_profile:?str"
    ),
    "LabelSpec": (
        "spec_schema_version:str name:str version:str output:DatasetField input_canonical_fields:*str transform_ref:str "
        "parameters:*SpecParameter requirements:SpecVersionRequirements observation_window:LabelObservationWindow "
        "horizon:LabelHorizon alignment_rule:str missing_data_policy:str cross_trading_day:CrossTradingDayPolicy kind:str"
    ),
    "LabelObservationWindow": "unit:str start_offset:int end_offset:int",
    "LabelHorizon": "unit:str value:int",
    "CrossTradingDayPolicy": "allow:bool boundary_rule:?str",
    "CrossDayLabelDecision": (
        "sample_key:str bar_sample_version_id:str label_spec_pin_id:str schedule_pin_id:str dataset_as_of:?datetime "
        "code:str interval:str adjustment:str requested_session:str feature_window_close:datetime "
        "anchor_market_calendar_date:date anchor_event_time:datetime anchor_slot:int anchor:?CrossDayLabelRowReference "
        "required_slots:*CrossDayLabelSlot considered_canonical_build_ids:*str selected_rows:*CrossDayLabelRowReference "
        "rejected_archive_rows:*CrossDayLabelRowReference absence_proofs:*CrossDayLabelGapProof status:str "
        "reason_code:?str archive_limited:bool actual_label_end_time:?datetime"
    ),
    "CrossDayLabelRowReference": (
        "offset:int canonical_bar_key:str canonical_row_version_id:str backing_canonical_build_ids:*str "
        "event_time:datetime market_available_at:datetime archive_available_at:datetime"
    ),
    "CrossDayLabelSlot": (
        "offset:int market_calendar_date:date event_time:datetime session_open:datetime session_close:datetime slot_fits:bool"
    ),
    "CrossDayLabelSampleBinding": (
        "sample_key:str bar_sample_version_id:str multi_source_sample_version_id:?str schedule_pin_id:str decision_ids:*str"
    ),
    "CrossDayLabelGapProof": (
        "offset:int gap_id:str backing_canonical_build_ids:*str previous_canonical_row_version_id:str "
        "next_canonical_row_version_id:str missing_from_event_time:datetime missing_to_event_time:datetime "
        "proof_archive_available_at:datetime"
    ),
    "CrossDayValues": (
        "implementation_pins:*ImplementationPin implementation_source_hashes:*(str,str) values:*CrossDayLabelValueResult"
    ),
    "CrossDayLabelValueResult": (
        "sample_key:str bar_sample_version_id:str multi_source_sample_version_id:?str label_name:str spec_pin:SpecPin "
        "implementation_pin:ImplementationPin schedule_pin_id:str decision_id:str anchor_canonical_row_version_id:?str "
        "consumed_rows:*CrossDayLabelRowReference status:str value:?number reason_code:?str actual_label_end_time:?datetime"
    ),
    "ChronologicalSplitResult": (
        "split_spec:ChronologicalSplitSpec split_spec_pin:SpecPin splitter_version:str "
        "assignments:*ChronologicalSplitAssignment assignment_schema:DatasetSchema assignment_rows:*SplitAssignmentRow "
        "assignment_schema_id:str assignment_content_id:str split_result_id:str diagnostics:ChronologicalSplitDiagnostics"
    ),
    "ChronologicalSplitSpec": (
        "spec_schema_version:str name:str version:str boundary_timezone:str train_end_date:date validation_end_date:date "
        "test_end_date:date assignment_rule:str purge_rule:str incomplete_label_policy:str out_of_range_policy:str kind:str"
    ),
    "ChronologicalSplitAssignment": (
        "sample_key:str sample_version_id:str feature_window_close:datetime feature_window_close_date:date "
        "label_status:str actual_label_end_time:?datetime nominal_split:?str final_split:?str "
        "assignment_status:str reason_code:?str purge_boundary:?datetime"
    ),
    "ChronologicalSplitDiagnostics": (
        "sample_count:int assigned_count:int train_assigned_count:int validation_assigned_count:int test_assigned_count:int "
        "purged_count:int train_purged_count:int validation_purged_count:int excluded_count:int "
        "incomplete_label_excluded_count:int out_of_range_excluded_count:int"
    ),
    "MultiSourceCrossDaySampleAudit": (
        "sample_key:str bar_sample_version_id:str multi_source_sample_version_id:str code:str interval:str adjustment:str "
        "requested_session:str anchor_market_calendar_date:date feature_window_start:datetime feature_window_close:datetime "
        "dataset_as_of:?datetime feature_association_schema_id:str feature_association_content_id:str ts2_sample_id:str "
        "ts2_values_content_id:str observation_binding_id:str observation_values_content_id:str cross_day_sample_binding_id:str "
        "cross_day_values_content_id:str schedule_pin_id:str ts2_feature_status:str observation_feature_status:str "
        "label_status:str actual_label_end_time:?datetime matrix_eligible:bool matrix_present:bool "
        "split_feature_window_close_date:?date split_nominal_split:?str split_final_split:?str "
        "split_assignment_status:?str split_reason_code:?str split_purge_boundary:?datetime"
    ),
    "MultiSourceCrossDayCompletionSummary": (
        "complete_count:int incomplete_count:int missing_count:int entries:*MultiSourceCrossDayCompletionEntry"
    ),
    "MultiSourceCrossDayCompletionEntry": "code:str trade_date:date status:str reason_code:?str",
    "ImplementationSourceHash": "transform_ref:str source_sha256:str",
    "BuildReport": (
        "report_contract_version:str dataset_id:str requested_sample_count:int matrix_row_count:int "
        "feature_excluded_sample_count:int label_incomplete_sample_count:int complete_scope_count:int "
        "incomplete_scope_count:int missing_scope_count:int"
    ),
}

# Row dictionaries have the same declared projection as the corresponding record.
_DECLARATIONS["SplitAssignmentRow"] = _DECLARATIONS["ChronologicalSplitAssignment"]
_DECLARATIONS["TS2Features"] = (
    _DECLARATIONS["TS2FeatureExecutionResult"] + " implementation_source_hashes:*ImplementationSourceHash"
)
_SCHEMAS = MappingProxyType({
    name: tuple(tuple(field.split(":")) for field in declaration.split())
    for name, declaration in _DECLARATIONS.items()
})
del _DECLARATIONS


@dataclass(frozen=True, slots=True)
class _Recorded:
    """Untrusted recorded facts, deliberately not any upstream result type."""

    _schema_name: str
    _items: tuple

    def __getattr__(self, name):
        for key, value in self._items:
            if key == name:
                return value
        raise AttributeError(name)


def _typed(value, descriptor, *, decoding):
    if descriptor.startswith("?"):
        return None if value is None else _typed(value, descriptor[1:], decoding=decoding)
    if descriptor.startswith("*"):
        _require(type(value) is (list if decoding else tuple), "ARTIFACT_DECODE", "exact sequence required")
        result = tuple(_typed(v, descriptor[1:], decoding=decoding) for v in value)
        return result if decoding else list(result)
    if descriptor.startswith("("):
        shapes = descriptor[1:-1].split(",")
        _require(type(value) is (list if decoding else tuple) and len(value) == len(shapes),
                 "ARTIFACT_DECODE", "exact pair required")
        result = tuple(_typed(v, shape, decoding=decoding) for v, shape in zip(value, shapes))
        return result if decoding else list(result)
    if descriptor in _SCHEMAS:
        return _decode_record(descriptor, value) if decoding else _encode_record(value, descriptor)
    if descriptor == "datetime":
        return decode_timestamp(value) if decoding else timestamp_text(value)
    if descriptor == "date":
        if decoding:
            return decode_date(value)
        _require(type(value) is date, "ARTIFACT_DECODE", "exact date required")
        return value.isoformat()
    scalar_types = {"str": (str,), "bool": (bool,), "int": (int,), "float": (float,),
                    "number": (int, float), "dimension": (str, int, float),
                    "parameter": (str, int, float, bool, type(None))}
    _require(descriptor in scalar_types and type(value) in scalar_types[descriptor],
             "ARTIFACT_DECODE", "scalar differs from declared type: " + descriptor)
    canonical_json(value)
    return value


def _decode_record(kind, value):
    _require(kind in _SCHEMAS, "ARTIFACT_DECODE", "unknown record schema")
    schema = _SCHEMAS[kind]
    exact_fields(value, (name for name, _ in schema))
    return _Recorded(kind, tuple((name, _typed(value[name], shape, decoding=True)) for name, shape in schema))


def _encode_record(value, kind):
    _require(type(value) is _Recorded and value._schema_name == kind and kind in _SCHEMAS,
             "ARTIFACT_DECODE", "exact private recorded projection required")
    schema = _SCHEMAS[kind]
    _require(tuple(name for name, _ in value._items) == tuple(name for name, _ in schema),
             "ARTIFACT_DECODE", "recorded fields/order differ")
    return {name: _typed(member, shape, decoding=False)
            for (name, shape), (_, member) in zip(schema, value._items)}


def _fact_bytes(kind, records):
    _require(type(records) is tuple, "ARTIFACT_DECODE", "exact records tuple required")
    return canonical_json({"artifact_version": SERIALIZATION_FORMAT_VERSION,
                           "records": [_encode_record(record, kind) for record in records]})


def _read_facts(kind, data, *, singleton=False):
    payload = exact_fields(decode_json(data), ("artifact_version", "records"))
    _require(payload["artifact_version"] == SERIALIZATION_FORMAT_VERSION and type(payload["records"]) is list,
             "ARTIFACT_DECODE", "sidecar contract mismatch")
    _require(not singleton or len(payload["records"]) == 1, "ARTIFACT_DECODE", "singleton sidecar required")
    return tuple(_decode_record(kind, value) for value in payload["records"])


_SOURCE_MODULE_GROUPS = {
    "dataset.models": "DatasetScope DatasetSchema DatasetField CanonicalBuildPin SourceSnapshotPin GapReference SpecPin ImplementationPin",
    "canonical.reader": "VerifiedCanonicalBuild VerifiedCanonicalRequest GapBoundaryBars",
    "canonical.models": "CanonicalBar CanonicalSourceRef",
    "canonical.gaps": "GapRange",
    "dataset.pit_models": "PITAssemblyResult PITSample PITSampleRequest PITDiagnostics PITAssemblyDiagnostics",
    "ts2_feature.models": "TS2FeatureExecutionResult TS2FeatureSampleResult TS2FeatureValueResult",
    "dataset.spec_models": (
        "FeatureSpec SpecParameter SpecVersionRequirements LabelSpec LabelObservationWindow LabelHorizon CrossTradingDayPolicy"
    ),
    "observation.pit_models": (
        "ObservationPITAssemblyResult ObservationPITDecision ObservationDecisionEvidence ObservationBuildPin "
        "ObservationSnapshotPin ObservationSampleBinding ObservationPITFeatureBinding ObservationSourceSpec"
    ),
    "observation.models": (
        "ObservationContractPin ObservationCoverage ObservationScope ObservationDimension Observation "
        "ObservationSourceSnapshotInput ObservationSnapshotMember ObservationBuildIdentityInput"
    ),
    "observation.schema": "ObservationValueSchema ObservationValueField",
    "multi_source.feature_spec_models": "ObservationFeatureSpec",
    "multi_source.feature_models": (
        "ObservationFeatureExecutionResult ObservationFeatureSampleResult ObservationFeatureValueResult"
    ),
    "cross_day.schedule": "VerifiedTradingDaySchedule TradingDayRecord",
    "cross_day.models": (
        "CrossDayLabelDecision CrossDayLabelRowReference CrossDayLabelSlot CrossDayLabelSampleBinding "
        "CrossDayLabelGapProof CrossDayLabelValueResult"
    ),
    "dataset.split_models": (
        "ChronologicalSplitResult ChronologicalSplitSpec ChronologicalSplitAssignment ChronologicalSplitDiagnostics"
    ),
    "cross_day_dataset.models": (
        "MultiSourceCrossDaySampleAudit MultiSourceCrossDayCompletionSummary MultiSourceCrossDayCompletionEntry"
    ),
}
_SOURCE_MODULES = MappingProxyType({
    name: "market_vault." + module for module, names in _SOURCE_MODULE_GROUPS.items() for name in names.split()
})
del _SOURCE_MODULE_GROUPS
_OMITTED = MappingProxyType({
    "VerifiedCanonicalBuild": ("manifest_payload", "build_path"),
    "CanonicalBar": ("snapshot_file",),
    "CanonicalSourceRef": ("snapshot_file",),
})


def _snapshot_members(node, module, name, field_names):
    _require(type(node) is tuple and len(node) == 3 and node[:2] == (module, name),
             "ARTIFACT_AUTHORITY", "unexpected issuance snapshot record")
    pairs = node[2]
    _require(type(pairs) is tuple and all(type(p) is tuple and len(p) == 2 and type(p[0]) is str for p in pairs),
             "ARTIFACT_AUTHORITY", "invalid snapshot fields")
    values = dict(pairs)
    _require(len(values) == len(pairs) and set(values) == set(field_names),
             "ARTIFACT_AUTHORITY", "issuance snapshot fields differ")
    return values


def _snapshot_scalar(node):
    _require(type(node) is tuple and bool(node), "ARTIFACT_AUTHORITY", "invalid snapshot node")
    tag = node[0]
    if tag == "none":
        _require(node == ("none",), "ARTIFACT_AUTHORITY", "invalid null snapshot")
        return None
    if tag in ("str", "bool", "int"):
        _require(len(node) == 2 and type(node[1]) is {"str": str, "bool": bool, "int": int}[tag],
                 "ARTIFACT_AUTHORITY", "invalid scalar snapshot")
        return node[1]
    if tag == "float64":
        _require(len(node) == 2 and type(node[1]) is bytes and len(node[1]) == 8,
                 "ARTIFACT_AUTHORITY", "invalid float snapshot")
        return unpack("!d", node[1])[0]
    if tag == "date":
        _require(len(node) == 4 and all(type(v) is int for v in node[1:]),
                 "ARTIFACT_AUTHORITY", "invalid date snapshot")
        return date(*node[1:])
    if tag in ("datetime", "timestamp"):
        _require(len(node) == (2 if tag == "datetime" else 3) and (tag != "timestamp" or node[2] == 0),
                 "ARTIFACT_AUTHORITY", "non-microsecond snapshot timestamp")
        facts = node[1]
        _require(type(facts) is tuple and len(facts) == 9 and all(type(v) is int for v in facts[:8]),
                 "ARTIFACT_AUTHORITY", "invalid timestamp snapshot")
        tz = facts[8]
        _require(type(tz) is tuple and bool(tz), "ARTIFACT_AUTHORITY", "invalid snapshot timezone")
        if tz[0] == "timezone" and len(tz) == 5:
            zone = timezone(timedelta(days=tz[1], seconds=tz[2], microseconds=tz[3]), tz[4])
        elif tz == ("pytz-utc",):
            zone = timezone.utc
        elif tz[0] == "zoneinfo" and len(tz) == 2 and tz[1] in ("UTC", "America/New_York"):
            zone = ZoneInfo(tz[1])
        else:
            _require(False, "ARTIFACT_AUTHORITY", "unsupported snapshot timezone")
        return datetime(*facts[:7], tzinfo=zone, fold=facts[7]).astimezone(timezone.utc)
    _require(False, "ARTIFACT_AUTHORITY", "unexpected scalar snapshot tag")


def _snapshot_value(node, shape):
    if shape.startswith("?"):
        return None if node == ("none",) else _snapshot_value(node, shape[1:])
    if shape.startswith("*") or shape.startswith("("):
        _require(type(node) is tuple and len(node) == 2 and node[0] == "tuple" and type(node[1]) is tuple,
                 "ARTIFACT_AUTHORITY", "tuple snapshot required")
        if shape.startswith("*"):
            return tuple(_snapshot_value(v, shape[1:]) for v in node[1])
        shapes = shape[1:-1].split(",")
        _require(len(node[1]) == len(shapes), "ARTIFACT_AUTHORITY", "pair snapshot length differs")
        return tuple(_snapshot_value(v, s) for v, s in zip(node[1], shapes))
    if shape in _SCHEMAS:
        return _snapshot_projection(node, shape)
    value = _snapshot_scalar(node)
    _typed(value, shape, decoding=False)
    return value


def _snapshot_projection(node, kind):
    _require(kind in _SCHEMAS, "ARTIFACT_AUTHORITY", "unknown snapshot projection")
    schema = _SCHEMAS[kind]
    if kind in ("PITAssociationRow", "SplitAssignmentRow"):
        _require(type(node) is tuple and len(node) == 2 and node[0] == "mappingproxy",
                 "ARTIFACT_AUTHORITY", "recorded row requires snapshot mapping")
        pairs = tuple((_snapshot_scalar(key), value) for key, value in node[1])
        values = dict(pairs)
        _require(len(values) == len(pairs) and set(values) == {name for name, _ in schema},
                 "ARTIFACT_AUTHORITY", "row snapshot fields differ")
    else:
        _require(kind in _SOURCE_MODULES, "ARTIFACT_AUTHORITY", "projection requires explicit assembly")
        values = _snapshot_members(node, _SOURCE_MODULES[kind], kind,
                                   tuple(name for name, _ in schema) + _OMITTED.get(kind, ()))
    return _Recorded(kind, tuple((name, _snapshot_value(values[name], shape)) for name, shape in schema))
