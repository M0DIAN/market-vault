"""Closed native capability policy; unknown tuples are never qualified."""

import ctypes as c
import os
import sys

from .artifact_models import _require


# Populated only from exact-code native qualification evidence, never discovery.
_QUALIFIED_CAPABILITIES = frozenset({
    ("Windows", (10, 0, 26100), 1, (34404, 0),
     ("cpython", "3.14.7 (tags/v3.14.7:823f032, Aug  5 2026, 10:51:32) [MSC v.1944 64 bit (AMD64)]", 64),
     "NTFS", 29830879, (3, 1, 512, 4096, 1024), "protected-DACL-FileIdInfo-v1"),
    ("Linux", "6.17.0-1022-azure", "x86_64", "2.39",
     ("cpython", "3.11.16 (main, Aug 13 2026, 02:46:14) [GCC 13.3.0]", 64),
     61267, 4128, 4096, ("ext4", ("relatime", "rw"),
                       ("commit=30", "discard", "errors=remount-ro", "rw")), "statx-protected-ext4-v1"),
})


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
