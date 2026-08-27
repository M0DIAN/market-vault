"""Fail-closed Storage & Cleanup controller for the QML desktop."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from market_vault.desktop.controllers import TablePageController
from market_vault.desktop.runtime import DesktopOperationRuntime


SCOPE_FIELDS = (
    "source",
    "symbols",
    "start_date",
    "end_date",
    "interval",
    "session",
    "adjustment",
    "source_schema_version",
)


class StorageCleanupController(TablePageController):
    """Own reviewed-plan state and delegate mutation to ConsoleBackend only."""

    reviewChanged = Signal()

    def __init__(
        self,
        runtime: DesktopOperationRuntime,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(runtime, parent=parent)
        self._scope = {
            "source": "moomoo",
            "symbols": "US.SPY",
            "start_date": "",
            "end_date": "",
            "interval": "1m",
            "session": "ALL",
            "adjustment": "NONE",
            "source_schema_version": "10.9",
        }
        if runtime.settings_path is not None:
            try:
                from market_vault.config import load_settings

                settings = load_settings(runtime.settings_path)
            except Exception:
                # Defaults remain usable when optional presentation hints cannot load.
                pass
            else:
                self._scope["source"] = settings.source
                self._scope["source_schema_version"] = settings.source_schema_version
        self._plan_id = ""
        self._plan_status = "UNREVIEWED"
        self._plan_executable = False
        self._reviewed_fingerprint = ""
        self._confirmation = ""
        self._refusal_reasons: list[dict[str, Any]] = []

    @Property("QVariantMap", notify=reviewChanged)
    def scope(self) -> dict[str, str]:
        return dict(self._scope)

    @Property(str, notify=reviewChanged)
    def planId(self) -> str:  # noqa: N802
        return self._plan_id

    @Property(str, notify=reviewChanged)
    def planStatus(self) -> str:  # noqa: N802
        return self._plan_status

    @Property(bool, notify=reviewChanged)
    def planExecutable(self) -> bool:  # noqa: N802
        return self._plan_executable

    @Property(str, notify=reviewChanged)
    def confirmation(self) -> str:
        return self._confirmation

    @Property("QVariantList", notify=reviewChanged)
    def refusalReasons(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(item) for item in self._refusal_reasons]

    @Property(bool, notify=reviewChanged)
    def executeEnabled(self) -> bool:  # noqa: N802
        return (
            self._plan_executable
            and bool(self._plan_id)
            and self._reviewed_fingerprint == self._scope_fingerprint()
            and self._confirmation == f"PURGE {self._plan_id}"
            and not self.busy
            and not self._runtime.busy
        )

    def _scope_fingerprint(self) -> str:
        payload = json.dumps(
            self._scope, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _invalidate_review(self) -> None:
        self._plan_id = ""
        self._plan_status = "UNREVIEWED"
        self._plan_executable = False
        self._reviewed_fingerprint = ""
        self._confirmation = ""
        self._refusal_reasons = []
        backend = self._runtime.backend_if_initialized
        if backend is not None and not self._runtime.busy:
            backend.invalidate_purge_preview()
        self.reviewChanged.emit()

    @Slot(str, str, result=bool)
    def setScopeField(self, name: str, value: str) -> bool:  # noqa: N802
        if name not in SCOPE_FIELDS:
            return False
        if self._runtime.busy and self._runtime.activeOperation == "storage_execute":
            return False
        normalized = str(value)
        if self._scope[name] == normalized:
            return True
        self._scope[name] = normalized
        self._invalidate_review()
        return True

    @Slot(str)
    def setConfirmation(self, value: str) -> None:  # noqa: N802
        if self._confirmation == value:
            return
        self._confirmation = value
        self.reviewChanged.emit()

    @Slot(result=bool)
    def review(self) -> bool:
        sealed_scope = dict(self._scope)
        fingerprint = self._scope_fingerprint()

        def apply(plan: Any) -> None:
            if fingerprint != self._scope_fingerprint():
                backend = self._runtime.backend_if_initialized
                if backend is not None:
                    backend.invalidate_purge_preview()
                raise RuntimeError("Storage scope changed while review was running.")
            self._plan_id = str(plan.plan_id)
            self._plan_status = str(plan.status)
            self._plan_executable = bool(plan.executable)
            self._reviewed_fingerprint = fingerprint
            self._confirmation = ""
            self._refusal_reasons = [dict(item) for item in plan.refusal_reasons]
            self._set_page(plan.items)
            self._summary = {str(k): str(v) for k, v in plan.summary.items()}
            self.reviewChanged.emit()

        return self._submit(
            "storage_review",
            lambda backend: backend.preview_purge(**sealed_scope),
            apply,
        )

    @Slot(str, str, result=bool)
    def execute_purge(self, plan_id: str, confirmation: str) -> bool:
        """Execute only the exact Python-owned reviewed plan and confirmation."""

        if (
            not self.executeEnabled
            or plan_id != self._plan_id
            or confirmation != self._confirmation
        ):
            self._status = "FAILED"
            self._error = "Review an executable plan and enter its exact confirmation."
            self.stateChanged.emit()
            return False
        fingerprint = self._reviewed_fingerprint

        def apply(result: dict[str, Any]) -> None:
            if fingerprint != self._scope_fingerprint():
                raise RuntimeError("Storage scope changed during execution.")
            self._summary = {str(k): str(v) for k, v in result.items()}
            self._plan_status = str(result.get("status", "SUCCESS"))
            self._plan_executable = False
            self._confirmation = ""
            self.reviewChanged.emit()

        return self._submit(
            "storage_execute",
            lambda backend: backend.execute_purge(
                plan_id=plan_id, confirmation=confirmation
            ),
            apply,
        )
