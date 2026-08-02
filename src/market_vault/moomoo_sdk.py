from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


class MoomooDependencyError(RuntimeError):
    pass


INSTALL_HINT = "Install or repair the moomoo Python SDK with: pip install -U moomoo-api"


def load_moomoo_sdk() -> dict[str, Any]:
    module, module_name = _import_sdk_module()
    return {
        "module": module,
        "module_name": module_name,
        "version": sdk_version(module),
        "OpenQuoteContext": _required_attr(module, "OpenQuoteContext"),
        "RET_OK": _required_attr(module, "RET_OK"),
        "AuType": getattr(module, "AuType", None),
        "KLType": getattr(module, "KLType", None),
        "KL_FIELD": getattr(module, "KL_FIELD", None),
        "Session": getattr(module, "Session", None),
        "IndexOptionType": getattr(module, "IndexOptionType", None),
        "OptionCondType": getattr(module, "OptionCondType", None),
        "OptionType": getattr(module, "OptionType", None),
        "OptionVolatilityTimePeriodType": getattr(module, "OptionVolatilityTimePeriodType", None),
    }


def _import_sdk_module() -> tuple[ModuleType, str]:
    errors: list[str] = []
    for module_name in ["moomoo", "futu"]:
        try:
            return importlib.import_module(module_name), module_name
        except ImportError as exc:
            errors.append(f"{module_name}: {exc}")
    raise MoomooDependencyError(f"{INSTALL_HINT}. Tried modules: {'; '.join(errors)}")


def sdk_version(module: Any) -> str | None:
    for name in ["__version__", "VERSION", "version"]:
        value = getattr(module, name, None)
        if value is not None:
            return str(value)
    return None


def _required_attr(module: Any, name: str) -> Any:
    value = getattr(module, name, None)
    if value is None:
        raise MoomooDependencyError(f"moomoo SDK is missing required attribute {name}. {INSTALL_HINT}")
    return value
