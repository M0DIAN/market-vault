"""Native fixed-decision stress of one explicitly captured saved procedure."""

from __future__ import annotations

import hashlib
import json

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .controllers import PageController
from .intraday_research import risk_value
from .table_model import QtTableModel


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _value(metric):
    return risk_value(metric.get("value"), metric.get("unit", "NUMBER"))


class IntradayProcedureStressController(PageController):
    changed = Signal()
    resultChanged = Signal()
    tableChanged = Signal()
    scenarioChoicesChanged = Signal()
    sectionChoicesChanged = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._path, self._source, self._source_ready = "", None, False
        self._revision, self._completed_key, self._pending = 0, None, None
        self._study_error, self._notice = "", ""
        self._report, self._bound_source, self._result_summary = {}, {}, {}
        self._complete_report, self._completed_details = "", ""
        self._view_index, self._scenario_index, self._role_index = 0, 0, 0
        self._origin_index, self._section_index, self._page = 0, 0, 1
        self._scenario_options, self._section_options = [], ["all_fields"]
        self._columns, self._rows, self._evidence_rows, self._page_evidence = (), (), [], None
        self._model = QtTableModel(parent=self)
        self._set_page()
        self.operationFailed.connect(self._failed)

    def _key(self):
        return self._revision, self._path, self._source["sha256"] if self._source else None

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

    @Property("QStringList", constant=True)
    def viewOptions(self):
        return ["scenarios", "metrics", "daily", "signals", "accounts", "folds", "basis", "baseline"]

    @Property("QStringList", constant=True)
    def roleOptions(self):
        return ["procedure", "fixed_reference", "benchmark"]

    @Property("QStringList", constant=True)
    def originOptions(self):
        return ["scenario_account", "source_account"]

    @Property("QVariantList", notify=scenarioChoicesChanged)
    def scenarioOptions(self):
        return list(self._scenario_options)

    @Property("QStringList", notify=sectionChoicesChanged)
    def sectionOptions(self):
        return list(self._section_options)

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property(int, notify=changed)
    def scenarioIndex(self):
        return self._scenario_index

    @Property(int, notify=changed)
    def roleIndex(self):
        return self._role_index

    @Property(int, notify=changed)
    def originIndex(self):
        return self._origin_index

    @Property(int, notify=changed)
    def sectionIndex(self):
        return self._section_index

    def _scenario(self):
        return self._report["scenarios"][self._scenario_index] if self._report else {}

    @Property("QVariantMap", notify=tableChanged)
    def scenarioSummary(self):
        scenario = self._scenario()
        if not scenario:
            return {}
        role = self.roleOptions[self._role_index]
        increment, account = scenario["increment"], scenario["accounts"][role]
        signals = account["signals"]
        return {**{key: scenario[key] for key in ("scenario_index", "additional_slippage_bps", "delay_bars", "status",
                    "unavailable_reason", "detail")}, "role": role, "execution_policy": account["execution_policy"],
            "mean_display": risk_value(increment["mean"], "RATIO").removesuffix("%"),
            "delta_display": _value(increment["delta_from_zero"]), "sample_count": increment["sample_count"],
            "increment_unavailable_reason": increment["unavailable_reason"],
            "signal_counts": {key: value for key, value in signals.items() if key != "provenance"}}

    def _account(self):
        if not self._report:
            return None, ""
        role = self.roleOptions[self._role_index]
        if self._origin_index:
            return self._report["accounts"][role], "/accounts/" + role
        return self._scenario()["accounts"][role], "/scenarios/" + str(self._scenario_index) + "/accounts/" + role

    def _update_sections(self):
        account, _ = self._account()
        sections = ["all_fields"]
        for key, value in (account or {}).items():
            sections.extend("execution." + child for child in value) if key == "execution" and value else sections.append(key)
        if sections != self._section_options:
            self._section_options = sections
            self.sectionChoicesChanged.emit()

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
            start = (self._page - 1) * 100
            view = self.viewOptions[self._view_index]
            selection = {"view": view}
            if view in ("scenarios", "metrics", "signals", "accounts"):
                selection["role"] = self.roleOptions[self._role_index]
            elif view == "folds":
                selection["role"] = "procedure"
            else:
                selection["roles"] = self.roleOptions
            if view in ("scenarios", "metrics", "daily", "signals"):
                selection["account_origin"] = "scenario_account"
            elif view == "accounts":
                selection.update(account_origin=self.originOptions[self._origin_index],
                                 section=self._section_options[self._section_index])
            if view in ("metrics", "daily", "signals") or view == "accounts" and not self._origin_index:
                selection["scenario_index"] = self._scenario_index
            # Hidden account/scenario selectors retain navigation preferences,
            # but never relabel rows whose active view has a different scope.
            self._page_evidence = _json({"stress_id": self._report["stress_id"], "source": self._bound_source,
                **selection, "page": self._page, "rows": self._evidence_rows[start:start + 100]})
        return self._page_evidence

    def _account_rows(self):
        rows, section = [], self._section_options[self._section_index]
        account, base = self._account()

        def append(path, value):
            kind = "OBJECT" if isinstance(value, dict) else "ARRAY" if isinstance(value, list) else "VALUE"
            rows.append({"record_path": path, "record_kind": kind,
                         "record_value": len(value) if kind != "VALUE" else value, "complete_record": value})

        def walk(path, value):
            if isinstance(value, dict) and value:
                for key, child in value.items():
                    walk(path + "/" + key.replace("~", "~0").replace("/", "~1"), child)
            elif isinstance(value, list) and value:
                for index, child in enumerate(value):
                    append(path + "/" + str(index), child)
            else:
                append(path, value)

        if section == "all_fields":
            walk(base, account)
        elif section.startswith("execution."):
            field = section.removeprefix("execution.")
            walk(base + "/execution/" + field, account["execution"][field])
        else:
            walk(base + "/" + section, account[section])
        return rows

    def _refresh(self):
        self._columns, self._rows, self._evidence_rows, self._page = (), (), [], 1
        if not self._report:
            self._set_page()
            return
        rows, scenario, role = [], self._scenario(), self.roleOptions[self._role_index]
        account = scenario["accounts"][role]
        if self._view_index == 0:
            columns = ("scenario_index", "additional_slippage_bps", "delay_bars", "status", "total_return",
                       "return_change_pp", "observed_max_drawdown", "trade_count", "commission_total",
                       "slippage_total", "unavailable_reason", "detail")
            for item in self._report["scenarios"]:
                side = item["accounts"][role]
                metadata = {key: item[key] for key in ("scenario_index", "additional_slippage_bps", "delay_bars",
                                                     "status", "unavailable_reason", "detail")}
                rows.append({**metadata, **{metric: _value(side["metrics"][metric]) for metric in
                    ("total_return", "observed_max_drawdown", "trade_count", "commission_total", "slippage_total")},
                    "return_change_pp": _value(side["delta_from_zero"]["total_return"]),
                    "complete_record": {**metadata, "role": role, "execution_policy": side["execution_policy"],
                        "metrics": side["metrics"], "delta_from_zero": side["delta_from_zero"], "increment": item["increment"]}})
        elif self._view_index == 1:
            columns = ("metric", "metric_value", "unit", "change_from_zero", "change_unit", "unavailable_reason")
            for key, metric in account["metrics"].items():
                change = account["delta_from_zero"][key]
                rows.append({"metric": key, "metric_value": _value(metric), "unit": metric["unit"],
                    "change_from_zero": _value(change), "change_unit": change["unit"],
                    "unavailable_reason": metric["unavailable_reason"] or change["unavailable_reason"],
                    "complete_record": {"metric": key, "metric_record": metric, "delta_from_zero": change}})
        elif self._view_index == 2:
            columns = ("trading_day", "fold_id", "procedure_return", "fixed_reference_return", "benchmark_return", "increment_pp")
            rows = [{"trading_day": row["trading_day"], "fold_id": row["fold_id"],
                **{name + "_return": risk_value(value, "RATIO") for name, value in row["returns"].items()},
                "increment_pp": risk_value(row["procedure_minus_fixed_reference"], "RATIO").removesuffix("%"),
                "complete_record": row} for row in scenario["daily"]]
        elif self._view_index == 3:
            columns = ("source_observation_key", "source_trading_day", "source_slot", "source_time", "source_target",
                       "source_score", "delay_bars", "arrival_slot", "arrival_time", "derived_decision_key", "status", "passed_to_kernel")
            rows = [{**row, "passed_to_kernel": "YES" if row["passed_to_kernel"] else "NO", "complete_record": row}
                    for row in account["signals"]["provenance"]]
        elif self._view_index == 4:
            columns, rows = ("record_path", "record_kind", "record_value"), self._account_rows()
        elif self._view_index == 5:
            columns = ("fold_index", "fold_id", "selected_index", "strategy_kind", "alpha", "threshold_bps", "model_id", "training_boundary")
            for index, fold in enumerate(self._report["member"]["outer_folds"]):
                recipe = fold.get("selected_recipe") or {}
                applied = fold.get("refit") or fold.get("application") or {}
                model = applied.get("model") or {}
                rows.append({"fold_index": index, "fold_id": fold["fold_id"], "selected_index": fold.get("selected_index"),
                    "strategy_kind": recipe.get("kind"), "alpha": recipe.get("alpha"),
                    "threshold_bps": recipe["threshold"] * 10000 if recipe else None, "model_id": model.get("model_id"),
                    "training_boundary": model.get("training_boundary"), "complete_record": fold})
        elif self._view_index == 6:
            columns = ("basis_check", "basis_matches", "expected", "recorded")
            rows = [{"basis_check": "basis_" + row["key"], "basis_matches": "YES" if row["matches"] else "NO",
                     "expected": _json(row["expected"]), "recorded": _json(row["recorded"]), "complete_record": row}
                    for row in self._report["basis"]["checks"]]
        else:
            columns = ("check_group", "account_role", "status", "basis_matches", "unavailable_reason", "detail")
            for group in ("availability", "projection", "baseline"):
                checks = self._report[group].get("accounts", [self._report[group]])
                for check in checks:
                    rows.append({"check_group": group, "account_role": check.get("account", "all_roles"),
                        "status": check["status"], "basis_matches": "—" if check.get("matches") is None else "YES" if check["matches"] else "NO",
                        "unavailable_reason": check["unavailable_reason"], "detail": check["detail"], "complete_record": check})
        self._columns, self._evidence_rows = columns, rows
        self._rows = tuple(tuple("—" if row.get(column) is None else str(row[column]) for column in columns) for row in rows)
        self._set_page()

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index < len(self.viewOptions):
            return False
        if index != self._view_index:
            self._view_index = index
            self._refresh()
            self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectScenario(self, index):
        if type(index) is not int or not 0 <= index < len(self._scenario_options):
            return False
        if index != self._scenario_index:
            self._scenario_index, self._section_index = index, 0
            self._update_sections()
            self._refresh()
            self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectRole(self, index):
        if type(index) is not int or not 0 <= index < len(self.roleOptions):
            return False
        if index != self._role_index:
            self._role_index, self._section_index = index, 0
            self._update_sections()
            self._refresh()
            self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectOrigin(self, index):
        if type(index) is not int or not 0 <= index < len(self.originOptions):
            return False
        if index != self._origin_index:
            self._origin_index, self._section_index = index, 0
            self._update_sections()
            self._refresh()
            self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectSection(self, index):
        if type(index) is not int or not 0 <= index < len(self._section_options):
            return False
        if index != self._section_index:
            self._section_index = index
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

        accepted = self._submit("intraday_procedure_stress_" + action, operation, completed, requires_backend=False)
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
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(self._path)
        except (OSError, TypeError, ValueError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)

        def operation(backend):
            from ..research.intraday_inner_selection import INTRADAY_INNER_SELECTION_VERSION
            from ..research.intraday_joint_selection import INTRADAY_JOINT_SELECTION_VERSION
            from ..research.intraday_threshold_selection import INTRADAY_THRESHOLD_SELECTION_VERSION
            from ..research.strategy_experiment import load_strategy_experiment
            kinds = {INTRADAY_INNER_SELECTION_VERSION: ("INNER_MODEL_SELECTION", "inner_selection_id"),
                     INTRADAY_THRESHOLD_SELECTION_VERSION: ("ECONOMIC_THRESHOLD_SELECTION", "threshold_selection_id"),
                     INTRADAY_JOINT_SELECTION_VERSION: ("JOINT_ECONOMIC_SELECTION", "joint_selection_id")}
            snapshot = load_strategy_experiment(path)
            root = snapshot.as_dict()
            if root["artifact_schema_version"] not in kinds:
                raise ValueError("Open one saved AVAILABLE Q25, Q31 or Q36 study with its complete ordinary DEV source.")
            if root["report"]["status"] != "AVAILABLE":
                raise ValueError("SOURCE_STUDY_UNAVAILABLE: procedure stress requires an AVAILABLE Q25/Q31/Q36 study.")
            kind, id_key = kinds[root["artifact_schema_version"]]
            return {"path": str(path), "content": snapshot.content, "name": root["name"],
                "experiment_id": root["experiment_id"], "selection_id": root["report"][id_key], "source_kind": kind,
                "sha256": hashlib.sha256(snapshot.content).hexdigest()}

        def opened(source):
            self._source, self._source_ready = source, True
            self._revision += 1

        return self._start("open", operation, opened)

    @Slot(result=bool)
    def runStudy(self):
        if self.busy or self._runtime.busy:
            return False
        if not self.canRun:
            exc = ValueError("Explicitly open one AVAILABLE saved Q25/Q31/Q36 study before running procedure stress.")
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)
        captured = dict(self._source)

        def operation(backend):
            from ..research.intraday_procedure_stress import analyze_intraday_procedure_stress
            from ..research.strategy_experiment import StrategyExperiment
            report = analyze_intraday_procedure_stress(StrategyExperiment(captured["content"]))
            # Twenty-seven full accounts can be large. Serialize once off the UI
            # thread; input, language, scenario and page changes reuse this text.
            return report, _json(report)

        def completed(value):
            self._report, self._complete_report = value
            self._bound_source = {key: value for key, value in captured.items() if key != "content"}
            self._completed_key = self._key()
            report = self._report
            self._result_summary = {key: report[key] for key in ("status", "stress_id", "ordinary_source_id", "data_id",
                "source_selection", "scenario_counts", "unavailable_reason", "detail")}
            self._result_summary.update(basis_matches=report["basis"]["matches"], baseline_status=report["baseline"]["status"],
                projection_status=report["projection"]["status"], sample_count=report["sample"]["sample_count"],
                fold_count=report["sample"]["fold_count"])
            metadata = {key: report[key] for key in ("version", "stress_id", "status", "evaluation_scope", "experiment_id",
                "ordinary_source_id", "data_id", "source_kind", "source_schema_version", "algorithm_versions", "selection_id",
                "source_selection", "source_evaluation_scope", "evidence", "method", "scenario_counts", "sample", "availability",
                "projection", "baseline", "unavailable_reason", "detail", "warnings")}
            self._completed_details = _json({"source": self._bound_source, **metadata})
            self._scenario_index, self._role_index, self._origin_index, self._section_index = 0, 0, 0, 0
            options = [{key: row[key] for key in ("scenario_index", "additional_slippage_bps", "delay_bars")}
                       for row in report["scenarios"]]
            if options != self._scenario_options:
                self._scenario_options = options
                self.scenarioChoicesChanged.emit()
            self._update_sections()
            self._refresh()
            self.resultChanged.emit()

        return self._start("run", operation, completed)
