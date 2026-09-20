"""Four frozen L4 evidence domains over the unchanged Dataset encoder."""

import hashlib

from ..dataset.encoding import encode_identity
from ._canonical import _canonical_json


_DOMAINS = frozenset({
    "l4-trading-day-source-record-v1",
    "l4-trading-day-source-snapshot-v1",
    "l4-trading-day-coverage-completion-v1",
    "l4-trading-day-schedule-artifact-v1",
})


def _sha256(data: bytes) -> str:
    if type(data) is not bytes:
        raise TypeError("exact SHA256 input bytes required")
    return hashlib.sha256(data).hexdigest()


def _identity(domain: str, payload: object) -> str:
    if type(domain) is not str:
        raise TypeError("exact identity domain string required")
    if domain not in _DOMAINS:
        raise ValueError("unrecognized L4 identity domain")
    return encode_identity(domain, {
        "canonical_payload_sha256": _sha256(_canonical_json(payload)),
    })
