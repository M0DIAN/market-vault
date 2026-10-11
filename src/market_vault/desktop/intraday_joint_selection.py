"""Native joint-family evidence, reusing immutable threshold-study actions."""

from __future__ import annotations

from copy import deepcopy
import json

from PySide6.QtCore import Property

from .intraday_research import execution_series
from .intraday_threshold_selection import IntradayThresholdSelectionController


class IntradayJointSelectionController(IntradayThresholdSelectionController):
    """Keep Q36 state separate while sharing Q31's captured-action lifecycle."""

    _study_id_key = "joint_selection_id"
    _operation_prefix = "intraday_joint_"
    _study_title = "intraday joint economic-selection study"
    _source_requirement = "Select an ordinary saved DEV linear or quadratic Ridge candidate with 1 to 6 Features."
    _metric_columns = ("threshold_account", "candidate_index", "strategy_kind", "alpha", "threshold_bps",
                       "threshold_chosen", "metric", "value", "unit", "unavailable_reason")
    _model_columns = ("fold_index", "joint_model_index", "strategy_kind", "alpha", "model_threshold_bps",
                      "model_stage", "feature", "training_count", "intercept", "coefficient",
                      "mean", "scale", "model_id", "training_boundary")

    @Property(bool, notify=IntradayThresholdSelectionController.changed)
    def canRun(self):
        # PySide properties delegate through fget; super().canRun is the
        # Property descriptor itself rather than the base getter's value.
        return bool(IntradayThresholdSelectionController.canRun.fget(self) and 1 <= len(self._research._root["report"]["context"]["feature_fields"]) <= 6)

    def _schema_version(self):
        from ..research.intraday_joint_selection import INTRADAY_JOINT_SELECTION_VERSION
        return INTRADAY_JOINT_SELECTION_VERSION

    def _run_study(self, captured, data):
        from ..research.intraday_joint_selection import run_intraday_joint_selection
        return run_intraday_joint_selection(captured["path"], expected_experiment_id=captured["experiment_id"],
            cost_index=captured["cost_index"], candidate_index=captured["candidate_index"],
            expected_candidate_id=captured["candidate_id"], intraday_data_file=data, name="Intraday joint economic selection")

    @Property("QVariantList", notify=IntradayThresholdSelectionController.changed)
    def accountOptions(self):
        if not self._root or self._window() is None:
            return IntradayThresholdSelectionController.accountOptions.fget(self)
        selected = self._window()["selected_index"]
        return [{"kind": "JOINT_MEMBER", "candidate_index": index,
                 "model_index": index // len(self._root["report"]["method"]["thresholds"]),
                 "strategy_kind": member["kind"], "alpha": member["alpha"],
                 "threshold_bps": member["threshold"] * 10000, "chosen": index == selected}
                for index, member in enumerate(self._root["report"]["method"]["family"])]

    def _account_metadata(self, option):
        result = super()._account_metadata(option)
        if option["kind"] == "JOINT_MEMBER":
            result.update(candidate_index=option["candidate_index"], strategy_kind=option["strategy_kind"],
                          alpha=option["alpha"], threshold_chosen="YES" if option["chosen"] else "NO")
        elif option["kind"] == "FIXED_REFERENCE":
            strategy = self._source_parts()[2]["strategy"]
            result.update(strategy_kind=strategy["kind"], alpha=strategy["alpha"], threshold_bps=strategy["threshold"] * 10000)
        return result

    @Property("QVariantMap", notify=IntradayThresholdSelectionController.changed)
    def scopeSummary(self):
        result = IntradayThresholdSelectionController.scopeSummary.fget(self)
        window = self._window()
        if window is not None:
            result.update(model_count=len(window["models"]), account_count=len(window["family_results"]))
            if self._scope_index <= len(self._root["report"]["outer_folds"]):
                refit = self._root["report"]["outer_folds"][self._scope_index - 1]["refit"]
                if refit is not None:
                    result.update(refit_model_id=refit["model"]["model_id"],
                        refit_training_boundary=refit["model"]["training_boundary"],
                        refit_training_count=len(refit["model"]["training_keys"]))
        return result

    @Property(str, notify=IntradayThresholdSelectionController.changed)
    def completedDetails(self):
        if not self._root:
            return ""
        details = json.loads(IntradayThresholdSelectionController.completedDetails.fget(self))
        report = self._root["report"]
        details.update(evaluation_mode=self._root["evaluation_mode"], source_reconstruction=report["source_reconstruction"],
            outer_choices=[{"fold_id": row["fold_id"], "selected_index": row["inner"]["selected_index"],
                            "selected_recipe": row["inner"]["selected_recipe"],
                            "refit_model_id": row["refit"]["model"]["model_id"] if row["refit"] else None}
                           for row in report["outer_folds"]],
            final_dev_recipe=report["final_dev"]["selected_recipe"])
        return json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)

    @Property(str, notify=IntradayThresholdSelectionController.changed)
    def viewNotice(self):
        notice = IntradayThresholdSelectionController.viewNotice.fget(self)
        return {"SHARED_MODEL_DECISIONS": "SIX_SHARED_MODELS", "OUTER_FIXED_SCORES": "OUTER_WINNER_REFITS"}.get(notice, notice)

    @Property("QVariantList", notify=IntradayThresholdSelectionController.changed)
    def equitySeries(self):
        if self._window() is None:
            return IntradayThresholdSelectionController.equitySeries.fget(self)
        account = self._account()
        return [execution_series(account["execution"])] if account is not None else []

    @Property("QVariantList", notify=IntradayThresholdSelectionController.changed)
    def equityOptions(self):
        if self._window() is None:
            return IntradayThresholdSelectionController.equityOptions.fget(self)
        return [self.accountOptions[self._account_index]] if self._account() is not None else []

    @staticmethod
    def _model_identity(strategy, model_index=None):
        return {"strategy_kind": strategy["kind"], "joint_model_index": model_index,
                "model_threshold_bps": strategy["threshold"] * 10000}

    def _models(self):
        window = self._window()
        if window is not None:
            # Exactly six records: the complete models and their raw scores are
            # shared evidence, whereas account decisions use the actual threshold.
            return [{"fold_index": "—", **deepcopy(row),
                     "identity": self._model_identity(row["strategy"], row["model_index"])}
                    for row in window["models"]]
        if self._account_index == 0:
            return [{"fold_index": index, **deepcopy(row["refit"]),
                     "selected_index": row["inner"]["selected_index"],
                     "identity": self._model_identity(row["refit"]["strategy"])}
                    for index, row in enumerate(self._root["report"]["outer_folds"]) if row["refit"]]
        if self._account_index == 1:
            reference = self._source_parts()[2]
            return [{"fold_index": index, "model": deepcopy(row["model"]), "strategy": deepcopy(reference["strategy"]),
                     "identity": self._model_identity(reference["strategy"])}
                    for index, row in enumerate(reference["fold_models"])]
        return []
