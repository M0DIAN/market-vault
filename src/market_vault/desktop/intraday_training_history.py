"""Native, captured-input presentation of fixed training-history sensitivity."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .intraday_research import execution_series, formatted_rows, risk_value
from .table_model import QtTableModel


class IntradayTrainingHistoryController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, research, parent):
        super().__init__(runtime, parent=parent)
        self._research = research
        self._report, self._completed_source = {}, {}
        self._data_locator, self._study_error, self._notice = "", "", ""
        self._revision, self._variant_index, self._view_index, self._page = 0, 0, 0, 1
        self._source_signature, self._completed_signature, self._pending = None, None, None
        self._columns, self._rows = (), ()
        self._evidence_rows = []
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
        return bool(self._source_signature
            and self._research._root.get("artifact_schema_version") in INTRADAY_EXPERIMENT_VERSIONS
            and self._research._selected()[1]["strategy"]["kind"] in ("RIDGE", "QUADRATIC_RIDGE"))

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
        return bool(self._report)

    @Property(str, notify=changed)
    def studyError(self):
        return self._study_error

    @Property(str, notify=changed)
    def notice(self):
        return self._notice

    @Property(bool, notify=changed)
    def draftChanged(self):
        return bool(self._report and self._completed_signature != (self._source_signature, self._data_locator))

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        if not self._report:
            return {}
        report, sample = self._report, self._report["sample"]
        return {"status": report["status"], "strategy": deepcopy(report["strategy"]),
                "fold_count": sample["fold_count"], "day_count": sample["sample_count"],
                "prediction_count": sample["prediction_count"], "complete_target_count": sample["complete_target_count"]}

    @Property("QVariantMap", notify=changed)
    def completedDetails(self):
        if not self._report:
            return {}
        report = self._report
        return {**deepcopy(self._completed_source), "training_history_id": report["training_history_id"],
            "features": ", ".join(report["context"]["feature_fields"]),
            "policy": ", ".join(f"{key}={value}" for key, value in report["execution_policy"].items()),
            "first_day": report["sample"]["first_day"], "last_day": report["sample"]["last_day"],
            "gap_days": ", ".join(report["sample"]["gap_days"])}

    @Property("QVariantMap", notify=changed)
    def returnBasis(self):
        return deepcopy(self._report.get("return_basis", {}))

    def _selected_variant(self):
        if self._variant_index < 3:
            return self._report["variants"][self._variant_index]
        return {"variant": "BENCHMARK", "status": "AVAILABLE", "unavailable_reasons": [],
                "folds": [], "account": self._report["benchmark"]}

    @Property(str, notify=changed)
    def currentPageEvidence(self):
        if not self._report:
            return ""
        start = (self._page - 1) * 100
        rows = self._evidence_rows[start:start + 100]
        evidence = {"variant": self._selected_variant()["variant"], "page": self._page, "rows": rows}
        if self._view_index == 3:
            indices = {row["fold_index"] for row in rows}
            evidence["complete_fold_models"] = [fold for fold in self._selected_variant()["folds"]
                                                 if fold["fold_index"] in indices]
        return json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)

    @Property(int, notify=changed)
    def variantIndex(self):
        return self._variant_index

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property("QVariantMap", notify=changed)
    def variantSummary(self):
        if not self._report:
            return {}
        variant = self._selected_variant()
        return {key: deepcopy(variant[key]) for key in ("variant", "status", "unavailable_reasons")}

    @Property("QVariantList", notify=changed)
    def equitySeries(self):
        if not self._report:
            return []
        values = [row["account"] for row in self._report["variants"] if row["account"] is not None]
        return [execution_series(value["execution"]) for value in (*values, self._report["benchmark"])]

    @Property("QStringList", notify=changed)
    def equityNames(self):
        if not self._report:
            return []
        return [row["variant"] for row in self._report["variants"] if row["account"] is not None] + ["BENCHMARK"]

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    def _refresh(self):
        self._columns, self._rows, self._page, self._evidence_rows = (), (), 1, []
        if not self._report:
            self._set_page()
            return
        variant = self._selected_variant()
        account, rows = variant["account"], []
        if self._view_index == 0:
            columns = ("history_variant", "metric", "value", "unit", "unavailable_reason")
            for record in (*self._report["variants"], {"variant": "BENCHMARK", "account": self._report["benchmark"]}):
                side, value = record["variant"], record["account"]
                if value is None:
                    for reason in record["unavailable_reasons"]:
                        rows.append(dict(zip(columns, (side, f"FOLD {reason['fold_index']}", "—", "—", reason["reason"]))))
                    continue
                for key, number in value["execution"]["metrics"].items():
                    unit = ("RATIO" if key in ("total_return", "observed_max_drawdown") else
                            "COUNT" if key == "trade_count" else "INITIAL_CASH_UNITS")
                    rows.append(dict(zip(columns, (side, key, risk_value(number, unit), unit, "—"))))
                for key in ("mean_daily_return", "annualized_volatility", "sharpe_ratio"):
                    number = value["risk"][key]
                    unit = "NUMBER" if key == "sharpe_ratio" else "RATIO"
                    rows.append(dict(zip(columns, (side, key, risk_value(number, unit), unit,
                                                   value["risk"]["unavailable_reason"] if number is None else "—"))))
                for key, metric in value.get("prediction_quality", {}).items():
                    rows.append(dict(zip(columns, (side, key, risk_value(metric["value"], metric["unit"]),
                                                   metric["unit"], metric["unavailable_reason"] or "—"))))
                for key, metric in (record.get("prediction_error_changes") or {}).items():
                    rows.append(dict(zip(columns, (side, "delta_" + key, risk_value(metric["value"], metric["unit"]),
                                                   "PERCENTAGE_POINTS" if metric["unit"] == "RATIO" else metric["unit"],
                                                   metric["unavailable_reason"] or "—"))))
        elif self._view_index == 1:
            columns = ("fold_index", "training_count", "history_days", "training_boundary", "validation_days",
                       "validation_complete", "validation_mse", "unavailable_reason")
            for fold in variant["folds"]:
                metric = (fold["prediction_quality"] or {}).get("mse", {})
                rows.append(dict(zip(columns, (fold["fold_index"], len(fold["training_keys"]), len(fold["training_days"]),
                    fold["training_boundary"], ", ".join(fold["validation_days"]),
                    (fold["prediction_metrics"] or {}).get("complete_target_count", "—"),
                    risk_value(metric.get("value"), "SQUARED_RATIO"), fold["unavailable_reason"] or metric.get("unavailable_reason") or "—"))))
        elif self._view_index == 2:
            columns = ("fold_index", "history_role", "value")
            for fold in variant["folds"]:
                for key in ("training_days", "training_keys", "purged_keys", "validation_days", "validation_keys"):
                    rows.extend(dict(zip(columns, (fold["fold_index"], key, value))) for value in fold[key])
        elif self._view_index == 3:
            columns = ("fold_index", "model_stage", "feature", "alpha", "training_count", "intercept", "coefficient",
                       "mean", "scale", "model_id", "training_boundary")
            for fold in variant["folds"]:
                model = fold["model"]
                if model is None:
                    continue
                common = {"fold_index": fold["fold_index"], "alpha": model["alpha"], "training_count": len(model["training_keys"]),
                          "model_id": model["model_id"], "training_boundary": model["training_boundary"]}
                if "input_transform" in model:
                    rows.extend({**common, "model_stage": "INPUT_TRANSFORM", "feature": feature, "intercept": "—", "coefficient": "—",
                        "mean": model["input_transform"]["means"][index], "scale": model["input_transform"]["scales"][index]}
                        for index, feature in enumerate(model["input_features"]))
                    stage, model = "GENERATED_TERMS", model["ridge_model"]
                else:
                    stage = "LINEAR_FEATURES"
                rows.extend({**common, "model_stage": stage, "feature": feature, "intercept": model["intercept"],
                    "coefficient": model["coefficients"][index], "mean": model["means"][index], "scale": model["scales"][index]}
                    for index, feature in enumerate(model["feature_fields"]))
        elif self._view_index == 4:
            columns = ("observation_key", "trading_day", "slot", "decision_time", "score", "target")
            rows = account.get("predictions", []) if account else []
        elif self._view_index == 5:
            columns = ("entry_time", "exit_time", "exit_reason", "held_bars", "cash_before", "cash_after", "net_return")
            rows = account["execution"]["trades"] if account else []
        elif self._view_index == 6:
            columns = ("trading_day", "cash_open", "cash_close", "return", "trade_count")
            rows = account["execution"]["daily"] if account else []
        elif self._view_index == 7:
            columns = ("timestamp", "phase", "action", "reason", "cash", "quantity", "equity", "drawdown")
            rows = account["execution"]["ledger"] if account else []
        elif self._view_index == 8:
            columns = ("timestamp", "side", "reason", "quantity", "fill_price", "commission", "slippage")
            rows = account["execution"]["transactions"] if account else []
        else:
            columns = ("fold_index", "validation_days", "trade_count", "cash_contribution", "fold_id")
            rows = (self._report["benchmark_fold_contributions"] if self._variant_index == 3
                    else account["fold_contributions"] if account else [])
        self._evidence_rows = rows
        self._columns, self._rows = columns, formatted_rows(rows, columns)
        self._set_page()

    @Slot(int, result=bool)
    def selectVariant(self, index):
        if type(index) is not int or not 0 <= index < 4:
            return False
        self._variant_index = index
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 9:
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

    def _key(self):
        return self._revision, self._source_signature, self._data_locator

    @Slot(result=bool)
    def runSelected(self):
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            if not self.canRun:
                raise ValueError("Open or save an ordinary DEV linear or quadratic Ridge before analyzing training history.")
            captured = self._research.selection_source()
            raw_locator = self._data_locator
            locator = _experiment_file_path(raw_locator) if raw_locator.strip() else None
        except (OSError, TypeError, ValueError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)
        key = self._key()
        self._pending = key
        self._study_error, self._notice = "", ""

        def operation(backend):
            from ..research.intraday_training_history import analyze_intraday_training_history
            from ..research.strategy_experiment import StrategyExperiment
            return analyze_intraday_training_history(StrategyExperiment(captured["content"]),
                cost_index=captured["cost_index"], candidate_index=captured["candidate_index"], intraday_data_file=locator)

        def completed(report):
            self._pending = None
            if key != self._key():
                self._notice = "STALE_INPUT"
            else:
                self._report = report
                self._completed_signature = self._source_signature, raw_locator
                self._completed_source = {name: captured[name] for name in
                    ("path", "experiment_id", "candidate_id", "cost_index", "candidate_index")}
                self._completed_source["data_path"] = report["source_locator"]["used"]
                self._refresh()
            self.changed.emit()

        accepted = self._submit("intraday_training_history", operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        self.changed.emit()
        return accepted

    def _failed(self):
        key, self._pending = self._pending, None
        if key is not None:
            if key == self._key():
                self._study_error = self.error
            else:
                self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
                self.stateChanged.emit()
            self.changed.emit()
