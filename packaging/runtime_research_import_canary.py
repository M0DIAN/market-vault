"""Verification-only PyInstaller runtime hook for the Research Builder import chain."""

from __future__ import annotations

import os
from pathlib import Path
import traceback


target = os.environ.get("MARKET_VAULT_RESEARCH_IMPORT_CANARY")
if target:
    path = Path(target)
    try:
        import market_vault
        import market_vault.multi_source
        import market_vault.research_dataset
        from market_vault import multi_source

        payload = "\n".join(
            (
                "RESULT=PASS",
                f"ROOT={market_vault.__file__}",
                f"MULTI_SOURCE={market_vault.multi_source.__file__}",
                f"RESEARCH_DATASET={market_vault.research_dataset.__file__}",
                f"FROM_IMPORT={multi_source.__name__}",
            )
        )
    except BaseException:
        payload = "RESULT=FAIL\n" + traceback.format_exc()
    path.write_text(payload, encoding="utf-8")
