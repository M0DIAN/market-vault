"""Captured saved procedures for paired and complete-family native evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .controllers import PageController
from .intraday_research import risk_value
from .table_model import QtTableModel


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


class IntradayProcedureComparisonController(PageController):
    changed = Signal()
    choicesChanged = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._paths = {role: "" for role in ("A", "B", "C")}
        self._sources = {role: None for role in ("A", "B", "C")}
        self._mode_index = 0
        self._report, self._bound_sources = {}, []
        self._revision, self._completed_key, self._pending = 0, None, None
        self._study_error, self._notice = "", ""
        self._view_index, self._member_index, self._section_index, self._page = 0, 0, 0, 1
        self._columns, self._rows, self._evidence_rows = (), (), []
        self._model = QtTableModel(parent=self)
        self._set_page()
        self.operationFailed.connect(self._failed)

    def _key(self):
        roles = self._active_roles()
        return (self._revision, self._mode_index, *(self._paths[role] for role in roles),
                *(self._sources[role]["sha256"] if self._sources[role] else None for role in roles))

    def _active_roles(self):
        return ("A", "B", "C") if self.familyMode else ("A", "B")

    @Property(int, notify=changed)
    def modeIndex(self):
        return self._mode_index

    @Property(bool, notify=changed)
    def familyMode(self):
        return self._mode_index == 1

    @Property(bool, notify=changed)
    def completedFamily(self):
        # Finished views never inherit the meaning of a subsequently edited mode.
        return "family_bounds_id" in self._report

    @Slot(int, result=bool)
    def selectMode(self, index):
        if type(index) is not int or index not in (0, 1):
            return False
        if index != self._mode_index:
            choices = (self.viewOptions, self.memberOptions)
            self._mode_index = index
            self._revision += 1
            self._study_error, self._notice = "", ""
            if choices != (self.viewOptions, self.memberOptions):
                self.choicesChanged.emit()
            self.changed.emit()
        return True

    def _set_path(self, role, value):
        if value != self._paths[role]:
            self._paths[role] = value
            self._revision += 1
            self._study_error, self._notice = "", ""
            self.changed.emit()

    @Property(str, notify=changed)
    def leftPath(self):
        return self._paths["A"]

    @Property(str, notify=changed)
    def rightPath(self):
        return self._paths["B"]

    @Property(str, notify=changed)
    def thirdPath(self):
        return self._paths["C"]

    @Slot(str)
    def setLeftPath(self, value):
        self._set_path("A", value)

    @Slot(str)
    def setRightPath(self, value):
        self._set_path("B", value)

    @Slot(str)
    def setThirdPath(self, value):
        self._set_path("C", value)

    def _source_view(self, role):
        source = self._sources[role]
        return {key: source[key] for key in ("role", "path", "experiment_id", "selection_id", "source_kind", "name", "sha256")} if source else {}

    @Property("QVariantMap", notify=changed)
    def leftSource(self):
        return self._source_view("A")

    @Property("QVariantMap", notify=changed)
    def rightSource(self):
        return self._source_view("B")

    @Property("QVariantMap", notify=changed)
    def thirdSource(self):
        return self._source_view("C")

    @Property(str, notify=changed)
    def inputReason(self):
        roles = self._active_roles()
        if not all(self._sources[role] for role in roles):
            return "OPEN_THREE" if self.familyMode else "OPEN_TWO"
        try:
            from .quant_research import _experiment_file_path
            if any(str(_experiment_file_path(self._paths[role])) != self._sources[role]["path"] for role in roles):
                return "OPEN_CHANGED"
        except (OSError, TypeError, ValueError):
            return "OPEN_CHANGED"
        kinds = {self._sources[role]["source_kind"] for role in roles}
        if self.familyMode and kinds != {"INNER_MODEL_SELECTION", "ECONOMIC_THRESHOLD_SELECTION", "JOINT_ECONOMIC_SELECTION"}:
            return "COMPLETE_FAMILY_REQUIRED"
        if not self.familyMode and len(kinds) != 2:
            return "DIFFERENT_KINDS"
        return ""

    @Property(bool, notify=changed)
    def canRun(self):
        return not self.inputReason

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

    @Property("QVariantList", notify=changed)
    def boundSources(self):
        return deepcopy(self._bound_sources)

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        result = {**deepcopy({key: self._report.get(key) for key in (
            "status", "comparison_id", "ordinary_source_id", "data_id", "source_selection", "evaluation_scope",
            "sample", "sampling", "unavailable_reason", "unavailable_reasons", "family_bounds_id", "family_size",
            "family_scope", "historical_search_coverage", "family_inference")}),
            "basis_matches": (self._report.get("basis") or {}).get("matches")} if self._report else {}
        if self.completedFamily:
            result["reference"] = {key: value for key, value in self._report["reference"].items() if key != "account"}
            result["deduction_display"] = self._return_value(self._report["family_inference"]["deduction"], "B_MINUS_A")
        return result

    @Property(str, notify=changed)
    def completeReport(self):
        return _json(self._report) if self._report else ""

    @Property(str, notify=changed)
    def completedDetails(self):
        if not self._report:
            return ""
        # The native dialog stays responsive for long saved ledgers. Its
        # identity/method summary accompanies an exact full-report copy action;
        # complete records remain individually readable in the paged views.
        keys = ("version", "comparison_id", "family_bounds_id", "status", "evaluation_scope", "ordinary_source_id", "data_id",
                "source_selection", "evidence", "method", "parameters", "sample", "sampling", "statistics",
                "unavailable_reason", "unavailable_reasons", "family_size", "family_scope", "historical_search_coverage",
                "family_inference")
        details = {"sources": self._bound_sources, **{key: self._report[key] for key in keys if key in self._report}}
        if self.completedFamily:
            details["reference"] = self.resultSummary["reference"]
        return _json(details)

    @Slot(result=bool)
    def copyReport(self):
        if not self._report:
            return False
        QGuiApplication.clipboard().setText(self.completeReport)
        return True

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property("QStringList", notify=choicesChanged)
    def viewOptions(self):
        if self.completedFamily or not self._report and self.familyMode:
            return ["family_bounds", "family_daily", "folds", "accounts", "basis"]
        return ["intervals", "daily", "folds", "accounts", "basis"]

    @Property(int, notify=changed)
    def memberIndex(self):
        return self._member_index

    @Property("QStringList", notify=choicesChanged)
    def memberOptions(self):
        if self.completedFamily:
            return ["ALL_FAMILY", "Q25", "Q31", "Q36", *(["FAMILY_REFERENCE", "FAMILY_BENCHMARK"] if self._view_index == 3 else [])]
        return ["ALL", "A", "B"]

    def _members(self):
        members = self._report.get("members", [])
        return members if self._member_index == 0 else [member for member in members if member["role"] == self.memberOptions[self._member_index]]

    def _account_sources(self):
        role = self.memberOptions[self._member_index]
        if self.completedFamily and role == "FAMILY_REFERENCE":
            return [(role, self._report["reference"]["account"], "/reference/account")]
        if self.completedFamily and role == "FAMILY_BENCHMARK":
            return [(role, self._report["benchmark"], "/benchmark")]
        indices = {member["role"]: index for index, member in enumerate(self._report.get("members", []))}
        return [(member["role"], member.get("selected_account"), "/members/" + str(indices[member["role"]]) + "/selected_account")
                for member in self._members()]

    @Property(int, notify=changed)
    def sectionIndex(self):
        return self._section_index

    @Property("QStringList", notify=changed)
    def sectionOptions(self):
        sections = []
        for _, account, _ in self._account_sources():
            for key, value in (account or {}).items():
                sections.extend("execution." + child for child in value) if key == "execution" else sections.append(key)
        return ["all_fields", *dict.fromkeys(sections)]

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    @Property(str, notify=changed)
    def currentPageEvidence(self):
        if not self._report:
            return ""
        start = (self._page - 1) * 100
        id_key = "family_bounds_id" if self.completedFamily else "comparison_id"
        return _json({id_key: self._report[id_key], "sources": self._bound_sources,
                      "view": self.viewOptions[self._view_index], "member": self.memberOptions[self._member_index],
                      "section": self.sectionOptions[self._section_index], "page": self._page,
                      "rows": self._evidence_rows[start:start + 100]})

    @staticmethod
    def _return_value(value, series):
        displayed = risk_value(value, "RATIO")
        return displayed.removesuffix("%") if series == "B_MINUS_A" else displayed

    def _account_rows(self):
        rows, section = [], self.sectionOptions[self._section_index]

        def append(role, path, value):
            kind = "OBJECT" if isinstance(value, dict) else "ARRAY" if isinstance(value, list) else "VALUE"
            rows.append({"account_role": role, "record_path": path, "record_kind": kind,
                         "record_value": len(value) if kind != "VALUE" else value, "complete_record": deepcopy(value)})

        def walk(role, path, value):
            if isinstance(value, dict) and value:
                for key, child in value.items():
                    walk(role, path + "/" + key.replace("~", "~0").replace("/", "~1"), child)
            elif isinstance(value, list) and value:
                for index, child in enumerate(value):
                    append(role, path + "/" + str(index), child)
            else:
                append(role, path, value)

        for role, account, base in self._account_sources():
            if section == "all_fields":
                walk(role, base, account)
            elif section.startswith("execution."):
                field = section.removeprefix("execution.")
                if account and field in account.get("execution", {}):
                    walk(role, base + "/execution/" + field, account["execution"][field])
            elif account and section in account:
                walk(role, base + "/" + section, account[section])
        return rows

    def _refresh(self):
        self._columns, self._rows, self._evidence_rows, self._page = (), (), [], 1
        if not self._report:
            self._set_page()
            return
        rows = []
        if self.completedFamily and self._view_index == 0:
            columns = ("family_role", "family_mean_excess", "family_lower_95", "unit", "sample_count",
                       "mean_unavailable_reason", "bound_unavailable_reason", "detail")
            rows = [{"family_role": row["role"], "sample_count": row["sample_count"],
                "family_mean_excess": self._return_value(row["mean_excess"], "B_MINUS_A"),
                "family_lower_95": self._return_value(row["lower"], "B_MINUS_A"), "unit": "PERCENTAGE_POINTS",
                "mean_unavailable_reason": row["mean_unavailable_reason"] or "—",
                "bound_unavailable_reason": row["bound_unavailable_reason"] or "—", "detail": row["detail"] or "—",
                "complete_record": deepcopy(row)} for row in self._report["statistics"]]
        elif self.completedFamily and self._view_index == 1:
            columns = ("trading_day", "fold_id", "family_q25_excess", "family_q31_excess", "family_q36_excess")
            rows = [{"trading_day": row["trading_day"], "fold_id": row["fold_id"],
                **{column: self._return_value(row["values"][role], "B_MINUS_A") for column, role in
                   zip(columns[2:], ("Q25", "Q31", "Q36"), strict=True)}, "complete_record": deepcopy(row)}
                for row in self._report["daily"]]
        elif self._view_index == 0:
            columns = ("return_series", "return_mean", "return_lower_95", "return_upper_95", "unit", "sample_count",
                       "mean_unavailable_reason", "interval_unavailable_reason", "detail")
            for row in self._report["statistics"]:
                rows.append({"return_series": row["series"], "sample_count": row["sample_count"],
                    **{"return_" + field + ("_95" if field != "mean" else ""): self._return_value(row[field], row["series"])
                       for field in ("mean", "lower", "upper")},
                    "unit": "PERCENTAGE_POINTS" if row["series"] == "B_MINUS_A" else "RATIO",
                    "mean_unavailable_reason": row["mean_unavailable_reason"] or "—",
                    "interval_unavailable_reason": row["interval_unavailable_reason"] or "—",
                    "detail": row["detail"] or "—", "complete_record": deepcopy(row)})
        elif self._view_index == 1:
            columns = ("trading_day", "fold_id", "procedure_a", "procedure_b", "procedure_b_minus_a")
            rows = [{"trading_day": row["trading_day"], "fold_id": row["fold_id"],
                **{column: self._return_value(row["values"][series], series) for column, series in
                   zip(columns[2:], ("A", "B", "B_MINUS_A"), strict=True)}, "complete_record": deepcopy(row)}
                for row in self._report["daily"]]
        elif self._view_index == 2:
            columns = ("account_role", "fold_index", "fold_id", "selected_index", "strategy_kind", "alpha",
                       "threshold_bps", "model_id", "training_boundary")
            for member in self._members():
                for index, fold in enumerate(member["outer_folds"]):
                    recipe = fold.get("selected_recipe") or {}
                    applied = fold.get("refit") or fold.get("application") or {}
                    model = applied.get("model") or {}
                    rows.append({"account_role": member["role"], "fold_index": index, "fold_id": fold["fold_id"],
                        "selected_index": fold.get("selected_index"), "strategy_kind": recipe.get("kind"),
                        "alpha": recipe.get("alpha"), "threshold_bps": recipe["threshold"] * 10000 if recipe else None,
                        "model_id": model.get("model_id"), "training_boundary": model.get("training_boundary"),
                        "complete_record": deepcopy(fold)})
        elif self._view_index == 3:
            columns, rows = ("account_role", "record_path", "record_kind", "record_value"), self._account_rows()
        else:
            columns = ("account_role", "basis_check", "basis_matches", "expected", "recorded")
            basis = self._report.get("basis") or {}
            shared_role = "ALL_FAMILY" if self.completedFamily else "ALL"
            if basis:
                rows.append({"account_role": shared_role, "basis_check": "basis_complete_source", "basis_matches": "YES",
                    "expected": "COMPLETE_ORDINARY_SOURCE_AND_REFERENCE_EQUAL", "recorded": basis["source_comparison"],
                    "complete_record": {"source_comparison": basis["source_comparison"]}})
            for member in basis.get("members", []):
                rows.extend({"account_role": member["role"], "basis_check": "basis_" + row["key"],
                    "basis_matches": "YES" if row["matches"] else "NO", "expected": _json(row["expected"]),
                    "recorded": _json(row["recorded"]), "complete_record": deepcopy(row)} for row in member["checks"])
            rows.extend({"account_role": shared_role, "basis_check": "shared_" + row["account"],
                "basis_matches": "NO" if row["unavailable_reason"] else "YES", "expected": "AVAILABLE",
                "recorded": row["unavailable_reason"] or "AVAILABLE", "complete_record": deepcopy(row)}
                for row in self._report.get("shared_account_checks", []))
        self._columns, self._evidence_rows = columns, rows
        self._rows = tuple(tuple("—" if row.get(column) is None else str(row[column]) for column in columns) for row in rows)
        self._set_page()

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index < len(self.viewOptions):
            return False
        choices = self.memberOptions
        self._view_index = index
        if self._member_index >= len(self.memberOptions):
            self._member_index, self._section_index = 0, 0
        self._refresh()
        if choices != self.memberOptions:
            self.choicesChanged.emit()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectMember(self, index):
        if type(index) is not int or not 0 <= index < len(self.memberOptions):
            return False
        self._member_index, self._section_index = index, 0
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectSection(self, index):
        if type(index) is not int or not 0 <= index < len(self.sectionOptions):
            return False
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
        self.changed.emit()
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

        accepted = self._submit("intraday_procedure_" + action, operation, completed, requires_backend=False)
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

    def _open(self, roles):
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            paths = {role: _experiment_file_path(self._paths[role]) for role in roles}
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
            sources = {}
            for role, path in paths.items():
                snapshot = load_strategy_experiment(path)
                root = snapshot.as_dict()
                if root["artifact_schema_version"] not in kinds:
                    raise ValueError("Open saved Q25, Q31 or Q36 selection studies with their complete ordinary DEV source.")
                kind, id_key = kinds[root["artifact_schema_version"]]
                sources[role] = {"role": role, "path": str(path), "content": snapshot.content,
                    "experiment_id": root["experiment_id"], "selection_id": root["report"][id_key],
                    "source_kind": kind, "name": root["name"], "sha256": hashlib.sha256(snapshot.content).hexdigest()}
            return sources

        def opened(sources):
            # Group opening is atomic: one invalid file never replaces another.
            self._sources.update(sources)
            self._revision += 1

        return self._start("open", operation, opened)

    @Slot(result=bool)
    def openLeft(self):
        return self._open(("A",))

    @Slot(result=bool)
    def openRight(self):
        return self._open(("B",))

    @Slot(result=bool)
    def openThird(self):
        return self._open(("C",))

    @Slot(result=bool)
    def openPair(self):
        return self._open(self._active_roles())

    @Slot(result=bool)
    def runComparison(self):
        if self.busy or self._runtime.busy:
            return False
        if not self.canRun:
            exc = ValueError("Explicitly open the complete Q25/Q31/Q36 family before analyzing." if self.familyMode else
                             "Explicitly open two different saved Q25/Q31/Q36 procedures before comparing.")
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)
        family = self.familyMode
        captured = {role: dict(self._sources[role]) for role in self._active_roles()}

        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment
            if family:
                from ..research.intraday_procedure_family import analyze_intraday_procedure_family
                return analyze_intraday_procedure_family(tuple(StrategyExperiment(source["content"]) for source in captured.values()))
            from ..research.intraday_procedure_comparison import compare_intraday_procedures
            return compare_intraday_procedures(StrategyExperiment(captured["A"]["content"]),
                                                StrategyExperiment(captured["B"]["content"]))

        def compared(report):
            choices = (self.viewOptions, self.memberOptions)
            self._report = report
            if family:
                by_kind = {source["source_kind"]: source for source in captured.values()}
                self._bound_sources = [{**{key: value for key, value in by_kind[member["source_kind"]].items() if key != "content"},
                    "input_slot": by_kind[member["source_kind"]]["role"], "role": member["role"]} for member in report["members"]]
            else:
                self._bound_sources = [{key: value for key, value in captured[role].items() if key != "content"}
                                       for role in ("A", "B")]
            self._completed_key = self._key()
            self._member_index, self._section_index = 0, 0
            self._refresh()
            if choices != (self.viewOptions, self.memberOptions):
                self.choicesChanged.emit()

        return self._start("family" if family else "compare", operation, compared)
