"""Complete numeric implementation for the two frozen A4.1 transforms.

Only standard-library scalar predicates affect numeric behavior. The input
model is an immutable structural contract, never an external computation.
"""

import math


def _scalar(value, logical_type):
    if logical_type == "float64" and type(value) is float and math.isfinite(value):
        return 0.0 if value == 0.0 else value
    if logical_type == "int64" and type(value) is int and -(2**63) <= value < 2**63:
        return value
    raise ValueError("requires exact finite " + str(logical_type) + " scalar; no coercion")


def _identity(input_, logical_type):
    from .feature_models import ObservationFeatureTransformInput
    if type(input_) is not ObservationFeatureTransformInput:
        raise ValueError("requires ObservationFeatureTransformInput")
    if (len(input_.field_names) != 1 or input_.field_logical_types != (logical_type,)
            or len(input_.values) != 1 or input_.parameters != ()):
        raise ValueError("identity requires exactly one typed field and empty parameters")
    return _scalar(input_.values[0], logical_type)


def identity_float64(input_) -> float:
    return _identity(input_, "float64")


def identity_int64(input_) -> int:
    return _identity(input_, "int64")
