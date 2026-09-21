"""L4-owned read-only retained Linux descriptor/statx evidence; not qualification."""

import ctypes as c
import os
from pathlib import Path
import stat
import sys

from ._errors import _require
from ._models import _MAX_FILE_BYTES


class _Timestamp(c.Structure):
    _fields_ = [("sec", c.c_int64), ("nsec", c.c_uint32), ("reserved", c.c_int32)]


class _Statx(c.Structure):
    _fields_ = [("mask", c.c_uint32), ("blocksize", c.c_uint32), ("attributes", c.c_uint64),
        ("nlink", c.c_uint32), ("uid", c.c_uint32), ("gid", c.c_uint32), ("mode", c.c_uint16), ("reserved", c.c_uint16),
        ("ino", c.c_uint64), ("size", c.c_uint64), ("blocks", c.c_uint64), ("attributes_mask", c.c_uint64),
        ("atime", _Timestamp), ("btime", _Timestamp), ("ctime", _Timestamp), ("mtime", _Timestamp),
        ("rdev_major", c.c_uint32), ("rdev_minor", c.c_uint32), ("dev_major", c.c_uint32), ("dev_minor", c.c_uint32),
        ("mount_id", c.c_uint64), ("dio_mem_align", c.c_uint32), ("dio_offset_align", c.c_uint32),
        ("spare", c.c_uint64 * 12)]


class _Statfs(c.Structure):
    _fields_ = [("type", c.c_long), ("blocksize", c.c_long), ("blocks", c.c_uint64), ("free", c.c_uint64),
        ("available", c.c_uint64), ("files", c.c_uint64), ("files_free", c.c_uint64), ("fsid", c.c_int * 2),
        ("name_length", c.c_long), ("fragment_size", c.c_long), ("flags", c.c_long), ("spare", c.c_long * 4)]


def _native():
    _require(sys.platform == "linux" and c.sizeof(c.c_void_p) == 8 and c.sizeof(_Statx) == 256,
             "PLATFORM_UNQUALIFIED", "supported 64-bit Linux statx ABI required")
    libc = c.CDLL(None, use_errno=True)
    try:
        statx, fstatfs = libc.statx, libc.fstatfs
    except AttributeError:
        _require(False, "PLATFORM_UNQUALIFIED", "statx/fstatfs unavailable")
    statx.argtypes = (c.c_int, c.c_char_p, c.c_int, c.c_uint, c.POINTER(_Statx))
    statx.restype = c.c_int
    fstatfs.argtypes = (c.c_int, c.POINTER(_Statfs))
    fstatfs.restype = c.c_int
    return statx, fstatfs


def _raise_errno():
    error = c.get_errno()
    raise OSError(error, os.strerror(error))


def _mount_id(fd):
    statx, _ = _native()
    data = _Statx()
    if statx(fd, b"", 0x1000 | 0x100, 0x1000 | 0x7ff, c.byref(data)) != 0:
        _raise_errno()
    _require(data.mask & 0x1000 and data.mount_id != 0 and data.ino != 0,
             "PLATFORM_UNQUALIFIED", "stable statx mount/inode identity required")
    return data.mount_id


def _filesystem(fd):
    _, fstatfs = _native()
    data = _Statfs()
    if fstatfs(fd, c.byref(data)) != 0:
        _raise_errno()
    # Ext-family magic is necessary, not sufficient for exact ext4 qualification.
    return (data.type, tuple(data.fsid), data.flags, data.blocksize, _mount_id(fd))


def _mount_description(data, mount_id, device):
    """Bind statx's held mount to the kernel's explicit ext4/options record."""
    _require(type(data) is bytes and len(data) <= 1048576 and data.endswith(b"\n"),
             "PLATFORM_UNQUALIFIED", "bounded complete mount table required")
    records = []
    for line in data.splitlines():
        parts = line.split(b" ")
        _require(parts.count(b"-") == 1, "PLATFORM_UNQUALIFIED", "invalid mount record")
        separator = parts.index(b"-")
        _require(separator >= 6 and len(parts) == separator + 4 and parts[0].isdigit(),
                 "PLATFORM_UNQUALIFIED", "invalid mount fields")
        records.append((int(parts[0]), parts))
    matches = tuple(p for mid, p in records if mid == mount_id)
    _require(len(matches) == 1, "PLATFORM_UNQUALIFIED", "held mount missing or ambiguous")
    record = matches[0]
    separator = record.index(b"-")
    _require(record[2] == device and record[3] == b"/" and record[separator + 1] == b"ext4"
             and sum(p[2] == device for _, p in records) == 1,
             "PLATFORM_UNQUALIFIED", "non-ext4 or bind-mount ambiguity")
    mount_options = tuple(sorted(record[5].decode("ascii").split(",")))
    super_options = tuple(sorted(record[-1].decode("ascii").split(",")))
    _require("rw" in mount_options and "rw" in super_options and "ro" not in mount_options + super_options,
             "PLATFORM_UNQUALIFIED", "read-only mount")
    return "ext4", mount_options, super_options


def _ext4_capability(fd):
    data = os.fstat(fd)
    before = _mount_id(fd)
    with open("/proc/self/mountinfo", "rb") as stream:
        contents = stream.read(1048577)
    result = _mount_description(contents, before,
        (str(os.major(data.st_dev)) + ":" + str(os.minor(data.st_dev))).encode("ascii"))
    _require(_mount_id(fd) == before, "UNSAFE_PATH", "mount identity drift")
    return result


def _permissions(data, fd, *, ancestor):
    _require(data.st_uid in (0, os.geteuid()), "UNSAFE_PATH", "untrusted Linux object owner")
    writable = bool(data.st_mode & 0o022)
    _require(not writable or (ancestor and stat.S_ISDIR(data.st_mode) and bool(data.st_mode & stat.S_ISVTX)),
             "UNSAFE_PATH", "untrusted Linux mutation permissions")
    attributes = tuple(sorted(os.listxattr(fd)))
    _require(not any(n in ("system.posix_acl_access", "system.posix_acl_default") for n in attributes),
             "UNSAFE_PATH", "unqualified POSIX ACL")
    _require(not attributes, "UNSAFE_PATH", "unqualified extended attributes")
    return data.st_uid, data.st_gid, stat.S_IMODE(data.st_mode), attributes


class _LinuxObject:
    """A retained no-follow descriptor and its independent path binding."""

    def __init__(self, path, *, directory, ancestor=False):
        _require(sys.platform == "linux", "PLATFORM_UNQUALIFIED", "Linux native evidence unavailable")
        self.path, self.directory, self.ancestor = Path(path), directory, ancestor
        before = os.lstat(self.path)
        _require(stat.S_ISDIR(before.st_mode) if directory else stat.S_ISREG(before.st_mode),
                 "UNSAFE_PATH", "wrong Linux object type")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        if directory:
            flags |= os.O_DIRECTORY
        self.fd = os.open(self.path, flags)
        try:
            self.identity, self.filesystem, self.security, self.size = self._facts()
            _require(self.identity[:2] == (before.st_dev, before.st_ino), "UNSAFE_PATH", "object changed during open")
        except BaseException:
            self.close()
            raise

    def _facts(self):
        _require(self.fd is not None, "PHYSICAL_DRIFT", "closed descriptor")
        data = os.fstat(self.fd)
        _require(stat.S_ISDIR(data.st_mode) if self.directory else stat.S_ISREG(data.st_mode), "UNSAFE_PATH", "wrong retained object type")
        _require(data.st_ino != 0 and (self.directory or data.st_nlink == 1), "UNSAFE_PATH", "missing identity or hard link")
        security = _permissions(data, self.fd, ancestor=self.ancestor)
        return (data.st_dev, data.st_ino, self.directory), _filesystem(self.fd), security, (0 if self.directory else data.st_size)

    def recheck(self):
        _require(self._facts() == (self.identity, self.filesystem, self.security, self.size), "UNSAFE_PATH", "held Linux object drift")
        other = _LinuxObject(self.path, directory=self.directory, ancestor=self.ancestor)
        try:
            _require((other.identity, other.filesystem, other.security, other.size) == (self.identity, self.filesystem, self.security, self.size),
                     "UNSAFE_PATH", "same-path replacement or Linux permission drift")
        finally:
            other.close()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read_bytes(self, size):
        _require(not self.directory and self.fd is not None, "UNSAFE_PATH", "held file required")
        _require(type(size) is int and 0 <= size <= _MAX_FILE_BYTES and size == self.size,
                 "INTEGRITY_MISMATCH", "bounded captured native size required")
        self.recheck()
        chunks, offset = [], 0
        while offset < size:
            chunk = os.pread(self.fd, min(65536, size - offset), offset)
            _require(bool(chunk), "PHYSICAL_DRIFT", "short native read")
            chunks.append(chunk)
            offset += len(chunk)
        self.recheck()
        return b"".join(chunks)
