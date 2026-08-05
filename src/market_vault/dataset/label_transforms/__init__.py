"""Built-in Label transform implementations (v0.5.0 PR-4).

Each transform lives in its own self-contained module and registers under
its full stable ``transform_ref``
(``market_vault.dataset.label_transforms.<name>:<name>``); the PR-2
implementation fingerprint hashes each module's complete source, so a change
to one transform only churns that transform's pin. The functions are pure:
they never write files, never access external state, never read the current
time, and never touch the network. They consume only the frozen
:class:`LabelTransformInput` the executor constructed from the exact
Feature-close anchor row and the proven future Label rows.
"""

from __future__ import annotations

from .forward_direction import forward_direction
from .forward_return import forward_return
from .maximum_adverse_excursion import maximum_adverse_excursion
from .maximum_favorable_excursion import maximum_favorable_excursion

__all__ = [
    "forward_direction",
    "forward_return",
    "maximum_adverse_excursion",
    "maximum_favorable_excursion",
]
