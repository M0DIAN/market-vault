"""Verified intraday observations, full session prices and independent targets.

Only this additive research format uses these sampling/target semantics. Feature
formulas and PIT selection are delegated to the existing TS2 authorities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
import os
from pathlib import Path

from ..canonical.reader import load_verified_canonical_build
from ..cross_day._authority import admit_builds, reconcile
from ..cross_day.schedule import admit_schedule
from ..dataset.encoding import normalize_utc_datetime
from ..dataset.pit import assemble_point_in_time_samples
from ..dataset.pit_models import PITSampleRequest, PIT_ASSEMBLER_VERSION
from ..ts2_feature import execute_ts2_features
from ..ts2_feature.registry import TS2_FEATURE_EXECUTION_CONTRACT_VERSION


INTRADAY_DATA_VERSION = "market-vault-intraday-data-v1"
INTRADAY_PLAN_VERSION = "market-vault-intraday-data-plan-v1"
INTRADAY_SAMPLING_VERSION = "market-vault-intraday-sampling-v1"
INTRADAY_TARGET_VERSION = "market-vault-intraday-open-to-close-target-v1"
INTRADAY_INTERVALS = ("1m", "5m", "15m", "30m")
_PLAN_FIELDS = {"plan_schema_version", "canonical_build_dirs", "schedule", "symbol",
                "interval", "preset", "stride_bars", "target_horizon_bars", "dataset_as_of"}
_ROOT_FIELDS = {"artifact_schema_version", "data_id", "plan", "source_build_ids",
                "algorithm_versions", "report"}


class IntradayDataError(ValueError):
    """An invalid explicit input or a failed research data verification."""


def json_values(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [json_values(item) for item in value]
    if isinstance(value, dict):
        return {key: json_values(item) for key, item in value.items()}
    return value


def canonical_json(value) -> bytes:
    return (json.dumps(json_values(value), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(value) -> str:
    return sha256(canonical_json(value)).hexdigest()


def object_fields(value, fields, name):
    if type(value) is not dict or set(value) != set(fields):
        raise IntradayDataError(f"{name} must contain exactly: {', '.join(sorted(fields))}")
    return value


def positive_int(value, name):
    if type(value) is not int or not 1 <= value <= 2**31 - 1:
        raise IntradayDataError(f"{name} must be a positive integer")
    return value


def finite_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise IntradayDataError(f"{name} must be finite numeric data")
    return float(value)


def parse_json(payload: bytes):
    from ..dataset.cli import _no_duplicate_pairs
    if type(payload) is not bytes or payload.startswith(b"\xef\xbb\xbf"):
        raise IntradayDataError("JSON must be UTF-8 bytes without a BOM")
    def constant(value):
        raise IntradayDataError(f"nonfinite JSON value: {value}")
    return json.loads(payload.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs,
                      parse_constant=constant)


def parse_intraday_plan(value, *, base: Path | None = None) -> dict:
    """Validate before source I/O; all defaults belong to the explicit UI plan."""
    from ..dataset.cli import _resolve_plan_path
    from ..research_cli import ResearchCLIError, _parse_schedule
    from ..research_workspace import _symbol, _feature_preset
    object_fields(value, _PLAN_FIELDS, "intraday data plan")
    if value["plan_schema_version"] != INTRADAY_PLAN_VERSION:
        raise IntradayDataError("unsupported intraday data plan version")
    symbol = _symbol(value["symbol"])
    if value["interval"] not in INTRADAY_INTERVALS:
        raise IntradayDataError("intraday interval must be 1m, 5m, 15m or 30m")
    if type(value["preset"]) is not str or value["preset"] not in ("LIGHT_TECHNICAL", "CORE_TECHNICAL"):
        raise IntradayDataError("unsupported intraday Feature preset")
    _feature_preset(value["preset"])
    positive_int(value["stride_bars"], "stride_bars")
    horizon = value["target_horizon_bars"]
    if horizon is not None:
        positive_int(horizon, "target_horizon_bars")
    cutoff = value["dataset_as_of"]
    if cutoff is not None:
        if type(cutoff) is not str:
            raise IntradayDataError("dataset_as_of must be an aware ISO timestamp or null")
        cutoff = normalize_utc_datetime(datetime.fromisoformat(cutoff), "dataset_as_of")
    try:
        schedule = _parse_schedule(value["schedule"], dataset_as_of=cutoff)
    except ResearchCLIError as exc:
        raise IntradayDataError(str(exc)) from exc
    paths = value["canonical_build_dirs"]
    if type(paths) is not list or not paths:
        raise IntradayDataError("canonical_build_dirs must be a nonempty array")
    if any(type(path) is not str or not path.strip() for path in paths):
        raise IntradayDataError("Canonical build paths must be nonempty strings")
    base = (Path.cwd() if base is None else
            _resolve_plan_path(str(base), base=Path.cwd(), label="intraday plan base"))
    resolved = [str(_resolve_plan_path(path, base=base, label="Canonical build")) for path in paths]
    if len(set(resolved)) != len(resolved):
        raise IntradayDataError("duplicate Canonical build directories")
    return {**value, "symbol": symbol, "canonical_build_dirs": sorted(resolved),
            "schedule": json_values(asdict(schedule)),
            "dataset_as_of": None if cutoff is None else cutoff.isoformat()}


def algorithm_versions():
    return {"sampling": INTRADAY_SAMPLING_VERSION, "target": INTRADAY_TARGET_VERSION,
            "pit": PIT_ASSEMBLER_VERSION, "ts2_features": TS2_FEATURE_EXECUTION_CONTRACT_VERSION}


def _data_identity(root):
    plan = dict(root["plan"])
    del plan["canonical_build_dirs"]  # Locators are not economic data identity.
    return digest({**root, "plan": plan, "data_id": None})


@dataclass(frozen=True, slots=True)
class IntradayDataset:
    """Immutable snapshot; execution consumers must call verify_intraday_dataset."""

    content: bytes
    path: Path | None = None

    def __post_init__(self):
        root = parse_json(self.content)
        object_fields(root, _ROOT_FIELDS, "intraday data artifact")
        if root["artifact_schema_version"] != INTRADAY_DATA_VERSION:
            raise IntradayDataError("unsupported intraday data version")
        if root["data_id"] != _data_identity(root):
            raise IntradayDataError("intraday data content identity mismatch")
        if self.content != canonical_json(root):
            raise IntradayDataError("intraday artifact must use its canonical encoding")

    def as_dict(self):
        return parse_json(self.content)

    @property
    def data_id(self):
        return self.as_dict()["data_id"]


def build_intraday_dataset(plan: dict, *, base: Path | None = None) -> IntradayDataset:
    """Re-read exact Canonical artifacts and derive all three independent views."""
    from ..research_cli import _parse_schedule
    from ..research_workspace import _feature_preset
    plan = parse_intraday_plan(plan, base=base)
    cutoff = None if plan["dataset_as_of"] is None else datetime.fromisoformat(plan["dataset_as_of"])
    schedule = admit_schedule(_parse_schedule(plan["schedule"], dataset_as_of=cutoff), cutoff)
    builds = admit_builds(tuple(load_verified_canonical_build(path) for path in plan["canonical_build_dirs"]))
    ids = tuple(build.canonical_build_id for build in builds)
    if len(set(ids)) != len(ids):
        raise IntradayDataError("duplicate Canonical build identities")
    interval = plan["interval"]
    symbol = plan["symbol"]
    days = {day.market_calendar_date: day for day in schedule.daily_records}
    for build in builds:
        req = build.normalized_request
        if req.symbols != (symbol,) or req.interval != interval:
            raise IntradayDataError("Canonical build differs from the single-symbol interval scope")
    rows = reconcile(builds)
    delta = timedelta(minutes=int(interval[:-1]))
    price_by_slot = {}
    for source in rows.values():
        bar = source.bar
        day = days.get(bar.market_calendar_date)
        if day is None:
            continue
        if day.day_status != "TRADING":
            raise IntradayDataError("Canonical row falls on a declared closed day")
        event = normalize_utc_datetime(bar.event_time, "bar event")
        available = normalize_utc_datetime(bar.market_available_at, "bar availability")
        if (event < day.session_open or event + delta > day.session_close
                or (event - day.session_open) % delta != timedelta(0)
                or available != event + delta):
            raise IntradayDataError("Canonical bar differs from the admitted session grid/availability")
        if cutoff is not None and bar.archive_available_at > cutoff:
            continue
        slot = (event - day.session_open) // delta
        key = (day.market_calendar_date, slot)
        if key in price_by_slot:
            raise IntradayDataError("multiple Canonical versions in one session slot")
        prices = {name: finite_number(getattr(bar, name), name)
                  for name in ("open", "high", "low", "close", "volume")}
        if min(prices[name] for name in ("open", "high", "low", "close")) <= 0 or prices["volume"] < 0:
            raise IntradayDataError("prices must be positive and volume nonnegative")
        price_by_slot[key] = {"trading_day": day.market_calendar_date.isoformat(), "slot": slot,
                              "event_time": event.isoformat(), "available_at": available.isoformat(),
                              "row_version_id": bar.canonical_row_version_id, **prices}

    specs, window = _feature_preset(plan["preset"])
    requests, gaps, sessions = [], [], []
    for day in schedule.daily_records:
        if day.day_status != "TRADING":
            continue
        count = (day.session_close - day.session_open) // delta
        missing = [slot for slot in range(count) if (day.market_calendar_date, slot) not in price_by_slot]
        gaps.extend({"trading_day": day.market_calendar_date.isoformat(), "slot": slot,
                     "event_time": (day.session_open + slot * delta).isoformat()} for slot in missing)
        slots = range(window - 1, count, plan["stride_bars"])
        sessions.append({"trading_day": day.market_calendar_date.isoformat(),
                         "open_time": day.session_open.isoformat(), "close_time": day.session_close.isoformat(),
                         "profile": day.session_profile, "bar_count": count, "missing_bar_count": len(missing),
                         "warmup_bar_count": min(window - 1, count), "observation_count": len(slots)})
        for slot in slots:
            close = day.session_open + (slot + 1) * delta
            requests.append(PITSampleRequest(symbol, interval, "NONE", "RTH", day.market_calendar_date,
                                            close - window * delta, close))
    if not sessions:
        raise IntradayDataError("intraday range contains no trading sessions")
    pit = assemble_point_in_time_samples(builds, tuple(requests), dataset_as_of=cutoff)
    features = execute_ts2_features(builds, pit, specs, dataset_as_of=cutoff)
    sample_by_key = {sample.sample_key: sample for sample in pit.samples}
    observations, targets = [], []
    horizon = plan["target_horizon_bars"]
    for sample in features.samples:
        request = sample_by_key[sample.sample_key].request
        day = days[request.anchor_market_calendar_date]
        slot = (request.feature_window_close - day.session_open) // delta - 1
        continuous = all((day.market_calendar_date, i) in price_by_slot for i in range(slot - window + 1, slot + 1))
        ready = continuous and sample.status == "COMPLETE"
        observations.append({"observation_key": sample.sample_key,
                             "trading_day": day.market_calendar_date.isoformat(), "slot": slot,
                             "decision_time": request.feature_window_close.isoformat(),
                             "window_start": request.feature_window_start.isoformat(),
                             "status": "READY" if ready else "UNAVAILABLE",
                             "reason": None if ready else "FEATURE_WINDOW_INCOMPLETE",
                             "features": {v.feature_name: v.value for v in sample.values},
                             "feature_value_ids": {v.feature_name: v.value_id for v in sample.values}})
        if horizon is None:
            continue
        remaining = (day.session_close - request.feature_window_close) // delta
        future = [price_by_slot.get((day.market_calendar_date, i)) for i in range(slot + 1, slot + min(horizon, remaining) + 1)]
        reason = ("SESSION_END" if horizon > remaining else
                  "MISSING_PRICE" if len(future) != horizon or any(row is None for row in future) else None)
        complete = reason is None
        entry, exit_ = (future[0], future[-1]) if complete else (None, None)
        targets.append({"observation_key": sample.sample_key,
                        "status": "COMPLETE" if complete else "INCOMPLETE", "reason": reason,
                        "actual_label_end_time": exit_["available_at"] if complete else None,
                        "entry_row_version_id": entry["row_version_id"] if complete else None,
                        "exit_row_version_id": exit_["row_version_id"] if complete else None,
                        "value": exit_["close"] / entry["open"] - 1.0 if complete else None})
    observations.sort(key=lambda row: (row["decision_time"], row["observation_key"]))
    target_by_key = {row["observation_key"]: row for row in targets}
    targets = [target_by_key[row["observation_key"]] for row in observations] if horizon is not None else []
    prices = [price_by_slot[key] for key in sorted(price_by_slot)]
    report = {"symbol": symbol, "interval": interval, "feature_names": [s.name for s in specs],
              "feature_window_bars": window, "feature_execution_id": features.execution_id,
              "sessions": sessions, "prices": prices, "gaps": gaps,
              "observations": observations, "targets": targets,
              "ready_observation_count": sum(row["status"] == "READY" for row in observations),
              "complete_target_count": sum(row["status"] == "COMPLETE" for row in targets)}
    root = {"artifact_schema_version": INTRADAY_DATA_VERSION, "data_id": None,
            "plan": plan, "source_build_ids": sorted(ids), "algorithm_versions": algorithm_versions(),
            "report": report}
    root["data_id"] = _data_identity(root)
    return IntradayDataset(canonical_json(root))


def verify_intraday_dataset(snapshot: IntradayDataset) -> IntradayDataset:
    """A snapshot hash is not source authority: reproduce every raw data field."""
    if type(snapshot) is not IntradayDataset:
        raise IntradayDataError("an IntradayDataset is required")
    checked = IntradayDataset(snapshot.content, snapshot.path)
    root = checked.as_dict()
    if root["algorithm_versions"] != algorithm_versions():
        raise IntradayDataError("intraday algorithm versions differ")
    actual = build_intraday_dataset(root["plan"])
    if actual.content != checked.content:
        raise IntradayDataError("intraday data differs from verified source reconstruction")
    return checked


def _path(value) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise IntradayDataError("an explicit file path is required")
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _read(path: Path):
    if path.is_symlink() or not path.is_file():
        raise IntradayDataError("intraday data path must be a regular file")
    return path.read_bytes()


def load_intraday_dataset(path: str | Path) -> IntradayDataset:
    path = _path(path)
    return verify_intraday_dataset(IntradayDataset(_read(path), path))


def write_intraday_dataset(snapshot: IntradayDataset, *, path: str | Path) -> Path:
    """Exclusive creation and identical reuse; never replace existing data."""
    if type(snapshot) is not IntradayDataset:
        raise IntradayDataError("an IntradayDataset is required")
    snapshot = IntradayDataset(snapshot.content, snapshot.path)
    path = _path(path)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise IntradayDataError("data parent must be an existing regular directory")
    if not path.exists() and not path.is_symlink():
        try:
            with path.open("xb") as handle:
                handle.write(snapshot.content)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass
    if _read(path) != snapshot.content:
        raise IntradayDataError("existing data differs; choose a new file path")
    IntradayDataset(_read(path))
    return path


def intraday_summary(snapshot: IntradayDataset) -> dict[str, str]:
    data = snapshot.as_dict()
    report = data["report"]
    return {"intraday_data_id": data["data_id"], "symbol": report["symbol"], "interval": report["interval"],
            "trading_dates": str(len(report["sessions"])), "intraday_prices": str(len(report["prices"])),
            "intraday_observations": str(len(report["observations"])),
            "intraday_ready": str(report["ready_observation_count"]),
            "intraday_complete_targets": str(report["complete_target_count"]),
            "intraday_incomplete_targets": str(len(report["targets"]) - report["complete_target_count"]),
            "intraday_missing_prices": str(len(report["gaps"]))}
