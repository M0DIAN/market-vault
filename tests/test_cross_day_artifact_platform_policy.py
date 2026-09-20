"""Pure capability parsing and fail-closed policy tests; no qualification claim."""

import pytest

from market_vault.cross_day_dataset import _artifact_platform as policy
from market_vault.cross_day_dataset._artifact_linux import _mount_description
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError


MOUNT = b"36 35 8:0 / / rw,relatime shared:1 - ext4 /dev/root rw,errors=remount-ro\n"
WINDOWS = (
    "Windows", (10, 0, 26100), 1, (34404, 0),
    ("cpython", "3.14.7 (tags/v3.14.7:823f032, Aug  5 2026, 10:51:32) [MSC v.1944 64 bit (AMD64)]", 64),
    "NTFS", 29830879, (3, 1, 512, 4096, 1024), "protected-DACL-FileIdInfo-v1",
)
LINUX = (
    "Linux", "6.17.0-1022-azure", "x86_64", "2.39",
    ("cpython", "3.11.16 (main, Aug 13 2026, 02:46:14) [GCC 13.3.0]", 64),
    61267, 4128, 4096, ("ext4", ("relatime", "rw"),
                      ("commit=30", "discard", "errors=remount-ro", "rw")), "statx-protected-ext4-v1",
)


def test_production_capabilities_are_exactly_the_two_reviewed_literals():
    assert type(policy._QUALIFIED_CAPABILITIES) is frozenset
    assert len(policy._QUALIFIED_CAPABILITIES) == 2
    assert policy._QUALIFIED_CAPABILITIES == frozenset({WINDOWS, LINUX})


@pytest.mark.parametrize("capability", [WINDOWS, LINUX], ids=["Windows", "Linux"])
def test_exact_reviewed_native_tuple_is_admitted(monkeypatch, capability):
    monkeypatch.setattr(policy, "_capability", lambda scope: capability)
    assert policy._require_qualified(object()) == capability


def _single_field_mutations(value, path=()):
    if type(value) is tuple:
        yield path, value + ("UNTESTED",)
        for index, field in enumerate(value):
            for changed_path, changed in _single_field_mutations(field, path + (index,)):
                yield changed_path, value[:index] + (changed,) + value[index + 1:]
    else:
        yield path, value + 1 if type(value) is int else value + "-UNTESTED"


@pytest.mark.parametrize("capability", [
    pytest.param(changed, id=original[0] + "-" + ".".join(map(str, path)))
    for original in (WINDOWS, LINUX)
    for path, changed in _single_field_mutations(original)
])
def test_each_changed_native_tuple_field_fails_closed(monkeypatch, capability):
    assert capability not in policy._QUALIFIED_CAPABILITIES
    monkeypatch.setattr(policy, "_capability", lambda scope: capability)
    with pytest.raises(MultiSourceCrossDayArtifactError, match="PLATFORM_UNQUALIFIED"):
        policy._require_qualified(object())


def test_mount_description_binds_exact_mount_and_type():
    assert _mount_description(MOUNT, 36, b"8:0") == (
        "ext4", ("relatime", "rw"), ("errors=remount-ro", "rw"))


@pytest.mark.parametrize("contents,identifier,device", [
    (MOUNT, 37, b"8:0"), (MOUNT, 36, b"8:1"), (MOUNT + MOUNT, 36, b"8:0"),
    (MOUNT.replace(b"ext4", b"ext3"), 36, b"8:0"), (MOUNT.replace(b"ext4", b"nfs"), 36, b"8:0"),
    (MOUNT.replace(b" / / ", b" /subdir / "), 36, b"8:0"),
    (MOUNT.replace(b"rw,relatime", b"ro,relatime"), 36, b"8:0"),
    (MOUNT[:-1], 36, b"8:0"), (b"invalid\n", 36, b"8:0"),
    (MOUNT + MOUNT.replace(b"36 35", b"37 35"), 36, b"8:0"),
])
def test_mount_description_refuses_unknown_or_ambiguous(contents, identifier, device):
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _mount_description(contents, identifier, device)


def test_unknown_native_tuple_fails_closed(monkeypatch):
    monkeypatch.setattr(policy, "_capability", lambda scope: ("UNTESTED",))
    with pytest.raises(MultiSourceCrossDayArtifactError, match="PLATFORM_UNQUALIFIED"):
        policy._require_qualified(object())
