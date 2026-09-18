"""Static access-policy tests do not constitute native platform qualification."""

import os
import ctypes

import pytest

from market_vault.cross_day_dataset._artifact_windows import _access_boundary
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError


CURRENT = "S-1-5-21-1-2-3-1001"


@pytest.fixture
def native_evidence(monkeypatch):
    from market_vault.cross_day_dataset import _artifact_windows as native
    volume = "\\\\?\\Volume{00000000-0000-0000-0000-000000000001}\\"
    facts = dict(guid_path=volume, directory=1, attributes=0x10, tag=0,
                 serial=17, identifier=1, delete_pending=0, drive_type=3)

    def info(handle, code, pointer, size):
        assert handle == 123
        kind = {18: native._IdInfo, 9: native._TagInfo, 1: native._StandardInfo}[code]
        assert size == ctypes.sizeof(kind)
        record = ctypes.cast(pointer, ctypes.POINTER(kind)).contents
        if code == 18:
            record.serial = facts["serial"]
            record.identifier[0] = facts["identifier"]
        elif code == 9:
            record.attributes, record.tag = facts["attributes"], facts["tag"]
        else:
            record.directory, record.delete_pending = facts["directory"], facts["delete_pending"]
        return 1

    def volume_path(path, buffer, size):
        assert path == "Z:\\"
        buffer.value = "Z:\\"
        return 1

    def volume_name(mount, buffer, size):
        assert mount.value == "Z:\\"
        buffer.value = volume
        return 1

    monkeypatch.setattr(native, "_info", info, raising=False)
    monkeypatch.setattr(native, "_file_type", lambda handle: 1, raising=False)
    monkeypatch.setattr(native, "_handle_path", lambda handle, flags: facts["guid_path"] if flags else "\\\\?\\Z:\\")
    monkeypatch.setattr(native, "_volume_path", volume_path, raising=False)
    monkeypatch.setattr(native, "_volume_name", volume_name, raising=False)
    monkeypatch.setattr(native, "_drive_type", lambda mount: facts["drive_type"], raising=False)
    return facts


def test_observed_sandbox_mask_only_admitted_for_native_volume_ancestor(native_evidence):
    facts = ("S-1-5-18", 0x1000, ((0, 0, 0x001301BF, "S-1-5-11"),), b"sd")
    _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary(facts, CURRENT, ancestor=False, held_handle=123)
    native_evidence["guid_path"] += "ordinary-ancestor"
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)


@pytest.mark.parametrize("mask", (0x40, 0x40000, 0x80000, 0x10000000, 0x40000000))
@pytest.mark.parametrize("ace_flags", (0, 0x10))
def test_native_volume_root_still_rejects_child_or_security_authority(native_evidence, mask, ace_flags):
    facts = ("S-1-5-18", 0, ((0, ace_flags, mask, "S-1-5-11"),), b"sd")
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)


def test_ordinary_ancestor_delete_remains_forbidden(native_evidence):
    native_evidence["guid_path"] += "ordinary-ancestor"
    facts = ("S-1-5-18", 0, ((0, 0, 0x10000, "S-1-5-11"),), b"sd")
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary(facts, CURRENT, ancestor=True, held_handle=123)


def test_native_root_requires_exact_guid_root_not_shared_prefix(native_evidence):
    from market_vault.cross_day_dataset._artifact_windows import _native_volume_root
    assert _native_volume_root(123) is True
    native_evidence["guid_path"] += "child"
    assert _native_volume_root(123) is False
    native_evidence["guid_path"] = "\\\\?\\Volume{00000000-0000-0000-0000-000000000002}\\"
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _native_volume_root(123)


@pytest.mark.parametrize("key,value", (("directory", 0), ("attributes", 0), ("attributes", 0x410),
    ("tag", 0xA0000003), ("serial", 0), ("identifier", 0), ("delete_pending", 1), ("drive_type", 4)))
def test_native_volume_root_requires_live_nonreparse_local_directory(native_evidence, key, value):
    from market_vault.cross_day_dataset._artifact_windows import _native_volume_root
    native_evidence[key] = value
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _native_volume_root(123)


def test_caller_boolean_cannot_establish_volume_root(native_evidence):
    from market_vault.cross_day_dataset._artifact_windows import _native_volume_root
    facts = (CURRENT, 0x1000, (), b"sd")
    with pytest.raises(TypeError):
        _access_boundary(facts, CURRENT, ancestor=True, volume_root=True)
    for value in (True, False, None, 0, -1, "C:\\"):
        with pytest.raises(MultiSourceCrossDayArtifactError):
            _native_volume_root(value)


@pytest.mark.parametrize("principal", ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-21-1-2-3-1002"))
@pytest.mark.parametrize("mask", (2, 4, 0x10, 0x40, 0x100, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000))
def test_windows_untrusted_mutation_grant_fails(principal, mask):
    facts = (CURRENT, 0x1000, ((0, 0, 0x1f01ff, CURRENT), (0, 0, mask, principal)), b"sd")
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary(facts, CURRENT, ancestor=False)


def test_parent_sibling_creation_is_not_delete_child_authority():
    facts = ("S-1-5-18", 0, ((0, 0, 2 | 4, "S-1-5-11"),), b"sd")
    _access_boundary(facts, CURRENT, ancestor=True)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary(facts, CURRENT, ancestor=False)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary((facts[0], 0, ((0, 0, 0x40, "S-1-5-11"),), b"sd"), CURRENT, ancestor=True)


def test_protected_private_child_and_trusted_owner_required():
    entries = tuple((0, 3, 0x1f01ff, sid) for sid in (CURRENT, "S-1-5-18", "S-1-5-32-544"))
    _access_boundary((CURRENT, 0x1000, entries, b"sd"), CURRENT, ancestor=False)
    for owner, control in ((CURRENT, 0), ("S-1-1-0", 0x1000)):
        with pytest.raises(MultiSourceCrossDayArtifactError):
            _access_boundary((owner, control, entries, b"sd"), CURRENT, ancestor=False)


def test_inherited_ace_is_not_ignored():
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _access_boundary((CURRENT, 0x1000, ((0, 0x10, 0x10000, "S-1-5-11"),), b"sd"), CURRENT, ancestor=False)


def test_linux_native_adapter_refuses_windows():
    if os.name != "nt":
        pytest.skip("Windows-only unavailable-API refusal")
    from market_vault.cross_day_dataset._artifact_linux import _native
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _native()
