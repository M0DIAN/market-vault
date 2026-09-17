"""Offline, real verified upstream authorities for the pure Dataset join."""

from dataclasses import fields
from datetime import date, timedelta

import cross_day_helpers as cd
import ts2_feature_helpers as ts
from test_observation_pit_models import artifacts, T
from test_observation_models import sample_snapshot, sample_observation
from test_multi_source_feature_execution import spec as obs_spec
from market_vault.observation import assemble_observation_pit_sidecar, observation_source_snapshot_id
from market_vault.multi_source import observation_feature_binding, execute_observation_features
from market_vault.ts2_feature import execute_ts2_features
from market_vault.cross_day import assemble_cross_day_labels, execute_cross_day_labels
from market_vault.dataset.models import DatasetScope
from market_vault.dataset.split_models import ChronologicalSplitSpec


SPLIT = ChronologicalSplitSpec("market-vault-chronological-split-spec-v1", "cd_chrono", "v1",
    "America/New_York", date(2025, 3, 4), date(2025, 3, 5), date(2025, 3, 6),
    "FEATURE_WINDOW_CLOSE_DATE", "ACTUAL_LABEL_END", "EXCLUDE", "EXCLUDE")
SCOPE = DatasetScope(("US.AAPL",), (date(2025, 3, 3),), "NONE", "5m", "RTH")


def tamper(record, **changes):
    """Deliberately bypass a frozen constructor only to challenge admission."""
    assert set(changes) <= {f.name for f in fields(record)}
    copy = object.__new__(type(record))
    for field in fields(record):
        object.__setattr__(copy, field.name, changes.get(field.name, getattr(record, field.name)))
    return copy


def fixture(root, case="A", *, slots=(0, 1), n=None, reverse=False, two_proofs=False,
            cutoff=cd.AS_OF, label_specs=None, schedule=None, label_bars=None):
    fb = cd.build(root / "feature", tuple(cd.bar(slot=s, close=100.0 + i * 25.0) for i, s in enumerate(slots)))
    slot = max(slots, default=1)
    pit = cd.pit((fb,), slot=slot, requests=() if case == "E" else None, cutoff=cutoff)
    tspecs = (ts.spec(n=n if n is not None else 3 if case == "C" else 2),)
    ospecs = (obs_spec(max_age_us=1 if case == "D" else 10),)
    lspecs = (cd.spec(),) if label_specs is None else label_specs
    if case == "F":
        tspecs += (ts.spec("candle_body"),)
        ospecs += (obs_spec("int64", name="obs_count"),)
        lspecs += (cd.spec(transform="forward_direction", name="cd_direction_1d"),)
    if reverse:
        tspecs, ospecs, lspecs = tspecs[::-1], ospecs[::-1], lspecs[::-1]
    close = cd.local("2025-03-03") + timedelta(minutes=(slot + 1) * 5)
    delta = close - T
    us = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    create = artifacts.__wrapped__(root / "observation")
    snapshot = sample_snapshot(completed_possession_at=close - timedelta(seconds=1))
    row = sample_observation(event_time=close - timedelta(microseconds=5), known_at=close - timedelta(microseconds=4),
        archive_available_at=close - timedelta(microseconds=3), source_snapshot_id=observation_source_snapshot_id(snapshot))
    def proof(clock):
        return create((row,), effective=(us - 86400000000, us + 86400000000),
                      knowledge=(us - 86400000000, us + 86400000000), created=us + clock, snapshots=(snapshot,))
    builds = (proof(300),)
    if two_proofs:
        builds += (proof(400),)
    if reverse:
        builds = builds[::-1]
    a3 = assemble_observation_pit_sidecar(pit, builds, tuple(observation_feature_binding(s) for s in ospecs))
    ov = execute_observation_features(a3, () if case == "E" else builds, ospecs)
    tv = execute_ts2_features((fb,), pit, tspecs, dataset_as_of=cutoff)
    label = cd.bar("2025-03-04", slot=slot, close=150.0,
                   archive=cd.AS_OF + timedelta(days=1) if case == "B" else cd.ARCHIVE)
    labels = (cd.build(root / "label", (label,) if label_bars is None else label_bars),)
    if case == "H_considered":
        labels += (cd.build(root / "diagnostic", (cd.bar("2025-03-05", close=150.0),)),)
    if case == "H_backing":
        labels += (cd.build(root / "backing", (label,), dates=(date(2025, 3, 4), date(2025, 3, 5))),)
    if reverse:
        labels = labels[::-1]
    sch = schedule or cd.schedule(archive=cd.ARCHIVE - timedelta(microseconds=1) if case == "G" else cd.ARCHIVE)
    association = assemble_cross_day_labels(pit, (fb,), labels, sch, lspecs, dataset_as_of=cutoff, observation_pit=a3)
    lv = execute_cross_day_labels(association)
    return dict(feature_pit=pit, ts2_features=tv, observation_pit=a3, observation_builds=builds,
                observation_feature_specs=ospecs, observation_features=ov, cross_day_association=association,
                cross_day_labels=lv, schedule=sch, scope=SCOPE, split_spec=SPLIT, dataset_as_of=cutoff)
