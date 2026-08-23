#!/usr/bin/env python3
"""Fail-closed destructive-operation design-contract gate.

The checker has two modes:

* ``repository`` validates every registered contract, exemption, and detected
  production surface in the checked-out tree.
* ``pull_request`` additionally proves that every changed destructive surface
  is bound to an unchanged contract that already existed in the exact base.

This is deliberately conservative static analysis. It establishes a machine
boundary for repository-owned production code; it does not claim to prove the
runtime semantics of arbitrary Python or external consumers.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


CONTRACT_SCHEMA_VERSION = "market-vault-destructive-operation-v1"
EXEMPTION_SCHEMA_VERSION = "market-vault-destructive-exemptions-v1"
CONTRACT_ROOT = PurePosixPath("docs/governance/destructive_operations")
EXEMPTIONS_PATH = CONTRACT_ROOT / "exemptions.json"
PRODUCTION_ROOT = PurePosixPath("src/market_vault")
ALLOWED_APPROVAL = {"APPROVED"}
ALLOWED_BINDING_ROLES = {
    "ENTRYPOINT",
    "MUTATION_OWNER",
    "STATE_AUTHORITY",
    "USER_INTERFACE",
    "SUPPORTING",
}
ALLOWED_FINDING_KINDS = {
    "destructive_call",
    "destructive_public_name",
    "destructive_sql",
}
DESTRUCTIVE_NAME_TOKENS = {
    "cleanup",
    "delete",
    "drop",
    "gc",
    "migrate",
    "overwrite",
    "purge",
    "restore",
    "truncate",
}
SQL_PATTERN = re.compile(
    r"\b(?:DELETE\s+FROM|DROP\s+(?:TABLE|VIEW)|TRUNCATE\s+TABLE)\b",
    re.IGNORECASE,
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,79}$")


class GateError(RuntimeError):
    """A policy input or proof could not be validated safely."""


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    symbol: str
    kind: str
    signal: str
    fingerprint: str
    line: int

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (self.path, self.symbol, self.kind, self.signal, self.fingerprint)

    def display(self) -> str:
        return (
            f"{self.path}:{self.line}:{self.symbol}:"
            f"{self.kind}:{self.signal}:{self.fingerprint}"
        )


@dataclass(frozen=True)
class Binding:
    path: str
    symbols: tuple[str, ...]
    role: str
    allowed_kinds: frozenset[str]

    def covers(self, finding: Finding) -> bool:
        return (
            finding.path == self.path
            and finding.symbol in self.symbols
            and finding.kind in self.allowed_kinds
        )


@dataclass(frozen=True)
class Contract:
    operation_id: str
    canonical_bytes: bytes
    bindings: tuple[Binding, ...]

    def covers(self, finding: Finding) -> bool:
        return any(binding.covers(finding) for binding in self.bindings)


@dataclass(frozen=True)
class Exemption:
    exemption_id: str
    path: str
    symbol: str
    kind: str
    signal: str
    fingerprint: str
    expected_count: int
    rationale: str

    def covers(self, finding: Finding) -> bool:
        return finding.identity == (
            self.path,
            self.symbol,
            self.kind,
            self.signal,
            self.fingerprint,
        )


@dataclass(frozen=True)
class Snapshot:
    findings: tuple[Finding, ...]
    symbol_hashes: dict[tuple[str, str], str]
    contracts: dict[str, Contract]
    exemptions: tuple[Exemption, ...]


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _fingerprint(node: ast.AST) -> str:
    payload = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_fingerprint(node: ast.AST, source: str) -> str:
    """Hash exact normalized source independently of Python AST revisions."""
    segment = ast.get_source_segment(source, node)
    if segment is None:
        raise GateError("cannot recover exact source for a destructive AST surface")
    normalized = segment.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json(data: bytes, label: str) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError(f"{label}: JSON must be UTF-8: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, GateError) as exc:
        raise GateError(f"{label}: invalid JSON: {exc}") from exc


def _expect_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(f"{label} must be an object")
    return value


def _expect_exact_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise GateError(f"{label} fields mismatch; missing={missing}, unknown={unknown}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(f"{label} must be a non-empty string")
    if value.strip().upper() in {"N/A", "NA", "NOT APPLICABLE"}:
        raise GateError(f"{label} cannot use bare N/A; use applicable=false with rationale")
    return value.strip()


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise GateError(f"{label} must be a non-empty list")
    result = [_nonempty_string(item, f"{label}[]") for item in value]
    if len(set(result)) != len(result):
        raise GateError(f"{label} contains duplicates")
    return result


def _statements_or_not_applicable(value: Any, label: str) -> None:
    if isinstance(value, list):
        _string_list(value, label)
        return
    marker = _expect_object(value, label)
    _expect_exact_keys(marker, {"applicable", "rationale"}, label)
    if marker["applicable"] is not False:
        raise GateError(f"{label}.applicable must be false")
    _nonempty_string(marker["rationale"], f"{label}.rationale")


def _validate_applicability(value: Any, label: str = "contract") -> None:
    if isinstance(value, str):
        _nonempty_string(value, label)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_applicability(item, f"{label}[{index}]")
        return
    if not isinstance(value, dict):
        return
    if value.get("applicable") is False:
        _nonempty_string(value.get("rationale"), f"{label}.rationale")
    for key, item in value.items():
        _validate_applicability(item, f"{label}.{key}")


def _safe_source_path(value: Any, label: str) -> str:
    text = _nonempty_string(value, label).replace("\\", "/")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
        or not text.startswith("src/market_vault/")
        or not text.endswith(".py")
    ):
        raise GateError(f"{label} must be an exact Python file under src/market_vault")
    if any(char in text for char in "*?[]"):
        raise GateError(f"{label} cannot contain wildcard characters")
    return text


def _validate_contract(value: Any, label: str) -> Contract:
    obj = _expect_object(value, label)
    required = {
        "schema_version",
        "operation_id",
        "approval",
        "identity",
        "implementation_bindings",
        "authority_boundary",
        "persistent_scope",
        "state_machine",
        "commit_point",
        "crash_semantics",
        "rollback_recovery",
        "idempotence",
        "locking_concurrency",
        "execution_revalidation",
        "success_evidence",
        "path_safety",
        "stale_plan_ui",
        "physical_atomicity",
        "unsupported_cascade",
        "permanent_deletion",
        "implementation_tests",
    }
    _expect_exact_keys(obj, required, label)
    if obj["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise GateError(f"{label}: unknown schema_version {obj['schema_version']!r}")
    operation_id = _nonempty_string(obj["operation_id"], f"{label}.operation_id")
    if not ID_PATTERN.fullmatch(operation_id):
        raise GateError(f"{label}.operation_id has invalid syntax")

    approval = _expect_object(obj["approval"], f"{label}.approval")
    _expect_exact_keys(approval, {"status", "rationale"}, f"{label}.approval")
    if approval["status"] not in ALLOWED_APPROVAL:
        raise GateError(f"{label}.approval.status is unknown")
    _nonempty_string(approval["rationale"], f"{label}.approval.rationale")

    identity = _expect_object(obj["identity"], f"{label}.identity")
    _expect_exact_keys(identity, {"name", "purpose"}, f"{label}.identity")
    _nonempty_string(identity["name"], f"{label}.identity.name")
    _nonempty_string(identity["purpose"], f"{label}.identity.purpose")

    raw_bindings = obj["implementation_bindings"]
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise GateError(f"{label}.implementation_bindings must be a non-empty list")
    bindings: list[Binding] = []
    seen_bindings: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_bindings):
        binding_label = f"{label}.implementation_bindings[{index}]"
        binding = _expect_object(raw, binding_label)
        _expect_exact_keys(
            binding,
            {"path", "symbols", "role", "allowed_surface_kinds", "rationale"},
            binding_label,
        )
        path = _safe_source_path(binding["path"], f"{binding_label}.path")
        symbols = _string_list(binding["symbols"], f"{binding_label}.symbols")
        if any(
            symbol in {"<module>", "."} or any(char in symbol for char in "*?[]")
            for symbol in symbols
        ):
            raise GateError(f"{binding_label}.symbols must contain exact symbols")
        if binding["role"] not in ALLOWED_BINDING_ROLES:
            raise GateError(f"{binding_label}.role is unknown")
        kinds = frozenset(
            _string_list(
                binding["allowed_surface_kinds"],
                f"{binding_label}.allowed_surface_kinds",
            )
        )
        if not kinds <= ALLOWED_FINDING_KINDS:
            raise GateError(f"{binding_label}.allowed_surface_kinds contains unknown values")
        _nonempty_string(binding["rationale"], f"{binding_label}.rationale")
        for symbol in symbols:
            key = (path, symbol)
            if key in seen_bindings:
                raise GateError(f"{label}: duplicate implementation binding {key}")
            seen_bindings.add(key)
        bindings.append(Binding(path, tuple(symbols), binding["role"], kinds))

    authority = _expect_object(obj["authority_boundary"], f"{label}.authority_boundary")
    _expect_exact_keys(
        authority,
        {"initiators", "mutation_owner", "forbidden_bypass_layers"},
        f"{label}.authority_boundary",
    )
    _string_list(authority["initiators"], f"{label}.authority_boundary.initiators")
    _nonempty_string(authority["mutation_owner"], f"{label}.authority_boundary.mutation_owner")
    _string_list(
        authority["forbidden_bypass_layers"],
        f"{label}.authority_boundary.forbidden_bypass_layers",
    )

    scope = _expect_object(obj["persistent_scope"], f"{label}.persistent_scope")
    _expect_exact_keys(scope, {"mutated_assets", "excluded_assets"}, f"{label}.persistent_scope")
    _string_list(scope["mutated_assets"], f"{label}.persistent_scope.mutated_assets")
    _string_list(scope["excluded_assets"], f"{label}.persistent_scope.excluded_assets")

    machine = _expect_object(obj["state_machine"], f"{label}.state_machine")
    _expect_exact_keys(
        machine,
        {"states", "initial_state", "terminal_states", "allowed_transitions", "forbidden_transitions"},
        f"{label}.state_machine",
    )
    states = _string_list(machine["states"], f"{label}.state_machine.states")
    state_set = set(states)
    initial = _nonempty_string(machine["initial_state"], f"{label}.state_machine.initial_state")
    terminals = _string_list(machine["terminal_states"], f"{label}.state_machine.terminal_states")
    if initial not in state_set or not set(terminals) <= state_set:
        raise GateError(f"{label}.state_machine references an unknown initial/terminal state")
    for transition_key in ("allowed_transitions", "forbidden_transitions"):
        transitions = machine[transition_key]
        if not isinstance(transitions, list) or not transitions:
            raise GateError(f"{label}.state_machine.{transition_key} must be non-empty")
        seen: set[tuple[str, str]] = set()
        for index, raw_transition in enumerate(transitions):
            transition = _expect_object(
                raw_transition, f"{label}.state_machine.{transition_key}[{index}]"
            )
            _expect_exact_keys(
                transition,
                {"from", "to", "rationale"},
                f"{label}.state_machine.{transition_key}[{index}]",
            )
            source = _nonempty_string(transition["from"], "transition.from")
            target = _nonempty_string(transition["to"], "transition.to")
            _nonempty_string(transition["rationale"], "transition.rationale")
            if source not in state_set or target not in state_set:
                raise GateError(f"{label}: transition references unknown state {source}->{target}")
            if (source, target) in seen:
                raise GateError(f"{label}: duplicate {transition_key} {source}->{target}")
            seen.add((source, target))

    commit = _expect_object(obj["commit_point"], f"{label}.commit_point")
    _expect_exact_keys(
        commit,
        {"durable_authority", "before_state", "after_state", "success_authoritative_when"},
        f"{label}.commit_point",
    )
    for key in ("durable_authority", "success_authoritative_when"):
        _nonempty_string(commit[key], f"{label}.commit_point.{key}")
    if commit["before_state"] not in state_set or commit["after_state"] not in state_set:
        raise GateError(f"{label}.commit_point references unknown state")
    if commit["before_state"] == commit["after_state"]:
        raise GateError(f"{label}.commit_point must cross a durable state boundary")

    section_shapes = {
        "crash_semantics": {"pre_commit", "post_commit"},
        "rollback_recovery": {"restorable", "non_restorable", "interruption_detection"},
        "idempotence": {"same_request_retry", "completed_retry", "conflicting_retry"},
        "locking_concurrency": {"lock_authority", "lock_scope", "under_lock_revalidation", "concurrent_behavior"},
        "execution_revalidation": {"identities", "drift_behavior"},
        "success_evidence": {"authoritative_evidence", "non_success_evidence", "integrity_binding"},
        "stale_plan_ui": {"invalidation_triggers", "confirmation_invalidation", "execution_policy"},
        "physical_atomicity": {"lifecycle_unit", "partial_mutation", "rollback_expectation"},
        "unsupported_cascade": {"retained_dependents", "refused_cases", "unsupported_cases"},
    }
    for section_name, keys in section_shapes.items():
        section = _expect_object(obj[section_name], f"{label}.{section_name}")
        _expect_exact_keys(section, keys, f"{label}.{section_name}")
        for key in keys:
            _statements_or_not_applicable(
                section[key], f"{label}.{section_name}.{key}"
            )

    path_safety = _expect_object(obj["path_safety"], f"{label}.path_safety")
    _expect_exact_keys(
        path_safety,
        {"mutates_paths", "windows_reparse_policy", "unverifiable_path_policy"},
        f"{label}.path_safety",
    )
    if not isinstance(path_safety["mutates_paths"], bool):
        raise GateError(f"{label}.path_safety.mutates_paths must be boolean")
    if path_safety["mutates_paths"]:
        if path_safety["windows_reparse_policy"] != "FAIL_CLOSED_FILE_ATTRIBUTE_REPARSE_POINT":
            raise GateError(f"{label}: path mutation requires Windows reparse fail-closed policy")
        if path_safety["unverifiable_path_policy"] != "FAIL_CLOSED":
            raise GateError(f"{label}: path mutation requires unverifiable paths to fail closed")
    else:
        for key in ("windows_reparse_policy", "unverifiable_path_policy"):
            marker = _expect_object(path_safety[key], f"{label}.path_safety.{key}")
            _expect_exact_keys(marker, {"applicable", "rationale"}, f"{label}.path_safety.{key}")
            if marker["applicable"] is not False:
                raise GateError(f"{label}.path_safety.{key}.applicable must be false")
            _nonempty_string(marker["rationale"], f"{label}.path_safety.{key}.rationale")

    permanent = _expect_object(obj["permanent_deletion"], f"{label}.permanent_deletion")
    _expect_exact_keys(permanent, {"supported", "rationale"}, f"{label}.permanent_deletion")
    if not isinstance(permanent["supported"], bool):
        raise GateError(f"{label}.permanent_deletion.supported must be boolean")
    _nonempty_string(permanent["rationale"], f"{label}.permanent_deletion.rationale")
    _string_list(obj["implementation_tests"], f"{label}.implementation_tests")
    _validate_applicability(obj, label)
    return Contract(operation_id, _canonical_json(obj), tuple(bindings))


def _validate_exemptions(value: Any, label: str) -> tuple[Exemption, ...]:
    obj = _expect_object(value, label)
    _expect_exact_keys(obj, {"schema_version", "exemptions"}, label)
    if obj["schema_version"] != EXEMPTION_SCHEMA_VERSION:
        raise GateError(f"{label}: unknown schema_version {obj['schema_version']!r}")
    rows = obj["exemptions"]
    if not isinstance(rows, list):
        raise GateError(f"{label}.exemptions must be a list")
    result: list[Exemption] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        row_label = f"{label}.exemptions[{index}]"
        row = _expect_object(raw, row_label)
        _expect_exact_keys(
            row,
            {
                "exemption_id",
                "path",
                "symbol",
                "kind",
                "signal",
                "fingerprint",
                "expected_count",
                "rationale",
            },
            row_label,
        )
        exemption_id = _nonempty_string(row["exemption_id"], f"{row_label}.exemption_id")
        if not ID_PATTERN.fullmatch(exemption_id) or exemption_id in seen:
            raise GateError(f"{row_label}.exemption_id is invalid or duplicated")
        seen.add(exemption_id)
        path = _safe_source_path(row["path"], f"{row_label}.path")
        symbol = _nonempty_string(row["symbol"], f"{row_label}.symbol")
        if any(char in symbol for char in "*?[]") or symbol in {"<module>", "."}:
            raise GateError(f"{row_label}.symbol must be an exact non-module symbol")
        kind = _nonempty_string(row["kind"], f"{row_label}.kind")
        if kind not in ALLOWED_FINDING_KINDS:
            raise GateError(f"{row_label}.kind is unknown")
        signal = _nonempty_string(row["signal"], f"{row_label}.signal")
        if any(char in signal for char in "*?[]"):
            raise GateError(f"{row_label}.signal cannot contain wildcards")
        fingerprint = _nonempty_string(row["fingerprint"], f"{row_label}.fingerprint")
        if not SHA256_PATTERN.fullmatch(fingerprint):
            raise GateError(f"{row_label}.fingerprint must be lowercase SHA-256")
        expected_count = row["expected_count"]
        if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 1:
            raise GateError(f"{row_label}.expected_count must be a positive integer")
        rationale = _nonempty_string(row["rationale"], f"{row_label}.rationale")
        result.append(
            Exemption(
                exemption_id,
                path,
                symbol,
                kind,
                signal,
                fingerprint,
                expected_count,
                rationale,
            )
        )
    return tuple(result)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _destructive_call_signal(call: ast.Call) -> str | None:
    name = _call_name(call.func)
    if name in {
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "shutil.rmtree",
        "shutil.move",
    }:
        return name
    if isinstance(call.func, ast.Attribute) and call.func.attr in {"unlink", "rmdir", "rename"}:
        return f"path.{call.func.attr}"
    if isinstance(call.func, ast.Attribute) and call.func.attr == "replace":
        receiver = call.func.value
        if _looks_like_path_expression(receiver):
            return "path.replace"
    return None


def _looks_like_path_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        return _call_name(node.func) in {"Path", "pathlib.Path"}
    if isinstance(node, ast.Name):
        name = node.id.lower()
        return name in {"path", "source", "destination", "target"} or name.endswith(
            ("_path", "_file", "_dir", "_directory")
        )
    if isinstance(node, ast.Attribute):
        name = node.attr.lower()
        return name.endswith(("_path", "_file", "_dir", "_directory"))
    return False


def _sql_signal(call: ast.Call) -> str | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in {"execute", "sql"}:
        return None
    if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(call.args[0].value, str):
        return None
    match = SQL_PATTERN.search(call.args[0].value)
    if not match:
        return None
    return "sql." + "_".join(match.group(0).upper().split())


class _InventoryVisitor(ast.NodeVisitor):
    def __init__(self, path: str, source: str) -> None:
        self.path = path
        self.source = source
        self.stack: list[str] = []
        self.findings: list[Finding] = []
        self.symbol_hashes: dict[tuple[str, str], str] = {}

    @property
    def symbol(self) -> str:
        return ".".join(self.stack) if self.stack else "<module>"

    def _enter_symbol(self, node: ast.AST, name: str) -> None:
        self.stack.append(name)
        symbol = self.symbol
        self.symbol_hashes[(self.path, symbol)] = _fingerprint(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts = {part for part in name.lower().split("_") if part}
            matched = sorted(parts & DESTRUCTIVE_NAME_TOKENS)
            if not name.startswith("_") and matched:
                signal = "name." + "+".join(matched)
                self.findings.append(
                    Finding(
                        self.path,
                        symbol,
                        "destructive_public_name",
                        signal,
                        hashlib.sha256(f"{symbol}:{signal}".encode("utf-8")).hexdigest(),
                        node.lineno,
                    )
                )
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter_symbol(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_symbol(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_symbol(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        signal = _destructive_call_signal(node)
        kind = "destructive_call"
        if signal is None:
            signal = _sql_signal(node)
            kind = "destructive_sql"
        if signal is not None:
            self.findings.append(
                Finding(
                    self.path,
                    self.symbol,
                    kind,
                    signal,
                    _source_fingerprint(node, self.source),
                    node.lineno,
                )
            )
        self.generic_visit(node)


def _analyze_source(path: str, data: bytes) -> tuple[list[Finding], dict[tuple[str, str], str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError(f"{path}: production source must be UTF-8: {exc}") from exc
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise GateError(f"{path}: AST parse failed: {exc}") from exc
    visitor = _InventoryVisitor(path, text)
    visitor.visit(tree)
    return visitor.findings, visitor.symbol_hashes


def _run_git(repo: Path, args: list[str], *, text: bool = False) -> bytes | str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise GateError(f"git {' '.join(args)} failed: {str(detail).strip()}") from exc
    return result.stdout


def _worktree_files(repo: Path, root: PurePosixPath, suffix: str) -> dict[str, bytes]:
    directory = repo.joinpath(*root.parts)
    if not directory.exists():
        return {}
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob(f"*{suffix}"))
        if path.is_file()
    }


def _git_files(repo: Path, ref: str, root: PurePosixPath, suffix: str) -> dict[str, bytes]:
    raw = _run_git(repo, ["ls-tree", "-r", "--name-only", ref, "--", root.as_posix()])
    assert isinstance(raw, bytes)
    paths = [line for line in raw.decode("utf-8").splitlines() if line.endswith(suffix)]
    result: dict[str, bytes] = {}
    for path in paths:
        data = _run_git(repo, ["show", f"{ref}:{path}"])
        assert isinstance(data, bytes)
        result[path] = data
    return result


def _build_snapshot(
    source_files: dict[str, bytes],
    governance_files: dict[str, bytes],
    *,
    allow_missing_registry: bool = False,
) -> Snapshot:
    findings: list[Finding] = []
    symbol_hashes: dict[tuple[str, str], str] = {}
    for path, data in sorted(source_files.items()):
        file_findings, file_hashes = _analyze_source(path, data)
        findings.extend(file_findings)
        symbol_hashes.update(file_hashes)

    exemptions_data = governance_files.get(EXEMPTIONS_PATH.as_posix())
    if exemptions_data is None:
        if not allow_missing_registry:
            raise GateError(f"missing exemption registry: {EXEMPTIONS_PATH.as_posix()}")
        exemptions: tuple[Exemption, ...] = ()
    else:
        exemptions = _validate_exemptions(
            _parse_json(exemptions_data, EXEMPTIONS_PATH.as_posix()),
            EXEMPTIONS_PATH.as_posix(),
        )
    contracts: dict[str, Contract] = {}
    contract_paths: dict[str, str] = {}
    for path, data in sorted(governance_files.items()):
        if path == EXEMPTIONS_PATH.as_posix():
            continue
        contract = _validate_contract(_parse_json(data, path), path)
        if contract.operation_id in contracts:
            raise GateError(f"duplicate operation_id: {contract.operation_id}")
        contracts[contract.operation_id] = contract
        contract_paths[contract.operation_id] = path
    for operation_id, path in contract_paths.items():
        expected_path = (CONTRACT_ROOT / f"{operation_id}.json").as_posix()
        if path != expected_path:
            raise GateError(
                f"contract {operation_id} must use canonical path {expected_path}; "
                f"got {path}"
            )
    return Snapshot(tuple(sorted(findings)), symbol_hashes, contracts, exemptions)


def load_worktree_snapshot(repo: Path) -> Snapshot:
    return _build_snapshot(
        _worktree_files(repo, PRODUCTION_ROOT, ".py"),
        _worktree_files(repo, CONTRACT_ROOT, ".json"),
    )


def load_git_snapshot(
    repo: Path, ref: str, *, allow_missing_registry: bool = False
) -> Snapshot:
    return _build_snapshot(
        _git_files(repo, ref, PRODUCTION_ROOT, ".py"),
        _git_files(repo, ref, CONTRACT_ROOT, ".json"),
        allow_missing_registry=allow_missing_registry,
    )


def validate_snapshot(snapshot: Snapshot) -> list[str]:
    errors: list[str] = []
    exemption_matches = {row.exemption_id: 0 for row in snapshot.exemptions}
    for finding in snapshot.findings:
        contract_hits = sorted(
            contract.operation_id
            for contract in snapshot.contracts.values()
            if contract.covers(finding)
        )
        exemption_hits = [row for row in snapshot.exemptions if row.covers(finding)]
        total = len(contract_hits) + len(exemption_hits)
        if total == 0:
            errors.append(f"unclassified destructive surface: {finding.display()}")
        elif total > 1:
            labels = contract_hits + [row.exemption_id for row in exemption_hits]
            errors.append(
                f"ambiguous destructive surface classification {finding.display()}: {labels}"
            )
        elif exemption_hits:
            exemption_matches[exemption_hits[0].exemption_id] += 1
    for exemption in snapshot.exemptions:
        actual = exemption_matches[exemption.exemption_id]
        if actual != exemption.expected_count:
            errors.append(
                f"exemption {exemption.exemption_id} expected exactly "
                f"{exemption.expected_count} matching surface(s), found {actual}"
            )
    return errors


def _changed_paths(repo: Path, base: str, head: str) -> set[str]:
    raw = _run_git(repo, ["diff", "--name-only", f"{base}...{head}", "--"])
    assert isinstance(raw, bytes)
    return {line for line in raw.decode("utf-8").splitlines() if line}


def _base_contract_covering(snapshot: Snapshot, finding: Finding) -> list[Contract]:
    return [contract for contract in snapshot.contracts.values() if contract.covers(finding)]


def validate_pull_request(repo: Path, base: str, head: str) -> tuple[Snapshot, list[str]]:
    # Bootstrap is intentionally one-way: a historical base predating the
    # registry is represented as having zero approved contracts. HEAD must
    # still validate completely, and any same-PR implementation delta then
    # fails because no BASE contract can authorize it.
    base_snapshot = load_git_snapshot(repo, base, allow_missing_registry=True)
    head_snapshot = load_git_snapshot(repo, head)
    errors = validate_snapshot(head_snapshot)
    changed = _changed_paths(repo, base, head)
    changed_source = {path for path in changed if path.startswith("src/market_vault/") and path.endswith(".py")}

    base_findings = {(item.path, item.symbol, item.kind, item.signal, item.fingerprint): item for item in base_snapshot.findings}
    head_findings = {(item.path, item.symbol, item.kind, item.signal, item.fingerprint): item for item in head_snapshot.findings}
    impacted: dict[tuple[str, str], list[Finding]] = {}
    for finding in head_snapshot.findings:
        if finding.path not in changed_source:
            continue
        symbol_key = (finding.path, finding.symbol)
        if (
            finding.identity not in base_findings
            or base_snapshot.symbol_hashes.get(symbol_key)
            != head_snapshot.symbol_hashes.get(symbol_key)
        ):
            impacted.setdefault(symbol_key, []).append(finding)

    # A changed symbol already registered by a base contract remains an
    # implementation delta even if its destructive call itself is unchanged.
    for contract in base_snapshot.contracts.values():
        for binding in contract.bindings:
            if binding.path not in changed_source:
                continue
            for symbol in binding.symbols:
                key = (binding.path, symbol)
                before = base_snapshot.symbol_hashes.get(key)
                after = head_snapshot.symbol_hashes.get(key)
                if before != after and (before is not None or after is not None):
                    surfaces = [
                        item
                        for item in head_snapshot.findings
                        if item.path == binding.path and item.symbol == symbol
                    ]
                    impacted.setdefault(key, []).extend(surfaces)

    for key, surfaces in sorted(impacted.items()):
        path, symbol = key
        base_contracts: dict[str, Contract] = {}
        for finding in surfaces:
            for contract in _base_contract_covering(base_snapshot, finding):
                base_contracts[contract.operation_id] = contract
        # Bound symbols can have no directly detected call (for example a
        # service wrapper); recover the base binding explicitly.
        for contract in base_snapshot.contracts.values():
            if any(path == binding.path and symbol in binding.symbols for binding in contract.bindings):
                base_contracts[contract.operation_id] = contract
        if not base_contracts:
            details = ", ".join(item.display() for item in surfaces) or "bound symbol changed"
            errors.append(
                f"destructive implementation delta lacks approved BASE contract: "
                f"{path}:{symbol} ({details})"
            )
            continue
        if len(base_contracts) > 1:
            errors.append(
                f"destructive implementation delta has ambiguous BASE contracts: "
                f"{path}:{symbol}: {sorted(base_contracts)}"
            )
            continue
        operation_id, base_contract = next(iter(base_contracts.items()))
        head_contract = head_snapshot.contracts.get(operation_id)
        if head_contract is None:
            errors.append(
                f"destructive implementation delta removed its BASE contract: {operation_id}"
            )
        elif head_contract.canonical_bytes != base_contract.canonical_bytes:
            errors.append(
                f"destructive implementation and contract changed together for "
                f"{operation_id}; merge a design-only contract PR first"
            )

    # A removed finding in changed source is still a destructive-surface
    # implementation delta and must not be paired with a same-PR redesign.
    for identity, finding in sorted(base_findings.items()):
        if finding.path not in changed_source or identity in head_findings:
            continue
        contracts = _base_contract_covering(base_snapshot, finding)
        for contract in contracts:
            current = head_snapshot.contracts.get(contract.operation_id)
            if current is None or current.canonical_bytes != contract.canonical_bytes:
                errors.append(
                    f"removed destructive surface and BASE contract changed together for "
                    f"{contract.operation_id}: {finding.display()}"
                )
    return head_snapshot, errors


def _print_inventory(snapshot: Snapshot) -> None:
    for finding in snapshot.findings:
        owner = next(
            (
                contract.operation_id
                for contract in snapshot.contracts.values()
                if contract.covers(finding)
            ),
            None,
        )
        if owner is None:
            owner = next(
                (row.exemption_id for row in snapshot.exemptions if row.covers(finding)),
                "UNCLASSIFIED",
            )
        print(f"inventory={finding.display()}:owner={owner}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("repository", "pull_request"), default="repository")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--inventory", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = args.repo.resolve()
    try:
        if args.mode == "pull_request":
            if not args.base or not args.head:
                raise GateError("pull_request mode requires exact --base and --head")
            snapshot, errors = validate_pull_request(repo, args.base, args.head)
        else:
            if args.base or args.head:
                raise GateError("repository mode does not accept --base or --head")
            snapshot = load_worktree_snapshot(repo)
            errors = validate_snapshot(snapshot)
        if args.inventory:
            _print_inventory(snapshot)
        if errors:
            for error in errors:
                print(f"DESTRUCTIVE_DESIGN_GATE_ERROR: {error}", file=sys.stderr)
            return 1
        print(
            "DESTRUCTIVE_DESIGN_GATE_OK "
            f"contracts={len(snapshot.contracts)} "
            f"exemptions={len(snapshot.exemptions)} "
            f"surfaces={len(snapshot.findings)} mode={args.mode}"
        )
        return 0
    except GateError as exc:
        print(f"DESTRUCTIVE_DESIGN_GATE_ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # fail closed without an ordinary-user traceback
        print(
            f"DESTRUCTIVE_DESIGN_GATE_ERROR: unexpected checker failure: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
