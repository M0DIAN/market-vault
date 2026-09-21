"""Literal path admission without filesystem lookup or platform qualification."""

from pathlib import Path

import pytest

from market_vault.schedule_artifact._errors import _ScheduleArtifactError
from market_vault.schedule_artifact._paths import _final_path


_NAME = "schedule_artifact_id=" + "a" * 64


@pytest.mark.parametrize("windows,root", [(False, "/safe"), (True, "C:\\safe"), (True, "C:/safe")])
def test_absolute_final_literal(windows, root):
    assert _final_path(root + "/" + _NAME, windows=windows).name == _NAME


@pytest.mark.parametrize("name", [
    "latest", "current", "dataset_id=" + "a" * 64,
    "schedule_artifact_id=" + "a" * 63, "schedule_artifact_id=" + "A" * 64,
    "schedule_artifact_id=" + "g" * 64, "schedule_artifact_id=" + "a" * 65,
    "." + "a" * 64 + ".tmp-" + "b" * 32,
])
@pytest.mark.parametrize("windows,root", [(False, "/safe/"), (True, "C:\\safe\\")])
def test_nonfinal_names_rejected(name, windows, root):
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        _final_path(root + name, windows=windows)


@pytest.mark.parametrize("part", ["", ".", "..", "tail.", "tail ", "CON", "con.txt", "NUL", "aux",
                                      "COM1", "LPT9.txt", "COM\u00b9", "file:stream", "a\x00", "a\n", "a\x7f", "a\x80", "e\u0301"])
@pytest.mark.parametrize("windows,root", [(False, "/"), (True, "C:/")])
def test_unsafe_components_rejected(part, windows, root):
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        _final_path(root + part + "/" + _NAME, windows=windows)


@pytest.mark.parametrize("prefix", ["", "relative/", "C:", "c:/", "\\\\server\\share\\", "//server/share/", "\\\\?\\C:\\", "\\\\.\\C:\\", "/"])
def test_windows_nonlocal_nonabsolute_namespace_rejected(prefix):
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        _final_path(prefix + _NAME, windows=True)


@pytest.mark.parametrize("suffix", ["/", "//", "\\", "/.", "/.."])
@pytest.mark.parametrize("windows,root", [(False, "/safe/"), (True, "C:/safe/")])
def test_trailing_ambiguity_rejected(suffix, windows, root):
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        _final_path(root + _NAME + suffix, windows=windows)


@pytest.mark.parametrize("value", [None, b"path", Path("/safe")])
def test_only_literal_text_preserves_pre_normalization_evidence(value):
    with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
        _final_path(value)


def test_relative_posix_and_nested_artifacts_rejected():
    for path in (_NAME, "//safe/" + _NAME, "/" + _NAME + "/" + _NAME):
        with pytest.raises(_ScheduleArtifactError, match="UNSAFE_PATH"):
            _final_path(path, windows=False)
