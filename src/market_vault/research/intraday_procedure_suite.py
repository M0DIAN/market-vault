"""Run the fixed Q25, Q31 and Q36 family from one captured ordinary source.

One action strictly verifies Q5 and reconstructs the complete ordinary study
once. Each member still performs its own existing selection and retains its
original immutable artifact grammar, identity and unavailability semantics.
"""

from __future__ import annotations

from pathlib import Path

from . import intraday_inner_selection as inner
from . import intraday_joint_selection as joint
from . import intraday_threshold_selection as threshold
from .intraday_backtest import intraday_data_path
from .intraday_data import digest
from .intraday_selection_source import _prepare_selection_source
from .strategy_experiment import StrategyExperiment, canonical_json, environment_versions, load_strategy_experiment


PROCEDURE_ORDER = ("Q25", "Q31", "Q36")
_MEMBERS = (
    (inner, inner.normalize_inner_selection_plan, inner.inner_selection_versions,
     inner.INTRADAY_INNER_SELECTION_PLAN_VERSION, inner.INTRADAY_INNER_SELECTION_VERSION, "INTRADAY_INNER_SELECTION"),
    (threshold, threshold.normalize_threshold_selection_plan, threshold.threshold_selection_versions,
     threshold.INTRADAY_THRESHOLD_SELECTION_PLAN_VERSION, threshold.INTRADAY_THRESHOLD_SELECTION_VERSION,
     "INTRADAY_THRESHOLD_SELECTION"),
    (joint, joint.normalize_joint_selection_plan, joint.joint_selection_versions,
     joint.INTRADAY_JOINT_SELECTION_PLAN_VERSION, joint.INTRADAY_JOINT_SELECTION_VERSION, "INTRADAY_JOINT_SELECTION"),
)


def evaluate_intraday_procedure_suite(source: StrategyExperiment, *, source_experiment_path: str | Path,
                                     expected_experiment_id: str, cost_index: int, candidate_index: int,
                                     expected_candidate_id: str, intraday_data_file: str | Path | None = None,
                                     name: str = "", notes: str = "") -> tuple[StrategyExperiment, StrategyExperiment, StrategyExperiment]:
    """Evaluate captured immutable bytes without reopening their original path.

    The explicit path records where the caller opened this source; it is not
    used to substitute different bytes later. IDs bind the captured selection.
    All members are returned, including independently UNAVAILABLE studies.
    This API does not write files, select a winning procedure or run TEST.
    """
    if type(source) is not StrategyExperiment:
        raise ValueError("an immutable ordinary StrategyExperiment is required")
    if type(name) is not str or type(notes) is not str:
        raise ValueError("experiment name and notes must be strings")
    root = source.as_dict()
    path = intraday_data_path(str(source_experiment_path))
    comparison = root["plan"].get("comparison_plan", root["plan"])
    locator = (str(intraday_data_path(str(intraday_data_file))) if intraday_data_file is not None
               else comparison.get("intraday_data_path", ""))
    plans = []
    for module, normalize, _, plan_version, _, _ in _MEMBERS:
        plan = normalize({"plan_schema_version": plan_version,
            "source_experiment": {"path": str(path), "experiment_id": expected_experiment_id},
            "selection": {"cost_index": cost_index, "candidate_index": candidate_index,
                          "candidate_id": expected_candidate_id},
            "intraday_data_path": locator})
        # Admit all three requested procedures before data access or fitting.
        module._selected(root, plan)
        plans.append(plan)
    prepared = _prepare_selection_source(root, plans[0], label="procedure suite")
    studies = []
    for (module, _, versions, _, artifact_version, mode), plan in zip(_MEMBERS, plans, strict=True):
        report = module._evaluate(root, plan, prepared_source=prepared)
        member = {"artifact_schema_version": artifact_version, "evaluation_mode": mode,
            "dataset_id": root["dataset_id"], "plan": plan, "report": report,
            "algorithm_versions": versions(root), "environment": environment_versions(), "name": name, "notes": notes}
        member["experiment_id"] = digest(member)
        studies.append(StrategyExperiment(canonical_json(member)))
    return studies[0], studies[1], studies[2]


def run_intraday_procedure_suite(source_experiment_path: str | Path, *, expected_experiment_id: str,
                                cost_index: int, candidate_index: int, expected_candidate_id: str,
                                intraday_data_file: str | Path | None = None, name: str = "",
                                notes: str = "") -> tuple[StrategyExperiment, StrategyExperiment, StrategyExperiment]:
    """Read one explicit ordinary file once, then evaluate its captured bytes."""
    path = intraday_data_path(str(source_experiment_path))
    return evaluate_intraday_procedure_suite(load_strategy_experiment(path), source_experiment_path=path,
        expected_experiment_id=expected_experiment_id, cost_index=cost_index, candidate_index=candidate_index,
        expected_candidate_id=expected_candidate_id, intraday_data_file=intraday_data_file, name=name, notes=notes)
