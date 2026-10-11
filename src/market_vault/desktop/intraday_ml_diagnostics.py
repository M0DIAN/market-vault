"""Captured-source native ML prediction, inner-objective and return evidence."""

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
        self._mode_index = 0
        self._view_index, self._scope_index, self._page = 0, 0, 1
        self._evidence_account_index, self._evidence_section_index = 0, 0
        self._completed_key, self._pending = None, None
        self._columns, self._rows, self._evidence_rows = (), (), []
        self._model = QtTableModel(parent=self)
        self._set_page()
        self.operationFailed.connect(self._failed)

    def _key(self):
        return (self._revision, self._source_path, self._root.get("experiment_id"),
                self._cost_index, self._candidate_index, self._data_locator, self._mode_index)

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

    @Property(int, notify=changed)
    def modeIndex(self):
        return self._mode_index

    @Slot(int, result=bool)
    def selectMode(self, index):
        if type(index) is not int or index not in (0, 1, 2):
            return False
        if index != self._mode_index:
            self._mode_index = index
            self._input_changed()
        return True

    @Property(bool, notify=changed)
    def sensitivityMode(self):
        return self._mode_index == 1

    @Property(bool, notify=changed)
    def uncertaintyMode(self):
        return self._mode_index == 2

    @Property(bool, notify=changed)
    def recordedOnlyMode(self):
        return self._mode_index in (1, 2)

    @Property(bool, notify=changed)
    def completedSensitivity(self):
        # Completed views use the actual returned report, never the draft mode.
        return "sensitivity_id" in self._report

    @Property(bool, notify=changed)
    def completedUncertainty(self):
        return "uncertainty_id" in self._report

    @Property(str, notify=changed)
    def draftNotice(self):
        if self.recordedOnlyMode and self.ordinarySource:
            return "uncertainty_source_required" if self.uncertaintyMode else "sensitivity_source_required"
        return ""

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
        if self.recordedOnlyMode:
            return self._source_kind in ("INNER_MODEL_SELECTION", "ECONOMIC_THRESHOLD_SELECTION", "JOINT_ECONOMIC_SELECTION")
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
                "diagnostic_kind": "uncertainty_mode" if self.completedUncertainty else
                                   "sensitivity_mode" if self.completedSensitivity else "quality_mode",
                "sample": deepcopy(self._report.get("sample", {})),
                "sampling": deepcopy(self._report.get("sampling")),
                "basis_matches": self._report["basis"]["matches"] if self._report.get("basis") is not None else None,
                "source_path": self._completed_source["source_path"],
                "unavailable_reasons": deepcopy(self._report.get("unavailable_reasons", []))}

    @Property(str, notify=changed)
    def completedDetails(self):
        if not self._report:
            return ""
        return _json({**deepcopy(self._completed_source), **{key: deepcopy(self._report[key]) for key in
            ("version", "status", "experiment_id", "data_id", "source_kind", "source_schema_version",
             "source_selection", "selection_id", "prediction_quality_id", "sensitivity_id", "uncertainty_id", "source_locator", "method",
             "evidence", "context", "sample", "ordinary_source_id", "algorithm_versions", "source_evaluation_scope",
             "evaluation_scope", "parameters", "sampling", "basis", "unavailable_reason", "unavailable_reasons") if key in self._report}})

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property(int, notify=changed)
    def scopeIndex(self):
        return self._scope_index

    @Property(int, notify=changed)
    def foldCount(self):
        return len(self._report.get("folds", []))

    @Property("QVariantList", notify=changed)
    def scopeOptions(self):
        if self.completedUncertainty:
            return [{"kind": "all_outer_returns", "fold_index": None}]
        if self.completedSensitivity:
            return [{"kind": "all_inner_windows", "fold_index": None}] + [
                {"kind": window["scope"], "fold_index": window["fold_index"], "window_index": window["window_index"]}
                for window in self._report["windows"]]
        return [{"kind": "pooled", "fold_index": None}] + [
            {"kind": "fold", "fold_index": fold["fold_index"]} for fold in self._report.get("folds", [])]

    @Property("QStringList", notify=changed)
    def viewOptions(self):
        if self.completedUncertainty:
            return ["return_intervals", "daily_returns", "return_basis", "outer_accounts"]
        if self.completedSensitivity:
            return ["window_overview", "original_objectives", "omission_results", "omission_objectives",
                    "selection_counts", "fixed_evidence"]
        return ["metrics", "bins", "folds", "predictions", "models_keys"]

    @Property(int, notify=changed)
    def evidenceAccountIndex(self):
        return self._evidence_account_index

    @Property("QStringList", notify=changed)
    def evidenceAccountOptions(self):
        return ["all_accounts", *self._report.get("accounts", {})]

    def _evidence_accounts(self):
        accounts = self._report.get("accounts", {})
        if self._evidence_account_index:
            name = self.evidenceAccountOptions[self._evidence_account_index]
            return {name: accounts[name]}
        return accounts

    @Property(int, notify=changed)
    def evidenceSectionIndex(self):
        return self._evidence_section_index

    @Property("QStringList", notify=changed)
    def evidenceSectionOptions(self):
        sections = []
        for account in self._evidence_accounts().values():
            for key, value in account.items():
                if key == "execution":
                    sections.extend("execution." + child for child in value)
                else:
                    sections.append(key)
        return ["all_fields", *dict.fromkeys(sections)]

    @Slot(int, result=bool)
    def selectEvidenceAccount(self, index):
        if type(index) is not int or not 0 <= index < len(self.evidenceAccountOptions):
            return False
        self._evidence_account_index, self._evidence_section_index = index, 0
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectEvidenceSection(self, index):
        if type(index) is not int or not 0 <= index < len(self.evidenceSectionOptions):
            return False
        self._evidence_section_index = index
        self._refresh()
        self.changed.emit()
        return True

    def _scope(self):
        if self._scope_index == 0:
            return self._report
        return self._report["windows" if self.completedSensitivity else "folds"][self._scope_index - 1]

    @Property(str, notify=changed)
    def currentPageEvidence(self):
        if not self._report:
            return ""
        start = (self._page - 1) * 100
        rows = self._evidence_rows[start:start + 100]
        if self.completedUncertainty:
            result = {"uncertainty_id": self._report["uncertainty_id"], "source": deepcopy(self._completed_source),
                      "view": self.viewOptions[self._view_index], "scope": self.scopeOptions[0], "page": self._page, "rows": rows}
            if self._view_index == 3:
                result.update(account=self.evidenceAccountOptions[self._evidence_account_index],
                              section=self.evidenceSectionOptions[self._evidence_section_index])
            return _json(result)
        if self.completedSensitivity:
            indices = {row["window_index"] for row in rows}
            return _json({"sensitivity_id": self._report["sensitivity_id"], "source": deepcopy(self._completed_source),
                "view": self.viewOptions[self._view_index], "scope": self.scopeOptions[self._scope_index],
                "page": self._page, "rows": rows,
                "complete_window_evidence": deepcopy(self._scope()) if self._scope_index else [
                    deepcopy(window) for window in self._report["windows"] if window["window_index"] in indices]})
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
        if self.completedUncertainty:
            columns, rows = self._uncertainty_rows()
        elif self.completedSensitivity:
            columns, rows = self._sensitivity_rows()
        elif self._view_index == 0:
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
        self._rows = tuple(tuple("—" if row.get(column) is None else str(row[column]) for column in columns) for row in rows)
        self._set_page()

    @staticmethod
    def _return_value(value, series):
        displayed = risk_value(value, "RATIO")
        return displayed.removesuffix("%") if series.startswith("procedure_minus_") else displayed

    def _uncertainty_rows(self):
        if self._view_index == 0:
            columns = ("return_series", "return_mean", "return_lower_95", "return_upper_95", "unit", "sample_count",
                       "mean_unavailable_reason", "interval_unavailable_reason", "detail")
            rows = [{"return_series": row["series"], "sample_count": row["sample_count"],
                     **{"return_" + field + ("_95" if field != "mean" else ""): self._return_value(row[field], row["series"])
                        for field in ("mean", "lower", "upper")},
                     "unit": "PERCENTAGE_POINTS" if row["series"].startswith("procedure_minus_") else "RATIO",
                     "mean_unavailable_reason": row["mean_unavailable_reason"] or "—",
                     "interval_unavailable_reason": row["interval_unavailable_reason"] or "—",
                     "detail": row["detail"] or "—", "complete_record": deepcopy(row)} for row in self._report["statistics"]]
        elif self._view_index == 1:
            series = self._report["method"]["series_order"]
            columns = ("trading_day", "fold_id", *series)
            rows = [{"trading_day": row["trading_day"], "fold_id": row["fold_id"],
                     **{name: self._return_value(row["values"][name], name) for name in series},
                     "complete_record": deepcopy(row)} for row in self._report["daily"]]
        elif self._view_index == 2:
            columns = ("basis_check", "basis_matches", "expected", "recorded")
            rows = [{"basis_check": "basis_" + row["key"], "basis_matches": "YES" if row["matches"] else "NO",
                     "expected": json.dumps(row["expected"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                     "recorded": json.dumps(row["recorded"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                     "complete_record": deepcopy(row)} for row in (self._report.get("basis") or {}).get("checks", [])]
        else:
            columns = ("account_role", "record_path", "record_kind", "record_value")
            rows = self._account_evidence_rows()
        return columns, rows

    def _account_evidence_rows(self):
        rows = []
        section = self.evidenceSectionOptions[self._evidence_section_index]

        def append(name, path, value):
            kind = "OBJECT" if isinstance(value, dict) else "ARRAY" if isinstance(value, list) else "VALUE"
            rows.append({"account_role": name, "record_path": path, "record_kind": kind,
                         "record_value": len(value) if kind != "VALUE" else value, "complete_record": deepcopy(value)})

        def walk(name, path, value):
            if isinstance(value, dict) and value:
                for key, child in value.items():
                    walk(name, path + "/" + key.replace("~", "~0").replace("/", "~1"), child)
            elif isinstance(value, list) and value:
                for index, child in enumerate(value):
                    append(name, path + "/" + str(index), child)
            else:
                append(name, path, value)

        for name, account in self._evidence_accounts().items():
            if section == "all_fields":
                walk(name, "/accounts/" + name, account)
            elif section.startswith("execution."):
                field = section.removeprefix("execution.")
                if field in account.get("execution", {}):
                    walk(name, "/accounts/" + name + "/execution/" + field, account["execution"][field])
            elif section in account:
                walk(name, "/accounts/" + name + "/" + section, account[section])
        return rows

    @staticmethod
    def _choice_fields(choice):
        margin = choice["margin"]
        return {"status": choice["status"], "selected_index": choice["selected_index"],
                "runner_up_index": choice["runner_up_index"], "margin": risk_value(margin["value"], margin["unit"]),
                "unit": margin["unit"], "unavailable_reason": choice["unavailable_reason"] or margin["unavailable_reason"] or "—"}

    @staticmethod
    def _recipe_fields(recipe):
        return {"strategy_kind": recipe["kind"], "alpha": recipe["alpha"],
                "threshold": risk_value(recipe["threshold"], "RATIO")} if recipe else {}

    def _sensitivity_rows(self):
        windows = self._report["windows"] if self._scope_index == 0 else [self._scope()]
        identity = ("window_index", "ml_window_scope")
        joint = self._report["source_kind"] == "JOINT_ECONOMIC_SELECTION"
        chosen_columns = ("strategy_kind", "alpha", "threshold") if joint else ()
        if self._view_index == 0:
            columns = (*identity, "status", "selected_index", *chosen_columns, "objective_value", "unit", "margin",
                       "available_omission_count", "changed_choice_count", "unavailable_reason")
        elif self._view_index in (1, 3):
            columns = (*identity, *(("omitted_day",) if self._view_index == 3 else ()), "candidate_index",
                       "strategy_kind", "alpha", "threshold", "objective_value", "unit", "ml_chosen", "unavailable_reason")
        elif self._view_index == 2:
            columns = (*identity, "omitted_day", "status", "remaining_day_count", "removed_complete_target_count",
                       "remaining_complete_target_count", "selected_index", *chosen_columns, "runner_up_index", "margin", "unit",
                       "changed_choice", "unchanged_reason", "unavailable_reason")
        elif self._view_index == 4:
            columns = (*identity, "candidate_index", *chosen_columns, "selection_count", "available_omission_count")
        else:
            model_columns = ("joint_model_index", "strategy_kind", "alpha", "threshold", "model_threshold_bps") if joint else ()
            columns = (*identity, "candidate_index", *model_columns, "ml_evidence_role", "observation_key", "trading_day", "value", "unit")
        rows = []
        for window in windows:
            common = {"window_index": window["window_index"], "ml_window_scope": window["scope"]}
            original = window["original"]
            if self._view_index == 0:
                chosen = next((row for row in original["objectives"] if row["candidate_index"] == original["selected_index"]), None)
                rows.append({**common, **self._choice_fields(original),
                    **(self._recipe_fields(original["selected_recipe"]) if joint else {}),
                    "objective_value": risk_value(chosen["value"], chosen["unit"]) if chosen else "—",
                    "available_omission_count": window["available_omission_count"],
                    "changed_choice_count": window["changed_choice_count"]})
            elif self._view_index in (1, 3):
                choices = [original] if self._view_index == 1 else window["omissions"]
                for choice in choices:
                    for objective in choice["objectives"]:
                        recipe = objective["recipe"]
                        rows.append({**common, "omitted_day": choice.get("omitted_day"),
                            "candidate_index": objective["candidate_index"], "strategy_kind": recipe["kind"],
                            "alpha": recipe["alpha"], "threshold": risk_value(recipe["threshold"], "RATIO"),
                            "objective_value": risk_value(objective["value"], objective["unit"]), "unit": objective["unit"],
                            "ml_chosen": "—" if choice["selected_index"] is None else
                                         "YES" if objective["candidate_index"] == choice["selected_index"] else "NO",
                            "unavailable_reason": objective["unavailable_reason"] or "—", "complete_objective": deepcopy(objective)})
            elif self._view_index == 2:
                for choice in window["omissions"]:
                    rows.append({**common, **self._choice_fields(choice), "omitted_day": choice["omitted_day"],
                        **(self._recipe_fields(choice["selected_recipe"]) if joint else {}),
                        "remaining_day_count": len(choice["remaining_days"]),
                        "removed_complete_target_count": choice["removed_complete_target_count"],
                        "remaining_complete_target_count": choice["remaining_complete_target_count"],
                        "changed_choice": "—" if choice["changed_choice"] is None else "YES" if choice["changed_choice"] else "NO",
                        "unchanged_reason": choice["unchanged_reason"] or "—", "complete_omission": deepcopy(choice)})
            elif self._view_index == 4:
                recipes = {row["candidate_index"]: row["recipe"] for row in original["objectives"]} if joint else {}
                rows.extend({**common, "candidate_index": row["candidate_index"], "selection_count": row["count"],
                             **(self._recipe_fields(recipes[row["candidate_index"]]) if joint else {}),
                             "available_omission_count": window["available_omission_count"]} for row in window["selection_counts"])
            else:
                rows.extend({**common, **row} for row in self._fixed_evidence_rows(window["fixed_evidence"], joint=joint))
        return columns, rows

    @staticmethod
    def _fixed_evidence_rows(fixed, *, joint=False):
        rows = []
        for role in ("history_days", "training_days", "validation_days", "history_training_keys", "history_purged_keys",
                     "training_keys", "purged_keys", "validation_keys"):
            rows.extend({"ml_evidence_role": "inner_" + role, "value": value} for value in fixed[role])
        for role in ("history_boundary", "training_boundary"):
            rows.append({"ml_evidence_role": "inner_" + role, "value": fixed[role]})
        targets = {row["observation_key"]: row for row in fixed.get("scored_targets", [])}
        members = fixed["models"] if joint else fixed["family_results"] if "scored_targets" in fixed else [fixed]
        for member in members:
            model, candidate = member["model"], member.get("candidate_index")
            shared = {"joint_model_index": member["model_index"], "strategy_kind": member["strategy"]["kind"],
                      "alpha": member["strategy"]["alpha"], "model_threshold_bps": member["strategy"]["threshold"] * 10000,
                      "complete_recipe": deepcopy(member["strategy"])} if joint else {}
            rows.append({"candidate_index": candidate, **shared,
                         "ml_evidence_role": "fixed_shared_model" if joint else "fixed_model", "value": model["model_id"],
                         "complete_model": deepcopy(model)})
            for prediction in member["predictions"]:
                rows.append({"candidate_index": candidate, **shared,
                    "ml_evidence_role": "fixed_shared_prediction" if joint else "fixed_prediction",
                    "observation_key": prediction["observation_key"], "trading_day": prediction["trading_day"],
                    "value": risk_value(prediction["score"], "RATIO"), "unit": "RATIO",
                    "complete_prediction": deepcopy(prediction), "scored_target": deepcopy(targets.get(prediction["observation_key"]))})
        for target in targets.values():
            rows.append({"ml_evidence_role": "fixed_scored_target", "observation_key": target["observation_key"],
                "trading_day": target["trading_day"], "value": risk_value(target["value"], "RATIO"), "unit": "RATIO",
                "complete_target": deepcopy(target)})
        if "scored_targets" not in fixed:
            for member in fixed["family_results"]:
                recipe = {"joint_model_index": member["model_index"],
                          **IntradayMLDiagnosticsController._recipe_fields(member["strategy"]),
                          "complete_recipe": deepcopy(member["strategy"])} if joint else {}
                for day in member["execution"]["daily"]:
                    rows.append({"candidate_index": member["candidate_index"], **recipe, "ml_evidence_role": "fixed_daily_cash",
                        "trading_day": day["trading_day"], "value": risk_value(day["return"], "RATIO"), "unit": "RATIO",
                        "complete_daily_cash": deepcopy(day)})
        return rows

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index < len(self.viewOptions):
            return False
        self._view_index = index
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectScope(self, index):
        if type(index) is not int or not 0 <= index < len(self.scopeOptions):
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
            from ..research.intraday_joint_selection import INTRADAY_JOINT_SELECTION_VERSION
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
            elif schema == INTRADAY_JOINT_SELECTION_VERSION:
                kind = "JOINT_ECONOMIC_SELECTION"
            else:
                raise ValueError("Open an ordinary learned DEV experiment, an inner ML, economic threshold or joint economic selection study.")
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
                raise ValueError("Open an inner ML, economic threshold or joint economic selection study before analyzing." if self.recordedOnlyMode else
                                 "Open the selected saved source and choose a learned DEV candidate before analyzing.")
            mode = self._mode_index
            locator = _experiment_file_path(self._data_locator) if mode == 0 and self._data_locator.strip() else None
            content, cost, candidate = self._content, self._cost_index, self._candidate_index
            captured = {"source_path": self._opened_path, "source_experiment_id": self._root["experiment_id"],
                        "diagnostic_mode": ("PREDICTION_QUALITY", "INNER_OBJECTIVE_SENSITIVITY", "PROCEDURE_RETURN_UNCERTAINTY")[mode]}
            if mode == 0:
                captured.update(requested_cost_index=cost, requested_candidate_index=candidate,
                                requested_data_locator=self._data_locator)
        except (TypeError, ValueError, OSError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)

        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment
            if mode == 2:
                from ..research.intraday_procedure_return_uncertainty import analyze_intraday_procedure_return_uncertainty
                return analyze_intraday_procedure_return_uncertainty(StrategyExperiment(content))
            if mode == 1:
                from ..research.intraday_inner_objective_sensitivity import analyze_intraday_inner_objective_sensitivity
                return analyze_intraday_inner_objective_sensitivity(StrategyExperiment(content))
            from ..research.intraday_ml_diagnostics import analyze_intraday_ml_prediction_quality
            return analyze_intraday_ml_prediction_quality(StrategyExperiment(content), cost_index=cost,
                candidate_index=candidate, intraday_data_file=locator)

        def analyzed(report):
            changed_method = self._report.get("version") != report["version"]
            self._report, self._completed_source, self._completed_key = report, captured, self._key()
            self._scope_index = 0
            self._evidence_account_index, self._evidence_section_index = 0, 0
            if changed_method:
                self._view_index = 0
            self._refresh()

        return self._start(("analyze", "sensitivity", "procedure_uncertainty")[mode], operation, analyzed)
