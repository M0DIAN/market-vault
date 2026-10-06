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

from .atr import atr
from .candle_body import candle_body
from .candle_range import candle_range
from .ema import ema
from .log_return import log_return
from .kdj_d import kdj_d
from .kdj_j import kdj_j
from .kdj_k import kdj_k
from .macd import macd
from .macd_histogram import macd_histogram
from .macd_signal import macd_signal
from .obv import obv
from .rolling_mean import rolling_mean
from .rolling_std import rolling_std
from .rolling_volume_mean import rolling_volume_mean
from .rsi import rsi
from .simple_return import simple_return
from .sma import sma
from .volume_ratio import volume_ratio

__all__ = [
    "atr",
    "candle_body",
    "candle_range",
    "ema",
    "log_return",
    "kdj_d",
    "kdj_j",
    "kdj_k",
    "macd",
    "macd_histogram",
    "macd_signal",
    "obv",
    "rolling_mean",
    "rolling_std",
    "rolling_volume_mean",
    "rsi",
    "simple_return",
    "sma",
    "volume_ratio",
]
