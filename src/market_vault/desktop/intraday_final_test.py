"""Thin Qt state for independent immutable selection and TEST snapshots."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .intraday_research import execution_series, formatted_rows
from .table_model import QtTableModel


class IntradayFinalController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, research, parent):
        super().__init__(runtime, parent=parent)
        self._research = research
        self._selection_content, self._test_content = b"", b""
        self._selection_root, self._test_root = {}, {}
        self._selection_path, self._test_path = "", ""
        self._selection_proof, self._test_proof = "", ""
        self._pending_replay = ""
        self._binding_revision = 0
        self._view_index, self._page = 0, 1
        self._columns, self._rows = (), ()
        self._model = QtTableModel(parent=self)
        self._set_page()
        research.changed.connect(self.changed.emit)
        self.operationFailed.connect(self._replay_failed)

    @Property(QObject, constant=True)
    def researchController(self):
        return self._research

    @Property(bool, notify=changed)
    def canFreeze(self):
        return bool(self._research.resultLoaded and self._research.experimentPath)

    @Property(bool, notify=changed)
    def selectionLoaded(self):
        return bool(self._selection_content)

    @Property(bool, notify=changed)
    def testLoaded(self):
        return bool(self._test_content)

    @Property(str, notify=changed)
    def selectionPath(self):
        return self._selection_path

    @Property(str, notify=changed)
    def testPath(self):
        return self._test_path

    @Property(int, notify=changed)
    def bindingRevision(self):
        return self._binding_revision

    @Property("QVariantMap", notify=changed)
    def frozenCandidate(self):
        return deepcopy(self._selection_root.get("report", {}).get("candidate", {}))

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        if not self.selectionLoaded:
            return {}
        result = {"intraday_selection_proof": self._selection_proof}
        if self.testLoaded:
            report = self._test_root["report"]
            result.update(intraday_test_proof=self._test_proof, intraday_eval_days=str(len(report["execution"]["daily"])),
                          intraday_ready=str(len(report["predictions"])))
        return result

    @Property(str, notify=changed)
    def selectionDetails(self):
        if not self.selectionLoaded:
            return ""
        report = self._selection_root["report"]
        candidate, context = report["candidate"], report["context"]
        strategy, policy = candidate["strategy"], candidate["execution_policy"]
        if strategy["kind"] == "RIDGE":
            parameters = f'alpha={strategy["alpha"]}, threshold={strategy["threshold"]}'
        else:
            rules = strategy.get("conditions", [strategy])
            parameters = f' {strategy.get("match", "")} '.join(f'{r["signal_field"]} {r["comparator"]} {r["threshold"]}' for r in rules)
        days = " | ".join(f'{key}: {context["split"][key][0]} → {context["split"][key][-1]} ({len(context["split"][key])})'
                          for key in ("TRAIN", "VALIDATION", "TEST"))
        return f'{strategy["name"]}: {parameters} | {policy["commission_bps"]}/{policy["slippage_bps"]} bps\n{days}'

    @Property(str, notify=changed)
    def provenanceDetails(self):
        if not self.selectionLoaded:
            return ""
        root = self._selection_root
        return f'Selection ID: {root["report"]["selection_id"]}\nData ID: {root["dataset_id"]}\n' + root["plan"]["source_experiment"]["path"] + "\n" + root["report"]["context"]["intraday_data_path"]

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    @Property("QVariantList", notify=changed)
    def equitySeries(self):
        if not self.testLoaded:
            return []
        report = self._test_root["report"]
        return [execution_series(report["execution"]), execution_series(report["benchmark"]["execution"])]

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    def _refresh_view(self):
        from .quant_research import _format_number, _format_percent
        self._columns, self._rows = (), ()
        if self.testLoaded:
            report = self._test_root["report"]
            execution, model = report["execution"], report["model"]
            if self._view_index == 0:
                self._columns = ("strategy", "commission_bps", "slippage_bps", "trade_count", "total_return", "benchmark_return",
                                 "observed_max_drawdown", "annualized_volatility", "sharpe_ratio", "mae", "rmse", "r2")
                self._rows = ((report["strategy"]["name"], _format_number(report["execution_policy"]["commission_bps"]),
                    _format_number(report["execution_policy"]["slippage_bps"]), str(execution["metrics"]["trade_count"]),
                    _format_percent(execution["metrics"]["total_return"]), _format_percent(report["benchmark"]["execution"]["metrics"]["total_return"]),
                    _format_percent(execution["metrics"]["observed_max_drawdown"]), _format_percent(report["risk"]["annualized_volatility"]),
                    _format_number(report["risk"]["sharpe_ratio"]),
                    *(_format_number((report["prediction_metrics"] or {}).get(key)) for key in ("mae", "rmse", "r2"))),)
            else:
                if self._view_index == 1:
                    columns, rows = ("entry_time", "exit_time", "exit_reason", "held_bars", "cash_before", "cash_after", "net_return"), execution["trades"]
                elif self._view_index == 2:
                    columns, rows = ("timestamp", "phase", "action", "reason", "cash", "quantity", "equity", "drawdown"), execution["ledger"]
                elif self._view_index == 3:
                    columns, rows = ("trading_day", "cash_open", "cash_close", "return", "trade_count"), execution["daily"]
                elif self._view_index == 4:
                    columns = ("feature", "alpha", "training_count", "intercept", "coefficient", "mean", "scale")
                    rows = [] if model is None else [{"feature": feature, "alpha": model["alpha"], "training_count": len(model["training_keys"]),
                        "intercept": model["intercept"], "coefficient": model["coefficients"][j],
                        "mean": model["means"][j], "scale": model["scales"][j]} for j, feature in enumerate(model["feature_fields"])]
                else:
                    columns, rows = ("decision_time", "trading_day", "slot", "score", "target"), report["predictions"]
                self._columns, self._rows = columns, formatted_rows(rows, columns)
        self._page = 1
        self._set_page()

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 5:
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

    def _apply_selection(self, snapshot, *, path="", opened=False, notify=True):
        self._selection_content, self._selection_root = snapshot.content, snapshot.as_dict()
        self._selection_path, self._selection_proof = path, "RECORDED" if opened else "FROZEN"
        self._test_content, self._test_root, self._test_path, self._test_proof = b"", {}, "", ""
        self._binding_revision += 1
        self._refresh_view()
        if notify:
            self.changed.emit()

    def _apply_test(self, snapshot, *, path="", opened=False):
        from ..research.strategy_experiment import StrategyExperiment
        root = snapshot.as_dict()
        if opened:
            selection = StrategyExperiment(json.dumps(root["plan"]["selection"]).encode("utf-8"))
            self._apply_selection(selection, opened=True, notify=False)
        self._test_content, self._test_root = snapshot.content, root
        self._test_path, self._test_proof = path, "RECORDED" if opened else "COMPUTED"
        self._refresh_view()
        self.changed.emit()

    @Slot(result=bool)
    def freezeSelected(self):
        try:
            captured = self._research.selection_source()
        except (TypeError, ValueError, IndexError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_final_test import freeze_intraday_candidate
            return freeze_intraday_candidate(captured["path"], expected_experiment_id=captured["experiment_id"],
                cost_index=captured["cost_index"], candidate_index=captured["candidate_index"],
                expected_candidate_id=captured["candidate_id"], name="Intraday selection")
        return self._submit("intraday_selection_freeze", operation, self._apply_selection, requires_backend=False)

    def _open(self, raw_path, *, test):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import load_strategy_experiment
            from ..research.intraday_final_test import INTRADAY_SELECTION_VERSION, INTRADAY_TEST_EXPERIMENT_VERSION
            snapshot = load_strategy_experiment(path)
            if snapshot.as_dict()["artifact_schema_version"] != (INTRADAY_TEST_EXPERIMENT_VERSION if test else INTRADAY_SELECTION_VERSION):
                raise ValueError("Select an intraday TEST experiment." if test else "Select a frozen intraday selection.")
            return snapshot
        apply = self._apply_test if test else self._apply_selection
        return self._submit("intraday_test_open" if test else "intraday_selection_open", operation,
                            lambda value: apply(value, path=str(path), opened=True), requires_backend=False)

    def _save(self, raw_path, *, test):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
            content = self._test_content if test else self._selection_content
            if not content:
                raise ValueError("Create or open the snapshot before saving.")
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, write_strategy_experiment
            return write_strategy_experiment(StrategyExperiment(content), path=path)
        def apply(result):
            if test:
                self._test_path = str(result.path)
            else:
                self._selection_path = str(result.path)
            self.changed.emit()
        return self._submit("intraday_test_save" if test else "intraday_selection_save", operation, apply, requires_backend=False)

    @Slot(str, result=bool)
    def openSelection(self, path):
        return self._open(path, test=False)

    @Slot(str, result=bool)
    def openTest(self, path):
        return self._open(path, test=True)

    @Slot(str, result=bool)
    def saveSelection(self, path):
        return self._save(path, test=False)

    @Slot(str, result=bool)
    def saveTest(self, path):
        return self._save(path, test=True)

    def _paths(self, source, data):
        from .quant_research import _experiment_file_path
        return (_experiment_file_path(source) if source else None, _experiment_file_path(data) if data else None)

    @Slot(str, str, result=bool)
    def runTest(self, source="", data=""):
        try:
            if not self._selection_content:
                raise ValueError("Freeze or open a selection before TEST.")
            paths, content = self._paths(source, data), self._selection_content
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment
            from ..research.intraday_final_test import create_intraday_test_experiment, run_intraday_final_test
            selected = StrategyExperiment(content)
            report = run_intraday_final_test(selected, source_experiment_file=paths[0], intraday_data_file=paths[1])
            return create_intraday_test_experiment(selected, report, name="Intraday TEST")
        return self._submit("intraday_test_run", operation, self._apply_test, requires_backend=False)

    def _replay_failed(self):
        if self._pending_replay:
            if self._pending_replay == "test":
                self._test_proof = "REPLAY_FAILED"
            else:
                self._selection_proof = "REPLAY_FAILED"
            self._pending_replay = ""
            self.changed.emit()

    def _replay(self, source, data, *, test):
        if self.busy or self._runtime.busy:
            return False
        content = self._test_content if test else self._selection_content
        try:
            paths = self._paths(source, data)
            if not content:
                raise ValueError("Create or open the snapshot before replay.")
        except (OSError, TypeError, ValueError) as exc:
            if content:
                self._pending_replay = "test" if test else "selection"
                self._replay_failed()
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, replay_strategy_experiment
            return replay_strategy_experiment(StrategyExperiment(content), source_experiment_file=paths[0], intraday_data_file=paths[1])
        def apply(result):
            self._pending_replay = ""
            if test:
                self._test_proof = "REPLAY_MATCH"
            else:
                self._selection_proof = "REPLAY_MATCH"
            self.changed.emit()
        self._pending_replay = "test" if test else "selection"
        if test:
            self._test_proof = "REPLAY_PENDING"
        else:
            self._selection_proof = "REPLAY_PENDING"
        self.changed.emit()
        accepted = self._submit("intraday_test_replay" if test else "intraday_selection_replay", operation, apply, requires_backend=False)
        if not accepted:
            self._replay_failed()
        return accepted

    @Slot(str, str, result=bool)
    def replaySelection(self, source="", data=""):
        return self._replay(source, data, test=False)

    @Slot(str, str, result=bool)
    def replayTest(self, source="", data=""):
        return self._replay(source, data, test=True)
