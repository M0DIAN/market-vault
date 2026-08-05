"""Render the verified Dataset CLI example plans from their templates.

This is an examples-only, Python 3.11 standard-library helper. It is NOT
part of the ``market_vault`` package, is not a public API, and never calls
the CLI or the Dataset chain. It copies the example FeatureSpec / LabelSpec
files and the standalone chronological split spec into one destination
bundle and renders ``complete.plan.json`` and ``empty.plan.json`` by
substituting the template placeholders with JSON structure edits (never
with raw string replacement).

Renderer contract:

- ``--canonical-build-dir`` is repeatable and at least one is required;
- ``--output-root``, ``--built-at`` and ``--destination`` are required;
- ``--dataset-as-of`` is optional;
- ``built_at`` and ``dataset_as_of`` must be timezone-aware ISO 8601
  datetimes; naive values fail with a non-zero exit code;
- both datetimes are normalized to UTC with microsecond precision;
- the rendered plans keep the exact example spec paths relative to the
  plan files (``specs/...``);
- no ``latest`` lookup, no directory scanning, no glob / environment
  expansion, no Canonical discovery, no ``datetime.now()``, no network,
  no OpenD, no settings;
- an existing non-empty destination is never overwritten;
- output is UTF-8 with ``indent=2`` and a trailing newline; identical
  inputs produce byte-identical bundles.

Exit codes: 0 on success, 1 on any documented renderer failure, 2 for
argparse usage errors.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent
PLANS_DIR = EXAMPLES_DIR / "plans"
SPECS_DIR = EXAMPLES_DIR / "specs"
SPLIT_SPECS_DIR = EXAMPLES_DIR / "split_specs"

PLACEHOLDERS = frozenset(
    {
        "<CANONICAL_BUILD_DIR>",
        "<OUTPUT_ROOT>",
        "<BUILT_AT>",
    }
)


class RendererError(Exception):
    """Documented renderer failure with a stable message."""


def _reject_blank(text: str, label: str) -> None:
    """Reject an empty or whitespace-only path argument.

    The check uses ``strip()`` only to decide blankness; the plan always
    carries the user's original non-empty path string unchanged."""
    if not text or not text.strip():
        raise RendererError(f"{label} must not be empty or whitespace-only")


def _parse_aware_datetime(text: str, label: str) -> str:
    """Parse one timezone-aware ISO 8601 datetime and normalize it to UTC
    with a fixed six-digit microsecond field, exactly like the Dataset
    CLI's ``built_at`` handling. Naive values are rejected; the system
    local timezone is never used; ``Z`` is never emitted."""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RendererError(f"{label} must be an ISO 8601 datetime, got {text!r}") from exc
    if parsed.tzinfo is None:
        raise RendererError(
            f"{label} must be timezone-aware, got a naive value {text!r}"
        )
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _load_json(path: Path, label: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RendererError(f"cannot read {label} {path}: {exc}") from exc


def _assert_no_placeholders(value, label: str) -> None:
    """Recursively reject any template placeholder that was left behind."""
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_no_placeholders(key, label)
            _assert_no_placeholders(item, label)
    elif isinstance(value, list):
        for item in value:
            _assert_no_placeholders(item, label)
    elif isinstance(value, str):
        if "<" in value and ">" in value:
            raise RendererError(f"{label} still contains a template placeholder {value!r}")


def _render_template(
    template: dict,
    *,
    canonical_dirs: list[str],
    split_spec: dict,
    dataset_as_of: str | None,
    output_root: str,
    built_at: str,
    label: str,
) -> dict:
    plan = copy.deepcopy(template)
    plan["canonical_build_dirs"] = list(canonical_dirs)
    plan["split_spec"] = copy.deepcopy(split_spec)
    plan["dataset_as_of"] = dataset_as_of
    plan["output_root"] = output_root
    plan["built_at"] = built_at
    _assert_no_placeholders(plan, label)
    return plan


def _write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def render(
    *,
    canonical_dirs: list[str],
    output_root: str,
    built_at: str,
    destination: Path,
    dataset_as_of: str | None = None,
) -> None:
    """Render one example bundle into ``destination`` (which must not exist
    or must be empty)."""
    if not canonical_dirs:
        raise RendererError("at least one --canonical-build-dir is required")
    if destination.exists():
        if not destination.is_dir():
            raise RendererError(
                f"destination exists and is not a directory: {destination}"
            )
        if any(destination.iterdir()):
            raise RendererError(
                "destination must be empty or not exist, "
                f"refusing to overwrite: {destination}"
            )

    built_at_utc = _parse_aware_datetime(built_at, "built_at")
    dataset_as_of_utc = (
        _parse_aware_datetime(dataset_as_of, "dataset_as_of")
        if dataset_as_of is not None
        else None
    )
    split_spec = _load_json(
        SPLIT_SPECS_DIR / "chronological_v1.json", "split spec"
    )
    complete_template = _load_json(
        PLANS_DIR / "complete.plan.template.json", "complete plan template"
    )
    empty_template = _load_json(
        PLANS_DIR / "empty.plan.template.json", "empty plan template"
    )

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "specs").mkdir(exist_ok=True)
    (destination / "split_specs").mkdir(exist_ok=True)

    complete = _render_template(
        complete_template,
        canonical_dirs=canonical_dirs,
        split_spec=split_spec,
        dataset_as_of=dataset_as_of_utc,
        output_root=output_root,
        built_at=built_at_utc,
        label="complete plan",
    )
    empty = _render_template(
        empty_template,
        canonical_dirs=canonical_dirs,
        split_spec=split_spec,
        dataset_as_of=dataset_as_of_utc,
        output_root=output_root,
        built_at=built_at_utc,
        label="empty plan",
    )

    _write_json(destination / "complete.plan.json", complete)
    _write_json(destination / "empty.plan.json", empty)
    for name in ("feature_simple_return_v1.yaml", "label_forward_return_v1.yaml"):
        source = SPECS_DIR / name
        (destination / "specs" / name).write_bytes(source.read_bytes())
    (destination / "split_specs" / "chronological_v1.json").write_bytes(
        (SPLIT_SPECS_DIR / "chronological_v1.json").read_bytes()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_plans.py",
        description=(
            "Render the verified Dataset CLI example bundle: complete and "
            "empty build plans plus the FeatureSpec / LabelSpec / split spec "
            "copies into --destination."
        ),
    )
    parser.add_argument(
        "--canonical-build-dir",
        action="append",
        required=True,
        metavar="PATH",
        help="Verified Canonical final build directory (repeatable, at least one)",
    )
    parser.add_argument("--output-root", required=True, metavar="PATH")
    parser.add_argument("--built-at", required=True, metavar="ISO8601")
    parser.add_argument("--destination", required=True, metavar="PATH")
    parser.add_argument("--dataset-as-of", metavar="ISO8601", default=None)
    args = parser.parse_args(argv)

    try:
        # Blank checks run on the raw argument strings so that an empty
        # destination can never be silently interpreted as the current
        # directory by Path("").
        for directory in args.canonical_build_dir:
            _reject_blank(directory, "--canonical-build-dir")
        _reject_blank(args.output_root, "--output-root")
        _reject_blank(args.destination, "--destination")
        render(
            canonical_dirs=args.canonical_build_dir,
            output_root=args.output_root,
            built_at=args.built_at,
            dataset_as_of=args.dataset_as_of,
            destination=Path(args.destination),
        )
    except RendererError as exc:
        print(f"render_plans: error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"render_plans: error: filesystem operation failed: {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"rendered example bundle to {Path(args.destination)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
