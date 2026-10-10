"""Thin Qt state for independent immutable selection and TEST snapshots."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .intraday_research import (
    execution_series, formatted_rows, performance_table, risk_diagnostics_report, risk_diagnostics_table,
)
from .table_model import QtTableModel


def _model_rows(model, **labels):
    """Display the two recorded transforms in their fitted Feature/term order."""
    if model is None:
        return []
    common = {**labels, "alpha": model["alpha"], "training_count": len(model["training_keys"]),
              "model_id": model["model_id"], "training_boundary": model["training_boundary"]}
    rows = []
    if "input_transform" in model:
        rows.extend({**common, "model_stage": "INPUT_TRANSFORM", "feature": feature,
            "intercept": "—", "coefficient": "—", "mean": model["input_transform"]["means"][index],
            "scale": model["input_transform"]["scales"][index]} for index, feature in enumerate(model["input_features"]))
        stage, model = "GENERATED_TERMS", model["ridge_model"]
    else:
        stage = "LINEAR_FEATURES"
    rows.extend({**common, "model_stage": stage, "feature": feature, "intercept": model["intercept"],
        "coefficient": model["coefficients"][index], "mean": model["means"][index], "scale": model["scales"][index]}
        for index, feature in enumerate(model["feature_fields"]))
    return rows


_MODEL_COLUMNS = ("model_stage", "feature", "alpha", "training_count", "intercept", "coefficient",
                  "mean", "scale", "model_id", "training_boundary")


class IntradayFinalController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, research, parent, inner=None):
        super().__init__(runtime, parent=parent)
        self._research = research
        self._inner = inner
        self._selection_content, self._test_content = b"", b""
        self._selection_root, self._test_root = {}, {}
        self._selection_path, self._test_path = "", ""
        self._selection_proof, self._test_proof = "", ""
        self._pending_action = None
        self._locators, self._locator_revision, self._notice = ("", ""), 0, ""
        self._binding_revision = 0
        self._view_index, self._page = 0, 1
        self._risk_report = None
        self._columns, self._rows = (), ()
        self._model = QtTableModel(parent=self)
        self._set_page()
        research.changed.connect(self.changed.emit)
        if inner is not None:
            inner.changed.connect(self.changed.emit)
        self.operationFailed.connect(self._bound_failed)

    @Property(QObject, constant=True)
    def researchController(self):
        return self._research

    @Property(bool, notify=changed)
    def canFreeze(self):
        return bool(self._research.resultLoaded and self._research.experimentPath and not self.freezeUnsupported)

    @Property(bool, notify=changed)
    def freezeUnsupported(self):
        from ..research.intraday_experiment import INTRADAY_EXPERIMENT_VERSION, INTRADAY_EXPERIMENT_V2_VERSION
        if not self._research.resultLoaded:
            return False
        schema = self._research._root.get("artifact_schema_version")
        return not (schema == INTRADAY_EXPERIMENT_VERSION or (schema == INTRADAY_EXPERIMENT_V2_VERSION
                    and self._research._selected()[1]["strategy"]["kind"] == "QUADRATIC_RIDGE"))

    @Property(bool, notify=changed)
    def canFreezeInner(self):
        return bool(self._inner is not None and self._inner.experimentPath and self._inner.finalRecipe
                    and self._inner._root["report"]["status"] == "AVAILABLE")

    @Property(str, notify=changed)
    def innerSourceDetails(self):
        if self._inner is None or not self._inner.resultLoaded:
            return ""
        recipe = self._inner.finalRecipe
        shown = f'{recipe["kind"]} · alpha={recipe["alpha"]} · threshold={recipe["threshold"]}' if recipe else "UNAVAILABLE"
        return f'{shown}\n{self._inner.experimentPath or "UNSAVED"}'

    @Property(str, notify=changed)
    def notice(self):
        return self._notice

    @Slot(str, str)
    def setLocations(self, source, data):
        locators = (source, data)
        if locators != self._locators:
            self._locators = locators
            self._locator_revision += 1
            self._notice = ""
            self.changed.emit()

    @Property(bool, notify=changed)
    def hasDevSelection(self):
        return bool(self._selection_root.get("report", {}).get("dev_selection"))

    @Property("QVariantMap", notify=changed)
    def selectionEvidence(self):
        if not self.selectionLoaded:
            return {}
        root, report = self._selection_root, self._selection_root["report"]
        candidate, source = report["candidate"], root["plan"]["source_experiment"]
        evidence = report.get("dev_selection")
        result = {"source_id": source["experiment_id"], "source_path": source["path"],
                  "selection_id": report["selection_id"], "features": ", ".join(report["context"]["feature_fields"]),
                  "policy": ", ".join(f"{key}={value}" for key, value in candidate["execution_policy"].items()),
                  "data_path": report["context"]["intraday_data_path"], "data_id": root["dataset_id"],
                  "kind": candidate["strategy"]["kind"], "axis_values": str(candidate["axis_values"])}
        if evidence:
            reference, window = evidence["fixed_reference"], evidence["final_dev"]
            recipe = reference["strategy"]
            result.update(reference=f'{recipe["kind"]} · alpha={recipe["alpha"]} · threshold={recipe["threshold"]} · axes={reference["axis_values"]}',
                ordinary_source_id=evidence["source_experiment"]["experiment_id"],
                candidate_id=evidence["source_selection"]["candidate_id"],
                cost_index=evidence["source_selection"]["cost_index"], candidate_index=evidence["source_selection"]["candidate_index"],
                final_cutoff=window["history_boundary"], inner_cutoff=window["training_boundary"],
                inner_days=" → ".join((window["validation_days"][0], window["validation_days"][-1])),
                selected_index=window["selected_index"], method=evidence["method"])
        else:
            result.update(candidate_id=root["plan"]["selection"]["candidate_id"],
                          cost_index=root["plan"]["selection"]["cost_index"], candidate_index=root["plan"]["selection"]["candidate_index"])
        if self.testLoaded and self._test_root["report"]["model"]:
            model = self._test_root["report"]["model"]
            result.update(final_model_id=model["model_id"], final_training_count=len(model["training_keys"]),
                          final_training_boundary=model["training_boundary"],
                          terms=", ".join(term["name"] for term in model.get("terms", [])))
        return result

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
        if strategy["kind"] in ("RIDGE", "QUADRATIC_RIDGE"):
            parameters = f'alpha={strategy["alpha"]}, threshold={strategy["threshold"]}'
        else:
            rules = strategy.get("conditions", [strategy])
            parameters = f' {strategy.get("match", "")} '.join(f'{r["signal_field"]} {r["comparator"]} {r["threshold"]}' for r in rules)
        days = " | ".join(f'{key}: {context["split"][key][0]} → {context["split"][key][-1]} ({len(context["split"][key])})'
                          for key in ("TRAIN", "VALIDATION", "TEST"))
        return f'{strategy["name"]} · {strategy["kind"]}: {parameters} | {policy["commission_bps"]}/{policy["slippage_bps"]} bps\n{days}'

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
        if self._view_index >= 15:
            self._dev_view()
        elif self.testLoaded:
            report = self._test_root["report"]
            execution, model = report["execution"], report["model"]
            if self._view_index >= 10:
                if self._risk_report is None:
                    self._risk_report = risk_diagnostics_report(self._test_content)
                self._columns, self._rows = risk_diagnostics_table(self._risk_report, self._view_index - 10)
            elif self._view_index == 0:
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
                    columns, rows = _MODEL_COLUMNS, _model_rows(model)
                elif self._view_index == 5:
                    columns, rows = ("decision_time", "trading_day", "slot", "score", "target"), report["predictions"]
                else:
                    self._columns, self._rows = performance_table(execution, self._view_index - 6)
                    self._page = 1
                    self._set_page()
                    return
                self._columns, self._rows = columns, formatted_rows(rows, columns)
        self._page = 1
        self._set_page()

    def _dev_view(self):
        evidence = self._selection_root.get("report", {}).get("dev_selection")
        if not evidence:
            return
        window, rows = evidence["final_dev"], []
        if self._view_index == 15:
            columns = ("inner_member", "strategy", "alpha", "inner_mse", "inner_chosen", "training_count",
                       "inner_complete", "training_boundary", "inner_history_boundary")
            rows = [dict(zip(columns, (member["candidate_index"], member["strategy"]["kind"], member["strategy"]["alpha"],
                member["mse"], "YES" if member["candidate_index"] == window["selected_index"] else "NO",
                len(window["training_keys"]), len(window["scored_targets"]), window["training_boundary"], window["history_boundary"])))
                for member in window["family_results"]]
        elif self._view_index == 16:
            columns = ("inner_member", *_MODEL_COLUMNS)
            rows = [row for member in window["family_results"] for row in _model_rows(member["model"], inner_member=member["candidate_index"])]
        elif self._view_index == 17:
            columns = ("inner_role", "value", "inner_label_end", "inner_target")
            for key in ("history_days", "training_days", "validation_days", "history_training_keys", "history_purged_keys",
                        "training_keys", "purged_keys", "validation_keys"):
                rows.extend(dict(zip(columns, (key, value, "—", "—"))) for value in window[key])
            rows.extend(dict(zip(columns, ("SCORED_TARGET", row["observation_key"], row["actual_label_end_time"], row["value"])))
                        for row in window["scored_targets"])
        else:
            columns = ("inner_member", "trading_day", "decision_time", "score", "target", "inner_target", "inner_label_end")
            targets = {row["observation_key"]: row for row in window["scored_targets"]}
            for member in window["family_results"]:
                for row in member["predictions"]:
                    target = targets.get(row["observation_key"], {})
                    rows.append({**row, "inner_member": member["candidate_index"], "inner_target": target.get("value", "—"),
                                 "inner_label_end": target.get("actual_label_end_time", "—")})
        self._columns, self._rows = columns, formatted_rows(rows, columns)

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 18:
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
        self._notice = ""
        self._selection_path, self._selection_proof = path, "RECORDED" if opened else "FROZEN"
        self._test_content, self._test_root, self._test_path, self._test_proof = b"", {}, "", ""
        self._risk_report = None
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
        self._risk_report = None
        self._test_path, self._test_proof = path, "RECORDED" if opened else "COMPUTED"
        self._refresh_view()
        self.changed.emit()

    @Slot(result=bool)
    def freezeSelected(self):
        try:
            if self.freezeUnsupported:
                raise ValueError("This saved strategy is not yet supported by final TEST.")
            captured = self._research.selection_source()
        except (TypeError, ValueError, IndexError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_final_test import freeze_intraday_candidate
            return freeze_intraday_candidate(captured["path"], expected_experiment_id=captured["experiment_id"],
                cost_index=captured["cost_index"], candidate_index=captured["candidate_index"],
                expected_candidate_id=captured["candidate_id"], name="Intraday selection")
        return self._submit("intraday_selection_freeze", operation, self._apply_selection, requires_backend=False)

    @Slot(result=bool)
    def freezeInnerSelection(self):
        try:
            if not self.canFreezeInner:
                raise ValueError("Open or save an AVAILABLE inner-selection study before freezing its final DEV recipe.")
            captured = (self._inner.experimentPath, self._inner._root["experiment_id"])
        except (TypeError, ValueError, KeyError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_final_test import freeze_intraday_inner_selection
            return freeze_intraday_inner_selection(captured[0], expected_experiment_id=captured[1], name="Intraday final DEV selection")
        return self._submit("intraday_selection_freeze_inner", operation, self._apply_selection, requires_backend=False)

    @Slot(str, result=bool)
    def openInnerSource(self, path):
        if self._inner is None:
            return self._reject_input(ValueError("The inner-selection source controller is unavailable."))
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import load_strategy_experiment
            from ..research.intraday_inner_selection import INTRADAY_INNER_SELECTION_VERSION
            snapshot = load_strategy_experiment(path)
            if snapshot.as_dict()["artifact_schema_version"] != INTRADAY_INNER_SELECTION_VERSION:
                raise ValueError("Open a saved inner-selection study.")
            return snapshot
        return self._submit("intraday_inner_open", operation,
            lambda snapshot: self._inner._apply(snapshot, path=str(path), opened=True), requires_backend=False)

    def _open(self, raw_path, *, test):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import load_strategy_experiment
            from ..research.intraday_final_test import INTRADAY_SELECTION_VERSIONS, INTRADAY_TEST_EXPERIMENT_VERSIONS
            snapshot = load_strategy_experiment(path)
            if snapshot.as_dict()["artifact_schema_version"] not in (INTRADAY_TEST_EXPERIMENT_VERSIONS if test else INTRADAY_SELECTION_VERSIONS):
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
        return self._start_bound("run", operation, self._apply_test)

    def _bound_key(self):
        return (self._binding_revision, self._selection_root.get("experiment_id"),
                self._test_root.get("experiment_id"), self._locator_revision)

    def _set_proof(self, action, value):
        if action == "replay_test":
            self._test_proof = value
        elif action == "replay_selection":
            self._selection_proof = value

    def _start_bound(self, action, operation, apply):
        if self.busy or self._runtime.busy:
            return False
        key = self._bound_key()
        self._pending_action, self._notice = (action, key), ""
        self.changed.emit()
        def completed(value):
            self._pending_action = None
            if key != self._bound_key():
                self._notice = "STALE_INPUT"
                self._set_proof(action, "REPLAY_STALE_INPUT")
                self.changed.emit()
                return
            apply(value)
        accepted = self._submit("intraday_test_run" if action == "run" else
            "intraday_test_replay" if action == "replay_test" else "intraday_selection_replay", operation, completed, requires_backend=False)
        if not accepted:
            self._pending_action = None
            self._set_proof(action, "REPLAY_FAILED")
        return accepted

    def _bound_failed(self):
        pending, self._pending_action = self._pending_action, None
        if pending is None:
            return
        action, key = pending
        if key != self._bound_key():
            self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
            self._set_proof(action, "REPLAY_STALE_INPUT")
            self.stateChanged.emit()
        else:
            self._set_proof(action, "REPLAY_FAILED")
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
                self._set_proof("replay_test" if test else "replay_selection", "REPLAY_FAILED")
                self.changed.emit()
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, replay_strategy_experiment
            return replay_strategy_experiment(StrategyExperiment(content), source_experiment_file=paths[0], intraday_data_file=paths[1])
        def apply(result):
            self._set_proof("replay_test" if test else "replay_selection", "REPLAY_MATCH")
            self.changed.emit()
        action = "replay_test" if test else "replay_selection"
        self._set_proof(action, "REPLAY_PENDING")
        self.changed.emit()
        return self._start_bound(action, operation, apply)

    @Slot(str, str, result=bool)
    def replaySelection(self, source="", data=""):
        return self._replay(source, data, test=False)

    @Slot(str, str, result=bool)
    def replayTest(self, source="", data=""):
        return self._replay(source, data, test=True)
