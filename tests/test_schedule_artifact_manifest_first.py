"""G1 manifest-first sequencing and G2 directory-name identity binding.

The fake scope tracks capture mechanics only; it is never platform qualification.
The pure-core fixture supplies genuine canonical bytes for every member.
"""

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path

import pytest

from market_vault.schedule_artifact import _physical as p, _semantics
from market_vault.schedule_artifact._errors import _ScheduleArtifactError
from market_vault.schedule_artifact._paths import _MEMBERS, _final_path
from market_vault.schedule_artifact._semantics import _admit_manifest
from test_schedule_artifact_physical import _FakeScope, _tree
from test_schedule_artifact_schema import _bundle, _c, _h


def _artifact_id(bundle):
    return bundle["manifest.json"]["schedule_artifact_id"]


_DOCUMENTS = tuple(member for member in _MEMBERS if member != "_SUCCESS")
_LOGICAL = tuple(document for document in _DOCUMENTS if document != "manifest.json")


def _write_tree(base, bundle, name=None):
    root = _tree(Path(base))
    for member in _MEMBERS:
        if member != "_SUCCESS":
            (root / member).write_bytes(_c(bundle[member]))
    if name is not None:
        renamed = root.with_name(name)
        root.rename(renamed)
        return renamed
    return root


def _valid(base, name=None):
    bundle = _bundle()
    root = _write_tree(base, bundle, name)
    return bundle, root, _FakeScope()


def _mutate_json(root, member, edit):
    document = json.loads((root / member).read_bytes().decode("utf-8"))
    edit(document)
    (root / member).write_bytes(_c(document))


def _reseal(root, edit, base):
    """Mutate documents the way a writer would, then re-seal manifest claims and name."""
    documents = {member: json.loads((root / member).read_bytes().decode("utf-8"))
                 for member in _DOCUMENTS}
    edit(documents)
    for member, document in documents.items():
        (root / member).write_bytes(_c(document))
    manifest = documents["manifest.json"]
    for claim in manifest["content"]["output_files"]:
        raw = _c(documents[claim["path"]])
        claim["byte_size"] = len(raw)
        claim["sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["schedule_artifact_id"] = _h("l4-trading-day-schedule-artifact-v1",
                                          manifest["content"])
    (root / "manifest.json").write_bytes(_c(manifest))
    target = root.with_name(_directory_name(manifest["schedule_artifact_id"]))
    root.rename(target)
    return target


def _claim_edit(edit):
    def mutate(root):
        _mutate_json(root, "manifest.json",
                     lambda document: edit(document["content"]["output_files"]))
    return mutate


def _orchestrated(monkeypatch, base, name=None, mutate=None):
    """Run the orchestrator with a fake scope, recording every canonical parse."""
    bundle, root, scope = _valid(base, name)
    parsed = []
    original = _semantics._parse_document

    def recording(document_name, data):
        parsed.append(document_name)
        return original(document_name, data)

    monkeypatch.setattr(_semantics, "_parse_document", recording)
    monkeypatch.setattr(p, "_NativeScope", lambda parent: scope)
    monkeypatch.setattr(p, "_require_qualified", lambda qualified: ())
    if mutate is not None:
        root = mutate(root) or root
    try:
        return parsed, None, p._capture_physical(str(root)), bundle
    except BaseException as exc:  # noqa: BLE001 - the reason code is the assertion subject
        return parsed, exc, None, bundle


@pytest.mark.parametrize("edit,detail", [
    (lambda files: files[0].__setitem__("byte_size", files[0]["byte_size"] + 1), "member bytes"),
    (lambda files: files[1].__setitem__("sha256", "f" * 64), "member bytes"),
    (lambda files: files.reverse(), "output inventory"),
    (lambda files: files.pop(), "output inventory"),
    (lambda files: files[0].__setitem__("role", "SCHEDULE"), "output inventory"),
    (lambda files: files[0].__setitem__("path", "latest"), "invalid schema value"),
])
def test_manifest_claim_rejection_precedes_every_logical_parse(monkeypatch, tmp_path, edit, detail):
    parsed, error, facts, _ = _orchestrated(monkeypatch, tmp_path, mutate=_claim_edit(edit))
    assert facts is None
    assert isinstance(error, _ScheduleArtifactError)
    assert detail in str(error)
    assert parsed == ["manifest.json"], "a logical document was parsed before admission succeeded"


def test_byte_size_and_sha256_claims_fail_independently(monkeypatch, tmp_path):
    files = _bundle()["manifest.json"]["content"]["output_files"]
    for index, field, value in ((0, "byte_size", files[0]["byte_size"] + 1),
                                (1, "sha256", "0" * 64)):
        candidate = tmp_path / field
        candidate.mkdir()
        parsed, error, facts, _ = _orchestrated(
            monkeypatch, candidate,
            mutate=_claim_edit(lambda items, i=index, f=field, v=value: items[i].__setitem__(f, v)))
        assert facts is None
        assert error is not None and error.reason_code == "INTEGRITY_MISMATCH"
        assert "member bytes" in str(error)
        assert parsed == ["manifest.json"]


def test_manifest_field_disagreeing_with_recomputed_identity_fails(monkeypatch, tmp_path):
    zero = "0" * 64
    parsed, error, facts, _ = _orchestrated(
        monkeypatch, tmp_path, name=_directory_name(zero),
        mutate=lambda root: _mutate_json(
            root, "manifest.json",
            lambda document: document.__setitem__("schedule_artifact_id", zero)))
    assert facts is None
    assert error is not None and error.reason_code == "IDENTITY_MISMATCH"
    assert "artifact ID" in str(error)
    assert parsed == ["manifest.json"]


def test_shape_valid_directory_name_differing_from_recomputed_id_fails(monkeypatch, tmp_path):
    recomputed = _artifact_id(_bundle())
    other = "b" * 64
    assert other != recomputed
    # The admitted path accepts the differing spelling, so only G2 can refuse it.
    _final_path(("C:/safe/" if os.name == "nt" else "/safe/") + _directory_name(other))
    parsed, error, facts, _ = _orchestrated(monkeypatch, tmp_path, name=_directory_name(other))
    assert facts is None
    assert error is not None and error.reason_code == "IDENTITY_MISMATCH"
    assert "artifact directory name" in str(error)
    assert parsed == ["manifest.json"]


def test_correctly_named_artifact_reaches_downstream_semantic_checks(monkeypatch, tmp_path):
    """Admission and identity binding succeed, so the logical documents are parsed."""
    bundle = _bundle()
    parsed, error, facts, _ = _orchestrated(
        monkeypatch, tmp_path,
        mutate=lambda root: _reseal(root, lambda documents: documents["schedule.json"].__setitem__(
            "coverage_complete", False), tmp_path))
    assert parsed[0] == "manifest.json"
    assert sorted(parsed[1:]) == sorted(_LOGICAL)
    assert facts is None
    assert error is not None and error.reason_code == "INTEGRITY_MISMATCH"
    assert "coverage_complete" in str(error)


def test_phase_two_content_binding_binds_a_manifest_field(monkeypatch, tmp_path):
    """A manifest field the artifact ID also covers is still bound in phase two."""
    bundle = _bundle()
    parsed, error, facts, _ = _orchestrated(
        monkeypatch, tmp_path,
        mutate=lambda root: _reseal(root, lambda documents: documents["manifest.json"]["content"]
                                    .__setitem__("schedule_content_id", "0" * 64), tmp_path))
    assert parsed[0] == "manifest.json"
    assert sorted(parsed[1:]) == sorted(_LOGICAL)
    assert facts is None
    assert error is not None and error.reason_code == "IDENTITY_MISMATCH"
    assert "logical schedule IDs" in str(error)


def test_noncanonical_manifest_bytes_fail_before_any_document_parse(monkeypatch, tmp_path):
    _, root, scope = _valid(tmp_path)
    (root / "manifest.json").write_bytes(b"{}")
    parsed, original = [], _semantics._parse_document
    monkeypatch.setattr(_semantics, "_parse_document",
                        lambda name, data: (parsed.append(name), original(name, data))[1])
    monkeypatch.setattr(p, "_NativeScope", lambda parent: scope)
    monkeypatch.setattr(p, "_require_qualified", lambda qualified: ())
    with pytest.raises(ValueError, match="noncanonical"):
        p._capture_physical(str(root))
    assert parsed == [], "a document was parsed although the manifest was not canonical"


def test_nonempty_and_missing_success_marker_still_fail_closed(tmp_path):
    _, root, scope = _valid(tmp_path)
    (root / "_SUCCESS").write_bytes(b"x")
    with pytest.raises(_ScheduleArtifactError, match="INTEGRITY_MISMATCH"):
        p._capture_members(scope, root)
    assert not scope.reads

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _, other, other_scope = _valid(sibling)
    (other / "_SUCCESS").rename(sibling / "detached")
    with pytest.raises(_ScheduleArtifactError, match="INVENTORY_MISMATCH"):
        p._capture_members(other_scope, other)
    assert not other_scope.reads


def _supplied(bundle):
    return {document: _c(bundle[document]) for document in _DOCUMENTS}


def _directory_name(artifact_id):
    return "schedule_artifact_id=" + artifact_id


def test_directory_name_preserves_the_admitted_lowercase_hex_spelling():
    name = "schedule_artifact_id=" + "0123456789abcdef" * 4
    prefix = "C:/safe/" if os.name == "nt" else "/safe/"
    admitted = _final_path(prefix + name)
    assert admitted.name == name
    assert type(admitted.name) is str


def test_phase_two_requires_an_admitted_manifest_value():
    with pytest.raises(_ScheduleArtifactError, match="admitted manifest"):
        _semantics_validate_without_admission()
    with pytest.raises(_ScheduleArtifactError, match="inventory of captured document bytes"):
        _admit_manifest(manifest_bytes=_c(_bundle()["manifest.json"]), supplied={})
    with pytest.raises(_ScheduleArtifactError, match="invalid schema value: manifest.json"):
        _admit_manifest(manifest_bytes=b"{}\n", supplied=_supplied(_bundle()))


def _semantics_validate_without_admission():
    return _semantics._validate_artifact_structure(
        admitted="forged", source_snapshot_bytes=b"", coverage_evidence_bytes=b"",
        verification_receipt_bytes=b"", schedule_bytes=b"", directory_name="0" * 64)


def test_admitted_manifest_is_frozen_and_carries_no_authority():
    bundle = _bundle()
    admitted = _admit_manifest(manifest_bytes=_c(bundle["manifest.json"]),
                               supplied=_supplied(bundle))
    assert admitted.document.name == "manifest.json"
    assert admitted.artifact_id == _artifact_id(bundle)
    with pytest.raises(FrozenInstanceError):
        admitted.artifact_id = "0" * 64
