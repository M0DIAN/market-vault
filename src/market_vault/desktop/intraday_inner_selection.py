"""Thin native state for the independent fixed inner-selection experiment."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .intraday_research import execution_series, formatted_rows, risk_value
from .table_model import QtTableModel


class IntradayInnerSelectionController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, research, parent):
        super().__init__(runtime, parent=parent)
        self._research = research
        self._content, self._root, self._path, self._proof = b"", {}, "", ""
        self._data_locator, self._notice, self._study_error = "", "", ""
        self._revision, self._artifact_revision = 0, 0
        self._source_signature = None
        self._pending = None
        self._view_index, self._page = 0, 1
        self._columns, self._rows = (), ()
        self._model = QtTableModel(parent=self)
        self._set_page()
        research.changed.connect(self._source_changed)
        self.operationFailed.connect(self._failed)
        self._source_changed()

    def _signature(self):
        try:
            captured = self._research.selection_source()
            return (captured["path"], captured["experiment_id"], captured["candidate_id"],
                    captured["cost_index"], captured["candidate_index"])
        except (ValueError, TypeError, IndexError, KeyError):
            return None

    def _source_changed(self):
        signature = self._signature()
        if signature != self._source_signature:
            self._source_signature = signature
            self._revision += 1
            self._study_error = ""
        self.changed.emit()

    @Property(QObject, constant=True)
    def researchController(self):
        return self._research

    @Property(bool, notify=changed)
    def canRun(self):
        from ..research.intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
        if self._source_signature is None or self._research._root.get("artifact_schema_version") not in INTRADAY_EXPERIMENT_VERSIONS:
            return False
        return (self._research._selected()[1]["strategy"]["kind"] in ("RIDGE", "QUADRATIC_RIDGE")
                and 1 <= len(self._research._root["report"]["context"]["feature_fields"]) <= 6)

    @Property(str, notify=changed)
    def dataLocator(self):
        return self._data_locator

    @Slot(str)
    def setDataLocator(self, value):
        if value != self._data_locator:
            self._data_locator = value
            self._revision += 1
            self._study_error = ""
            self.changed.emit()

    @Property(bool, notify=changed)
    def resultLoaded(self):
        return bool(self._content)

    @Property(str, notify=changed)
    def experimentPath(self):
        return self._path

    @Property(str, notify=changed)
    def proof(self):
        return self._proof

    @Property(str, notify=changed)
    def notice(self):
        return self._notice

    @Property(str, notify=changed)
    def studyError(self):
        return self._study_error

    @Property("QVariantMap", notify=changed)
    def finalRecipe(self):
        return deepcopy(self._root.get("report", {}).get("final_dev", {}).get("selected_recipe") or {})

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        if not self._root:
            return {}
        report = self._root["report"]
        account = report["selected_account"]
        return {"inner_status": report["status"], "inner_proof": self._proof,
                "inner_folds": str(len(report["outer_folds"])),
                "intraday_ready": str(len(account["predictions"])) if account else "—"}

    @Property("QVariantMap", notify=changed)
    def completedDetails(self):
        if not self._root:
            return {}
        plan, report = self._root["plan"], self._root["report"]
        source = report["source_experiment"]
        selection = plan["selection"]
        recipe = report["final_dev"]["selected_recipe"]
        context = source["report"]["context"]
        final = (f'{recipe["kind"]} · alpha={recipe["alpha"]} · threshold={recipe["threshold"]}' if recipe else "UNAVAILABLE")
        group = source["report"]["groups"][selection["cost_index"]]
        return {"final_recipe": final, "features": ", ".join(context["feature_fields"]),
                "evaluated_days": len(context["evaluated_days"]), "cost_index": selection["cost_index"],
                "candidate_index": selection["candidate_index"], "experiment_id": self._root["experiment_id"],
                "source_id": source["experiment_id"], "candidate_id": selection["candidate_id"],
                "source_path": plan["source_experiment"]["path"], "data_path": plan["intraday_data_path"],
                "policy": ", ".join(f"{key}={value}" for key, value in group["execution_policy"].items()),
                "final_cutoff": report["final_dev"]["history_boundary"],
                "unavailable_reasons": deepcopy(report["unavailable_reasons"])}

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _reference(self):
        report, selection = self._root["report"], self._root["plan"]["selection"]
        return report["source_experiment"]["report"]["groups"][selection["cost_index"]]["results"][selection["candidate_index"]]

    @Property("QVariantList", notify=changed)
    def equitySeries(self):
        if not self._root or self._root["report"]["selected_account"] is None:
            return []
        report = self._root["report"]
        return [execution_series(value["execution"]) for value in
                (report["selected_account"], self._reference(), report["benchmark"])]

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    def _windows(self):
        report = self._root["report"]
        return [(f"OUTER {index}", row["inner"]) for index, row in enumerate(report["outer_folds"])] + [("FINAL DEV", report["final_dev"])]

    def _refresh(self):
        self._columns, self._rows = (), ()
        self._page = 1
        if not self._root:
            self._set_page()
            return
        report, rows = self._root["report"], []
        account, reference = report["selected_account"], self._reference()
        view = self._view_index
        if view == 0:
            columns = ("inner_scope", "metric", "value", "unit")
            for side, value in (("SELECTED PROCEDURE", account), ("FIXED REFERENCE", reference), ("BENCHMARK", report["benchmark"])):
                if value is None:
                    continue
                for key, number in value["execution"]["metrics"].items():
                    unit = ("RATIO" if key in ("total_return", "observed_max_drawdown") else
                            "COUNT" if key == "trade_count" else "INITIAL_CASH_UNITS")
                    rows.append(dict(zip(columns, (side, key, risk_value(number, unit), unit))))
                for key, number in value.get("prediction_metrics", {}).items():
                    unit = ("RATIO" if key in ("mae", "rmse") else "COUNT" if key.endswith("count") else
                            "NUMBER" if key == "r2" else "—")
                    shown = (number or "—") if key == "unavailable_reason" else risk_value(number, unit)
                    rows.append(dict(zip(columns, (side, key, shown, unit))))
        elif view == 1:
            columns = ("inner_scope", "inner_member", "strategy", "alpha", "inner_mse", "inner_chosen",
                       "training_count", "inner_complete", "training_boundary", "inner_history_boundary")
            for scope, window in self._windows():
                for member in window["family_results"]:
                    rows.append(dict(zip(columns, (scope, member["candidate_index"], member["strategy"]["kind"], member["strategy"]["alpha"],
                        member["mse"], "YES" if member["candidate_index"] == window["selected_index"] else "NO",
                        len(window["training_keys"]), len(window["scored_targets"]), window["training_boundary"], window["history_boundary"]))))
        elif view == 2:
            columns = ("inner_scope", "inner_role", "value", "inner_label_end", "inner_target")
            for scope, window in self._windows():
                for key in ("history_days", "training_days", "validation_days", "history_training_keys", "history_purged_keys",
                            "training_keys", "purged_keys", "validation_keys"):
                    rows.extend(dict(zip(columns, (scope, key, value, "—", "—"))) for value in window[key])
                rows.extend(dict(zip(columns, (scope, "SCORED_TARGET", row["observation_key"], row["actual_label_end_time"], row["value"])))
                            for row in window["scored_targets"])
        elif view == 3:
            columns = ("inner_scope", "inner_member", "model_stage", "feature", "alpha", "training_count", "intercept", "coefficient",
                       "mean", "scale", "model_id", "training_boundary")
            models = [(scope, member["candidate_index"], member["model"]) for scope, window in self._windows() for member in window["family_results"]]
            models += [(f"OUTER {index} REFIT", "SELECTED", row["refit"]["model"]) for index, row in enumerate(report["outer_folds"]) if row["refit"]]
            for scope, member, model in models:
                common = {"inner_scope": scope, "inner_member": member, "alpha": model["alpha"], "training_count": len(model["training_keys"]),
                          "model_id": model["model_id"], "training_boundary": model["training_boundary"]}
                if "input_transform" in model:
                    rows.extend({**common, "model_stage": "INPUT_TRANSFORM", "feature": feature, "intercept": "—", "coefficient": "—",
                        "mean": model["input_transform"]["means"][index], "scale": model["input_transform"]["scales"][index]}
                        for index, feature in enumerate(model["input_features"]))
                    stage, model = "GENERATED_TERMS", model["ridge_model"]
                else:
                    stage = "LINEAR_FEATURES"
                rows.extend({**common, "model_stage": stage, "feature": feature, "intercept": model["intercept"], "coefficient": model["coefficients"][index],
                    "mean": model["means"][index], "scale": model["scales"][index]} for index, feature in enumerate(model["feature_fields"]))
        elif view == 4:
            columns = ("inner_scope", "inner_member", "trading_day", "decision_time", "score", "target", "inner_target", "inner_label_end")
            for scope, window in self._windows():
                targets = {row["observation_key"]: row for row in window["scored_targets"]}
                for member in window["family_results"]:
                    for row in member["predictions"]:
                        target = targets.get(row["observation_key"], {})
                        rows.append({**row, "inner_scope": scope, "inner_member": member["candidate_index"],
                                     "inner_target": target.get("value", "—"), "inner_label_end": target.get("actual_label_end_time", "—")})
        elif view == 5:
            columns = ("trading_day", "slot", "decision_time", "score", "target", "inner_reference_score", "inner_reference_target")
            original = {row["observation_key"]: row for row in reference["predictions"]}
            rows = [{**row, "inner_reference_score": original[row["observation_key"]]["score"],
                     "inner_reference_target": original[row["observation_key"]]["target"]} for row in account["predictions"]] if account else []
        elif view == 6:
            columns = ("entry_time", "exit_time", "exit_reason", "held_bars", "cash_before", "cash_after", "net_return")
            rows = account["execution"]["trades"] if account else []
        elif view == 7:
            columns = ("trading_day", "cash_open", "cash_close", "return", "trade_count")
            rows = account["execution"]["daily"] if account else []
        else:
            columns = ("timestamp", "phase", "action", "reason", "cash", "quantity", "equity", "drawdown")
            rows = account["execution"]["ledger"] if account else []
        self._columns, self._rows = columns, formatted_rows(rows, columns)
        self._set_page()

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 8:
            return False
        self._view_index = index
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def changePage(self, delta):
        page = self._page + delta
        if page < 1 or page > max(1, (len(self._rows) + 99) // 100):
            return False
        self._page = page
        self._set_page()
        self.changed.emit()
        return True

    def _apply(self, snapshot, *, path="", opened=False):
        self._content, self._root, self._path = snapshot.content, snapshot.as_dict(), path
        self._artifact_revision += 1
        self._proof, self._notice, self._study_error = "RECORDED" if opened else "COMPUTED", "", ""
        self._refresh()
        self.changed.emit()

    def _key(self, action):
        artifact = (self._root.get("experiment_id"), self._artifact_revision)
        return (self._revision, self._source_signature, self._data_locator) if action == "run" else (
            *artifact, self._revision, self._data_locator) if action == "replay" else artifact

    def _start(self, action, operation, apply):
        if self.busy or self._runtime.busy:
            return False
        key = self._key(action)
        self._pending = (action, key)
        self._study_error, self._notice = "", ""
        def completed(value):
            self._pending = None
            if key != self._key(action):
                self._notice = "STALE_INPUT"
                if action == "replay" and key[:2] == self._key(action)[:2]:
                    self._proof = "REPLAY_STALE_INPUT"
                self.changed.emit()
                return
            apply(value)
        accepted = self._submit("intraday_inner_" + action, operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        return accepted

    def _failed(self):
        pending, self._pending = self._pending, None
        if pending is None:
            return
        action, key = pending
        if key == self._key(action):
            self._study_error = self.error
            if action == "replay":
                self._proof = "REPLAY_FAILED"
        else:
            self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
            if action == "replay" and key[:2] == self._key(action)[:2]:
                self._proof = "REPLAY_STALE_INPUT"
            self.stateChanged.emit()
        self.changed.emit()

    @Slot(result=bool)
    def runSelected(self):
        try:
            from .quant_research import _experiment_file_path
            if not self.canRun:
                raise ValueError("Select a saved DEV linear or quadratic Ridge with 1–6 Features.")
            captured = self._research.selection_source()
            data = _experiment_file_path(self._data_locator) if self._data_locator.strip() else None
        except (OSError, TypeError, ValueError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)
        def operation(backend):
            from ..research.intraday_inner_selection import run_intraday_inner_selection
            return run_intraday_inner_selection(captured["path"], expected_experiment_id=captured["experiment_id"],
                cost_index=captured["cost_index"], candidate_index=captured["candidate_index"], expected_candidate_id=captured["candidate_id"],
                intraday_data_file=data, name="Intraday inner selection")
        return self._start("run", operation, self._apply)

    @Slot(str, result=bool)
    def openExperiment(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import load_strategy_experiment
            from ..research.intraday_inner_selection import INTRADAY_INNER_SELECTION_VERSION
            snapshot = load_strategy_experiment(path)
            if snapshot.as_dict()["artifact_schema_version"] != INTRADAY_INNER_SELECTION_VERSION:
                raise ValueError("Open an intraday inner-selection experiment.")
            return snapshot
        return self._start("open", operation, lambda snapshot: self._apply(snapshot, path=str(path), opened=True))

    @Slot(str, result=bool)
    def saveExperiment(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
            if not self._content:
                raise ValueError("Run or open an inner selection before saving.")
            content = self._content
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, write_strategy_experiment
            return write_strategy_experiment(StrategyExperiment(content), path=path)
        def saved(result):
            self._path = str(result.path)
            self.changed.emit()
        return self._start("save", operation, saved)

    @Slot(result=bool)
    def replayExperiment(self):
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            data = _experiment_file_path(self._data_locator) if self._data_locator.strip() else None
            if not self._content:
                raise ValueError("Run or open an inner selection before replay.")
            content = self._content
        except (OSError, TypeError, ValueError) as exc:
            if self._content:
                self._proof = "REPLAY_FAILED"
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)
        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, replay_strategy_experiment
            return replay_strategy_experiment(StrategyExperiment(content), intraday_data_file=data)
        def verified(result):
            self._proof = "REPLAY_MATCH"
            self.changed.emit()
        self._proof = "REPLAY_PENDING"
        self.changed.emit()
        return self._start("replay", operation, verified)
