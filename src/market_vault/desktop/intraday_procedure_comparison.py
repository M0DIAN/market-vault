"""Explicit saved A/B procedure inputs and immutable native comparison evidence."""

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

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._paths, self._sources = {"A": "", "B": ""}, {"A": None, "B": None}
        self._report, self._bound_sources = {}, []
        self._revision, self._completed_key, self._pending = 0, None, None
        self._study_error, self._notice = "", ""
        self._view_index, self._member_index, self._section_index, self._page = 0, 0, 0, 1
        self._columns, self._rows, self._evidence_rows = (), (), []
        self._model = QtTableModel(parent=self)
        self._set_page()
        self.operationFailed.connect(self._failed)

    def _key(self):
        return (self._revision, *(self._paths[role] for role in ("A", "B")),
                *(source["sha256"] if source else None for source in self._sources.values()))

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

    @Slot(str)
    def setLeftPath(self, value):
        self._set_path("A", value)

    @Slot(str)
    def setRightPath(self, value):
        self._set_path("B", value)

    def _source_view(self, role):
        source = self._sources[role]
        return {key: source[key] for key in ("role", "path", "experiment_id", "selection_id", "source_kind", "name", "sha256")} if source else {}

    @Property("QVariantMap", notify=changed)
    def leftSource(self):
        return self._source_view("A")

    @Property("QVariantMap", notify=changed)
    def rightSource(self):
        return self._source_view("B")

    @Property(str, notify=changed)
    def inputReason(self):
        if not all(self._sources.values()):
            return "OPEN_TWO"
        try:
            from .quant_research import _experiment_file_path
            if any(str(_experiment_file_path(self._paths[role])) != self._sources[role]["path"] for role in ("A", "B")):
                return "OPEN_CHANGED"
        except (OSError, TypeError, ValueError):
            return "OPEN_CHANGED"
        if self._sources["A"]["source_kind"] == self._sources["B"]["source_kind"]:
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
        return {**deepcopy({key: self._report.get(key) for key in (
            "status", "comparison_id", "ordinary_source_id", "data_id", "source_selection", "evaluation_scope",
            "sample", "sampling", "unavailable_reason", "unavailable_reasons")}),
            "basis_matches": (self._report.get("basis") or {}).get("matches")} if self._report else {}

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
        keys = ("version", "comparison_id", "status", "evaluation_scope", "ordinary_source_id", "data_id",
                "source_selection", "evidence", "method", "parameters", "sample", "sampling", "statistics",
                "unavailable_reason", "unavailable_reasons")
        return _json({"sources": self._bound_sources, **{key: self._report[key] for key in keys}})

    @Slot(result=bool)
    def copyReport(self):
        if not self._report:
            return False
        QGuiApplication.clipboard().setText(self.completeReport)
        return True

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property("QStringList", constant=True)
    def viewOptions(self):
        return ["intervals", "daily", "folds", "accounts", "basis"]

    @Property(int, notify=changed)
    def memberIndex(self):
        return self._member_index

    @Property("QStringList", constant=True)
    def memberOptions(self):
        return ["ALL", "A", "B"]

    def _members(self):
        members = self._report.get("members", [])
        return members if self._member_index == 0 else [member for member in members if member["role"] == self.memberOptions[self._member_index]]

    @Property(int, notify=changed)
    def sectionIndex(self):
        return self._section_index

    @Property("QStringList", notify=changed)
    def sectionOptions(self):
        sections = []
        for member in self._members():
            for key, value in (member.get("selected_account") or {}).items():
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
        return _json({"comparison_id": self._report["comparison_id"], "sources": self._bound_sources,
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

        for member in self._members():
            account, role = member.get("selected_account"), member["role"]
            base = "/members/" + str(("A", "B").index(role)) + "/selected_account"
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
        if self._view_index == 0:
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
            if basis:
                rows.append({"account_role": "ALL", "basis_check": "basis_complete_source", "basis_matches": "YES",
                    "expected": "COMPLETE_ORDINARY_SOURCE_AND_REFERENCE_EQUAL", "recorded": basis["source_comparison"],
                    "complete_record": {"source_comparison": basis["source_comparison"]}})
            for member in basis.get("members", []):
                rows.extend({"account_role": member["role"], "basis_check": "basis_" + row["key"],
                    "basis_matches": "YES" if row["matches"] else "NO", "expected": _json(row["expected"]),
                    "recorded": _json(row["recorded"]), "complete_record": deepcopy(row)} for row in member["checks"])
            rows.extend({"account_role": "ALL", "basis_check": "shared_" + row["account"],
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
        self._view_index = index
        self._refresh()
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
            # Pair opening is atomic: one invalid side never replaces the other.
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
    def openPair(self):
        return self._open(("A", "B"))

    @Slot(result=bool)
    def runComparison(self):
        if self.busy or self._runtime.busy:
            return False
        if not self.canRun:
            exc = ValueError("Explicitly open two different saved Q25/Q31/Q36 procedures before comparing.")
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)
        captured = {role: dict(source) for role, source in self._sources.items()}

        def operation(backend):
            from ..research.intraday_procedure_comparison import compare_intraday_procedures
            from ..research.strategy_experiment import StrategyExperiment
            return compare_intraday_procedures(StrategyExperiment(captured["A"]["content"]),
                                                StrategyExperiment(captured["B"]["content"]))

        def compared(report):
            self._report = report
            self._bound_sources = [{key: value for key, value in captured[role].items() if key != "content"}
                                   for role in ("A", "B")]
            self._completed_key = self._key()
            self._member_index, self._section_index = 0, 0
            self._refresh()

        return self._start("compare", operation, compared)
