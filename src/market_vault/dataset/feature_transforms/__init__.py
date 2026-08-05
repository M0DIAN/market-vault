"""Built-in Feature transform implementations (v0.5.0 PR-3).

Each transform lives in its own self-contained module and registers under
its full stable ``transform_ref``
(``market_vault.dataset.feature_transforms.<name>:<name>``); the PR-2
implementation fingerprint hashes each module's complete source, so a change
to one transform only churns that transform's pin. The functions are pure:
they never write files, never access external state, never read the current
time, and never touch the network.
"""

from __future__ import annotations

from .candle_body import candle_body
from .candle_range import candle_range
from .log_return import log_return
from .rolling_mean import rolling_mean
from .rolling_std import rolling_std
from .rolling_volume_mean import rolling_volume_mean
from .simple_return import simple_return
from .volume_ratio import volume_ratio

__all__ = [
    "candle_body",
    "candle_range",
    "log_return",
    "rolling_mean",
    "rolling_std",
    "rolling_volume_mean",
    "simple_return",
    "volume_ratio",
]
