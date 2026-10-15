"""Native offline saved-account forward observation entry (Q83).

Presentation only: the v1/v2/v3 forward research reader remains the sole
authority for scope, identities, clocks, matching, and publication semantics.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from PySide6.QtCore import Property, Signal, Slot

from .controllers import PageController


def _optional_index(value, field: str) -> int | None:
    if value is None or value == "":
        return None
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and re.fullmatch(r"(0|[1-9][0-9]*)", value):
        return int(value)
    raise ValueError(f"{field} must be blank or an explicit nonnegative integer")


def _mode_and_paths(values: dict) -> tuple[str, Path, Path, Path, int | None, int | None]:
    # Desktop path parsing is identical to the existing explicit saved-file
    # controller: no working-directory relative locators or remote QUrl.
    from .quant_research import _experiment_file_path

    mode = values.get("mode")
    if mode not in ("TEMPLATE", "RECONCILE"):
        raise ValueError("Select template export or observation reconciliation.")
    experiment = _experiment_file_path(values.get("experiment_path", ""))
    source_field = "declaration_path" if mode == "TEMPLATE" else "observations_path"
    source = _experiment_file_path(values.get(source_field, ""))
    output = _experiment_file_path(values.get("output_path", ""))
    if len({experiment, source, output}) != 3:
        raise ValueError("Experiment, input, and new output paths must be different.")
    cost = _optional_index(values.get("cost_index"), "cost_index")
    candidate = _optional_index(values.get("candidate_index"), "candidate_index")
    if mode == "RECONCILE" and (cost is not None or candidate is not None):
        raise ValueError("Cost/candidate indices apply only to template export.")
    if mode == "TEMPLATE" and ((cost is None) != (candidate is None)):
        raise ValueError("Supply both ordinary DEV indices, or leave both blank for procedure/TEST.")
    return mode, experiment, source, output, cost, candidate


def _scope(version: str) -> str:
    if version.endswith("-v3"):
        return "SAVED_TEST"
    if version.endswith("-v2"):
        return "SELECTED_PROCEDURE_DEV"
    return "ORDINARY_DEV"


def _presentation(mode: str, payload: dict, output: Path) -> dict:
    if mode == "TEMPLATE":
        identities = {key.removeprefix("expected_"): value for key, value in payload.items()
                      if key.startswith("expected_")}
        identities.update({key: payload[key] for key in ("cost_index", "candidate_index") if key in payload})
        result = {
            "mode": mode, "status": "TEMPLATE_CREATED", "scope": _scope(payload["schema_version"]),
            "output": str(output), "identities": identities,
            "summary": {"reference_action_count": len(payload["records"]),
                        "supplied_record_count": len(payload["records"]),
                        "measured_quote_count": None, "missing_record_count": None,
                        "unmatched_record_count": None, "quote_policy_exceeded_count": None},
            "statistics": {}, "forward_capture_verified": False, "fills_verified": False,
        }
    else:
        source = payload["source"]
        identities = {k: source[k] for k in
                      ("experiment_id", "execution_id", "candidate_id", "procedure_id",
                       "selection_id", "final_test_id", "data_id", "cost_index", "candidate_index")
                      if k in source}
        result = {
            "mode": mode, "status": payload["status"], "scope": _scope(payload["version"]),
            "output": str(output), "identities": identities,
            "summary": deepcopy(payload["summary"]), "statistics": deepcopy(payload["statistics"]),
            "forward_capture_verified": payload["forward_capture_verified"],
            "fills_verified": payload["fills_verified"],
        }
    return result


class IntradayForwardController(PageController):
    """Capture explicit local inputs for one independent asynchronous worker."""

    changed = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._draft: dict = {}
        self._revision = 0
        self._pending: int | None = None
        self._result: dict = {}
        self._notice = ""
        self.operationFailed.connect(self._failed)

    @Property(bool, notify=changed)
    def resultLoaded(self) -> bool:
        return bool(self._result)

    @Property("QVariantMap", notify=changed)
    def resultSummary(self) -> dict:
        return deepcopy(self._result.get("summary", {}))

    @Property("QVariantMap", notify=changed)
    def sourceIdentities(self) -> dict:
        return deepcopy(self._result.get("identities", {}))

    @Property("QVariantMap", notify=changed)
    def statistics(self) -> dict:
        return deepcopy(self._result.get("statistics", {}))

    @Property(str, notify=changed)
    def resultStatus(self) -> str:
        return self._result.get("status", "")

    @Property(str, notify=changed)
    def resultScope(self) -> str:
        return self._result.get("scope", "")

    @Property(str, notify=changed)
    def resultMode(self) -> str:
        return self._result.get("mode", "")

    @Property(str, notify=changed)
    def outputPath(self) -> str:
        return self._result.get("output", "")

    @Property(str, notify=changed)
    def notice(self) -> str:
        return self._notice

    @Property(bool, notify=changed)
    def forwardCaptureVerified(self) -> bool:
        return self._result.get("forward_capture_verified", False)

    @Property(bool, notify=changed)
    def fillsVerified(self) -> bool:
        return self._result.get("fills_verified", False)

    @Slot("QVariantMap")
    def setDraft(self, values: dict) -> None:
        captured = dict(values)
        if captured != self._draft:
            self._draft = captured
            self._revision += 1
            self._result = {}  # Never label an old result as the new draft.
            self._notice = "INPUT_CHANGED" if self._pending is None else "INPUT_CHANGED_WHILE_RUNNING"
            if not self.busy:
                self._error = ""
                self.stateChanged.emit()
            self.changed.emit()

    @Slot("QVariantMap", result=bool)
    def run(self, values: dict) -> bool:
        if self.busy or self._runtime.busy:
            return False
        self.setDraft(values)
        try:
            mode, experiment, source, output, cost, candidate = _mode_and_paths(self._draft)
            # A new existing output must fail inside the same exclusive
            # publisher; do not pre-delete or pre-create anything here.
        except (OSError, TypeError, ValueError) as exc:
            self._notice = ""
            self.changed.emit()
            return self._reject_input(exc)

        submitted = self._revision
        self._pending = submitted
        self._notice = ""
        self.changed.emit()

        def operation(_backend):
            from market_vault.quality.market_data_comparison import read_json_file, write_market_data_json
            from market_vault.research.intraday_forward_reconciliation import (
                analyze_intraday_forward_reconciliation, create_intraday_forward_template,
            )
            explicit = read_json_file(source)
            if mode == "TEMPLATE":
                payload = create_intraday_forward_template(
                    experiment, explicit, cost_index=cost, candidate_index=candidate)
            else:
                payload = analyze_intraday_forward_reconciliation(experiment, explicit)
            created = write_market_data_json(output, payload)
            return _presentation(mode, payload, created)

        def completed(result):
            self._pending = None
            if submitted == self._revision:
                self._result = result
                self._notice = ""
            else:
                self._notice = "STALE_INPUT"
            self.changed.emit()

        accepted = self._submit("intraday_forward", operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
            self.changed.emit()
        return accepted

    def _failed(self) -> None:
        submitted, self._pending = self._pending, None
        if submitted is not None and submitted != self._revision:
            # Keep the current draft clean when a now-obsolete worker fails.
            self._notice = "STALE_INPUT"
            self._error = ""
            self._status = "STALE_INPUT"
            self.stateChanged.emit()
        self.changed.emit()
