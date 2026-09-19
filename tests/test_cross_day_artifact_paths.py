"""Lexical path rejection never touches the filesystem."""

import os
from pathlib import Path

import pytest

from market_vault.cross_day_dataset._artifact_paths import _absolute_path, _output_root, _relative_member, _expected_inventory
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError


@pytest.mark.parametrize("path", ("relative", "../escape", "D:relative", "//server/share", "\\\\server\\share",
    "\\\\?\\D:\\root", "D:/../root", "D:/a/./b", "D:/a//b", "D:/NUL", "D:/file:stream", "D:/trailing.",
    "D:/trailing ", "D:/a\x00b", "D:/a\nb"))
def test_unsafe_absolute_path_rejected_without_io(path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("lexical admission performed I/O")
    monkeypatch.setattr(os, "lstat", forbidden)
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _absolute_path(path)


@pytest.mark.parametrize("path", ("/absolute", "..", "a/../b", "a//b", "./a", "a/", "a\\b", "x:stream",
    "COM1", "lpt9.txt", "a/CON", "a/space ", "a/dot.", "a\x1fb"))
def test_unsafe_member_rejected(path):
    with pytest.raises(MultiSourceCrossDayArtifactError):
        _relative_member(path)


def test_root_not_volume_or_existing_artifact():
    prefix = "D:/" if os.name == "nt" else "/"
    for path in (prefix, prefix + "dataset_id=" + "a" * 64, prefix + "dataset_id=" + "a" * 64 + "/nested"):
        with pytest.raises(MultiSourceCrossDayArtifactError):
            _output_root(path)
    assert _output_root(prefix + "MV-L33-Qualification") == Path(prefix + "MV-L33-Qualification")


def test_exact_inventory_includes_only_required_parent_directories():
    assert _expected_inventory(("_SUCCESS", "specs/ts2/abc.yaml")) == (
        ("_SUCCESS", "FILE"), ("specs", "DIRECTORY"), ("specs/ts2", "DIRECTORY"), ("specs/ts2/abc.yaml", "FILE"))
    for names in (("a", "A"), ("a", "a/b"), ("a", "a")):
        with pytest.raises(MultiSourceCrossDayArtifactError):
            _expected_inventory(names)
