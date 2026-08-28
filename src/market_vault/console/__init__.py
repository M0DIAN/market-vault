"""UI-neutral adapters shared by MarketVault desktop presentation layers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .backend import ConsoleBackend
    from .models import DashboardSnapshot, ExportResult, PurgePlanView, TablePage

__all__ = ["ConsoleBackend", "DashboardSnapshot", "ExportResult", "PurgePlanView", "TablePage"]


def __getattr__(name: str) -> Any:
    """Load public adapters only when a caller explicitly requests one."""

    if name == "ConsoleBackend":
        from .backend import ConsoleBackend

        return ConsoleBackend
    if name in {"DashboardSnapshot", "ExportResult", "PurgePlanView", "TablePage"}:
        from . import models

        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
