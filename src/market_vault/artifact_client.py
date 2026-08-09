"""MarketVault settings-independent Python artifact client foundation.

The :class:`ArtifactClient` is the v0.7.0 settings-independent public root
for read-only verified artifact access. This module ships the PR-2
foundation only: the constructor is a strict zero-argument, stateless,
side-effect-free initializer. Canonical / Dataset / Dataset Catalog read
capabilities are planned in PR-3 / PR-4 and are not implemented here.
"""

from __future__ import annotations


class ArtifactClient:
    """Settings-independent artifact client foundation (v0.7.0 PR-2).

    The constructor takes no arguments and performs no work: no settings,
    no filesystem access, no network, no OpenD, no current time. Instances
    are stateless (``__slots__ = ()``).
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Initialize the foundation with no configuration and no side
        effects."""
