"""Closed native capability policy; unknown tuples are never qualified."""

import ctypes as c
import os
import sys

from .artifact_models import _require


# Populated only from exact-code native qualification evidence, never discovery.
_QUALIFIED_CAPABILITIES = frozenset()


def _capability(scope):
    python = (sys.implementation.name, sys.version, c.sizeof(c.c_void_p) * 8)
    if os.name == "nt":
        from ._artifact_windows import _ntfs_capability, _machine_capability
        version = sys.getwindowsversion()
        return ("Windows", tuple(version.platform_version), version.product_type, _machine_capability(), python,
                scope.filesystem[3], scope.filesystem[4], _ntfs_capability(scope.filesystem),
                "protected-DACL-FileIdInfo-v1")
    if sys.platform == "linux":
        from ._artifact_linux import _ext4_capability
        libc = c.CDLL(None)
        try:
            get_version = libc.gnu_get_libc_version
        except AttributeError:
            _require(False, "PLATFORM_UNQUALIFIED", "glibc identity unavailable")
        get_version.argtypes, get_version.restype = (), c.c_char_p
        uname = os.uname()
        return ("Linux", uname.release, uname.machine, get_version().decode("ascii"), python,
                scope.filesystem[0], scope.filesystem[2], scope.filesystem[3], _ext4_capability(scope.root_object.fd),
                "statx-protected-ext4-v1")
    _require(False, "PLATFORM_UNQUALIFIED", "unsupported native platform")


def _require_qualified(scope):
    capability = _capability(scope)
    _require(capability in _QUALIFIED_CAPABILITIES, "PLATFORM_UNQUALIFIED", "unqualified exact native capability: " + repr(capability))
    return capability
