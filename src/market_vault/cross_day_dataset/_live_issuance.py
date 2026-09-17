"""Closed issuance snapshots and a reload invalidation anchor; never enrollment."""

from datetime import date, datetime, timezone
from pathlib import PosixPath, WindowsPath
from struct import pack
from types import MappingProxyType
from zoneinfo import ZoneInfo

from pandas import Timestamp
from pytz import UTC as _pytz_utc

import market_vault.cross_day_dataset.models as _result_models
import market_vault.dataset.models as _dataset_models
import market_vault.canonical.reader as _canonical_reader
import market_vault.canonical.models as _canonical_models
import market_vault.dataset.pit_models as _pit_models
import market_vault.ts2_feature.models as _ts2_models
import market_vault.dataset.spec_models as _spec_models
import market_vault.observation.pit_models as _observation_pit_models
import market_vault.observation.models as _observation_models
import market_vault.observation.artifact_models as _observation_artifact_models
import market_vault.observation.schema as _observation_schema
import market_vault.multi_source.feature_spec_models as _observation_feature_specs
import market_vault.multi_source.feature_models as _observation_features
import market_vault.cross_day.assembly as _label_assembly
import market_vault.cross_day.schedule as _schedule
import market_vault.cross_day.models as _label_models
import market_vault.cross_day.execution as _label_execution
import market_vault.dataset.split_models as _split_models
import market_vault.canonical.gaps as _gaps
from ._validation import require

# Execution reload rotates this anchor. Saved closures retain their old generation.
_generation = object()

# Literal declared fields of exact, sealed record types; not a general serializer.
_FIELDS = MappingProxyType({
    _result_models.MultiSourceCrossDayDatasetResult: (
        "identity_input dataset_id scope dataset_as_of schema rows sample_audit completion split_result "
        "feature_pit ts2_features observation_pit observation_builds observation_feature_specs "
        "observation_features cross_day_association cross_day_labels schedule status"
    ).split(),
    _result_models.MultiSourceCrossDayDatasetIdentityInput: (
        "scope dataset_as_of schema rows canonical_builds canonical_build_pins gap_references feature_pit "
        "ts2_features observation_pit observation_builds observation_input_proofs observation_feature_specs "
        "observation_features cross_day_association cross_day_labels schedule split_result sample_audit "
        "completion"
    ).split(),
    _dataset_models.DatasetScope: (
        "symbols trade_dates adjustment interval requested_session"
    ).split(),
    _dataset_models.DatasetSchema: (
        "fields"
    ).split(),
    _dataset_models.DatasetField: (
        "name logical_type nullable"
    ).split(),
    _canonical_reader.VerifiedCanonicalBuild: (
        "canonical_build_id canonical_content_id resolution_content_id gap_content_id "
        "canonical_builder_version canonical_schema_version materializer_version gap_policy_version status "
        "normalized_request bars canonical_row_version_ids source_snapshot_provenance gap_ranges "
        "gap_boundaries gap_count manifest_payload build_path"
    ).split(),
    _canonical_reader.VerifiedCanonicalRequest: (
        "symbols trade_dates interval requested_session adjustment source_schema_version"
    ).split(),
    _canonical_models.CanonicalBar: (
        "canonical_bar_key canonical_row_version_id dataset_kind code interval adjustment event_time "
        "market_available_at archive_available_at open high low close volume extra_fields ingestion_run_id "
        "physical_snapshot_hash logical_source_rows_hash source_schema_version canonical_builder_version "
        "requested_trade_date requested_session market_calendar_date session snapshot_file"
    ).split(),
    _canonical_models.CanonicalSourceRef: (
        "ingestion_run_id physical_snapshot_hash logical_source_rows_hash source_schema_version "
        "snapshot_file requested_trade_date requested_session"
    ).split(),
    _dataset_models.CanonicalBuildPin: (
        "canonical_build_id canonical_content_id canonical_builder_version canonical_schema_version "
        "materializer_version gap_policy_version gap_content_id status canonical_row_version_ids "
        "source_snapshots"
    ).split(),
    _dataset_models.SourceSnapshotPin: (
        "ingestion_run_id physical_snapshot_hash logical_source_rows_hash source_schema_version "
        "requested_trade_date requested_session"
    ).split(),
    _dataset_models.GapReference: (
        "canonical_build_id gap_content_id gap_range_count"
    ).split(),
    _pit_models.PITAssemblyResult: (
        "samples canonical_build_pins canonical_row_version_ids gap_references association_schema "
        "association_rows association_schema_id association_content_id diagnostics"
    ).split(),
    _pit_models.PITSample: (
        "sample_key sample_version_id request dataset_as_of feature_canonical_row_version_ids "
        "label_canonical_row_version_ids considered_canonical_build_ids diagnostics"
    ).split(),
    _pit_models.PITSampleRequest: (
        "code interval adjustment requested_session anchor_market_calendar_date feature_window_start "
        "feature_window_close label_window_start label_window_close"
    ).split(),
    _pit_models.PITDiagnostics: (
        "feature_candidate_count feature_selected_count feature_market_future_excluded_count "
        "feature_archive_future_excluded_count label_candidate_count label_selected_count "
        "label_market_future_excluded_count label_archive_future_excluded_count known_feature_gap_ids "
        "known_label_gap_ids empty_observation_window"
    ).split(),
    _pit_models.PITAssemblyDiagnostics: (
        "sample_count total_feature_rows total_label_rows feature_market_future_excluded_count "
        "feature_archive_future_excluded_count label_market_future_excluded_count "
        "label_archive_future_excluded_count considered_canonical_build_ids"
    ).split(),
    _ts2_models.TS2FeatureExecutionResult: (
        "execution_contract_version registry_contract_version feature_association_content_id "
        "feature_association_schema_id dataset_as_of considered_canonical_build_ids feature_specs "
        "feature_spec_pins registry_implementation_pins samples status"
    ).split(),
    _spec_models.FeatureSpec: (
        "spec_schema_version name version output input_canonical_fields transform_ref parameters "
        "requirements kind"
    ).split(),
    _spec_models.SpecParameter: (
        "name value"
    ).split(),
    _spec_models.SpecVersionRequirements: (
        "canonical_schema_versions source_schema_versions"
    ).split(),
    _dataset_models.SpecPin: (
        "kind name version content_sha256"
    ).split(),
    _dataset_models.ImplementationPin: (
        "name version content_sha256"
    ).split(),
    _ts2_models.TS2FeatureSampleResult: (
        "sample_key bar_sample_version_id values status"
    ).split(),
    _ts2_models.TS2FeatureValueResult: (
        "sample_key bar_sample_version_id feature_name spec_pin implementation_pin feature_window_close "
        "dataset_as_of considered_canonical_build_ids candidate_canonical_row_version_ids "
        "consumed_canonical_row_version_ids status value reason_code"
    ).split(),
    _observation_pit_models.ObservationPITAssemblyResult: (
        "decisions evidence sample_bindings bindings observation_association_content_id "
        "sample_binding_content_id combined_association_content_id bar_association_content_id "
        "bar_association_schema_id"
    ).split(),
    _observation_pit_models.ObservationPITDecision: (
        "sample_key bar_sample_version_id feature_spec_pin_id observation_source_spec_id T A "
        "considered_observation_builds_digest status reason archive_limited selected_observation_key "
        "selected_observation_version_id selected_observation_build_id selected_source_snapshot_id "
        "selected_known_at_authority_id selected_event_time selected_known_at selected_archive_available_at "
        "scoped_version_count future_known_excluded_count archive_future_excluded_count eligible_key_count "
        "alignment_candidate_count"
    ).split(),
    _observation_pit_models.ObservationDecisionEvidence: (
        "sample_key feature_spec_pin_id build_pins coverages"
    ).split(),
    _observation_pit_models.ObservationBuildPin: (
        "observation_build_id observation_content_id observation_schema_version coverage_id "
        "coverage_proof_available_at status authority_evidence_ids provider_contracts normalizations "
        "source_snapshots selected_observation_version_ids"
    ).split(),
    _observation_models.ObservationContractPin: (
        "version content_id"
    ).split(),
    _observation_pit_models.ObservationSnapshotPin: (
        "source_snapshot_id source_content_sha256 provider_id source_kind provider_contract_version "
        "provider_contract_content_id normalized_request_id acquisition_receipt_id "
        "acquisition_receipt_content_id completed_possession_at"
    ).split(),
    _observation_models.ObservationCoverage: (
        "scope provider_contract effective_start effective_end knowledge_start knowledge_end "
        "normalized_request_id request_completion_evidence_id request_pages_complete missing_semantics "
        "missing_semantics_content_id revision_inventory_content_id revision_inventory_complete"
    ).split(),
    _observation_models.ObservationScope: (
        "provider_id source_kind entity_id observation_name dimensions"
    ).split(),
    _observation_models.ObservationDimension: (
        "name logical_type value"
    ).split(),
    _observation_pit_models.ObservationSampleBinding: (
        "sample_key bar_sample_version_id observation_binding_id multi_source_sample_version_id"
    ).split(),
    _observation_pit_models.ObservationPITFeatureBinding: (
        "feature_spec_pin source_spec feature_spec_pin_id observation_source_spec_id"
    ).split(),
    _observation_pit_models.ObservationSourceSpec: (
        "provider_id source_kind observation_name dimensions entity_binding entity_id code_entity_map "
        "input_field_names value_schema_id provider_contract_version provider_contract_content_id "
        "normalization_version normalization_content_id known_at_authority_policy_version "
        "known_at_authority_policy_content_id alignment exact_target_binding max_age_us missing_policy"
    ).split(),
    _observation_artifact_models.VerifiedObservationBuild: (
        "observation_build_id observation_content_id status rows source_snapshots authority_evidence_ids "
        "provider_contracts normalizations coverage created_at manifest_payload build_dir"
    ).split(),
    _observation_models.Observation: (
        "provider_id source_kind entity_id observation_name dimensions event_time event_period_start "
        "value_schema values value_status known_at known_at_authority_id archive_available_at "
        "source_snapshot_id source_content_sha256 provider_contract_version provider_contract_content_id "
        "normalization_version normalization_content_id revision_id supersedes_revision_id value_schema_id "
        "observation_key observation_version_id"
    ).split(),
    _observation_schema.ObservationValueSchema: (
        "fields"
    ).split(),
    _observation_schema.ObservationValueField: (
        "name logical_type unit representation"
    ).split(),
    _observation_models.ObservationSourceSnapshotInput: (
        "provider_id source_kind provider_contract normalized_request_id source_content_sha256 "
        "acquisition_receipt_id acquisition_receipt_content_id completed_possession_at members"
    ).split(),
    _observation_feature_specs.ObservationFeatureSpec: (
        "spec_schema_version name version output source_spec transform_ref parameters kind"
    ).split(),
    _observation_features.ObservationFeatureExecutionResult: (
        "samples feature_spec_pins implementation_pins execution_contract_version"
    ).split(),
    _observation_features.ObservationFeatureSampleResult: (
        "sample_key multi_source_sample_version_id status values"
    ).split(),
    _observation_features.ObservationFeatureValueResult: (
        "sample_key multi_source_sample_version_id feature_name spec_pin implementation_pin decision_id "
        "status value reason_code consumed_observation_version_id"
    ).split(),
    _label_assembly.CrossDayLabelAssemblyResult: (
        "feature_pit feature_builds label_builds schedule label_specs dataset_as_of decisions "
        "sample_bindings observation_pit"
    ).split(),
    _schedule.VerifiedTradingDaySchedule: (
        "schedule_schema_version market requested_session market_timezone coverage_start_date "
        "coverage_end_date daily_records source_snapshot_id source_content_hash calendar_contract_version "
        "normalization_version coverage_completion_evidence_id coverage_complete archive_available_at"
    ).split(),
    _schedule.TradingDayRecord: (
        "market_calendar_date day_status session_open session_close session_profile"
    ).split(),
    _spec_models.LabelSpec: (
        "spec_schema_version name version output input_canonical_fields transform_ref parameters "
        "requirements observation_window horizon alignment_rule missing_data_policy cross_trading_day kind"
    ).split(),
    _spec_models.LabelObservationWindow: (
        "unit start_offset end_offset"
    ).split(),
    _spec_models.LabelHorizon: (
        "unit value"
    ).split(),
    _spec_models.CrossTradingDayPolicy: (
        "allow boundary_rule"
    ).split(),
    _label_models.CrossDayLabelDecision: (
        "sample_key bar_sample_version_id label_spec_pin_id schedule_pin_id dataset_as_of code interval "
        "adjustment requested_session feature_window_close anchor_market_calendar_date anchor_event_time "
        "anchor_slot anchor required_slots considered_canonical_build_ids selected_rows "
        "rejected_archive_rows absence_proofs status reason_code archive_limited actual_label_end_time"
    ).split(),
    _label_models.CrossDayLabelRowReference: (
        "offset canonical_bar_key canonical_row_version_id backing_canonical_build_ids event_time "
        "market_available_at archive_available_at"
    ).split(),
    _label_models.CrossDayLabelSlot: (
        "offset market_calendar_date event_time session_open session_close slot_fits"
    ).split(),
    _label_models.CrossDayLabelSampleBinding: (
        "sample_key bar_sample_version_id multi_source_sample_version_id schedule_pin_id decision_ids"
    ).split(),
    _label_execution.CrossDayLabelExecutionResult: (
        "association implementation_pins implementation_source_hashes values"
    ).split(),
    _label_models.CrossDayLabelValueResult: (
        "sample_key bar_sample_version_id multi_source_sample_version_id label_name spec_pin "
        "implementation_pin schedule_pin_id decision_id anchor_canonical_row_version_id consumed_rows "
        "status value reason_code actual_label_end_time"
    ).split(),
    _split_models.ChronologicalSplitResult: (
        "split_spec split_spec_pin splitter_version assignments assignment_schema assignment_rows "
        "assignment_schema_id assignment_content_id split_result_id diagnostics"
    ).split(),
    _split_models.ChronologicalSplitSpec: (
        "spec_schema_version name version boundary_timezone train_end_date validation_end_date "
        "test_end_date assignment_rule purge_rule incomplete_label_policy out_of_range_policy kind"
    ).split(),
    _split_models.ChronologicalSplitAssignment: (
        "sample_key sample_version_id feature_window_close feature_window_close_date label_status "
        "actual_label_end_time nominal_split final_split assignment_status reason_code purge_boundary"
    ).split(),
    _split_models.ChronologicalSplitDiagnostics: (
        "sample_count assigned_count train_assigned_count validation_assigned_count test_assigned_count "
        "purged_count train_purged_count validation_purged_count excluded_count "
        "incomplete_label_excluded_count out_of_range_excluded_count"
    ).split(),
    _result_models.MultiSourceCrossDaySampleAudit: (
        "sample_key bar_sample_version_id multi_source_sample_version_id code interval adjustment "
        "requested_session anchor_market_calendar_date feature_window_start feature_window_close "
        "dataset_as_of feature_association_schema_id feature_association_content_id ts2_sample_id "
        "ts2_values_content_id observation_binding_id observation_values_content_id "
        "cross_day_sample_binding_id cross_day_values_content_id schedule_pin_id ts2_feature_status "
        "observation_feature_status label_status actual_label_end_time matrix_eligible matrix_present "
        "split_feature_window_close_date split_nominal_split split_final_split split_assignment_status "
        "split_reason_code split_purge_boundary"
    ).split(),
    _result_models.MultiSourceCrossDayCompletionSummary: (
        "complete_count incomplete_count missing_count entries"
    ).split(),
    _result_models.MultiSourceCrossDayCompletionEntry: (
        "code trade_date status reason_code"
    ).split(),
    _gaps.GapRange: (
        "gap_id gap_policy_version dataset_kind code interval adjustment market_calendar_date session "
        "previous_event_time next_event_time missing_from_event_time missing_to_event_time "
        "missing_bar_count"
    ).split(),
    _canonical_reader.GapBoundaryBars: (
        "gap_id previous_archive_available_at next_market_available_at next_archive_available_at"
    ).split(),
    _observation_models.ObservationSnapshotMember: (
        "relative_name byte_size sha256"
    ).split(),
    _label_models.CrossDayLabelGapProof: (
        "offset gap_id backing_canonical_build_ids previous_canonical_row_version_id "
        "next_canonical_row_version_id missing_from_event_time missing_to_event_time "
        "proof_archive_available_at"
    ).split(),
})
_FIELDS = MappingProxyType({cls: tuple(names) for cls, names in _FIELDS.items()})
_RESULT = _result_models.MultiSourceCrossDayDatasetResult


def _capture(result):
    """Return detached typed values and original non-scalar references, excluding root."""
    references, active, memo = [], set(), {}

    def timezone_facts(tz):
        if tz is None:
            return ("naive",)
        if type(tz) is timezone:
            offset = tz.utcoffset(None)
            return ("timezone", offset.days, offset.seconds, offset.microseconds, tz.tzname(None))
        if type(tz) is ZoneInfo:
            return ("zoneinfo", tz.key)
        if tz is _pytz_utc:
            return ("pytz-utc",)
        require(False, "RESULT_AUTHORITY", "unsupported snapshot timezone")

    def visit(value, *, root=False):
        cls = type(value)
        if value is None:
            return ("none",)
        if cls is bool:
            return ("bool", value)
        if cls is int:
            return ("int", value)
        if cls is str:
            return ("str", value)
        if cls is bytes:
            return ("bytes", value)
        if cls is float:
            return ("float64", pack("!d", value))
        if cls is date:
            return ("date", value.year, value.month, value.day)
        if cls is datetime or cls is Timestamp:
            facts = (value.year, value.month, value.day, value.hour, value.minute,
                     value.second, value.microsecond, value.fold, timezone_facts(value.tzinfo))
            return ("datetime", facts) if cls is datetime else ("timestamp", facts, value.nanosecond)
        names = next((names for known, names in _FIELDS.items() if cls is known), None)
        require(cls is tuple or cls is MappingProxyType or cls is PosixPath or cls is WindowsPath
                or names is not None, "RESULT_AUTHORITY", "unsupported snapshot graph type")
        require(root or value is not result, "RESULT_AUTHORITY", "snapshot references result")
        key = id(value)
        require(key not in active, "RESULT_AUTHORITY", "cyclic snapshot graph")
        # Bind every encountered edge, including aliases to already captured nodes.
        if not root:
            references.append(value)
        if key in memo:
            return memo[key]
        active.add(key)
        if cls is tuple:
            facts = ("tuple", tuple(visit(v) for v in value))
        elif cls is MappingProxyType:
            facts = ("mappingproxy", tuple((visit(k), visit(v)) for k, v in value.items()))
        elif cls is PosixPath or cls is WindowsPath:
            parts = value.parts
            require(type(parts) is tuple and all(type(part) is str for part in parts),
                    "RESULT_AUTHORITY", "unsupported snapshot path parts")
            facts = ("posix-path" if cls is PosixPath else "windows-path", parts)
        else:
            facts = (cls.__module__, cls.__name__,
                     tuple((name, visit(getattr(value, name))) for name in names))
        active.remove(key)
        memo[key] = facts
        return facts

    require(type(result) is _RESULT, "RESULT_AUTHORITY", "exact live result required")
    snapshot = visit(result, root=True)
    return snapshot, tuple(references)


def _same_capture(result, snapshot, references):
    current, nodes = _capture(result)
    require(len(nodes) == len(references) and all(a is b for a, b in zip(nodes, references)),
            "RESULT_AUTHORITY", "issued reference graph changed")
    require(current == snapshot, "RESULT_AUTHORITY", "issued typed snapshot changed")
