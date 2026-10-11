"""One captured DEV action, three ordinary studies and existing native views."""

from __future__ import annotations

from PySide6.QtCore import Property, Signal, Slot

from .controllers import PageController


_ROLES = ("Q25", "Q31", "Q36")
_SELECTION_IDS = ("inner_selection_id", "threshold_selection_id", "joint_selection_id")


class IntradayProcedureSuiteController(PageController):
    changed = Signal()
    sectionRequested = Signal(int)

    def __init__(self, runtime, *, research, inner, threshold, joint, comparison, parent):
        super().__init__(runtime, parent=parent)
        self._research = research
        self._controllers = (inner, threshold, joint)
        self._comparison = comparison
        self._data_locator, self._notice, self._study_error = "", "", ""
        self._source_signature, self._completed_signature, self._pending = None, None, None
        self._revision, self._artifact_revision = 0, 0
        self._studies, self._roots = (), ()
        self._saved_paths = ["", "", ""]
        self._completed_source = {}
        research.changed.connect(self._source_changed)
        self.operationFailed.connect(self._failed)
        self._source_changed()

    @staticmethod
    def _captured_signature(captured):
        return (captured["path"], captured["experiment_id"], captured["candidate_id"],
                captured["cost_index"], captured["candidate_index"])

    def _source_changed(self):
        try:
            signature = self._captured_signature(self._research.selection_source())
        except (ValueError, TypeError, IndexError, KeyError):
            signature = None
        if signature != self._source_signature:
            self._source_signature = signature
            self._revision += 1
            self._study_error = ""
        self.changed.emit()

    @Property(bool, notify=changed)
    def canRun(self) -> bool:
        return bool(self._source_signature and self._controllers[2].canRun)

    @Property(str, notify=changed)
    def dataLocator(self) -> str:
        return self._data_locator

    @Slot(str)
    def setDataLocator(self, value: str) -> None:
        if value != self._data_locator:
            self._data_locator = value
            self._revision += 1
            self._study_error = ""
            self.changed.emit()

    @staticmethod
    def _source_view(signature, data_locator):
        return {**dict(zip(("source_path", "source_id", "candidate_id", "cost_index", "candidate_index"), signature)),
                "data_locator": data_locator} if signature else {}

    @Property("QVariantMap", notify=changed)
    def draftSource(self) -> dict:
        return self._source_view(self._source_signature, self._data_locator)

    @Property("QVariantMap", notify=changed)
    def completedSource(self) -> dict:
        return dict(self._completed_source)

    @Property(bool, notify=changed)
    def resultLoaded(self) -> bool:
        return bool(self._studies)

    @Property(bool, notify=changed)
    def draftChanged(self) -> bool:
        return bool(self._studies and self._completed_signature != (self._source_signature, self._data_locator))

    @Property("QVariantList", notify=changed)
    def studyResults(self) -> list:
        return [{"role": role, "experiment_id": root["experiment_id"],
                 "selection_id": root["report"][id_key], "status": root["report"]["status"],
                 "unavailable_reason": "; ".join(dict.fromkeys(row["reason"] for row in root["report"]["unavailable_reasons"])),
                 "path": path, "save_state": "SAVED" if path else "UNSAVED"}
                for role, id_key, root, path in zip(_ROLES, _SELECTION_IDS, self._roots, self._saved_paths)]

    @Property(bool, notify=changed)
    def canCompare(self) -> bool:
        return len(self._studies) == 3 and all(self._saved_paths)

    @Property(str, notify=changed)
    def notice(self) -> str:
        return self._notice

    @Property(str, notify=changed)
    def studyError(self) -> str:
        return self._study_error

    def _key(self, action):
        return (self._revision, self._source_signature, self._data_locator) if action == "run" else self._artifact_revision

    def _start(self, action, operation, apply):
        if self.busy or self._runtime.busy:
            return False
        key = self._key(action)
        self._pending = (action, key)
        self._notice, self._study_error = "", ""

        def completed(value):
            self._pending = None
            if key != self._key(action):
                self._notice = "STALE_INPUT"
            else:
                apply(value)
            self.changed.emit()

        accepted = self._submit("intraday_procedure_suite_" + action, operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        self.changed.emit()
        return accepted

    def _failed(self):
        pending, self._pending = self._pending, None
        if pending is not None:
            action, key = pending
            if key == self._key(action):
                self._study_error = self.error
            else:
                self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
                self.stateChanged.emit()
            self.changed.emit()

    def _invalid(self, exc):
        self._study_error, self._notice = str(exc), ""
        self.changed.emit()
        return self._reject_input(exc)

    def _apply(self, studies, *, captured, data_locator):
        roots = tuple(study.as_dict() for study in studies)
        signature = self._captured_signature(captured)
        self._studies, self._roots = studies, roots
        self._completed_signature = (signature, data_locator)
        self._completed_source = self._source_view(signature, data_locator)
        self._saved_paths = ["", "", ""]
        self._artifact_revision += 1
        self._notice, self._study_error = "", ""

    @Slot(result=bool)
    def runSelected(self) -> bool:
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            if not self.canRun:
                raise ValueError(self._controllers[2]._source_requirement)
            captured = self._research.selection_source()
            data_locator = self._data_locator
            data = _experiment_file_path(data_locator) if data_locator.strip() else None
        except (OSError, TypeError, ValueError) as exc:
            return self._invalid(exc)

        def operation(backend):
            from ..research.intraday_procedure_suite import evaluate_intraday_procedure_suite
            from ..research.strategy_experiment import StrategyExperiment
            return evaluate_intraday_procedure_suite(StrategyExperiment(captured["content"]),
                source_experiment_path=captured["path"], expected_experiment_id=captured["experiment_id"],
                cost_index=captured["cost_index"], candidate_index=captured["candidate_index"],
                expected_candidate_id=captured["candidate_id"], intraday_data_file=data)

        return self._start("run", operation, lambda studies: self._apply(studies, captured=captured, data_locator=data_locator))

    def _study(self, index):
        if type(index) is not int or index not in range(3) or not self._studies:
            raise ValueError("Run the three procedures before selecting a completed study.")
        return self._studies[index]

    @Slot(int, str, result=bool)
    def saveStudy(self, index: int, raw_path: str) -> bool:
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            study, path = self._study(index), _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._invalid(exc)

        def operation(backend):
            from ..research.strategy_experiment import write_strategy_experiment
            return write_strategy_experiment(study, path=path)

        def saved(result):
            self._saved_paths[index] = str(result.path)

        return self._start("save", operation, saved)

    @Slot(int, result=bool)
    def viewStudy(self, index: int) -> bool:
        self._assert_thread()
        if self.busy or self._runtime.busy:
            return False
        try:
            study = self._study(index)
        except (TypeError, ValueError) as exc:
            return self._invalid(exc)
        controller = self._controllers[index]
        if controller.busy:
            return False
        options = {"path": self._saved_paths[index]}
        if index:
            options["completed_signature"] = self._completed_signature
        controller._apply(study, **options)
        self.sectionRequested.emit((5, 7, 9)[index])
        return True

    @Slot(result=bool)
    def compareSaved(self) -> bool:
        self._assert_thread()
        if self.busy or self._runtime.busy or self._comparison.busy:
            return False
        if not self.canCompare:
            return self._invalid(ValueError("Save all three completed studies before comparing the complete family."))
        if not self._comparison.adopt_saved_family(self._studies, tuple(self._saved_paths)):
            return self._invalid(ValueError(self._comparison.studyError or self._comparison.error))
        if not self._comparison.runComparison():
            return self._invalid(ValueError(self._comparison.studyError or self._comparison.error))
        self._notice, self._study_error = "", ""
        self.changed.emit()
        self.sectionRequested.emit(10)
        return True
