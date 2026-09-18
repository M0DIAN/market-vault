"""Pure capability parsing and fail-closed policy tests; no qualification claim."""

import pytest

from market_vault.cross_day_dataset import _artifact_platform as policy
from market_vault.cross_day_dataset._artifact_linux import _mount_description
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError


MOUNT = b"36 35 8:0 / / rw,relatime shared:1 - ext4 /dev/root rw,errors=remount-ro\n"


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
