"""Offline deterministic tests for the Transform Implementation Registry
contract (v0.5.0 PR-2).

Covers frozen registration models, callable restrictions, the immutable
exact-key registry, FeatureSpec / LabelSpec compatibility preflight,
parameter-schema validation, v0.5 Label boundary gates, the versioned
implementation fingerprint, ImplementationPin generation, and the
DatasetIdentityInput / dataset_id integration. No network, no OpenD, no
stored market data, no current time, no locale, no registry-insertion-order
dependence, and no execution of any registered callable.
"""

from __future__ import annotations

import hashlib
import linecache
import os
import re
import sys
import types
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from market_vault.dataset import (
    BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
    BOUNDARY_POLICY_PIT_WINDOW_ONLY,
    BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    MISSING_POLICY_EXCLUDE_SAMPLE,
    MISSING_POLICY_FAIL,
    MISSING_POLICY_LABEL_INCOMPLETE,
    PARAMETER_TYPE_BOOL,
    PARAMETER_TYPE_FLOAT64,
    PARAMETER_TYPE_INT64,
    PARAMETER_TYPE_STRING,
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION,
    TRANSFORM_REGISTRY_CONTRACT_VERSION,
    WINDOW_BOUNDARY_EXCLUSIVE,
    WINDOW_BOUNDARY_INCLUSIVE,
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_LABEL_HORIZON,
    WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW,
    WINDOW_SOURCE_NONE,
    WINDOW_SOURCE_PARAMETER,
    WINDOW_UNIT_BARS,
    WINDOW_UNIT_MINUTES,
    WINDOW_UNIT_NONE,
    CanonicalBuildPin,
    CompletionEntry,
    CompletionSummary,
    CrossTradingDayPolicy,
    DatasetError,
    DatasetField,
    DatasetIdentityInput,
    DatasetScope,
    DatasetSchema,
    FeatureSpec,
    GapReference,
    ImplementationPin,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    ResolvedTransform,
    SourceSnapshotPin,
    SpecParameter,
    SpecPin,
    SpecValidationError,
    SpecVersionRequirements,
    TransformParameterContract,
    TransformRegistration,
    TransformRegistry,
    TransformRegistryError,
    TransformWindowRequirement,
    dataset_id,
    dataset_schema_id,
    feature_label_spec_content_id,
    feature_label_spec_pin,
    logical_dataset_content_id,
    transform_implementation_fingerprint,
    transform_implementation_pin,
)

UTC = timezone.utc
_SHA_HEX = re.compile(r"^[0-9a-f]{64}$")

FEATURE_SOURCE = '''\
"""Feature fixture implementation module."""

def my_transform(rows):
    return 1
'''

LABEL_SOURCE = '''\
"""Label fixture implementation module."""

def my_label(rows):
    return 1
'''


def sha(text) -> str:
    payload = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures: real module files on disk, registered in sys.modules without any
# import machinery, plus spec / registration builders.
# ---------------------------------------------------------------------------


@pytest.fixture
def impl(tmp_path, monkeypatch):
    """Build a plain module-level function with real on-disk source."""
    created: list[types.ModuleType] = []

    def _build(
        source: str,
        *,
        module_name: str | None = None,
        func_name: str = "my_transform",
        file_name: str | None = None,
    ) -> types.ModuleType:
        module_name = module_name or f"test_registry_impl_{len(created)}"
        file = tmp_path / (file_name or f"{module_name}.py")
        # Bytes on purpose: text-mode write would translate newlines on
        # Windows, corrupting the CRLF/LF equivalence tests.
        file.write_bytes(source.encode("utf-8"))
        module = types.ModuleType(module_name)
        module.__file__ = str(file)
        exec(compile(source, str(file), "exec"), module.__dict__)
        assert hasattr(module, func_name), f"module {module_name} lacks {func_name}"
        monkeypatch.setitem(sys.modules, module_name, module)
        created.append(module)
        linecache.clearcache()
        return module

    yield _build
    linecache.clearcache()


def registration(
    module: types.ModuleType,
    *,
    func_name: str = "my_transform",
    kind: str = SPEC_KIND_FEATURE,
    **overrides,
) -> TransformRegistration:
    ref = f"{module.__name__}:{func_name}"
    defaults = dict(
        transform_ref=ref,
        kind=kind,
        implementation_version="v1",
        implementation=getattr(module, func_name),
        input_canonical_fields=("close",),
        supported_canonical_schema_versions=("market-bars-canonical-schema-v1",),
        supported_source_schema_versions=("10.9",),
        output_logical_type="float64",
        output_nullable=True,
        parameters=(),
        lookback=TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE),
        lookforward=TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE),
        boundary_policy=BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
        missing_policy=MISSING_POLICY_FAIL,
        display_name=None,
    )
    defaults.update(overrides)
    return TransformRegistration(**defaults)


def feature_spec(
    transform_ref: str,
    *,
    name: str = "my_feature",
    parameters=(),
    **overrides,
) -> FeatureSpec:
    defaults = dict(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name, "float64", True),
        input_canonical_fields=("close",),
        transform_ref=transform_ref,
        parameters=tuple(parameters),
        requirements=SpecVersionRequirements(
            ("market-bars-canonical-schema-v1",), ("10.9",)
        ),
    )
    defaults.update(overrides)
    if "output" not in overrides and "name" in overrides:
        defaults["output"] = DatasetField(overrides["name"], "float64", True)
    return FeatureSpec(**defaults)


def label_spec(
    transform_ref: str,
    *,
    name: str = "my_label",
    parameters=(),
    **overrides,
) -> LabelSpec:
    defaults = dict(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name, "float64", True),
        input_canonical_fields=("close",),
        transform_ref=transform_ref,
        parameters=tuple(parameters),
        requirements=SpecVersionRequirements(
            ("market-bars-canonical-schema-v1",), ("10.9",)
        ),
        observation_window=LabelObservationWindow("BARS", 0, 5),
        horizon=LabelHorizon("BARS", 5),
        alignment_rule="ALIGN_CLOSE",
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )
    defaults.update(overrides)
    if "output" not in overrides and "name" in overrides:
        defaults["output"] = DatasetField(overrides["name"], "float64", True)
    return LabelSpec(**defaults)


def make_registry(*registrations) -> TransformRegistry:
    return TransformRegistry(tuple(registrations))


# ---------------------------------------------------------------------------
# A. Model validation.
# ---------------------------------------------------------------------------


def test_registration_is_frozen_and_deeply_immutable(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    with pytest.raises(FrozenInstanceError):
        setattr(reg, "transform_ref", "other")
    with pytest.raises(FrozenInstanceError):
        setattr(reg, "implementation_fingerprint", sha("x"))
    assert isinstance(reg.input_canonical_fields, tuple)
    assert isinstance(reg.supported_canonical_schema_versions, tuple)
    assert isinstance(reg.supported_source_schema_versions, tuple)
    assert isinstance(reg.parameters, tuple)
    for model in (reg, reg.lookback, reg.lookforward, reg.parameters[0]
                  if reg.parameters else reg.lookback):
        with pytest.raises(FrozenInstanceError):
            setattr(model, "x", 1)


def test_parameter_contract_frozen():
    contract = TransformParameterContract("lookback", PARAMETER_TYPE_INT64, False)
    with pytest.raises(FrozenInstanceError):
        setattr(contract, "name", "other")


def test_invalid_kind_rejected(impl):
    module = impl(FEATURE_SOURCE)
    for kind in ("SPLIT", "feature", "LABELx", "", 1, None):
        with pytest.raises(TransformRegistryError):
            registration(module, kind=kind)


def test_invalid_transform_ref_rejected(impl):
    module = impl(FEATURE_SOURCE)
    for ref in ("module", "module:", ":func", "module.func", "module::func",
                "1a:b", "a:b:c", "a.b:c.d", "a .b:c", "a.b:c d", ""):
        with pytest.raises(TransformRegistryError):
            registration(module, transform_ref=ref)
    # A well-formed ref that does not equal module:name is also rejected.
    with pytest.raises(TransformRegistryError):
        registration(module, transform_ref="some.other.module:my_transform")


def test_invalid_implementation_version_rejected(impl):
    module = impl(FEATURE_SOURCE)
    for version in ("", " ", " v1", "v1 ", 5, None, "v\x1f1"):
        with pytest.raises(TransformRegistryError):
            registration(module, implementation_version=version)


def test_duplicate_input_fields_rejected(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registration(module, input_canonical_fields=("close", "close"))
    with pytest.raises(TransformRegistryError):
        registration(module, input_canonical_fields=())


def test_duplicate_supported_versions_rejected(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registration(
            module,
            supported_canonical_schema_versions=("a", "a"),
        )
    with pytest.raises(TransformRegistryError):
        registration(module, supported_source_schema_versions=("b", "b"))
    with pytest.raises(TransformRegistryError):
        registration(module, supported_canonical_schema_versions=())
    with pytest.raises(TransformRegistryError):
        registration(module, supported_source_schema_versions=())


def test_invalid_output_contract_rejected(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registration(module, output_logical_type="object")
    with pytest.raises(TransformRegistryError):
        registration(module, output_logical_type="")
    with pytest.raises(TransformRegistryError):
        registration(module, output_nullable=1)
    with pytest.raises(TransformRegistryError):
        registration(module, output_nullable=None)


def test_output_arity_is_fixed_one(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    assert reg.output_arity == 1
    with pytest.raises(TypeError):
        registration(module, output_arity=2)  # init=False; not constructible


def test_duplicate_parameter_contracts_rejected(impl):
    module = impl(FEATURE_SOURCE)
    contracts = (
        TransformParameterContract("a", PARAMETER_TYPE_INT64, False),
        TransformParameterContract("b", PARAMETER_TYPE_INT64, False),
        TransformParameterContract("a", PARAMETER_TYPE_INT64, False),
    )
    with pytest.raises(TransformRegistryError):
        registration(module, parameters=contracts)


def test_parameter_contract_validation(impl):
    module = impl(FEATURE_SOURCE)
    # invalid name (empty, whitespace padding, unsafe text)
    for bad_name in ("", "   ", " look", "look ", "bad\x1fname", 5, None):
        with pytest.raises(TransformRegistryError):
            TransformParameterContract(bad_name, PARAMETER_TYPE_INT64, False)
    # invalid value type
    for value_type in ("int", "double", "OBJECT", "", None):
        with pytest.raises(TransformRegistryError):
            TransformParameterContract("p", value_type, False)
    # nullable must be a real bool
    with pytest.raises(TransformRegistryError):
        TransformParameterContract("p", PARAMETER_TYPE_INT64, 1)
    # bounds only on numeric contracts
    with pytest.raises(TransformRegistryError):
        TransformParameterContract(
            "p", PARAMETER_TYPE_BOOL, False, lower_bound=0
        )
    with pytest.raises(TransformRegistryError):
        TransformParameterContract(
            "p", PARAMETER_TYPE_STRING, False, upper_bound=5
        )
    # reversed bounds
    with pytest.raises(TransformRegistryError):
        TransformParameterContract(
            "p", PARAMETER_TYPE_INT64, False, lower_bound=10, upper_bound=5
        )
    # NaN / infinity bounds
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(TransformRegistryError):
            TransformParameterContract(
                "p", PARAMETER_TYPE_FLOAT64, False, lower_bound=bad
            )
    # bool bounds rejected
    with pytest.raises(TransformRegistryError):
        TransformParameterContract("p", PARAMETER_TYPE_INT64, False, lower_bound=True)


def test_parameter_contract_allowed_values():
    with pytest.raises(TransformRegistryError):
        TransformParameterContract("mode", PARAMETER_TYPE_STRING, False,
                                   allowed_values=("b", "a", "b"))  # duplicates
    with pytest.raises(TransformRegistryError):
        TransformParameterContract("mode", PARAMETER_TYPE_STRING, False,
                                   allowed_values=())
    # value-type mismatch
    with pytest.raises(TransformRegistryError):
        TransformParameterContract("mode", PARAMETER_TYPE_INT64, False,
                                   allowed_values=(1, "x"))
    with pytest.raises(TransformRegistryError):
        TransformParameterContract("mode", PARAMETER_TYPE_BOOL, False,
                                   allowed_values=(True, 1))
    with pytest.raises(TransformRegistryError):
        TransformParameterContract("mode", PARAMETER_TYPE_INT64, False,
                                   allowed_values=(None,))
    # deterministic sorting; stored as a tuple
    assert TransformParameterContract(
        "mode", PARAMETER_TYPE_STRING, False, allowed_values=("c", "a", "b")
    ).allowed_values == ("a", "b", "c")
    assert TransformParameterContract(
        "n", PARAMETER_TYPE_INT64, False, allowed_values=(3, 1, 2)
    ).allowed_values == (1, 2, 3)
    assert isinstance(
        TransformParameterContract(
            "mode", PARAMETER_TYPE_STRING, False, allowed_values=("x",)
        ).allowed_values,
        tuple,
    )
    assert TransformParameterContract(
        "mode", PARAMETER_TYPE_STRING, False
    ).allowed_values is None


def test_window_requirement_validation(impl):
    module = impl(FEATURE_SOURCE)
    # invalid source / unit / boundary
    for bad in ("LOOKBACK", "", None, 1):
        with pytest.raises(TransformRegistryError):
            TransformWindowRequirement(bad, WINDOW_UNIT_NONE)
    for bad in ("TRADING_DAYS", "BARSX", "", None):
        with pytest.raises(TransformRegistryError):
            TransformWindowRequirement(WINDOW_SOURCE_FIXED, bad, value=1)
    for bad in ("OPEN", "", None):
        with pytest.raises(TransformRegistryError):
            TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE, boundary=bad)
    # NONE must not carry value / parameter
    with pytest.raises(TransformRegistryError):
        TransformWindowRequirement(WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE, value=1)
    with pytest.raises(TransformRegistryError):
        TransformWindowRequirement(
            WINDOW_SOURCE_NONE, WINDOW_UNIT_NONE, parameter_name="n"
        )
    # FIXED requires a positive integer in BARS/MINUTES
    for bad_value in (0, -1, True, None, 1.5, "5"):
        with pytest.raises(TransformRegistryError):
            TransformWindowRequirement(WINDOW_SOURCE_FIXED, WINDOW_UNIT_BARS, value=bad_value)
    with pytest.raises(TransformRegistryError):
        TransformWindowRequirement(
            WINDOW_SOURCE_FIXED, WINDOW_UNIT_BARS, value=1, parameter_name="n"
        )
    assert TransformWindowRequirement(
        WINDOW_SOURCE_FIXED, WINDOW_UNIT_MINUTES, value=2
    ).value == 2
    # PARAMETER requires a safe non-empty parameter name
    for bad_name in (None, "", "  ", "bad\x1fname"):
        with pytest.raises(TransformRegistryError):
            TransformWindowRequirement(
                WINDOW_SOURCE_PARAMETER, WINDOW_UNIT_BARS, parameter_name=bad_name
            )
    with pytest.raises(TransformRegistryError):
        TransformWindowRequirement(
            WINDOW_SOURCE_PARAMETER, WINDOW_UNIT_BARS, parameter_name="n", value=1
        )
    # Label-derived sources must not carry a value or parameter name
    for source in (WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW, WINDOW_SOURCE_LABEL_HORIZON):
        with pytest.raises(TransformRegistryError):
            TransformWindowRequirement(source, WINDOW_UNIT_BARS, value=1)
    assert TransformWindowRequirement(
        WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS
    ).source == WINDOW_SOURCE_LABEL_HORIZON


def test_invalid_boundary_and_missing_policies_rejected(impl):
    module = impl(FEATURE_SOURCE)
    for policy in ("NO_CROSS_DAY", "", None, "pit_window_only"):
        with pytest.raises(TransformRegistryError):
            registration(module, boundary_policy=policy)
    for policy in ("NONE", "WARN", "", None, "fail"):
        with pytest.raises(TransformRegistryError):
            registration(module, missing_policy=policy)


def test_feature_missing_policy_label_incomplete_rejected(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registration(module, missing_policy=MISSING_POLICY_LABEL_INCOMPLETE)
    # LABEL may use it.
    label_module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(label_module, func_name="my_label",
                        kind=SPEC_KIND_LABEL,
                        missing_policy=MISSING_POLICY_LABEL_INCOMPLETE)
    assert reg.missing_policy == MISSING_POLICY_LABEL_INCOMPLETE


def test_feature_lookforward_must_be_none(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registration(module, lookforward=TransformWindowRequirement(
            WINDOW_SOURCE_FIXED, WINDOW_UNIT_BARS, value=1))
    # Label lookforward may be non-NONE.
    label_module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(
        label_module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookforward=TransformWindowRequirement(
            WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS),
    )
    assert reg.lookforward.source == WINDOW_SOURCE_LABEL_HORIZON


def test_label_derived_sources_restricted(impl):
    module = impl(FEATURE_SOURCE)
    # lookback never derives from a Label source.
    for source in (WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW, WINDOW_SOURCE_LABEL_HORIZON):
        with pytest.raises(TransformRegistryError):
            registration(module, lookback=TransformWindowRequirement(source, WINDOW_UNIT_BARS))
    # lookforward deriving from a Label source requires kind LABEL.
    with pytest.raises(TransformRegistryError):
        registration(module, lookforward=TransformWindowRequirement(
            WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS))
    label_module = impl(LABEL_SOURCE, func_name="my_label")
    registration(
        label_module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookback=TransformWindowRequirement(WINDOW_SOURCE_FIXED, WINDOW_UNIT_BARS, value=3),
        lookforward=TransformWindowRequirement(
            WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW, WINDOW_UNIT_BARS),
    )


def test_parameter_source_window_requirement_checks(impl):
    module = impl(FEATURE_SOURCE)
    lookback = TransformWindowRequirement(WINDOW_SOURCE_PARAMETER, WINDOW_UNIT_BARS,
                                          parameter_name="window")
    # parameter not declared
    with pytest.raises(TransformRegistryError):
        registration(module, lookback=lookback)
    # parameter declared but not int64
    with pytest.raises(TransformRegistryError):
        registration(
            module,
            parameters=(TransformParameterContract("window", PARAMETER_TYPE_FLOAT64, False),),
            lookback=lookback,
        )
    # nullable int64 parameter rejected for a window requirement
    with pytest.raises(TransformRegistryError):
        registration(
            module,
            parameters=(TransformParameterContract("window", PARAMETER_TYPE_INT64, True),),
            lookback=lookback,
        )
    # int64 contract without a lower_bound rejected (a window size must be a
    # positive integer contract)
    with pytest.raises(TransformRegistryError):
        registration(
            module,
            parameters=(TransformParameterContract("window", PARAMETER_TYPE_INT64, False),),
            lookback=lookback,
        )
    # lower_bound 0 or negative rejected
    for lower in (0, -1):
        with pytest.raises(TransformRegistryError):
            registration(
                module,
                parameters=(TransformParameterContract(
                    "window", PARAMETER_TYPE_INT64, False, lower_bound=lower),),
                lookback=lookback,
            )
    # allowed_values containing 0 or a negative rejected
    with pytest.raises(TransformRegistryError):
        registration(
            module,
            parameters=(TransformParameterContract(
                "window", PARAMETER_TYPE_INT64, False,
                lower_bound=1, allowed_values=(1, 0)),),
            lookback=lookback,
        )
    with pytest.raises(TransformRegistryError):
        registration(
            module,
            parameters=(TransformParameterContract(
                "window", PARAMETER_TYPE_INT64, False,
                lower_bound=1, allowed_values=(1, -2)),),
            lookback=lookback,
        )
    # positive contract with positive allowed_values accepted
    reg = registration(
        module,
        parameters=(TransformParameterContract(
            "window", PARAMETER_TYPE_INT64, False,
            lower_bound=1, upper_bound=10, allowed_values=(1, 2, 5)),),
        lookback=lookback,
    )
    assert reg.lookback.parameter_name == "window"


def test_parameter_window_spec_value_must_be_positive(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(
        module,
        parameters=(TransformParameterContract(
            "window", PARAMETER_TYPE_INT64, False, lower_bound=1),),
        lookback=TransformWindowRequirement(
            WINDOW_SOURCE_PARAMETER, WINDOW_UNIT_BARS, parameter_name="window"),
    )
    registry = make_registry(reg)
    # zero, negative, null, and bool all fail closed
    for value in (0, -1):
        with pytest.raises(TransformRegistryError):
            registry.resolve_spec(feature_spec(
                reg.transform_ref, parameters=(SpecParameter("window", value),)))
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(
            reg.transform_ref, parameters=(SpecParameter("window", None),)))
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(
            reg.transform_ref, parameters=(SpecParameter("window", True),)))
    # a positive value resolves
    resolved = registry.resolve_spec(feature_spec(
        reg.transform_ref, parameters=(SpecParameter("window", 1),)))
    assert resolved.parameters[0].value == 1
    resolved_big = registry.resolve_spec(feature_spec(
        reg.transform_ref, parameters=(SpecParameter("window", 120),)))
    assert resolved_big.parameters[0].value == 120


def test_display_name_validation(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registration(module, display_name="")
    with pytest.raises(TransformRegistryError):
        registration(module, display_name=" bad ")
    reg = registration(module, display_name="Close return")
    assert reg.display_name == "Close return"
    assert registration(module).display_name is None


def test_registration_error_is_dataset_error(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError) as caught:
        registration(module, kind="SPLIT")
    assert isinstance(caught.value, DatasetError)
    assert isinstance(caught.value, ValueError)
    assert str(caught.value)


# ---------------------------------------------------------------------------
# B. Callable restrictions.
# ---------------------------------------------------------------------------


def test_module_level_function_accepted(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    assert reg.transform_ref == f"{module.__name__}:my_transform"


def test_lambda_rejected(impl):
    module = impl("my_transform = lambda rows: 1\n", func_name="my_transform")
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_local_function_rejected(impl):
    module = impl(
        "def factory():\n    def my_transform(rows):\n        return 1\n"
        "    return my_transform\n\nmy_transform = factory()\n",
        func_name="my_transform",
    )
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_closure_rejected(impl):
    module = impl(
        "def factory():\n    x = 1\n    def my_transform(rows):\n"
        "        return x\n    return my_transform\n\n"
        "my_transform = factory()\n",
        func_name="my_transform",
    )
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_bound_method_rejected(impl):
    module = impl(
        "class C:\n    def my_transform(self, rows):\n        return 1\n\n"
        "my_transform = C().my_transform\n",
        func_name="my_transform",
    )
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_callable_object_rejected(impl):
    module = impl(
        "class C:\n    def __call__(self, rows):\n        return 1\n\n"
        "my_transform = C()\n",
        func_name="my_transform",
    )
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_builtin_rejected(impl):
    module = impl("my_transform = abs\n", func_name="my_transform")
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_async_function_rejected(impl):
    module = impl("async def my_transform(rows):\n    return 1\n",
                  func_name="my_transform")
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_generator_rejected(impl):
    module = impl("def my_transform(rows):\n    yield 1\n", func_name="my_transform")
    with pytest.raises(TransformRegistryError):
        registration(module)


def test_mismatched_transform_ref_rejected(impl):
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registration(module, transform_ref=f"{module.__name__}:other")


def test_missing_source_rejected(impl, monkeypatch):
    # A module with no __file__ (no stable source) fails closed.
    module = types.ModuleType("no_source_module")
    exec("def my_transform(rows):\n    return 1\n", module.__dict__)
    monkeypatch.setitem(sys.modules, "no_source_module", module)
    with pytest.raises(TransformRegistryError):
        registration(module)
    # A module whose file does not exist fails closed too.
    ghost = types.ModuleType("ghost_module")
    ghost.__file__ = "C:/definitely/not/here.py"
    exec("def my_transform(rows):\n    return 1\n", ghost.__dict__)
    monkeypatch.setitem(sys.modules, "ghost_module", ghost)
    with pytest.raises(TransformRegistryError):
        registration(ghost)


def test_implementation_is_never_executed(impl):
    calls = {"n": 0}
    source = (
        "CALLS = 0\n"
        "def my_transform(rows):\n"
        "    global CALLS\n"
        "    CALLS += 1\n"
        "    raise RuntimeError('must never be called')\n"
    )
    module = impl(source, func_name="my_transform")
    reg = registration(module)
    fingerprint = transform_implementation_fingerprint(reg)
    pin = transform_implementation_pin(reg)
    registry = make_registry(reg)
    resolved = registry.resolve_spec(feature_spec(reg.transform_ref))
    assert module.__dict__["CALLS"] == 0
    assert calls["n"] == 0
    assert fingerprint == reg.implementation_fingerprint
    assert resolved.pin == pin


# ---------------------------------------------------------------------------
# C. Registry.
# ---------------------------------------------------------------------------


def test_empty_registry_allowed_and_fails_closed(impl):
    # Decision: an empty registry is allowed; every resolve fails closed as
    # an unknown transform instead of silently succeeding.
    registry = TransformRegistry(())
    assert registry.registrations == ()
    module = impl(FEATURE_SOURCE)
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(f"{module.__name__}:my_transform"))


def test_registrations_sorted_deterministically(impl):
    a = impl(FEATURE_SOURCE, module_name="mod_a")
    b = impl(FEATURE_SOURCE, module_name="mod_b")
    reg_a = registration(a)
    reg_b = registration(b)
    registry = TransformRegistry((reg_b, reg_a))
    assert tuple(r.transform_ref for r in registry.registrations) == (
        "mod_a:my_transform",
        "mod_b:my_transform",
    )
    assert TransformRegistry((reg_a, reg_b)).registrations == registry.registrations


def test_duplicate_transform_ref_rejected(impl):
    module = impl(FEATURE_SOURCE)
    reg_a = registration(module, implementation_version="v1")
    reg_b = registration(module, implementation_version="v2")
    with pytest.raises(TransformRegistryError):
        TransformRegistry((reg_a, reg_b))
    with pytest.raises(TransformRegistryError):
        TransformRegistry((reg_a, reg_a))  # byte-identical duplicates too


def test_unknown_transform_rejected(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec("market_vault.nothing:missing"))


def test_registry_immutable_after_construction(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    with pytest.raises(FrozenInstanceError):
        registry.registrations = ()
    with pytest.raises(FrozenInstanceError):
        setattr(registry, "registrations", ())
    assert isinstance(registry.registrations, tuple)


def test_registry_construction_type_errors_wrapped():
    """Non-iterable registrations fail as TransformRegistryError; no bare
    TypeError leaks."""
    for bad in (None, 1, object()):
        with pytest.raises(TransformRegistryError) as caught:
            TransformRegistry(bad)
        assert isinstance(caught.value, DatasetError)
    # Bare strings must not be treated as a list of registrations either.
    with pytest.raises(TransformRegistryError):
        TransformRegistry("not a registration")


def test_resolve_never_imports_transform_ref(impl, monkeypatch):
    """Resolution must not import the ref's module, touch the filesystem for
    it, or scan anything."""
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    before = set(sys.modules)
    resolved = registry.resolve_spec(feature_spec(registry.registrations[0].transform_ref))
    assert set(sys.modules) == before
    assert resolved.pin is not None
    # A nonexistent module ref fails as unknown, never as an import error.
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec("this_module_does_not_exist_xyz:fn"))


def test_no_global_registry_on_import():
    import market_vault.dataset as dataset
    namespace = {name: getattr(dataset, name) for name in dir(dataset)}
    registry_instances = [
        value for value in namespace.values()
        if isinstance(value, TransformRegistry)
    ]
    assert registry_instances == []


# ---------------------------------------------------------------------------
# D. Spec compatibility preflight.
# ---------------------------------------------------------------------------


def test_valid_feature_spec_resolves(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    registry = make_registry(reg)
    spec = feature_spec(reg.transform_ref)
    resolved = registry.resolve_spec(spec)
    assert isinstance(resolved, ResolvedTransform)
    assert resolved.spec is spec
    assert resolved.registration is reg
    assert resolved.parameters == spec.parameters
    assert resolved.pin == transform_implementation_pin(reg)
    assert resolved.pin.name == reg.transform_ref
    assert resolved.pin.version == "v1"
    assert _SHA_HEX.fullmatch(resolved.pin.content_sha256)


def test_valid_label_spec_resolves(impl):
    module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(
        module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookforward=TransformWindowRequirement(
            WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS),
    )
    registry = make_registry(reg)
    spec = label_spec(reg.transform_ref)
    resolved = registry.resolve_label_spec(spec)
    assert resolved.spec is spec
    assert resolved.registration is reg
    assert resolved.pin == transform_implementation_pin(reg)


def test_kind_mismatch_rejected(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(label_spec(module.__name__ + ":my_transform"))


def test_input_mismatch_rejected(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    spec = feature_spec(
        registry.registrations[0].transform_ref,
        input_canonical_fields=("open",),
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


def test_input_order_mismatch_rejected(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module, input_canonical_fields=("close", "open"))
    registry = make_registry(reg)
    spec = feature_spec(reg.transform_ref, input_canonical_fields=("open", "close"))
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


def test_output_type_mismatch_rejected(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    spec = feature_spec(
        registry.registrations[0].transform_ref,
        output=DatasetField("my_feature", "string", True),
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


def test_output_nullable_mismatch_rejected(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    spec = feature_spec(
        registry.registrations[0].transform_ref,
        output=DatasetField("my_feature", "float64", False),
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


def test_unsupported_schema_versions_rejected(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    ref = registry.registrations[0].transform_ref
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(
            ref,
            requirements=SpecVersionRequirements(
                ("market-bars-canonical-schema-v2",), ("10.9",)),
        ))
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(
            ref,
            requirements=SpecVersionRequirements(
                ("market-bars-canonical-schema-v1",), ("10.8",)),
        ))


def test_registration_supporting_more_versions_resolves(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(
        module,
        supported_canonical_schema_versions=(
            "market-bars-canonical-schema-v1", "market-bars-canonical-schema-v2"),
        supported_source_schema_versions=("10.8", "10.9"),
    )
    registry = make_registry(reg)
    resolved = registry.resolve_spec(feature_spec(reg.transform_ref))
    assert resolved.registration is reg
    # The spec is never modified to match the registration.
    assert resolved.spec.requirements.canonical_schema_versions == (
        "market-bars-canonical-schema-v1",)


def test_missing_parameter_rejected(impl):
    module = impl(FEATURE_SOURCE)
    contracts = (TransformParameterContract("window", PARAMETER_TYPE_INT64, False),)
    reg = registration(module, parameters=contracts)
    registry = make_registry(reg)
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(reg.transform_ref, parameters=()))


def test_unknown_parameter_rejected(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    spec = feature_spec(
        registry.registrations[0].transform_ref,
        parameters=(SpecParameter("extra", 1),),
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


def test_parameter_type_mismatch_rejected(impl):
    module = impl(FEATURE_SOURCE)
    contracts = (TransformParameterContract("n", PARAMETER_TYPE_INT64, False),)
    reg = registration(module, parameters=contracts)
    registry = make_registry(reg)
    for value in ("5", 5.0, 5.5):
        with pytest.raises(TransformRegistryError):
            registry.resolve_spec(feature_spec(
                reg.transform_ref, parameters=(SpecParameter("n", value),)))
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(
            reg.transform_ref, parameters=(SpecParameter("n", None),)))


def test_bool_as_int_and_int_as_bool_rejected(impl):
    module = impl(FEATURE_SOURCE)
    int_reg = registration(
        module, parameters=(TransformParameterContract("n", PARAMETER_TYPE_INT64, False),))
    bool_reg = registration(
        module, parameters=(TransformParameterContract("f", PARAMETER_TYPE_BOOL, False),),
        implementation_version="v2",
    )
    with pytest.raises(TransformRegistryError):
        make_registry(int_reg).resolve_spec(feature_spec(
            int_reg.transform_ref, parameters=(SpecParameter("n", True),)))
    with pytest.raises(TransformRegistryError):
        make_registry(bool_reg).resolve_spec(feature_spec(
            bool_reg.transform_ref, parameters=(SpecParameter("f", 1),)))
    resolved = make_registry(int_reg).resolve_spec(feature_spec(
        int_reg.transform_ref, parameters=(SpecParameter("n", 1),)))
    assert resolved.parameters[0].value == 1


def test_range_violation_rejected(impl):
    module = impl(FEATURE_SOURCE)
    contracts = (
        TransformParameterContract("n", PARAMETER_TYPE_INT64, False,
                                   lower_bound=1, upper_bound=10),
    )
    reg = registration(module, parameters=contracts)
    registry = make_registry(reg)
    for value in (0, 11, 2**63 - 1):
        with pytest.raises(TransformRegistryError):
            registry.resolve_spec(feature_spec(
                reg.transform_ref, parameters=(SpecParameter("n", value),)))
    resolved = registry.resolve_spec(feature_spec(
        reg.transform_ref, parameters=(SpecParameter("n", 5),)))
    assert resolved.parameters[0].value == 5


def test_choices_violation_rejected(impl):
    module = impl(FEATURE_SOURCE)
    contracts = (
        TransformParameterContract("mode", PARAMETER_TYPE_STRING, False,
                                   allowed_values=("simple", "log")),
    )
    reg = registration(module, parameters=contracts)
    registry = make_registry(reg)
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(feature_spec(
            reg.transform_ref, parameters=(SpecParameter("mode", "other"),)))
    resolved = registry.resolve_spec(feature_spec(
        reg.transform_ref, parameters=(SpecParameter("mode", "log"),)))
    assert resolved.parameters[0].value == "log"


def test_nullable_contract(impl):
    module = impl(FEATURE_SOURCE)
    nullable_reg = registration(
        module,
        parameters=(TransformParameterContract("opt", PARAMETER_TYPE_STRING, True),),
    )
    non_nullable_reg = registration(
        module,
        parameters=(TransformParameterContract("opt", PARAMETER_TYPE_STRING, False),),
        implementation_version="v2",
    )
    with pytest.raises(TransformRegistryError):
        make_registry(non_nullable_reg).resolve_spec(feature_spec(
            non_nullable_reg.transform_ref,
            parameters=(SpecParameter("opt", None),)))
    resolved = make_registry(nullable_reg).resolve_spec(feature_spec(
        nullable_reg.transform_ref, parameters=(SpecParameter("opt", None),)))
    assert resolved.parameters[0].value is None


def test_parameter_order_determinism(impl):
    module = impl(FEATURE_SOURCE)
    contracts = (
        TransformParameterContract("z", PARAMETER_TYPE_INT64, False),
        TransformParameterContract("a", PARAMETER_TYPE_INT64, False),
    )
    reg = registration(module, parameters=contracts)
    registry = make_registry(reg)
    spec = feature_spec(
        reg.transform_ref,
        parameters=(SpecParameter("z", 1), SpecParameter("a", 2)),
    )
    resolved = registry.resolve_spec(spec)
    assert tuple(p.name for p in resolved.parameters) == ("a", "z")
    assert resolved.spec is spec  # never mutated


def test_float_and_bool_and_string_contracts(impl):
    module = impl(FEATURE_SOURCE)
    contracts = (
        TransformParameterContract("f", PARAMETER_TYPE_FLOAT64, False, lower_bound=0.0),
        TransformParameterContract("flag", PARAMETER_TYPE_BOOL, False),
        TransformParameterContract("name", PARAMETER_TYPE_STRING, False),
    )
    reg = registration(module, parameters=contracts)
    registry = make_registry(reg)
    spec = feature_spec(
        reg.transform_ref,
        parameters=(
            SpecParameter("f", 1.5),
            SpecParameter("flag", True),
            SpecParameter("name", "x"),
        ),
    )
    resolved = registry.resolve_spec(spec)
    assert dict((p.name, p.value) for p in resolved.parameters) == {
        "f": 1.5, "flag": True, "name": "x",
    }


def test_resolve_typed_wrappers(impl):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    with pytest.raises(TransformRegistryError):
        registry.resolve_feature_spec("not a spec")
    with pytest.raises(TransformRegistryError):
        registry.resolve_label_spec("not a spec")


def test_resolved_transform_direct_construction_validation(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    registry = make_registry(reg)
    spec = feature_spec(reg.transform_ref)
    resolved = registry.resolve_spec(spec)
    # A consistent reconstruction is accepted and equal.
    assert ResolvedTransform(
        spec=spec, registration=reg,
        parameters=spec.parameters, pin=resolved.pin,
    ) == resolved
    # wrong spec type
    for bad_spec in ("not a spec", object(), None):
        with pytest.raises(TransformRegistryError):
            ResolvedTransform(spec=bad_spec, registration=reg,
                              parameters=(), pin=resolved.pin)
    # FeatureSpec + LABEL registration rejected
    label_module = impl(LABEL_SOURCE, func_name="my_label")
    label_reg = registration(label_module, func_name="my_label",
                              kind=SPEC_KIND_LABEL)
    with pytest.raises(TransformRegistryError):
        ResolvedTransform(spec=spec, registration=label_reg,
                          parameters=spec.parameters, pin=resolved.pin)
    # transform_ref mismatch rejected
    other_module = impl(FEATURE_SOURCE, module_name="other_mod")
    other_reg = registration(other_module)
    with pytest.raises(TransformRegistryError):
        ResolvedTransform(spec=spec, registration=other_reg,
                          parameters=spec.parameters, pin=resolved.pin)
    # parameter mismatch rejected (missing, wrong value, non-tuple) — the
    # spec must declare parameters for the mismatch to be observable
    param_reg = registration(
        module,
        parameters=(TransformParameterContract("n", PARAMETER_TYPE_INT64, False),),
        implementation_version="v2",
    )
    param_spec = feature_spec(param_reg.transform_ref,
                              parameters=(SpecParameter("n", 5),))
    param_resolved = make_registry(param_reg).resolve_spec(param_spec)
    with pytest.raises(TransformRegistryError):
        ResolvedTransform(spec=param_spec, registration=param_reg, parameters=(),
                          pin=param_resolved.pin)
    with pytest.raises(TransformRegistryError):
        ResolvedTransform(spec=param_spec, registration=param_reg,
                          parameters=(SpecParameter("n", 6),), pin=param_resolved.pin)
    with pytest.raises(TransformRegistryError):
        ResolvedTransform(spec=param_spec, registration=param_reg,
                          parameters="abc", pin=param_resolved.pin)
    # a consistent parameterized reconstruction is accepted
    assert ResolvedTransform(
        spec=param_spec, registration=param_reg,
        parameters=param_spec.parameters, pin=param_resolved.pin,
    ) == param_resolved
    # unrelated pin rejected
    other_pin = transform_implementation_pin(other_reg)
    with pytest.raises(TransformRegistryError):
        ResolvedTransform(spec=spec, registration=reg,
                          parameters=spec.parameters, pin=other_pin)
    # non-ImplementationPin rejected
    for bad_pin in ("not a pin", object(), None):
        with pytest.raises(TransformRegistryError):
            ResolvedTransform(spec=spec, registration=reg,
                              parameters=spec.parameters, pin=bad_pin)
    # frozen behavior preserved
    with pytest.raises(FrozenInstanceError):
        resolved.registration = reg
    with pytest.raises(FrozenInstanceError):
        setattr(resolved, "pin", other_pin)


# ---------------------------------------------------------------------------
# E. v0.5 Label boundaries.
# ---------------------------------------------------------------------------


def test_trading_days_label_rejected(impl):
    module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(
        module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookforward=TransformWindowRequirement(WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS),
    )
    registry = make_registry(reg)
    spec = label_spec(
        reg.transform_ref,
        observation_window=LabelObservationWindow("TRADING_DAYS", 0, 1),
        horizon=LabelHorizon("TRADING_DAYS", 1),
        cross_trading_day=CrossTradingDayPolicy(True, "END_OF_TRADING_DAY"),
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


def test_cross_trading_day_opt_in_rejected(impl):
    module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(
        module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookforward=TransformWindowRequirement(WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS),
    )
    registry = make_registry(reg)
    spec = label_spec(
        reg.transform_ref,
        observation_window=LabelObservationWindow("BARS", 0, 5),
        horizon=LabelHorizon("BARS", 5),
        cross_trading_day=CrossTradingDayPolicy(True, "END_OF_TRADING_DAY"),
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


def test_bars_no_cross_day_label_accepted(impl):
    module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(
        module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookforward=TransformWindowRequirement(WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS),
    )
    registry = make_registry(reg)
    resolved = registry.resolve_spec(label_spec(reg.transform_ref))
    assert resolved.pin is not None


def test_minutes_label_accepted(impl):
    module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(
        module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookforward=TransformWindowRequirement(
            WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW, WINDOW_UNIT_MINUTES),
    )
    registry = make_registry(reg)
    spec = label_spec(
        reg.transform_ref,
        observation_window=LabelObservationWindow("MINUTES", 0, 30),
        horizon=LabelHorizon("MINUTES", 30),
    )
    resolved = registry.resolve_spec(spec)
    assert resolved.pin is not None


def test_label_lookforward_unit_mismatch_rejected(impl):
    module = impl(LABEL_SOURCE, func_name="my_label")
    reg = registration(
        module, func_name="my_label", kind=SPEC_KIND_LABEL,
        lookforward=TransformWindowRequirement(WINDOW_SOURCE_LABEL_HORIZON, WINDOW_UNIT_BARS),
    )
    registry = make_registry(reg)
    spec = label_spec(
        reg.transform_ref,
        observation_window=LabelObservationWindow("MINUTES", 0, 30),
        horizon=LabelHorizon("MINUTES", 30),
    )
    with pytest.raises(TransformRegistryError):
        registry.resolve_spec(spec)


# ---------------------------------------------------------------------------
# F. Implementation fingerprint.
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic_same_inputs(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    assert transform_implementation_fingerprint(reg) == reg.implementation_fingerprint
    assert _SHA_HEX.fullmatch(reg.implementation_fingerprint)
    assert len(reg.implementation_fingerprint) == 64
    # A second registration over the same source and metadata agrees.
    reg_again = registration(module)
    assert reg_again.implementation_fingerprint == reg.implementation_fingerprint


def test_fingerprint_rejects_non_registration():
    with pytest.raises(TransformRegistryError):
        transform_implementation_fingerprint("not a registration")
    with pytest.raises(TransformRegistryError):
        transform_implementation_pin("not a registration")


def test_registry_order_irrelevant(impl):
    a = impl(FEATURE_SOURCE, module_name="mod_a")
    b = impl(FEATURE_SOURCE, module_name="mod_b")
    reg_a = registration(a)
    reg_b = registration(b)
    first = TransformRegistry((reg_a, reg_b))
    second = TransformRegistry((reg_b, reg_a))
    assert first.resolve_spec(feature_spec(reg_a.transform_ref)).pin == \
        second.resolve_spec(feature_spec(reg_a.transform_ref)).pin
    assert first.resolve_spec(feature_spec(reg_b.transform_ref)).pin == \
        second.resolve_spec(feature_spec(reg_b.transform_ref)).pin


def test_crlf_lf_normalization_equivalence(tmp_path, impl):
    # The two modules share one transform_ref (same module name, different
    # source files) so only the newline style differs.
    source_lf = FEATURE_SOURCE
    source_crlf = FEATURE_SOURCE.replace("\n", "\r\n")
    lf_reg = registration(impl(source_lf, module_name="nl_mod"))
    crlf_reg = registration(
        impl(source_crlf, module_name="nl_mod", file_name="crlf_file.py"))
    assert lf_reg.implementation_fingerprint == crlf_reg.implementation_fingerprint


def test_triple_quoted_string_whitespace_is_preserved(impl):
    """Trailing whitespace inside a triple-quoted string literal is source
    content and must change the fingerprint (no per-line trimming)."""
    base = ('"""doc"""\n'
            '\n'
            'def my_transform(rows):\n'
            '    value = """prefix  \n'
            '    suffix"""\n'
            '    return value\n')
    changed = ('"""doc"""\n'
               '\n'
               'def my_transform(rows):\n'
               '    value = """prefix \n'
               '    suffix"""\n'
               '    return value\n')
    base_reg = registration(impl(base, module_name="str_mod"))
    changed_reg = registration(
        impl(changed, module_name="str_mod", file_name="str_file.py"))
    assert base_reg.implementation_fingerprint != changed_reg.implementation_fingerprint


def test_ordinary_line_trailing_whitespace_changes_fingerprint(impl):
    """Trailing whitespace on ordinary code lines is source content; the
    conservative contract lets it change the fingerprint."""
    base = '"""doc"""\n\ndef my_transform(rows):\n    return 1\n'
    changed = '"""doc"""\n\ndef my_transform(rows):\n    return 1  \n'
    assert registration(impl(base, module_name="ws2_mod")).implementation_fingerprint != \
        registration(impl(changed, module_name="ws2_mod",
                          file_name="ws2_file.py")).implementation_fingerprint


def test_source_semantic_change_changes_fingerprint(impl):
    # One transform_ref; only the source body changes.
    base = registration(impl('"""doc"""\n\ndef my_transform(rows):\n    return 1\n',
                             module_name="sem_mod"))
    changed = registration(
        impl('"""doc"""\n\ndef my_transform(rows):\n    return 2\n',
             module_name="sem_mod", file_name="changed_file.py"),
    )
    assert changed.implementation_fingerprint != base.implementation_fingerprint


def test_registration_metadata_change_changes_fingerprint(impl):
    module = impl(FEATURE_SOURCE)
    base = registration(module)
    for changed in (
        registration(module, boundary_policy=BOUNDARY_POLICY_NO_CROSS_TRADING_DAY),
        registration(module, missing_policy=MISSING_POLICY_EXCLUDE_SAMPLE),
        registration(module, display_name="Renamed"),
        registration(module, output_logical_type="string"),
        registration(module, output_nullable=False),
        registration(module, input_canonical_fields=("open",)),
        registration(module, lookback=TransformWindowRequirement(
            WINDOW_SOURCE_FIXED, WINDOW_UNIT_BARS, value=3,
            boundary=WINDOW_BOUNDARY_EXCLUSIVE)),
        registration(module, parameters=(
            TransformParameterContract("n", PARAMETER_TYPE_INT64, False),)),
    ):
        assert changed.implementation_fingerprint != base.implementation_fingerprint
        assert transform_implementation_pin(changed) != transform_implementation_pin(base)


def test_implementation_version_change_changes_pin_and_fingerprint(impl):
    module = impl(FEATURE_SOURCE)
    v1 = transform_implementation_pin(registration(module, implementation_version="v1"))
    v2 = transform_implementation_pin(registration(module, implementation_version="v2"))
    assert v2 != v1
    assert v2.version == "v2"
    assert v2.content_sha256 != v1.content_sha256  # version is in the payload


def test_path_and_mtime_absent_from_fingerprint(tmp_path, impl):
    dir_one = tmp_path / "one"
    dir_two = tmp_path / "two"
    dir_one.mkdir()
    dir_two.mkdir()
    file_one = dir_one / "impl_a.py"
    file_two = dir_two / "impl_b.py"
    file_one.write_bytes(FEATURE_SOURCE.encode("utf-8"))
    file_two.write_bytes(FEATURE_SOURCE.encode("utf-8"))

    def build_module(path, name):
        module = types.ModuleType(name)
        module.__file__ = str(path)
        exec(compile(FEATURE_SOURCE, str(path), "exec"), module.__dict__)
        sys.modules[name] = module
        linecache.clearcache()
        return module

    try:
        # One transform_ref (same module name) with two source paths.
        a_reg = registration(build_module(file_one, "path_mod"))
        b_reg = registration(build_module(file_two, "path_mod"))
        assert a_reg.implementation_fingerprint == b_reg.implementation_fingerprint
        # mtime change never changes the fingerprint (construction snapshot).
        old_mtime = os.stat(file_one).st_mtime
        os.utime(file_one, (old_mtime + 3600, old_mtime + 3600))
        assert a_reg.implementation_fingerprint == b_reg.implementation_fingerprint
        # The fingerprint never equals the raw file byte hash and never
        # contains the file path.
        assert a_reg.implementation_fingerprint != sha(FEATURE_SOURCE)
        assert str(file_one) not in a_reg.implementation_fingerprint
        assert str(id(a_reg.implementation)) not in a_reg.implementation_fingerprint
    finally:
        sys.modules.pop("path_mod", None)
        linecache.clearcache()


def test_pin_never_none_content_hash(impl):
    module = impl(FEATURE_SOURCE)
    pin = transform_implementation_pin(registration(module))
    assert isinstance(pin, ImplementationPin)
    assert pin.content_sha256 is not None
    assert _SHA_HEX.fullmatch(pin.content_sha256)
    assert pin.name == f"{module.__name__}:my_transform"


# ---------------------------------------------------------------------------
# G. Cross-contract: DatasetIdentityInput / dataset_id integration.
# ---------------------------------------------------------------------------


def identity_input(feature_specs=(), label_specs=(), implementations=()):
    schema = DatasetSchema(
        (DatasetField("ts", "timestamp_us_utc", False),
         DatasetField("close", "float64", True))
    )
    scope = DatasetScope(
        ["US.MU"], [date(2026, 7, 1)], adjustment="NONE", interval="1m",
        requested_session="ALL",
    )
    build = CanonicalBuildPin(
        canonical_build_id=sha("build"),
        canonical_content_id=sha("content"),
        canonical_builder_version="market-bars-canonical-builder-v1",
        canonical_schema_version="market-bars-canonical-schema-v1",
        materializer_version="market-bars-materializer-v1",
        gap_policy_version="market-bars-gap-policy-v1",
        gap_content_id=sha("gap"),
        status="COMPLETE",
        canonical_row_version_ids=(sha("row-1"), sha("row-2")),
        source_snapshots=(
            SourceSnapshotPin("run-1", sha("phys"), sha("logical"), "10.9",
                              date(2026, 7, 1), "ALL"),
        ),
    )
    rows = [
        {"ts": datetime(2026, 7, 1, 13, 30, tzinfo=UTC), "close": 100.5},
        {"ts": datetime(2026, 7, 1, 13, 31, tzinfo=UTC), "close": 101.25},
    ]
    return DatasetIdentityInput(
        dataset_kind="market_bars_dataset",
        scope=scope,
        dataset_as_of=None,
        schema=schema,
        dataset_schema_id=dataset_schema_id(schema),
        logical_dataset_content_id=logical_dataset_content_id(schema, rows),
        canonical_builds=(build,),
        canonical_row_version_ids=build.canonical_row_version_ids,
        feature_specs=tuple(feature_specs),
        label_specs=tuple(label_specs),
        split_spec=None,
        implementations=tuple(implementations),
        completion=CompletionSummary(
            1, 0, 0, (CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),)
        ),
        gap_references=(GapReference(build.canonical_build_id, build.gap_content_id, 0),),
    )


def test_pin_enters_dataset_identity_input(impl):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    registry = make_registry(reg)
    spec = feature_spec(reg.transform_ref)
    resolved = registry.resolve_spec(spec)
    base = dataset_id(identity_input(feature_specs=(feature_label_spec_pin(spec),)))
    with_pin = dataset_id(identity_input(
        feature_specs=(feature_label_spec_pin(spec),),
        implementations=(resolved.pin,),
    ))
    assert with_pin != base
    assert dataset_id(identity_input(
        feature_specs=(feature_label_spec_pin(spec),),
        implementations=(resolved.pin,),
    )) == with_pin  # deterministic


def test_pin_change_changes_dataset_id(impl):
    module = impl(FEATURE_SOURCE)
    spec = feature_spec(f"{module.__name__}:my_transform")
    spec_pin = feature_label_spec_pin(spec)
    pin_v1 = transform_implementation_pin(registration(module, implementation_version="v1"))
    pin_v2 = transform_implementation_pin(registration(module, implementation_version="v2"))
    pin_meta = transform_implementation_pin(registration(module, display_name="Other"))
    id_v1 = dataset_id(identity_input(feature_specs=(spec_pin,), implementations=(pin_v1,)))
    assert dataset_id(identity_input(feature_specs=(spec_pin,), implementations=(pin_v2,))) != id_v1
    assert dataset_id(identity_input(feature_specs=(spec_pin,), implementations=(pin_meta,))) != id_v1
    # Identical pins in any registry order produce the identical dataset_id.
    other = impl(FEATURE_SOURCE, module_name="mod_other")
    reg_other = registration(other)
    registry_a = TransformRegistry((reg_other,))
    resolved = registry_a.resolve_spec(feature_spec(reg_other.transform_ref))
    same = dataset_id(identity_input(feature_specs=(spec_pin,), implementations=(resolved.pin,)))
    assert dataset_id(identity_input(feature_specs=(spec_pin,), implementations=(pin_meta,))) != same


def test_existing_identity_contracts_untouched(impl):
    """The registry never modifies existing identity algorithms: spec pins
    and content IDs behave exactly as before, and dataset_id with no
    implementations is deterministic under the existing contract."""
    module = impl(FEATURE_SOURCE)
    spec = feature_spec(f"{module.__name__}:my_transform")
    spec_pin = feature_label_spec_pin(spec)
    assert isinstance(spec_pin, SpecPin)
    assert spec_pin.kind == SPEC_KIND_FEATURE
    content_id = feature_label_spec_content_id(spec)
    assert _SHA_HEX.fullmatch(content_id)
    assert feature_label_spec_pin(spec).content_sha256 == content_id
    first = dataset_id(identity_input(feature_specs=(spec_pin,)))
    second = dataset_id(identity_input(feature_specs=(spec_pin,)))
    assert first == second


# ---------------------------------------------------------------------------
# H. Offline / no-side-effect guarantees.
# ---------------------------------------------------------------------------


def test_resolve_offline_no_write_no_cwd_change(impl, tmp_path):
    module = impl(FEATURE_SOURCE)
    registry = make_registry(registration(module))
    spec = feature_spec(registry.registrations[0].transform_ref)
    cwd = os.getcwd()
    registry.resolve_spec(spec)
    assert os.getcwd() == cwd
    datasets_dir = tmp_path / "data" / "datasets"
    assert not datasets_dir.exists()


def test_no_timezone_dependence(impl, monkeypatch):
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    base = reg.implementation_fingerprint
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    reg_tz = registration(module)
    assert reg_tz.implementation_fingerprint == base


def test_fingerprint_never_hash_or_id_based(impl):
    """The fingerprint is a deterministic SHA-256, never Python's
    process-randomized hash() and never a memory-address-derived value."""
    module = impl(FEATURE_SOURCE)
    reg = registration(module)
    assert _SHA_HEX.fullmatch(reg.implementation_fingerprint)
    assert reg.implementation_fingerprint != str(hash(reg.implementation))
    assert reg.implementation_fingerprint != str(id(reg.implementation))
    assert reg.implementation_fingerprint != repr(reg.implementation)


def test_import_has_no_registration_side_effects():
    import market_vault.dataset as dataset
    before = set(sys.modules)
    exec("from market_vault.dataset import *", {})
    assert set(sys.modules) == before
    assert dataset.TRANSFORM_REGISTRY_CONTRACT_VERSION == "market-vault-transform-registry-v1"
    assert (dataset.TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION
            == "market-vault-transform-implementation-fingerprint-v1")


# ---------------------------------------------------------------------------
# Public API surface.
# ---------------------------------------------------------------------------


def test_public_api_exports():
    import market_vault.dataset as dataset
    for name in (
        "TRANSFORM_REGISTRY_CONTRACT_VERSION",
        "TRANSFORM_IMPLEMENTATION_FINGERPRINT_VERSION",
        "TransformRegistryError",
        "TransformParameterContract",
        "TransformWindowRequirement",
        "TransformRegistration",
        "ResolvedTransform",
        "TransformRegistry",
        "transform_implementation_fingerprint",
        "transform_implementation_pin",
        "WINDOW_SOURCE_NONE",
        "WINDOW_SOURCE_FIXED",
        "WINDOW_SOURCE_PARAMETER",
        "WINDOW_SOURCE_LABEL_OBSERVATION_WINDOW",
        "WINDOW_SOURCE_LABEL_HORIZON",
        "WINDOW_UNIT_NONE",
        "WINDOW_UNIT_BARS",
        "WINDOW_UNIT_MINUTES",
        "WINDOW_BOUNDARY_INCLUSIVE",
        "WINDOW_BOUNDARY_EXCLUSIVE",
        "BOUNDARY_POLICY_PIT_WINDOW_ONLY",
        "BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE",
        "BOUNDARY_POLICY_NO_CROSS_TRADING_DAY",
        "MISSING_POLICY_FAIL",
        "MISSING_POLICY_EXCLUDE_SAMPLE",
        "MISSING_POLICY_LABEL_INCOMPLETE",
        "PARAMETER_TYPE_BOOL",
        "PARAMETER_TYPE_INT64",
        "PARAMETER_TYPE_FLOAT64",
        "PARAMETER_TYPE_STRING",
    ):
        assert name in dataset.__all__, name
        assert hasattr(dataset, name), name
    namespace = {}
    exec("from market_vault.dataset import *", namespace)
    for name in dataset.__all__:
        assert name in namespace, name
