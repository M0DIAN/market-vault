from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Iterable

RTH_TIMEZONE = "America/New_York"
SPECIAL_SESSION_AUTHORITY_VERSION = "us-rth-special-session-authority-v1"
NORMAL_RTH_PROFILE_VERSION = "moomoo-rth-normal-profile-v1"
EXCHANGE_AUTHORITY_REFERENCE = (
    "https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf"
)
EXCHANGE_AUTHORITY_CAPTURE_METADATA = (
    "qualification_record="
    "docs/market_bar_early_close_rth_geometry_qualification_v1.md",
    "qualification_record_git_blob=5c596779c8dcccef8dedf1c099233dad57a55a8f",
)
EXCHANGE_AUTHORITY_REVIEW_METADATA = (
    "pull_request=147",
    "reviewed_head=4ad003876e8c26dcc18caf6d16055e70ed216b93",
    "formal_design_main=23fa8a780777852b1cd4be3d653295f8c631fb80",
)
PROVIDER_PROFILE_VERSION = "moomoo-us-rth-0930-1300-1m-5m-15m-30m-60m-v1"
PROVIDER_PROBE_MANIFEST_SHA256 = (
    "b82628b3b8810c7717c23af02e531f6af79f0c9409682074a71062088b52535b"
)

_NORMAL_OPEN = time(9, 30)
_NORMAL_CLOSE = time(16, 0)
_QUALIFIED_EARLY_CLOSE = time(13, 0)


@dataclass(frozen=True, slots=True)
class RTHSessionGeometry:
    trade_date: date
    market: str
    timezone: str
    open_time: time
    close_time: time
    classification: str
    authority_version: str
    authority_reference: str
    authority_capture_metadata: tuple[str, ...] | None = None
    authority_review_metadata: tuple[str, ...] | None = None
    provider_profile_version: str | None = None
    provider_probe_manifest_sha256: str | None = None


SPECIAL_RTH_SESSION_GEOMETRIES: tuple[RTHSessionGeometry, ...] = (
    RTHSessionGeometry(
        trade_date=date(2025, 11, 28),
        market="US",
        timezone=RTH_TIMEZONE,
        open_time=_NORMAL_OPEN,
        close_time=_QUALIFIED_EARLY_CLOSE,
        classification="EARLY_CLOSE",
        authority_version=SPECIAL_SESSION_AUTHORITY_VERSION,
        authority_reference=EXCHANGE_AUTHORITY_REFERENCE,
        authority_capture_metadata=EXCHANGE_AUTHORITY_CAPTURE_METADATA,
        authority_review_metadata=EXCHANGE_AUTHORITY_REVIEW_METADATA,
        provider_profile_version=PROVIDER_PROFILE_VERSION,
        provider_probe_manifest_sha256=PROVIDER_PROBE_MANIFEST_SHA256,
    ),
    RTHSessionGeometry(
        trade_date=date(2025, 12, 24),
        market="US",
        timezone=RTH_TIMEZONE,
        open_time=_NORMAL_OPEN,
        close_time=_QUALIFIED_EARLY_CLOSE,
        classification="EARLY_CLOSE",
        authority_version=SPECIAL_SESSION_AUTHORITY_VERSION,
        authority_reference=EXCHANGE_AUTHORITY_REFERENCE,
        authority_capture_metadata=EXCHANGE_AUTHORITY_CAPTURE_METADATA,
        authority_review_metadata=EXCHANGE_AUTHORITY_REVIEW_METADATA,
        provider_profile_version=PROVIDER_PROFILE_VERSION,
        provider_probe_manifest_sha256=PROVIDER_PROBE_MANIFEST_SHA256,
    ),
)


def _validate_special_geometry(geometry: RTHSessionGeometry) -> None:
    if geometry.market != "US":
        raise ValueError("Malformed RTH special-session authority: market must be US")
    if geometry.timezone != RTH_TIMEZONE:
        raise ValueError(
            "Malformed RTH special-session authority: timezone must be "
            f"{RTH_TIMEZONE}"
        )
    if geometry.classification != "EARLY_CLOSE":
        raise ValueError(
            "Malformed RTH special-session authority: classification must be "
            "EARLY_CLOSE"
        )
    if geometry.authority_version != SPECIAL_SESSION_AUTHORITY_VERSION:
        raise ValueError(
            "Malformed RTH special-session authority: unsupported authority version"
        )
    if geometry.authority_reference != EXCHANGE_AUTHORITY_REFERENCE:
        raise ValueError(
            "Malformed RTH special-session authority: exchange authority reference "
            "is missing or unknown"
        )
    if geometry.authority_capture_metadata != EXCHANGE_AUTHORITY_CAPTURE_METADATA:
        raise ValueError(
            "Malformed RTH special-session authority: exchange authority capture "
            "metadata is missing or unknown"
        )
    if geometry.authority_review_metadata != EXCHANGE_AUTHORITY_REVIEW_METADATA:
        raise ValueError(
            "Malformed RTH special-session authority: exchange authority review "
            "metadata is missing or unknown"
        )
    if geometry.provider_profile_version != PROVIDER_PROFILE_VERSION:
        raise ValueError(
            "Malformed RTH special-session authority: provider profile version is "
            "missing or unknown"
        )
    if geometry.provider_probe_manifest_sha256 != PROVIDER_PROBE_MANIFEST_SHA256:
        raise ValueError(
            "Malformed RTH special-session authority: provider probe manifest seal "
            "is missing or unknown"
        )
    if (
        geometry.open_time != _NORMAL_OPEN
        or geometry.close_time != _QUALIFIED_EARLY_CLOSE
    ):
        raise ValueError(
            "Unsupported RTH special-session geometry: only the qualified "
            "09:30-13:00 profile is supported"
        )


def resolve_rth_session_geometry(
    requested_trade_date: date,
    *,
    authorities: Iterable[RTHSessionGeometry] | None = None,
) -> RTHSessionGeometry:
    """Resolve an exact special-session override or the normal RTH profile."""
    entries = (
        SPECIAL_RTH_SESSION_GEOMETRIES
        if authorities is None
        else tuple(authorities)
    )
    matches = tuple(
        entry
        for entry in entries
        if getattr(entry, "trade_date", None) == requested_trade_date
    )
    if not matches:
        return RTHSessionGeometry(
            trade_date=requested_trade_date,
            market="US",
            timezone=RTH_TIMEZONE,
            open_time=_NORMAL_OPEN,
            close_time=_NORMAL_CLOSE,
            classification="NORMAL",
            authority_version=NORMAL_RTH_PROFILE_VERSION,
            authority_reference="market_bar_timestamp_semantics_v2",
        )
    if len(matches) != 1:
        raise ValueError(
            "Conflicting RTH special-session authority for "
            f"{requested_trade_date.isoformat()}"
        )
    geometry = matches[0]
    if not isinstance(geometry, RTHSessionGeometry):
        raise ValueError(
            "Malformed RTH special-session authority for "
            f"{requested_trade_date.isoformat()}"
        )
    _validate_special_geometry(geometry)
    return geometry
