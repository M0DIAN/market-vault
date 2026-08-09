"""MarketVault settings-independent Python artifact client (v0.7.0).

The :class:`ArtifactClient` is the v0.7.0 settings-independent public root
for read-only verified artifact access. PR-2 shipped the strict
zero-argument, stateless, side-effect-free constructor foundation. PR-3
adds exactly two verified read methods:

- :meth:`ArtifactClient.load_canonical_build` delegates verbatim to
  :func:`market_vault.canonical.reader.load_verified_canonical_build`;
- :meth:`ArtifactClient.load_dataset` delegates verbatim to
  :func:`market_vault.dataset.reader.load_verified_dataset`.

The client performs zero artifact validation of its own: the formal
readers remain the only validation authority, their exceptions propagate
unwrapped, and nothing is ever written, repaired, or discovered.
Reader imports occur at the actual method-call boundary so this module
stays lightweight at import time. Dataset Catalog access is PR-4 and is
not implemented here.
"""

from __future__ import annotations


class ArtifactClient:
    """Settings-independent read-only artifact client (v0.7.0 PR-3).

    The constructor takes no arguments and performs no work: no settings,
    no filesystem access, no network, no OpenD, no current time. Instances
    are stateless (``__slots__ = ()``).

    Verified reads are explicit-path only: ``load_canonical_build`` and
    ``load_dataset`` delegate directly to the formal verified readers and
    return their verified objects unchanged.
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Initialize the client with no configuration and no side
        effects."""

    def load_canonical_build(self, build_dir):
        """Read and verify one Canonical build directory.

        Delegates verbatim to
        :func:`market_vault.canonical.reader.load_verified_canonical_build`
        and returns its :class:`~market_vault.canonical.VerifiedCanonicalBuild`
        unchanged. The formal reader performs all validation; its
        :class:`~market_vault.canonical.CanonicalArtifactValidationError`
        failures propagate unwrapped. The reader is imported only when this
        method is actually called.
        """
        from .canonical.reader import load_verified_canonical_build

        return load_verified_canonical_build(build_dir)

    def load_dataset(self, build_dir):
        """Read and verify one Dataset build directory.

        Delegates verbatim to
        :func:`market_vault.dataset.reader.load_verified_dataset`
        and returns its :class:`~market_vault.dataset.VerifiedDatasetBuild`
        unchanged. The formal reader performs all validation; its
        :class:`~market_vault.dataset.DatasetArtifactValidationError`
        failures propagate unwrapped. The reader is imported only when this
        method is actually called.
        """
        from .dataset.reader import load_verified_dataset

        return load_verified_dataset(build_dir)
