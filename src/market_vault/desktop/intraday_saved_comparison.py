"""Offline A/B presentation with separate input drafts and captured results."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .table_model import QtTableModel


def metric_value(value: float | int | None, unit: str) -> str:
    """Keep small return errors visible; ratio units alone are percentages."""
    if value is None:
        return "—"
    if value == 0:
        value = 0
    if unit == "RATIO":
        return f"{Decimal(str(value)) * 100:.6g}%"
    return str(value) if type(value) is int else f"{value:.6g}"


def compact_value(value: object, *, present: bool = True) -> str:
    if not present:
        return "MISSING"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if type(value) in (list, dict) and len(text) > 80:
        count = f"[{len(value)}]" if type(value) is list else f"{{{len(value)}}}"
        return count + " · " + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return text


def utc_time(value: str) -> str:
    """Keep the displayed time consistent with its UTC column heading."""
    return datetime.fromisoformat(value).astimezone(timezone.utc).time().isoformat()


class IntradaySavedComparisonController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._sources = {"left": None, "right": None}
        self._result = {}
        self._bound_sources = []
        self._portfolio_result = {}
        self._portfolio_bound_sources = []
        self._portfolio_model_index = 0
        self._weight_a_text, self._weight_b_text = "0.5", "0.5"
        self._view_index, self._page = 0, 1
        self._columns, self._rows = (), ()
        self._model = QtTableModel(parent=self)
        self._set_page()

    def _source_view(self, side):
        source = self._sources[side]
        if source is None:
            return {"loaded": False, "path": "", "name": "", "experiment_id": "", "candidate_id": "",
                    "cost_names": [], "candidate_names": [], "cost_index": 0, "candidate_index": 0, "is_test": False}
        root = source["root"]
        is_test = root["evaluation_mode"] == "INTRADAY_TEST"
        groups = [root["report"]] if is_test else root["report"]["groups"]
        group = groups[source["cost_index"]]
        candidates = [root["report"]] if is_test else group["results"]
        candidate = candidates[source["candidate_index"]]
        return {"loaded": True, "path": source["path"], "name": root["name"], "experiment_id": root["experiment_id"],
                "candidate_id": candidate["final_test_id"] if is_test else candidate["candidate_id"],
                "is_test": is_test, "cost_index": source["cost_index"], "candidate_index": source["candidate_index"],
                "cost_names": [f'{index} · {group["execution_policy"]["commission_bps"]}/{group["execution_policy"]["slippage_bps"]} bps'
                               for index, group in enumerate(groups)],
                "candidate_names": [f'{index} · {row["strategy"]["name"]}' for index, row in enumerate(candidates)]}

    @Property("QVariantMap", notify=changed)
    def leftSource(self):
        return self._source_view("left")

    @Property("QVariantMap", notify=changed)
    def rightSource(self):
        return self._source_view("right")

    @Property(bool, notify=changed)
    def canCompare(self):
        return all(self._sources.values())

    @Property(bool, notify=changed)
    def resultLoaded(self):
        return bool(self._result)

    @Property("QVariantList", notify=changed)
    def boundSources(self):
        return deepcopy(self._bound_sources)

    @Property(bool, notify=changed)
    def portfolioView(self):
        return self._view_index >= 4

    @Property(bool, notify=changed)
    def portfolioResultLoaded(self):
        return bool(self._portfolio_result)

    @Property(bool, notify=changed)
    def displayedResultLoaded(self):
        return self.portfolioResultLoaded if self.portfolioView else self.resultLoaded

    @Property("QVariantList", notify=changed)
    def displayedBoundSources(self):
        return deepcopy(self._portfolio_bound_sources if self.portfolioView else self._bound_sources)

    @Property(str, notify=changed)
    def weightAText(self):
        return self._weight_a_text

    @Property(str, notify=changed)
    def weightBText(self):
        return self._weight_b_text

    @Property(int, notify=changed)
    def portfolioModelIndex(self):
        return self._portfolio_model_index

    @Slot(int, result=bool)
    def selectPortfolioModel(self, index):
        if type(index) is not int or index not in (0, 1):
            return False
        self._portfolio_model_index = index
        self.changed.emit()
        return True

    @Property(bool, notify=changed)
    def portfolioRebalanceResult(self):
        return self._portfolio_result.get("allocation", {}).get("method") == "DAILY_TARGET_CASH_REALLOCATION"

    @Property(str, notify=changed)
    def portfolioReportId(self):
        key = "portfolio_rebalance_id" if self.portfolioRebalanceResult else "portfolio_id"
        return self._portfolio_result.get(key, "")

    def _draft_weights(self):
        try:
            values = (float(self._weight_a_text), float(self._weight_b_text))
        except ValueError as exc:
            raise ValueError("Enter finite A and B weights from 0 to 1, with a total no greater than 1.") from exc
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values) or math.fsum(values) > 1:
            raise ValueError("Enter finite A and B weights from 0 to 1, with a total no greater than 1.")
        return values

    @Property(str, notify=changed)
    def draftCashWeight(self):
        try:
            a, b = self._draft_weights()
        except ValueError:
            return "—"
        return metric_value(1 - math.fsum((a, b)), "RATIO")

    @Property(str, notify=changed)
    def portfolioInputReason(self):
        if not self.canCompare:
            return "OPEN_TWO_DEV"
        if any(self._source_view(side)["is_test"] for side in ("left", "right")):
            return "DEV_ONLY"
        try:
            self._draft_weights()
        except ValueError:
            return "INVALID_WEIGHTS"
        return ""

    @Property(bool, notify=changed)
    def canAnalyzePortfolio(self):
        return not self.portfolioInputReason

    @Slot(str, result=bool)
    def setWeightA(self, value):
        if type(value) is not str:
            return False
        self._weight_a_text = value
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def setWeightB(self, value):
        if type(value) is not str:
            return False
        self._weight_b_text = value
        self.changed.emit()
        return True

    @Property("QVariantMap", notify=changed)
    def portfolioContext(self):
        return deepcopy({key: self._portfolio_result[key] for key in
            ("portfolio_id", "portfolio_rebalance_id", "version", "evidence", "allocation", "sample", "basis", "availability")
            if key in self._portfolio_result})

    @Property("QVariantList", notify=changed)
    def portfolioCalendarRows(self):
        if not self._portfolio_result:
            return []
        return deepcopy([{"side": "COMMON", **self._portfolio_result["sample"]},
            *({"side": row["side"], **row["sample"]} for row in self._portfolio_bound_sources)])

    @Property("QVariantList", notify=changed)
    def portfolioWarnings(self):
        availability = self._portfolio_result.get("availability", {})
        return [{"side": "A" if row["side"] == "LEFT" else "B", "part": row["account"],
                 "reason": row["unavailable_reason"] or "", "detail": row["detail"] or ""}
                for row in availability.get("account_checks", []) if row["status"] != "AVAILABLE"]

    @Property("QStringList", notify=changed)
    def portfolioJointLossDays(self):
        return list(self._portfolio_result.get("complementarity", {}).get("joint_loss_days", []))

    @Property("QVariantList", notify=changed)
    def portfolioPolicyRows(self):
        rows = []
        for source in self._portfolio_bound_sources:
            for account, policy_key in (("STRATEGY", "execution_policy"), ("BENCHMARK", "benchmark_execution_policy")):
                rows.append({"side": source["side"], "account": account,
                    "fields": [{"key": "execution_policy." + key, "value": compact_value(value)}
                               for key, value in source[policy_key].items()]})
        return rows

    @Property(str, notify=changed)
    def comparisonNotice(self):
        if not self._result:
            return ""
        if any(self._result[side]["evaluation_mode"] == "INTRADAY_TEST" for side in ("left", "right")):
            return "TEST_DESCRIPTIVE_ONLY"
        return "COMPARABLE_DEV" if self._result["delta_allowed"] else "BASIS_MISMATCH"

    @Property("QStringList", notify=changed)
    def comparisonReasons(self):
        return list(self._result.get("delta_reasons", []))

    @Property("QVariantList", notify=changed)
    def performanceWarnings(self):
        rows = []
        if self._result:
            for side, label in (("left", "A"), ("right", "B")):
                for part in ("candidate", "benchmark"):
                    value = self._result[side][part + "_performance"]
                    if value["status"] == "UNAVAILABLE":
                        rows.append({"side": label, "part": part, "reason": value["unavailable_reason"] or "",
                                     "detail": value["detail"] or ""})
        return rows

    @Property("QVariantList", notify=changed)
    def configurationRows(self):
        def value(row, side):
            return json.dumps(row[side], ensure_ascii=False, sort_keys=True) if row[side + "_present"] else "MISSING"
        return [{"key": row["key"], "left": value(row, "left"), "right": value(row, "right")}
                for row in self._result.get("configuration_differences", [])]

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    def _refresh_view(self):
        self._columns, self._rows = (), ()
        if self.portfolioView:
            self._refresh_portfolio_view()
        elif self._result:
            if self._view_index < 2:
                self._columns = ("metric", "compare_left", "compare_left_unit", "compare_right", "compare_right_unit",
                                 "compare_delta", "compare_delta_unit", "compare_left_reason", "compare_right_reason",
                                 "compare_delta_reason", "compare_left_evidence", "compare_right_evidence")
                self._rows = tuple((row["metric"], metric_value(row["left"]["value"], row["left"]["unit"]), row["left"]["unit"],
                    metric_value(row["right"]["value"], row["right"]["unit"]), row["right"]["unit"],
                    metric_value(row["delta"]["value"], row["delta"]["unit"]), row["delta"]["unit"],
                    row["left"]["unavailable_reason"] or "", row["right"]["unavailable_reason"] or "",
                    row["delta"]["unavailable_reason"] or "", row["left"]["evidence"], row["right"]["evidence"])
                    for row in self._result[("strategy_metrics", "benchmark_metrics")[self._view_index]])
            elif self._view_index == 2:
                self._columns = ("compare_field", "compare_left", "compare_right")
                self._rows = tuple((row["key"], compact_value(row["left"], present=row["left_present"]),
                                    compact_value(row["right"], present=row["right_present"]))
                                   for row in self._result["configuration_differences"])
            else:
                self._columns = ("compare_field", "compare_left", "compare_right", "compare_matches")
                self._rows = tuple((row["key"], compact_value(row["left"]), compact_value(row["right"]),
                                    "MATCH" if row["matches"] else "DIFFERENT") for row in self._result["basis_checks"])
        self._page = 1
        self._set_page()

    def _refresh_portfolio_view(self):
        report = self._portfolio_result
        if not report:
            return
        def metric(row):
            return metric_value(row["value"], row["unit"]), row["unit"], row["unavailable_reason"] or ""
        if self._view_index == 4:
            self._columns = ("metric", "value", "unit", "unavailable_reason")
            values = report["complementarity"]
            rows = [(key, *metric(values[key])) for key in ("correlation", "joint_loss_count", "joint_loss_ratio")]
            rows.extend(("holding_" + key + "_" + measure, *metric(row[measure]))
                        for key, row in values["holding_overlap"].items() for measure in ("minutes", "ratio"))
            self._rows = tuple(rows)
        elif self._view_index == 5:
            self._columns = ("portfolio_account", "metric", "value", "unit", "unavailable_reason")
            self._rows = tuple((account, key, *metric(report[account][section][key]))
                for account in ("portfolio", "benchmark")
                for section, keys in (("summary", ("initial_cash", "final_cash", "total_return", "observed_max_drawdown")),
                    ("risk", ("return_count", "mean_daily_return", "annualized_volatility", "sharpe_ratio")))
                for key in keys)
        elif self._view_index == 6:
            self._columns = ("portfolio_sequence", "trading_day", "slot", "portfolio_time", "phase", "equity", "cash",
                             "drawdown", "portfolio_benchmark_equity", "portfolio_benchmark_cash", "portfolio_benchmark_drawdown")
            self._rows = tuple((str(row["sequence"]), row["trading_day"], str(row["slot"]),
                utc_time(row["timestamp"]), row["phase"],
                *(metric_value(row[key], "RATIO" if "drawdown" in key else "NUMBER")
                  for key in ("equity", "cash", "drawdown", "benchmark_equity", "benchmark_cash", "benchmark_drawdown")))
                for row in report["path"])
        elif self._view_index == 7:
            self._columns = ("portfolio_account", "portfolio_sleeve", "metric", "value", "unit", "unavailable_reason")
            keys = ("weight", "final_cash", "cash_contribution", "market_pnl", "commission_total", "slippage_total")
            if self.portfolioRebalanceResult:
                keys += ("initial_allocation", "net_transfers")
            self._rows = tuple((account, row["sleeve"], key, *metric(row[key]))
                for account in ("portfolio", "benchmark") for row in report["attribution"][account]
                for key in keys)
        elif self._view_index in (8, 9):
            allocation = self._view_index == 8
            keys = (("target_weight", "source_cash_open", "scale_factor", "allocated_cash", "cash_close",
                     "cash_contribution", "market_pnl", "commission_total", "slippage_total") if allocation else
                    ("previous_cash_close", "target_cash", "net_transfer"))
            self._columns = ("portfolio_account", "trading_day", "portfolio_time", "portfolio_sleeve",
                *("portfolio_trading_contribution" if key == "cash_contribution" else key for key in keys))
            collection = report["daily_allocations" if allocation else "cash_transfers"]
            self._rows = tuple((account, row["trading_day"], utc_time(row["open_time"]), row["sleeve"],
                *(metric_value(row[key], "RATIO" if key == "target_weight" else "NUMBER") for key in keys))
                for account in ("portfolio", "benchmark") for row in collection[account])

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index < (10 if self.portfolioRebalanceResult else 8):
            return False
        self._view_index = index
        self._refresh_view()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def changePage(self, offset):
        if type(offset) is not int:
            return False
        page = self._page + offset
        if not 1 <= page <= max(1, (len(self._rows) + 99) // 100):
            return False
        self._page = page
        self._set_page()
        return True

    def _open(self, side, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import load_strategy_experiment
            from ..research.intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
            from ..research.intraday_final_test import INTRADAY_TEST_EXPERIMENT_VERSION
            from ..research.intraday_execution_scenarios import INTRADAY_EXECUTION_SCENARIOS_VERSIONS
            snapshot = load_strategy_experiment(path)
            root = snapshot.as_dict()
            if root["artifact_schema_version"] in INTRADAY_EXECUTION_SCENARIOS_VERSIONS:
                raise ValueError("Export one scenario as a development experiment before opening it for A/B comparison.")
            if root["artifact_schema_version"] not in (*INTRADAY_EXPERIMENT_VERSIONS, INTRADAY_TEST_EXPERIMENT_VERSION):
                raise ValueError("Open a saved intraday development, diagnostics or TEST experiment.")
            return {"content": snapshot.content, "root": root, "path": str(path), "cost_index": 0, "candidate_index": 0}
        def apply(value):
            self._sources[side] = value
            self.changed.emit()
        return self._submit("intraday_compare_open_" + side, operation, apply, requires_backend=False)

    @Slot(str, result=bool)
    def openLeft(self, path):
        return self._open("left", path)

    @Slot(str, result=bool)
    def openRight(self, path):
        return self._open("right", path)

    def _select(self, side, *, cost=None, candidate=None):
        source = self._sources[side]
        if source is None:
            return False
        choices = self._source_view(side)
        if cost is not None:
            if type(cost) is not int or not 0 <= cost < len(choices["cost_names"]):
                return False
            source["cost_index"] = cost
            count = 1 if choices["is_test"] else len(source["root"]["report"]["groups"][cost]["results"])
            source["candidate_index"] = min(source["candidate_index"], count - 1)
        else:
            if type(candidate) is not int or not 0 <= candidate < len(choices["candidate_names"]):
                return False
            source["candidate_index"] = candidate
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectLeftCost(self, index):
        return self._select("left", cost=index)

    @Slot(int, result=bool)
    def selectRightCost(self, index):
        return self._select("right", cost=index)

    @Slot(int, result=bool)
    def selectLeftCandidate(self, index):
        return self._select("left", candidate=index)

    @Slot(int, result=bool)
    def selectRightCandidate(self, index):
        return self._select("right", candidate=index)

    @Slot(result=bool)
    def compare(self):
        try:
            if not self.canCompare:
                raise ValueError("Open both A and B before comparing saved experiments.")
            captured = {side: {key: self._sources[side][key] for key in ("content", "path", "cost_index", "candidate_index")}
                        for side in ("left", "right")}
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment
            from ..research.intraday_saved_comparison import compare_saved_intraday_experiments
            return compare_saved_intraday_experiments(StrategyExperiment(captured["left"]["content"]),
                StrategyExperiment(captured["right"]["content"]),
                **{side + "_" + key: source[key] for side, source in captured.items() for key in ("cost_index", "candidate_index")})
        def apply(value):
            self._result = value
            self._bound_sources = [{"side": label, "path": captured[side]["path"],
                **{key: deepcopy(value[side][key]) for key in ("name", "experiment_id", "data_id", "candidate_id",
                    "evaluation_mode", "cost_index", "candidate_index", "strategy", "execution_policy")}}
                for side, label in (("left", "A"), ("right", "B"))]
            self._refresh_view()
            self.changed.emit()
        return self._submit("intraday_compare_saved", operation, apply, requires_backend=False)

    @Slot(result=bool)
    def analyzePortfolio(self):
        try:
            if not self.canCompare or any(self._source_view(side)["is_test"] for side in ("left", "right")):
                raise ValueError("Open two ordinary saved DEV candidates before analyzing a portfolio.")
            weight_a, weight_b = self._draft_weights()
            model_index = self._portfolio_model_index
            captured = {side: {key: self._sources[side][key] for key in ("content", "path", "cost_index", "candidate_index")}
                        for side in ("left", "right")}
        except (TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment
            if model_index == 1:
                from ..research.intraday_portfolio_rebalance import analyze_intraday_portfolio_rebalance as analyze
            else:
                from ..research.intraday_portfolio import analyze_intraday_portfolio as analyze
            return analyze(StrategyExperiment(captured["left"]["content"]),
                StrategyExperiment(captured["right"]["content"]), weight_a=weight_a, weight_b=weight_b,
                **{side + "_" + key: source[key] for side, source in captured.items() for key in ("cost_index", "candidate_index")})
        def apply(value):
            # An explicit action owns this captured result, even if drafts changed while it ran.
            self._portfolio_result = value
            self._portfolio_bound_sources = [{"side": label, "path": captured[side]["path"], **deepcopy(value[side])}
                for side, label in (("left", "A"), ("right", "B"))]
            if not self.portfolioView or (self._view_index >= 8 and not self.portfolioRebalanceResult):
                self._view_index = 4
            self._refresh_view()
            self.changed.emit()
        name = "intraday_portfolio_rebalance" if model_index == 1 else "intraday_portfolio"
        return self._submit(name, operation, apply, requires_backend=False)
