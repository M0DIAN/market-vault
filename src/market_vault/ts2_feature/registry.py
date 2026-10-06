"""Nineteen fixed TS2 registrations; only static implementation source is read."""

from dataclasses import dataclass
import inspect
import sys
import types

from ..dataset.feature_transforms import (
    atr, candle_body, candle_range, ema, kdj_d, kdj_j, kdj_k, log_return,
    macd, macd_histogram,
    macd_signal, obv, rolling_mean, rolling_std, rolling_volume_mean, rsi,
    simple_return, sma, volume_ratio,
)
from ..dataset.models import ImplementationPin
from ..dataset.transform_models import _module_source_sha256
from ..dataset.encoding import encode_identity
from ._validation import TS2FeatureError, require, digest

TS2_FEATURE_REGISTRY_CONTRACT_VERSION = "ts2-feature-registry-v1"
TS2_FEATURE_EXECUTION_CONTRACT_VERSION = "ts2-feature-execution-v1"
TS2_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION = "ts2-feature-transform-call-v1"
TS2_FEATURE_IMPLEMENTATION_FINGERPRINT_VERSION = "ts2-feature-implementation-v1"
SOURCE_SCHEMA_VERSION = "10.9-mv-ts2"
CANONICAL_SCHEMA_VERSION = "market-bars-canonical-schema-v1"


@dataclass(frozen=True, slots=True)
class _Contract:
    name: str
    implementation: object
    fields: tuple[str, ...]
    minimum: int | None
    fixed_lookback: int = 1

    @property
    def transform_ref(self):
        return f"market_vault.dataset.feature_transforms.{self.name}:{self.name}"


_CONTRACTS = (
    _Contract("atr", atr, ("high", "low", "close"), 2),
    _Contract("candle_body", candle_body, ("open", "close"), None),
    _Contract("candle_range", candle_range, ("high", "low"), None),
    _Contract("ema", ema, ("close",), 1),
    _Contract("kdj_d", kdj_d, ("high", "low", "close"), 9),
    _Contract("kdj_j", kdj_j, ("high", "low", "close"), 9),
    _Contract("kdj_k", kdj_k, ("high", "low", "close"), 9),
    _Contract("log_return", log_return, ("close",), 2),
    _Contract("macd", macd, ("close",), None, 26),
    _Contract("macd_histogram", macd_histogram, ("close",), None, 34),
    _Contract("macd_signal", macd_signal, ("close",), None, 34),
    _Contract("obv", obv, ("close", "volume"), 2),
    _Contract("rolling_mean", rolling_mean, ("close",), 1),
    _Contract("rolling_std", rolling_std, ("close",), 2),
    _Contract("rolling_volume_mean", rolling_volume_mean, ("volume",), 1),
    _Contract("rsi", rsi, ("close",), 2),
    _Contract("simple_return", simple_return, ("close",), 2),
    _Contract("sma", sma, ("close",), 1),
    _Contract("volume_ratio", volume_ratio, ("volume",), 2),
)

# Compatibility baseline of the original TS2 registry shipped before the
# v0.9.0 Feature Library expansion.  These eight implementation pins remain
# part of every TS2 execution identity so historical Dataset/Artifact IDs do
# not churn when unrelated extension transforms are added later.
_BASELINE_CONTRACT_NAMES = frozenset((
    "candle_body",
    "candle_range",
    "log_return",
    "rolling_mean",
    "rolling_std",
    "rolling_volume_mean",
    "simple_return",
    "volume_ratio",
))


@dataclass(frozen=True, slots=True)
class _Registration:
    contract: _Contract
    source_sha256: str
    pin: ImplementationPin


def implementation_payload(contract, source_sha256):
    """The frozen F payload; calculating it does not confer result authority."""
    parameterized = contract.minimum is not None
    payload = dict(
        registry_contract_version=TS2_FEATURE_REGISTRY_CONTRACT_VERSION,
        execution_contract_version=TS2_FEATURE_EXECUTION_CONTRACT_VERSION,
        transform_call_contract_version=TS2_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION,
        input_transport_contract_version="market-vault-feature-transform-call-v1",
        transform_ref=contract.transform_ref, kind="FEATURE", implementation_version="v1",
        implementation_source_sha256=digest(source_sha256), canonical_schema_version=CANONICAL_SCHEMA_VERSION,
        source_schema_version=SOURCE_SCHEMA_VERSION, requested_session="RTH", adjustment="NONE", market="US",
        input_count=len(contract.fields), output_arity=1, output_logical_type="float64", output_nullable=False,
        parameter_count=int(parameterized), lookback_source="PARAMETER" if parameterized else "FIXED",
        lookback_unit="BARS", lookback_value=None if parameterized else contract.fixed_lookback,
        lookback_parameter_name="window_bars" if parameterized else None,
        lookforward_source="NONE", boundary_policy="SAME_MARKET_CALENDAR_DATE", missing_policy="EXCLUDE_SAMPLE",
        **{f"input_{i:04d}": name for i, name in enumerate(contract.fields)},
    )
    if parameterized:
        payload.update(parameter_0000_name="window_bars", parameter_0000_value_type="int64",
                       parameter_0000_nullable=False, parameter_0000_lower_bound=contract.minimum,
                       parameter_0000_upper_bound=9223372036854775807)
    return payload


def _build_registry(contracts):
    registrations = []
    for contract in contracts:
        require(type(contract.fixed_lookback) is int and contract.fixed_lookback >= 1,
                "REGISTRY_AUTHORITY", "fixed lookback must be a positive integer")
        require(contract.minimum is None or contract.fixed_lookback == 1,
                "REGISTRY_AUTHORITY", "parameterized transform cannot declare fixed lookback")
        fn = contract.implementation
        module_name, name = contract.transform_ref.split(":")
        module = sys.modules.get(module_name)
        require(type(fn) is types.FunctionType and fn.__module__ == module_name and fn.__name__ == name
                and fn.__qualname__ == name and not fn.__closure__ and module is not None
                and getattr(module, name, None) is fn and not inspect.isgeneratorfunction(fn)
                and not inspect.iscoroutinefunction(fn) and not inspect.isasyncgenfunction(fn),
                "REGISTRY_AUTHORITY", "static module/function binding mismatch")
        parameters = tuple(inspect.signature(fn).parameters.values())
        require(len(parameters) == 1 and parameters[0].kind in (
                    inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                and parameters[0].default is inspect.Parameter.empty,
                "REGISTRY_AUTHORITY", "one positional argument without defaults required")
        try:
            source = _module_source_sha256(fn, contract.transform_ref)
        except (ValueError, TypeError, OSError, UnicodeError) as exc:
            raise TS2FeatureError("SOURCE_FINGERPRINT", "static source acquisition failed") from exc
        fingerprint = encode_identity(TS2_FEATURE_IMPLEMENTATION_FINGERPRINT_VERSION,
                                      implementation_payload(contract, source))
        registrations.append(_Registration(contract, source, ImplementationPin(contract.transform_ref, "v1", fingerprint)))
    return tuple(registrations)


def _registry():
    """Full static catalog, used by catalog/identity tests and discovery."""
    return _build_registry(_CONTRACTS)


def _registry_for_specs(specs):
    """Compatibility baseline plus only extension transforms requested by specs.

    The original eight registrations remain identity-bearing for every TS2
    execution.  Feature-Library extensions are admitted lazily and become
    identity-bearing only when their exact transform_ref is requested.
    Unknown refs are intentionally not added here; _resolve rejects them.
    """
    require(type(specs) is tuple, "REGISTRY_AUTHORITY", "exact spec tuple required")
    requested_refs = frozenset(getattr(spec, "transform_ref", None) for spec in specs)
    selected = tuple(
        contract for contract in _CONTRACTS
        if contract.name in _BASELINE_CONTRACT_NAMES
        or contract.transform_ref in requested_refs
    )
    require(
        {contract.name for contract in selected if contract.name in _BASELINE_CONTRACT_NAMES}
        == _BASELINE_CONTRACT_NAMES,
        "REGISTRY_AUTHORITY",
        "TS2 compatibility baseline is incomplete",
    )
    return _build_registry(selected)
