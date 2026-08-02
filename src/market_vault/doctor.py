from __future__ import annotations

import contextlib
import io
import logging
import socket
import sys
import time
from typing import Any

from .moomoo_sdk import load_moomoo_sdk
from .models import Settings


def run_doctor(settings: Settings, sdk_info: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "moomoo_sdk_module": None,
        "moomoo_sdk_importable": False,
        "moomoo_sdk_version": None,
        "opend_host": settings.opend_host,
        "opend_port": settings.opend_port,
        "opend_connectable": False,
        "get_option_chain": "unsupported",
        "get_option_volatility": "unsupported",
    }

    try:
        sdk = sdk_info if sdk_info is not None else load_moomoo_sdk()
        result["moomoo_sdk_importable"] = True
        result["moomoo_sdk_module"] = sdk.get("module_name")
        result["moomoo_sdk_version"] = sdk.get("version")
        ctx = None
        try:
            previous_disable_level = logging.root.manager.disable
            try:
                logging.disable(logging.CRITICAL)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    ctx = sdk["OpenQuoteContext"](host=settings.opend_host, port=settings.opend_port)
            finally:
                logging.disable(previous_disable_level)
            result["get_option_chain"] = "supported" if hasattr(ctx, "get_option_chain") else "unsupported"
            result["get_option_volatility"] = "supported" if hasattr(ctx, "get_option_volatility") else "unsupported"
        finally:
            if ctx is not None:
                try:
                    previous_disable_level = logging.root.manager.disable
                    try:
                        logging.disable(logging.CRITICAL)
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            ctx.close()
                        time.sleep(0.1)
                    finally:
                        logging.disable(previous_disable_level)
                except Exception:
                    pass
    except Exception as exc:
        result["moomoo_sdk_error"] = _short_error(exc)

    try:
        with socket.create_connection((settings.opend_host, settings.opend_port), timeout=2):
            result["opend_connectable"] = True
    except OSError as exc:
        result["opend_error"] = _short_error(exc)

    return result


def _short_error(exc: BaseException) -> str:
    text = str(exc).strip()
    return text if text else exc.__class__.__name__
