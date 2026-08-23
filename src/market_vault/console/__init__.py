"""MarketVault Console package.

Importing this package is headless-safe. Tkinter is imported only by
``market_vault.console.ui`` when the desktop application is launched.
"""

from .backend import ConsoleBackend
from .models import DashboardSnapshot, ExportResult, PurgePlanView, TablePage

__all__ = ["ConsoleBackend", "DashboardSnapshot", "ExportResult", "PurgePlanView", "TablePage"]
