"""MarketVault phase/risk routing policy, v1 (Python 3.11+, standard library).

This helper selects a role; it does NOT launch Codex, grant permissions, authenticate,
run commands, update configuration, or authorize merges. The coordinator must dispatch
and verify the observed runtime separately. Input fields are evidence claims, not a
security boundary. Keep credentials and unrestricted prompts out of input/log files.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

POLICY_VERSION = "1.1.0"
ROLE_SPECS = {
    "mv_inventory": ("gpt-6-luna", "low", "read-only", 0),
    "mv_analyst": ("gpt-6-sol", "medium", "read-only", 1),
    "mv_builder": ("gpt-6-sol", "medium", "workspace-write", 1),
    "mv_reasoner": ("gpt-6-astra", "medium", "read-only", 2),
    "mv_reviewer": ("gpt-6-astra", "high", "read-only", 2),
}
PHASES = {
    "mechanical", "discovery", "adversarial_review", "evidence_convergence",
    "patch_planning", "implementation", "validation_readback",
    "exact_head_review", "publish_gate", "remote_write",
}
RISK_SIGNALS = {
    "artifact_identity", "filesystem", "native_evidence", "pit", "destructive",
    "publication", "cryptography", "ci_control_plane", "security_boundary",
    "evidence_conflict", "new_architecture", "governance",
}
NON_REASONING_FAILURES = {"authentication", "sandbox", "environment", "quota"}
FAILURE_KINDS = NON_REASONING_FAILURES | {"none", "reasoning", "test"}
REQUIRED = {
    "schema_version", "task_id", "phase", "complexity", "ambiguity",
    "scope_clear", "risk_signals", "changed_paths", "write_authorized",
    "authorization_reference", "approved_paths", "risk_review_reference",
    "failure_kind", "phase_attempt", "available_models",
    "effective_parent_sandbox", "permission_evidence_reference",
}
PARENT_SANDBOXES = {"read-only", "workspace-write", "danger-full-access", "unknown"}
STATE_KEYS = {"task_id", "phase", "role", "checkpoint_closed"}
LEVELS = {"low", "medium", "high"}
MAX_INPUT_BYTES = 131_072


class InputError(ValueError):
    """Malformed or unsupported policy input."""


def _string(value: Any, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise InputError(f"{label}: expected {'possibly empty ' if empty else ''}string")
    if len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise InputError(f"{label}: excessive length or control character")
    return value


def _list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 1000:
        raise InputError(f"{label}: expected bounded list")
    result = [_string(v, label) for v in value]
    if len(result) != len(set(result)):
        raise InputError(f"{label}: duplicate values")
    return result


def normalize_path(raw: str) -> str:
    """Lexical repo-relative paths only; the caller must separately resolve symlinks."""
    value = _string(raw, "path").replace("\\", "/")
    parts = value.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise InputError("path must be a normalized relative file path")
    if any(c in value for c in (":", "*", "?", "[", "]")):
        raise InputError("absolute paths, drive names and globs are not allowed")
    if any(p.endswith((" ", ".")) for p in parts):
        raise InputError("ambiguous Windows path component")
    return value.casefold()


def _paths(value: Any, label: str) -> list[str]:
    normalized = [normalize_path(v) for v in _list(value, label)]
    if len(normalized) != len(set(normalized)):
        raise InputError(f"{label}: equivalent path listed twice")
    return normalized


def sensitive_path(path: str) -> bool:
    return (
        path == "agents.md"
        or path.startswith((".codex/", ".github/", "ci/", "docs/contracts/", "docs/governance/"))
        or path.startswith(("scripts/ci_", "scripts/check_release", "scripts/check_destructive"))
        or path in {"scripts/codex_model_router.py", "tests/test_codex_model_router.py"}
    )


def validate_task(task: Any) -> dict[str, Any]:
    if not isinstance(task, dict) or set(task) != REQUIRED:
        got = set(task) if isinstance(task, dict) else set()
        raise InputError(f"task fields mismatch: missing={sorted(REQUIRED-got)}, unknown={sorted(got-REQUIRED)}")
    if type(task["schema_version"]) is not int or task["schema_version"] != 1:
        raise InputError("unsupported schema_version")
    t = dict(task)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", _string(t["task_id"], "task_id")):
        raise InputError("invalid task_id")
    if _string(t["phase"], "phase") not in PHASES:
        raise InputError("unknown phase")
    for key in ("complexity", "ambiguity"):
        if _string(t[key], key) not in LEVELS:
            raise InputError(f"invalid {key}")
    for key in ("scope_clear", "write_authorized"):
        if type(t[key]) is not bool:
            raise InputError(f"{key}: expected boolean")
    t["risk_signals"] = _list(t["risk_signals"], "risk_signals")
    if set(t["risk_signals"]) - RISK_SIGNALS:
        raise InputError("unknown risk signal")
    t["available_models"] = _list(t["available_models"], "available_models")
    t["changed_paths"] = _paths(t["changed_paths"], "changed_paths")
    t["approved_paths"] = _paths(t["approved_paths"], "approved_paths")
    if _string(t["effective_parent_sandbox"], "effective_parent_sandbox") not in PARENT_SANDBOXES:
        raise InputError("unknown effective_parent_sandbox")
    for key in ("authorization_reference", "risk_review_reference", "permission_evidence_reference"):
        t[key] = _string(t[key], key, empty=True)
    if _string(t["failure_kind"], "failure_kind") not in FAILURE_KINDS:
        raise InputError("unknown failure_kind")
    if type(t["phase_attempt"]) is not int or not 1 <= t["phase_attempt"] <= 1000:
        raise InputError("phase_attempt must be an integer in 1..1000")
    return t


def validate_state(state: Any, task_id: str) -> dict[str, Any] | None:
    if state is None:
        return None
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise InputError("invalid sticky state fields")
    for key in ("task_id", "phase", "role"):
        _string(state[key], "sticky " + key)
    if state["task_id"] != task_id or state["phase"] not in PHASES or state["role"] not in ROLE_SPECS:
        raise InputError("sticky state belongs to another task or unknown phase/role")
    if type(state["checkpoint_closed"]) is not bool:
        raise InputError("checkpoint_closed must be boolean")
    # Prevent a writer role being smuggled into a read-only phase through state.
    if (state["role"] == "mv_builder") != (state["phase"] == "implementation"):
        raise InputError("sticky role incompatible with phase")
    return dict(state)


def choose_route(task: Any, state: Any = None) -> dict[str, Any]:
    t = validate_task(task)
    previous = validate_state(state, t["task_id"])
    out: dict[str, Any] = {
        "policy_version": POLICY_VERSION,
        "task_id": t["task_id"], "phase": t["phase"],
        "decision": "HOLD", "role": None, "requested_model": None,
        "requested_effort": None, "requested_sandbox": None,
        # Supplied evidence claims are not independently verified by this helper.
        "required_parent_sandbox": None,
        "effective_parent_sandbox": t["effective_parent_sandbox"],
        "permission_evidence_reference": t["permission_evidence_reference"],
        "runtime_permissions_verified": False,
        "observed_model": None, "runtime_dispatch_verified": False,
        "authority_granted": False, "automatic_remote_write": False,
        "reason_codes": [], "transition": "none", "next_state": None,
    }

    def hold(reason: str) -> dict[str, Any]:
        out["reason_codes"].append(reason)
        return out

    if t["failure_kind"] in NON_REASONING_FAILURES:
        return hold("FIX_ENVIRONMENT_OR_ACCESS_NOT_MODEL:" + t["failure_kind"])
    if t["phase_attempt"] > 3:
        return hold("PHASE_ATTEMPT_BUDGET_EXHAUSTED")
    if previous and previous["phase"] != t["phase"] and not previous["checkpoint_closed"]:
        return hold("PREVIOUS_PHASE_CHECKPOINT_STILL_OPEN")
    if t["phase"] == "remote_write":
        return hold("USE_SEPARATELY_AUTHORIZED_EXECUTOR_AND_EXACT_OBJECT_RECHECK")

    risks = set(t["risk_signals"])
    if any(sensitive_path(p) for p in t["changed_paths"]):
        risks.add("governance")
        out["reason_codes"].append("SENSITIVE_PATH")
    hard = bool(risks) or t["complexity"] == "high" or t["ambiguity"] == "high"
    repeated_failure = t["failure_kind"] in {"reasoning", "test"} and t["phase_attempt"] >= 3

    if t["phase"] == "implementation":
        if not t["scope_clear"]:
            return hold("SCOPE_NOT_FROZEN")
        if not t["write_authorized"] or not t["authorization_reference"].strip():
            return hold("EXPLICIT_SCOPED_WRITE_AUTHORIZATION_REQUIRED")
        if not t["changed_paths"] or not set(t["changed_paths"]).issubset(t["approved_paths"]):
            return hold("PATH_OUTSIDE_APPROVED_SCOPE")
        if (hard or repeated_failure) and not t["risk_review_reference"].strip():
            return hold("ASTRA_READONLY_PLAN_REVIEW_REQUIRED_BEFORE_WRITING")
        if repeated_failure:
            return hold("STOP_REPEATED_PATCHING_AND_REOPEN_REASONING_CHECKPOINT")
        role = "mv_builder"
        out["reason_codes"].append("IMPLEMENT_APPROVED_PLAN_WITH_SINGLE_WRITER")
    elif t["phase"] in {"exact_head_review", "publish_gate"}:
        role = "mv_reviewer"
        out["reason_codes"].append("FRESH_READONLY_REVIEW_REQUIRED_NOT_MERGE_AUTHORITY")
    elif t["phase"] in {"adversarial_review", "evidence_convergence"}:
        role = "mv_reasoner"
        out["reason_codes"].append("ADVERSARIAL_OR_COMPLETION_JUDGMENT")
    elif hard or repeated_failure or not t["scope_clear"]:
        role = "mv_reasoner"
        out["reason_codes"].append("RISK_AMBIGUITY_OR_REPEATED_REASONING_FAILURE")
    elif (t["phase"] in {"mechanical", "validation_readback"}
          and t["complexity"] == "low" and t["ambiguity"] == "low"):
        role = "mv_inventory"
        out["reason_codes"].append("BOUNDED_READONLY_EXTRACTION")
    else:
        role = "mv_analyst"
        out["reason_codes"].append("NORMAL_DISCOVERY_OR_PLANNING")

    transition = "new_phase"
    if previous and previous["phase"] == t["phase"] and not previous["checkpoint_closed"]:
        old = previous["role"]
        if ROLE_SPECS[old][3] > ROLE_SPECS[role][3]:
            role = old
            out["reason_codes"].append("STICKY_NO_DOWNGRADE_BEFORE_CHECKPOINT")
        transition = "keep_role" if role == old else "stop_child_then_escalate_at_checkpoint"

    model, effort, sandbox, _ = ROLE_SPECS[role]
    required_parent = "workspace-write" if role == "mv_builder" else "read-only"
    out.update(role=role, requested_model=model, requested_effort=effort,
               requested_sandbox=sandbox, required_parent_sandbox=required_parent)
    if model not in t["available_models"]:
        return hold("REQUIRED_MODEL_UNAVAILABLE_NO_SILENT_FALLBACK")
    # Gate the final (including sticky) role using current parent evidence, never
    # the role-local sandbox default. Neither a stronger mode nor unknown qualifies.
    if t["effective_parent_sandbox"] != required_parent:
        return hold("BUILDER_REQUIRES_WORKSPACE_WRITE_PARENT" if role == "mv_builder"
                    else "READONLY_ROLE_REQUIRES_READONLY_PARENT")
    if not t["permission_evidence_reference"].strip():
        return hold("CURRENT_PARENT_PERMISSION_EVIDENCE_REQUIRED")
    out.update(
        decision="DISPATCH_REQUEST", transition=transition,
        next_state={"task_id": t["task_id"], "phase": t["phase"], "role": role, "checkpoint_closed": False},
    )
    return out


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: str) -> Any:
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError("input exceeds byte limit")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="JSON task file, or - for stdin")
    parser.add_argument("--state", help="Optional previous phase state JSON")
    args = parser.parse_args()
    try:
        result = choose_route(read_json(args.task), read_json(args.state) if args.state else None)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(json.dumps({"decision": "INVALID_INPUT", "error": str(exc), "authority_granted": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["decision"] == "DISPATCH_REQUEST" else 3


if __name__ == "__main__":
    raise SystemExit(main())
