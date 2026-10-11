"""Action-local complete ordinary-source preparation for selection procedures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import intraday_research as research
from .strategy_experiment import canonical_json


def _binding(plan: dict) -> bytes:
    return canonical_json({key: plan[key] for key in ("source_experiment", "selection", "intraday_data_path")})


@dataclass(frozen=True, slots=True)
class _PreparedSelectionSource:
    """Private result of this action's strict data and complete source replay."""

    source_content: bytes
    plan_binding: bytes
    prepared: research._PreparedIntradayResearch

    def context_for(self, source: dict, plan: dict) -> research._PreparedIntradayResearch:
        if canonical_json(source) != self.source_content or _binding(plan) != self.plan_binding:
            raise ValueError("selection source differs from this action's prepared inputs")
        return self.prepared


def _prepare_selection_source(source: dict, plan: dict, *, data_file: str | Path | None = None,
                              data=None, label: str) -> _PreparedSelectionSource:
    """Strictly prepare once; independent run/replay entries still call here."""
    if source["algorithm_versions"] != research.research_algorithm_versions(source["plan"]):
        raise ValueError("recorded source algorithms differ; no Q5 data was read or model fitted")
    normalized, children, axes = research.expand_intraday_plan(source["plan"], recorded=True)
    prepared = research._prepare_intraday_research(children[0], data=data,
        data_file=data_file or plan["intraday_data_path"])
    if canonical_json(prepared.context) != canonical_json(source["report"]["context"]):
        raise ValueError(f"{label} source common context differs")
    original = research._evaluate_intraday_research(normalized, children, axes, prepared)
    if canonical_json(original) != canonical_json(source["report"]):
        raise ValueError(f"{label} complete ordinary source reconstruction differs")
    return _PreparedSelectionSource(canonical_json(source), _binding(plan), prepared)
