"""Captured native presentation of recorded sample-use and market evidence."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .controllers import PageController
from .table_model import QtTableModel


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _text(value):
    if value is None:
        return "—"
    if type(value) is bool:
        return "YES" if value else "NO"
    return str(value)


def _support_text(value):
    return " / ".join(str(value[key]) for key in
                      ("different_sample_count", "incomplete_evidence_sample_count", "applicable_sample_count"))


class IntradaySampleUsageController(PageController):
    changed = Signal()
    resultChanged = Signal()
    tableChanged = Signal()
    choicesChanged = Signal()

    def __init__(self, runtime, *, parent):
        super().__init__(runtime, parent=parent)
        self._source_path, self._manifest_path, self._data_locator = "", "", ""
        self._source, self._root, self._source_ready = {}, {}, False
        self._revision, self._cost_index, self._candidate_index = 0, 0, 0
        self._pending, self._completed_key = None, None
        self._study_error, self._notice, self._saved_path = "", "", ""
        self._report, self._bound_source, self._result_summary = {}, {}, {}
        self._complete_report, self._completed_details = "", ""
        self._view_index, self._stage_index, self._sample_index, self._bar_scope_index = 0, 0, 0, 0
        self._page, self._columns, self._rows, self._evidence_rows = 1, (), (), []
        self._page_evidence = None
        self._model = QtTableModel(parent=self)
        self._set_page()
        self.operationFailed.connect(self._failed)

    def _key(self, action="run"):
        if action == "save":
            return self._report.get("sample_usage_id")
        return (self._revision, self._source_path, self._source.get("content_sha256"),
                self._cost_index, self._candidate_index, self._manifest_path, self._data_locator)

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
    def manifestPath(self):
        return self._manifest_path

    @Slot(str)
    def setManifestPath(self, value):
        if value != self._manifest_path:
            self._manifest_path = value
            self._input_changed()

    @Property(str, notify=changed)
    def dataLocator(self):
        return self._data_locator

    @Slot(str)
    def setDataLocator(self, value):
        if value != self._data_locator:
            self._data_locator = value
            self._input_changed()

    @Property("QVariantMap", notify=changed)
    def sourceInfo(self):
        return {key: value for key, value in self._source.items() if key != "content"}

    @Property(bool, notify=changed)
    def ordinarySource(self):
        return self._source.get("source_kind") == "ORDINARY"

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

    @Property(str, notify=changed)
    def inputReason(self):
        if not self._source_ready:
            return "OPEN_SOURCE"
        try:
            from .quant_research import _experiment_file_path
            if str(_experiment_file_path(self._source_path)) != self._source["path"]:
                return "OPEN_CHANGED"
        except (OSError, TypeError, ValueError):
            return "OPEN_CHANGED"
        if self.ordinarySource:
            candidate = self._root["report"]["groups"][self._cost_index]["results"][self._candidate_index]
            if candidate["strategy"]["kind"] not in ("RIDGE", "QUADRATIC_RIDGE"):
                return "LEARNED_CANDIDATE_REQUIRED"
        return "" if self._manifest_path.strip() else "MANIFEST_REQUIRED"

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

    @Property(str, notify=changed)
    def savedPath(self):
        return self._saved_path

    @Property("QVariantMap", notify=resultChanged)
    def boundSource(self):
        return dict(self._bound_source)

    @Property("QVariantMap", notify=resultChanged)
    def resultSummary(self):
        return deepcopy(self._result_summary)

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
        return ["overview", "stages", "samples", "bars"]

    @Property("QStringList", constant=True)
    def barScopeOptions(self):
        return ["sample_support", "stage_prices", "all_market_rows"]

    @Property(int, notify=tableChanged)
    def viewIndex(self):
        return self._view_index

    @Property(int, notify=tableChanged)
    def stageIndex(self):
        return self._stage_index

    @Property(int, notify=tableChanged)
    def sampleIndex(self):
        return self._sample_index

    @Property(int, notify=tableChanged)
    def barScopeIndex(self):
        return self._bar_scope_index

    def _stage(self):
        return self._report["stages"][self._stage_index] if self._report and self._report["stages"] else None

    def _observations(self):
        return self._report["dependency_evidence"]["observations"] if self._report else []

    @Property("QVariantList", notify=choicesChanged)
    def stageOptions(self):
        return [{key: stage[key] for key in ("stage_index", "stage_kind", "scope", "fold_index")}
                | {"sample_count": stage["recorded_sample_count"], "price_count": stage["recorded_price_slot_count"]}
                for stage in self._report.get("stages", [])]

    @Property("QVariantMap", notify=tableChanged)
    def stageSummary(self):
        return deepcopy(self._stage() or {})

    @Property("QVariantList", notify=choicesChanged)
    def sampleOptions(self):
        stage, observations = self._stage(), self._observations()
        return [{"sample_ref": index, **{key: observations[index][key] for key in ("observation_key", "trading_day", "slot")}}
                for index in stage["sample_refs"]] if stage else []

    def _sample_ref(self):
        stage = self._stage()
        return stage["sample_refs"][self._sample_index] if stage and stage["sample_refs"] else None

    @Property(QObject, constant=True)
    def tableModel(self):
        return self._model

    def _set_page(self):
        from ..console.models import TablePage
        start = (self._page - 1) * 100
        self._model.set_page(TablePage(self._columns, self._rows[start:start + 100], self._page, 100, len(self._rows)))
        self._page_evidence = None
        self.tableChanged.emit()

    def _bar_indices(self):
        market = self._report["dependency_evidence"]["market_evidence"]
        if self._bar_scope_index == 2:
            return list(range(len(market["rows"])))
        stage = self._stage()
        if self._bar_scope_index == 1:
            return stage["price_row_refs"] if stage else []
        reference = self._sample_ref()
        if reference is None:
            return []
        observation = self._observations()[reference]
        indices = set(observation["feature_support"]["bar_indices"])
        if observation["target"] is not None:
            target = observation["target"]
            indices.update(target["completeness_support"]["bar_indices"])
            if target["endpoints"] is not None:
                indices.update(endpoint["bar_index"] for endpoint in target["endpoints"].values())
        return sorted(indices)

    def _refresh(self):
        self._page, self._columns, self._rows, self._evidence_rows = 1, (), (), []
        if self._report:
            self._columns, records, self._evidence_rows = self._table()
            self._rows = tuple(tuple(_text(record.get(key)) for key in self._columns) for record in records)
        self._set_page()

    def _table(self):
        report, observations = self._report, self._observations()
        if self._view_index == 0:
            fields = {"status": report["status"], "source_kind": report["source"]["source_kind"],
                      "study_status": report["source"]["study_status"], **report["summary"],
                      **report["binding"], **report["analysis_actions"]}
            records = [{"fact": key, "value": value} for key, value in fields.items()]
            return ("fact", "value"), records, records
        if self._view_index == 1:
            columns = ("stage_index", "scope", "stage_kind", "usage", "recorded_sample_count", "actual_used_count",
                       "feature_usage", "label_usage", "fit_origin", "feature_window", "target_endpoints",
                       "target_completeness", "recorded_price_slot_count", "actual_used_price_slot_count")
            records = [{**stage, **{key: _support_text(value) for key, value in stage["support_counts"].items()}}
                       for stage in report["stages"]]
            return columns, records, report["stages"]
        if self._view_index == 2:
            columns = ("observation_key", "trading_day", "slot", "observation_status", "sample_target_status",
                       "feature_bar_links", "feature_different_links", "target_bar_links", "target_different_links",
                       "session_end_shortfall", "entry_evidence", "exit_evidence")
            records, evidence = [], []
            for reference in (self._stage() or {}).get("sample_refs", []):
                observation = observations[reference]
                target, feature = observation["target"], observation["feature_support"]["counts"]
                completeness = target["completeness_support"] if target else None
                endpoints = target["endpoints"] if target else None
                records.append({**observation, "sample_target_status": target["status"] if target else "NO_TARGET",
                    "feature_bar_links": feature["bar_links"], "feature_different_links": feature["comparison_status_counts"]["DIFFERENT"],
                    "target_bar_links": completeness["counts"]["bar_links"] if completeness else None,
                    "target_different_links": completeness["counts"]["comparison_status_counts"]["DIFFERENT"] if completeness else None,
                    "session_end_shortfall": completeness["session_end_shortfall"] if completeness else None,
                    **{role + "_evidence": endpoints[role]["evidence_status"] if endpoints else None for role in ("entry", "exit")}})
                evidence.append({"sample_ref": reference, "observation": observation})
            return columns, records, evidence
        market = report["dependency_evidence"]["market_evidence"]
        indices = self._bar_indices()
        columns = ("bar_index", "trading_day", "slot", "row_version_id", "local_state", "comparison_local_state",
                   "reference_state", "status", "open", "close", "volume")
        records = [{"bar_index": index, **market["rows"][index], **(market["rows"][index]["local_values"] or {})} for index in indices]
        return columns, records, [{"bar_index": index, "bar": market["rows"][index]} for index in indices]

    @Property(str, notify=tableChanged)
    def currentPageEvidence(self):
        if not self._report:
            return ""
        if self._page_evidence is None:
            start = (self._page - 1) * 100
            rows = self._evidence_rows[start:start + 100]
            value = {"sample_usage_id": self._report["sample_usage_id"], "completed_source": self._bound_source,
                     "binding": self._report["binding"], "view": self.viewOptions[self._view_index],
                     "page": self._page, "total_rows": len(self._rows), "rows": rows}
            if self._view_index in (2, 3):
                value["stage"] = self._stage()
            if self._view_index == 3:
                value["bar_scope"] = self.barScopeOptions[self._bar_scope_index]
                reference = self._sample_ref() if self._bar_scope_index == 0 else None
                value["sample"] = None if reference is None else {"sample_ref": reference, "observation": self._observations()[reference]}
                indices = {row["bar"]["reference_index"] for row in rows}
                market = self._report["dependency_evidence"]["market_evidence"]
                value["references"] = [item for item in market["references"] if item["reference_index"] in indices]
            self._page_evidence = _json(value)
        return self._page_evidence

    @Slot(int, result=bool)
    def selectView(self, index):
        if type(index) is not int or not 0 <= index < len(self.viewOptions):
            return False
        if index != self._view_index:
            self._view_index = index
            self._refresh()
        return True

    @Slot(int, result=bool)
    def selectStage(self, index):
        if type(index) is not int or not 0 <= index < len(self._report.get("stages", [])):
            return False
        if index != self._stage_index:
            self._stage_index, self._sample_index = index, 0
            self.choicesChanged.emit()
            self._refresh()
        return True

    @Slot(int, result=bool)
    def selectSample(self, index):
        if type(index) is not int or not 0 <= index < len((self._stage() or {}).get("sample_refs", [])):
            return False
        if index != self._sample_index:
            self._sample_index = index
            self._refresh()
        return True

    @Slot(int, result=bool)
    def selectBarScope(self, index):
        if type(index) is not int or not 0 <= index < len(self.barScopeOptions):
            return False
        if index != self._bar_scope_index:
            self._bar_scope_index = index
            self._refresh()
        return True

    @Slot(int, result=bool)
    def changePage(self, delta):
        if type(delta) is not int:
            return False
        page = self._page + delta
        if not 1 <= page <= max(1, (len(self._rows) + 99) // 100):
            return False
        self._page = page
        self._set_page()
        return True

    def _start(self, action, operation, apply):
        key = self._key(action)
        self._pending = action, key
        self._study_error, self._notice = "", ""

        def completed(value):
            self._pending = None
            if key != self._key(action):
                self._notice = "STALE_INPUT"
            else:
                apply(value)
            self.changed.emit()

        accepted = self._submit("intraday_sample_usage_" + action, operation, completed, requires_backend=False)
        if not accepted:
            self._pending = None
        self.changed.emit()
        return accepted

    def _failed(self):
        pending, self._pending = self._pending, None
        if pending is not None:
            if pending[1] == self._key(pending[0]):
                self._study_error = self.error
            else:
                self._notice, self._error, self._status = "STALE_INPUT", "", "STALE_INPUT"
                self.stateChanged.emit()
            self.changed.emit()

    def _input_error(self, exc):
        self._study_error = str(exc)
        self.changed.emit()
        return self._reject_input(exc)

    @Slot(result=bool)
    def openSource(self):
        if self.busy or self._runtime.busy:
            return False
        self._source_ready = False
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(self._source_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._input_error(exc)

        def operation(backend):
            from ..research.intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
            from ..research.intraday_inner_selection import INTRADAY_INNER_SELECTION_VERSION
            from ..research.intraday_threshold_selection import INTRADAY_THRESHOLD_SELECTION_VERSION
            from ..research.intraday_joint_selection import INTRADAY_JOINT_SELECTION_VERSION
            from ..research.strategy_experiment import load_strategy_experiment
            snapshot = load_strategy_experiment(path)
            root = snapshot.as_dict()
            schema = root["artifact_schema_version"]
            kinds = {INTRADAY_INNER_SELECTION_VERSION: "INNER_MODEL_SELECTION",
                     INTRADAY_THRESHOLD_SELECTION_VERSION: "ECONOMIC_THRESHOLD_SELECTION",
                     INTRADAY_JOINT_SELECTION_VERSION: "JOINT_ECONOMIC_SELECTION"}
            if schema in INTRADAY_EXPERIMENT_VERSIONS and root["evaluation_mode"] in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS"):
                if not any(row["strategy"]["kind"] in ("RIDGE", "QUADRATIC_RIDGE")
                           for group in root["report"]["groups"] for row in group["results"]):
                    raise ValueError("The saved DEV source contains no supported learned candidate.")
                kind = "ORDINARY"
            elif schema in kinds:
                kind = kinds[schema]
            else:
                raise ValueError("Open an ordinary learned DEV source or saved Q25/Q31/Q36 study.")
            return root, {"path": str(path), "name": root["name"], "source_kind": kind,
                          "experiment_id": root["experiment_id"], "content": snapshot.content,
                          "content_sha256": sha256(snapshot.content).hexdigest()}

        def opened(value):
            self._root, self._source = value
            self._source_ready, self._cost_index, self._candidate_index = True, 0, 0
            self._revision += 1

        return self._start("open", operation, opened)

    @Slot(result=bool)
    def runSelected(self):
        if self.busy or self._runtime.busy:
            return False
        try:
            from .quant_research import _experiment_file_path
            if not self.canRun:
                raise ValueError("Open the saved source, select a learned candidate and provide an explicit market-evidence manifest.")
            manifest = _experiment_file_path(self._manifest_path)
            locator = _experiment_file_path(self._data_locator) if self._data_locator.strip() else None
            content, cost, candidate = self._source["content"], self._cost_index, self._candidate_index
            captured = {"opened_source_path": self._source["path"], "opened_source_content_sha256": self._source["content_sha256"],
                        "requested_cost_index": cost, "requested_candidate_index": candidate,
                        "requested_data_locator": self._data_locator, "requested_manifest_path": self._manifest_path}
        except (OSError, TypeError, ValueError) as exc:
            return self._input_error(exc)

        def operation(backend):
            from ..quality.market_data_comparison import read_json_file
            from ..research.intraday_sample_usage import analyze_intraday_sample_usage
            from ..research.strategy_experiment import StrategyExperiment
            plan = read_json_file(manifest)
            report = analyze_intraday_sample_usage(StrategyExperiment(content), plan, cost_index=cost,
                candidate_index=candidate, intraday_data_file=locator, base=manifest.parent)
            return report, _json(report)

        def analyzed(value):
            report, serialized = value
            dependency = report["dependency_evidence"]
            self._report, self._complete_report = report, serialized
            self._bound_source = {**captured, "sample_usage_id": report["sample_usage_id"]}
            self._completed_key, self._saved_path = self._key(), ""
            self._result_summary = {key: report[key] for key in ("status", "source", "binding", "summary")}
            self._result_summary.update(market_status=dependency["market_evidence"]["status"],
                market_summary=dependency["market_evidence"]["summary"], observation_count=dependency["summary"]["observation_count"],
                target_horizon_bars=dependency["sampling"]["target_horizon_bars"])
            self._completed_details = _json({"capture": self._bound_source, **{key: report[key] for key in
                ("version", "sample_usage_id", "status", "source", "binding", "analysis_actions", "summary", "limitations")}})
            self._stage_index, self._sample_index, self._bar_scope_index = 0, 0, 0
            self.choicesChanged.emit()
            self._refresh()
            self.resultChanged.emit()

        return self._start("run", operation, analyzed)

    @Slot(str, result=bool)
    def saveReport(self, raw_path):
        if self.busy or self._runtime.busy or not self._report:
            return False
        try:
            from .quant_research import _experiment_file_path
            path = _experiment_file_path(raw_path)
        except (OSError, TypeError, ValueError) as exc:
            return self._input_error(exc)
        report = self._report

        def operation(backend):
            from ..quality.market_data_comparison import write_market_data_json
            from ..storage.atomic_file import AtomicFilePublicationError
            try:
                return str(write_market_data_json(path, report))
            except AtomicFilePublicationError as exc:
                raise ValueError(f"Report publication failed (published={exc.published}): {exc}") from exc

        def saved(value):
            self._saved_path = value

        return self._start("save", operation, saved)
