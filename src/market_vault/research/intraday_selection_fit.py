"""Identical raw fits owned by one strictly prepared procedure-suite action."""

from __future__ import annotations

from copy import deepcopy
from functools import partial
from hashlib import sha256

from .intraday_selection_source import _PreparedSelectionSource
from .strategy_experiment import canonical_json


def _fit_key(rows, observations, features, recipe, boundary):
    # Retain the exact numeric JSON representation, including alpha 1 vs 1.0.
    # Keys alone cannot identify mutable decoded values. Project only what the
    # raw fitter consumes; prediction metadata is rebuilt for every caller.
    inputs = {"kind": recipe["kind"], "alpha": recipe["alpha"], "features": list(features),
        "training": [[row["observation_key"], [row["features"][name] for name in features], target["value"]]
                     for row, target in rows],
        "boundary": boundary,
        "observations": [[row["observation_key"], [row["features"][name] for name in features]]
                         for row in observations]}
    return sha256(canonical_json(inputs)).digest()


class _SelectionFitCache:
    """Private raw-model/score reuse; never a source-verification substitute."""

    def __init__(self, source: _PreparedSelectionSource):
        if type(source) is not _PreparedSelectionSource:
            raise ValueError("a prepared selection source is required for fit reuse")
        self._source = source
        self._fits = {}

    def fitter(self, source: _PreparedSelectionSource, fit):
        if source is not self._source:
            raise ValueError("fit reuse belongs to another prepared selection action")
        return partial(fit, fit_cache=self)

    def raw_fit(self, rows, observations, features, recipe, boundary, fit):
        key = _fit_key(rows, observations, features, recipe, boundary)
        cached = self._fits.get(key)
        if cached is None:
            model, scores = fit(rows, observations, features, recipe["alpha"], boundary=boundary)
            cached = model, tuple(scores)
            self._fits[key] = cached
        # A result cannot mutate this cache or another procedure's evidence.
        return deepcopy(cached[0]), cached[1]
