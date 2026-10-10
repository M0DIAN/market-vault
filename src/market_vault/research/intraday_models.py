"""Fixed intraday quadratic Ridge representation, shared by DEV and Q23.

This module contains no source admission or new execution account. Callers
provide the already admitted historical rows and explicit prediction rows.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .intraday_data import digest
from .ridge_baseline import _column_stats
from .strategy_comparison import RidgeStrategy


INTRADAY_QUADRATIC_RIDGE_VERSION = "market-vault-intraday-quadratic-ridge-v1"
MAX_QUADRATIC_INPUT_FEATURES = 6


@dataclass(frozen=True, slots=True)
class QuadraticRidgeStrategy(RidgeStrategy):
    """The existing numeric Ridge options with a fixed degree-two basis."""


def quadratic_terms(features):
    if not 1 <= len(features) <= MAX_QUADRATIC_INPUT_FEATURES:
        raise ValueError("quadratic Ridge requires 1 to 6 saved Features")
    return ([{"name": f"z_{index}", "input_indices": [index]} for index in range(len(features))]
            + [{"name": f"z_{left}*z_{right}", "input_indices": [left, right]}
               for left in range(len(features)) for right in range(left, len(features))])


def input_values(observation, features):
    values = tuple(observation["features"][name] for name in features)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("quadratic Ridge input Feature is not finite")
    return values


def input_stats(training_values):
    means, scales = [], []
    for column in zip(*training_values, strict=True):
        # Equal TRAIN inputs stay zero in VALIDATION too, even when a rounded
        # arithmetic mean would differ from that constant input.
        if all(value == column[0] for value in column):
            mean, scale = column[0], 0.0
        else:
            column_means, column_scales = _column_stats(tuple((value,) for value in column))
            mean, scale = column_means[0], column_scales[0]
        means.append(mean)
        scales.append(scale)
    return tuple(means), tuple(scales)


def expanded_observation(observation, features, means, scales, terms):
    values = input_values(observation, features)
    normalized = tuple(0.0 if scale == 0 else (value - mean) / scale
                       for value, mean, scale in zip(values, means, scales, strict=True))
    if not all(math.isfinite(value) for value in normalized):
        raise ValueError("quadratic Ridge input normalization is not finite")
    expanded = {}
    for term in terms:
        indices = term["input_indices"]
        value = normalized[indices[0]]
        if len(indices) == 2:
            value *= normalized[indices[1]]
        if not math.isfinite(value):
            raise ValueError("quadratic Ridge generated term is not finite")
        expanded[term["name"]] = 0.0 if value == 0 else value
    return {**observation, "features": expanded}


def fit_quadratic_rows(rows, observations, features, alpha, *, boundary):
    """Fit both historical transforms and return the complete composite model."""
    from .intraday_research import fit_ridge_rows

    terms = quadratic_terms(features)
    means, scales = input_stats(tuple(input_values(row, features) for row, _ in rows))
    if not all(math.isfinite(value) for value in (*means, *scales)):
        raise ValueError("quadratic Ridge input normalization is not finite")
    expanded_training = tuple((expanded_observation(row, features, means, scales, terms), target)
                              for row, target in rows)
    validation = tuple(expanded_observation(row, features, means, scales, terms) for row in observations)
    ridge_model, values = fit_ridge_rows(expanded_training, validation,
        [term["name"] for term in terms], alpha, boundary=boundary)
    model = {"version": INTRADAY_QUADRATIC_RIDGE_VERSION, "kind": "QUADRATIC_BASIS_RIDGE",
             "alpha": alpha, "input_features": list(features),
             "input_transform": {"means": list(means), "scales": list(scales), "constant_policy": "ZERO"},
             "terms": terms, "training_keys": [row["observation_key"] for row, _ in rows],
             "training_boundary": boundary, "ridge_model": ridge_model}
    model["model_id"] = digest(model)
    return model, values
