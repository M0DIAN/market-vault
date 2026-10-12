"""Native inspection of captured outer risk and inner-cost diagnostics."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .controllers import PageController
from .intraday_research import risk_value
from .table_model import QtTableModel


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _display(value):
    if value is None:
        return "—"
    if type(value) is bool:
        return "YES" if value else "NO"
    if type(value) in (int, float):
        return risk_value(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return str(value)


def _records(value, path):
    """Page complete list records; preserve scalar and empty-container evidence."""
    rows = []

    def append(pointer, item):
        kind = "OBJECT" if isinstance(item, dict) else "ARRAY" if isinstance(item, list) else "VALUE"
        rows.append({"record_path": pointer, "record_kind": kind,
            "record_value": len(item) if kind != "VALUE" else item, "complete_record": item})

    def walk(pointer, item):
        if isinstance(item, dict) and item:
            for key, child in item.items():
                walk(pointer + "/" + key.replace("~", "~0").replace("/", "~1"), child)
        elif isinstance(item, list) and item:
            for index, child in enumerate(item):
                append(pointer + "/" + str(index), child)
        else:
            append(pointer, item)

    walk(path, value)
    return rows


def _recipe(recipe):
    recipe = recipe or {}
    return {"strategy_kind": recipe.get("kind"), "alpha": recipe.get("alpha"),
            "threshold_bps": recipe["threshold"] * 10000 if "threshold" in recipe else None}


class IntradaySelectionDiagnosticsController(PageController):
    changed = Signal()
    resultChanged = Signal()
    tableChanged = Signal()
    choicesChanged = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._path, self._source, self._source_ready = "", None, False
        self._revision, self._mode_index, self._pending = 0, 0, None
        self._completed_key, self._completed_mode = None, ""
        self._study_error, self._notice = "", ""
        self._report, self._bound_source, self._result_summary = {}, {}, {}
        self._complete_report, self._completed_details = "", ""
        self._view_index, self._role_index, self._window_index = 0, 0, 0
        self._scenario_index, self._member_index, self._section_index = 0, 0, 0
        self._window_options, self._scenario_options, self._member_options = [], [], []
        self._section_options = ["all_fields"]
        self._columns, self._rows, self._evidence_rows = (), (), []
        self._page, self._page_evidence = 1, None
        self._model = QtTableModel(parent=self)
        self._set_page()
        self.operationFailed.connect(self._failed)

    def _key(self):
        return self._revision, self._path, self._mode_index, self._source["sha256"] if self._source else None

    @Property(str, notify=changed)
    def sourcePath(self):
        return self._path

    @Slot(str)
    def setSourcePath(self, value):
        if value != self._path:
            self._path = value
            self._revision += 1
            self._study_error, self._notice = "", ""
            self.changed.emit()

    @Property("QVariantMap", notify=changed)
    def sourceInfo(self):
        return {key: value for key, value in (self._source or {}).items() if key != "content"}

    @Property("QStringList", notify=changed)
    def modeOptions(self):
        return ["outer_risk"] if self._source and self._source["source_kind"] == "INNER_MODEL_SELECTION" else ["outer_risk", "inner_cost"]

    @Property(int, notify=changed)
    def modeIndex(self):
        return self._mode_index

    @Slot(int, result=bool)
    def selectMode(self, index):
        if type(index) is not int or not 0 <= index < len(self.modeOptions):
            return False
        if index != self._mode_index:
            self._mode_index = index
            self._revision += 1
            self._study_error, self._notice = "", ""
            self.changed.emit()
        return True

    @Property(str, notify=changed)
    def inputReason(self):
        if not self._source_ready:
            return "OPEN_STUDY"
        try:
            from .quant_research import _experiment_file_path
            if str(_experiment_file_path(self._path)) != self._source["path"]:
                return "OPEN_CHANGED"
        except (OSError, TypeError, ValueError):
            return "OPEN_CHANGED"
        return ""

    @Property(bool, notify=changed)
    def canRun(self):
        return not self.inputReason

    @Property(bool, notify=resultChanged)
    def resultLoaded(self):
        return bool(self._report)

    @Property(str, notify=resultChanged)
    def completedMode(self):
        return self._completed_mode

    @Property(bool, notify=changed)
    def draftChanged(self):
        return bool(self._report and self._completed_key != self._key())

    @Property(str, notify=changed)
    def studyError(self):
        return self._study_error

    @Property(str, notify=changed)
    def notice(self):
        return self._notice

    @Property("QVariantMap", notify=resultChanged)
    def boundSource(self):
        return dict(self._bound_source)

    @Property("QVariantMap", notify=resultChanged)
    def resultSummary(self):
        return dict(self._result_summary)

    @Property(str, notify=resultChanged)
    def completeReport(self):
        return self._complete_report

    @Property(str, notify=resultChanged)
    def completedDetails(self):
        return self._completed_details

    @Slot(result=bool)
    def copyReport(self):
        if not self._report:
            return False
        QGuiApplication.clipboard().setText(self._complete_report)
        return True

    @Property("QStringList", notify=resultChanged)
    def viewOptions(self):
        if self._completed_mode == "inner_cost":
            return ["choice_changes", "windows", "scenarios", "members", "baseline", "fixed_evidence", "accounts", "basis"]
        return ["risk_summary", "drawdown_episodes", "return_distributions", "cash_concentration", "risk_folds", "recipes", "accounts", "basis"]

    @Property("QStringList", constant=True)
    def roleOptions(self):
        return ["procedure", "fixed_reference", "benchmark"]

    @Property("QVariantList", notify=choicesChanged)
    def windowOptions(self):
        return list(self._window_options)

    @Property("QVariantList", notify=choicesChanged)
    def scenarioOptions(self):
        return list(self._scenario_options)

    @Property("QVariantList", notify=choicesChanged)
    def memberOptions(self):
        return list(self._member_options)

    @Property("QStringList", notify=choicesChanged)
    def sectionOptions(self):
        return list(self._section_options)

    @Property(int, notify=tableChanged)
    def viewIndex(self):
        return self._view_index

    @Property(int, notify=tableChanged)
    def roleIndex(self):
        return self._role_index

    @Property(int, notify=tableChanged)
    def windowIndex(self):
        return self._window_index

    @Property(int, notify=tableChanged)
    def scenarioIndex(self):
        return self._scenario_index

    @Property(int, notify=tableChanged)
    def memberIndex(self):
        return self._member_index

    @Property(int, notify=tableChanged)
    def sectionIndex(self):
        return self._section_index

    @Property("QVariantMap", notify=tableChanged)
    def selectors(self):
        view, cost = self.viewOptions[self._view_index], self._completed_mode == "inner_cost"
        return {"role": not cost and view in self.viewOptions[:5] + ["accounts"],
                "window": cost and view in ("scenarios", "members", "baseline", "fixed_evidence", "accounts"),
                "scenario": cost and view in ("members", "accounts"), "member": cost and view == "accounts",
                "section": view in ("accounts", "fixed_evidence")}

    def _window(self):
        return self._report["windows"][self._window_index] if self._completed_mode == "inner_cost" else {}

    def _scenario(self):
        window = self._window()
        return window["scenarios"][self._scenario_index] if window else {}

    def _member(self):
        members = self._scenario().get("members", [])
        return members[self._member_index] if members else None

    def _record_source(self):
        if self._completed_mode != "inner_cost":
            role = self.roleOptions[self._role_index]
            return self._report["accounts"][role], "/accounts/" + role
        base = "/windows/" + str(self._window_index)
        if self.viewOptions[self._view_index] == "fixed_evidence":
            return self._window()["fixed_evidence"], base + "/fixed_evidence"
        member = self._member()
        base += "/scenarios/" + str(self._scenario_index) + "/members"
        return (member, base + "/" + str(self._member_index)) if member else ([], base)

    def _update_choices(self):
        window, scenario = self._window(), self._scenario()
        self._scenario_options = [{"additional_slippage_bps": row["additional_slippage_bps"],
            "slippage_bps": row["execution_policy"]["slippage_bps"], "status": row["status"]}
            for row in window.get("scenarios", [])]
        self._member_options = [{"candidate_index": row["candidate_index"], "status": row["status"], **_recipe(row["recipe"])}
            for row in scenario.get("members", [])]
        record, _ = self._record_source()
        sections = ["all_fields"]
        for key, value in (record if isinstance(record, dict) else {}).items():
            sections.extend("execution." + child for child in value) if key == "execution" and value else sections.append(key)
        self._section_options = sections
        self.choicesChanged.emit()

    @Property("QVariantMap", notify=tableChanged)
    def selectionSummary(self):
        if not self._report:
            return {}
        if self.selectors["role"]:
            role = self.roleOptions[self._role_index]
            wrapper = self._report["diagnostics"][role]
            return {"role": role, **{key: value for key, value in wrapper.items() if key != "report"},
                "role_diagnostics_id": (wrapper["report"] or {}).get("diagnostics_id")}
        if not self.selectors["window"]:
            return {}
        window = self._window()
        result = {"window": {key: value for key, value in window.items() if key not in ("scenarios", "fixed_evidence", "baseline")},
                  "baseline_status": window["baseline"]["status"], "baseline_reason": window["baseline"]["unavailable_reason"]}
        if self.selectors["scenario"]:
            result["scenario"] = {key: value for key, value in self._scenario().items() if key != "members"}
            result["gap_display"] = risk_value(self._scenario()["best_runner_up_gap"], "RATIO").removesuffix("%")
        if self.selectors["member"]:
            member = self._member()
            result["member"] = {key: value for key, value in member.items() if key != "execution"} if member else None
        return result

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))
        self._page_evidence = None
        self.tableChanged.emit()

    @Property(str, notify=tableChanged)
    def currentPageEvidence(self):
        if not self._report:
            return ""
        if self._page_evidence is None:
            selection = {"view": self.viewOptions[self._view_index]}
            for name in ("role", "window", "scenario", "member", "section"):
                if not self.selectors[name]:
                    continue
                if name == "role":
                    selection["role"] = self.roleOptions[self._role_index]
                    selection["role_diagnostics_id"] = (self._report["diagnostics"][selection["role"]]["report"] or {}).get("diagnostics_id")
                elif name == "section":
                    selection["section"] = self._section_options[self._section_index]
                elif name == "window":
                    selection.update(window_index=self._window_index, scope=self._window()["scope"], fold_index=self._window()["fold_index"])
                elif name == "scenario":
                    selection.update(scenario_index=self._scenario_index, additional_slippage_bps=self._scenario()["additional_slippage_bps"])
                else:
                    member = self._member()
                    selection.update(member_index=self._member_index if member else None,
                                     candidate_index=member["candidate_index"] if member else None)
            if selection["view"] == "recipes":
                selection["role"] = "procedure"
            id_key = "sensitivity_id" if self._completed_mode == "inner_cost" else "diagnostics_id"
            start = (self._page - 1) * 100
            self._page_evidence = _json({"version": self._report["version"], id_key: self._report[id_key],
                "source": self._bound_source, "completed_mode": self._completed_mode, **selection,
                "page": self._page, "page_size": 100, "total_rows": len(self._rows),
                "rows": self._evidence_rows[start:start + 100]})
        return self._page_evidence

    def _risk_rows(self, view):
        role = self.roleOptions[self._role_index]
        wrapper = self._report["diagnostics"][role]
        if wrapper["status"] != "AVAILABLE":
            return ("status", "unavailable_reason", "detail"), [{**wrapper, "complete_record": wrapper}]
        report, rows = wrapper["report"], []
        if view == "risk_summary":
            for group, metrics in (("DRAWDOWNS", report["summary"]), ("FOLDS", report["fold_diagnostics"]["summary"])):
                for key, metric in (metrics or {}).items():
                    rows.append({"group": group, "metric": key, "metric_value": risk_value(metric["value"], metric["unit"]),
                        "unit": metric["unit"], "unavailable_reason": metric["unavailable_reason"], "complete_record": metric})
            if report["fold_diagnostics"]["status"] != "AVAILABLE":
                rows.append({"group": "FOLDS", "metric": "risk_folds", "unavailable_reason": report["fold_diagnostics"]["unavailable_reason"],
                             "complete_record": report["fold_diagnostics"]})
            return ("group", "metric", "metric_value", "unit", "unavailable_reason"), rows
        if view == "drawdown_episodes":
            for episode in report["drawdown_episodes"]:
                for prefix in ("peak", "trough", "recovery"):
                    rows.append({"drawdown_episode": episode["episode_index"],
                        "drawdown_stage": "UNRECOVERED" if prefix == "recovery" and not episode["recovered"] else prefix.upper(),
                        "sequence": episode[prefix + "_sequence"], "risk_time": episode[prefix + "_time"],
                        "risk_equity": risk_value(episode[prefix + "_equity"]), "drawdown_depth": risk_value(episode["depth"], "RATIO"),
                        "duration_minutes": episode["duration_minutes"], "recovered": episode["recovered"], "complete_record": episode})
            return ("drawdown_episode", "drawdown_stage", "sequence", "risk_time", "risk_equity", "drawdown_depth", "duration_minutes", "recovered"), rows
        if view == "return_distributions":
            for group in ("daily_return_distribution", "trade_return_distribution"):
                distribution = report[group]
                for key in ("sample_count", "positive_count", "zero_count", "negative_count", "minimum", "p05", "p25", "p50", "p75", "p95", "maximum"):
                    unit = "COUNT" if key.endswith("_count") else distribution["unit"]
                    rows.append({"distribution": group, "metric": key, "metric_value": risk_value(distribution[key], unit),
                        "unit": unit, "unavailable_reason": distribution["unavailable_reason"] if distribution[key] is None else None,
                        "complete_record": {"metric": key, "distribution": distribution}})
            return ("distribution", "metric", "metric_value", "unit", "unavailable_reason"), rows
        if view == "cash_concentration":
            for sign, concentration in report["cash_concentration"].items():
                for key in ("day_count", "total_absolute_cash", "top_1_absolute_cash", "top_3_absolute_cash", "top_1_share", "top_3_share"):
                    unit = "COUNT" if key == "day_count" else "RATIO" if key.endswith("_share") else "INITIAL_CASH_UNITS"
                    rows.append({"contribution_sign": sign, "metric": key, "metric_value": risk_value(concentration[key], unit),
                        "unit": unit, "unavailable_reason": concentration["unavailable_reason"] if concentration[key] is None else None,
                        "complete_record": concentration})
                for day in concentration["top_days"]:
                    rows.append({"contribution_sign": sign, "metric": "top_days", "trading_day": day["trading_day"],
                        "metric_value": risk_value(day["cash_contribution"]), "unit": "INITIAL_CASH_UNITS", "complete_record": day})
            return ("contribution_sign", "metric", "trading_day", "metric_value", "unit", "unavailable_reason"), rows
        folds = report["fold_diagnostics"]
        if folds["status"] != "AVAILABLE":
            return ("status", "unavailable_reason"), [{**folds, "complete_record": folds}]
        for fold in folds["rows"]:
            rows.append({**fold, "validation_start_day": fold["validation_days"][0], "validation_end_day": fold["validation_days"][-1],
                "compound_return": risk_value(fold["compound_return"], "RATIO"), "complete_record": fold})
        return ("fold_index", "validation_start_day", "validation_end_day", "day_count", "trade_count", "cash_only_days", "compound_return", "cash_contribution", "return_sign"), rows

    def _cost_rows(self, view):
        rows = []
        if view == "choice_changes":
            for item in self._report["choice_changes"]:
                rows.append({**item, "changed_choice_rate": risk_value(item["changed_choice_rate"], "RATIO"), "complete_record": item})
            return ("scope", "additional_slippage_bps", "status", "eligible_window_count", "declared_window_count", "changed_choice_count", "changed_choice_rate", "unavailable_reason"), rows
        if view == "windows":
            for window in self._report["windows"]:
                record = {key: value for key, value in window.items() if key not in ("scenarios", "fixed_evidence")}
                rows.append({**record, "selected_index": window["original"]["selected_index"], **_recipe(window["original"]["selected_recipe"]),
                    "baseline_status": window["baseline"]["status"], "complete_record": record})
            return ("window_index", "scope", "fold_index", "status", "selected_index", "strategy_kind", "alpha", "threshold_bps", "baseline_status", "source_unavailable_reason"), rows
        if view == "scenarios":
            for scenario in self._window()["scenarios"]:
                record = {key: value for key, value in scenario.items() if key != "members"}
                rows.append({**record, "gap_pp": risk_value(scenario["best_runner_up_gap"], "RATIO").removesuffix("%"),
                    "applied_slippage_bps": scenario["execution_policy"]["slippage_bps"],
                    **_recipe(scenario["selected_recipe"]), "complete_record": record})
            return ("additional_slippage_bps", "applied_slippage_bps", "status", "selected_index", "runner_up_index", "gap_pp", "changed_choice", "tied_best_indices", "member_counts", "unavailable_reason"), rows
        if view == "members":
            for member in self._scenario()["members"]:
                record = {key: value for key, value in member.items() if key != "execution"}
                metrics = member["metrics"] or {}
                rows.append({**record, **_recipe(member["recipe"]),
                    **{key: risk_value(metrics.get(key), "RATIO" if key in ("total_return", "observed_max_drawdown") else "NUMBER")
                       for key in ("initial_cash", "final_cash", "total_return", "observed_max_drawdown", "trade_count", "commission_total", "slippage_total")},
                    "complete_record": record})
            return ("candidate_index", "status", "strategy_kind", "alpha", "threshold_bps", "total_return", "trade_count", "commission_total", "slippage_total", "initial_cash", "final_cash", "observed_max_drawdown", "unavailable_reason"), rows
        baseline = self._window()["baseline"]
        summary = {key: value for key, value in baseline.items() if key != "member_checks"}
        for key in ("selected_index_matches", "selected_recipe_matches"):
            rows.append({"check": key, "matches": baseline[key], "status": baseline["status"],
                "unavailable_reason": baseline["unavailable_reason"], "complete_record": summary})
        for check in baseline["member_checks"]:
            rows.append({**check, "check": "complete_account", "complete_record": check})
        return ("check", "candidate_index", "matches", "status", "different_fields", "unavailable_reason"), rows

    def _refresh(self):
        self._columns, self._rows, self._evidence_rows, self._page = (), (), [], 1
        if not self._report:
            self._set_page()
            return
        view = self.viewOptions[self._view_index]
        if view in ("accounts", "fixed_evidence"):
            record, base = self._record_source()
            section = self._section_options[self._section_index]
            if section != "all_fields":
                for key in section.split("."):
                    record, base = record[key], base + "/" + key
            columns, rows = ("record_path", "record_kind", "record_value"), _records(record, base)
        elif view == "basis":
            keys = ("source_status", "source_unavailable_reasons", "source_selection", "context", "method", "evidence",
                    "sample", "unavailable_reason", "unavailable_reasons", "detail", "basis", "comparability", "account_availability", "return_basis")
            record = {key: self._report[key] for key in keys if key in self._report}
            columns, rows = ("record_path", "record_kind", "record_value"), _records(record, "")
        elif view == "recipes":
            rows = []
            for index, fold in enumerate(self._report["procedure"]["outer_folds"]):
                rows.append({"fold_index": index, "fold_id": fold["fold_id"], "selected_index": fold.get("selected_index"),
                    **_recipe(fold.get("selected_recipe")), "complete_record": fold})
            columns = ("fold_index", "fold_id", "selected_index", "strategy_kind", "alpha", "threshold_bps")
        elif self._completed_mode == "inner_cost":
            columns, rows = self._cost_rows(view)
        else:
            columns, rows = self._risk_rows(view)
        self._columns, self._evidence_rows = columns, rows
        self._rows = tuple(tuple(_display(row.get(key)) for key in columns) for row in rows)
        self._set_page()

    def _select(self, name, index, options):
        if type(index) is not int or not 0 <= index < len(options):
            return False
        attr = "_" + name + "_index"
        if index != getattr(self, attr):
            setattr(self, attr, index)
            if name == "window":
                self._scenario_index, self._member_index = 0, 0
            elif name == "scenario":
                self._member_index = 0
            if name != "section":
                self._section_index = 0
                self._update_choices()
            self._refresh()
        return True

    @Slot(int, result=bool)
    def selectView(self, index):
        return self._select("view", index, self.viewOptions) if self._report else False

    @Slot(int, result=bool)
    def selectRole(self, index):
        return self._select("role", index, self.roleOptions) if self._report else False

    @Slot(int, result=bool)
    def selectWindow(self, index):
        return self._select("window", index, self._window_options)

    @Slot(int, result=bool)
    def selectScenario(self, index):
        return self._select("scenario", index, self._scenario_options)

    @Slot(int, result=bool)
    def selectMember(self, index):
        return self._select("member", index, self._member_options)

    @Slot(int, result=bool)
    def selectSection(self, index):
        return self._select("section", index, self._section_options) if self._report else False

    @Slot(int, result=bool)
    def changePage(self, delta):
        page = self._page + delta
        if page < 1 or page > max(1, (len(self._rows) + 99) // 100):
            return False
        self._page = page
        self._set_page()
        return True

    def _start(self, action, operation, apply):
        key = self._key()
        self._pending = key
        self._study_error, self._notice = "", ""

        def completed(value):
            self._pending = None
            if key != self._key():
                self._notice = "STALE_INPUT"
            else:
                apply(value)
            self.changed.emit()

        accepted = self._submit("intraday_selection_diagnostics_" + action, operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        self.changed.emit()
        return accepted

    def _failed(self):
        pending, self._pending = self._pending, None
        if pending is not None:
            if pending == self._key():
                self._study_error = self.error
            else:
                self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
                self.stateChanged.emit()
            self.changed.emit()

    @Slot(result=bool)
    def openStudy(self):
        if self.busy or self._runtime.busy:
            return False
        self._source_ready = False
        self._revision += 1
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(self._path)
        except (OSError, TypeError, ValueError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)

        def operation(backend):
            from .intraday_procedure_comparison import IntradayProcedureComparisonController
            from ..research.strategy_experiment import load_strategy_experiment
            return IntradayProcedureComparisonController._source_descriptor("study", load_strategy_experiment(path), path)

        def opened(source):
            self._source, self._source_ready = source, True
            if source["source_kind"] == "INNER_MODEL_SELECTION":
                self._mode_index = 0

        return self._start("open", operation, opened)

    @Slot(result=bool)
    def runStudy(self):
        if self.busy or self._runtime.busy:
            return False
        if not self.canRun:
            exc = ValueError("Explicitly open one saved Q25/Q31/Q36 study before running selection diagnostics.")
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)
        captured, mode = dict(self._source), self.modeOptions[self._mode_index]
        source = {key: value for key, value in captured.items() if key != "content"}

        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment
            if mode == "inner_cost":
                from ..research.intraday_inner_cost_sensitivity import analyze_intraday_inner_cost_sensitivity as analyze
            else:
                from ..research.intraday_procedure_risk_diagnostics import analyze_intraday_procedure_risk_diagnostics as analyze
            report = analyze(StrategyExperiment(captured["content"]))
            metadata = {key: value for key, value in report.items() if key not in ("accounts", "procedure", "diagnostics", "windows")}
            # Serialize the full report once in the worker; draft edits,
            # language changes, navigation and clipboard copy reuse this text.
            return report, _json(report), _json({"captured_source": source, "completed_mode": mode, **metadata})

        def completed(value):
            self._report, self._complete_report, self._completed_details = value
            self._bound_source, self._completed_mode, self._completed_key = source, mode, self._key()
            id_key = "sensitivity_id" if mode == "inner_cost" else "diagnostics_id"
            self._result_summary = {key: self._report[key] for key in ("status", "source_status", "source_selection", "ordinary_source_id", "unavailable_reason")}
            self._result_summary.update(report_id=self._report[id_key], id_key=id_key, mode=mode)
            if mode == "inner_cost":
                self._result_summary.update(sample=self._report["sample"])
            else:
                self._result_summary.update(account_availability=self._report["account_availability"], comparability=self._report["comparability"])
            self._view_index, self._role_index, self._window_index = 0, 0, 0
            self._scenario_index, self._member_index, self._section_index = 0, 0, 0
            self._window_options = [{key: window[key] for key in ("window_index", "scope", "fold_index", "fold_id", "status")}
                for window in self._report.get("windows", [])]
            self._update_choices()
            self._refresh()
            self.resultChanged.emit()

        return self._start("run", operation, completed)
