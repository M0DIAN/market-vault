"""Bounded native Windows object/volume/security evidence, without publication."""

import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path

from .artifact_models import _require


class _IdInfo(c.Structure):
    _fields_ = [("serial", c.c_ulonglong), ("identifier", c.c_ubyte * 16)]


class _TagInfo(c.Structure):
    _fields_ = [("attributes", w.DWORD), ("tag", w.DWORD)]


class _StandardInfo(c.Structure):
    _fields_ = [("allocation", c.c_longlong), ("size", c.c_longlong), ("links", w.DWORD),
                ("delete_pending", c.c_ubyte), ("directory", c.c_ubyte)]


class _Acl(c.Structure):
    _fields_ = [("revision", c.c_ubyte), ("sbz", c.c_ubyte), ("size", w.WORD), ("count", w.WORD), ("sbz2", w.WORD)]


class _Ace(c.Structure):
    _fields_ = [("type", c.c_ubyte), ("flags", c.c_ubyte), ("size", w.WORD), ("mask", w.DWORD), ("sid", w.DWORD)]


class _SecurityAttributes(c.Structure):
    _fields_ = [("length", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]


class _NtfsData(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ("serial", "sectors", "clusters", "free", "reserved")] + [
        (name, c.c_uint32) for name in ("sector_bytes", "cluster_bytes", "record_bytes", "record_clusters")] + [
        (name, c.c_uint64) for name in ("mft_length", "mft_start", "mft2_start", "zone_start", "zone_end")]


def _api(dll, name, args, result):
    function = getattr(dll, name)
    function.argtypes, function.restype = args, result
    return function


if os.name == "nt":
    _kernel = c.WinDLL("kernel32", use_last_error=True)
    _advapi = c.WinDLL("advapi32", use_last_error=True)
    _create = _api(_kernel, "CreateFileW", [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE)
    _close = _api(_kernel, "CloseHandle", [w.HANDLE], w.BOOL)
    _info = _api(_kernel, "GetFileInformationByHandleEx", [w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL)
    _file_type = _api(_kernel, "GetFileType", [w.HANDLE], w.DWORD)
    _final_path = _api(_kernel, "GetFinalPathNameByHandleW", [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD], w.DWORD)
    _volume_path = _api(_kernel, "GetVolumePathNameW", [w.LPCWSTR, w.LPWSTR, w.DWORD], w.BOOL)
    _volume_name = _api(_kernel, "GetVolumeNameForVolumeMountPointW", [w.LPCWSTR, w.LPWSTR, w.DWORD], w.BOOL)
    _volume_info = _api(_kernel, "GetVolumeInformationByHandleW", [w.HANDLE, w.LPWSTR, w.DWORD, c.POINTER(w.DWORD),
        c.POINTER(w.DWORD), c.POINTER(w.DWORD), w.LPWSTR, w.DWORD], w.BOOL)
    _drive_type = _api(_kernel, "GetDriveTypeW", [w.LPCWSTR], w.UINT)
    _local_free = _api(_kernel, "LocalFree", [c.c_void_p], c.c_void_p)
    _security = _api(_advapi, "GetSecurityInfo", [w.HANDLE, c.c_int, w.DWORD, c.POINTER(c.c_void_p),
        c.c_void_p, c.POINTER(c.c_void_p), c.c_void_p, c.POINTER(c.c_void_p)], w.DWORD)
    _sid_text = _api(_advapi, "ConvertSidToStringSidW", [c.c_void_p, c.POINTER(c.c_void_p)], w.BOOL)
    _sd_length = _api(_advapi, "GetSecurityDescriptorLength", [c.c_void_p], w.DWORD)
    _sd_control = _api(_advapi, "GetSecurityDescriptorControl", [c.c_void_p, c.POINTER(w.WORD), c.POINTER(w.DWORD)], w.BOOL)
    _get_ace = _api(_advapi, "GetAce", [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)], w.BOOL)
    _current_process = _api(_kernel, "GetCurrentProcess", [], w.HANDLE)
    _open_token = _api(_advapi, "OpenProcessToken", [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)], w.BOOL)
    _token_info = _api(_advapi, "GetTokenInformation", [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL)
    _convert_sd = _api(_advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                       [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(w.DWORD)], w.BOOL)
    _mkdir = _api(_kernel, "CreateDirectoryW", [w.LPCWSTR, c.POINTER(_SecurityAttributes)], w.BOOL)
    _seek = _api(_kernel, "SetFilePointerEx", [w.HANDLE, c.c_longlong, c.POINTER(c.c_longlong), w.DWORD], w.BOOL)
    _read = _api(_kernel, "ReadFile", [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p], w.BOOL)
    _write = _api(_kernel, "WriteFile", [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p], w.BOOL)
    _flush = _api(_kernel, "FlushFileBuffers", [w.HANDLE], w.BOOL)
    _ioctl = _api(_kernel, "DeviceIoControl", [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD,
        c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p], w.BOOL)


def _ok(value):
    if not value:
        raise c.WinError(c.get_last_error())
    return value


def _sid(pointer):
    text = c.c_void_p()
    _ok(_sid_text(pointer, c.byref(text)))
    try:
        return c.wstring_at(text)
    finally:
        _local_free(text)


def _current_sid():
    _require(os.name == "nt", "PLATFORM_UNQUALIFIED", "Windows native evidence unavailable")
    token = w.HANDLE()
    _ok(_open_token(_current_process(), 0x0008, c.byref(token)))
    try:
        size = w.DWORD()
        _token_info(token, 1, None, 0, c.byref(size))
        _require(0 < size.value <= 65536, "PLATFORM_UNQUALIFIED", "invalid token information length")
        buffer = c.create_string_buffer(size.value)
        _ok(_token_info(token, 1, buffer, size, c.byref(size)))
        return _sid(c.cast(buffer, c.POINTER(c.c_void_p))[0])
    finally:
        _close(token)


def _security_facts(handle):
    owner, dacl, descriptor = c.c_void_p(), c.c_void_p(), c.c_void_p()
    error = _security(handle, 1, 0x00000005, c.byref(owner), None, c.byref(dacl), None, c.byref(descriptor))
    if error:
        raise c.WinError(error)
    try:
        _require(bool(owner.value) and bool(dacl.value), "UNSAFE_PATH", "owner and non-null DACL required")
        control, revision = w.WORD(), w.DWORD()
        _ok(_sd_control(descriptor, c.byref(control), c.byref(revision)))
        acl = c.cast(dacl, c.POINTER(_Acl)).contents
        entries = []
        for index in range(acl.count):
            pointer = c.c_void_p()
            _ok(_get_ace(dacl, index, c.byref(pointer)))
            ace = c.cast(pointer, c.POINTER(_Ace)).contents
            _require(ace.type in (0, 1) and ace.size >= 16, "UNSAFE_PATH", "unsupported ACE semantics")
            entries.append((ace.type, ace.flags, ace.mask, _sid(pointer.value + _Ace.sid.offset)))
        raw = c.string_at(descriptor, _sd_length(descriptor))
        return _sid(owner), control.value, tuple(entries), raw
    finally:
        _local_free(descriptor)


def _access_boundary(facts, current_sid, *, ancestor, held_handle=None):
    owner, control, entries, _ = facts
    trusted = {current_sid, "S-1-5-18", "S-1-5-32-544"}
    if ancestor:
        trusted.add("S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464")
    _require(owner in trusted, "UNSAFE_PATH", "untrusted object owner")
    _require(ancestor or bool(control & 0x1000), "UNSAFE_PATH", "private root/member DACL must be protected")
    # Creating a sibling alone does not permit replacing a protected child.
    forbidden = 0x00010000 | 0x00040000 | 0x00080000 | 0x00000040 | 0x00000100 | 0x00000010
    if ancestor and held_handle is not None and _native_volume_root(held_handle):
        # Only a proven native volume root gets this protected-child policy.
        forbidden &= ~(0x00010000 | 0x00000100 | 0x00000010)
    if not ancestor:
        forbidden |= 0x00000002 | 0x00000004
    for ace_type, flags, mask, sid in entries:
        if ace_type == 0 and not flags & 0x08 and sid not in trusted:
            _require(not mask & (forbidden | 0x10000000 | 0x40000000), "UNSAFE_PATH", "untrusted mutation grant")


def _handle_path(handle, flags):
    buffer = c.create_unicode_buffer(32768)
    length = _final_path(handle, buffer, len(buffer), flags)
    _ok(length)
    _require(length < len(buffer), "UNSAFE_PATH", "native handle path overflow")
    return buffer.value


def _native_volume_root(handle):
    """Classify the retained native object, never a caller path or boolean."""
    _require(type(handle) is int and handle > 0, "UNSAFE_PATH", "retained native handle required")
    identity, tag, standard = _IdInfo(), _TagInfo(), _StandardInfo()
    _require(_file_type(handle) == 1, "UNSAFE_PATH", "not a retained disk object")
    for code, value in ((18, identity), (9, tag), (1, standard)):
        _ok(_info(handle, code, c.byref(value), c.sizeof(value)))
    _require(identity.serial != 0 and any(identity.identifier), "PLATFORM_UNQUALIFIED", "unstable FileIdInfo")
    _require(standard.directory and tag.attributes & 0x10 and not standard.delete_pending,
             "UNSAFE_PATH", "volume ancestor must be a live directory")
    _require(not tag.attributes & 0x400 and tag.tag == 0, "UNSAFE_PATH", "reparse volume ancestor")
    dos_path, guid_path = _handle_path(handle, 0), _handle_path(handle, 1)
    _require(dos_path.startswith("\\\\?\\"), "UNSAFE_PATH", "native DOS handle path required")
    mount, guid = c.create_unicode_buffer(32768), c.create_unicode_buffer(128)
    _ok(_volume_path(dos_path[4:], mount, len(mount)))
    _ok(_volume_name(mount, guid, len(guid)))
    _require(_drive_type(mount) == 3 and guid.value.startswith("\\\\?\\Volume{")
             and guid.value.endswith("}\\") and guid_path.startswith(guid.value),
             "FILESYSTEM_MISMATCH", "nonlocal or mismatched volume-root evidence")
    # Sharing the volume prefix proves membership, not root classification.
    return guid_path == guid.value


def _streams(handle):
    buffer = c.create_string_buffer(65536)
    if not _info(handle, 7, buffer, len(buffer)):
        error = c.get_last_error()
        if error == 38:
            return ()
        raise c.WinError(error)
    offset, names = 0, []
    while True:
        _require(offset + 24 <= len(buffer), "UNSAFE_PATH", "invalid stream information")
        following = w.DWORD.from_buffer(buffer, offset).value
        length = w.DWORD.from_buffer(buffer, offset + 4).value
        _require(length % 2 == 0 and offset + 24 + length <= len(buffer), "UNSAFE_PATH", "invalid stream length")
        names.append(c.string_at(c.addressof(buffer) + offset + 24, length).decode("utf-16-le", errors="strict"))
        if not following:
            return tuple(names)
        _require(following >= 24 and offset + following < len(buffer), "UNSAFE_PATH", "invalid next stream")
        offset += following


def _ntfs_capability(filesystem):
    """Read-only native volume format query, not a caller qualification assertion."""
    guid, serial, _, fs, _ = filesystem
    _require(fs == "NTFS" and guid.startswith("\\\\?\\Volume{") and guid.endswith("}\\"),
             "PLATFORM_UNQUALIFIED", "native NTFS volume binding required")
    handle = _create(guid[:-1], 0x80000000, 7, None, 3, 0, None)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        buffer, count = c.create_string_buffer(4096), w.DWORD()
        _ok(_ioctl(handle, 0x00090064, None, 0, buffer, len(buffer), c.byref(count), None))
        base = c.sizeof(_NtfsData)
        _require(base == 96 and count.value >= base + 8, "PLATFORM_UNQUALIFIED", "NTFS extended data unavailable")
        data = _NtfsData.from_buffer(buffer)
        extended_size = c.c_uint32.from_buffer(buffer, base).value
        major = c.c_uint16.from_buffer(buffer, base + 4).value
        minor = c.c_uint16.from_buffer(buffer, base + 6).value
        _require(data.serial == serial and extended_size >= 8 and major > 0,
                 "FILESYSTEM_MISMATCH", "NTFS format/volume identity differs")
        return (major, minor, data.sector_bytes, data.cluster_bytes, data.record_bytes)
    finally:
        _close(handle)


def _machine_capability():
    _require(os.name == "nt", "PLATFORM_UNQUALIFIED", "Windows machine evidence unavailable")
    try:
        query = _api(_kernel, "IsWow64Process2", [w.HANDLE, c.POINTER(w.WORD), c.POINTER(w.WORD)], w.BOOL)
    except AttributeError:
        _require(False, "PLATFORM_UNQUALIFIED", "native/WOW64 machine evidence unavailable")
    process, native = w.WORD(), w.WORD()
    _ok(query(_current_process(), c.byref(process), c.byref(native)))
    _require(native.value != 0, "PLATFORM_UNQUALIFIED", "unknown native architecture")
    return native.value, process.value


class _WindowsObject:
    """Retained no-follow handle; a path or recycled file ID is not ownership."""

    def __init__(self, path, *, directory, current_sid, ancestor=False):
        _require(os.name == "nt", "PLATFORM_UNQUALIFIED", "Windows native evidence unavailable")
        self.path, self.directory, self.current_sid, self.ancestor = Path(path), directory, current_sid, ancestor
        self.handle = _create(str(path), 0x00020081, 7, None, 3, 0x02200000, None)
        if self.handle == c.c_void_p(-1).value:
            self.handle = None
            raise c.WinError(c.get_last_error())
        try:
            self.identity, self.filesystem, self.security = self._facts()
        except BaseException:
            self.close()
            raise

    def _facts(self):
        _require(self.handle is not None and _file_type(self.handle) == 1, "UNSAFE_PATH", "not a retained disk object")
        identity, tag, standard = _IdInfo(), _TagInfo(), _StandardInfo()
        for code, value in ((18, identity), (9, tag), (1, standard)):
            _ok(_info(self.handle, code, c.byref(value), c.sizeof(value)))
        _require(not tag.attributes & 0x400 and tag.tag == 0 and not standard.delete_pending,
                 "UNSAFE_PATH", "reparse or delete-pending object")
        _require(bool(standard.directory) == self.directory and bool(tag.attributes & 0x10) == self.directory,
                 "UNSAFE_PATH", "native object type differs")
        _require(self.directory or standard.links == 1, "UNSAFE_PATH", "hard-linked file")
        _require(identity.serial != 0 and any(identity.identifier), "PLATFORM_UNQUALIFIED", "unstable FileIdInfo")
        dos_path, guid_path = _handle_path(self.handle, 0), _handle_path(self.handle, 1)
        _require(dos_path.startswith("\\\\?\\") and dos_path[4:] == str(self.path), "UNSAFE_PATH", "handle/path spelling differs")
        mount, guid = c.create_unicode_buffer(32768), c.create_unicode_buffer(128)
        _ok(_volume_path(str(self.path), mount, len(mount)))
        _ok(_volume_name(mount, guid, len(guid)))
        _require(_drive_type(mount) == 3 and guid_path.startswith(guid.value), "FILESYSTEM_MISMATCH", "nonlocal or mismatched volume")
        name, fs = c.create_unicode_buffer(261), c.create_unicode_buffer(261)
        serial, maximum, flags = w.DWORD(), w.DWORD(), w.DWORD()
        _ok(_volume_info(self.handle, name, len(name), c.byref(serial), c.byref(maximum), c.byref(flags), fs, len(fs)))
        _require(fs.value == "NTFS" and flags.value & 8, "PLATFORM_UNQUALIFIED", "local persistent-ACL NTFS required")
        security = _security_facts(self.handle)
        _access_boundary(security, self.current_sid, ancestor=self.ancestor, held_handle=self.handle)
        _require(self.ancestor or not tag.attributes & 0x2, "INVENTORY_MISMATCH", "hidden artifact object")
        _require(all(n == "::$DATA" for n in _streams(self.handle)), "INVENTORY_MISMATCH", "named stream outside inventory")
        # Archive/access-time changes from our own writes are not permission changes.
        security = (*security, tag.attributes & 0x7)
        return (identity.serial, bytes(identity.identifier), self.directory), (guid.value, identity.serial, serial.value, fs.value, flags.value), security

    def recheck(self):
        _require(self._facts() == (self.identity, self.filesystem, self.security), "UNSAFE_PATH", "held object/security drift")
        other = _WindowsObject(self.path, directory=self.directory, current_sid=self.current_sid, ancestor=self.ancestor)
        try:
            _require((other.identity, other.filesystem, other.security) == (self.identity, self.filesystem, self.security),
                     "UNSAFE_PATH", "same-path replacement or security drift")
        finally:
            other.close()

    def close(self):
        if self.handle is not None:
            _close(self.handle)
            self.handle = None

    def close_for_directory_rename(self):
        _require(self.handle is not None and _file_type(self.handle) == 1,
                 "UNSAFE_PATH", "valid retained descendant handle required")
        _ok(_close(self.handle))
        self.handle = None

    def read_bytes(self):
        _require(not self.directory and self.handle is not None, "UNSAFE_PATH", "regular held file required")
        _ok(_seek(self.handle, 0, None, 0))
        buffer, count, chunks = c.create_string_buffer(65536), w.DWORD(), []
        while True:
            _ok(_read(self.handle, buffer, len(buffer), c.byref(count), None))
            if not count.value:
                return b"".join(chunks)
            chunks.append(buffer.raw[:count.value])


def _new_directory(path, current_sid):
    """Exclusive creation with the protected DACL supplied at object creation."""
    descriptor, size = c.c_void_p(), w.DWORD()
    sddl = "D:P(A;OICI;FA;;;" + current_sid + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    _ok(_convert_sd(sddl, 1, c.byref(descriptor), c.byref(size)))
    try:
        attributes = _SecurityAttributes(c.sizeof(_SecurityAttributes), descriptor, False)
        _ok(_mkdir(str(path), c.byref(attributes)))
    finally:
        _local_free(descriptor)


def _new_file_handle(path, current_sid):
    descriptor, size = c.c_void_p(), w.DWORD()
    sddl = "D:P(A;;FA;;;" + current_sid + ")(A;;FA;;;SY)(A;;FA;;;BA)"
    _ok(_convert_sd(sddl, 1, c.byref(descriptor), c.byref(size)))
    try:
        attributes = _SecurityAttributes(c.sizeof(_SecurityAttributes), descriptor, False)
        handle = _create(str(path), 0x40020080, 7, c.byref(attributes), 1, 0x00200080, None)
        if handle == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        return handle
    finally:
        _local_free(descriptor)


def _write_handle(handle, data):
    _require(type(data) is bytes, "INPUT_AUTHORITY", "exact output bytes required")
    count, offset = w.DWORD(), 0
    while offset < len(data):
        chunk = data[offset:offset + 65536]
        buffer = c.create_string_buffer(chunk)
        _ok(_write(handle, buffer, len(chunk), c.byref(count), None))
        _require(0 < count.value <= len(chunk), "PUBLICATION_FAILED", "invalid native write count")
        offset += count.value
    _ok(_flush(handle))
