"""Pure input admission, coverage and revision proofs for A3."""

from dataclasses import dataclass, replace
from datetime import timedelta

from ..dataset.content import dataset_schema_id, logical_dataset_content_id
from ..dataset.pit import PIT_ASSOCIATION_COLUMNS, pit_association_schema
from ..dataset.pit_identity import pit_sample_key, pit_sample_version_id
from ..dataset.pit_models import PITAssemblyResult, PITSample
from ._artifact_validation import validate_inputs, verify_revisions
from .artifact_models import VerifiedObservationBuild
from .identity import observation_build_id, observation_content_id, observation_source_snapshot_id
from .models import ObservationBuildIdentityInput, ObservationContractPin
from .pit_models import ObservationPITError
from .schema import OBSERVATION_SCHEMA_VERSION


def admit_bar(bar):
    if type(bar) is not PITAssemblyResult:
        raise ObservationPITError("bar input requires PITAssemblyResult")
    bar = replace(bar)
    if bar.association_schema != pit_association_schema():
        raise ObservationPITError("bar association schema mismatch")
    if (dataset_schema_id(bar.association_schema) != bar.association_schema_id
            or logical_dataset_content_id(bar.association_schema, bar.association_rows) != bar.association_content_id):
        raise ObservationPITError("bar association identity mismatch")
    samples = {}
    expected = {}
    pins = {p.canonical_build_id: replace(p) for p in bar.canonical_build_pins}
    if len(pins) != len(bar.canonical_build_pins):
        raise ObservationPITError("duplicate bar build pins")
    for sample in bar.samples:
        if type(sample) is not PITSample or sample.sample_key in samples:
            raise ObservationPITError("invalid or duplicate bar sample")
        sample = replace(sample)
        request = replace(sample.request)
        if sample.sample_key != pit_sample_key(request):
            raise ObservationPITError("bar sample key mismatch")
        version = pit_sample_version_id(
            sample_key=sample.sample_key, dataset_as_of=sample.dataset_as_of,
            feature_canonical_row_version_ids=sample.feature_canonical_row_version_ids,
            label_canonical_row_version_ids=sample.label_canonical_row_version_ids,
            considered_canonical_build_ids=sample.considered_canonical_build_ids)
        if sample.sample_version_id != version or not set(sample.considered_canonical_build_ids) <= pins.keys():
            raise ObservationPITError("bar sample version/build references mismatch")
        samples[sample.sample_key] = replace(sample, request=request)
        for role, versions in (("FEATURE", sample.feature_canonical_row_version_ids),
                               ("LABEL", sample.label_canonical_row_version_ids)):
            for pos, row_version in enumerate(versions):
                expected[(sample.sample_key, role, pos)] = row_version
    seen = set()
    for row in bar.association_rows:
        if set(row) != set(PIT_ASSOCIATION_COLUMNS):
            raise ObservationPITError("bar association field mismatch")
        key = (row["sample_key"], row["role"], row["position"])
        if type(row["position"]) is not int or key in seen or key not in expected:
            raise ObservationPITError("bar association sample/position mismatch")
        seen.add(key)
        sample = samples[row["sample_key"]]
        if (row["sample_version_id"] != sample.sample_version_id
                or row["code"] != sample.request.code
                or row["canonical_row_version_id"] != expected[key]
                or row["canonical_build_id"] not in sample.considered_canonical_build_ids
                or row["canonical_row_version_id"] not in pins[row["canonical_build_id"]].canonical_row_version_ids):
            raise ObservationPITError("bar association references mismatch")
    if seen != expected.keys() or set(bar.canonical_row_version_ids) != set(expected.values()):
        raise ObservationPITError("bar association cardinality mismatch")
    return tuple(samples[k] for k in sorted(samples))


@dataclass(frozen=True)
class _Build:
    identity: ObservationBuildIdentityInput
    snapshots: tuple
    created_at: object
    build_id: str
    content_id: str
    status: str


def admit_build(value):
    if type(value) is not VerifiedObservationBuild:
        raise ObservationPITError("Observation input requires VerifiedObservationBuild")
    if value.manifest_payload.get("observation_schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise ObservationPITError("unsupported Observation schema")
    identity = ObservationBuildIdentityInput(
        rows=value.rows,
        source_snapshot_ids=tuple(observation_source_snapshot_id(s) for s in value.source_snapshots),
        authority_evidence_ids=value.authority_evidence_ids,
        provider_contracts=value.provider_contracts, normalizations=value.normalizations,
        coverage=value.coverage)
    identity, snapshots, created = validate_inputs(identity, value.source_snapshots, value.created_at)
    content = observation_content_id(identity.rows)
    build_id = observation_build_id(identity)
    status = "COMPLETE" if identity.rows else "EMPTY"
    if content != value.observation_content_id or build_id != value.observation_build_id or status != value.status:
        raise ObservationPITError("verified build has inconsistent identities/status")
    return _Build(identity, snapshots, created, build_id, content, status)


def admit_source(build, source):
    identity = build.identity
    provider = ObservationContractPin(source.provider_contract_version, source.provider_contract_content_id)
    normalizer = ObservationContractPin(source.normalization_version, source.normalization_content_id)
    if identity.coverage.provider_contract != provider or provider not in identity.provider_contracts:
        raise ObservationPITError("wrong provider contract")
    if normalizer not in identity.normalizations:
        raise ObservationPITError("wrong normalizer")
    if source.known_at_authority_policy_content_id not in identity.authority_evidence_ids:
        raise ObservationPITError("missing known-at policy authority")
    for row in identity.rows:
        if (row.provider_contract_version != source.provider_contract_version
                or row.provider_contract_content_id != source.provider_contract_content_id
                or row.normalization_version != source.normalization_version
                or row.normalization_content_id != source.normalization_content_id
                or row.value_schema_id != source.value_schema_id):
            raise ObservationPITError("scoped row schema/contract drift")
        names = {f.name for f in row.value_schema.fields}
        if not set(source.input_field_names) <= names:
            raise ObservationPITError("unknown input field")


def prove_coverage(builds, start, end, T, A, *, earliest_known=None):
    intervals = []
    for build in builds:
        cov = build.identity.coverage
        if (cov.request_pages_complete and cov.revision_inventory_complete
                and cov.knowledge_start <= T <= cov.knowledge_end
                and (earliest_known is None or cov.knowledge_start <= earliest_known)
                and (A is None or build.created_at <= A)):
            lo, hi = max(start, cov.effective_start), min(end, cov.effective_end)
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
    raise ObservationPITError("coverage authority does not prove continuous required domain through T")


def reconcile(builds):
    versions = {}
    containing = {}
    for build in builds:
        for row in build.identity.rows:
            previous = versions.get(row.observation_version_id)
            if previous is not None and previous != row:
                raise ObservationPITError("conflicting duplicate version")
            versions[row.observation_version_id] = row
            containing.setdefault(row.observation_version_id, set()).add(build.build_id)
    rows = tuple(versions[k] for k in sorted(versions))
    verify_revisions(rows)
    groups = {}
    for row in rows:
        groups.setdefault(row.observation_key, {}).setdefault(row.revision_id, []).append(row)
    chains = {}
    for key, revisions in groups.items():
        successors = {rs[0].supersedes_revision_id: revision for revision, rs in revisions.items()}
        chain = []
        revision = successors[None]
        while revision is not None:
            chain.append(tuple(revisions[revision]))
            revision = successors.get(revision)
        chains[key] = tuple(chain)
    return rows, containing, chains


def eligible(chains, T, A):
    result = {}
    for key, chain in chains.items():
        for captures in chain:
            visible = [r for r in captures if r.known_at <= T and (A is None or r.archive_available_at <= A)]
            if visible:
                result[key] = min(visible, key=lambda r: (r.archive_available_at, r.source_snapshot_id,
                                                         r.observation_version_id))
    return result
