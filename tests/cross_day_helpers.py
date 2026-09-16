"""Synthetic offline TS2 fixtures; every execution build passes the old reader."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from market_vault.canonical.bars import CANONICAL_BUILDER_VERSION, DEFAULT_DATASET_KIND
from market_vault.canonical.identity import canonical_bar_key, canonical_row_version_id
from market_vault.canonical.materialization import materialize_build_result
from market_vault.canonical.models import (
    CanonicalBar, CanonicalBuildResult, CanonicalMaterializationRequest,
    CanonicalRequestKey, CanonicalResolutionEntry, CanonicalSourceRef,
)
from market_vault.canonical.reader import load_verified_canonical_build
from market_vault.dataset import assemble_point_in_time_samples, PITSampleRequest
from market_vault.dataset.models import DatasetField
from market_vault.dataset.spec_models import (
    LabelSpec, LabelHorizon, LabelObservationWindow, CrossTradingDayPolicy, SpecVersionRequirements,
)
from market_vault.cross_day import TradingDayRecord, VerifiedTradingDaySchedule, assemble_cross_day_labels, execute_cross_day_labels

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
ARCHIVE = datetime(2025, 12, 31, tzinfo=UTC)
AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def local(day, hour=9, minute=30):
    if type(day) is str:
        day = date.fromisoformat(day)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY).astimezone(UTC)


def schedule(daily=(("2025-03-03", "N"), ("2025-03-04", "N")), *, archive=ARCHIVE):
    records = []
    for day, status in daily:
        day = date.fromisoformat(day) if type(day) is str else day
        closed = status == "C"
        records.append(TradingDayRecord(day, "CLOSED" if closed else "TRADING",
            None if closed else local(day), None if closed else local(day, 13 if status == "E" else 16, 0),
            None if closed else "QUALIFIED_EARLY_CLOSE" if status == "E" else "NORMAL"))
    return VerifiedTradingDaySchedule("trading-day-schedule-v1", "US", "RTH", "America/New_York",
        records[0].market_calendar_date, records[-1].market_calendar_date, tuple(records), "1" * 64, "2" * 64,
        "cross-day-us-rth-calendar-contract-v1", "trading-day-schedule-normalization-v1", "3" * 64, True, archive)


def spec(n=1, transform="forward_return", name=None, schema="10.9-mv-ts2"):
    excursion = transform.startswith("maximum_")
    fields = ("close", "high") if transform == "maximum_favorable_excursion" else (
        ("close", "low") if excursion else ("close",))
    name = name or ("cd_mfe_2d" if excursion else "cd_return_1d")
    return LabelSpec("market-vault-label-spec-v1", name, "v1",
        DatasetField(name, "int64" if transform == "forward_direction" else "float64", False),
        fields, f"market_vault.dataset.label_transforms.{transform}:{transform}", (),
        SpecVersionRequirements(("market-bars-canonical-schema-v1",), (schema,)),
        LabelObservationWindow("TRADING_DAYS", 0 if excursion else n - 1, n - 1), LabelHorizon("TRADING_DAYS", n),
        "FEATURE_CLOSE_ALIGNED", "INCOMPLETE", CrossTradingDayPolicy(True, "SAME_REQUESTED_SESSION_BAR_SLOT"))


def bar(day="2025-03-03", slot=1, *, close=100.0, high=150.0, low=75.0, interval="5m",
        schema="10.9-mv-ts2", archive=ARCHIVE, market=None, source="a", code="US.AAPL"):
    day = date.fromisoformat(day) if type(day) is str else day
    event = pd.Timestamp(local(day) + timedelta(minutes=int(interval[:-1]) * slot))
    key = canonical_bar_key(dataset_kind=DEFAULT_DATASET_KIND, code=code, interval=interval, adjustment="NONE", event_time=event)
    version = canonical_row_version_id(canonical_bar_key=key, ingestion_run_id="run-" + source,
        source_snapshot_content_hash=source * 64, source_schema_version=schema, canonical_builder_version=CANONICAL_BUILDER_VERSION)
    return CanonicalBar(key, version, DEFAULT_DATASET_KIND, code, interval, "NONE", event,
        pd.Timestamp(market or event + timedelta(minutes=int(interval[:-1]))), pd.Timestamp(archive),
        100.0, high, low, close, 100.0, (), "run-" + source, source * 64, "f" * 64,
        schema, CANONICAL_BUILDER_VERSION, day, "RTH", day, "RTH", "offline/" + source + ".parquet")


def build(tmp_path, bars, *, dates=None, schema="10.9-mv-ts2", interval="5m"):
    bars = tuple(bars)
    sources = {b.canonical_bar_key: CanonicalSourceRef(b.ingestion_run_id, b.physical_snapshot_hash,
        b.logical_source_rows_hash, b.source_schema_version, b.snapshot_file, b.requested_trade_date, b.requested_session)
        for b in bars}
    result = CanonicalBuildResult(bars, tuple(CanonicalResolutionEntry(k, sources[k]) for k in sorted(sources)),
        CANONICAL_BUILDER_VERSION, len(set(sources.values())))
    request = CanonicalMaterializationRequest(sorted({b.code for b in bars}) or ["US.AAPL"],
        dates or sorted({b.requested_trade_date for b in bars}) or [date(2025, 3, 4)],
        CanonicalRequestKey(interval, "RTH", "NONE", schema))
    artifact = materialize_build_result(result, request, output_root=tmp_path / "canonical",
                                         created_at=datetime(2026, 1, 2, tzinfo=UTC))
    return load_verified_canonical_build(artifact.build_path)


def pit(features, day="2025-03-03", slot=1, *, cutoff=AS_OF, interval="5m", requests=None):
    day = date.fromisoformat(day) if type(day) is str else day
    nominal = timedelta(minutes=int(interval[:-1]))
    event = local(day) + slot * nominal
    request = PITSampleRequest("US.AAPL", interval, "NONE", "RTH", day, local(day), event + nominal)
    return assemble_point_in_time_samples(features, (request,) if requests is None else requests, dataset_as_of=cutoff)


def run(features, labels, *, sched=None, specs=None, day="2025-03-03", slot=1, cutoff=AS_OF, requests=None):
    association = assemble_cross_day_labels(pit(features, day, slot, cutoff=cutoff, requests=requests),
        features, labels, schedule() if sched is None else sched, (spec(),) if specs is None else specs, dataset_as_of=cutoff)
    return execute_cross_day_labels(association)
