"""Common execution semantics and offline Dataset -> CLI/UI integration.

The workspace fixture uses real Catalog/Parquet/Canonical and Research logic;
only Research artifact publication I/O uses the existing MemoryFS model.
It is not evidence of native Research publication capability.
"""

from datetime import date, timedelta
import json
import math

import pytest

from market_vault.backtest import BacktestRule
from market_vault.backtest.engine import _Candidate
from market_vault.research import strategy_comparison as comparison
from market_vault.research.strategy_comparison import (
    FeatureRuleStrategy, RidgeStrategy, StrategyComparisonError, compare_strategies,
)
from market_vault import cli, strategy_comparison_cli
from test_ridge_final_trading import FEATURES, LABEL, _execution_bundle, _time


def _strategies(feature="f1"):
    return (
        FeatureRuleStrategy("trend", BacktestRule(feature, "GT", 0)),
        FeatureRuleStrategy("reversion", BacktestRule(feature, "LT", 100)),
        RidgeStrategy("ridge", alpha=1, threshold=-100),
    )


def _config(**overrides):
    return {
        "feature_fields": FEATURES,
        "return_label": LABEL,
        "strategies": _strategies(),
        "minimum_train_periods": 3,
        "validation_periods": 2,
        "step_periods": 2,
        "commission_bps": 10,
        "slippage_bps": 5,
        **overrides,
    }


def _bind_bundle(monkeypatch, bundle, *, late_entry_period=None):
    # Only the artifact boundary is replaced here. Folds, training, prediction,
    # chronological joining and the financial kernel all run normally.
    monkeypatch.setattr(comparison, "build_experiment_dataset", lambda *a, **k: bundle)
    monkeypatch.setattr(comparison, "validate_execution_safe_experiment", lambda d, b: (d, b))

    def candidates(dataset, rule, label, split):
        assert split in ("TRAIN", "VALIDATION")  # TEST must never supply trades.
        source = bundle.train if split == "TRAIN" else bundle.validation
        return tuple(_Candidate(
            m.sample_key, m.code, m.feature_window_close,
            m.feature_window_close + timedelta(
                hours=3 if m.feature_window_close == late_entry_period else 0.5
            ),
            m.actual_label_end_time, X[0], y,
        ) for m, X, y in zip(source.metadata, source.X, source.y, strict=True))

    monkeypatch.setattr(comparison, "_candidates", candidates)


def test_common_samples_include_original_train_and_respect_validation_gaps(monkeypatch):
    bundle = _execution_bundle()
    _bind_bundle(monkeypatch, bundle)
    result = compare_strategies(object(), **_config(
        minimum_train_periods=2, validation_periods=1, step_periods=3,
    ))
    expected = (bundle.train.metadata[2].sample_key, bundle.validation.metadata[1].sample_key)
    assert result.validation_sample_keys == expected
    assert result.evaluation_scope == "WALK_FORWARD_VALIDATION"
    assert result.plan.held_out_test_count == 2
    assert all(item.metrics.candidate_count == 2 for item in result.results)
    assert all(tuple(t.sample_key for t in item.trades) == expected for item in result.results)
    assert not set(expected).intersection(m.sample_key for m in bundle.test.metadata)


def test_one_account_across_folds_uses_proven_entry_and_identical_costs(monkeypatch):
    bundle = _execution_bundle(crossing_ends={
        (4, "US.AAPL"): _time(6) + timedelta(hours=2),
        (6, "US.AAPL"): _time(6) + timedelta(hours=4),
    })
    _bind_bundle(monkeypatch, bundle, late_entry_period=_time(6))
    result = compare_strategies(object(), **_config())
    assert len(result.plan.folds) == 2
    assert [m.feature_window_close for f in result.plan.folds for m in f.validation.metadata] == [
        _time(3), _time(4), _time(5), _time(6),
    ]
    for strategy in result.results:
        assert [t.signal_time for t in strategy.trades] == [_time(3), _time(4), _time(6)]
        assert strategy.metrics.signal_count == 4
        assert strategy.metrics.overlap_skipped_count == 1
        # Signal 6 precedes exit 4, but its actual entry is later and is valid.
        assert strategy.trades[2].signal_time < strategy.trades[1].exit_time
        assert strategy.trades[2].entry_time > strategy.trades[1].exit_time
        assert strategy.metrics.total_return == pytest.approx(4 * 5 * 7 * 0.9985 ** 6 - 1)
        assert strategy.metrics.gross_total_return == pytest.approx(4 * 5 * 7 - 1)
        assert strategy.trades[2].equity_before == strategy.trades[1].equity_after
    assert len({item.result_id for item in result.results}) == 3


def test_test_targets_do_not_change_development_predictions_or_metrics(monkeypatch):
    _bind_bundle(monkeypatch, _execution_bundle())
    first = compare_strategies(object(), **_config())
    _bind_bundle(monkeypatch, _execution_bundle(test_y_shift=10_000))
    second = compare_strategies(object(), **_config())
    # This synthetic bundle holds dataset_id fixed to isolate TEST use. A real
    # changed artifact can legitimately change its upstream dataset identity.
    assert first == second
    changed_cost = compare_strategies(object(), **_config(commission_bps=20))
    assert changed_cost.comparison_id != first.comparison_id
    assert changed_cost.results[0].metrics.total_return < first.results[0].metrics.total_return


def test_missing_execution_sample_and_non_feature_rule_fail_closed(monkeypatch):
    bundle = _execution_bundle()
    _bind_bundle(monkeypatch, bundle)
    with pytest.raises(StrategyComparisonError, match="common Feature projection"):
        compare_strategies(object(), **_config(strategies=(
            FeatureRuleStrategy("label", BacktestRule(LABEL, "GT", 0)),
        )))
    original = comparison._candidates
    monkeypatch.setattr(comparison, "_candidates", lambda *args: original(*args)[:-1])
    with pytest.raises(StrategyComparisonError, match="missing validation execution evidence"):
        compare_strategies(object(), **_config())


@pytest.fixture(scope="module")
def verified_workspace_dataset(tmp_path_factory):
    from market_vault.api import MarketVault
    from market_vault import research_workspace as workspace
    from market_vault.cross_day_dataset import load_verified_multi_source_cross_day_dataset
    from cross_day_artifact_memory_fs import MemoryFS
    from test_research_workspace import _days, _settings, _write_real_calendar, _write_real_ts2_day

    path = tmp_path_factory.mktemp("strategy-comparison")
    days = _days() + [date(2026, 1, day) for day in (20, 21, 22, 23, 26, 27)]
    base = _settings(path)
    cfg = workspace.research_ready_settings(base)
    _write_real_calendar(base, days)
    for index, day in enumerate(days):
        _write_real_ts2_day(cfg, day, ordinal=index)
    with pytest.MonkeyPatch.context() as patches:
        MemoryFS(patches, cfg.data_root / "research" / "cross_day")
        built = workspace.build_local_research_dataset(
            MarketVault(base), symbol="US.SPY", start_date=days[0], end_date=days[-1],
            interval="5m", preset="LIGHT_TECHNICAL", horizon_trading_days=1,
        )
        assert built.canonical_build_path.is_dir()
        yield load_verified_multi_source_cross_day_dataset(built.dataset_build_path)


def _real_config():
    return _config(
        feature_fields=("return_2",), return_label="execution_return_1d",
        strategies=(
            FeatureRuleStrategy("trend", BacktestRule("return_2", "GT", 0)),
            FeatureRuleStrategy("reversion", BacktestRule("return_2", "LT", 0)),
            RidgeStrategy("ridge", 1, 0),
        ),
    )


def _plan(dataset_dir):
    config = _real_config()
    return {
        "plan_schema_version": strategy_comparison_cli.STRATEGY_COMPARISON_PLAN_VERSION,
        "dataset_build_dir": str(dataset_dir),
        **config,
        "strategies": [
            {"kind": "FEATURE_RULE", "name": "trend", "signal_field": "return_2", "comparator": "GT", "threshold": 0},
            {"kind": "FEATURE_RULE", "name": "reversion", "signal_field": "return_2", "comparator": "LT", "threshold": 0},
            {"kind": "RIDGE", "name": "ridge", "alpha": 1, "threshold": 0},
        ],
    }


def test_verified_dataset_and_settings_independent_cli(verified_workspace_dataset, tmp_path, monkeypatch, capsys):
    dataset = verified_workspace_dataset
    report = compare_strategies(dataset, **_real_config())
    assert len(report.plan.folds) >= 2
    assert report.plan.held_out_test_count > 0
    assert report.results[0].metrics.trade_count > 0
    assert report.results[1].metrics.trade_count == 0
    assert report.results[2].metrics.trade_count > 0
    assert all(r.metrics.candidate_count == len(report.validation_sample_keys) for r in report.results)
    expected = math.prod(
        (1 + t.gross_return) * 0.9985 ** 2 for t in report.results[0].trades
    ) - 1
    assert report.results[0].metrics.total_return == pytest.approx(expected)
    plan = tmp_path / "comparison.json"
    plan.write_text(json.dumps(_plan(dataset.build_path)), encoding="utf-8")
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("offline comparison loaded settings"))
    assert cli.main(["research-compare-strategies", "--plan", str(plan)]) == 0
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert output.err == ""
    assert payload["comparison_id"] == report.comparison_id
    assert payload["evaluation_scope"] == "WALK_FORWARD_VALIDATION"
    assert payload["validation_sample_keys"] == list(report.validation_sample_keys)
    assert payload["results"][0]["trades"][0]["entry_time"] == report.results[0].trades[0].entry_time.isoformat()
    from market_vault.research.trading_authority import TradingAuthorityError
    with pytest.raises(TradingAuthorityError, match="execution-safe"):
        compare_strategies(dataset, **{**_real_config(), "return_label": "forward_return_1d"})


def test_desktop_worker_uses_verified_workspace_comparison(verified_workspace_dataset):
    pytest.importorskip("PySide6")
    from market_vault.desktop.quant_research import _run_strategy_comparison
    view = _run_strategy_comparison(
        verified_workspace_dataset.build_path, trend_feature="return_2", trend_threshold=0,
        reversion_feature="return_2", reversion_threshold=0, ridge_alpha=1,
        ridge_threshold=0, return_label="execution_return_1d", minimum_train_periods=3,
        validation_periods=2, step_periods=2, commission_bps=10, slippage_bps=5,
    )
    assert len(view.summary["comparison_id"]) == 64
    assert int(view.summary["common_validation_rows"]) > 0
    assert [row[0] for row in view.page.rows] == ["Trend", "MeanReversion", "Ridge"]
    assert view.page.rows[1][1] == "0"


@pytest.mark.parametrize("change", [
    {"split": "TEST"},
    {"step_periods": 1},
    {"commission_bps": True},
    {"strategies": [{"kind": "RIDGE", "name": "ridge", "alpha": 0, "threshold": 0}]},
])
def test_cli_invalid_configuration_returns_structured_failure(tmp_path, capsys, change):
    plan = tmp_path / "comparison.json"
    plan.write_text(json.dumps({**_plan(tmp_path / "missing"), **change}), encoding="utf-8")
    assert cli.main(["research-compare-strategies", "--plan", str(plan)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["status"] == "FAILED"
