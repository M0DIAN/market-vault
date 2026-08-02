from __future__ import annotations

import importlib
import socket
import sys
from types import ModuleType
from typing import Any

from .models import Settings


def run_doctor(settings: Settings, sdk_module: ModuleType | Any | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "moomoo_sdk_module": "futu",
        "moomoo_sdk_importable": False,
        "moomoo_sdk_version": None,
        "opend_host": settings.opend_host,
        "opend_port": settings.opend_port,
        "opend_connectable": False,
        "get_option_chain": "unsupported",
        "get_option_volatility": "unsupported",
    }

    try:
        sdk = sdk_module if sdk_module is not None else importlib.import_module("futu")
        result["moomoo_sdk_importable"] = True
        result["moomoo_sdk_version"] = _sdk_version(sdk)
        context = getattr(sdk, "OpenQuoteContext", None)
        if context is not None:
            result["get_option_chain"] = "supported" if hasattr(context, "get_option_chain") else "unsupported"
            result["get_option_volatility"] = (
                "supported" if hasattr(context, "get_option_volatility") else "unsupported"
            )
    except Exception as exc:
        result["moomoo_sdk_error"] = _short_error(exc)

    try:
        with socket.create_connection((settings.opend_host, settings.opend_port), timeout=2):
            result["opend_connectable"] = True
    except OSError as exc:
        result["opend_error"] = _short_error(exc)

    return result


def _sdk_version(sdk: Any) -> str | None:
    for name in ["__version__", "VERSION", "version"]:
        value = getattr(sdk, name, None)
        if value is not None:
            return str(value)
    return None


def _short_error(exc: BaseException) -> str:
    text = str(exc).strip()
    return text if text else exc.__class__.__name__
