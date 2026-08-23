from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyarrow.parquet as pq

from .lifecycle import (
    LifecycleLockError,
    MarketBarLifecycleLock,
    reject_link,
    verify_directory_chain,
)
from .models import Settings
from .storage import Catalog


PURGE_PLAN_VERSION = "market-vault-safe-purge-plan-v2"
PURGE_RESULT_VERSION = "market-vault-safe-purge-result-v2"
PURGE_PRECOMMIT_VERSION = "market-vault-safe-purge-precommit-v1"
RETENTION_POLICY = "RETAIN_VERIFIED_DERIVED_ARTIFACTS_V1"
_PLAN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_PARTITION_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class PurgeError(RuntimeError):
    """Base error for Safe Purge."""


class PurgeRefusedError(PurgeError):
    """The sealed plan is intentionally non-executable."""


class PurgeDriftError(PurgeError):
    """The active archive no longer matches the sealed plan."""


@dataclass(frozen=True)
class PurgeScope:
    source: str
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    interval: str
    requested_session: str
    adjustment: str
    source_schema_version: str

    @classmethod
    def create(
        cls,
        *,
        source: str,
        symbols: list[str] | tuple[str, ...],
        start_date: date,
        end_date: date,
        interval: str,
        requested_session: str,
        adjustment: str,
        source_schema_version: str,
    ) -> "PurgeScope":
        normalized_source = _partition_value(source, "source")
        normalized_symbols = tuple(sorted({_symbol(value) for value in symbols}))
        if not normalized_symbols:
            raise ValueError("at least one exact symbol is required")
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        normalized_interval = _partition_value(interval.lower(), "interval")
        normalized_session = _nonblank(requested_session, "requested_session").upper()
        normalized_adjustment = _nonblank(adjustment, "adjustment").upper()
        normalized_schema = _nonblank(source_schema_version, "source_schema_version")
        return cls(
            normalized_source,
            normalized_symbols,
            start_date,
            end_date,
            normalized_interval,
            normalized_session,
            normalized_adjustment,
            normalized_schema,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "symbols": list(self.symbols),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "interval": self.interval,
            "requested_session": self.requested_session,
            "adjustment": self.adjustment,
            "source_schema_version": self.source_schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PurgeScope":
        return cls.create(
            source=value["source"],
            symbols=value["symbols"],
            start_date=date.fromisoformat(value["start_date"]),
            end_date=date.fromisoformat(value["end_date"]),
            interval=value["interval"],
            requested_session=value["requested_session"],
            adjustment=value["adjustment"],
            source_schema_version=value["source_schema_version"],
        )


@dataclass(frozen=True)
class PurgePlan:
    plan_id: str
    content_hash: str
    status: str
    scope: PurgeScope
    targets: tuple[dict[str, Any], ...]
    summary: dict[str, Any]
    dependency_state: dict[str, Any]
    retained_evidence: tuple[str, ...]
    refusal_reasons: tuple[dict[str, Any], ...]
    quarantine_root: str
    plan_file: str

    @property
    def executable(self) -> bool:
        return self.status == "PLANNED" and not self.refusal_reasons

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_version": PURGE_PLAN_VERSION,
            "plan_id": self.plan_id,
            "content_hash": self.content_hash,
            "status": self.status,
            "scope": self.scope.as_dict(),
            "targets": list(self.targets),
            "summary": self.summary,
            "dependency_state": self.dependency_state,
            "retained_evidence": list(self.retained_evidence),
            "refusal_reasons": list(self.refusal_reasons),
            "quarantine_root": self.quarantine_root,
            "plan_file": self.plan_file,
        }


@dataclass(frozen=True)
class PurgeResult:
    result_version: str
    plan_id: str
    content_hash: str
    evidence_hash: str
    status: str
    moved_files: tuple[dict[str, Any], ...]
    result_file: str
    completed_at: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "result_version": self.result_version,
            "plan_id": self.plan_id,
            "content_hash": self.content_hash,
            "evidence_hash": self.evidence_hash,
            "status": self.status,
            "moved_files": list(self.moved_files),
            "result_file": self.result_file,
            "completed_at": self.completed_at,
            "message": self.message,
        }


@dataclass(frozen=True)
class _Facts:
    row_count: int
    symbols: tuple[str, ...]
    dates: tuple[str, ...]
    intervals: tuple[str, ...]
    sessions: tuple[str, ...]
    adjustments: tuple[str, ...]
    run_ids: tuple[str, ...]
    sources: tuple[str, ...] = ()
    schema_versions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "symbols": list(self.symbols),
            "dates": list(self.dates),
            "intervals": list(self.intervals),
            "requested_sessions": list(self.sessions),
            "adjustments": list(self.adjustments),
            "ingestion_run_ids": list(self.run_ids),
            "sources": list(self.sources),
            "source_schema_versions": list(self.schema_versions),
        }


def _nonblank(value: Any, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} cannot be blank")
    return text


def _partition_value(value: Any, label: str) -> str:
    text = _nonblank(value, label)
    if not _PARTITION_RE.fullmatch(text) or text in {".", ".."} or ".." in text:
        raise ValueError(f"unsafe {label}: {text!r}")
    return text


def _symbol(value: Any) -> str:
    return _partition_value(value, "symbol").upper()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _path_from_metadata(settings: Settings, text: str) -> Path:
    path = Path(text)
    return Path(os.path.abspath(path if path.is_absolute() else settings.project_root / path))


def _assert_safe_file(path: Path, root: Path, *, label: str) -> None:
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PurgeError(f"{label} is outside its configured active root: {path}") from exc
    verify_directory_chain(root, label=f"{label} root")
    current = path.parent
    while True:
        reject_link(current, label)
        if current == root:
            break
        if root not in current.parents:
            raise PurgeError(f"{label} escaped its configured active root: {path}")
        current = current.parent
    reject_link(path, label)
    if not path.is_file():
        raise PurgeError(f"{label} is not a regular file: {path}")


def _file_identity(path: Path, data_root: Path, active_root: Path, *, layer: str) -> dict[str, Any]:
    _assert_safe_file(path, active_root, label=f"{layer} market-bars snapshot")
    stat = path.stat()
    return {
        "layer": layer.upper(),
        "relative_path": path.relative_to(data_root).as_posix(),
        "byte_size": stat.st_size,
        "sha256": _sha256_file(path),
    }


def _values(mapping: dict[str, list[Any]], name: str, transform=str) -> tuple[str, ...]:
    result = set()
    for value in mapping[name]:
        if value is None:
            result.add("")
        elif hasattr(value, "isoformat"):
            result.add(value.isoformat())
        else:
            result.add(transform(value))
    return tuple(sorted(result))


def _read_facts(path: Path, *, curated: bool) -> _Facts:
    required = {
        "code",
        "requested_trade_date",
        "interval",
        "requested_session",
        "adjustment",
        "ingestion_run_id",
    }
    if curated:
        required.update({"source", "source_schema_version"})
    try:
        parquet = pq.ParquetFile(path)
        columns = set(parquet.schema_arrow.names)
        missing = sorted(required - columns)
        if missing:
            raise PurgeError(f"snapshot {path} is missing required columns: {missing}")
        mapping = parquet.read(columns=sorted(required)).to_pydict()
    except PurgeError:
        raise
    except Exception as exc:
        raise PurgeError(f"failed to inspect snapshot {path}: {exc}") from exc
    return _Facts(
        row_count=parquet.metadata.num_rows,
        symbols=_values(mapping, "code", lambda value: str(value).strip().upper()),
        dates=_values(mapping, "requested_trade_date"),
        intervals=_values(mapping, "interval", lambda value: str(value).strip().lower()),
        sessions=_values(mapping, "requested_session", lambda value: str(value).strip().upper()),
        adjustments=_values(mapping, "adjustment", lambda value: str(value).strip().upper()),
        run_ids=_values(mapping, "ingestion_run_id", lambda value: str(value).strip()),
        sources=(
            _values(mapping, "source", lambda value: str(value).strip()) if curated else ()
        ),
        schema_versions=(
            _values(mapping, "source_schema_version", lambda value: str(value).strip())
            if curated
            else ()
        ),
    )


def _facts_intersect_scope(facts: _Facts, scope: PurgeScope, *, curated: bool) -> bool:
    if not set(facts.symbols).intersection(scope.symbols):
        return False
    if not any(scope.start_date.isoformat() <= value <= scope.end_date.isoformat() for value in facts.dates):
        return False
    if scope.interval not in facts.intervals or scope.requested_session not in facts.sessions:
        return False
    if scope.adjustment not in facts.adjustments:
        return False
    if curated and (
        scope.source not in facts.sources
        or scope.source_schema_version not in facts.schema_versions
    ):
        return False
    return True


def _scope_refusals(
    raw: _Facts, curated: _Facts, scope: PurgeScope, run_id: str
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    symbols = set(raw.symbols) | set(curated.symbols)
    extra_symbols = sorted(symbols - set(scope.symbols))
    if extra_symbols:
        reasons.append(
            {
                "code": "COLOCATED_SYMBOLS",
                "run_id": run_id,
                "message": "physical snapshot contains unselected symbols",
                "symbols": extra_symbols,
            }
        )
    dates = set(raw.dates) | set(curated.dates)
    expected_dates = {
        value
        for value in dates
        if scope.start_date.isoformat() <= value <= scope.end_date.isoformat()
    }
    outside_dates = sorted(dates - expected_dates)
    key_mismatch = (
        set(raw.intervals) != {scope.interval}
        or set(curated.intervals) != {scope.interval}
        or set(raw.sessions) != {scope.requested_session}
        or set(curated.sessions) != {scope.requested_session}
        or set(raw.adjustments) != {scope.adjustment}
        or set(curated.adjustments) != {scope.adjustment}
        or set(curated.sources) != {scope.source}
        or set(curated.schema_versions) != {scope.source_schema_version}
        or set(raw.run_ids) != {run_id}
        or set(curated.run_ids) != {run_id}
    )
    if outside_dates or key_mismatch:
        reasons.append(
            {
                "code": "COLOCATED_DATA",
                "run_id": run_id,
                "message": "physical snapshot contains dates or request-key data outside the purge scope",
                "outside_dates": outside_dates,
            }
        )
    if (
        raw.row_count != curated.row_count
        or raw.symbols != curated.symbols
        or raw.dates != curated.dates
    ):
        reasons.append(
            {
                "code": "RAW_CURATED_SCOPE_MISMATCH",
                "run_id": run_id,
                "message": "Raw and Curated files do not describe the same physical batch scope",
            }
        )
    return reasons


def _active_root(settings: Settings, scope: PurgeScope, layer: str) -> Path:
    return (
        settings.data_root
        / layer
        / f"source={scope.source}"
        / "dataset=market_bars"
    )


def _catalog_runs(catalog: Catalog, scope: PurgeScope) -> tuple[list[tuple], list[str]]:
    catalog.initialize()
    with catalog.connect() as con:
        rows = con.execute(
            """
            SELECT run_id, requested_trade_date, requested_symbols::VARCHAR,
                   interval, session, adjustment, raw_file, curated_file, status
            FROM ingestion_runs
            WHERE requested_trade_date >= ? AND requested_trade_date <= ?
              AND lower(interval) = ? AND upper(session) = ? AND upper(adjustment) = ?
            ORDER BY requested_trade_date, run_id
            """,
            [
                scope.start_date,
                scope.end_date,
                scope.interval,
                scope.requested_session,
                scope.adjustment,
            ],
        ).fetchall()
    selected: list[tuple] = []
    active: list[str] = []
    for row in rows:
        try:
            requested = {_symbol(value) for value in json.loads(row[2])}
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PurgeError(f"run {row[0]} has invalid requested_symbols metadata") from exc
        if not requested.intersection(scope.symbols):
            continue
        if str(row[8]).upper() == "RUNNING":
            active.append(str(row[0]))
        selected.append(row)
    return selected, active


def _metadata_relative_path(settings: Settings, value: str, *, label: str) -> str:
    path = _path_from_metadata(settings, value)
    root = Path(os.path.abspath(settings.data_root))
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise PurgeError(f"{label} metadata path is outside data_root: {path}") from exc


def _run_binding(settings: Settings, row: tuple) -> dict[str, Any]:
    try:
        symbols = sorted({_symbol(value) for value in json.loads(row[2])})
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PurgeError(f"run {row[0]} has invalid requested_symbols metadata") from exc
    if not row[6] or not row[7]:
        raise PurgeError(f"run {row[0]} does not have a complete physical file pair")
    trade_date = row[1]
    if not hasattr(trade_date, "isoformat"):
        raise PurgeError(f"run {row[0]} has invalid requested_trade_date metadata")
    return {
        "run_id": str(row[0]),
        "requested_trade_date": trade_date.isoformat(),
        "requested_symbols": symbols,
        "interval": str(row[3]).strip().lower(),
        "requested_session": str(row[4]).strip().upper(),
        "adjustment": str(row[5]).strip().upper(),
        "raw_relative_path": _metadata_relative_path(
            settings, str(row[6]), label=f"run {row[0]} Raw"
        ),
        "curated_relative_path": _metadata_relative_path(
            settings, str(row[7]), label=f"run {row[0]} Curated"
        ),
        "status": str(row[8]).strip().upper(),
    }


def _resolve_run(catalog: Catalog, run_id: str) -> tuple | None:
    catalog.initialize()
    with catalog.connect() as con:
        return con.execute(
            """
            SELECT run_id, requested_trade_date, requested_symbols::VARCHAR,
                   interval, session, adjustment, raw_file, curated_file, status
            FROM ingestion_runs
            WHERE run_id = ?
            """,
            [run_id],
        ).fetchone()


def _verify_run_bindings(settings: Settings, catalog: Catalog, plan: PurgePlan) -> None:
    """Rebind every sealed physical pair to its current ingestion run row."""
    for target in plan.targets:
        sealed = target.get("run_binding")
        if not isinstance(sealed, dict):
            raise PurgeDriftError(
                f"sealed target lacks an ingestion run binding: {target.get('ingestion_run_id')}"
            )
        run_id = str(target["ingestion_run_id"])
        current_row = _resolve_run(catalog, run_id)
        if current_row is None:
            raise PurgeDriftError(f"planned ingestion run disappeared: {run_id}")
        try:
            current = _run_binding(settings, current_row)
        except PurgeError as exc:
            raise PurgeDriftError(str(exc)) from exc
        if current != sealed:
            raise PurgeDriftError(f"planned ingestion run metadata drifted: {run_id}")
        if (
            sealed["raw_relative_path"] != target["raw"]["relative_path"]
            or sealed["curated_relative_path"] != target["curated"]["relative_path"]
            or sealed["run_id"] != run_id
        ):
            raise PurgeDriftError(f"sealed target binding is inconsistent: {run_id}")


def _partition_files(settings: Settings, scope: PurgeScope, layer: str) -> list[Path]:
    root = _active_root(settings, scope, layer)
    if not root.exists():
        return []
    files: list[Path] = []
    current = scope.start_date
    while current <= scope.end_date:
        directory = root / f"interval={scope.interval}" / f"requested_trade_date={current.isoformat()}"
        if directory.exists():
            verify_directory_chain(directory, label=f"{layer} market-bars partition")
            for entry in sorted(directory.iterdir(), key=lambda value: value.name):
                reject_link(entry, f"{layer} market-bars partition entry")
                if entry.is_file() and entry.suffix.lower() == ".parquet":
                    files.append(entry)
        current = date.fromordinal(current.toordinal() + 1)
    return files


def _refusal(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _dedupe_reasons(reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[bytes, dict[str, Any]] = {}
    for reason in reasons:
        unique[_canonical_bytes(reason)] = reason
    return [unique[key] for key in sorted(unique)]


def _build_plan_content(settings: Settings, scope: PurgeScope) -> dict[str, Any]:
    if scope.source != settings.source:
        raise ValueError(
            f"source must equal configured collector source {settings.source!r}"
        )
    catalog = Catalog(settings)
    rows, active_runs = _catalog_runs(catalog, scope)
    refusals: list[dict[str, Any]] = []
    if active_runs:
        refusals.append(
            _refusal(
                "ACTIVE_RUN",
                "matching market-bar ingestion runs are still RUNNING",
                run_ids=active_runs,
            )
        )
    targets: list[dict[str, Any]] = []
    referenced: set[str] = set()
    matched_symbols: set[str] = set()
    data_root = Path(os.path.abspath(settings.data_root))
    for row in rows:
        run_id, _, _, _, _, _, raw_text, curated_text, status = row
        if not raw_text and not curated_text and str(status).upper() == "FAILED":
            # Failed requests with no physical output remain historical run
            # evidence, but they do not form a purge lifecycle unit.
            continue
        if not raw_text or not curated_text:
            refusals.append(
                _refusal(
                    "RAW_CURATED_MISMATCH",
                    "matching run does not record a complete Raw/Curated file pair",
                    run_id=run_id,
                )
            )
            continue
        raw_path = _path_from_metadata(settings, raw_text)
        curated_path = _path_from_metadata(settings, curated_text)
        try:
            raw_identity = _file_identity(
                raw_path,
                data_root,
                _active_root(settings, scope, "raw"),
                layer="raw",
            )
            curated_identity = _file_identity(
                curated_path,
                data_root,
                _active_root(settings, scope, "curated"),
                layer="curated",
            )
            raw_facts = _read_facts(raw_path, curated=False)
            curated_facts = _read_facts(curated_path, curated=True)
            run_binding = _run_binding(settings, row)
        except (PurgeError, LifecycleLockError) as exc:
            refusals.append(
                _refusal("UNSAFE_OR_MISSING_TARGET", str(exc), run_id=str(run_id))
            )
            continue
        referenced.update({raw_identity["relative_path"], curated_identity["relative_path"]})
        if not _facts_intersect_scope(curated_facts, scope, curated=True):
            continue
        pair_refusals = _scope_refusals(raw_facts, curated_facts, scope, str(run_id))
        refusals.extend(pair_refusals)
        matched_symbols.update(set(curated_facts.symbols).intersection(scope.symbols))
        targets.append(
            {
                "ingestion_run_id": str(run_id),
                "run_binding": run_binding,
                "raw": {**raw_identity, "facts": raw_facts.as_dict()},
                "curated": {**curated_identity, "facts": curated_facts.as_dict()},
                "affected_row_count": curated_facts.row_count,
                "physical_scope_status": "REFUSED" if pair_refusals else "EXACT",
            }
        )

    for layer, curated in (("raw", False), ("curated", True)):
        try:
            partition_files = _partition_files(settings, scope, layer)
        except LifecycleLockError as exc:
            refusals.append(
                _refusal(
                    "UNSAFE_OR_MISSING_TARGET",
                    str(exc),
                    layer=layer.upper(),
                )
            )
            continue
        for path in partition_files:
            relative = path.relative_to(data_root).as_posix()
            if relative in referenced:
                continue
            try:
                facts = _read_facts(path, curated=curated)
            except PurgeError as exc:
                refusals.append(_refusal("UNVERIFIABLE_SNAPSHOT", str(exc), layer=layer.upper()))
                continue
            if _facts_intersect_scope(facts, scope, curated=curated):
                refusals.append(
                    _refusal(
                        "UNREGISTERED_SNAPSHOT",
                        "matching active snapshot is not paired through ingestion metadata",
                        layer=layer.upper(),
                        relative_path=relative,
                    )
                )

    missing_symbols = sorted(set(scope.symbols) - matched_symbols)
    if missing_symbols:
        refusals.append(
            _refusal(
                "NO_MATCHING_SYMBOL_DATA",
                "no complete physical snapshot pair matched one or more requested symbols",
                symbols=missing_symbols,
            )
        )
    if not targets and not refusals:
        refusals.append(_refusal("NO_MATCHING_DATA", "no matching market-bar data was found"))

    targets.sort(key=lambda item: (item["curated"]["relative_path"], item["ingestion_run_id"]))
    refusals = _dedupe_reasons(refusals)
    raw_bytes = sum(item["raw"]["byte_size"] for item in targets)
    curated_bytes = sum(item["curated"]["byte_size"] for item in targets)
    return {
        "plan_version": PURGE_PLAN_VERSION,
        "status": "REFUSED" if refusals else "PLANNED",
        "scope": scope.as_dict(),
        "targets": targets,
        "summary": {
            "affected_snapshot_count": len(targets),
            "affected_row_count": sum(item["affected_row_count"] for item in targets),
            "raw_file_count": len(targets),
            "raw_bytes": raw_bytes,
            "curated_file_count": len(targets),
            "curated_bytes": curated_bytes,
        },
        "dependency_state": {
            "policy": RETENTION_POLICY,
            "blocking": False,
            "official_derived_artifacts": [
                "VERIFIED_CANONICAL",
                "DATASET",
                "DATASET_CATALOG",
            ],
            "treatment": "RETAIN_NO_CASCADE",
            "external_consumers": "OUTSIDE_MARKETVAULT_LIFECYCLE_GUARANTEE",
        },
        "retained_evidence": [
            "ingestion_runs",
            "quality_results",
            "collection_manifests",
            "quality_reports",
            "purge_plan",
            "purge_result",
        ],
        "refusal_reasons": refusals,
        "quarantine_root_template": "quarantine/purge_id=<plan_id>",
    }


def _evidence_path(settings: Settings, kind: str, plan_id: str) -> Path:
    base = Path(os.path.abspath(settings.manifest_dir)) / "purge" / kind
    verify_directory_chain(base, label="purge evidence directory")
    if kind == "plans":
        return base / f"{plan_id}.json"
    return base / plan_id / f"result-{uuid4().hex}.json"


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    data = _canonical_bytes(payload)
    verify_directory_chain(path.parent, label="purge evidence directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    verify_directory_chain(path.parent, label="purge evidence directory")
    reject_link(path, "purge evidence file")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise PurgeError(f"immutable purge evidence already exists with different bytes: {path}")


def _plan_from_payload(payload: dict[str, Any], plan_file: Path) -> PurgePlan:
    return PurgePlan(
        plan_id=payload["plan_id"],
        content_hash=payload["content_hash"],
        status=payload["status"],
        scope=PurgeScope.from_dict(payload["scope"]),
        targets=tuple(payload["targets"]),
        summary=payload["summary"],
        dependency_state=payload["dependency_state"],
        retained_evidence=tuple(payload["retained_evidence"]),
        refusal_reasons=tuple(payload["refusal_reasons"]),
        quarantine_root=(
            f"quarantine/purge_id={payload['plan_id']}"
        ),
        plan_file=str(plan_file),
    )


def purge_plan(
    settings: Settings,
    *,
    source: str,
    symbols: list[str],
    start_date: date,
    end_date: date,
    interval: str,
    requested_session: str,
    adjustment: str,
    source_schema_version: str,
) -> PurgePlan:
    """Create an immutable local plan without mutating active market data."""
    scope = PurgeScope.create(
        source=source,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
        requested_session=requested_session,
        adjustment=adjustment,
        source_schema_version=source_schema_version,
    )
    with MarketBarLifecycleLock(settings.data_root, "purge_plan"):
        content = _build_plan_content(settings, scope)
        content_hash = hashlib.sha256(_canonical_bytes(content)).hexdigest()
        plan_id = content_hash[:32]
        plan_file = _evidence_path(settings, "plans", plan_id)
        payload = {**content, "plan_id": plan_id, "content_hash": content_hash}
        _write_immutable(plan_file, payload)
        plan = _plan_from_payload(payload, plan_file)
        Catalog(settings).record_purge_plan(
            plan_id=plan_id,
            plan_hash=content_hash,
            state=plan.status,
            scope_json=json.dumps(scope.as_dict(), sort_keys=True, separators=(",", ":")),
            plan_file=str(plan_file),
            planned_at=datetime.now(timezone.utc),
        )
        return plan


def _load_sealed_plan(settings: Settings, plan_id: str) -> PurgePlan:
    if not _PLAN_ID_RE.fullmatch(plan_id):
        raise PurgeError("plan_id must be exactly 32 lowercase hexadecimal characters")
    expected_path = _evidence_path(settings, "plans", plan_id)
    record = Catalog(settings).purge_operation(plan_id)
    if record is None:
        raise PurgeError(f"unknown purge plan id: {plan_id}")
    if Path(record["plan_file"]) != expected_path:
        raise PurgeError("purge plan index points outside the authoritative evidence path")
    reject_link(expected_path, "sealed purge plan")
    try:
        payload = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PurgeError(f"cannot read sealed purge plan {plan_id}") from exc
    if payload.get("plan_id") != plan_id or payload.get("plan_version") != PURGE_PLAN_VERSION:
        raise PurgeError("sealed purge plan identity or version is invalid")
    content = {key: value for key, value in payload.items() if key not in {"plan_id", "content_hash"}}
    digest = hashlib.sha256(_canonical_bytes(content)).hexdigest()
    if digest != payload.get("content_hash") or digest != record["plan_hash"]:
        raise PurgeError("sealed purge plan content hash mismatch")
    return _plan_from_payload(payload, expected_path)


def _identity_path(settings: Settings, identity: dict[str, Any]) -> Path:
    relative = Path(identity["relative_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise PurgeDriftError("sealed target has an unsafe relative path")
    return Path(os.path.abspath(settings.data_root / relative))


def _quarantine_path(settings: Settings, plan_id: str, identity: dict[str, Any]) -> Path:
    return Path(os.path.abspath(settings.data_root)) / "quarantine" / f"purge_id={plan_id}" / identity["relative_path"]


def _verify_identity(
    path: Path,
    identity: dict[str, Any],
    settings: Settings,
    *,
    quarantine: bool = False,
) -> None:
    layer = identity["layer"].lower()
    scope_source = Path(identity["relative_path"]).parts[1].split("=", 1)[1]
    root = (
        settings.data_root / "quarantine"
        if quarantine
        else settings.data_root / layer / f"source={scope_source}" / "dataset=market_bars"
    )
    _assert_safe_file(path, root, label=f"sealed {layer} target")
    if path.stat().st_size != identity["byte_size"] or _sha256_file(path) != identity["sha256"]:
        raise PurgeDriftError(f"sealed target identity changed: {identity['relative_path']}")


def _move_file(source: Path, destination: Path) -> None:
    if os.name == "nt":
        # MoveFileEx without replacement is the behavior of os.rename on
        # Windows. A concurrently created destination therefore fails.
        os.rename(source, destination)
        return
    # POSIX rename may replace an existing destination. A hard-link plus
    # unlink preserves same-filesystem bytes and provides no-replace
    # publication through O_EXCL-like link semantics.
    os.link(source, destination)
    os.unlink(source)


_RESULT_KEYS = {
    "result_version",
    "plan_id",
    "content_hash",
    "evidence_hash",
    "status",
    "moved_files",
    "result_file",
    "completed_at",
    "message",
}


def _build_result(
    plan: PurgePlan,
    *,
    status: str,
    moved_files: list[dict[str, Any]],
    message: str,
    result_path: Path,
) -> PurgeResult:
    content = {
        "result_version": PURGE_RESULT_VERSION,
        "plan_id": plan.plan_id,
        "content_hash": plan.content_hash,
        "status": status,
        "moved_files": moved_files,
        "result_file": str(result_path),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "message": message,
    }
    evidence_hash = hashlib.sha256(_canonical_bytes(content)).hexdigest()
    return PurgeResult(
        result_version=PURGE_RESULT_VERSION,
        plan_id=plan.plan_id,
        content_hash=plan.content_hash,
        evidence_hash=evidence_hash,
        status=status,
        moved_files=tuple(moved_files),
        result_file=str(result_path),
        completed_at=content["completed_at"],
        message=message,
    )


def _parse_result_payload(
    payload: dict[str, Any], *, expected_hash: str | None = None
) -> PurgeResult:
    if set(payload) != _RESULT_KEYS:
        raise PurgeError("purge result evidence has an unexpected canonical schema")
    content = {key: value for key, value in payload.items() if key != "evidence_hash"}
    digest = hashlib.sha256(_canonical_bytes(content)).hexdigest()
    if digest != payload.get("evidence_hash") or (
        expected_hash is not None and digest != expected_hash
    ):
        raise PurgeError("purge result evidence hash mismatch")
    try:
        return PurgeResult(
            result_version=payload["result_version"],
            plan_id=payload["plan_id"],
            content_hash=payload["content_hash"],
            evidence_hash=payload["evidence_hash"],
            status=payload["status"],
            moved_files=tuple(payload["moved_files"]),
            result_file=payload["result_file"],
            completed_at=payload["completed_at"],
            message=payload["message"],
        )
    except (KeyError, TypeError) as exc:
        raise PurgeError("purge result evidence cannot be parsed") from exc


def _write_result(
    settings: Settings,
    plan: PurgePlan,
    *,
    status: str,
    moved_files: list[dict[str, Any]],
    message: str,
) -> PurgeResult:
    result = _build_result(
        plan,
        status=status,
        moved_files=moved_files,
        message=message,
        result_path=_evidence_path(settings, "results", plan.plan_id),
    )
    _write_immutable(Path(result.result_file), result.as_dict())
    return result


def _prepare_success_result(
    settings: Settings,
    plan: PurgePlan,
    moved_files: list[dict[str, Any]],
) -> tuple[PurgeResult, Path]:
    attempt_id = uuid4().hex
    root = Path(os.path.abspath(settings.manifest_dir)) / "purge" / "results" / plan.plan_id
    result_path = root / f"result-{attempt_id}.json"
    precommit_path = root / f"precommit-{attempt_id}.json"
    result = _build_result(
        plan,
        status="SUCCESS",
        moved_files=moved_files,
        message=(
            "Selected physical Raw/Curated snapshot pairs moved to quarantine; "
            "no permanent deletion occurred."
        ),
        result_path=result_path,
    )
    content = {
        "precommit_version": PURGE_PRECOMMIT_VERSION,
        "plan_id": plan.plan_id,
        "plan_hash": plan.content_hash,
        "terminal_result": result.as_dict(),
        "terminal_result_hash": result.evidence_hash,
    }
    payload = {
        **content,
        "precommit_hash": hashlib.sha256(_canonical_bytes(content)).hexdigest(),
    }
    _write_immutable(precommit_path, payload)
    return result, precommit_path


def _load_precommit(
    settings: Settings, plan: PurgePlan, record: dict[str, Any]
) -> PurgeResult:
    if not record.get("precommit_file") or not record.get("result_hash"):
        raise PurgeError("completed purge index is missing precommit integrity evidence")
    path = Path(os.path.abspath(record["precommit_file"]))
    root = Path(os.path.abspath(settings.manifest_dir)) / "purge" / "results" / plan.plan_id
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PurgeError("purge precommit index points outside its evidence path") from exc
    verify_directory_chain(root, label="purge result directory")
    reject_link(path, "purge precommit evidence")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PurgeError("purge precommit evidence cannot be parsed") from exc
    if raw != _canonical_bytes(payload):
        raise PurgeError("purge precommit evidence is not canonical")
    expected_keys = {
        "precommit_version",
        "plan_id",
        "plan_hash",
        "terminal_result",
        "terminal_result_hash",
        "precommit_hash",
    }
    if set(payload) != expected_keys:
        raise PurgeError("purge precommit evidence has an unexpected schema")
    content = {key: value for key, value in payload.items() if key != "precommit_hash"}
    if hashlib.sha256(_canonical_bytes(content)).hexdigest() != payload["precommit_hash"]:
        raise PurgeError("purge precommit evidence hash mismatch")
    if (
        payload["precommit_version"] != PURGE_PRECOMMIT_VERSION
        or payload["plan_id"] != plan.plan_id
        or payload["plan_hash"] != plan.content_hash
        or payload["terminal_result_hash"] != record["result_hash"]
    ):
        raise PurgeError("purge precommit evidence is inconsistent")
    result = _parse_result_payload(
        payload["terminal_result"], expected_hash=record["result_hash"]
    )
    if result.result_file != record.get("result_file"):
        raise PurgeError("purge precommit result path is inconsistent")
    return result


def _result_from_file(path: Path, *, expected_hash: str) -> PurgeResult:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if raw != _canonical_bytes(payload):
        raise PurgeError("purge result evidence is not canonical")
    return _parse_result_payload(payload, expected_hash=expected_hash)


def _load_success_result(
    settings: Settings, plan: PurgePlan, record: dict[str, Any]
) -> PurgeResult:
    prepared = _load_precommit(settings, plan, record)
    path = Path(os.path.abspath(record["result_file"]))
    root = Path(os.path.abspath(settings.manifest_dir)) / "purge" / "results" / plan.plan_id
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PurgeError("purge result index points outside the authoritative evidence path") from exc
    verify_directory_chain(root, label="purge result directory")
    reject_link(path, "purge result evidence")
    if not path.exists():
        # Catalog SUCCESS is the commit point. A crash after that transaction
        # is recovered by publishing the exact integrity-bound payload sealed
        # in the immutable precommit evidence.
        _write_immutable(path, prepared.as_dict())
    if not path.is_file():
        raise PurgeError("completed purge result evidence is not a regular file")
    try:
        result = _result_from_file(path, expected_hash=record["result_hash"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise PurgeError("completed purge result evidence cannot be parsed") from exc
    expected_moved = tuple(
        {
            **target[key],
            "quarantine_relative_path": _quarantine_path(
                settings, plan.plan_id, target[key]
            ).relative_to(settings.data_root).as_posix(),
        }
        for target in plan.targets
        for key in ("raw", "curated")
    )
    if (
        result.result_version != PURGE_RESULT_VERSION
        or result.plan_id != plan.plan_id
        or result.content_hash != plan.content_hash
        or result.status != "SUCCESS"
        or Path(result.result_file) != path
        or result.moved_files != expected_moved
        or result.as_dict() != prepared.as_dict()
    ):
        raise PurgeError("completed purge result evidence is inconsistent")
    return result


def purge_execute(settings: Settings, *, plan_id: str, confirmation: str) -> PurgeResult:
    """Execute an exact sealed plan by moving whole file pairs to quarantine."""
    plan = _load_sealed_plan(settings, plan_id)
    if confirmation != f"PURGE {plan_id}":
        raise PurgeError(f"confirmation must be exactly: PURGE {plan_id}")
    if not plan.executable:
        codes = ", ".join(reason["code"] for reason in plan.refusal_reasons)
        raise PurgeRefusedError(f"purge plan is REFUSED: {codes}")
    catalog = Catalog(settings)
    moved_this_attempt: list[tuple[Path, Path, dict[str, Any]]] = []
    moved_evidence: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc)
    with MarketBarLifecycleLock(settings.data_root, f"purge_execute:{plan_id}"):
        record = catalog.purge_operation(plan_id)
        if record is None:
            raise PurgeError(f"unknown purge plan id: {plan_id}")
        _verify_run_bindings(settings, catalog, plan)
        if record["state"] == "SUCCESS":
            for target in plan.targets:
                for key in ("raw", "curated"):
                    destination = _quarantine_path(settings, plan_id, target[key])
                    _verify_identity(destination, target[key], settings, quarantine=True)
            return _load_success_result(settings, plan, record)

        catalog.begin_purge_operation(plan_id, started_at=started_at)
        committed = False
        try:
            # This second binding check occurs after the attempt transition;
            # both checks are under the same cross-process mutation lock.
            _verify_run_bindings(settings, catalog, plan)
            _, active_runs = _catalog_runs(catalog, plan.scope)
            if active_runs:
                raise PurgeDriftError(f"matching RUNNING ingestion runs appeared: {active_runs}")
            expected_active = {
                target[key]["relative_path"]
                for target in plan.targets
                for key in ("raw", "curated")
            }
            for layer, curated in (("raw", False), ("curated", True)):
                for path in _partition_files(settings, plan.scope, layer):
                    facts = _read_facts(path, curated=curated)
                    relative = path.relative_to(settings.data_root).as_posix()
                    if _facts_intersect_scope(facts, plan.scope, curated=curated) and relative not in expected_active:
                        raise PurgeDriftError(f"unplanned matching snapshot appeared: {relative}")

            for target in plan.targets:
                for key in ("raw", "curated"):
                    identity = target[key]
                    source = _identity_path(settings, identity)
                    destination = _quarantine_path(settings, plan_id, identity)
                    if source.exists() and destination.exists():
                        raise PurgeDriftError(
                            f"target exists in both active archive and quarantine: {identity['relative_path']}"
                        )
                    if destination.exists():
                        _verify_identity(destination, identity, settings, quarantine=True)
                        moved_evidence.append(
                            {**identity, "quarantine_relative_path": destination.relative_to(settings.data_root).as_posix()}
                        )
                        continue
                    if not source.exists():
                        raise PurgeDriftError(f"sealed target is missing: {identity['relative_path']}")
                    _verify_identity(source, identity, settings)
                    verify_directory_chain(destination.parent, label="quarantine destination")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    verify_directory_chain(destination.parent, label="quarantine destination")
                    if source.stat().st_dev != destination.parent.stat().st_dev:
                        raise PurgeError("quarantine destination is not on the same filesystem")
                    moved_this_attempt.append((source, destination, identity))
                    _move_file(source, destination)
                    moved_evidence.append(
                        {**identity, "quarantine_relative_path": destination.relative_to(settings.data_root).as_posix()}
                    )

            catalog.refresh_market_bars_view()
            result, precommit_path = _prepare_success_result(
                settings, plan, moved_evidence
            )
            # The Catalog transaction is the commit point. No terminal
            # SUCCESS evidence exists before this call succeeds.
            catalog.commit_purge_operation(
                plan_id,
                plan_hash=plan.content_hash,
                precommit_file=str(precommit_path),
                result_file=result.result_file,
                result_hash=result.evidence_hash,
                finished_at=datetime.now(timezone.utc),
            )
            committed = True
            # Publication is recoverable: a retry can reproduce these exact
            # bytes from the immutable precommit after validating quarantine.
            _write_immutable(Path(result.result_file), result.as_dict())
            return result
        except BaseException as exc:
            if committed:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise PurgeError(
                    "purge committed but terminal result publication requires "
                    f"an idempotent retry: {exc}"
                ) from exc
            rollback_errors: list[str] = []
            for source, destination, identity in reversed(moved_this_attempt):
                try:
                    if destination.exists() and not source.exists():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        _move_file(destination, source)
                    elif destination.exists() and source.exists():
                        # POSIX no-replace movement uses link+unlink. If the
                        # unlink half failed, both names reference the sealed
                        # bytes; remove only the transient quarantine link.
                        if (
                            destination.stat().st_size != identity["byte_size"]
                            or _sha256_file(destination) != identity["sha256"]
                            or _sha256_file(source) != identity["sha256"]
                        ):
                            raise OSError("cannot safely roll back duplicated target names")
                        destination.unlink()
                except OSError as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            try:
                catalog.refresh_market_bars_view()
            except Exception as refresh_exc:
                rollback_errors.append(f"view refresh failed: {refresh_exc}")
            error = str(exc)
            if rollback_errors:
                error += f"; rollback incomplete: {rollback_errors}"
            try:
                failure = _write_result(
                    settings,
                    plan,
                    status="FAILED",
                    moved_files=moved_evidence,
                    message=error,
                )
                catalog.fail_purge_operation(
                    plan_id,
                    result_file=failure.result_file,
                    result_hash=failure.evidence_hash,
                    finished_at=datetime.now(timezone.utc),
                    error=error,
                )
            except Exception:
                # The original failure remains authoritative; an EXECUTING
                # index is intentionally not converted to SUCCESS.
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise PurgeError(error) from exc
