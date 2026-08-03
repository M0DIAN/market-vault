from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_json_report_atomic(report_path: Path, payload: dict) -> None:
    """Write a JSON report via a temp file + replace() to avoid half-written files."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=report_path.parent, prefix=f"{report_path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, report_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
