from types import SimpleNamespace

import pytest

import market_vault.moomoo_sdk as sdk_loader
from market_vault.collectors.moomoo_history import MoomooHistoryCollector
from market_vault.collectors.moomoo_options import MoomooOptionCollector
from market_vault.moomoo_sdk import MoomooDependencyError, load_moomoo_sdk
from market_vault.models import Settings


class FakeQuoteContext:
    def __init__(self, host=None, port=None):
        self.host = host
        self.port = port

    def close(self):
        pass


def fake_sdk_module(version: str):
    return SimpleNamespace(
        __version__=version,
        OpenQuoteContext=FakeQuoteContext,
        RET_OK=0,
        AuType=SimpleNamespace(NONE="NONE"),
        KLType=SimpleNamespace(K_1M="K_1M"),
        KL_FIELD=SimpleNamespace(ALL="ALL"),
        Session=SimpleNamespace(ALL="ALL"),
        OptionType=SimpleNamespace(ALL="ALL"),
        OptionCondType=SimpleNamespace(ALL="ALL", WITHIN="WITHIN", OUTSIDE="OUTSIDE"),
        OptionVolatilityTimePeriodType=SimpleNamespace(WEEK="WEEK"),
    )


def patch_imports(monkeypatch, modules):
    def fake_import(name):
        if name in modules:
            return modules[name]
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(sdk_loader.importlib, "import_module", fake_import)


def test_loader_prefers_moomoo_module(monkeypatch):
    moomoo = fake_sdk_module("moomoo-version")
    futu = fake_sdk_module("futu-version")
    patch_imports(monkeypatch, {"moomoo": moomoo, "futu": futu})

    loaded = load_moomoo_sdk()

    assert loaded["module"] is moomoo
    assert loaded["module_name"] == "moomoo"
    assert loaded["version"] == "moomoo-version"


def test_loader_falls_back_to_futu(monkeypatch):
    futu = fake_sdk_module("futu-version")
    patch_imports(monkeypatch, {"futu": futu})

    loaded = load_moomoo_sdk()

    assert loaded["module"] is futu
    assert loaded["module_name"] == "futu"
    assert loaded["version"] == "futu-version"


def test_loader_reports_clear_error_when_sdk_missing(monkeypatch):
    patch_imports(monkeypatch, {})

    with pytest.raises(MoomooDependencyError, match="pip install -U moomoo-api"):
        load_moomoo_sdk()


def test_collectors_share_unified_loader(monkeypatch, tmp_path):
    calls = []

    def fake_loader():
        calls.append("load")
        return {
            "module": fake_sdk_module("test"),
            "module_name": "moomoo",
            "version": "test",
            "OpenQuoteContext": FakeQuoteContext,
            "RET_OK": 0,
        }

    import market_vault.collectors.moomoo_history as history_module
    import market_vault.collectors.moomoo_options as options_module

    monkeypatch.setattr(history_module, "load_moomoo_sdk", fake_loader)
    monkeypatch.setattr(options_module, "load_moomoo_sdk", fake_loader)
    settings = Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
    )

    assert MoomooHistoryCollector(settings)._load_sdk()["module_name"] == "moomoo"
    assert MoomooOptionCollector(settings)._load_sdk()["module_name"] == "moomoo"
    assert calls == ["load", "load"]
