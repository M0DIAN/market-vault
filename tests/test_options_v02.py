from datetime import date, timedelta
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from market_vault.cli import build_parser
from market_vault.collectors.moomoo_options import MoomooOptionCollector, select_option_volatility_period
from market_vault.doctor import run_doctor
from market_vault.models import Settings
from market_vault.normalization.options import normalize_option_contracts, normalize_option_volatility
from market_vault.quality.checks import (
    run_option_contract_quality_checks,
    run_option_volatility_quality_checks,
)
from market_vault.service import collect_option_chain, collect_option_volatility, option_chain_date_chunks
from market_vault.storage import Catalog, ParquetStore


def settings(tmp_path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        request_pause_seconds=0,
    )


def option_chain_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["US.MU260807C120000", "US.MU260807P100000", "US.MU260807C120000"],
            "name": ["MU CALL", "MU PUT", "MU CALL duplicate"],
            "owner_stock_code": ["US.MU", "US.MU", "US.MU"],
            "option_type": ["CALL", "PUT", "CALL"],
            "strike_price": ["120.0", "100.0", "120.0"],
            "strike_time": ["2026-08-07", "2026-08-07", "2026-08-07"],
            "lot_size": ["1", "1", "1"],
        }
    )


def test_option_chain_normalizes_fields_and_deduplicates():
    captured_at = pd.Timestamp("2026-08-02T01:00:00Z")
    out = normalize_option_contracts(option_chain_frame(), "US.MU", captured_at, "moomoo", "10.9", "run-1")

    assert len(out) == 2
    assert out["option_code"].tolist() == ["US.MU260807C120000", "US.MU260807P100000"]
    assert out.loc[0, "underlying_code"] == "US.MU"
    assert out.loc[0, "strike_price"] == 120.0
    assert out.loc[0, "expiry_date"] == date(2026, 8, 7)


def test_option_type_can_be_mapped_from_contract_code():
    raw = option_chain_frame().drop(columns=["option_type"])
    out = normalize_option_contracts(raw, "US.MU", pd.Timestamp("2026-08-02T01:00:00Z"), "moomoo", "10.9", "run-1")

    assert out.set_index("option_code").loc["US.MU260807C120000", "option_type"] == "CALL"
    assert out.set_index("option_code").loc["US.MU260807P100000", "option_type"] == "PUT"


def test_option_contract_quality_warns_on_underlying_mismatch():
    out = normalize_option_contracts(option_chain_frame(), "US.MU", pd.Timestamp("2026-08-02T01:00:00Z"), "moomoo", "10.9", "run-1")
    out.loc[0, "underlying_code"] = "US.SPY"

    checks = {item.check_name: item for item in run_option_contract_quality_checks(out)}

    assert checks["option_code_non_empty"].result == "PASS"
    assert checks["option_underlying_relationship"].result == "WARN"


def test_option_volatility_normalizes_and_filters_range():
    raw = pd.DataFrame(
        {
            "timestamp_str": ["2026-07-01", "2026-07-15", "2026-08-01"],
            "implied_volatility": ["25.0", "26.5", "27.0"],
            "history_volatility": [20.0, 21.0, 22.0],
            "volatility_premium": [5.0, 5.5, 5.0],
            "average_impvol": [25.8, 25.8, 25.8],
            "impvol_status": ["NORMAL", "NORMAL", "NORMAL"],
        }
    )
    out = normalize_option_volatility(raw, "US.MU260807C120000", date(2026, 7, 1), date(2026, 7, 31), "moomoo", "run-1")

    assert out["trade_date"].tolist() == [date(2026, 7, 1), date(2026, 7, 15)]
    assert out.loc[0, "historical_volatility"] == 20.0
    assert out.loc[0, "average_implied_volatility"] == 25.8


def test_option_volatility_quality_fails_on_negative_values():
    df = pd.DataFrame(
        {
            "option_code": ["US.MU260807C120000"],
            "trade_date": [date(2026, 7, 1)],
            "implied_volatility": [-1.0],
            "historical_volatility": [None],
            "volatility_premium": [None],
            "average_implied_volatility": [None],
            "volatility_status": ["LOW"],
            "source": ["moomoo"],
            "ingestion_run_id": ["run-1"],
        }
    )

    checks = {item.check_name: item for item in run_option_volatility_quality_checks(df, date(2026, 7, 1), date(2026, 7, 31))}

    assert checks["non_negative_volatility"].result == "FAIL"


def test_cli_parses_option_commands():
    parser = build_parser()

    chain = parser.parse_args(
        [
            "option-chain",
            "--underlying",
            "US.MU",
            "--start-date",
            "2026-08-07",
            "--end-date",
            "2026-09-18",
            "--option-type",
            "ALL",
        ]
    )
    vol = parser.parse_args(
        [
            "option-volatility",
            "--codes",
            "US.MU260807C120000",
            "US.MU260807P100000",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-31",
        ]
    )

    assert chain.command == "option-chain"
    assert chain.underlying == "US.MU"
    assert vol.codes == ["US.MU260807C120000", "US.MU260807P100000"]


def test_cli_rejects_atm_option_condition():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "option-chain",
                "--underlying",
                "US.MU",
                "--start-date",
                "2026-08-07",
                "--end-date",
                "2026-09-18",
                "--option-cond-type",
                "ATM",
            ]
        )


class FakeOptionContext:
    def __init__(self):
        self.chain_calls = []
        self.vol_calls = []

    def get_option_chain(self, **kwargs):
        self.chain_calls.append(kwargs)
        return 0, option_chain_frame()

    def get_option_volatility(self, code, query_time_period, hv_time_period):
        self.vol_calls.append(
            {
                "code": code,
                "query_time_period": query_time_period,
                "hv_time_period": hv_time_period,
            }
        )
        return 0, pd.DataFrame({"timestamp_str": ["2026-07-01"], "implied_volatility": [25.0]})

    def close(self):
        pass


def test_option_collector_calls_chain_and_batches_volatility(tmp_path):
    ctx = FakeOptionContext()
    collector = MoomooOptionCollector(settings(tmp_path))
    collector._ctx = ctx
    collector._sdk = {
        "OptionType": SimpleNamespace(ALL="ALL", CALL="CALL", PUT="PUT"),
        "OptionCondType": SimpleNamespace(ALL="ALL", WITHIN="WITHIN", OUTSIDE="OUTSIDE"),
        "IndexOptionType": SimpleNamespace(NORMAL="NORMAL"),
        "OptionVolatilityTimePeriodType": SimpleNamespace(
            WEEK="WEEK",
            MONTH="MONTH",
            QUARTER="QUARTER",
            HALF_YEAR="HALF_YEAR",
            YEAR="YEAR",
        ),
        "RET_OK": 0,
    }

    chain = collector.fetch_option_chain("US.MU", date(2026, 8, 7), date(2026, 9, 18), "CALL", "ITM")
    vol_1 = collector.fetch_option_volatility("US.MU260807C120000", "MONTH")
    vol_2 = collector.fetch_option_volatility("US.MU260807P100000", "MONTH")

    assert len(chain) == 3
    assert ctx.chain_calls[0]["option_type"] == "CALL"
    assert ctx.chain_calls[0]["option_cond_type"] == "WITHIN"
    assert len(ctx.vol_calls) == 2
    assert ctx.vol_calls[0]["query_time_period"] == "MONTH"
    assert not vol_1.empty and not vol_2.empty


def test_option_condition_strictly_maps_otm_to_outside(tmp_path):
    ctx = FakeOptionContext()
    collector = MoomooOptionCollector(settings(tmp_path))
    collector._ctx = ctx
    collector._sdk = {
        "OptionType": SimpleNamespace(ALL="ALL", CALL="CALL", PUT="PUT"),
        "OptionCondType": SimpleNamespace(ALL="ALL", WITHIN="WITHIN", OUTSIDE="OUTSIDE"),
        "IndexOptionType": SimpleNamespace(NORMAL="NORMAL"),
        "OptionVolatilityTimePeriodType": SimpleNamespace(WEEK="WEEK"),
        "RET_OK": 0,
    }

    collector.fetch_option_chain("US.MU", date(2026, 8, 7), date(2026, 9, 18), "ALL", "OTM")

    assert ctx.chain_calls[0]["option_cond_type"] == "OUTSIDE"


def test_option_condition_missing_sdk_enum_does_not_fallback_to_all(tmp_path):
    collector = MoomooOptionCollector(settings(tmp_path))
    collector._ctx = FakeOptionContext()
    collector._sdk = {
        "OptionType": SimpleNamespace(ALL="ALL", CALL="CALL", PUT="PUT"),
        "OptionCondType": SimpleNamespace(ALL="ALL", OUTSIDE="OUTSIDE"),
        "IndexOptionType": SimpleNamespace(NORMAL="NORMAL"),
        "OptionVolatilityTimePeriodType": SimpleNamespace(WEEK="WEEK"),
        "RET_OK": 0,
    }

    with pytest.raises(ValueError, match="WITHIN"):
        collector.fetch_option_chain("US.MU", date(2026, 8, 7), date(2026, 9, 18), "ALL", "ITM")


@pytest.mark.parametrize(
    ("start_date", "expected"),
    [
        (date(2026, 7, 25), "WEEK"),
        (date(2026, 7, 2), "MONTH"),
        (date(2026, 5, 2), "QUARTER"),
        (date(2026, 2, 1), "HALF_YEAR"),
        (date(2025, 8, 2), "YEAR"),
    ],
)
def test_option_volatility_period_selection(start_date, expected):
    assert select_option_volatility_period(start_date, date(2026, 8, 1)) == expected


def test_option_volatility_rejects_more_than_one_year():
    with pytest.raises(ValueError, match="YEAR"):
        select_option_volatility_period(date(2025, 7, 30), date(2026, 8, 1))


class ServiceFakeCollector:
    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def fetch_option_volatility(self, option_code, query_time_period, hv_time_period=30):
        return pd.DataFrame(
            {
                "timestamp_str": ["2026-07-10", "2026-07-15", "2026-08-01"],
                "implied_volatility": [25.0, 26.0, 27.0],
                "history_volatility": [20.0, 21.0, 22.0],
            }
        )


def test_option_volatility_manifest_marks_incomplete_range(monkeypatch, tmp_path):
    import market_vault.service as service

    monkeypatch.setattr(service, "MoomooOptionCollector", ServiceFakeCollector)

    manifest = collect_option_volatility(
        settings(tmp_path),
        ["US.MU260807C120000"],
        date(2026, 7, 1),
        date(2026, 7, 31),
        as_of_date=date(2026, 7, 31),
    )

    assert manifest.parameters["query_time_period"] == "MONTH"
    assert manifest.parameters["returned_min_date"] == "2026-07-10"
    assert manifest.parameters["returned_max_date"] == "2026-08-01"
    assert manifest.parameters["range_complete"] is False
    assert manifest.status == "PARTIAL"
    assert manifest.row_count == 2


def test_option_volatility_filter_keeps_only_requested_range():
    raw = pd.DataFrame(
        {
            "timestamp_str": ["2026-06-30", "2026-07-01", "2026-07-31", "2026-08-01"],
            "implied_volatility": [24.0, 25.0, 26.0, 27.0],
        }
    )

    out = normalize_option_volatility(
        raw,
        "US.MU260807C120000",
        date(2026, 7, 1),
        date(2026, 7, 31),
        "moomoo",
        "run-1",
    )

    assert out["trade_date"].tolist() == [date(2026, 7, 1), date(2026, 7, 31)]


def test_doctor_reports_missing_option_volatility_as_unsupported(tmp_path):
    class FakeQuoteContext:
        def __init__(self, host=None, port=None):
            pass

        def get_option_chain(self):
            pass

        def close(self):
            pass

    fake_sdk = {
        "module_name": "moomoo",
        "version": "10.9.fake",
        "OpenQuoteContext": FakeQuoteContext,
    }

    report = run_doctor(settings(tmp_path), sdk_info=fake_sdk)

    assert report["moomoo_sdk_importable"] is True
    assert report["moomoo_sdk_module"] == "moomoo"
    assert report["moomoo_sdk_version"] == "10.9.fake"
    assert report["get_option_chain"] == "supported"
    assert report["get_option_volatility"] == "unsupported"


def test_option_paths_and_duckdb_latest_view(tmp_path):
    cfg = settings(tmp_path)
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    captured_at = pd.Timestamp("2026-08-02T01:00:00Z")
    curated = normalize_option_contracts(option_chain_frame(), "US.MU", captured_at, "moomoo", "10.9", "run-1")
    raw_path = store.write_option_chain_raw(option_chain_frame(), "US.MU", date(2026, 8, 2), "run-1")
    curated_path = store.write_option_contracts_curated(curated, "US.MU", date(2026, 8, 2), "run-1")

    assert "raw/source=moomoo/dataset=option_chain" in raw_path.as_posix()
    assert "curated/option_contracts/underlying_code=US.MU/capture_date=2026-08-02" in curated_path.as_posix()
    assert catalog.refresh_option_contract_views()

    with duckdb.connect(str(cfg.catalog_path)) as con:
        latest_count = con.execute("SELECT count(*) FROM option_contracts_latest").fetchone()[0]

    assert latest_count == 2


def test_option_chain_chunks_for_one_day_and_thirty_days():
    assert option_chain_date_chunks(date(2026, 8, 7), date(2026, 8, 7)) == [
        (date(2026, 8, 7), date(2026, 8, 7))
    ]
    assert option_chain_date_chunks(date(2026, 8, 7), date(2026, 9, 5)) == [
        (date(2026, 8, 7), date(2026, 9, 5))
    ]


def test_option_chain_chunks_for_thirty_one_days():
    assert option_chain_date_chunks(date(2026, 8, 7), date(2026, 9, 6)) == [
        (date(2026, 8, 7), date(2026, 9, 5)),
        (date(2026, 9, 6), date(2026, 9, 6)),
    ]


def test_option_chain_chunks_for_real_expiration_range():
    assert option_chain_date_chunks(date(2026, 8, 7), date(2026, 9, 18)) == [
        (date(2026, 8, 7), date(2026, 9, 5)),
        (date(2026, 9, 6), date(2026, 9, 18)),
    ]


def test_option_chain_chunks_have_no_overlap_or_gap():
    chunks = option_chain_date_chunks(date(2026, 8, 7), date(2026, 10, 10))

    assert chunks[0][0] == date(2026, 8, 7)
    assert chunks[-1][1] == date(2026, 10, 10)
    for left, right in zip(chunks, chunks[1:]):
        assert right[0] == left[1] + timedelta(days=1)


class ServiceFakeOptionChainCollector:
    responses = {}
    failures = set()
    instances = []

    def __init__(self, settings):
        self.settings = settings
        self.calls = []
        ServiceFakeOptionChainCollector.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def fetch_option_chain(self, underlying, start_date, end_date, option_type="ALL", option_cond_type="ALL"):
        self.calls.append(
            {
                "underlying": underlying,
                "start_date": start_date,
                "end_date": end_date,
                "option_type": option_type,
                "option_cond_type": option_cond_type,
            }
        )
        key = (start_date, end_date)
        if key in self.failures:
            raise RuntimeError(f"chunk failed: {start_date} to {end_date}")
        return self.responses.get(key, option_chain_frame())


def reset_fake_option_chain_collector():
    ServiceFakeOptionChainCollector.responses = {}
    ServiceFakeOptionChainCollector.failures = set()
    ServiceFakeOptionChainCollector.instances = []


def chunk_frame(code: str, name: str = "MU CALL") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": [code],
            "name": [name],
            "owner_stock_code": ["US.MU"],
            "option_type": ["CALL" if "C" in code[-7:] else "PUT"],
            "strike_price": ["120.0"],
            "strike_time": ["2026-08-07"],
        }
    )


def test_option_chain_service_merges_multichunk_results_and_deduplicates(monkeypatch, tmp_path):
    import market_vault.service as service

    reset_fake_option_chain_collector()
    first = (date(2026, 8, 7), date(2026, 9, 5))
    second = (date(2026, 9, 6), date(2026, 9, 18))
    ServiceFakeOptionChainCollector.responses = {
        first: chunk_frame("US.MU260807C120000"),
        second: chunk_frame("US.MU260807C120000", "duplicate"),
    }
    monkeypatch.setattr(service, "MoomooOptionCollector", ServiceFakeOptionChainCollector)

    manifest = collect_option_chain(
        settings(tmp_path),
        "US.MU",
        date(2026, 8, 7),
        date(2026, 9, 18),
        option_type="CALL",
        option_cond_type="ITM",
    )

    assert manifest.status == "SUCCESS"
    assert manifest.row_count == 1
    assert manifest.parameters["chunk_count"] == 2
    assert manifest.parameters["returned_contract_count"] == 1
    assert len(manifest.parameters["successful_chunks"]) == 2
    assert len(manifest.parameters["failed_chunks"]) == 0
    assert len(ServiceFakeOptionChainCollector.instances[0].calls) == 2
    assert ServiceFakeOptionChainCollector.instances[0].calls[0]["option_type"] == "CALL"


def test_option_chain_partial_chunk_failure_saves_successes(monkeypatch, tmp_path):
    import market_vault.service as service

    reset_fake_option_chain_collector()
    first = (date(2026, 8, 7), date(2026, 9, 5))
    second = (date(2026, 9, 6), date(2026, 9, 18))
    ServiceFakeOptionChainCollector.responses = {first: chunk_frame("US.MU260807C120000")}
    ServiceFakeOptionChainCollector.failures = {second}
    monkeypatch.setattr(service, "MoomooOptionCollector", ServiceFakeOptionChainCollector)

    manifest = collect_option_chain(settings(tmp_path), "US.MU", date(2026, 8, 7), date(2026, 9, 18))

    assert manifest.status == "PARTIAL"
    assert manifest.row_count == 1
    assert len(manifest.parameters["successful_chunks"]) == 1
    assert manifest.parameters["failed_chunks"] == [
        {
            "start_date": "2026-09-06",
            "end_date": "2026-09-18",
            "error": "chunk failed: 2026-09-06 to 2026-09-18",
        }
    ]


def test_option_chain_all_chunks_failed_marks_failed(monkeypatch, tmp_path):
    import market_vault.service as service

    reset_fake_option_chain_collector()
    ServiceFakeOptionChainCollector.failures = {
        (date(2026, 8, 7), date(2026, 9, 5)),
        (date(2026, 9, 6), date(2026, 9, 18)),
    }
    monkeypatch.setattr(service, "MoomooOptionCollector", ServiceFakeOptionChainCollector)

    manifest = collect_option_chain(settings(tmp_path), "US.MU", date(2026, 8, 7), date(2026, 9, 18))

    assert manifest.status == "FAILED"
    assert manifest.row_count == 0
    assert len(manifest.parameters["successful_chunks"]) == 0
    assert len(manifest.parameters["failed_chunks"]) == 2


def test_option_chain_chunks_share_one_run_id(monkeypatch, tmp_path):
    import market_vault.service as service

    reset_fake_option_chain_collector()
    monkeypatch.setattr(service, "MoomooOptionCollector", ServiceFakeOptionChainCollector)

    manifest = collect_option_chain(settings(tmp_path), "US.MU", date(2026, 8, 7), date(2026, 9, 18))
    raw = pd.read_parquet(manifest.raw_file)

    assert raw["ingestion_run_id"].nunique() == 1
    assert raw["ingestion_run_id"].iloc[0] == manifest.run_id
    assert manifest.parameters["chunk_ranges"] == [
        {"start_date": "2026-08-07", "end_date": "2026-09-05"},
        {"start_date": "2026-09-06", "end_date": "2026-09-18"},
    ]
