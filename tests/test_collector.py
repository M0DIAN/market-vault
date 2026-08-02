from datetime import date
from types import SimpleNamespace

import pandas as pd

from market_vault.collectors.moomoo_history import MoomooHistoryCollector
from market_vault.models import Settings


class FakeContext:
    def __init__(self):
        self.calls = []

    def request_history_kline(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["page_req_key"] is None:
            return 0, pd.DataFrame({"code": ["US.MU"], "close": [100.0]}), b"next"
        return 0, pd.DataFrame({"code": ["US.MU"], "close": [101.0]}), None

    def close(self):
        pass


def test_fetch_history_pages_until_key_is_none(tmp_path):
    settings = Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        request_pause_seconds=0,
    )
    collector = MoomooHistoryCollector(settings)
    collector._ctx = FakeContext()
    collector._sdk = {
        "AuType": SimpleNamespace(NONE="NONE", QFQ="QFQ", HFQ="HFQ"),
        "KLType": SimpleNamespace(K_1M="K_1M", K_DAY="K_DAY"),
        "KL_FIELD": SimpleNamespace(ALL="ALL"),
        "RET_OK": 0,
        "Session": SimpleNamespace(ALL="ALL", RTH="RTH"),
    }

    frame = collector.fetch_history("US.MU", date(2026, 7, 31), "1m", "NONE", "ALL")

    assert frame["close"].tolist() == [100.0, 101.0]
    assert len(collector._ctx.calls) == 2
    assert collector._ctx.calls[0]["session"] == "ALL"
