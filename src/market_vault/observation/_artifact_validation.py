"""Pure A2 admission and revision structure checks shared with the reader."""

from ._validation import instant
from .artifact_models import ObservationArtifactError
from .identity import observation_source_snapshot_id
from .manifest import build_from_payload, canonical_json, payload, snapshot_from_payload
from .models import ObservationBuildIdentityInput, ObservationSourceSnapshotInput


def validate_inputs(build, source_snapshots, created_at):
    if type(build) is not ObservationBuildIdentityInput:
        raise ObservationArtifactError("build must be ObservationBuildIdentityInput")
    if type(source_snapshots) is not tuple or any(
        type(s) is not ObservationSourceSnapshotInput for s in source_snapshots
    ):
        raise ObservationArtifactError("source_snapshots must be an explicit tuple of snapshots")
    # Reconstruct every nested declaration, including derived IDs; no forged A1 input is trusted.
    build = build_from_payload(payload(build))
    snapshots = tuple(snapshot_from_payload(payload(s)) for s in source_snapshots)
    by_id = {observation_source_snapshot_id(s): s for s in snapshots}
    if len(by_id) != len(snapshots) or set(by_id) != set(build.source_snapshot_ids):
        raise ObservationArtifactError("source snapshot set mismatch or duplicate")
    snapshots = tuple(by_id[key] for key in sorted(by_id))
    coverage = build.coverage
    if not coverage.request_pages_complete or not coverage.revision_inventory_complete:
        raise ObservationArtifactError("complete request and revision coverage required")
    created_at = instant(created_at, "created_at")
    for snapshot in snapshots:
        if (snapshot.normalized_request_id != coverage.normalized_request_id
                or snapshot.provider_id != coverage.scope.provider_id
                or snapshot.source_kind != coverage.scope.source_kind
                or snapshot.provider_contract != coverage.provider_contract):
            raise ObservationArtifactError("snapshot does not match coverage/request/provider contract")
        if created_at < snapshot.completed_possession_at:
            raise ObservationArtifactError("created_at precedes snapshot possession")
    for row in build.rows:
        snapshot = by_id[row.source_snapshot_id]
        if (row.provider_id != snapshot.provider_id or row.source_kind != snapshot.source_kind
                or row.provider_contract_version != snapshot.provider_contract.version
                or row.provider_contract_content_id != snapshot.provider_contract.content_id
                or row.source_content_sha256 != snapshot.source_content_sha256):
            raise ObservationArtifactError("row source snapshot cross-binding mismatch")
        if row.archive_available_at < snapshot.completed_possession_at:
            raise ObservationArtifactError("archive_available_at precedes snapshot possession")
        if created_at < row.archive_available_at:
            raise ObservationArtifactError("created_at precedes row archive availability")
    verify_revisions(build.rows)
    return build, snapshots, created_at


def verify_revisions(rows):
    groups = {}
    capture_fields = {"archive_available_at", "source_snapshot_id", "source_content_sha256",
                      "observation_version_id"}
    for row in rows:
        revisions = groups.setdefault(row.observation_key, {})
        previous = revisions.get(row.revision_id)
        facts = {k: v for k, v in payload(row).items() if k not in capture_fields}
        if previous is not None:
            old_facts = {k: v for k, v in payload(previous).items() if k not in capture_fields}
            if canonical_json(facts) != canonical_json(old_facts):
                raise ObservationArtifactError("conflicting repeated capture of economic revision")
        else:
            revisions[row.revision_id] = row
    for revisions in groups.values():
        initial = [r for r in revisions.values() if r.supersedes_revision_id is None]
        if len(initial) != 1:
            raise ObservationArtifactError("revision chain requires exactly one initial revision")
        successors = {}
        for row in revisions.values():
            predecessor_id = row.supersedes_revision_id
            if predecessor_id is None:
                continue
            predecessor = revisions.get(predecessor_id)
            if predecessor is None or predecessor_id == row.revision_id:
                raise ObservationArtifactError("missing or self revision predecessor")
            if predecessor_id in successors:
                raise ObservationArtifactError("forked revision chain")
            if row.known_at <= predecessor.known_at:
                raise ObservationArtifactError("successor known_at must strictly increase")
            successors[predecessor_id] = row.revision_id
        seen = set()
        current = initial[0].revision_id
        while current is not None:
            if current in seen:
                raise ObservationArtifactError("cyclic revision chain")
            seen.add(current)
            current = successors.get(current)
        if seen != set(revisions):
            raise ObservationArtifactError("disconnected revision chain")
