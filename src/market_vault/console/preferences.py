from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping


UI_PREFERENCES_SCHEMA = "market-vault-ui-preferences-v1"
SUPPORTED_LOCALES = ("en", "zh-CN", "ja")
DEFAULT_LOCALE = "en"


def resolve_ui_preferences_path(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve the user-owned preference file without touching the filesystem."""

    if root is not None:
        return Path(root).expanduser().resolve() / "ui-preferences.json"

    env = os.environ if environ is None else environ
    current_platform = sys.platform if platform is None else platform
    user_home = Path.home() if home is None else Path(home)
    if current_platform == "win32":
        local_app_data = env.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return base / "MarketVault" / "ui-preferences.json"

    xdg_config_home = env.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg_config_home) if xdg_config_home else user_home / ".config"
    return base / "market-vault" / "ui-preferences.json"


class UiPreferenceStore:
    def __init__(self, path: Path | None = None, **resolver_kwargs):
        self.path = Path(path) if path is not None else resolve_ui_preferences_path(**resolver_kwargs)

    def load_language(self) -> str:
        try:
            text = self.path.read_text(encoding="utf-8")
            if not text.strip():
                return DEFAULT_LOCALE
            payload = json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return DEFAULT_LOCALE
        if not isinstance(payload, dict):
            return DEFAULT_LOCALE
        if payload.get("schema") != UI_PREFERENCES_SCHEMA:
            return DEFAULT_LOCALE
        language = payload.get("language")
        return language if language in SUPPORTED_LOCALES else DEFAULT_LOCALE

    def save_language(self, language: str) -> bool:
        if language not in SUPPORTED_LOCALES:
            return False
        payload = {
            "schema": UI_PREFERENCES_SCHEMA,
            "language": language,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except (OSError, UnicodeError):
            return False
        return True
