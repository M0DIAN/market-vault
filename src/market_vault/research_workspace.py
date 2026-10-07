"""Local production Research Dataset workspace orchestration.

This module bridges the existing collection/Catalog, Canonical, Cross-Day
Research Dataset, and desktop surfaces without inventing a second research
engine.  It is deliberately narrow:

* one US symbol;
* RTH / NONE only;
* the qualified Moomoo Timestamp Semantics V2 source cohort;
* one explicit local trading-calendar range;
* built-in TS2 Feature presets and execution-safe Cross-Day Labels;
* deterministic chronological 70/15/15 split boundaries.

Network access is not performed here.  Research-ready market-data collection
is exposed separately through the existing backfill service using a derived
Settings value whose source schema is pinned to Timestamp Semantics V2.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd

from .backfill import collect_history_backfill, missing_coverage_ranges, plan_history_backfill
from .canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from .canonical.schema import CANONICAL_SCHEMA_VERSION
from .cross_day import TradingDayRecord, verify_trading_day_schedule
from .cross_day.registry import CROSS_DAY_SOURCE_SCHEMA_VERSION
from .cross_day.schedule import (
    CALENDAR_CONTRACT_VERSION,
    SCHEDULE_NORMALIZATION_VERSION,
    TRADING_DAY_SCHEDULE_SCHEMA_VERSION,
)
from .cross_day_dataset import CrossDayAnchor
from .dataset.models import DatasetField, DatasetScope
from .dataset.spec_models import (
    CrossTradingDayPolicy,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    SpecParameter,
    SpecVersionRequirements,
)
from .dataset.split_models import (
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
    SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
    SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
    SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
    ChronologicalSplitSpec,
)
from .normalization import MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA
from .normalization.rth_session_geometry import (
    RTH_TIMEZONE,
    resolve_rth_session_geometry,
)
from .research_dataset import build_research_dataset
from .storage import Catalog


if TYPE_CHECKING:
    from .api import MarketVault
    from .models import Settings


RESEARCH_WORKSPACE_VERSION = "market-vault-local-research-workspace-v1"
RESEARCH_SOURCE_SCHEMA_VERSION = MOOMOO_TIMESTAMP_SEMANTICS_V2_SCHEMA
RESEARCH_SESSION = "RTH"
RESEARCH_ADJUSTMENT = "NONE"
RESEARCH_MARKET = "US"
RESEARCH_INTERVALS = ("1m", "5m", "15m", "30m", "60m")
RESEARCH_PRESETS = ("CORE_TECHNICAL", "LIGHT_TECHNICAL")
_NY = ZoneInfo(RTH_TIMEZONE)
_INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}


class ResearchWorkspaceError(ValueError):
    """Fail-closed local Research Dataset workspace error."""


@dataclass(frozen=True, slots=True)
class ResearchWorkspacePlan:
    symbol: str
    start_date: date
    end_date: date
    interval: str
    preset: str
    horizon_trading_days: int
    feature_window_bars: int
    trading_dates: tuple[date, ...]
    anchor_dates: tuple[date, ...]
    missing_research_dates: tuple[date, ...]
    schedule: object
    scope: DatasetScope
    split_spec: ChronologicalSplitSpec
    anchors: tuple[CrossDayAnchor, ...]
    feature_specs: tuple[FeatureSpec, ...]
    label_specs: tuple[LabelSpec, ...]
    canonical_output_root: Path
    dataset_output_root: Path

    @property
    def ready(self) -> bool:
        return not self.missing_research_dates

    @property
    def summary(self) -> dict[str, str]:
        n = len(self.anchor_dates)
        return {
            "research_schema": RESEARCH_SOURCE_SCHEMA_VERSION,
            "symbol": self.symbol,
            "interval": self.interval,
            "preset": self.preset,
            "horizon": str(self.horizon_trading_days),
            "trading_dates": str(len(self.trading_dates)),
            "anchor_dates": str(n),
            "missing_research_dates": str(len(self.missing_research_dates)),
            "feature_count": str(len(self.feature_specs)),
            "feature_window_bars": str(self.feature_window_bars),
            "train_end": self.split_spec.train_end_date.isoformat(),
            "validation_end": self.split_spec.validation_end_date.isoformat(),
            "test_end": self.split_spec.test_end_date.isoformat(),
            "build_ready": "true" if self.ready else "false",
        }

    @property
    def rows(self) -> tuple[dict[str, str], ...]:
        missing = set(self.missing_research_dates)
        anchors = set(self.anchor_dates)
        rows = []
        for day in self.trading_dates:
            if day in missing:
                data_status = "MISSING_TS2"
            else:
                data_status = "READY"
            if day not in anchors:
                split = "LABEL_EVIDENCE_ONLY"
            elif day <= self.split_spec.train_end_date:
                split = "TRAIN"
            elif day <= self.split_spec.validation_end_date:
                split = "VALIDATION"
            else:
                split = "TEST"
            record = next(
                item for item in self.schedule.daily_records
                if item.market_calendar_date == day
            )
            rows.append({
                "trade_date": day.isoformat(),
                "calendar_profile": str(record.session_profile),
                "research_data": data_status,
                "role": split,
            })
        return tuple(rows)


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceBuildResult:
    plan: ResearchWorkspacePlan
    canonical_build_id: str
    canonical_build_path: Path
    canonical_row_count: int
    dataset_id: str
    dataset_build_path: Path
    dataset_status: str
    dataset_row_count: int
    split_counts: dict[str, int]

    @property
    def summary(self) -> dict[str, str]:
        return {
            **self.plan.summary,
            "canonical_build_id": self.canonical_build_id,
            "canonical_rows": str(self.canonical_row_count),
            "dataset_id": self.dataset_id,
            "dataset_status": self.dataset_status,
            "dataset_rows": str(self.dataset_row_count),
            "train_rows": str(self.split_counts.get("TRAIN", 0)),
            "validation_rows": str(self.split_counts.get("VALIDATION", 0)),
            "test_rows": str(self.split_counts.get("TEST", 0)),
            "dataset_path": str(self.dataset_build_path),
        }


def research_ready_settings(settings: "Settings"):
    """Return the exact research-ready collection cohort over the same stores."""

    return replace(
        settings,
        source_schema_version=RESEARCH_SOURCE_SCHEMA_VERSION,
        default_session=RESEARCH_SESSION,
        default_adjustment=RESEARCH_ADJUSTMENT,
    )


def plan_research_ready_backfill(
    settings: "Settings",
    *,
    symbol: str,
    start_date: date,
    end_date: date,
    interval: str,
):
    return plan_history_backfill(
        research_ready_settings(settings),
        symbols=[_symbol(symbol)],
        start_date=start_date,
        end_date=end_date,
        calendar_market=RESEARCH_MARKET,
        interval=_interval(interval),
        session=RESEARCH_SESSION,
        adjustment=RESEARCH_ADJUSTMENT,
        force=False,
        incremental=False,
    )


def collect_research_ready_backfill(
    settings: "Settings",
    *,
    symbol: str,
    start_date: date,
    end_date: date,
    interval: str,
    max_retries: int = 2,
    retry_backoff_seconds: float = 2.0,
):
    return collect_history_backfill(
        research_ready_settings(settings),
        symbols=[_symbol(symbol)],
        start_date=start_date,
        end_date=end_date,
        calendar_market=RESEARCH_MARKET,
        interval=_interval(interval),
        session=RESEARCH_SESSION,
        adjustment=RESEARCH_ADJUSTMENT,
        force=False,
        incremental=False,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )


def _symbol(value: str) -> str:
    text = str(value).strip().upper()
    if not text.startswith("US.") or len(text) <= 3:
        raise ResearchWorkspaceError("Research symbol must be one US.* code")
    return text


def _interval(value: str) -> str:
    text = str(value).strip().lower()
    if text not in RESEARCH_INTERVALS:
        raise ResearchWorkspaceError(
            "interval must be one of " + ", ".join(RESEARCH_INTERVALS)
        )
    return text


def _preset(value: str) -> str:
    text = str(value).strip().upper()
    if text not in RESEARCH_PRESETS:
        raise ResearchWorkspaceError(
            "preset must be one of " + ", ".join(RESEARCH_PRESETS)
        )
    return text


def _horizon(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 20:
        raise ResearchWorkspaceError(
            "horizon_trading_days must be an integer within [1, 20]"
        )
    return value


def _digest(prefix: str, payload) -> str:
    text = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256((prefix + "\n" + text).encode("utf-8")).hexdigest()


def _calendar_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _calendar_schedule(
    vault: "MarketVault",
    *,
    start_date: date,
    end_date: date,
):
    ranges = vault.catalog.trading_calendar_requested_ranges(
        "MARKET",
        RESEARCH_MARKET,
        start_date,
        end_date,
    )
    gaps = missing_coverage_ranges(start_date, end_date, ranges)
    if gaps:
        formatted = ", ".join(
            f"{left.isoformat()}..{right.isoformat()}" for left, right in gaps
        )
        raise ResearchWorkspaceError(
            "Local US trading calendar does not fully cover the research range: "
            + formatted
        )

    frame = vault.load_trading_calendar(
        market=RESEARCH_MARKET,
        start_date=start_date,
        end_date=end_date,
    )
    if frame.empty:
        raise ResearchWorkspaceError(
            "Local US trading calendar contains no trading dates in the research range"
        )
    rows_by_date = {}
    for row in frame.itertuples(index=False):
        day = pd.Timestamp(row.trade_date).date()
        if day in rows_by_date:
            raise ResearchWorkspaceError(
                f"Local trading calendar has duplicate latest rows for {day.isoformat()}"
            )
        rows_by_date[day] = row

    records = []
    day = start_date
    while day <= end_date:
        row = rows_by_date.get(day)
        if row is None:
            records.append(TradingDayRecord(day, "CLOSED", None, None, None))
        else:
            trade_type = str(row.trade_date_type or "").strip().upper()
            geometry = resolve_rth_session_geometry(day)
            if trade_type == "WHOLE":
                if geometry.classification != "NORMAL":
                    raise ResearchWorkspaceError(
                        f"Calendar/session authority mismatch for {day.isoformat()}: "
                        "calendar says WHOLE but qualified RTH geometry is special"
                    )
            elif trade_type == "MORNING":
                if geometry.classification != "EARLY_CLOSE":
                    raise ResearchWorkspaceError(
                        f"{day.isoformat()} is a MORNING trading day but MarketVault "
                        "has no qualified RTH early-close geometry for that date"
                    )
            elif trade_type == "AFTERNOON":
                raise ResearchWorkspaceError(
                    f"{day.isoformat()} is AFTERNOON-only and is unsupported by "
                    "the US RTH Research workspace"
                )
            else:
                raise ResearchWorkspaceError(
                    f"Unsupported trading-calendar type for {day.isoformat()}: "
                    f"{trade_type or '<blank>'}"
                )

            session_open = datetime.combine(
                day, geometry.open_time, tzinfo=_NY
            ).astimezone(timezone.utc)
            session_close = datetime.combine(
                day, geometry.close_time, tzinfo=_NY
            ).astimezone(timezone.utc)
            profile = (
                "QUALIFIED_EARLY_CLOSE"
                if geometry.classification == "EARLY_CLOSE"
                else "NORMAL"
            )
            records.append(
                TradingDayRecord(
                    day,
                    "TRADING",
                    session_open,
                    session_close,
                    profile,
                )
            )
        day += timedelta(days=1)

    normalized_rows = [
        {
            column: _calendar_value(getattr(row, column))
            for column in (
                "trade_date",
                "trade_date_type",
                "requested_start_date",
                "requested_end_date",
                "captured_at",
                "source",
                "source_schema_version",
                "ingestion_run_id",
            )
        }
        for row in frame.itertuples(index=False)
    ]
    range_payload = [
        [left.isoformat(), right.isoformat()] for left, right in ranges
    ]
    source_content_hash = _digest(
        "market-vault-research-calendar-content-v1",
        normalized_rows,
    )
    source_snapshot_id = _digest(
        "market-vault-research-calendar-source-v1",
        {
            "runs": sorted(
                {
                    str(value)
                    for value in frame["ingestion_run_id"].dropna().tolist()
                }
            ),
            "content": source_content_hash,
        },
    )
    coverage_evidence_id = _digest(
        "market-vault-research-calendar-coverage-v1",
        {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "ranges": range_payload,
        },
    )
    captured = [
        pd.Timestamp(value).tz_convert("UTC").to_pydatetime()
        for value in frame["captured_at"].dropna().tolist()
    ]
    if not captured:
        raise ResearchWorkspaceError(
            "Trading-calendar evidence is missing captured_at authority"
        )
    return verify_trading_day_schedule(
        dataset_as_of=None,
        schedule_schema_version=TRADING_DAY_SCHEDULE_SCHEMA_VERSION,
        market=RESEARCH_MARKET,
        requested_session=RESEARCH_SESSION,
        market_timezone=RTH_TIMEZONE,
        coverage_start_date=start_date,
        coverage_end_date=end_date,
        daily_records=tuple(records),
        source_snapshot_id=source_snapshot_id,
        source_content_hash=source_content_hash,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        normalization_version=SCHEDULE_NORMALIZATION_VERSION,
        coverage_completion_evidence_id=coverage_evidence_id,
        coverage_complete=True,
        archive_available_at=max(captured),
    )


_FEATURE_FIELDS = {
    "sma": ("close",),
    "ema": ("close",),
    "rsi": ("close",),
    "atr": ("high", "low", "close"),
    "obv": ("close", "volume"),
    "macd": ("close",),
    "kdj_k": ("high", "low", "close"),
    "kdj_d": ("high", "low", "close"),
    "kdj_j": ("high", "low", "close"),
    "simple_return": ("close",),
    "volume_ratio": ("volume",),
    "candle_body": ("open", "close"),
    "candle_range": ("high", "low"),
}
_FIXED_FEATURES = frozenset(
    {"macd", "kdj_k", "kdj_d", "kdj_j", "candle_body", "candle_range"}
)


def _feature_spec(transform: str, name: str, window_bars: int | None = None):
    return FeatureSpec(
        "market-vault-feature-spec-v1",
        name,
        "v1",
        DatasetField(name, "float64", False),
        _FEATURE_FIELDS[transform],
        (
            "market_vault.dataset.feature_transforms."
            f"{transform}:{transform}"
        ),
        (
            ()
            if transform in _FIXED_FEATURES
            else (SpecParameter("window_bars", int(window_bars)),)
        ),
        SpecVersionRequirements(
            (CANONICAL_SCHEMA_VERSION,),
            (RESEARCH_SOURCE_SCHEMA_VERSION,),
        ),
    )


def _feature_preset(name: str) -> tuple[tuple[FeatureSpec, ...], int]:
    preset = _preset(name)
    if preset == "CORE_TECHNICAL":
        specs = (
            _feature_spec("sma", "sma_20", 20),
            _feature_spec("ema", "ema_20", 20),
            _feature_spec("rsi", "rsi_14", 14),
            _feature_spec("atr", "atr_14", 14),
            _feature_spec("obv", "obv_20", 20),
            _feature_spec("macd", "macd"),
            _feature_spec("kdj_k", "kdj_k"),
            _feature_spec("kdj_d", "kdj_d"),
            _feature_spec("kdj_j", "kdj_j"),
            _feature_spec("simple_return", "return_2", 2),
            _feature_spec("volume_ratio", "volume_ratio_20", 20),
            _feature_spec("candle_body", "candle_body"),
            _feature_spec("candle_range", "candle_range"),
        )
        return specs, 26
    specs = (
        _feature_spec("sma", "sma_5", 5),
        _feature_spec("ema", "ema_5", 5),
        _feature_spec("rsi", "rsi_5", 5),
        _feature_spec("atr", "atr_5", 5),
        _feature_spec("obv", "obv_5", 5),
        _feature_spec("simple_return", "return_2", 2),
        _feature_spec("volume_ratio", "volume_ratio_5", 5),
        _feature_spec("candle_body", "candle_body"),
        _feature_spec("candle_range", "candle_range"),
    )
    return specs, 5


def _label_specs(horizon: int) -> tuple[LabelSpec, ...]:
    requirements = SpecVersionRequirements(
        (CANONICAL_SCHEMA_VERSION,),
        (CROSS_DAY_SOURCE_SCHEMA_VERSION,),
    )
    common = dict(
        spec_schema_version="market-vault-label-spec-v1",
        version="v1",
        parameters=(),
        requirements=requirements,
        alignment_rule="FEATURE_CLOSE_ALIGNED",
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(
            True,
            "SAME_REQUESTED_SESSION_BAR_SLOT",
        ),
    )
    ordinary_name = f"forward_return_{horizon}d"
    execution_name = f"execution_return_{horizon}d"
    return (
        LabelSpec(
            name=ordinary_name,
            output=DatasetField(ordinary_name, "float64", False),
            input_canonical_fields=("close",),
            transform_ref=(
                "market_vault.dataset.label_transforms.forward_return:"
                "forward_return"
            ),
            observation_window=LabelObservationWindow(
                "TRADING_DAYS", horizon - 1, horizon - 1
            ),
            horizon=LabelHorizon("TRADING_DAYS", horizon),
            **common,
        ),
        LabelSpec(
            name=execution_name,
            output=DatasetField(execution_name, "float64", False),
            input_canonical_fields=("open", "close"),
            transform_ref=(
                "market_vault.dataset.label_transforms.forward_open_to_close_return:"
                "forward_open_to_close_return"
            ),
            observation_window=LabelObservationWindow(
                "TRADING_DAYS", 0, horizon - 1
            ),
            horizon=LabelHorizon("TRADING_DAYS", horizon),
            **common,
        ),
    )


def _split_spec(
    anchor_dates: tuple[date, ...],
    horizon_trading_days: int,
) -> ChronologicalSplitSpec:
    count = len(anchor_dates)
    minimum_train = horizon_trading_days + 1
    minimum_validation = horizon_trading_days + 1
    minimum_test = 1
    minimum_total = minimum_train + minimum_validation + minimum_test
    if count < minimum_total:
        raise ResearchWorkspaceError(
            "Research range is too short for leakage-safe TRAIN/VALIDATION/TEST "
            f"with a {horizon_trading_days}-trading-day Label horizon; "
            f"need at least {minimum_total} anchor trading dates"
        )

    train_count = max(minimum_train, math.floor(count * 0.70))
    validation_count = max(minimum_validation, math.floor(count * 0.15))
    allowed_development = count - minimum_test
    excess = train_count + validation_count - allowed_development
    if excess > 0:
        reducible_train = train_count - minimum_train
        reduction = min(excess, reducible_train)
        train_count -= reduction
        excess -= reduction
    if excess > 0:
        reducible_validation = validation_count - minimum_validation
        reduction = min(excess, reducible_validation)
        validation_count -= reduction
        excess -= reduction
    if excess:
        raise ResearchWorkspaceError(
            "Unable to allocate leakage-safe chronological split boundaries"
        )

    train_end_index = train_count - 1
    validation_end_index = train_count + validation_count - 1
    return ChronologicalSplitSpec(
        CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
        "desktop_quant_70_15_15",
        "v1",
        RTH_TIMEZONE,
        anchor_dates[train_end_index],
        anchor_dates[validation_end_index],
        anchor_dates[-1],
        SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
        SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
        SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
        SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    )


def _anchor_slot(record: TradingDayRecord, interval: str, feature_window: int):
    minutes = _INTERVAL_MINUTES[interval]
    duration_minutes = int(
        (record.session_close - record.session_open).total_seconds() // 60
    )
    full_slots = duration_minutes // minutes
    if full_slots < feature_window:
        raise ResearchWorkspaceError(
            f"{record.market_calendar_date.isoformat()} has only {full_slots} "
            f"full {interval} RTH bars but preset requires {feature_window}"
        )
    return full_slots - 1


def plan_local_research_dataset(
    vault: "MarketVault",
    *,
    symbol: str,
    start_date: date,
    end_date: date,
    interval: str,
    preset: str = "CORE_TECHNICAL",
    horizon_trading_days: int = 1,
) -> ResearchWorkspacePlan:
    symbol = _symbol(symbol)
    interval = _interval(interval)
    preset = _preset(preset)
    horizon = _horizon(horizon_trading_days)
    if type(start_date) is not date or type(end_date) is not date:
        raise ResearchWorkspaceError("start_date and end_date must be dates")
    if start_date > end_date:
        raise ResearchWorkspaceError("start_date must be on or before end_date")

    schedule = _calendar_schedule(
        vault,
        start_date=start_date,
        end_date=end_date,
    )
    trading_dates = tuple(
        item.market_calendar_date
        for item in schedule.daily_records
        if item.day_status == "TRADING"
    )
    if len(trading_dates) <= horizon:
        raise ResearchWorkspaceError(
            "Research range does not contain enough future trading days for the Label horizon"
        )
    anchor_dates = trading_dates[:-horizon]
    split = _split_spec(anchor_dates, horizon)
    features, feature_window = _feature_preset(preset)
    labels = _label_specs(horizon)

    by_day = {
        item.market_calendar_date: item for item in schedule.daily_records
    }
    anchors = tuple(
        CrossDayAnchor(
            symbol,
            day,
            _anchor_slot(by_day[day], interval, feature_window),
        )
        for day in anchor_dates
    )
    scope = DatasetScope(
        (symbol,),
        anchor_dates,
        RESEARCH_ADJUSTMENT,
        interval,
        RESEARCH_SESSION,
    )

    research_settings = research_ready_settings(vault.settings)
    catalog = Catalog(research_settings)
    complete = catalog.completed_market_bar_items(
        symbols=[symbol],
        trade_dates=list(trading_dates),
        interval=interval,
        requested_session=RESEARCH_SESSION,
        adjustment=RESEARCH_ADJUSTMENT,
        source_schema_version=RESEARCH_SOURCE_SCHEMA_VERSION,
    )
    missing = tuple(
        day for day in trading_dates
        if (symbol, day) not in complete
    )

    return ResearchWorkspacePlan(
        symbol,
        start_date,
        end_date,
        interval,
        preset,
        horizon,
        feature_window,
        trading_dates,
        anchor_dates,
        missing,
        schedule,
        scope,
        split,
        anchors,
        features,
        labels,
        research_settings.data_root
        / "canonical"
        / "dataset=market_bars_canonical",
        research_settings.data_root / "research" / "cross_day",
    )


def _ensure_research_output_root(data_root: Path, output_root: Path) -> None:
    """Create only the fixed app-owned Research output root.

    The sealed artifact publisher deliberately requires a pre-existing root.
    This helper creates the two deterministic descendants under the configured
    data root and rejects links/reparse points before the publisher performs
    its own stronger native identity/capability validation.
    """

    data_root = Path(data_root)
    output_root = Path(output_root)
    expected = data_root / "research" / "cross_day"
    if output_root != expected:
        raise ResearchWorkspaceError("Research output root differs from the fixed workspace path")
    if not data_root.is_absolute():
        raise ResearchWorkspaceError("Configured data root must be absolute")

    def validate_directory(path: Path) -> None:
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"Cannot inspect Research output ancestry: {path}"
            ) from exc
        if not stat.S_ISDIR(info.st_mode):
            raise ResearchWorkspaceError(
                f"Research output ancestry is not a directory: {path}"
            )
        if stat.S_ISLNK(info.st_mode):
            raise ResearchWorkspaceError(
                f"Research output ancestry cannot be a symlink: {path}"
            )
        if os.name == "nt" and (
            getattr(info, "st_file_attributes", 0) & 0x400
        ):
            raise ResearchWorkspaceError(
                f"Research output ancestry cannot be a reparse point: {path}"
            )

    validate_directory(data_root)
    windows_sid = None
    windows_mkdir = None
    if os.name == "nt":
        from .cross_day_dataset._artifact_windows import (
            _current_sid,
            _new_directory,
        )

        windows_sid = _current_sid()
        windows_mkdir = _new_directory

    for path in (data_root / "research", output_root):
        if path.exists():
            validate_directory(path)
            continue
        try:
            if windows_mkdir is not None:
                windows_mkdir(path, windows_sid)
            else:
                os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"Cannot create Research output root: {path}"
            ) from exc
        validate_directory(path)


def build_local_research_dataset(
    vault: "MarketVault",
    *,
    symbol: str,
    start_date: date,
    end_date: date,
    interval: str,
    preset: str = "CORE_TECHNICAL",
    horizon_trading_days: int = 1,
) -> ResearchWorkspaceBuildResult:
    plan = plan_local_research_dataset(
        vault,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
        preset=preset,
        horizon_trading_days=horizon_trading_days,
    )
    if plan.missing_research_dates:
        preview = ", ".join(
            day.isoformat() for day in plan.missing_research_dates[:8]
        )
        suffix = "..." if len(plan.missing_research_dates) > 8 else ""
        raise ResearchWorkspaceError(
            "Research-ready Timestamp V2 RTH data is missing for "
            f"{len(plan.missing_research_dates)} trading dates: {preview}{suffix}. "
            "Prepare research data before building."
        )

    now = datetime.now(timezone.utc)
    settings = research_ready_settings(vault.settings)
    canonical_result = materialize_canonical_market_bars(
        Catalog(settings),
        symbols=[plan.symbol],
        trade_dates=list(plan.trading_dates),
        request_key=CanonicalRequestKey(
            plan.interval,
            RESEARCH_SESSION,
            RESEARCH_ADJUSTMENT,
            RESEARCH_SOURCE_SCHEMA_VERSION,
        ),
        output_root=plan.canonical_output_root,
        created_at=now,
    )
    if canonical_result.status != "COMPLETE":
        raise ResearchWorkspaceError(
            f"Canonical build is not COMPLETE: {canonical_result.status}"
        )
    canonical = load_verified_canonical_build(canonical_result.build_path)

    _ensure_research_output_root(settings.data_root, plan.dataset_output_root)
    materialized = build_research_dataset(
        feature_builds=(canonical,),
        label_builds=(canonical,),
        observation_builds=(),
        schedule=plan.schedule,
        scope=plan.scope,
        split_spec=plan.split_spec,
        anchors=plan.anchors,
        ts2_feature_specs=plan.feature_specs,
        observation_feature_specs=(),
        label_specs=plan.label_specs,
        feature_window_bars=plan.feature_window_bars,
        dataset_as_of=None,
        output_root=plan.dataset_output_root,
        built_at=now,
    )
    verified = materialized.verified
    split_counts = {
        split: sum(
            item.assignment_status == "ASSIGNED"
            and item.final_split == split
            for item in verified.split_result.assignments
        )
        for split in ("TRAIN", "VALIDATION", "TEST")
    }
    if not all(split_counts.values()):
        raise ResearchWorkspaceError(
            "Research Dataset produced an empty TRAIN, VALIDATION, or TEST split"
        )
    return ResearchWorkspaceBuildResult(
        plan,
        canonical_result.canonical_build_id,
        canonical_result.build_path,
        canonical_result.row_count,
        verified.dataset_id,
        Path(verified.build_path),
        verified.status,
        len(verified.rows),
        split_counts,
    )
