"""Native explicit-file presentation of the existing Q74 policy judgment."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import Property, Signal, Slot

from .controllers import PageController


class IntradayDataAcceptanceController(PageController):
    changed = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._draft = dict.fromkeys(("data_path", "manifest_path", "policy_path"), "")
        self._revision = 0
        self._pending = None
        self._report = {}
        self._receipt = {}
        self._notice = ""
        self.operationFailed.connect(self._failed)

    @Property(bool, notify=changed)
    def resultLoaded(self) -> bool:
        return bool(self._report)

    @Property(str, notify=changed)
    def resultStatus(self) -> str:
        return self._report.get("status", "")

    @Property("QVariantMap", notify=changed)
    def resultSummary(self) -> dict:
        return deepcopy(self._report.get("summary", {}))

    @Property("QVariantMap", notify=changed)
    def resultIdentities(self) -> dict:
        return {key: self._report[key] for key in
                ("data_id", "policy_id", "market_evidence_id", "market_dependencies_id", "acceptance_id")
                if key in self._report}

    @Property(str, notify=changed)
    def reportJson(self) -> str:
        return json.dumps(self._report, ensure_ascii=False, indent=2) if self._report else ""

    @Property(str, notify=changed)
    def reasonsJson(self) -> str:
        return json.dumps({key: self._report.get(key, []) for key in ("rejections", "evidence_gaps")},
                          ensure_ascii=False, indent=2) if self._report else ""

    @Property("QVariantMap", notify=changed)
    def exportReceipt(self) -> dict:
        return dict(self._receipt)

    @Property(str, notify=changed)
    def notice(self) -> str:
        return self._notice

    @Slot("QVariantMap")
    def setDraft(self, values: dict) -> None:
        captured = {key: values.get(key, "") for key in self._draft}
        if captured != self._draft:
            self._draft = captured
            self._revision += 1
            self._report, self._receipt = {}, {}
            self._notice = "INPUT_CHANGED_WHILE_RUNNING" if self._pending is not None else "INPUT_CHANGED"
            if not self.busy:
                self._error = ""
                self.stateChanged.emit()
            self.changed.emit()

    @Slot("QVariantMap", result=bool)
    def run(self, values: dict) -> bool:
        if self.busy or self._runtime.busy:
            return False
        self.setDraft(values)
        self._report, self._receipt, self._notice = {}, {}, ""
        self.changed.emit()
        try:
            from .quant_research import _experiment_file_path
            paths = {}
            for key in self._draft:
                try:
                    paths[key] = _experiment_file_path(self._draft[key])
                except ValueError as exc:
                    raise ValueError(f"{key}: choose an absolute local file path or file:/// URL.") from exc
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        submitted = self._revision
        self._pending = submitted

        def operation(_backend):
            from ..research.intraday_data_acceptance import run_intraday_data_acceptance
            return run_intraday_data_acceptance(paths["data_path"], paths["manifest_path"], paths["policy_path"])

        def completed(report):
            self._pending = None
            if submitted == self._revision:
                self._report = report
            else:
                self._notice = "STALE_INPUT"
            self.changed.emit()

        accepted = self._submit("intraday_data_acceptance", operation, completed,
            result_status=lambda report: "SUCCESS" if report["status"] == "POLICY_SATISFIED" else "PARTIAL",
            requires_backend=False)
        if not accepted:
            self._pending = None
        return accepted

    @Slot(str, result=bool)
    def exportReport(self, raw_path: str) -> bool:
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            if not self._report:
                raise ValueError("Analyze the explicit files before exporting a captured report.")
            path = _experiment_file_path(raw_path)
            captured = deepcopy(self._report)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)
        submitted = self._revision
        self._pending, self._notice, self._receipt = submitted, "", {}
        self.changed.emit()

        def operation(_backend):
            from ..quality.market_data_comparison import write_market_data_json
            return write_market_data_json(path, captured)

        def completed(created):
            self._pending = None
            if submitted == self._revision:
                self._receipt = {"path": str(created), "acceptance_id": captured["acceptance_id"]}
            else:
                self._notice = "STALE_INPUT"
            self.changed.emit()

        accepted = self._submit("intraday_data_acceptance_export", operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        return accepted

    def _failed(self) -> None:
        submitted, self._pending = self._pending, None
        if submitted is not None and submitted != self._revision:
            self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
            self.stateChanged.emit()
        self.changed.emit()
