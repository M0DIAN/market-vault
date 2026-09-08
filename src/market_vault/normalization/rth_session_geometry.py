from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Iterable

RTH_TIMEZONE = "America/New_York"
SPECIAL_SESSION_AUTHORITY_VERSION = "us-rth-special-session-authority-v1"
NORMAL_RTH_PROFILE_VERSION = "moomoo-rth-normal-profile-v1"

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


SPECIAL_RTH_SESSION_GEOMETRIES: tuple[RTHSessionGeometry, ...] = (
    RTHSessionGeometry(
        trade_date=date(2025, 11, 28),
        market="US",
        timezone=RTH_TIMEZONE,
        open_time=_NORMAL_OPEN,
        close_time=_QUALIFIED_EARLY_CLOSE,
        classification="EARLY_CLOSE",
        authority_version=SPECIAL_SESSION_AUTHORITY_VERSION,
        authority_reference=(
            "https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf"
        ),
    ),
    RTHSessionGeometry(
        trade_date=date(2025, 12, 24),
        market="US",
        timezone=RTH_TIMEZONE,
        open_time=_NORMAL_OPEN,
        close_time=_QUALIFIED_EARLY_CLOSE,
        classification="EARLY_CLOSE",
        authority_version=SPECIAL_SESSION_AUTHORITY_VERSION,
        authority_reference=(
            "https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf"
        ),
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
    if not geometry.authority_reference.strip():
        raise ValueError(
            "Malformed RTH special-session authority: authority reference is required"
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
