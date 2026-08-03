"""MarketVault package.

The public API is loaded lazily so normalization and quality modules can be
used in lightweight environments before DuckDB is installed. Importing this
package must not import duckdb, pandas, moomoo, or futu.
"""

from typing import Any

from ._version import __version__

__all__ = ["MarketVault", "__version__"]


def __getattr__(name: str) -> Any:
    if name == "MarketVault":
        from .api import MarketVault

        return MarketVault
    raise AttributeError(name)
