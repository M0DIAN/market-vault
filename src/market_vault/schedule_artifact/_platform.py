"""L4-specific exact native capability calculation; no platform is admitted."""

import ctypes as c
import os
import sys

from ._errors import _require


_QUALIFIED_CAPABILITIES = frozenset()


def _capability(scope):
    scope.recheck()
    python = (sys.implementation.name, sys.version, c.sizeof(c.c_void_p) * 8)
    if os.name == "nt":
        from ._windows import _machine_capability, _ntfs_capability
        version = sys.getwindowsversion()
        return ("Windows", tuple(version.platform_version), version.product_type,
                _machine_capability(), python, scope.filesystem[3], scope.filesystem[4],
                _ntfs_capability(scope.filesystem), "l4-schedule-readonly-FileIdInfo-v1")
    if sys.platform == "linux":
        from ._linux import _ext4_capability
        libc = c.CDLL(None)
        try:
            version = libc.gnu_get_libc_version
        except AttributeError:
            _require(False, "PLATFORM_UNQUALIFIED", "glibc identity unavailable")
        version.argtypes, version.restype = (), c.c_char_p
        uname = os.uname()
        return ("Linux", uname.release, uname.machine, version().decode("ascii"), python,
                scope.filesystem[0], scope.filesystem[2], scope.filesystem[3],
                _ext4_capability(scope.root_object.fd), "l4-schedule-readonly-statx-ext4-v1")
    _require(False, "PLATFORM_UNQUALIFIED", "unsupported native platform")


def _require_qualified(scope):
    capability = _capability(scope)
    _require(capability in _QUALIFIED_CAPABILITIES,
             "PLATFORM_UNQUALIFIED", "unqualified exact L4 native capability: " + repr(capability))
    return capability
