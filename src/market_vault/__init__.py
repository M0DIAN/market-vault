"""MarketVault package.

The public API is loaded lazily so normalization and quality modules can be
used in lightweight environments before DuckDB is installed. Importing this
package must not import duckdb, pandas, moomoo, or futu.
"""

from typing import Any

from ._version import __version__

__all__ = [
    "ArtifactClient",
    "MarketVault",
    "build_research_dataset",
    "__version__",
]


def __getattr__(name: str) -> Any:
    if name == "ArtifactClient":
        from .artifact_client import ArtifactClient

        return ArtifactClient
    if name == "MarketVault":
        from .api import MarketVault

        return MarketVault
    if name == "build_research_dataset":
        from .research_dataset import build_research_dataset

        return build_research_dataset
    raise AttributeError(name)
