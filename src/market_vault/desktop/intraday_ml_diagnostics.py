"""Captured-source native views of outer DEV ML prediction diagnostics."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .intraday_research import risk_value
from .table_model import QtTableModel


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


class IntradayMLDiagnosticsController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._source_path, self._opened_path, self._data_locator = "", "", ""
        self._content, self._root, self._report, self._completed_source = b"", {}, {}, {}
        self._source_kind, self._study_error, self._notice = "", "", ""
        self._revision, self._cost_index, self._candidate_index = 0, 0, 0
        self._view_index, self._scope_index, self._page = 0, 0, 1
        self._completed_key, self._pending = None, None
        self._columns, self._rows, self._evidence_rows = (), (), []
        self._model = QtTableModel(parent=self)
        self._set_page()
        self.operationFailed.connect(self._failed)

    def _key(self):
        return (self._revision, self._source_path, self._root.get("experiment_id"),
                self._cost_index, self._candidate_index, self._data_locator)

    def _input_changed(self):
        self._revision += 1
        self._study_error, self._notice = "", ""
        self.changed.emit()

    @Property(str, notify=changed)
    def sourcePath(self):
        return self._source_path

    @Slot(str)
    def setSourcePath(self, value):
        if value != self._source_path:
            self._source_path = value
            self._input_changed()

    @Property(str, notify=changed)
    def dataLocator(self):
        return self._data_locator

    @Slot(str)
    def setDataLocator(self, value):
        if value != self._data_locator:
            self._data_locator = value
            self._input_changed()

    @Property(bool, notify=changed)
    def ordinarySource(self):
        return self._source_kind == "ORDINARY"

    @Property(int, notify=changed)
    def costIndex(self):
        return self._cost_index

    @Property(int, notify=changed)
    def candidateIndex(self):
        return self._candidate_index

    @Property("QStringList", notify=changed)
    def costNames(self):
        if not self.ordinarySource:
            return []
        return [f'{index} · {group["execution_policy"]["commission_bps"]}/{group["execution_policy"]["slippage_bps"]} bp'
                for index, group in enumerate(self._root["report"]["groups"])]

    @Property("QStringList", notify=changed)
    def candidateNames(self):
        if not self.ordinarySource:
            return []
        return [f'{index} · {row["strategy"]["name"]} · {row["strategy"]["kind"]}'
                for index, row in enumerate(self._root["report"]["groups"][self._cost_index]["results"])]

    @Slot(int, result=bool)
    def selectCost(self, index):
        if type(index) is not int or not 0 <= index < len(self.costNames):
            return False
        if index != self._cost_index:
            self._cost_index, self._candidate_index = index, 0
            self._input_changed()
        return True

    @Slot(int, result=bool)
    def selectCandidate(self, index):
        if type(index) is not int or not 0 <= index < len(self.candidateNames):
            return False
        if index != self._candidate_index:
            self._candidate_index = index
            self._input_changed()
        return True

    @Property(bool, notify=changed)
    def canRun(self):
        if not self._content:
            return False
        try:
            from .quant_research import _experiment_file_path
            if str(_experiment_file_path(self._source_path)) != self._opened_path:
                return False
        except (TypeError, ValueError, OSError):
            return False
        if self.ordinarySource:
            candidate = self._root["report"]["groups"][self._cost_index]["results"][self._candidate_index]
            return candidate["strategy"]["kind"] in ("RIDGE", "QUADRATIC_RIDGE")
        return True

    @Property("QVariantMap", notify=changed)
    def draftSource(self):
        if not self._root:
            return {}
        return {"path": self._opened_path, "experiment_id": self._root["experiment_id"],
                "source_kind": self._source_kind, "name": self._root["name"],
                "cost_index": self._cost_index, "candidate_index": self._candidate_index}

    @Property(bool, notify=changed)
    def resultLoaded(self):
        return bool(self._report)

    @Property(bool, notify=changed)
    def draftChanged(self):
        return bool(self._report and self._completed_key != self._key())

    @Property(str, notify=changed)
    def studyError(self):
        return self._study_error

    @Property(str, notify=changed)
    def notice(self):
        return self._notice

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        if not self._report:
            return {}
        return {"status": self._report["status"], "source_kind": self._report["source_kind"],
                "sample": deepcopy(self._report.get("sample", {})),
                "source_path": self._completed_source["source_path"],
                "unavailable_reasons": deepcopy(self._report.get("unavailable_reasons", []))}

    @Property(str, notify=changed)
    def completedDetails(self):
        if not self._report:
            return ""
        return _json({**deepcopy(self._completed_source), **{key: deepcopy(self._report.get(key)) for key in
            ("version", "status", "experiment_id", "data_id", "source_kind", "source_schema_version",
             "source_selection", "selection_id", "prediction_quality_id", "source_locator", "method",
             "evidence", "context", "sample", "ordinary_source_id", "algorithm_versions", "source_evaluation_scope",
             "unavailable_reason", "unavailable_reasons")}})

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property(int, notify=changed)
    def scopeIndex(self):
        return self._scope_index

    @Property(int, notify=changed)
    def foldCount(self):
        return len(self._report.get("folds", []))

    def _scope(self):
        return self._report if self._scope_index == 0 else self._report["folds"][self._scope_index - 1]

    @Property(str, notify=changed)
    def currentPageEvidence(self):
        if not self._report:
            return ""
        start = (self._page - 1) * 100
        rows = self._evidence_rows[start:start + 100]
        result = {"prediction_quality_id": self._report["prediction_quality_id"], "source": deepcopy(self._completed_source),
                  "view_index": self._view_index, "scope_index": self._scope_index, "page": self._page, "rows": rows}
        if self._scope_index:
            result["complete_fold_evidence"] = deepcopy(self._scope())
        elif self._view_index in (2, 4):
            indices = {row["fold_index"] for row in rows}
            result["complete_fold_evidence"] = [deepcopy(fold) for fold in self._report.get("folds", [])
                                                  if fold["fold_index"] in indices]
        return _json(result)

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    @staticmethod
    def _metric_rows(forecasts):
        return [{"forecast": forecast["forecast"], "metric": name, "value": risk_value(metric["value"], metric["unit"]),
                 "unit": metric["unit"], "unavailable_reason": metric["unavailable_reason"] or "—",
                 "complete_metric": deepcopy(metric)}
                for forecast in forecasts for name, metric in forecast["metrics"].items()]

    def _refresh(self):
        self._columns, self._rows, self._evidence_rows, self._page = (), (), [], 1
        if not self._report:
            self._set_page()
            return
        scope, rows = self._scope(), []
        if self._view_index == 0:
            columns = ("forecast", "metric", "value", "unit", "unavailable_reason")
            rows = self._metric_rows(scope.get("forecasts", []))
        elif self._view_index == 1:
            columns = ("ml_bin", "prediction_count", "complete_target_count", "incomplete_target_count",
                       "metric", "value", "unit", "unavailable_reason")
            for bucket in scope.get("bins", []):
                common = {"ml_bin": "BIN_" + str(bucket["bin_index"]), **bucket["sample"]}
                metrics = dict(bucket["metrics"])
                ready = bucket.get("ready_mean_prediction")
                metrics["ready_mean_prediction"] = (ready if isinstance(ready, dict) else
                    {"value": ready, "unit": "RATIO", "unavailable_reason": "NO_READY_PREDICTIONS" if ready is None else None})
                for name, metric in metrics.items():
                    rows.append({**common, "metric": name, "value": risk_value(metric["value"], metric["unit"]),
                                 "unit": metric["unit"], "unavailable_reason": metric["unavailable_reason"] or "—",
                                 "complete_bin": deepcopy(bucket)})
        elif self._view_index == 2:
            columns = ("fold_index", "strategy_kind", "alpha", "threshold", "model_id", "training_boundary",
                       "training_count", "prediction_count", "complete_target_count", "training_target_mean")
            folds = self._report.get("folds", []) if self._scope_index == 0 else [scope]
            for fold in folds:
                rows.append({"fold_index": fold["fold_index"], "strategy_kind": fold["strategy"]["kind"],
                    "alpha": fold["strategy"]["alpha"], "threshold": risk_value(fold["strategy"]["threshold"], "RATIO"),
                    "model_id": fold["model_id"], "training_boundary": fold.get("training_boundary", fold.get("boundary")),
                    "training_count": len(fold["training_keys"]), **fold["sample"],
                    "training_target_mean": risk_value(fold["training_target_mean"], "RATIO")})
        elif self._view_index == 3:
            columns = ("observation_key", "trading_day", "slot", "target_status", "ml_selected_prediction",
                       "ml_reference_prediction", "target_value", "decision", "reference_decision", "ml_bin", "model_id")
            predictions = self._report.get("predictions", [])
            if self._scope_index:
                predictions = [row for row in predictions if row["fold_id"] == scope["fold_id"]]
            for row in predictions:
                rows.append({**deepcopy(row), "ml_selected_prediction": risk_value(row["scores"]["SELECTED"], "RATIO"),
                    "ml_reference_prediction": risk_value(row["scores"]["FIXED_REFERENCE"], "RATIO"),
                    "target_value": risk_value(row["target_value"], "RATIO"), "ml_bin": "BIN_" + str(row["bin_index"]),
                    "complete_prediction": deepcopy(row)})
        else:
            columns = ("fold_index", "ml_evidence_role", "value")
            folds = self._report.get("folds", []) if self._scope_index == 0 else [scope]
            for fold in folds:
                for role in ("training_days", "training_keys", "purged_keys", "validation_days", "validation_keys"):
                    rows.extend({"fold_index": fold["fold_index"], "ml_evidence_role": role, "value": value}
                                for value in fold.get(role, []))
                for role in ("model", "reference_model"):
                    rows.append({"fold_index": fold["fold_index"], "ml_evidence_role": role,
                                 "value": fold[role]["model_id"], "complete_model": deepcopy(fold[role])})
        self._columns, self._evidence_rows = columns, rows
        self._rows = tuple(tuple(str(row.get(column, "—")) for column in columns) for row in rows)
        self._set_page()

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 4:
            return False
        self._view_index = index
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectScope(self, index):
        if type(index) is not int or not 0 <= index <= self.foldCount:
            return False
        self._scope_index = index
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

    def _start(self, action, operation, apply):
        key = self._key()
        self._pending = action, key
        self._study_error, self._notice = "", ""

        def completed(value):
            self._pending = None
            if key != self._key():
                self._notice = "STALE_INPUT"
            else:
                apply(value)
            self.changed.emit()

        accepted = self._submit("intraday_ml_diagnostics_" + action, operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        self.changed.emit()
        return accepted

    def _failed(self):
        pending, self._pending = self._pending, None
        if pending is not None:
            if pending[1] == self._key():
                self._study_error = self.error
            else:
                self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
                self.stateChanged.emit()
            self.changed.emit()

    @Slot(str, result=bool)
    def openSource(self, raw_path):
        if self.busy or self._runtime.busy:
            return False
        self.setSourcePath(raw_path)
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (TypeError, ValueError, OSError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)

        def operation(backend):
            from ..research.intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
            from ..research.intraday_inner_selection import INTRADAY_INNER_SELECTION_VERSION
            from ..research.intraday_threshold_selection import INTRADAY_THRESHOLD_SELECTION_VERSION
            from ..research.strategy_experiment import load_strategy_experiment
            snapshot = load_strategy_experiment(path)
            root = snapshot.as_dict()
            schema = root["artifact_schema_version"]
            if schema in INTRADAY_EXPERIMENT_VERSIONS and root["evaluation_mode"] in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS"):
                if not any(row["strategy"]["kind"] in ("RIDGE", "QUADRATIC_RIDGE")
                           for group in root["report"]["groups"] for row in group["results"]):
                    raise ValueError("The saved DEV source contains no linear or quadratic Ridge candidate.")
                kind = "ORDINARY"
            elif schema == INTRADAY_INNER_SELECTION_VERSION:
                kind = "INNER_MODEL_SELECTION"
            elif schema == INTRADAY_THRESHOLD_SELECTION_VERSION:
                kind = "ECONOMIC_THRESHOLD_SELECTION"
            else:
                raise ValueError("Open an ordinary learned DEV experiment, an inner ML selection study or an economic threshold study.")
            return snapshot, root, kind

        def opened(value):
            snapshot, self._root, self._source_kind = value
            self._content, self._opened_path = snapshot.content, str(path)
            self._cost_index, self._candidate_index = 0, 0
            if self.ordinarySource:
                self._cost_index, self._candidate_index = next((cost, candidate)
                    for cost, group in enumerate(self._root["report"]["groups"])
                    for candidate, row in enumerate(group["results"])
                    if row["strategy"]["kind"] in ("RIDGE", "QUADRATIC_RIDGE"))

        return self._start("open", operation, opened)

    @Slot(result=bool)
    def runSelected(self):
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            if not self.canRun:
                raise ValueError("Open the selected saved source and choose a learned DEV candidate before analyzing.")
            locator = _experiment_file_path(self._data_locator) if self._data_locator.strip() else None
            content, cost, candidate = self._content, self._cost_index, self._candidate_index
            captured = {"source_path": self._opened_path, "source_experiment_id": self._root["experiment_id"],
                        "requested_cost_index": cost, "requested_candidate_index": candidate,
                        "requested_data_locator": self._data_locator}
        except (TypeError, ValueError, OSError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)

        def operation(backend):
            from ..research.intraday_ml_diagnostics import analyze_intraday_ml_prediction_quality
            from ..research.strategy_experiment import StrategyExperiment
            return analyze_intraday_ml_prediction_quality(StrategyExperiment(content), cost_index=cost,
                candidate_index=candidate, intraday_data_file=locator)

        def analyzed(report):
            self._report, self._completed_source, self._completed_key = report, captured, self._key()
            self._scope_index = 0
            self._refresh()

        return self._start("analyze", operation, analyzed)
