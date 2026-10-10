"""Complete existing research plans and explicit saved-candidate continuation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PureWindowsPath

from ..dataset.cli import DatasetCLIError, _verify_parent_chain, _verify_regular_file
from ..strategy_comparison_io import canonical_json
from .intraday_backtest import intraday_data_path
from .intraday_data import parse_json
from .intraday_execution_scenarios import (
    INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSIONS, normalize_intraday_execution_scenarios_plan,
)
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_research import (
    INTRADAY_DIAGNOSTICS_PLAN_VERSIONS, INTRADAY_RESEARCH_PLAN_VERSIONS,
    _identity, expand_intraday_plan, is_intraday_plan_v2, normalize_intraday_research_plan,
)
from .strategy_config import parse_strategy_specs, strategy_plan_fields
from .strategy_experiment import load_strategy_experiment


def _normalized(plan, *, base=None):
    if type(plan) is not dict or plan.get("plan_schema_version") not in (
        *INTRADAY_RESEARCH_PLAN_VERSIONS, *INTRADAY_DIAGNOSTICS_PLAN_VERSIONS, *INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSIONS,
    ):
        raise ValueError("an existing intraday comparison, diagnostics or execution-scenarios plan is required")
    value = deepcopy(plan)
    comparison = value if value["plan_schema_version"] in INTRADAY_RESEARCH_PLAN_VERSIONS else value.get("comparison_plan")
    if type(comparison) is not dict:
        raise ValueError("a complete comparison plan is required")
    locator = comparison.get("intraday_data_path")
    absolute = type(locator) is str and (Path(locator).is_absolute() or PureWindowsPath(locator).is_absolute())
    if not absolute and base is not None:
        comparison["intraday_data_path"] = str(intraday_data_path(locator, base=base))
    if value["plan_schema_version"] in INTRADAY_EXECUTION_SCENARIOS_PLAN_VERSIONS:
        return normalize_intraday_execution_scenarios_plan(value, recorded=True)
    return expand_intraday_plan(value, recorded=True)[0]


def serialize_intraday_plan(plan: dict) -> bytes:
    """Capture a complete valid plan, retaining its absolute portable locator."""
    return canonical_json(_normalized(plan))


def parse_intraday_plan_bytes(content: bytes, *, base: Path | None = None) -> dict:
    """Parse without data I/O; only a relative locator uses an explicit base."""
    try:
        return _normalized(parse_json(content), base=base)
    except DatasetCLIError as exc:
        raise ValueError(str(exc)) from exc


def _plan_path(path) -> Path:
    if not isinstance(path, (str, Path)):
        raise ValueError("plan path must be an explicit str or Path")
    try:
        return intraday_data_path(str(path))
    except DatasetCLIError as exc:
        raise ValueError(str(exc)) from exc


def _read_plan(path: Path) -> bytes:
    try:
        _verify_regular_file(path, "intraday plan")
    except DatasetCLIError as exc:
        raise ValueError(str(exc)) from exc
    return path.read_bytes()


def load_intraday_plan(path: str | Path) -> dict:
    """Load one named plan as a draft; never access its data or execute it."""
    file_path = _plan_path(path)
    return parse_intraday_plan_bytes(_read_plan(file_path), base=file_path.parent)


@dataclass(frozen=True, slots=True)
class IntradayPlanWriteResult:
    path: Path
    plan_schema_version: str
    content_sha256: str
    created_new_file: bool


def write_intraday_plan(content: bytes, *, path: str | Path) -> IntradayPlanWriteResult:
    """Write captured canonical bytes by exclusive creation or identical reuse."""
    plan = parse_intraday_plan_bytes(content)
    if canonical_json(plan) != content:
        raise ValueError("saved plan content must be normalized canonical bytes")
    file_path = _plan_path(path)
    try:
        _verify_parent_chain(file_path, "intraday plan")
    except DatasetCLIError as exc:
        raise ValueError(str(exc)) from exc
    if not file_path.parent.is_dir():
        raise ValueError("plan parent must be an existing regular directory")

    def result(created):
        return IntradayPlanWriteResult(file_path, plan["plan_schema_version"], sha256(content).hexdigest(), created)

    def reuse():
        if _read_plan(file_path) != content:
            raise ValueError("existing plan differs; choose a new file path")
        return result(False)

    if file_path.exists() or file_path.is_symlink():
        return reuse()
    try:
        with file_path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        return reuse()
    if _read_plan(file_path) != content:
        raise ValueError("plan readback differs from the captured content")
    return result(True)


def extract_intraday_candidate_plan(source_experiment_path: str | Path, *,
                                   expected_experiment_id: str | None = None,
                                   expected_candidate_id: str | None = None,
                                   cost_index: int = 0, candidate_index: int = 0) -> dict:
    """Read one saved DEV selection into a comparison draft, without rerunning."""
    if any(type(value) is not int or value < 0 for value in (cost_index, candidate_index)):
        raise ValueError("cost_index and candidate_index must be nonnegative integers")
    for value, label in ((expected_experiment_id, "expected experiment ID"), (expected_candidate_id, "expected candidate ID")):
        if value is not None:
            _identity(value, label)
    root = load_strategy_experiment(source_experiment_path).as_dict()
    if (root["artifact_schema_version"] not in INTRADAY_EXPERIMENT_VERSIONS
            or root["evaluation_mode"] not in ("INTRADAY_COMPARISON", "INTRADAY_DIAGNOSTICS")
            or root["report"]["evaluation_scope"] != "DEVELOPMENT_WALK_FORWARD_ONLY"):
        raise ValueError("continue requires an ordinary saved Q7 DEV comparison or diagnostics experiment")
    if expected_experiment_id is not None and root["experiment_id"] != expected_experiment_id:
        raise ValueError("source experiment identity differs from the explicitly selected experiment")
    groups = root["report"]["groups"]
    if cost_index >= len(groups) or candidate_index >= len(groups[cost_index]["results"]):
        raise ValueError("selected cost/candidate index is outside the saved experiment")
    group, candidate = groups[cost_index], groups[cost_index]["results"][candidate_index]
    if expected_candidate_id is not None and candidate["candidate_id"] != expected_candidate_id:
        raise ValueError("candidate identity differs from the explicitly selected candidate")
    comparison = root["plan"].get("comparison_plan", root["plan"])
    strategy = strategy_plan_fields(parse_strategy_specs([candidate["strategy"]], allow_quadratic=is_intraday_plan_v2(comparison))[0])
    return normalize_intraday_research_plan({**comparison, "strategies": [strategy],
                                            "execution": group["execution_policy"]}, recorded=True)
