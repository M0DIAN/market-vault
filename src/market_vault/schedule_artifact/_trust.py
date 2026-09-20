"""Empty reader-owned qualification registries; dependency availability is not trust."""

from types import MappingProxyType

from ._errors import _ScheduleArtifactError


_QUALIFIED_SOURCE_PROFILES = MappingProxyType({})
_QUALIFIED_CUSTODY_KEYS = MappingProxyType({})
_QUALIFIED_VERIFIER_KEYS = MappingProxyType({})


def _resolve_source_profile(provider_id, source_id, source_contract_id,
                            source_contract_version, source_schema_version,
                            api_contract_version):
    key = (provider_id, source_id, source_contract_id, source_contract_version,
           source_schema_version, api_contract_version)
    if not all(type(part) is str for part in key) or key not in _QUALIFIED_SOURCE_PROFILES:
        raise _ScheduleArtifactError("SOURCE_CONTRACT_UNQUALIFIED", "no qualified source profile")
    return _QUALIFIED_SOURCE_PROFILES[key]


def _resolve_custody_key(custody_authority_id, key_id):
    key = (custody_authority_id, key_id)
    if not all(type(part) is str for part in key) or key not in _QUALIFIED_CUSTODY_KEYS:
        raise _ScheduleArtifactError("EVIDENCE_AUTHORITY_UNQUALIFIED", "no qualified custody key")
    return _QUALIFIED_CUSTODY_KEYS[key]


def _resolve_verifier_key(verification_authority_id, verifier_contract_version, key_id):
    key = (verification_authority_id, verifier_contract_version, key_id)
    if not all(type(part) is str for part in key) or key not in _QUALIFIED_VERIFIER_KEYS:
        raise _ScheduleArtifactError("EVIDENCE_AUTHORITY_UNQUALIFIED", "no qualified verifier/key")
    return _QUALIFIED_VERIFIER_KEYS[key]
