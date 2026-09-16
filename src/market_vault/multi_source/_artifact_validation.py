"""Pure recorded-authority closure. Never executes PIT or Feature/Label code."""

from dataclasses import fields
from datetime import timedelta

from ..dataset.artifact_serialization import feature_spec_artifact, label_spec_artifact, split_spec_artifact, parse_split_spec_artifact
from ..dataset.content import dataset_schema_id, logical_dataset_content_id
from ..dataset.models import ImplementationPin
from ..dataset.pit import pit_association_schema_id, pit_association_content_id
from ..dataset.specs import parse_feature_spec, parse_label_spec, feature_label_spec_pin
from ..dataset.split_models import ChronologicalSplitSample, chronological_split_spec_pin
from ..dataset.splits import assign_chronological_splits
from ..observation.models import ObservationContractPin
from ..observation.pit_models import ObservationPITDecision, ObservationSampleBinding
from ..observation.pit_identity import (
    feature_spec_pin_id, observation_decision_id, considered_observation_builds_digest, observation_binding_id,
    multi_source_sample_version_id, observation_association_content_id, sample_binding_content_id,
    combined_association_content_id,
)
from ._artifact_schema import physical_values
from ._orchestration_closure import normalize_spec_families, derive_schema, completion
from ._serialization import canonical_json, require
from .feature_specs import parse_observation_feature_spec, serialize_observation_feature_spec, observation_feature_spec_pin, observation_feature_binding
from .feature_models import ObservationFeatureValueResult, ObservationFeatureSampleResult, ObservationFeatureExecutionResult
from .feature_identity import observation_feature_values_content_id
from .identity import multi_source_dataset_id


def parse_specs(files, identity):
    families = []
    for pins, prefix, parser, serializer, pin_fn in (
        (identity.bar_feature_specs, "feature_specs/bar", parse_feature_spec, feature_spec_artifact, feature_label_spec_pin),
        (identity.observation_feature_specs, "feature_specs/observation", parse_observation_feature_spec, serialize_observation_feature_spec, observation_feature_spec_pin),
        (identity.label_specs, "label_specs", parse_label_spec, label_spec_artifact, feature_label_spec_pin),
    ):
        specs = []
        for pin in pins:
            raw = files[prefix + "/" + pin.content_sha256 + ".yaml"]
            spec = parser(raw.decode("utf-8"))
            require(serializer(spec) == raw and pin_fn(spec) == pin, "noncanonical spec artifact or pin mismatch")
            specs.append(spec)
        families.append(tuple(specs))
    bar, observation, labels = normalize_spec_families(*families)
    split = parse_split_spec_artifact(files["split_spec.yaml"].decode("utf-8"))
    require(split_spec_artifact(split) == files["split_spec.yaml"] and chronological_split_spec_pin(split) == identity.split_spec,
            "split artifact/pin mismatch")
    refs = {s.transform_ref for s in bar + observation + labels}
    require({p.name for p in identity.implementations} == refs and all(p.content_sha256 is not None for p in identity.implementations),
            "exact implementation pin set mismatch")
    by_feature = {s.name: s for s in bar}
    by_label = {s.name: s for s in labels}
    for audit in identity.sample_audit:
        for v in audit.bar_feature_values + audit.label_values:
            spec = (by_feature if v.spec_pin.kind == "FEATURE" else by_label)[v.spec_pin.name]
            require(v.implementation_pin.name == spec.transform_ref, "audit implementation/spec mismatch")
    return bar, observation, labels, split


def verify_bar(identity, rows):
    audit = {a.sample_key: a for a in identity.sample_audit}
    pins = {p.canonical_build_id: p for p in identity.canonical_builds}
    expected = {(a.sample_key, role, pos): version for a in audit.values()
        for role, versions in (("FEATURE", a.feature_canonical_row_version_ids), ("LABEL", a.label_canonical_row_version_ids))
        for pos, version in enumerate(versions)}
    require({(r["sample_key"], r["role"], r["position"]) for r in rows} == set(expected), "bar association positions/cardinality mismatch")
    by_version = {}
    for r in rows:
        a = audit[r["sample_key"]]
        require(r["sample_version_id"] == a.bar_sample_version_id and r["code"] == a.request.code and
            r["canonical_row_version_id"] == expected[(a.sample_key, r["role"], r["position"])] and
            r["canonical_build_id"] in a.considered_canonical_build_ids and
            r["canonical_row_version_id"] in pins[r["canonical_build_id"]].canonical_row_version_ids,
            "bar association provenance mismatch")
        start, end = ((a.request.feature_window_start, a.request.feature_window_close) if r["role"] == "FEATURE"
                      else (a.request.label_window_start, a.request.label_window_close))
        require(start is not None and end is not None and start <= r["event_time"] < end and
            r["market_available_at"] <= end and (identity.dataset_as_of is None or r["archive_available_at"] <= identity.dataset_as_of),
            "bar association clock/window mismatch")
        facts = tuple(r[n] for n in ("canonical_bar_key", "code", "event_time", "market_available_at", "archive_available_at"))
        previous = by_version.setdefault(r["canonical_row_version_id"], facts)
        require(previous == facts, "conflicting bar version facts")
    require(set(identity.canonical_row_version_ids) == set(expected.values()), "Canonical row pin set mismatch")
    for a in audit.values():
        for role in ("FEATURE", "LABEL"):
            selected = [r for r in rows if r["sample_key"] == a.sample_key and r["role"] == role]
            require([(r["event_time"], r["canonical_bar_key"], r["canonical_row_version_id"]) for r in selected] ==
                sorted((r["event_time"], r["canonical_bar_key"], r["canonical_row_version_id"]) for r in selected), "bar role order mismatch")
        for value in a.label_values:
            ids = value.consumed_label_canonical_row_version_ids
            require(value.actual_label_end_time == (by_version[ids[-1]][3] if ids else None), "Label end is not last consumed market time")
    require(pit_association_schema_id() == identity.bar_association_schema_id and
            pit_association_content_id(rows) == identity.bar_association_content_id, "bar association identity mismatch")


def _coverage(pairs, start, end, decision, earliest=None):
    intervals = []
    for p, c in pairs:
        if (c.request_pages_complete and c.revision_inventory_complete and c.knowledge_start <= decision.T <= c.knowledge_end
                and (earliest is None or c.knowledge_start <= earliest)
                and (decision.A is None or p.coverage_proof_available_at <= decision.A)):
            lo, hi = max(start, c.effective_start), min(end, c.effective_end)
            if lo <= hi:
                intervals.append((lo, hi))
    cursor = start
    for lo, hi in sorted(intervals):
        if lo > cursor:
            break
        if hi >= end:
            return
        if hi >= cursor:
            cursor = hi + timedelta(microseconds=1)
    require(False, "recorded coverage does not prove required continuous domain")


def _proof(decision, evidence, source, audit):
    entity = source.entity_id if source.entity_binding == "EXACT_ENTITY" else dict(source.code_entity_map)[audit.request.code]
    provider = ObservationContractPin(source.provider_contract_version, source.provider_contract_content_id)
    normalizer = ObservationContractPin(source.normalization_version, source.normalization_content_id)
    pairs = tuple(zip(evidence.build_pins, evidence.coverages))
    selected = decision.selected_observation_version_id
    containing = []
    for pin, cov in pairs:
        require(cov.scope == source.scope(entity) and cov.provider_contract == provider and provider in pin.provider_contracts
            and normalizer in pin.normalizations and source.known_at_authority_policy_content_id in pin.authority_evidence_ids,
            "Observation source/proof scope or contract mismatch")
        require(cov.request_pages_complete and cov.revision_inventory_complete, "incomplete Observation coverage")
        require(set(pin.selected_observation_version_ids) <= ({selected} if selected is not None else set()), "unexpected selected membership")
        for snapshot in pin.source_snapshots:
            require(snapshot.provider_id == source.provider_id and snapshot.source_kind == source.source_kind and
                snapshot.provider_contract_version == provider.version and snapshot.provider_contract_content_id == provider.content_id and
                snapshot.normalized_request_id == cov.normalized_request_id and snapshot.completed_possession_at <= pin.coverage_proof_available_at,
                "snapshot/source/coverage cross-binding mismatch")
        if selected in pin.selected_observation_version_ids:
            containing.append(pin)
            require(pin.status == "COMPLETE" and decision.selected_known_at_authority_id in pin.authority_evidence_ids,
                    "selected authority not pinned")
            snapshots = [s for s in pin.source_snapshots if s.source_snapshot_id == decision.selected_source_snapshot_id]
            require(len(snapshots) == 1 and snapshots[0].completed_possession_at <= decision.selected_archive_available_at <= pin.coverage_proof_available_at,
                    "selected snapshot/possession clock mismatch")
    require(considered_observation_builds_digest(evidence.build_pins) == decision.considered_observation_builds_digest,
            "considered proof digest mismatch")
    latest = source.alignment == "LATEST_EFFECTIVE_AT_OR_BEFORE"
    target = decision.T if source.exact_target_binding == "FEATURE_WINDOW_CLOSE" else audit.request.feature_window_start
    fresh = decision.T - timedelta(microseconds=source.max_age_us)
    _coverage(pairs, fresh if latest else target, decision.T if latest else target, decision)
    if selected is not None:
        require(decision.alignment_candidate_count > 0, "selected decision has no candidate")
        require(containing and decision.selected_observation_build_id == min(p.observation_build_id for p in containing),
                "selected representative/membership mismatch")
        require(latest or decision.selected_event_time == target, "selected exact target mismatch")
        _coverage(pairs, decision.selected_event_time, decision.selected_event_time, decision, decision.selected_known_at)
        if latest and decision.selected_event_time < fresh:
            _coverage(pairs, decision.selected_event_time, decision.T, decision)
        require(decision.status != "COMPLETE" or decision.selected_event_time >= fresh, "COMPLETE selected row is stale")
        require(decision.reason != "STALE" or decision.selected_event_time < fresh, "STALE selected row is fresh")
    else:
        require(decision.alignment_candidate_count == 0, "unselected decision has alignment candidates")
    require(decision.reason != "ARCHIVE_FUTURE" or decision.A is not None and decision.archive_limited
            and decision.archive_future_excluded_count > 0, "invalid archive-future evidence")
    require(decision.reason != "FUTURE_KNOWN" or decision.future_known_excluded_count > 0, "invalid future-known evidence")
    require(source.missing_policy != "FAIL" or decision.status == "COMPLETE", "excluded decision violates missing policy")


def verify_sidecar(identity, observation_specs, decision_rows, binding_rows):
    decisions = tuple(ObservationPITDecision(**r) for r in decision_rows)
    bindings = tuple(ObservationSampleBinding(**r) for r in binding_rows)
    sources = {b.feature_spec_pin_id: b for b in map(observation_feature_binding, observation_specs)}
    audit = {a.sample_key: a for a in identity.sample_audit}
    expected = {(key, pin) for key in audit for pin in sources}
    require({(d.sample_key, d.feature_spec_pin_id) for d in decisions} == expected, "decision cardinality mismatch")
    require({b.sample_key for b in bindings} == set(audit), "sample binding cardinality mismatch")
    evidence = {(e.sample_key, e.feature_spec_pin_id): e for e in identity.observation_evidence}
    for d in decisions:
        a, source = audit[d.sample_key], sources[d.feature_spec_pin_id]
        require(d.bar_sample_version_id == a.bar_sample_version_id and d.T == a.request.feature_window_close
                and d.A == identity.dataset_as_of and d.observation_source_spec_id == source.observation_source_spec_id,
                "decision/sample/source linkage mismatch")
        _proof(d, evidence[(d.sample_key, d.feature_spec_pin_id)], source.source_spec, a)
    for b in bindings:
        digest = observation_binding_id(tuple(d for d in decisions if d.sample_key == b.sample_key))
        require(b.bar_sample_version_id == audit[b.sample_key].bar_sample_version_id and b.observation_binding_id == digest and
            b.multi_source_sample_version_id == multi_source_sample_version_id(b.sample_key, b.bar_sample_version_id, digest),
            "sample binding identity mismatch")
    observation_id, sample_id = observation_association_content_id(decisions), sample_binding_content_id(bindings)
    require(observation_id == identity.observation_association_content_id and sample_id == identity.sample_binding_content_id and
        combined_association_content_id(identity.bar_association_content_id, identity.bar_association_schema_id, observation_id, sample_id)
        == identity.combined_association_content_id, "sidecar content identity mismatch")
    return decisions, bindings


def verify_values(identity, specs, rows, decisions, bindings):
    specs_by_id = {feature_spec_pin_id(observation_feature_spec_pin(s)): s for s in specs}
    decision_by_key = {(d.sample_key, d.feature_spec_pin_id): d for d in decisions}
    versions = {b.sample_key: b.multi_source_sample_version_id for b in bindings}
    require({(r["sample_key"], r["feature_spec_pin_id"]) for r in rows} == set(decision_by_key), "value cardinality mismatch")
    values = []
    for r in rows:
        spec = specs_by_id[r["feature_spec_pin_id"]]
        d = decision_by_key[(r["sample_key"], r["feature_spec_pin_id"])]
        t = spec.output.logical_type
        require(r["output_logical_type"] == t and r["value_float64" if t == "int64" else "value_int64"] is None,
                "invalid value physical type slot")
        pin = ImplementationPin(r["implementation_name"], r["implementation_version"], r["implementation_content_sha256"])
        require(pin in identity.implementations and pin.name == spec.transform_ref, "value implementation/spec mismatch")
        value = ObservationFeatureValueResult(r["sample_key"], r["multi_source_sample_version_id"], r["feature_name"],
            observation_feature_spec_pin(spec), pin, r["decision_id"], r["status"], r["value_" + t],
            r["reason_code"], r["consumed_observation_version_id"])
        require(value.multi_source_sample_version_id == versions[d.sample_key] and value.decision_id == observation_decision_id(d)
            and value.status == d.status and value.reason_code == d.reason and
            value.consumed_observation_version_id == (d.selected_observation_version_id if d.status == "COMPLETE" else None),
            "value/decision/consumption linkage mismatch")
        values.append(value)
    impls = tuple(p for p in identity.implementations if p.name in {s.transform_ref for s in specs})
    require({p.name for p in impls} == {s.transform_ref for s in specs}, "missing Observation implementation pin")
    samples = []
    for key in sorted(versions):
        per = tuple(sorted((v for v in values if v.sample_key == key), key=lambda v: (v.spec_pin.kind, v.spec_pin.name, v.spec_pin.version, v.spec_pin.content_sha256)))
        samples.append(ObservationFeatureSampleResult(key, versions[key], "COMPLETE" if all(v.status == "COMPLETE" for v in per) else "EXCLUDED", per))
    result = ObservationFeatureExecutionResult(tuple(samples), identity.observation_feature_specs, impls)
    require(physical_values(result, specs) == rows, "noncanonical physical values")
    require(observation_feature_values_content_id(result) == identity.observation_feature_values_content_id, "Feature values content mismatch")
    return result


def verify_matrix(identity, specs, matrix, bindings, observations):
    bar, observation, labels, split_spec = specs
    schema = derive_schema(bar, observation, labels, identity.dataset_as_of)
    require(schema == identity.schema and dataset_schema_id(schema) == identity.dataset_schema_id, "derived matrix schema mismatch")
    by_obs = {s.sample_key: s for s in observations.samples}
    versions = {s.sample_key: s.multi_source_sample_version_id for s in bindings}
    eligible = tuple(a for a in identity.sample_audit if a.bar_feature_status == "COMPLETE" and by_obs[a.sample_key].status == "COMPLETE")
    split = assign_chronological_splits(tuple(ChronologicalSplitSample(a.sample_key, versions[a.sample_key], a.request.feature_window_close,
        a.label_status, a.actual_label_end_time) for a in eligible), split_spec)
    assignments = {a.sample_key: a for a in split.assignments}
    expected = []
    for a in eligible:
        row = dict(code=a.request.code, sample_key=a.sample_key, sample_version_id=versions[a.sample_key],
            feature_window_close=a.request.feature_window_close, actual_label_end_time=a.actual_label_end_time,
            label_status=a.label_status, dataset_as_of=a.dataset_as_of)
        row.update((v.feature_name, v.value) for v in a.bar_feature_values + by_obs[a.sample_key].values)
        row.update((v.label_name, v.value) for v in a.label_values)
        for name in ("feature_window_close_date", "nominal_split", "final_split", "assignment_status", "reason_code", "purge_boundary"):
            row[name] = getattr(assignments[a.sample_key], name)
        expected.append({f.name: row[f.name] for f in schema.fields})
    expected.sort(key=lambda r: (r["code"], r["feature_window_close"], r["sample_key"]))
    require(canonical_json(expected) == canonical_json(matrix), "matrix eligibility/value/split closure mismatch")
    require(logical_dataset_content_id(schema, matrix) == identity.logical_dataset_content_id, "matrix content ID mismatch")
    require(completion(identity.scope, identity.sample_audit, observations) == identity.completion, "completion mismatch")
    return split


def build_report(identity, built_at, row_count, observations, split):
    values = tuple(v for s in observations.samples for v in s.values)
    return dict(report_version="multi-source-dataset-build-report-v1", built_at=built_at,
        dataset_id=multi_source_dataset_id(identity), status="COMPLETE" if row_count else "EMPTY", sample_count=len(identity.sample_audit),
        matrix_row_count=row_count, feature_excluded_sample_count=len(identity.sample_audit)-row_count,
        label_incomplete_sample_count=sum(a.label_status == "INCOMPLETE" for a in identity.sample_audit),
        observation_complete_value_count=sum(v.status == "COMPLETE" for v in values),
        observation_excluded_value_count=sum(v.status == "EXCLUDED" for v in values),
        split_assigned_count=split.diagnostics.assigned_count, split_purged_count=split.diagnostics.purged_count,
        split_excluded_count=split.diagnostics.excluded_count, completion=identity.completion)
