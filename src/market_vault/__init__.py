"""MarketVault package.

The public API is loaded lazily so normalization and quality modules can be
used in lightweight environments before DuckDB is installed.
"""

from typing import Any

__all__ = ["MarketVault"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name == "MarketVault":
        from .api import MarketVault

        return MarketVault
    raise AttributeError(name)
