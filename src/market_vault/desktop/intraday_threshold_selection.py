"""Native evidence and immutable actions for fixed-model threshold selection."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import QObject, Property, Signal, Slot

from .controllers import PageController
from .intraday_research import execution_series, formatted_rows, risk_value
from .table_model import QtTableModel


class IntradayThresholdSelectionController(PageController):
    changed = Signal()
    _study_id_key = "threshold_selection_id"
    _operation_prefix = "intraday_threshold_"
    _study_title = "intraday economic threshold-selection study"
    _source_requirement = "Select an ordinary saved DEV linear or quadratic Ridge candidate."
    _metric_columns = ("threshold_account", "threshold_bps", "threshold_chosen", "metric", "value", "unit", "unavailable_reason")
    _model_columns = ("fold_index", "model_stage", "feature", "alpha", "training_count", "intercept", "coefficient",
                      "mean", "scale", "model_id", "training_boundary")

    def __init__(self, runtime, *, research, parent):
        super().__init__(runtime, parent=parent)
        self._research = research
        self._content, self._root, self._path, self._proof = b"", {}, "", ""
        self._data_locator, self._source_locator, self._notice, self._study_error = "", "", "", ""
        self._verified_data_path, self._verified_source_path = "", ""
        self._revision, self._artifact_revision = 0, 0
        self._source_signature, self._completed_signature, self._pending = None, None, None
        self._scope_index, self._account_index, self._view_index, self._page = 0, 0, 0, 1
        self._columns, self._rows, self._evidence_rows = (), (), []
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
        return bool(self._source_signature and not self._research._collection_content
            and self._research._root.get("artifact_schema_version") in INTRADAY_EXPERIMENT_VERSIONS
            and self._research._root.get("evaluation_mode") in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")
            and self._research._selected()[1]["strategy"]["kind"] in ("RIDGE", "QUADRATIC_RIDGE"))

    @Property("QVariantMap", notify=changed)
    def draftSource(self):
        if self._source_signature is None:
            return {}
        return dict(zip(("source_path", "source_id", "candidate_id", "cost_index", "candidate_index"), self._source_signature))

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

    @Property(str, notify=changed)
    def sourceLocator(self):
        return self._source_locator

    @Slot(str)
    def setSourceLocator(self, value):
        if value != self._source_locator:
            self._source_locator = value
            self._revision += 1
            self._study_error = ""
            self.changed.emit()

    @Property(bool, notify=changed)
    def resultLoaded(self):
        return bool(self._content)

    @Property(str, notify=changed)
    def experimentPath(self):
        return self._path

    @Property(str, notify=changed)
    def proof(self):
        return self._proof

    @Property(str, notify=changed)
    def notice(self):
        return self._notice

    @Property(str, notify=changed)
    def studyError(self):
        return self._study_error

    @Property(bool, notify=changed)
    def draftChanged(self):
        return bool(self._completed_signature is not None
                    and self._completed_signature != (self._source_signature, self._data_locator))

    def _source_parts(self):
        report = self._root["report"]
        source, selection = report["source_experiment"], report["fixed_reference"]
        group = source["report"]["groups"][selection["cost_index"]]
        return source["report"]["context"], group, group["results"][selection["candidate_index"]]

    @Property("QVariantMap", notify=changed)
    def resultSummary(self):
        if not self._root:
            return {}
        report = self._root["report"]
        context, _, reference = self._source_parts()
        return {"status": report["status"], "strategy": deepcopy(reference["strategy"]),
                "fold_count": len(report["outer_folds"]), "day_count": len(context["evaluated_days"]),
                "final_recipe": deepcopy(report["final_dev"]["selected_recipe"]),
                "unavailable_reasons": deepcopy(report["unavailable_reasons"])}

    @Property("QVariantMap", notify=changed)
    def returnBasis(self):
        return deepcopy(self._root.get("report", {}).get("return_basis", {}))

    @Property(str, notify=changed)
    def completedDetails(self):
        if not self._root:
            return ""
        root, report = self._root, self._root["report"]
        context, group, reference = self._source_parts()
        details = {"experiment_id": root["experiment_id"], "study_path": self._path,
            self._study_id_key: report[self._study_id_key], "proof": self._proof,
            "source_experiment": deepcopy(root["plan"]["source_experiment"]),
            "fixed_reference": deepcopy(report["fixed_reference"]), "fixed_recipe": deepcopy(reference["strategy"]),
            "feature_fields": context["feature_fields"], "evaluated_days": context["evaluated_days"],
            "execution_policy": group["execution_policy"], "recorded_data_path": root["plan"]["intraday_data_path"],
            "verified_replay_data_path": self._verified_data_path,
            "verified_replay_source_path": self._verified_source_path, "method": report["method"],
            "return_basis": report["return_basis"], "unavailable_reasons": report["unavailable_reasons"]}
        return json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)

    @Property(int, notify=changed)
    def scopeIndex(self):
        return self._scope_index

    @Property(int, notify=changed)
    def accountIndex(self):
        return self._account_index

    @Property(int, notify=changed)
    def viewIndex(self):
        return self._view_index

    @Property("QVariantList", notify=changed)
    def scopeOptions(self):
        if not self._root:
            return []
        return [{"kind": "OUTER_ACCOUNTS", "fold_index": None}] + [
            {"kind": "OUTER_INNER", "fold_index": index} for index in range(len(self._root["report"]["outer_folds"]))
        ] + [{"kind": "FINAL_DEV", "fold_index": None}]

    def _window(self):
        if not self._root or self._scope_index == 0:
            return None
        report = self._root["report"]
        if self._scope_index == len(report["outer_folds"]) + 1:
            return report["final_dev"]
        return report["outer_folds"][self._scope_index - 1]["inner"]

    @Property("QVariantList", notify=changed)
    def accountOptions(self):
        if not self._root:
            return []
        window = self._window()
        if window is None:
            return [{"kind": kind, "threshold_bps": None, "chosen": False}
                    for kind in ("SELECTED_PROCEDURE", "FIXED_REFERENCE", "BENCHMARK")]
        return [{"kind": "THRESHOLD", "threshold_bps": value * 10000, "chosen": index == window["selected_index"]}
                for index, value in enumerate(self._root["report"]["method"]["thresholds"])]

    def _accounts(self):
        window = self._window()
        if window is not None:
            return [{"execution": row["execution"]} for row in window["family_results"]]
        report = self._root["report"]
        return [report["selected_account"], self._source_parts()[2], report["benchmark"]]

    def _account(self):
        accounts = self._accounts()
        return accounts[self._account_index] if self._account_index < len(accounts) else None

    @Property("QVariantMap", notify=changed)
    def scopeSummary(self):
        if not self._root:
            return {}
        window = self._window()
        if window is None:
            return {"kind": "OUTER_ACCOUNTS", "status": self._root["report"]["status"]}
        return {"kind": self.scopeOptions[self._scope_index]["kind"], "status": self._root["report"]["status"],
                "training_boundary": window["training_boundary"], "history_boundary": window["history_boundary"],
                "training_count": len(window["training_keys"]), "prediction_count": len(window["validation_keys"]),
                "selected_index": window["selected_index"], "selected_recipe": deepcopy(window["selected_recipe"]),
                "unavailable_reason": window["unavailable_reason"], "execution_input": deepcopy(window["execution_input"])}

    @Property(str, notify=changed)
    def viewNotice(self):
        if not self._root:
            return ""
        window = self._window()
        if window is not None:
            if self._root["report"]["status"] == "UNAVAILABLE":
                return "WHOLE_STUDY_NOT_COMPUTED"
            return "NO_INNER_FOLD_CONTRIBUTIONS" if self._view_index == 8 else "SHARED_MODEL_DECISIONS"
        if self._view_index in (9, 10):
            return "INNER_INPUTS_ONLY"
        if self._account_index == 2 and self._view_index in (1, 2, 8):
            return "BENCHMARK_NO_MODEL"
        if self._account_index == 2:
            return "BENCHMARK_ACCOUNT"
        if self._account() is None:
            return "WHOLE_STUDY_NOT_COMPUTED"
        return "OUTER_FIXED_SCORES"

    @Property("QVariantList", notify=changed)
    def equitySeries(self):
        return [execution_series(value["execution"]) for value in self._accounts() if value is not None] if self._root else []

    @Property("QVariantList", notify=changed)
    def equityOptions(self):
        if not self._root:
            return []
        return [option for option, value in zip(self.accountOptions, self._accounts()) if value is not None]

    def _models(self):
        window = self._window()
        if window is not None:
            return [{"fold_index": "—", "model": window["model"]}] if window["model"] else []
        if self._account_index == 0:
            return [{"fold_index": index, "model": row["application"]["model"]}
                    for index, row in enumerate(self._root["report"]["outer_folds"]) if row["application"]]
        if self._account_index == 1:
            return [{"fold_index": index, "model": row["model"]}
                    for index, row in enumerate(self._source_parts()[2]["fold_models"])]
        return []

    @Property(str, notify=changed)
    def currentPageEvidence(self):
        if not self._root:
            return ""
        start = (self._page - 1) * 100
        account = self._account()
        execution = account["execution"] if account is not None else {}
        evidence = {"scope": self.scopeOptions[self._scope_index], "account": self.accountOptions[self._account_index],
            "page": self._page, "summary": self.scopeSummary, "rows": self._evidence_rows[start:start + 100],
            "execution_metadata": {key: value for key, value in execution.items()
                if key not in ("decisions", "trades", "transactions", "ledger", "daily")}}
        if self._view_index == 2:
            evidence["complete_models"] = self._models()
        return json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))

    def _key_rows(self):
        window = self._window()
        if window is None:
            if self._account_index == 2 or self._account() is None:
                return []
            values = [(index, fold) for index, fold in enumerate(self._source_parts()[0]["folds"])]
            fields = ("training_boundary", "training_days", "training_keys", "purged_keys", "validation_days", "validation_keys")
        else:
            values = [("—", window)]
            fields = ("history_boundary", "training_boundary", "history_days", "history_training_keys", "history_purged_keys",
                      "training_days", "training_keys", "purged_keys", "validation_days", "validation_keys")
        rows = []
        for index, value in values:
            for field in fields:
                items = value[field] if isinstance(value[field], list) else [value[field]]
                role = field if window is not None else "OUTER_" + field.upper()
                rows.extend({"fold_index": index, "threshold_role": role, "value": item} for item in items)
            rows.extend({**target, "fold_index": index, "threshold_role": "HISTORY_TARGET",
                         "value": target["observation_key"], "label_return": target["value"]}
                        for target in value.get("history_targets", []))
        return rows

    def _model_rows(self):
        rows = []
        for record in self._models():
            model = record["model"]
            common = {"fold_index": record["fold_index"], "alpha": model["alpha"],
                      "training_count": len(model["training_keys"]), "model_id": model["model_id"],
                      "training_boundary": model["training_boundary"], **record.get("identity", {})}
            if "input_transform" in model:
                rows.extend({**common, "model_stage": "INPUT_TRANSFORM", "feature": feature,
                    "mean": model["input_transform"]["means"][index], "scale": model["input_transform"]["scales"][index]}
                    for index, feature in enumerate(model["input_features"]))
                stage, model = "GENERATED_TERMS", model["ridge_model"]
            else:
                stage = "LINEAR_FEATURES"
            rows.extend({**common, "model_stage": stage, "feature": feature, "intercept": model["intercept"],
                "coefficient": model["coefficients"][index], "mean": model["means"][index], "scale": model["scales"][index]}
                for index, feature in enumerate(model["feature_fields"]))
        return rows

    def _account_metadata(self, option):
        return {"threshold_account": option["kind"], "threshold_bps": option["threshold_bps"],
                "threshold_chosen": "YES" if option["chosen"] else "NO" if option["kind"] == "THRESHOLD" else "—"}

    def _metric_rows(self):
        rows = []
        for option, account in zip(self.accountOptions, self._accounts()):
            if account is None:
                continue
            common = self._account_metadata(option)
            for key, value in account["execution"]["metrics"].items():
                unit = ("RATIO" if key in ("total_return", "observed_max_drawdown") else
                        "COUNT" if key == "trade_count" else "INITIAL_CASH_UNITS")
                rows.append({**common, "metric": key, "value": value, "unit": unit, "unavailable_reason": None})
            for key in ("mean_daily_return", "annualized_volatility", "sharpe_ratio"):
                if "risk" in account:
                    value = account["risk"][key]
                    rows.append({**common, "metric": key, "value": value, "unit": "NUMBER" if key == "sharpe_ratio" else "RATIO",
                                 "unavailable_reason": account["risk"]["unavailable_reason"] if value is None else None})
            for key, value in account.get("prediction_metrics", {}).items():
                if key == "unavailable_reason":
                    continue
                unit = "RATIO" if key in ("mae", "rmse") else "COUNT" if key.endswith("count") else "NUMBER"
                rows.append({**common, "metric": key, "value": value, "unit": unit,
                    "unavailable_reason": account["prediction_metrics"]["unavailable_reason"] if value is None else None})
        return rows

    def _refresh(self):
        self._columns, self._rows, self._evidence_rows, self._page = (), (), [], 1
        if not self._root:
            self._set_page()
            return
        window, account, view = self._window(), self._account(), self._view_index
        execution = account["execution"] if account is not None else {}
        if view == 0:
            columns = self._metric_columns
            rows = self._metric_rows()
        elif view == 1:
            columns = ("fold_index", "threshold_role", "value", "actual_label_end_time", "label_return")
            rows = self._key_rows()
        elif view == 2:
            columns = self._model_columns
            rows = self._model_rows()
        elif view == 3:
            columns = ("observation_key", "trading_day", "slot", "decision_time", "score", "target")
            rows = execution.get("decisions", [])
        elif view == 4:
            columns = ("entry_time", "exit_time", "exit_reason", "held_bars", "cash_before", "cash_after", "net_return")
            rows = execution.get("trades", [])
        elif view == 5:
            columns = ("trading_day", "cash_open", "cash_close", "return", "trade_count")
            rows = execution.get("daily", [])
        elif view == 6:
            columns = ("timestamp", "phase", "action", "reason", "cash", "quantity", "equity", "drawdown")
            rows = execution.get("ledger", [])
        elif view == 7:
            columns = ("timestamp", "side", "reason", "quantity", "fill_price", "commission", "slippage")
            rows = execution.get("transactions", [])
        elif view == 8:
            columns = ("fold_index", "validation_days", "trade_count", "cash_contribution", "fold_id")
            rows = account.get("fold_contributions", []) if account is not None else []
        elif view == 9:
            columns = ("trading_day", "open_time", "close_time", "profile", "bar_count", "missing_bar_count")
            rows = window["sessions"] if window else []
        else:
            columns = ("trading_day", "slot", "event_time", "available_at", "open", "close", "row_version_id")
            rows = window["prices"] if window else []
        self._evidence_rows = rows
        shown = [{key: row.get(key) if row.get(key) is not None else "—" for key in columns} for row in rows]
        if view == 0:
            for item, raw in zip(shown, rows, strict=True):
                item["value"] = risk_value(raw["value"], raw["unit"])
        self._columns, self._rows = columns, formatted_rows(shown, columns)
        self._set_page()

    @Slot(int, result=bool)
    def selectScope(self, index):
        if type(index) is not int or not 0 <= index < len(self.scopeOptions):
            return False
        self._scope_index = index
        window = self._window()
        self._account_index = window["selected_index"] if window and window["selected_index"] is not None else 0
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectAccount(self, index):
        if type(index) is not int or not 0 <= index < len(self.accountOptions):
            return False
        self._account_index = index
        self._refresh()
        self.changed.emit()
        return True

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index <= 10:
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

    def _apply(self, snapshot, *, path="", opened=False):
        self._content, self._root, self._path = snapshot.content, snapshot.as_dict(), path
        self._artifact_revision += 1
        self._scope_index, self._account_index, self._view_index = 0, 0, 0
        self._completed_signature = None if opened else (self._source_signature, self._data_locator)
        self._proof, self._notice, self._study_error = "RECORDED" if opened else "COMPUTED", "", ""
        self._verified_data_path, self._verified_source_path = "", ""
        self._refresh()
        self.changed.emit()

    def _key(self, action):
        artifact = (self._root.get("experiment_id"), self._artifact_revision)
        return (self._revision, self._source_signature, self._data_locator) if action == "run" else (
            *artifact, self._revision, self._data_locator, self._source_locator) if action == "replay" else artifact

    def _start(self, action, operation, apply):
        if self.busy or self._runtime.busy:
            return False
        key = self._key(action)
        self._pending = (action, key)
        self._study_error, self._notice = "", ""

        def completed(value):
            self._pending = None
            if key != self._key(action):
                self._notice = "STALE_INPUT"
                if action == "replay" and key[:2] == self._key(action)[:2]:
                    self._proof = "REPLAY_STALE_INPUT"
                self.changed.emit()
                return
            apply(value)

        accepted = self._submit(self._operation_prefix + action, operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        self.changed.emit()
        return accepted

    def _failed(self):
        pending, self._pending = self._pending, None
        if pending is None:
            return
        action, key = pending
        if key == self._key(action):
            self._study_error = self.error
            if action == "replay":
                self._proof = "REPLAY_FAILED"
        else:
            self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
            if action == "replay" and key[:2] == self._key(action)[:2]:
                self._proof = "REPLAY_STALE_INPUT"
            self.stateChanged.emit()
        self.changed.emit()

    @Slot(result=bool)
    def runSelected(self):
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            if not self.canRun:
                raise ValueError(self._source_requirement)
            captured = self._research.selection_source()
            data = _experiment_file_path(self._data_locator) if self._data_locator.strip() else None
        except (OSError, TypeError, ValueError) as exc:
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)

        def operation(backend):
            return self._run_study(captured, data)

        return self._start("run", operation, self._apply)

    def _run_study(self, captured, data):
        from ..research.intraday_threshold_selection import run_intraday_threshold_selection
        return run_intraday_threshold_selection(captured["path"], expected_experiment_id=captured["experiment_id"],
            cost_index=captured["cost_index"], candidate_index=captured["candidate_index"],
            expected_candidate_id=captured["candidate_id"], intraday_data_file=data, name="Intraday economic threshold selection")

    def _schema_version(self):
        from ..research.intraday_threshold_selection import INTRADAY_THRESHOLD_SELECTION_VERSION
        return INTRADAY_THRESHOLD_SELECTION_VERSION

    @Slot(str, result=bool)
    def openExperiment(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def operation(backend):
            from ..research.strategy_experiment import load_strategy_experiment
            snapshot = load_strategy_experiment(path)
            if snapshot.as_dict()["artifact_schema_version"] != self._schema_version():
                raise ValueError(f"Open an {self._study_title}.")
            return snapshot

        return self._start("open", operation, lambda snapshot: self._apply(snapshot, path=str(path), opened=True))

    @Slot(str, result=bool)
    def saveExperiment(self, raw_path):
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
            if not self._content:
                raise ValueError(f"Run or open an {self._study_title} before saving.")
            content = self._content
        except (OSError, TypeError, ValueError) as exc:
            return self._reject_input(exc)

        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, write_strategy_experiment
            return write_strategy_experiment(StrategyExperiment(content), path=path)

        def saved(result):
            self._path = str(result.path)
            self.changed.emit()

        return self._start("save", operation, saved)

    @Slot(result=bool)
    def replayExperiment(self):
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            data = _experiment_file_path(self._data_locator) if self._data_locator.strip() else None
            source = _experiment_file_path(self._source_locator) if self._source_locator.strip() else None
            if not self._content:
                raise ValueError(f"Run or open an {self._study_title} before full replay.")
            content = self._content
            used_data = str(data) if data is not None else self._root["plan"]["intraday_data_path"]
            used_source = str(source) if source is not None else "EMBEDDED_SNAPSHOT"
        except (OSError, TypeError, ValueError) as exc:
            if self._content:
                self._proof = "REPLAY_FAILED"
            self._study_error = str(exc)
            self.changed.emit()
            return self._reject_input(exc)

        def operation(backend):
            from ..research.strategy_experiment import StrategyExperiment, replay_strategy_experiment
            return replay_strategy_experiment(StrategyExperiment(content), intraday_data_file=data, source_experiment_file=source)

        def verified(result):
            self._proof, self._verified_data_path = "REPLAY_MATCH", used_data
            self._verified_source_path = used_source
            self.changed.emit()

        self._proof = "REPLAY_PENDING"
        self.changed.emit()
        return self._start("replay", operation, verified)
