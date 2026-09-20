"""Private pure-validation failures, without reader or publication authority."""


_REASONS = frozenset({
    "NONCANONICAL_BYTES", "INTEGRITY_MISMATCH", "SOURCE_CONTRACT_UNQUALIFIED",
    "EVIDENCE_AUTHORITY_UNQUALIFIED", "SOURCE_AUTHENTICATION_FAILED",
    "SOURCE_SCOPE_MISMATCH", "SOURCE_CONFLICT", "COVERAGE_INCOMPLETE",
    "SESSION_GEOMETRY_UNQUALIFIED", "ARCHIVE_BOUND_INVALID",
    "LOGICAL_SCHEDULE_MISMATCH", "IDENTITY_MISMATCH",
})


class _ScheduleArtifactError(ValueError):
    """A structural/semantic failure, never a Feature/Label status."""

    def __init__(self, reason_code, detail):
        if reason_code not in _REASONS:
            raise ValueError("unsupported pure schedule-artifact reason")
        self.reason_code = reason_code
        super().__init__(reason_code + ": " + detail)


def _require(condition, reason, detail):
    if not condition:
        raise _ScheduleArtifactError(reason, detail)
