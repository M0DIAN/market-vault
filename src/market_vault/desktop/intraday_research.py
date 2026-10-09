"""Thin Qt presentation of versioned intraday development experiments."""

from __future__ import annotations

from datetime import datetime
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .table_model import QtTableModel


GRID_METRICS = ("total_return", "observed_max_drawdown", "trade_count", "worst_fold_return",
                "median_fold_return", "best_fold_return")


def execution_series(execution):
    daily = execution["daily"]
    return [[datetime.fromisoformat(daily[0]["open_time"]).timestamp() * 1000, 1.0]] + [
        [datetime.fromisoformat(row["close_time"]).timestamp() * 1000, row["cash_close"]] for row in daily]


def formatted_rows(rows, columns):
    from .quant_research import _format_number
    return tuple(tuple(_format_number(row[k]) if type(row[k]) in (int, float) else
                       ", ".join(row[k]) if type(row[k]) is list else str(row[k]) for k in columns) for row in rows)


def performance_table(execution, index):
    """Shared descriptive views; keep Open/Replay proof states unchanged."""
    from ..research.intraday_performance import summarize_intraday_execution
    from .quant_research import _format_number, _format_percent
    try:
        report = summarize_intraday_execution(execution)
    except (ValueError, ArithmeticError) as exc:
        return ("metric", "value", "unavailable_reason"), (("UNAVAILABLE", "—", str(exc)),)
    if index == 0:
        return ("metric", "value", "unit", "unavailable_reason"), tuple(
            (key, (_format_percent if value["unit"] == "RATIO" else _format_number)(value["value"]),
             value["unit"], value["unavailable_reason"] or "") for key, value in report["summary"].items())
    columns = ("group", "trade_count", "market_pnl", "commission_total", "slippage_total", "net_cash_pnl", "holding_minutes")
    rows = report[("by_exit_reason", "by_entry_hour", "by_trading_day")[index - 1]]
    return columns, formatted_rows(rows, columns)


def risk_value(value, unit="NUMBER"):
    """Keep small ratios visible without overflowing the percentage display."""
    if value is None:
        return "—"
    if value == 0:
        value = 0
    if unit == "RATIO":
        return f"{Decimal(str(value)) * 100:.6g}%"
    return str(value) if type(value) is int else f"{value:.6g}"


def risk_diagnostics_report(content, *, cost_index=0, candidate_index=0):
    """Derive the current immutable selection; never alter its replay proof."""
    from ..research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    from ..research.strategy_experiment import StrategyExperiment
    try:
        return analyze_intraday_risk_diagnostics(StrategyExperiment(content),
            cost_index=cost_index, candidate_index=candidate_index)
    except (ValueError, ArithmeticError) as exc:
        unavailable = {"status": "UNAVAILABLE", "unavailable_reason": str(exc), "report": None}
        return {"strategy_diagnostics": unavailable, "benchmark_diagnostics": unavailable}


def risk_diagnostics_table(result, index):
    """Small scalar tables over the public report, with each account identified."""
    sides = (("STRATEGY", "strategy_diagnostics"), ("BENCHMARK", "benchmark_diagnostics"))
    if index == 4 and not any(result[key]["status"] == "AVAILABLE"
            and result[key]["report"]["fold_diagnostics"]["status"] == "AVAILABLE" for _, key in sides):
        return ("risk_series", "metric", "unavailable_reason"), tuple(
            (side, "fold_diagnostics", result[key]["unavailable_reason"] if result[key]["status"] != "AVAILABLE"
             else result[key]["report"]["fold_diagnostics"]["unavailable_reason"]) for side, key in sides)
    columns = (
        ("risk_series", "group", "metric", "value", "unit", "unavailable_reason"),
        ("risk_series", "drawdown_episode", "drawdown_stage", "risk_date", "risk_clock", "risk_zone", "risk_equity",
         "drawdown_depth", "duration_minutes", "unavailable_reason"),
        ("risk_series", "distribution", "metric", "value", "unit", "unavailable_reason"),
        ("risk_series", "contribution_sign", "metric", "trading_day", "value", "unit", "unavailable_reason"),
        ("risk_series", "fold_index", "validation_start_day", "validation_end_day", "day_count", "trade_count",
         "cash_only_days", "compound_return", "cash_contribution", "return_sign", "unavailable_reason"),
    )[index]
    rows = []

    def unavailable(side, reason):
        message = reason or "UNAVAILABLE"
        values = {"risk_series": side, "metric": "UNAVAILABLE", "drawdown_stage": message, "unavailable_reason": message}
        rows.append(tuple(values.get(column, "—") for column in columns))

    for side, key in sides:
        wrapper = result[key]
        if wrapper["status"] != "AVAILABLE":
            unavailable(side, wrapper["unavailable_reason"])
            continue
        report = wrapper["report"]
        if index == 0:
            for metric, value in report["summary"].items():
                rows.append((side, "DRAWDOWNS", metric, risk_value(value["value"], value["unit"]),
                             value["unit"], value["unavailable_reason"] or ""))
            folds = report["fold_diagnostics"]
            if folds["status"] == "AVAILABLE":
                for metric, value in folds["summary"].items():
                    rows.append((side, "FOLDS", metric, risk_value(value["value"], value["unit"]),
                                 value["unit"], value["unavailable_reason"] or ""))
            else:
                rows.append((side, "FOLDS", "fold_diagnostics", "—", "—", folds["unavailable_reason"]))
        elif index == 1:
            if not report["drawdown_episodes"]:
                unavailable(side, "NO_DRAWDOWN_EPISODES")
            for episode in report["drawdown_episodes"]:
                number = str(episode["episode_index"])
                for stage, prefix in (("PEAK", "peak"), ("TROUGH", "trough"),
                                      ("RECOVERY" if episode["recovered"] else "UNRECOVERED", "recovery")):
                    instant = episode[prefix + "_time"]
                    point = datetime.fromisoformat(instant) if instant else None
                    clock = (point.date().isoformat(), point.time().isoformat(), point.strftime("%z")) if point else ("—", "—", "—")
                    rows.append((side, number, stage, *clock,
                        risk_value(episode[prefix + "_equity"], "INITIAL_CASH_UNITS"),
                        risk_value(episode["depth"], "RATIO") if prefix == "trough" else "—",
                        risk_value(episode["duration_minutes"], "MINUTES") if prefix == "recovery" else "—",
                        "UNRECOVERED" if prefix == "recovery" and not episode["recovered"] else ""))
        elif index == 2:
            for distribution, key in (("DAILY_RETURNS", "daily_return_distribution"),
                                      ("TRADE_RETURNS", "trade_return_distribution")):
                values = report[key]
                for metric in ("sample_count", "positive_count", "zero_count", "negative_count",
                               "minimum", "p05", "p25", "p50", "p75", "p95", "maximum"):
                    unit = "COUNT" if metric.endswith("_count") else values["unit"]
                    rows.append((side, distribution, metric, risk_value(values[metric], unit), unit,
                                 values["unavailable_reason"] if values[metric] is None else ""))
        elif index == 3:
            for sign in ("positive", "negative"):
                values = report["cash_concentration"][sign]
                for metric in ("day_count", "total_absolute_cash", "top_1_absolute_cash", "top_3_absolute_cash",
                               "top_1_share", "top_3_share"):
                    unit = "COUNT" if metric == "day_count" else "RATIO" if metric.endswith("_share") else "INITIAL_CASH_UNITS"
                    rows.append((side, sign.upper(), metric, "—", risk_value(values[metric], unit), unit,
                                 values["unavailable_reason"] if values[metric] is None else ""))
                for rank, day in enumerate(values["top_days"], 1):
                    rows.append((side, sign.upper(), f"top_day_{rank}", day["trading_day"],
                                 risk_value(day["cash_contribution"], "INITIAL_CASH_UNITS"), "INITIAL_CASH_UNITS", ""))
        else:
            folds = report["fold_diagnostics"]
            if folds["status"] != "AVAILABLE":
                unavailable(side, folds["unavailable_reason"])
                continue
            for fold in folds["rows"]:
                rows.append((side, str(fold["fold_index"]), fold["validation_days"][0], fold["validation_days"][-1],
                    str(fold["day_count"]), str(fold["trade_count"]), str(fold["cash_only_days"]),
                    risk_value(fold["compound_return"], "RATIO"), risk_value(fold["cash_contribution"], "INITIAL_CASH_UNITS"),
                    fold["return_sign"], ""))
    return columns, tuple(rows)


def return_uncertainty_table(result):
    """Display arithmetic daily means and intervals with explicit excess units."""
    columns = ("risk_series", "metric", "value", "unit", "unavailable_reason")
    rows = []
    for statistic in result["statistics"]:
        series = statistic["series"].upper()
        unit = "PERCENTAGE_POINTS" if series == "PAIRED_EXCESS" else "RATIO"
        for field, metric in (("mean", "ARITHMETIC_MEAN"), ("lower", "LOWER_95"), ("upper", "UPPER_95")):
            raw = statistic[field]
            value = risk_value(raw, "RATIO")
            if unit == "PERCENTAGE_POINTS" and raw is not None:
                value = value.removesuffix("%")
            reason = statistic["mean_unavailable_reason" if field == "mean" else "interval_unavailable_reason"]
            rows.append((series, metric, value, unit, reason or ""))
    return columns, tuple(rows)


def family_bounds_table(result):
    """Keep the complete saved family in recorded order, with separate reasons."""
    columns = ("family_member", "family_candidate_id", "family_mean_excess", "family_lower_95",
               "family_mean_reason", "family_bound_reason")
    return columns, tuple((f'{member["candidate_index"]} · {member["strategy"]["name"]}',
        member["candidate_id"][:12], risk_value(member["mean_excess"], "RATIO").removesuffix("%"),
        risk_value(member["lower"], "RATIO").removesuffix("%"),
        member["mean_unavailable_reason"] or "", member["bound_unavailable_reason"] or "")
        for member in result["members"])


class IntradayResearchController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, owner):
        super().__init__(runtime, parent=owner)
        self._owner = owner
        self._source_id = ""
        self._defaults = {}
        self._source_note = ""
        self._content = b""
        self._root = {}
        self._path = ""
        self._proof = ""
        self._collection_content = b""
        self._collection_root = {}
        self._collection_path = ""
        self._collection_proof = ""
        self._scenario_index = 0
        self._scenario_paths = {}
        self._replay_pending = False
        self._restore_revision = 0
        self._draft_plan, self._draft_source = {}, {}
        self._draft_revision = 0
        self._plan_save_pending = None
        self._plan_save_receipt = {}
        self._candidate_index = 0
        self._positions = ()
        self._names = []
        self._view_index = 0
        self._risk_report = None
        self._uncertainty_report = None
        self._uncertainty_error = ""
        self._uncertainty_pending = None
        self._family_report = None
        self._family_error = ""
        self._family_pending = None
        self._grid_snapshot = None
        self._grid_report = None
        self._grid_key = None
        self._grid_error = ""
        self._grid_metric = GRID_METRICS[0]
        self._page = 1
        self._columns, self._rows = (), ()
        self._model = QtTableModel(parent=self)
        self._set_page()
        owner.researchChanged.connect(self._source_changed)
        self.operationFailed.connect(self._replay_failed)
        self.operationFailed.connect(self._uncertainty_failed)
        self.operationFailed.connect(self._family_bounds_failed)
        runtime.operationFinished.connect(self._analysis_idle)

    def _replay_failed(self):
        if self._replay_pending:
            self._replay_pending = False
            self._proof = "REPLAY_FAILED"
            if self._collection_content:
                self._collection_proof = "REPLAY_FAILED"
            self.changed.emit()

    def _source_changed(self):
        if self._owner._intraday_data:
            raw = json.loads(self._owner._intraday_data)
            if raw["data_id"] != self._source_id:
                self._source_id = raw["data_id"]
                try:
                    from ..research.intraday_data import IntradayDataset
                    from ..research.intraday_research import default_intraday_research_plan
                    data = IntradayDataset(self._owner._intraday_data, Path(self._owner.intradayPath))
                    self._defaults = default_intraday_research_plan(data, commission_bps=0, slippage_bps=0)
                    self._source_note = ""
                except (TypeError, ValueError) as exc:
                    self._defaults = {}
                    self._source_note = "Default split unavailable; enter explicit trading-day boundaries and windows. " + str(exc)
        self.changed.emit()

    @Property(bool, notify=changed)
    def dataLoaded(self):
        return self._owner.intradayLoaded

    @Property(str, notify=changed)
    def dataPath(self):
        return self._owner.intradayPath

    @Property(str, notify=changed)
    def sourceId(self):
        return self._source_id

    @Property(str, notify=changed)
    def sourceNote(self):
        return self._source_note

    @Property("QStringList", notify=changed)
    def featureNames(self):
        return self._owner.intradayFeatureNames

    @Property("QVariantMap", notify=changed)
    def defaults(self):
        return deepcopy(self._defaults)

    @Property(bool, notify=changed)
    def draftLoaded(self):
        return bool(self._draft_plan)

    @Property(int, notify=changed)
    def draftRevision(self):
        return self._draft_revision

    @Property("QVariantMap", notify=changed)
    def draftPlan(self):
        return deepcopy(self._draft_plan)

    @Property("QVariantMap", notify=changed)
    def draftSource(self):
        return deepcopy(self._draft_source)

    @Property("QVariantMap", notify=changed)
    def planSaveReceipt(self):
        return deepcopy(self._plan_save_receipt)

    @Property(str, notify=changed)
    def pendingPlanKind(self):
        return self._plan_save_pending["kind"] if self._plan_save_pending else ""

    @Property(bool, notify=changed)
    def canContinueCandidate(self):
        return bool(self._path and self._positions and self._root.get("evaluation_mode") in
                    ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS"))

    @Property("QVariantMap", notify=changed)
    def restoredPlan(self):
        plan = self._root.get("plan", {})
        return deepcopy(plan.get("comparison_plan", plan))

    @Property("QVariantMap", notify=changed)
    def diagnosticPlan(self):
        plan = self._root.get("plan", {})
        return deepcopy(plan) if "comparison_plan" in plan else {}

    @Property("QVariantMap", notify=changed)
    def scenarioPlan(self):
        return deepcopy(self._collection_root.get("plan", {}))

    @Property(bool, notify=changed)
    def scenariosLoaded(self):
        return bool(self._collection_content)

    @Property("QStringList", notify=changed)
    def scenarioNames(self):
        return [row["name"] for row in self._collection_root.get("report", {}).get("scenarios", [])]

    @Property(int, notify=changed)
    def scenarioIndex(self):
        return self._scenario_index

    @Property(str, notify=changed)
    def collectionPath(self):
        return self._collection_path

    @Property(str, notify=changed)
    def collectionProof(self):
        return self._collection_proof

    @Property(int, notify=changed)
    def restoreRevision(self):
        return self._restore_revision

    @Property(bool, notify=changed)
    def resultLoaded(self):
        return bool(self._content)

    @Property(str, notify=changed)
    def experimentPath(self):
        return self._path

    @Property("QStringList", notify=changed)
    def candidateNames(self):
        return list(self._names)

    @Property(int, notify=changed)
    def candidateIndex(self):
        return self._candidate_index

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property(bool, notify=changed)
    def uncertaintyAvailable(self):
        return bool(self._content and self._path and self._positions and not self._collection_content
                    and self._root.get("evaluation_mode") in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS"))

    @Property(str, notify=changed)
    def uncertaintyError(self):
        return self._uncertainty_error

    @Property("QVariantMap", notify=changed)
    def uncertaintySummary(self):
        if self._uncertainty_report is None:
            return {}
        report = self._uncertainty_report
        sample = report["sample"]
        return deepcopy({"experiment_id": report["experiment_id"], "candidate_id": report["candidate_id"],
            "cost_index": report["cost_index"], "candidate_index": report["candidate_index"],
            "sampling": report["sampling"], "sample": {key: sample[key] for key in
                ("sample_count", "first_day", "last_day", "development_day_count", "fold_count", "is_contiguous",
                 "unevaluated_development_day_count", "prediction_count", "complete_target_count",
                 "complete_target_count_unavailable_reason")},
            "warnings": [{"series": row["series"].upper(),
                "reasons": list(dict.fromkeys(reason for reason in
                    (row["mean_unavailable_reason"], row["interval_unavailable_reason"]) if reason)),
                "detail": row["detail"]} for row in report["statistics"]
                if row["mean_unavailable_reason"] or row["interval_unavailable_reason"]]})

    @Property(bool, notify=changed)
    def familyBoundsAvailable(self):
        return self.uncertaintyAvailable

    @Property(str, notify=changed)
    def familyBoundsError(self):
        return self._family_error

    @Property("QVariantMap", notify=changed)
    def familyBoundsSummary(self):
        if self._family_report is None:
            return {}
        report = self._family_report
        summary = {key: report[key] for key in ("experiment_id", "data_id", "cost_index", "family_size",
            "family_scope", "historical_search_coverage", "execution_policy", "sampling", "family_inference")}
        summary["sample"] = {key: report["sample"][key] for key in ("sample_count", "first_day", "last_day",
            "fold_count", "is_contiguous", "unevaluated_development_day_count")}
        summary["deduction_display"] = risk_value(report["family_inference"]["deduction"], "RATIO").removesuffix("%")
        summary["members"] = [{key: member[key] for key in
            ("candidate_index", "candidate_id", "strategy", "mean_unavailable_reason", "detail")}
            for member in report["members"]]
        return deepcopy(summary)

    @Property(bool, notify=changed)
    def gridAvailable(self):
        return self._grid_snapshot is not None

    @Property(str, notify=changed)
    def gridError(self):
        return self._grid_error

    @Property(int, notify=changed)
    def gridCostIndex(self):
        return self._positions[self._candidate_index][0] if self._positions else 0

    @Property(int, notify=changed)
    def gridMetricIndex(self):
        return GRID_METRICS.index(self._grid_metric)

    @Property("QStringList", notify=changed)
    def gridCostNames(self):
        if not self.gridAvailable:
            return []
        return [f'{i} · {g["execution_policy"]["commission_bps"]}/{g["execution_policy"]["slippage_bps"]} bps'
                for i, g in enumerate(self._root["report"]["groups"])]

    @Property("QVariantMap", notify=changed)
    def parameterGrid(self):
        """Small detached view; coordinates retain Python's round-trip precision."""
        if self._grid_report is None:
            return {}
        view = deepcopy(self._grid_report)
        for axis in view["axes"]:
            axis["values"] = [str(value) for value in axis["values"]]
        for row in [*view["cells"], *view["neighbors"]]:
            row["axis_values"] = [str(value) for value in row["axis_values"]]
            for key in ("metric", "delta"):
                if key in row:
                    row[key]["display"] = risk_value(row[key]["value"], row[key]["unit"])
        view["center"] = view["cells"][view["selection"]["center_candidate_index"]]
        summary = view["neighborhood_summary"]
        for key in ("minimum", "median", "maximum"):
            summary[key + "_display"] = risk_value(summary[key], summary["unit"])
        return view

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        if not self._root:
            return {}
        context = self._root["report"]["context"]
        report = self._collection_root["report"] if self._collection_content else self._root["report"]
        result = {"evaluation_count": str(report["evaluation_count"]),
                "intraday_eval_days": str(len(context["evaluated_days"])),
                "intraday_ready": str(len(context["validation_keys"])), "intraday_verification": self._proof}
        if self._collection_content:
            result["intraday_scenarios"] = str(len(report["scenarios"]))
        return result

    @Property(str, notify=changed)
    def resultDetails(self):
        if not self._root:
            return ""
        parts = self._root["report"]["context"]["split"]
        dates = " | ".join(f"{name}: {parts[name][0]} → {parts[name][-1]} ({len(parts[name])})" for name in ("TRAIN", "VALIDATION", "TEST"))
        return dates + "\nData ID: " + self._root["dataset_id"]

    @Property("QVariantList", notify=changed)
    def equitySeries(self):
        if not self._positions:
            return []
        group, candidate = self._selected()
        return [execution_series(candidate["execution"]), execution_series(group["benchmark"]["execution"])]

    def _selected(self):
        cost, index = self._positions[self._candidate_index]
        group = self._root["report"]["groups"][cost]
        return group, group["results"][index]

    def selection_source(self):
        """Capture one saved immutable result before a worker can be scheduled."""
        if not self._content or not self._path or not self._positions:
            raise ValueError("Save or open the development experiment before freezing a candidate.")
        content, path = self._content, self._path
        root = json.loads(content)
        cost, index = self._positions[self._candidate_index]
        return {"path": path, "content": content, "experiment_id": root["experiment_id"],
                "cost_index": cost, "candidate_index": index,
                "candidate_id": root["report"]["groups"][cost]["results"][index]["candidate_id"]}

    def _scenario_overview(self):
        from .quant_research import _format_number, _format_percent
        scenarios = self._collection_root["report"]["scenarios"]
        baseline = scenarios[0]["experiment"]["report"]["groups"][0]["results"]
        fields = ("entry_delay_minutes", "stop_new_minutes", "flatten_minutes", "max_hold_bars",
                  "commission_bps", "slippage_bps")
        self._columns = ("scenario", "strategy", *fields, "trade_count", "total_return", "scenario_return_change",
                         "benchmark_return", "observed_max_drawdown", "annualized_volatility", "sharpe_ratio")
        rows = []
        for scenario in scenarios:
            group = scenario["experiment"]["report"]["groups"][0]
            for index, candidate in enumerate(group["results"]):
                metrics, risk = candidate["execution"]["metrics"], candidate["risk"]
                delta = metrics["total_return"] - baseline[index]["execution"]["metrics"]["total_return"]
                rows.append((scenario["name"], candidate["strategy"]["name"],
                    *(_format_number(group["execution_policy"][field]) for field in fields),
                    str(metrics["trade_count"]), _format_percent(metrics["total_return"]), _format_number(delta * 100),
                    _format_percent(group["benchmark"]["execution"]["metrics"]["total_return"]),
                    _format_percent(metrics["observed_max_drawdown"]), _format_percent(risk["annualized_volatility"]),
                    _format_number(risk["sharpe_ratio"])))
        self._rows = tuple(rows)

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    def _refresh_view(self):
        from .quant_research import _format_number, _format_percent
        if not self._root:
            return
        report = self._root["report"]
        group, candidate = self._selected()
        execution = candidate["execution"]
        if self._view_index == 18:
            if self._family_report is not None:
                self._columns, self._rows = family_bounds_table(self._family_report)
            else:
                self._columns, self._rows = (), ()
        elif self._view_index == 17:
            if self._uncertainty_report is not None:
                self._columns, self._rows = return_uncertainty_table(self._uncertainty_report)
            else:
                self._columns, self._rows = (), ()
        elif self._view_index == 16:
            self._refresh_grid()
            self._columns, self._rows = (), ()
        elif self._view_index >= 11:
            if self._risk_report is None:
                cost, index = self._positions[self._candidate_index]
                self._risk_report = risk_diagnostics_report(self._content, cost_index=cost, candidate_index=index)
            self._columns, self._rows = risk_diagnostics_table(self._risk_report, self._view_index - 11)
        elif self._view_index == 0 and self._collection_content:
            self._scenario_overview()
        elif self._view_index == 0:
            self._columns = ("strategy", "commission_bps", "slippage_bps", "trade_count", "total_return", "benchmark_return",
                             "observed_max_drawdown", "annualized_volatility", "sharpe_ratio", "cost_return_change", "mae", "rmse", "r2")
            self._rows = tuple((r["strategy"]["name"], _format_number(g["execution_policy"]["commission_bps"]),
                _format_number(g["execution_policy"]["slippage_bps"]), str(r["execution"]["metrics"]["trade_count"]),
                _format_percent(r["execution"]["metrics"]["total_return"]), _format_percent(g["benchmark"]["execution"]["metrics"]["total_return"]),
                _format_percent(r["execution"]["metrics"]["observed_max_drawdown"]), _format_percent(r["risk"]["annualized_volatility"]),
                _format_number(r["risk"]["sharpe_ratio"]), _format_percent(r["return_change_from_first_cost"]),
                *(_format_number((r["prediction_metrics"] or {}).get(key)) for key in ("mae", "rmse", "r2")))
                for g in report["groups"] for r in g["results"])
        else:
            if self._view_index == 1:
                columns, rows = ("entry_time", "exit_time", "exit_reason", "held_bars", "cash_before", "cash_after", "net_return"), execution["trades"]
            elif self._view_index == 2:
                columns, rows = ("timestamp", "phase", "action", "reason", "cash", "quantity", "equity", "drawdown"), execution["ledger"]
            elif self._view_index == 3:
                columns, rows = ("trading_day", "cash_open", "cash_close", "return", "trade_count"), execution["daily"]
            elif self._view_index == 4:
                columns = ("fold_index", "feature", "alpha", "training_count", "intercept", "coefficient", "mean", "scale")
                rows = [{"fold_index": i, "feature": feature, "alpha": r["model"]["alpha"], "training_count": len(r["model"]["training_keys"]),
                         "intercept": r["model"]["intercept"], "coefficient": r["model"]["coefficients"][j],
                         "mean": r["model"]["means"][j], "scale": r["model"]["scales"][j]}
                        for i, r in enumerate(candidate["fold_models"]) for j, feature in enumerate(r["model"]["feature_fields"])]
            elif self._view_index == 5:
                columns, rows = ("decision_time", "trading_day", "slot", "score", "target"), candidate["predictions"]
            elif self._view_index == 6:
                columns, rows = ("fold_index", "validation_days", "trade_count", "cash_contribution"), candidate["fold_contributions"]
            else:
                self._columns, self._rows = performance_table(execution, self._view_index - 7)
                self._page = 1
                self._set_page()
                return
            self._columns = columns
            self._rows = formatted_rows(rows, columns)
        self._page = 1
        self._set_page()
        if self._view_index == 17:
            self._start_uncertainty()
        elif self._view_index == 18:
            self._start_family_bounds()

    @Slot(int, result=bool)
    def selectCandidate(self, index):
        if type(index) is not int or not 0 <= index < len(self._positions):
            return False
        if self._candidate_index != index:
            self._risk_report = None
            self._uncertainty_report, self._uncertainty_error = None, ""
            self._grid_report, self._grid_key = None, None
            if self._positions[self._candidate_index][0] != self._positions[index][0]:
                self._family_report, self._family_error = None, ""
        self._candidate_index = index
        self._refresh_view()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectScenario(self, index):
        if self.busy or self._runtime.busy:
            return False
        scenarios = self._collection_root.get("report", {}).get("scenarios", [])
        if type(index) is not int or not 0 <= index < len(scenarios):
            return False
        self._scenario_index = index
        child = scenarios[index]["experiment"]
        self._apply_child(child, path=self._scenario_paths.get(child["experiment_id"], ""),
                          proof=self._collection_proof, candidate_index=self._candidate_index)
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 18:
            return False
        self._view_index = index
        self._refresh_view()
        self.changed.emit()
        return True

    def _uncertainty_selection(self):
        if not self.uncertaintyAvailable:
            return None
        return (self._root["experiment_id"], *self._positions[self._candidate_index])

    def _start_uncertainty(self):
        """Queue one saved selection through the existing offline worker."""
        if (self._view_index != 17 or not self.uncertaintyAvailable or self._uncertainty_report is not None
                or self._uncertainty_error or self._uncertainty_pending is not None or self.busy or self._runtime.busy):
            return
        selection, content = self._uncertainty_selection(), self._content
        self._uncertainty_pending = selection

        def operation(backend):
            from ..research.intraday_return_uncertainty import analyze_intraday_return_uncertainty
            from ..research.strategy_experiment import StrategyExperiment
            return analyze_intraday_return_uncertainty(StrategyExperiment(content),
                cost_index=selection[1], candidate_index=selection[2])

        def apply(report):
            self._uncertainty_pending = None
            if selection != self._uncertainty_selection():
                return
            self._uncertainty_report = report
            if self._view_index == 17:
                self._refresh_view()
            self.changed.emit()

        if not self._submit("intraday_return_uncertainty", operation, apply, requires_backend=False):
            self._uncertainty_pending = None

    def _analysis_idle(self, operation):
        # Open/Save applies its result before the runtime becomes idle. Starting
        # here also replaces a stale in-flight selection without nested workers.
        self._start_uncertainty()
        self._start_family_bounds()

    def _uncertainty_failed(self):
        selection, self._uncertainty_pending = self._uncertainty_pending, None
        if selection is not None and selection == self._uncertainty_selection():
            self._uncertainty_error = self.error
            self.changed.emit()

    @Slot(result=bool)
    def retryUncertainty(self):
        if self.busy or self._runtime.busy or not self.uncertaintyAvailable or not self._uncertainty_error:
            return False
        self._uncertainty_error = ""
        self._refresh_view()
        self.changed.emit()
        return True

    def _family_selection(self):
        if not self.familyBoundsAvailable:
            return None
        return (self._root["experiment_id"], self._positions[self._candidate_index][0])

    def _start_family_bounds(self):
        """The saved cost group is the family, regardless of its selected member."""
        if (self._view_index != 18 or not self.familyBoundsAvailable or self._family_report is not None
                or self._family_error or self._family_pending is not None or self.busy or self._runtime.busy):
            return
        selection, content = self._family_selection(), self._content
        self._family_pending = selection

        def operation(backend):
            from ..research.intraday_family_bounds import analyze_intraday_family_bounds
            from ..research.strategy_experiment import StrategyExperiment
            return analyze_intraday_family_bounds(StrategyExperiment(content), cost_index=selection[1])

        def apply(report):
            self._family_pending = None
            if selection != self._family_selection():
                return
            self._family_report = report
            if self._view_index == 18:
                self._refresh_view()
            self.changed.emit()

        if not self._submit("intraday_family_bounds", operation, apply, requires_backend=False):
            self._family_pending = None

    def _family_bounds_failed(self):
        selection, self._family_pending = self._family_pending, None
        if selection is not None and selection == self._family_selection():
            self._family_error = self.error
            self.changed.emit()

    @Slot(result=bool)
    def retryFamilyBounds(self):
        if self.busy or self._runtime.busy or not self.familyBoundsAvailable or not self._family_error:
            return False
        self._family_error = ""
        self._refresh_view()
        self.changed.emit()
        return True

    def _refresh_grid(self):
        if not self.gridAvailable:
            return
        cost, candidate = self._positions[self._candidate_index]
        key = (cost, candidate, self._grid_metric)
        if self._grid_key == key:
            return
        from ..research.intraday_parameter_grid import analyze_intraday_parameter_grid
        try:
            self._grid_report = analyze_intraday_parameter_grid(self._grid_snapshot, cost_index=cost,
                center_candidate_index=candidate, metric=self._grid_metric)
            self._grid_key, self._grid_error = key, ""
        except (ValueError, ArithmeticError) as exc:
            self._grid_report, self._grid_key, self._grid_error = None, None, str(exc)

    @Slot(int, result=bool)
    def selectGridCost(self, index):
        if not self.gridAvailable or type(index) is not int or not 0 <= index < len(self.gridCostNames):
            return False
        candidate = self._positions[self._candidate_index][1]
        return self.selectCandidate(self._positions.index((index, candidate)))

    @Slot(int, result=bool)
    def selectGridCandidate(self, index):
        if not self.gridAvailable or type(index) is not int:
            return False
        position = (self.gridCostIndex, index)
        return self.selectCandidate(self._positions.index(position)) if position in self._positions else False

    @Slot(int, result=bool)
    def selectGridMetric(self, index):
        if not self.gridAvailable or type(index) is not int or not 0 <= index < len(GRID_METRICS):
            return False
        self._grid_metric = GRID_METRICS[index]
        if self._view_index == 16:
            self._refresh_grid()
        self.changed.emit()
        return True

    @Slot(result=bool)
    def openGridCandidateDetails(self):
        return self.selectView(1) if self.gridAvailable else False

    @Slot(int, result=bool)
    def changePage(self, offset):
        page = self._page + offset
        if not 1 <= page <= max(1, (len(self._rows) + 99) // 100):
            return False
        self._page = page
        self._set_page()
        return True

    def _compile_comparison(self, values):
        from .quant_research import _bounded_int, _parse_comparison_strategies
        from ..research.intraday_research import INTRADAY_RESEARCH_PLAN_VERSION, normalize_intraday_research_plan
        from ..research.strategy_config import strategy_plan_fields
        common = _parse_comparison_strategies(values, values.get("feature_fields", []))
        plan = {"plan_schema_version": INTRADAY_RESEARCH_PLAN_VERSION,
                "intraday_data_path": values.get("intraday_data_path", self.dataPath),
                "data_id": values.get("data_id", self._source_id), "feature_fields": list(common["feature_fields"]),
                "strategies": [strategy_plan_fields(s) for s in common["strategies"]],
                "split": {key: values.get(key, "") for key in ("train_end_day", "validation_end_day", "test_end_day")},
                "walk_forward": {key: _bounded_int(values.get(key), key, 1, 2**31 - 1) for key in
                                 ("minimum_train_days", "validation_days", "step_days")},
                "execution": self._owner._intraday_execution_values(values)}
        return normalize_intraday_research_plan(plan, recorded=True)

    def _admit_run(self, plan):
        comparison = plan.get("comparison_plan", plan)
        if not Path(comparison["intraday_data_path"]).is_absolute():
            raise ValueError("The original intraday data locator is not an absolute path on this host.")
        if not self.dataLoaded:
            raise ValueError("Open intraday data before running development research.")
        if comparison["data_id"] != self._source_id:
            raise ValueError("Open the intraday data matching these research settings before running.")
        if any(field not in self.featureNames for field in comparison["feature_fields"]):
            raise ValueError("Common Features must be available in the currently open intraday data.")
        return plan

    def _plan(self, values):
        return self._admit_run(self._compile_comparison(values))

    def _compile_diagnostics(self, values):
        from .quant_research import _finite_float
        from ..research.intraday_research import INTRADAY_DIAGNOSTICS_PLAN_VERSION, expand_intraday_plan
        axes = [{**axis, "values": [_finite_float(v.strip(), "axis value") for v in axis["values"].split(",")]
                 if type(axis["values"]) is str else axis["values"]} for axis in values["parameter_axes"]]
        costs = values["cost_scenarios"]
        if type(costs) is str:
            pairs = [part.split("/") for part in costs.split(",")]
            if any(len(pair) != 2 for pair in pairs):
                raise ValueError("Costs use commission/slippage pairs separated by commas.")
            costs = [{"commission_bps": _finite_float(a, "commission"), "slippage_bps": _finite_float(b, "slippage")} for a, b in pairs]
        plan, _, _ = expand_intraday_plan({"plan_schema_version": INTRADAY_DIAGNOSTICS_PLAN_VERSION,
            "comparison_plan": self._compile_comparison(values["comparison"]), "strategy_name": values["strategy_name"],
            "parameter_axes": axes, "cost_scenarios": costs}, recorded=True)
        return plan

    def _compile_scenarios(self, values):
        from ..research.intraday_backtest import EXECUTION_FIELDS
        from ..research.intraday_execution_scenarios import (
            INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION, normalize_intraday_execution_scenarios_plan,
        )
        scenarios = values["execution_scenarios"]
        if type(scenarios) is not list or not scenarios:
            raise ValueError("Enter at least one explicit execution scenario.")
        normalized_scenarios = []
        for scenario in scenarios:
            if type(scenario) is not dict or set(scenario) != {"name", "execution"}:
                raise ValueError("Each scenario requires a name and its complete execution policy.")
            if type(scenario["execution"]) is not dict or set(scenario["execution"]) != EXECUTION_FIELDS:
                raise ValueError("Each scenario requires all six execution fields.")
            normalized_scenarios.append({"name": scenario["name"],
                "execution": self._owner._intraday_execution_values(scenario["execution"])})
        common = deepcopy(values["comparison"])
        # Only the initial, unbound form may leave its unused common costs blank.
        if not common.get("execution_policy_bound", False) and any(common.get(key) in (None, "")
                for key in ("commission_bps", "slippage_bps")):
            # Validate every other edited field before materializing this policy.
            self._compile_comparison({**common, **{key: 0 for key in ("commission_bps", "slippage_bps")
                if common.get(key) in (None, "")}})
            common.update(normalized_scenarios[0]["execution"])
        return normalize_intraday_execution_scenarios_plan({
            "plan_schema_version": INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSION,
            "comparison_plan": self._compile_comparison(common), "execution_scenarios": normalized_scenarios,
        }, recorded=True)

    @Slot(str, "QVariantMap", result=bool)
    def preparePlanSave(self, kind, values):
        self._plan_save_pending = None
        try:
            from ..research.intraday_plan import serialize_intraday_plan
            compiler = {"comparison": self._compile_comparison, "diagnostics": self._compile_diagnostics,
                        "scenarios": self._compile_scenarios}.get(kind)
            if compiler is None:
                raise ValueError("Choose an explicit comparison, diagnostics or scenarios plan.")
            self._plan_save_pending = {"kind": kind, "content": serialize_intraday_plan(compiler(values))}
        except (TypeError, ValueError, KeyError) as exc:
            self.changed.emit()
            return self._reject_input(exc)
        self._error, self._status = "", "READY"
        self.stateChanged.emit()
        self.changed.emit()
        return True

    @Slot()
    def cancelPlanSave(self):
        self._plan_save_pending = None
        self.changed.emit()

    @Slot(str, result=bool)
    def savePreparedPlan(self, raw_path):
        captured, self._plan_save_pending = self._plan_save_pending, None
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
            if captured is None:
                raise ValueError("Capture a valid plan before choosing its save path.")
        except (OSError, TypeError, ValueError) as exc:
            self.changed.emit()
            return self._reject_input(exc)
        self.changed.emit()
        def operation(backend):
            from ..research.intraday_plan import write_intraday_plan
            return write_intraday_plan(captured["content"], path=path)
        def apply(value):
            self._plan_save_receipt = {"path": str(value.path), "kind": captured["kind"],
                "content_sha256": value.content_sha256, "created_new_file": value.created_new_file}
            self.changed.emit()
        return self._submit("intraday_plan_save", operation, apply, requires_backend=False)

    def _apply_draft(self, plan, source):
        self._draft_plan, self._draft_source = deepcopy(plan), deepcopy(source)
        self._draft_revision += 1
        self.changed.emit()

    @Slot(str, result=bool)
    def loadPlan(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_plan import load_intraday_plan
            return load_intraday_plan(path)
        return self._submit("intraday_plan_load", operation,
            lambda plan: self._apply_draft(plan, {"kind": "FILE", "path": str(path)}), requires_backend=False)

    @Slot(result=bool)
    def continueCandidate(self):
        try:
            if not self.canContinueCandidate:
                raise ValueError("Save or open a development candidate first; export a scenario as an ordinary experiment.")
            captured = self.selection_source()
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_plan import extract_intraday_candidate_plan
            return extract_intraday_candidate_plan(captured["path"],
                expected_experiment_id=captured["experiment_id"], expected_candidate_id=captured["candidate_id"],
                cost_index=captured["cost_index"], candidate_index=captured["candidate_index"])
        source = {key: captured[key] for key in ("path", "experiment_id", "candidate_id", "cost_index", "candidate_index")}
        return self._submit("intraday_plan_continue", operation,
            lambda plan: self._apply_draft(plan, {"kind": "CANDIDATE", **source}), requires_backend=False)

    def _apply_child(self, root, *, path="", proof="COMPUTED", candidate_index=0, snapshot=None):
        """Present an already validated ordinary Q7 child; its file path is separate."""
        from ..strategy_comparison_io import canonical_json
        self._content = canonical_json(root)
        self._root = root
        self._risk_report = None
        self._uncertainty_report, self._uncertainty_error = None, ""
        self._family_report, self._family_error = None, ""
        self._grid_snapshot = snapshot if root["evaluation_mode"] == "INTRADAY_DIAGNOSTICS" else None
        self._grid_report, self._grid_key, self._grid_error = None, None, ""
        self._grid_metric = GRID_METRICS[0]
        self._path, self._proof = path, proof
        self._positions = tuple((i, j) for i, g in enumerate(self._root["report"]["groups"]) for j in range(len(g["results"])))
        self._names = [f'{self._root["report"]["groups"][i]["results"][j]["strategy"]["name"]} | {self._root["report"]["groups"][i]["execution_policy"]["commission_bps"]}/{self._root["report"]["groups"][i]["execution_policy"]["slippage_bps"]} bps'
                       for i, j in self._positions]
        self._candidate_index = min(candidate_index, len(self._positions) - 1)
        self._refresh_view()

    def _apply(self, snapshot, *, path="", opened=False):
        from ..research.intraday_execution_scenarios import INTRADAY_EXECUTION_SCENARIOS_VERSION
        root = snapshot.as_dict()
        proof = "RECORDED" if opened else "COMPUTED"
        self._scenario_index, self._scenario_paths = 0, {}
        if root["artifact_schema_version"] == INTRADAY_EXECUTION_SCENARIOS_VERSION:
            self._collection_content, self._collection_root = snapshot.content, root
            self._collection_path, self._collection_proof = path, proof
            self._apply_child(root["report"]["scenarios"][0]["experiment"], proof=proof)
        else:
            self._collection_content, self._collection_root = b"", {}
            self._collection_path, self._collection_proof = "", ""
            self._apply_child(root, path=path, proof=proof, snapshot=snapshot)
        if opened:
            self._restore_revision += 1
        self.changed.emit()

    def _run(self, plan):
        def operation(backend):
            from ..research.intraday_research import run_intraday_research
            from ..research.intraday_experiment import create_intraday_experiment
            return create_intraday_experiment(plan=plan, report=run_intraday_research(plan), name="Intraday development")
        return self._submit("intraday_research", operation, self._apply, requires_backend=False)

    @Slot("QVariantMap", result=bool)
    def runComparison(self, values):
        try:
            plan = self._plan(values)
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        return self._run(plan)

    @Slot("QVariantMap", result=bool)
    def runDiagnostics(self, values):
        try:
            plan = self._admit_run(self._compile_diagnostics(values))
        except (TypeError, ValueError, KeyError) as exc:
            return self._reject_input(exc)
        return self._run(plan)

    @Slot("QVariantMap", result=bool)
    def runScenarios(self, values):
        try:
            plan = self._admit_run(self._compile_scenarios(values))
        except (TypeError, ValueError, KeyError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_execution_scenarios import run_intraday_execution_scenarios
            return run_intraday_execution_scenarios(plan, name="Intraday execution scenarios")
        return self._submit("intraday_scenarios", operation, self._apply, requires_backend=False)

    @Slot(str, result=bool)
    def saveExperiment(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
            if not self._content:
                raise ValueError("Run or open an intraday experiment before saving.")
            is_collection = bool(self._collection_content)
            content = self._collection_content if is_collection else self._content
            experiment_id = json.loads(content)["experiment_id"]
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, write_strategy_experiment
            return write_strategy_experiment(StrategyExperiment(content), path=path)
        def apply(result):
            if is_collection:
                if self._collection_root.get("experiment_id") == experiment_id:
                    self._collection_path = str(result.path)
            elif self._root.get("experiment_id") == experiment_id:
                self._path = str(result.path)
            self.changed.emit()
        return self._submit("intraday_scenarios_save" if is_collection else "intraday_experiment_save",
                            operation, apply, requires_backend=False)

    @Slot(str, result=bool)
    def exportScenario(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
            if not self._collection_content:
                raise ValueError("Run or open execution scenarios before exporting one scenario.")
            content = self._collection_content
            collection_id = self._collection_root["experiment_id"]
            index, child_id = self._scenario_index, self._root["experiment_id"]
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_execution_scenarios import extract_intraday_execution_scenario
            from ..research.strategy_experiment import StrategyExperiment, write_strategy_experiment
            child = extract_intraday_execution_scenario(StrategyExperiment(content),
                expected_experiment_id=collection_id, scenario_index=index, expected_child_experiment_id=child_id)
            return write_strategy_experiment(child, path=path)
        def apply(result):
            if self._collection_root.get("experiment_id") == collection_id:
                self._scenario_paths[child_id] = str(result.path)
                if self._scenario_index == index and self._root.get("experiment_id") == child_id:
                    self._path = str(result.path)
            self.changed.emit()
        return self._submit("intraday_scenario_export", operation, apply, requires_backend=False)

    @Slot(str, result=bool)
    def openExperiment(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import load_strategy_experiment
            from ..research.intraday_experiment import INTRADAY_EXPERIMENT_VERSION
            from ..research.intraday_execution_scenarios import INTRADAY_EXECUTION_SCENARIOS_VERSION
            snapshot = load_strategy_experiment(path)
            if snapshot.as_dict()["artifact_schema_version"] not in (INTRADAY_EXPERIMENT_VERSION, INTRADAY_EXECUTION_SCENARIOS_VERSION):
                raise ValueError("Select an intraday development experiment or execution scenario collection.")
            return snapshot
        return self._submit("intraday_experiment_open", operation, lambda value: self._apply(value, path=str(path), opened=True), requires_backend=False)

    @Slot(str, result=bool)
    def replayExperiment(self, raw_path=""):
        if self.busy or self._runtime.busy:
            return False
        if not self._content:
            return self._reject_input(ValueError("Open or run an experiment before replay."))
        try:
            from .quant_research import _experiment_file_path
            data_file = _experiment_file_path(raw_path) if raw_path else None
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        is_collection = bool(self._collection_content)
        content = self._collection_content if is_collection else self._content
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, replay_strategy_experiment
            return replay_strategy_experiment(StrategyExperiment(content), intraday_data_file=data_file)
        def apply(result):
            self._replay_pending = False
            self._proof = "REPLAY_MATCH"
            if is_collection:
                self._collection_proof = "REPLAY_MATCH"
            self.changed.emit()
        self._replay_pending = True
        self._proof = "REPLAY_PENDING"
        if is_collection:
            self._collection_proof = "REPLAY_PENDING"
        self.changed.emit()
        accepted = self._submit("intraday_scenarios_replay" if is_collection else "intraday_experiment_replay",
                                operation, apply, requires_backend=False)
        if not accepted:
            self._replay_failed()
        return accepted
