"""Pure recorded-closure admission. No upstream execution or selection entry."""

from dataclasses import dataclass, fields, is_dataclass

from ..canonical.reader import VerifiedCanonicalBuild
from ..cross_day import _authority as canonical
from ..cross_day.assembly import CrossDayLabelAssemblyResult
from ..cross_day.execution import CrossDayLabelExecutionResult
from ..cross_day.registry import admit_specs, built_in_cross_day_label_registry
from ..cross_day.schedule import VerifiedTradingDaySchedule, admit_schedule
from ..dataset.models import DatasetScope, CanonicalBuildPin, SourceSnapshotPin, GapReference
from ..dataset.pit_models import PITAssemblyResult
from ..dataset.split_models import ChronologicalSplitSpec
from ..multi_source.feature_models import ObservationFeatureExecutionResult
from ..multi_source.feature_spec_models import normalize_specs
from ..multi_source.feature_registry import _preflight_registry, _resolve as resolve_observation
from ..observation.pit_models import ObservationPITAssemblyResult
from ..ts2_feature.models import TS2FeatureExecutionResult
from ..ts2_feature.execution import _specs, _resolve, _builds, _pit
from ..ts2_feature.registry import _registry
from ..ts2_feature._validation import TS2FeatureError
from ._label_closure import verify_labels
from ._observation_closure import admit_observation, verify_observation_features
from ._ts2_closure import verify_ts2
from ._validation import MultiSourceCrossDayDatasetError, checked_record, cutoff, records, require, require_immutable, stage


FIXED_COLUMNS = ("code", "sample_key", "sample_version_id", "feature_window_close",
                 "actual_label_end_time", "label_status", "dataset_as_of", "feature_window_close_date",
                 "nominal_split", "final_split", "assignment_status", "reason_code", "purge_boundary")
RESERVED_NAMES = frozenset(FIXED_COLUMNS + ("bar_sample_version_id", "multi_source_sample_version_id",
                                           "dataset_id", "status", "built_at", "schedule_pin_id"))


def _logical_build(build):
    # These two path-bearing fields and manifest bytes are descriptive A2/Canonical metadata.
    def logical(value):
        if is_dataclass(value):
            return tuple((f.name, logical(getattr(value, f.name))) for f in fields(value)
                         if f.name not in ("build_path", "snapshot_file", "manifest_payload"))
        if type(value) is tuple:
            return tuple(logical(v) for v in value)
        return value
    return logical(build)


def canonical_pins(builds):
    pins, gaps = [], []
    for build in builds:
        sources = tuple(SourceSnapshotPin(s.ingestion_run_id, s.physical_snapshot_hash, s.logical_source_rows_hash,
                        s.source_schema_version, s.requested_trade_date, s.requested_session)
                        for s in build.source_snapshot_provenance)
        pins.append(CanonicalBuildPin(build.canonical_build_id, build.canonical_content_id,
            build.canonical_builder_version, build.canonical_schema_version, build.materializer_version,
            build.gap_policy_version, build.gap_content_id, build.status, build.canonical_row_version_ids, sources))
        gaps.append(GapReference(build.canonical_build_id, build.gap_content_id, len(build.gap_ranges)))
    return tuple(pins), tuple(gaps)


@dataclass(frozen=True, slots=True)
class _Admitted:
    feature_pit: PITAssemblyResult
    ts2_features: TS2FeatureExecutionResult
    observation_pit: ObservationPITAssemblyResult
    observation_builds: tuple
    observation_input_proofs: tuple
    observation_feature_specs: tuple
    observation_features: ObservationFeatureExecutionResult
    cross_day_association: CrossDayLabelAssemblyResult
    cross_day_labels: CrossDayLabelExecutionResult
    schedule: VerifiedTradingDaySchedule
    scope: DatasetScope
    split_spec: ChronologicalSplitSpec
    dataset_as_of: object
    canonical_builds: tuple
    canonical_build_pins: tuple
    gap_references: tuple
    registries: tuple


def admit_inputs(*, feature_pit, ts2_features, observation_pit, observation_builds,
                 observation_feature_specs, observation_features, cross_day_association,
                 cross_day_labels, schedule, scope, split_spec, dataset_as_of):
    typed = ((feature_pit, PITAssemblyResult), (ts2_features, TS2FeatureExecutionResult),
             (observation_pit, ObservationPITAssemblyResult), (observation_features, ObservationFeatureExecutionResult),
             (cross_day_association, CrossDayLabelAssemblyResult), (cross_day_labels, CrossDayLabelExecutionResult),
             (schedule, VerifiedTradingDaySchedule), (scope, DatasetScope), (split_spec, ChronologicalSplitSpec))
    for value, cls in typed:
        require(type(value) is cls, "INPUT_TYPE", "exact " + cls.__name__ + " required")
    dataset_as_of = cutoff(dataset_as_of)
    with stage("SCOPE"):
        scope = checked_record(scope, DatasetScope, "SCOPE")
        require(scope.symbols and scope.trade_dates and scope.interval in canonical.INTERVAL_MINUTES
                and all(s.startswith("US.") for s in scope.symbols)
                and scope.adjustment == "NONE" and scope.requested_session == "RTH", "SCOPE", "unsupported Dataset scope")
    with stage("SPEC_CONTRACT"):
        specs = _specs(ts2_features.feature_specs)
        observation_specs = normalize_specs(observation_feature_specs)
        require(specs and observation_specs and cross_day_association.label_specs,
                "SPEC_CONTRACT", "all three spec families must be nonempty")
        split_spec = checked_record(split_spec, ChronologicalSplitSpec, "SPEC_CONTRACT")
        names = tuple(s.name for s in specs + observation_specs + cross_day_association.label_specs)
        require(len(set(names)) == len(names), "DUPLICATE_INPUT", "cross-family output collision")
        require(not set(names) & RESERVED_NAMES, "SPEC_CONTRACT", "reserved output name")
    with stage("IMPLEMENTATION_BINDING"):
        registrations = _registry()
        _preflight_registry()
        observation_regs = tuple(resolve_observation(s) for s in observation_specs)
        label_registry = built_in_cross_day_label_registry()
    with stage("SPEC_CONTRACT"):
        resolved = _resolve(specs, registrations)
        label_specs = admit_specs(cross_day_association.label_specs, label_registry)
    with stage("SCHEDULE_BINDING"):
        schedule = admit_schedule(schedule, dataset_as_of)
        require(schedule == cross_day_association.schedule and schedule == cross_day_labels.association.schedule,
                "SCHEDULE_BINDING", "schedule copies differ")
    with stage("PIT_BINDING"):
        feature_builds = records(cross_day_association.feature_builds, VerifiedCanonicalBuild,
                                 lambda b: b.canonical_build_id)
        label_builds = records(cross_day_association.label_builds, VerifiedCanonicalBuild,
                               lambda b: b.canonical_build_id)
        for build in feature_builds + label_builds:
            request = build.normalized_request
            require(request.source_schema_version == "10.9-mv-ts2"
                    and build.canonical_schema_version == "market-bars-canonical-schema-v1"
                    and all(b.source_schema_version == "10.9-mv-ts2" for b in build.bars)
                    and set(request.symbols) <= set(scope.symbols)
                    and (request.interval, request.adjustment, request.requested_session) ==
                    (scope.interval, scope.adjustment, scope.requested_session), "SCOPE", "Canonical boundary outside scope")
        by_id = {}
        for build in feature_builds + label_builds:
            previous = by_id.get(build.canonical_build_id)
            require(previous is None or _logical_build(previous) == _logical_build(build),
                    "PIT_BINDING", "conflicting overlapping Canonical build")
            by_id[build.canonical_build_id] = build
        union, union_rows = _builds(tuple(by_id[k] for k in sorted(by_id)))
        features = tuple(b for b in union if b.canonical_build_id in {v.canonical_build_id for v in feature_builds})
        feature_rows = canonical.reconcile(features)
        try:
            pit = _pit(feature_pit, features, feature_rows, dataset_as_of)
        except TS2FeatureError as exc:
            if exc.reason_code in ("SCOPE", "CLOCK_AUTHORITY"):
                raise MultiSourceCrossDayDatasetError(exc.reason_code, str(exc)) from exc
            raise
        require(tuple(p.canonical_build_id for p in pit.canonical_build_pins) ==
                tuple(b.canonical_build_id for b in features), "PIT_BINDING", "full Feature build boundary differs")
        for sample in pit.samples:
            req = sample.request
            require(req.code in scope.symbols and req.anchor_market_calendar_date in scope.trade_dates
                    and (req.interval, req.adjustment, req.requested_session) ==
                    (scope.interval, scope.adjustment, scope.requested_session), "SCOPE", "PIT request outside scope")
    with stage("TS2_FEATURE_BINDING"):
        verify_ts2(ts2_features, pit, features, feature_rows, resolved, registrations, dataset_as_of)
    with stage("A3_BINDING"):
        observations, proofs, decisions, samples, selected = admit_observation(
            pit, observation_pit, observation_builds, observation_specs)
    with stage("OBSERVATION_FEATURE_BINDING"):
        verify_observation_features(observation_features, observation_specs, observation_regs, decisions, samples, selected)
    with stage("CROSS_DAY_BINDING"):
        verify_labels(cross_day_association, cross_day_labels, pit, observation_pit, schedule,
                      union, union_rows, label_specs, dataset_as_of)
    pins, gaps = canonical_pins(union)
    admitted = _Admitted(pit, ts2_features, observation_pit, observations, proofs, observation_specs,
                          observation_features, cross_day_association, cross_day_labels, schedule, scope, split_spec,
                          dataset_as_of, union, pins, gaps, (registrations, observation_regs, label_registry))
    require_immutable(admitted)
    return admitted
