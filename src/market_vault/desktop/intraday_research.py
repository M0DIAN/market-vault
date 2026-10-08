"""Thin Qt presentation of versioned intraday development experiments."""

from __future__ import annotations

from datetime import datetime
from copy import deepcopy
import json
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .table_model import QtTableModel


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
        self._replay_pending = False
        self._restore_revision = 0
        self._candidate_index = 0
        self._positions = ()
        self._names = []
        self._view_index = 0
        self._page = 1
        self._columns, self._rows = (), ()
        self._model = QtTableModel(parent=self)
        self._set_page()
        owner.researchChanged.connect(self._source_changed)
        self.operationFailed.connect(self._replay_failed)

    def _replay_failed(self):
        if self._replay_pending:
            self._replay_pending = False
            self._proof = "REPLAY_FAILED"
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

    @Property("QVariantMap", notify=changed)
    def restoredPlan(self):
        plan = self._root.get("plan", {})
        return deepcopy(plan.get("comparison_plan", plan))

    @Property("QVariantMap", notify=changed)
    def diagnosticPlan(self):
        plan = self._root.get("plan", {})
        return deepcopy(plan) if "comparison_plan" in plan else {}

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

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        if not self._root:
            return {}
        context = self._root["report"]["context"]
        return {"evaluation_count": str(self._root["report"]["evaluation_count"]),
                "intraday_eval_days": str(len(context["evaluated_days"])),
                "intraday_ready": str(len(context["validation_keys"])), "intraday_verification": self._proof}

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
        return [self._series(candidate["execution"]), self._series(group["benchmark"]["execution"])]

    def _series(self, execution):
        daily = execution["daily"]
        return [[datetime.fromisoformat(daily[0]["open_time"]).timestamp() * 1000, 1.0]] + [
            [datetime.fromisoformat(row["close_time"]).timestamp() * 1000, row["cash_close"]] for row in daily]

    def _selected(self):
        cost, index = self._positions[self._candidate_index]
        group = self._root["report"]["groups"][cost]
        return group, group["results"][index]

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
        if self._view_index == 0:
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
            else:
                columns, rows = ("fold_index", "validation_days", "trade_count", "cash_contribution"), candidate["fold_contributions"]
            self._columns = columns
            self._rows = tuple(tuple(_format_number(row[k]) if type(row[k]) in (int, float) else
                                    ", ".join(row[k]) if type(row[k]) is list else str(row[k]) for k in columns) for row in rows)
        self._page = 1
        self._set_page()

    @Slot(int, result=bool)
    def selectCandidate(self, index):
        if type(index) is not int or not 0 <= index < len(self._positions):
            return False
        self._candidate_index = index
        self._refresh_view()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 6:
            return False
        self._view_index = index
        self._refresh_view()
        return True

    @Slot(int, result=bool)
    def changePage(self, offset):
        page = self._page + offset
        if not 1 <= page <= max(1, (len(self._rows) + 99) // 100):
            return False
        self._page = page
        self._set_page()
        return True

    def _plan(self, values):
        from .quant_research import _bounded_int, _parse_comparison_strategies
        from ..research.intraday_research import INTRADAY_RESEARCH_PLAN_VERSION, normalize_intraday_research_plan
        from ..research.strategy_config import strategy_plan_fields
        if not self.dataLoaded:
            raise ValueError("Open intraday data before running development research.")
        if values.get("data_id", self._source_id) != self._source_id:
            raise ValueError("Open the intraday data matching these research settings before running.")
        common = _parse_comparison_strategies(values, self.featureNames)
        plan = {"plan_schema_version": INTRADAY_RESEARCH_PLAN_VERSION, "intraday_data_path": self.dataPath,
                "data_id": self._source_id, "feature_fields": list(common["feature_fields"]),
                "strategies": [strategy_plan_fields(s) for s in common["strategies"]],
                "split": {key: values.get(key, "") for key in ("train_end_day", "validation_end_day", "test_end_day")},
                "walk_forward": {key: _bounded_int(values.get(key), key, 1, 2**31 - 1) for key in
                                 ("minimum_train_days", "validation_days", "step_days")},
                "execution": self._owner._intraday_execution_values(values)}
        return normalize_intraday_research_plan(plan)

    def _apply(self, snapshot, *, path="", opened=False):
        self._content = snapshot.content
        self._root = snapshot.as_dict()
        self._path, self._proof = path, "RECORDED" if opened else "COMPUTED"
        self._positions = tuple((i, j) for i, g in enumerate(self._root["report"]["groups"]) for j in range(len(g["results"])))
        self._names = [f'{self._root["report"]["groups"][i]["results"][j]["strategy"]["name"]} | {self._root["report"]["groups"][i]["execution_policy"]["commission_bps"]}/{self._root["report"]["groups"][i]["execution_policy"]["slippage_bps"]} bps'
                       for i, j in self._positions]
        self._candidate_index = 0
        if opened:
            self._restore_revision += 1
        self._refresh_view()
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
                "comparison_plan": self._plan(values["comparison"]), "strategy_name": values["strategy_name"],
                "parameter_axes": axes, "cost_scenarios": costs})
        except (TypeError, ValueError, KeyError) as exc:
            return self._reject_input(exc)
        return self._run(plan)

    @Slot(str, result=bool)
    def saveExperiment(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
            if not self._content:
                raise ValueError("Run or open an intraday experiment before saving.")
            content = self._content
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, write_strategy_experiment
            return write_strategy_experiment(StrategyExperiment(content), path=path)
        def apply(result):
            self._path = str(result.path)
            self.changed.emit()
        return self._submit("intraday_experiment_save", operation, apply, requires_backend=False)

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
            snapshot = load_strategy_experiment(path)
            if snapshot.as_dict()["artifact_schema_version"] != INTRADAY_EXPERIMENT_VERSION:
                raise ValueError("Select an intraday development experiment.")
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
        content = self._content
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, replay_strategy_experiment
            return replay_strategy_experiment(StrategyExperiment(content), intraday_data_file=data_file)
        def apply(result):
            self._replay_pending = False
            self._proof = "REPLAY_MATCH"
            self.changed.emit()
        self._replay_pending = True
        self._proof = "REPLAY_PENDING"
        self.changed.emit()
        accepted = self._submit("intraday_experiment_replay", operation, apply, requires_backend=False)
        if not accepted:
            self._replay_failed()
        return accepted
