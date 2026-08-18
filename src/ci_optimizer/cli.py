"""``ci-opt`` command-line interface.

Subcommands:

- ``classify``:          classify a change range into one of the stable
                         risk tiers (docs_fast / package_docs /
                         control_plane / full), with component impact.
                         Output formats: ``json`` (default),
                         ``env`` (production key=value lines), and
                         ``github-env`` (only valid GitHub Actions
                         ``CI_*`` environment assignments).
- ``verify-reuse``:      prove post-merge FULL reuse eligibility (V1).
                         Proof failure is never a CI failure: the CLI
                         always exits 0 for a proof verdict and prints
                         ``POST_MERGE_REUSE=false`` with a specific
                         ``reason=``.
- ``create-attestation``: write the FULL attestation JSON from CI
                         environment context (exits 1 on any failure so
                         the package job fails; attestation absence must
                         never enable reuse).

Exit codes:
- ``classify``: 0 = classification completed (any tier), 2 = usage /
  git resolution / config error (workflows convert to tier=full).
- ``verify-reuse``: 0 always (a proof failure is a verdict, not a CI
  failure).
- ``create-attestation``: 0 = attestation written, 1 = failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .attestation import create_attestation as _create_attestation
from .classifier import (
    REASON_CLASSIFIER_ERROR,
    REASON_INVALID_CONFIG,
    TIER_FULL,
    classify,
)
from .git import Git, GitError
from .github_api import GitHubAPI
from .policy import Config, ConfigError, load_config
from .post_merge_reuse import Verdict, render_verdict, run_verifier

# Deterministic JSON key order for the classify output.
_CLASSIFY_JSON_KEYS = (
    "tier",
    "reason",
    "components",
    "core_changed",
    "package_changed",
    "unknown_changed",
    "shared_changed",
    "independent_only",
    "full_matrix_required",
    "changed_files",
    "files",
)


def _print_classify(
    tier: str,
    reason: str,
    impact: Any,
    paths: list[str],
    output: str,
) -> None:
    if output == "github-env":
        # Only valid GitHub Actions environment assignments; no
        # "files:" / "- path" lines. Safe to append to $GITHUB_ENV.
        lines = [
            f"CI_TIER={tier}",
            f"CI_TIER_REASON={reason}",
            f"CI_COMPONENTS={','.join(impact.components) if impact.components else 'none'}",
            f"CI_CORE_CHANGED={'true' if impact.core_changed else 'false'}",
            f"CI_PACKAGE_CHANGED={'true' if impact.package_changed else 'false'}",
            f"CI_UNKNOWN_CHANGED={'true' if impact.unknown_changed else 'false'}",
            f"CI_SHARED_CHANGED={'true' if impact.shared_changed else 'false'}",
            f"CI_INDEPENDENT_ONLY={'true' if impact.independent_only else 'false'}",
            f"CI_FULL_MATRIX_REQUIRED={'true' if impact.full_matrix_required else 'false'}",
            f"CI_CHANGED_FILES={len(paths)}",
        ]
        sys.stdout.write("\n".join(lines) + "\n")
        return
    if output == "json":
        payload = {
            "tier": tier,
            "reason": reason,
            "components": list(impact.components),
            "core_changed": impact.core_changed,
            "package_changed": impact.package_changed,
            "unknown_changed": impact.unknown_changed,
            "shared_changed": impact.shared_changed,
            "independent_only": impact.independent_only,
            "full_matrix_required": impact.full_matrix_required,
            "changed_files": len(paths),
            "files": list(paths),
        }
        # Deterministic key order (stable json.dumps insertion order).
        ordered = {key: payload[key] for key in _CLASSIFY_JSON_KEYS}
        sys.stdout.write(json.dumps(ordered, indent=2, ensure_ascii=True) + "\n")
        return
    lines = [
        f"tier={tier}",
        f"reason={reason}",
        f"components={','.join(impact.components) if impact.components else 'none'}",
        f"core_changed={'true' if impact.core_changed else 'false'}",
        f"package_changed={'true' if impact.package_changed else 'false'}",
        f"unknown_changed={'true' if impact.unknown_changed else 'false'}",
        f"shared_changed={'true' if impact.shared_changed else 'false'}",
        f"independent_only={'true' if impact.independent_only else 'false'}",
        f"full_matrix_required={'true' if impact.full_matrix_required else 'false'}",
        f"changed_files={len(paths)}",
        "files:",
    ]
    for path in paths:
        lines.append(f"- {path}")
    sys.stdout.write("\n".join(lines) + "\n")


def _print_classify_error(reason: str, error: str, output: str) -> None:
    if output == "github-env":
        # Fail-closed assignment block: classifier inability is never a
        # fast tier. The workflow additionally re-exports these exact
        # values on any non-zero exit.
        sys.stdout.write(
            "CI_TIER=full\n"
            f"CI_TIER_REASON={reason}\n"
            "CI_FULL_MATRIX_REQUIRED=true\n"
        )
        return
    if output == "json":
        payload = {
            "tier": TIER_FULL,
            "reason": reason,
            "components": [],
            "core_changed": False,
            "package_changed": False,
            "unknown_changed": True,
            "shared_changed": False,
            "independent_only": False,
            "full_matrix_required": True,
            "changed_files": 0,
            "files": [],
            "error": error,
        }
        ordered = {key: payload[key] for key in (*_CLASSIFY_JSON_KEYS, "error")}
        sys.stdout.write(json.dumps(ordered, indent=2, ensure_ascii=True) + "\n")
        return
    sys.stdout.write(f"tier={TIER_FULL}\nreason={reason}\nerror={error}\n")


def cmd_classify(args: argparse.Namespace, *, git: Git | None = None) -> int:
    """Classify a change range. Any config / git / ref failure exits 2
    with tier=full in the output (the workflow fail-closes to FULL)."""
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        _print_classify_error(REASON_INVALID_CONFIG, str(exc), args.output)
        return 2
    g = git if git is not None else Git(args.repo)
    try:
        g.resolve_ref(args.base)
        g.resolve_ref(args.head)
        paths = g.changed_paths(
            args.base, args.head, merge_base=(args.mode == "pull_request")
        )
    except GitError as exc:
        _print_classify_error(REASON_CLASSIFIER_ERROR, exc.reason, args.output)
        return 2
    tier, reason, impact = classify(paths, config)
    _print_classify(tier, reason, impact, paths, args.output)
    return 0


def _print_verdict(verdict: Verdict) -> None:
    sys.stdout.write(render_verdict(verdict))


def cmd_verify(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Prove post-merge FULL reuse eligibility. Always exits 0 for a
    verdict; a proof failure is never a CI failure."""
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        _print_verdict(Verdict(False, "invalid_config_fail_closed"))
        print(f"error={exc}")
        return 0
    if not config.reuse_enabled:
        _print_verdict(Verdict(False, "reuse_disabled"))
        return 0
    repository = args.repo or env.get("GITHUB_REPOSITORY")
    event_name = args.event_name or env.get("GITHUB_EVENT_NAME")
    ref = args.ref or env.get("GITHUB_REF")
    main_sha = args.main_sha or env.get("GITHUB_SHA")
    token = env.get(args.token_env)

    before_sha = args.before
    if not before_sha:
        event_path = env.get("GITHUB_EVENT_PATH")
        if event_path:
            try:
                event = json.loads(Path(event_path).read_text(encoding="utf-8"))
                before_sha = event.get("before")
            except (OSError, ValueError):
                before_sha = None

    if not repository:
        _print_verdict(Verdict(False, "missing_repo_context"))
        return 0
    if not token:
        _print_verdict(Verdict(False, "missing_token"))
        return 0

    api = GitHubAPI(repository, token)
    git = Git()
    verdict = run_verifier(
        config=config,
        repository=repository,
        event_name=event_name,
        ref=ref,
        before_sha=before_sha,
        main_sha=main_sha,
        api=api,
        git=git,
    )
    _print_verdict(verdict)
    return 0


def cmd_create_attestation(args: argparse.Namespace, env: dict[str, str]) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"FULL_CI_ATTESTATION_FAILED reason=invalid_config_fail_closed")
        print(f"error={exc}")
        return 1
    return _create_attestation(
        args.path, env=env, git=Git(), workflow=config.workflow_name
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci-opt",
        description=(
            "Conservative, fail-closed CI optimization framework: "
            "risk-tier classification and exact-tree post-merge FULL reuse."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_classify = sub.add_parser(
        "classify", help="classify a change range into a risk tier"
    )
    p_classify.add_argument(
        "--config", required=True, metavar="PATH",
        help="framework config file (ciopt.toml)",
    )
    p_classify.add_argument(
        "--repo", default=".", metavar="PATH",
        help="repository root (default: current directory)",
    )
    p_classify.add_argument(
        "--mode", required=True, choices=("pull_request", "push"),
        help="pull_request uses the merge-base-correct three-dot diff; "
             "push uses the direct tree diff",
    )
    p_classify.add_argument(
        "--base", required=True, metavar="GIT_REF",
        help="base git ref (PR base SHA / push 'before' SHA)",
    )
    p_classify.add_argument(
        "--head", required=True, metavar="GIT_REF",
        help="head git ref (PR head SHA / pushed SHA)",
    )
    p_classify.add_argument(
        "--output", choices=("json", "env", "github-env"), default="json",
        help="output format (default: json); github-env emits only valid "
             "GitHub Actions CI_* environment assignments",
    )

    p_verify = sub.add_parser(
        "verify-reuse", help="prove post-merge FULL reuse eligibility (V1)"
    )
    p_verify.add_argument("--config", required=True, metavar="PATH")
    p_verify.add_argument(
        "--repo", metavar="OWNER/REPO", help="default $GITHUB_REPOSITORY"
    )
    p_verify.add_argument("--event-name", help="default $GITHUB_EVENT_NAME")
    p_verify.add_argument("--ref", help="git ref (default $GITHUB_REF)")
    p_verify.add_argument(
        "--before", metavar="SHA", help="previous main SHA (default from event file)"
    )
    p_verify.add_argument("--main-sha", metavar="SHA", help="default $GITHUB_SHA")
    p_verify.add_argument(
        "--token-env", default="GITHUB_TOKEN",
        help="env var holding the token (default GITHUB_TOKEN)",
    )

    p_create = sub.add_parser(
        "create-attestation",
        help="write the FULL attestation JSON from CI env context",
    )
    p_create.add_argument("--config", required=True, metavar="PATH")
    p_create.add_argument("path", metavar="PATH", help="output JSON path")

    return parser


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    env = env if env is not None else os.environ
    args = build_parser().parse_args(argv)
    if args.command == "classify":
        return cmd_classify(args)
    if args.command == "verify-reuse":
        return cmd_verify(args, env)
    return cmd_create_attestation(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
