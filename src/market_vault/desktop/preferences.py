"""User-owned preferences for the parallel QML desktop."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


DESKTOP_PREFERENCE_SCHEMA = "market-vault-desktop-preferences-v1"
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("zh-CN", "en")
PREFERENCE_FILENAME = "desktop-preferences.json"


def default_desktop_preference_path() -> Path:
    """Resolve the desktop preference file independently of the current directory."""

    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
        return base / "MarketVault" / PREFERENCE_FILENAME

    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root) if root else Path.home() / ".config"
    return base / "market-vault" / PREFERENCE_FILENAME


class DesktopPreferenceStore:
    """Read and write the isolated bilingual QML preference contract."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        path: Path | None = None,
    ) -> None:
        if root is not None and path is not None:
            raise ValueError("Specify either preference root or path, not both.")
        if path is not None:
            self._path = Path(path)
        elif root is not None:
            self._path = Path(root) / PREFERENCE_FILENAME
        else:
            self._path = default_desktop_preference_path()

    @property
    def path(self) -> Path:
        return self._path

    def load_language(self) -> str:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return DEFAULT_LANGUAGE
        if not isinstance(payload, dict):
            return DEFAULT_LANGUAGE
        if payload.get("schema") != DESKTOP_PREFERENCE_SCHEMA:
            return DEFAULT_LANGUAGE
        language = payload.get("language")
        if language not in SUPPORTED_LANGUAGES:
            return DEFAULT_LANGUAGE
        return str(language)

    def save_language(self, language: str) -> bool:
        if language not in SUPPORTED_LANGUAGES:
            return False
        payload = {
            "schema": DESKTOP_PREFERENCE_SCHEMA,
            "language": language,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            return False
        return True
