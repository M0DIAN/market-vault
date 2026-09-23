"""Offline policy and project-configuration checks. No Codex/API/Git invocation."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts.codex_model_router import InputError, ROLE_SPECS, choose_route, normalize_path, read_json

ROOT = Path(__file__).resolve().parents[1]
MODELS = ["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"]


def task(**updates):
    value = {
        "schema_version": 1, "task_id": "routing-smoke-1", "phase": "discovery",
        "complexity": "medium", "ambiguity": "low", "scope_clear": True,
        "risk_signals": [], "changed_paths": [], "write_authorized": False,
        "authorization_reference": "", "approved_paths": [], "risk_review_reference": "",
        "failure_kind": "none", "phase_attempt": 1, "available_models": MODELS.copy(),
        "effective_parent_sandbox": "read-only",
        "permission_evidence_reference": "offline-fixture:parent-turn-1",
    }
    value.update(updates)
    return value


class RoutingTests(unittest.TestCase):
    def test_normal_discovery_sol(self):
        self.assertEqual(choose_route(task())["role"], "mv_analyst")

    def test_mechanical_luna(self):
        self.assertEqual(choose_route(task(phase="mechanical", complexity="low"))["role"], "mv_inventory")

    def test_validation_readback_luna(self):
        self.assertEqual(choose_route(task(phase="validation_readback", complexity="low"))["requested_model"], MODELS[0])

    def test_adversarial_astra(self):
        self.assertEqual(choose_route(task(phase="adversarial_review"))["role"], "mv_reasoner")

    def test_convergence_astra(self):
        self.assertEqual(choose_route(task(phase="evidence_convergence"))["role"], "mv_reasoner")

    def test_final_review_astra_high(self):
        r = choose_route(task(phase="exact_head_review", complexity="low"))
        self.assertEqual((r["role"], r["requested_effort"], r["requested_sandbox"]), ("mv_reviewer", "high", "read-only"))

    def test_publish_gate_cannot_authorize_merge(self):
        r = choose_route(task(phase="publish_gate"))
        self.assertEqual(r["role"], "mv_reviewer")
        self.assertFalse(r["authority_granted"])
        self.assertFalse(r["automatic_remote_write"])

    def test_ambiguity_upgrade(self):
        self.assertEqual(choose_route(task(phase="mechanical", complexity="low", ambiguity="high"))["role"], "mv_reasoner")

    def test_complexity_upgrade(self):
        self.assertEqual(choose_route(task(complexity="high"))["role"], "mv_reasoner")

    def test_risk_overrides_luna(self):
        r = choose_route(task(phase="mechanical", complexity="low", risk_signals=["security_boundary"]))
        self.assertEqual(r["role"], "mv_reasoner")

    def test_sensitive_paths_not_file_extension_heuristic(self):
        for path in ["AGENTS.md", ".codex/agents/a.toml", ".GITHUB/workflows/x.yml", "docs/governance/x.md", "ci/components.toml", "scripts/codex_model_router.py"]:
            with self.subTest(path=path):
                self.assertEqual(choose_route(task(changed_paths=[path]))["role"], "mv_reasoner")

    def test_scope_uncertain_cannot_downgrade(self):
        self.assertEqual(choose_route(task(phase="mechanical", complexity="low", scope_clear=False))["role"], "mv_reasoner")

    def test_missing_write_auth_holds(self):
        self.assertEqual(choose_route(task(phase="implementation"))["decision"], "HOLD")

    def test_boolean_auth_without_reference_holds(self):
        r = choose_route(task(phase="implementation", write_authorized=True))
        self.assertIn("EXPLICIT_SCOPED_WRITE_AUTHORIZATION_REQUIRED", r["reason_codes"])

    def test_approved_plan_builder(self):
        r = choose_route(task(phase="implementation", effective_parent_sandbox="workspace-write", write_authorized=True,
                             authorization_reference="work-order-1", changed_paths=["src/ui.py"], approved_paths=["src/ui.py"]))
        self.assertEqual(r["role"], "mv_builder")
        self.assertEqual(r["decision"], "DISPATCH_REQUEST")
        self.assertFalse(r["authority_granted"])

    def test_out_of_scope_write_holds(self):
        r = choose_route(task(phase="implementation", effective_parent_sandbox="workspace-write", write_authorized=True,
                             authorization_reference="work-order-1", changed_paths=["src/data.py"], approved_paths=["src/ui.py"]))
        self.assertIn("PATH_OUTSIDE_APPROVED_SCOPE", r["reason_codes"])

    def test_sensitive_write_needs_review(self):
        r = choose_route(task(phase="implementation", effective_parent_sandbox="workspace-write", write_authorized=True,
                             authorization_reference="work-order-1", changed_paths=["AGENTS.md"], approved_paths=["AGENTS.md"]))
        self.assertIn("ASTRA_READONLY_PLAN_REVIEW_REQUIRED_BEFORE_WRITING", r["reason_codes"])

    def test_sensitive_write_after_review(self):
        r = choose_route(task(phase="implementation", effective_parent_sandbox="workspace-write", write_authorized=True,
                             authorization_reference="work-order-1", risk_review_reference="review-record-1",
                             changed_paths=["AGENTS.md"], approved_paths=["AGENTS.md"]))
        self.assertEqual(r["decision"], "DISPATCH_REQUEST")

    def test_two_failed_attempts_escalate(self):
        r = choose_route(task(phase_attempt=3, failure_kind="reasoning"))
        self.assertEqual(r["role"], "mv_reasoner")

    def test_attempt_budget_stops(self):
        self.assertEqual(choose_route(task(phase_attempt=4))["decision"], "HOLD")

    def test_environment_is_not_reasoning_failure(self):
        for failure in ("authentication", "sandbox", "environment", "quota"):
            with self.subTest(failure=failure):
                r = choose_route(task(failure_kind=failure))
                self.assertEqual(r["decision"], "HOLD")
                self.assertIsNone(r["requested_model"])

    def test_remote_write_holds_even_with_write_flag(self):
        self.assertEqual(choose_route(task(phase="remote_write", write_authorized=True,
                                         authorization_reference="owner-message"))["decision"], "HOLD")

    def test_unavailable_astra_never_silently_falls_back(self):
        r = choose_route(task(phase="exact_head_review", available_models=["gpt-6-sol"]))
        self.assertEqual(r["decision"], "HOLD")
        self.assertEqual(r["requested_model"], "gpt-6-astra")

    def test_empty_catalog_cannot_activate(self):
        self.assertEqual(choose_route(task(available_models=[]))["decision"], "HOLD")

    def test_sticky_no_downgrade_inside_phase(self):
        old = {"task_id": "routing-smoke-1", "phase": "discovery", "role": "mv_reasoner", "checkpoint_closed": False}
        self.assertEqual(choose_route(task(), old)["role"], "mv_reasoner")

    def test_downgrade_after_closed_checkpoint(self):
        old = {"task_id": "routing-smoke-1", "phase": "discovery", "role": "mv_reasoner", "checkpoint_closed": True}
        self.assertEqual(choose_route(task(), old)["role"], "mv_analyst")

    def test_phase_change_reselects(self):
        old = {"task_id": "routing-smoke-1", "phase": "discovery", "role": "mv_reasoner", "checkpoint_closed": True}
        self.assertEqual(choose_route(task(phase="mechanical", complexity="low"), old)["role"], "mv_inventory")

    def test_new_phase_requires_old_checkpoint_closed(self):
        old = {"task_id": "routing-smoke-1", "phase": "discovery", "role": "mv_reasoner", "checkpoint_closed": False}
        r = choose_route(task(phase="mechanical", complexity="low"), old)
        self.assertEqual(r["decision"], "HOLD")
        self.assertIn("PREVIOUS_PHASE_CHECKPOINT_STILL_OPEN", r["reason_codes"])

    def test_escalation_requires_stopping_old_child(self):
        old = {"task_id": "routing-smoke-1", "phase": "discovery", "role": "mv_analyst", "checkpoint_closed": False}
        r = choose_route(task(risk_signals=["evidence_conflict"]), old)
        self.assertEqual(r["transition"], "stop_child_then_escalate_at_checkpoint")

    def test_writer_cannot_be_smuggled_into_read_phase(self):
        old = {"task_id": "routing-smoke-1", "phase": "discovery", "role": "mv_builder", "checkpoint_closed": False}
        with self.assertRaises(InputError):
            choose_route(task(), old)

    def test_cross_task_state_rejected(self):
        old = {"task_id": "other", "phase": "discovery", "role": "mv_analyst", "checkpoint_closed": False}
        with self.assertRaises(InputError):
            choose_route(task(), old)

    def test_unknown_and_missing_fields_rejected(self):
        extra = task(); extra["grant_merge"] = True
        missing = task(); del missing["scope_clear"]
        for value in (extra, missing):
            with self.assertRaises(InputError):
                choose_route(value)

    def test_wrong_types_rejected(self):
        for field, value in [("write_authorized", "true"), ("phase_attempt", True), ("schema_version", True), ("risk_signals", "security_boundary")]:
            with self.subTest(field=field), self.assertRaises(InputError):
                choose_route(task(**{field: value}))

    def test_unknown_enums_rejected(self):
        for update in [{"phase": "invented"}, {"failure_kind": "maybe"}, {"risk_signals": ["invented"]}]:
            with self.assertRaises(InputError):
                choose_route(task(**update))

    def test_invalid_paths_rejected(self):
        for value in ["/tmp/file", "D:\\file", "../file", "a/../file", "a//file", "a/*", "a/./file", "a./file"]:
            with self.subTest(value=value), self.assertRaises(InputError):
                normalize_path(value)

    def test_windows_paths_canonicalized(self):
        self.assertEqual(normalize_path("Docs\\GOVERNANCE\\x.md"), "docs/governance/x.md")

    def test_case_equivalent_duplicate_paths_rejected(self):
        with self.assertRaises(InputError):
            choose_route(task(changed_paths=["AGENTS.md", "agents.md"]))

    def test_no_input_mutation(self):
        t = task(); before = copy.deepcopy(t)
        choose_route(t)
        self.assertEqual(t, before)

    def test_requested_model_is_not_observed_model(self):
        r = choose_route(task())
        self.assertIsNone(r["observed_model"])
        self.assertFalse(r["runtime_dispatch_verified"])

    def test_no_authority_grant_in_any_phase(self):
        from scripts.codex_model_router import PHASES
        for phase in PHASES:
            self.assertFalse(choose_route(task(phase=phase))["authority_granted"])

    def test_all_readonly_phases_require_exact_readonly_parent(self):
        phases = {
            "mechanical": ("mv_inventory", "gpt-6-luna", "low"),
            "discovery": ("mv_analyst", "gpt-6-sol", "medium"),
            "adversarial_review": ("mv_reasoner", "gpt-6-astra", "medium"),
            "evidence_convergence": ("mv_reasoner", "gpt-6-astra", "medium"),
            "patch_planning": ("mv_analyst", "gpt-6-sol", "medium"),
            "validation_readback": ("mv_inventory", "gpt-6-luna", "low"),
            "exact_head_review": ("mv_reviewer", "gpt-6-astra", "high"),
            "publish_gate": ("mv_reviewer", "gpt-6-astra", "high"),
        }
        for phase, expected in phases.items():
            for parent in ("read-only", "workspace-write", "danger-full-access", "unknown"):
                with self.subTest(phase=phase, parent=parent):
                    r = choose_route(task(phase=phase, complexity="low", effective_parent_sandbox=parent))
                    self.assertEqual((r["role"], r["requested_model"], r["requested_effort"]), expected)
                    self.assertEqual(r["required_parent_sandbox"], "read-only")
                    self.assertEqual(r["effective_parent_sandbox"], parent)
                    self.assertEqual(r["decision"], "DISPATCH_REQUEST" if parent == "read-only" else "HOLD")
                    self.assertFalse(r["authority_granted"])
                    self.assertFalse(r["automatic_remote_write"])
                    self.assertFalse(r["runtime_permissions_verified"])
                    if parent != "read-only":
                        self.assertEqual(r["reason_codes"][-1], "READONLY_ROLE_REQUIRES_READONLY_PARENT")
                        self.assertIsNone(r["next_state"])
                        self.assertEqual(r["transition"], "none")

    def test_builder_requires_exact_workspace_write_parent_and_authority(self):
        for parent in ("read-only", "workspace-write", "danger-full-access", "unknown"):
            with self.subTest(parent=parent):
                r = choose_route(task(
                    phase="implementation", effective_parent_sandbox=parent,
                    write_authorized=True, authorization_reference="work-order-1",
                    changed_paths=["fixture.txt"], approved_paths=["fixture.txt"]))
                self.assertEqual((r["role"], r["requested_model"], r["requested_effort"]),
                                 ("mv_builder", "gpt-6-sol", "medium"))
                self.assertEqual(r["required_parent_sandbox"], "workspace-write")
                self.assertEqual(r["decision"], "DISPATCH_REQUEST" if parent == "workspace-write" else "HOLD")
                self.assertFalse(r["authority_granted"])
                self.assertFalse(r["automatic_remote_write"])
                if parent != "workspace-write":
                    self.assertEqual(r["reason_codes"][-1], "BUILDER_REQUIRES_WORKSPACE_WRITE_PARENT")
                    self.assertIsNone(r["next_state"])
        r = choose_route(task(phase="implementation", effective_parent_sandbox="workspace-write"))
        self.assertEqual(r["decision"], "HOLD")
        self.assertIn("EXPLICIT_SCOPED_WRITE_AUTHORIZATION_REQUIRED", r["reason_codes"])

    def test_remote_write_holds_for_every_parent_even_without_permission_evidence(self):
        for parent in ("read-only", "workspace-write", "danger-full-access", "unknown"):
            for reference in ("parent-turn-evidence-1", ""):
                with self.subTest(parent=parent, reference=reference):
                    r = choose_route(task(phase="remote_write", effective_parent_sandbox=parent,
                                          permission_evidence_reference=reference, write_authorized=True,
                                          authorization_reference="owner-message"))
                    self.assertEqual(r["decision"], "HOLD")
                    self.assertEqual(r["reason_codes"],
                                     ["USE_SEPARATELY_AUTHORIZED_EXECUTOR_AND_EXACT_OBJECT_RECHECK"])
                    self.assertIsNone(r["next_state"])
                    self.assertFalse(r["authority_granted"])
                    self.assertFalse(r["automatic_remote_write"])

    def test_matching_parent_without_evidence_reference_holds(self):
        for phase, parent in (("discovery", "read-only"), ("implementation", "workspace-write")):
            for reference in ("", "   "):
                with self.subTest(phase=phase, reference=reference):
                    r = choose_route(task(phase=phase, effective_parent_sandbox=parent,
                                          permission_evidence_reference=reference, write_authorized=True,
                                          authorization_reference="work-order-1", changed_paths=["fixture.txt"],
                                          approved_paths=["fixture.txt"]))
                    self.assertEqual(r["decision"], "HOLD")
                    self.assertEqual(r["reason_codes"][-1], "CURRENT_PARENT_PERMISSION_EVIDENCE_REQUIRED")
                    self.assertIsNone(r["next_state"])

    def test_parent_permission_fields_are_required_not_inferred_from_role(self):
        for field in ("effective_parent_sandbox", "permission_evidence_reference"):
            value = task(); del value[field]
            with self.subTest(field=field), self.assertRaises(InputError):
                choose_route(value)

    def test_parent_permission_schema_is_closed_and_typed(self):
        for parent in (None, True, [], {}, "", "READ-ONLY", "workspace_write", "external-sandbox"):
            with self.subTest(parent=parent), self.assertRaises(InputError):
                choose_route(task(effective_parent_sandbox=parent))
        for reference in (None, True, [], {}, "line\nbreak", "x" * 1025):
            with self.subTest(reference=reference), self.assertRaises(InputError):
                choose_route(task(permission_evidence_reference=reference))

    def test_permission_claims_are_distinct_from_role_defaults_and_runtime_proof(self):
        r = choose_route(task(effective_parent_sandbox="workspace-write",
                              permission_evidence_reference="runtime-record:parent-7/turn-3"))
        self.assertEqual(r["requested_sandbox"], "read-only")
        self.assertEqual(r["required_parent_sandbox"], "read-only")
        self.assertEqual(r["effective_parent_sandbox"], "workspace-write")
        self.assertEqual(r["permission_evidence_reference"], "runtime-record:parent-7/turn-3")
        self.assertFalse(r["runtime_permissions_verified"])
        self.assertFalse(r["runtime_dispatch_verified"])
        self.assertEqual(r["decision"], "HOLD")

    def test_sticky_role_cannot_bypass_current_parent_permission_gate(self):
        old = {"task_id": "routing-smoke-1", "phase": "discovery", "role": "mv_reasoner", "checkpoint_closed": False}
        before = copy.deepcopy(old)
        r = choose_route(task(effective_parent_sandbox="workspace-write"), old)
        self.assertEqual(r["role"], "mv_reasoner")
        self.assertIn("STICKY_NO_DOWNGRADE_BEFORE_CHECKPOINT", r["reason_codes"])
        self.assertEqual(r["decision"], "HOLD")
        self.assertEqual(r["reason_codes"][-1], "READONLY_ROLE_REQUIRES_READONLY_PARENT")
        self.assertIsNone(r["next_state"])
        self.assertEqual(old, before)

    def test_matching_parent_cannot_bypass_model_availability(self):
        for phase, parent in (("discovery", "read-only"), ("implementation", "workspace-write")):
            r = choose_route(task(phase=phase, effective_parent_sandbox=parent,
                                  available_models=[], write_authorized=True,
                                  authorization_reference="work-order-1", changed_paths=["fixture.txt"],
                                  approved_paths=["fixture.txt"]))
            self.assertEqual(r["decision"], "HOLD")
            self.assertIn("REQUIRED_MODEL_UNAVAILABLE_NO_SILENT_FALLBACK", r["reason_codes"])

    def test_cli_permission_mismatch_is_nonzero_without_next_state(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/codex_model_router.py"), "--task", "-"],
                              input=json.dumps(task(phase="mechanical", complexity="low",
                                                    effective_parent_sandbox="workspace-write")),
                              text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 3, proc.stderr)
        r = json.loads(proc.stdout)
        self.assertEqual(r["decision"], "HOLD")
        self.assertEqual(r["reason_codes"][-1], "READONLY_ROLE_REQUIRES_READONLY_PARENT")
        self.assertIsNone(r["next_state"])

    def test_agent_toml_matches_policy(self):
        for name, (model, effort, sandbox, _) in ROLE_SPECS.items():
            p = ROOT / ".codex" / "agents" / f"{name}.toml"
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            with self.subTest(role=name):
                self.assertEqual((data["name"], data["model"], data["model_reasoning_effort"], data["sandbox_mode"]),
                                 (name, model, effort, sandbox))
                self.assertTrue(data["description"])
                self.assertTrue(data["developer_instructions"])
                self.assertNotIn("approval_policy", data)
                self.assertNotIn("mcp_servers", data)

    def test_exact_hold_reasons_do_not_hide_other_guards(self):
        cases = [
            (task(phase="implementation"), "EXPLICIT_SCOPED_WRITE_AUTHORIZATION_REQUIRED"),
            (task(phase="implementation", scope_clear=False), "SCOPE_NOT_FROZEN"),
            (task(phase="remote_write", write_authorized=True,
                  authorization_reference="owner-message"),
             "USE_SEPARATELY_AUTHORIZED_EXECUTOR_AND_EXACT_OBJECT_RECHECK"),
            (task(available_models=[]), "REQUIRED_MODEL_UNAVAILABLE_NO_SILENT_FALLBACK"),
            (task(phase_attempt=4), "PHASE_ATTEMPT_BUDGET_EXHAUSTED"),
        ]
        for value, reason in cases:
            with self.subTest(reason=reason):
                result = choose_route(value)
                self.assertEqual(result["decision"], "HOLD")
                expected = (["NORMAL_DISCOVERY_OR_PLANNING", reason]
                            if reason == "REQUIRED_MODEL_UNAVAILABLE_NO_SILENT_FALLBACK"
                            else [reason])
                self.assertEqual(result["reason_codes"], expected)
                self.assertIsNone(result["next_state"])

    def test_repeated_writer_failure_holds_after_all_authority_checks(self):
        result = choose_route(task(
            phase="implementation", effective_parent_sandbox="workspace-write", phase_attempt=3, failure_kind="test",
            write_authorized=True, authorization_reference="work-order-1",
            risk_review_reference="independent-plan-reference",
            changed_paths=["fixture.txt"], approved_paths=["fixture.txt"]))
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["reason_codes"],
                         ["STOP_REPEATED_PATCHING_AND_REOPEN_REASONING_CHECKPOINT"])

    def test_malformed_state_types_raise_input_error(self):
        for field in ("task_id", "phase", "role"):
            for value in ([], {}, None, True):
                state = {"task_id": "routing-smoke-1", "phase": "discovery",
                         "role": "mv_analyst", "checkpoint_closed": False}
                state[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(InputError):
                    choose_route(task(), state)

    def test_cli_malformed_json_and_excessive_nesting(self):
        for raw in ("", "{", "[]", "[" * 2000 + "]" * 2000):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts/codex_model_router.py"), "--task", "-"],
                input=raw, text=True, capture_output=True, check=False)
            with self.subTest(raw_length=len(raw)):
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["decision"], "INVALID_INPUT")

    def test_input_byte_limit(self):
        from scripts.codex_model_router import MAX_INPUT_BYTES
        with tempfile.TemporaryDirectory(prefix="mv-router-") as temp:
            p = Path(temp) / "oversize.json"
            p.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            with self.assertRaisesRegex(InputError, "input exceeds byte limit"):
                read_json(str(p))

    def test_project_defaults_and_no_duplicate_registration(self):
        config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
        self.assertEqual((config["model"], config["model_reasoning_effort"]),
                         ("gpt-6-sol", "medium"))
        self.assertTrue(config["agents"]["enabled"])
        self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 1)
        self.assertFalse(set(ROLE_SPECS) & set(config["agents"]))
        names = []
        for name in ROLE_SPECS:
            role = tomllib.loads((ROOT / f".codex/agents/{name}.toml").read_text(encoding="utf-8"))
            names.append(role["name"])
            self.assertFalse(role["agents"]["enabled"])
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse({"approval_policy", "permissions", "projects", "model_provider"} & set(config))

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory(prefix="mv-router-") as temp:
            p = Path(temp) / "duplicate.json"
            p.write_text('{"phase":"mechanical","phase":"remote_write"}', encoding="utf-8")
            with self.assertRaises(InputError):
                read_json(str(p))

    def test_cli_emits_parseable_decision(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/codex_model_router.py"), "--task", "-"],
                              input=json.dumps(task()), text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["decision"], "DISPATCH_REQUEST")

    def test_cli_holds_with_nonzero_exit(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/codex_model_router.py"), "--task", "-"],
                              input=json.dumps(task(phase="remote_write")), text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(json.loads(proc.stdout)["decision"], "HOLD")

    def test_cli_invalid_input_not_pass(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/codex_model_router.py"), "--task", "-"],
                              input="{}", text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["decision"], "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
