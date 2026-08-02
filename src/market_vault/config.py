from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Settings


def _resolve(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (project_root / path).resolve()


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Settings file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    project_root = config_path.parent.parent
    opend = raw.get("opend", {})
    storage = raw.get("storage", {})
    collector = raw.get("collector", {})

    return Settings(
        project_root=project_root,
        opend_host=str(opend.get("host", "127.0.0.1")),
        opend_port=int(opend.get("port", 11111)),
        data_root=_resolve(project_root, storage.get("root_dir", "./data")),
        catalog_path=_resolve(project_root, storage.get("catalog_path", "./catalog/market_vault.duckdb")),
        manifest_dir=_resolve(project_root, storage.get("manifest_dir", "./manifests")),
        report_dir=_resolve(project_root, storage.get("report_dir", "./reports/data_quality")),
        max_count=int(collector.get("max_count", 1000)),
        source=str(collector.get("source", "moomoo")),
        source_schema_version=str(collector.get("source_schema_version", "10.9")),
        default_session=str(collector.get("default_session", "ALL")),
        default_adjustment=str(collector.get("default_adjustment", "NONE")),
        request_pause_seconds=float(collector.get("request_pause_seconds", 0.35)),
    )


def load_universe(path: str | Path) -> dict[str, list[str]]:
    universe_path = Path(path).resolve()
    with universe_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {key: [str(item) for item in (value or [])] for key, value in raw.items()}
